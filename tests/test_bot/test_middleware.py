"""The error guard, and the two language resolvers the whole bot renders through.

Three things are proved here and nowhere else.

The guard: an unhandled exception inside an aiogram handler is logged by the framework and
then *nothing happens* — the chat simply goes quiet, which reads as a dead bot. Every test
in the first half asserts that a sentence came out instead.

:func:`~bayram.bot.middleware.resolve_language_or_none` versus
:func:`~bayram.bot.middleware.resolve_language`: the difference between the two is a
one-character type change that fixed a real clobber, and it is only visible in a test that
asks for the ``None``. ``resolve_language`` answers the FALLBACK language whenever there is
no draft, so when the gate offered *that* into ``users.ui_language`` the drain stamped
UZ_LATN over a Russian speaker's real choice for sixty seconds after every
``state.clear()``. A value a caller is about to WRITE has to be able to say "we never
asked"; a value a caller is about to SPEAK never can.

That both values come from **one** ``state.get_data()`` is the third property, and it is a
performance contract with teeth: ``InboundGateMiddleware`` runs inside aiogram's per-chat
FSM isolation lock, and that lock is what makes the Confirm state filter a real gate rather
than a hint. A second read there does not merely cost a round trip, it widens the
double-tap window the lock exists to close.

**No ``profiles=`` on this module's three ``BotDeps``.** It imports no wizard walker and
drives no onboarding screen, so it is deliberately outside the rule that every
walker-touching module carries a profile store.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, TelegramObject

from bayram.bot.deps import DEPS_KEY, BotDeps
from bayram.bot.draft import UI_LANGUAGE_KEY, WizardDraft
from bayram.bot.gate import InboundGateMiddleware, TouchQueue
from bayram.bot.i18n import FALLBACK_LANGUAGE, translate
from bayram.bot.middleware import ErrorGuardMiddleware, resolve_language, resolve_language_or_none
from bayram.config import Settings
from bayram.contracts import Language, Result, ok
from bayram.entitlements import CreditBalance
from bayram.errors import ModerationRejectedError, ProviderTimeoutError
from tests.test_bot.conftest import (
    BOT_ID,
    CHAT_ID,
    USER_ID,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    callback_update,
    make_message,
    message_update,
)


def exploding_dispatcher(deps: BotDeps, exception: Exception) -> Dispatcher:
    """A dispatcher whose only handler raises, wrapped in the real guard."""
    router = Router(name="exploding")

    async def boom(event: Message | CallbackQuery) -> None:
        raise exception

    router.message.register(boom, Command("boom"))
    router.callback_query.register(boom)

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher[DEPS_KEY] = deps
    guard = ErrorGuardMiddleware()
    dispatcher.message.middleware(guard)
    dispatcher.callback_query.middleware(guard)
    dispatcher.include_router(router)
    return dispatcher


@pytest.mark.parametrize(
    ("exception", "expected_key"),
    [
        (RuntimeError("unexpected"), "error.generic"),
        (ProviderTimeoutError("slow", provider="elevenlabs"), "error.provider_slow"),
        (ModerationRejectedError("nope"), "error.content_not_allowed"),
    ],
)
async def test_exception_becomes_a_localised_message(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    exception: Exception,
    expected_key: str,
) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )
    dispatcher = exploding_dispatcher(deps, exception)

    # Act — must not raise out of feed_update
    await dispatcher.feed_update(bot, message_update("/boom"))

    # Assert
    assert session.last_screen.text == translate(expected_key, Language.UZ_LATN)


async def test_failure_is_logged_with_full_context(
    settings: Settings, bot: Bot, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )
    dispatcher = exploding_dispatcher(deps, RuntimeError("kaboom"))

    # Act
    with caplog.at_level(logging.ERROR):
        await dispatcher.feed_update(bot, message_update("/boom"))

    # Assert
    record = next(record for record in caplog.records if record.message == "handler failed")
    assert record.failure.startswith("RuntimeError")  # type: ignore[attr-defined]
    assert record.event_type == "Message"  # type: ignore[attr-defined]
    assert record.exc_info is not None


async def test_a_failing_callback_still_gets_its_spinner_stopped(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )
    dispatcher = exploding_dispatcher(deps, RuntimeError("kaboom"))

    # Act
    await dispatcher.feed_update(bot, callback_update("anything"))

    # Assert
    assert session.named("AnswerCallbackQuery")
    assert session.named("SendMessage")


async def test_resolve_language_reads_the_draft(state: FSMContext) -> None:
    # Arrange
    await state.update_data(**WizardDraft(ui_language=Language.RU).to_state_data())

    # Act
    language = await resolve_language(state)

    # Assert
    assert language is Language.RU


async def test_resolve_language_falls_back_without_a_draft(state: FSMContext) -> None:
    # Arrange / Act
    language = await resolve_language(state)

    # Assert
    assert language is Language.UZ_LATN


async def test_resolve_language_falls_back_without_a_state() -> None:
    # Arrange / Act / Assert
    assert await resolve_language(None) is Language.UZ_LATN


# ---------------------------------------------------------------------------
# resolve_language_or_none — the value a caller is allowed to WRITE
# ---------------------------------------------------------------------------
async def test_resolve_language_or_none_answers_none_when_nobody_has_been_asked(
    state: FSMContext,
) -> None:
    """The whole reason this function exists beside ``resolve_language``.

    An empty FSM is what every customer has before onboarding asks the question, and it is
    what every customer has for a moment after ``state.clear()``. ``resolve_language``
    answers UZ_LATN here, which is a perfectly good language to SPEAK and a catastrophic
    thing to WRITE: ``gate.UserTouch`` carries it into ``users.ui_language``, so within
    sixty seconds of any clear the drain stamped the fallback over whatever the customer had
    actually picked, and the Settings screen appeared to forget itself for no reason a
    reader of either file could see. ``None`` is how "we never asked" survives the trip.
    """
    # Arrange / Act
    chosen = await resolve_language_or_none(state)

    # Assert
    assert chosen is None


async def test_resolve_language_or_none_answers_none_without_a_state() -> None:
    """No FSM at all — a channel post, or a handler outside the state middleware. Still a
    question nobody has answered, so still not a language anyone may write."""
    # Arrange / Act / Assert
    assert await resolve_language_or_none(None) is None


async def test_resolve_language_or_none_reads_the_cached_choice_between_flows(
    state: FSMContext,
) -> None:
    """``UI_LANGUAGE_KEY`` is what ``common.clear_keeping_identity`` deliberately keeps.

    Between flows there is no draft, so before this key existed the only honest answer was
    "nobody chose" — and the customer was re-asked their language every time they finished
    a song. The cache is the identity that survives a clear; the row is still the truth.
    """
    # Arrange — no draft, only the cache.
    await state.update_data({UI_LANGUAGE_KEY: Language.RU.value})

    # Act
    chosen = await resolve_language_or_none(state)

    # Assert
    assert chosen is Language.RU


async def test_resolve_language_or_none_prefers_the_live_draft_over_the_cache(
    state: FSMContext,
) -> None:
    """The draft wins, and the order is the point rather than an accident.

    A customer who changes language in Settings mid-wizard has it written onto the draft in
    the same handler. Reading the cache first would leave the wizard screens and the error
    guard rendering the same tap in two different languages — the bug this ordering exists
    to make impossible, asserted with the two sources deliberately disagreeing.
    """
    # Arrange
    await state.update_data(
        {UI_LANGUAGE_KEY: Language.EN.value, **WizardDraft(ui_language=Language.RU).to_state_data()}
    )

    # Act
    chosen = await resolve_language_or_none(state)

    # Assert
    assert chosen is Language.RU


async def test_resolve_language_or_none_ignores_a_stored_value_that_names_no_language(
    state: FSMContext,
) -> None:
    """Redis holds these keys for fourteen days, across deploys and hand-edits.

    A code that no longer names a member must read as "nobody chose" and not as a crash on
    the hot path — the gate is the one middleware ``ErrorGuardMiddleware`` does not wrap, so
    an exception here takes the update with it and the chat goes silent.
    """
    # Arrange
    await state.update_data({UI_LANGUAGE_KEY: "kk_latn"})

    # Act
    chosen = await resolve_language_or_none(state)

    # Assert
    assert chosen is None


async def test_resolve_language_still_speaks_the_fallback_where_the_writer_says_none(
    state: FSMContext,
) -> None:
    """The two functions must disagree on an empty FSM, and that is not a bug.

    Pinned in one test so a future "simplification" that makes ``resolve_language`` return
    ``Language | None`` (or ``resolve_language_or_none`` return the fallback) fails here,
    with the reason attached, instead of quietly restoring the clobber.
    """
    # Arrange / Act / Assert
    assert await resolve_language_or_none(state) is None
    assert await resolve_language(state) is FALLBACK_LANGUAGE


# ---------------------------------------------------------------------------
# One FSM read, two derived values
# ---------------------------------------------------------------------------
class _CountingFSMContext(FSMContext):
    """An ``FSMContext`` that counts ``get_data`` calls.

    A real subclass rather than a duck-typed wrapper because ``gate._decide`` narrows with
    ``isinstance(state, FSMContext)``: anything else is treated as "no state at all", the
    gate reads nothing, and the assertion below passes on zero reads while proving nothing.
    """

    def __init__(self, inner: FSMContext) -> None:
        super().__init__(storage=inner.storage, key=inner.key)
        self.reads = 0

    async def get_data(self) -> dict[str, Any]:
        self.reads += 1
        return await super().get_data()


class _BlockedMeter:
    """A barred account, implementing ONLY what the gate is allowed to call.

    Deliberately partial: ``balance_for`` is the single non-writing member of
    ``EntitlementStore`` and therefore the only one the bot may reach for (a bot that could
    move a credit is the failure ``BotDeps.entitlements`` is shaped to prevent). A fake that
    satisfied the whole protocol would let a future gate start charging unnoticed, so this
    one is passed through a typed ignore instead.
    """

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        return ok(
            CreditBalance(
                telegram_user_id=telegram_user_id, credits=0, in_flight=0, is_blocked=True
            )
        )

    async def touch(self, telegram_user_id: int, *, ui_language: Language | None) -> Result[None]:
        return ok(None)


async def test_the_gate_reads_the_fsm_once_and_derives_both_values(
    bot: Bot, session: RecordingSession
) -> None:
    """One ``state.get_data()`` per update, and two different answers taken from it.

    ``InboundGateMiddleware`` runs inside aiogram's per-chat FSM isolation lock — the lock
    that turns the Confirm state filter into a real gate rather than a hint. A second read
    in there does not merely cost a round trip: it serialises the chat behind one more
    awaited store call and widens the double-tap window the lock was added to close. The
    obvious way to write ``_decide`` is one ``resolve_language_or_none`` for the touch and
    one ``resolve_language`` for the refusal copy, which is exactly two reads; this test is
    what stops that shape coming back.

    Both derived values are asserted, because a test that only counted reads would still
    pass if the second value were dropped instead of derived. The account has never chosen a
    language, so the two are genuinely different: the queued touch carries ``None`` (nothing
    may be written over an unasked question) while the refusal is rendered in the fallback
    (a refusal nobody can read is not a refusal).
    """
    # Arrange — a barred account with an empty FSM.
    storage = MemoryStorage()
    counting = _CountingFSMContext(
        FSMContext(storage=storage, key=StorageKey(bot_id=BOT_ID, chat_id=CHAT_ID, user_id=USER_ID))
    )
    queue = TouchQueue()
    middleware = InboundGateMiddleware(
        entitlements=_BlockedMeter(),  # type: ignore[arg-type]
        touches=queue,
    )
    reached = False

    async def handler(event: TelegramObject, data: dict[str, Any]) -> None:
        nonlocal reached
        reached = True

    # Act
    await middleware(handler, make_message("hi").as_(bot), {"state": counting})

    # Assert — one read, and the handler never ran: this is a refusal, not a pass-through.
    assert counting.reads == 1
    assert reached is False

    # Assert — the value that would be WRITTEN is the absence itself.
    assert [touch.ui_language for touch in queue.take_all()] == [None]

    # Assert — and the value that is SPOKEN is a real language.
    assert session.last_screen.text == translate("error.blocked", FALLBACK_LANGUAGE)
