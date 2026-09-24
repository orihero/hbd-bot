"""Queries over ``terms_acceptances`` (IMAGE_VIDEO_SPEC §2.1, §3.2.1).

Four statements and no more: record an acceptance, ask whether an account has accepted a
version pair, ask where it stands against one (accepted / an older pair / never), and take the
identity off an account's acceptances on ``/forget``. The gate, the Redis cache in front of it
(``terms:ok:{tg}``) and the screens are the bot's (``bayram.terms``, M1.2); this module is only
what they read and write, plus :class:`SqlTermsLedger`, the never-throw facade the bot holds
through :class:`bayram.terms.TermsLedger`.

**Nothing here touches ``user_profiles``.** Onboarding infers "has chosen a language" from a
profile row existing (IMAGE_VIDEO_SPEC §0.3), and the terms step sits between the language
picker and the contact screen — a writer here that opened a profile row would skip the next
new customer past the language screen. The ``language`` recorded on an acceptance is passed
in by the caller, never looked up from a profile.

The free functions are session first and positional, let exceptions propagate, and **commit
nothing**: the caller owns the transaction, matching :mod:`bayram.db.topup_sql`. The facade
owns one transaction per call and never raises, matching
:class:`bayram.db.user_profiles.SqlUserProfiles`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import Language, Result
from bayram.db.base import utc_now
from bayram.db.credit_sql import rowcount_of, upsert_statement
from bayram.db.enums import TermsAcceptanceSource
from bayram.db.guard import run_guarded
from bayram.db.models.terms_acceptance import TermsAcceptanceRow
from bayram.terms import TermsSource, TermsStanding, TermsVersions

__all__ = [
    "SqlTermsLedger",
    "acceptance_standing",
    "anonymise_terms_acceptances",
    "has_accepted",
    "record_acceptance",
]

#: The UNIQUE's columns, which ``ON CONFLICT`` must name exactly.
_CONFLICT_COLUMNS: tuple[str, ...] = ("telegram_user_id", "terms_version", "privacy_version")


async def record_acceptance(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    terms_version: str,
    privacy_version: str,
    language: Language,
    source: TermsAcceptanceSource,
    now: datetime,
) -> bool:
    """Record that this account accepted this version pair. True when a row was written.

    ONE STATEMENT, ``INSERT … ON CONFLICT DO NOTHING`` on the table's unique constraint, so a
    second tap of ✅, a replayed update or two processes racing the same accept leave exactly
    one row — and the FIRST acceptance's instant, language and screen, which are the facts a
    dispute asks about. False means the pair was already on record; the caller treats both
    answers as "accepted".
    """
    statement = upsert_statement(
        session,
        TermsAcceptanceRow,
        {
            "id": uuid4(),
            "telegram_user_id": telegram_user_id,
            "terms_version": terms_version,
            "privacy_version": privacy_version,
            "language": language,
            "accepted_at": now,
            "source": source,
        },
        index_elements=_CONFLICT_COLUMNS,
        set_=None,
    )
    return rowcount_of(await session.execute(statement)) == 1


async def has_accepted(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    terms_version: str,
    privacy_version: str,
) -> bool:
    """Whether this account has accepted exactly this version pair.

    An exact match rather than "the latest row": versions are dates written by the owner and
    a bump may move either one alone, so "accepted something at least this new" is a
    comparison this table has no business making. Served by the unique constraint, whose
    leading column is ``telegram_user_id``.
    """
    found = await session.scalar(
        sa.select(sa.literal(True))
        .select_from(TermsAcceptanceRow)
        .where(
            TermsAcceptanceRow.telegram_user_id == telegram_user_id,
            TermsAcceptanceRow.terms_version == terms_version,
            TermsAcceptanceRow.privacy_version == privacy_version,
        )
        .limit(1)
    )
    return found is True


async def acceptance_standing(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    terms_version: str,
    privacy_version: str,
) -> TermsStanding:
    """Accepted this exact pair, an earlier one only, or nothing at all.

    ONE statement: every pair the account has on record, which is a handful of rows at most
    (one per version bump it lived through). The distinction between ``OUTDATED`` and ``NEVER``
    is only which sentence the customer reads — ``terms.updated`` or ``terms.gate`` — so it is
    not worth a second round trip, and it is not worth a ``GROUP BY`` either.
    """
    pairs = (
        await session.execute(
            sa.select(TermsAcceptanceRow.terms_version, TermsAcceptanceRow.privacy_version).where(
                TermsAcceptanceRow.telegram_user_id == telegram_user_id
            )
        )
    ).all()
    if not pairs:
        return TermsStanding.NEVER
    if any(terms == terms_version and privacy == privacy_version for terms, privacy in pairs):
        return TermsStanding.ACCEPTED
    return TermsStanding.OUTDATED


async def anonymise_terms_acceptances(session: AsyncSession, *, telegram_user_id: int) -> int:
    """Strip the account off its acceptances, keeping every row. Rows touched.

    The third retention route (IMAGE_VIDEO_SPEC §3.2.4), ``broadcast_recipients``' treatment:
    the id comes off and the versions, the language, the screen and the instant stay as an
    anonymous record that SOMEONE accepted that text then. Deleting instead would make the
    acceptance count for a version shrink retroactively by the number of people who have
    since asked to be forgotten. The anonymous row leaves on the 400-day cutoff in
    :mod:`bayram.db.purge`.

    The Redis cache ``terms:ok:{tg}`` is the caller's to delete in the same ``/forget`` arm
    (IMAGE_VIDEO_SPEC §9.3); without that, a forgotten account would skip the terms screen
    until the cache expired.
    """
    result = await session.execute(
        sa.update(TermsAcceptanceRow)
        .where(TermsAcceptanceRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    return rowcount_of(result)


class SqlTermsLedger:
    """:class:`bayram.terms.TermsLedger` over ``terms_acceptances``. Never raises.

    Owns its transactions and its clock. **It touches no other table** — in particular it never
    opens a ``user_profiles`` or a ``users`` row (IMAGE_VIDEO_SPEC §0.3): the terms step runs
    before the contact screen, and a row opened here would read to onboarding as a language
    choice the customer never made.
    """

    __slots__ = ("_clock", "_sessions")

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = session_factory
        self._clock = clock

    async def standing(
        self, telegram_user_id: int, versions: TermsVersions
    ) -> Result[TermsStanding]:
        async def work() -> TermsStanding:
            async with self._sessions() as session:
                return await acceptance_standing(
                    session,
                    telegram_user_id=telegram_user_id,
                    terms_version=versions.terms,
                    privacy_version=versions.privacy,
                )

        return await run_guarded("terms_standing", work, telegram_user_id=telegram_user_id)

    async def accept(
        self,
        telegram_user_id: int,
        versions: TermsVersions,
        *,
        language: Language,
        source: TermsSource,
    ) -> Result[None]:
        now = self._clock()

        async def work() -> None:
            async with self._sessions.begin() as session:
                await record_acceptance(
                    session,
                    telegram_user_id=telegram_user_id,
                    terms_version=versions.terms,
                    privacy_version=versions.privacy,
                    language=language,
                    source=TermsAcceptanceSource(source),
                    now=now,
                )

        return await run_guarded("terms_accept", work, telegram_user_id=telegram_user_id)
