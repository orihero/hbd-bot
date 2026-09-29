"""``terms_acceptances``: an idempotent accept, an anonymising ``/forget``, a narrow cutoff.

IMAGE_VIDEO_SPEC §2.1, §3.2.1, §3.2.4 and §9.3. Four properties are pinned here because each
one fails quietly if nobody looks:

* **A second accept is one row, and the first one's facts win.** The gate may see a double
  tap or a replayed update; the record of WHEN and IN WHICH LANGUAGE the text was accepted
  must not move.
* **The writer opens no ``user_profiles`` row.** Onboarding reads a profile row's existence
  as "has chosen a language" (§0.3), so a terms accept that opened one would skip the next
  customer past the language screen.
* **``/forget`` anonymises and the account can accept again.** The NULL-tolerant unique
  constraint is what lets the gate re-prompt a forgotten account and record the new accept.
* **The cutoff never reaches an identified row.** A live account's proof of acceptance must
  not age out while the account still uses the bot.
"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import Language, is_ok
from bayram.db.credit_erasure import forget_account
from bayram.db.enums import TermsAcceptanceSource
from bayram.db.models import TermsAcceptanceRow, UserProfileRow, UserRow
from bayram.db.purge import (
    TERMS_ACCEPTANCE_RETENTION_DAYS,
    purge_expired,
    rows_past_expiry_statements,
)
from bayram.db.terms import SqlTermsLedger, has_accepted, record_acceptance
from bayram.terms import TermsStanding, TermsVersions
from tests.test_db.conftest import MovableClock

#: Outside the 32-bit range, like every account id in the credit tests.
_USER: Final[int] = 8_912_345_678_901
_OTHER_USER: Final[int] = 7_112_345_678_902
_TERMS: Final[str] = "2026-10-01"
_PRIVACY: Final[str] = "2026-10-01"


async def _accept(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    *,
    user: int = _USER,
    terms: str = _TERMS,
    language: Language = Language.UZ_LATN,
    source: TermsAcceptanceSource = TermsAcceptanceSource.ONBOARDING,
) -> bool:
    async with sessions.begin() as session:
        return await record_acceptance(
            session,
            telegram_user_id=user,
            terms_version=terms,
            privacy_version=_PRIVACY,
            language=language,
            source=source,
            now=clock.now,
        )


async def _rows(sessions: async_sessionmaker[AsyncSession]) -> list[TermsAcceptanceRow]:
    async with sessions() as session:
        result = await session.scalars(
            sa.select(TermsAcceptanceRow).order_by(TermsAcceptanceRow.accepted_at)
        )
        return list(result.all())


async def _accepted(sessions: async_sessionmaker[AsyncSession], *, terms: str = _TERMS) -> bool:
    async with sessions() as session:
        return await has_accepted(
            session, telegram_user_id=_USER, terms_version=terms, privacy_version=_PRIVACY
        )


async def test_a_second_accept_writes_nothing_and_keeps_the_first_ones_facts(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    first_at = clock.now
    assert await _accept(sessions, clock) is True

    # Act — a double tap a minute later, from the other screen, in another language.
    clock.advance(seconds=60)
    again = await _accept(sessions, clock, language=Language.RU, source=TermsAcceptanceSource.GATE)

    # Assert
    assert again is False
    rows = await _rows(sessions)
    assert len(rows) == 1
    assert rows[0].accepted_at == first_at
    assert rows[0].language is Language.UZ_LATN
    assert rows[0].source is TermsAcceptanceSource.ONBOARDING


async def test_accepting_opens_no_profile_row(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Act
    await _accept(sessions, clock)

    # Assert — a profile row here would read as "language chosen" (IMAGE_VIDEO_SPEC §0.3).
    async with sessions() as session:
        profiles = await session.scalar(sa.select(sa.func.count()).select_from(UserProfileRow))
    assert profiles == 0


async def test_a_version_bump_is_not_accepted_until_it_is_accepted(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    await _accept(sessions, clock)

    # Act / Assert — the old pair stays on record beside the new one.
    assert await _accepted(sessions) is True
    assert await _accepted(sessions, terms="2026-11-01") is False
    assert await _accept(sessions, clock, terms="2026-11-01") is True
    assert await _accepted(sessions, terms="2026-11-01") is True
    assert len(await _rows(sessions)) == 2


async def test_forget_anonymises_the_acceptances_and_leaves_other_accounts_alone(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    await _accept(sessions, clock)
    await _accept(sessions, clock, terms="2026-11-01")
    await _accept(sessions, clock, user=_OTHER_USER)

    # Act
    async with sessions.begin() as session:
        erased = await forget_account(session, telegram_user_id=_USER)

    # Assert — the rows survive without their owner; the other account keeps its own.
    assert erased.terms_acceptances_anonymised == 2
    owners = [row.telegram_user_id for row in await _rows(sessions)]
    assert owners.count(None) == 2
    assert owners.count(_OTHER_USER) == 1
    assert len(owners) == 3
    assert await _accepted(sessions) is False


async def test_a_forgotten_account_can_accept_the_same_versions_again(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    await _accept(sessions, clock)
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)

    # Act — the gate re-prompts after /forget; the NULL row must not block the new accept.
    again = await _accept(sessions, clock)

    # Assert
    assert again is True
    assert await _accepted(sessions) is True
    assert len(await _rows(sessions)) == 2


async def test_the_cutoff_never_sweeps_an_identified_acceptance(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    await _accept(sessions, clock)

    # Act — years past the cutoff, the account never asked to be forgotten.
    result = await purge_expired(sessions, now=clock.advance(days=3 * 365))

    # Assert
    assert is_ok(result)
    assert result.value.terms_acceptances_deleted == 0
    assert await _accepted(sessions) is True


async def test_an_anonymised_acceptance_survives_until_the_cutoff_then_goes(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    await _accept(sessions, clock)
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER, now=clock.now)

    # Act / Assert — one day inside the cutoff, kept.
    kept = await purge_expired(
        sessions, now=clock.advance(days=TERMS_ACCEPTANCE_RETENTION_DAYS - 1)
    )
    assert is_ok(kept)
    assert kept.value.terms_acceptances_deleted == 0
    assert len(await _rows(sessions)) == 1

    # Act / Assert — past it, swept whole.
    swept = await purge_expired(sessions, now=clock.advance(days=2))
    assert is_ok(swept)
    assert swept.value.terms_acceptances_deleted == 1
    assert await _rows(sessions) == []


async def test_the_cutoff_counts_from_the_forget_not_from_the_acceptance(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """IMAGE_VIDEO_SPEC §3.2.1: kept "400 days after account deletion". An acceptance far older
    than the cutoff, forgotten today, is still kept for the full 400 days."""
    # Arrange — accepted 500 days ago, forgotten today.
    await _accept(sessions, clock)
    forgotten_at = clock.advance(days=500)
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER, now=forgotten_at)

    # Act / Assert — the next run, and one day inside the cutoff: kept.
    first = await purge_expired(sessions, now=clock.advance(days=1))
    assert is_ok(first)
    assert first.value.terms_acceptances_deleted == 0
    kept = await purge_expired(
        sessions, now=clock.advance(days=TERMS_ACCEPTANCE_RETENTION_DAYS - 2)
    )
    assert is_ok(kept)
    assert kept.value.terms_acceptances_deleted == 0
    [row] = await _rows(sessions)
    assert row.anonymised_at == forgotten_at

    # Act / Assert — 400 days after the /forget: swept.
    swept = await purge_expired(sessions, now=clock.advance(days=2))
    assert is_ok(swept)
    assert swept.value.terms_acceptances_deleted == 1
    assert await _rows(sessions) == []


async def test_the_backlog_counts_exactly_what_the_sweep_would_take(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — one anonymised and one identified acceptance, both past the cutoff.
    await _accept(sessions, clock)
    await _accept(sessions, clock, user=_OTHER_USER)
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER, now=clock.now)
    later = clock.advance(days=TERMS_ACCEPTANCE_RETENTION_DAYS + 1)

    # Act
    statements = dict(rows_past_expiry_statements(now=later))
    async with sessions() as session:
        backlog = await session.scalar(statements["terms_acceptances_deleted"])

    # Assert
    assert backlog == 1


# ---------------------------------------------------------------------------
# SqlTermsLedger — the facade the bot holds (IMAGE_VIDEO_SPEC §2.1, M1.2)
# ---------------------------------------------------------------------------
_PAIR: Final[TermsVersions] = TermsVersions(terms=_TERMS, privacy=_PRIVACY)


async def test_the_ledger_tells_never_from_outdated_from_accepted(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Three answers, because the customer reads three different sentences off them."""
    # Arrange
    ledger = SqlTermsLedger(sessions, clock=lambda: clock.now)
    bumped = TermsVersions(terms="2026-11-01", privacy=_PRIVACY)

    # Act / Assert
    never = await ledger.standing(_USER, _PAIR)
    assert is_ok(never) and never.value is TermsStanding.NEVER
    accepted = await ledger.accept(_USER, _PAIR, language=Language.RU, source="gate")
    assert is_ok(accepted)
    now_accepted = await ledger.standing(_USER, _PAIR)
    assert is_ok(now_accepted) and now_accepted.value is TermsStanding.ACCEPTED
    outdated = await ledger.standing(_USER, bumped)
    assert is_ok(outdated) and outdated.value is TermsStanding.OUTDATED
    rows = await _rows(sessions)
    assert [(row.language, row.source) for row in rows] == [
        (Language.RU, TermsAcceptanceSource.GATE)
    ]


async def test_the_ledger_accept_opens_no_profile_and_no_user_row(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The row-existence bug (IMAGE_VIDEO_SPEC §0.3), through the facade the bot really calls."""
    # Arrange
    ledger = SqlTermsLedger(sessions, clock=lambda: clock.now)

    # Act
    result = await ledger.accept(_USER, _PAIR, language=Language.EN, source="onboarding")

    # Assert
    assert is_ok(result)
    async with sessions() as session:
        profiles = await session.scalar(sa.select(sa.func.count()).select_from(UserProfileRow))
        users = await session.scalar(sa.select(sa.func.count()).select_from(UserRow))
    assert (profiles, users) == (0, 0)


async def test_a_forgotten_account_stands_nowhere(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """After ``/forget`` the gate asks again: the anonymised row names nobody."""
    # Arrange
    ledger = SqlTermsLedger(sessions, clock=lambda: clock.now)
    await ledger.accept(_USER, _PAIR, language=Language.EN, source="onboarding")

    # Act
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)
    standing = await ledger.standing(_USER, _PAIR)

    # Assert
    assert is_ok(standing) and standing.value is TermsStanding.NEVER
