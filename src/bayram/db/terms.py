"""Queries over ``terms_acceptances`` (IMAGE_VIDEO_SPEC §2.1, §3.2.1).

Three statements and no more: record an acceptance, ask whether an account has accepted a
version pair, and take the identity off an account's acceptances on ``/forget``. The gate,
the Redis cache in front of it (``terms:ok:{tg}``) and the screens are the bot's (M1.2); this
module is only what they read and write.

**Nothing here touches ``user_profiles``.** Onboarding infers "has chosen a language" from a
profile row existing (IMAGE_VIDEO_SPEC §0.3), and the terms step sits between the language
picker and the contact screen — a writer here that opened a profile row would skip the next
new customer past the language screen. The ``language`` recorded on an acceptance is passed
in by the caller, never looked up from a profile.

Session first and positional, exceptions propagate, and **nothing is committed here**: the
caller owns the transaction, matching :mod:`bayram.db.topup_sql`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.contracts import Language
from bayram.db.credit_sql import rowcount_of, upsert_statement
from bayram.db.enums import TermsAcceptanceSource
from bayram.db.models.terms_acceptance import TermsAcceptanceRow

__all__ = ["anonymise_terms_acceptances", "has_accepted", "record_acceptance"]

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
