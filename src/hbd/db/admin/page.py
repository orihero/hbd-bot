"""Keyset pagination, in one place so every admin list endpoint shares it.

**Why not OFFSET.** ``orders`` and ``generation_attempts`` only grow, and the page an
operator reaches for under pressure is the deep one — "show me every failure this quarter".
``OFFSET 40000`` makes the database walk and discard forty thousand rows to hand back fifty,
every page, forever. Keyset carries the last row's sort key instead and turns each page into
an indexed range scan whose cost does not depend on how far in it is. It is also the repo's
own standing rule 12 ("bound every list query"), and the reason
``repository.MAX_ORDER_HISTORY`` exists at all.

**The key is ``(created_at, id)``, descending.** ``created_at`` alone is not unique — two
orders created in the same millisecond would make one of them unreachable or repeat the
other — so the primary key is appended as a total-order tie-break. The predicate is written
out longhand as ``at < :at OR (at = :at AND id < :id)`` rather than as a row-value
comparison ``(at, id) < (:at, :id)``: both dialects accept the row-value form, but only the
longhand is guaranteed to be planned against a ``(filter_column, created_at)`` index on
every version of both, and this is exactly the query the indexes in migration ``0009``
exist to serve.

**The cursor is opaque and untrusted.** It arrives as a query string from a browser, so
:func:`decode_cursor` is a never-throw boundary that returns ``Result`` — the project's rule
on parsing text you did not construct applies to a base64 blob exactly as it applies to an
LLM payload. It validates shape, not just syntax: a well-formed base64 JSON object with a
naive timestamp is still rejected, because ``UtcDateTime`` would raise ``ValueError`` on it
deep inside the driver where no handler is looking.

**Termination.** ``LIMIT n + 1`` is fetched, the extra row is dropped, and its existence is
the entire signal for "there is a next page". No count, no second query, and the last page
returns ``next_cursor=None`` because the extra row was not there.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from hbd.contracts import Result, err, is_err, ok
from hbd.errors import ValidationError

__all__ = [
    "MIN_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "DEFAULT_PAGE_LIMIT",
    "TOTAL_COUNT_CAP",
    "Cursor",
    "PageRequest",
    "Page",
    "BoundedTotal",
    "encode_cursor",
    "decode_cursor",
    "page_request",
    "keyset_predicate",
    "keyset_order",
    "build_page",
    "bounded_total",
]

#: §6.1. One is the smallest useful page; two hundred is the ceiling a single JSON response
#: and a single index range scan both stay comfortable at.
MIN_PAGE_LIMIT: Final[int] = 1
MAX_PAGE_LIMIT: Final[int] = 200
DEFAULT_PAGE_LIMIT: Final[int] = 50

#: ``?withTotal=true`` counts a bounded subquery so "10,000+" is honest rather than a lie or
#: a full table scan. Exactly this many rows means "at least this many", not "this many".
TOTAL_COUNT_CAP: Final[int] = 10_000

_CURSOR_AT: Final[str] = "at"
_CURSOR_ID: Final[str] = "id"
#: A cursor is two short fields; anything larger did not come from us.
_MAX_CURSOR_CHARS: Final[int] = 256


@dataclass(frozen=True, slots=True)
class Cursor:
    """The sort key of the last row of a page. Aware timestamps only."""

    at: datetime
    id: UUID

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError(f"cursor timestamp must be timezone-aware, got {self.at!r}")


@dataclass(frozen=True, slots=True)
class PageRequest:
    """A validated page request: how many rows, and where to resume from."""

    limit: int = DEFAULT_PAGE_LIMIT
    cursor: Cursor | None = None

    def __post_init__(self) -> None:
        if not MIN_PAGE_LIMIT <= self.limit <= MAX_PAGE_LIMIT:
            raise ValueError(f"limit must be {MIN_PAGE_LIMIT}..{MAX_PAGE_LIMIT}, got {self.limit}")

    @property
    def fetch_limit(self) -> int:
        """One more row than the caller asked for — the probe that detects a next page."""
        return self.limit + 1


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of view models plus the cursor that fetches the next one.

    ``next_cursor`` is ``None`` on the last page and on an empty one. Nothing else means
    "the end", so a client's loop terminates on one condition.
    """

    items: tuple[T, ...]
    next_cursor: str | None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


@dataclass(frozen=True, slots=True)
class BoundedTotal:
    """A row count that stopped at :data:`TOTAL_COUNT_CAP`.

    ``is_exact`` is false when the count hit the cap, so the UI renders "10,000+" instead of
    a number it would otherwise state with unearned confidence.
    """

    total: int
    is_exact: bool


def encode_cursor(cursor: Cursor) -> str:
    """Serialise a cursor to the opaque base64url token §6.1 specifies."""
    payload = json.dumps(
        {_CURSOR_AT: cursor.at.isoformat(), _CURSOR_ID: str(cursor.id)},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(raw: str) -> Result[Cursor]:
    """Parse a cursor from a query string. Never raises; every failure is a typed ``Err``.

    Six things can be wrong with an inbound cursor — oversize, bad base64, bad UTF-8, bad
    JSON, a missing or non-string field, an unparseable timestamp or UUID — and all of them
    mean the same thing to the caller (422, "cursor is not one of ours"), so they collapse
    into one error rather than a taxonomy nobody branches on.
    """
    if len(raw) > _MAX_CURSOR_CHARS:
        return err(_bad_cursor("cursor is too long"))
    try:
        decoded = base64.urlsafe_b64decode(_padded(raw))
        fields = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, ValueError) as exc:
        # ``ValueError`` covers UnicodeDecodeError and json.JSONDecodeError, both subclasses.
        return err(_bad_cursor("cursor is not decodable", cause=exc))
    return _cursor_from_fields(fields)


def page_request(*, limit: int | None = None, cursor: str | None = None) -> Result[PageRequest]:
    """Validate the two query parameters every list endpoint takes.

    Out-of-range limits are rejected rather than clamped: silently serving 200 rows to a
    caller who asked for 5,000 hides a client bug that will surface later as a timeout.
    """
    resolved = DEFAULT_PAGE_LIMIT if limit is None else limit
    if not MIN_PAGE_LIMIT <= resolved <= MAX_PAGE_LIMIT:
        return err(
            ValidationError(
                f"limit must be between {MIN_PAGE_LIMIT} and {MAX_PAGE_LIMIT}",
                context={"limit": resolved},
            )
        )
    if cursor is None:
        return ok(PageRequest(limit=resolved))
    decoded = decode_cursor(cursor)
    if is_err(decoded):
        return decoded
    return ok(PageRequest(limit=resolved, cursor=decoded.value))


def keyset_predicate(
    at_column: sa.SQLColumnExpression[datetime],
    id_column: sa.SQLColumnExpression[UUID],
    cursor: Cursor | None,
) -> ColumnElement[bool] | None:
    """``WHERE`` clause resuming after ``cursor``, or ``None`` for the first page."""
    if cursor is None:
        return None
    return sa.or_(
        at_column < cursor.at,
        sa.and_(at_column == cursor.at, id_column < cursor.id),
    )


def keyset_order(
    at_column: sa.SQLColumnExpression[datetime], id_column: sa.SQLColumnExpression[UUID]
) -> tuple[ColumnElement[Any], ColumnElement[Any]]:
    """Newest first, with the primary key as the total-order tie-break."""
    return (at_column.desc(), id_column.desc())


def build_page[T](rows: Sequence[T], request: PageRequest, key: Callable[[T], Cursor]) -> Page[T]:
    """Trim the ``limit + 1`` probe row and emit the next cursor if it was there.

    ``key`` extracts the sort key from a view model rather than from a database row, so the
    cursor a client receives is derived from exactly the values it was ordered by.
    """
    if len(rows) <= request.limit:
        return Page(items=tuple(rows), next_cursor=None)
    kept = tuple(rows[: request.limit])
    return Page(items=kept, next_cursor=encode_cursor(key(kept[-1])))


async def bounded_total(session: AsyncSession, statement: Select[Any]) -> BoundedTotal:
    """``SELECT count(*) FROM (SELECT 1 FROM … LIMIT 10001) s`` — §6.1's honest total.

    The inner ``LIMIT`` is what keeps ``?withTotal=true`` from becoming the full table scan
    the whole keyset design exists to avoid. ``statement`` must already carry the page's
    filters and must NOT carry its keyset predicate — a total is over the filtered set, not
    over the tail of it.
    """
    # ``maintain_column_froms`` is load-bearing: without it ``with_only_columns`` discards
    # the FROM the original columns implied and the probe becomes a bare ``SELECT 1``, which
    # counts one row no matter how many the filters match.
    trimmed = statement.with_only_columns(sa.literal(1), maintain_column_froms=True)
    probe = trimmed.limit(TOTAL_COUNT_CAP + 1).subquery()
    counted = await session.scalar(sa.select(sa.func.count()).select_from(probe))
    total = int(counted or 0)
    if total > TOTAL_COUNT_CAP:
        return BoundedTotal(total=TOTAL_COUNT_CAP, is_exact=False)
    return BoundedTotal(total=total, is_exact=True)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _padded(raw: str) -> bytes:
    """Restore the ``=`` padding a URL-safe encoder may have stripped."""
    return (raw + "=" * (-len(raw) % 4)).encode("ascii", errors="ignore")


def _bad_cursor(message: str, *, cause: Exception | None = None) -> ValidationError:
    # The offending value is deliberately NOT in the context: it is attacker-supplied text
    # that would otherwise be interpolated into a log line and an error body.
    return ValidationError(message, context={"parameter": "cursor"}, cause=cause)


def _cursor_from_fields(fields: object) -> Result[Cursor]:
    """Validate a decoded JSON object into a cursor. Shape, not just syntax.

    Unknown keys are **refused**, matching the ``extra="forbid"`` posture the API schemas
    keep. Ignoring them was harmless in practice — an extra key never reached SQL, and the
    two that are read are coerced to ``datetime`` and ``UUID`` and then bound — but it was
    the one lenient spot in a boundary whose docstring promises to validate shape, and a
    deliberate decision beats an accidental one.
    """
    if not isinstance(fields, dict):
        return err(_bad_cursor("cursor is not an object"))
    if set(fields) - {_CURSOR_AT, _CURSOR_ID}:
        return err(_bad_cursor("cursor carries fields this endpoint does not issue"))
    at_raw = fields.get(_CURSOR_AT)
    id_raw = fields.get(_CURSOR_ID)
    if not isinstance(at_raw, str) or not isinstance(id_raw, str):
        return err(_bad_cursor("cursor is missing its position fields"))
    try:
        at = datetime.fromisoformat(at_raw)
        row_id = UUID(id_raw)
    except ValueError as exc:
        return err(_bad_cursor("cursor position is unparseable", cause=exc))
    if at.tzinfo is None:
        # UtcDateTime rejects naive values inside the driver, where nothing catches it.
        return err(_bad_cursor("cursor timestamp has no offset"))
    return ok(Cursor(at=at, id=row_id))
