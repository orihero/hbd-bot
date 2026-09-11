"""``/broadcasts`` — the campaign list, one campaign, and the ledger of who it reached.

**One row per CAMPAIGN, never one per recipient.** That is the whole shape of this module
and the mistake it exists to make impossible: the sidebar screen lists the handful of
campaigns a deployment has composed, while ``broadcast_recipients`` is the largest table in
the schema and is paged only ever *inside* one campaign. So there are two lists here with
two filter sets and two counts, sharing nothing but the keyset helpers — a single list that
took an optional ``broadcast_id`` would be one forgotten parameter away from paging forty
thousand rows onto the campaigns screen.

**Nothing is re-evaluated. THE AUDIENCE IS FROZEN AT CREATION** (``BROADCAST_SPEC §2.1``),
and this module is a reader of that promise rather than a second implementation of it: the
recipient rows were materialised when the campaign was created, so "who is in this campaign"
is a ``SELECT`` over those rows and never a recompilation of ``broadcasts.segment``. The
stored document travels on :class:`~bayram.db.admin.views.BroadcastDetail` verbatim, because a
recompiled segment answers "who would match NOW" — a different question, and on a campaign
that has already gone out a misleading one. :mod:`bayram.db.admin.segment` is therefore
deliberately not imported here; it is the *writer's* dependency (the creation path counts
the audience with ``users.count_segment_exactly`` and freezes it), not the reader's.

**Two sources for the same six numbers, and both are published on purpose.** ``broadcasts``
carries denormalised counters the worker's rollup writes; :func:`broadcast_progress` counts
the recipient rows themselves. The list renders the former because a ``GROUP BY`` per row
over the recipient table is the N+1 this layer never ships, and the detail renders the
latter because an operator watching a send must see the ledger and not a summary a crashed
rollup has not caught up with. Where they disagree, the rows are right — the same argument
``credit_accounts.balance`` beside ``SUM(credit_ledger.delta)`` is kept for.

**What crosses, and under whose authority.** :class:`~bayram.db.admin.views.BroadcastRecipientItem`
carries a Telegram id, which makes this the third read in ``bayram.db.admin`` that names a
person — ``audience_lists`` makes the argument in full and it is not restated here: the
account holder's id is what ``GET /api/users`` already publishes, served on ``RECORDS_READ``
with an audit row as the control. This module widens that by nothing. No handle, no first
name, no phone number, and no per-recipient copy of the message; the reveal machinery is
untouched. An erased row (``telegram_user_id IS NULL`` after ``/forget``) is RENDERED with
its id gone rather than filtered away, for ``audience_lists``' reason: a delivery record that
vanished because somebody exercised a right takes "was this person sent that campaign?" away
from every other row too.

No relationship is ever traversed — every model in this schema is ``lazy="raise"``, so an
accidental ``broadcast.bodies`` would surface as a greenlet error at an unrelated await. The
detail issues its own three statements instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from bayram.contracts import BroadcastKind, BroadcastRecipientState, BroadcastState, Language
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
from bayram.db.admin.sql import TimeWindow, apply_in, apply_search, apply_window
from bayram.db.admin.views import (
    BroadcastBodyView,
    BroadcastDetail,
    BroadcastListItem,
    BroadcastProgress,
    BroadcastRecipientItem,
)
from bayram.db.models.broadcast import BroadcastRow
from bayram.db.models.broadcast_body import BroadcastBodyRow
from bayram.db.models.broadcast_recipient import BroadcastRecipientRow

__all__ = [
    "BroadcastFilters",
    "RecipientFilters",
    "list_broadcasts",
    "count_broadcasts",
    "get_broadcast",
    "list_recipients",
    "count_recipients",
    "broadcast_progress",
    "broadcast_list_item",
    "broadcast_body_view",
    "recipient_item",
]

#: How many language bodies are composed for a campaign. A correlated ``COUNT`` rather than a
#: join, for the reason ``orders._ASSET_COUNT`` gives: a join to a one-to-many child would
#: multiply the page's rows, and a keyset ``LIMIT`` over multiplied rows is a page that drops
#: campaigns. ``bodies`` has at most one row per language, so this is an index probe on
#: ``uq_broadcast_bodies_broadcast_id_language`` per row of a list that gains a few rows a week.
_BODY_COUNT: Final[sa.ScalarSelect[int]] = (
    sa.select(sa.func.count())
    .select_from(BroadcastBodyRow)
    .where(BroadcastBodyRow.broadcast_id == BroadcastRow.id)
    .correlate(BroadcastRow)
    .scalar_subquery()
)

#: What ``?q=`` may substring-match on the campaign list, and the boundary is the same
#: privacy decision the other lists make rather than a convenience one. The title is
#: operator-authored, is printed in full in every row of the same response, and is NEVER sent
#: to a customer — the message itself is in ``broadcast_bodies``. So matching a substring of
#: it discloses nothing the caller was not already handed.
#:
#: ``broadcast_bodies.text`` is deliberately absent. It is a body an operator wrote and not a
#: customer's words, so the refusal is not a privacy one: a ``LIKE`` over a child table would
#: have to be an ``EXISTS`` whose rows the list cannot show, so ``q=sale`` would return
#: campaigns with no visible reason for being there. Searching what is on the screen is the
#: rule; the body is on the detail.
_SEARCHABLE_COLUMNS: Final[tuple[sa.SQLColumnExpression[str], ...]] = (BroadcastRow.title,)


@dataclass(frozen=True, slots=True)
class BroadcastFilters:
    """The campaign list's filter set. Repeated values are OR within a field, AND across."""

    states: tuple[BroadcastState, ...] = ()
    kinds: tuple[BroadcastKind, ...] = ()
    #: Applied to ``broadcasts.created_at`` — when the campaign was COMPOSED, half-open.
    #: Deliberately not ``scheduled_for``: a window on a nullable column would silently drop
    #: every immediate campaign from a range an operator believes covers everything.
    window: TimeWindow | None = None
    #: Substring over :data:`_SEARCHABLE_COLUMNS`. Blank or ``None`` means no filter, never
    #: an empty page — :func:`~bayram.db.admin.sql.search_clause`'s asymmetry.
    search: str | None = None


@dataclass(frozen=True, slots=True)
class RecipientFilters:
    """The recipient ledger's filter set, applied INSIDE one campaign.

    There is no window here and that is deliberate: every row of one campaign was written by
    one expansion within minutes of itself, so a date range narrows nothing an operator would
    ask for. What they do ask is "show me the failures" and "did this person get it", which
    is :attr:`states` and :attr:`telegram_user_id`.
    """

    states: tuple[BroadcastRecipientState, ...] = ()
    #: The account's language AT EXPANSION, which is the body it was sent — not its language
    #: today. See ``BroadcastRecipientRow.language``.
    languages: tuple[Language, ...] = ()
    #: Exact, and the first question of any complaint. An erased row matches nothing here,
    #: because ``/forget`` took the id; it is still listed by an unfiltered read.
    telegram_user_id: int | None = None


async def list_broadcasts(
    session: AsyncSession, *, filters: BroadcastFilters, request: PageRequest
) -> Page[BroadcastListItem]:
    """One keyset page of campaigns, newest composed first. One row per campaign.

    ``(created_at, id)`` descending, the ordering every list in this package defaults to and
    the only one this list has: a campaign screen is short, is read top-down, and a sort key
    that is not carried in the cursor cannot be resumed — the sorted walk in
    ``db/admin/users.py`` exists because a segment's registry offers keys to sort by, and
    nothing here does.
    """
    statement = _filtered(filters)
    resume = keyset_predicate(BroadcastRow.created_at, BroadcastRow.id, request.cursor)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(*keyset_order(BroadcastRow.created_at, BroadcastRow.id)).limit(
        request.fetch_limit
    )
    rows = (await session.execute(statement)).all()
    items = [broadcast_list_item(row, body_count=body_count) for row, body_count in rows]
    return build_page(items, request, _cursor_of)


async def count_broadcasts(session: AsyncSession, *, filters: BroadcastFilters) -> BoundedTotal:
    """``?withTotal=true`` for the same filter set. Bounded — see :func:`bounded_total`.

    Bounded even though this table gains a handful of rows a week, because the cap is what
    makes the count's cost independent of the table it counts, and a list total that
    saturates at ten thousand campaigns is a deployment nobody is paging through by hand
    anyway. The number an operator authorises a SEND against is a different one and is never
    this: that is ``users.count_segment_exactly``, exact by construction.
    """
    return await bounded_total(session, _filtered(filters))


async def get_broadcast(session: AsyncSession, broadcast_id: UUID) -> BroadcastDetail | None:
    """The campaign, its composed bodies and the progress its recipient rows report.

    ``None`` for an unknown id — the caller answers 404. Three statements rather than one
    join: the bodies are one row per language and the progress is a grouped count over a
    table with tens of thousands of rows for this campaign, so joining either to the campaign
    row would produce a shape Python has to un-multiply.

    The progress is recomputed from ``broadcast_recipients`` while the row's own counters
    travel beside it on :attr:`~bayram.db.admin.views.BroadcastDetail.broadcast` — both, on
    purpose, for the reason the module docstring gives.
    """
    row = (
        await session.execute(_filtered(BroadcastFilters()).where(BroadcastRow.id == broadcast_id))
    ).first()
    if row is None:
        return None
    broadcast, body_count = row
    return BroadcastDetail(
        broadcast=broadcast_list_item(broadcast, body_count=body_count),
        bodies=await _load_bodies(session, broadcast_id),
        segment=broadcast.segment,
        progress=await broadcast_progress(session, broadcast_id),
    )


async def list_recipients(
    session: AsyncSession,
    broadcast_id: UUID,
    *,
    filters: RecipientFilters,
    request: PageRequest,
) -> Page[BroadcastRecipientItem]:
    """One keyset page of one campaign's recipient rows, newest first.

    ``broadcast_id`` is positional and required, which is the point: there is no reading of
    this table across campaigns, so the narrowing that keeps the largest table in the schema
    bounded cannot be left out by forgetting a keyword.

    The keyset is ``(created_at, id)`` like every other list, and it is a total order here
    even though a chunked expansion writes thousands of rows sharing one instant — that is
    exactly what the primary-key tie-break is for. The scan is served by
    ``ix_broadcast_recipients_broadcast_id_state`` when ``states`` narrows it, which is the
    filter an operator reaches for ("show me the failures"), and by the campaign predicate
    alone otherwise.
    """
    statement = _recipients_filtered(broadcast_id, filters)
    resume = keyset_predicate(
        BroadcastRecipientRow.created_at, BroadcastRecipientRow.id, request.cursor
    )
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(
        *keyset_order(BroadcastRecipientRow.created_at, BroadcastRecipientRow.id)
    ).limit(request.fetch_limit)
    rows = (await session.execute(statement)).scalars().all()
    items = [recipient_item(row) for row in rows]
    return build_page(items, request, _recipient_cursor_of)


async def count_recipients(
    session: AsyncSession, broadcast_id: UUID, *, filters: RecipientFilters
) -> BoundedTotal:
    """``?withTotal=true`` for one campaign's ledger under the same filters. Bounded.

    Bounded rather than exact because it answers "how long is this list", and a forty-thousand
    row campaign is precisely where the unbounded version would cost the most for the least.
    The exact numbers this screen actually reports — how many sent, failed, blocked — are
    :func:`broadcast_progress`, which is one grouped index scan and never saturates.
    """
    return await bounded_total(session, _recipients_filtered(broadcast_id, filters))


async def broadcast_progress(session: AsyncSession, broadcast_id: UUID) -> BroadcastProgress:
    """Per-state counters for one campaign, counted from the recipient rows. Exact, zero-filled.

    **Not bounded and not sampled.** ``bounded_total``'s ``LIMIT`` trick cannot be borrowed
    here for ``count_orders_by_state``'s reason: an arbitrary ten thousand rows have an
    arbitrary distribution, so a progress bar drawn from them would be differently wrong with
    no way to see that it was. One ``GROUP BY`` over ``ix_broadcast_recipients_broadcast_id_state``
    is what it costs, and the index exists for exactly this query and the chunk claim beside it.

    Every state is reported, always, including the ones with no rows — a bar whose segments do
    not appear from nowhere under an operator's cursor while they watch a send. A campaign
    with no recipient rows, and an id that belongs to no campaign, both report seven zeros:
    existence is :func:`get_broadcast`'s answer to give, not this function's.
    """
    statement = (
        sa.select(BroadcastRecipientRow.state, sa.func.count())
        .where(BroadcastRecipientRow.broadcast_id == broadcast_id)
        .group_by(BroadcastRecipientRow.state)
    )
    counted = {state: int(total) for state, total in (await session.execute(statement)).all()}
    return BroadcastProgress(
        pending=counted.get(BroadcastRecipientState.PENDING, 0),
        sending=counted.get(BroadcastRecipientState.SENDING, 0),
        sent=counted.get(BroadcastRecipientState.SENT, 0),
        failed=counted.get(BroadcastRecipientState.FAILED, 0),
        skipped_blocked=counted.get(BroadcastRecipientState.SKIPPED_BLOCKED, 0),
        undeliverable=counted.get(BroadcastRecipientState.UNDELIVERABLE, 0),
        unknown=counted.get(BroadcastRecipientState.UNKNOWN, 0),
    )


# ---------------------------------------------------------------------------
# Row -> view model. Pure.
# ---------------------------------------------------------------------------
def broadcast_list_item(row: BroadcastRow, *, body_count: int) -> BroadcastListItem:
    """Build a campaign row. ``body_count`` is keyword-only: it is a bare integer beside six
    other bare integers, and positionally a transposition is a bug every fixture with equal
    counts would wave through."""
    return BroadcastListItem(
        id=row.id,
        title=row.title,
        kind=row.kind,
        state=row.state,
        segment_hash=row.segment_hash,
        audience_size=row.audience_size,
        audience_evaluated_at=row.audience_evaluated_at,
        recipient_count=row.recipient_count,
        sent_count=row.sent_count,
        failed_count=row.failed_count,
        skipped_count=row.skipped_count,
        undeliverable_count=row.undeliverable_count,
        unknown_count=row.unknown_count,
        scheduled_for=row.scheduled_for,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_by_admin_id=row.created_by_admin_id,
        created_by_username=row.created_by_username,
        scheduled_by_admin_id=row.scheduled_by_admin_id,
        scheduled_by_username=row.scheduled_by_username,
        reason_code=row.reason_code,
        reason_ref=row.reason_ref,
        error_code=row.error_code,
        body_count=body_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def broadcast_body_view(row: BroadcastBodyRow) -> BroadcastBodyView:
    """Build one language's body. The cached ``media_file_id`` crosses as a boolean only."""
    return BroadcastBodyView(
        id=row.id,
        broadcast_id=row.broadcast_id,
        language=row.language,
        text=row.text,
        media_storage_key=row.media_storage_key,
        has_media_file_id=row.media_file_id is not None,
        button_label=row.button_label,
        button_url=row.button_url,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def recipient_item(row: BroadcastRecipientRow) -> BroadcastRecipientItem:
    """Build one ledger row. An erased row is rendered, with its id ``None``."""
    return BroadcastRecipientItem(
        id=row.id,
        broadcast_id=row.broadcast_id,
        telegram_user_id=row.telegram_user_id,
        language=row.language,
        state=row.state,
        attempts=row.attempts,
        error_code=row.error_code,
        settled_at=row.settled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _filtered(filters: BroadcastFilters) -> Select[tuple[BroadcastRow, int]]:
    """The shared ``FROM``/``WHERE`` every campaign query starts from, keyset excluded.

    The body count rides in the ``SELECT`` list rather than the ``WHERE``, which is why
    :func:`count_broadcasts` does not pay for it: ``bounded_total`` replaces the column list
    with ``literal(1)`` and the correlated subquery goes with it. The search predicate, by
    contrast, is a ``WHERE`` clause and narrows both — which it must, or ``?withTotal=true``
    would label a two-row page with the unfiltered count.
    """
    statement = sa.select(BroadcastRow, _BODY_COUNT.label("body_count"))
    statement = apply_in(statement, BroadcastRow.state, filters.states)
    statement = apply_in(statement, BroadcastRow.kind, filters.kinds)
    statement = apply_window(statement, BroadcastRow.created_at, filters.window)
    return apply_search(statement, filters.search, _SEARCHABLE_COLUMNS)


def _recipients_filtered(
    broadcast_id: UUID, filters: RecipientFilters
) -> Select[tuple[BroadcastRecipientRow]]:
    """One campaign's ledger, narrowed. The campaign predicate is applied FIRST and always.

    Shared by the page and its count so the two cannot describe different populations, and
    written so that no path through it can omit ``broadcast_id`` — the filters are optional,
    the campaign is not.
    """
    statement = sa.select(BroadcastRecipientRow).where(
        BroadcastRecipientRow.broadcast_id == broadcast_id
    )
    statement = apply_in(statement, BroadcastRecipientRow.state, filters.states)
    statement = apply_in(statement, BroadcastRecipientRow.language, filters.languages)
    if filters.telegram_user_id is not None:
        statement = statement.where(
            BroadcastRecipientRow.telegram_user_id == filters.telegram_user_id
        )
    return statement


async def _load_bodies(session: AsyncSession, broadcast_id: UUID) -> tuple[BroadcastBodyView, ...]:
    """Every composed body for one campaign, ordered by language so two reads compare equal."""
    rows = (
        (
            await session.execute(
                sa.select(BroadcastBodyRow)
                .where(BroadcastBodyRow.broadcast_id == broadcast_id)
                .order_by(BroadcastBodyRow.language)
            )
        )
        .scalars()
        .all()
    )
    return tuple(broadcast_body_view(row) for row in rows)


def _cursor_of(item: BroadcastListItem) -> Cursor:
    return Cursor(at=item.created_at, id=item.id)


def _recipient_cursor_of(item: BroadcastRecipientItem) -> Cursor:
    return Cursor(at=item.created_at, id=item.id)
