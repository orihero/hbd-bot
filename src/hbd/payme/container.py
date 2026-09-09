"""The gateway's composition root: an engine, a queue handle, a ledger and a dispatcher.

**This is one of the three modules in ``hbd.payme`` allowed to import ``hbd.db``, and the
exception is deliberate rather than an oversight of the package docstring's rule.** A
composition root is defined by importing everything it wires; the rule the rest of the package
obeys — persistence implements the ports declared here, never the other way round — is what
makes that possible at all. This is where the two halves are joined, once, at boot. The other
two doors are narrower: :mod:`hbd.payme.app` reaches for ``hbd.db.engine.ping`` and nothing
else, and :mod:`hbd.payme.cli` runs the cross-table diagnostics that have no port and must not
be given one on a process facing the public internet. Every OTHER module here names ``hbd.db``
nowhere, and ``test_only_the_three_named_doors_reach_persistence`` in
``tests/test_payme/test_protocol.py`` is what makes a fourth door an argument rather than an
import.

**It is emphatically NOT ``hbd.runtime.container.build_container``.** That function builds a
``KitRepository``, a ``ProviderSet``, an ``httpx`` client per vendor, an ffmpeg post-processor,
a ``Storage`` over a writable workspace and a Telegram ``Bot`` — and it reads
``hbd.config.Settings``, which is the model that holds all four outbound credentials. A payment
endpoint has business with none of that. Reaching for it would put the Telegram token and two
vendor keys in the address space of the only process in this system with an inbound socket
from the public internet, which is precisely the arrangement the fourth process exists to
prevent. The absence of an HTTP client here is the same control ``hbd.admin.container`` makes:
a process with no vendor adapter has no vendor spend to reach and no SSRF surface.

**The connection arithmetic, written down so the FIFTH process has to re-argue it rather than
inherit it.** ``hbd/db/engine.py:40-41`` sizes the bot and the worker at ``10 + 20`` each;
``hbd/admin/container.py:53-54`` sizes the admin API at ``5 + 5``. That is ``30 + 30 + 10 =
70`` against a stock Postgres ``max_connections`` of 100. This process asks for ``3 + 2``,
taking the total to 75, so adding it needs no host change — and five is genuinely enough,
because every method on the ledger is one short transaction with no vendor call, no Telegram
call and no HTTP of its own inside it.

**Do not quote ``engine.py:64-67`` for this.** Its ``3 × 30 = 90`` is the hypothetical the
admin's smaller pool exists to AVOID, not the fleet's real ask; sizing a fifth pool off that
sentence would leave somebody believing there are five connections of headroom when there are
twenty-five. The full argument is in ``docs/deployment/08-payme.md`` §3.1.

**Redis is constructed without connecting.** ``arq.create_pool`` pings on the way up; using it
here would mean a Redis outage stops the payment endpoint from booting, which trades a delayed
notification for refused money. The queue handle is therefore built from a lazy connection pool
and the first command is the first connection — so a Redis failure surfaces where it belongs,
inside the swallowed post-commit enqueue, with the sweep as its backstop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from arq import ArqRedis
from redis.asyncio import ConnectionPool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hbd.db.base import utc_now
from hbd.db.engine import create_engine, create_session_factory
from hbd.db.models import Base
from hbd.db.payme import SqlPaymeLedger
from hbd.db.payme_sql import insert_rpc_log
from hbd.logging import get_logger
from hbd.payme.ports import PaymeLedger
from hbd.payme.service import NotifyEnqueue, PaymeService, RpcJournal
from hbd.payme.settings import PaymeSettings

__all__ = [
    "PaymeContainer",
    "PAYME_POOL_SIZE",
    "PAYME_MAX_OVERFLOW",
    "PAYME_NOTIFY_JOB_NAME",
    "SqlRpcJournal",
    "QueuedNotifier",
    "notify_job_id",
    "build_payme_container",
    "payme_container",
]

_LOGGER: Final = get_logger(__name__)

#: This process's share of the connection budget. See the module docstring for the arithmetic.
PAYME_POOL_SIZE: Final[int] = 3
PAYME_MAX_OVERFLOW: Final[int] = 2

#: The ARQ function name the worker registers for "tell this customer their payment landed".
#:
#: **Restated here rather than imported from ``hbd.runtime.payme_jobs``, on purpose.** Importing
#: it would pull ``hbd.runtime`` into this process, and that package's ``__init__`` chain
#: reaches the bot, the provider set and every vendor adapter — the entire graph this container
#: exists to stay out of. ARQ dispatches by NAME anyway: the coupling between the two processes
#: is a string on a Redis queue whichever way it is spelled, so the choice is between a string
#: in two files and a vendor credential in one address space.
PAYME_NOTIFY_JOB_NAME: Final[str] = "notify_payment_settled"

#: Prefix of the deterministic job id. ARQ refuses to queue an id that is already queued, so a
#: Payme ``PerformTransaction`` retry — or a retry racing the sweep's delivery arm — enqueues
#: nothing the second time instead of sending the customer two messages.
#:
#: **It is the job NAME, and it has to be**, because the deduplication is between TWO PROCESSES:
#: this gateway's post-commit enqueue and ``hbd.runtime.payme_jobs.run_payme_sweep``'s backstop
#: enqueue, whose id is ``f"{PAYME_NOTIFY_JOB_NAME}:{public_ref}"``. A prefix of our own —
#: ``payme-notify`` was the first spelling here — produces a DIFFERENT id for the same intent,
#: which ARQ happily queues alongside the other: both jobs run, the customer is told twice, and
#: nothing fails. The two spellings are held together by a single assertion in
#: ``tests/test_runtime/test_payme_jobs.py`` — the one place where importing both sides is
#: free, and the only thing that can see across the process boundary this constant exists so
#: as not to import over.
_NOTIFY_JOB_PREFIX: Final[str] = PAYME_NOTIFY_JOB_NAME

#: Fake and test runs point at SQLite, which has no migration history to honour, so the schema
#: is materialised directly — exactly as ``hbd.runtime.container`` and ``hbd.admin.container``
#: both do it.
_SQLITE_PREFIX: Final[str] = "sqlite"


def notify_job_id(public_ref: str) -> str:
    """The ARQ job id for one settled intent. One id per intent, forever.

    Keyed on ``public_ref`` and not on the rail-side transaction id: the customer is told about
    an ORDER, once, and an intent that was settled by an operator's force-settle and then again
    by a late genuine ``PerformTransaction`` must not produce two messages about one song.
    """
    return f"{_NOTIFY_JOB_PREFIX}:{public_ref}"


class SqlRpcJournal:
    """Writes one ``payme_rpc_log`` row per inbound call, in its own transaction.

    Satisfies :class:`hbd.payme.service.RpcJournal` structurally, matching every other adapter
    in this repository — a Protocol change is then a type error here rather than a runtime
    surprise.

    **Its own session, never the settlement's.** A journal write inside the perform transaction
    would mean a failed INSERT into an audit table rolls back a payment that the rail has
    already been told about. The row is written afterwards, and if it cannot be written the
    dispatcher logs and moves on: an audit gap is a worse outcome than nothing only until you
    compare it with a customer charged for a receipt that no longer exists.
    """

    __slots__ = ("_sessions",)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def record(
        self,
        *,
        at: datetime,
        method: str,
        payme_transaction_id: str | None,
        public_ref: str | None,
        reply_code: int,
        peer_ip: str | None,
        duration_ms: int,
    ) -> None:
        async with self._sessions.begin() as session:
            await insert_rpc_log(
                session,
                at=at,
                method=method,
                payme_transaction_id=payme_transaction_id,
                public_ref=public_ref,
                reply_code=reply_code,
                peer_ip=peer_ip,
                duration_ms=duration_ms,
            )


class QueuedNotifier:
    """Enqueues the worker's "your payment went through" job. Satisfies ``NotifyEnqueue``.

    A class rather than a closure so that a test can see what it holds, and so the deterministic
    job id has one obvious home. It does not catch its own failures: the dispatcher swallows them
    deliberately, in one place, and a second swallow here would hide the failure from the ERROR
    line that exists to report it.
    """

    __slots__ = ("_redis",)

    def __init__(self, redis: ArqRedis) -> None:
        self._redis = redis

    async def __call__(self, public_ref: str) -> None:
        await self._redis.enqueue_job(
            PAYME_NOTIFY_JOB_NAME, public_ref, _job_id=notify_job_id(public_ref)
        )


@dataclass(frozen=True, slots=True)
class PaymeContainer:
    """Every long-lived resource the gateway holds, already built. Immutable.

    ``ledger`` is typed as the PORT and not as ``SqlPaymeLedger``. That is the same discipline
    the bot's handle takes from the other direction — there it is narrowed to
    ``hbd.checkout.PaymentIntentOpener`` so the bot cannot settle a payment — and here it means
    nothing in this process can reach a persistence internal that is not on the protocol.

    ``clock`` is held rather than imported at each call site so the whole process runs off one
    injected instant source: the dispatcher reads it once per request and passes that instant
    down into the ledger, which is what lets certification drive the twelve-hour expiry branch
    in seconds.
    """

    settings: PaymeSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: ArqRedis
    ledger: PaymeLedger
    service: PaymeService
    clock: Callable[[], datetime]

    async def aclose(self) -> None:
        """Release the pool and the queue handle, reporting each failure separately.

        One resource failing to close must not hide the other: a leaked Redis connection after
        a database error is how a restart loop becomes connection exhaustion.
        """
        try:
            # ``aclose`` since redis-py 5.0.1; ``close`` is deprecated. The pinned
            # ``types-redis`` 4.6 stubs predate the rename and shadow redis-py's own inline
            # types, so the call is correct at runtime and invisible to mypy — the same
            # suppression ``hbd.admin.container`` carries, for the same stub.
            await self.redis.aclose()  # type: ignore[attr-defined]
        except Exception as exc:
            _LOGGER.warning(
                "payme redis client did not close cleanly",
                extra={"event": "payme.container.redis_close_failed", "detail": repr(exc)},
            )
        await self.engine.dispose()


async def build_payme_container(
    settings: PaymeSettings, *, clock: Callable[[], datetime] = utc_now
) -> PaymeContainer:
    """Build everything from configuration. No I/O beyond the SQLite schema shortcut.

    ``clock`` is a parameter with a production default rather than a module-level read, so a
    certification run or a test can hand in a movable one and drive the expiry branch without
    waiting twelve hours. Nothing here calls it: the clock is read per request.
    """
    engine = create_engine(
        settings.database_url,
        pool_size=PAYME_POOL_SIZE,
        max_overflow=PAYME_MAX_OVERFLOW,
    )
    if settings.database_url.startswith(_SQLITE_PREFIX):
        await _create_schema(engine)
    session_factory = create_session_factory(engine)
    # Lazy: no connection is opened here. See the module docstring — a Redis outage must not
    # stop this process booting, because the money path does not need Redis at all.
    redis = ArqRedis(ConnectionPool.from_url(settings.redis_url))
    ledger = SqlPaymeLedger(
        session_factory,
        merchant_id=settings.payme_merchant_id,
        clock=clock,
        transaction_timeout_ms=settings.payme_transaction_timeout_ms,
        duplicate_code=settings.payme_duplicate_transaction_code,
        account_field=settings.payme_account_field,
    )
    # ``intent_ttl_s`` is deliberately NOT passed. Opening an intent is the BOT's port
    # (``hbd.checkout.PaymentIntentOpener``), performed in the bot's process under the bot's
    # settings; this process never calls ``open_intent``, so a copy of that value here would be
    # a second place for the link's lifetime to be configured and only one of them would ever
    # be read.
    # Annotated as the PORTS rather than the concrete classes, so ``mypy --strict`` checks
    # the structural conformance here, at the one place both halves are in scope. A protocol
    # change is then a type error at the composition root instead of an AttributeError on the
    # money path.
    journal: RpcJournal = SqlRpcJournal(session_factory)
    notify: NotifyEnqueue = QueuedNotifier(redis)
    service = PaymeService(
        ledger,
        clock=clock,
        journal=journal,
        notify=notify,
        account_field=settings.payme_account_field,
        duplicate_code=settings.payme_duplicate_transaction_code,
    )
    _LOGGER.info(
        "payme container built",
        extra={
            "event": "payme.container.built",
            "environment": settings.environment,
            "pool_size": PAYME_POOL_SIZE,
            # The host half only. The full DSN carries a password, and the redaction layer
            # would mask the whole value, which tells an operator nothing.
            "database": settings.database_url.split("@")[-1],
            "merchant_id": settings.payme_merchant_id,
            "is_sandbox": settings.payme_is_sandbox,
        },
    )
    return PaymeContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        redis=redis,
        ledger=ledger,
        service=service,
        clock=clock,
    )


@asynccontextmanager
async def payme_container(
    settings: PaymeSettings, *, clock: Callable[[], datetime] = utc_now
) -> AsyncIterator[PaymeContainer]:
    """Build, hand over, and always release. The shape the lifespan and the CLI both use."""
    container = await build_payme_container(settings, clock=clock)
    try:
        yield container
    finally:
        await container.aclose()


async def _create_schema(engine: AsyncEngine) -> None:
    """SQLite has no migration history to honour, so the schema is materialised directly."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
