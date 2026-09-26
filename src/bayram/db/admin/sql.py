"""Query fragments the admin read modules share. No session, no view models.

Three things live here because writing them four times is how four subtly different
answers get shipped:

* :class:`DurationSeconds` — subtracting two instants is the one piece of arithmetic that
  has no portable spelling. Postgres wants ``EXTRACT(EPOCH FROM (a - b))``; SQLite has no
  interval type at all and wants ``(julianday(a) - julianday(b)) * 86400``. The whole
  latency metric depends on ordering rows *by duration*, which cannot be done in Python
  without fetching every delivered order — so the expression is compiled per dialect and
  the percentile stays a database operation.
* :class:`TimeWindow` — every dashboard query takes ``from``/``to``. §6.1 says a naive
  datetime is a 422, and it has to be caught here rather than at the column: ``UtcDateTime``
  raises ``ValueError`` inside the driver's bind processor, where ``run_guarded`` does not
  look and no handler is waiting.
* :func:`count_where` — a conditional count. ``count(CASE WHEN … THEN 1 END)`` rather than
  ``sum(CASE … ELSE 0 END)`` because ``count`` is never ``NULL``: an empty group reads as
  ``0`` without a ``COALESCE`` anybody can forget.
* :func:`search_clause` — the ``?q=`` predicate. Free text going into a ``LIKE`` is the one
  place in this layer where a caller's characters change the *shape* of the query rather
  than its parameters, so the escaping and the length cap are written once here instead of
  once per resource that grows a search box.

Nothing here fetches rows into Python to work on them. That is the standing rule for the
metrics module and this is the toolkit that makes it keepable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import ColumnElement, Select, or_
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.functions import FunctionElement

from bayram.contracts import Result, err, ok
from bayram.db.models import Base
from bayram.errors import ValidationError

__all__ = [
    "DurationSeconds",
    "TimeWindow",
    "InstantColumn",
    "time_window",
    "apply_window",
    "apply_in",
    "apply_search",
    "count_where",
    "escape_like",
    "search_clause",
    "MAX_SEARCH_CHARS",
    "LIKE_ESCAPE_CHAR",
    "UtcDay",
    "UtcHour",
    "SeriesGrain",
    "bucket_expression",
    "bucket_started_at",
    "previous_window",
    "spanning_window",
    "count_pair",
    "nearest_rank_offset",
    "has_table",
    "CHAT_MESSAGES_TABLE",
    "PAYMENTS_TABLE",
    "VENDOR_USAGE_TABLE",
]

#: A column of instants, nullable or not. ``orders.delivered_at`` is ``datetime | None`` and
#: is exactly the column the throughput series windows on, so every helper below that takes
#: "a timestamp column" has to accept both spellings or the honest query does not type-check.
#: Widening here rather than casting at four call sites: a ``cast`` would silence the checker
#: at the one place it is actually telling the truth about a nullable column.
type InstantColumn = sa.SQLColumnExpression[datetime] | sa.SQLColumnExpression[datetime | None]

_SECONDS_PER_DAY = 86_400.0

#: Tables later phases add. Named rather than spelled inline so the capability probe and
#: the timeline's "not enabled here" list cannot drift apart on a typo.
CHAT_MESSAGES_TABLE: Final[str] = "chat_messages"
PAYMENTS_TABLE: Final[str] = "payments"

#: The vendor spend ledger. Named here for the same reason as the two above, but read for a
#: different one: its capabilities are ROW probes rather than :func:`has_table` probes, so
#: this constant names the table a reader is looking for and never stands in for the probe.
#: A migration that landed on a deployment whose worker has never written is honestly "not
#: instrumented", and ``has_table`` would call it instrumented.
VENDOR_USAGE_TABLE: Final[str] = "vendor_usage"


def has_table(name: str) -> bool:
    """True when ``name`` is part of the installed schema.

    Read from ``Base.metadata`` rather than from a hardcoded constant so a capability flips
    itself on the day the migration that creates the table lands, instead of waiting for
    somebody to remember a boolean in an unrelated module.
    """
    return name in Base.metadata.tables


class DurationSeconds(FunctionElement[float]):
    """``end - start`` as a float number of seconds, on either dialect.

    Constructed as ``DurationSeconds(start, end)``. ``inherit_cache`` is ``True`` because
    the rendering depends only on the compiled children, which is exactly the condition
    SQLAlchemy's statement cache requires.
    """

    inherit_cache = True
    name = "duration_seconds"
    type = sa.Float()


@compiles(DurationSeconds)
def _compile_duration(element: DurationSeconds, compiler: SQLCompiler, **kw: Any) -> str:
    """Default rendering — ANSI ``EXTRACT``, which is what Postgres runs."""
    start, end = _duration_operands(element, compiler, **kw)
    return f"EXTRACT(EPOCH FROM ({end} - {start}))"


@compiles(DurationSeconds, "sqlite")
def _compile_duration_sqlite(element: DurationSeconds, compiler: SQLCompiler, **kw: Any) -> str:
    """SQLite has no interval type; ``julianday`` returns days as a float."""
    start, end = _duration_operands(element, compiler, **kw)
    return f"((julianday({end}) - julianday({start})) * {_SECONDS_PER_DAY})"


def _duration_operands(
    element: DurationSeconds, compiler: SQLCompiler, **kw: Any
) -> tuple[str, str]:
    start, end = tuple(element.clauses)
    return compiler.process(start, **kw), compiler.process(end, **kw)


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A half-open ``[start, end)`` of aware instants, open below when ``start`` is ``None``.

    Half-open rather than closed so consecutive windows tile without double-counting the
    row that lands exactly on a boundary — the bug that makes two adjacent daily buckets
    both claim the same midnight order.

    **``start`` is optional and ``end`` is not**, which looks lopsided until you ask what the
    missing half would have to be. "Everything up to Y" has a real, expressible meaning — drop
    the lower predicate and the query says exactly that — so ``start=None`` costs nothing and
    invents nothing. "Everything from X onwards" has no such spelling: the upper bound would
    have to be *some* instant, and the only defensible one is the moment the caller was
    served. That is a decision about a request, not about a query, so it is made one layer up
    in :func:`bayram.admin.window.resolve_window` and this type never sees a fabricated bound.
    An epoch sentinel for the lower bound was the alternative and is what the ``None`` exists
    to avoid: ``created_at >= 0001-01-01`` is a predicate the planner must still evaluate and
    a number an operator reading an echoed window never typed.
    """

    start: datetime | None
    end: datetime

    def __post_init__(self) -> None:
        if (self.start is not None and self.start.tzinfo is None) or self.end.tzinfo is None:
            raise ValueError("time window bounds must be timezone-aware")
        if self.start is not None and self.end < self.start:
            raise ValueError("time window ends before it starts")


def time_window(start: datetime | None, end: datetime) -> Result[TimeWindow]:
    """Validate a caller-supplied window. Never raises; a bad window is a typed ``Err``.

    The single owner of "``to`` before ``from``" for every caller, HTTP or not. A ``start`` of
    ``None`` skips that check because there is nothing to compare, not because the check was
    waived.
    """
    try:
        return ok(TimeWindow(start=start, end=end))
    except ValueError as exc:
        return err(ValidationError(str(exc), context={"parameter": "window"}, cause=exc))


def apply_window[R: tuple[Any, ...]](
    statement: Select[R], column: InstantColumn, window: TimeWindow | None
) -> Select[R]:
    """Restrict ``statement`` to ``window``, or return it untouched when there is none.

    An open lower bound emits **no** lower predicate rather than a comparison against a
    sentinel: same rows, one less clause, and nothing in the plan that a reader would have to
    trace back to a constant nobody chose.
    """
    if window is None:
        return statement
    if window.start is None:
        return statement.where(column < window.end)
    return statement.where(column >= window.start, column < window.end)


def apply_in[R: tuple[Any, ...], V](
    statement: Select[R], column: sa.SQLColumnExpression[V], values: tuple[V, ...]
) -> Select[R]:
    """OR-within-a-field filtering (§6.1). An empty tuple means "no filter", not "match none".

    That asymmetry is deliberate and is the whole reason this helper exists: ``IN ()`` is
    the query that quietly returns an empty page when a caller passes no values, and every
    filter on every list endpoint would otherwise have to remember its own guard.
    """
    if not values:
        return statement
    if len(values) == 1:
        return statement.where(column == values[0])
    return statement.where(column.in_(values))


#: Longest ``?q=`` this layer will hand to a ``LIKE``. A leading-wildcard pattern cannot use
#: a b-tree index on any dialect, so every search is a scan and the only cost left to bound is
#: the *per-row* one: ``LIKE`` backtracks, and its worst case grows with the pattern, so an
#: 8 KB ``q`` turns a scan of a few thousand rows into work nobody asked for on the process
#: that also serves ``/readyz``. Sixty-four characters is longer than any correlation id
#: (32), any telegram id (19 digits) and any recipient display name this system stores.
MAX_SEARCH_CHARS: Final[int] = 64

#: The ``ESCAPE`` character, stated explicitly so both dialects use the same one. Postgres
#: defaults to backslash and SQLite defaults to *no* escape character at all, so a pattern
#: containing a literal ``%`` would match everything on SQLite and only itself on Postgres —
#: the class of "works in tests, wrong in production" bug this constant exists to close.
LIKE_ESCAPE_CHAR: Final[str] = "\\"

#: Escaped in this order. The backslash **must** come first: escaping ``%`` before ``\`` would
#: then re-escape the backslash the first pass just wrote and turn ``50%`` into ``50\\%``,
#: which matches a literal backslash followed by anything.
_LIKE_METACHARACTERS: Final[str] = "\\%_"


def escape_like(text: str) -> str:
    """Neutralise ``LIKE`` metacharacters so ``text`` matches only itself.

    This is not an injection defence — the pattern is always a bound parameter and never
    interpolated — it is a *correctness* one. Without it ``q=100%`` silently means "starts
    with 100" and ``q=a_b`` matches ``axb``, so an operator searching for a note that really
    contains a percent sign is shown rows that do not, with nothing on the page to explain it.
    """
    escaped = text
    for character in _LIKE_METACHARACTERS:
        escaped = escaped.replace(character, LIKE_ESCAPE_CHAR + character)
    return escaped


def search_clause(
    text: str | None, columns: Sequence[sa.SQLColumnExpression[Any]]
) -> ColumnElement[bool] | None:
    """``q`` as a case-insensitive substring match over ``columns``, OR-ed together.

    ``None`` for a blank or absent query, and ``None`` for an empty column list — "no filter",
    never "match none", the same asymmetry :func:`apply_in` documents and for the same reason:
    a search box that has not been typed into must not empty the table.

    **Over-length input is truncated rather than refused**, because this is the backstop and
    not the gate. Routers declare ``Query(alias="q", max_length=MAX_SEARCH_CHARS)`` so an
    operator who pastes a wall of text gets a 422 naming the parameter — the same shape as
    ``provider`` and ``errorCode`` on ``/generations`` — and this truncation only ever fires
    for a caller that reached the query layer without going through HTTP. Truncating a
    substring pattern *widens* it, so the failure mode is extra rows an operator can see and
    dismiss, never rows silently missing from an answer they are about to act on.

    **Case folding is the one thing that is not identical across dialects.** Postgres ``ILIKE``
    folds by locale; SQLAlchemy renders ``ilike`` on SQLite as ``lower(a) LIKE lower(b)`` and
    SQLite's ``lower`` is ASCII-only, so ``q=Ā`` matches ``ā`` in production and not in a unit
    test. Stated rather than worked around: the alternatives are shipping an ICU build with
    the test suite or folding in Python, and folding in Python means fetching every row. The
    *escaping* — the half that decides whether the query means what it says — is done here in
    Python before the value is bound, so it is byte-identical on both.
    """
    if text is None or not columns:
        return None
    needle = text.strip()[:MAX_SEARCH_CHARS]
    if not needle:
        return None
    pattern = f"%{escape_like(needle)}%"
    matches = [column.ilike(pattern, escape=LIKE_ESCAPE_CHAR) for column in columns]
    if len(matches) == 1:
        return matches[0]
    return or_(*matches)


def apply_search[R: tuple[Any, ...]](
    statement: Select[R], text: str | None, columns: Sequence[sa.SQLColumnExpression[Any]]
) -> Select[R]:
    """Narrow ``statement`` to rows matching ``text``, or return it untouched.

    The counterpart to :func:`apply_window` and :func:`apply_in`, so a list query reads as one
    chain of narrowings and the "no filter given" branch lives in exactly one place per filter
    rather than in every caller's ``if``.
    """
    clause = search_clause(text, columns)
    if clause is None:
        return statement
    return statement.where(clause)


def count_where(condition: ColumnElement[bool]) -> ColumnElement[int]:
    """``count(CASE WHEN condition THEN 1 END)`` — a conditional count that is never NULL."""
    return sa.func.count(sa.case((condition, 1), else_=None))


class UtcDay(FunctionElement[str]):
    """The UTC calendar day of an instant, as the ten characters ``YYYY-MM-DD``.

    Not ``sa.func.date(column)``, which is the trap this class exists to avoid. Postgres
    resolves ``date(timestamptz)`` through a cast that uses the **session** ``TimeZone``, so
    a server set to ``Asia/Tashkent`` would file every order made after 19:00 UTC under the
    next day and the daily chart would silently disagree with every other number on the
    page. The UTC conversion is therefore explicit here and the result is text on both
    dialects, so the Python type coming back does not depend on which database answered.
    """

    inherit_cache = True
    name = "utc_day"
    type = sa.String()


@compiles(UtcDay)
def _compile_utc_day(element: UtcDay, compiler: SQLCompiler, **kw: Any) -> str:
    """Postgres: convert out of the session zone first, then format."""
    (column,) = tuple(element.clauses)
    return f"to_char({compiler.process(column, **kw)} AT TIME ZONE 'UTC', 'YYYY-MM-DD')"


@compiles(UtcDay, "sqlite")
def _compile_utc_day_sqlite(element: UtcDay, compiler: SQLCompiler, **kw: Any) -> str:
    """SQLite stores what ``UtcDateTime`` bound: UTC wall time, no offset. Slice it."""
    (column,) = tuple(element.clauses)
    return f"strftime('%Y-%m-%d', {compiler.process(column, **kw)})"


class UtcHour(FunctionElement[str]):
    """The UTC hour of an instant, as the thirteen characters ``YYYY-MM-DDTHH``.

    :class:`UtcDay`'s sibling and it exists for the identical reason: ``date_trunc`` and
    ``sa.func.date`` both resolve a ``timestamptz`` through the **session** ``TimeZone`` on
    Postgres, so a server set to ``Asia/Tashkent`` would file every call made after 19:00
    UTC under the wrong bucket and the hourly chart would silently disagree with the daily
    one drawn beside it from the same rows. The conversion is explicit and the result is
    text on both dialects, so the Python type coming back does not depend on which database
    answered.

    The separator is ``T`` rather than a space so the bucket key sorts lexicographically in
    the same order it sorts chronologically on both dialects, and so a caller parsing it
    back reaches ``datetime.fromisoformat`` without a substitution.
    """

    inherit_cache = True
    name = "utc_hour"
    type = sa.String()


@compiles(UtcHour)
def _compile_utc_hour(element: UtcHour, compiler: SQLCompiler, **kw: Any) -> str:
    """Postgres: convert out of the session zone first, then format."""
    (column,) = tuple(element.clauses)
    return f"to_char({compiler.process(column, **kw)} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24')"


@compiles(UtcHour, "sqlite")
def _compile_utc_hour_sqlite(element: UtcHour, compiler: SQLCompiler, **kw: Any) -> str:
    """SQLite stores what ``UtcDateTime`` bound: UTC wall time, no offset. Slice it."""
    (column,) = tuple(element.clauses)
    return f"strftime('%Y-%m-%dT%H', {compiler.process(column, **kw)})"


class SeriesGrain(StrEnum):
    """The two bucket widths the DATABASE groups at. Not the two the wire offers.

    **There is deliberately no ``WEEK`` or ``MONTH`` member**, and the omission is the whole
    point of naming the type. Postgres spells an ISO week ``to_char(…, 'IYYY-IW')`` and
    SQLite spells ``strftime('%Y-%W', …)``, which is a *different* numbering — Monday-start
    ``00``–``53`` against ISO's ``01``–``53``, disagreeing about the first and last week of
    most years. A query only production can execute is a query nobody tests; a query both
    dialects execute *differently* is worse, because it passes the suite and is wrong in
    production. So the coarser grains are folded from the daily series one layer up, in
    Python, over rows the database has already grouped — bounded by the bucket count and
    never by rows, which is the same licence :func:`~bayram.db.admin.metrics.failure_breakdown`
    takes to turn counts into shares. The fold also guarantees a monthly series sums exactly
    to the daily one it came from, which two independent SQL expressions could not.
    """

    HOUR = "hour"
    DAY = "day"


def bucket_expression(grain: SeriesGrain, column: InstantColumn) -> ColumnElement[str]:
    """The grouping key for ``grain`` over ``column``. Text on both dialects, always UTC."""
    return UtcHour(column) if grain is SeriesGrain.HOUR else UtcDay(column)


def bucket_started_at(grain: SeriesGrain, key: str) -> datetime:
    """The instant a bucket key names, as an aware UTC instant. The inverse of the grouping.

    Beside :func:`bucket_expression` rather than in a caller because the two spellings are
    one contract: the day compiler emits ``YYYY-MM-DD`` and the hour compiler emits
    ``YYYY-MM-DDTHH``, and a parser written anywhere else is one that keeps working after
    somebody changes a format string here.

    The tzinfo is attached rather than parsed. Both compilers convert to UTC explicitly and
    emit no offset, so the text is a UTC wall clock with the zone left implicit; reading it
    back as naive and then treating it as local is the exact defect the two ``AT TIME ZONE``
    clauses exist to prevent.
    """
    stamp = f"{key}:00:00" if grain is SeriesGrain.HOUR else f"{key}T00:00:00"
    return datetime.fromisoformat(stamp).replace(tzinfo=UTC)


def previous_window(window: TimeWindow | None) -> TimeWindow | None:
    """The equal-length window immediately preceding ``window``, or ``None``.

    ``None`` when there is no window at all and — the case that matters — ``None`` when
    ``window.start`` is ``None``. An open-below range has no length, so it has no
    predecessor, and every alternative invents one: an epoch lower bound would make the
    "previous period" the whole of recorded history, and a fabricated span would make it a
    number the operator never chose. The caller reports ``previous`` as ``null`` and the
    delta as absent, which is the honest rendering of "you did not say since when".

    The boundary is shared rather than adjacent — ``previous.end == window.start`` — so the
    two half-open ranges tile exactly and the instant on the boundary is counted once, in
    the current window. That is :class:`TimeWindow`'s own rule applied to a pair of them.
    """
    if window is None or window.start is None:
        return None
    return TimeWindow(start=window.start - (window.end - window.start), end=window.start)


def spanning_window(current: TimeWindow, previous: TimeWindow) -> TimeWindow:
    """``[previous.start, current.end)`` — the one predicate both halves of a delta scan.

    The delta arm's whole economy. Every card on the dashboard carries a change against the
    preceding period, and the obvious implementation is a second query per card; at eighteen
    cards that is eighteen extra round trips on a page that refreshes on a timer. Instead the
    two counts are taken as :func:`count_pair` conditionals under this single range, so the
    database makes ONE index range scan that happens to be twice as wide and returns both
    numbers from it.
    """
    return TimeWindow(start=previous.start, end=current.end)


def count_pair(
    column: InstantColumn, *, current: TimeWindow
) -> tuple[ColumnElement[int], ColumnElement[int]]:
    """``(rows in the current window, rows before it)`` as two conditional counts.

    Select both under one :func:`apply_window` over :func:`spanning_window`. The split is a
    single comparison against ``current.start`` because the spanning predicate has already
    excluded everything outside the two windows, so ``< current.start`` means "in the
    previous one" and nothing else — no second bound to keep in step, and no row counted
    twice at the seam.

    ``current.start`` must not be ``None``; :func:`previous_window` is what tells a caller
    whether the pair is available at all, and a caller that skipped it would be asking for a
    delta against a range with no beginning.
    """
    if current.start is None:
        raise ValueError("a delta needs a lower bound to split on")
    return (
        count_where(column >= current.start),
        count_where(column < current.start),
    )


def nearest_rank_offset(sample_count: int, fraction: float) -> int:
    """Zero-based ``OFFSET`` of the nearest-rank percentile of ``sample_count`` samples.

    Nearest-rank (``ceil(p × n)``, one-based) rather than linear interpolation: it always
    returns a value that was actually observed, which is what an operator asking "how slow
    is a slow order" wants, and it needs no arithmetic the database cannot do with
    ``ORDER BY … LIMIT 1 OFFSET k``.
    """
    if sample_count <= 0:
        raise ValueError("percentile of an empty sample is undefined")
    rank = max(1, math.ceil(fraction * sample_count))
    return min(rank, sample_count) - 1
