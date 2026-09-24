"""``media_jobs`` — one customer request for images or a video (IMAGE_VIDEO_SPEC §3.2.2).

A separate table from ``orders`` rather than a new order kind, because ``orders`` feeds the
song metrics (28 references in the admin metrics module), ``assets.order_id`` is a NOT NULL
foreign key and ``generation_attempts`` tunes the name strategy — a media row in any of them
would be counted as a song somewhere (§0.1).

**THE STATE MACHINE IS THE ROW'S OWN.** ``state`` walks §3.3's chain, and every move after
``paid`` is a conditional ``UPDATE … WHERE id = :id AND state IN (<expected>)`` issued by
:func:`bayram.db.media.transition`; rowcount 0 means another path (the deadline sweep,
``/forget``, an output block) got there first and the caller becomes a no-op. The partial
unique index :data:`OPEN_REQUEST_INDEX` allows one OPEN request per (account, kind); no code
path moves a terminal row back into that set, so it can never fire inside the Payme money
commit (§7.2 step 3).

**THE TEXT IS ON A CLOCK, THE ROW IS NOT (yet).** ``prompt``, ``narration_text`` and
``voice_transcript`` are what the customer wrote or said, and are nulled together when
``text_expires_at`` passes (§3.2.4) or on ``/forget``; ``text_purged_at`` is the proof. The
clock is stamped at insert (created + quote TTL + 30 d) and moved to terminal + 30 d by the
same UPDATE that sets any terminal state. An UNPAID terminal row (rejected, cancelled,
abandoned) is deleted whole once that clock has run; a paid one keeps its row, with the text
gone, as the record of a sale.

**PRIVACY** — in ``tables_with_personal_data`` (``tests/test_db/test_privacy_constraints.py``):
the three text columns are free text about real people, and ``text_expires_at`` is the clock
that obliges a sweep by name. ``params`` carries geometry and seeds and **never text**.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import Language
from bayram.db.base import SHA256_LENGTH, Base, UtcDateTime, enum_type, utc_now
from bayram.db.enums import (
    MEDIA_OPEN_STATES,
    MediaAspect,
    MediaBackend,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaRefundState,
    MediaScreenDecision,
    MediaSku,
    MediaTier,
    MediaVoiceGender,
    MediaVoiceMode,
)

__all__ = [
    "MediaJobRow",
    "OPEN_REQUEST_INDEX",
    "OPEN_REQUEST_PREDICATE",
    "PROMPT_LENGTH",
    "NARRATION_LENGTH",
    "TRANSCRIPT_LENGTH",
    "FAILED_REASON_LENGTH",
    "MEDIA_ERROR_CODE_LENGTH",
]

#: §1.3: a prompt is 3–800 characters.
PROMPT_LENGTH: Final[int] = 800
#: ~12 words is the ceiling for a 5-second narration (O14); 160 leaves room for Uzbek.
NARRATION_LENGTH: Final[int] = 160
#: The whisper text of an own voice note, capped by the clip length.
TRANSCRIPT_LENGTH: Final[int] = 400
#: ``_SAFE_CONTEXT_KEYS`` text only — never a vendor body, which can quote the prompt back.
FAILED_REASON_LENGTH: Final[int] = 256
#: A closed ``bayram.errors`` code, as on ``vendor_usage``.
MEDIA_ERROR_CODE_LENGTH: Final[int] = 48

#: One open request per (account, kind), §7.6. Hand-named and spelled identically in 0031.
OPEN_REQUEST_INDEX: Final[str] = "ix_media_jobs_one_open_request"
#: The predicate, rendered from the enum ONCE here; revision 0031 spells the same literals
#: (DDL outlives the class). ``IN (…)`` over string literals renders on both engines.
OPEN_REQUEST_PREDICATE: Final[str] = "state IN ({})".format(
    ", ".join(f"'{state.value}'" for state in sorted(MEDIA_OPEN_STATES))
)

_SHORT_ENUM: Final[int] = 16
_STATE_LENGTH: Final[int] = 24
_ASPECT_LENGTH: Final[int] = 8
_LANGUAGE_LENGTH: Final[int] = 8
_MODEL_ID_LENGTH: Final[int] = 64
_POLICY_VERSION_LENGTH: Final[int] = 32


class MediaJobRow(Base):
    """One image or video request, from the frozen draft to delivery or refund."""

    __tablename__ = "media_jobs"
    __table_args__ = (
        sa.CheckConstraint("outputs_requested BETWEEN 1 AND 4", name="outputs_requested_in_range"),
        # Zero is legal (the free beta quotes nothing); a negative price is a refund wearing
        # a quote's shape, and refunds are credits on their own ledger (§7.5).
        sa.CheckConstraint("price_minor >= 0", name="price_not_negative"),
        # The three list reads §3.2.2 names: the sweep by state, a customer's history, and
        # the finance series by SKU. ``id`` last so a keyset page is index-only.
        sa.Index("ix_media_jobs_state_created", "state", "created_at", "id"),
        sa.Index("ix_media_jobs_user_created", "telegram_user_id", "created_at", "id"),
        sa.Index("ix_media_jobs_sku_created", "sku", "created_at", "id"),
        # ONE OPEN REQUEST PER (ACCOUNT, KIND), enforced by the database (§7.6). Partial: any
        # number of finished requests coexist.
        sa.Index(
            OPEN_REQUEST_INDEX,
            "telegram_user_id",
            "kind",
            unique=True,
            postgresql_where=sa.text(OPEN_REQUEST_PREDICATE),
            sqlite_where=sa.text(OPEN_REQUEST_PREDICATE),
        ),
    )

    #: Also the D17-style resume marker on ``payment_intents.resume_media_job_id`` and the
    #: seed of every ARQ job id for this request (§3.3).
    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Leading column of the history index and of the open-request index, so no index of
    #: its own.
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    kind: Mapped[MediaKind] = mapped_column(
        enum_type(MediaKind, length=_SHORT_ENUM), nullable=False
    )
    #: Video only.
    tier: Mapped[MediaTier | None] = mapped_column(
        enum_type(MediaTier, length=_SHORT_ENUM), nullable=True
    )
    sku: Mapped[MediaSku] = mapped_column(enum_type(MediaSku), nullable=False)
    state: Mapped[MediaJobState] = mapped_column(
        enum_type(MediaJobState, length=_STATE_LENGTH), nullable=False
    )
    #: Where the worker edits and delivers.
    chat_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    #: The tray the worker turns into quote / refusal / busy.
    tray_message_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: The progress message (§3.3 Progress).
    status_message_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: Hash of prompt + narration + every input ``sha256``, written by ``media_screen``;
    #: ``media_start`` re-checks it so what runs is exactly what was screened (§2.3.1).
    content_sha256: Mapped[str | None] = mapped_column(sa.String(SHA256_LENGTH), nullable=True)
    #: Monotonic suffixes for deliberate ARQ re-enqueues (§3.3): ARQ silently drops an
    #: enqueue whose id it still remembers, so a re-run needs a new one.
    submit_seq: Mapped[int] = mapped_column(
        sa.SmallInteger, nullable=False, default=0, server_default=sa.text("0")
    )
    oscreen_seq: Mapped[int] = mapped_column(
        sa.SmallInteger, nullable=False, default=0, server_default=sa.text("0")
    )
    #: 2 for an image request, 1 for a video (§1.3).
    outputs_requested: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    aspect: Mapped[MediaAspect] = mapped_column(
        enum_type(MediaAspect, length=_ASPECT_LENGTH), nullable=False
    )
    #: Width, height, length, fps, steps, denoise, seed — **no text**, ever.
    params: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False, default=dict)
    #: Stamped at submit.
    backend: Mapped[MediaBackend | None] = mapped_column(
        enum_type(MediaBackend, length=_SHORT_ENUM), nullable=True
    )
    model_id: Mapped[str | None] = mapped_column(sa.String(_MODEL_ID_LENGTH), nullable=True)
    language: Mapped[Language] = mapped_column(
        enum_type(Language, length=_LANGUAGE_LENGTH), nullable=False
    )

    # -- the customer's words: on ``text_expires_at``, nulled together -------------------
    prompt: Mapped[str | None] = mapped_column(sa.String(PROMPT_LENGTH), nullable=True)
    voice_mode: Mapped[MediaVoiceMode] = mapped_column(
        enum_type(MediaVoiceMode, length=_SHORT_ENUM), nullable=False
    )
    voice_gender: Mapped[MediaVoiceGender | None] = mapped_column(
        enum_type(MediaVoiceGender, length=_ASPECT_LENGTH), nullable=True
    )
    narration_text: Mapped[str | None] = mapped_column(sa.String(NARRATION_LENGTH), nullable=True)
    voice_transcript: Mapped[str | None] = mapped_column(
        sa.String(TRANSCRIPT_LENGTH), nullable=True
    )
    #: THE TEXT CLOCK. Indexed for the purge; read by ``_media_job_texts_due`` and by the
    #: unpaid-terminal row sweep.
    text_expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    text_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- screening: closed codes only (§6.3) ----------------------------------------------
    #: 16 rather than §3.2.2's 8: ``unavailable`` is eleven characters.
    screen_decision: Mapped[MediaScreenDecision | None] = mapped_column(
        enum_type(MediaScreenDecision, length=_SHORT_ENUM), nullable=True
    )
    screen_categories: Mapped[list[str] | None] = mapped_column(
        sa.JSON(none_as_null=True), nullable=True
    )
    screen_policy_version: Mapped[str | None] = mapped_column(
        sa.String(_POLICY_VERSION_LENGTH), nullable=True
    )
    output_decision: Mapped[MediaScreenDecision | None] = mapped_column(
        enum_type(MediaScreenDecision, length=_SHORT_ENUM), nullable=True
    )
    output_categories: Mapped[list[str] | None] = mapped_column(
        sa.JSON(none_as_null=True), nullable=True
    )

    # -- money ----------------------------------------------------------------------------
    #: Snapshotted at quote, so a price change never moves an open quote.
    price_minor: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    #: No foreign key (0006/0015/0020/0023 precedent).
    payment_intent_id: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True)
    paid_via: Mapped[MediaPaidVia | None] = mapped_column(
        enum_type(MediaPaidVia, length=_SHORT_ENUM), nullable=True
    )

    # -- fan-in, failure, refund, erasure -------------------------------------------------
    render_ready_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    audio_ready_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(
        sa.String(MEDIA_ERROR_CODE_LENGTH), nullable=True
    )
    failed_reason: Mapped[str | None] = mapped_column(
        sa.String(FAILED_REASON_LENGTH), nullable=True
    )
    #: The refund latch: NULL → ``due`` by conditional UPDATE, then ``granted`` (§3.2.2).
    refund_state: Mapped[MediaRefundState | None] = mapped_column(
        enum_type(MediaRefundState, length=_SHORT_ENUM), nullable=True
    )
    #: Set by ``/forget`` on a paid, unfinished job: it is not delivered and is purged at its
    #: next stage boundary (§9.3).
    forget_requested_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- clocks ---------------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
    quoted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
