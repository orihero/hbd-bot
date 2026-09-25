"""Queries over the media tables (IMAGE_VIDEO_SPEC §3.2.2, §3.3, §7.2, §7.5).

The data half of the image and video products. The stage jobs (M2.4), the bot's compose flow
(M2.5) and the settlement path (M5) are this module's callers; none of them writes a
``media_*`` row any other way, so the invariants below hold because there is one writer.

**Every state move is conditional.** :func:`transition` is ``UPDATE … WHERE id = :id AND
state IN (<expected>)`` and answers whether THIS caller moved the row; rowcount 0 means
another path (the deadline sweep, ``/forget``, an output block) got there first and the caller
must become a no-op — release the GPU lock, discard what it holds, never deliver or refund
(§3.2.2 "State guards"). It refuses outright to move a terminal row back into an open state:
the partial unique index over the open states could otherwise fire inside the Payme money
commit (§7.2 step 3).

**Setting a terminal state moves the text clock in the same statement** (§3.2.4): terminal +
``retention_media_output_days``. Payment resets the inputs' backstop clock in the same
transaction as ``→ paid`` (:func:`mark_paid`).

**A job refunds at most once, whatever the reason** (:func:`grant_refund`): the claim on
``media_jobs.refund_state`` comes first, and two partial unique indexes on the ledger back it.

**Legal-hold rows are never touched here except by :func:`place_legal_hold`** (§6.7): every
delete in this module and in the purge carries ``retention_class <> 'legal_hold'``.

Shape follows :mod:`bayram.db.terms` and :mod:`bayram.db.topup_sql`: session first, exceptions
propagate, and **nothing is committed here** — the caller owns the transaction, which is what
lets a spend's four writes be atomic. Functions that delete rows whose bytes live in object
storage return the keys; the caller deletes the objects AFTER its commit, so a crash leaves an
orphaned object (sweepable) rather than a row pointing at nothing (§3.6, ``bayram.db.purge``).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.contracts import CostSource, Language
from bayram.db.credit_sql import rowcount_of, upsert_statement
from bayram.db.enums import (
    MEDIA_OPEN_STATES,
    MEDIA_PREPAY_STATES,
    MEDIA_TERMINAL_STATES,
    MediaAspect,
    MediaAttemptStage,
    MediaAttemptStatus,
    MediaCreditReason,
    MediaInputRole,
    MediaJobState,
    MediaKind,
    MediaLegalHoldDecision,
    MediaOutputRole,
    MediaPaidVia,
    MediaPurchaseProvider,
    MediaRefundState,
    MediaSku,
    MediaTier,
    MediaVoiceGender,
    MediaVoiceMode,
)
from bayram.db.models.media_attempt import MediaAttemptRow
from bayram.db.models.media_credit import MediaCreditBalanceRow, MediaCreditLedgerRow
from bayram.db.models.media_input import MediaInputRow, MediaOutputRow
from bayram.db.models.media_job import CSAM_BLOCKED_ERROR_CODE, MediaJobRow
from bayram.db.models.media_purchase import MediaPurchaseRow
from bayram.db.retention import DEFAULT_RETENTION_POLICY, RetentionClass, RetentionPolicy

__all__ = [
    "MEDIA_REVIEW_SLA",
    "INTERMEDIATE_OUTPUT_ROLES",
    "create_job",
    "load_job",
    "transition",
    "update_draft",
    "delete_inputs",
    "mark_paid",
    "cancel_prepay_jobs",
    "add_input",
    "record_input_stored",
    "add_output",
    "place_legal_hold",
    "record_legal_hold_decision",
    "has_standing_csam_block",
    "clear_csam_blocks",
    "cleanup_job_media",
    "insert_attempt",
    "set_attempt_status",
    "list_inputs",
    "list_outputs",
    "find_attempt",
    "latest_attempts",
    "bump_seq",
    "touch_job",
    "record_output_file_id",
    "average_run_ms",
    "record_purchase",
    "media_balance",
    "grant_refund",
    "spend_credit",
]

#: The human-review window a held output may wait (§3.2.2, §6.6). Part of how long a paid
#: job's uploads are kept: ``paid_at`` + the SKU's deadline + this.
MEDIA_REVIEW_SLA: Final[timedelta] = timedelta(hours=24)

#: Outputs that exist only to be combined: 24 hours, and ``media_cleanup`` takes them (§3.2.4).
INTERMEDIATE_OUTPUT_ROLES: Final[frozenset[MediaOutputRole]] = frozenset(
    {MediaOutputRole.VIDEO_RAW, MediaOutputRole.NARRATION}
)

#: Who a ledger movement is attributed to when no operator is involved.
_WORKER_ACTOR: Final[str] = "worker"

#: The rows a refund may be granted for: something was paid for them. A beta job is free and
#: its failure grants nothing (§7.5, M5.1); a job nobody paid for can only be refunded by a
#: late settlement, which is money arriving for a request we already cancelled.
_REFUNDABLE_PAID_VIA: Final[frozenset[MediaPaidVia]] = frozenset(
    {MediaPaidVia.PAYME, MediaPaidVia.CREDIT}
)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
async def create_job(
    session: AsyncSession,
    *,
    user_id: UUID,
    telegram_user_id: int,
    kind: MediaKind,
    sku: MediaSku,
    state: MediaJobState,
    chat_id: int,
    outputs_requested: int,
    aspect: MediaAspect,
    language: Language,
    prompt: str,
    price_minor: int,
    currency: str,
    now: datetime,
    quote_ttl: timedelta,
    tier: MediaTier | None = None,
    params: Mapping[str, Any] | None = None,
    voice_mode: MediaVoiceMode = MediaVoiceMode.NONE,
    voice_gender: MediaVoiceGender | None = None,
    narration_text: str | None = None,
    tray_message_id: int | None = None,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> UUID:
    """Insert a frozen draft. Returns its id.

    ``state`` is ``drafting`` (video) or ``screening`` (image), and nothing else: a row is
    born open. ``text_expires_at`` is ``now`` + the quote TTL + the output period (§3.2.2), so
    an abandoned draft's prompt is gone on the same schedule a delivered one's is.

    Raises ``IntegrityError`` when the account already has an open request of this kind — the
    partial unique index (§7.6). Freezing cancels earlier PRE-PAY rows first
    (:func:`cancel_prepay_jobs`), so what that error means is "a paid request is still open".
    """
    if state not in (MediaJobState.DRAFTING, MediaJobState.SCREENING):
        raise ValueError(f"a media job is created drafting or screening, not {state}")
    job_id = uuid4()
    session.add(
        MediaJobRow(
            id=job_id,
            user_id=user_id,
            telegram_user_id=telegram_user_id,
            kind=kind,
            tier=tier,
            sku=sku,
            state=state,
            chat_id=chat_id,
            tray_message_id=tray_message_id,
            outputs_requested=outputs_requested,
            aspect=aspect,
            params=dict(params or {}),
            language=language,
            prompt=prompt,
            voice_mode=voice_mode,
            voice_gender=voice_gender,
            narration_text=narration_text,
            text_expires_at=policy.media_output_expires_at(now + quote_ttl),
            price_minor=price_minor,
            currency=currency,
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()
    return job_id


async def load_job(session: AsyncSession, job_id: UUID) -> MediaJobRow | None:
    """The row as the database holds it now, not the identity map's copy.

    ``populate_existing`` because every caller reads AFTER a Core ``UPDATE`` in the same
    transaction, and a plain ``session.get`` would hand back the stale object.
    """
    return await session.get(MediaJobRow, job_id, populate_existing=True)


async def transition(
    session: AsyncSession,
    job_id: UUID,
    *,
    expected: Collection[MediaJobState],
    to: MediaJobState,
    now: datetime,
    values: Mapping[str, Any] | None = None,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> bool:
    """Move ``job_id`` to ``to`` iff it is in ``expected``. True when THIS call moved it.

    ``values`` rides the same statement (``error_code``, ``started_at``, …). A terminal ``to``
    also moves ``text_expires_at`` to ``now`` + the output period (§3.2.4).
    """
    if to in MEDIA_OPEN_STATES and any(state in MEDIA_TERMINAL_STATES for state in expected):
        # Forward-only (§3.2.2): a terminal row re-opened could collide with the one-open-
        # request index inside the Payme money commit.
        raise ValueError(f"a terminal media job never moves back to {to}")
    extra: dict[str, Any] = dict(values or {})
    if to in MEDIA_TERMINAL_STATES:
        extra["text_expires_at"] = policy.media_output_expires_at(now)
    result = await session.execute(
        sa.update(MediaJobRow)
        .where(MediaJobRow.id == job_id, MediaJobRow.state.in_(tuple(expected)))
        .values(state=to, updated_at=now, **extra)
    )
    return rowcount_of(result) == 1


async def update_draft(
    session: AsyncSession, job_id: UUID, *, now: datetime, values: Mapping[str, Any]
) -> bool:
    """Write a video draft's choices onto its row — only while it is ``drafting`` (§2.4.1).

    The voice steps write ``voice_mode``, ``voice_gender`` and ``narration_text`` here and
    nowhere else: once the row has moved on (screening, cancelled), it is never edited in
    place (§2.3.1). True when the row was a draft and took the values.
    """
    result = await session.execute(
        sa.update(MediaJobRow)
        .where(MediaJobRow.id == job_id, MediaJobRow.state == MediaJobState.DRAFTING)
        .values(updated_at=now, **dict(values))
    )
    return rowcount_of(result) == 1


async def delete_inputs(
    session: AsyncSession, job_id: UUID, *, role: MediaInputRole
) -> tuple[str, ...]:
    """Delete one role's input rows of a job (not under legal hold). The object keys, for
    the caller to delete after its commit — an own voice note refused for its length (§5.4)."""
    rows = (
        await session.execute(
            sa.select(MediaInputRow.id, MediaInputRow.storage_key).where(
                MediaInputRow.job_id == job_id,
                MediaInputRow.role == role,
                MediaInputRow.retention_class != RetentionClass.LEGAL_HOLD,
            )
        )
    ).all()
    if rows:
        await session.execute(
            sa.delete(MediaInputRow).where(MediaInputRow.id.in_([row_id for row_id, _ in rows]))
        )
    return tuple(key for _, key in rows if key is not None)


async def mark_paid(
    session: AsyncSession,
    job_id: UUID,
    *,
    paid_via: MediaPaidVia,
    now: datetime,
    deadline: timedelta,
    expected: Collection[MediaJobState] = (MediaJobState.QUOTED, MediaJobState.AWAITING_PAYMENT),
    values: Mapping[str, Any] | None = None,
) -> bool:
    """``quoted``/``awaiting_payment`` → ``paid``, and reset the uploads' backstop clock.

    ONE transaction, the caller's (§3.2.2): an upload's ``expires_at`` becomes ``now`` + the
    SKU's ``deadline`` + :data:`MEDIA_REVIEW_SLA`, so a customer who pays late in the quote
    window keeps their photos until the job is done. Legal-hold rows keep their own clock.
    False — and nothing reset — when the job was not in ``expected``.
    """
    moved = await transition(
        session,
        job_id,
        expected=expected,
        to=MediaJobState.PAID,
        now=now,
        values={"paid_via": paid_via, "paid_at": now, **dict(values or {})},
    )
    if not moved:
        return False
    await session.execute(
        sa.update(MediaInputRow)
        .where(
            MediaInputRow.job_id == job_id,
            MediaInputRow.retention_class != RetentionClass.LEGAL_HOLD,
        )
        .values(expires_at=now + deadline + MEDIA_REVIEW_SLA)
    )
    return True


async def cancel_prepay_jobs(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    now: datetime,
    kind: MediaKind | None = None,
    states: Collection[MediaJobState] = MEDIA_PREPAY_STATES,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> list[UUID]:
    """Cancel every PRE-PAY request of this account (of one kind, or all). The ids moved.

    ``/forget`` calls it for all kinds and every pre-pay state (§9.3). Freezing a new draft
    and ``/cancel`` pass ``states`` without ``awaiting_payment`` (§2.3.1, §2.6): a request
    whose pay link is out may have money in flight, so it is never swept aside by a new
    draft. A paid request is never touched here. The caller runs ``media_cleanup`` for each
    id returned.
    """
    if not set(states) <= MEDIA_PREPAY_STATES:
        raise ValueError("cancel_prepay_jobs cancels pre-pay states only")
    wanted = tuple(states)
    conditions = [
        MediaJobRow.telegram_user_id == telegram_user_id,
        MediaJobRow.state.in_(wanted),
    ]
    if kind is not None:
        conditions.append(MediaJobRow.kind == kind)
    ids = list((await session.scalars(sa.select(MediaJobRow.id).where(*conditions))).all())
    if not ids:
        return []
    # RETURNING, not the SELECT's ids: a row that moved in between (a 🎟 spend committing
    # QUOTED → PAID) is rightly not cancelled, and must not be reported as cancelled either —
    # its caller would enqueue a ``media_cleanup`` that no-ops now and, under the
    # deterministic ARQ id, drops the real one after delivery.
    moved = await session.scalars(
        sa.update(MediaJobRow)
        .where(MediaJobRow.id.in_(ids), MediaJobRow.state.in_(wanted))
        .values(
            state=MediaJobState.CANCELLED,
            updated_at=now,
            text_expires_at=policy.media_output_expires_at(now),
        )
        .returning(MediaJobRow.id)
    )
    return list(moved.all())


# ---------------------------------------------------------------------------
# Bytes
# ---------------------------------------------------------------------------
async def add_input(
    session: AsyncSession,
    *,
    job_id: UUID,
    ordinal: int,
    role: MediaInputRole,
    now: datetime,
    tg_file_id: str | None = None,
    tg_file_unique_id: str | None = None,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> UUID:
    """Record an upload (or the collage) against a job, before its bytes are fetched.

    ``expires_at`` starts at the pre-payment backstop, ``created_at`` + 24 h (§3.2.2).
    """
    input_id = uuid4()
    session.add(
        MediaInputRow(
            id=input_id,
            job_id=job_id,
            ordinal=ordinal,
            role=role,
            tg_file_id=tg_file_id,
            tg_file_unique_id=tg_file_unique_id,
            retention_class=RetentionClass.MEDIA_INPUT,
            expires_at=policy.media_input_expires_at(now),
            created_at=now,
        )
    )
    await session.flush()
    return input_id


async def record_input_stored(
    session: AsyncSession,
    input_id: UUID,
    *,
    storage_key: str,
    mime: str,
    size_bytes: int,
    sha256: str,
    width: int | None = None,
    height: int | None = None,
    duration_ms: int | None = None,
) -> bool:
    """Record where ``media_screen`` stored the checked bytes and what they hash to.

    Generation, collage, TTS and mux read only this copy, verified against ``sha256`` (§3.3
    "Screened bytes only").
    """
    result = await session.execute(
        sa.update(MediaInputRow)
        .where(MediaInputRow.id == input_id)
        .values(
            storage_key=storage_key,
            mime=mime,
            size_bytes=size_bytes,
            sha256=sha256,
            width=width,
            height=height,
            duration_ms=duration_ms,
        )
    )
    return rowcount_of(result) == 1


async def add_output(
    session: AsyncSession,
    *,
    job_id: UUID,
    role: MediaOutputRole,
    variant: int,
    storage_key: str,
    now: datetime,
    mime: str | None = None,
    size_bytes: int | None = None,
    sha256: str | None = None,
    width: int | None = None,
    height: int | None = None,
    duration_ms: int | None = None,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> bool:
    """Record a stored result. True when THIS call wrote it.

    ``INSERT … ON CONFLICT DO NOTHING`` on ``(job_id, role, variant)``: a redelivered fetch
    writes one row, and the loser learns it lost (and deletes the object it just stored, if
    its key differs). Intermediates get 24 hours, deliverables the output period (§3.2.4).
    """
    expires_at = (
        policy.media_intermediate_expires_at(now)
        if role in INTERMEDIATE_OUTPUT_ROLES
        else policy.media_output_expires_at(now)
    )
    statement = upsert_statement(
        session,
        MediaOutputRow,
        {
            "id": uuid4(),
            "job_id": job_id,
            "role": role,
            "variant": variant,
            "storage_key": storage_key,
            "mime": mime,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "width": width,
            "height": height,
            "duration_ms": duration_ms,
            "retention_class": RetentionClass.MEDIA_OUTPUT,
            "expires_at": expires_at,
            "created_at": now,
        },
        index_elements=("job_id", "role", "variant"),
        set_=None,
    )
    return rowcount_of(await session.execute(statement)) == 1


async def place_legal_hold(
    session: AsyncSession,
    job_id: UUID,
    *,
    now: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> int:
    """Put every input and output of ``job_id`` under legal hold (§6.7). Rows moved.

    The hold's own clock is at most :attr:`RetentionPolicy.media_legal_hold_max_hours` from
    the block. From here on ``media_cleanup``, ``/forget`` and both ordinary purge predicates
    skip the rows; only the legal-hold purge arm, when this clock runs out, deletes them.
    Encryption and the escalation owner's handover are M3.1's.
    """
    until = policy.media_legal_hold_expires_at(now)
    moved = 0
    for model in (MediaInputRow, MediaOutputRow):
        result = await session.execute(
            sa.update(model)
            .where(model.job_id == job_id)
            .values(retention_class=RetentionClass.LEGAL_HOLD, legal_hold_expires_at=until)
        )
        moved += rowcount_of(result)
    return moved


async def record_legal_hold_decision(
    session: AsyncSession, job_id: UUID, decision: MediaLegalHoldDecision, *, now: datetime
) -> int:
    """The escalation owner's reporting decision on a held job (§6.7). Held rows it covers.

    ``HANDOVER`` keeps the bytes past ``legal_hold_expires_at`` — the purge skips the job
    (``db.purge._media_holds_due``). ``DELETE`` brings every still-present held object's
    clock forward to ``now``, so the next purge takes the bytes and keeps the rows. A later
    decision replaces an earlier one (a handover done, then delete). 0 — and nothing
    written — when the job holds nothing.
    """
    held = int(
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(MediaInputRow)
            .where(
                MediaInputRow.job_id == job_id,
                MediaInputRow.retention_class == RetentionClass.LEGAL_HOLD,
            )
        )
        or 0
    ) + int(
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(MediaOutputRow)
            .where(
                MediaOutputRow.job_id == job_id,
                MediaOutputRow.retention_class == RetentionClass.LEGAL_HOLD,
            )
        )
        or 0
    )
    if held == 0:
        return 0
    await session.execute(
        sa.update(MediaJobRow)
        .where(MediaJobRow.id == job_id)
        .values(legal_hold_decision=decision, legal_hold_decided_at=now)
    )
    if decision is MediaLegalHoldDecision.DELETE:
        for model in (MediaInputRow, MediaOutputRow):
            await session.execute(
                sa.update(model)
                .where(
                    model.job_id == job_id,
                    model.retention_class == RetentionClass.LEGAL_HOLD,
                    model.deleted_at.is_(None),
                    model.legal_hold_expires_at > now,
                )
                .values(legal_hold_expires_at=now)
            )
    return held


def _standing_csam_block(telegram_user_id: int) -> sa.ColumnElement[bool]:
    return sa.and_(
        MediaJobRow.telegram_user_id == telegram_user_id,
        MediaJobRow.error_code == CSAM_BLOCKED_ERROR_CODE,
        MediaJobRow.csam_cleared_at.is_(None),
    )


async def has_standing_csam_block(session: AsyncSession, telegram_user_id: int) -> bool:
    """Whether the account has a CSAM-class block no operator has cleared (§6.4).

    The durable half of the suspension: Redis (``moderation.strikes``) is a cache here, and a
    restart without persistence must not lift a suspension that only an operator may lift.
    """
    found = await session.scalar(
        sa.select(MediaJobRow.id).where(_standing_csam_block(telegram_user_id)).limit(1)
    )
    return found is not None


async def clear_csam_blocks(session: AsyncSession, telegram_user_id: int, *, now: datetime) -> int:
    """An operator lifts the account's CSAM-class suspension (``tools.media unsuspend``).
    Jobs cleared. The held bytes are untouched: they follow their own decision (§6.7)."""
    result = await session.execute(
        sa.update(MediaJobRow)
        .where(_standing_csam_block(telegram_user_id))
        .values(csam_cleared_at=now)
    )
    return rowcount_of(result)


async def cleanup_job_media(session: AsyncSession, job_id: UUID) -> tuple[str, ...]:
    """``media_cleanup``'s rows: every upload and every intermediate. The object keys.

    Run after delivery and on failure, rejection, cancellation and abandonment (O16). The
    deliverable images and video stay on their output clock — **unless the account asked to
    be forgotten** (§9.3): a render in flight at /forget may have stored its result after the
    erasure ran, and this is that job's next stage boundary. **Legal-hold rows are skipped**
    (§6.7). The caller deletes the returned objects after its commit.
    """
    forgotten = (
        await session.scalar(
            sa.select(MediaJobRow.forget_requested_at).where(MediaJobRow.id == job_id)
        )
    ) is not None
    keys: list[str] = []
    inputs = (
        await session.execute(
            sa.select(MediaInputRow.id, MediaInputRow.storage_key).where(
                MediaInputRow.job_id == job_id,
                MediaInputRow.retention_class != RetentionClass.LEGAL_HOLD,
            )
        )
    ).all()
    if inputs:
        keys.extend(key for _, key in inputs if key is not None)
        await session.execute(
            sa.delete(MediaInputRow).where(MediaInputRow.id.in_([row_id for row_id, _ in inputs]))
        )
    outputs = (
        await session.execute(
            sa.select(MediaOutputRow.id, MediaOutputRow.storage_key).where(
                MediaOutputRow.job_id == job_id,
                sa.true()
                if forgotten
                else MediaOutputRow.role.in_(tuple(INTERMEDIATE_OUTPUT_ROLES)),
                MediaOutputRow.retention_class != RetentionClass.LEGAL_HOLD,
            )
        )
    ).all()
    if outputs:
        keys.extend(key for _, key in outputs)
        await session.execute(
            sa.delete(MediaOutputRow).where(
                MediaOutputRow.id.in_([row_id for row_id, _ in outputs])
            )
        )
    return tuple(keys)


# ---------------------------------------------------------------------------
# Attempts
# ---------------------------------------------------------------------------
async def insert_attempt(
    session: AsyncSession,
    *,
    job_id: UUID,
    stage: MediaAttemptStage,
    variant: int,
    attempt: int,
    provider: str,
    now: datetime,
    model_id: str | None = None,
    attempt_id: UUID | None = None,
) -> UUID | None:
    """Write the ``submitting`` row BEFORE the POST (R7). Its id, or None if it existed.

    None is the crash-recovery signal: an attempt with this (job, stage, variant, attempt)
    was already started, and if it has no ``remote_id`` the caller must mark it
    ``ambiguous`` and reconcile — never POST again (§3.3).

    ``attempt_id`` lets the caller mint the id first: ``media_submit`` takes the GPU lock in
    the attempt's name BEFORE the row exists (§3.4), so a lock it fails to get leaves no
    ``submitting`` row behind to be mistaken for a crash.
    """
    attempt_id = attempt_id or uuid4()
    statement = upsert_statement(
        session,
        MediaAttemptRow,
        {
            "id": attempt_id,
            "job_id": job_id,
            "stage": stage,
            "variant": variant,
            "attempt": attempt,
            "provider": provider,
            "model_id": model_id,
            "status": MediaAttemptStatus.SUBMITTING,
            "created_at": now,
        },
        index_elements=("job_id", "stage", "variant", "attempt"),
        set_=None,
    )
    if rowcount_of(await session.execute(statement)) != 1:
        return None
    return attempt_id


async def set_attempt_status(
    session: AsyncSession,
    attempt_id: UUID,
    *,
    expected: Collection[MediaAttemptStatus],
    status: MediaAttemptStatus,
    now: datetime,
    remote_id: str | None = None,
    error_code: str | None = None,
    queue_ms: int | None = None,
    run_ms: int | None = None,
    gpu_seconds: float | None = None,
    cost_usd: float | None = None,
    cost_source: CostSource | None = None,
) -> bool:
    """Move an attempt iff it is in ``expected``. A terminal status stamps ``finished_at``.

    Only the measurements passed are written; ``None`` never overwrites one already stored.
    """
    values: dict[str, Any] = {"status": status}
    for name, value in (
        ("remote_id", remote_id),
        ("error_code", error_code),
        ("queue_ms", queue_ms),
        ("run_ms", run_ms),
        ("gpu_seconds", gpu_seconds),
        ("cost_usd", cost_usd),
        ("cost_source", cost_source),
    ):
        if value is not None:
            values[name] = value
    if status not in (MediaAttemptStatus.SUBMITTING, MediaAttemptStatus.SUBMITTED):
        values["finished_at"] = now
    result = await session.execute(
        sa.update(MediaAttemptRow)
        .where(MediaAttemptRow.id == attempt_id, MediaAttemptRow.status.in_(tuple(expected)))
        .values(**values)
    )
    return rowcount_of(result) == 1


# ---------------------------------------------------------------------------
# Reads and small writes for the stage chain (IMAGE_VIDEO_SPEC §3.3)
# ---------------------------------------------------------------------------
#: The order generation reads inputs in, and therefore the order ``content_sha256`` hashes
#: them in: every photo by ordinal, then the collage built from them.
_INPUT_ROLE_ORDER: Final[dict[MediaInputRole, int]] = {
    MediaInputRole.PHOTO: 0,
    MediaInputRole.VOICE_NOTE: 1,
    MediaInputRole.COLLAGE: 2,
}


async def list_inputs(session: AsyncSession, job_id: UUID) -> list[MediaInputRow]:
    """Every input row of the job, photos first by ordinal, then voice note, then collage."""
    rows = list(
        (await session.scalars(sa.select(MediaInputRow).where(MediaInputRow.job_id == job_id)))
        .unique()
        .all()
    )
    rows.sort(key=lambda row: (_INPUT_ROLE_ORDER.get(row.role, 9), row.ordinal))
    return rows


async def list_outputs(
    session: AsyncSession, job_id: UUID, *, role: MediaOutputRole
) -> list[MediaOutputRow]:
    """The job's outputs of one role, by variant."""
    return list(
        (
            await session.scalars(
                sa.select(MediaOutputRow)
                .where(MediaOutputRow.job_id == job_id, MediaOutputRow.role == role)
                .order_by(MediaOutputRow.variant)
            )
        ).all()
    )


async def find_attempt(
    session: AsyncSession,
    job_id: UUID,
    *,
    stage: MediaAttemptStage,
    variant: int,
    attempt: int,
) -> MediaAttemptRow | None:
    found: MediaAttemptRow | None = await session.scalar(
        sa.select(MediaAttemptRow)
        .where(
            MediaAttemptRow.job_id == job_id,
            MediaAttemptRow.stage == stage,
            MediaAttemptRow.variant == variant,
            MediaAttemptRow.attempt == attempt,
        )
        .execution_options(populate_existing=True)
    )
    return found


async def latest_attempts(
    session: AsyncSession, job_id: UUID, *, stage: MediaAttemptStage
) -> dict[int, MediaAttemptRow]:
    """The highest-numbered attempt of each variant that has one."""
    rows = (
        await session.scalars(
            sa.select(MediaAttemptRow)
            .where(MediaAttemptRow.job_id == job_id, MediaAttemptRow.stage == stage)
            .order_by(MediaAttemptRow.variant, MediaAttemptRow.attempt)
            .execution_options(populate_existing=True)
        )
    ).all()
    latest: dict[int, MediaAttemptRow] = {}
    for row in rows:
        latest[row.variant] = row
    return latest


async def bump_seq(
    session: AsyncSession, job_id: UUID, *, column: str, now: datetime
) -> int | None:
    """``submit_seq`` / ``oscreen_seq`` + 1, returning the new value (§3.3 "ARQ job ids").

    The suffix of a deliberate re-enqueue: a fresh ARQ id every time, so ARQ never drops the
    re-run as a duplicate of the job that is enqueueing it. Also stamps ``updated_at``, which
    is the heartbeat ``media_sweep`` reads to tell a job waiting for the GPU from a job whose
    chain died. ``None`` when the row is gone.
    """
    if column not in ("submit_seq", "oscreen_seq"):
        raise ValueError(f"{column} is not a re-enqueue suffix")
    target = getattr(MediaJobRow, column)
    result = await session.execute(
        sa.update(MediaJobRow)
        .where(MediaJobRow.id == job_id)
        .values({column: target + 1, "updated_at": now})
    )
    if rowcount_of(result) != 1:
        return None
    value = await session.scalar(sa.select(target).where(MediaJobRow.id == job_id))
    return None if value is None else int(value)


async def touch_job(session: AsyncSession, job_id: UUID, *, now: datetime) -> None:
    """The stage chain's heartbeat: a live poll proves the job is not stranded (§3.3 (c))."""
    await session.execute(
        sa.update(MediaJobRow).where(MediaJobRow.id == job_id).values(updated_at=now)
    )


async def record_output_file_id(session: AsyncSession, output_id: UUID, *, tg_file_id: str) -> None:
    """What Telegram minted on delivery: a re-send costs zero bytes."""
    await session.execute(
        sa.update(MediaOutputRow)
        .where(MediaOutputRow.id == output_id)
        .values(tg_file_id=tg_file_id)
    )


async def average_run_ms(
    session: AsyncSession,
    *,
    stage: MediaAttemptStage,
    model_id: str | None,
    sample: int = 20,
) -> int | None:
    """The moving average of the last ``sample`` successful runs of a model (§3.4 ETA)."""
    conditions = [
        MediaAttemptRow.stage == stage,
        MediaAttemptRow.status == MediaAttemptStatus.SUCCEEDED,
        MediaAttemptRow.run_ms.is_not(None),
    ]
    if model_id is not None:
        conditions.append(MediaAttemptRow.model_id == model_id)
    recent = (
        sa.select(MediaAttemptRow.run_ms)
        .where(*conditions)
        .order_by(MediaAttemptRow.created_at.desc())
        .limit(sample)
        .subquery()
    )
    value = await session.scalar(sa.select(sa.func.avg(recent.c.run_ms)))
    return None if value is None else int(value)


# ---------------------------------------------------------------------------
# Money: receipts, the kind-scoped credit
# ---------------------------------------------------------------------------
async def record_purchase(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    job_id: UUID,
    sku: MediaSku,
    amount_minor: int,
    currency: str,
    provider: MediaPurchaseProvider,
    reference: str,
    idempotency_key: str,
    now: datetime,
) -> bool:
    """Write the receipt. True when THIS call wrote it; a replayed settlement writes one."""
    statement = upsert_statement(
        session,
        MediaPurchaseRow,
        {
            "id": uuid4(),
            "telegram_user_id": telegram_user_id,
            "job_id": job_id,
            "sku": sku,
            "amount_minor": amount_minor,
            "currency": currency,
            "provider": provider,
            "reference": reference,
            "idempotency_key": idempotency_key,
            "created_at": now,
        },
        index_elements=("idempotency_key",),
        set_=None,
    )
    return rowcount_of(await session.execute(statement)) == 1


async def media_balance(session: AsyncSession, *, telegram_user_id: int, sku: MediaSku) -> int:
    """Spendable refund credits for one SKU. Zero when no row exists."""
    balance = await session.scalar(
        sa.select(MediaCreditBalanceRow.balance).where(
            MediaCreditBalanceRow.telegram_user_id == telegram_user_id,
            MediaCreditBalanceRow.sku == sku,
        )
    )
    return int(balance or 0)


async def grant_refund(
    session: AsyncSession,
    job_id: UUID,
    *,
    reason: MediaCreditReason,
    now: datetime,
    actor: str | None = None,
) -> bool:
    """Grant ONE credit for this job's SKU, at most once whatever the reason. True if granted.

    ``actor`` is the ledger's attribution — ``admin:{username}`` when an operator's review
    decision caused the refund (§6.6), the worker when None.

    The claim comes first: ``refund_state`` NULL → ``due`` by conditional UPDATE, so a
    deadline failure followed by a late generation failure — or a variant failure followed by
    an output block — grants one credit (§3.2.2). Then the ledger ``+1``, the balance upsert
    and ``granted``, all in the caller's transaction. The ledger's partial unique index is the
    second layer.

    Refused (False, nothing written) for a beta job, which was free (§7.5), for an unpaid
    job unless ``reason`` is ``late_settlement`` — money that arrived for a request we had
    already cancelled — and for a job whose account asked to be forgotten (§9.3): /forget
    deleted the balance and anonymised the ledger, and a credit would write both back.
    """
    if reason in (MediaCreditReason.SPENT, MediaCreditReason.ADMIN_CORRECTION):
        raise ValueError(f"{reason} is not a refund reason")
    job = (
        await session.execute(
            sa.select(
                MediaJobRow.telegram_user_id,
                MediaJobRow.sku,
                MediaJobRow.paid_via,
                MediaJobRow.forget_requested_at,
            ).where(MediaJobRow.id == job_id)
        )
    ).one_or_none()
    if job is None:
        return False
    telegram_user_id, sku, paid_via, forget_requested_at = job
    if forget_requested_at is not None:
        return False
    if paid_via is None and reason is not MediaCreditReason.LATE_SETTLEMENT:
        return False
    if paid_via is not None and paid_via not in _REFUNDABLE_PAID_VIA:
        return False
    claimed = await session.execute(
        sa.update(MediaJobRow)
        .where(MediaJobRow.id == job_id, MediaJobRow.refund_state.is_(None))
        .values(refund_state=MediaRefundState.DUE, updated_at=now)
    )
    if rowcount_of(claimed) != 1:
        return False
    session.add(
        MediaCreditLedgerRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            sku=sku,
            delta=1,
            reason=reason,
            job_id=job_id,
            actor=actor or _WORKER_ACTOR,
            created_at=now,
        )
    )
    await session.flush()
    await session.execute(
        upsert_statement(
            session,
            MediaCreditBalanceRow,
            {"telegram_user_id": telegram_user_id, "sku": sku, "balance": 1, "updated_at": now},
            index_elements=("telegram_user_id", "sku"),
            set_={"balance": MediaCreditBalanceRow.balance + 1, "updated_at": now},
        )
    )
    await session.execute(
        sa.update(MediaJobRow)
        .where(MediaJobRow.id == job_id)
        .values(refund_state=MediaRefundState.GRANTED)
    )
    return True


async def spend_credit(
    session: AsyncSession,
    job_id: UUID,
    *,
    now: datetime,
    deadline: timedelta,
    actor: str = "bot",
) -> bool:
    """Pay for a ``quoted`` job with one credit of its SKU. True when THIS call paid.

    §3.2.2's four writes, in the caller's transaction: the balance ``-1`` (only if ≥ 1), the
    job ``quoted → paid`` (:func:`mark_paid`, which also resets the uploads' clock), the ledger
    ``-1 spent`` and a zero-amount ``credit`` receipt — zero because the money was taken on the
    request that failed, and counting it again would double the revenue. If the balance is
    not there nothing is written; if the job was not ``quoted`` the debit is put back in the
    same transaction, so either answer leaves the books as they were. Two concurrent taps with
    a balance of one spend once: the balance predicate is the concurrency control.
    """
    job = (
        await session.execute(
            sa.select(MediaJobRow.telegram_user_id, MediaJobRow.sku, MediaJobRow.currency).where(
                MediaJobRow.id == job_id
            )
        )
    ).one_or_none()
    if job is None:
        return False
    telegram_user_id, sku, currency = job
    debited = await session.execute(
        sa.update(MediaCreditBalanceRow)
        .where(
            MediaCreditBalanceRow.telegram_user_id == telegram_user_id,
            MediaCreditBalanceRow.sku == sku,
            MediaCreditBalanceRow.balance >= 1,
        )
        .values(balance=MediaCreditBalanceRow.balance - 1, updated_at=now)
    )
    if rowcount_of(debited) != 1:
        return False
    paid = await mark_paid(
        session,
        job_id,
        paid_via=MediaPaidVia.CREDIT,
        now=now,
        deadline=deadline,
        expected=(MediaJobState.QUOTED,),
    )
    if not paid:
        await session.execute(
            sa.update(MediaCreditBalanceRow)
            .where(
                MediaCreditBalanceRow.telegram_user_id == telegram_user_id,
                MediaCreditBalanceRow.sku == sku,
            )
            .values(balance=MediaCreditBalanceRow.balance + 1, updated_at=now)
        )
        return False
    entry_id = uuid4()
    session.add(
        MediaCreditLedgerRow(
            id=entry_id,
            telegram_user_id=telegram_user_id,
            sku=sku,
            delta=-1,
            reason=MediaCreditReason.SPENT,
            job_id=job_id,
            actor=actor,
            created_at=now,
        )
    )
    await session.flush()
    await record_purchase(
        session,
        telegram_user_id=telegram_user_id,
        job_id=job_id,
        sku=sku,
        amount_minor=0,
        currency=currency,
        provider=MediaPurchaseProvider.CREDIT,
        reference=str(entry_id),
        idempotency_key=f"media:{job_id}:credit",
        now=now,
    )
    return True
