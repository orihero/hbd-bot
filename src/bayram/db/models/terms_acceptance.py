"""``terms_acceptances`` — who accepted which Terms of Use and Privacy Notice, and when.

The record behind the Terms + Privacy gate every account passes before first use
(IMAGE_VIDEO_SPEC §2.1, D26). It is the LAWFUL-BASIS RECORD: when someone asks months later
"did this person agree to the rules the photo they uploaded was screened under?", a row here
is the only answer, which is why it is kept for as long as the account is and never on a
clock (§3.2.1).

**APPEND-ONLY, AND ONE ROW PER (ACCOUNT, TERMS VERSION, PRIVACY VERSION).** A version bump
re-prompts everyone, and the acceptance of the new pair is a NEW row beside the old one — the
old row is the proof of what the account agreed to before the bump and is never overwritten.
``UNIQUE (telegram_user_id, terms_version, privacy_version)`` makes a second tap of ✅, a
replayed update or two processes racing an accept one row and not two, so the writer
(:func:`bayram.db.terms.record_acceptance`) is a single ``INSERT … ON CONFLICT DO NOTHING``.
That constraint's leading column is ``telegram_user_id``, so it is also the index the gate's
"has this account accepted?" lookup and ``/forget``'s anonymising ``UPDATE`` read; a separate
single-column index on it would be a second copy of the same B-tree.

**IT MUST NOT OPEN A ``user_profiles`` ROW, AND IT HAS NO FOREIGN KEY TO ONE.** Onboarding
infers "has chosen a language" from a profile row existing (IMAGE_VIDEO_SPEC §0.3), and the
terms screen sits between the language picker and the contact step, so a writer that
created a profile row here would skip the next customer past the language screen. No foreign
key to ``users`` either, following every other table that holds this column: the record must
outlive the account row.

**THE THIRD RETENTION ROUTE** (IMAGE_VIDEO_SPEC §3.2.4), on ``broadcast_recipients``'
footing: identity leaves by ``/forget``'s anonymisation arm
(:func:`bayram.db.credit_erasure.forget_account`), which nulls ``telegram_user_id`` in place —
the UNIQUE tolerates any number of NULLs on both engines, so an anonymised row stops
participating in it — and growth is bounded by a 400-day cutoff over ANONYMISED rows only
(``bayram.db.purge.TERMS_ACCEPTANCE_RETENTION_DAYS``). An identified row is never swept: a
live account's proof of acceptance must not age out while the account still uses the bot.
No column ends in ``*_expires_at`` because nothing here is a published per-row clock.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import Language
from bayram.db.base import Base, UtcDateTime, enum_type, utc_now
from bayram.db.enums import TermsAcceptanceSource

__all__ = ["TermsAcceptanceRow", "UNIQUE_ACCEPTANCE_CONSTRAINT", "VERSION_LENGTH"]

#: ``BAYRAM_TERMS_VERSION`` / ``BAYRAM_PRIVACY_VERSION`` are dates such as ``2026-10-01``; 32
#: leaves room for a suffix (``2026-10-01-r2``) without inviting prose.
VERSION_LENGTH: Final[int] = 32

#: The idempotency constraint's name. See ``__table_args__`` on why it is not templated.
UNIQUE_ACCEPTANCE_CONSTRAINT: Final[str] = "uq_terms_acceptances_account_versions"

#: The longest ``Language`` value is ``uz_latn``, seven characters.
_LANGUAGE_LENGTH: Final[int] = 8

#: ``onboarding`` or ``gate``.
_SOURCE_LENGTH: Final[int] = 16


class TermsAcceptanceRow(Base):
    """One account's acceptance of one (Terms, Privacy) version pair.

    No ``TimestampMixin``: the row is never updated except by ``/forget``, and the one clock
    it needs is the acceptance instant, named for what it records.
    """

    __tablename__ = "terms_acceptances"
    __table_args__ = (
        # HAND-NAMED, unlike most constraints here: ``NAMING_CONVENTION``'s ``uq`` template
        # would render a 67-character name, past Postgres's 63-character identifier limit,
        # which Postgres truncates silently and SQLite does not — so the two engines would
        # disagree about the name a later migration has to drop. Spelled identically in 0030.
        sa.UniqueConstraint(
            "telegram_user_id",
            "terms_version",
            "privacy_version",
            name=UNIQUE_ACCEPTANCE_CONSTRAINT,
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: Who. **NULLABLE ONLY SO THAT ERASURE HAS SOMEWHERE TO GO** — the accept handler always
    #: knows the account, so a NULL means one thing only: ``/forget`` ran.
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    terms_version: Mapped[str] = mapped_column(sa.String(VERSION_LENGTH), nullable=False)
    privacy_version: Mapped[str] = mapped_column(sa.String(VERSION_LENGTH), nullable=False)
    #: The language the text was SHOWN in, which is part of what was agreed to: the uz, ru
    #: and en texts are translations, and a dispute about a clause is a dispute about one of
    #: them.
    language: Mapped[Language] = mapped_column(
        enum_type(Language, length=_LANGUAGE_LENGTH), nullable=False
    )
    #: Indexed for the retention cutoff, which selects anonymised rows by this clock.
    accepted_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
    #: Which screen took the tap. Nullable as IMAGE_VIDEO_SPEC §3.2.1 specifies; the writer
    #: always supplies it.
    source: Mapped[TermsAcceptanceSource | None] = mapped_column(
        enum_type(TermsAcceptanceSource, length=_SOURCE_LENGTH), nullable=True
    )
