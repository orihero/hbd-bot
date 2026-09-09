"""The inbound gate: the block wall, the erasure carve-out, the throttle, and failing open.

Most of these drive a REAL dispatcher rather than calling the middleware, because three of
the properties under test are properties of the *wiring* and vanish under a direct call:

* the gate is OUTER, so it runs before any handler's filters — a blocked account must not
  be able to reach a handler by sending something no filter would have claimed;
* a refusal on the callback surface has to answer the callback query, or the customer's
  button spins until Telegram gives up;
* ``ErrorGuardMiddleware`` is INNER and therefore does not wrap this one, which is why the
  gate has to catch its own exceptions.

The shared ``deps`` fixture wires no meter at all (``tests/test_bot/conftest.py``), so the
other twenty-odd bot test modules run with the gate registered and only the throttle live —
which is exactly what the last test in this file asserts on purpose rather than by luck.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, TelegramObject, User

import hbd.bot.gate as gate_module
from hbd.bot.app import build_dispatcher
from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.gate import ERASURE_COMMANDS, InboundGateMiddleware
from hbd.bot.i18n import FALLBACK_LANGUAGE, translate
from hbd.config import Settings
from hbd.contracts import Language, Result
from hbd.entitlements import CreditBalance
from hbd.errors import StorageError
from tests.test_bot.conftest import (
    CHAT_ID,
    FIXED_MOMENT,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    make_message,
)
from tests.test_bot.test_credit_gate import FakeEntitlements
from tests.test_bot.test_wizard_flow import press, send, walk_to_confirm


#: Every rendering of a refusal, in every catalogue. The gate resolves the language from
#: the draft, which does not exist yet on the first update of a session, so a test that
#: pinned one language would be asserting on where in the wizard it happened to be.
def _every_rendering(key: str) -> frozenset[str]:
    return frozenset(translate(key, language) for language in Language)


BLOCKED_TEXTS = _every_rendering("error.blocked")
TOO_FAST_TEXTS = _every_rendering("error.too_fast")


class ExplodingEntitlements:
    """A meter that raises rather than returning ``Err``.

    ``EntitlementStore`` promises a ``Result`` and never an exception, and this is the fake
    that refuses to believe it. The gate is not wrapped by ``ErrorGuardMiddleware``, so an
    exception escaping it would take the update with it and the chat would go silent.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        self.calls += 1
        raise RuntimeError("the meter is on fire")

    async def touch(self, telegram_user_id: int, *, ui_language: Language | None) -> Result[None]:
        raise RuntimeError("the meter is on fire")


def wire(
    settings: Settings,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    *,
    entitlements: object | None = None,
) -> BotDeps:
    """``BotDeps`` with a meter of the test's choosing.

    Typed ``object`` and passed through an ignore because two of the fakes here are
    deliberately PARTIAL: they implement only ``balance_for`` and ``touch``, which is
    everything the gate is permitted to call. A fake that satisfied the whole
    ``EntitlementStore`` would let a future gate start charging without a test noticing.

    ``profiles`` is a real (empty) :class:`~tests.test_bot.conftest.FakeProfiles` and not
    ``None``, because this module imports the walkers and the walkers now drive the two
    onboarding screens. With ``profiles=None`` ``onboarding.load_identity`` fails open and
    treats everybody as onboarded, so every walk here would take a branch that ships to
    nobody — and the throttle and block-wall assertions below would be counting the messages
    of a bot none of these customers can actually reach.
    """
    return BotDeps(
        settings=settings,
        submitter=submitter,
        content=RecordingContentWriter(),
        clock=clock,
        entitlements=entitlements,  # type: ignore[arg-type]
        profiles=FakeProfiles(),
    )


def message_from(telegram_user_id: int) -> Message:
    """A plain text message from a chosen account. The conftest builder pins one id."""
    return Message(
        message_id=1,
        date=FIXED_MOMENT,
        chat=Chat(id=telegram_user_id, type="private"),
        from_user=User(id=telegram_user_id, is_bot=False, first_name="Dilnoza"),
        text="hi",
    )


def texts(session: RecordingSession) -> list[str]:
    """Everything the bot said, on any surface — sent, edited or answered on a callback."""
    said = [getattr(call, "text", None) for call in session.calls]
    return [text for text in said if isinstance(text, str) and text]


def answer_texts(session: RecordingSession) -> list[str | None]:
    """The text of every ``answerCallbackQuery``. ``None`` is a real value: a bare answer
    clears the spinner without saying anything, which is what a spent notice budget does."""
    return [getattr(call, "text", None) for call in session.named("AnswerCallbackQuery")]


# ---------------------------------------------------------------------------
# The block wall
# ---------------------------------------------------------------------------
async def test_a_blocked_account_s_message_never_reaches_a_handler(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """Including an account that has no ``users`` row at all.

    That is the case a rowcount-checked ``UPDATE users SET is_blocked`` would silently miss.
    There are exactly three writers of that table and none of them has run for this customer:
    ``db.users_sql.ensure_user`` called from ``repository._create_order``, which needs a
    confirmed order; the same function called from ``SqlUserProfiles.record_language``, which
    needs the language question to have been answered; and ``credits.touch``, which is the
    drain this gate feeds. Somebody who has just opened the chat has done none of the three.
    The gate therefore asks the meter about the *account*, not about a row it assumes exists
    — and the touch drain is what gives that account its row.
    """
    # Arrange
    credits = FakeEntitlements(is_blocked=True)
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=credits), storage=storage
    )

    # Act
    await send(dispatcher, bot, "/start")

    # Assert — the first screen never went up, and the refusal did. The key named here MUST be
    # one the catalogues actually define: ``translate`` degrades a missing key to the key
    # itself, so a stale name in a ``not in`` assertion passes for ever while testing nothing.
    assert translate("onboarding.language.prompt", FALLBACK_LANGUAGE) not in texts(session)
    assert BLOCKED_TEXTS & set(texts(session))
    assert credits.reads == [None]


async def test_a_blocked_account_s_button_press_is_refused_on_the_callback_itself(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """A refused callback MUST be answered, or the button spins until Telegram times out.

    Answering it is also a reply rather than a new chat message, which is why the callback
    surface carries the words even when the notice budget has gone quiet.
    """
    # Arrange
    credits = FakeEntitlements(is_blocked=True)
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=credits), storage=storage
    )

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    answers = session.named("AnswerCallbackQuery")
    assert len(answers) == 1
    assert answer_texts(session)[0] in BLOCKED_TEXTS
    assert submitter.submitted == []


async def test_the_gate_never_writes_through_the_meter_on_the_hot_path(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The touch is OFFERED, never awaited: the gate runs inside the FSM isolation lock.

    ``FakeEntitlements`` records every write it is asked for. With no drain running — a
    dispatcher that was never polled has none — the list must still be empty, which is what
    proves the upsert went to the queue rather than onto the customer's update.
    """
    # Arrange
    credits = FakeEntitlements()
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=credits), storage=storage
    )

    # Act
    await walk_to_confirm(dispatcher, bot)

    # Assert
    assert credits.writes == []


# ---------------------------------------------------------------------------
# The erasure carve-out
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("command", sorted(ERASURE_COMMANDS))
async def test_a_blocked_account_can_still_make_a_data_subject_request(
    command: str,
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """Non-negotiable. Blocking is an operator action of indefinite length, and it must
    never become the mechanism by which someone's erasure request is refused."""
    # Arrange
    credits = FakeEntitlements(is_blocked=True)
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=credits), storage=storage
    )

    # Act
    await send(dispatcher, bot, f"/{command}")

    # Assert — the handler answered and the refusal was never sent
    assert texts(session), f"/{command} produced no reply at all"
    assert not BLOCKED_TEXTS & set(texts(session))


@pytest.mark.parametrize("text", ["/Forget@hbd_bot", "/forget now please", "/PRIVACY"])
async def test_the_carve_out_reads_the_command_the_way_telegram_writes_it(
    text: str, bot: Bot
) -> None:
    """``/forget@some_bot`` is the form Telegram sends in a group, an argument is still a
    command, and clients happily send ``/PRIVACY``. All three are the same request.

    Driven straight at the middleware: routing a group-form command needs ``bot.me()``,
    which the recording session cannot answer, and the thing under test is the gate's
    reading of the text rather than aiogram's ``Command`` filter.
    """
    # Arrange
    gate = InboundGateMiddleware(entitlements=FakeEntitlements(is_blocked=True))
    handled: list[TelegramObject] = []

    async def handler(event: TelegramObject, data: dict[str, Any]) -> str:
        handled.append(event)
        return "handled"

    # Act
    await gate(handler, make_message(text).as_(bot), {})

    # Assert
    assert len(handled) == 1


async def test_a_blocked_account_is_still_refused_a_command_that_is_not_a_carve_out(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The exemption is three commands, not "anything beginning with a slash"."""
    # Arrange
    credits = FakeEntitlements(is_blocked=True)
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=credits), storage=storage
    )

    # Act
    await send(dispatcher, bot, "/help")

    # Assert
    assert BLOCKED_TEXTS & set(texts(session))


def test_every_carved_out_command_is_actually_registered_by_the_commands_router() -> None:
    """A carve-out naming a command nobody handles exempts nothing at all.

    Read out of the source rather than asserted against a second list, so renaming
    ``/forget`` in ``handlers.commands`` fails HERE instead of quietly emptying the
    exemption and leaving a blocked person with no way to ask for their data back.
    """
    # Arrange
    source = (
        Path(__file__).resolve().parents[2] / "src" / "hbd" / "bot" / "handlers" / "commands.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Act — every ``Command("x")`` named inside a ``…register(…)`` call
    registered: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "register"):
            continue
        segment = ast.get_source_segment(source, node) or ""
        registered |= set(re.findall(r'Command\("([a-z_]+)"\)', segment))

    # Assert
    assert registered >= ERASURE_COMMANDS


# ---------------------------------------------------------------------------
# The throttle
# ---------------------------------------------------------------------------
def throttled_at(settings: Settings, ceiling: int) -> Settings:
    """The same settings with a ceiling a test can actually reach."""
    return settings.model_copy(update={"inbound_max_updates": ceiling})


async def test_a_data_subject_command_is_metered_on_its_own_generous_budget(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The carve-out is from the BLOCK gate and from the ordinary ceiling — not from every
    limiter.

    ``handle_forget`` is not the "one canned message" the exemption was costed at: it clears
    the FSM, writes state three times, and opens a transaction that rewrites every
    ``credit_ledger`` row for the account and deletes its balance. Exempt from everything, it
    was an unmetered write amplifier reachable by holding a key down. Its own budget keeps
    the request answerable — the refusal is ``error.too_fast``, "send it again in a moment",
    never a denial — while bounding the writes.
    """
    # Arrange — a budget of two, and a fixed clock so every send lands in one window.
    deps = wire(settings.model_copy(update={"inbound_erasure_max_updates": 2}), submitter, clock)
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    for _ in range(5):
        await send(dispatcher, bot, "/privacy")

    # Assert — two answered, the rest refused, and the refusal is the throttle's, not the
    # block gate's: a data-subject request is never denied, only asked to wait.
    said = texts(session)
    assert sum(1 for text in said if text in TOO_FAST_TEXTS) == 1
    assert not BLOCKED_TEXTS & set(said)
    assert sum(1 for text in said if text.startswith("🔒")) == 2


async def test_a_blocked_account_s_erasure_request_is_never_refused_by_the_block_gate(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The half of the carve-out that must survive the new budget, stated on its own.

    The erasure branch is decided BEFORE the block gate is consulted, so a barred account
    still reaches the handler; adding a limiter must not have quietly moved that decision.
    """
    # Arrange
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=FakeEntitlements(is_blocked=True)),
        storage=storage,
    )

    # Act
    await send(dispatcher, bot, "/forget")

    # Assert
    assert texts(session)
    assert not BLOCKED_TEXTS & set(texts(session))


async def test_the_update_past_the_ceiling_is_refused_and_told_once(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """Two properties in one walk, because they are the same decision seen twice.

    The update after the ceiling gets no handler, and the four after that get no words
    either: the account being throttled is precisely the one sending enough updates to make
    a reply-per-update its own flood.
    """
    # Arrange — the clock is fixed, so all six updates land in one window
    deps = wire(throttled_at(settings, 2), submitter, clock)
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    for _ in range(6):
        await send(dispatcher, bot, "/help")

    # Assert
    said = texts(session)
    assert sum(1 for text in said if text in TOO_FAST_TEXTS) == 1
    assert sum(1 for text in said if text == translate("help.text", FALLBACK_LANGUAGE)) == 2


async def test_a_throttled_button_press_is_answered_even_when_the_words_are_spent(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """Silence on a callback is not silence, it is a spinner that never stops."""
    # Arrange — one update of budget, spent on the message below
    dispatcher = build_dispatcher(
        wire(throttled_at(settings, 1), submitter, clock), storage=storage
    )
    await send(dispatcher, bot, "/help")

    # Act — two presses past the ceiling; the notice budget is gone after the first
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert — both were answered, and only one carried words
    answers = answer_texts(session)
    assert len(answers) == 2
    assert answers.count(None) == 1


async def test_the_throttle_runs_with_no_meter_wired_at_all(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The shape the whole existing bot suite runs in, asserted rather than assumed.

    ``BotDeps.entitlements`` defaults to ``None``, and the counters default to the in-memory
    store because fake mode, the demo and every test run without Redis. A throttle that
    needed either would be a throttle that is switched off in three of the four ways this
    program is ever run.
    """
    # Arrange
    dispatcher = build_dispatcher(
        wire(throttled_at(settings, 1), submitter, clock), storage=storage
    )

    # Act
    await send(dispatcher, bot, "/help")
    await send(dispatcher, bot, "/help")

    # Assert
    assert TOO_FAST_TEXTS & set(texts(session))


# ---------------------------------------------------------------------------
# Failing open
# ---------------------------------------------------------------------------
async def test_a_meter_that_raises_still_lets_the_update_through(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """FAILS OPEN, and it has to fail open on its own: ``ErrorGuardMiddleware`` is INNER.

    An exception escaping an outer middleware reaches aiogram's own error machinery, which
    logs it and answers nobody — the chat simply goes quiet, which reads as a dead bot.
    """
    # Arrange
    meter = ExplodingEntitlements()
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=meter), storage=storage
    )

    # Act
    await send(dispatcher, bot, "/help")

    # Assert — the meter was consulted, it exploded, and the customer still got their answer
    assert meter.calls == 1
    assert translate("help.text", FALLBACK_LANGUAGE) in texts(session)


async def test_a_meter_that_returns_an_error_still_lets_the_update_through(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The ordinary failure, distinct from the one above: a typed ``Err``, not an exception.

    It is deliberately NOT cached — a blip must not buy an amnesty for the whole cache
    window — so the next update asks again.
    """
    # Arrange
    credits = FakeEntitlements(is_blocked=True, failure=StorageError("the meter is unreadable"))
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=credits), storage=storage
    )

    # Act
    await send(dispatcher, bot, "/help")
    await send(dispatcher, bot, "/help")

    # Assert
    assert not BLOCKED_TEXTS & set(texts(session))
    assert len(credits.reads) == 2


async def test_the_block_answer_is_cached_rather_than_read_on_every_tap(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """One database round trip per account per cache window, not one per update.

    The gate runs inside the FSM isolation lock, so a read here serialises one chat's
    updates behind it. The price of the cache is the lag on an UNBLOCK, which is the
    trade ``HBD_INBOUND_BLOCK_CACHE_S`` exists to let an operator retune.
    """
    # Arrange — the fixed clock keeps every update inside one cache window
    credits = FakeEntitlements()
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=credits), storage=storage
    )

    # Act
    for _ in range(5):
        await send(dispatcher, bot, "/help")

    # Assert
    assert len(credits.reads) == 1


# ---------------------------------------------------------------------------
# The updates that are none of the gate's business
# ---------------------------------------------------------------------------
async def test_an_update_with_no_from_user_is_passed_through_untouched(bot: Bot) -> None:
    """A channel post has no account to meter, nothing to block and nobody to throttle.

    Called directly rather than through the dispatcher, because the point is that NOTHING
    happened — no touch queued, no counter charged — and only the middleware can be asked.
    """
    # Arrange
    gate = InboundGateMiddleware(entitlements=FakeEntitlements(is_blocked=True))
    anonymous = Message(
        message_id=7, date=FIXED_MOMENT, chat=Chat(id=-100, type="channel"), text="hello"
    ).as_(bot)
    handled: list[TelegramObject] = []

    async def handler(event: TelegramObject, data: dict[str, Any]) -> str:
        handled.append(event)
        return "handled"

    # Act
    result = await gate(handler, anonymous, {})

    # Assert
    assert result == "handled"
    assert handled == [anonymous]
    assert gate.touches.pending == 0


async def test_a_metered_update_offers_exactly_one_touch(bot: Bot) -> None:
    """The touch is offered BEFORE the carve-out and before either refusal, so an account
    that is about to be refused still gets the row that makes it blockable in the first
    place."""
    # Arrange
    gate = InboundGateMiddleware(entitlements=FakeEntitlements(is_blocked=True))
    message = make_message("/start").as_(bot)

    async def handler(event: TelegramObject, data: dict[str, Any]) -> str:
        return "handled"

    # Act
    await gate(handler, message, {})

    # Assert
    assert gate.touches.pending == 1


# ---------------------------------------------------------------------------
# The wiring
# ---------------------------------------------------------------------------
def test_the_gate_is_one_outer_middleware_on_both_customer_surfaces(
    settings: Settings, submitter: RecordingSubmitter, clock: Callable[[], datetime]
) -> None:
    """OUTER, because only outer runs before a handler's filters — an inner one would let a
    blocked account walk the bot by sending something no filter matched. And ONE instance,
    because the counters, the block cache and the touch queue live on it: two instances
    would hand every account two budgets.
    """
    # Arrange / Act
    dispatcher = build_dispatcher(wire(settings, submitter, clock), storage=MemoryStorage())

    # Assert
    on_messages = [
        m for m in dispatcher.message.outer_middleware if isinstance(m, InboundGateMiddleware)
    ]
    on_callbacks = [
        m
        for m in dispatcher.callback_query.outer_middleware
        if isinstance(m, InboundGateMiddleware)
    ]
    assert len(on_messages) == 1
    assert on_messages == on_callbacks
    # ... and the error guard stays INNER, which is why the gate catches its own failures.
    assert not any(isinstance(m, InboundGateMiddleware) for m in dispatcher.message.middleware)


async def test_the_drain_is_started_and_closed_with_the_dispatcher(
    settings: Settings,
    bot: Bot,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The drain is a background task, so it needs a loop to start on and a shutdown to
    stop on. ``dispatcher.startup``/``shutdown`` are what ``start_polling`` fires."""
    # Arrange
    credits = FakeEntitlements()
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=credits), storage=MemoryStorage()
    )
    gate = next(
        m for m in dispatcher.message.outer_middleware if isinstance(m, InboundGateMiddleware)
    )
    assert gate.drain is not None

    # Act
    await dispatcher.emit_startup(bot=bot)
    is_running = gate.drain.is_running
    await dispatcher.emit_shutdown(bot=bot)

    # Assert
    assert is_running is True
    assert gate.drain.is_running is False


# ---------------------------------------------------------------------------
# The defensive branches — the ones that only run on a bad day
# ---------------------------------------------------------------------------
async def test_a_refusal_that_cannot_be_sent_is_logged_and_not_raised(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """Telling someone they are blocked is best effort — they may have blocked the bot back.

    A ``TelegramAPIError`` here would escape an OUTER middleware, past the error guard,
    into aiogram's own machinery. The refusal already happened; failing to announce it must
    not become a second incident.
    """
    # Arrange — the chat will not take a message at all
    session.failures["SendMessage"] = TelegramBadRequest(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="bot was blocked by the user"
    )
    credits = FakeEntitlements(is_blocked=True)
    dispatcher = build_dispatcher(
        wire(settings, submitter, clock, entitlements=credits), storage=storage
    )

    # Act — no exception may reach here
    await send(dispatcher, bot, "/start")

    # Assert — it was attempted, and the handler still never ran
    assert session.named("SendMessage")
    assert submitter.submitted == []


async def test_the_block_cache_forgets_everything_rather_than_growing_forever(
    bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-process map keyed on account id, in a process that runs for months.

    Forgetting costs one extra read per account — which is exactly what the map was saving
    — and never a wrong answer, so dropping it wholesale is the right last resort. The cap
    is patched rather than reached: fifty thousand distinct accounts is not a unit test.
    """
    # Arrange
    monkeypatch.setattr(gate_module, "_MEMO_MAX_ACCOUNTS", 2)
    credits = FakeEntitlements()
    gate = InboundGateMiddleware(entitlements=credits)

    async def handler(event: TelegramObject, data: dict[str, Any]) -> str:
        return "handled"

    # Act — three distinct accounts, then the first one again
    for telegram_user_id in (1, 2, 3, 1):
        await gate(handler, message_from(telegram_user_id).as_(bot), {})

    # Assert — account 1 was read twice: the cache was dropped, not silently unbounded
    assert credits.reads.count(None) == 4


async def test_a_gate_with_no_meter_starts_and_closes_without_a_drain(bot: Bot) -> None:
    """``BotDeps.entitlements`` defaults to ``None``, and ``start_polling`` fires these two
    hooks regardless — so both have to be no-ops rather than attribute errors."""
    # Arrange
    gate = InboundGateMiddleware()

    # Act
    await gate.start()
    await gate.aclose()

    # Assert
    assert gate.drain is None
