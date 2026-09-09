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

**Sorting is a second cursor, not a wider one.** ``BROADCAST_SPEC §1.6`` asks for lists
ordered by things other than ``created_at``, and a sort key that is not carried in the
cursor cannot be resumed. :class:`SortedCursor` carries the sort value, the key it was
minted under and its direction, so a token replayed after the operator changed the sort is
**refused** (:func:`decode_sorted_cursor`) rather than resumed halfway through a different
ordering, which is how a page silently repeats or skips rows. Three invariants make the
sorted walk safe: the key is total (:func:`total_sort_key` — no NULL, so no dialect
disagreement about where NULLs land and no row the cursor cannot name), the primary key is
still the tie-break in the same direction as the key itself, and the key is an expression
object the caller resolved from an allowlist — no string from the wire ever reaches
``ORDER BY``. :class:`Cursor` and its two helpers are untouched by any of this; a list that
has one order keeps the smaller token.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Literal
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
    "SORT_EPOCH",
    "Cursor",
    "PageRequest",
    "Page",
    "BoundedTotal",
    "SortDirection",
    "SortValue",
    "SortValueKind",
    "SortSpec",
    "SortedCursor",
    "encode_cursor",
    "decode_cursor",
    "page_request",
    "keyset_predicate",
    "keyset_order",
    "build_page",
    "bounded_total",
    "encode_sorted_cursor",
    "decode_sorted_cursor",
    "total_sort_key",
    "sorted_keyset_predicate",
    "sorted_keyset_order",
    "build_sorted_page",
]

#: §6.1. One is the smallest useful page; two hundred is the ceiling a single JSON response
#: and a single index range scan both stay comfortable at.
MIN_PAGE_LIMIT: Final[int] = 1
MAX_PAGE_LIMIT: Final[int] = 200
DEFAULT_PAGE_LIMIT: Final[int] = 50

#: ``?withTotal=true`` counts a bounded subquery so "10,000+" is honest rather than a lie or
#: a full table scan. Exactly this many rows means "at least this many", not "this many".
TOTAL_COUNT_CAP: Final[int] = 10_000

#: What a never-happened instant sorts as once :func:`total_sort_key` has made the key
#: total. The UI states the consequence rather than hiding it: "never ordered" sorts oldest.
SORT_EPOCH: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)

_CURSOR_AT: Final[str] = "at"
_CURSOR_ID: Final[str] = "id"
#: The sorted cursor's own fields. One letter each: the token is base64 of JSON and is
#: repeated in every "next page" link, so the names are paid for on the wire every time.
_CURSOR_SORT_KEY: Final[str] = "k"
_CURSOR_SORT_DIRECTION: Final[str] = "d"
_CURSOR_SORT_VALUE: Final[str] = "v"
#: A cursor is two short fields; anything larger did not come from us.
_MAX_CURSOR_CHARS: Final[int] = 256

_SORTED_CURSOR_FIELDS: Final[frozenset[str]] = frozenset(
    {_CURSOR_SORT_KEY, _CURSOR_SORT_DIRECTION, _CURSOR_SORT_VALUE, _CURSOR_ID}
)
_ASCENDING: Final[str] = "asc"
_DESCENDING: Final[str] = "desc"
_SORT_DIRECTIONS: Final[frozenset[str]] = frozenset({_ASCENDING, _DESCENDING})

#: Two members, compared and never iterated, so a ``Literal`` alias rather than a StrEnum —
#: the same shape ``config.LogLevel`` uses.
type SortDirection = Literal["asc", "desc"]

#: Everything a sort key may be. Instants and integers, and deliberately nothing else: a
#: text sort key would mean ordering accounts by a name, and a total order over names is the
#: unmask oracle ``db/admin/users.py``'s ``_SEARCHABLE_COLUMNS`` already refuses. Adding a
#: third member is therefore a privacy decision, not a typing one.
type SortValue = datetime | int


@dataclass(frozen=True, slots=True)
class Cursor:
    """The sort key of the last row of a page. Aware timestamps only."""

    at: datetime
    id: UUID

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError(f"cursor timestamp must be timezone-aware, got {self.at!r}")


class SortValueKind(StrEnum):
    """How a sort value is written into a cursor and read back out of one.

    The kind is supplied by the caller's field registry, never inferred from the token: an
    ISO-8601 instant and a decimal integer are both strings on the wire, and guessing which
    one a value is would make the parse depend on the data rather than on the schema.
    """

    INSTANT = "instant"
    INTEGER = "integer"


@dataclass(frozen=True, slots=True)
class SortSpec:
    """What a list is ordered by. ``key`` is a NAME, never a column.

    The caller resolves ``key`` against its own allowlist and hands this module the
    resulting expression object, so an unknown key is a 422 at the registry and no string
    from a query parameter ever reaches ``ORDER BY``.
    """

    key: str
    direction: SortDirection = "desc"

    def __post_init__(self) -> None:
        if self.direction not in _SORT_DIRECTIONS:
            raise ValueError(f"sort direction must be asc or desc, got {self.direction!r}")


@dataclass(frozen=True, slots=True)
class SortedCursor:
    """The position of the last row of a page, under an explicit sort.

    ``k`` and ``d`` are the sort this cursor was minted under, and they are carried for one
    reason: to be *checked*. Resuming a ``delivered_order_count`` cursor inside a
    ``last_order_at`` ordering is not a smaller bug than an off-by-one — it silently pages
    over rows and repeats others — so the mismatch is refused at the boundary instead.
    """

    k: str
    d: SortDirection
    v: SortValue
    id: UUID

    def __post_init__(self) -> None:
        if self.d not in _SORT_DIRECTIONS:
            raise ValueError(f"sort direction must be asc or desc, got {self.d!r}")
        if isinstance(self.v, datetime) and self.v.tzinfo is None:
            raise ValueError(f"cursor sort value must be timezone-aware, got {self.v!r}")

    @property
    def sort(self) -> SortSpec:
        """The sort this cursor belongs to, for comparison against the requested one."""
        return SortSpec(key=self.k, direction=self.d)


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


def encode_sorted_cursor(cursor: SortedCursor) -> str:
    """Serialise a sorted cursor to the same opaque base64url shape §6.1 specifies.

    The value is written as canonical text — ISO-8601 for an instant, decimal for an integer
    — so the token a client holds does not depend on how JSON happened to render a number.
    """
    payload = json.dumps(
        {
            _CURSOR_SORT_KEY: cursor.k,
            _CURSOR_SORT_DIRECTION: cursor.d,
            _CURSOR_SORT_VALUE: _encode_sort_value(cursor.v),
            _CURSOR_ID: str(cursor.id),
        },
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_sorted_cursor(raw: str, *, sort: SortSpec, kind: SortValueKind) -> Result[SortedCursor]:
    """Parse a sorted cursor AND check it belongs to ``sort``. Never raises.

    Everything :func:`decode_cursor` refuses is refused here for the same reasons, plus the
    one failure that only a sorted list has: a token minted under another sort. That is a
    ``ValidationError`` — a 422 the operator sees as "this cursor belongs to a different
    sort" — and never a silent resume, because the two orders interleave differently and the
    page would drop rows without anything looking wrong.

    ``kind`` says how to read the value; it comes from the caller's field registry, which is
    also where ``sort.key`` was resolved, so the two cannot drift apart.
    """
    if len(raw) > _MAX_CURSOR_CHARS:
        return err(_bad_cursor("cursor is too long"))
    try:
        decoded = base64.urlsafe_b64decode(_padded(raw))
        fields = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, ValueError) as exc:
        return err(_bad_cursor("cursor is not decodable", cause=exc))
    return _sorted_cursor_from_fields(fields, sort=sort, kind=kind)


def total_sort_key(
    expression: sa.SQLColumnExpression[Any], *, absent: SortValue
) -> ColumnElement[Any]:
    """``COALESCE(expression, absent)`` — a nullable sort key made total.

    A NULL in the sort key breaks keyset paging three ways at once: SQLite and PostgreSQL
    put NULLs at opposite ends by default, ``expression < NULL`` is NULL rather than true so
    a page boundary landing on a NULL row loses every row behind it, and the cursor has no
    value to carry for the row it stopped on. ``COALESCE`` deletes the case instead of
    teaching every call site about it — "never delivered" sorts as :data:`SORT_EPOCH`,
    "never ordered" sorts as ``0`` — and the UI says so rather than leaving an operator to
    infer it from the bottom of a list.

    The fallback is bound with an explicit type rather than an inferred one: an aware
    datetime inferred as ``TIMESTAMP WITHOUT TIME ZONE`` is rejected by asyncpg at execution
    time, on PostgreSQL only, which is the one place no unit test would catch it.
    """
    return sa.func.coalesce(expression, sa.literal(absent, type_=_absent_type(absent)))


def sorted_keyset_predicate(
    sort_column: sa.SQLColumnExpression[Any],
    id_column: sa.SQLColumnExpression[UUID],
    cursor: SortedCursor | None,
    *,
    sort: SortSpec,
) -> ColumnElement[bool] | None:
    """``WHERE`` clause resuming after ``cursor`` under ``sort``, or ``None`` for page one.

    ``sort_column`` must be the same total expression :func:`sorted_keyset_order` is given —
    :func:`total_sort_key` is how it is made total — and the longhand ``key < :key OR (key =
    :key AND id < :id)`` is written out for the reason the module docstring gives.

    A cursor from another sort raises: :func:`decode_sorted_cursor` is the boundary that
    turns that into a 422, so reaching this function with a mismatch means a caller skipped
    the boundary, which is a bug in our code and not in the request.
    """
    if cursor is None:
        return None
    if cursor.sort != sort:
        raise ValueError(f"cursor was minted under a different sort than {sort.key!r}")
    if sort.direction == _ASCENDING:
        return sa.or_(
            sort_column > cursor.v,
            sa.and_(sort_column == cursor.v, id_column > cursor.id),
        )
    return sa.or_(
        sort_column < cursor.v,
        sa.and_(sort_column == cursor.v, id_column < cursor.id),
    )


def sorted_keyset_order(
    sort_column: sa.SQLColumnExpression[Any],
    id_column: sa.SQLColumnExpression[UUID],
    *,
    direction: SortDirection,
) -> tuple[ColumnElement[Any], ColumnElement[Any]]:
    """The sort key, then the primary key as the total-order tie-break.

    The tie-break follows the key's direction rather than staying descending: the predicate
    resumes a tie-block with ``id > :id`` under ``asc``, and an ``ORDER BY key ASC, id DESC``
    would walk that block the other way — every page would hand back rows the predicate had
    already excluded, and the block would be paged through once per page instead of once.
    """
    if direction == _ASCENDING:
        return (sort_column.asc(), id_column.asc())
    return (sort_column.desc(), id_column.desc())


def build_sorted_page[T](
    rows: Sequence[T], request: PageRequest, key: Callable[[T], SortedCursor]
) -> Page[T]:
    """:func:`build_page` for a sorted list: same probe row, sorted token."""
    if len(rows) <= request.limit:
        return Page(items=tuple(rows), next_cursor=None)
    kept = tuple(rows[: request.limit])
    return Page(items=kept, next_cursor=encode_sorted_cursor(key(kept[-1])))


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


def _sorted_cursor_from_fields(
    fields: object, *, sort: SortSpec, kind: SortValueKind
) -> Result[SortedCursor]:
    """Validate a decoded JSON object into a sorted cursor, against the requested sort."""
    if not isinstance(fields, dict):
        return err(_bad_cursor("cursor is not an object"))
    if set(fields) != _SORTED_CURSOR_FIELDS:
        return err(_bad_cursor("cursor carries fields this endpoint does not issue"))
    key_raw = fields[_CURSOR_SORT_KEY]
    direction_raw = fields[_CURSOR_SORT_DIRECTION]
    value_raw = fields[_CURSOR_SORT_VALUE]
    id_raw = fields[_CURSOR_ID]
    if not isinstance(key_raw, str) or not isinstance(direction_raw, str):
        return err(_bad_cursor("cursor is missing its sort"))
    if not isinstance(value_raw, str) or not isinstance(id_raw, str):
        return err(_bad_cursor("cursor is missing its position fields"))
    # Checked BEFORE the value is parsed. A cursor from another sort carries a value of
    # another kind, so parsing first would report "unparseable" to an operator whose only
    # mistake was to change the sort with a next-page link still in hand.
    if key_raw != sort.key or direction_raw != sort.direction:
        return err(_bad_cursor("cursor belongs to a different sort"))
    try:
        row_id = UUID(id_raw)
    except ValueError as exc:
        return err(_bad_cursor("cursor position is unparseable", cause=exc))
    value = _sort_value_from_text(value_raw, kind)
    if is_err(value):
        return value
    # ``k`` and ``d`` are taken from ``sort``, not from the token: they were just proved
    # equal, and this way nothing that arrived over the wire survives into the query.
    return ok(SortedCursor(k=sort.key, d=sort.direction, v=value.value, id=row_id))


def _encode_sort_value(value: SortValue) -> str:
    """Canonical text for a sort value. The inverse of :func:`_sort_value_from_text`."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sort_value_from_text(raw: str, kind: SortValueKind) -> Result[SortValue]:
    if kind is SortValueKind.INSTANT:
        try:
            at = datetime.fromisoformat(raw)
        except ValueError as exc:
            return err(_bad_cursor("cursor position is unparseable", cause=exc))
        if at.tzinfo is None:
            # As in :func:`_cursor_from_fields`: naive values raise inside the driver.
            return err(_bad_cursor("cursor timestamp has no offset"))
        instant: SortValue = at
        return ok(instant)
    try:
        count: SortValue = int(raw)
    except ValueError as exc:
        return err(_bad_cursor("cursor position is unparseable", cause=exc))
    return ok(count)


def _absent_type(absent: SortValue) -> sa.types.TypeEngine[Any]:
    """The bind type :func:`total_sort_key` gives its fallback. See that docstring."""
    if isinstance(absent, datetime):
        if absent.tzinfo is None:
            raise ValueError(f"the absent sort value must be timezone-aware, got {absent!r}")
        return sa.DateTime(timezone=True)
    return sa.Integer()
