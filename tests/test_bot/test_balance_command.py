"""``/balance`` and the Confirm-screen note: the two places the meter becomes visible.

The property every test here defends is one property, stated two ways. **A number is shown
only when the product will honour it**, and **the absence of a number is said out loud
rather than left as a blank screen.** Between those two sits the configuration this repo
actually ships — the meter wired and ``credits_enforced`` off, so nothing is ever charged —
and a ``/balance`` that answered "3 songs left" there would be inviting a customer to budget
against a number that never moves.

The Confirm-screen half is asserted by comparison rather than by pattern: the screen a
customer sees with no meter is compared BYTE FOR BYTE with the screen they saw before this
module existed, because "the note is additive" is the claim the whole existing wizard-screen
suite rests on and a substring assertion cannot make it.

``FakeEntitlements`` is reused from ``test_credit_gate`` rather than re-declared: it already
records every write, so every test below is also a proof that ``/balance`` reads and nothing
more.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.deps import BotDeps
from bayram.bot.i18n import translate
from bayram.bot.states import Wizard
from bayram.config import Settings
from bayram.contracts import Language
from bayram.entitlements import DEFAULT_ENTITLEMENT_POLICY
from bayram.errors import StorageError
from tests.test_bot.conftest import (
    BOT_ID,
    CHAT_ID,
    USER_ID,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
)
from tests.test_bot.test_credit_gate import FakeEntitlements, enforcing, wire
from tests.test_bot.test_wizard_flow import send, walk_to_confirm

#: The window after ``FIXED_MOMENT`` (2026-03-21), written out for the same reason
#: ``test_credit_gate`` writes it out: a change to the window arithmetic must fail in the
#: copy the customer reads rather than agree with itself.
NEXT_GRANT_DAY = "2026-04-07"

#: A rolling allowance, stated here and threaded through ``Settings`` rather than read off
#: ``DEFAULT_ENTITLEMENT_POLICY``.
#:
#: The two numbers used to be the same one. Since the paywall shipped they are not:
#: ``Settings.free_allowance_credits`` defaults to **0** — every recording is sold — while
#: the dataclass default stays at 3 for the callers that hold no settings object, so
#: ``resolve_entitlement_policy(settings)`` and ``DEFAULT_ENTITLEMENT_POLICY`` now disagree
#: by design. A test of the ALLOWANCE COPY has to run on a deployment that actually grants
#: an allowance, or it asserts that "your allowance is 0 every 30 days" is shown to somebody
#: — which is true of no shipped configuration and is exactly the sentence
#: ``credits.balance_metered`` exists to avoid. Written as a literal rather than taken from
#: the resolver so the expectation cannot agree with the code by construction.
ALLOWANCE_CREDITS = 3


def unwired(settings: Settings, submitter: RecordingSubmitter) -> BotDeps:
    """``BotDeps`` with no METER at all — the shape the whole existing bot suite runs on.

    Unwired means unwired for entitlements, and for nothing else. The profile store is present
    and is not an inconsistency: ``confirm_screen_text`` reaches the Confirm screen through
    ``walk_to_confirm``, which drives the real onboarding screens, and without a store the
    onboarding router fails open, the walker's language press matches no handler, and the
    "byte-identical" comparison below silently becomes a comparison of two fallback-language
    screens that agree with each other and with nothing the customer sees. That is the exact
    shape of vacuous green this file's byte-for-byte assertion exists to avoid, so the store is
    wired on BOTH sides of it.
    """
    return BotDeps(
        settings=settings,
        submitter=submitter,
        content=RecordingContentWriter(),
        profiles=FakeProfiles(),
    )


async def ask_balance(dispatcher: Dispatcher, bot: Bot, session: RecordingSession) -> str:
    """Send ``/balance`` through the real router tree and return what came back."""
    session.clear()
    await send(dispatcher, bot, "/balance")
    said = [text for call in session.calls if isinstance(text := getattr(call, "text", None), str)]
    assert said, "/balance must always answer"
    return said[-1]


async def confirm_screen_text(bot: Bot, session: RecordingSession, deps: BotDeps) -> str:
    """Walk a fresh session to the Confirm screen and return the text it put up."""
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())
    session.clear()
    await walk_to_confirm(dispatcher, bot)
    text = session.last_screen.text
    assert isinstance(text, str)
    return text


# ---------------------------------------------------------------------------
# /balance
# ---------------------------------------------------------------------------
async def test_balance_says_nothing_is_counted_when_there_is_no_meter(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
) -> None:
    """A deployment with no entitlement store has never counted anything. Say so."""
    # Arrange
    dispatcher = build_dispatcher(unwired(settings, submitter), storage=MemoryStorage())

    # Act
    answer = await ask_balance(dispatcher, bot, session)

    # Assert
    assert answer == translate("credits.balance_none", Language.UZ_LATN)


async def test_a_dark_meter_shows_no_number_however_many_credits_it_is_holding(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The shipped configuration, and the sharpest honesty test in the file.

    With ``credits_enforced`` off the render gate returns before it touches the store, so no
    credit is ever spent and this account's three will still be three after ten songs.
    Printing the three would be a worse lie than printing nothing, because a customer plans
    around it.
    """
    # Arrange — wired, holding credits, but the flag is off
    credits = FakeEntitlements(credits=3)
    dispatcher = build_dispatcher(
        wire(settings, submitter, credits, clock), storage=MemoryStorage()
    )

    # Act
    answer = await ask_balance(dispatcher, bot, session)

    # Assert
    assert answer == translate("credits.balance_none", Language.UZ_LATN)
    assert "3" not in answer
    assert credits.writes == []


async def test_an_enforcing_meter_shows_the_real_count_and_the_allowance_behind_it(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """A bare number answers "how many" and not "how many more will I get, and when".

    The allowance is set on ``Settings`` here — see :data:`ALLOWANCE_CREDITS` — because this
    is the copy for a deployment that STILL gives songs away, and the shipped one no longer
    does. Nothing about the branch changed; only the number behind it has to be asked for.
    """
    # Arrange
    credits = FakeEntitlements(credits=2)
    generous = enforcing(settings).model_copy(update={"free_allowance_credits": ALLOWANCE_CREDITS})
    dispatcher = build_dispatcher(
        wire(generous, submitter, credits, clock), storage=MemoryStorage()
    )

    # Act
    answer = await ask_balance(dispatcher, bot, session)

    # Assert
    assert answer == translate(
        "credits.balance",
        Language.UZ_LATN,
        credits=2,
        allowance=ALLOWANCE_CREDITS,
        period_days=DEFAULT_ENTITLEMENT_POLICY.allowance_period_days,
    )
    assert credits.writes == []


async def test_an_empty_allowance_is_told_the_day_the_next_song_opens(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """Zero is the one count that is useless on its own — the customer needs the date.

    The same sentence the Confirm-screen refusal ends on, so someone who checks ``/balance``
    first and someone who finds out by being refused are told the same thing.
    """
    # Arrange
    credits = FakeEntitlements(credits=0)
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=MemoryStorage()
    )

    # Act
    answer = await ask_balance(dispatcher, bot, session)

    # Assert
    assert translate("credits.next_opens", Language.UZ_LATN, next_grant_at=NEXT_GRANT_DAY) in answer


@pytest.mark.parametrize("is_enforced", [False, True])
async def test_a_song_already_in_the_studio_is_named_whatever_the_flag_says(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    is_enforced: bool,
) -> None:
    """The in-flight cap enforces from the day it merged, flag or no flag (D-B).

    So a balance that omitted it would answer "yes, go ahead" to an account whose very next
    Confirm is going to be refused — which is the meter lying in the other direction.
    """
    # Arrange
    credits = FakeEntitlements(credits=3)
    credits.open_orders.add(uuid4())
    chosen = enforcing(settings) if is_enforced else settings
    dispatcher = build_dispatcher(wire(chosen, submitter, credits, clock), storage=MemoryStorage())

    # Act
    answer = await ask_balance(dispatcher, bot, session)

    # Assert
    assert translate("credits.balance_in_flight", Language.UZ_LATN) in answer


async def test_a_meter_that_cannot_be_read_admits_it_instead_of_promising_freedom(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """ "I cannot tell you" and "nothing is counted" are different answers, and it matters.

    Folding a failed read into ``credits.balance_none`` would tell a customer their songs are
    unlimited on the strength of a database timeout.
    """
    # Arrange
    credits = FakeEntitlements(failure=StorageError("the meter is down"))
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=MemoryStorage()
    )

    # Act
    answer = await ask_balance(dispatcher, bot, session)

    # Assert
    assert answer != translate("credits.balance_none", Language.UZ_LATN)
    assert answer == translate(StorageError("the meter is down").user_message_key, Language.UZ_LATN)


async def test_balance_leaves_a_half_typed_wizard_exactly_where_it_was(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """It answers a question about the account, so it must not cost anyone their draft.

    The note step accepts any text, and a customer checking their balance mid-wizard would
    otherwise have "/balance" sung to their mother — which is exactly the defect the
    standing-commands router was built against, and a new command joins that guarantee or
    breaks it.
    """
    # Arrange — parked on the Confirm screen with a complete draft
    credits = FakeEntitlements(credits=1)
    storage = MemoryStorage()
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=storage
    )
    await walk_to_confirm(dispatcher, bot)
    state = FSMContext(
        storage=storage, key=StorageKey(bot_id=BOT_ID, chat_id=CHAT_ID, user_id=USER_ID)
    )
    before = await state.get_data()

    # Act
    await ask_balance(dispatcher, bot, session)

    # Assert
    assert await state.get_state() == Wizard.confirm.state
    assert await state.get_data() == before


# ---------------------------------------------------------------------------
# The Confirm-screen note
# ---------------------------------------------------------------------------
async def test_the_confirm_screen_is_byte_identical_with_no_meter_and_with_a_dark_one(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The claim the whole existing wizard suite rests on, asserted rather than assumed.

    Neither an unwired store nor the shipped dark one may add so much as a newline to the
    commit screen, because every other test in ``tests/test_bot`` reads that screen and none
    of them knows the entitlement layer exists.
    """
    # Arrange / Act
    without = await confirm_screen_text(bot, session, unwired(settings, submitter))
    dark = await confirm_screen_text(
        bot, session, wire(settings, submitter, FakeEntitlements(credits=3), clock)
    )

    # Assert
    assert dark == without


async def test_an_enforcing_meter_prices_the_song_on_the_screen_that_commits_to_it(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The last screen before the only irreversible press should say what it costs.

    Asserted as "the old screen plus exactly one appended line", so the note can never
    quietly rewrite the summary a customer is checking their answers on.
    """
    # Arrange
    credits = FakeEntitlements(credits=2)
    without = await confirm_screen_text(bot, session, unwired(settings, submitter))

    # Act
    priced = await confirm_screen_text(
        bot, session, wire(enforcing(settings), submitter, credits, clock)
    )

    # Assert
    note = translate("credits.confirm_note", Language.EN, credits=2)
    assert priced == f"{without}\n\n{note}"
    assert credits.writes == []
