"""Fixtures and fakes shared by the runtime tests.

The one thing that lives here rather than in a test module is
:class:`RecordingEntitlementStore`. Three modules need the same fake — ``test_jobs`` builds
a container with it, ``test_payments`` drives the render gate through it, and the settlement
tests assert what the worker wrote through it — and a fake that exists in three copies is a
fake that drifts in two of them.

It is a *working* store, not a stub: it keeps a balance, refuses when the balance is spent,
and is idempotent per order in exactly the way the real ledger is (by net position, not by
row presence). That matters because the point of handing it to ``_Container`` is that the
worker's settlement paths can be exercised against something that can actually tell a
double-settle from a first one — a ``None`` there made every one of those paths untestable.

The ``session``/``bot`` pair moved up here for the same reason: ``test_jobs`` and
``test_settlement`` drive the SAME job function through the SAME recording transport, and
two module-local copies of a bot fixture is two places to forget ``parse_mode`` in.

The broadcast half at the bottom is the same argument a third time. ``test_broadcast_expand``
and ``test_broadcast_send`` are two halves of one pipeline — one materialises an audience and
the other delivers to it — so they seed the same accounts, the same campaign and the same
worker context. What is NOT shared is the assertion helpers: each module reads the state its
own subject writes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.methods import TelegramMethod

from hbd.config import Settings
from hbd.contracts import BroadcastKind, Language, Result, err, ok
from hbd.db.broadcasts import (
    BroadcastActor,
    BroadcastBody,
    NewBroadcast,
    create_broadcast,
    expand_chunk,
)
from hbd.db.enums import AuditReasonCode
from hbd.db.models.broadcast import BroadcastRow
from hbd.db.models.broadcast_recipient import BroadcastRecipientRow
from hbd.db.models.user import UserRow
from hbd.entitlements import (
    ChargeOutcome,
    CreditBalance,
    EntitlementError,
    InsufficientCreditsError,
    SettlementOutcome,
)
from hbd.errors import HbdError
from hbd.runtime.container import AppContainer, build_container
from tests.test_bot.conftest import BOT_TOKEN, RecordingSession

__all__ = [
    "RecordingEntitlementStore",
    "Movement",
    "BroadcastSession",
    "RecordingQueue",
    "QueuedJob",
    "EVERYONE",
    "FIRST_ACCOUNT",
    "FROZEN_AT",
    "broadcast_ctx",
    "broadcast_settings",
    "campaign_row",
    "materialise",
    "recipients",
    "seed_accounts",
    "seed_campaign",
]


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def bot(session: RecordingSession) -> Bot:
    """A bot whose every call is recorded rather than sent.

    ``parse_mode=HTML`` is not decoration: the delivery captions and every locale string
    are written as HTML, so a bot built without it renders tags as literal text and a test
    comparing against ``translate(...)`` passes while production shows markup.
    """
    return Bot(
        token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


#: One thing that happened to the ledger, in the order it happened. A tuple rather than a
#: model because every assertion on it is an equality against a literal, and a literal is
#: the most legible form of "exactly one CONSUME, and it was for this order".
type Movement = tuple[str, UUID | None, int]


class RecordingEntitlementStore:
    """In-memory ``hbd.entitlements.EntitlementStore``. Never raises, never touches a DB.

    ``runtime_checkable`` verifies member PRESENCE only, so an ``isinstance`` assertion will
    happily accept this class after the protocol has drifted away from it. ``mypy --strict``
    over ``tests`` is what actually keeps the two in step — which is why the container field
    it is assigned to is typed and not ``Any``.
    """

    def __init__(self, *, credits: int = 3, is_blocked: bool = False) -> None:
        self.credits = credits
        self.is_blocked = is_blocked
        #: Set to make ``charge`` fail with something that is NOT a business refusal — a
        #: database outage, which is retryable. The distinction is what the ARQ ladder reads
        #: off ``Err.is_retryable``, so a test that only ever sees an entitlement refusal
        #: cannot prove the gate stopped second-guessing it.
        self.charge_failure: HbdError | None = None
        #: Every write, in order: ("debit"|"refund"|"consume"|"grant", order_id, delta).
        self.movements: list[Movement] = []
        #: Net position per order, which is what decides replay in the real ledger too.
        self._net: dict[UUID, int] = {}
        self._settled: set[UUID] = set()
        #: Every touch, as ``(account, the language it was told to write or None)``.
        #: ``Language | None`` and not ``Language``: ``EntitlementStore.touch`` widened so
        #: that ``None`` can mean "this update said nothing about the language, leave the
        #: column alone". Recording a resolved default here would make the one case the
        #: widening exists for unassertable — and, because parameter types are
        #: contravariant, a narrow ``touch`` below stops this class satisfying
        #: ``EntitlementStore`` at all, which ``mypy --strict`` catches at the
        #: ``AppContainer.credits`` assignment rather than here.
        self.touched: list[tuple[int, Language | None]] = []
        self.blocked: list[tuple[int, bool]] = []
        #: Every account this store was asked to erase.
        self.forgotten: list[int] = []

    # -- EntitlementStore ---------------------------------------------------
    async def charge(
        self, *, telegram_user_id: int, order_id: UUID, actor: str, cost: int = 1
    ) -> Result[tuple[ChargeOutcome, CreditBalance]]:
        if self.charge_failure is not None:
            return err(self.charge_failure)
        if self._net.get(order_id, 0) < 0:
            return ok((ChargeOutcome.ALREADY_PAID, self._balance(telegram_user_id)))
        if self.is_blocked:
            # The BASE class, not the out-of-credits subclass: a block is the one
            # entitlement refusal with no number attached, and it renders "error.blocked".
            return err(
                EntitlementError(
                    "the fake store refused a blocked account",
                    context={"telegram_user_id": telegram_user_id},
                )
            )
        if self.credits < cost:
            return err(
                InsufficientCreditsError(
                    "the fake store has nothing left to spend",
                    context={
                        "telegram_user_id": telegram_user_id,
                        "balance": self.credits,
                        "needed": cost,
                    },
                )
            )
        self.credits -= cost
        self._net[order_id] = self._net.get(order_id, 0) - cost
        self.movements.append(("debit", order_id, -cost))
        return ok((ChargeOutcome.CHARGED, self._balance(telegram_user_id)))

    async def settle(
        self, *, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> Result[bool]:
        # Both halves of "writes nothing" are real answers, not failures: an order that was
        # never debited must never mint a credit, and a redelivered job must not settle
        # twice. Ok(False) is how the real store says so, so this says it the same way.
        if self._net.get(order_id, 0) >= 0 or order_id in self._settled:
            return ok(False)
        self._settled.add(order_id)
        if outcome is SettlementOutcome.FAILED:
            self.credits += 1
            self._net[order_id] = 0
            self.movements.append(("refund", order_id, 1))
            return ok(True)
        self.movements.append(("consume", order_id, 0))
        return ok(True)

    async def grant(
        self, *, telegram_user_id: int, credits: int, idempotency_key: str, actor: str
    ) -> Result[CreditBalance]:
        self.credits += credits
        self.movements.append(("grant", None, credits))
        return ok(self._balance(telegram_user_id))

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        return ok(self._balance(telegram_user_id, exclude_order_id=exclude_order_id))

    async def set_blocked(self, telegram_user_id: int, *, is_blocked: bool) -> Result[None]:
        self.is_blocked = is_blocked
        self.blocked.append((telegram_user_id, is_blocked))
        return ok(None)

    async def touch(self, telegram_user_id: int, *, ui_language: Language | None) -> Result[None]:
        """The liveness upsert, recorded rather than written.

        ``ui_language`` is passed straight through instead of being defaulted, because the
        real store's whole decision hangs on the distinction: ``db.credits.touch`` writes
        the column only when it is given a language, and supplies ``_DEFAULT_UI_LANGUAGE``
        on the INSERT half alone. A fake that resolved ``None`` to a language here would let
        a regression that clobbered a customer's real choice pass unnoticed.
        """
        self.touched.append((telegram_user_id, ui_language))
        return ok(None)

    async def forget(self, telegram_user_id: int) -> Result[None]:
        """The erasure, modelled the way the real store behaves: the balance goes, the
        history stays. ``movements`` is deliberately NOT cleared — that list is this fake's
        stand-in for the append-only ledger, and a fake that dropped it would let a worker
        test pass while the real ``/forget`` destroyed the audit trail."""
        self.forgotten.append(telegram_user_id)
        self.credits = 0
        return ok(None)

    # -- helpers for the tests ----------------------------------------------
    def _balance(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> CreditBalance:
        in_flight = sum(
            1
            for order_id, net in self._net.items()
            if net < 0 and order_id not in self._settled and order_id != exclude_order_id
        )
        return CreditBalance(
            telegram_user_id=telegram_user_id,
            credits=self.credits,
            in_flight=in_flight,
            is_blocked=self.is_blocked,
        )

    def kinds_for(self, order_id: UUID) -> list[str]:
        """Every movement recorded against one order, in order. The settlement assertion."""
        return [kind for kind, recorded, _ in self.movements if recorded == order_id]


# ---------------------------------------------------------------------------
# Broadcasts — shared by test_broadcast_expand and test_broadcast_send
# ---------------------------------------------------------------------------
#: The instant a campaign's audience is frozen at. Mid-day, so a test that moves the clock
#: cannot pass by landing on a boundary, and WELL IN THE PAST rather than near today's date: the
#: property several of these tests turn on is that a relative rule is compiled against this
#: instant and never against ``utc_now()``, which is unassertable while the two are the same
#: afternoon.
FROZEN_AT: Final[datetime] = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: The first seeded Telegram id. Its own range, so a broadcast test's accounts can never
#: collide with the entitlement suite's.
FIRST_ACCOUNT: Final[int] = 7_100_000_001

#: Everyone. An empty root group is the unfiltered audience — the shape the compiler lowers
#: to ``predicate is None`` — which is what most of these tests want: the population is the
#: seed, and the segment is not what they are about.
EVERYONE: Final[dict[str, Any]] = {"v": 1, "match": "all", "rules": []}


@dataclass(frozen=True, slots=True)
class QueuedJob:
    """One enqueue, as :class:`RecordingQueue` saw it."""

    name: str
    arguments: tuple[Any, ...]
    job_id: str
    defer_s: float


class RecordingQueue:
    """ARQ's pool as the broadcast jobs use it: one method, recorded rather than sent.

    ``enqueue_job`` answers ``None`` — which is what the real one answers when the id is
    already queued — because none of these jobs reads the returned handle. What they do read
    is whether the call raised, so :attr:`failure` exists: a lost enqueue must never take
    down the job that has just done real work, and that is only assertable against a queue
    that can fail.
    """

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.jobs: list[QueuedJob] = []
        self.failure = failure

    async def enqueue_job(
        self, name: str, *arguments: Any, _job_id: str, _defer_by: float = 0.0
    ) -> None:
        if self.failure is not None:
            raise self.failure
        self.jobs.append(
            QueuedJob(name=name, arguments=arguments, job_id=_job_id, defer_s=float(_defer_by))
        )
        return

    def named(self, name: str) -> tuple[QueuedJob, ...]:
        return tuple(job for job in self.jobs if job.name == name)


class BroadcastSession(RecordingSession):
    """A recording session that can refuse ONE chat, and act between messages.

    Both additions exist because a campaign's whole difficulty is per-recipient: the fake in
    ``tests/test_bot`` fails a whole METHOD, and "``sendMessage`` fails" makes the case that
    matters — one account blocked the bot and the other 199 must still receive it —
    unassertable. :attr:`after_call` is the same argument for time: a pause arrives *while*
    a chunk is sending, and a hook that runs between two messages is the only way to write
    that down without sleeping.
    """

    def __init__(self) -> None:
        super().__init__()
        #: chat id -> what Telegram answers that chat with.
        self.refusals: dict[int, Exception] = {}
        #: Awaited after every successful call. Where a test pauses a campaign mid-chunk.
        self.after_call: Callable[[], Awaitable[None]] | None = None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 - the signature is aiogram's, not ours
    ) -> Any:
        refusal = self.refusals.get(getattr(method, "chat_id", 0))
        if refusal is not None:
            # Recorded before it is raised: a refused send is still a call that was made, and
            # a test asserting "we did try this account" needs it in the list.
            self.calls.append(method)
            raise refusal
        response = await super().make_request(bot, method, timeout)
        if self.after_call is not None:
            await self.after_call()
        return response

    def chats(self, name: str = "SendMessage") -> tuple[int, ...]:
        """Which accounts a method was aimed at, in order."""
        return tuple(getattr(call, "chat_id", 0) for call in self.named(name))


@pytest.fixture
def broadcast_session() -> BroadcastSession:
    return BroadcastSession()


@pytest.fixture
def broadcast_bot(broadcast_session: BroadcastSession) -> Bot:
    """The worker's ``Bot``, recording. ``parse_mode=HTML`` for the reason ``bot`` states:
    a campaign body is operator-authored HTML and is sent verbatim."""
    return Bot(
        token=BOT_TOKEN,
        session=broadcast_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


def broadcast_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """A worker's settings over a file-backed SQLite database.

    A FILE and not ``:memory:``: the container opens its own pool, and an in-memory database
    is private to a connection unless the pool is pinned — which ``build_container`` has no
    reason to do and no way to be told.
    """
    values: dict[str, Any] = {
        "_env_file": None,
        "telegram_bot_token": "t",
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'broadcasts.db'}",
        "elevenlabs_api_key": "k",
        "llm_api_key": "k",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
async def broadcast_container(tmp_path: Path) -> AsyncIterator[AppContainer]:
    """A REAL container with no vendors: a database, an object store, and a churn recorder.

    Real rather than hand-built because two of the properties under test are properties of
    the wiring — a refused send is recorded through ``container.bot_blocks``, and a campaign
    image is read through ``container.storage`` — and a stub for either would assert that the
    test's own fake was called.
    """
    container = await build_container(
        broadcast_settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    yield container
    await container.aclose()


def broadcast_ctx(
    container: AppContainer, bot: Bot | None, queue: RecordingQueue
) -> dict[str, Any]:
    """The context ARQ hands a job, with the three keys these four jobs read.

    ``bot`` is optional because two of the four jobs never touch one — the expansion writes
    rows and the sweep writes enqueues — and a test that had to build a Telegram client to
    exercise them would be asserting its own fixture.
    """
    return {"container": container, "bot": bot, "redis": queue}


async def seed_accounts(
    container: AppContainer,
    *,
    count: int,
    first_id: int = FIRST_ACCOUNT,
    language: Language = Language.UZ_LATN,
    blocked_bot: tuple[int, ...] = (),
    joined: datetime = FROZEN_AT - timedelta(days=30),
) -> tuple[int, ...]:
    """``count`` accounts, newest first, so the expansion's keyset walk is predictable.

    ``blocked_bot`` names ids that have blocked the bot: they are seeded, they are expanded,
    and they are materialised as skips — the funnel is arithmetic in the table rather than a
    filter somebody has to remember.
    """
    async with container.require_session_factory().begin() as session:
        for offset in range(count):
            telegram_user_id = first_id + offset
            session.add(
                UserRow(
                    id=uuid4(),
                    telegram_user_id=telegram_user_id,
                    ui_language=language,
                    is_blocked=False,
                    last_seen_at=joined,
                    blocked_bot_at=joined if telegram_user_id in blocked_bot else None,
                    created_at=joined - timedelta(minutes=offset),
                    updated_at=joined,
                )
            )
    return tuple(first_id + offset for offset in range(count))


async def seed_campaign(
    container: AppContainer,
    *,
    segment: Mapping[str, Any] | None = None,
    bodies: tuple[BroadcastBody, ...] | None = None,
    audience_size: int = 0,
    scheduled_for: datetime | None = None,
    evaluated_at: datetime = FROZEN_AT,
    at: datetime = FROZEN_AT,
) -> UUID:
    """One campaign, born ``expanding`` the way :func:`create_broadcast` is the only writer of.

    ``scheduled_for`` is written straight onto the draft rather than through
    ``mark_scheduled``, which only accepts from ``ready``: these tests are about what the
    worker does with a schedule, not about how the panel sets one.
    """
    draft = NewBroadcast(
        title="September outage notice",
        kind=BroadcastKind.SERVICE,
        segment=segment if segment is not None else EVERYONE,
        segment_hash="a" * 64,
        audience_size=audience_size,
        audience_evaluated_at=evaluated_at,
        bodies=bodies
        or (BroadcastBody(language=Language.UZ_LATN, text="Bugun kechqurun yangilanish."),),
        scheduled_for=scheduled_for,
        created_by=BroadcastActor(admin_id=uuid4(), username="ops.dilnoza"),
        reason_code=AuditReasonCode.ROUTINE_OPS,
        reason_ref="OPS-9",
    )
    async with container.require_session_factory().begin() as session:
        return await create_broadcast(session, draft=draft, at=at)


async def materialise(
    container: AppContainer, broadcast_id: UUID, *, at: datetime = FROZEN_AT
) -> None:
    """Write the recipient rows and leave the campaign ``ready``, without a job.

    The send tests start from a materialised audience because that is the state the send job
    is defined over; how the rows got there is :mod:`test_broadcast_expand`'s subject.
    """
    async with container.require_session_factory().begin() as session:
        chunk = await expand_chunk(
            session, broadcast_id=broadcast_id, predicate=None, cursor=None, at=at
        )
    assert chunk.is_complete, "the seed is meant to fit in one page"


async def recipients(
    container: AppContainer, broadcast_id: UUID
) -> tuple[BroadcastRecipientRow, ...]:
    """Every recipient row, oldest first — the order the claim drains them in."""
    async with container.require_session_factory()() as session:
        rows = await session.scalars(
            sa.select(BroadcastRecipientRow)
            .where(BroadcastRecipientRow.broadcast_id == broadcast_id)
            .order_by(BroadcastRecipientRow.created_at, BroadcastRecipientRow.id)
        )
        return tuple(rows)


async def campaign_row(container: AppContainer, broadcast_id: UUID) -> BroadcastRow:
    async with container.require_session_factory()() as session:
        row = await session.get(BroadcastRow, broadcast_id)
        assert row is not None
        return row
