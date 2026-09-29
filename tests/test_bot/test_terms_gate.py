"""The Terms of Use + Privacy gate (IMAGE_VIDEO_SPEC §2.1, §10 M1.2, D26), end to end.

Every acceptance line of M1.2 has a test here, through the real router tree and the real
middleware chain, with an in-memory ledger standing in for ``terms_acceptances`` (the SQL half
is pinned in ``tests/test_db/test_terms_acceptances.py``):

* a new customer is asked language → terms → contact, in that order;
* an FSM that expired on the Terms step, then ``/start``, brings the Terms back — not contact;
* ✅ from a customer who has not finished onboarding reaches the accept handler, not the
  ``NotOnboarded`` catch-all;
* an onboarded customer is stopped until they accept, and is handed the menu when they do;
* ``/support`` and the reply that describes the ticket both get through;
* a blocked button is always answered;
* a version bump re-prompts;
* after ``/forget`` the next message shows the Terms;
* a render in flight is not interrupted, and the gate sits on no observer but the two
  inbound ones;
* accepting opens no ``user_profiles`` row;
* and with no version configured — the shipped default — none of it exists.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Final, cast

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, Update, User

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import (
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    SupportAction,
    SupportCB,
    TermsAction,
    TermsCB,
    pack_reference,
)
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import privacy_text
from bayram.bot.handlers.submitting import ORDER_ID_KEY
from bayram.bot.i18n import translate
from bayram.bot.keyboards import MENU_SETTINGS_LABEL_KEY
from bayram.bot.locales import CATALOGUES
from bayram.bot.screens import (
    menu_screen,
    onboarding_contact_screen,
    onboarding_language_screen,
    settings_screen,
    terms_full_screen,
    terms_screen,
)
from bayram.bot.states import Onboarding, Wizard
from bayram.bot.terms_gate import TermsGateMiddleware
from bayram.bot_chats import SupportGroupTarget
from bayram.config import Settings
from bayram.contracts import (
    Language,
    Result,
    SupportTicketSource,
    SupportTicketStatus,
    err,
    is_ok,
    ok,
)
from bayram.db.retention import DEFAULT_RETENTION_POLICY
from bayram.errors import BayramError, StorageError
from bayram.main import build_terms_gate
from bayram.terms import (
    LEGAL_TEXT_FINGERPRINT,
    LEGAL_TEXT_IS_DRAFT,
    InMemoryTermsCache,
    TermsGate,
    TermsSource,
    TermsStanding,
    TermsVersions,
    terms_cache_key,
)
from tests.test_bot.conftest import (
    BOT_ID,
    CHAT_ID,
    FIXED_MOMENT,
    USER_ID,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    contact_update,
)
from tests.test_bot.test_credit_gate import FakeEntitlements
from tests.test_bot.test_support import (
    GROUP_CHAT_ID,
    STAFF_USER_ID,
    FakeBotChats,
    FakeSupportTickets,
    group_callback,
    group_sends,
    private_reply,
)
from tests.test_bot.test_wizard_flow import press, send, tap

V1: Final[TermsVersions] = TermsVersions(terms="2026-10-01", privacy="2026-10-01")
V2: Final[TermsVersions] = TermsVersions(terms="2026-11-01", privacy="2026-10-01")

ACCEPT: Final[str] = TermsCB(action=TermsAction.ACCEPT, v=V1.stamp).pack()
READ_FULL: Final[str] = TermsCB(action=TermsAction.READ_FULL).pack()
ENGLISH: Final[str] = LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack()


class FakeTermsLedger:
    """An in-memory :class:`bayram.terms.TermsLedger`. ``failure`` is returned while set."""

    def __init__(self) -> None:
        #: ``(telegram_user_id, versions, language, source)`` per accepted pair, first wins.
        self.rows: list[tuple[int | None, TermsVersions, Language, TermsSource]] = []
        self.failure: BayramError | None = None
        self.reads = 0

    async def standing(
        self, telegram_user_id: int, versions: TermsVersions
    ) -> Result[TermsStanding]:
        self.reads += 1
        if self.failure is not None:
            return err(self.failure)
        mine = [row[1] for row in self.rows if row[0] == telegram_user_id]
        if not mine:
            return ok(TermsStanding.NEVER)
        return ok(TermsStanding.ACCEPTED if versions in mine else TermsStanding.OUTDATED)

    async def accept(
        self,
        telegram_user_id: int,
        versions: TermsVersions,
        *,
        language: Language,
        source: TermsSource,
    ) -> Result[None]:
        if self.failure is not None:
            return err(self.failure)
        if not any(row[0] == telegram_user_id and row[1] == versions for row in self.rows):
            self.rows.append((telegram_user_id, versions, language, source))
        return ok(None)

    def anonymise(self, telegram_user_id: int) -> None:
        """What ``forget_account``'s terms arm does to the real table."""
        self.rows = [
            (None if owner == telegram_user_id else owner, versions, language, source)
            for owner, versions, language, source in self.rows
        ]


class ForgettingMeter(FakeEntitlements):
    """A meter whose ``forget`` also anonymises the acceptances, as ``forget_account`` does in
    one transaction against Postgres (pinned in ``tests/test_db/test_terms_acceptances.py``)."""

    def __init__(self, ledger: FakeTermsLedger) -> None:
        super().__init__()
        self._ledger = ledger

    async def forget(self, telegram_user_id: int) -> Result[None]:
        self._ledger.anonymise(telegram_user_id)
        return await super().forget(telegram_user_id)


class ExplodingCache:
    """A :class:`bayram.terms.TermsCache` whose every command fails, like a Redis that is down."""

    async def get(self, name: str) -> Any:
        raise ConnectionError("redis is down")

    async def set(self, name: str, value: str, *, ex: int) -> Any:
        raise ConnectionError("redis is down")

    async def delete(self, *names: str) -> Any:
        raise ConnectionError("redis is down")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def ledger() -> FakeTermsLedger:
    return FakeTermsLedger()


@pytest.fixture
def cache() -> InMemoryTermsCache:
    return InMemoryTermsCache()


@pytest.fixture
def gate(ledger: FakeTermsLedger, cache: InMemoryTermsCache) -> TermsGate:
    return TermsGate(ledger, V1, cache=cache)


@pytest.fixture
def deps(
    settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    gate: TermsGate,
) -> BotDeps:
    """The shared dependencies with the gate ON — every test here is about it."""
    return BotDeps(
        settings=settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        terms=gate,
    )


def gate_text(language: Language = Language.EN, versions: TermsVersions = V1) -> str:
    return terms_screen(language, versions).text


def shown(session: RecordingSession) -> list[str]:
    return [
        text
        for call in session.calls
        if type(call).__name__ in {"SendMessage", "EditMessageText"}
        and isinstance(text := getattr(call, "text", None), str)
    ]


def toasts(session: RecordingSession) -> list[str | None]:
    return [getattr(call, "text", None) for call in session.named("AnswerCallbackQuery")]


def reply_to_the_bot(text: str) -> Update:
    """A message that answers one of the bot's own — how a ``/support`` ticket is described."""
    return Update(
        update_id=9_001,
        message=Message(
            message_id=31,
            date=FIXED_MOMENT,
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
            text=text,
            reply_to_message=Message(
                message_id=30,
                date=FIXED_MOMENT,
                chat=Chat(id=CHAT_ID, type="private"),
                from_user=User(id=BOT_ID, is_bot=True, first_name="Bayram"),
                text="✉️ Tell me here what went wrong",
            ),
        ),
    )


async def expire_the_session(state: FSMContext) -> None:
    """What Redis does to an FSM key after fourteen idle days: state and data both gone."""
    await state.set_state(None)
    await state.set_data({})


# ---------------------------------------------------------------------------
# New customers: language → terms → contact
# ---------------------------------------------------------------------------
async def test_a_new_customer_is_asked_language_then_terms_then_contact(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    ledger: FakeTermsLedger,
) -> None:
    # Act / Assert — the language first, in the operator's default.
    await send(dispatcher, bot, "/start")
    assert await state.get_state() == Onboarding.language.state

    # Then the Terms, in the language just chosen, with ✅ and 📄 under them.
    await press(dispatcher, bot, ENGLISH)
    assert await state.get_state() == Onboarding.terms.state
    assert session.last_screen.text == gate_text()
    assert "trm:ok" in str(session.last_screen.reply_markup)

    # Then the contact screen — and the acceptance is on record, from the onboarding screen.
    await press(dispatcher, bot, ACCEPT)
    assert await state.get_state() == Onboarding.contact.state
    assert session.last_screen.text == onboarding_contact_screen(Language.EN).text
    assert ledger.rows == [(USER_ID, V1, Language.EN, "onboarding")]

    # And the number finishes onboarding exactly as before the gate existed.
    await dispatcher.feed_update(bot, contact_update())
    assert await state.get_state() is None


async def test_anything_but_accept_on_the_terms_step_repeats_the_terms(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """Declining is just not accepting: ``terms.required`` and the same two buttons."""
    # Arrange
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, ENGLISH)

    # Act
    await send(dispatcher, bot, "no thanks")

    # Assert
    assert await state.get_state() == Onboarding.terms.state
    assert session.last_screen.text == terms_screen(Language.EN, V1, is_repeat=True).text


@pytest.mark.parametrize("arrival", ["/start", "hello"])
async def test_an_expired_session_on_the_terms_step_comes_back_to_the_terms(
    arrival: str,
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
) -> None:
    """Language → TERMS → contact, from ``/start`` and from the catch-all alike."""
    # Arrange — a language chosen, the Terms on screen, then fourteen idle days.
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, ENGLISH)
    await expire_the_session(state)

    # Act
    await send(dispatcher, bot, arrival)

    # Assert — the Terms again, never the contact screen that would skip them.
    assert await state.get_state() == Onboarding.terms.state
    assert session.last_screen.text == gate_text()


async def test_accept_from_a_customer_not_yet_onboarded_reaches_the_accept_handler(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    ledger: FakeTermsLedger,
) -> None:
    """With no FSM state the ``NotOnboarded`` catch-all would claim ✅ — it must not."""
    # Arrange — a language on record, the FSM gone, the old Terms message still on screen.
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, ENGLISH)
    await expire_the_session(state)

    # Act
    await press(dispatcher, bot, ACCEPT)

    # Assert
    assert ledger.rows == [(USER_ID, V1, Language.EN, "onboarding")]
    assert await state.get_state() == Onboarding.contact.state
    assert session.last_screen.text == onboarding_contact_screen(Language.EN).text


async def test_accepting_opens_no_profile_row(
    dispatcher: Dispatcher,
    bot: Bot,
    profiles: FakeProfiles,
    ledger: FakeTermsLedger,
) -> None:
    """IMAGE_VIDEO_SPEC §0.3: a row opened here would read as a language choice."""
    # Act — a ✅ from a stranger with no row at all (a forwarded screen, a stale chat).
    await press(dispatcher, bot, ACCEPT)

    # Assert
    assert ledger.rows == [(USER_ID, V1, Language.UZ_LATN, "onboarding")]
    assert profiles.rows == {}


# ---------------------------------------------------------------------------
# The installed base: the middleware
# ---------------------------------------------------------------------------
async def test_an_onboarded_customer_is_stopped_until_they_accept(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    profiles: FakeProfiles,
    ledger: FakeTermsLedger,
    submitter: RecordingSubmitter,
) -> None:
    # Arrange
    profiles.seed(USER_ID)

    # Act — the settings button, which would otherwise open Settings.
    await tap(dispatcher, bot, MENU_SETTINGS_LABEL_KEY, Language.EN)

    # Assert — the Terms instead, and nothing behind them ran.
    assert session.last_screen.text == gate_text()
    assert settings_screen(Language.EN).text not in shown(session)
    assert submitter.submitted == []

    # Act — ✅, from the gate screen this time.
    await press(dispatcher, bot, ACCEPT)

    # Assert — recorded as the gate's, and the customer is handed the menu.
    assert ledger.rows == [(USER_ID, V1, Language.EN, "gate")]
    assert session.last_screen.text == menu_screen(Language.EN).text

    # And the next tap goes where it was always going.
    await tap(dispatcher, bot, MENU_SETTINGS_LABEL_KEY, Language.EN)
    assert session.last_screen.text == settings_screen(Language.EN).text


async def test_start_hands_an_onboarded_customer_who_owes_the_terms_the_terms(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    # Arrange
    profiles.seed(USER_ID)

    # Act
    await send(dispatcher, bot, "/start")

    # Assert
    assert session.last_screen.text == gate_text()


async def test_a_blocked_message_is_answered_with_the_screen_once_a_minute(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    # Arrange
    profiles.seed(USER_ID)

    # Act
    for _ in range(3):
        await send(dispatcher, bot, "hello?")

    # Assert
    assert shown(session).count(gate_text()) == 1


async def test_a_blocked_button_is_always_answered(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    """An unanswered callback spins; the toast is not metered, the screen is."""
    # Arrange
    profiles.seed(USER_ID)
    to_menu = NavCB(action=NavAction.TO_MENU).pack()

    # Act
    await press(dispatcher, bot, to_menu)
    await press(dispatcher, bot, to_menu)

    # Assert
    assert toasts(session) == [translate("terms.required", Language.EN)] * 2
    assert shown(session).count(gate_text()) == 1


async def test_support_and_the_reply_that_describes_it_both_pass(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    profiles: FakeProfiles,
    gate: TermsGate,
) -> None:
    """A ticket is opened with a command and described with a reply; refusing the reply would
    open a ticket nobody can fill in (IMAGE_VIDEO_SPEC §2.1, §10 M1.2)."""
    # Arrange — an onboarded customer who owes the Terms, with a real ticket store wired.
    profiles.seed(USER_ID)
    support = FakeSupportTickets()
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        profiles=profiles,
        support=support,
        terms=gate,
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Act
    await send(dispatcher, bot, "/support")
    prompt_id = support.only().prompt_message_id
    assert prompt_id is not None, "/support opened no ticket"
    await dispatcher.feed_update(bot, private_reply("The name was wrong", to_message_id=prompt_id))

    # Assert — the ticket is described, and neither update was answered with the Terms.
    ticket = support.only()
    assert ticket.telegram_user_id == USER_ID
    assert ticket.body == "The name was wrong"
    assert ticket.described_at is not None
    assert gate_text() not in shown(session)


async def test_a_reply_to_the_bot_that_no_ticket_listens_for_is_stopped(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
    content: RecordingContentWriter,
) -> None:
    """Only a reply ``ListeningTicket`` would claim passes. A reply to the note prompt is wizard
    input and would reach the lyric writer with no acceptance on record (D26)."""
    # Arrange
    profiles.seed(USER_ID)
    await state.set_state(Wizard.note)

    # Act
    await dispatcher.feed_update(bot, reply_to_the_bot("she loves the sea"))

    # Assert
    assert session.last_screen.text == gate_text()
    assert content.calls == 0
    assert await state.get_state() == Wizard.note.state


async def test_a_wizard_language_button_is_stopped_and_the_writer_never_called(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
    content: RecordingContentWriter,
) -> None:
    """``lang:out`` rewrites the lyric — a vendor LLM call carrying the brief. Only the settings
    picker's ``lang:set`` is on the allowlist."""
    # Arrange
    profiles.seed(USER_ID)
    await state.set_state(Wizard.output_language)

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.EN).pack())
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.RU).pack())

    # Assert
    assert content.calls == 0
    assert toasts(session) == [translate("terms.required", Language.EN)] * 2
    assert await state.get_state() == Wizard.output_language.state


async def test_the_settings_language_picker_still_passes(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    # Arrange
    profiles.seed(USER_ID)

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.SETTINGS, code=Language.RU).pack())

    # Assert — not refused: no ``terms.required`` toast.
    assert translate("terms.required", Language.EN) not in toasts(session)


async def test_the_support_group_is_not_gated(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    profiles: FakeProfiles,
    gate: TermsGate,
) -> None:
    """A staffer who once used the bot and has not accepted the Terms can still work tickets,
    and no Terms screen is ever posted into the staff room."""
    # Arrange — the staffer is an onboarded account with no acceptance on record.
    profiles.seed(STAFF_USER_ID)
    support = FakeSupportTickets()
    opened = await support.open_ticket(
        telegram_user_id=USER_ID,
        language=Language.EN,
        source=SupportTicketSource.SUPPORT_COMMAND,
        order_id=None,
        now=FIXED_MOMENT,
    )
    assert is_ok(opened)
    ticket = opened.value
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        profiles=profiles,
        support=support,
        bot_chats=FakeBotChats(selected=SupportGroupTarget(chat_id=GROUP_CHAT_ID, thread_id=None)),
        terms=gate,
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Act
    await dispatcher.feed_update(
        bot,
        group_callback(SupportCB(action=SupportAction.CLAIM, ref=pack_reference(ticket.id)).pack()),
    )

    # Assert — the claim reached ``handle_claim``, and nothing Terms-shaped went to the group.
    claimed = support.only()
    assert claimed.status is SupportTicketStatus.IN_PROGRESS
    assert translate("terms.required", Language.EN) not in toasts(session)
    assert all(gate_text(language) not in shown(session) for language in Language)
    assert group_sends(session) == []


@pytest.mark.parametrize("command", ["/privacy", "/forget", "/terms", "/help", "/cancel"])
async def test_the_allowlisted_commands_pass(
    command: str,
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    profiles: FakeProfiles,
) -> None:
    # Arrange
    profiles.seed(USER_ID)

    # Act
    await send(dispatcher, bot, command)

    # Assert
    assert gate_text() not in shown(session)
    assert shown(session), f"{command} was answered by nothing"


async def test_a_version_bump_re_prompts_with_the_new_version(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    profiles: FakeProfiles,
    ledger: FakeTermsLedger,
    cache: InMemoryTermsCache,
) -> None:
    # Arrange — accepted V1, cached; the owner then writes V2.
    profiles.seed(USER_ID)
    await ledger.accept(USER_ID, V1, language=Language.EN, source="gate")
    await cache.set(terms_cache_key(USER_ID), V1.cache_value, ex=60)
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        profiles=profiles,
        terms=TermsGate(ledger, V2, cache=cache),
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Act
    await send(dispatcher, bot, "hello")

    # Assert — ``terms.updated``, naming the new version; the V1 cache entry did not count.
    expected = terms_screen(Language.EN, V2, standing=TermsStanding.OUTDATED).text
    assert session.last_screen.text == expected
    assert V2.label in expected


async def test_after_forget_the_next_message_shows_the_terms(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    ledger: FakeTermsLedger,
    cache: InMemoryTermsCache,
) -> None:
    """``/forget`` anonymises the rows AND drops ``terms:ok:{tg}`` (IMAGE_VIDEO_SPEC §9.3).

    No profile store, so onboarding fails open and the very next message meets the gate
    rather than the language screen — the shape the spec's acceptance line names.
    """
    # Arrange — accepted and cached.
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        entitlements=ForgettingMeter(ledger),
        terms=TermsGate(ledger, V1, cache=cache),
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())
    await press(dispatcher, bot, ACCEPT)
    assert terms_cache_key(USER_ID) in cache.values

    # Act
    await send(dispatcher, bot, "/forget")
    assert session.last_screen.text == translate("privacy.forgotten", Language.UZ_LATN)
    await send(dispatcher, bot, "hello")

    # Assert
    assert terms_cache_key(USER_ID) not in cache.values
    assert session.last_screen.text == gate_text(Language.UZ_LATN)


async def test_after_forget_a_returning_customer_meets_the_terms_after_the_language(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    profiles: FakeProfiles,
    ledger: FakeTermsLedger,
) -> None:
    """With a profile store the row is gone too, so onboarding re-asks — Terms included."""
    # Arrange
    profiles.seed(USER_ID)
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        profiles=profiles,
        entitlements=ForgettingMeter(ledger),
        terms=TermsGate(ledger, V1),
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())
    await press(dispatcher, bot, ACCEPT)

    # Act
    await send(dispatcher, bot, "/forget")
    await send(dispatcher, bot, "hello")
    assert session.last_screen.text == onboarding_language_screen(Language.UZ_LATN).text
    await press(dispatcher, bot, ENGLISH)

    # Assert
    assert session.last_screen.text == gate_text()


async def test_a_forget_whose_cache_delete_fails_says_so(
    settings: Settings, bot: Bot, session: RecordingSession, ledger: FakeTermsLedger
) -> None:
    """``privacy.forgotten`` promises the Terms come again; a stale cache would break that."""
    # Arrange
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        terms=TermsGate(ledger, V1, cache=ExplodingCache()),
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Act
    await send(dispatcher, bot, "/forget")

    # Assert
    assert session.last_screen.text != translate("privacy.forgotten", Language.UZ_LATN)


async def test_a_render_in_flight_is_not_interrupted(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """``Wizard.submitting`` is ``handlers.submitting``'s: the song being made is still said to be
    coming, and the worker's delivery never passes through a dispatcher at all."""
    # Arrange
    profiles.seed(USER_ID)
    await state.set_state(Wizard.submitting)
    await state.update_data({ORDER_ID_KEY: "3f1e0c7a-0000-4000-8000-000000000001"})

    # Act
    await send(dispatcher, bot, "is it ready?")

    # Assert
    assert gate_text() not in shown(session)
    assert await state.get_state() == Wizard.submitting.state


def test_the_gate_sits_on_the_two_inbound_observers_and_nowhere_else(deps: BotDeps) -> None:
    """Deliveries are unaffected because nothing outbound, and no other observer, carries it."""
    # Arrange
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Act
    carrying = {
        name
        for name, observer in dispatcher.observers.items()
        if any(isinstance(m, TermsGateMiddleware) for m in observer.outer_middleware)
    }

    # Assert
    assert carrying == {"message", "callback_query"}


# ---------------------------------------------------------------------------
# /terms, /privacy, 📄
# ---------------------------------------------------------------------------
async def test_terms_shows_the_whole_text_with_accept_when_it_is_owed(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    # Arrange
    profiles.seed(USER_ID)

    # Act
    await send(dispatcher, bot, "/terms")

    # Assert
    expected = terms_full_screen(Language.EN, version=V1.label, is_accept_offered=True)
    assert session.last_screen.text == expected.text
    assert "trm:ok" in str(session.last_screen.reply_markup)


async def test_read_full_draws_the_whole_text_over_the_summary(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    # Arrange
    profiles.seed(USER_ID)

    # Act
    await press(dispatcher, bot, READ_FULL)

    # Assert
    edited = session.last_named("EditMessageText")
    assert edited.text == terms_full_screen(Language.EN, version=V1.label).text


async def test_privacy_renders_the_versioned_notice(
    settings: Settings, bot: Bot, session: RecordingSession, deps: BotDeps
) -> None:
    """The one notice, through ``privacy_text``, with the configured version under it."""
    # Arrange
    versioned = BotDeps(
        settings=settings.model_copy(update={"privacy_version": "2026-10-01"}),
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        terms=deps.terms,
    )
    dispatcher = build_dispatcher(versioned, storage=MemoryStorage())

    # Act
    await send(dispatcher, bot, "/privacy")

    # Assert
    text = session.last_screen.text
    assert text == privacy_text(Language.UZ_LATN, DEFAULT_RETENTION_POLICY, version="2026-10-01")
    assert "2026-10-01" in text


# ---------------------------------------------------------------------------
# The shipped default: no version, no gate
# ---------------------------------------------------------------------------
async def test_with_no_version_onboarding_is_language_then_contact(
    settings: Settings, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        profiles=profiles,
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Act
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, ENGLISH)

    # Assert
    assert session.last_screen.text == onboarding_contact_screen(Language.EN).text
    assert not any(isinstance(m, TermsGateMiddleware) for m in dispatcher.message.outer_middleware)


async def test_with_no_version_terms_shows_the_text_and_nothing_to_accept(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Act
    await send(dispatcher, bot, "/terms")

    # Assert
    assert session.last_screen.text == terms_full_screen(Language.UZ_LATN).text
    assert session.last_screen.reply_markup is None


def test_build_terms_gate_is_off_without_a_version_and_without_a_database(
    settings: Settings,
) -> None:
    # Arrange
    with_db = cast(Any, SimpleNamespace(session_factory=object()))
    without_db = cast(Any, SimpleNamespace(session_factory=None))
    versioned = settings.model_copy(
        update={"terms_version": "2026-10-01", "privacy_version": "2026-10-02"}
    )

    # Act / Assert
    assert build_terms_gate(settings, with_db, None) is None
    assert build_terms_gate(versioned, without_db, None) is None
    gate = build_terms_gate(versioned, with_db, None)
    assert gate is not None
    assert gate.versions == TermsVersions(terms="2026-10-01", privacy="2026-10-02")


@pytest.mark.parametrize(("terms", "privacy"), [("2026-10-01", ""), ("", "2026-10-01")])
def test_one_version_without_the_other_refuses_to_boot(
    settings_env: dict[str, str], terms: str, privacy: str
) -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="together or not at all"):
        Settings(
            _env_file=None,
            telegram_bot_token=settings_env["BAYRAM_TELEGRAM_BOT_TOKEN"],
            database_url=settings_env["BAYRAM_DATABASE_URL"],
            terms_version=terms,
            privacy_version=privacy,
        )


def test_the_gate_is_off_by_default(settings: Settings) -> None:
    assert settings.is_terms_gate_enabled is False


# ---------------------------------------------------------------------------
# TermsGate: the cache, and failing open
# ---------------------------------------------------------------------------
async def test_an_accepted_standing_is_cached_and_a_refusal_is_not(
    ledger: FakeTermsLedger, cache: InMemoryTermsCache
) -> None:
    # Arrange
    gate = TermsGate(ledger, V1, cache=cache)

    # Act / Assert — NEVER is asked of the ledger every time.
    assert await gate.standing(USER_ID) is TermsStanding.NEVER
    assert await gate.standing(USER_ID) is TermsStanding.NEVER
    assert ledger.reads == 2
    # ACCEPTED is written back and answered from the cache thereafter.
    await ledger.accept(USER_ID, V1, language=Language.EN, source="gate")
    assert await gate.standing(USER_ID) is TermsStanding.ACCEPTED
    assert await gate.standing(USER_ID) is TermsStanding.ACCEPTED
    assert ledger.reads == 3
    assert cache.values[terms_cache_key(USER_ID)] == V1.cache_value


async def test_a_bytes_cache_value_counts(ledger: FakeTermsLedger) -> None:
    """redis-py answers bytes unless the client decodes; the gate must read both."""

    class BytesCache(InMemoryTermsCache):
        async def get(self, name: str) -> Any:
            value = self.values.get(name)
            return value.encode() if value is not None else None

    cache = BytesCache()
    await cache.set(terms_cache_key(USER_ID), V1.cache_value, ex=60)

    assert await TermsGate(ledger, V1, cache=cache).standing(USER_ID) is TermsStanding.ACCEPTED
    assert ledger.reads == 0


async def test_an_unreadable_ledger_fails_open_and_is_not_cached(
    ledger: FakeTermsLedger, cache: InMemoryTermsCache
) -> None:
    # Arrange
    ledger.failure = StorageError("the database is down")
    gate = TermsGate(ledger, V1, cache=cache)

    # Act / Assert
    assert await gate.standing(USER_ID) is TermsStanding.ACCEPTED
    assert cache.values == {}


async def test_a_dead_cache_falls_back_to_the_ledger(ledger: FakeTermsLedger) -> None:
    # Arrange
    gate = TermsGate(ledger, V1, cache=ExplodingCache())

    # Act / Assert — asked, answered, and the failed write-back is swallowed.
    assert await gate.standing(USER_ID) is TermsStanding.NEVER
    accepted = await gate.accept(USER_ID, language=Language.EN, source="onboarding")
    assert is_ok(accepted)
    assert await gate.standing(USER_ID) is TermsStanding.ACCEPTED


async def test_a_failed_record_is_an_error_on_the_button_and_does_not_advance(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    ledger: FakeTermsLedger,
) -> None:
    # Arrange
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, ENGLISH)
    ledger.failure = StorageError("the database is down")

    # Act
    await press(dispatcher, bot, ACCEPT)

    # Assert
    assert await state.get_state() == Onboarding.terms.state
    alert = session.last_named("AnswerCallbackQuery")
    assert alert.show_alert is True
    assert ledger.rows == []


# ---------------------------------------------------------------------------
# The texts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language", list(Language))
def test_every_legal_text_fits_one_telegram_message(language: Language) -> None:
    """Telegram refuses a message over 4096 characters; the Terms and the notice are long."""
    for text in (
        terms_full_screen(language, version=V2.label, is_accept_offered=True).text,
        privacy_text(language, DEFAULT_RETENTION_POLICY, version=V2.privacy),
        terms_screen(language, V2, standing=TermsStanding.OUTDATED, url="https://x.uz/t").text,
    ):
        assert len(text) < 4_096, (language, len(text))
        assert "{" not in text, "an unfilled placeholder reached the customer"


@pytest.mark.parametrize("language", list(Language))
def test_the_draft_is_marked_draft_everywhere_it_is_shown(language: Language) -> None:
    """D26 / O17: the text is Claude's draft until M1.3, and says so on every surface."""
    banner = translate("terms.draft_banner", language)
    assert LEGAL_TEXT_IS_DRAFT is True
    assert terms_full_screen(language).text.startswith(banner)
    assert privacy_text(language, DEFAULT_RETENTION_POLICY).startswith(banner)
    assert terms_screen(language, V1).text.startswith(banner)


@pytest.mark.parametrize("language", list(Language))
def test_the_privacy_notice_names_media_retention_exactly_once(language: Language) -> None:
    """IMAGE_VIDEO_SPEC §2.1: the media periods are interpolated, and said once.

    Measured with a policy whose three media numbers appear nowhere else in the notice, so a
    count of one is the interpolation and not a coincidence with a song period. The third is
    the CSAM legal hold (O16, Q16, Appendix A.2 §6), the one exception to "deleted right after
    delivery" that the notice must not leave out.
    """
    policy = replace(
        DEFAULT_RETENTION_POLICY,
        media_input_max_hours=23,
        media_output_days=41,
        media_legal_hold_max_hours=67,
    )
    text = privacy_text(language, policy)
    assert text.count("23") == 1
    assert text.count("41") == 1
    assert text.count("67") == 1


# ---------------------------------------------------------------------------
# M1.R: a stale ✅, /forget with the gate off, the fail-closed question, the boot probe
# ---------------------------------------------------------------------------
async def test_a_button_drawn_before_a_version_bump_records_nothing(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    profiles: FakeProfiles,
    ledger: FakeTermsLedger,
) -> None:
    """A ✅ carrying V1's stamp, pressed after the owner wrote V2, would record acceptance of a
    text the customer never saw. It redraws the current screen instead."""
    # Arrange
    profiles.seed(USER_ID)
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        profiles=profiles,
        terms=TermsGate(ledger, V2),
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Act
    await press(dispatcher, bot, ACCEPT)

    # Assert — nothing recorded; the V2 screen, whose ✅ carries V2's stamp.
    assert ledger.rows == []
    assert session.last_screen.text == gate_text(versions=V2)
    assert TermsCB(action=TermsAction.ACCEPT, v=V2.stamp).pack() in str(
        session.last_screen.reply_markup
    )

    # And the fresh button records V2.
    await press(dispatcher, bot, TermsCB(action=TermsAction.ACCEPT, v=V2.stamp).pack())
    assert ledger.rows == [(USER_ID, V2, Language.EN, "gate")]


def test_a_version_stamp_tells_pairs_apart_and_fits_a_callback() -> None:
    assert V1.stamp != V2.stamp
    assert len(TermsCB(action=TermsAction.ACCEPT, v=V1.stamp).pack().encode()) <= 64


async def test_forget_drops_the_cache_entry_with_the_gate_switched_off(
    settings: Settings, bot: Bot, session: RecordingSession, cache: InMemoryTermsCache
) -> None:
    """An entry written while the gate was on must not survive a /forget sent while it is off:
    switching the gate back on inside the day would pass a forgotten account (§9.3)."""
    # Arrange
    await cache.set(terms_cache_key(USER_ID), V1.cache_value, ex=60)
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        terms_cache=cache,
    )
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Act
    await send(dispatcher, bot, "/forget")

    # Assert
    assert terms_cache_key(USER_ID) not in cache.values
    assert session.last_screen.text == translate("privacy.forgotten", Language.UZ_LATN)


async def test_require_fails_closed(ledger: FakeTermsLedger, cache: InMemoryTermsCache) -> None:
    """The media paths' question (D20, D26): only an acceptance of the pair in force is Ok."""
    # Arrange
    gate = TermsGate(ledger, V1, cache=cache)

    # Act / Assert — never accepted, then an older pair only: both refused.
    assert not is_ok(await gate.require(USER_ID))
    await ledger.accept(USER_ID, V2, language=Language.EN, source="gate")
    assert not is_ok(await gate.require(USER_ID))
    # Accepted: Ok, and cached.
    await ledger.accept(USER_ID, V1, language=Language.EN, source="gate")
    assert is_ok(await gate.require(USER_ID))
    assert cache.values[terms_cache_key(USER_ID)] == V1.cache_value
    # An unreadable ledger is a refusal, where ``standing`` would have let them through.
    cache.values.clear()
    ledger.failure = StorageError("the database is down")
    assert not is_ok(await gate.require(USER_ID))
    assert await gate.standing(USER_ID) is TermsStanding.ACCEPTED


async def test_the_boot_probe_reports_an_unreadable_ledger(ledger: FakeTermsLedger) -> None:
    gate = TermsGate(ledger, V1)
    assert is_ok(await gate.probe())
    ledger.failure = StorageError("relation terms_acceptances does not exist")
    assert not is_ok(await gate.probe())


def test_the_terms_version_is_stripped(settings_env: dict[str, str]) -> None:
    configured = Settings(
        _env_file=None,
        telegram_bot_token=settings_env["BAYRAM_TELEGRAM_BOT_TOKEN"],
        database_url=settings_env["BAYRAM_DATABASE_URL"],
        terms_version=" 2026-10-01 ",
        privacy_version="2026-10-01 ",
    )
    assert configured.terms_version == "2026-10-01"
    assert configured.privacy_version == "2026-10-01"


def test_the_legal_text_fingerprint_is_pinned() -> None:
    """``bayram.terms.LEGAL_TEXT_FINGERPRINT`` is the deliberate record that the shipped text
    changed. When this fails, the Terms or the Privacy Notice moved: update the constant AND
    bump ``BAYRAM_TERMS_VERSION``/``BAYRAM_PRIVACY_VERSION`` in the release that ships it, or
    nobody is asked to accept the new text."""
    digest = hashlib.sha256()
    for language in sorted(Language, key=lambda each: each.value):
        for key in ("terms.full", "privacy.text"):
            digest.update(f"{language.value}\0{key}\0{CATALOGUES[language][key]}\0".encode())
    assert digest.hexdigest()[:16] == LEGAL_TEXT_FINGERPRINT
