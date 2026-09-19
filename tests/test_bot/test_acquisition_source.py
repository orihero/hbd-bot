"""Where a customer came from, recorded once, from the ``/start`` payload and nothing else.

This file exists because the link and the column are useless apart, and each was built to a
guess about the other. ``bayrambot.uz/ig`` hands Telegram a payload, Telegram hands the bot
``/start ig_bio``, and until the handler declared a ``CommandObject`` that payload was not
merely unread but *unreadable* — so every campaign looked identical to someone typing
``/start``, and the one number the Instagram plan is measured on did not exist.

Four properties, and each of them is a way the feature silently degrades into a wrong number
rather than into an error anybody would notice:

* **First touch wins.** A returning customer who taps a highlight must not overwrite the
  campaign that actually earned them. Overwrite and the column stops being acquisition and
  becomes "wherever they last clicked", which reads exactly the same in a dashboard.
* **A payload Telegram could not have carried is discarded, not truncated.** The payload is
  attacker-supplied text at a trust boundary, and a truncated label is a wrong answer wearing
  the shape of a right one.
* **``/start paid`` is not an acquisition.** It is claimed by the checkout handler's filter,
  and were it not, every customer returning from the payment page would be recorded as having
  been acquired by the payment page.
* **Nothing about it may block an arrival.** A customer who taps the bio link came to order a
  song; a store that cannot write a label is not a reason to answer them with an error.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.start import PAID_DEEP_LINK
from bayram.config import Settings
from bayram.errors import StorageError
from tests.test_bot.conftest import (
    USER_ID,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
)
from tests.test_bot.test_wizard_flow import send

pytestmark = pytest.mark.anyio


def wire(settings: Settings, profiles: FakeProfiles) -> tuple[Dispatcher, FakeProfiles]:
    """A dispatcher over a store this test can read back, and that store."""
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        profiles=profiles,
    )
    return build_dispatcher(deps, storage=MemoryStorage()), profiles


async def test_the_bio_link_payload_is_recorded_on_a_first_ever_start(
    settings: Settings, bot: Bot
) -> None:
    """``/start ig_bio`` from a stranger creates the row and stamps the label on it.

    The account does not exist yet — no language chosen, no number — which is the whole point:
    this is the FIRST update the bot ever sees from this person, and it is the only moment the
    payload is on the wire. A store that needed a row to already exist would record nothing for
    precisely the customers the campaign just bought.
    """
    dispatcher, profiles = wire(settings, FakeProfiles())

    await send(dispatcher, bot, "/start ig_bio")

    assert profiles.rows[USER_ID].acquisition_source == "ig_bio"


async def test_a_second_start_does_not_overwrite_the_first_campaign(
    settings: Settings, bot: Bot
) -> None:
    """First touch wins forever. This is the property the whole column is for.

    A customer arrives from the bio link, comes back a week later through a highlight, and the
    stored answer to "where did this customer come from" must still be the bio link. Without
    the ``COALESCE`` this passes as ``ig_hl_narxlar`` and the acquisition report quietly
    becomes a report of most-recent-link instead.
    """
    dispatcher, profiles = wire(settings, FakeProfiles())

    await send(dispatcher, bot, "/start ig_bio")
    await send(dispatcher, bot, "/start ig_hl_narxlar")

    assert profiles.rows[USER_ID].acquisition_source == "ig_bio"


async def test_a_bare_start_records_nothing_and_leaves_no_row_behind(
    settings: Settings, bot: Bot
) -> None:
    """Somebody typing ``/start`` has no campaign, and ``None`` is the honest record.

    It must not write an empty string, a placeholder, or a row whose source is ``""`` — each of
    those would be counted as an arrival from a campaign named nothing, which is a cohort that
    does not exist.
    """
    dispatcher, profiles = wire(settings, FakeProfiles())

    await send(dispatcher, bot, "/start")

    assert USER_ID not in profiles.rows or profiles.rows[USER_ID].acquisition_source is None


@pytest.mark.parametrize(
    "payload",
    [
        "a" * 65,
        "ig bio",
        "ig/bio",
        "ig.bio",
        "igʻbio",
        "<script>",
        "ig_bio; DROP TABLE users",
    ],
    ids=["too-long", "space", "slash", "dot", "uzbek-apostrophe", "markup", "sql-ish"],
)
async def test_a_payload_telegram_could_not_have_carried_is_discarded(
    settings: Settings, bot: Bot, payload: str
) -> None:
    """Outside Telegram's ``1..64`` of ``A-Za-z0-9_-``, nothing is stored at all.

    None of these can reach us from a real ``t.me`` link — they were typed, pasted, or built by
    hand — so recording them would put arbitrary text into a column an operator reads as a
    campaign name. Discarding beats truncating: ``("a" * 65)[:64]`` is a label that looks
    plausible and means nothing.

    The Uzbek ``ʻ`` (U+02BB) is in this list on purpose. It is in the bot's own copy everywhere,
    so it is exactly the character a well-meaning person would put in a campaign slug, and it is
    exactly the one Telegram will not carry.
    """
    dispatcher, profiles = wire(settings, FakeProfiles())

    await send(dispatcher, bot, f"/start {payload}")

    assert USER_ID not in profiles.rows or profiles.rows[USER_ID].acquisition_source is None


async def test_returning_from_the_payment_page_is_not_an_acquisition(
    settings: Settings, bot: Bot
) -> None:
    """``/start paid`` is claimed by the checkout handler and never reaches the recorder.

    The guard is a filter registered one line above ``handle_start``, so this test is really
    about registration ORDER — and order is the kind of thing a later refactor reshuffles
    without noticing. If it ever does, every paying customer is re-attributed to the checkout
    rail, which would make the payment page look like the best campaign we run.
    """
    dispatcher, profiles = wire(settings, FakeProfiles())

    await send(dispatcher, bot, f"/start {PAID_DEEP_LINK}")

    assert USER_ID not in profiles.rows or profiles.rows[USER_ID].acquisition_source is None


async def test_a_store_that_refuses_the_write_does_not_stop_the_customer_arriving(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    """The label is best effort. The song is not.

    A customer who taps the bio link must reach the bot whether or not an analytics column
    could be written this second. ``run_guarded`` has already logged the failure, so the
    silence is in the flow and not in the record — the same posture ``record_avatar`` takes.
    """
    failing = FakeProfiles()
    failing.failure = StorageError("the database is having a moment")
    dispatcher, _ = wire(settings, failing)

    await send(dispatcher, bot, "/start ig_bio")

    assert session.calls, "the customer was answered with nothing at all"
