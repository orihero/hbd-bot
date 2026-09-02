"""The job: generate the kit, then deliver it to the chat that asked for it.

``hbd.pipeline.worker.generate_kit`` stops at "kit persisted". Delivery is a Telegram
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

It also assembles ``WorkerSettings``, which is where the SECOND job lives: the hourly
retention sweep (:mod:`hbd.runtime.retention_job`). Until it was added there, ``functions``
held one entry and ``cron_jobs`` did not exist, so ``purge_expired`` — complete, tested and
legally required — was called by nothing at all. The registration is here rather than in
the sweep's own module because ARQ needs one class naming every job the process can run,
and one place naming them is what keeps the enqueue side and the worker side in step.
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
from arq.worker import Retry

from hbd.bot.delivery import deliver_kit
from hbd.bot.handlers.submitting import ORDER_ID_KEY
from hbd.bot.i18n import translate
from hbd.bot.keyboards import start_over_keyboard
from hbd.bot.progress import TelegramProgressSink
from hbd.config import Settings
from hbd.contracts import Err, Order
from hbd.entitlements import SettlementOutcome
from hbd.errors import PipelineError
from hbd.logging import correlation_scope, get_logger
from hbd.payments import PIPELINE_ACTOR
from hbd.pipeline.events import (
    PipelineStage,
    ProgressReporter,
    ProgressStatus,
    scheduled_stages,
)
from hbd.pipeline.outcome import PipelineOutcome
from hbd.runtime.container import AppContainer
from hbd.runtime.retention_job import (
    RETENTION_CRON_MINUTE,
    RETENTION_JOB_NAME,
    run_retention_sweep,
)

__all__ = [
    "generate_and_deliver",
    "run_retention_sweep",
    "build_kit_worker_settings",
    "KIT_JOB_NAME",
    "RETENTION_JOB_NAME",
    "CONTAINER_CTX_KEY",
    "BOT_CTX_KEY",
    "STORAGE_CTX_KEY",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function name, so the enqueue side and the worker side must agree
#: on this exact string. It is asserted against the function itself at import.
KIT_JOB_NAME: Final[str] = "generate_and_deliver"

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


async def _send_kit(
    bot: Bot,
    order: Order,
    result: PipelineOutcome,
    *,
    ctx: Mapping[str, Any],
    settings: Settings,
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
    """
    await reporter.emit(PipelineStage.DELIVERING, ProgressStatus.STARTED, now=_utc_now())
    delivered = await deliver_kit(
        bot,
        chat_id=chat_id,
        kit=result.kit,
        language=order.brief.ui_language,
        gaps=result.gaps,
    )
    if not isinstance(delivered, Err):
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
    if delivered.error.is_retryable and not _is_final_attempt(ctx, settings):
        raise Retry(defer=_defer_seconds(ctx, settings))
    await reporter.emit(
        PipelineStage.DELIVERING, ProgressStatus.FAILED, now=_utc_now(), error=delivered.error
    )
    await _tell_the_customer_why(bot, order, key=delivered.error.user_message_key, chat_id=chat_id)
    return False


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
    with correlation_scope(order.correlation_id):
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
        settings=container.settings,
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
    and ``python -m hbd.worker`` stays importable in a test.
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
        functions = [generate_and_deliver, run_retention_sweep]
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
        # also runs ``hbd.db.credits.settle_stale_debits``, which closes debits whose job
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
            )
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
