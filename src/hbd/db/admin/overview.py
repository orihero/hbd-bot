"""The account population — how many there are, how many are reachable, how many left.

These aggregates have no home in :mod:`hbd.db.admin.users`, and the split is deliberate
rather than alphabetical. That module is the per-ROW layer: a keyset list, one detail, and
``_rollups`` that describe the fifty accounts a page happens to hold. Everything here is a
count over the whole table or over a cutoff, it returns no row and no identifier, and it is
read under DASHBOARD_READ rather than RECORDS_READ. A function that answers "how many
accounts exist" living beside one that answers "who are they" is how a dashboard ends up
holding a permission it does not need.

**Every number is computed by the database.** The standing rule of
:mod:`hbd.db.admin.metrics` holds without exception; nothing here fetches rows and folds
them in Python.

**No ``telegram_user_id`` leaves this module.** Only counts of them. That is what lets the
whole audience surface sit on DASHBOARD_READ with no masking branch, no reveal gate and no
unmasked variant of any response — the same statement ``vendor_usage.py`` makes about its
own columns, restated here because this module reads the one table that holds identifiers.

**The active-accounts predicate is what earns the index, and it must not be simplified
away.** :func:`active_accounts` narrows to ``last_seen_at >= now - 30d`` FIRST and takes the
seven- and one-day cutoffs as conditional counts inside that range. The obvious refactor —
three bare :func:`~hbd.db.admin.sql.count_where` cutoffs and no ``WHERE`` at all — has no
predicate, so it scans ``users`` end to end no matter what is indexed, and
``ix_users_last_seen_at`` becomes pure write cost on the hottest-written column in the
schema. That is precisely the failure migration 0009's docstring is a post-mortem of. The
thirty-day bound also costs nothing: a "monthly active" count is by definition bounded by
the monthly cutoff.

**``now`` is a parameter, never a call**, per :mod:`hbd.admin.window`'s rule. Routers read
``utc_now()`` from their own module globals so a test can move one router's clock; a helper
that read the clock itself would move the window out from under the only mechanism this
package has for shifting time.

**The live gauge and the recorded series are two reads and stay two reads.**
:func:`active_accounts` counts against a cutoff and answers from the first minute of a
deployment; :func:`activity_history` reads ``user_activity_snapshots``, which begins the
first night the job ran and cannot be back-filled because the column it would be
reconstructed from is a gauge that was overwritten. Merging them would put a fabricated
past under a perfectly good present, and :func:`has_recorded_activity_history` exists so a
panel can say which of the two it is looking at.

**Two kinds of "cannot be reached" are two numbers and never a sum.** ``users.is_blocked``
is the OPERATOR's bar; ``users.blocked_bot_at`` is the CUSTOMER's, written from
``my_chat_member`` and from a delivery refusal. An account can be both, so adding them
double-counts, and the remedies differ — one is a decision somebody here made and can undo,
the other is a decision the customer made and cannot be undone from this side.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from hbd.contracts import BotMembershipEvent, Language
from hbd.db.admin.sql import (
    SeriesGrain,
    TimeWindow,
    apply_window,
    bucket_expression,
    bucket_started_at,
    count_pair,
    count_where,
    previous_window,
    spanning_window,
)
from hbd.db.admin.views import (
    AccountTotals,
    ActiveAccounts,
    ActivityPoint,
    ChurnCounts,
    LanguageMix,
    LanguageMixTotals,
    NewAccountsPerBucket,
    Trend,
)
from hbd.db.models.bot_membership_event import BotMembershipEventRow
from hbd.db.models.user import UserRow
from hbd.db.models.user_activity_snapshot import UserActivitySnapshotRow

__all__ = [
    "ACTIVE_WINDOW_DAYS",
    "account_totals",
    "active_accounts",
    "new_accounts",
    "new_accounts_per_bucket",
    "language_mix",
    "activity_history",
    "churn_counts",
    "has_recorded_churn",
    "has_recorded_activity_history",
]

#: The DAU / WAU / MAU cutoffs, in days, widest LAST. Named as a triple rather than written
#: as three literals at three call sites so the three cannot be transposed, and named here
#: rather than in ``Settings`` because these are the definition of the metric and not a knob:
#: an operator who moved "weekly active" to nine days would have a number nobody else's
#: dashboard means, and the snapshot rows already written under the old definition would
#: silently join the series under the new one.
ACTIVE_WINDOW_DAYS: Final[tuple[int, int, int]] = (1, 7, 30)


async def account_totals(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> AccountTotals:
    """Every account, the operator-blocked, the customer-blocked, and the total's trend.

    Two round trips and not four. The three population counts ride in ONE statement with no
    ``WHERE`` clause, because two of them are conditional counts over the same rows the
    first has to visit anyway: separate queries would be three scans of one table for three
    numbers that sit beside each other on one card. The trend is a second statement because
    it has a different predicate — the sign-up window — and cannot share the scan.

    **This one scans ``users``, deliberately.** "How many accounts exist" admits no
    predicate that could narrow it, and the partial index on ``is_blocked`` that would speed
    the second column is refused: folding that count into a scan that was happening anyway
    costs nothing, and a partial index on a boolean would have to justify itself against
    ``credits.set_blocked``'s write path.

    **It must never route through** :func:`~hbd.db.admin.page.bounded_total`. That helper
    saturates at ``TOTAL_COUNT_CAP`` (10 000) because a LIST needs to know "more than a
    page's worth" and not the exact figure. Here the exact figure IS the metric, and a hero
    Audience tile reading "10 000+" for ever from the day this deployment crosses ten
    thousand accounts would freeze the one number a founder most wants to watch cross.

    INDEX: none, and none would help — see above. The trend rides ``ix_users_created_at``.
    """
    totals: Select[tuple[int, int, int]] = sa.select(
        sa.func.count().label("total"),
        count_where(UserRow.is_blocked.is_(True)).label("blocked"),
        count_where(UserRow.blocked_bot_at.is_not(None)).label("bot_blocked"),
    ).select_from(UserRow)
    row = (await session.execute(totals)).one()
    return AccountTotals(
        total=int(row.total),
        blocked=int(row.blocked),
        bot_blocked=int(row.bot_blocked),
        total_trend=await new_accounts(session, window=window),
    )


async def active_accounts(session: AsyncSession, *, now: datetime) -> ActiveAccounts:
    """DAU / WAU / MAU in one query, narrowed to the widest cutoff first.

    Nested by construction: every account counted in ``day`` is also counted in ``week`` and
    ``month``, because the three are cutoffs against one column rather than three disjoint
    buckets. The caller renders them as three tiles, never as a stacked bar.

    The ``WHERE`` clause is load-bearing and not cosmetic — see the module docstring. It is
    also the honest bound: the widest number this function reports IS the monthly cutoff, so
    narrowing to it discards nothing.

    ``last_seen_at`` is read here as an AGGREGATE and only as an aggregate. The column is
    deliberately withheld from every per-row ``/users`` projection so an operator cannot
    watch one customer minute by minute, and indexing it for this count is not permission to
    expose it.

    INDEX: ``ix_users_last_seen_at``, a range scan over the active tail.
    """
    day_days, week_days, month_days = ACTIVE_WINDOW_DAYS
    statement: Select[tuple[int, int, int]] = (
        sa.select(
            sa.func.count().label("month"),
            count_where(UserRow.last_seen_at >= now - timedelta(days=week_days)).label("week"),
            count_where(UserRow.last_seen_at >= now - timedelta(days=day_days)).label("day"),
        )
        .select_from(UserRow)
        .where(UserRow.last_seen_at >= now - timedelta(days=month_days))
    )
    row = (await session.execute(statement)).one()
    return ActiveAccounts(day=int(row.day), week=int(row.week), month=int(row.month), as_of=now)


async def new_accounts(session: AsyncSession, *, window: TimeWindow | None = None) -> Trend:
    """Accounts created in the window, and in the equal-length window before it.

    One index range scan for both numbers — see :func:`~hbd.db.admin.sql.count_pair`.
    ``previous`` is ``None`` when the caller gave no lower bound, because a range with no
    beginning has no length to step back by, and a zero there would read as "the preceding
    period was measured and nobody signed up".

    INDEX: ``ix_users_created_at``, which has existed since revision 0001 by way of
    ``TimestampMixin``.
    """
    return await _trend(session, UserRow.created_at, UserRow, window=window)


async def new_accounts_per_bucket(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    grain: SeriesGrain = SeriesGrain.DAY,
) -> tuple[NewAccountsPerBucket, ...]:
    """Sign-ups per UTC bucket, oldest first. Buckets with no sign-up are ABSENT.

    Absent rather than zero-filled, for the standing reason: this layer does not know what
    range the caller wants charted — both bounds are optional — so a filled bucket before
    the first row would claim "0 sign-ups" for days this deployment did not exist on. The
    API layer, which knows the requested range, decides what an asked-about gap renders as.

    INDEX: ``ix_users_created_at``.
    """
    bucket = bucket_expression(grain, UserRow.created_at)
    statement: Select[tuple[str, int]] = sa.select(
        bucket.label("bucket"), sa.func.count().label("signups")
    ).select_from(UserRow)
    statement = apply_window(statement, UserRow.created_at, window)
    rows = (await session.execute(statement.group_by(bucket).order_by(bucket))).all()
    return tuple(
        NewAccountsPerBucket(
            bucket=str(key), started_at=bucket_started_at(grain, str(key)), count=int(count)
        )
        for key, count in rows
    )


async def language_mix(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> LanguageMixTotals:
    """Accounts per ``users.ui_language``, largest first, with the denominator beside them.

    ONE ``GROUP BY``, and it answers a narrower question than a pie chart labelled "language"
    implies. The column is ``NOT NULL`` with a column default that
    :data:`~hbd.db.users_sql.DEFAULT_UI_LANGUAGE` is pinned to, so every account lands in
    exactly one entry and there is no unknown bucket to invent — **but a row holding the
    default is not the same fact as a row holding a choice, and this read cannot tell them
    apart.** ``ensure_user`` refreshes ``ui_language`` only for a writer that passes
    ``is_language_authoritative``; an account first seen through an order, a top-up or
    ``churn.mark_bot_blocked`` takes the default because nobody knew the answer, and nothing
    in the row records which of the two put the value there. The ``UZ_LATN`` entry therefore
    over-counts *choice* by however many accounts arrived that way. What the number is
    exactly is what the bot WILL SPEAK to each account — the operational question — and it
    is not a survey result. A ``chose_language`` timestamp would separate the two and does
    not exist; adding one is a schema decision, not something this read can work around.

    **This is the INTERFACE language, never the song's.** ``briefs.output_language`` is what
    gets sung, the two are chosen independently, and a customer driving the bot in Russian
    while ordering in Uzbek Latin is ordinary rather than exceptional.

    **A language no account holds is ABSENT, and the reason is presentational rather than
    the null-never-zero rule.** Be precise about which rule is doing the work: because
    ``ui_language`` is ``NOT NULL`` over a population this statement visits in full, "no
    account reads the bot in English" really *has* been measured, so a zero here would be a
    true number and not a fabricated one — unlike the gaps in :func:`activity_history`. It
    is left out because this shape is a share list ordered by size, where a zero entry
    carries a 0% slice and a legend row for a language nobody reads, and not a fixed-slot
    bar like :func:`~hbd.db.admin.orders.order_state_totals`, which zero-fills precisely so
    its segments do not re-lay-out under the operator's cursor. A caller that wants fixed
    slots can fill them from :class:`~hbd.contracts.Language` itself, because
    :attr:`~hbd.db.admin.views.LanguageMixTotals.accounts` travels with the entries and a
    reconstructed denominator is exactly what that field exists to make unnecessary.

    **``window`` narrows by ``users.created_at``** — the mix among accounts that SIGNED UP in
    the range, which is the only windowing this table can support and is not the mix that was
    on screen during it. ``ui_language`` is a gauge with no history: a customer who switches
    to Russian rewrites their only row and the previous value is gone. So a window over a
    distant month reports what those accounts read in TODAY, and the honest reading of a
    windowed call is "the cohort that joined then, as they are now".

    The total is summed in Python over rows the database has already grouped — at most one
    per :class:`~hbd.contracts.Language` member, four of them today — which is the same
    licence :func:`~hbd.db.admin.metrics.failure_breakdown` takes for its shares. It is not a
    second ``COUNT``, deliberately: a separately queried total could disagree with the
    entries it is the denominator of if a row were inserted between the two statements.

    Ties break on the stored language value, which is byte-identical on both dialects because
    :func:`~hbd.db.base.enum_type` builds a ``VARCHAR`` and never a native enum — so two
    languages with equal counts come back in the same order from Postgres and from SQLite,
    and a caller may compare a whole tuple.

    INDEX: ``ix_users_created_at`` when a window narrows it; none otherwise, and none is
    wanted. An unwindowed mix visits every account by definition, and an index on a
    four-valued column is a scan the planner would decline anyway while charging
    ``ensure_user``'s upsert path for the privilege of maintaining it.
    """
    accounts = sa.func.count()
    statement: Select[tuple[Language, int]] = sa.select(
        UserRow.ui_language, accounts.label("accounts")
    ).select_from(UserRow)
    statement = apply_window(statement, UserRow.created_at, window)
    rows = (
        await session.execute(
            statement.group_by(UserRow.ui_language).order_by(accounts.desc(), UserRow.ui_language)
        )
    ).all()
    languages = tuple(
        LanguageMix(language=language, accounts=int(count)) for language, count in rows
    )
    return LanguageMixTotals(
        languages=languages, accounts=sum(entry.accounts for entry in languages)
    )


async def activity_history(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    grain: SeriesGrain = SeriesGrain.DAY,
) -> tuple[ActivityPoint, ...]:
    """The recorded DAU / WAU / MAU series, oldest first. A night with no sample is ABSENT.

    The history of :func:`active_accounts`'s three tiles, read from
    ``user_activity_snapshots`` — the only reader of that table other than the existence
    probe in :func:`has_recorded_activity_history`. The three counts stay NESTED cutoffs on
    one population (``day ⊆ week ⊆ month``, all three from one ``last_seen_at`` predicate
    evaluated at one instant), so they are three lines and never a stack: summing them
    triple-counts everybody active today and produces a top line no query can reproduce.

    **A day the job did not run is missing from this tuple and is never a zero.** This is the
    null-never-zero rule applied to a SERIES: a zero-filled night would state that nobody
    used the bot, which is a fabricated measurement wearing a chart line, and the values that
    would have answered it are gone — ``users.last_seen_at`` is UPSERTed in place, so there
    is no back-fill, no estimate from ``users.created_at`` and no seeding migration, at any
    later date. This layer also does not know what range the caller wants drawn (both bounds
    are optional, exactly as in :func:`new_accounts_per_bucket`), so **the API layer, which
    knows the requested range, decides what an asked-about gap renders as** — a break in the
    line, a dashed segment, or nothing at all. Note the first thirty days of any deployment
    for a different reason: ``active_30d_accounts`` is bounded by deployment age there, a
    ramp that looks like growth and is not.

    **It buckets but does not ``GROUP BY``, and that is not an oversight.** The job files
    each sample under ``taken_at.date()`` and ``snapshot_date`` is ``UNIQUE``, so there is at
    most one row per UTC day already, and an hourly key is strictly finer than a daily one.
    Every group would therefore be a singleton, and the aggregate a ``GROUP BY`` would demand
    is the danger rather than the cost: ``max()`` over the three counts independently could
    take ``day`` from one sample and ``month`` from another, breaking the nesting the shape
    promises. One row IS one point, so the bucket key is computed for it and nothing is
    folded. ``HOUR`` grain is honest and nearly pointless — the same nightly samples under
    finer keys, never an interpolation between them — and it is accepted rather than refused
    so a caller can render this series against an hourly one without a special case.

    **The window is applied to ``taken_at``, not to ``snapshot_date``**, though the latter is
    the indexed column. A :class:`~hbd.db.admin.sql.TimeWindow` bound is an instant, and
    comparing one to a ``DATE`` means a cast that Postgres resolves through the *session*
    ``TimeZone`` — the identical trap :class:`~hbd.db.admin.sql.UtcDay` exists to close, and
    it would drop or admit the boundary day on a server set to ``Asia/Tashkent``. The two
    agree in any case: ``snapshot_date`` is defined as the UTC day of ``taken_at``, which
    ``tests/test_db/test_activity_snapshots.py`` pins.

    INDEX: none, and none is wanted. ``taken_at`` is unindexed and the unique index on
    ``snapshot_date`` cannot serve a predicate on it, so this scans the table — which grows
    by one row a night, 3 650 in a decade, and is deliberately never swept. An index on a
    table that will not reach five figures in the lifetime of this deployment would be
    ceremony charged to the nightly writer.
    """
    bucket = bucket_expression(grain, UserActivitySnapshotRow.taken_at)
    statement: Select[tuple[str, int, int, int]] = sa.select(
        bucket.label("bucket"),
        UserActivitySnapshotRow.active_24h_accounts.label("day"),
        UserActivitySnapshotRow.active_7d_accounts.label("week"),
        UserActivitySnapshotRow.active_30d_accounts.label("month"),
    ).select_from(UserActivitySnapshotRow)
    statement = apply_window(statement, UserActivitySnapshotRow.taken_at, window)
    rows = (await session.execute(statement.order_by(bucket))).all()
    return tuple(
        ActivityPoint(
            bucket=str(key),
            started_at=bucket_started_at(grain, str(key)),
            day=int(day),
            week=int(week),
            month=int(month),
        )
        for key, day, week, month in rows
    )


async def churn_counts(session: AsyncSession, *, window: TimeWindow | None = None) -> ChurnCounts:
    """Customers who blocked the bot in the window, and those who unblocked it.

    Read from ``bot_membership_events``, which records PASSAGES and not states, so someone
    who left and came back inside one window is counted in both numbers. That is the right
    shape for a flow: the gauge of who is blocked *right now* is
    ``AccountTotals.bot_blocked``, taken from ``users.blocked_bot_at``, and the two answer
    different questions. Reading either as the other is how a win-back campaign gets
    measured against the wrong denominator.

    An unblock is only recorded when a row that WAS blocked comes back — the writer refuses
    to record the ``left → member`` update Telegram sends on every first ``/start`` — so a
    non-zero unblock count means real returns and never new arrivals.

    Two round trips rather than one because the two are different populations of the same
    table under different predicates; a single statement would need the event as a grouping
    key, and then a window with no unblocks would return one row instead of two and the
    caller would have to invent the missing zero. A count that IS zero is a measurement here.

    INDEX: ``ix_bot_membership_events_at``, a range scan, with ``event`` checked in the heap.
    """
    return ChurnCounts(
        blocked=await _trend(
            session,
            BotMembershipEventRow.at,
            BotMembershipEventRow,
            window=window,
            extra=(BotMembershipEventRow.event == BotMembershipEvent.BLOCKED,),
        ),
        unblocked=await _trend(
            session,
            BotMembershipEventRow.at,
            BotMembershipEventRow,
            window=window,
            extra=(BotMembershipEventRow.event == BotMembershipEvent.UNBLOCKED,),
        ),
    )


async def has_recorded_churn(session: AsyncSession) -> bool:
    """True once ANY membership transition has been recorded. Window-blind, by design.

    The ``isChurnInstrumented`` capability. "Nobody blocked the bot in the range you chose"
    and "nothing in this deployment has ever recorded a block" are two different screens
    with two different remedies, and a windowed count cannot tell them apart — the same
    argument :func:`~hbd.db.admin.vendor_usage.has_recorded_vendor_usage` makes.
    """
    probe = await session.scalar(
        sa.select(sa.literal(1)).select_from(BotMembershipEventRow).limit(1)
    )
    return probe is not None


async def has_recorded_activity_history(session: AsyncSession) -> bool:
    """True once a nightly activity snapshot exists. The ``isActivityHistory`` capability.

    Separate from :func:`active_accounts`, which answers fine from the first day: the live
    gauge is a count against a cutoff, and the HISTORICAL series exists only from the first
    night the snapshot job ran. A panel that could not tell the two apart would draw an
    empty trend line for a deployment whose DAU is perfectly well known today.
    """
    probe = await session.scalar(
        sa.select(sa.literal(1)).select_from(UserActivitySnapshotRow).limit(1)
    )
    return probe is not None


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
async def _trend(
    session: AsyncSession,
    column: sa.SQLColumnExpression[datetime],
    entity: Any,
    *,
    window: TimeWindow | None,
    extra: tuple[sa.ColumnElement[bool], ...] = (),
) -> Trend:
    """One window's count and its predecessor's, in one scan where a predecessor exists.

    The shape every delta on this surface takes, written once: a spanning predicate over
    both ranges and two conditional counts inside it. When the caller gave no lower bound
    there is no predecessor to count, so this degrades to a single count and an honest
    ``previous=None`` rather than manufacturing a range.
    """
    previous = previous_window(window)
    if window is None or previous is None:
        plain: Select[tuple[int]] = sa.select(sa.func.count()).select_from(entity)
        if extra:
            plain = plain.where(*extra)
        plain = apply_window(plain, column, window)
        return Trend(current=int(await session.scalar(plain) or 0), previous=None)
    current_count, previous_count = count_pair(column, current=window)
    pair: Select[tuple[int, int]] = sa.select(
        current_count.label("current"), previous_count.label("previous")
    ).select_from(entity)
    if extra:
        pair = pair.where(*extra)
    pair = apply_window(pair, column, spanning_window(window, previous))
    row = (await session.execute(pair)).one()
    return Trend(current=int(row.current), previous=int(row.previous))
