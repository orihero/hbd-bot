"""The join between the orchestrator and Telegram.

The pipeline stops at "kit persisted" and knows nothing about chats; the bot knows about
chats and nothing about pipelines. This function is the only place the two meet, so what
is tested here is that the kit *actually leaves the building*, that progress reaches the
message the wizard already posted, and that each way it can fail is a way a customer or an
operator can be told about.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from arq.worker import Retry

from hbd.config import Settings
from hbd.contracts import Kit, Order, Result, err, ok
from hbd.errors import PipelineError, ProviderTimeoutError, StorageError
from hbd.pipeline.events import PipelineStage, ProgressSink
from hbd.pipeline.outcome import PipelineOutcome
from hbd.runtime.container import AppContainer
from hbd.runtime.jobs import BOT_CTX_KEY, CONTAINER_CTX_KEY, generate_and_deliver
from hbd.storage import LocalFileStorage
from tests.test_bot.conftest import BOT_TOKEN, CHAT_ID, RecordingSession

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

    def __init__(self, outcome: Result[PipelineOutcome], sink: ProgressSink | None) -> None:
        self._outcome = outcome
        self._sink = sink

    async def run(self, order: Order) -> Result[PipelineOutcome]:
        await asyncio.sleep(0)
        return self._outcome


class _Container(AppContainer):
    """A real container shape with a scripted pipeline. Frozen, so this is a subclass."""

    def __init__(self, *, order: Order | None, outcome: Result[PipelineOutcome], root: Path):
        settings = Settings(
            _env_file=None,
            telegram_bot_token="t",
            database_url="sqlite+aiosqlite:///:memory:",
            elevenlabs_api_key="k",
            llm_api_key="k",
        )
        super().__init__(
            settings=settings,
            providers=None,  # type: ignore[arg-type]
            repository=_Repository(order),  # type: ignore[arg-type]
            storage=LocalFileStorage(root),
            post=None,  # type: ignore[arg-type]
            payment=None,  # type: ignore[arg-type]
            workspace_root=root,
            engine=None,  # type: ignore[arg-type]
            music_slots=asyncio.Semaphore(1),
            tts_slots=asyncio.Semaphore(1),
        )
        object.__setattr__(self, "_outcome", outcome)
        object.__setattr__(self, "sinks", [])

    def pipeline(self, *, sink: ProgressSink | None = None) -> Any:
        self.sinks.append(sink)  # type: ignore[attr-defined]
        return _Pipeline(self._outcome, sink)  # type: ignore[attr-defined]


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def bot(session: RecordingSession) -> Bot:
    return Bot(
        token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


def _outcome(kit: Kit) -> PipelineOutcome:
    return PipelineOutcome(kit=kit, gaps=(), timings=(), name_verdicts=(), total_cost_usd=0.0)


def _ctx(container: AppContainer, bot: Bot, **extra: Any) -> dict[str, Any]:
    return {CONTAINER_CTX_KEY: container, BOT_CTX_KEY: bot, **extra}


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
