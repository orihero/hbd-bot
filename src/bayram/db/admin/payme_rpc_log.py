"""``payme_rpc_log`` — every inbound call the rail has made to us, and how it was answered.

The third of the rail's read modules (one per table; the ROUTER joins sources, never the data
layer), and the one that will be non-empty FIRST. The gateway daemon already runs on
127.0.0.1:8091 behind a Cloudflare Tunnel while ``CHECKOUT_PROVIDER`` is still unset, so this
journal fills with Payme's checks before a single ``payment_intents`` row exists. "We have
heard from them and nobody has bought anything" is the honest first state of this deployment
and it is legible only from here.

Everything :mod:`bayram.db.admin.plan_purchases` establishes holds: every number is computed by
the database, nothing commits, no clock is read, the session is first and positional, no
``*Row`` escapes, and each function names its index.

**TWO PROPERTIES OF THIS TABLE THAT NO SHARED HELPER MAY ASSUME.**

*It is the only one of the three rail tables with NO* ``TimestampMixin``. There is no
``created_at`` and no ``updated_at``: the row is append-only and ``at`` is the one clock. So a
list helper written against "the three rail tables" cannot window them uniformly, and this
module's cursor is ``(at, id)`` where its siblings' is ``(created_at, id)``.

*The keyset tie-break is NOT index-covered.* ``ix_payme_rpc_log_at`` is a single-column index
and the ``id`` half of the cursor predicate is rechecked in the heap. That is acceptable at 90
days of retention (``PAYME_RPC_LOG_RETENTION_DAYS``) and at the call rate of one merchant
cashbox, and it is the kind of thing that stops being acceptable quietly — so if that constant
is ever raised, this is the read to re-measure, and the fix is a composite ``(at, id)`` index,
not a different pagination scheme.

**SUCCESS AND FAULT ARE TOLD APART BY SIGN.** ``reply_code`` is ``0`` for success and the
JSON-RPC error code otherwise, which is NEGATIVE for every protocol fault. There is
deliberately no second boolean column: a flag beside the code would state a fact the code
already states and would be free to disagree with it. Every predicate here is therefore
``reply_code != 0`` and every count is
:func:`~bayram.db.admin.sql.count_where`, never ``sum(CASE … ELSE 0)``.

**NOTHING IN THIS TABLE IS PERSONAL DATA.** No Telegram id, no request body, no header.
``peer_ip`` is the RAIL's data-centre address and never a customer's — the transport's view of
who called us. That absence is the design and it is what keeps this journal off the retention
and privacy inventories the other two tables are on, which in turn is why these reads carry no
masking branch and sit on the aggregate permission rather than the identified one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from bayram.db.admin.page import (
    BoundedTotal,
    Cursor,
    Page,
    PageRequest,
    bounded_total,
    build_page,
    keyset_order,
    keyset_predicate,
)
from bayram.db.admin.sql import TimeWindow, apply_in, apply_window, count_where
from bayram.db.admin.views import FaultCluster, InboundCall
from bayram.db.models.payme_rpc_log import PaymeRpcLogRow

__all__ = [
    "CallFilters",
    "last_inbound_call",
    "has_recorded_inbound_call",
    "call_totals",
    "fault_clusters",
    "list_calls",
    "count_calls",
    "calls_for_intent",
]


@dataclass(frozen=True, slots=True)
class CallFilters:
    """Everything the journal may be narrowed by. An empty ``methods`` means NO filter.

    :func:`~bayram.db.admin.sql.apply_in`'s asymmetry, and it matters more here than anywhere
    else on this surface: an incident is investigated by clearing filters one at a time, and a
    ``methods=()`` that meant "match none" would empty the table at exactly the moment somebody
    is trying to see everything.

    ``method`` is a plain string and not an enum by the schema's own decision: an UNKNOWN method
    is one of the things this journal exists to record, so a closed type anywhere on the path
    would lose exactly the row an incident needs.
    """

    methods: tuple[str, ...] = ()
    #: ``reply_code != 0``. See the module docstring on why there is no second column.
    faults_only: bool = False
    public_ref: str | None = None
    payme_transaction_id: str | None = None
    window: TimeWindow | None = None


async def last_inbound_call(session: AsyncSession) -> InboundCall | None:
    """The most recent call, whenever it was. **The window is deliberately ignored.**

    This is the rail header's "last heard from Payme" line, and it is evidence rather than a
    status light. A green dot would be a guess wearing the costume of a measurement — this
    process makes NO outbound call and structurally cannot, since it is forbidden the merchant
    key and refuses to boot in production if that variable is reachable. What it can honestly
    say is when they last called US, with the method, the code and their address, and let an
    operator judge.

    Window-blind because the answer is most useful when it is OLD: "nothing for six hours" is
    the signal, and scoping the read to the header's range would replace it with "nothing in
    the last hour", which is a different and much less alarming sentence.

    ``None`` means Payme has never reached this endpoint at all.

    INDEX: ``ix_payme_rpc_log_at``.
    """
    row = (
        await session.execute(
            _projection().order_by(PaymeRpcLogRow.at.desc(), PaymeRpcLogRow.id.desc()).limit(1)
        )
    ).one_or_none()
    return None if row is None else _call(row)


async def has_recorded_inbound_call(session: AsyncSession) -> bool:
    """True once Payme has ever called this endpoint. Window-blind.

    A ROW probe, not a :func:`~bayram.db.admin.sql.has_table` probe — the migration ships with
    the panel, so the table's existence answers nothing. ``False`` is the interesting answer and
    is what the panel must render as "Payme has never reached this endpoint" rather than as an
    empty chart, which reads as a failed fetch.
    """
    probe = await session.scalar(sa.select(sa.literal(1)).select_from(PaymeRpcLogRow).limit(1))
    return probe is not None


async def call_totals(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[int, int]:
    """``(calls, faults)`` over the window, in ONE statement.

    One statement and not two, for the reason every paired count in this package gives: read
    separately, a call landing between them can make faults exceed calls, and a ratio greater
    than one on an incident screen destroys the trust the screen exists to earn.

    The fault arm is :func:`~bayram.db.admin.sql.count_where`, i.e.
    ``count(CASE WHEN … THEN 1 END)``, and never ``sum(CASE … ELSE 0)`` — ``count`` is never
    ``NULL``, so an empty window reads as ``0`` without a ``COALESCE`` anybody can forget.

    INDEX: ``ix_payme_rpc_log_at``. ``reply_code`` carries no index and needs none: the window
    is the selective clause, and a second index on an append-only journal that a five-minute
    sweep writes to is a cost paid on every call for one card's benefit.
    """
    statement: Select[Any] = sa.select(
        sa.func.count().label("calls"),
        count_where(PaymeRpcLogRow.reply_code != 0).label("faults"),
    ).select_from(PaymeRpcLogRow)
    statement = apply_window(statement, PaymeRpcLogRow.at, window)
    row = (await session.execute(statement)).one()
    return (int(row.calls), int(row.faults))


async def fault_clusters(
    session: AsyncSession, *, window: TimeWindow | None = None, limit: int
) -> tuple[FaultCluster, ...]:
    """Failed calls grouped by ``(method, reply_code)``, commonest first.

    The shape an incident is actually read in. Two hundred and forty rows of
    ``CheckTransaction / -31003`` are one fact, and the two instants beside the count are what
    turn it into a diagnosis: the same number spread across a night and packed into eight
    minutes are different incidents with different causes.

    ``slowest_ms`` is a MAX and not a mean, deliberately: a mean over a cluster containing one
    timeout hides the timeout, and the timeout is the row somebody needs to see.

    ``reply_code = 0`` is excluded by construction — success is not a cluster — which is the
    module docstring's sign rule applied at the grouping.

    ``limit`` is required rather than defaulted, so a caller states how much of an unbounded
    grouping it is prepared to render. The route refuses an out-of-range value with a 422
    naming the parameter instead of silently clamping.

    INDEX: ``ix_payme_rpc_log_at`` for the window; the grouping itself is an aggregate over
    the selected rows that no index serves, and is bounded by the number of distinct
    ``(method, reply_code)`` pairs the rail can produce rather than by the table.
    """
    statement: Select[Any] = (
        sa.select(
            PaymeRpcLogRow.method,
            PaymeRpcLogRow.reply_code,
            sa.func.count().label("calls"),
            sa.func.min(PaymeRpcLogRow.at).label("first_at"),
            sa.func.max(PaymeRpcLogRow.at).label("last_at"),
            sa.func.max(PaymeRpcLogRow.duration_ms).label("slowest_ms"),
        )
        .select_from(PaymeRpcLogRow)
        .where(PaymeRpcLogRow.reply_code != 0)
    )
    statement = apply_window(statement, PaymeRpcLogRow.at, window)
    rows = (
        await session.execute(
            statement.group_by(PaymeRpcLogRow.method, PaymeRpcLogRow.reply_code)
            .order_by(sa.func.count().desc(), PaymeRpcLogRow.method, PaymeRpcLogRow.reply_code)
            .limit(limit)
        )
    ).all()
    return tuple(
        FaultCluster(
            method=str(row.method),
            reply_code=int(row.reply_code),
            calls=int(row.calls),
            first_at=row.first_at,
            last_at=row.last_at,
            slowest_ms=int(row.slowest_ms),
        )
        for row in rows
    )


async def list_calls(
    session: AsyncSession, *, filters: CallFilters, request: PageRequest
) -> Page[InboundCall]:
    """One keyset page of the journal, newest first.

    The cursor is ``(at, id)`` and not ``(created_at, id)``: this table has no
    ``TimestampMixin``. See the module docstring on why the tie-break is not index-covered and
    what would make that stop being acceptable.

    INDEX: ``ix_payme_rpc_log_at``.
    """
    statement = _filtered(filters)
    resume = keyset_predicate(PaymeRpcLogRow.at, PaymeRpcLogRow.id, request.cursor)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(*keyset_order(PaymeRpcLogRow.at, PaymeRpcLogRow.id)).limit(
        request.fetch_limit
    )
    rows = (await session.execute(statement)).all()
    return build_page([_call(row) for row in rows], request, _cursor_of)


async def count_calls(session: AsyncSession, *, filters: CallFilters) -> BoundedTotal:
    """``?withTotal=true`` for the journal. Bounded — a busy rail's journal is unbounded.

    Saturating at :data:`~bayram.db.admin.page.TOTAL_COUNT_CAP` is right here in a way it is
    not for a revenue count: nobody reconciles a books figure against the number of health
    checks Payme made, and "10,000+" is exactly what an operator wants to be told.
    """
    return await bounded_total(session, _filtered(filters))


async def calls_for_intent(
    session: AsyncSession, *, public_ref: str, payme_transaction_ids: tuple[str, ...]
) -> tuple[InboundCall, ...]:
    """Every call that named this intent, by either identifier, **oldest first**.

    Two identifiers, OR-ed, because the journal records what each call actually carried: a call
    about an unknown account has ``public_ref`` and no transaction, a perform has both, and a
    call that failed authentication has neither and therefore belongs to no intent at all. A
    query on one column would silently drop half the story.

    Oldest first, matching :func:`bayram.db.admin.payme_transactions.transactions_for_intent`
    and for the same reason: this is a narrative an operator reads forwards.

    **An empty result means two different things and the caller must decide which.** "Payme
    never called us about this" — which is exactly what a force-settled intent looks like, and
    is the answer rather than a gap — or "the 90-day journal has aged out from under a payment
    older than that". The row's own age against ``PAYME_RPC_LOG_RETENTION_DAYS`` is what
    separates them, and the panel must render the second as PURGED rather than as never
    happened. That distinction is not computed here because this function has no clock and no
    business having one.

    ``apply_in`` handles the empty tuple as NO filter, so the ``OR`` degrades to the
    ``public_ref`` arm alone rather than to a predicate that matches nothing — which is exactly
    the case of an intent Payme has never opened a transaction against.

    INDEX: ``ix_payme_rpc_log_public_ref`` and ``ix_payme_rpc_log_payme_transaction_id``.
    """
    matches = PaymeRpcLogRow.public_ref == public_ref
    if payme_transaction_ids:
        matches = sa.or_(matches, PaymeRpcLogRow.payme_transaction_id.in_(payme_transaction_ids))
    rows = (
        await session.execute(
            _projection().where(matches).order_by(PaymeRpcLogRow.at.asc(), PaymeRpcLogRow.id.asc())
        )
    ).all()
    return tuple(_call(row) for row in rows)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _projection() -> Select[Any]:
    """The journal's columns, spelled once. Every column; the row has nothing to withhold."""
    return sa.select(
        PaymeRpcLogRow.id,
        PaymeRpcLogRow.at,
        PaymeRpcLogRow.method,
        PaymeRpcLogRow.public_ref,
        PaymeRpcLogRow.payme_transaction_id,
        PaymeRpcLogRow.reply_code,
        PaymeRpcLogRow.peer_ip,
        PaymeRpcLogRow.duration_ms,
    ).select_from(PaymeRpcLogRow)


def _filtered(filters: CallFilters) -> Select[Any]:
    """:func:`_projection` narrowed by every filter the caller supplied."""
    statement = apply_in(_projection(), PaymeRpcLogRow.method, filters.methods)
    if filters.faults_only:
        statement = statement.where(PaymeRpcLogRow.reply_code != 0)
    if filters.public_ref is not None:
        statement = statement.where(PaymeRpcLogRow.public_ref == filters.public_ref)
    if filters.payme_transaction_id is not None:
        statement = statement.where(
            PaymeRpcLogRow.payme_transaction_id == filters.payme_transaction_id
        )
    return apply_window(statement, PaymeRpcLogRow.at, filters.window)


def _cursor_of(item: InboundCall) -> Cursor:
    return Cursor(at=item.at, id=item.id)


def _call(row: Any) -> InboundCall:
    return InboundCall(
        id=row.id,
        at=row.at,
        method=str(row.method),
        public_ref=None if row.public_ref is None else str(row.public_ref),
        payme_transaction_id=(
            None if row.payme_transaction_id is None else str(row.payme_transaction_id)
        ),
        reply_code=int(row.reply_code),
        peer_ip=None if row.peer_ip is None else str(row.peer_ip),
        duration_ms=int(row.duration_ms),
    )
