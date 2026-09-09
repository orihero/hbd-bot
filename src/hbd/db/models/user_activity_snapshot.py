"""``user_activity_snapshots`` — one row per UTC day, so "active users" has a past.

``users.last_seen_at`` is UPSERTed IN PLACE by ``credits.touch`` (through ``bot/gate.py``'s
``TouchDrain``, coalesced to one write per account per minute). It is therefore a GAUGE
whose history is overwritten every minute an account is alive: nothing in this schema can
say how many people were active last Tuesday, and nothing ever could, because the value
that would have answered it was written over.

**WHY DAY-GRAIN COUNTS AND NOT (day, user).** A per-day per-user presence row would buy
retroactive cohorts — "were the people active in March the same people active in April" —
which nothing on the dashboard asks for, at DAU rows per day (10k DAU is 3.65M rows a
year) instead of 365. Decisively, it would BE personal data: a per-day presence log keyed to
an identified account is a movement record about a person. It would land in
``tables_with_personal_data``, oblige an ``*_expires_at`` column, a sweep in
``hbd.db.purge``, a ``RetentionPolicy`` period and a ``/forget`` decision — and it would
build exactly the per-customer surveillance record the panel already refuses by withholding
``last_seen_at`` from every ``/users`` projection so an operator cannot watch one customer
minute by minute. Aggregate counts over the whole population answer every card on the mock
and hold nothing about anybody.

**THESE ARE ROLLING WINDOWS SAMPLED DAILY, NOT CALENDAR-DAY DISTINCT-USER COUNTS.** Active
means ``last_seen_at >= taken_at - N days``, evaluated in ONE statement at the instant the
job runs. The columns are named ``active_24h_accounts`` / ``active_7d_accounts`` /
``active_30d_accounts`` and never ``dau``/``wau``/``mau``, because calendar-day DAU is
UNOBTAINABLE from this schema at any grain: ``last_seen_at`` is overwritten, so a customer
active on Monday and again on Tuesday leaves no trace of Monday, and counting "seen during
day D" after D has ended systematically undercounts D. Summing a column across days does
NOT give unique users either — an account active forty days running contributes to forty
rows. A serializer or a UI label that renames a field ``dau`` reintroduces precisely the
confusion this naming was chosen to prevent.

**THE SERIES CANNOT BE BACKFILLED, and no later change may pretend otherwise.** The past
values of ``last_seen_at`` are gone. There is no seeding migration, no estimate from
``users.created_at``, and no zero-fill: the series begins the first night the job runs,
``active_30d_accounts`` is bounded by deployment age for its first thirty days (a ramp that
looks like growth and is not), and a day the worker was down produces NO ROW. **The
null-never-zero rule governs the SERIES here, not only the columns:** a zero-filled gap
would report that nobody used the bot that day, which is a fabricated measurement wearing a
chart line, so the read layer returns the days it has and the panel renders the rest as
absent.

**NOT PERSONAL DATA, and the exemption is written down** in
``tests/test_db/test_privacy_constraints.py`` beside ``vendor_usage``'s rather than left
silent, because that file's own comment states an unnamed table is silently exempt. Every
column is a calendar date, a UTC instant, or an integer count over the entire user
population; nothing is keyed to an account and no row narrows to fewer than everybody. That
claim is stronger than ``vendor_usage``'s and it holds for a structural reason worth
restating: the day grain was chosen OVER a (day, user) grain precisely so it would be true.
No column is named ``*_expires_at``, so ``tests/test_db/test_audit_retention.py`` passes
over this table by construction.

**NO RETENTION CUTOFF AND NO CLOCK — a deliberate departure from ``vendor_usage`` (400
days) and ``purge_runs`` (365), argued rather than omitted.** Three reasons, each
sufficient: growth is one row a day, 3 650 in a decade, so there is nothing to bound; the
long history IS the product, and a cutoff would delete the year-over-year comparison ("is
this September busier than last September?") this table exists to make possible; and there
is no personal data here, so no legal schedule applies. Consequently there is no constant
in ``hbd.db.purge``, no ``PurgeReport`` field, no ``PurgeRunRow`` column, no entry in
``rows_past_expiry_statements`` and no ``RetentionPolicy`` field — and ``hbd.db.purge``'s
own module docstring names this table as deliberately unswept, exactly as it already does
for ``user_profiles``, so the decision cannot decay into an oversight.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, UtcDateTime, utc_now

__all__ = ["UserActivitySnapshotRow"]


class UserActivitySnapshotRow(Base):
    """One night's counts over the whole account population.

    ``TimestampMixin`` is deliberately not used, following ``PurgeRunRow`` and
    ``VendorUsageRow``: this row measures a moment that has already passed, so an
    ``updated_at`` could never be true, and the mixin's INDEXED ``created_at`` would
    duplicate the unique ``snapshot_date`` that every read already goes through.

    **THE COUNTS ARE NOT NULL AND CARRY NO DEFAULT, and the reasoning must not be applied
    by habit in either direction.** The null-never-zero rule exists because a DEFAULT of 0
    turns "nobody measured this" into "this was zero" — which is exactly how
    ``generation_attempts.cost_usd`` (0.0) and ``latency_ms`` (0) became unreadable. Here
    the ROW IS THE MEASUREMENT: all five counts come from ONE ``SELECT`` over ``users``, in
    one transaction, and the row is written only if that statement returned. There is no
    path on which a row exists with a count unmeasured, so ``NULL`` would be a state the
    writer cannot produce and the reader would have to branch on anyway. The load-bearing
    half is the absence of any default: an ``INSERT`` that omitted a count fails loudly
    instead of writing a fabricated zero.

    **THE FORWARD RULE.** Any count column added to this table by a LATER revision MUST be
    nullable with no default, because rows already written never measured it. Revision
    0016's ``purge_runs.vendor_usage_deleted`` carve-out does NOT transfer: that column
    could be back-filled with 0 because zero was the TRUE answer for old sweeps (the table
    did not exist), whereas "how many accounts were active 30 days ago" has no true value
    for a night nobody counted. The concrete case is already visible — a
    ``bot_blocked_accounts`` column matching ``users.blocked_bot_at`` would have to be
    nullable, because every snapshot taken before revision 0017 measured no such thing.
    """

    __tablename__ = "user_activity_snapshots"
    __table_args__ = (
        # The idempotency authority, and the only one: the snapshot job writes through
        # ``insert_or_ignore``, so a re-run later the same day is an ignored no-op rather
        # than a silent re-anchoring of that day's measurement by several hours. Named
        # ``snapshot_date`` so ``NAMING_CONVENTION``'s ``uq`` template renders
        # ``uq_user_activity_snapshots_snapshot_date``, matching the migration's ``op.f``.
        sa.UniqueConstraint("snapshot_date", name="snapshot_date"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: The UTC calendar day this sample is filed under. No default: the job computes it once
    #: and passes it in, so there is exactly one place that decides which day a sample
    #: belongs to.
    snapshot_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    #: The instant the counts were evaluated at — the anchor of every rolling window on the
    #: row. Stored rather than assumed, because a snapshot taken at 16:00 after an outage is
    #: a true number anchored differently from its neighbours, and that is recorded rather
    #: than smoothed over or refused.
    taken_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: Every account that has ever spoken to the bot.
    total_accounts: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: ``COUNT(users.is_blocked IS TRUE)`` — the OPERATOR-set bar. **This is not churn.**
    #: A customer blocking the bot is ``users.blocked_bot_at`` and
    #: ``bot_membership_events``; conflating the two would report operator moderation as
    #: customer churn. It is snapshotted because ``is_blocked`` is a mutable flag with no
    #: history and is therefore unreconstructable after the fact — unlike "new accounts",
    #: which is deliberately absent here because ``users.created_at`` answers it forever and
    #: a stored copy could only drift.
    blocked_accounts: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    active_24h_accounts: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    active_7d_accounts: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    active_30d_accounts: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: When the ROW was written, which differs from :attr:`taken_at` by the duration of the
    #: job — exactly as ``PurgeRunRow`` separates ``ran_at`` from ``created_at``.
    #: Deliberately UNINDEXED: no read of this table orders or filters on it.
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)

    @property
    def anchor_offset_s(self) -> int:
        """How far into its own UTC day this sample was taken, in seconds.

        The routine value is a few hundred (the job runs just after midnight). A large one
        says the point is anchored unlike its neighbours — a true number, taken late after
        an outage — and publishing it is how a reader sees that instead of guessing at a
        step in the line.
        """
        midnight = datetime.combine(self.snapshot_date, time.min, tzinfo=UTC)
        return int((self.taken_at - midnight).total_seconds())
