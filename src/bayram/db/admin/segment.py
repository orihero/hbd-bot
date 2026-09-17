"""The segment DSL — an ALLOWLIST of predicates an operator may point an audience at.

**This module is a registry, not a query builder.** The document a caller sends names a
*key*; :data:`FIELDS` turns that key into an expression this file wrote. Nothing a caller
types ever becomes an identifier, a column name, an operator or a fragment of SQL — values
travel as bound parameters through ordinary SQLAlchemy construction and nothing else. There
is no raw-text construct and no dynamic column reference anywhere below, and
``tests/test_db/test_admin_segment.py`` walks this file's syntax tree to keep it that way, because
"we do not interpolate" is a claim that has to survive the next contributor rather than only
the review that first made it.

**Why an allowlist and not a schema walk.** The obvious implementation derives the filterable
set from the ORM metadata, and it is the one refusal this module exists to make impossible to
regress. ``UserFilters`` already argues at length why there is no name filter and no phone
filter (``db/admin/users.py``): a value predicate on a column that is masked at every role is
an unaudited unmask oracle, and a substring predicate is that oracle three characters at a
time. A registry derived from a row schema would hand every one of those columns back the
moment somebody added one, silently, in a migration. So the four identity columns are named
in :data:`SEGMENT_REFUSALS`, adding a field is a diff a reviewer sees, and the presence
fields below (:func:`has_phone`, ``has_username``) are deliberately the *only* thing the
segment engine can say about them — "we hold one" is a fact about our records, "it starts
with +99890" is a fact about the customer.

**One compiler, two consumers.** ``GET /api/users?segment=`` and the broadcast wizard hand
the identical document to :func:`compile_segment`. A field the records screen cannot filter
on is therefore a field a campaign cannot target — structurally, not by convention.

**The NULL rule, stated once here and never decided at a call site.** On a nullable instant,
"has not done this in 90 days" must contain "has never done this", so
:data:`SegmentOp.NOT_WITHIN_LAST_DAYS`, :data:`SegmentOp.LT` and :data:`SegmentOp.LTE`
include NULL rows when the field says :attr:`FieldSpec.null_is_stale`; ``within_last_days``,
``gt`` and ``gte`` exclude them. Anything else ships a re-engagement campaign that reaches
everybody except the people who never engaged.

**``now`` is a parameter.** ``utc_now()`` is not called in this module and must not be: every
relative operator is a function of one instant, and a compiler that read the wall clock could
not be tested across a boundary at all. The caller reads its clock once and threads it in —
the same discipline ``db/admin/users.get_user_detail`` keeps.

**Nothing here is async and nothing here touches a session.** :func:`compile_segment` returns
an expression; who executes it, with which filters ANDed beside it, is the caller's business.
It imports no FastAPI, no pydantic wire model and nothing from ``bayram.admin`` — the dependency
runs the other way, and the wire models in ``bayram.admin.schemas.segment`` lower onto the plain
dataclasses declared below.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Literal, Protocol

import sqlalchemy as sa
from sqlalchemy.sql import ColumnElement

from bayram.checkout import PaymentIntentState, PlanStatus
from bayram.contracts import BotMembershipEvent, Err, Language, OrderState, Result, err, is_err, ok
from bayram.db.admin.sql import CHAT_MESSAGES_TABLE, has_table
from bayram.db.base import UtcDateTime
from bayram.db.enums import ChatDirection
from bayram.db.models.bot_membership_event import BotMembershipEventRow
from bayram.db.models.chat_message import WIZARD_STEP_LENGTH, ChatMessageRow
from bayram.db.models.credit_account import CreditAccountRow
from bayram.db.models.order import OrderRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.db.models.user import UserRow
from bayram.db.models.user_profile import UserProfileRow
from bayram.errors import ValidationError

__all__ = [
    "SegmentError",
    "SEGMENT_REFUSALS",
    "SEGMENT_LIMITS",
    "SegmentLimits",
    "MIN_RELATIVE_DAYS",
    "MAX_RELATIVE_DAYS",
    "MatchMode",
    "SegmentOp",
    "FieldKind",
    "SortDirection",
    "SortSpec",
    "DEFAULT_SORT",
    "SegmentRule",
    "SegmentGroup",
    "SegmentNode",
    "Segment",
    "FieldSpec",
    "FIELDS",
    "SORT_KEYS",
    "CompiledSegment",
    "compile_segment",
    "sort_expression",
    "segment_capabilities",
]


class SegmentError(ValidationError):
    """A segment document this compiler refuses, carried inside an ``Err``.

    Its own class rather than a bare :class:`~bayram.errors.ValidationError` so the boundary can
    render every refusal as one 422 shape without string-matching a message, and so a reader
    grepping for "what can a segment be rejected for" finds one type. ``context`` names the
    offending **parameter** and, where there is one, the **field key** — which is a schema
    name this API already publishes. The caller's *value* is never in the context: it is
    attacker-supplied text that would otherwise be interpolated into a log line and an error
    body, the refusal ``page._bad_cursor`` makes for the same reason.
    """


#: Columns no field may ever compare a caller-supplied value against, at any role, ever.
#:
#: Four identity columns and one message body. They are listed by bare column name because
#: that is what a reviewer greps for, and the list is module-level — rather than an argument
#: inside a function — for the same reason ``users._SEARCHABLE_COLUMNS`` is: the answer to
#: "what can an operator ask about a customer's identity here?" must be one greppable line
#: that a diff changes visibly.
#:
#: The presence fields (``has_phone``, ``has_username``, ``has_avatar``) do read two of these
#: columns, and that is the exact boundary this constant draws: ``IS NOT NULL`` is a fact
#: about our records, ``= '+998901234542'`` is a fact about the customer. No ``eq``, no
#: ``contains``, no ``startswith``, no ``in`` — and no ``FieldSpec`` of a string kind over any
#: of them, which is what stops the distinction being re-argued one operator at a time.
SEGMENT_REFUSALS: Final[frozenset[str]] = frozenset(
    {"phone_e164", "first_name", "last_name", "telegram_username", "body"}
)


@dataclass(frozen=True, slots=True)
class SegmentLimits:
    """The bounds a document must fit inside, all of them refusals rather than truncations.

    Truncating a segment would narrow or widen an audience without saying so, and the caller
    would ship the result believing it was what they wrote. Every breach is a refusal naming
    the limit it broke.
    """

    #: Total LEAF rules across every group. Twenty-five is far past any audience anybody has
    #: described and far short of a document that costs the planner real money.
    max_rules: int
    #: Root plus two nested levels. Depth is where a reader stops being able to hold the
    #: boolean in their head, and an audience nobody can read is an audience nobody can check.
    max_depth: int
    #: ``in``/``not_in`` list length. Also the cap on how many probes one request may carry.
    max_value_members: int
    #: Rules whose field compiles to a correlated subquery. Each one is a scan the planner
    #: pays for on the whole filtered set, so this is the only limit here that is about cost.
    max_aggregate_rules: int


SEGMENT_LIMITS: Final[SegmentLimits] = SegmentLimits(
    max_rules=25, max_depth=3, max_value_members=50, max_aggregate_rules=6
)

#: Bounds on ``n`` for the three relative-day operators. One day is the shortest window that
#: means anything; ten years is longer than this product has existed, so a larger number is a
#: typo rather than an intention — and an unbounded ``n`` is an ``INTERVAL`` computed from a
#: value a caller chose.
MIN_RELATIVE_DAYS: Final[int] = 1
MAX_RELATIVE_DAYS: Final[int] = 3650

#: What a sortable expression yields for an account the aggregate found nothing for. Sorting
#: must be total and non-null — see :func:`sort_expression` — and the UI states the
#: consequence in the rule row: "never ordered" sorts as the epoch, "never metered" as zero.
_EPOCH: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)

#: Mirrors ``users._PAID_STATES`` and ``repository._PAID_STATES``. Restated rather than
#: imported for the reason the read layer already gives: both spellings it could import from
#: are private to their module, and a read model must not make a private constant public by
#: reaching for it.
_PAID_STATES: Final[tuple[OrderState, ...]] = (
    OrderState.AUTHORIZED,
    OrderState.GENERATING,
    OrderState.DELIVERED,
)

#: An intent that was started and never paid. ``AWAITING`` is in the set because the customer
#: did reach a rail and did not come back with money; ``PAID`` is the state the second half of
#: the predicate subtracts, so somebody who abandoned one checkout and completed another is
#: not in this audience.
_ABANDONED_INTENT_STATES: Final[tuple[PaymentIntentState, ...]] = (
    PaymentIntentState.PENDING,
    PaymentIntentState.AWAITING,
    PaymentIntentState.EXPIRED,
    PaymentIntentState.CANCELLED,
)


class MatchMode(StrEnum):
    """How a group combines its children. ``NONE`` is the ONE negation this DSL has.

    There is deliberately no per-rule ``negate`` flag. One negation mechanism means one place
    to reason about the NULL semantics the module docstring states, instead of a truth table
    that has to be re-derived at every rule row.
    """

    ALL = "all"
    ANY = "any"
    NONE = "none"


class SegmentOp(StrEnum):
    """Every comparison a rule may make. A closed set, matched against each field's own set."""

    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    NOT_IN = "not_in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    BETWEEN = "between"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    WITHIN_LAST_DAYS = "within_last_days"
    NOT_WITHIN_LAST_DAYS = "not_within_last_days"
    WITHIN_NEXT_DAYS = "within_next_days"


class FieldKind(StrEnum):
    """What a field's values ARE, so a builder can render the right control.

    Published on ``GET /api/segments/fields`` and therefore part of the contract: the panel
    draws a date picker for :attr:`INSTANT` and a multi-select for :attr:`ENUM` from this
    alone, which is what keeps a field from appearing in the UI that the compiler refuses.
    """

    INT = "int"
    BOOL = "bool"
    ENUM = "enum"
    INSTANT = "instant"
    #: A short token written by the bot from its own closed vocabulary — never free text a
    #: customer typed, and never a column in :data:`SEGMENT_REFUSALS`. ``wizard_step`` is the
    #: only one, and it takes ``in`` alone, with each member length-capped at the column's own
    #: width so the operator cannot smuggle a ``LIKE``-shaped probe through a bound parameter.
    TOKEN = "token"


type SortDirection = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class SortSpec:
    """A sort key from :data:`SORT_KEYS` and the direction to read it in.

    Declared here rather than in ``page.py`` because the *vocabulary* of sorts is the field
    registry: a key is sortable because a ``FieldSpec`` says so, and a second declaration
    elsewhere would let the keyset helpers and the registry disagree about which keys exist.
    ``page.py``'s cursor helpers take the expression this module hands them.
    """

    key: str
    direction: SortDirection


#: What a page is ordered by when nobody said. ``joined_at`` is ``users.created_at`` — the
#: same column and the same direction the keyset has always used — under the registry's own
#: name for it. There is exactly one name per column on purpose: two spellings of one order
#: is two cursors that believe they are the same, which is how a page repeats or skips rows.
DEFAULT_SORT: Final[SortSpec] = SortSpec(key="joined_at", direction="desc")


@dataclass(frozen=True, slots=True)
class SegmentRule:
    """One leaf predicate: a registry key, an operator, and the operator's value.

    ``value`` is whatever the document carried — an ``int``, a ``str``, a ``bool``, an aware
    :class:`~datetime.datetime`, or a list of those. It is validated against the field's kind
    by the compiler and never trusted before that.
    """

    field: str
    op: SegmentOp
    value: object = None


@dataclass(frozen=True, slots=True)
class SegmentGroup:
    """A boolean node. Empty ``rules`` is legal only at the root — see :func:`compile_segment`."""

    match: MatchMode
    rules: tuple[SegmentNode, ...] = ()


type SegmentNode = SegmentRule | SegmentGroup


@dataclass(frozen=True, slots=True)
class Segment:
    """A whole document: one root group and the order its results are read in."""

    root: SegmentGroup
    sort: SortSpec = DEFAULT_SORT


class _Build(Protocol):
    """How a field turns one operator and one value into a predicate.

    A protocol rather than a ``Callable`` alias so ``now`` stays keyword-only in the
    signature: it is threaded in, never read inside, and a positional clock is one refactor
    away from being confused with a value.
    """

    def __call__(
        self, op: SegmentOp, value: object, *, now: datetime
    ) -> Result[ColumnElement[bool]]: ...


class _SortBuild(Protocol):
    """The total, non-null expression a sortable field is ordered by.

    See :func:`sort_expression` for why it may never be NULL.
    """

    def __call__(self) -> sa.SQLColumnExpression[Any]: ...


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One filterable field, and the argument for why exposing it is safe.

    :attr:`doc` is not decoration. Every entry in :data:`FIELDS` widens what admin code can
    ask about a customer, and the place to make that case is beside the field rather than in
    a review comment nobody can find later — so a field with no argument for itself is a
    field that does not get added.
    """

    key: str
    kind: FieldKind
    ops: frozenset[SegmentOp]
    build: _Build
    #: Why exposing this field is safe, in the voice the rest of this package argues in.
    doc: str
    sortable: bool = False
    #: Whether ``lt``/``lte``/``not_within_last_days`` include rows where the underlying
    #: expression is NULL. True exactly when NULL means "never happened" — see the module
    #: docstring's NULL rule, which is decided here and nowhere else.
    null_is_stale: bool = False
    #: True when the predicate is a correlated subquery, which is what
    #: :attr:`SegmentLimits.max_aggregate_rules` counts and what makes a sort expensive.
    is_aggregate: bool = False
    #: The table this field needs, or ``None`` when it is always available. A rule on an
    #: absent capability is a refusal naming the field, never a dropped clause: "the table is
    #: not installed here" and "nobody matched" must not look the same on a screen an
    #: operator is about to send forty thousand messages from.
    capability: str | None = None
    sort_build: _SortBuild | None = None


# ---------------------------------------------------------------------------
# Refusals and coercions — every caller value is validated before it is bound
# ---------------------------------------------------------------------------
def _refuse(message: str, **context: object) -> Err:
    """A typed refusal. The value that caused it is never in the context."""
    return err(SegmentError(message, context={"parameter": "segment", **context}))


def _as_int(value: object) -> Result[int]:
    """An ``int`` and not a ``bool``.

    ``bool`` is an ``int`` subclass in Python and JSON's ``true`` decodes to one, so without
    this branch ``{"field": "order_count", "op": "gte", "value": true}`` would compile to
    ``order_count >= 1`` — a predicate nobody wrote, matching an audience nobody chose.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return _refuse("this operator needs a whole number")
    return ok(value)


def _as_days(value: object) -> Result[int]:
    """``n`` for a relative-day operator, bounded at both ends."""
    parsed = _as_int(value)
    if is_err(parsed):
        return parsed
    if not MIN_RELATIVE_DAYS <= parsed.value <= MAX_RELATIVE_DAYS:
        return _refuse(f"a day count must be between {MIN_RELATIVE_DAYS} and {MAX_RELATIVE_DAYS}")
    return parsed


def _as_instant(value: object) -> Result[datetime]:
    """An aware instant. A naive one is a refusal, never a guess about which zone it meant.

    The same rule ``?from=`` follows (``admin.window.require_aware``), enforced here as well
    rather than only there because this module is also reachable from the worker, where there
    is no request boundary to have caught it.
    """
    if not isinstance(value, datetime):
        return _refuse("this operator needs an instant")
    if value.tzinfo is None:
        return _refuse("an instant must carry a UTC offset")
    return ok(value)


def _as_members[T](value: object, coerce: Callable[[object], Result[T]]) -> Result[tuple[T, ...]]:
    """A non-empty, bounded list of members, each coerced by ``coerce``.

    An empty list is a refusal rather than ``IN ()``: the SQL is a syntax error on one dialect
    and "matches nothing" on the other, and neither is what an operator who cleared a
    multi-select meant.
    """
    if not isinstance(value, list | tuple):
        return _refuse("this operator needs a list of values")
    members: Sequence[object] = value
    if not members:
        return _refuse("this operator needs at least one value")
    if len(members) > SEGMENT_LIMITS.max_value_members:
        return _refuse(f"a value list may name at most {SEGMENT_LIMITS.max_value_members} members")
    coerced: list[T] = []
    for member in members:
        parsed = coerce(member)
        if is_err(parsed):
            return parsed
        coerced.append(parsed.value)
    return ok(tuple(coerced))


def _as_enum[E: StrEnum](value: object, enum_cls: type[E]) -> Result[E]:
    """One member of a closed enum, resolved through the enum itself.

    ``enum_cls(value)`` and not a string comparison: an unknown member raises ``ValueError``
    here, before any SQL exists, so a typo is a 422 rather than a page that silently matches
    nobody. The member — not the caller's string — is what gets bound.
    """
    if not isinstance(value, str):
        return _refuse("this operator needs a named value")
    try:
        return ok(enum_cls(value))
    except ValueError as exc:
        return err(
            SegmentError(
                "unknown value for this field", context={"parameter": "segment"}, cause=exc
            )
        )


def _as_token(value: object) -> Result[str]:
    """A short token from the bot's own vocabulary, length-capped at the column's own width."""
    if not isinstance(value, str) or not value:
        return _refuse("this operator needs a token")
    if len(value) > WIZARD_STEP_LENGTH:
        return _refuse(f"a token may be at most {WIZARD_STEP_LENGTH} characters")
    return ok(value)


def _as_pair[T: (int, datetime)](
    value: object, coerce: Callable[[object], Result[T]]
) -> Result[tuple[T, T]]:
    """The two bounds of a ``between``, in order."""
    if not isinstance(value, list | tuple) or len(value) != 2:
        return _refuse("between needs exactly two bounds")
    low = coerce(value[0])
    if is_err(low):
        return low
    high = coerce(value[1])
    if is_err(high):
        return high
    if high.value < low.value:
        return _refuse("between ends before it starts")
    return ok((low.value, high.value))


# ---------------------------------------------------------------------------
# Expression fragments — the only place a column is ever named
# ---------------------------------------------------------------------------
def _exists(*predicates: ColumnElement[bool]) -> ColumnElement[bool]:
    """``EXISTS (SELECT 1 FROM … WHERE …)``, correlated to ``users``.

    Correlated rather than joined for the reason ``users._has_positive_balance`` gives: a
    ``WHERE`` clause is where a filter has to live if ``count_users`` and ``list_users`` are
    to narrow identically, and ``_filtered`` is the statement that must not grow joins the
    count would then pay for on every matching row. An ``EXISTS`` is a boolean regardless of
    how many child rows there are, so it cannot multiply the page either.
    """
    return sa.exists(sa.select(sa.literal(1)).where(*predicates)).correlate(UserRow)


def _scalar(
    expression: sa.SQLColumnExpression[Any], *predicates: ColumnElement[bool]
) -> ColumnElement[Any]:
    """A correlated scalar subquery over one aggregate of one account's child rows."""
    return sa.select(expression).where(*predicates).correlate(UserRow).scalar_subquery()


def _counted(entity: Any, *predicates: ColumnElement[bool]) -> ColumnElement[Any]:
    """``(SELECT count(*) FROM entity WHERE …)`` — never NULL, so it needs no COALESCE.

    ``count`` over an empty set is ``0`` on both dialects with no ``GROUP BY``, which is why
    only the ``SUM`` and the bare-column reads below are wrapped.
    """
    return (
        sa.select(sa.func.count())
        .select_from(entity)
        .where(*predicates)
        .correlate(UserRow)
        .scalar_subquery()
    )


def _by_telegram_id(entity: Any) -> ColumnElement[bool]:
    """``child.telegram_user_id = users.telegram_user_id``.

    Every table this joins to has a NULLABLE ``telegram_user_id`` that ``/forget`` sets to
    ``NULL``, and this equality already excludes those rows — ``NULL = anything`` is unknown.
    Said here once so nobody adds a redundant ``IS NOT NULL`` beside it and leaves a reader
    wondering which of the two is load-bearing.
    """
    matched: ColumnElement[bool] = entity.telegram_user_id == UserRow.telegram_user_id
    return matched


def _profile_column(column: sa.SQLColumnExpression[Any]) -> ColumnElement[Any]:
    """One ``user_profiles`` column for this user, or NULL when they have no profile row.

    Keyed on ``user_profiles.user_id``, that table's PRIMARY KEY, so the subquery is scalar by
    construction rather than by a ``LIMIT`` somebody has to remember.
    """
    return _scalar(column, UserProfileRow.user_id == UserRow.id)


def _epoch_floor(expression: sa.SQLColumnExpression[Any]) -> ColumnElement[Any]:
    """``COALESCE(expr, epoch)`` — see :func:`sort_expression` for why a sort may not be NULL."""
    return sa.func.coalesce(expression, sa.literal(_EPOCH, UtcDateTime))


# ---------------------------------------------------------------------------
# Operator application — one implementation per kind, shared by every field
# ---------------------------------------------------------------------------
def _bool_predicate(expression: ColumnElement[bool], op: SegmentOp) -> Result[ColumnElement[bool]]:
    """``is_true`` / ``is_false``, as the expression and its exact complement.

    ``sa.not_(expr)`` rather than ``expr.is_(False)``: every boolean field in this registry is
    either a ``NOT NULL`` column, an ``EXISTS`` or an ``IS NOT NULL`` test, none of which can
    be NULL, so the complement is exact — and ``NOT`` renders identically on both dialects
    while ``IS false`` does not. The exactness is the point, and it is the same one
    ``UserFilters.has_balance`` makes: an operator must be able to flip the chip and see
    every row the other value did not.
    """
    if op is SegmentOp.IS_TRUE:
        return ok(expression)
    if op is SegmentOp.IS_FALSE:
        return ok(sa.not_(expression))
    return _refuse("this operator does not apply to a yes/no field")


def _int_predicate(
    expression: sa.SQLColumnExpression[Any], op: SegmentOp, value: object
) -> Result[ColumnElement[bool]]:
    """The numeric comparisons, including ``between`` as the half-open ``[a, b)``."""
    if op is SegmentOp.BETWEEN:
        bounds = _as_pair(value, _as_int)
        if is_err(bounds):
            return bounds
        low, high = bounds.value
        return ok(sa.and_(expression >= low, expression < high))
    if op in (SegmentOp.IN, SegmentOp.NOT_IN):
        members = _as_members(value, _as_int)
        if is_err(members):
            return members
        matched = expression.in_(members.value)
        return ok(matched if op is SegmentOp.IN else sa.not_(matched))
    parsed = _as_int(value)
    if is_err(parsed):
        return parsed
    number = parsed.value
    match op:
        case SegmentOp.EQ:
            return ok(expression == number)
        case SegmentOp.NEQ:
            return ok(expression != number)
        case SegmentOp.GT:
            return ok(expression > number)
        case SegmentOp.GTE:
            return ok(expression >= number)
        case SegmentOp.LT:
            return ok(expression < number)
        case SegmentOp.LTE:
            return ok(expression <= number)
        case _:
            return _refuse("this operator does not apply to a numeric field")


def _instant_predicate(
    expression: sa.SQLColumnExpression[Any],
    op: SegmentOp,
    value: object,
    *,
    now: datetime,
    stale: bool,
) -> Result[ColumnElement[bool]]:
    """The instant comparisons and the NULL rule the module docstring states.

    ``between`` is half-open ``[a, b)``, the convention ``apply_window`` uses, so a June
    segment and a June dashboard tile count the same orders and the row that lands exactly on
    1 July belongs to July in both.

    ``stale`` — the field's :attr:`FieldSpec.null_is_stale` — is what turns "has not ordered
    since March" into a predicate that contains "has never ordered". It is applied to the
    three backward-looking operators and to nothing else: ``within_last_days`` and ``gt`` are
    claims that something *did* happen, and a NULL is not evidence of that.
    """
    if op is SegmentOp.IS_NULL:
        return ok(expression.is_(None))
    if op is SegmentOp.IS_NOT_NULL:
        return ok(expression.is_not(None))
    if op is SegmentOp.BETWEEN:
        bounds = _as_pair(value, _as_instant)
        if is_err(bounds):
            return bounds
        low, high = bounds.value
        return ok(sa.and_(expression >= low, expression < high))
    if op in (SegmentOp.WITHIN_LAST_DAYS, SegmentOp.NOT_WITHIN_LAST_DAYS):
        days = _as_days(value)
        if is_err(days):
            return days
        cutoff = now - timedelta(days=days.value)
        if op is SegmentOp.WITHIN_LAST_DAYS:
            return ok(expression >= cutoff)
        return ok(_or_null(expression < cutoff, expression, stale=stale))
    if op is SegmentOp.WITHIN_NEXT_DAYS:
        days = _as_days(value)
        if is_err(days):
            return days
        return ok(sa.and_(expression >= now, expression < now + timedelta(days=days.value)))
    parsed = _as_instant(value)
    if is_err(parsed):
        return parsed
    instant = parsed.value
    match op:
        case SegmentOp.GT:
            return ok(expression > instant)
        case SegmentOp.GTE:
            return ok(expression >= instant)
        case SegmentOp.LT:
            return ok(_or_null(expression < instant, expression, stale=stale))
        case SegmentOp.LTE:
            return ok(_or_null(expression <= instant, expression, stale=stale))
        case _:
            return _refuse("this operator does not apply to a date field")


def _or_null(
    predicate: ColumnElement[bool], expression: sa.SQLColumnExpression[Any], *, stale: bool
) -> ColumnElement[bool]:
    """``predicate OR expr IS NULL`` when the field says a NULL is stale, else ``predicate``."""
    if not stale:
        return predicate
    return sa.or_(predicate, expression.is_(None))


def _membership_predicate[E: StrEnum](
    op: SegmentOp,
    value: object,
    *,
    enum_cls: type[E],
    matches: Callable[[tuple[E, ...]], ColumnElement[bool]],
) -> Result[ColumnElement[bool]]:
    """``eq``/``in``/``not_in`` over a closed enum, via a per-field membership predicate.

    ``matches`` receives the resolved members — never the caller's strings — and returns the
    positive predicate, so a direct column and a correlated ``EXISTS`` share one operator
    implementation and cannot drift on what ``not_in`` means.
    """
    if op in (SegmentOp.EQ, SegmentOp.NEQ):
        parsed = _as_enum(value, enum_cls)
        if is_err(parsed):
            return parsed
        matched: ColumnElement[bool] = matches((parsed.value,))
        return ok(matched if op is SegmentOp.EQ else sa.not_(matched))
    if op in (SegmentOp.IN, SegmentOp.NOT_IN):
        members = _as_members(value, lambda member: _as_enum(member, enum_cls))
        if is_err(members):
            return members
        matched = matches(members.value)
        return ok(matched if op is SegmentOp.IN else sa.not_(matched))
    return _refuse("this operator does not apply to a named-value field")


# ---------------------------------------------------------------------------
# Field factories — a spec is data, so adding one is a row rather than a function
# ---------------------------------------------------------------------------
_BOOL_OPS: Final[frozenset[SegmentOp]] = frozenset({SegmentOp.IS_TRUE, SegmentOp.IS_FALSE})
_INT_OPS: Final[frozenset[SegmentOp]] = frozenset(
    {
        SegmentOp.EQ,
        SegmentOp.NEQ,
        SegmentOp.IN,
        SegmentOp.NOT_IN,
        SegmentOp.GT,
        SegmentOp.GTE,
        SegmentOp.LT,
        SegmentOp.LTE,
        SegmentOp.BETWEEN,
    }
)
_INSTANT_OPS: Final[frozenset[SegmentOp]] = frozenset(
    {
        SegmentOp.GT,
        SegmentOp.GTE,
        SegmentOp.LT,
        SegmentOp.LTE,
        SegmentOp.BETWEEN,
        SegmentOp.IS_NULL,
        SegmentOp.IS_NOT_NULL,
        SegmentOp.WITHIN_LAST_DAYS,
        SegmentOp.NOT_WITHIN_LAST_DAYS,
        SegmentOp.WITHIN_NEXT_DAYS,
    }
)
_MEMBERSHIP_OPS: Final[frozenset[SegmentOp]] = frozenset(
    {SegmentOp.EQ, SegmentOp.NEQ, SegmentOp.IN, SegmentOp.NOT_IN}
)
_SET_OPS: Final[frozenset[SegmentOp]] = frozenset({SegmentOp.IN, SegmentOp.NOT_IN})
_ID_OPS: Final[frozenset[SegmentOp]] = frozenset({SegmentOp.EQ, SegmentOp.IN})


def _bool_field(
    key: str,
    expression: Callable[[], ColumnElement[bool]],
    doc: str,
    *,
    is_aggregate: bool = False,
    capability: str | None = None,
) -> FieldSpec:
    def build(op: SegmentOp, value: object, *, now: datetime) -> Result[ColumnElement[bool]]:
        del value, now  # a yes/no field carries no value and reads no clock
        return _bool_predicate(expression(), op)

    return FieldSpec(
        key=key,
        kind=FieldKind.BOOL,
        ops=_BOOL_OPS,
        build=build,
        doc=doc,
        is_aggregate=is_aggregate,
        capability=capability,
    )


def _int_field(
    key: str,
    expression: Callable[[], sa.SQLColumnExpression[Any]],
    doc: str,
    *,
    ops: frozenset[SegmentOp] = _INT_OPS,
    sortable: bool = False,
    is_aggregate: bool = False,
    capability: str | None = None,
) -> FieldSpec:
    def build(op: SegmentOp, value: object, *, now: datetime) -> Result[ColumnElement[bool]]:
        del now  # a count is not a function of the clock
        return _int_predicate(expression(), op, value)

    return FieldSpec(
        key=key,
        kind=FieldKind.INT,
        ops=ops,
        build=build,
        doc=doc,
        sortable=sortable,
        is_aggregate=is_aggregate,
        capability=capability,
        sort_build=expression if sortable else None,
    )


def _instant_field(
    key: str,
    expression: Callable[[], sa.SQLColumnExpression[Any]],
    doc: str,
    *,
    null_is_stale: bool,
    sortable: bool = False,
    is_aggregate: bool = False,
    capability: str | None = None,
) -> FieldSpec:
    def build(op: SegmentOp, value: object, *, now: datetime) -> Result[ColumnElement[bool]]:
        return _instant_predicate(expression(), op, value, now=now, stale=null_is_stale)

    def sorted_by() -> sa.SQLColumnExpression[Any]:
        return _epoch_floor(expression())

    return FieldSpec(
        key=key,
        kind=FieldKind.INSTANT,
        ops=_INSTANT_OPS,
        build=build,
        doc=doc,
        sortable=sortable,
        null_is_stale=null_is_stale,
        is_aggregate=is_aggregate,
        capability=capability,
        sort_build=sorted_by if sortable else None,
    )


def _enum_field[E: StrEnum](
    key: str,
    enum_cls: type[E],
    matches: Callable[[tuple[E, ...], datetime], ColumnElement[bool]],
    doc: str,
    *,
    ops: frozenset[SegmentOp] = _MEMBERSHIP_OPS,
    is_aggregate: bool = False,
    capability: str | None = None,
) -> FieldSpec:
    def build(op: SegmentOp, value: object, *, now: datetime) -> Result[ColumnElement[bool]]:
        return _membership_predicate(
            op, value, enum_cls=enum_cls, matches=lambda members: matches(members, now)
        )

    return FieldSpec(
        key=key,
        kind=FieldKind.ENUM,
        ops=ops,
        build=build,
        doc=doc,
        is_aggregate=is_aggregate,
        capability=capability,
    )


# ---------------------------------------------------------------------------
# Per-field membership predicates that need more than a column
# ---------------------------------------------------------------------------
def _order_state_matches(members: tuple[OrderState, ...], now: datetime) -> ColumnElement[bool]:
    """ "Has an order in one of these states" — a presence question, not a count."""
    del now
    return _exists(_by_telegram_id(OrderRow), OrderRow.state.in_(members))


def _plan_status_matches(members: tuple[PlanStatus, ...], now: datetime) -> ColumnElement[bool]:
    """One of the four plan cases, each derived from ``PlanState``'s two predicates.

    ``is_current`` is ``plan_ends_at > now`` and ``is_live`` is that plus
    ``songs_used < songs_included`` — the same two comparisons ``plan_sql.current_plan`` and
    ``plan_sql.live_plan`` make, restated as set predicates over an account's whole history
    rather than as a third definition of "live". The day either predicate changes, this must
    change with it, which is why they are spelled from the same columns in the same order.

    The four cases are mutually exclusive and exhaustive, so ``in`` over all four matches
    every account and ``not_in`` over all four matches none — which is what makes the chip
    honest when an operator ticks every box.
    """
    return sa.or_(*(_plan_status_case(status, now) for status in members))


def _plan_status_case(status: PlanStatus, now: datetime) -> ColumnElement[bool]:
    any_plan = _exists(_by_telegram_id(PlanPurchaseRow))
    current = _exists(_by_telegram_id(PlanPurchaseRow), PlanPurchaseRow.plan_ends_at > now)
    live = _exists(
        _by_telegram_id(PlanPurchaseRow),
        PlanPurchaseRow.plan_ends_at > now,
        PlanPurchaseRow.songs_used < PlanPurchaseRow.songs_included,
    )
    match status:
        case PlanStatus.NONE:
            return sa.not_(any_plan)
        case PlanStatus.ACTIVE:
            return live
        case PlanStatus.EXHAUSTED:
            return sa.and_(current, sa.not_(live))
        case PlanStatus.LAPSED:
            return sa.and_(any_plan, sa.not_(current))


def _language_matches(members: tuple[Language, ...], now: datetime) -> ColumnElement[bool]:
    del now
    return UserRow.ui_language.in_(members)


def _wizard_step_build(
    op: SegmentOp, value: object, *, now: datetime
) -> Result[ColumnElement[bool]]:
    """``in`` over the bot's own step names. Tokens, length-capped, never free text."""
    del now
    if op not in _SET_OPS:
        return _refuse("this operator does not apply to a step field")
    members = _as_members(value, _as_token)
    if is_err(members):
        return members
    matched = _exists(
        ChatMessageRow.telegram_user_id == UserRow.telegram_user_id,
        ChatMessageRow.wizard_step.in_(members.value),
    )
    return ok(matched if op is SegmentOp.IN else sa.not_(matched))


def _telegram_user_id_build(
    op: SegmentOp, value: object, *, now: datetime
) -> Result[ColumnElement[bool]]:
    """``eq``/``in`` on the id, and nothing that could turn into a range scan of the table."""
    del now
    if op is SegmentOp.EQ:
        parsed = _as_int(value)
        if is_err(parsed):
            return parsed
        return ok(UserRow.telegram_user_id == parsed.value)
    if op is SegmentOp.IN:
        members = _as_members(value, _as_int)
        if is_err(members):
            return members
        return ok(UserRow.telegram_user_id.in_(members.value))
    return _refuse("this operator does not apply to an account id")


# ---------------------------------------------------------------------------
# THE REGISTRY
# ---------------------------------------------------------------------------
_SPECS: Final[tuple[FieldSpec, ...]] = (
    # -- users, direct columns: the cheapest predicates there are ------------
    FieldSpec(
        key="telegram_user_id",
        kind=FieldKind.INT,
        ops=_ID_OPS,
        build=_telegram_user_id_build,
        doc=(
            "Safe because this screen already returns the value unmasked in every row — "
            "every ``/users/**`` route keys on it, so the panel could not draw a link or a "
            "reveal without it. A predicate over a value the same response prints in full "
            "discloses nothing the caller did not already hold. ``eq`` and ``in`` only: a "
            "range over account ids is not a question anybody asks and is a full scan "
            "wearing a filter's clothes."
        ),
    ),
    _enum_field(
        "ui_language",
        Language,
        _language_matches,
        doc=(
            "The language the bot speaks to this account in — our own setting, chosen by the "
            "customer from four options, and the one field a broadcast genuinely cannot work "
            "without: a campaign body is written per language and sending the Russian one to "
            "an Uzbek speaker is the failure this field exists to prevent."
        ),
    ),
    _bool_field(
        "is_blocked",
        lambda: UserRow.is_blocked.is_(True),
        doc=(
            "**The OPERATOR's bar**, written by the panel itself. It is our own decision "
            "about our own account, so filtering on it discloses nothing about the customer "
            "that the operator did not write. Never OR-ed with ``bot_blocked``: they are "
            "opposite facts with opposite subjects, they get different labels in the "
            "builder, and collapsing them is how 'barred by us' silently becomes 'left us'."
        ),
    ),
    _bool_field(
        "bot_blocked",
        lambda: UserRow.blocked_bot_at.is_not(None),
        doc=(
            "**The CUSTOMER's block** — they blocked the bot. Safe for the same reason as "
            "``is_blocked`` and load-bearing for a different one: it is the cheapest way to "
            "keep a campaign from spending its whole rate budget on accounts Telegram will "
            "refuse. A presence test over a stamp we recorded, never the stamp itself."
        ),
    ),
    _instant_field(
        "bot_blocked_at",
        lambda: UserRow.blocked_bot_at,
        doc=(
            "When they blocked us. An instant we observed about our own delivery, at "
            "day-scale resolution in practice, and the only way to ask 'who left us in the "
            "week after the price change'. NULL means not currently blocked, which is why a "
            "backward-looking operator includes NULLs: 'has not blocked us since March' must "
            "contain everyone who never blocked us at all."
        ),
        null_is_stale=True,
    ),
    _instant_field(
        "joined_at",
        lambda: UserRow.created_at,
        doc=(
            "FIRST CONTACT — the language question, a touch, or an order, whichever came "
            "first (``users`` has three writers; see ``db/admin/users``'s module docstring). "
            "It is already published on every row of the list as ``accountCreatedAt``, and "
            "it is the default sort because it is the column the keyset has always used. "
            "'Joined in June' is this field with a half-open ``between``."
        ),
        null_is_stale=False,
        sortable=True,
    ),
    _instant_field(
        "last_activity_at",
        lambda: UserRow.last_seen_at,
        doc=(
            "``users.last_seen_at``, and it is FILTERABLE BUT NEVER SORTABLE — the one "
            "asymmetry in this registry, and it is deliberate. ``credits.touch`` moves this "
            "column on every inbound update, which is why ``db/admin/users`` and "
            "``db/admin/overview`` withhold it from every per-row projection: a published "
            "column would let an operator watch a customer's activity minute by minute from "
            "a screen whose stated purpose is records. A PREDICATE discloses only the bucket "
            "the operator already chose ('quiet for 90 days'), which is the one question a "
            "re-engagement campaign is made of. A SORT discloses a total order over "
            "identified accounts — the same surveillance the withheld projection exists to "
            "prevent, rebuilt one page at a time. So the predicate is allowed and the sort "
            "is refused, and ``sortable=False`` here is that refusal in code."
        ),
        null_is_stale=False,
    ),
    _bool_field(
        "is_reachable",
        lambda: sa.and_(UserRow.is_blocked.is_(False), UserRow.blocked_bot_at.is_(None)),
        doc=(
            "Derived: neither barred by us nor blocked by them. Two columns the operator "
            "may already filter on, ANDed — so it discloses nothing either one does not, and "
            "it exists because every campaign wants it and a wizard that made each operator "
            "spell it out would eventually meet one who spelled it wrong."
        ),
    ),
    # -- user_profiles: PRESENCE ONLY. See SEGMENT_REFUSALS ------------------
    _bool_field(
        "has_profile",
        lambda: _exists(UserProfileRow.user_id == UserRow.id),
        doc=(
            "Whether we hold a profile row at all. A fact about OUR RECORDS, not about the "
            "customer, and one the list already publishes as ``isProfilePresent``. It is "
            "also the honest way to ask 'who never finished onboarding' without touching a "
            "single identity column."
        ),
        is_aggregate=True,
    ),
    _bool_field(
        "has_phone",
        lambda: _exists(
            UserProfileRow.user_id == UserRow.id, UserProfileRow.phone_e164.is_not(None)
        ),
        doc=(
            "Whether a phone number is on file — and the exact boundary ``SEGMENT_REFUSALS`` "
            "draws. 'We hold one' is a fact about our records that the panel already shows "
            "as a masked cell; 'it starts with +99890' is a fact about the customer and is "
            "refused at every role, because an exact or prefix predicate on a column masked "
            "everywhere is an unmask oracle with no step-up, no budget unit and no audit "
            "row. ``POST /reveal`` stays the only unmask path, which is only true while "
            "nothing else in the API answers questions about the value."
        ),
        is_aggregate=True,
    ),
    _bool_field(
        "has_username",
        lambda: _exists(
            UserProfileRow.user_id == UserRow.id, UserProfileRow.telegram_username.is_not(None)
        ),
        doc=(
            "Whether Telegram gave us a handle. Presence only, on the identical argument as "
            "``has_phone``: a substring predicate over a handle recovers it three characters "
            "at a time, which is the refusal ``UserFilters.search`` already makes in prose."
        ),
        is_aggregate=True,
    ),
    _bool_field(
        "has_avatar",
        lambda: _exists(
            UserProfileRow.user_id == UserRow.id, UserProfileRow.avatar_stored_at.is_not(None)
        ),
        doc=(
            "Whether we have stored an avatar. A presence tick over a stamp WE wrote — never "
            "a claim about bytes, which ``db/admin/assets`` refuses to make without reading "
            "them, and never anything about what the picture shows."
        ),
        is_aggregate=True,
    ),
    _instant_field(
        "onboarded_at",
        lambda: _profile_column(UserProfileRow.onboarded_at),
        doc=(
            "When onboarding completed. An instant in OUR funnel, the thing a 'welcome, one "
            "week in' campaign is keyed on, and it says nothing about the customer beyond "
            "when they finished answering us."
        ),
        null_is_stale=True,
        is_aggregate=True,
    ),
    _instant_field(
        "phone_shared_at",
        lambda: _profile_column(UserProfileRow.phone_shared_at),
        doc=(
            "WHEN a number was shared — deliberately not WHAT was shared. The stamp is a "
            "step in our own funnel; the value behind it stays masked and unfilterable."
        ),
        null_is_stale=True,
        is_aggregate=True,
    ),
    _instant_field(
        "language_chosen_at",
        lambda: _profile_column(UserProfileRow.language_chosen_at),
        doc=(
            "When the first question the bot asks was answered — the earliest signal this "
            "system has that an account is a person, and a cohort boundary for every "
            "campaign that wants 'people who arrived after the redesign'."
        ),
        null_is_stale=True,
        is_aggregate=True,
    ),
    # -- credit_accounts -----------------------------------------------------
    _bool_field(
        "has_credit_account",
        lambda: _exists(_by_telegram_id(CreditAccountRow)),
        doc=(
            "Whether this account has ever been metered. The row is opened by the first "
            "charge or grant, so its absence means never metered — a fact about our ledger, "
            "and the distinction ``UserListItem.credit_balance`` publishes as NULL rather "
            "than 0 for exactly this reason."
        ),
        is_aggregate=True,
    ),
    _int_field(
        "credit_balance",
        lambda: sa.func.coalesce(
            _scalar(CreditAccountRow.balance, _by_telegram_id(CreditAccountRow)), 0
        ),
        doc=(
            "The STORED balance, never ``read_balance``'s projection. Our own ledger number "
            "about our own product, already on every row of the list. It is the stored "
            "column for the reason ``UserFilters.has_balance`` gives: the projection is "
            "three statements per account and a function of ``now``, so a page filtered or "
            "sorted on it would drift under its own cursor mid-pagination. ``COALESCE(…, 0)`` "
            "so the sort is total: 'never metered' orders as zero, and the UI says so."
        ),
        sortable=True,
        is_aggregate=True,
    ),
    _int_field(
        "lifetime_credits_granted",
        lambda: sa.func.coalesce(
            _scalar(CreditAccountRow.lifetime_granted, _by_telegram_id(CreditAccountRow)), 0
        ),
        doc=(
            "Everything we have ever granted this account. A monotonic number from our own "
            "ledger — the closest thing to 'how much has this customer been given', which is "
            "the question behind every thank-you campaign."
        ),
        sortable=True,
        is_aggregate=True,
    ),
    _instant_field(
        "first_metered_at",
        lambda: _scalar(CreditAccountRow.created_at, _by_telegram_id(CreditAccountRow)),
        doc=(
            "When the credit account was opened — the first charge or grant. An instant in "
            "our ledger, not in the customer's life, and the cohort key for 'people whose "
            "first month is about to end'."
        ),
        null_is_stale=True,
        sortable=True,
        is_aggregate=True,
    ),
    # -- orders --------------------------------------------------------------
    _int_field(
        "order_count",
        lambda: _counted(OrderRow, _by_telegram_id(OrderRow)),
        doc=(
            "How many orders this account has placed, in any state. A count of OUR OWN "
            "records that the list already publishes per row, and the coarsest possible "
            "shape of 'how engaged is this customer' — a number, never a title, never a "
            "recipient, never a lyric."
        ),
        sortable=True,
        is_aggregate=True,
    ),
    _int_field(
        "paid_order_count",
        lambda: _counted(OrderRow, _by_telegram_id(OrderRow), OrderRow.state.in_(_PAID_STATES)),
        doc=(
            "Orders that reached a paid state, using the same ``_PAID_STATES`` tuple the list "
            "rollup counts with, so the chip and the column can never disagree about what "
            "'paid' means."
        ),
        sortable=True,
        is_aggregate=True,
    ),
    _int_field(
        "delivered_order_count",
        lambda: _counted(
            OrderRow, _by_telegram_id(OrderRow), OrderRow.state == OrderState.DELIVERED
        ),
        doc=(
            "Songs actually delivered. This is 'generated the most' — as a THRESHOLD, "
            "because a sort alone narrows nothing and a campaign aimed at 'the top of a "
            "list' has no members until somebody says how far down the list goes."
        ),
        sortable=True,
        is_aggregate=True,
    ),
    _int_field(
        "failed_order_count",
        lambda: _counted(OrderRow, _by_telegram_id(OrderRow), OrderRow.state == OrderState.FAILED),
        doc=(
            "Orders that failed on our side. Our own defect record, and the only honest way "
            "to address an apology to the people it is owed to."
        ),
        sortable=True,
        is_aggregate=True,
    ),
    _instant_field(
        "first_order_at",
        lambda: _scalar(sa.func.min(OrderRow.created_at), _by_telegram_id(OrderRow)),
        doc=(
            "When they first ordered. Derived from ``MIN(orders.created_at)`` rather than "
            "read from a column, so it stays true no matter what a later writer does — the "
            "same derivation the list publishes as ``firstOrderAt``."
        ),
        null_is_stale=True,
        sortable=True,
        is_aggregate=True,
    ),
    _instant_field(
        "last_order_at",
        lambda: _scalar(sa.func.max(OrderRow.created_at), _by_telegram_id(OrderRow)),
        doc=(
            "When they last ordered — the purchase-shaped activity signal this package "
            "publishes INSTEAD of ``last_seen_at``, and the reason that refusal costs the "
            "panel nothing. Bounded, purchase-shaped, and one number rather than a live "
            "feed. NULL means never ordered, which a backward-looking operator includes."
        ),
        null_is_stale=True,
        sortable=True,
        is_aggregate=True,
    ),
    _instant_field(
        "last_delivered_at",
        lambda: _scalar(sa.func.max(OrderRow.delivered_at), _by_telegram_id(OrderRow)),
        doc=(
            "When we last delivered to them. Separate from ``last_order_at`` because an "
            "order placed and an order fulfilled are different facts, and a 'here is "
            "something new' campaign is owed to people we actually delivered to."
        ),
        null_is_stale=True,
        sortable=True,
        is_aggregate=True,
    ),
    _enum_field(
        "order_state",
        OrderState,
        _order_state_matches,
        doc=(
            "'Has an order in one of these states' — a presence question over a closed enum "
            "of our own pipeline's stages. It names no order and reveals nothing about any "
            "one of them, which is what keeps it a segment predicate rather than a peek at "
            "the orders screen. ``in``/``not_in`` only: an account has many orders, so 'is "
            "equal to' has no single answer to be equal to."
        ),
        ops=_SET_OPS,
        is_aggregate=True,
    ),
    # -- plan_purchases ------------------------------------------------------
    _enum_field(
        "plan_status",
        PlanStatus,
        _plan_status_matches,
        doc=(
            "Where the account stands on plans, in four mutually-exclusive, exhaustive "
            "cases derived from ``PlanState``'s own two predicates. Our commercial "
            "relationship with them, which is the thing a campaign is allowed to be about. "
            "**``lapsed`` is the only truthful spelling of 'did not renew'** — there is no "
            "renewal in this product, no auto-renew and no recurring billing, so the "
            "operator-facing label must read 'plan expired and not repurchased'. Getting "
            "that wrong ships 'your subscription lapsed' to people who never had one."
        ),
        ops=_SET_OPS,
        is_aggregate=True,
    ),
    _instant_field(
        "plan_ends_at",
        lambda: _scalar(
            sa.func.max(PlanPurchaseRow.plan_ends_at), _by_telegram_id(PlanPurchaseRow)
        ),
        doc=(
            "When the longest-running plan stops minting. The one field with a genuine "
            "forward-looking use — ``within_next_days`` is 'whose plan ends this week', the "
            "audience for the only renewal-shaped message this product can honestly send."
        ),
        null_is_stale=True,
        is_aggregate=True,
    ),
    _int_field(
        "plan_purchase_count",
        lambda: _counted(PlanPurchaseRow, _by_telegram_id(PlanPurchaseRow)),
        doc=(
            "How many plans they have bought. A count of receipts we issued; it separates a "
            "first-time buyer from someone who has come back three times, which is the whole "
            "of what a loyalty message needs to know."
        ),
        is_aggregate=True,
    ),
    # -- topup_purchases, payment_intents, bot_membership_events -------------
    _int_field(
        "topup_count",
        lambda: _counted(TopupPurchaseRow, _by_telegram_id(TopupPurchaseRow)),
        doc=(
            "How many top-ups they have bought. A count of receipts WE issued, on our own "
            "one-off rail. It separates somebody who bought a single song once from somebody "
            "who keeps coming back for them, which is the only thing a repeat-purchase "
            "message needs to know — and it names no product, no amount and no date."
        ),
        sortable=True,
        is_aggregate=True,
    ),
    _int_field(
        "topup_spend_minor",
        lambda: sa.func.coalesce(
            _scalar(sa.func.sum(TopupPurchaseRow.amount_minor), _by_telegram_id(TopupPurchaseRow)),
            0,
        ),
        doc=(
            "Total top-up spend in minor units. Money WE charged, from our own ledger, in "
            "the currency the receipt was written in. ``SUM`` is NULL over an empty set on "
            "both dialects, so the ``COALESCE`` is what makes 'never topped up' sort as zero "
            "instead of vanishing to whichever end the dialect puts NULLs."
        ),
        sortable=True,
        is_aggregate=True,
    ),
    _instant_field(
        "last_topup_at",
        lambda: _scalar(
            sa.func.max(TopupPurchaseRow.created_at), _by_telegram_id(TopupPurchaseRow)
        ),
        doc=(
            "When they last topped up — our own receipt's stamp, not a claim about the "
            "customer's wallet. It is the money-shaped counterpart to ``last_order_at`` and "
            "carries the same NULL reading: never topped up is stale, so a backward-looking "
            "operator reaches them and a forward-looking one does not."
        ),
        null_is_stale=True,
        sortable=True,
        is_aggregate=True,
    ),
    _bool_field(
        "has_paid_ever",
        lambda: sa.or_(
            _exists(_by_telegram_id(TopupPurchaseRow)), _exists(_by_telegram_id(PlanPurchaseRow))
        ),
        doc=(
            "Has money ever moved, on either rail. The single most useful cut a campaign "
            "makes — 'customers' against 'people who have only ever looked' — and it is one "
            "bit derived from two of our own ledgers, disclosing neither amount nor date."
        ),
        is_aggregate=True,
    ),
    _bool_field(
        "has_abandoned_checkout",
        lambda: sa.and_(
            _exists(
                _by_telegram_id(PaymentIntentRow),
                PaymentIntentRow.state.in_(_ABANDONED_INTENT_STATES),
            ),
            sa.not_(
                _exists(
                    _by_telegram_id(PaymentIntentRow),
                    PaymentIntentRow.state == PaymentIntentState.PAID,
                )
            ),
        ),
        doc=(
            "Started a payment and never completed one. A fact about our own checkout "
            "funnel — no amount, no rail, no card, no reference. The second half subtracts "
            "anyone who ever paid, so this never reaches a customer who abandoned one "
            "attempt and completed the next."
        ),
        is_aggregate=True,
    ),
    _int_field(
        "bot_block_event_count",
        lambda: _counted(
            BotMembershipEventRow,
            _by_telegram_id(BotMembershipEventRow),
            BotMembershipEventRow.event == BotMembershipEvent.BLOCKED,
        ),
        doc=(
            "How many times this account has blocked the bot. Our own delivery history. Not "
            "sortable: a ranked list of the people most annoyed with us is a leaderboard "
            "nobody needs, and the count answers every question a campaign has as a filter."
        ),
        is_aggregate=True,
    ),
    _bool_field(
        "has_returned_after_block",
        lambda: sa.and_(
            _exists(
                _by_telegram_id(BotMembershipEventRow),
                BotMembershipEventRow.event == BotMembershipEvent.BLOCKED,
            ),
            _exists(
                _by_telegram_id(BotMembershipEventRow),
                BotMembershipEventRow.event == BotMembershipEvent.UNBLOCKED,
            ),
        ),
        doc=(
            "Blocked us at some point and unblocked us at some point. Two bits from our own "
            "membership log, and the audience most worth being careful with: they left once "
            "already."
        ),
        is_aggregate=True,
    ),
    # -- chat_messages: capability-gated -------------------------------------
    _int_field(
        "inbound_message_count",
        lambda: _counted(
            ChatMessageRow,
            ChatMessageRow.telegram_user_id == UserRow.telegram_user_id,
            ChatMessageRow.direction == ChatDirection.INBOUND,
        ),
        doc=(
            "How many messages this account has sent us. A COUNT of rows, never their "
            "contents: ``chat_messages.body`` is in ``SEGMENT_REFUSALS`` on exactly the same "
            "footing as the profile names, and no operator, at any role, may point a "
            "predicate at what a customer typed."
        ),
        is_aggregate=True,
        capability=CHAT_MESSAGES_TABLE,
    ),
    _instant_field(
        "last_inbound_message_at",
        lambda: _scalar(
            sa.func.max(ChatMessageRow.created_at),
            ChatMessageRow.telegram_user_id == UserRow.telegram_user_id,
            ChatMessageRow.direction == ChatDirection.INBOUND,
        ),
        doc=(
            "When they last wrote to us. A stamp on our own inbox, at the granularity a "
            "re-engagement window needs, and the closest this registry comes to "
            "``last_seen_at`` — which is why it is filterable and not sortable either."
        ),
        null_is_stale=True,
        is_aggregate=True,
        capability=CHAT_MESSAGES_TABLE,
    ),
    FieldSpec(
        key="wizard_step",
        kind=FieldKind.TOKEN,
        ops=_SET_OPS,
        build=_wizard_step_build,
        doc=(
            "Which step of OUR wizard they have reached. The values are short tokens this "
            "system writes from its own closed vocabulary — never text a customer typed — "
            "and each is length-capped at the column's own width, so the ``in`` list cannot "
            "become a probe of anything else. It is how 'people who got as far as choosing "
            "an occasion and stopped' is expressible at all."
        ),
        is_aggregate=True,
        capability=CHAT_MESSAGES_TABLE,
    ),
)

#: The allowlist, keyed by the name the wire document uses. A miss is a refusal naming the
#: field, never a fallback and never a column lookup.
FIELDS: Final[Mapping[str, FieldSpec]] = {spec.key: spec for spec in _SPECS}

#: Sortable keys, derived from :data:`FIELDS` rather than listed a second time — a second
#: list is how ``last_activity_at`` would eventually become sortable by accident. **No string
#: from a caller ever reaches ``ORDER BY``**: the key indexes into this mapping and the
#: mapping returns an expression object this module built.
SORT_KEYS: Final[Mapping[str, FieldSpec]] = {
    spec.key: spec for spec in _SPECS if spec.sortable and spec.sort_build is not None
}


@dataclass(frozen=True, slots=True)
class CompiledSegment:
    """What a document lowers to: one predicate, one order, and what it cost to compile.

    ``predicate is None`` means "everyone" — the unfiltered list — and is reachable only from
    an empty ROOT group. An empty nested group is a refusal, because a silently-true group is
    how an operator ships a campaign to the whole database believing it was narrowed.
    """

    predicate: ColumnElement[bool] | None
    sort: SortSpec
    #: How many rules compiled to a correlated subquery. The router reads it to refuse
    #: ``?withTotal=`` beside an aggregate sort, so one request never pays for both.
    aggregate_rule_count: int


def segment_capabilities() -> frozenset[str]:
    """Which optional tables this deployment actually has installed.

    Read from the ORM metadata through ``sql.has_table`` so a capability flips itself on the
    day its migration lands rather than waiting for somebody to remember a boolean. The
    caller passes the result to :func:`compile_segment`; it is not read inside, so a test can
    compile against a deployment it is not running on.
    """
    return frozenset(name for name in (CHAT_MESSAGES_TABLE,) if has_table(name))


def compile_segment(
    segment: Segment, *, now: datetime, capabilities: frozenset[str]
) -> Result[CompiledSegment]:
    """Lower a segment document to a boolean expression. Never raises; a bad document is an ``Err``.

    The whole document is validated before any of it is trusted: the limits first, so a
    pathological document is refused before it is walked, then each rule against the field's
    own operator set, its kind and this deployment's capabilities.

    ``now`` is threaded to every relative operator and read nowhere else, so one clock decides
    what "the last 90 days" means for every rule in the document — a compiler that read the
    wall clock per rule could produce a segment whose two halves disagree about today.
    """
    limits = _check_limits(segment.root)
    if is_err(limits):
        return limits
    sort = _check_sort(segment.sort)
    if is_err(sort):
        return sort
    counter = _AggregateCounter()
    compiled = _compile_group(segment.root, now=now, capabilities=capabilities, counter=counter)
    if is_err(compiled):
        return compiled
    if counter.total > SEGMENT_LIMITS.max_aggregate_rules:
        return _refuse(
            "a segment may use at most "
            f"{SEGMENT_LIMITS.max_aggregate_rules} rules that scan a related table",
            parameter="rules",
        )
    return ok(
        CompiledSegment(
            predicate=compiled.value, sort=sort.value, aggregate_rule_count=counter.total
        )
    )


def sort_expression(key: str) -> sa.SQLColumnExpression[Any]:
    """The total, non-null expression ``key`` orders by.

    **Total and non-null is a requirement, not a nicety.** SQLite and Postgres disagree about
    where NULLs land without an explicit ``NULLS FIRST/LAST``, and a keyset cursor has to
    carry a concrete scalar it can resume from — so every sortable expression is
    ``COALESCE``-d to zero or to the epoch. The consequence is stated in the UI rather than
    hidden: "never ordered" sorts as the epoch, "never metered" as zero.

    Raises :class:`SegmentError` for a key that is not sortable. Unlike everything else in
    this module that is a ``raise`` and not an ``Err``, because the key reaching here has
    already been validated by :func:`compile_segment` against the same mapping: a miss is a
    caller that skipped the compiler, which is a bug rather than bad input.
    """
    spec = SORT_KEYS.get(key)
    if spec is None or spec.sort_build is None:
        raise SegmentError("this field cannot be sorted on", context={"parameter": "sort"})
    return spec.sort_build()


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
class _AggregateCounter:
    """How many correlated-subquery rules the walk has seen. One mutable box, not a return."""

    def __init__(self) -> None:
        self.total = 0


def _check_sort(sort: SortSpec) -> Result[SortSpec]:
    """The key must be in the registry's own sortable subset.

    The DIRECTION needs no check: :data:`SortDirection` is a two-member ``Literal`` and the
    wire layer cannot construct anything else, so a runtime guard here would be dead code
    asserting what the type already carries.
    """
    if sort.key not in SORT_KEYS:
        return _refuse("unknown sort key", parameter="sort", field=sort.key)
    return ok(sort)


def _check_limits(root: SegmentGroup) -> Result[None]:
    """Depth and total rule count, checked before the document is walked.

    Before, not during: a refusal that fires halfway through a walk has already built half a
    query out of a document it was going to reject, and the error it reports is whichever
    rule it happened to reach rather than the limit that was actually broken.
    """
    depth = _depth(root)
    if depth > SEGMENT_LIMITS.max_depth:
        return _refuse(
            f"a segment may nest at most {SEGMENT_LIMITS.max_depth} levels deep",
            parameter="rules",
        )
    total = _rule_count(root)
    if total > SEGMENT_LIMITS.max_rules:
        return _refuse(
            f"a segment may carry at most {SEGMENT_LIMITS.max_rules} rules", parameter="rules"
        )
    return ok(None)


def _depth(node: SegmentNode) -> int:
    if isinstance(node, SegmentRule):
        return 0
    if not node.rules:
        return 1
    return 1 + max(_depth(child) for child in node.rules)


def _rule_count(node: SegmentNode) -> int:
    if isinstance(node, SegmentRule):
        return 1
    return sum(_rule_count(child) for child in node.rules)


def _compile_group(
    group: SegmentGroup,
    *,
    now: datetime,
    capabilities: frozenset[str],
    counter: _AggregateCounter,
    is_root: bool = True,
) -> Result[ColumnElement[bool] | None]:
    """One group to one clause, or ``None`` for the empty root.

    An empty NESTED group is refused while an empty ROOT group means "everyone". The
    asymmetry is the point: an operator who cleared the last rule off the top-level filter
    can see that the list is unfiltered, whereas an empty ``any`` buried two levels down is
    invisibly ``TRUE`` and takes the whole group's negation with it.
    """
    if not group.rules:
        if is_root:
            return ok(None)
        return _refuse("a group must carry at least one rule", parameter="rules")
    clauses: list[ColumnElement[bool]] = []
    for child in group.rules:
        if isinstance(child, SegmentRule):
            leaf = _compile_rule(child, now=now, capabilities=capabilities, counter=counter)
            if is_err(leaf):
                return leaf
            clauses.append(leaf.value)
            continue
        nested = _compile_group(
            child, now=now, capabilities=capabilities, counter=counter, is_root=False
        )
        if is_err(nested):
            return nested
        if nested.value is not None:
            clauses.append(nested.value)
    match group.match:
        case MatchMode.ALL:
            return ok(sa.and_(*clauses))
        case MatchMode.ANY:
            return ok(sa.or_(*clauses))
        case MatchMode.NONE:
            return ok(sa.not_(sa.or_(*clauses)))


def _compile_rule(
    rule: SegmentRule,
    *,
    now: datetime,
    capabilities: frozenset[str],
    counter: _AggregateCounter,
) -> Result[ColumnElement[bool]]:
    """One rule to one predicate, through the registry and nothing else.

    The document supplies a KEY. ``FIELDS[key]`` is a dict lookup against a mapping this file
    wrote; a miss is a refusal naming the field, which is a schema name this API already
    publishes and not customer data. The value never appears in an error.
    """
    spec = FIELDS.get(rule.field)
    if spec is None:
        return _refuse("unknown field", parameter="rules", field=rule.field)
    if spec.capability is not None and spec.capability not in capabilities:
        # Named, never dropped: "this deployment has no chat log" and "nobody matched" must
        # not look the same on a screen an operator is about to send a campaign from.
        return _refuse("this field is not available here", parameter="rules", field=rule.field)
    if rule.op not in spec.ops:
        return _refuse("this operator does not apply to this field", field=rule.field)
    if spec.is_aggregate:
        counter.total += 1
    built = spec.build(rule.op, rule.value, now=now)
    if is_err(built):
        # Re-stamped with the field so a caller with twenty-five rules is told WHICH one, and
        # still without the value that caused it.
        return err(built.error.with_context(field=rule.field))
    return built
