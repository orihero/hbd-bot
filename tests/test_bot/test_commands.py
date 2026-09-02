"""The standing commands, and the two defects that made them urgent.

The wizard collects a third party's name and private facts about them. Two things were
missing and both are asserted here: the disclosure itself (``/privacy``, rendered from the
retention policy so it cannot drift), and the guarantee that a command typed at the note
step is obeyed rather than stored as the fact we know about the recipient and sung.

The four handlers are exercised directly, bound to a real bot. That is deliberate: what
this module owns is the answer each command gives, and the one thing it does NOT own —
that the router is included before the free-text steps — is asserted once, where the router
tree is built, in ``test_app.py``.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from hbd.bot.app import publish_commands
from hbd.bot.callbacks import (
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    OccasionCB,
    VocalGenderCB,
)
from hbd.bot.deps import BotDeps
from hbd.bot.draft import load_draft
from hbd.bot.handlers.commands import (
    BOT_COMMANDS,
    handle_forget,
    handle_help,
    handle_privacy,
    handle_support,
)
from hbd.bot.handlers.submitting import ORDER_ID_KEY
from hbd.bot.i18n import FALLBACK_LANGUAGE, translate
from hbd.bot.states import Wizard
from hbd.config import Settings
from hbd.contracts import Genre, Language, Occasion, Result, VoiceGender, err, is_ok
from hbd.db.retention import DEFAULT_RETENTION_POLICY
from hbd.errors import StorageError
from tests.test_bot.conftest import (
    USER_ID,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    make_message,
)
from tests.test_bot.test_credit_gate import FakeEntitlements
from tests.test_bot.test_wizard_flow import (
    UZBEK_TYPED,
    press,
    send,
    walk_to_confirm,
    walk_to_name,
)

SUPPORT_CONTACT = "@hbd_support"

#: The bullet the privacy notice puts in front of the credit record. A marker rather than a
#: phrase: the four dated clocks each have one, and this is the fifth.
CREDIT_RECORD_MARKER = "🧾"


async def walk_to_note(dispatcher: Dispatcher, bot: Bot) -> None:
    """/start through to the note prompt, in English — the free-text step under test."""
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(dispatcher, bot, OccasionCB(value=Occasion.BIRTHDAY).pack())
    await press(dispatcher, bot, GenreCB(value=Genre.UZBEK_POP).pack())
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.FEMALE).pack())


async def read_note(state: FSMContext) -> str:
    """The note currently in the draft. Empty until the step is answered."""
    result = load_draft(await state.get_data())
    assert is_ok(result), "the draft should still be readable"
    return result.value.note


def bound_message(text: str, bot: Bot) -> Message:
    """A message the handler can reply through, bound the way a router binds it."""
    return make_message(text).as_(bot)


def deps_with_contact(settings: Settings, contact: str) -> BotDeps:
    return BotDeps(
        settings=settings.model_copy(update={"support_contact": contact}),
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
    )


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------
async def test_help_answers_a_chat_that_has_no_session(
    bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange / Act — a cold chat, no /start ever sent
    await handle_help(bound_message("/help", bot), state)

    # Assert
    assert session.last_screen.text == translate("help.text", Language.UZ_LATN)


async def test_help_answers_in_the_chosen_interface_language(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)
    session.clear()

    # Act
    await handle_help(bound_message("/help", bot), state)

    # Assert
    assert session.last_screen.text == translate("help.text", Language.EN)


# ---------------------------------------------------------------------------
# /privacy
# ---------------------------------------------------------------------------
async def test_privacy_states_the_periods_the_purge_job_actually_runs_on(
    bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """A notice that disagrees with the code is worse than no notice.

    The four periods are interpolated from ``DEFAULT_RETENTION_POLICY`` at call time, so
    this fails the moment somebody shortens one without revisiting the copy.
    """
    # Arrange / Act
    await handle_privacy(bound_message("/privacy", bot), state)

    # Assert
    text = session.last_screen.text
    policy = DEFAULT_RETENTION_POLICY
    for days in (
        policy.recipient_identity_days,
        policy.brief_text_days,
        policy.paid_audio_days,
        policy.abandoned_draft_days,
    ):
        assert str(days) in text
    assert "{" not in text, "an unfilled placeholder reached the customer"


async def test_privacy_does_not_disturb_a_half_typed_wizard(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """Reading the privacy notice must not cost the user the answers they have given."""
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await handle_privacy(bound_message("/privacy", bot), state)

    # Assert
    assert await state.get_state() == Wizard.name.state
    assert await read_note(state) == "Loves plov and the mountains"


# ---------------------------------------------------------------------------
# /support
# ---------------------------------------------------------------------------
async def test_support_names_the_configured_destination(
    settings: Settings, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    deps = deps_with_contact(settings, SUPPORT_CONTACT)

    # Act
    await handle_support(bound_message("/support", bot), state, deps)

    # Assert
    assert SUPPORT_CONTACT in session.last_screen.text


async def test_support_with_no_contact_configured_does_not_invent_one(
    settings: Settings, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """An unconfigured contact changes the copy; it never fakes a destination.

    Rendering ``support.text`` with an empty contact would tell the customer to write to
    nobody, and they would walk away believing the problem had been reported.
    """
    # Arrange
    assert settings.support_contact == "", "the default must be empty, not a placeholder"

    # Act
    await handle_support(bound_message("/support", bot), state, deps_with_contact(settings, ""))

    # Assert
    text = session.last_screen.text
    assert text == translate("support.no_contact", Language.UZ_LATN)
    assert "{contact}" not in text


# ---------------------------------------------------------------------------
# /forget
# ---------------------------------------------------------------------------
async def test_forget_erases_the_draft_and_offers_a_way_back(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    deps: BotDeps,
) -> None:
    """The draft holds the recipient's name, the note and the lyric. It really goes.

    For every session abandoned before CONFIRM that draft is the only copy that ever
    existed, so clearing it is a real erasure and not a gesture.
    """
    # Arrange
    await walk_to_name(dispatcher, bot)
    await send(dispatcher, bot, UZBEK_TYPED)
    assert await state.get_data() != {}
    session.clear()

    # Act
    await handle_forget(bound_message("/forget", bot), state, deps)

    # Assert
    assert await state.get_state() is None
    assert await state.get_data() == {}
    screen = session.last_screen
    assert screen.text == translate("privacy.forgotten", Language.EN)
    assert screen.reply_markup is not None, "a command that ends a flow must offer a way on"


async def test_forget_keeps_the_parking_place_of_a_song_already_at_the_studio(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    deps: BotDeps,
) -> None:
    """``privacy.forgotten`` says the queued song survives. The FSM has to agree.

    A bare ``state.clear()`` contradicted that copy within two taps: with the park gone,
    ``order_in_flight`` went blind, and the next /cancel answered "Cancelled — nothing was
    made, and nothing was kept" about a song that then arrived.
    """
    # Arrange — an order is in flight
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    order_id = (await state.get_data())[ORDER_ID_KEY]
    session.clear()

    # Act
    await handle_forget(bound_message("/forget", bot), state, deps)

    # Assert — the draft is gone, the fact that a song is being made is not
    data = await state.get_data()
    assert "draft" not in data
    assert await state.get_state() == Wizard.submitting.state
    assert data[ORDER_ID_KEY] == order_id


async def test_cancel_after_forget_still_refuses_to_claim_nothing_was_made(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    deps: BotDeps,
) -> None:
    # Arrange
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    await handle_forget(bound_message("/forget", bot), state, deps)
    session.clear()

    # Act — the name went with the draft, so this is the no-name refusal. So did the
    # chosen interface language, which is why this renders in the default one.
    await send(dispatcher, bot, "/cancel")

    # Assert
    texts = " ".join(getattr(call, "text", "") or "" for call in session.calls)
    assert translate("wizard.still_in_studio", FALLBACK_LANGUAGE) in texts
    assert translate("wizard.cancelled", Language.EN) not in texts
    assert translate("wizard.cancelled", FALLBACK_LANGUAGE) not in texts
    assert await state.get_state() == Wizard.submitting.state


async def test_forget_confirms_in_the_language_that_was_chosen(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    deps: BotDeps,
) -> None:
    """The language is read before the clear, or every confirmation is in the fallback."""
    # Arrange
    await walk_to_name(dispatcher, bot)
    session.clear()

    # Act
    await handle_forget(bound_message("/forget", bot), state, deps)

    # Assert
    assert session.last_screen.text == translate("privacy.forgotten", Language.EN)


class _RefusingEraser(FakeEntitlements):
    """A meter that cannot erase. Stands in for the database being down mid-request."""

    async def forget(self, telegram_user_id: int) -> Result[None]:
        self.writes.append("forget")
        return err(StorageError("the ledger is unreachable"))


def deps_with_meter(
    settings: Settings, credits: FakeEntitlements, *, is_enforced: bool = False
) -> BotDeps:
    return BotDeps(
        settings=settings.model_copy(update={"credits_enforced": is_enforced}),
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        entitlements=credits,
    )


async def test_forget_erases_the_credit_record_the_privacy_notice_now_names(
    bot: Bot, session: RecordingSession, state: FSMContext, settings: Settings
) -> None:
    """``/privacy`` promises deletion; ``credit_accounts`` and ``credit_ledger`` are on no
    clock, so this command is the only thing that can make that promise true for them."""
    # Arrange
    credits = FakeEntitlements(credits=2)

    # Act
    await handle_forget(bound_message("/forget", bot), state, deps_with_meter(settings, credits))

    # Assert
    assert credits.erased == [USER_ID]
    assert session.last_screen.text == translate("privacy.forgotten", FALLBACK_LANGUAGE)


async def test_forget_does_not_claim_an_erasure_the_store_refused_to_perform(
    bot: Bot, session: RecordingSession, state: FSMContext, settings: Settings
) -> None:
    """``privacy.forgotten`` says the record was unlinked. After a failed write it was not.

    The draft is gone either way — that half is local and irreversible — but the sentence
    the customer reads has to be about what actually happened, and ``/forget`` is idempotent
    so sending it again finishes the job.
    """
    # Arrange
    credits = _RefusingEraser()

    # Act
    await handle_forget(bound_message("/forget", bot), state, deps_with_meter(settings, credits))

    # Assert
    said = session.last_screen.text
    assert said != translate("privacy.forgotten", FALLBACK_LANGUAGE)
    assert said == translate(StorageError("x").user_message_key, FALLBACK_LANGUAGE)


async def test_forget_still_works_for_a_bot_built_with_no_meter_at_all(
    bot: Bot, session: RecordingSession, state: FSMContext, deps: BotDeps
) -> None:
    """A deployment that has never counted a credit has nothing to erase, and that is a
    successful erasure rather than a failure the customer should hear about."""
    # Arrange / Act
    await handle_forget(bound_message("/forget", bot), state, deps)

    # Assert
    assert session.last_screen.text == translate("privacy.forgotten", FALLBACK_LANGUAGE)


@pytest.mark.parametrize("language", list(Language))
def test_the_privacy_notice_names_the_credit_record_in_every_language(
    language: Language,
) -> None:
    """The notice enumerated four clocks and silently omitted the two tables with none.

    Pinned on the marker the line carries rather than on its wording, so a translator may
    rewrite the sentence but cannot drop it — which is the failure mode that matters, since
    a notice that is true in English and incomplete in Uzbek is not a notice.
    """
    # Arrange
    policy = DEFAULT_RETENTION_POLICY

    # Act
    notice = translate(
        "privacy.text",
        language,
        recipient_identity_days=policy.recipient_identity_days,
        brief_text_days=policy.brief_text_days,
        paid_audio_days=policy.paid_audio_days,
        abandoned_draft_days=policy.abandoned_draft_days,
    )

    # Assert
    assert CREDIT_RECORD_MARKER in notice
    assert "/forget" in notice, "naming the record without naming the way out is worse"


# ---------------------------------------------------------------------------
# TRUST-11: a command at the note step is obeyed, never stored and sung
# ---------------------------------------------------------------------------
async def test_a_known_command_at_the_note_step_is_answered_not_recorded(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """The defect itself, through the real router tree.

    Requires ``commands.build_router()`` to be included before ``questions``; see the
    ordering assertion in ``test_app.py``.
    """
    # Arrange
    await walk_to_note(dispatcher, bot)
    session.clear()

    # Act
    await send(dispatcher, bot, "/help")

    # Assert
    assert session.last_screen.text == translate("help.text", Language.EN)
    assert await state.get_state() == Wizard.note.state
    assert await read_note(state) == ""


@pytest.mark.parametrize("typed", ["/halp", "/list_my_songs", "/"])
async def test_an_unknown_command_at_the_note_step_is_never_sung(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    typed: str,
) -> None:
    """No router claims these, so without the guard they land in the draft verbatim."""
    # Arrange
    await walk_to_note(dispatcher, bot)
    session.clear()

    # Act
    await send(dispatcher, bot, typed)

    # Assert — the note is untouched and the prompt is back up with its buttons
    assert await read_note(state) == ""
    assert await state.get_state() == Wizard.note.state
    assert session.last_screen.reply_markup is not None


async def test_an_ordinary_note_still_reaches_the_draft(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The guard must fire on commands and on nothing else."""
    # Arrange
    await walk_to_note(dispatcher, bot)

    # Act
    await send(dispatcher, bot, "She reads poetry every morning")

    # Assert
    assert await read_note(state) == "She reads poetry every morning"


# ---------------------------------------------------------------------------
# The Telegram command menu
# ---------------------------------------------------------------------------
def test_every_advertised_command_is_one_the_bot_answers() -> None:
    """The menu, spelled out. An exact set, so an entry cannot be added without being read.

    ``/balance`` joined it with the entitlement layer: a metered product whose meter has no
    surface of its own tells a customer how many songs they have left only by refusing one.
    """
    # Arrange / Assert
    advertised = {command.command for command in BOT_COMMANDS}
    assert advertised == {"start", "cancel", "balance", "help", "privacy", "support", "forget"}
    assert all(command.description for command in BOT_COMMANDS)


@pytest.mark.parametrize("command", [entry.command for entry in BOT_COMMANDS])
async def test_every_advertised_command_gets_an_answer_through_the_real_router(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, command: str
) -> None:
    """The other end of the assertion above: a menu entry nobody handles replies with silence.

    The set test pins what is advertised; this one pins that each of them reaches a handler
    through the router tree the bot actually builds. Both are needed — ``/balance`` is
    declared in ``handlers.commands`` and implemented in ``handlers.balance``, which is
    exactly the shape where an entry is advertised and never registered.
    """
    # Arrange
    session.clear()

    # Act
    await send(dispatcher, bot, f"/{command}")

    # Assert
    said = [text for call in session.calls if (text := getattr(call, "text", None))]
    assert said, f"/{command} is on the menu and answered with nothing"


async def test_publish_commands_fills_the_menu(bot: Bot, session: RecordingSession) -> None:
    # Arrange / Act
    await publish_commands(bot)

    # Assert
    call = session.last_named("SetMyCommands")
    assert [command.command for command in call.commands] == [
        command.command for command in BOT_COMMANDS
    ]


async def test_a_rejected_menu_does_not_stop_the_bot(bot: Bot, session: RecordingSession) -> None:
    """The menu is a convenience. A Telegram hiccup must not block a bot ready to work."""
    # Arrange
    session.failures["SetMyCommands"] = TelegramBadRequest(
        method=None,  # type: ignore[arg-type]
        message="too many commands",
    )

    # Act / Assert — no exception escapes
    await publish_commands(bot)
    assert session.named("SetMyCommands")
