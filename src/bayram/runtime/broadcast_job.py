"""The send pipeline: materialise a frozen audience, then deliver to it without ever
delivering twice.

Four jobs live here — an expansion, a send chunk, a one-account test send and a cron sweep —
and all four are shaped by the same fact: ``retry_jobs`` defaults to ``True`` and SIGTERM
cancels running tasks, so **every one of these jobs will be replayed, on every deploy.** The
record of who has been messaged therefore cannot live in a job. It lives in
``broadcast_recipients``, and this module's only real responsibility is to keep two orderings
intact:

* **claim, commit, then send.** :meth:`~bayram.db.broadcasts.SqlBroadcasts.claim` moves a row to
  ``sending`` in its own committed transaction *before* the Telegram call is made, and
  :meth:`~bayram.db.broadcasts.SqlBroadcasts.settle` closes it after. A job killed in between
  leaves the row in ``sending``, where nothing will ever claim it again: the sweep retires it
  to ``unknown`` after the lease, counted as neither sent nor failed. "We do not know whether
  three of forty thousand were delivered" is the answer this pipeline prefers over "three
  people received it twice";
* **compile the segment against the frozen instant, never against now.** The audience is
  fixed when the campaign is created — ``broadcasts.audience_evaluated_at`` — so a resumed
  expansion selects the same population as the chunk before it. A rule like "joined in the
  last 30 days" re-read per chunk would quietly select a different audience each time.

**The worker owns the ``Bot`` and the panel owns the composition.** The admin process is
denied a Telegram token (``FORBIDDEN_ENV_VARS``, D10) and cannot send; this process holds the
``Bot`` in its ARQ context under :data:`BOT_CTX_KEY` and never constructs one. The same split
is why an operator's image arrives as an object-store key rather than as a ``file_id``:
nobody over there could have minted one. The worker uploads the bytes once, keeps the
``file_id`` Telegram answers with, and quotes it for the rest of the campaign.

**Nothing here retries a recipient.** A refusal is terminal on the row — ``skipped_blocked``
for a customer who blocked the bot, ``undeliverable`` for a chat that is gone, ``failed`` for
anything else — because the only route from ``sending`` back to ``pending`` is
:func:`~bayram.db.broadcasts.release_recipient`, and it may be used **only** when the request
demonstrably never left the process. Two places use it: a pause noticed between messages, and
a flood wait raised before the send. Both know the message did not go.

**The three job ids the panel mints are deterministic; the successors this module enqueues
are not, and that is deliberate.** ARQ refuses a job id whose *result* is still in Redis
(``keep_result``, an hour), so a chunk job re-enqueuing itself under
``broadcast:send:{id}`` would be refused by its own predecessor's result and the campaign
would stall until the sweep. The successor therefore carries a fresh suffix. Nothing is lost:
an id never was the thing that stopped two workers sending the same message — the conditional
``UPDATE`` in :func:`~bayram.db.broadcasts.claim_chunk` is, and it holds however many chunk jobs
happen to be alive.

The registration lives in :mod:`bayram.runtime.jobs` with every other job, and the cron entry
beside it. A job that is not in that list is a job ARQ will never dispatch, silently.

``BROADCAST_SPEC §4.1``–``§4.7`` is the design this implements; the deviations from it are
stated where they are made rather than collected here.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import SecretStr
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from bayram.admin.schemas.segment import SegmentModel, to_segment
from bayram.bot.delivery import is_blocked_by_customer
from bayram.bot.i18n import FALLBACK_LANGUAGE
from bayram.bot.locales import REFERENCE_LANGUAGE
from bayram.config import ENV_PREFIX, env_file
from bayram.contracts import (
    BotBlockSource,
    BroadcastRecipientState,
    BroadcastState,
    Language,
    Result,
    err,
    is_err,
    ok,
)
from bayram.db.admin.audit import AuditEntry, AuditValueRejectedError, append
from bayram.db.admin.segment import compile_segment, segment_capabilities
from bayram.db.base import utc_now
from bayram.db.broadcasts import (
    EXPAND_CHUNK_SIZE,
    SEND_CHUNK_SIZE,
    BroadcastPlan,
    ClaimedRecipient,
    ComposedBody,
    DueBroadcast,
    ExpansionChunk,
    RecipientTally,
    SqlBroadcasts,
    decode_expand_cursor,
    mark_finished,
)
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode
from bayram.db.guard import run_guarded
from bayram.db.models.admin_audit import AuditOutcome
from bayram.errors import PipelineError, ValidationError
from bayram.logging import get_logger
from bayram.runtime.container import AppContainer
from bayram.runtime.pacer import (
    InMemorySendBudgetStore,
    RedisSendBudgetStore,
    SendBudgetStore,
    SendPacer,
    resolve_pacer_policy,
)

__all__ = [
    "EXPAND_JOB_NAME",
    "SEND_JOB_NAME",
    "TEST_SEND_JOB_NAME",
    "DUE_JOB_NAME",
    "BROADCAST_DUE_CRON_MINUTE",
    "PAUSE_CHECK_EVERY",
    "expand_broadcast_audience",
    "send_broadcast_chunk",
    "send_broadcast_test",
    "sweep_due_broadcasts",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function NAME, and for three of these four the enqueue side is another
#: PROCESS — the admin panel, through :mod:`bayram.admin.queue`, which restates these same three
#: strings rather than importing them (importing this module would drag the runtime container
#: and a ``Bot`` into a process that must hold neither). Both copies are asserted against
#: their functions: here at the bottom of this module, there by the constants' own comment.
EXPAND_JOB_NAME: Final[str] = "expand_broadcast_audience"
SEND_JOB_NAME: Final[str] = "send_broadcast_chunk"
TEST_SEND_JOB_NAME: Final[str] = "send_broadcast_test"
#: The sweep has no enqueue side at all: it is a cron, and the only caller is the schedule in
#: :mod:`bayram.runtime.jobs`.
DUE_JOB_NAME: Final[str] = "sweep_due_broadcasts"

#: Twelve times an hour, offset by four minutes from every other schedule in this worker
#: (:00/:05/… is the Payme sweep, :07 the activity snapshot, :17 retention, :43 the balance
#: poll). The cadence is a customer-facing number rather than a technical one: it is the
#: ceiling on how late a *scheduled* campaign goes out, and the ceiling on how long a
#: campaign whose worker died sits still. A tuple and not a set, for the reason
#: :func:`bayram.runtime.payme_jobs.sweep_minutes` gives at length — a set is unhashable and
#: ``test_no_two_crons_in_this_worker_contend_for_the_same_minute`` collects these values
#: into one.
BROADCAST_DUE_CRON_MINUTE: Final[tuple[int, ...]] = tuple(range(4, 60, 5))

#: How often the send loop re-reads ``broadcasts.state``. Twenty-five messages is about two
#: seconds at the shipped rate, which is what "a pause takes effect in seconds, not at the
#: end of a chunk" costs: one indexed primary-key read per twenty-five sends.
PAUSE_CHECK_EVERY: Final[int] = 25

#: The kit job's context keys, RE-STATED rather than imported from :mod:`bayram.runtime.jobs`.
#: Importing them would make this module depend on the one that registers it, which is a
#: cycle; every other job module in this package restates the same strings for the same
#: reason.
CONTAINER_CTX_KEY: Final[str] = "container"
BOT_CTX_KEY: Final[str] = "bot"
#: ARQ's own key for the pool it hands every job. Present in a real worker and absent in a
#: hand-built context, which is why both readers of it treat it as optional.
REDIS_CTX_KEY: Final[str] = "redis"

#: Every job id this module mints starts here, matching what the panel's seam mints so one
#: Redis ``SCAN`` shows an operator every broadcast job in flight.
_JOB_ID_PREFIX: Final[str] = "broadcast"

#: Error codes written on a recipient row. Symbolic tokens and never a message, still less an
#: excerpt of a Telegram response body: a third party's error text can quote what we sent it.
_NO_BODY: Final[str] = "no_body_for_language"
_FORGOTTEN: Final[str] = "account_forgotten"
_MEDIA_UNREADABLE: Final[str] = "media_unreadable"
_BLOCKED: Final[str] = "blocked_by_customer"
_CHAT_UNAVAILABLE: Final[str] = "chat_unavailable"

#: Error codes written on the CAMPAIGN. A campaign fails for structural reasons only; a
#: recipient's refusal never grades the run.
_SEGMENT_UNDECODABLE: Final[str] = "segment_undecodable"
_CURSOR_UNDECODABLE: Final[str] = "cursor_undecodable"

#: Telegram's other ``Forbidden`` and its ``chat not found``: the chat is gone rather than
#: closed to us. Matched the way :func:`bayram.bot.delivery.is_blocked_by_customer` matches its
#: own carve-out, and with the same accepted risk stated there — if Telegram rewords these,
#: the outcome degrades to ``failed``, which is a weaker fact rather than a wrong one.
_UNDELIVERABLE_MESSAGES: Final[tuple[str, ...]] = (
    "user is deactivated",
    "chat not found",
    "bot was kicked",
    "peer_id_invalid",
)

#: What an outcome row records when the campaign's operator cannot be named — the account was
#: deleted, or the campaign was created by a path that stored no actor. ``system:`` marks it
#: as the host rather than an operator, exactly as the bootstrap CLI's row does.
_SYSTEM_ACTOR: Final[str] = "system:broadcast"
#: The role an outcome row carries when :attr:`BroadcastPlan.actor_role` is unknown. OWNER,
#: because the actor is then the system itself and the bootstrap CLI already spells that
#: combination — an operator's role is never *guessed* here, it is read live or not claimed.
_SYSTEM_ROLE: Final[AdminRole] = AdminRole.OWNER
#: The placeholder ``bayram.admin.audit_sink`` writes when a value is refused at the boundary.
#: Restated rather than imported: that module reaches an ``AdminContainer`` this process does
#: not have and importing it here would be a dependency on the panel's request machinery.
_UNSTORABLE_USERNAME: Final[str] = "unstorable"

#: Filename attached to an uploaded broadcast image. Telegram ignores it for a photo; it
#: exists because ``BufferedInputFile`` requires one and a blank would be logged as one.
_MEDIA_FILENAME: Final[str] = "broadcast.jpg"


class _AuditChainSettings(BaseSettings):
    """The audit chain key, read on its own rather than through :class:`bayram.config.Settings`.

    **It cannot be a field on ``Settings`` and this is not a workaround.**
    ``tests/test_admin/test_settings_and_boot.py`` asserts set equality between every
    secret-shaped field name on that class and ``VENDOR_SECRET_FIELDS`` — the tuple the admin
    lifespan derives ``FORBIDDEN_ENV_VARS`` from — so a field named ``…_key`` there would
    make ``BAYRAM_ADMIN_AUDIT_HMAC_KEY`` a variable the *panel* is refused at boot, which is the
    one process that cannot run without it. A separate settings model is the shape
    :class:`bayram.payme.settings.PaymeSettings` already uses for a secret that must not live on
    the shared object.

    **Optional, and unset is a supported deployment.** A worker with no key writes no OUTCOME
    audit row and says so at ERROR; the campaign row — ``finished_at`` and its six counters —
    is unaffected and remains the operational record. What is lost is the accountability copy
    in the 730-day table, so a deployment that wants it sets the same value here as the panel
    holds. That is a deliberate widening of where the chain key lives, and it is the price of
    an outcome row written by the process that knows the outcome.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    admin_audit_hmac_key: SecretStr | None = None


def audit_chain_key() -> str | None:
    """The key the OUTCOME row is chained with, or ``None`` when this worker holds none.

    Read per campaign completion rather than cached, because a campaign finishes at most
    once and a cache would hold a value across a configuration change for the life of a
    worker that runs for weeks.
    """
    key = _AuditChainSettings().admin_audit_hmac_key
    return None if key is None else key.get_secret_value() or None


def _require_container(ctx: Mapping[str, Any]) -> AppContainer:
    container = ctx.get(CONTAINER_CTX_KEY)
    if not isinstance(container, AppContainer):
        raise PipelineError(
            "worker context is missing a usable 'container'",
            context={"key": CONTAINER_CTX_KEY, "found": type(container).__name__},
        )
    return container


def _require_bot(ctx: Mapping[str, Any]) -> Bot:
    bot = ctx.get(BOT_CTX_KEY)
    if not isinstance(bot, Bot):
        raise PipelineError(
            "worker context is missing a usable 'bot'",
            context={"key": BOT_CTX_KEY, "found": type(bot).__name__},
        )
    return bot


def _store(container: AppContainer) -> SqlBroadcasts:
    """The campaign handle, built here rather than taken off the container.

    :func:`bayram.runtime.payme_jobs.build_worker_payme_ledger`'s precedent: the container holds
    the ports the BOT needs, and a campaign is not one of them — the bot may not send a
    broadcast and the panel may not send anything at all.
    """
    return SqlBroadcasts(container.require_session_factory())


def _campaign_id(broadcast_id: str) -> UUID:
    """Parse the queued id. A non-UUID means the enqueue side is broken, so it raises."""
    try:
        return UUID(broadcast_id)
    except ValueError as exc:
        raise PipelineError(
            "a broadcast job was queued with an id that is not a UUID",
            context={"broadcast_id": broadcast_id},
            cause=exc,
        ) from exc


def _pacer(ctx: Mapping[str, Any], container: AppContainer) -> SendPacer:
    """The outbound pacer, over Redis when this worker has one.

    The fallback is per-process and is honest about it: ``use_fake_providers`` mode and the
    whole unit suite run with no Redis, and a pacer that could only exist against a server
    would be switched off exactly where a developer would notice it misbehaving. A
    multi-replica deployment always has ``ctx["redis"]``, because ARQ puts it there.
    """
    redis = ctx.get(REDIS_CTX_KEY)
    store: SendBudgetStore
    if isinstance(redis, Redis):
        store = RedisSendBudgetStore(redis)
    else:
        # Typed rather than merely null-checked, for ``_require_container``'s reason: a
        # context holding something that is not a client would otherwise degrade one
        # ``AttributeError`` per message through the pacer's own broad ``except``, which is
        # the shape of a store that is down and not the shape of one that was never wired.
        _LOG.warning(
            "no redis client in the worker context; the send rate is paced per process only",
            extra={
                "rate_per_s": container.settings.broadcast_send_rate_per_s,
                "found": type(redis).__name__,
            },
        )
        store = InMemorySendBudgetStore()
    return SendPacer(store, policy=resolve_pacer_policy(container.settings))


async def _enqueue(
    ctx: Mapping[str, Any], job: str, *arguments: Any, job_id: str, defer_s: float = 0.0
) -> bool:
    """Queue one broadcast job. Never raises; a lost enqueue is the sweep's problem.

    Every enqueue in this module is an OPTIMISATION on latency and never the only path: the
    campaign's state is in Postgres, and the five-minutely sweep re-enqueues anything that
    stopped moving. So an unreachable Redis is logged and counted, exactly as
    :func:`bayram.runtime.payme_jobs.run_payme_sweep`'s delivery arm treats it, rather than
    taking down the job that has just done real work.
    """
    redis = ctx.get(REDIS_CTX_KEY)
    enqueue_job = getattr(redis, "enqueue_job", None)
    if enqueue_job is None:
        _LOG.warning(
            "this worker has no queue handle; the due sweep will pick the campaign up",
            extra={"job": job, "job_id": job_id},
        )
        return False
    try:
        await enqueue_job(job, *arguments, _job_id=job_id, _defer_by=defer_s)
    except (TimeoutError, OSError) as exc:
        _LOG.error(
            "a broadcast job could not be enqueued; the due sweep is the backstop",
            extra={"job": job, "job_id": job_id, "failure": repr(exc)},
        )
        return False
    return True


def _successor_id(job: str, broadcast_id: UUID) -> str:
    """A fresh id for the next chunk of the same campaign.

    Unique per call, because ARQ refuses an id whose result is still in Redis and the
    predecessor's result is exactly that — a deterministic successor would be refused by the
    job that queued it and the campaign would stall for ``keep_result`` seconds. Exclusivity
    is not lost with it: it never lived in the id. It lives in the conditional ``UPDATE``
    that claims a recipient row, which is safe against any number of concurrent chunks.
    """
    return f"{_JOB_ID_PREFIX}:{job}:{broadcast_id}:{uuid4().hex}"


# ---------------------------------------------------------------------------
# Expansion — the frozen audience, materialised one keyset page at a time
# ---------------------------------------------------------------------------
async def expand_broadcast_audience(
    ctx: Mapping[str, Any], broadcast_id: str, now_iso: str
) -> dict[str, Any]:
    """Write one page of the audience into ``broadcast_recipients``, then queue the next.

    ``now_iso`` is the instant the panel froze the audience at. It is carried through the
    queue for the record and then **cross-checked against the row**, which is the authority:
    ``broadcasts.audience_evaluated_at`` is the instant ``count_segment_exactly`` counted
    against and therefore the only instant that makes the operator's number true. A
    disagreement is logged rather than obeyed.

    Resumable by construction. The cursor is persisted with the rows it belongs to, the
    insert goes through ``insert_or_ignore`` against the unique
    ``(broadcast_id, telegram_user_id)``, and the campaign flips to ``ready`` on the page
    that has no successor — so a replayed chunk writes nothing, a resumed one continues, and
    neither needs a branch anybody has to get right.

    Returns a JSON-safe summary. Raises only ``PipelineError`` when the worker was wired up
    wrong, which is a startup bug rather than a run-time one.
    """
    container = _require_container(ctx)
    store = _store(container)
    campaign = _campaign_id(broadcast_id)
    at = utc_now()
    started = time.monotonic()

    plan = await _plan_or_none(store, campaign)
    if plan is None:
        return _expand_summary(broadcast_id, started=started, error="unknown_campaign")
    if plan.state is not BroadcastState.EXPANDING:
        # Cancelled, or already expanded by the job this one is a replay of. Either way there
        # is nothing to do and nothing to queue.
        _LOG.info(
            "the expansion found the campaign no longer expanding",
            extra={"broadcast_id": broadcast_id, "state": str(plan.state)},
        )
        return _expand_summary(broadcast_id, started=started, state=plan.state)
    _warn_on_instant_drift(plan, now_iso=now_iso)

    predicate = _compile(plan)
    if is_err(predicate):
        await _fail_campaign(container, plan, error_code=_SEGMENT_UNDECODABLE, at=at)
        return _expand_summary(broadcast_id, started=started, error=_SEGMENT_UNDECODABLE)

    try:
        cursor = decode_expand_cursor(plan.expand_cursor)
    except ValidationError:
        # The token was minted by ``expand_chunk`` and written by us, so one that will not
        # parse is a corrupted row rather than bad input — and it is corrupted identically on
        # every retry. Failing the campaign is what stops the sweep re-queueing it forever;
        # resuming from the beginning instead was rejected, because a cursor nobody can read
        # is a cursor nobody can prove is the FIRST page.
        _LOG.exception(
            "a campaign's expansion cursor cannot be read; it cannot be resumed",
            extra={"broadcast_id": broadcast_id},
        )
        await _fail_campaign(container, plan, error_code=_CURSOR_UNDECODABLE, at=at)
        return _expand_summary(broadcast_id, started=started, error=_CURSOR_UNDECODABLE)

    chunk = await store.expand(
        campaign,
        predicate=predicate.value,
        cursor=cursor,
        at=at,
        limit=EXPAND_CHUNK_SIZE,
    )
    if is_err(chunk):
        _LOG.error(
            "an expansion chunk failed; the due sweep will resume it",
            extra={"broadcast_id": broadcast_id, **chunk.error.to_log_dict()},
        )
        return _expand_summary(broadcast_id, started=started, error=chunk.error.code)

    page = chunk.value
    if not page.accepted:
        # The campaign left ``expanding`` while this page was being written — a cancel, in
        # practice. The rows this pass inserted are harmless (a cancelled campaign sends
        # nothing and the cascade takes them with the row); what must not happen is a
        # successor.
        _LOG.info(
            "the campaign stopped wanting its audience mid-expansion",
            extra={"broadcast_id": broadcast_id, "inserted": page.inserted},
        )
        return _expand_summary(broadcast_id, started=started, chunk=page)

    if page.next_cursor is not None:
        await _enqueue(
            ctx,
            EXPAND_JOB_NAME,
            broadcast_id,
            now_iso,
            job_id=_successor_id("expand", campaign),
        )
        return _expand_summary(broadcast_id, started=started, chunk=page, state=plan.state)

    # The last page. The campaign is ``ready``; whether it goes now or at its instant is the
    # schedule's business, and the sweep owns the future one.
    is_due = plan.scheduled_for is None or plan.scheduled_for <= at
    if is_due:
        await _enqueue(ctx, SEND_JOB_NAME, broadcast_id, job_id=_successor_id("send", campaign))
    _LOG.info(
        "a campaign's audience is materialised",
        extra={
            "broadcast_id": broadcast_id,
            "inserted": page.inserted,
            "suppressed": page.suppressed,
            "is_due": is_due,
        },
    )
    return _expand_summary(
        broadcast_id, started=started, chunk=page, state=BroadcastState.READY, is_due=is_due
    )


def _warn_on_instant_drift(plan: BroadcastPlan, *, now_iso: str) -> None:
    """Say so when the queued instant and the stored one disagree. The row wins."""
    try:
        queued_at = datetime.fromisoformat(now_iso)
    except ValueError:
        queued_at = None
    if queued_at is None or queued_at != plan.audience_evaluated_at:
        _LOG.warning(
            "the enqueued audience instant is not the one on the campaign; using the row",
            extra={
                "broadcast_id": str(plan.id),
                "queued": now_iso,
                "stored": plan.audience_evaluated_at.isoformat(),
            },
        )


def _compile(plan: BroadcastPlan) -> Result[ColumnElement[bool] | None]:
    """Lower the stored document to a predicate, against the FROZEN instant.

    The document was stored in the panel's wire shape, so it is decoded by the panel's own
    models: a second decoder in this process would be a second vocabulary to keep in step
    with the field registry, and the day they drifted the campaign that went out would not be
    the one the operator previewed. The import costs no FastAPI — ``bayram.admin.schemas`` is
    pydantic and the compiler underneath it is plain SQLAlchemy.

    ``Ok(None)`` is a legal answer and means *everyone*: an empty root group is the
    unfiltered audience, which the panel counted exactly the same way.
    """
    try:
        model = SegmentModel.model_validate(dict(plan.segment))
    except PydanticValidationError as exc:
        _LOG.error(
            "a stored segment no longer validates; the campaign cannot be expanded",
            extra={"broadcast_id": str(plan.id), "issue_count": len(exc.errors())},
        )
        return err(
            ValidationError(
                "a stored segment document no longer matches the schema it was written with",
                context={"broadcast_id": str(plan.id)},
                cause=exc,
            )
        )
    compiled = compile_segment(
        to_segment(model),
        now=plan.audience_evaluated_at,
        capabilities=segment_capabilities(),
    )
    if is_err(compiled):
        _LOG.error(
            "a stored segment no longer compiles; the campaign cannot be expanded",
            extra={"broadcast_id": str(plan.id), **compiled.error.to_log_dict()},
        )
        return compiled
    return ok(compiled.value.predicate)


async def _plan_or_none(store: SqlBroadcasts, broadcast_id: UUID) -> BroadcastPlan | None:
    """The campaign, or ``None`` when it is gone or unreadable.

    A read failure and a missing row are collapsed on purpose: neither is something a job
    can act on, both are logged with their own message, and branching on the difference
    would only produce two ways of doing nothing.
    """
    plan = await store.plan(broadcast_id)
    if is_err(plan):
        _LOG.error(
            "a campaign could not be read; the due sweep is the backstop",
            extra={"broadcast_id": str(broadcast_id), **plan.error.to_log_dict()},
        )
        return None
    if plan.value is None:
        _LOG.warning(
            "a broadcast job was queued for a campaign that does not exist",
            extra={"broadcast_id": str(broadcast_id)},
        )
    return plan.value


async def _started(
    store: SqlBroadcasts, plan: BroadcastPlan, *, at: datetime
) -> BroadcastState | None:
    """Move ``ready -> sending`` if this is the first chunk, and report where we are.

    ``mark_sending`` answers ``False`` on a replay — the campaign is already ``sending`` and
    the chunk proceeds, which is correct: the guard exists so ``started_at`` records the
    first message rather than the last restart. Anything else (paused, cancelled, still
    expanding) is returned unchanged and the caller stops.
    """
    if plan.state is not BroadcastState.READY:
        return plan.state
    if plan.scheduled_for is not None and plan.scheduled_for > at:
        # A chunk that arrived early. Nothing in this system enqueues one — the panel queues a
        # send only for a campaign with no instant, and the sweep waits for the instant to
        # pass — so this is a guard against a mis-enqueue rather than a path. It is worth
        # having because the failure it prevents is a campaign going out three days before the
        # operator said it would, which no later correction undoes.
        _LOG.warning(
            "a send chunk arrived before the campaign's scheduled instant; refusing it",
            extra={
                "broadcast_id": str(plan.id),
                "scheduled_for": plan.scheduled_for.isoformat(),
                "at": at.isoformat(),
            },
        )
        return plan.state
    started = await store.start(plan.id, at=at)
    if is_err(started):
        _LOG.error(
            "a campaign could not be moved to sending",
            extra={"broadcast_id": str(plan.id), **started.error.to_log_dict()},
        )
        return None
    return BroadcastState.SENDING


# ---------------------------------------------------------------------------
# The send chunk
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _Chunk:
    """One chunk's working state: the caches that make it cheap, and what it did.

    Mutable, and the only mutable thing in this module. The two caches are what keep a chunk
    to one object-store read and one image upload per language — after the first successful
    photo, every later message quotes the ``file_id`` Telegram answered with, which is
    ``assets.tg_file_id``'s cost control applied to a fan-out.
    """

    container: AppContainer
    bot: Bot
    store: SqlBroadcasts
    pacer: SendPacer
    broadcast_id: UUID
    bodies: Mapping[Language, ComposedBody]
    #: language -> the image's bytes, read once from our object store.
    media_bytes: dict[Language, bytes] = field(default_factory=dict)
    #: language -> the ``file_id`` Telegram minted, learned during this chunk.
    media_file_ids: dict[Language, str] = field(default_factory=dict)
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    undeliverable: int = 0
    #: Rows handed back to ``pending`` because the request never left this process.
    released: int = 0

    def language_of(self, recipient: ClaimedRecipient) -> ComposedBody | None:
        """The body this account reads, or ``None`` when the campaign has none it can use.

        Exact language, then ``uz_latn``, then ``en`` — ``bayram.bot.i18n._resolve_template``'s
        ladder, applied to operator-authored text rather than to a catalogue key. The
        compose-time validator refuses a campaign whose bodies do not cover its own preview,
        so reaching the end of this ladder is a defence and not a routine path.
        """
        for candidate in (recipient.language, FALLBACK_LANGUAGE, REFERENCE_LANGUAGE):
            body = self.bodies.get(candidate)
            if body is not None:
                return body
        return None


#: What one delivery attempt tells the loop: ``None`` to carry on, or the seconds every
#: sender is parked for — in which case the chunk ends here and its successor is deferred.
type _Deferral = float | None


async def send_broadcast_chunk(ctx: Mapping[str, Any], broadcast_id: str) -> dict[str, Any]:
    """Send one chunk of a campaign, settle every outcome, and queue the next chunk.

    The shape of one pass, in the order that makes it safe to replay:

    1. ``ready -> sending`` (a no-op on a replay), then a pause/cancel read;
    2. the pacer is asked whether Telegram has parked every sender. If it has, the chunk
       ends before claiming anything — a chunk that slept out a park in ``acquire`` would
       burn its job timeout and be cancelled with rows still claimed;
    3. up to :data:`~bayram.db.broadcasts.SEND_CHUNK_SIZE` rows are claimed, each by a
       conditional ``UPDATE`` whose rowcount is the claim, and the claim is committed;
    4. each row is paced, sent and settled individually, with the campaign's state re-read
       every :data:`PAUSE_CHECK_EVERY` messages so a stop is felt in seconds;
    5. the counters are recomputed from the rows, and either a successor is queued or the
       campaign is finished and its OUTCOME audit row written (``BROADCAST_SPEC §4.7``).

    Returns a JSON-safe summary, which ARQ keeps for an hour. It is operational garnish and
    never the record: Postgres holds the progress.
    """
    container = _require_container(ctx)
    bot = _require_bot(ctx)
    store = _store(container)
    campaign = _campaign_id(broadcast_id)
    at = utc_now()
    started = time.monotonic()

    plan = await _plan_or_none(store, campaign)
    if plan is None:
        return _send_summary(broadcast_id, started=started, error="unknown_campaign")
    state = await _started(store, plan, at=at)
    if state is not BroadcastState.SENDING:
        _LOG.info(
            "a send chunk found the campaign not sending",
            extra={"broadcast_id": broadcast_id, "state": str(state)},
        )
        return _send_summary(broadcast_id, started=started, state=state)

    parked_s = await _park_seconds(ctx, container)
    if parked_s > 0.0:
        await _enqueue(
            ctx,
            SEND_JOB_NAME,
            broadcast_id,
            job_id=_successor_id("send", campaign),
            defer_s=parked_s,
        )
        return _send_summary(broadcast_id, started=started, state=state, parked_s=parked_s)

    bodies = await store.bodies(campaign)
    if is_err(bodies):
        _LOG.error(
            "a campaign's bodies could not be read; the sweep will retry the chunk",
            extra={"broadcast_id": broadcast_id, **bodies.error.to_log_dict()},
        )
        return _send_summary(broadcast_id, started=started, error=bodies.error.code)

    claimed = await store.claim(campaign, at=at, limit=SEND_CHUNK_SIZE)
    if is_err(claimed):
        _LOG.error(
            "a send chunk could not be claimed; the sweep will retry it",
            extra={"broadcast_id": broadcast_id, **claimed.error.to_log_dict()},
        )
        return _send_summary(broadcast_id, started=started, error=claimed.error.code)

    chunk = _Chunk(
        container=container,
        bot=bot,
        store=store,
        pacer=_pacer(ctx, container),
        broadcast_id=campaign,
        bodies={body.language: body for body in bodies.value},
    )
    deferral = await _run_chunk(chunk, claimed.value, at=at)
    return await _close_chunk(
        ctx,
        chunk,
        plan=plan,
        claimed=len(claimed.value),
        deferral=deferral,
        at=at,
        started=started,
    )


async def _park_seconds(ctx: Mapping[str, Any], container: AppContainer) -> float:
    """How long every sender is parked for, read before a chunk commits to anything.

    A separate pacer instance from the one the chunk uses, because this call happens before
    the claim and the chunk's own is built after it; both read the same Redis key, which is
    where a park actually lives.
    """
    return await _pacer(ctx, container).parked_for_s()


async def _run_chunk(
    chunk: _Chunk, claimed: tuple[ClaimedRecipient, ...], *, at: datetime
) -> _Deferral:
    """Deliver to every claimed row, settling each one as it lands.

    A row is settled or released before this returns — never abandoned — except on a
    cancellation, which re-raises so ARQ sees it and leaves the row in ``sending`` for the
    sweep to retire to ``unknown``. That hole is the never-double-send rule being paid for,
    and it is deliberately visible rather than smoothed away.
    """
    for index, recipient in enumerate(claimed):
        if index and index % PAUSE_CHECK_EVERY == 0 and not await _is_still_sending(chunk):
            await _release_rest(chunk, claimed[index:], at=at)
            return None
        deferral = await _deliver(chunk, recipient, at=at)
        if deferral is not None:
            # Telegram parked every sender. This row's message never left the process, so it
            # and everything after it go back to ``pending`` — the one case where returning a
            # claimed row is not a double-send.
            await _release_rest(chunk, claimed[index:], at=at)
            return deferral
    return None


async def _is_still_sending(chunk: _Chunk) -> bool:
    """Re-read the campaign's state mid-chunk. A read failure keeps sending.

    Failing the other way would let one unreachable database turn a healthy campaign into a
    half-sent one, and the operator's pause is still honoured by the next chunk — which
    cannot start without a state read it will not get either.
    """
    state = await chunk.store.state_of(chunk.broadcast_id)
    if is_err(state):
        _LOG.error(
            "a campaign's state could not be re-read mid-chunk; continuing",
            extra={"broadcast_id": str(chunk.broadcast_id), **state.error.to_log_dict()},
        )
        return True
    if state.value is BroadcastState.SENDING:
        return True
    _LOG.info(
        "a campaign stopped mid-chunk; the rest of the claim is handed back",
        extra={"broadcast_id": str(chunk.broadcast_id), "state": str(state.value)},
    )
    return False


async def _release_rest(
    chunk: _Chunk, remaining: tuple[ClaimedRecipient, ...], *, at: datetime
) -> None:
    """Hand back rows this chunk claimed and will not send to.

    Legal exactly here: nothing was sent for any of them, so ``pending`` is the truth. A
    caller that could not say that must settle ``unknown`` instead.
    """
    for recipient in remaining:
        released = await chunk.store.release(recipient.id, at=at)
        if is_err(released):
            _LOG.error(
                "a claimed recipient could not be released; the lease will retire it",
                extra={"recipient_id": str(recipient.id), **released.error.to_log_dict()},
            )
            continue
        chunk.released += 1


async def _deliver(chunk: _Chunk, recipient: ClaimedRecipient, *, at: datetime) -> _Deferral:
    """One account: resolve the body, pace, send, settle. Returns a park, or ``None``.

    The refusal classification is ``BROADCAST_SPEC §4.5`` and the pacing is ``§4.3``.

    Everything that can fail without a Telegram call happening — a forgotten account, no
    usable body, an unreadable image — settles the row terminally and spends no budget. Only
    a row that reaches :meth:`SendPacer.acquire` can cost the campaign a message.
    """
    if recipient.telegram_user_id is None:
        # ``/forget`` ran between the expansion and the send. The row is claimed rather than
        # skipped so the campaign can finish: leaving it would keep ``outstanding`` above
        # zero forever.
        await _settle(chunk, recipient, BroadcastRecipientState.UNDELIVERABLE, _FORGOTTEN, at=at)
        chunk.undeliverable += 1
        return None
    body = chunk.language_of(recipient)
    if body is None:
        await _settle(chunk, recipient, BroadcastRecipientState.FAILED, _NO_BODY, at=at)
        chunk.failed += 1
        return None
    photo = await _photo(chunk, body)
    if body.media_storage_key is not None and photo is None:
        await _settle(chunk, recipient, BroadcastRecipientState.FAILED, _MEDIA_UNREADABLE, at=at)
        chunk.failed += 1
        return None

    await chunk.pacer.acquire()
    try:
        message = await _send(chunk, recipient.telegram_user_id, body=body, photo=photo)
    except TelegramRetryAfter as exc:
        # Not a failure of this recipient: the message never left. The row goes back to
        # ``pending`` with everything after it and the successor waits out the park.
        return await chunk.pacer.park_after_flood(exc)
    except TelegramAPIError as exc:
        await _settle_refusal(chunk, recipient, exc, at=at)
        return None
    await _remember_media(chunk, body, message=message, at=at)
    await _settle(chunk, recipient, BroadcastRecipientState.SENT, None, at=at)
    chunk.sent += 1
    return None


async def _send(
    chunk: _Chunk,
    telegram_user_id: int,
    *,
    body: ComposedBody,
    photo: str | BufferedInputFile | None,
) -> Message:
    """The one Telegram call. HTML, because the body is operator-authored HTML.

    It is **not** escaped here and **not** passed through ``translate``: the compose step
    validated it and an operator's deliberate ``<b>`` must survive to the customer. The
    optional button is a URL button and never a callback one — a callback needs a handler,
    and adding one for a campaign that ended last month is how a dead button becomes a
    customer-visible error.
    """
    markup = _button(body)
    if photo is None:
        return await chunk.bot.send_message(
            chat_id=telegram_user_id, text=body.text, reply_markup=markup
        )
    return await chunk.bot.send_photo(
        chat_id=telegram_user_id, photo=photo, caption=body.text, reply_markup=markup
    )


def _button(body: ComposedBody) -> InlineKeyboardMarkup | None:
    """The single URL button, or nothing. Both halves are present or neither is."""
    if body.button_label is None or body.button_url is None:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=body.button_label, url=body.button_url)]]
    )


async def _photo(chunk: _Chunk, body: ComposedBody) -> str | BufferedInputFile | None:
    """What to put in ``photo=``: a cached ``file_id``, the bytes, or nothing at all.

    ``None`` with no ``media_storage_key`` means this body is text. ``None`` *with* one means
    the object could not be read, which the caller turns into a failed row rather than into a
    campaign that quietly went out without its picture.
    """
    if body.media_storage_key is None:
        return None
    file_id = chunk.media_file_ids.get(body.language) or body.media_file_id
    if file_id is not None:
        return file_id
    cached = chunk.media_bytes.get(body.language)
    if cached is None:
        loaded = await chunk.container.storage.get(body.media_storage_key)
        if is_err(loaded):
            _LOG.error(
                "a campaign's image could not be read from the object store",
                extra={"broadcast_id": str(chunk.broadcast_id), **loaded.error.to_log_dict()},
            )
            return None
        cached = loaded.value
        chunk.media_bytes[body.language] = cached
    return BufferedInputFile(cached, filename=_MEDIA_FILENAME)


async def _remember_media(
    chunk: _Chunk, body: ComposedBody, *, message: Message, at: datetime
) -> None:
    """Cache the ``file_id`` Telegram minted, so the rest of the campaign quotes it.

    Written once — the ``UPDATE`` is guarded on ``media_file_id IS NULL`` — and held locally
    as well, because the chunk read its bodies before this send and would otherwise re-upload
    the same bytes for every remaining recipient in it.
    """
    if body.media_storage_key is None or body.language in chunk.media_file_ids:
        return
    if body.media_file_id is not None or not message.photo:
        return
    file_id = message.photo[-1].file_id
    chunk.media_file_ids[body.language] = file_id
    stored = await chunk.store.remember_media_file_id(
        chunk.broadcast_id, language=body.language, file_id=file_id, at=at
    )
    if is_err(stored):
        # The local cache still holds it, so this chunk pays nothing; the next one re-uploads
        # once. Worth an ERROR and not worth failing a send over.
        _LOG.error(
            "a campaign's image id could not be cached",
            extra={"broadcast_id": str(chunk.broadcast_id), **stored.error.to_log_dict()},
        )


async def _settle_refusal(
    chunk: _Chunk, recipient: ClaimedRecipient, exc: TelegramAPIError, *, at: datetime
) -> None:
    """Classify one Telegram refusal onto the row, and record a block where there is one.

    Three outcomes and they are not interchangeable. A customer who blocked the bot is
    ``skipped_blocked`` — no delivery was attempted in any meaningful sense — and it is
    ALSO written to ``bot_membership_events`` through the same recorder the delivery arm
    uses, because ``run_polling(drop_pending_updates=True)`` throws away every
    ``my_chat_member`` update that arrived during a deploy and a broadcast is the largest
    block detector this system will ever have. A deactivated account or a chat that is gone
    is ``undeliverable``: nobody can ever be won back from it, and counting it as churn would
    put a number on the dashboard no second source could corroborate. Everything else is
    ``failed``, carrying the exception's class name and never its message.
    """
    if is_blocked_by_customer(exc):
        await _settle(chunk, recipient, BroadcastRecipientState.SKIPPED_BLOCKED, _BLOCKED, at=at)
        chunk.skipped += 1
        await _record_block(chunk, recipient, at=at)
        return
    if _is_undeliverable(exc):
        await _settle(
            chunk, recipient, BroadcastRecipientState.UNDELIVERABLE, _CHAT_UNAVAILABLE, at=at
        )
        chunk.undeliverable += 1
        return
    _LOG.warning(
        "a broadcast message was refused",
        extra={
            "broadcast_id": str(chunk.broadcast_id),
            "recipient_id": str(recipient.id),
            "failure": type(exc).__name__,
        },
    )
    await _settle(chunk, recipient, BroadcastRecipientState.FAILED, type(exc).__name__, at=at)
    chunk.failed += 1


def _is_undeliverable(exc: TelegramAPIError) -> bool:
    """Whether the chat is GONE, as opposed to closed to us or briefly unhappy.

    A structured fact rather than a substring test on a log line, and deliberately narrow:
    the dependency on Telegram's wording is real and is accepted in the direction that
    degrades to ``failed`` — a weaker fact — rather than to ``undeliverable``, which asserts
    something about a customer's account that we would then have no evidence for.
    """
    message = (exc.message or "").casefold()
    return any(known in message for known in _UNDELIVERABLE_MESSAGES)


async def _record_block(chunk: _Chunk, recipient: ClaimedRecipient, *, at: datetime) -> None:
    """Feed a refusal to the churn recorder. Never changes this send's outcome."""
    recorder = chunk.container.bot_blocks
    if recorder is None or recipient.telegram_user_id is None:
        return
    recorded = await recorder.record_bot_blocked(
        recipient.telegram_user_id, at=at, source=BotBlockSource.DELIVERY_REFUSAL
    )
    if is_err(recorded):
        _LOG.warning(
            "a broadcast refusal could not be recorded as a block",
            extra={"recipient_id": str(recipient.id), **recorded.error.to_log_dict()},
        )


async def _settle(
    chunk: _Chunk,
    recipient: ClaimedRecipient,
    state: BroadcastRecipientState,
    error_code: str | None,
    *,
    at: datetime,
) -> None:
    """Close one row, in its own transaction. ``False`` is a replay, not a failure."""
    settled = await chunk.store.settle(recipient.id, state=state, at=at, error_code=error_code)
    if is_err(settled):
        _LOG.error(
            "a recipient's outcome could not be recorded; the lease will retire the row",
            extra={
                "broadcast_id": str(chunk.broadcast_id),
                "recipient_id": str(recipient.id),
                "state": state.value,
                **settled.error.to_log_dict(),
            },
        )


async def _close_chunk(
    ctx: Mapping[str, Any],
    chunk: _Chunk,
    *,
    plan: BroadcastPlan,
    claimed: int,
    deferral: _Deferral,
    at: datetime,
    started: float,
) -> dict[str, Any]:
    """Retire abandoned rows, recount, then queue the next chunk or finish the campaign.

    The lease is aged **before** the roll-up because ``outstanding`` counts ``sending``: a
    campaign with a row left behind by a killed job would otherwise never reach zero, and
    would never finish.
    """
    container = chunk.container
    lease_s = container.settings.broadcast_sending_lease_s
    aged = await chunk.store.age_stale(
        chunk.broadcast_id, older_than=at - timedelta(seconds=lease_s), at=at
    )
    if is_err(aged):
        _LOG.error(
            "abandoned recipients could not be retired",
            extra={"broadcast_id": str(chunk.broadcast_id), **aged.error.to_log_dict()},
        )
    tally = await chunk.store.roll_up(chunk.broadcast_id, at=at)
    if is_err(tally):
        _LOG.error(
            "a campaign's counters could not be rolled up",
            extra={"broadcast_id": str(chunk.broadcast_id), **tally.error.to_log_dict()},
        )
        return _send_summary(str(chunk.broadcast_id), started=started, chunk=chunk, claimed=claimed)

    state = await chunk.store.state_of(chunk.broadcast_id)
    is_sending = not is_err(state) and state.value is BroadcastState.SENDING
    is_finished = False
    if is_sending and tally.value.outstanding == 0:
        is_finished = await _finish(container, plan, tally=tally.value, at=at)
    elif is_sending and claimed:
        # A successor only when this chunk actually claimed something. A chunk that claimed
        # NOTHING while rows are still outstanding is waiting on the lease — every remaining
        # row is in ``sending`` behind a job that died — and enqueueing a successor for that
        # would spin the queue at full speed for five minutes to do nothing. The sweep is
        # what wakes that campaign, once, when the lease has actually expired.
        await _enqueue(
            ctx,
            SEND_JOB_NAME,
            str(chunk.broadcast_id),
            job_id=_successor_id("send", chunk.broadcast_id),
            defer_s=deferral or 0.0,
        )
    elif is_sending:
        _LOG.info(
            "a campaign has nothing claimable left; the sweep will resume it after the lease",
            extra={
                "broadcast_id": str(chunk.broadcast_id),
                "outstanding": tally.value.outstanding,
                "lease_s": lease_s,
            },
        )
    summary = _send_summary(
        str(chunk.broadcast_id),
        started=started,
        chunk=chunk,
        claimed=claimed,
        tally=tally.value,
        parked_s=deferral or 0.0,
        is_finished=is_finished,
    )
    _LOG.info("a broadcast chunk finished", extra=summary)
    return summary


# ---------------------------------------------------------------------------
# Finishing, and the OUTCOME audit row
# ---------------------------------------------------------------------------
async def _finish(
    container: AppContainer, plan: BroadcastPlan, *, tally: RecipientTally, at: datetime
) -> bool:
    """Mark the campaign ``completed`` and record the outcome, in ONE transaction.

    One transaction because the two halves are one fact: a campaign marked finished with no
    audit row, or an audit row for a campaign that is not finished, are both worse than
    neither. ``mark_finished`` answers ``False`` when the campaign was already terminal —
    a replayed final chunk — and the audit row is then not written either, so a replay is a
    no-op rather than a second outcome for one run.

    ``FAILED`` is not reachable from here and that is the design: a campaign in which twelve
    of forty thousand messages were refused is ``COMPLETED``. The per-account outcome lives
    on the recipient row.
    """
    key = audit_chain_key()
    if key is None:
        _LOG.error(
            "no audit chain key in this worker; the campaign's outcome row is not written",
            extra={"broadcast_id": str(plan.id), "variable": f"{ENV_PREFIX}ADMIN_AUDIT_HMAC_KEY"},
        )
    sessions = container.require_session_factory()

    async def _write() -> bool:
        async with sessions.begin() as session:
            finished = await mark_finished(
                session, broadcast_id=plan.id, state=BroadcastState.COMPLETED, at=at
            )
            if finished and key is not None:
                await _append_outcome(session, plan, tally=tally, key=key, at=at)
            return finished

    outcome = await run_guarded("broadcasts.finish_with_audit", _write, broadcast_id=str(plan.id))
    if is_err(outcome):
        # The sweep re-reads this campaign in five minutes and finishes it then: nothing was
        # sent that is not on a row, and ``outstanding`` is still zero.
        return False
    if outcome.value:
        _LOG.info(
            "a campaign finished",
            extra={
                "broadcast_id": str(plan.id),
                "sent": tally.sent,
                "failed": tally.failed,
                "skipped": tally.skipped,
                "undeliverable": tally.undeliverable,
                "unknown": tally.unknown,
            },
        )
    return outcome.value


async def _append_outcome(
    session: AsyncSession, plan: BroadcastPlan, *, tally: RecipientTally, key: str, at: datetime
) -> None:
    """Write ``broadcast.sent`` — the row that says what actually landed.

    Two audit rows exist per campaign and they answer different questions: the panel's
    ``broadcast.schedule`` records that an operator authorised a message to N accounts, which
    is knowable in the request; this one records what became of it, which is knowable only an
    hour later and only here. The actor is the operator who scheduled it, with the role read
    live from ``admin_users`` — the action being recorded is this completion, so today's role
    is the role at the time of the action.

    The retry mirrors ``bayram.admin.audit_sink._append``: a value refused at the boundary is an
    incident to surface, and the action is still recorded without it.
    """
    entry = AuditEntry(
        action=AuditAction.BROADCAST_SENT,
        actor_id=plan.actor.admin_id,
        actor_username=plan.actor.username or _SYSTEM_ACTOR,
        actor_role=plan.actor_role or _SYSTEM_ROLE,
        subject_type="broadcast",
        subject_id=str(plan.id),
        field_names=("broadcasts.state", "broadcasts.sent_count"),
        record_count=tally.sent,
        reason_code=plan.reason_code or AuditReasonCode.ROUTINE_OPS,
        reason_ref=plan.reason_ref,
        outcome=AuditOutcome.OK,
    )
    try:
        await append(session, entry, key=key, now=at)
    except AuditValueRejectedError:
        _LOG.exception(
            "an audited value was refused; the campaign's outcome is recorded without it",
            extra={"broadcast_id": str(plan.id)},
        )
        await append(
            session,
            replace(entry, actor_id=None, actor_username=_UNSTORABLE_USERNAME),
            key=key,
            now=at,
        )


async def _fail_campaign(
    container: AppContainer, plan: BroadcastPlan, *, error_code: str, at: datetime
) -> None:
    """Stop a campaign that cannot run at all. No audit row: nothing was sent.

    ``FAILED`` grades the RUN, and this is the only thing in the pipeline that can produce
    it — a structural defect, discovered before any message left. The outcome row is
    deliberately not written: ``broadcast.sent`` says what landed, and nothing did.
    """
    store = _store(container)
    finished = await store.finish(
        plan.id, state=BroadcastState.FAILED, at=at, error_code=error_code
    )
    if is_err(finished):
        _LOG.error(
            "a campaign that cannot run could not be marked failed",
            extra={"broadcast_id": str(plan.id), **finished.error.to_log_dict()},
        )
        return
    _LOG.error(
        "a campaign was failed before anything was sent",
        extra={"broadcast_id": str(plan.id), "error_code": error_code},
    )


# ---------------------------------------------------------------------------
# The test send
# ---------------------------------------------------------------------------
async def send_broadcast_test(
    ctx: Mapping[str, Any], broadcast_id: str, telegram_user_id: int
) -> dict[str, Any]:
    """Send every composed body to ONE account, so a human can read what will go out.

    Every language, one message each, because the point is to proof-read the campaign rather
    than to simulate one delivery — and because this job is handed an account, never a
    language. It writes NO recipient row and touches no counter: a test send is not part of
    the campaign's ledger, and putting it there would make ``sent_count`` a number that
    includes the operator.

    The allowlist that decides who may receive this lives in the panel
    (``admin_broadcast_test_recipients``) and is enforced before the enqueue. This job trusts
    the id it is given, exactly as the kit job trusts its chat id.
    """
    container = _require_container(ctx)
    bot = _require_bot(ctx)
    store = _store(container)
    campaign = _campaign_id(broadcast_id)
    at = utc_now()
    started = time.monotonic()

    bodies = await store.bodies(campaign)
    if is_err(bodies):
        return _test_summary(broadcast_id, started=started, error=bodies.error.code)
    chunk = _Chunk(
        container=container,
        bot=bot,
        store=store,
        pacer=_pacer(ctx, container),
        broadcast_id=campaign,
        bodies={body.language: body for body in bodies.value},
    )
    sent = 0
    failures: list[str] = []
    for body in bodies.value:
        photo = await _photo(chunk, body)
        if body.media_storage_key is not None and photo is None:
            failures.append(_MEDIA_UNREADABLE)
            continue
        await chunk.pacer.acquire()
        try:
            message = await _send(chunk, telegram_user_id, body=body, photo=photo)
        except TelegramAPIError as exc:
            # Including a flood wait: a test send is one message an operator is watching for,
            # so there is nothing to defer and nothing to hand to a successor.
            failures.append(type(exc).__name__)
            continue
        await _remember_media(chunk, body, message=message, at=at)
        sent += 1
    summary = _test_summary(broadcast_id, started=started, sent=sent, failures=tuple(failures))
    _LOG.info("a broadcast test send finished", extra=summary)
    return summary


# ---------------------------------------------------------------------------
# The sweep — the scheduled-send path and the crash recovery, in one cron
# ---------------------------------------------------------------------------
async def sweep_due_broadcasts(
    ctx: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Start campaigns whose instant has arrived, and revive the ones whose worker died.

    ``now`` is injectable for the reason every clock in this repository is: a test schedules
    a campaign for tomorrow and arrives there in one line.

    **Both of its arms are the same sentence — enqueue what is waiting — and neither is
    optional.** A scheduled campaign has nobody else to start it: the panel enqueues nothing
    for a future instant, deliberately, because a job deferred by three days in Redis is a
    promise made by the least durable component in the system. And a campaign whose chunk job
    was cancelled mid-deploy has nobody else to resume it either: ARQ's own retry cannot,
    because a cancelled job's rows are already claimed and its successor was never queued.

    Only campaigns that have stopped moving are revived — ``broadcasts.updated_at`` is
    re-stamped by every chunk's roll-up — so a healthy campaign is never given a second chain
    of chunk jobs by a sweep that runs twelve times an hour.

    It never raises into the scheduler. A failed sweep is logged and reported; the next one
    five minutes later is the retry, and ``max_tries=1`` is what keeps a failure from
    becoming two concurrent sweeps.
    """
    container = _require_container(ctx)
    store = _store(container)
    at = now or utc_now()
    started = time.monotonic()
    lease_s = container.settings.broadcast_sending_lease_s

    due = await store.due(now=at, stalled_before=at - timedelta(seconds=lease_s))
    if is_err(due):
        _LOG.error("the broadcast sweep could not read its work", extra=due.error.to_log_dict())
        return _sweep_summary(started=started, faults=1)

    expansions = 0
    sends = 0
    aged = 0
    for campaign in due.value:
        if campaign.state is BroadcastState.EXPANDING:
            expansions += int(await _resume_expansion(ctx, campaign))
            continue
        if campaign.state is BroadcastState.SENDING:
            aged += await _age(store, campaign, lease_s=lease_s, at=at)
        sends += int(
            await _enqueue(
                ctx,
                SEND_JOB_NAME,
                str(campaign.id),
                job_id=_successor_id("send", campaign.id),
            )
        )
    summary = _sweep_summary(
        started=started, scanned=len(due.value), expansions=expansions, sends=sends, aged=aged
    )
    _LOG.info("the broadcast sweep finished", extra=summary)
    return summary


async def _resume_expansion(ctx: Mapping[str, Any], campaign: DueBroadcast) -> bool:
    """Re-queue a stalled expansion against the instant its audience was frozen at."""
    return await _enqueue(
        ctx,
        EXPAND_JOB_NAME,
        str(campaign.id),
        campaign.audience_evaluated_at.isoformat(),
        job_id=_successor_id("expand", campaign.id),
    )


async def _age(
    store: SqlBroadcasts, campaign: DueBroadcast, *, lease_s: float, at: datetime
) -> int:
    """Retire this campaign's abandoned claims before its next chunk counts them.

    Done here as well as at the end of a chunk because a campaign whose last chunk job was
    killed has no chunk to do it: its rows sit in ``sending``, ``outstanding`` never reaches
    zero, and the campaign would never finish however many times the sweep re-queued it.
    """
    aged = await store.age_stale(campaign.id, older_than=at - timedelta(seconds=lease_s), at=at)
    if is_err(aged):
        _LOG.error(
            "abandoned recipients could not be retired by the sweep",
            extra={"broadcast_id": str(campaign.id), **aged.error.to_log_dict()},
        )
        return 0
    return aged.value


# ---------------------------------------------------------------------------
# Summaries — what ARQ stores, and what the log lines carry
# ---------------------------------------------------------------------------
def _expand_summary(
    broadcast_id: str,
    *,
    started: float,
    chunk: ExpansionChunk | None = None,
    state: BroadcastState | None = None,
    is_due: bool | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "broadcast_id": broadcast_id,
        "scanned": 0 if chunk is None else chunk.scanned,
        "inserted": 0 if chunk is None else chunk.inserted,
        "suppressed": 0 if chunk is None else chunk.suppressed,
        "is_complete": False if chunk is None else chunk.is_complete,
        "state": None if state is None else str(state),
        "is_due": is_due,
        "duration_ms": _elapsed_ms(started),
        "error": error,
    }


def _send_summary(
    broadcast_id: str,
    *,
    started: float,
    chunk: _Chunk | None = None,
    claimed: int = 0,
    tally: RecipientTally | None = None,
    state: BroadcastState | None = None,
    parked_s: float = 0.0,
    is_finished: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "broadcast_id": broadcast_id,
        "claimed": claimed,
        "sent": 0 if chunk is None else chunk.sent,
        "failed": 0 if chunk is None else chunk.failed,
        "skipped": 0 if chunk is None else chunk.skipped,
        "undeliverable": 0 if chunk is None else chunk.undeliverable,
        "released": 0 if chunk is None else chunk.released,
        "remaining": None if tally is None else tally.outstanding,
        "unknown": None if tally is None else tally.unknown,
        "state": None if state is None else str(state),
        "parked_s": round(parked_s, 3),
        "is_finished": is_finished,
        "duration_ms": _elapsed_ms(started),
        "error": error,
    }


def _test_summary(
    broadcast_id: str,
    *,
    started: float,
    sent: int = 0,
    failures: tuple[str, ...] = (),
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "broadcast_id": broadcast_id,
        "sent": sent,
        "failures": list(failures),
        "duration_ms": _elapsed_ms(started),
        "error": error,
    }


def _sweep_summary(
    *,
    started: float,
    scanned: int = 0,
    expansions: int = 0,
    sends: int = 0,
    aged: int = 0,
    faults: int = 0,
) -> dict[str, Any]:
    return {
        "campaigns_scanned": scanned,
        "expansions_enqueued": expansions,
        "sends_enqueued": sends,
        "recipients_retired": aged,
        "faults": faults,
        "duration_ms": _elapsed_ms(started),
    }


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


assert expand_broadcast_audience.__name__ == EXPAND_JOB_NAME, (
    "the enqueue name and the job function have drifted apart; ARQ would never dispatch"
)
assert send_broadcast_chunk.__name__ == SEND_JOB_NAME, (
    "the enqueue name and the job function have drifted apart; ARQ would never dispatch"
)
assert send_broadcast_test.__name__ == TEST_SEND_JOB_NAME, (
    "the enqueue name and the job function have drifted apart; ARQ would never dispatch"
)
assert sweep_due_broadcasts.__name__ == DUE_JOB_NAME, (
    "the registered name and the job function have drifted apart; ARQ would never dispatch"
)
