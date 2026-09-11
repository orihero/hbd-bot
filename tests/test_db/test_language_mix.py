"""``language_mix`` — the share list, its denominator, and the zero it is allowed to have.

This read is one ``GROUP BY`` and the temptation is to test it as one, which would miss the
three things that can actually go wrong with a share list:

* **The denominator drifting away from the entries it divides.** ``accounts`` is summed in
  Python over the rows the database already grouped, precisely so a second ``COUNT`` cannot
  disagree with them. That invariant is asserted on every fixture below rather than in one
  test of its own — a mix whose parts do not add up to its whole renormalises every slice.
* **A zero entry appearing for a language nobody reads.** Absence here is a presentational
  choice and NOT the null-never-zero rule, and the distinction is worth keeping straight:
  ``ui_language`` is ``NOT NULL`` over a population this statement visits in full, so "no
  account reads the bot in English" really has been measured and a zero would be a true
  number. It is left out because a 0% slice and a legend row for a language nobody uses is
  noise in a list ordered by size, not because the number is unknown.
* **The window being read as "the mix during that month".** It is not, and it cannot be:
  ``ui_language`` is a gauge with no history, so a window narrows by ``users.created_at``
  and reports what a SIGNUP COHORT reads today. The test for that names what it measures.

Accounts are inserted through the ORM with an explicit ``created_at`` and an explicit
``ui_language``, following ``test_admin_queries.py``: these tests assert counts computed by
hand from the fixture, which only means anything if the fixture's clocks and languages are
exactly what the test says rather than whatever ``ensure_user``'s authoritative-writer rule
would have left behind.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import Language
from bayram.db.admin.overview import language_mix
from bayram.db.admin.sql import TimeWindow
from bayram.db.admin.views import LanguageMix
from bayram.db.models.user import UserRow

#: Mid-day, so nothing below passes by landing on a boundary it did not mean to.
_NOW: Final[datetime] = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)

#: Telegram ids are unique and irrelevant to the mix, so they are handed out in order.
_NEXT_ID: Final[list[int]] = [70_000]


async def _account(
    sessions: async_sessionmaker[AsyncSession],
    *,
    language: Language,
    created_at: datetime = _NOW,
) -> int:
    """One account that reads the bot in ``language``, signed up at a stated instant."""
    _NEXT_ID[0] += 1
    telegram_user_id = _NEXT_ID[0]
    async with sessions.begin() as session:
        session.add(
            UserRow(
                id=uuid4(),
                telegram_user_id=telegram_user_id,
                ui_language=language,
                is_blocked=False,
                last_seen_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return telegram_user_id


# ---------------------------------------------------------------------------
# The empty deployment
# ---------------------------------------------------------------------------
async def test_a_deployment_with_no_accounts_has_no_entries_and_not_four_zeroes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act — nobody has ever spoken to this bot.
    async with sessions() as session:
        mix = await language_mix(session)

    # Assert — no entry per `Language` member at zero. A four-slice pie of nothing is a chart
    # that reports a population it does not have, and the caller that wants fixed slots can
    # build them from `Language` itself because `accounts` travels with the entries.
    assert mix.languages == ()
    # `accounts` is 0 and that is a MEASUREMENT, not a coalesced null: `ui_language` is NOT
    # NULL over a population this statement visits in full, so "no accounts exist" has been
    # counted rather than left unknown. The null-never-zero rule bites on an aggregate that
    # was never taken — see `activity_history`'s missing nights — and not on this one.
    assert mix.accounts == 0


# ---------------------------------------------------------------------------
# The shape of the list
# ---------------------------------------------------------------------------
async def test_the_entries_are_largest_first_and_a_language_nobody_reads_is_absent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three of the four languages are represented, English by nobody.
    for _ in range(3):
        await _account(sessions, language=Language.UZ_LATN)
    for _ in range(2):
        await _account(sessions, language=Language.RU)
    await _account(sessions, language=Language.UZ_CYRL)

    # Act
    async with sessions() as session:
        mix = await language_mix(session)

    # Assert — the whole tuple, in order, because the ordering IS the contract a share list
    # is read through. English is not present at zero; it is not present.
    assert mix.languages == (
        LanguageMix(language=Language.UZ_LATN, accounts=3),
        LanguageMix(language=Language.RU, accounts=2),
        LanguageMix(language=Language.UZ_CYRL, accounts=1),
    )
    assert Language.EN not in {entry.language for entry in mix.languages}


async def test_the_denominator_is_the_sum_of_the_entries_it_divides(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — an uneven mix, so a denominator taken from the wrong statement would show.
    for _ in range(4):
        await _account(sessions, language=Language.UZ_LATN)
    await _account(sessions, language=Language.EN)

    # Act
    async with sessions() as session:
        mix = await language_mix(session)

    # Assert — this is what `accounts` exists for. A share whose denominator the SPA
    # reconstructed by summing a filtered or truncated tuple renormalises to 100% of
    # whatever survived; a denominator taken as a SECOND `COUNT` could disagree with the
    # entries if a row landed between the two statements. It is neither: it is these rows.
    assert mix.accounts == 5
    assert mix.accounts == sum(entry.accounts for entry in mix.languages)


async def test_a_tie_breaks_on_the_stored_language_value_so_two_dialects_agree(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — every language on exactly one account, so `COUNT(*)` orders nothing at all
    # and the tie-break is the only thing deciding the tuple.
    for language in Language:
        await _account(sessions, language=language)

    # Act
    async with sessions() as session:
        mix = await language_mix(session)

    # Assert — the second sort key is the stored VARCHAR (`enum_type` builds no native
    # enum), so this order is byte-identical on Postgres and SQLite and a caller may compare
    # the whole tuple, as the tests above do. Declaration order would not have been: 'en' <
    # 'ru' < 'uz_cyrl' < 'uz_latn' is alphabetical and `Language` declares UZ_LATN first.
    assert [entry.language for entry in mix.languages] == [
        Language.EN,
        Language.RU,
        Language.UZ_CYRL,
        Language.UZ_LATN,
    ]
    assert {entry.accounts for entry in mix.languages} == {1}
    assert mix.accounts == 4


# ---------------------------------------------------------------------------
# What a window narrows
# ---------------------------------------------------------------------------
async def test_a_window_selects_the_signup_cohort_and_narrows_the_denominator_with_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — an older Uzbek-Latin population and a recent Russian-speaking one.
    for _ in range(3):
        await _account(sessions, language=Language.UZ_LATN, created_at=_NOW - timedelta(days=60))
    for _ in range(2):
        await _account(sessions, language=Language.RU, created_at=_NOW - timedelta(days=3))
    window = TimeWindow(start=_NOW - timedelta(days=7), end=_NOW)

    # Act
    async with sessions() as session:
        recent = await language_mix(session, window=window)
        everybody = await language_mix(session)

    # Assert — the window is on `users.created_at`, so this is "the cohort that joined in the
    # last week, as they read the bot TODAY" and not "the mix that was on screen last week":
    # `ui_language` is a gauge and a customer who switched to Russian rewrote their only row.
    # The denominator moves WITH the entries — 2, never the 5 accounts that exist — which is
    # what stops the card printing 40% under a caption naming the week.
    assert recent.languages == (LanguageMix(language=Language.RU, accounts=2),)
    assert recent.accounts == 2
    assert recent.accounts == sum(entry.accounts for entry in recent.languages)
    assert everybody.accounts == 5


async def test_a_window_in_which_nobody_signed_up_is_empty_rather_than_the_whole_table(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — every account predates the window by two months.
    for _ in range(3):
        await _account(sessions, language=Language.UZ_LATN, created_at=_NOW - timedelta(days=60))
    window = TimeWindow(start=_NOW - timedelta(days=2), end=_NOW)

    # Act
    async with sessions() as session:
        mix = await language_mix(session, window=window)

    # Assert — an empty cohort, not a silently unfiltered one. The failure this guards is a
    # window that never reached the statement, which shows up as a perfectly plausible mix.
    assert mix.languages == ()
    assert mix.accounts == 0
