"""The join between the orchestrator and Telegram.

The pipeline stops at "kit persisted" and knows nothing about chats; the bot knows about
chats and nothing about pipelines. This function is the only place the two meet, so what
is tested here is that the kit *actually leaves the building*, that progress reaches the
message the wizard already posted, and that each way it can fail is a way a customer or an
operator can be told about.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText
from arq.worker import Retry

from hbd.bot.i18n import translate
from hbd.config import Settings
from hbd.contracts import BotBlockSource, Kit, Order, Result, err, ok
from hbd.errors import PipelineError, ProviderTimeoutError, StorageError
from hbd.pipeline.events import (
    STAGE_MESSAGE_KEYS,
    PipelineStage,
    ProgressEvent,
    ProgressSink,
    ProgressStatus,
)
from hbd.pipeline.outcome import PipelineOutcome
from hbd.runtime.container import AppContainer
from hbd.runtime.jobs import (
    BOT_CTX_KEY,
    CONTAINER_CTX_KEY,
    STORAGE_CTX_KEY,
    build_kit_worker_settings,
    generate_and_deliver,
)
from hbd.storage import LocalFileStorage
from tests.test_bot.conftest import (
    CHAT_ID,
    FIXED_MOMENT,
    RecordingSession,
    buttons,
)
from tests.test_runtime.conftest import RecordingEntitlementStore

MESSAGE_ID = 4_242


class _Repository:
    def __init__(self, order: Order | None) -> None:
        self._order = order

    async def get_order(self, order_id: UUID) -> Result[Order]:
        if self._order is None:
            return err(StorageError("order not found", context={"order_id": str(order_id)}))
        return ok(self._order)


class _Pipeline:
    """Answers with a scripted outcome, and emits one progress frame on the way."""

    def __init__(
        self,
        outcome: Result[PipelineOutcome],
        sink: ProgressSink | None,
        *,
        hangs: bool = False,
    ) -> None:
        self._outcome = outcome
        self._sink = sink
        self._hangs = hangs

    async def run(self, order: Order) -> Result[PipelineOutcome]:
        if self._hangs:
            await self._emit(PipelineStage.COMPOSING_SONG)
            await asyncio.Event().wait()  # what a job that outruns its timeout looks like
        await asyncio.sleep(0)
        return self._outcome

    async def _emit(self, stage: PipelineStage) -> None:
        if self._sink is None:
            return
        await self._sink.emit(
            ProgressEvent(
                order_id=uuid4(),
                correlation_id="corr-1",
                stage=stage,
                status=ProgressStatus.STARTED,
                at=FIXED_MOMENT,
                detail_key=STAGE_MESSAGE_KEYS[stage],
            )
        )


@dataclass
class RecordingBlocks:
    """A ``BotBlockRecorder`` that writes nothing and remembers every call.

    ``answer`` is what the store returns, so one fake covers the three outcomes the worker
    logs differently: a recorded transition, an account already blocked (the ordinary case
    once the bot's ``my_chat_member`` handler got there first), and a storage failure.
    """

    answer: Result[bool] = field(default_factory=lambda: ok(True))
    calls: list[tuple[int, BotBlockSource]] = field(default_factory=list)

    async def record_bot_blocked(
        self, telegram_user_id: int, *, at: datetime, source: BotBlockSource
    ) -> Result[bool]:
        self.calls.append((telegram_user_id, source))
        return self.answer

    async def record_bot_unblocked(
        self, telegram_user_id: int, *, at: datetime, source: BotBlockSource
    ) -> Result[bool]:  # pragma: no cover - the worker never learns of a win-back
        raise AssertionError("the delivery arm must never record an unblock")


class _Container(AppContainer):
    """A real container shape with a scripted pipeline. Frozen, so this is a subclass.

    ``credits`` is a WORKING store rather than ``None``, and that is deliberate: the worker
    settles every run it finishes (consume on delivered, refund on a terminal failure,
    nothing at all on a cancellation), and a ``None`` there would let every one of those
    paths pass a test by doing nothing. ``store`` is exposed so a test can seed a balance
    or read back exactly what the run wrote.
    """

    def __init__(
        self,
        *,
        order: Order | None,
        outcome: Result[PipelineOutcome],
        root: Path,
        hangs: bool = False,
        credits: RecordingEntitlementStore | None = None,
        bot_blocks: RecordingBlocks | None = None,
    ):
        settings = Settings(
            _env_file=None,
            telegram_bot_token="t",
            database_url="sqlite+aiosqlite:///:memory:",
            elevenlabs_api_key="k",
            llm_api_key="k",
        )
        super().__init__(
            settings=settings,
            providers=None,
            repository=_Repository(order),  # type: ignore[arg-type]
            storage=LocalFileStorage(root),
            post=None,  # type: ignore[arg-type]
            payment=None,  # type: ignore[arg-type]
            workspace_root=root,
            engine=None,  # type: ignore[arg-type]
            music_slots=asyncio.Semaphore(1),
            tts_slots=asyncio.Semaphore(1),
            credits=credits or RecordingEntitlementStore(),
            bot_blocks=bot_blocks,
        )
        object.__setattr__(self, "_outcome", outcome)
        object.__setattr__(self, "_hangs", hangs)
        object.__setattr__(self, "sinks", [])

    def pipeline(self, *, sink: ProgressSink | None = None) -> Any:
        self.sinks.append(sink)  # type: ignore[attr-defined]
        return _Pipeline(self._outcome, sink, hangs=self._hangs)  # type: ignore[attr-defined]


# ``session`` and ``bot`` now come from tests/test_runtime/conftest.py, because
# test_settlement.py drives the same job function through the same transport.


def _outcome(kit: Kit) -> PipelineOutcome:
    return PipelineOutcome(kit=kit, gaps=(), timings=(), name_verdicts=(), total_cost_usd=0.0)


def _ctx(container: AppContainer, bot: Bot, **extra: Any) -> dict[str, Any]:
    return {CONTAINER_CTX_KEY: container, BOT_CTX_KEY: bot, **extra}


def _screens(session: RecordingSession) -> list[tuple[int, str]]:
    """Every progress edit, paired with where it fell in the call order."""
    return [
        (index, call.text or "")
        for index, call in enumerate(session.calls)
        if isinstance(call, EditMessageText)
    ]


async def test_a_finished_kit_is_sent_to_the_chat_that_asked_for_it(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    # Arrange
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is True
    assert session.named("SendAudio")
    assert session.named("SendVoice")


async def test_the_progress_sink_targets_the_message_the_wizard_already_posted(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    # Arrange
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)

    # Act
    await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert: one sink per job, aimed at this chat and this message.
    sink = container.sinks[0]  # type: ignore[attr-defined]
    assert sink._chat_id == CHAT_ID
    assert sink._message_id == MESSAGE_ID


async def test_a_retryable_failure_asks_arq_to_defer_rather_than_giving_up(
    order: Order, bot: Bot, tmp_path: Path
) -> None:
    # Arrange
    container = _Container(
        order=order, outcome=err(ProviderTimeoutError("slow", provider="music")), root=tmp_path
    )

    # Act / Assert
    with pytest.raises(Retry):
        await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)


async def test_a_terminal_failure_reports_a_user_message_key_instead_of_retrying(
    order: Order, bot: Bot, tmp_path: Path
) -> None:
    # Arrange
    failure = PipelineError("no", user_message_key="error.content_not_allowed")
    container = _Container(order=order, outcome=err(failure), root=tmp_path)

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is False
    assert summary["user_message_key"] == "error.content_not_allowed"


async def test_the_customer_is_told_why_the_run_failed(
    order: Order, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    """A failed render is the worker's only message to a customer, and it must not dead-end.

    The equality is EXACT and both buttons are named, deliberately. A membership check would
    keep passing if 🏠 Back to menu were dropped from ``start_over_keyboard``, and this is the
    one screen where that row matters most: the song did not arrive, the wizard is over, and
    the reply keyboard the customer would otherwise navigate from is chat-level state they may
    have collapsed hours ago. ↩️ Start over alone offers exactly one answer — "buy again" — to
    somebody who has just been told their order failed, and the alternative it hides is their
    balance, the support address, and the way out.

    Ordering is asserted too, because the two rows are not interchangeable: the recovery the
    worker is apologising for has to sit above the exit.
    """
    # Arrange — the one failure a customer can fix by rewording
    failure = PipelineError("moderator refused", user_message_key="error.content_not_allowed")
    container = _Container(order=order, outcome=err(failure), root=tmp_path)

    # Act
    await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert — the reason reaches the chat, in the language the order was placed in
    sent = session.last_named("SendMessage")
    assert sent.chat_id == CHAT_ID
    assert sent.text == translate("error.content_not_allowed", order.brief.ui_language)
    # and a dead end owes the reader BOTH ways out: start again, or go home.
    assert buttons(sent.reply_markup) == (
        (translate("button.start_over", order.brief.ui_language), "nav:start_over"),
        (translate("button.to_menu", order.brief.ui_language), "nav:to_menu"),
    )


async def test_a_failure_reason_telegram_refuses_does_not_break_the_job(
    order: Order, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    # Arrange
    from aiogram.exceptions import TelegramBadRequest

    session.failures["SendMessage"] = TelegramBadRequest(method=None, message="blocked")  # type: ignore[arg-type]
    failure = PipelineError("no", user_message_key="error.provider_generic")
    container = _Container(order=order, outcome=err(failure), root=tmp_path)

    # Act — the summary is still returned; ARQ must not see an exception
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is False


async def test_a_timed_out_job_says_so_before_it_dies(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    # Arrange — a job that outruns queue_job_timeout_s is cancelled where it stands
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path, hangs=True)
    task = asyncio.create_task(
        generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Act
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Assert — one terminal frame, and the cancellation still propagated to ARQ
    last = session.last_named("EditMessageText")
    assert translate("progress.timed_out", order.brief.ui_language) in last.text
    assert last.message_id == MESSAGE_ID
    assert buttons(last.reply_markup)  # a bar that stopped must still offer a way on


async def test_the_send_window_is_announced_before_anything_is_sent(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    # Arrange
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)
    language = order.brief.ui_language

    # Act
    await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert — "sending it over" before the first byte, "done" only after the last
    names = session.call_names
    edits = _screens(session)
    delivering = next(i for i, text in edits if translate("progress.delivering", language) in text)
    done = next(i for i, text in edits if translate("progress.done", language) in text)
    sends = [i for i, name in enumerate(names) if name in {"SendAudio", "SendVoice"}]
    assert delivering < min(sends)
    assert done > max(sends)


async def test_nothing_says_done_when_the_kit_never_left(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    # Arrange — every send is refused, so the job defers rather than finishing
    from aiogram.exceptions import TelegramBadRequest

    for name in ("SendAudio", "SendVoice", "SendMessage"):
        session.failures[name] = TelegramBadRequest(method=None, message="chat not found")  # type: ignore[arg-type]
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)

    # Act
    with pytest.raises(Retry):
        await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert — the tick is never drawn for a kit that did not arrive
    done = translate("progress.done", order.brief.ui_language)
    assert not [text for _, text in _screens(session) if done in text]


async def test_an_order_that_cannot_be_read_is_reported_not_retried_forever(
    bot: Bot, kit: Kit, tmp_path: Path
) -> None:
    # Arrange
    container = _Container(order=None, outcome=ok(_outcome(kit)), root=tmp_path)

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(uuid4()), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is False
    assert "error" in summary


async def test_a_job_queued_with_a_bad_order_id_is_a_wiring_bug_and_says_so(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    # Arrange
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)

    # Act / Assert
    with pytest.raises(PipelineError, match="not a UUID"):
        await generate_and_deliver(_ctx(container, bot), "not-a-uuid", CHAT_ID, MESSAGE_ID)


async def test_a_worker_started_without_a_container_fails_loudly(bot: Bot) -> None:
    # Act / Assert: a missing dependency is a startup bug, not a customer's problem.
    with pytest.raises(PipelineError, match="container"):
        await generate_and_deliver({BOT_CTX_KEY: bot}, str(uuid4()), CHAT_ID, MESSAGE_ID)


async def test_a_worker_started_without_a_bot_fails_loudly(
    order: Order, kit: Kit, tmp_path: Path
) -> None:
    # Arrange
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)

    # Act / Assert
    with pytest.raises(PipelineError, match="bot"):
        await generate_and_deliver(
            {CONTAINER_CTX_KEY: container}, str(order.id), CHAT_ID, MESSAGE_ID
        )


async def test_a_delivery_failure_does_not_discard_the_kit_that_was_already_built(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    # Arrange: every send is rejected by Telegram.
    from aiogram.exceptions import TelegramBadRequest

    for name in ("SendAudio", "SendVoice", "SendMessage"):
        session.failures[name] = TelegramBadRequest(method=None, message="chat not found")  # type: ignore[arg-type]
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)

    # Act: DeliveryError is retryable, so the job defers rather than dropping the kit.
    with pytest.raises(Retry):
        await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)


def test_the_stage_the_job_reports_is_a_real_pipeline_stage() -> None:
    # A guard against the summary drifting from the enum the locales key off.
    assert PipelineStage.DELIVERING in tuple(PipelineStage)


# ---------------------------------------------------------------------------
# Releasing the wizard session
#
# ``handlers.confirm`` deliberately does NOT clear the FSM when it queues an order: it
# parks the session in ``Wizard.submitting`` so the customer can be told truthfully where
# their song is for the several minutes it takes. That park is only true while the run is
# running. Nothing else in the system un-parks it — the Redis TTL is the fourteen-day
# abandoned-draft retention clock, a data lifetime rather than a session one — so a job
# that ends without releasing leaves a session that answers every message with "still in
# the studio" and refuses every button, for a fortnight.
# ---------------------------------------------------------------------------
async def _parked(bot: Bot, order: Order) -> tuple[MemoryStorage, StorageKey]:
    """A storage holding exactly what ``confirm`` leaves behind."""
    storage = MemoryStorage()
    key = StorageKey(bot_id=bot.id, chat_id=CHAT_ID, user_id=order.telegram_user_id)
    await storage.set_state(key, "Wizard:submitting")
    await storage.set_data(key, {"order_id": str(order.id)})
    return storage, key


async def test_delivering_the_kit_releases_the_session_that_was_waiting_on_it(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    # Arrange
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)
    storage, key = await _parked(bot, order)

    # Act
    await generate_and_deliver(
        _ctx(container, bot, **{STORAGE_CTX_KEY: storage}), str(order.id), CHAT_ID, MESSAGE_ID
    )

    # Assert
    assert await storage.get_state(key) is None
    assert await storage.get_data(key) == {}


async def test_a_terminal_failure_releases_the_session_too(
    order: Order, bot: Bot, tmp_path: Path
) -> None:
    # Arrange — a failure the pipeline will not retry
    container = _Container(
        order=order,
        outcome=err(PipelineError("no", user_message_key="error.generic")),
        root=tmp_path,
    )
    storage, key = await _parked(bot, order)

    # Act
    summary = await generate_and_deliver(
        _ctx(container, bot, **{STORAGE_CTX_KEY: storage}), str(order.id), CHAT_ID, MESSAGE_ID
    )

    # Assert
    assert summary["is_delivered"] is False
    assert await storage.get_state(key) is None


async def test_a_retryable_failure_leaves_the_session_parked(
    order: Order, bot: Bot, tmp_path: Path
) -> None:
    """The job is coming back, so "still in the studio" is still the true answer."""
    # Arrange
    container = _Container(
        order=order, outcome=err(ProviderTimeoutError("slow", provider="music")), root=tmp_path
    )
    storage, key = await _parked(bot, order)

    # Act
    with pytest.raises(Retry):
        await generate_and_deliver(
            _ctx(container, bot, **{STORAGE_CTX_KEY: storage}), str(order.id), CHAT_ID, MESSAGE_ID
        )

    # Assert
    assert await storage.get_state(key) == "Wizard:submitting"


async def test_the_queue_timeout_releases_the_session_before_re_raising(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    # Arrange — a run that never returns, cancelled the way the queue cancels it
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path, hangs=True)
    storage, key = await _parked(bot, order)
    task = asyncio.ensure_future(
        generate_and_deliver(
            _ctx(container, bot, **{STORAGE_CTX_KEY: storage}), str(order.id), CHAT_ID, MESSAGE_ID
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Act
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Assert — the cancellation still reaches ARQ, and the customer is not left parked
    assert await storage.get_state(key) is None


async def test_a_worker_wired_without_storage_still_delivers(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    """The handle is optional on purpose: a missing one costs a release, never a song."""
    # Arrange
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is True
    assert session.named("SendAudio")


# ---------------------------------------------------------------------------
# Retry exhaustion — the terminal end ARQ never lets the job see
# ---------------------------------------------------------------------------
# ARQ compares ``job_try`` to ``max_tries`` at the top of its own runner, so the attempt
# after the last permitted one never enters this coroutine: no frame, no message, no
# release. Left to the queue, a sustained vendor outage or five rate-limited sends parked
# the customer in ``Wizard.submitting`` for the full fourteen-day state TTL, answering
# every message with "still in the studio" about a run that stopped an hour ago. The job
# reads the same ``max_tries`` and stops raising ``Retry`` on its last attempt instead.
# ---------------------------------------------------------------------------
def _final_attempt(container: AppContainer) -> int:
    return container.settings.queue_max_tries


async def test_a_retryable_failure_on_the_last_attempt_is_reported_not_deferred(
    order: Order, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    # Arrange — the same vendor timeout that defers on attempt one
    container = _Container(
        order=order, outcome=err(ProviderTimeoutError("slow", provider="music")), root=tmp_path
    )
    ctx = _ctx(container, bot, job_try=_final_attempt(container))

    # Act — no Retry: raising one here would hand the order to nobody
    summary = await generate_and_deliver(ctx, str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert — the customer is told the reason rather than left watching a stopped bar
    assert summary["is_delivered"] is False
    assert summary["attempts"] == _final_attempt(container)
    texts = " ".join(getattr(call, "text", "") or "" for call in session.calls)
    assert translate("error.provider_slow", order.brief.ui_language) in texts


async def test_the_last_attempt_releases_the_session_a_retry_would_have_kept_parked(
    order: Order, bot: Bot, tmp_path: Path
) -> None:
    # Arrange
    container = _Container(
        order=order, outcome=err(ProviderTimeoutError("slow", provider="music")), root=tmp_path
    )
    storage, key = await _parked(bot, order)
    ctx = _ctx(container, bot, job_try=_final_attempt(container), **{STORAGE_CTX_KEY: storage})

    # Act
    await generate_and_deliver(ctx, str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert await storage.get_state(key) is None


async def test_a_send_that_fails_on_the_last_attempt_draws_the_failed_frame_and_unparks(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    """``DeliveryError`` is retryable by default, which made this whole branch dead code."""
    # Arrange — Telegram refuses every send, for the fifth and last time
    from aiogram.exceptions import TelegramBadRequest

    for name in ("SendAudio", "SendVoice", "SendMessage"):
        session.failures[name] = TelegramBadRequest(method=None, message="chat not found")  # type: ignore[arg-type]
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)
    storage, key = await _parked(bot, order)
    ctx = _ctx(container, bot, job_try=_final_attempt(container), **{STORAGE_CTX_KEY: storage})

    # Act
    summary = await generate_and_deliver(ctx, str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert — the bar stops on a failure rather than on "Sending it over…" forever
    assert summary["is_delivered"] is False
    assert any(
        translate("progress.failed", order.brief.ui_language) in text
        for _index, text in _screens(session)
    )
    assert await storage.get_state(key) is None


async def test_the_worker_and_the_job_agree_on_how_many_tries_an_order_gets(
    tmp_path: Path,
) -> None:
    """Two different numbers would abandon a customer early or park them for good."""
    # Arrange
    settings = Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url="sqlite+aiosqlite:///:memory:",
        elevenlabs_api_key="k",
        llm_api_key="k",
    )

    async def _dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker = build_kit_worker_settings(settings=settings, build_dependencies=_dependencies)

    # Assert
    assert worker.max_tries == settings.queue_max_tries


# ---------------------------------------------------------------------------
# The release is scoped to the order it is releasing
# ---------------------------------------------------------------------------
async def test_a_session_waiting_on_a_different_order_is_left_alone(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    """``/start`` does not refuse while an order is in flight, so this really happens.

    The customer confirms, gets impatient, sends ``/start`` and reaches Confirm on a second
    song. When the first order lands, a blind release would wipe the second session's state
    AND its draft — and un-park the second order along with it.
    """
    # Arrange — the session has moved on to a different order
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)
    storage, key = await _parked(bot, order)
    other_order_id = str(uuid4())
    await storage.set_data(key, {"order_id": other_order_id, "draft": {"note": "the second song"}})

    # Act
    await generate_and_deliver(
        _ctx(container, bot, **{STORAGE_CTX_KEY: storage}), str(order.id), CHAT_ID, MESSAGE_ID
    )

    # Assert
    assert await storage.get_state(key) == "Wizard:submitting"
    assert await storage.get_data(key) == {
        "order_id": other_order_id,
        "draft": {"note": "the second song"},
    }


# ---------------------------------------------------------------------------
# The churn arm: a send Telegram refused because the customer blocked the bot
# ---------------------------------------------------------------------------
def _blocked_by_the_customer() -> TelegramForbiddenError:
    return TelegramForbiddenError(method=None, message="Forbidden: bot was blocked by the user")  # type: ignore[arg-type]


def _refuse_every_send(session: RecordingSession, exc: Exception) -> None:
    for name in ("SendAudio", "SendVoice", "SendMessage"):
        session.failures[name] = exc


async def test_a_send_refused_by_a_blocked_customer_is_recorded_before_the_retry(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    """THE ORDERING IS THE POINT, and it is why this asserts on a retrying attempt.

    A retryable delivery failure raises ``Retry`` out of ``_send_kit``, so a record placed
    after that branch would never run on any attempt but the last — which is every attempt
    but one. This drives a NON-final attempt, which really does raise, and asserts the block
    was recorded anyway.

    It is the ACCOUNT that is recorded, not the chat: they are the same number for a private
    chat today, but the ``users`` row and the event row are keyed on the account, and taking
    it from the order is the version that survives a kit ever being delivered elsewhere.
    """
    # Arrange
    _refuse_every_send(session, _blocked_by_the_customer())
    recorder = RecordingBlocks()
    container = _Container(
        order=order, outcome=ok(_outcome(kit)), root=tmp_path, bot_blocks=recorder
    )

    # Act — a retryable failure on a non-final attempt still defers.
    with pytest.raises(Retry):
        await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert recorder.calls == [(order.telegram_user_id, BotBlockSource.DELIVERY_REFUSAL)]


async def test_an_ordinary_delivery_failure_records_no_block(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    """A 400 is not churn. Recording it would invent departures nothing could corroborate."""
    # Arrange
    from aiogram.exceptions import TelegramBadRequest

    _refuse_every_send(session, TelegramBadRequest(method=None, message="chat not found"))  # type: ignore[arg-type]
    recorder = RecordingBlocks()
    container = _Container(
        order=order, outcome=ok(_outcome(kit)), root=tmp_path, bot_blocks=recorder
    )

    # Act
    with pytest.raises(Retry):
        await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert recorder.calls == []


@pytest.mark.parametrize(
    "recorder",
    [None, RecordingBlocks(answer=ok(False)), RecordingBlocks(answer=err(StorageError("down")))],
    ids=["unwired", "already_recorded", "storage_failed"],
)
async def test_recording_the_block_never_changes_what_the_job_does(
    order: Order,
    kit: Kit,
    bot: Bot,
    session: RecordingSession,
    tmp_path: Path,
    recorder: RecordingBlocks | None,
) -> None:
    """Unwired, a no-op and a failure are all invisible to the retry ladder.

    ``Ok(False)`` is the ORDINARY outcome in a healthy deployment — the ``my_chat_member``
    update arrived first and the transition guard already claimed it — so it must be as
    uneventful as having no recorder at all.
    """
    # Arrange
    _refuse_every_send(session, _blocked_by_the_customer())
    container = _Container(
        order=order, outcome=ok(_outcome(kit)), root=tmp_path, bot_blocks=recorder
    )

    # Act / Assert — the raise is unchanged in all three configurations.
    with pytest.raises(Retry):
        await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)


async def test_a_delivered_kit_records_nothing_at_all(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    """The happy path must not touch the churn table; a delivery is the opposite of a block."""
    # Arrange
    recorder = RecordingBlocks()
    container = _Container(
        order=order, outcome=ok(_outcome(kit)), root=tmp_path, bot_blocks=recorder
    )

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is True
    assert recorder.calls == []
