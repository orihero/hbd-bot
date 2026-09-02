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

Nothing here fetches rows into Python to work on them. That is the standing rule for the
metrics module and this is the toolkit that makes it keepable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import ColumnElement, Select
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.functions import FunctionElement

from hbd.contracts import Result, err, ok
from hbd.db.models import Base
from hbd.errors import ValidationError

__all__ = [
    "DurationSeconds",
    "TimeWindow",
    "time_window",
    "apply_window",
    "apply_in",
    "count_where",
    "UtcDay",
    "nearest_rank_offset",
    "has_table",
    "CHAT_MESSAGES_TABLE",
    "PAYMENTS_TABLE",
]

_SECONDS_PER_DAY = 86_400.0

#: Tables later phases add. Named rather than spelled inline so the capability probe and
#: the timeline's "not enabled here" list cannot drift apart on a typo.
CHAT_MESSAGES_TABLE: Final[str] = "chat_messages"
PAYMENTS_TABLE: Final[str] = "payments"


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
    """A half-open ``[start, end)`` interval of aware instants.

    Half-open rather than closed so consecutive windows tile without double-counting the
    row that lands exactly on a boundary — the bug that makes two adjacent daily buckets
    both claim the same midnight order.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("time window bounds must be timezone-aware")
        if self.end < self.start:
            raise ValueError("time window ends before it starts")


def time_window(start: datetime, end: datetime) -> Result[TimeWindow]:
    """Validate a caller-supplied window. Never raises; a bad window is a typed ``Err``."""
    try:
        return ok(TimeWindow(start=start, end=end))
    except ValueError as exc:
        return err(ValidationError(str(exc), context={"parameter": "window"}, cause=exc))


def apply_window[R: tuple[Any, ...]](
    statement: Select[R], column: sa.SQLColumnExpression[datetime], window: TimeWindow | None
) -> Select[R]:
    """Restrict ``statement`` to ``window``, or return it untouched when there is none."""
    if window is None:
        return statement
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
