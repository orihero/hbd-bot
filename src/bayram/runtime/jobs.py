"""The job: generate the kit, then deliver it to the chat that asked for it.

``bayram.pipeline.worker.generate_kit`` stops at "kit persisted". Delivery is a Telegram
concern and the pipeline does not know Telegram exists — correctly. Something has to join
them, and this is that something: the only module in the system that imports both the
orchestrator and ``aiogram``.

The chat and the progress message travel *with the job*, not on the pipeline, because the
pipeline is shared across concurrent orders and a progress sink is aimed at exactly one
message. A per-job sink is the difference between fifteen customers watching their own
order and fifteen customers watching the fifteenth.

Because it is the join, it also owns every way the run can end from the customer's side:

* a terminal failure sends the error's ``user_message_key`` to the chat. The pipeline
  computes that key precisely so somebody can say it out loud, and this is the only place
  that can — ``error.content_not_allowed`` is the one failure a customer can fix by
  rewording, and it is worth nothing sitting in a job result dict;
* the send window is a real stage. ``DELIVERING`` is announced before the first byte
  leaves and only marked succeeded once ``deliver_kit`` says everything landed, so
  "sending it now" is never on screen for a kit that never arrived;
* the queue's job timeout cancels this coroutine. Cancellation emits no event, so the
  cancellation handler draws one terminal frame itself and then re-raises: ARQ must still
  see the cancellation, and the customer must not be left watching a bar that stopped;
* **retry exhaustion is a terminal end too, and it is one only this module can see.** ARQ
  compares ``job_try`` to ``max_tries`` *before* it calls the job function, so the attempt
  that would have been the sixth never runs: no frame is drawn, nobody is told, and the
  session is never released. Leaving that to the queue left a customer watching
  ``📦 Sending it over…`` forever with the wizard refusing every button. So the job reads
  the same ``max_tries`` the worker is configured with and, on its LAST attempt, stops
  raising ``Retry`` and takes the terminal path instead. See :func:`_is_final_attempt`;
* **the credit is settled here, and only here.** ``CreditGatedPaymentProvider`` is the only
  writer of a debit and it runs at ``AUTHORIZING``, near the top of the pipeline; nothing
  inside the pipeline knows whether the kit ever reached the customer, so nothing inside it
  can close that debit. This module is the first frame that does. Which of the three
  settlements a run gets is a policy with two separate exploits either side of it — see
  :func:`_settle`;
* the wizard session is released here, and only here. ``handlers.confirm`` deliberately
  does NOT clear the FSM when it queues an order — it parks it in ``Wizard.submitting`` so
  ``handlers.submitting`` can answer "still being made" for the whole generation window —
  which means something has to un-park it when the run ends, or the customer is told their
  song is in the studio for as long as the state survives. Redis is not that backstop:
  ``WIZARD_STATE_TTL`` is the fourteen-day abandoned-draft retention clock, a data
  lifetime rather than a session one. See :func:`_release_session`.

It also assembles ``WorkerSettings``, which is where every OTHER job lives. There are eleven
of them now, each in its own module and each registered here:

* the hourly retention sweep (:mod:`bayram.runtime.retention_job`). Until it was added,
  ``functions`` held one entry and ``cron_jobs`` did not exist, so ``purge_expired`` —
  complete, tested and legally required — was called by nothing at all;
* the hourly vendor balance poll (:mod:`bayram.runtime.vendor_balance_job`), the only thing in
  the system that asks a vendor how much credit is left. It runs HERE, in the worker, and
  never in the admin process, which holds no vendor key and no HTTP client by design;
* the nightly activity snapshot (:mod:`bayram.runtime.activity_job`), which gives
  ``users.last_seen_at`` — a gauge that is overwritten every minute — a history that can be
  charted;
* the settled-payment notification and the five-minutely Payme sweep
  (:mod:`bayram.runtime.payme_jobs`). These two are the first entries here whose ENQUEUE side is
  not in this repository's bot or admin process at all: the Payme gateway is a fourth process
  that holds the cashbox key and NO Telegram token, so "tell the customer their payment
  landed" is necessarily a job this worker performs on its behalf. The sweep is the backstop
  for the enqueue that gateway is allowed to lose — it owes Payme an HTTP 200 whether or not
  Redis answered — and it is the only cron here that fires more than once an hour, because its
  cadence is the ceiling on how long a paying customer waits to hear from us;
* the broadcast pipeline (:mod:`bayram.runtime.broadcast_job`) — an expansion, a send chunk, a
  one-account test send and a five-minutely due sweep. Their enqueue side is the ADMIN
  PANEL, the second process after the Payme gateway to queue work here, and for the mirror
  image of that reason: the panel is denied a Telegram token by design, so composing a
  campaign and sending it are necessarily two processes. The sweep is both the scheduled-send
  path (nothing else starts a campaign scheduled for Monday) and the crash recovery for a
  chunk job a deploy cancelled mid-send;
* the two support-ticket jobs (:mod:`bayram.runtime.support_jobs`) — repaint one ticket's card
  in the staff group, and deliver one operator's reply to the customer. Their enqueue side is
  the ADMIN PANEL again, for the same D10 reason as the broadcast four, and they are the first
  entries here with NO backstop sweep behind them. That is deliberate and is argued in their
  module: an unposted card and an undelivered reply are both already visible to an operator —
  on the board and on the ticket's timeline — where a settled-but-unannounced payment was
  visible to nobody, which is the whole reason ``run_payme_sweep`` has a third arm.

The registration is here rather than in each job's own module because ARQ needs one class
naming every job the process can run, and one place naming them is what keeps the enqueue
side and the worker side in step. Every entry states its ``timeout``, ``max_tries`` and
``run_at_startup`` explicitly and says why beside it: those three are where a scheduled job
either starves the customer-facing queue or hammers a rate-limited vendor.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import Retry, func
from sqlalchemy.exc import SQLAlchemyError

from bayram.bot.delivery import BLOCKED_BY_CUSTOMER_KEY, deliver_kit
from bayram.bot.handlers.submitting import ORDER_ID_KEY
from bayram.bot.i18n import translate
from bayram.bot.keyboards import start_over_keyboard
from bayram.bot.progress import TelegramProgressSink
from bayram.config import Settings
from bayram.contracts import BotBlockSource, Err, Order, is_ok
from bayram.db.repository import record_song_file_id
from bayram.entitlements import SettlementOutcome
from bayram.errors import BayramError, PipelineError
from bayram.logging import correlation_scope, get_logger
from bayram.payments import PIPELINE_ACTOR
from bayram.pipeline import worker as pipeline_worker
from bayram.pipeline.events import (
    PipelineStage,
    ProgressReporter,
    ProgressStatus,
    scheduled_stages,
)
from bayram.pipeline.outcome import PipelineOutcome
from bayram.pipeline.worker import KIT_JOB_NAME
from bayram.runtime.activity_job import (
    ACTIVITY_SNAPSHOT_CRON_HOUR,
    ACTIVITY_SNAPSHOT_CRON_MINUTE,
    ACTIVITY_SNAPSHOT_JOB_NAME,
    record_activity_snapshot,
)
from bayram.runtime.broadcast_job import (
    BROADCAST_DUE_CRON_MINUTE,
    DUE_JOB_NAME,
    EXPAND_JOB_NAME,
    SEND_JOB_NAME,
    TEST_SEND_JOB_NAME,
    expand_broadcast_audience,
    send_broadcast_chunk,
    send_broadcast_test,
    sweep_due_broadcasts,
)
from bayram.runtime.container import AppContainer
from bayram.runtime.payme_jobs import (
    PAYME_NOTIFY_JOB_NAME,
    PAYME_NOTIFY_MAX_TRIES,
    PAYME_SWEEP_JOB_NAME,
    notify_payment_settled,
    run_payme_sweep,
    sweep_minutes,
)
from bayram.runtime.retention_job import (
    RETENTION_CRON_MINUTE,
    RETENTION_JOB_NAME,
    run_retention_sweep,
)
from bayram.runtime.support_jobs import (
    SUPPORT_CARD_JOB_NAME,
    SUPPORT_CARD_MAX_TRIES,
    SUPPORT_RELAY_JOB_NAME,
    SUPPORT_RELAY_MAX_TRIES,
    SUPPORT_VERIFY_JOB_NAME,
    SUPPORT_VERIFY_MAX_TRIES,
    relay_support_reply,
    sync_support_card,
    verify_support_group,
)
from bayram.runtime.vendor_balance_job import (
    VENDOR_BALANCE_CRON_MINUTE,
    VENDOR_BALANCE_JOB_NAME,
    poll_vendor_balances,
)
from bayram.usage import usage_scope

__all__ = [
    "generate_and_deliver",
    "run_retention_sweep",
    "poll_vendor_balances",
    "record_activity_snapshot",
    "notify_payment_settled",
    "run_payme_sweep",
    "expand_broadcast_audience",
    "send_broadcast_chunk",
    "send_broadcast_test",
    "sweep_due_broadcasts",
    "sync_support_card",
    "relay_support_reply",
    "build_kit_worker_settings",
    "KIT_JOB_NAME",
    "RETENTION_JOB_NAME",
    "VENDOR_BALANCE_JOB_NAME",
    "ACTIVITY_SNAPSHOT_JOB_NAME",
    "PAYME_NOTIFY_JOB_NAME",
    "PAYME_SWEEP_JOB_NAME",
    "EXPAND_JOB_NAME",
    "SEND_JOB_NAME",
    "TEST_SEND_JOB_NAME",
    "DUE_JOB_NAME",
    "SUPPORT_CARD_JOB_NAME",
    "SUPPORT_RELAY_JOB_NAME",
    "SUPPORT_VERIFY_JOB_NAME",
    "CONTAINER_CTX_KEY",
    "BOT_CTX_KEY",
    "STORAGE_CTX_KEY",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function name, so the enqueue side and the worker side must agree
#: on this exact string. It is asserted against the function itself at the bottom of this
#: module.
#:
#: RE-EXPORTED, not defined: it now lives in :mod:`bayram.pipeline.worker`, which imports
#: nothing from ``bayram.runtime`` and can therefore be imported by ``runtime.submitter``
#: while this module is still executing. See that constant's docstring for the cycle. This
#: name stays because every existing importer — and two tests — reach for it here.

CONTAINER_CTX_KEY: Final[str] = "container"
BOT_CTX_KEY: Final[str] = "bot"

#: The wizard's FSM storage, so a finished run can un-park the session that is waiting on
#: it. OPTIONAL in the context: a worker wired without it still generates and delivers, it
#: only leaves the session parked, so a missing handle is logged rather than raised. Both
#: processes build it from the same Redis URL with aiogram's default key builder, which is
#: what makes the worker's key the same key the bot process writes.
STORAGE_CTX_KEY: Final[str] = "fsm_storage"

#: Job-level retry backoff. Multiplied by the attempt number, as ARQ counts them from 1.
_DEFAULT_JOB_TRY: Final[int] = 1


def _require[T](ctx: Mapping[str, Any], key: str, expected: type[T]) -> T:
    value = ctx.get(key)
    if not isinstance(value, expected):
        raise PipelineError(
            f"worker context is missing a usable '{key}'",
            context={"key": key, "found": type(value).__name__},
        )
    return value


def _attempt(ctx: Mapping[str, Any]) -> int:
    """Which attempt this is, counting from 1 the way ARQ does."""
    attempt = ctx.get("job_try", _DEFAULT_JOB_TRY)
    return attempt if isinstance(attempt, int) and attempt > 0 else _DEFAULT_JOB_TRY


def _defer_seconds(ctx: Mapping[str, Any], settings: Settings) -> float:
    return settings.provider_backoff_base_s * _attempt(ctx)


def _is_final_attempt(ctx: Mapping[str, Any], settings: Settings) -> bool:
    """``True`` when raising ``Retry`` would hand the order to nobody.

    ARQ checks ``job_try > max_tries`` at the top of its own runner, so the retry queued by
    the last permitted attempt is discarded before the job function is entered again. From
    inside the job, that discard is invisible and unrecoverable: no progress frame, no
    message, no session release. The only place the difference can be observed is here,
    before the ``Retry`` is raised, which is why this reads the setting rather than trusting
    the queue to come back.
    """
    return _attempt(ctx) >= settings.queue_max_tries


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _order_uuid(order_id: str) -> UUID:
    """Parse the queued id. A non-UUID means the enqueue side is broken, so it raises."""
    try:
        return UUID(order_id)
    except ValueError as exc:
        raise PipelineError(
            "job was queued with an order id that is not a UUID",
            context={"order_id": order_id},
            cause=exc,
        ) from exc


async def _settle(container: AppContainer, order: Order, *, outcome: SettlementOutcome) -> None:
    """Close this order's debit in the ledger. Never raises, whatever the store does.

    Called on exactly the ends that are final, and deliberately NOT on the ones that are
    coming back. Each half of that is a separate exploit:

    * ``DELIVERED`` and ``NOT_DELIVERED`` both CONSUME — delta 0, the debit marked spent,
      the in-flight slot freed. Refunding a failed *send* would be an exploit rather than a
      kindness: ``DeliveryError`` is retryable and by the time :func:`_send_kit` gives up
      the kit is fully rendered and persisted (``orders``/``kits``, so it is redeliverable),
      which means someone who blocks the bot the moment they tap Confirm would collect a
      full LLM + ElevenLabs render, five refused sends and their credit back — unlimited
      renders for one credit.
    * ``FAILED`` REFUNDS, moderation rejection included. The FAILED progress frame already
      tells the customer "you have not lost anything" (``progress.failed``), and this call
      is the only thing that makes that sentence true. Retry exhaustion arrives here too and
      is the same fact: nothing was delivered.
    * The ``asyncio.CancelledError`` path in :func:`generate_and_deliver` settles NOTHING.
      ``build_kit_worker_settings`` never sets ``retry_jobs``, so arq's default ``True``
      applies and ``Worker.handle_sig`` cancels running tasks on SIGTERM — a refund there
      would be a refund plus a requeue plus a replay that finds the order unpaid and charges
      nothing back, i.e. one free song per deploy. The two ``Retry`` paths raise out above
      this call for the same reason: the run is not over.

    ``Ok(False)`` is a normal answer, not a failure. It means the order was never debited
    (no store wired, or an account erased mid-render) or that a redelivered job already
    settled it. It is no longer the ordinary answer under ``credits_enforced=False``: the
    gate charges whatever that flag says, because the in-flight cap counts the rows it
    writes — the flag now only decides whether an empty balance REFUSES.
    """
    store = container.credits
    if store is None:
        # Only a hand-built container reaches this. ``build_container`` always wires
        # ``SqlCreditLedger``, whatever the enforcement flag says.
        _LOG.warning(
            "no entitlement store in the worker context; the debit stays open",
            extra={"order_id": str(order.id), "outcome": str(outcome)},
        )
        return
    try:
        settled = await store.settle(
            telegram_user_id=order.telegram_user_id,
            order_id=order.id,
            outcome=outcome,
            actor=PIPELINE_ACTOR,
        )
    except Exception:
        # ``run_guarded`` already turns every expected database failure into an ``Err``, so
        # anything raising here is the store itself being broken. The kit has already been
        # sent, or the failure already explained; losing that message over bookkeeping is
        # strictly worse, and an unsettled debit is the case WU6's sweep exists to close.
        _LOG.exception(
            "settling the credit raised; the debit stays open",
            extra={"order_id": str(order.id), "outcome": str(outcome)},
        )
        return
    if isinstance(settled, Err):
        _LOG.error(
            "the credit could not be settled; the debit stays open",
            extra={
                **settled.error.to_log_dict(),
                "order_id": str(order.id),
                "outcome": str(outcome),
            },
        )
        return
    if not settled.value and outcome is SettlementOutcome.DELIVERED:
        # A kit reached a customer and the ledger had nothing to close. That is either an
        # ordinary redelivery (the first run already consumed it) or a SONG THAT WAS FREE:
        # the debit was refunded out from under a live job — by the sweep, or by a
        # settlement written on a retry — so ``consume`` found ``net_position == 0``. There
        # is no other externally visible trace of the second case, so it is not allowed to
        # share the INFO line with every dark-meter no-op.
        _LOG.warning(
            "a delivered order settled nothing; its debit was already closed",
            extra={"order_id": str(order.id), "telegram_user_id": order.telegram_user_id},
        )
        return
    _LOG.info(
        "credit settled",
        extra={
            "order_id": str(order.id),
            "outcome": str(outcome),
            # False is the redelivery case and the never-charged case, not a problem.
            "is_written": settled.value,
        },
    )


async def _run_pipeline(
    container: AppContainer,
    bot: Bot,
    order: Order,
    *,
    ctx: Mapping[str, Any],
    sink: TelegramProgressSink,
    chat_id: int,
) -> PipelineOutcome | dict[str, Any]:
    """The outcome, or the JSON summary to return when the run failed terminally.

    A retryable failure on the last permitted attempt is treated exactly like a terminal
    one. The queue has nowhere left to put it, and "retryable" describes the vendor, not
    the customer: they are owed the reason and their session back either way. The
    orchestrator has already drawn the FAILED frame for the stage that fell over.
    """
    outcome = await container.pipeline(sink=sink).run(order)
    if not isinstance(outcome, Err):
        return outcome.value
    if outcome.error.is_retryable and not _is_final_attempt(ctx, container.settings):
        raise Retry(defer=_defer_seconds(ctx, container.settings))
    _LOG.error(
        "order failed terminally",
        extra={
            **outcome.error.to_log_dict(),
            "attempt": _attempt(ctx),
            "max_tries": container.settings.queue_max_tries,
            "is_retries_exhausted": outcome.error.is_retryable,
        },
    )
    # Refund BEFORE the customer is told, so that the sentence they read ("you have not
    # lost anything") is already true when it arrives rather than eventually true. _settle
    # never raises, so ordering it first cannot cost them the explanation.
    await _settle(container, order, outcome=SettlementOutcome.FAILED)
    await _tell_the_customer_why(bot, order, key=outcome.error.user_message_key, chat_id=chat_id)
    await _release_session(ctx, bot, order, chat_id=chat_id, reason="failed")
    return {
        "order_id": str(order.id),
        "is_delivered": False,
        "error": outcome.error.error_code,
        "user_message_key": outcome.error.user_message_key,
        "attempts": _attempt(ctx),
    }


async def _tell_the_customer_why(bot: Bot, order: Order, *, key: str, chat_id: int) -> None:
    """Say the specific reason the run failed. Never raises.

    The progress frame says only that it failed, which is the same sentence for every
    cause. This is the sentence that differs — and for ``error.content_not_allowed`` it is
    the difference between a customer who reworded the note and one who gave up.
    """
    language = order.brief.ui_language
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=translate(key, language),
            reply_markup=start_over_keyboard(language),
        )
    except TelegramAPIError as exc:
        _LOG.warning(
            "the failure reason could not be delivered",
            extra={
                "order_id": str(order.id),
                "chat_id": chat_id,
                "user_message_key": key,
                "failure": repr(exc),
            },
        )


async def _release_session(
    ctx: Mapping[str, Any], bot: Bot, order: Order, *, chat_id: int, reason: str
) -> None:
    """Un-park the wizard session waiting on this order. Never raises.

    ``handlers.confirm`` leaves the FSM in ``Wizard.submitting`` with the order id in its
    data precisely so the customer can be answered truthfully while the song is made. That
    is only true until the run ends: past that point the same state answers "your song is
    still in the studio" for a song that was delivered minutes ago, and every button the
    wizard draws is refused by ``navigation._refuse_while_running`` — the session becomes
    one the customer cannot use and cannot leave except by knowing to type ``/start``.

    Called on every TERMINAL end — delivered, failed for good, retries exhausted, cancelled
    at the timeout — and never on a retryable failure that is coming back, where the park is
    still telling the truth.

    **It releases only the session that is waiting on THIS order.** ``/start`` and the
    Start-over button deliberately do not refuse while an order is in flight, so by the time
    a run ends the customer may be halfway through a second wizard. Clearing the key blind
    wiped that new session's state and its draft — the customer's next button press landed
    on no state and was answered "that session expired" — and if they had reached Confirm
    again it un-parked the second order too, restoring the exact bug this function exists to
    prevent. So the stored order id is compared first, and anything else is left alone.

    A private chat gives ``chat_id == user_id``; the order's own ``telegram_user_id`` is
    used for the user half regardless, because that is the id the bot process keyed the
    state with and the one that stays right if a group chat ever reaches this path.
    """
    storage = ctx.get(STORAGE_CTX_KEY)
    if not isinstance(storage, BaseStorage):
        _LOG.warning(
            "no FSM storage in the worker context; the session stays parked",
            extra={"order_id": str(order.id), "chat_id": chat_id, "reason": reason},
        )
        return
    key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=order.telegram_user_id)
    try:
        parked_on = (await storage.get_data(key)).get(ORDER_ID_KEY)
        if parked_on != str(order.id):
            _LOG.info(
                "session is not waiting on this order; leaving it alone",
                extra={
                    "order_id": str(order.id),
                    "parked_on": parked_on if isinstance(parked_on, str) else None,
                    "chat_id": chat_id,
                    "reason": reason,
                },
            )
            return
        await storage.set_state(key, None)
        await storage.set_data(key, {})
    except Exception as exc:
        # Storage is Redis in production. A release that fails must not take down a job
        # whose song has already been delivered.
        _LOG.warning(
            "could not release the wizard session",
            extra={"order_id": str(order.id), "reason": reason, "failure": repr(exc)},
        )
        return
    _LOG.info(
        "wizard session released",
        extra={"order_id": str(order.id), "chat_id": chat_id, "reason": reason},
    )


async def _record_file_id(
    container: AppContainer, *, order_id: UUID, file_id: str | None
) -> None:
    """Store the song's Telegram handle, and never let that failure cost a delivered kit.

    ``deliver_kit`` reports the handle; this writes it down — the same division of labour
    the blocked-customer flag already uses. It runs only on the success path, because a
    handle is minted only by a send that landed.

    Every failure here is swallowed to a log line. The kit is ALREADY in the customer's
    chat by the time this runs, so raising would fail a job that succeeded, and the worst
    case of not writing it is a null column that costs a future re-send some bandwidth —
    which is exactly the state every row has been in since the column was created.
    """
    if file_id is None:
        return
    try:
        updated = await record_song_file_id(
            container.require_session_factory(), order_id=order_id, file_id=file_id
        )
    except SQLAlchemyError:
        _LOG.warning(
            "could not record the song's telegram file_id; the kit was delivered anyway",
            extra={"order_id": str(order_id)},
            exc_info=True,
        )
        return
    if updated == 0:
        _LOG.info(
            "no song asset row to carry the telegram file_id",
            extra={"order_id": str(order_id)},
        )


async def _send_kit(
    bot: Bot,
    order: Order,
    result: PipelineOutcome,
    *,
    ctx: Mapping[str, Any],
    container: AppContainer,
    reporter: ProgressReporter,
    chat_id: int,
) -> bool:
    """Send the finished kit. ``False`` means it was not delivered but must not be retried.

    The DELIVERING frames bracket the send itself. "Done" is emitted *after* the last byte
    lands, never before: a kit that failed to send must not leave a tick on the screen.

    ``DeliveryError`` is retryable by default, so before this took the final attempt into
    account EVERY failed send raised ``Retry`` and the branch below it was dead code: the
    FAILED frame was never drawn, ``error.delivery_failed`` could never render, and a kit
    Telegram refused five times left the progress bar frozen on "Sending it over…" with
    the session still parked. On the last attempt the send failure is terminal, and it is
    said out loud like any other.

    ``container`` rather than ``settings`` alone, because this function now has a second job:
    a send refused because the customer BLOCKED the bot is the only churn source that
    survives a deploy window (``run_polling`` drops every pending ``my_chat_member`` update
    on start), and recording it needs ``container.bot_blocks``. The settings it already used
    for the retry ladder come off the same object, so there is one handle here and not two
    that could disagree.
    """
    settings = container.settings
    await reporter.emit(PipelineStage.DELIVERING, ProgressStatus.STARTED, now=_utc_now())
    delivered = await deliver_kit(
        bot,
        chat_id=chat_id,
        kit=result.kit,
        language=order.brief.ui_language,
        gaps=result.gaps,
    )
    if not isinstance(delivered, Err):
        await _record_file_id(container, order_id=result.kit.order_id, file_id=delivered.value)
        await reporter.emit(PipelineStage.DELIVERING, ProgressStatus.SUCCEEDED, now=_utc_now())
        return True
    # The kit exists and is persisted; only the send failed. Retryable failures get
    # another pass, and the replay short-circuit means that costs a read.
    _LOG.error(
        "kit could not be delivered",
        extra={
            **delivered.error.to_log_dict(),
            "attempt": _attempt(ctx),
            "max_tries": settings.queue_max_tries,
        },
    )
    # BEFORE the Retry, and that ordering is load-bearing: a retryable delivery failure
    # raises out of this function, so a record placed after the branch would never run on any
    # attempt but the last — which is every attempt but one. Recording it changes neither
    # what this function returns nor what it raises; a blocked customer still burns the full
    # retry ladder on an undeliverable kit, which is existing behaviour and deliberately
    # unchanged here (short-circuiting the ladder touches settlement, and settlement's rule
    # that a kit Telegram refused must not be refunded is what stops a customer blocking the
    # bot mid-render for a free song).
    await _record_customer_block(container, order, delivered.error)
    if delivered.error.is_retryable and not _is_final_attempt(ctx, settings):
        raise Retry(defer=_defer_seconds(ctx, settings))
    await reporter.emit(
        PipelineStage.DELIVERING, ProgressStatus.FAILED, now=_utc_now(), error=delivered.error
    )
    await _tell_the_customer_why(bot, order, key=delivered.error.user_message_key, chat_id=chat_id)
    return False


async def _record_customer_block(container: AppContainer, order: Order, error: BayramError) -> None:
    """Write down that this customer blocked the bot, if that is what the refusal said.

    THE SECOND CHURN SOURCE, and it is not redundant with the first. The bot's
    ``my_chat_member`` handler learns a block at the instant it happens — but ``run_polling``
    calls ``delete_webhook(drop_pending_updates=True)`` on every start, so every membership
    update that arrived while the bot was down is discarded permanently and Telegram never
    resends it. This arm is the only source that survives a deploy window. Anyone tempted to
    delete it as duplicated work should read that sentence twice: the transition guard makes
    a duplicate harmless, and removing this makes every block during a restart invisible.

    ``order.telegram_user_id`` and not ``chat_id``. They are the same number for a private
    chat today, but the ACCOUNT is what the ``users`` row and the event row are keyed on, and
    taking it from the order is the version that stays correct if a kit is ever delivered
    somewhere other than the customer's own chat.

    ``Ok(False)`` is the ORDINARY outcome in a healthy deployment — the membership update
    arrived first and the transition guard already claimed it — so it is DEBUG rather than a
    warning. Nothing here changes the caller's return value or its raise.
    """
    if not error.context.get(BLOCKED_BY_CUSTOMER_KEY):
        return
    recorder = container.bot_blocks
    if recorder is None:
        return
    recorded = await recorder.record_bot_blocked(
        order.telegram_user_id, at=_utc_now(), source=BotBlockSource.DELIVERY_REFUSAL
    )
    context = {"order_id": str(order.id), "telegram_user_id": order.telegram_user_id}
    if not is_ok(recorded):
        _LOG.warning(
            "a delivery refusal could not be recorded as a block",
            extra={**context, **recorded.error.to_log_dict()},
        )
        return
    if recorded.value:
        _LOG.info("delivery refusal recorded a customer block", extra=context)
        return
    _LOG.debug("delivery refusal matched a block already recorded", extra=context)


async def generate_and_deliver(
    ctx: Mapping[str, Any],
    order_id: str,
    chat_id: int,
    progress_message_id: int,
) -> dict[str, Any]:
    """Run one order end to end and send the kit. Returns a JSON-safe summary.

    Raises only ``arq.worker.Retry`` (deliberately, to defer a retryable failure),
    ``asyncio.CancelledError`` (the queue's job timeout, re-raised untouched) and
    ``PipelineError`` when the worker was wired up wrong — a startup bug, not a run-time one.
    """
    container = _require(ctx, CONTAINER_CTX_KEY, AppContainer)
    bot = _require(ctx, BOT_CTX_KEY, Bot)

    found = await container.repository.get_order(_order_uuid(order_id))
    if isinstance(found, Err):
        _LOG.error("order not found for job", extra=found.error.to_log_dict())
        return {"order_id": order_id, "is_delivered": False, "error": found.error.error_code}

    order = found.value
    # The sink is built here, per job, because it is aimed at exactly one message — and
    # outside the try, because the cancellation handler needs it to draw the last frame.
    sink = TelegramProgressSink(
        bot,
        chat_id=chat_id,
        message_id=progress_message_id,
        language=order.brief.ui_language,
    )
    # Both scopes, for the same reason and at the same width: every log line and every
    # vendor_usage row this job writes names the order it was for. Bound HERE as well as in
    # the orchestrator because the job does more than run the pipeline — delivery, the
    # settlement legs and the failure paths are all inside it, and a vendor call made on any
    # of them would otherwise land unattributed. The scopes nest harmlessly when the
    # orchestrator binds the same id again.
    with correlation_scope(order.correlation_id), usage_scope(order_id=order.id):
        try:
            return await _run_order(container, bot, order, ctx=ctx, sink=sink, chat_id=chat_id)
        except asyncio.CancelledError:
            _LOG.error(
                "job cancelled; the queue timeout most likely killed the run",
                extra={
                    "order_id": order_id,
                    "chat_id": chat_id,
                    "job_timeout_s": container.settings.queue_job_timeout_s,
                },
            )
            # Deliberately NO _settle call. arq re-runs a cancelled job (retry_jobs
            # defaults True and handle_sig cancels on SIGTERM), and the replay finds the
            # order still paid for and renders it again — refunding here would hand out one
            # free song per deploy. WU6's sweep closes a debit whose job never came back.
            await sink.emit_timed_out(markup=start_over_keyboard(order.brief.ui_language))
            await _release_session(ctx, bot, order, chat_id=chat_id, reason="timed_out")
            raise


async def _run_order(
    container: AppContainer,
    bot: Bot,
    order: Order,
    *,
    ctx: Mapping[str, Any],
    sink: TelegramProgressSink,
    chat_id: int,
) -> dict[str, Any]:
    """Generate, then deliver. The summary ARQ stores is built from what actually happened."""
    outcome = await _run_pipeline(container, bot, order, ctx=ctx, sink=sink, chat_id=chat_id)
    if isinstance(outcome, dict):
        return outcome

    is_delivered = await _send_kit(
        bot,
        order,
        outcome,
        ctx=ctx,
        container=container,
        reporter=_delivery_reporter(sink, order, settings=container.settings),
        chat_id=chat_id,
    )
    # Settled on BOTH outcomes, and CONSUMED on both — see _settle for why a kit Telegram
    # refused must not be refunded. This is reached only once _send_kit has stopped asking
    # for a retry, so a send that is coming back around raises past here and settles nothing.
    await _settle(
        container,
        order,
        outcome=SettlementOutcome.DELIVERED if is_delivered else SettlementOutcome.NOT_DELIVERED,
    )
    # Released on BOTH outcomes. A non-retryable send failure is as terminal as a delivery:
    # the customer has been told, and leaving the session parked would answer their next
    # message with "still in the studio" about a run that has stopped.
    await _release_session(
        ctx, bot, order, chat_id=chat_id, reason="delivered" if is_delivered else "not_delivered"
    )
    return {
        "order_id": str(order.id),
        "is_delivered": is_delivered,
        "gaps": len(outcome.gaps),
        "total_duration_ms": outcome.total_duration_ms,
        "total_cost_usd": round(outcome.total_cost_usd, 6),
        "is_name_verified": all(verdict.is_match for verdict in outcome.name_verdicts),
    }


def _delivery_reporter(
    sink: TelegramProgressSink, order: Order, *, settings: Settings
) -> ProgressReporter:
    """A reporter for the send window, measured against the same plan the pipeline used.

    The stage plan has to match the orchestrator's or the last two frames would be scored
    against a different denominator than the forty before them.
    """
    return ProgressReporter(
        sink,
        order_id=order.id,
        correlation_id=order.correlation_id,
        stage_plan=scheduled_stages(has_greetings=settings.greetings_per_kit > 0),
    )


def build_kit_worker_settings(
    *,
    settings: Settings,
    build_dependencies: Callable[[], Awaitable[Mapping[str, Any]]],
    shutdown: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
) -> type[Any]:
    """ARQ's ``WorkerSettings`` for this project, hosting the one job.

    ``build_dependencies`` is awaited once at startup, so no pool is opened at import time
    and ``python -m bayram.worker`` stays importable in a test.
    """

    async def startup(ctx: dict[str, Any]) -> None:
        ctx.update(await build_dependencies())
        _LOG.info(
            "worker started",
            extra={"concurrency": settings.worker_concurrency, "job": KIT_JOB_NAME},
        )

    async def teardown(ctx: dict[str, Any]) -> None:
        if shutdown is not None:
            await shutdown(ctx)

    class WorkerSettings:
        # Every job this process can run, named here as well as scheduled below: ARQ finds
        # ``WorkerSettings`` at import and dispatches by FUNCTION NAME, so a cron entry whose
        # function is absent from this list is a schedule with nothing behind it.
        functions = [
            generate_and_deliver,
            run_retention_sweep,
            poll_vendor_balances,
            record_activity_snapshot,
            # THE SETTLED-PAYMENT NOTIFICATION. Wrapped in ``func`` rather than listed bare
            # for the ``max_tries``: this is the only job here whose enqueue side is another
            # PROCESS — the Payme gateway, which holds the cashbox key and no Telegram token
            # — and its retry ladder is therefore not the queue-wide one. Five attempts, five
            # seconds apart and growing, sized for a Telegram hiccup rather than for a vendor
            # rate limit, because the money is already ours and the customer is waiting. The
            # NAME is stated explicitly instead of being taken from ``__qualname__``: the
            # gateway enqueues by that string across a process boundary, and letting a
            # rename silently change it would stop notifications without failing any build.
            #
            # ``timeout`` is ``queue_job_timeout_s`` and not a knob of its own: the job makes
            # one Telegram call and two short reads, and the only thing it can hang on is the
            # database the kit job already shares that ceiling with.
            func(
                notify_payment_settled,
                name=PAYME_NOTIFY_JOB_NAME,
                max_tries=PAYME_NOTIFY_MAX_TRIES,
                timeout=settings.queue_job_timeout_s,
            ),
            # The sweep, registered as well as scheduled below. ARQ dispatches by NAME, so a
            # cron entry whose function is absent from this list is a schedule with nothing
            # behind it — and this one is also enqueued by hand by ``python -m bayram.payme.cli
            # reconcile``, which is a second caller that needs the name to resolve.
            run_payme_sweep,
            # THE THREE BROADCAST JOBS. Their enqueue side is the ADMIN PANEL — the second
            # process after the Payme gateway whose jobs run here — so all three names are
            # stated explicitly rather than taken from ``__qualname__``: ``bayram.admin.queue``
            # restates the same strings (it must not import this module, which would drag a
            # ``Bot`` into a process denied a token), and a rename that compiled on both
            # sides would silently stop every campaign without failing a build.
            #
            # ``max_tries=1`` on all three, and it is the same argument the crons make: the
            # retry is not a ladder, it is the successor chunk and the five-minutely due
            # sweep below. A ladder here would re-enter a job whose rows are already claimed
            # — every one of which is settled or released before the job returns — and buy
            # nothing that the sweep does not already provide from a cleaner state.
            #
            # ``timeout`` is ``broadcast_chunk_timeout_s`` and DELIBERATELY NOT
            # ``queue_job_timeout_s``: 900 seconds is sized for a music render, and a
            # campaign is 250 chunks. A chunk holding one of fifteen slots for a quarter of
            # an hour would starve the paying customer behind it, 250 times over. The
            # cancellation that timeout produces is not free either — it leaves claimed rows
            # in ``sending`` for the sweep to retire to ``unknown`` — which is why the number
            # is generous rather than tight.
            func(
                expand_broadcast_audience,
                name=EXPAND_JOB_NAME,
                max_tries=1,
                timeout=settings.broadcast_chunk_timeout_s,
            ),
            func(
                send_broadcast_chunk,
                name=SEND_JOB_NAME,
                max_tries=1,
                timeout=settings.broadcast_chunk_timeout_s,
            ),
            # The test send is one message to one allowlisted operator. ``max_tries=1``
            # matters MORE here than above, not less: a retried test send is a second
            # message to a human who is watching for exactly one.
            func(
                send_broadcast_test,
                name=TEST_SEND_JOB_NAME,
                max_tries=1,
                timeout=settings.broadcast_chunk_timeout_s,
            ),
            # The due sweep, registered as well as scheduled below, for the reason every
            # other cron here is: ARQ dispatches by NAME and a schedule whose function is
            # absent from this list has nothing behind it.
            sweep_due_broadcasts,
            # THE TWO SUPPORT-TICKET JOBS. Their enqueue side is the admin panel too, and
            # their names are stated explicitly for the broadcast trio's reason —
            # ``bayram.admin.queue`` restates the same two strings rather than importing this
            # package, because importing it would put ``aiogram.Bot`` in the import graph of
            # the one process that is structurally forbidden a Telegram token.
            #
            # ``max_tries`` is a DIFFERENT number for each, and both are read back by the job
            # itself: ARQ compares ``job_try > max_tries`` before it re-enters the function,
            # so a ``Retry`` raised on the last permitted attempt is discarded with nobody
            # told, and the constant a job stops raising at must equal the one registered
            # here. Three for the card and five for the reply, because the cost of giving up
            # differs: a stale card is repainted by the next action on that ticket, while an
            # undelivered reply is a customer who thinks they were ignored. Their own modules
            # carry the full argument.
            #
            # ``timeout`` is ``queue_job_timeout_s`` for both, and not a knob of their own:
            # each makes one Telegram call and one or two short reads. The one thing either
            # can sit in for a while is the outbound pacer's park, which is capped at 600
            # seconds — comfortably inside the 900 the kit job already shares that ceiling
            # with, and a job cancelled there has written nothing and is safe to replay.
            func(
                sync_support_card,
                name=SUPPORT_CARD_JOB_NAME,
                max_tries=SUPPORT_CARD_MAX_TRIES,
                timeout=settings.queue_job_timeout_s,
            ),
            func(
                relay_support_reply,
                name=SUPPORT_RELAY_JOB_NAME,
                max_tries=SUPPORT_RELAY_MAX_TRIES,
                timeout=settings.queue_job_timeout_s,
            ),
            # THE SUPPORT GROUP CHECK, and it is the odd one out in this list: it is about a
            # ROOM rather than about a ticket. The panel enqueues it the instant an operator
            # selects a support group, after that selection has COMMITTED — the uncommitted
            # enqueue was a critical defect in this feature only hours ago — and it is the only
            # thing in the system that can answer whether a chat id somebody typed is a real
            # room the bot may post in. Telegram has no "list my groups" API, so a pasted id is
            # the sole route to a group the bot was already sitting in; without this job that
            # route ends in a support inbox that is silently dead.
            #
            # ``max_tries`` is read back by the job for this list's stated reason, and THREE is
            # generous rather than tight: the four verdicts this job exists to produce are all
            # terminal and never touch the ladder at all. The ladder is for Telegram being
            # unreachable or rate-limiting, which is the one case where waiting helps.
            #
            # ``timeout`` is ``queue_job_timeout_s`` for the two above's reason — one ``getChat``,
            # one ``sendMessage`` and two short writes, with the group pacer's 600-second park
            # as the only thing it can sit in.
            func(
                verify_support_group,
                name=SUPPORT_VERIFY_JOB_NAME,
                max_tries=SUPPORT_VERIFY_MAX_TRIES,
                timeout=settings.queue_job_timeout_s,
            ),
        ]
        # The FIL-7 retention schedule, on a clock at last. Hourly rather than nightly for
        # two reasons: every sweep is bounded by ``batch_size``, so a backlog is worked off
        # in hourly bites instead of one lock-taking nightly run, and an hourly cadence
        # means a missed window costs an hour of latency on a legal obligation rather than
        # a day. ``max_tries=1`` because a failed sweep must not be retried into a second
        # concurrent purge — the next hour is the retry, and the failed run is on the
        # ``purge_runs`` row either way. ``unique=True`` (arq's default, stated here because
        # it is load-bearing) keeps a multi-worker deployment to ONE sweep per window.
        #
        # This entry carries a SECOND sweep that is not a retention clock: ``purge_expired``
        # also runs ``bayram.db.credits.settle_stale_debits``, which closes debits whose job
        # never came back to settle them — :func:`_settle` runs inside the job, so it cannot
        # close its own. That composes into the purge's transaction rather than taking a
        # cron of its own because it needs exactly what this one already provides, a bounded
        # transaction on a schedule, and a second hourly entry over the same database would
        # be two locks where one will do.
        cron_jobs = [
            cron(
                run_retention_sweep,
                name=RETENTION_JOB_NAME,
                minute=RETENTION_CRON_MINUTE,
                run_at_startup=False,
                unique=True,
                max_tries=1,
                timeout=settings.queue_job_timeout_s,
            ),
            # THE VENDOR BALANCE POLL. Hourly, because a balance moves at the pace of spend
            # and the alert thresholds are in DAYS of cover, so an hour of staleness cannot
            # change a decision — and the row carries ``fetched_at``, so its age is never
            # hidden. Daily was rejected: the SEV-1 condition is a capability's last healthy
            # provider hitting zero, and a day-old zero is a day of failed customer orders.
            #
            # ``timeout`` is ``vendor_balance_job_timeout_s`` and DELIBERATELY NOT
            # ``queue_job_timeout_s`` like every other entry here: 900 seconds is sized for a
            # music render, and a cron holding a worker slot for fifteen minutes over a hung
            # probe would starve the job a paying customer is waiting on, hourly, forever.
            #
            # ``max_tries=1``: the next hour IS the retry. The failure is on the
            # ``vendor_balances`` row either way, with its error code and an incremented
            # ``consecutive_failures``, and a retry ladder against a rate-limited vendor
            # endpoint is how a soft 429 becomes a hard block.
            #
            # ``run_at_startup=False``, and the alternative was considered. A worker
            # cold-started at 12:05 shows "not polled" for 38 minutes, which the tile renders
            # honestly. ``run_at_startup=True`` would close that gap and would fire once PER
            # REPLICA — arq's ``unique`` key derives from the cron WINDOW and a startup
            # invocation is in none — so a three-replica rolling deploy would make three
            # authenticated probes at once. A one-hour cold-start gap on a cached number is
            # cheaper than a rate-limit ban on the credential the pipeline depends on. Anyone
            # flipping this to True must bring their own dedupe.
            cron(
                poll_vendor_balances,
                name=VENDOR_BALANCE_JOB_NAME,
                minute=VENDOR_BALANCE_CRON_MINUTE,
                run_at_startup=False,
                unique=True,
                max_tries=1,
                timeout=settings.vendor_balance_job_timeout_s,
            ),
            # THE NIGHTLY ACTIVITY SNAPSHOT. Once a day just after midnight UTC, because the
            # row it writes IS a daily sample and a second one the same day is ignored by
            # ``uq_user_activity_snapshots_snapshot_date`` anyway. ``unique=True`` and
            # ``max_tries=1`` for the retention entry's reasons; the unique constraint makes
            # a duplicate harmless rather than merely unlikely, which is what lets
            # ``max_tries=1`` be safe here — a lost night is a GAP in the series, and a gap
            # is the honest record of a worker that was down. Nothing back-fills it: the
            # ``last_seen_at`` values that would have answered for yesterday no longer exist.
            #
            # ``timeout`` is ``queue_job_timeout_s`` here and not a knob of its own: this job
            # makes no network call at all, so the only thing it can hang on is the database
            # the kit job already shares that ceiling with.
            cron(
                record_activity_snapshot,
                name=ACTIVITY_SNAPSHOT_JOB_NAME,
                hour=ACTIVITY_SNAPSHOT_CRON_HOUR,
                minute=ACTIVITY_SNAPSHOT_CRON_MINUTE,
                run_at_startup=False,
                unique=True,
                max_tries=1,
                timeout=settings.queue_job_timeout_s,
            ),
            # THE PAYME SWEEP. The ONLY entry here that fires more than once an hour, and the
            # cadence is a customer-facing number rather than a technical one: it is the
            # ceiling on how long somebody who paid during a Redis outage waits to be told,
            # because the gateway's post-commit enqueue is best-effort by design (Payme is
            # owed an HTTP 200 whether or not Redis answered). ``BAYRAM_PAYME_SWEEP_MINUTES``
            # sets it; :func:`bayram.runtime.payme_jobs.sweep_minutes` turns "every N" into the
            # minute SET arq wants and clamps nonsense to the default rather than refusing to
            # build ``WorkerSettings``, which is read at IMPORT time and would take the kit
            # job down with it.
            #
            # ``max_tries=1``: the next run — five minutes away, not an hour — IS the retry,
            # which is the vendor poll's argument with a much shorter penalty. Every arm is
            # bounded by its own batch size and every one of them is idempotent, so a run
            # that dies halfway costs nothing but the rows it had not reached yet.
            #
            # ``unique=True`` (arq's default, stated because it is load-bearing) keeps a
            # multi-replica deployment to ONE sweep per window. Note the same caveat the
            # entries above carry: ``unique`` derives from the cron WINDOW, so a rolling
            # deploy that cold-starts N replicas produces no simultaneous runs here only
            # because ``run_at_startup=False`` — a startup invocation belongs to no window
            # and would fire once per replica. Anyone flipping that to True must bring their
            # own dedupe, and here it would mean N concurrent re-enqueues of the same backlog
            # (harmless, because the notification job id is deterministic, but N times the
            # reads for nothing).
            cron(
                run_payme_sweep,
                name=PAYME_SWEEP_JOB_NAME,
                # ``sweep_minutes`` hands back a sorted TUPLE and arq's ``OptionType`` says
                # ``None | int | Set[int]`` — but ``arq.cron._get_next_dt`` dispatches on
                # ``isinstance(v, (set, list, tuple))``, so the annotation is narrower than
                # the behaviour and a tuple is fully supported. The tuple is deliberate: a
                # ``set`` here is unhashable and would break
                # ``test_no_two_crons_in_this_worker_contend_for_the_same_minute``, which
                # collects every entry's ``minute`` to prove no two writers collide.
                minute=sweep_minutes(settings),  # type: ignore[arg-type]
                run_at_startup=False,
                unique=True,
                max_tries=1,
                timeout=settings.queue_job_timeout_s,
            ),
            # THE BROADCAST DUE SWEEP. The second entry here that fires more than once an
            # hour, and it is TWO backstops in one pass because they are one sentence —
            # enqueue what is waiting.
            #
            # It is the SCHEDULED-SEND PATH: the panel deliberately enqueues nothing for a
            # future instant, because a job deferred by three days inside Redis is a promise
            # made by the least durable component in the system, and a campaign an operator
            # scheduled for Monday must go out on Monday whether or not Redis was restarted
            # on Sunday. And it is the CRASH RECOVERY: a chunk job cancelled by a deploy
            # leaves rows claimed and no successor queued, and arq's own retry cannot fix
            # that — ``max_tries=1`` on the chunk means there is no retry, by design.
            #
            # Every campaign it revives has to have STOPPED MOVING first
            # (``broadcasts.updated_at`` older than the sending lease), which is what keeps a
            # sweep running twelve times an hour from giving one healthy campaign twelve
            # parallel chains of chunk jobs.
            #
            # ``:04, :09, …`` rather than ``:00, :05, …``: the Payme sweep already owns the
            # five-minute boundary and ``test_no_two_crons_in_this_worker_contend_for_the_
            # same_minute`` is the assertion that keeps two database writers off one minute.
            #
            # ``max_tries=1`` for the retention entry's reason — the next run five minutes
            # away IS the retry, and a failed sweep must not become two concurrent ones —
            # and ``timeout`` is the chunk timeout rather than ``queue_job_timeout_s``,
            # because this makes one bounded query and at most fifty enqueues and has no
            # business holding a worker slot for fifteen minutes if Redis goes quiet.
            cron(
                sweep_due_broadcasts,
                name=DUE_JOB_NAME,
                minute=BROADCAST_DUE_CRON_MINUTE,  # type: ignore[arg-type]
                run_at_startup=False,
                unique=True,
                max_tries=1,
                timeout=settings.broadcast_chunk_timeout_s,
            ),
        ]
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        max_jobs = settings.worker_concurrency
        job_timeout = settings.queue_job_timeout_s
        keep_result = settings.queue_result_ttl_s
        # Stated rather than left to ARQ's default, because the job reads the same number
        # to decide when a retryable failure has become terminal. Two places holding
        # different values would either abandon a customer one attempt early or park them
        # for good — see ``_is_final_attempt``.
        max_tries = settings.queue_max_tries
        on_startup = staticmethod(startup)
        on_shutdown = staticmethod(teardown)

    return WorkerSettings


assert generate_and_deliver.__name__ == KIT_JOB_NAME, (
    "the enqueue name and the job function have drifted apart; ARQ would never dispatch"
)

assert KIT_JOB_NAME is pipeline_worker.KIT_JOB_NAME, (
    "one spelling, two importers: the re-export above stopped being the same object"
)
