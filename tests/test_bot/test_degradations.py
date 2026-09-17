"""The unhappy paths that must degrade quietly instead of failing loudly.

Every ``BotDeps`` built here carries a ``FakeProfiles`` because this module imports the
walkers, and the walkers now drive the real onboarding screens. A dispatcher with no profile
store fails open (C1-5), so ``/start`` goes straight to the menu and the walker's first
language press matches no handler — which would turn every degradation assertion below into
the same "that session expired", the one failure this file is least able to tell apart from a
real degradation. ``test_walker_preconditions.py`` checks that statically.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import Audio, Chat, Message

from bayram.bot import i18n
from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import NavAction, NavCB
from bayram.bot.delivery import DeliveryLedger, deliver_kit, order_reference
from bayram.bot.deps import BotDeps
from bayram.bot.i18n import translate
from bayram.bot.progress import render_progress
from bayram.bot.states import WIZARD_ORDER, Wizard, WizardStep, next_step, step_for_state
from bayram.config import Settings
from bayram.contracts import AssetKind, Err, Kit, Language, Result, err
from bayram.errors import ErrorCode, PaymentError
from bayram.pipeline.events import PipelineStage, ProgressStatus
from bayram.pipeline.outcome import PipelineGap
from tests.conftest import make_asset
from tests.test_bot.conftest import (
    CHAT_ID,
    FIXED_MOMENT,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
)
from tests.test_bot.test_progress import event
from tests.test_bot.test_wizard_flow import press, send, walk_to_confirm, walk_to_name


class FailingPaymentProvider:
    """Authorisation that errors rather than declines. A different branch entirely."""

    name = "failing"

    async def authorize(
        self, *, order_id: Any, amount_minor: int, currency: str, telegram_user_id: int
    ) -> Result[Any]:
        return err(PaymentError("the rail is down", context={"order_id": str(order_id)}))


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------
def test_a_missing_placeholder_renders_visibly_instead_of_raising() -> None:
    # Arrange / Act — the template wants {limit}; it is handed something else
    text = translate("wizard.note.too_long", Language.EN, unrelated="x")

    # Assert
    assert "{limit}" in text


def test_a_broken_template_falls_back_to_the_raw_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — a translator typo that no schema can catch
    monkeypatch.setattr(i18n, "_resolve_template", lambda key, language: "{name!z}")

    # Act
    text = i18n.translate("any.key", Language.EN, name="Aziza")

    # Assert — a copy bug must never take down a delivery
    assert text == "{name!z}"


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------
def test_a_degraded_stage_is_marked_as_best_effort() -> None:
    # Arrange / Act
    text = render_progress(
        event(PipelineStage.VERIFYING_NAME, ProgressStatus.DEGRADED), Language.EN
    )

    # Assert
    assert translate("progress.degraded_suffix", Language.EN) in text


# ---------------------------------------------------------------------------
# states
# ---------------------------------------------------------------------------
def test_next_step_walks_the_declared_order() -> None:
    # Arrange / Act / Assert
    for earlier, later in pairwise(WIZARD_ORDER):
        assert next_step(earlier) is later
    assert next_step(WIZARD_ORDER[-1]) is None


def test_step_for_state_ignores_a_state_that_is_not_a_wizard_step() -> None:
    # Arrange / Act / Assert
    assert step_for_state(None) is None
    assert step_for_state("SomeOtherGroup:whatever") is None
    assert step_for_state(Wizard.name.state) is WizardStep.NAME


# ---------------------------------------------------------------------------
# screens over Telegram
# ---------------------------------------------------------------------------
async def test_a_screen_that_cannot_be_edited_is_sent_as_a_new_message(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=RecordingSubmitter(),
            content=RecordingContentWriter(),
            profiles=FakeProfiles(),
        ),
        storage=MemoryStorage(),
    )
    await send(dispatcher, bot, "/start")
    session.failures["EditMessageText"] = TelegramBadRequest(
        method=EditMessageText(chat_id=CHAT_ID, message_id=1, text="x"),
        message="message is not modified",
    )

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Assert — the user still sees the screen
    assert session.named("SendMessage")


# ---------------------------------------------------------------------------
# delivery
# ---------------------------------------------------------------------------
async def test_a_greeting_with_no_file_is_reported(bot: Bot, kit: Kit, tmp_path: Path) -> None:
    # Arrange
    ghost = make_asset(
        tmp_path,
        path=tmp_path / "ghost.ogg",
        kind=AssetKind.GREETING,
        mime="audio/ogg",
        duration_s=20.0,
        persona_id="ghost",
    )
    ghost.path.unlink()
    broken = kit.model_copy(update={"greetings": (ghost,)})

    # Act
    result = await deliver_kit(bot, chat_id=CHAT_ID, kit=broken, language=Language.EN)

    # Assert
    assert isinstance(result, Err)
    assert "greeting:missing-file" in str(result.error.context["failures"])


async def test_a_lyric_sheet_that_cannot_be_sent_is_reported(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange
    session.failures["SendMessage"] = TelegramBadRequest(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="chat not found"
    )

    # Act
    result = await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN)

    # Assert
    assert isinstance(result, Err)
    failures = str(result.error.context["failures"])
    assert "lyric_sheet" in failures
    assert "closing" in failures


async def test_a_gap_from_a_stage_nobody_mapped_is_disclosed_without_an_error_string(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """``gap_message_key`` is total: an unmapped stage costs a detail, never the disclosure.

    A gap recorded at PERSISTING is an asset that failed to ARCHIVE — an operator concern
    with nothing a customer can hear, since the file was delivered from local disk either
    way. It must not put ``error.generic`` under a delivered song, and it must not quietly
    turn the closing message back into a clean one.
    """
    # Arrange
    gap = PipelineGap(
        stage=PipelineStage.PERSISTING,
        error_code=ErrorCode.STORAGE_FAILED,
        detail="asset was not archived",
        user_message_key="error.generic",
    )

    # Act
    await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, gaps=(gap,))

    # Assert
    closing = session.named("SendMessage")[-1].text  # type: ignore[attr-defined]
    assert translate("error.generic", Language.EN) not in closing
    assert order_reference(kit.order_id) in closing


async def test_a_ledger_that_forgot_an_order_resends_rather_than_sending_nothing(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """The ledger is process-local and bounded, so eviction is a real state to survive.

    Losing the song is far worse than sending it twice, so an evicted order falls back to
    a duplicate send — never to a silent no-op.
    """
    # Arrange — a ledger with room for exactly one order, then a second order to evict it
    ledger = DeliveryLedger(max_orders=1)
    await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, ledger=ledger)
    other = kit.model_copy(update={"order_id": uuid4()})
    await deliver_kit(bot, chat_id=CHAT_ID, kit=other, language=Language.EN, ledger=ledger)
    session.clear()

    # Act
    result = await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, ledger=ledger)

    # Assert
    assert not isinstance(result, Err)
    assert session.named("SendAudio")


# ---------------------------------------------------------------------------
# payment
# ---------------------------------------------------------------------------
async def test_a_payment_provider_error_is_shown_in_the_user_s_language(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    submitter = RecordingSubmitter()
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=submitter,
            content=RecordingContentWriter(),
            payment=FailingPaymentProvider(),
            profiles=FakeProfiles(),
        ),
        storage=MemoryStorage(),
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    texts = " ".join(call.text or "" for call in session.calls if hasattr(call, "text"))
    assert translate("error.payment_failed", Language.EN) in texts
    assert submitter.submitted == []


async def test_the_wizard_survives_a_second_run_in_the_same_chat(
    settings: Settings, bot: Bot
) -> None:
    # Arrange
    submitter = RecordingSubmitter()
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=submitter,
            content=RecordingContentWriter(),
            profiles=FakeProfiles(),
        ),
        storage=MemoryStorage(),
    )

    # Act
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    await walk_to_name(dispatcher, bot)

    # Assert — one order queued, and the second wizard is running cleanly
    assert len(submitter.submitted) == 1


# ---------------------------------------------------------------------------
# SoW FIL-4: the song's Telegram handle, which was minted on every delivery and
# dropped on the floor until `_send_song` started reading it off the response.
# ---------------------------------------------------------------------------


async def test_the_song_file_id_is_captured_from_the_send_response(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """A delivered song reports the ``file_id`` Telegram minted for it.

    The whole point of the column (SoW FIL-4) is that a re-send costs zero bytes, which is
    only true if the handle was kept. ``deliver_kit`` answering ``ok(None)`` on a successful
    send is precisely the bug: it looks identical to success and silently costs a re-upload.
    """
    # Arrange: a Telegram that answers sendAudio like the real one does — with the audio.
    session.responses["SendAudio"] = Message(
        message_id=4242,
        date=FIXED_MOMENT,
        chat=Chat(id=CHAT_ID, type="private"),
        audio=Audio(
            file_id="AwACAgIAAxkBAAI-the-handle",
            file_unique_id="AgAD-unique",
            duration=int(kit.song.duration_s),
        ),
    )

    # Act
    result = await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN)

    # Assert
    assert not isinstance(result, Err)
    assert result.value == "AwACAgIAAxkBAAI-the-handle"


async def test_a_song_sent_without_an_audio_payload_yields_no_handle(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """A response carrying no ``audio`` is a null column, never an exception.

    The song reached the customer; only the handle is missing. Raising here would fail a
    job that succeeded, and the default ``RecordingSession`` answers exactly this shape —
    so this is also what keeps every other delivery test in this file honest.
    """
    # Act — the default canned Message has no `audio`.
    result = await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN)

    # Assert
    assert not isinstance(result, Err)
    assert result.value is None
