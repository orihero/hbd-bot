"""The audit log's one writer, its reader, and the chain that makes both worth trusting.

**:func:`append` is the only write path**, and it is the only function in the codebase that
constructs an :class:`~hbd.db.models.admin_audit.AdminAuditRow`. That is not a convention
kept by politeness — the chain is only linear if one function computes it, and a second
writer that skipped the HMAC would leave a row whose ``chain_hmac`` verifies against nothing
and a permanent "first break" at that ``seq``. ``tests/test_db/test_audit_chain.py`` asserts
the exclusivity by scanning the source tree.

**The chain is keyed.** ``chain_hmac`` is::

    HMAC-SHA256(admin_audit_hmac_key, "v1" ‖ "\\n" ‖ prev_hmac ‖ "\\n" ‖ canonical_json(row))

The key comes from ``AdminSettings.admin_audit_hmac_key``, which lives in the admin
process's environment and never in the database — so an adversary who can write the table
cannot recompute the chain over their edit. An unkeyed ``sha256`` chain, which is what §12.4
replaced, could be: it would have reported a rewritten log as clean, which is worse than no
chain at all because it is a control somebody would trust.

The canonical form is built from the row itself, by one function used by both the writer and
the verifier, so the two cannot drift. It excludes:

* ``seq`` — assigned by the database as the row is inserted, therefore not knowable when the
  MAC is computed. Order is still protected: the verifier walks in ``seq`` order and feeds
  each row the previous row's MAC, so a reordering, an insertion or a deletion in the middle
  breaks the next link.
* ``reason_text``, ``reason_expires_at`` and ``reason_purged_at`` — the three columns the
  90-day reason sweep writes. A chain covering them would break itself on schedule, and an
  alarm that cries wolf every quarter is an alarm nobody reads.

**Appends serialise on a Postgres advisory transaction lock.** Two concurrent appends that
both read the same head would fork the chain, and the verifier — which walks one line — would
report the fork as tampering. The lock is held until the transaction commits, so the next
appender reads a head that is actually committed. On SQLite there is nothing to take: writes
are serialised by the database itself.

**No secret ever enters this table.** :func:`append` refuses an argon2 hash, a session or
CSRF token, a vendor API key, a bearer token and a DSN carrying userinfo, in any operator-
supplied field, rather than storing a redacted version of it: a credential that reached an
audit row is an incident to surface, not a string to tidy up. Everything else that is free
text still passes through ``hbd.logging.redact``.

That rule covers **every** column, including the three that used to bypass it.
``correlation_id``, ``ip`` and ``user_agent_hash`` were written straight through with no
check at all, so a DSN carrying userinfo, an argon2 hash or a raw User-Agent string would
have landed verbatim in the table with the longest clock in the system the first time a
caller passed one. They are now shape-checked at this boundary rather than trusted to have
been checked at the call site — a boundary that trusts its callers is not one.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.db.enums import AdminRole, AuditAction, AuditReasonCode
from hbd.db.models.admin_audit import (
    AUDIT_REASON_RETENTION_DAYS,
    AUDIT_RETENTION_DAYS,
    REASON_TEXT_LENGTH,
    AdminAuditRow,
    AuditOutcome,
)
from hbd.db.models.audit_anchor import AuditAnchorKind, AuditChainAnchorRow
from hbd.logging import get_logger, redact

__all__ = [
    "AuditEntry",
    "AuditQuery",
    "AuditValueRejectedError",
    "ChainProtection",
    "ChainVerification",
    "SUBJECT_TYPES",
    "CHAIN_VERSION",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MAX_VERIFY_ROWS",
    "VERIFY_BATCH_SIZE",
    "PURGE_FUNCTION_NAME",
    "REASON_PURGE_FUNCTION_NAME",
    "append",
    "canonical_content",
    "compute_chain_hmac",
    "list_entries",
    "read_head",
    "read_head_anchor",
    "resolve_chain_protection",
    "verify_chain",
    "write_head_anchor",
    "write_truncation_anchor",
]

_LOGGER: Final = get_logger(__name__)

#: Stamped into every MAC. A future change to the canonical form bumps this rather than
#: silently invalidating every row written before it: the verifier can then say "this row
#: was written under v1" instead of reporting a break nobody can explain.
CHAIN_VERSION: Final[str] = "v1"

#: One constant for the whole table (§12.4). Advisory locks are a namespace of one 64-bit
#: integer; this is the only lock this codebase takes, and it is taken only here.
_ADVISORY_LOCK_KEY: Final[int] = 0x4842_4441_5544_4954

#: The ``SECURITY DEFINER`` functions migration 0007 installs on Postgres when the two-role
#: setup is in place. Named here so the retention sweep and the migration agree on the
#: spelling without either importing the other. Both take a row limit and **no cutoff**: the
#: expiry is each row's own, read against the server clock, so EXECUTE on them is the right
#: to delete what is already legally due and never the right to delete what the caller names.
PURGE_FUNCTION_NAME: Final[str] = "hbd_purge_audit_log"
REASON_PURGE_FUNCTION_NAME: Final[str] = "hbd_purge_audit_reasons"

DEFAULT_PAGE_SIZE: Final[int] = 50
MAX_PAGE_SIZE: Final[int] = 200
#: The verifier reads in bounded batches — the table is unbounded within its 730 days and a
#: single ``SELECT *`` over it is exactly the unbounded list query the repo's rules forbid.
VERIFY_BATCH_SIZE: Final[int] = 500
#: A ceiling on one verification pass, so a request can never become a full table scan of two
#: years of history. The result says whether it stopped early.
MAX_VERIFY_ROWS: Final[int] = 50_000

#: §5.4's closed vocabulary. A subject type outside it is a bug at the call site, not a new
#: kind of row: the panel joins on these strings.
SUBJECT_TYPES: Final[frozenset[str]] = frozenset(
    {"order", "user", "asset", "chat", "config", "admin", "session", "wizard_draft", "system"}
)

#: ``^[A-Za-z0-9#_-]{1,64}$`` per §5.4 — a ticket reference, not a sentence.
_REASON_REF_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9#_-]{1,64}$")
#: A UUID, a Telegram id or a config version. Never a name, and never long enough to hide a
#: credential in — but see :func:`_reject_secrets`, which checks anyway.
_SUBJECT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9:._-]{1,64}$")
#: A column or field **name**: lowercase, dotted, an identifier. Every column in this schema
#: is spelled that way, so the pattern refuses a capitalised word, a sentence and a number —
#: which is most of what a value looks like. It is a shape guard and not a proof: a lowercase
#: one-word value would pass it, and what stops that is that call sites pass literals.
_FIELD_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")

#: ``new_correlation_id()`` renders 32 hex characters; the middleware already refuses
#: anything else on the way in, and this refuses it again at the column.
_CORRELATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-zA-Z._-]{1,128}$")
#: ``user_agent_hash`` is documented as a sha256 digest. A non-digest is a call-site bug —
#: most likely the raw User-Agent string — and storing it would put a fingerprint, rather
#: than a correlation key, in the table with the longest clock in the system.
_USER_AGENT_HASH_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

#: Shapes ``hbd.logging.redact`` does not know about, because they are not things the bot
#: logs: the panel's own credentials. An argon2 PHC string, a hex digest of a session token,
#: and the base64url token itself.
_CREDENTIAL_SHAPES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\$(argon2[a-z0-9]*|2[aby]?)\$"),
    re.compile(r"\b[0-9a-f]{64}\b"),
    re.compile(r"[A-Za-z0-9_-]{40,}"),
)


class AuditValueRejectedError(ValueError):
    """An audited value was malformed, or looked like a credential.

    Raised rather than returned: this module follows ``hbd.db.admin``'s rule that the request
    owns the transaction, so a refused append must take the whole request down with it. A
    route that accepts operator text renders it as ``INVALID_INPUT`` (422); a route that
    caused it with a value of its own has a bug, and a 500 is the correct answer to that.
    """


class ChainProtection(StrEnum):
    """What is actually protecting the log on this deployment. Reported verbatim (§12.4).

    ``REVOKE_HMAC`` is claimed only when the database says so — the application role really
    cannot ``UPDATE``, ``DELETE`` or ``TRUNCATE`` the table. ``HMAC_ONLY`` is the honest
    answer everywhere else, including a Postgres deployment where the revoke was configured
    but did not land. A control that is not deployed is reported as not deployed.
    """

    REVOKE_HMAC = "revoke+hmac"
    HMAC_ONLY = "hmac-only"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One action, as the caller describes it. Everything derived is derived by :func:`append`.

    ``actor_id`` is ``None`` only for the system itself — the bootstrap CLI and the retention
    cron — and ``actor_username`` then reads ``system:<what>``, which is why it is a separate
    field rather than a lookup.
    """

    action: AuditAction
    actor_username: str
    actor_role: AdminRole
    subject_type: str
    reason_code: AuditReasonCode
    outcome: AuditOutcome = AuditOutcome.OK
    actor_id: UUID | None = None
    subject_id: str | None = None
    field_names: tuple[str, ...] | None = None
    record_count: int | None = None
    reason_ref: str | None = None
    reason_text: str | None = None
    error_code: str | None = None
    correlation_id: str | None = None
    ip: str | None = None
    user_agent_hash: str | None = None
    config_version: int | None = None


@dataclass(frozen=True, slots=True)
class AuditQuery:
    """§6.8's filter set. Repeated values are OR within a field, AND across fields."""

    actor_id: UUID | None = None
    actor_username: str | None = None
    actions: tuple[AuditAction, ...] = ()
    subject_type: str | None = None
    subject_id: str | None = None
    outcomes: tuple[AuditOutcome, ...] = ()
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChainVerification:
    """The result of one walk. ``first_break_seq`` is ``None`` exactly when ``is_ok``."""

    is_ok: bool
    first_break_seq: int | None
    checked_rows: int
    last_seq: int | None
    #: False when :data:`MAX_VERIFY_ROWS` stopped the walk before the end of the table, so a
    #: clean result is not mistaken for a clean *whole* chain.
    is_complete: bool
    protection: ChainProtection
    anchors: tuple[int, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Input scrubbing — nothing reaches a column before this
# ---------------------------------------------------------------------------
def _reject_secrets(name: str, value: str | None) -> None:
    """Refuse a value that carries a credential, whatever field it arrived in.

    Two sources: ``redact`` (vendor keys, bearer tokens, DSN userinfo — masking the value
    means it matched) and :data:`_CREDENTIAL_SHAPES` (the panel's own password hashes and
    session tokens, which the bot never logs and ``redact`` therefore never learned).
    """
    if not value:
        return
    is_masked = redact(value) != value
    if is_masked or any(shape.search(value) for shape in _CREDENTIAL_SHAPES):
        _LOGGER.error(
            "an audit value looked like a credential and was refused",
            extra={"event": "admin.audit.secret_refused", "field": name},
        )
        raise AuditValueRejectedError(f"{name} looks like a credential and must not be audited")


def _clean_text(name: str, value: str | None, *, limit: int) -> str | None:
    """Reject a secret, redact the rest, and cap the length. ``None`` and ``""`` are ``None``."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    _reject_secrets(name, text)
    masked = redact(text)
    cleaned = masked if isinstance(masked, str) else str(masked)
    return cleaned[:limit]


def _checked(name: str, value: str | None, pattern: re.Pattern[str]) -> str | None:
    """A closed-shape identifier, or a refusal naming the field."""
    if value is None:
        return None
    _reject_secrets(name, value)
    if not pattern.match(value):
        raise AuditValueRejectedError(f"{name} is not a storable {name.replace('_', ' ')}")
    return value


def _checked_field_names(names: tuple[str, ...] | None) -> list[str] | None:
    """Field **names**, never values (§12.4). The pattern is the whole control.

    A plain loop, not a comprehension with an ``if``: ``_checked`` raises on a non-match, so
    a filter would read as though bad names were quietly dropped when they in fact abort the
    whole append. Matching the other call sites is the point.
    """
    if names is None:
        return None
    for name in names:
        _checked("field_name", name, _FIELD_NAME_PATTERN)
    return list(names)


def _checked_digest(value: str | None) -> str | None:
    """A sha256 hex digest, or a refusal.

    Deliberately not routed through :func:`_checked`: ``_CREDENTIAL_SHAPES`` refuses any
    64-character hex run, because that is what a stolen session-token digest looks like —
    and it is also, exactly, what a legitimate User-Agent digest looks like. The pattern
    alone is the control here, and it is a tight one: anything that is not 64 hex characters
    (most obviously the raw User-Agent string) is refused.
    """
    if value is None:
        return None
    if not _USER_AGENT_HASH_PATTERN.match(value):
        raise AuditValueRejectedError("user_agent_hash is not a sha256 digest")
    return value


def _checked_ip(value: str | None) -> str | None:
    """A parseable IP address, or a refusal. Never free text, never a credential.

    ``ip`` reaches this row from :func:`hbd.admin.deps.resolve_request_ip`, which already
    derives it under the trusted-proxy rules — but the audit boundary is where §12.4 says
    "no secret ever enters this table", and a boundary that trusts its callers is not one.
    On SQLite the column's 45-character cap is unenforced, so without this a 77-character
    argon2 hash would persist in the longest-clocked table in the system.
    """
    if value is None:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError as exc:
        raise AuditValueRejectedError("ip is not an IP address") from exc
    return value


def _checked_subject_type(subject_type: str) -> str:
    if subject_type not in SUBJECT_TYPES:
        raise AuditValueRejectedError(
            f"subject_type {subject_type!r} is outside the closed set {sorted(SUBJECT_TYPES)}"
        )
    return subject_type


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------
def _instant(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def canonical_content(row: AdminAuditRow) -> str:
    """The exact bytes (as text) the MAC covers, for one row.

    Sorted keys and no whitespace, so two runs of the same row produce one string. Built from
    the mapped row rather than from a caller's dictionary, which is what keeps the writer and
    the verifier honest about being the same formula. ``seq`` and the three reason-sweep
    columns are excluded — see the module docstring.
    """
    payload: dict[str, Any] = {
        "id": str(row.id),
        "at": _instant(row.at),
        "actor_id": None if row.actor_id is None else str(row.actor_id),
        "actor_username": row.actor_username,
        "actor_role": str(row.actor_role),
        "action": str(row.action),
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "field_names": row.field_names,
        "record_count": row.record_count,
        "reason_code": str(row.reason_code),
        "reason_ref": row.reason_ref,
        "outcome": str(row.outcome),
        "error_code": row.error_code,
        "correlation_id": row.correlation_id,
        "ip": row.ip,
        "user_agent_hash": row.user_agent_hash,
        "config_version": row.config_version,
        "expires_at": _instant(row.expires_at),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_chain_hmac(*, key: str, prev_hmac: str | None, content: str) -> str:
    """``HMAC-SHA256(key, version ‖ prev ‖ content)``, hex.

    The version and the previous link are separated by newlines rather than concatenated, so
    no combination of contents can be re-cut into a different but identical message.
    """
    if not key:
        raise AuditValueRejectedError("the audit HMAC key is empty; the chain would be unkeyed")
    message = f"{CHAIN_VERSION}\n{prev_hmac or ''}\n{content}".encode()
    return hmac.new(key.encode("utf-8"), message, sha256).hexdigest()


def _is_postgres(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "postgresql"


async def _lock_chain(session: AsyncSession) -> None:
    """Serialise appenders on Postgres. Released when the request's transaction ends."""
    if _is_postgres(session):
        await session.execute(sa.select(sa.func.pg_advisory_xact_lock(_ADVISORY_LOCK_KEY)))


async def read_head(session: AsyncSession) -> AdminAuditRow | None:
    """The newest row, or ``None`` on an empty table. The chain's current head."""
    statement = sa.select(AdminAuditRow).order_by(AdminAuditRow.seq.desc()).limit(1)
    return (await session.execute(statement)).scalars().first()


async def append(
    session: AsyncSession, entry: AuditEntry, *, key: str, now: datetime
) -> AdminAuditRow:
    """Write one audited action and link it to the chain. The only write path.

    The order is fixed: scrub the inputs, take the lock, read the head, compute the MAC over
    the row as it will be stored, insert. The insert is a single statement — the row is never
    written and then updated, because on a two-role deployment ``UPDATE`` is revoked and the
    second half would fail after the first had committed.
    """
    row = _build_row(entry, now=now)
    await _lock_chain(session)
    head = await read_head(session)
    row.prev_hmac = None if head is None else head.chain_hmac
    row.chain_hmac = compute_chain_hmac(
        key=key, prev_hmac=row.prev_hmac, content=canonical_content(row)
    )
    session.add(row)
    await session.flush()
    return row


def _build_row(entry: AuditEntry, *, now: datetime) -> AdminAuditRow:
    """Every column except the two chain values, with each input already refused or cleaned."""
    reason_text = _clean_text("reason_text", entry.reason_text, limit=REASON_TEXT_LENGTH)
    _reject_secrets("actor_username", entry.actor_username)
    return AdminAuditRow(
        id=uuid4(),
        at=now,
        actor_id=entry.actor_id,
        actor_username=entry.actor_username,
        actor_role=entry.actor_role,
        action=entry.action,
        subject_type=_checked_subject_type(entry.subject_type),
        subject_id=_checked("subject_id", entry.subject_id, _SUBJECT_ID_PATTERN),
        field_names=_checked_field_names(entry.field_names),
        record_count=entry.record_count,
        reason_code=entry.reason_code,
        reason_ref=_checked("reason_ref", entry.reason_ref, _REASON_REF_PATTERN),
        reason_text=reason_text,
        reason_expires_at=(
            None if reason_text is None else now + timedelta(days=AUDIT_REASON_RETENTION_DAYS)
        ),
        outcome=entry.outcome,
        error_code=_clean_text("error_code", entry.error_code, limit=48),
        correlation_id=_checked("correlation_id", entry.correlation_id, _CORRELATION_PATTERN),
        ip=_checked_ip(entry.ip),
        user_agent_hash=_checked_digest(entry.user_agent_hash),
        config_version=entry.config_version,
        expires_at=now + timedelta(days=AUDIT_RETENTION_DAYS),
        chain_hmac="",
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _filtered(statement: sa.Select[Any], query: AuditQuery) -> sa.Select[Any]:
    """AND across fields, OR within one. Every value is bound, never interpolated."""
    conditions = [
        AdminAuditRow.actor_id == query.actor_id if query.actor_id is not None else None,
        AdminAuditRow.actor_username == query.actor_username if query.actor_username else None,
        AdminAuditRow.action.in_(query.actions) if query.actions else None,
        AdminAuditRow.subject_type == query.subject_type if query.subject_type else None,
        AdminAuditRow.subject_id == query.subject_id if query.subject_id else None,
        AdminAuditRow.outcome.in_(query.outcomes) if query.outcomes else None,
        AdminAuditRow.at >= query.since if query.since is not None else None,
        AdminAuditRow.at <= query.until if query.until is not None else None,
    ]
    for condition in conditions:
        if condition is not None:
            statement = statement.where(condition)
    return statement


async def list_entries(
    session: AsyncSession,
    query: AuditQuery,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    before_seq: int | None = None,
) -> Sequence[AdminAuditRow]:
    """One keyset page, newest first.

    ``seq`` is the cursor rather than ``(at, id)``: it is the table's own ordering key, it is
    assigned by the database, and it is monotonic — where ``at`` is supplied by the caller
    and two rows can share it. The page is always bounded (§6.1, and the repo's rule 12).
    """
    page_size = max(1, min(limit, MAX_PAGE_SIZE))
    statement = _filtered(sa.select(AdminAuditRow), query)
    if before_seq is not None:
        statement = statement.where(AdminAuditRow.seq < before_seq)
    statement = statement.order_by(AdminAuditRow.seq.desc()).limit(page_size)
    return (await session.execute(statement)).scalars().all()


def _is_gap_excused(row: AdminAuditRow, truncations: Sequence[AuditChainAnchorRow]) -> bool:
    """Whether an anchor accounts for the missing rows below ``row``.

    The first surviving row of a truncated log carries a ``prev_hmac`` pointing at a row
    that no longer exists. That is legitimate exactly once: when the 730-day sweep made the
    cut and said so, by writing a TRUNCATION anchor naming **this** row — its ``seq`` and
    its ``chain_hmac``. Any other missing prefix is an excision.

    Matching on the ``chain_hmac`` as well as the ``seq`` is what stops a stale anchor from
    excusing a later, deeper cut: an attacker who deletes one more row past a legitimate
    truncation leaves a survivor the existing anchor does not name.
    """
    return any(
        anchor.seq == row.seq and anchor.chain_hmac == row.chain_hmac for anchor in truncations
    )


async def _verify_batch(
    session: AsyncSession,
    *,
    key: str,
    after_seq: int,
    limit: int,
    prev: str | None,
    truncations: Sequence[AuditChainAnchorRow],
) -> tuple[list[AdminAuditRow], int | None, str | None]:
    """Walk one batch forward. Returns the rows, the first break in it, and the new tail."""
    statement = (
        sa.select(AdminAuditRow)
        .where(AdminAuditRow.seq > after_seq)
        .order_by(AdminAuditRow.seq)
        .limit(limit)
    )
    rows = list((await session.execute(statement)).scalars().all())
    for row in rows:
        is_first = prev is None and after_seq == 0
        if is_first and row.prev_hmac is not None and not _is_gap_excused(row, truncations):
            # Rows below this one are gone and no sweep admits to removing them. Seeding the
            # walk from the survivor's own link — which is what this used to do — classified
            # every prefix excision as a legitimate truncation and reported it clean.
            return rows, row.seq, prev
        expected_prev = row.prev_hmac if is_first else prev
        recomputed = compute_chain_hmac(
            key=key, prev_hmac=expected_prev, content=canonical_content(row)
        )
        if row.prev_hmac != expected_prev or recomputed != row.chain_hmac:
            return rows, row.seq, prev
        prev = row.chain_hmac
    return rows, None, prev


async def read_head_anchor(session: AsyncSession) -> AuditChainAnchorRow | None:
    """The newest HEAD anchor — how far the log reached when the sweep last pinned it."""
    statement = (
        sa.select(AuditChainAnchorRow)
        .where(AuditChainAnchorRow.kind == AuditAnchorKind.HEAD)
        .order_by(AuditChainAnchorRow.seq.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def _read_truncation_anchors(session: AsyncSession) -> tuple[AuditChainAnchorRow, ...]:
    statement = sa.select(AuditChainAnchorRow).where(
        AuditChainAnchorRow.kind == AuditAnchorKind.TRUNCATION
    )
    return tuple((await session.execute(statement)).scalars().all())


async def _tail_break(session: AsyncSession, *, last_seq: int) -> int | None:
    """The seq a HEAD anchor pins that the table no longer reaches, or ``None``.

    A chain walk cannot see a tail deletion: excise the newest rows and what remains still
    links perfectly. The anchor is the out-of-band record of where the log ended, so a head
    below it is the one deletion an attacker most wants — the record of what they just did.
    """
    anchor = await read_head_anchor(session)
    if anchor is None:
        return None
    return anchor.seq if last_seq < anchor.seq else None


async def verify_chain(
    session: AsyncSession,
    *,
    key: str,
    is_dsn_configured: bool,
    max_rows: int = MAX_VERIFY_ROWS,
) -> ChainVerification:
    """Walk the chain in ``seq`` order and report the first link that does not hold.

    Three failures are reported, not one. A **mutated** row breaks its own MAC; a **prefix**
    excision leaves a survivor whose ``prev_hmac`` no anchor accounts for; a **tail**
    excision leaves a head below the newest HEAD anchor. Only the first of those was
    detected before — which meant an attacker who deleted rows rather than editing them got
    a green badge.
    """
    protection = await resolve_chain_protection(session, is_dsn_configured=is_dsn_configured)
    truncations = await _read_truncation_anchors(session)
    anchors = tuple(
        sorted(
            anchor.truncated_below_seq
            for anchor in truncations
            if anchor.truncated_below_seq is not None
        )
    )
    checked = 0
    last_seq = 0
    prev: str | None = None
    while checked < max_rows:
        rows, break_seq, prev = await _verify_batch(
            session,
            key=key,
            after_seq=last_seq,
            limit=min(VERIFY_BATCH_SIZE, max_rows - checked),
            prev=prev,
            truncations=truncations,
        )
        checked += len(rows)
        if break_seq is not None:
            return ChainVerification(
                is_ok=False,
                first_break_seq=break_seq,
                checked_rows=checked,
                last_seq=rows[-1].seq,
                # Conclusive, not incomplete: the walk stopped because it found the answer.
                is_complete=True,
                protection=protection,
                anchors=anchors,
            )
        if not rows:
            break
        last_seq = rows[-1].seq
        if len(rows) < VERIFY_BATCH_SIZE:
            break
    is_ceiling_reached = checked >= max_rows
    tail = None if is_ceiling_reached else await _tail_break(session, last_seq=last_seq)
    return ChainVerification(
        is_ok=tail is None,
        first_break_seq=tail,
        checked_rows=checked,
        last_seq=last_seq or None,
        is_complete=not is_ceiling_reached,
        protection=protection,
        anchors=anchors,
    )


# ---------------------------------------------------------------------------
# Anchors — the head, recorded outside the table it protects
# ---------------------------------------------------------------------------
async def _write_anchor(
    session: AsyncSession,
    *,
    kind: AuditAnchorKind,
    seq: int,
    chain_hmac: str,
    now: datetime,
    truncated_below_seq: int | None = None,
    rows_deleted: int | None = None,
) -> AuditChainAnchorRow:
    """Insert the anchor **and** emit it as a log line. Both, always (§5.5)."""
    row = AuditChainAnchorRow(
        at=now,
        kind=kind,
        seq=seq,
        chain_hmac=chain_hmac,
        truncated_below_seq=truncated_below_seq,
        rows_deleted=rows_deleted,
    )
    session.add(row)
    await session.flush()
    _LOGGER.info(
        "audit chain anchor",
        extra={
            "event": "admin.audit.anchor",
            "kind": str(kind),
            "seq": seq,
            "hash": chain_hmac,
            "truncated_below_seq": truncated_below_seq,
            "rows_deleted": rows_deleted,
        },
    )
    return row


async def write_head_anchor(session: AsyncSession, *, now: datetime) -> AuditChainAnchorRow | None:
    """Pin the current head. ``None`` when nothing has been audited yet — there is no head."""
    head = await read_head(session)
    if head is None:
        return None
    return await _write_anchor(
        session, kind=AuditAnchorKind.HEAD, seq=head.seq, chain_hmac=head.chain_hmac, now=now
    )


async def write_truncation_anchor(
    session: AsyncSession, *, below_seq: int, rows_deleted: int, now: datetime
) -> AuditChainAnchorRow | None:
    """Record where the 730-day sweep cut the chain, so the cut is not read as tampering."""
    surviving = (
        (await session.execute(sa.select(AdminAuditRow).order_by(AdminAuditRow.seq).limit(1)))
        .scalars()
        .first()
    )
    if surviving is None:
        return None
    return await _write_anchor(
        session,
        kind=AuditAnchorKind.TRUNCATION,
        seq=surviving.seq,
        chain_hmac=surviving.chain_hmac,
        now=now,
        truncated_below_seq=below_seq,
        rows_deleted=rows_deleted,
    )


async def read_truncation_points(session: AsyncSession) -> tuple[int, ...]:
    """Every recorded cut, oldest first — the seqs below which a gap is expected."""
    statement = (
        sa.select(AuditChainAnchorRow.truncated_below_seq)
        .where(
            AuditChainAnchorRow.kind == AuditAnchorKind.TRUNCATION,
            AuditChainAnchorRow.truncated_below_seq.is_not(None),
        )
        .order_by(AuditChainAnchorRow.truncated_below_seq)
    )
    return tuple(seq for seq in (await session.execute(statement)).scalars().all() if seq)


# ---------------------------------------------------------------------------
# Which layers are actually deployed
# ---------------------------------------------------------------------------
_PRIVILEGE_PROBE: Final[str] = """
SELECT
    has_table_privilege(current_user, 'admin_audit_log', 'UPDATE')
    OR has_table_privilege(current_user, 'admin_audit_log', 'DELETE')
    OR has_table_privilege(current_user, 'admin_audit_log', 'TRUNCATE') AS is_writable
"""


async def resolve_chain_protection(
    session: AsyncSession, *, is_dsn_configured: bool
) -> ChainProtection:
    """What is really protecting the table — asked of the database, not of the configuration.

    ``admin_audit_dsn`` being set means the two-role setup was *intended*. Whether it landed
    is a question only Postgres can answer, so this asks it: if this connection can still
    ``UPDATE``, ``DELETE`` or ``TRUNCATE`` the log, the revoke is not in force and the honest
    answer is ``hmac-only`` — with a WARNING, because somebody believes otherwise.
    """
    if not is_dsn_configured or not _is_postgres(session):
        return ChainProtection.HMAC_ONLY
    try:
        is_writable = bool(await session.scalar(sa.text(_PRIVILEGE_PROBE)))
    except SQLAlchemyError as exc:
        _LOGGER.warning(
            "could not read the audit table's privileges; reporting the weaker guarantee",
            extra={"event": "admin.audit.privilege_probe_failed", "detail": repr(exc)},
        )
        return ChainProtection.HMAC_ONLY
    if is_writable:
        _LOGGER.warning(
            "the audit REVOKE is configured but not in force; the app role can still write",
            extra={"event": "admin.audit.revoke_missing"},
        )
        return ChainProtection.HMAC_ONLY
    return ChainProtection.REVOKE_HMAC
