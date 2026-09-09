"""``/users`` — the list and the detail, named for what the data can actually prove.

**``users`` has three writers, and none of them is an order alone.** This module used to
open by claiming exactly one writer (``repository._ensure_user``) and exactly one call site
(``_create_order``), and by concluding that a person who walks the whole wizard without
confirming "has no row at all". Every clause of that was already false in the shipped code
before onboarding existed, so it is corrected here rather than merely updated. The writers,
with their files:

* ``hbd.db.users_sql.ensure_user`` — called from ``repository._create_order`` when an order
  is placed, and from ``SqlUserProfiles.record_language`` (``db/user_profiles.py``) the
  moment somebody answers the first question the bot asks.
* ``credits.touch`` (``db/credits.py``) — an UPSERT keyed on ``telegram_user_id`` that runs
  for **every inbound update**, driven by ``bot/gate.py``'s ``TouchDrain`` and wired in
  production by ``main.py``. (Cited by name rather than by line: this paragraph's numbers
  had already rotted once, and a reader who lands in the middle of a different function
  reads the wrong writer's UPSERT semantics.)
* ``credits.set_blocked`` (``db/credits.py``) — an UPSERT too, deliberately, so an operator
  can bar an account that never ordered.

Two consequences, both surfaced rather than papered over:

* ``users.created_at`` — this module's ``account_created_at`` — means **first contact**, not
  first order, and the list therefore contains people who have never bought anything. That
  is what onboarding bought the panel, and it is the point.
* ``users.last_seen_at`` does now have a real writer, and this module still refuses to
  publish it: ``touch`` moves it per *update*, so a "last seen" column would let an operator
  watch a customer's activity minute by minute from a screen whose stated purpose is
  records. The list reports :attr:`~hbd.db.admin.views.UserListItem.last_order_at` instead,
  derived from ``MAX(orders.created_at)`` so it stays true no matter what a later writer
  does to the column, and says one bounded, purchase-shaped thing.

The identity half of a row — the phone number, the handle, the names, the avatar stamps —
comes from a LEFT OUTER join on ``user_profiles``, never an INNER one, for the reason
:func:`_filtered_with_profile` states at length. The entitlement half — balance, lifetime
grants, the last allowance window — comes from a second LEFT OUTER join on
``credit_accounts``, keyed on the **Telegram id** because that is the only column the two
tables share, and OUTER for a sharper reason than the profile's: ``credit_accounts`` has no
row until the account's first charge or grant, so an INNER join would delete every customer
who has not bought anything from a list whose whole point since onboarding is that they are
on it.

The detail additionally calls :func:`hbd.db.credit_sql.read_balance`, which is what the
bot's own gate calls, with the deployment's own :class:`~hbd.entitlements.EntitlementPolicy`
passed in — so the panel reports the number the customer was shown rather than a second one
derived here, and rather than one computed against a settlement grace this deployment does
not run (see :func:`get_user_detail`). The list does **not**: that function is one account's
answer and costs three statements, and fifty of them per page is the N+1 the join above
exists to avoid.

The per-user aggregates are one grouped query over the orders of the page's users, not one
query per row: a fifty-row page must be two round trips, never fifty-one. The join must not
break that promise, and it does not — it is on ``user_profiles.user_id``, that table's
PRIMARY KEY, so it cannot multiply rows.

**The segment engine enters here and nowhere else.** ``BROADCAST_SPEC §1.7``:
:mod:`hbd.db.admin.segment` compiles a document into one boolean expression, this module
ANDs it into :func:`_filtered` beside the chips, and that is the entire seam — so the
broadcast wizard's audience and the operator's Users screen are narrowed by the same
statement builder rather than by two that agree today. Two consequences are visible in this
module's API and are argued where they live: a sort key other than the default one makes the
page a :class:`~hbd.db.admin.page.SortedCursor` walk (:func:`_sorted`), and "how many people
will receive this" is :func:`count_segment_exactly` rather than the bounded
:func:`count_users`, because a total that saturates at ten thousand is not an answer a human
can authorise a send against.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from hbd.contracts import Language, OrderState
from hbd.db.admin.page import (
    BoundedTotal,
    Cursor,
    Page,
    PageRequest,
    SortedCursor,
    SortSpec,
    SortValue,
    SortValueKind,
    bounded_total,
    build_page,
    build_sorted_page,
    keyset_order,
    keyset_predicate,
    sorted_keyset_order,
    sorted_keyset_predicate,
)
from hbd.db.admin.segment import (
    SORT_KEYS,
    CompiledSegment,
    FieldKind,
    SegmentError,
    sort_expression,
)
from hbd.db.admin.segment import SortSpec as SegmentSortSpec
from hbd.db.admin.sql import TimeWindow, apply_search, apply_window, count_where
from hbd.db.admin.views import SegmentBreakdown, UserDetail, UserListItem
from hbd.db.credit_sql import read_balance
from hbd.db.models.credit_account import CreditAccountRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from hbd.db.models.user_profile import UserProfileRow
from hbd.entitlements import DEFAULT_ENTITLEMENT_POLICY, EntitlementPolicy

__all__ = [
    "UserFilters",
    "OrderRollup",
    "page_sort",
    "list_users",
    "count_users",
    "count_segment_exactly",
    "segment_breakdown",
    "get_user_detail",
    "load_avatar",
]

#: States that mean the customer paid, mirroring ``repository._PAID_STATES``. Restated rather
#: than imported because it is private there, and a read model must not make a private
#: constant public by using it.
_PAID_STATES: tuple[OrderState, ...] = (
    OrderState.AUTHORIZED,
    OrderState.GENERATING,
    OrderState.DELIVERED,
)


@dataclass(frozen=True, slots=True)
class UserFilters:
    """§6.6's filter set.

    **There is no phone filter and no name filter, and the two refusals are for different
    reasons.** The panel now holds a phone number and three names for every onboarded
    account, so "filter by phone" is a question an operator can finally ask — and must not
    be able to. The phone is masked at every role, OWNER included, so an exact-match filter
    on it would be an oracle: an operator could confirm a complete E.164 number by probing
    this parameter against a column they are not entitled to read, with no step-up, no
    budget unit and no audit row to show for it. ``POST /reveal`` is the only unmask path,
    which is only true for as long as nothing else in the API answers questions about the
    value.

    **:attr:`search` is that refusal restated for substrings, and a substring is worse.** An
    exact filter confirms a value somebody already holds whole; a ``LIKE '%…%'`` over
    ``user_profiles.first_name`` confirms it three characters at a time, so an operator with
    no reveal cell at all could recover a name by binary search against a screen that
    charges no budget and writes no audit row. Every free-text column this table can reach
    — ``telegram_username``, ``first_name``, ``last_name``, ``phone_e164`` — is ``M`` at all
    four roles in §12.3 and therefore off limits to a ``WHERE`` clause a caller steers. That
    is not a limitation of the helper: :func:`hbd.db.admin.sql.search_clause` would search
    them perfectly well, and the refusal is the point.

    **:attr:`segment` does not widen any of that, because the registry it compiles against is
    an ALLOWLIST.** ``BROADCAST_SPEC §1.1``'s document arrives as base64 JSON from a browser
    and names a **key**, never a column: ``FIELDS[key]`` is a dict lookup that returns a
    builder, so a field nobody wrote into :mod:`hbd.db.admin.segment` is unaddressable under
    any spelling and the four columns above are named in ``SEGMENT_REFUSALS`` so that adding
    one back is a deliberate edit rather than an oversight. Values are bound parameters
    through ordinary expression construction — the same rule this class's ``search`` obeys.
    The segment is therefore a *second* filter of the same shape as the chips, not a second
    permission: everything it can ask, an operator could already ask by clicking, and every
    free-text predicate stays refused in both.

    **``users.last_seen_at`` is the one asymmetry, and it is deliberate.** The registry lets a
    segment *filter* on it (``last_activity_at`` — "quiet for 90 days" is the whole of a
    re-engagement campaign, and it discloses only the bucket the operator themself chose),
    while this module refuses to *project* it (the module docstring; :func:`_list_item`
    publishes ``last_order_at`` instead) and the registry refuses to *sort* on it
    (``sortable=False``, so :func:`sort_expression` has no expression to hand back). A
    predicate answers one bounded question; a column or an ordering hands over a total
    activity ranking of identified accounts, which is the surveillance the withheld column
    exists to prevent.
    """

    #: Exact ``telegram_user_id``. Deliberately not a name search, and now deliberately not a
    #: phone search either. A name lives in ``briefs`` and is purged on its own clock, so a
    #: name query returns a shrinking answer set for the same input and reads as data loss.
    #: The phone is the refusal the class docstring argues: an exact-match filter on a value
    #: masked at every role is an unaudited unmask oracle.
    telegram_user_id: int | None = None
    #: §6.6's ``q``, and it searches **the Telegram id and nothing else** — the one value an
    #: operator has in hand from a support ticket, and the one this screen already returns
    #: unmasked in every row (``schemas/users.py``: every ``/users/**`` route keys on it, so
    #: the panel could not build a link or a reveal without it). Matching a substring of a
    #: value the same response already prints in full discloses nothing the caller did not
    #: have; matching a substring of a masked name discloses the mask. It is separate from
    #: :attr:`telegram_user_id` rather than a widening of it because the two are asked in
    #: different situations — a pasted id is exact, a half-remembered or line-wrapped one is
    #: not — and because an exact filter that silently became a substring match would change
    #: what every existing caller's page means.
    search: str | None = None
    is_blocked: bool | None = None
    #: "Has balance > 0", and its ``False`` is the exact complement of its ``True`` — which is
    #: the only reading that lets an operator flip the chip and see every row again.
    #:
    #: ``True`` matches an account whose ``credit_accounts.balance`` is strictly positive.
    #: A customer with **no** ``credit_accounts`` row does **not** match: the row is opened by
    #: the first charge or grant, so its absence means never metered, and never metered is not
    #: a positive balance no matter how much allowance the entitlement policy still owes them.
    #: (It is the same distinction :func:`_list_item` publishes as ``credit_balance=None``
    #: rather than ``0``, held to here so the filter and the column cannot disagree.)
    #:
    #: ``False`` therefore means "no positive balance" and covers **both** of the other two
    #: shapes — never metered, and metered down to zero — because anything narrower would
    #: leave rows that neither value of the filter can reach.
    #:
    #: It is deliberately a filter on the STORED column and not on
    #: :func:`~hbd.db.credit_sql.read_balance`'s projection: the projection is three statements
    #: per account and a ``WHERE`` cannot call it, and it is a function of ``now``, so a page
    #: filtered on it would change under a cursor mid-pagination.
    has_balance: bool | None = None
    ui_languages: tuple[Language, ...] = ()
    #: Applied to ``users.created_at`` — that is, this account's FIRST CONTACT, which since
    #: onboarding is the language question rather than a confirmed order. See the module
    #: docstring for the three writers that can mint the row.
    window: TimeWindow | None = None
    #: A COMPILED segment — :func:`hbd.db.admin.segment.compile_segment`'s output, never a
    #: document and never a string. It is ANDed with every chip above rather than replacing
    #: them, which is what keeps a bookmarked chip URL working and lets the wizard's audience
    #: and the operator's screen be narrowed by the same statement builder.
    #:
    #: ``CompiledSegment.predicate is None`` — an empty root group — means "everyone" and adds
    #: no clause at all, so an unfiltered segment costs exactly what no segment costs.
    segment: CompiledSegment | None = None
    #: The order the page is walked in, or ``None`` for the ``(users.created_at, users.id)``
    #: keyset this list has always used and the smaller :class:`~hbd.db.admin.page.Cursor`
    #: token that goes with it. ``None`` is not a *different* order from the registry's
    #: default: ``joined_at`` **is** ``users.created_at``, so a segment sorted the default way
    #: keeps the cheap cursor and only a genuinely different key pays for the sorted one.
    #:
    #: It is the PAGINATION layer's :class:`~hbd.db.admin.page.SortSpec`, not the segment
    #: layer's — the two are structurally identical and nominally distinct, which is the whole
    #: reason :func:`page_sort` exists rather than a constructor call at each call site.
    #: :meth:`__post_init__` refuses a sort that contradicts :attr:`segment`'s own, because a
    #: page ordered by one key while the stored document claims another is a campaign
    #: preview that describes an audience nobody will see in that order.
    sort: SortSpec | None = None

    def __post_init__(self) -> None:
        if self.segment is None or self.sort is None:
            return
        declared = (self.segment.sort.key, self.segment.sort.direction)
        if (self.sort.key, self.sort.direction) != declared:
            raise ValueError(f"sort {self.sort!r} contradicts the compiled segment's {declared!r}")


@dataclass(frozen=True, slots=True)
class OrderRollup:
    """One user's order aggregates, as the database returns them."""

    order_count: int
    paid_order_count: int
    first_order_at: datetime | None
    last_order_at: datetime | None


def page_sort(sort: SegmentSortSpec) -> tuple[SortSpec, SortValueKind]:
    """A compiled segment's sort, restated in the pagination layer's terms.

    Two things the caller needs and must not derive twice:
    :class:`hbd.db.admin.page.SortSpec` for :attr:`UserFilters.sort` and for
    :func:`~hbd.db.admin.page.decode_sorted_cursor`, and the
    :class:`~hbd.db.admin.page.SortValueKind` that same decoder needs to read the token's
    value back — an ISO instant and a decimal integer are both strings on the wire, and the
    kind comes from the field registry rather than from the token so the parse depends on the
    schema instead of on the data.

    It exists because ``page.SortSpec`` and ``segment.SortSpec`` are two frozen dataclasses
    with the same name and the same two fields, and a hand-written conversion at every call
    site is a rename away from being wrong at one of them.

    Raises :class:`~hbd.db.admin.segment.SegmentError` for a key the registry cannot order by,
    which is unreachable for a sort that came out of :func:`~hbd.db.admin.segment.compile_segment`
    — that is the boundary which turns an unknown key into a 422. A sortable field is an
    instant or an integer and nothing else: a text sort key would be a total alphabetical
    order over account names, the same unmask oracle :data:`_SEARCHABLE_COLUMNS` refuses.
    """
    spec = SORT_KEYS.get(sort.key)
    if spec is None:
        raise SegmentError("this field cannot be sorted on", context={"parameter": "sort"})
    if spec.kind is FieldKind.INSTANT:
        kind = SortValueKind.INSTANT
    elif spec.kind is FieldKind.INT:
        kind = SortValueKind.INTEGER
    else:
        raise SegmentError("this field cannot be sorted on", context={"parameter": "sort"})
    return SortSpec(key=sort.key, direction=sort.direction), kind


async def list_users(
    session: AsyncSession,
    *,
    filters: UserFilters,
    request: PageRequest,
    cursor: SortedCursor | None = None,
) -> Page[UserListItem]:
    """One keyset page of users, with their profile and order rollups.

    Newest account first unless :attr:`UserFilters.sort` asks for another order, and the two
    walks take **different cursors**: the default one resumes from ``request.cursor``, a
    sorted one from ``cursor``. They are separate parameters rather than one widened field
    because a token minted under one ordering cannot resume the other — that is the refusal
    :func:`~hbd.db.admin.page.decode_sorted_cursor` exists to make at the HTTP boundary — and
    a caller that supplies the wrong one has skipped that boundary, so it raises
    ``ValueError`` here rather than quietly paging through a different list.

    The keyset predicate and ordering stay on ``UserRow`` columns even though the statement
    now carries a second entity: a cursor is a position in the ``users`` table and was minted
    from ``users.created_at``/``users.id``, so letting the join anywhere near it would let a
    profile row move a page boundary and silently drop or repeat customers across pages. The
    sorted walk holds to the same rule — its key is a registry expression over ``users`` and
    its correlated subqueries, tie-broken on ``users.id``, and never a joined column.
    """
    if filters.sort is None:
        if cursor is not None:
            raise ValueError("a sorted cursor cannot resume a list that has no sort")
        return await _newest_first(session, filters, request)
    if request.cursor is not None:
        raise ValueError("an unsorted cursor cannot resume a sorted list")
    return await _sorted(session, filters, request, cursor, sort=filters.sort)


async def count_users(session: AsyncSession, *, filters: UserFilters) -> BoundedTotal:
    """``?withTotal=true`` for the same filter set."""
    return await bounded_total(session, _filtered(filters))


async def count_segment_exactly(session: AsyncSession, *, filters: UserFilters) -> int:
    """How many accounts this filter set really selects. No cap, no probe, one number.

    **Deliberately not :func:`count_users`.** That one stops at
    :data:`~hbd.db.admin.page.TOTAL_COUNT_CAP` and labels the answer ``is_exact=False``, which
    is the right trade for a screen where "10,000+" is a fine thing to render beside a page of
    fifty rows. It is the wrong trade for the only question a broadcast wizard asks — *how
    many people will receive this* — where a saturated count is not an approximation but a
    refusal to answer, and where an operator would be authorising a send against a number the
    system knows is not the number.

    The cost is stated rather than hidden: this is a full scan of everything the filters
    match, and a segment's aggregate rules make it a correlated subquery per row on the way
    through. That is affordable because it is paid **once per audience**, at the moment a
    human is deciding, and never per page render — which is exactly why it is a separate
    function with a separate name instead of a flag on the paginated count.
    """
    counted = await session.scalar(
        # ``maintain_column_froms`` for the reason ``bounded_total`` gives: without it the
        # FROM the original columns implied is discarded and the count counts one row.
        _filtered(filters).with_only_columns(sa.func.count(), maintain_column_froms=True)
    )
    return int(counted or 0)


async def segment_breakdown(session: AsyncSession, *, filters: UserFilters) -> SegmentBreakdown:
    """The audience preview's numbers: how many, how many reachable, and in which languages.

    **One grouped statement, not five counts.** The three dimensions a preview reports —
    ``ui_language``, our bar, their block — are all columns of ``users``, so grouping on them
    together costs one pass over whatever the filters matched, while five separate counts
    would pay for a segment's correlated subqueries five times over. The cardinality is
    bounded by ``len(Language) * 2 * 2`` regardless of how many accounts match, so the rows
    come back small however large the audience is.

    Aggregated in Python rather than with five conditional ``SUM``s for one reason: the
    overlap between :attr:`~hbd.db.admin.views.SegmentBreakdown.blocked` and
    :attr:`~hbd.db.admin.views.SegmentBreakdown.bot_blocked` is a fact about the audience,
    and it is easier to see it is preserved in four ``if``s over the same rows than inside
    four ``CASE`` expressions that would each have to be read for what they exclude.

    Exact for the reason :func:`count_segment_exactly` gives, and it shares
    :func:`_filtered` with the page for the reason that function's comment gives — the
    preview and the screen an operator checks it against cannot be two populations.
    """
    bot_blocked_column = UserRow.blocked_bot_at.is_not(None)
    statement = (
        # ``maintain_column_froms`` for the reason ``bounded_total`` gives: without it the
        # FROM the original columns implied is discarded.
        _filtered(filters)
        .with_only_columns(
            UserRow.ui_language,
            UserRow.is_blocked,
            bot_blocked_column,
            sa.func.count(),
            maintain_column_froms=True,
        )
        .group_by(UserRow.ui_language, UserRow.is_blocked, bot_blocked_column)
    )
    matched = 0
    reachable = 0
    blocked = 0
    bot_blocked = 0
    per_language: dict[Language, int] = {}
    for language, is_blocked, blocked_the_bot, count in (await session.execute(statement)).all():
        matched += count
        if is_blocked:
            blocked += count
        if blocked_the_bot:
            bot_blocked += count
        if not is_blocked and not blocked_the_bot:
            reachable += count
        per_language[language] = per_language.get(language, 0) + count
    return SegmentBreakdown(
        matched=matched,
        reachable=reachable,
        blocked=blocked,
        bot_blocked=bot_blocked,
        by_language=tuple(sorted(per_language.items(), key=lambda pair: pair[0].value)),
    )


async def get_user_detail(
    session: AsyncSession,
    telegram_user_id: int,
    *,
    now: datetime,
    policy: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
) -> UserDetail | None:
    """One user plus their per-state order breakdown, or ``None`` when they have no row.

    ``now`` is a parameter and never ``utc_now()`` read here, for the reason every read
    module in this package takes its clock: the allowance projection below is a function of
    which rolling window the instant falls in, so a query that read the wall clock itself
    could not be tested across a period boundary at all.

    ``policy`` is a parameter for the same reason, and it used to be defaulted here — which
    was a bug with a default that hid it. ``in_flight`` is counted against
    ``now - policy.settlement_grace_s``, and the WORKER'S grace is either
    ``HBD_SETTLEMENT_GRACE_S`` or derived from its queue ladder
    (:func:`hbd.entitlements.resolve_entitlement_policy`), so a deployment that moved either
    had this function counting against 4550 seconds while the gate that actually refused the
    customer counted against something else. Under shipped defaults the two agree, which is
    exactly why nothing caught it. The caller supplies the deployment's own policy; the
    default here is the shipped one, for the callers that have no settings to read from.

    ``None`` now means something much narrower than it used to, and the old wording — that
    this "is the honest answer for someone who has chatted but never confirmed an order" —
    is false: chatting is exactly what mints the row, through ``credits.touch`` on every
    inbound update and through ``users_sql.ensure_user`` at the language question. ``None``
    therefore means this Telegram id has never reached the bot at all: no language answer, no
    touch, no order. After onboarding that is a genuinely unknown person rather than a shy
    one, and the caller's 404 says so instead of inventing an empty profile that would imply
    we hold nothing on somebody we have never met.

    The same LEFT OUTER joins as the list, and now literally the same statement builder
    rather than a second one spelled the same way: an account with no ``user_profiles`` row
    and an account with no ``credit_accounts`` row must both still resolve, or
    ``/users/{id}`` 404s for a customer whose ``/forget`` succeeded — and a detail screen
    that quietly dropped a join the list has is how "the list says 3 credits and the detail
    says none" ships.
    """
    statement = _filtered_with_profile(UserFilters()).where(
        UserRow.telegram_user_id == telegram_user_id
    )
    row = (await session.execute(statement)).first()
    if row is None:
        return None
    user, profile, account = row
    rollups = await _rollups(session, (telegram_user_id,))
    by_state = await _orders_by_state(session, telegram_user_id)
    counts = dict(by_state)
    # ``read_balance`` rather than arithmetic on ``account.balance``. It is the SAME function
    # the bot's read-only gate calls, and it is given the deployment's OWN policy, so the
    # number on this screen is the number the customer was shown — including the allowance
    # that is due but unminted, which the account row alone cannot tell you about because
    # ``/forget`` deletes the row while deliberately keeping the grant's idempotency key.
    # Re-deriving it here would give an operator a second, disagreeing answer to the one
    # question they opened this screen to settle; passing the wrong grace does the same
    # thing more quietly, which is why ``policy`` is threaded rather than defaulted.
    projected = await read_balance(
        session, telegram_user_id=telegram_user_id, now=now, policy=policy
    )
    return UserDetail(
        user=_list_item(user, profile, account, rollups.get(telegram_user_id)),
        orders_by_state=by_state,
        delivered_order_count=counts.get(OrderState.DELIVERED, 0),
        failed_order_count=counts.get(OrderState.FAILED, 0),
        credits_projected=projected.credits,
        in_flight_render_count=projected.in_flight,
    )


async def load_avatar(
    session: AsyncSession, telegram_user_id: int
) -> tuple[UUID, str | None, datetime | None] | None:
    """``(user_id, avatar_mime, avatar_stored_at)`` for the avatar route, or ``None``.

    Three columns and no more. The route needs the user id to rebuild the object key, the
    mime to decide whether it will serve this at all, and the stamp to decide whether there
    is anything to serve — and nothing else it could be handed is anything it should have. A
    :class:`~hbd.db.admin.views.UserListItem` here would put a phone number and a name into
    the locals of a handler that streams bytes to a browser, one careless log line or one
    exception-with-locals away from a disclosure that no masking layer would ever see.

    The join is OUTER so that a ``users`` row with no ``user_profiles`` row answers
    ``(user_id, None, None)`` rather than ``None``: "we have never heard of this account" and
    "this account has no avatar" stay separable at the query level even though the route
    collapses them into one 404, because the day something else wants to tell them apart the
    distinction must already be in the data rather than in a rewrite. ``None`` here therefore
    means only that no ``users`` row exists at all.

    No ``stat`` and no storage call: this layer reports what the row claims, and the route
    discovers whether the bytes are really there by trying to read them. A presence tick
    computed without looking at a file is a claim about bytes nobody has seen — the same
    refusal ``db/admin/assets.py`` makes about ``isFilePresent``.
    """
    row = (
        await session.execute(
            sa.select(UserRow.id, UserProfileRow.avatar_mime, UserProfileRow.avatar_stored_at)
            .outerjoin(UserProfileRow, UserProfileRow.user_id == UserRow.id)
            .where(UserRow.telegram_user_id == telegram_user_id)
        )
    ).first()
    if row is None:
        return None
    user_id, avatar_mime, avatar_stored_at = row
    return (user_id, avatar_mime, avatar_stored_at)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
#: The only column ``?q=`` may touch, and the ``CAST`` is what makes a substring of an
#: integer expressible at all. Rendered as ``CAST(users.telegram_user_id AS VARCHAR)`` on
#: both dialects; there is no index that could serve the leading wildcard either way, so the
#: cast costs nothing a ``LIKE '%…%'`` was not already going to cost.
#:
#: Built as a module constant rather than inside :func:`_filtered` so that the answer to "what
#: can an operator search here?" is one greppable line, and so that adding a second column is
#: a diff a reviewer sees rather than an argument that grew.
_SEARCHABLE_COLUMNS: tuple[sa.SQLColumnExpression[str], ...] = (
    sa.cast(UserRow.telegram_user_id, sa.String),
)


def _has_positive_balance() -> sa.ColumnElement[bool]:
    """``EXISTS (SELECT 1 FROM credit_accounts WHERE …AND balance > 0)``, correlated to ``users``.

    **A correlated EXISTS rather than a predicate on the outer join
    :func:`_filtered_with_profile` already carries**, and the reason is the same one
    ``test_counting_users_does_not_pay_for_the_join`` guards. The filter has to live in
    :func:`_filtered` or ``count_users`` would label a two-row page with the unfiltered total —
    exactly the drift the ``q`` comment above it argues — and ``_filtered`` is the statement
    that must **not** grow a ``credit_accounts`` join, because the count selects no column from
    that table and pays for every row the filters match. A subquery in a ``WHERE`` clause costs
    nothing when the filter is unset (it is not built at all) and, when it is set, narrows the
    count by the same predicate the list uses rather than by a second spelling of it.

    It cannot multiply rows either, which a join added to the list for filtering could not
    promise as cheaply: ``telegram_user_id`` is ``credit_accounts``' PRIMARY KEY, and an
    ``EXISTS`` is a boolean regardless.

    Negation is left to the caller — ``~`` this — so that ``has_balance=False`` is the literal
    complement of ``has_balance=True`` and the two cannot drift into a gap no filter reaches.
    """
    return sa.exists(
        sa.select(sa.literal(1)).where(
            CreditAccountRow.telegram_user_id == UserRow.telegram_user_id,
            CreditAccountRow.balance > 0,
        )
    ).correlate(UserRow)


async def _newest_first(
    session: AsyncSession, filters: UserFilters, request: PageRequest
) -> Page[UserListItem]:
    """The list this screen has always had: ``(created_at, id)`` descending, opaque ``Cursor``."""
    statement = _filtered_with_profile(filters)
    resume = keyset_predicate(UserRow.created_at, UserRow.id, request.cursor)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(*keyset_order(UserRow.created_at, UserRow.id)).limit(
        request.fetch_limit
    )
    rows = (await session.execute(statement)).all()
    rollups = await _rollups(session, tuple(user.telegram_user_id for user, _, _ in rows))
    items = [
        _list_item(user, profile, account, rollups.get(user.telegram_user_id))
        for user, profile, account in rows
    ]
    return build_page(items, request, _cursor_of)


async def _sorted(
    session: AsyncSession,
    filters: UserFilters,
    request: PageRequest,
    cursor: SortedCursor | None,
    *,
    sort: SortSpec,
) -> Page[UserListItem]:
    """The same page under a registry sort key, with the sort value SELECTed beside each row.

    The extra column is not decoration: the next page's cursor has to carry the value the walk
    stopped on, and ``topup_spend_minor`` or ``delivered_order_count`` is nowhere on
    :class:`~hbd.db.admin.views.UserListItem` — a page that re-derived it in Python would be
    resuming from a number the database never agreed to. It is the SAME expression object that
    the predicate and the ``ORDER BY`` are built from, which is what
    :func:`~hbd.db.admin.page.sorted_keyset_predicate` requires and what keeps a tie-block from
    being paged twice.

    The projection is unchanged. Sorting on a field does not publish it: the row that comes
    back is the same :func:`_list_item` every other caller gets, and the sort value leaves this
    function inside an opaque cursor rather than on the view.
    """
    column = sort_expression(sort.key)
    statement = _filtered_with_profile(filters).add_columns(column)
    resume = sorted_keyset_predicate(column, UserRow.id, cursor, sort=sort)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(
        *sorted_keyset_order(column, UserRow.id, direction=sort.direction)
    ).limit(request.fetch_limit)
    rows = (await session.execute(statement)).all()
    rollups = await _rollups(session, tuple(user.telegram_user_id for user, _, _, _ in rows))
    placed = [
        (_list_item(user, profile, account, rollups.get(user.telegram_user_id)), _sort_value(value))
        for user, profile, account, value in rows
    ]
    page = build_sorted_page(
        placed,
        request,
        lambda row: SortedCursor(k=sort.key, d=sort.direction, v=row[1], id=row[0].id),
    )
    return Page(items=tuple(item for item, _ in page.items), next_cursor=page.next_cursor)


def _sort_value(value: Any) -> SortValue:
    """The sort key's value for one row, typed for the cursor that will carry it.

    Every sortable expression in the registry is total (``COALESCE``-d) and is either an
    instant or an integer, so there is no NULL branch and no third shape to widen to. The
    ``int()`` is for SQLite, which hands a ``count`` back as whatever the driver chose.
    """
    if isinstance(value, datetime):
        return value
    return int(value)


def _filtered(filters: UserFilters) -> Select[tuple[UserRow]]:
    statement = sa.select(UserRow)
    statement = apply_window(statement, UserRow.created_at, filters.window)
    # Applied HERE rather than in :func:`_filtered_with_profile`, so ``count_users`` and
    # ``list_users`` narrow identically: a ``?withTotal=true`` computed without the search
    # would label a two-row page "1,204".
    statement = apply_search(statement, filters.search, _SEARCHABLE_COLUMNS)
    if filters.telegram_user_id is not None:
        statement = statement.where(UserRow.telegram_user_id == filters.telegram_user_id)
    if filters.is_blocked is not None:
        statement = statement.where(UserRow.is_blocked.is_(filters.is_blocked))
    if filters.has_balance is not None:
        positive = _has_positive_balance()
        statement = statement.where(positive if filters.has_balance else ~positive)
    if filters.ui_languages:
        statement = statement.where(UserRow.ui_language.in_(filters.ui_languages))
    # ANDed with the chips above, and applied HERE for the same reason they are: the segment
    # narrows the count and the page identically, so a wizard's audience preview and the
    # screen an operator checks it against can never be two different populations.
    if filters.segment is not None and filters.segment.predicate is not None:
        statement = statement.where(filters.segment.predicate)
    return statement


def _filtered_with_profile(
    filters: UserFilters,
) -> Select[tuple[UserRow, UserProfileRow | None, CreditAccountRow | None]]:
    """The filtered page, with each user's profile and credit account beside it, or ``NULL``.

    **LEFT OUTER, never INNER.** A person who answered the language question and has not yet
    shared a phone has a ``users`` row and no ``user_profiles`` row, and so does a person
    whose ``/forget`` deleted it. An INNER join would delete both from the panel, which an
    operator reads as data loss rather than as a missing profile — and the second of them is
    exactly the account most likely to be the subject of the support ticket that opened this
    screen.

    Built on :func:`_filtered` rather than replacing it, and used by :func:`list_users`
    alone: ``count_users`` shares ``_filtered`` and a count must not pay for a join. The join
    predicate is ``user_profiles.user_id``, which is that table's PRIMARY KEY, so it cannot
    multiply rows — the keyset ``LIMIT`` stays exact and the page stays two round trips
    rather than becoming a cartesian product with a truncated tail.

    **The credit account is a THIRD outer join and not a per-row read**, which is the whole
    of what keeps this page two round trips. ``credit_sql.account_state`` answers for one
    account and is the right primitive for the detail screen and for the ledger endpoint;
    called once per list row it is fifty extra statements to render one page, and the N+1
    would be invisible until a fifty-row page met a slow link. It joins on
    ``credit_accounts.telegram_user_id``, that table's PRIMARY KEY (there is deliberately no
    foreign key — see ``models/credit_account.py`` — but the key is a key regardless), so it
    cannot multiply rows any more than the profile join can.

    It is joined on the **Telegram id** rather than on ``users.id``, because that is the only
    thing the two tables share: an account may be opened before a ``users`` row exists, which
    is exactly why ``credit_accounts`` has no ``user_id`` column to join to.

    The second and third entities are typed ``| None`` because that is what the outer join
    means at runtime; SQLAlchemy's own overloads cannot express the nullability an
    ``outerjoin`` introduces, so the annotation is the only place a reader is told.
    """
    return (
        _filtered(filters)
        .add_columns(UserProfileRow, CreditAccountRow)
        .outerjoin(UserProfileRow, UserProfileRow.user_id == UserRow.id)
        .outerjoin(CreditAccountRow, CreditAccountRow.telegram_user_id == UserRow.telegram_user_id)
    )


def _cursor_of(item: UserListItem) -> Cursor:
    return Cursor(at=item.account_created_at, id=item.id)


def _list_item(
    row: UserRow,
    profile: UserProfileRow | None,
    account: CreditAccountRow | None,
    rollup: OrderRollup | None,
) -> UserListItem:
    """Assemble a list row.

    A user with no orders is possible only through a manual insert. A user with no profile,
    by contrast, is ordinary: every account that has touched the bot since onboarding shipped
    but has not finished answering it, plus every account whose ``/forget`` ran, arrives here
    with ``profile is None``. That maps to ``is_profile_present=False`` and every identity
    field to ``None`` — one flag carrying the distinction, rather than the caller guessing it
    from a null phone number that a half-onboarded account also has.

    ``account is None`` is treated differently and deliberately so: the three credit columns
    become ``None`` rather than ``0`` and there is no presence flag beside them.
    :attr:`~hbd.db.admin.views.UserListItem.credit_balance` argues why — the column is
    ``NOT NULL`` in the schema, so a null on the view has exactly one cause and can carry the
    distinction by itself, while ``0`` would say "spent everything" about a customer who has
    never been metered and is still owed their whole allowance.
    """
    resolved = rollup or OrderRollup(
        order_count=0, paid_order_count=0, first_order_at=None, last_order_at=None
    )
    return UserListItem(
        id=row.id,
        telegram_user_id=row.telegram_user_id,
        ui_language=row.ui_language,
        is_blocked=row.is_blocked,
        account_created_at=row.created_at,
        first_order_at=resolved.first_order_at,
        last_order_at=resolved.last_order_at,
        order_count=resolved.order_count,
        paid_order_count=resolved.paid_order_count,
        is_profile_present=profile is not None,
        telegram_username=None if profile is None else profile.telegram_username,
        first_name=None if profile is None else profile.first_name,
        last_name=None if profile is None else profile.last_name,
        phone_e164=None if profile is None else profile.phone_e164,
        phone_shared_at=None if profile is None else profile.phone_shared_at,
        avatar_mime=None if profile is None else profile.avatar_mime,
        avatar_stored_at=None if profile is None else profile.avatar_stored_at,
        credit_balance=None if account is None else account.balance,
        lifetime_credits_granted=None if account is None else account.lifetime_granted,
        allowance_period_index=None if account is None else account.allowance_period_index,
    )


async def _rollups(
    session: AsyncSession, telegram_user_ids: Sequence[int]
) -> dict[int, OrderRollup]:
    """Order counts and first/last order instants for a page's users, in one grouped query."""
    if not telegram_user_ids:
        return {}
    statement = (
        sa.select(
            OrderRow.telegram_user_id,
            sa.func.count().label("order_count"),
            count_where(OrderRow.state.in_(_PAID_STATES)).label("paid_order_count"),
            sa.func.min(OrderRow.created_at).label("first_order_at"),
            sa.func.max(OrderRow.created_at).label("last_order_at"),
        )
        .where(OrderRow.telegram_user_id.in_(telegram_user_ids))
        .group_by(OrderRow.telegram_user_id)
    )
    rows = (await session.execute(statement)).all()
    return {
        int(telegram_user_id): OrderRollup(
            order_count=int(order_count),
            paid_order_count=int(paid_order_count),
            first_order_at=first_order_at,
            last_order_at=last_order_at,
        )
        for telegram_user_id, order_count, paid_order_count, first_order_at, last_order_at in rows
    }


async def _orders_by_state(
    session: AsyncSession, telegram_user_id: int
) -> tuple[tuple[OrderState, int], ...]:
    """States this user actually reached, with counts. Absent states stay absent."""
    statement = (
        sa.select(OrderRow.state, sa.func.count().label("total"))
        .where(OrderRow.telegram_user_id == telegram_user_id)
        .group_by(OrderRow.state)
    )
    rows = (await session.execute(statement)).all()
    return tuple(sorted(((state, int(total)) for state, total in rows), key=lambda pair: pair[0]))
