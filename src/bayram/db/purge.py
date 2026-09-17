"""The FIL-7 purge job. A legal requirement, not a housekeeping nicety.

Four independent clocks run here, and they are independent on purpose — collapsing them
into one sweep would be simpler and would also be wrong, because they protect different
things and expire at different times:

======================  ==============================================  ==========
What                    Where                                           Default
======================  ==============================================  ==========
Delivered paid audio    ``assets`` rows, deleted outright               12 months
Free-tier output        ``assets`` rows, deleted outright               30 days
Free-text brief         ``briefs.note`` + ``briefs.approved_lyrics``,   30 days
                        nulled in place
Free-text transcript    ``generation_attempts.stt_transcript``,         30 days
                        nulled in place
Recipient identity      ``briefs`` name columns, nulled in place        90 days
Recipient identity      ``generation_attempts`` name text, nulled       90 days
Abandoned drafts        ``orders`` in ``DRAFT``, deleted outright       14 days
Operator free text      ``admin_audit_log.reason_text``, nulled         90 days
Audited actions         ``admin_audit_log`` rows, deleted outright      730 days
Admin sessions          ``admin_sessions`` rows, deleted outright       12 h
Sweep records           ``purge_runs``, deleted outright                12 months
Vendor call telemetry   ``vendor_usage``, deleted outright              13 months
Bot membership events   ``bot_membership_events``, deleted outright     13 months
Payment RPC journal     ``payme_rpc_log``, deleted outright             90 days
Terminal unpaid intents ``payment_intents`` not ``paid``, deleted       13 months
Broadcast delivery log  ``broadcast_recipients``, deleted outright     13 months
======================  ==============================================  ==========

The last six rows are not customer data. ``purge_runs`` is this job's own audit trail,
swept by the same run so the bookkeeping cannot outgrow the thing it books; ``vendor_usage``
is the vendor-spend telemetry the admin panel's Vendors screen reads, kept on a cutoff
rather than a clock because it holds nothing about anybody (see
:data:`VENDOR_USAGE_RETENTION_DAYS`); ``bot_membership_events`` is the churn transition log
(revision 0017), kept on a cutoff for the same reason and NOT on a clock — the identity it
carries comes off through ``/forget``'s anonymisation arm rather than on any schedule, and
the cutoff bounds how long an account id sits there as defence in depth beside that arm,
never as a substitute for it (see :data:`BOT_MEMBERSHIP_RETENTION_DAYS`). The next two
arrived with the redirect payment rail (revision 0023) and are cutoffs for the same
reason again: ``payme_rpc_log`` is the journal of inbound calls from the rail and holds
no telegram id, no request body and no header at all (see
:data:`PAYME_RPC_LOG_RETENTION_DAYS`), while ``payment_intents`` is swept only where it
is TERMINAL AND UNPAID — a ``paid`` intent is never deleted, because it is the join
between a rail-side transaction and the receipt it paid for and the rail may still ask
us about it (see :data:`PAYMENT_INTENT_RETENTION_DAYS`). The last arrived with the
broadcast tables (revision 0024) and is ``bot_membership_events``' shape exactly:
``broadcast_recipients`` carries a ``telegram_user_id``, so the identity comes off it
through ``/forget``'s anonymisation arm rather than on any schedule, and this cutoff
bounds how long an account id sits there as defence in depth beside that arm, never as a
substitute for it (see :data:`BROADCAST_RECIPIENT_RETENTION_DAYS`).

**THREE TABLES ADDED BY THE DASHBOARD WORK ARE DELIBERATELY UNSWEPT, and their absence from
the table above is a decision rather than an oversight** — the same standing instruction the
``user_profiles`` paragraph below carries, and for the same reason: an unswept table nobody
argued about is how a retention gap starts.

* ``user_activity_snapshots`` (0018). One row per UTC day of aggregate counts, so growth is
  365 rows a year and there is nothing to bound; the long history IS the product, and a
  cutoff would delete exactly the year-over-year comparison the table exists to make
  possible. No column is keyed to an account, so there is no personal data to be obliged to
  delete.
* ``vendor_balances`` (0019). Bounded BY CONSTRUCTION: its primary key is a five-member enum
  crossed with a boolean, so it holds at most ten rows ever and rows are UPDATEd in place
  rather than appended. A cutoff here would be a scheduled no-op over a three-row table and a
  ``purge_runs`` counter that is permanently zero. The history a cache discards is not lost:
  every probe also writes a ``vendor_usage`` row with ``operation=HEALTH``, which the
  400-day cutoff above already covers.
* ``topup_purchases`` (0020). A RECEIPT, on the same footing as ``plan_purchases`` and
  ``credit_ledger`` — it answers "was this customer charged for a song they never got?"
  months after the recipient's name, the note and the audio are lawfully gone, and an audit
  trail that deletes itself on a schedule cannot answer a dispute about the period it just
  erased. Erased by ANONYMISATION on request, never by a clock.
* ``payme_transactions`` (0023). A FOURTH table on ``topup_purchases``' argument, and the
  strongest instance of it: this is what the payment RAIL says it charged, which is the
  only record that can answer "they say they took 7 000 soʼm from this card; did we ever
  grant anything for it?" long after the recipient's name, the customer's note and the
  audio are lawfully gone. The rail can also ask us about ANY transaction it has ever
  created, over an arbitrary period, through its statement call — so a row deleted on a
  schedule is a real payment we would have to answer "never existed" about, which is the
  one answer that loses a customer their dispute. It holds no telegram id at all: the
  person is reachable from it only by joining through ``payment_intents``, which is
  exactly the join ``/forget`` breaks. Growth is one row per payment actually attempted,
  bounded by the business rather than by a sweep.

Do not add a sweep for any of the four without first re-opening its classification in
``tests/test_db/test_privacy_constraints.py``, where each one's exemption is written down.

The three admin rows above them live in
:mod:`bayram.db.purge_admin`, because they are the only sweeps that have to know
about Postgres privileges: §12.4 revokes ``UPDATE``/``DELETE`` on ``admin_audit_log`` from
the application role, so on a two-role deployment they go through the ``SECURITY DEFINER``
functions migration 0007 installs.

**The one personal-data table this job does not sweep is ``user_profiles``**, and its
absence from the table above is deliberate. It carries no ``expires_at`` column because the
contact record has no dormancy clock: it is held while the account exists and deleted
outright by ``/forget`` (:func:`bayram.db.user_profiles.erase_profile`, which also hands the
caller the avatar's object key so the bytes go with the row).
``tests/test_db/test_audit_retention.py`` therefore passes over it by construction — both
``_clocks_in_the_schema`` and ``_clocks_read_by_a_sweep`` select on a column name ending in
``expires_at`` — and the guard that DOES cover it is
``tests/test_db/test_privacy_constraints.py``'s ``tables_erased_on_request`` set. Do not
add a sweep here without first moving that table out of that set: a table swept on a clock
AND named as erased on request means the two mechanisms disagree about the same data, and
the way that failure shows up is a number the customer was told is theirs to erase quietly
outliving the erasure, or vanishing without one.

Two design choices worth stating, because both look like mistakes until you see why:

**Identity is nulled, not deleted.** Deleting the brief row would take the order's
occasion and genre with it, and those are not personal data — they are the operating
record of a transaction the tax authority expects to survive (SoW DAT-3). Nulling the
name columns is what makes "the tax record and the personal-data record are separable at
the schema level" true in practice rather than in a design document.

**Assets are deleted, and their storage keys are returned rather than deleted.** This
module owns rows; it does not own an object store, and it must not silently half-succeed
by deleting bytes and then failing to commit the row deletion. The caller gets the keys
back in :class:`PurgeReport` and deletes the objects after the transaction commits, so a
crash leaves orphaned bytes (recoverable, sweepable) rather than a row pointing at bytes
that no longer exist (a broken re-send that looks like data corruption).

**The song transcript is free text, not just a name.** ``stt_transcript`` was sized for an
isolated name chunk; inpainting is enterprise-gated, so verification hears the whole track
and the column holds the whole lyric — which, since the wizard's preview step, may be words
the customer wrote about a named third party. Those words live on the 30-day clock in
``briefs.approved_lyrics``, so the copy of them here gets the same clock rather than the
90-day identity one; leaving it on identity alone would have retained the customer's free
text for sixty days past the schedule the privacy notice states. The identity sweep clears
it as well, for the same "whichever fires first wins" reason as the lyric below.

**The approved lyric is nulled by BOTH brief sweeps, and that is not a duplicate.** It is
free text, so the 30-day note clock owns it; but it also carries the recipient's identity —
``LyricDraft.name_display`` is the display name and the name-hook section sings it verbatim
— and ``RetentionPolicy`` accepts any positive periods, so a deployment with
``brief_text_days`` longer than ``recipient_identity_days`` would otherwise leave the name
on disk past its own clock while every other identity column had already been cleared. The
identity sweep therefore clears it too, and whichever clock fires first wins.

Every sweep is bounded by ``batch_size``. A first run against a year of unpurged data must
not take a lock on the whole ``assets`` table.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import OrderState, Result
from bayram.db.credits import settle_stale_debits
from bayram.db.enums import PaymentIntentState
from bayram.db.guard import run_guarded
from bayram.db.models.admin_audit import AdminAuditRow
from bayram.db.models.admin_session import AdminSessionRow
from bayram.db.models.asset import AssetRow
from bayram.db.models.bot_membership_event import BotMembershipEventRow
from bayram.db.models.brief import BriefRow
from bayram.db.models.broadcast_recipient import BroadcastRecipientRow
from bayram.db.models.chat_message import ChatMessageRow
from bayram.db.models.generation_attempt import GenerationAttemptRow
from bayram.db.models.name_record import NameRecordRow
from bayram.db.models.order import OrderRow
from bayram.db.models.payme_rpc_log import PaymeRpcLogRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.models.purge_run import PurgeRunRow
from bayram.db.models.vendor_usage import VendorUsageRow
from bayram.db.purge_admin import (
    admin_sessions_due,
    audit_reasons_due,
    audit_rows_due,
    pin_audit_head,
    purge_admin_sessions,
    purge_audit_log,
    purge_audit_reasons,
)
from bayram.db.retention import DEFAULT_RETENTION_POLICY, RetentionPolicy
from bayram.entitlements import DEFAULT_ENTITLEMENT_POLICY, EntitlementPolicy
from bayram.logging import get_logger
from bayram.storage import archive_key

__all__ = [
    "PurgeReport",
    "purge_expired",
    "DEFAULT_PURGE_BATCH_SIZE",
    "PURGE_RUN_RETENTION_DAYS",
    "VENDOR_USAGE_RETENTION_DAYS",
    "BOT_MEMBERSHIP_RETENTION_DAYS",
    "PAYME_RPC_LOG_RETENTION_DAYS",
    "PAYMENT_INTENT_RETENTION_DAYS",
    "BROADCAST_RECIPIENT_RETENTION_DAYS",
    "rows_past_expiry_statements",
]

_log = get_logger(__name__)

#: Rows touched per table per run. Sized so a sweep stays well inside a statement timeout.
DEFAULT_PURGE_BATCH_SIZE: int = 500

#: How long the sweep's own records are kept (admin plan §12.5). Not a ``RetentionPolicy``
#: field on purpose: the policy holds periods for CUSTOMER data, every one of which is a
#: published legal commitment an operator may tune. This one bounds an internal counter
#: table that holds no personal data, so making it configurable would add a knob whose only
#: possible effect is to lose operational history.
PURGE_RUN_RETENTION_DAYS: Final[int] = 365

#: How long ``vendor_usage`` rows are kept. Thirteen months, not twelve, so a year-over-year
#: comparison — "is this March dearer than last March?" — still has last March to compare
#: against on the day it is asked.
#:
#: Outside ``RetentionPolicy`` for the same reason as the constant above, and it is worth
#: being explicit about why, because this table's exclusion is the stronger claim: every
#: column on ``vendor_usage`` is a closed enum, an integer, a machine id or a bounded error
#: code, so there is no text about a person anywhere in it and no published customer
#: commitment to tune. It is a cutoff that bounds an internal telemetry table's growth, not a
#: legal clock — which is also why no column on that table is named ``*_expires_at``: that
#: suffix is reserved for retention clocks and obliges a sweep BY NAME in
#: ``tests/test_db/test_audit_retention.py``.
VENDOR_USAGE_RETENTION_DAYS: Final[int] = 400

#: How long ``bot_membership_events`` rows are kept. Thirteen months, and for a reason the
#: constant above only half shares: a year-over-year CHURN comparison — "did we lose more
#: customers this March than last?" — needs last March to still be there on the day it is
#: asked, and unlike vendor spend there is no invoice anywhere else that could answer it.
#:
#: Outside ``RetentionPolicy`` for :data:`PURGE_RUN_RETENTION_DAYS`' stated reason: the
#: policy holds periods for CUSTOMER data, every one of which is a published legal
#: commitment an operator may tune, and a knob on this one could only ever lose operational
#: history. It is a CUTOFF on ``at`` rather than a per-row clock, which is why no column on
#: that table is named ``*_expires_at`` — that suffix obliges a sweep BY NAME in
#: ``tests/test_db/test_audit_retention.py`` and would claim a legal schedule this table does
#: not have.
#:
#: **This cutoff is not the erasure route, and must never be mistaken for one.** Unlike
#: ``vendor_usage``, that table carries a ``telegram_user_id``, and the way a customer's
#: identity leaves it is ``/forget``'s anonymisation arm, which nulls the id in place and
#: keeps the row so the day counts survive. The cutoff bounds how long an id can sit there
#: at all, which is defence in depth beside that arm rather than a substitute for it.
BOT_MEMBERSHIP_RETENTION_DAYS: Final[int] = 400


#: How long ``payme_rpc_log`` rows are kept. Ninety days, and deliberately the SHORTEST bound
#: in this module, against 400 for the two telemetry tables above.
#:
#: The questions this journal answers are asked DURING an incident and in the fortnight after
#: it — "which four of those eleven calls did we refuse, and with what code?" — and a
#: certification dispute still open after a quarter will not be settled by a row in it. The
#: money questions are answered by ``payme_transactions``, which is on no bound at all.
#:
#: A CUTOFF on ``at``, not a per-row clock, and outside ``RetentionPolicy`` for
#: :data:`PURGE_RUN_RETENTION_DAYS`' stated reason: that policy holds periods for CUSTOMER
#: data, every one of which is a published legal commitment an operator may tune. This table
#: holds none — no telegram id, no request body, no header, so every column is a method name,
#: an opaque reference, a machine id, an integer or the address of PAYME's own server — which
#: is exactly ``vendor_usage``'s argument. That is also why no column on it is named
#: ``*_expires_at``: the suffix obliges a sweep BY NAME in
#: ``tests/test_db/test_audit_retention.py`` and would claim a legal schedule this table does
#: not have.
PAYME_RPC_LOG_RETENTION_DAYS: Final[int] = 90

#: How long a TERMINAL UNPAID ``payment_intents`` row is kept. Thirteen months, matching the
#: two cutoffs above so that a year-over-year funnel comparison — "did more people abandon the
#: payment page this March than last?" — still has last March to compare against.
#:
#: **The predicate is narrow on purpose, and the narrowness is the whole decision.** It sweeps
#: ``state IN ('cancelled', 'expired')`` and nothing else. A ``paid`` intent is NEVER deleted:
#: it is the join between a rail-side transaction and the receipt and credit grant written in
#: the same commit, and the rail may still ask about that transaction through its statement
#: call, which means a purged row turns a real payment into one we would answer "never
#: existed" about. A ``pending`` or ``awaiting`` intent is not swept either, because it is
#: live — expiry moves it to ``expired`` first, which is a different operation with a
#: different clock (``valid_until``, a BUSINESS clock) and belongs to the payment gateway
#: rather than to this job.
#:
#: A CUTOFF on ``created_at``, not a per-row clock, for :data:`VENDOR_USAGE_RETENTION_DAYS`'
#: reason: it bounds the growth of a table that gets a row every time anybody opens a payment
#: page, most of which are never paid. Like ``bot_membership_events`` and unlike
#: ``vendor_usage`` it CAN carry a ``telegram_user_id``, and the way that id leaves is
#: ``/forget``'s anonymisation arm in :mod:`bayram.db.credit_erasure` — this cutoff is defence in
#: depth beside it and never a substitute for it.
PAYMENT_INTENT_RETENTION_DAYS: Final[int] = 400

#: How long a ``broadcast_recipients`` row is kept. Thirteen months, matching the three
#: cutoffs above so that a year-over-year campaign comparison — "did last spring's
#: announcement reach more people than this one?" — still has last spring to compare against
#: on the day it is asked. Nothing else can answer it: the counters on ``broadcasts`` are a
#: rollup of these rows, and a campaign whose ledger has aged out keeps its totals while
#: losing the ability to say WHICH sends failed and why.
#:
#: **This is the fastest-growing table in the schema**, one row per account per campaign, so
#: it is the one where an unbounded log would actually cost something: a weekly send to forty
#: thousand accounts is two million rows a year on its own.
#:
#: A CUTOFF on ``created_at`` — the instant the audience was materialised — and not a per-row
#: clock, for :data:`VENDOR_USAGE_RETENTION_DAYS`' stated reason: it bounds a log's growth
#: rather than keeping a published legal promise, so it is outside ``RetentionPolicy``, where
#: every period is a customer commitment an operator may tune. Which is also why no column on
#: that table is named ``*_expires_at``: that suffix obliges a sweep BY NAME in
#: ``tests/test_db/test_audit_retention.py`` and would claim a legal schedule this table does
#: not have.
#:
#: **This cutoff is not the erasure route, and must never be mistaken for one** — the same
#: warning :data:`BOT_MEMBERSHIP_RETENTION_DAYS` carries, and for the same reason. These rows
#: hold a ``telegram_user_id``, and the way a customer's identity leaves them is ``/forget``'s
#: anonymisation arm in :mod:`bayram.db.credit_erasure`, which nulls the id in place and keeps
#: the row so a completed campaign's arithmetic does not change retroactively.
BROADCAST_RECIPIENT_RETENTION_DAYS: Final[int] = 400


class PurgeReport(BaseModel):
    """What one purge run did. Logged, and returned so a scheduler can alert on it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ran_at: datetime
    #: The bound every sweep below ran under. Carried on the report rather than left with
    #: the caller because ``has_work_remaining`` cannot be answered without it.
    batch_size: int = Field(default=DEFAULT_PURGE_BATCH_SIZE, gt=0)
    assets_deleted: int = Field(default=0, ge=0)
    #: Object-store keys whose rows are gone. The CALLER deletes these objects.
    storage_keys: tuple[str, ...] = ()
    brief_notes_purged: int = Field(default=0, ge=0)
    brief_identities_purged: int = Field(default=0, ge=0)
    attempt_identities_purged: int = Field(default=0, ge=0)
    attempt_transcripts_purged: int = Field(default=0, ge=0)
    name_records_deleted: int = Field(default=0, ge=0)
    abandoned_orders_deleted: int = Field(default=0, ge=0)
    #: ``admin_audit_log.reason_text`` nulled at 90 days — the operator's own free text, the
    #: one column in that table an operator can type a customer's name into.
    audit_reasons_purged: int = Field(default=0, ge=0)
    #: ``admin_audit_log`` rows deleted at 730 days. Every deletion writes a chain anchor.
    audit_rows_deleted: int = Field(default=0, ge=0)
    #: ``admin_sessions`` past their absolute cap. Token digests, CSRF tokens and operator
    #: IP addresses; the sweep existed and had no caller until this pass.
    admin_sessions_deleted: int = Field(default=0, ge=0)
    purge_runs_deleted: int = Field(default=0, ge=0)
    #: ``vendor_usage`` rows past the 400-day cutoff. Counted like every other sweep — a
    #: sweep whose number is not reported is a backlog the panel renders as zero.
    vendor_usage_deleted: int = Field(default=0, ge=0)
    #: ``bot_membership_events`` rows past the 400-day cutoff. Counted like every other
    #: sweep, and worth one line on why it is a sweep at all: the churn SERIES lives in that
    #: table, so this number is the only thing that says how much of it has aged out.
    membership_events_deleted: int = Field(default=0, ge=0)
    chat_bodies_purged: int = Field(default=0, ge=0)
    chat_messages_deleted: int = Field(default=0, ge=0)
    #: ``payme_rpc_log`` rows past the 90-day cutoff. Counted like every other sweep — a
    #: sweep whose number is not reported is a backlog the panel renders as zero.
    payme_rpc_rows_deleted: int = Field(default=0, ge=0)
    #: TERMINAL UNPAID ``payment_intents`` past the 400-day cutoff. Counted separately from
    #: everything else here because it is the one number that says how many payment pages
    #: were opened and abandoned — a funnel fact as much as a housekeeping one.
    payment_intents_deleted: int = Field(default=0, ge=0)
    #: ``broadcast_recipients`` rows past the 400-day cutoff. Counted like every other sweep,
    #: and this is the count most likely to be the one that matters: the table takes a row per
    #: account per campaign, so a sweep that quietly stops keeping up shows here as a small
    #: number beside a large backlog long before it shows anywhere else.
    broadcast_recipients_deleted: int = Field(default=0, ge=0)
    #: Open credit debits the sweep closed — refunded, or consumed when the kit was already
    #: rendered. Not a retention clock and not personal data; it rides this run because this
    #: is the transaction the worker already schedules. Deliberately NOT added to
    #: ``rows_past_expiry_statements``: that function answers "how far behind is the
    #: RETENTION schedule", which the panel renders as a legal backlog, and a stale debit is
    #: not one.
    stale_debits_settled: int = Field(default=0, ge=0)

    @property
    def per_sweep_counts(self) -> tuple[int, ...]:
        """Every sweep's own count, unsummed. The order is the order they ran in."""
        return (
            self.assets_deleted,
            self.brief_notes_purged,
            self.brief_identities_purged,
            self.attempt_identities_purged,
            self.attempt_transcripts_purged,
            self.name_records_deleted,
            self.abandoned_orders_deleted,
            self.audit_reasons_purged,
            self.audit_rows_deleted,
            self.admin_sessions_deleted,
            self.purge_runs_deleted,
            self.vendor_usage_deleted,
            self.membership_events_deleted,
            self.chat_bodies_purged,
            self.chat_messages_deleted,
            self.payme_rpc_rows_deleted,
            self.payment_intents_deleted,
            self.broadcast_recipients_deleted,
            self.stale_debits_settled,
        )

    @property
    def total_rows_affected(self) -> int:
        return sum(self.per_sweep_counts)

    @property
    def has_work_remaining(self) -> bool:
        """True when a sweep filled its batch, so the scheduler should run again soon.

        This used to be ``total_rows_affected > 0``, which is a different predicate wearing
        this one's docstring: it was true of every run that did any work at all and false
        the instant nothing was due. A nightly sweep that deleted three rows reported "more
        remaining" forever, and the panel's "run again" affordance would have been lit
        permanently — which is the same as not being there.

        A sweep is bounded by ``LIMIT batch_size``. The only evidence that more rows were
        due than one pass could take is a sweep that came back **full**, so that is what is
        asked. Each count is compared on its own: one saturated table means work remains
        even when every other clock had nothing due.
        """
        return any(count >= self.batch_size for count in self.per_sweep_counts)


async def purge_expired(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
    entitlements: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
    batch_size: int = DEFAULT_PURGE_BATCH_SIZE,
) -> Result[PurgeReport]:
    """Run every retention clock once, and close every debit nobody settled. Never raises.

    ``now`` is injected rather than read from the system clock so a test can advance time
    thirteen months without waiting thirteen months.

    ``entitlements`` supplies the settlement grace, and it is DEFAULTED rather than required
    because the caller on the cron (``bayram.runtime.retention_job``) predates it and passes
    only ``policy=``. The default is derived from the SHIPPED queue ladder — see
    ``bayram.entitlements.derive_settlement_grace_s`` — so a deployment that lengthens
    ``BAYRAM_QUEUE_JOB_TIMEOUT_S`` (or sets ``BAYRAM_SETTLEMENT_GRACE_S``) moves the ledger's
    in-flight window, which ``AppContainer`` resolves from ``Settings``, without moving this
    one. Passing ``entitlements=resolve_entitlement_policy(settings)`` at that call site is
    still the tidier wiring.

    **It is no longer a correctness gap, and that is deliberate rather than lucky.** A grace
    shorter than the deployment's own retry ladder used to let the sweep refund an order that
    was still rendering — the customer then kept the credit and got the song. The selection
    in ``credit_sql.stale_debits`` now requires the ORDERS ROW to have been quiet for the
    grace as well as the debit, and every stage transition stamps ``orders.updated_at``
    (``repository._set_order_state``), so a live job is visible as live whatever number this
    parameter carries. A short grace can now only make the sweep tidy up sooner than
    necessary, never take a credit back from a job that is about to deliver.
    """
    return await run_guarded(
        "purge_expired",
        lambda: _purge(
            session_factory,
            now=now,
            policy=policy,
            entitlements=entitlements,
            batch_size=batch_size,
        ),
        now=now.isoformat(),
    )


async def _purge(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    policy: RetentionPolicy,
    entitlements: EntitlementPolicy,
    batch_size: int,
) -> PurgeReport:
    async with session_factory.begin() as session:
        storage_keys, assets_deleted = await _purge_assets(session, now=now, limit=batch_size)
        notes = await _purge_brief_notes(session, now=now, limit=batch_size)
        identities = await _purge_brief_identities(session, now=now, limit=batch_size)
        attempts = await _purge_attempt_identities(session, now=now, limit=batch_size)
        transcripts = await _purge_attempt_transcripts(session, now=now, limit=batch_size)
        names = await _purge_name_records(session, now=now, limit=batch_size)
        drafts = await _purge_abandoned_orders(
            session, cutoff=policy.abandoned_draft_cutoff(now), limit=batch_size
        )
        # The admin panel's own three clocks. They run before the anchor is pinned, so a
        # truncation this run made is recorded below the head this run records.
        audit_reasons = await purge_audit_reasons(session, now=now, limit=batch_size)
        audit_rows = await purge_audit_log(session, now=now, limit=batch_size)
        admin_sessions = await purge_admin_sessions(session, now=now, limit=batch_size)
        await pin_audit_head(session, now=now)
        runs = await _purge_purge_runs(
            session, cutoff=now - timedelta(days=PURGE_RUN_RETENTION_DAYS), limit=batch_size
        )
        vendor_usage = await _purge_vendor_usage(
            session, cutoff=now - timedelta(days=VENDOR_USAGE_RETENTION_DAYS), limit=batch_size
        )
        membership_events = await _purge_membership_events(
            session, cutoff=now - timedelta(days=BOT_MEMBERSHIP_RETENTION_DAYS), limit=batch_size
        )
        chat_bodies = await _purge_chat_bodies(session, now=now, limit=batch_size)
        chat_messages = await _purge_chat_messages(session, now=now, limit=batch_size)
        payme_rpc_rows = await _purge_payme_rpc_log(
            session, cutoff=now - timedelta(days=PAYME_RPC_LOG_RETENTION_DAYS), limit=batch_size
        )
        intents = await _purge_terminal_intents(
            session, cutoff=now - timedelta(days=PAYMENT_INTENT_RETENTION_DAYS), limit=batch_size
        )
        recipients = await _purge_broadcast_recipients(
            session,
            cutoff=now - timedelta(days=BROADCAST_RECIPIENT_RETENTION_DAYS),
            limit=batch_size,
        )
        # Last, and inside the same transaction: it writes ledger rows rather than deleting
        # anything, so a purge that fails half way must take these back with it.
        debits = await settle_stale_debits(session, now=now, limit=batch_size, policy=entitlements)

    report = PurgeReport(
        ran_at=now,
        batch_size=batch_size,
        assets_deleted=assets_deleted,
        storage_keys=storage_keys,
        brief_notes_purged=notes,
        brief_identities_purged=identities,
        attempt_identities_purged=attempts,
        attempt_transcripts_purged=transcripts,
        name_records_deleted=names,
        abandoned_orders_deleted=drafts,
        audit_reasons_purged=audit_reasons,
        audit_rows_deleted=audit_rows,
        admin_sessions_deleted=admin_sessions,
        purge_runs_deleted=runs,
        vendor_usage_deleted=vendor_usage,
        membership_events_deleted=membership_events,
        chat_bodies_purged=chat_bodies,
        chat_messages_deleted=chat_messages,
        payme_rpc_rows_deleted=payme_rpc_rows,
        payment_intents_deleted=intents,
        broadcast_recipients_deleted=recipients,
        stale_debits_settled=debits,
    )
    # A purge that runs and does nothing is as important to see as one that deletes 40k
    # rows: silence here is indistinguishable from a scheduler that stopped firing.
    # The keys themselves are deliberately NOT logged — an object key is the only thing
    # standing between a signed URL and someone else's birthday song.
    summary = report.model_dump(mode="json", exclude={"storage_keys"})
    _log.info("retention purge complete", extra={**summary, "storage_key_count": len(storage_keys)})
    return report


# ---------------------------------------------------------------------------
# The predicates, named once
# ---------------------------------------------------------------------------
# Each sweep below and :func:`rows_past_expiry_statements` ask the SAME question, one with
# a ``LIMIT`` and one with a ``COUNT``. Writing that question twice is how the panel comes
# to report a backlog the job does not sweep — or, worse, reports none while rows rot — so
# it is written once, here, and both callers read it from the same place.
def _assets_due(now: datetime) -> sa.ColumnElement[bool]:
    return AssetRow.expires_at <= now


def _brief_notes_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        BriefRow.note_expires_at <= now,
        sa.or_(BriefRow.note.is_not(None), BriefRow.approved_lyrics.is_not(None)),
    )


def _brief_identities_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        BriefRow.identity_expires_at <= now,
        BriefRow.recipient_name_display.is_not(None),
    )


def _attempt_identities_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        GenerationAttemptRow.identity_expires_at <= now,
        GenerationAttemptRow.identity_purged_at.is_(None),
        sa.or_(
            GenerationAttemptRow.name_candidate_text.is_not(None),
            GenerationAttemptRow.stt_transcript.is_not(None),
        ),
    )


def _attempt_transcripts_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        GenerationAttemptRow.text_expires_at <= now,
        GenerationAttemptRow.text_purged_at.is_(None),
        GenerationAttemptRow.stt_transcript.is_not(None),
    )


def _name_records_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(NameRecordRow.expires_at.is_not(None), NameRecordRow.expires_at <= now)


def _abandoned_orders_due(cutoff: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(OrderRow.state == OrderState.DRAFT, OrderRow.created_at <= cutoff)


def _purge_runs_due(cutoff: datetime) -> sa.ColumnElement[bool]:
    return PurgeRunRow.ran_at <= cutoff


def _vendor_usage_due(cutoff: datetime) -> sa.ColumnElement[bool]:
    """Telemetry rows written before ``cutoff``.

    On ``created_at``, not on an ``*_expires_at`` column, and that is the whole difference
    between this and the clocks above: a retention clock is stamped per row by its writer
    from a published policy, while this is a cutoff applied at sweep time to a table holding
    no personal data. Naming a column ``expires_at`` there would enlist ``vendor_usage`` in
    ``test_audit_retention.py``'s clock inventory and claim a legal schedule this table does
    not have.
    """
    return VendorUsageRow.created_at <= cutoff


def _membership_events_due(cutoff: datetime) -> sa.ColumnElement[bool]:
    """Churn transitions observed before ``cutoff``.

    On ``at`` — the instant the transition happened — and not on an ``*_expires_at`` column,
    for the same reason :func:`_vendor_usage_due` is on ``created_at``: this is a cutoff
    applied at sweep time to bound a log's growth, not a per-row clock stamped by a writer
    from a published policy. The difference from ``vendor_usage`` worth naming is that these
    rows CAN carry a ``telegram_user_id``, and the way that id leaves is ``/forget``'s
    anonymisation, not this predicate.
    """
    return BotMembershipEventRow.at <= cutoff


def _payme_rpc_log_due(cutoff: datetime) -> sa.ColumnElement[bool]:
    """Inbound rail calls journalled before ``cutoff``.

    On ``at`` — the instant the call was answered — and not on an ``*_expires_at`` column,
    for the reason :func:`_vendor_usage_due` is on ``created_at``: this is a cutoff applied
    at sweep time to bound a journal's growth, not a per-row clock stamped by a writer from
    a published policy. The claim is stronger here than it is for ``vendor_usage``, because
    that table merely happens to hold no telegram id while this one is DESIGNED to hold no
    identifier of a person at all — no id, no request body, no header.
    """
    return PaymeRpcLogRow.at <= cutoff


def _terminal_intents_due(cutoff: datetime) -> sa.ColumnElement[bool]:
    """Payment intents opened before ``cutoff`` that ended without money changing hands.

    Two terms, and the second is the whole point. On ``created_at`` for
    :func:`_vendor_usage_due`'s reason — bounded growth, not a legal clock — AND on a
    terminal-unpaid state, because **a ``paid`` intent must never be deleted**: it is the
    join between a rail-side transaction and the receipt and credit grant written in the
    same commit, and the rail may still ask about that transaction through its statement
    call. A purged row would turn a real payment into one we answer "never existed" about.

    ``pending`` and ``awaiting`` are excluded because they are LIVE. Expiry moves a lapsed
    ``pending`` intent to ``expired`` first — a different operation, on ``valid_until``,
    which is a business clock owned by the payment gateway and not by this job — and an
    ``awaiting`` intent is one the rail is charging a card against right now.

    The states are spelled as enum members rather than literals because this is application
    code and the enum is the single definition; the CHECK constraints in revision 0023 spell
    the same values literally, and that asymmetry is deliberate — DDL outlives the class.
    """
    return sa.and_(
        PaymentIntentRow.created_at <= cutoff,
        PaymentIntentRow.state.in_((PaymentIntentState.CANCELLED, PaymentIntentState.EXPIRED)),
    )


def _broadcast_recipients_due(cutoff: datetime) -> sa.ColumnElement[bool]:
    """Delivery rows materialised before ``cutoff``.

    On ``created_at`` — the instant the audience was frozen — and not on an ``*_expires_at``
    column, for the reason :func:`_vendor_usage_due` is on ``created_at``: this is a cutoff
    applied at sweep time to bound a log's growth, not a per-row clock stamped by a writer
    from a published policy. The state is deliberately NOT part of the predicate, unlike
    :func:`_terminal_intents_due`: a row still ``PENDING`` after thirteen months belongs to a
    campaign nobody is going to finish, and excluding it would leave exactly the abandoned
    expansion this cutoff exists to bound.

    The difference from ``vendor_usage`` worth naming is the one
    :func:`_membership_events_due` names: these rows CAN carry a ``telegram_user_id``, and
    the way that id leaves is ``/forget``'s anonymisation, not this predicate.
    """
    return BroadcastRecipientRow.created_at <= cutoff


def _chat_bodies_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        ChatMessageRow.text_expires_at <= now,
        ChatMessageRow.body.is_not(None),
        ChatMessageRow.body_purged_at.is_(None),
    )


def _chat_messages_due(now: datetime) -> sa.ColumnElement[bool]:
    return ChatMessageRow.expires_at <= now


def rows_past_expiry_statements(
    *,
    now: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> tuple[tuple[str, sa.Select[tuple[int]]], ...]:
    """``(report field name, COUNT statement)`` for every clock, unbounded by ``batch_size``.

    This is what ``GET /api/retention``'s ``rowsPastExpiry`` is built from, and it is the
    number an operator actually wants: ``has_work_remaining`` only says "a batch came back
    full", which answers *whether* to run again but never *how far behind* the sweep is.

    The keys are ``PurgeReport`` field names so a caller can line the backlog up against
    the last run's counts without a translation table in between.
    """
    return (
        ("assets_deleted", _count_of(AssetRow, _assets_due(now))),
        ("brief_notes_purged", _count_of(BriefRow, _brief_notes_due(now))),
        ("brief_identities_purged", _count_of(BriefRow, _brief_identities_due(now))),
        (
            "attempt_identities_purged",
            _count_of(GenerationAttemptRow, _attempt_identities_due(now)),
        ),
        (
            "attempt_transcripts_purged",
            _count_of(GenerationAttemptRow, _attempt_transcripts_due(now)),
        ),
        ("name_records_deleted", _count_of(NameRecordRow, _name_records_due(now))),
        (
            "abandoned_orders_deleted",
            _count_of(OrderRow, _abandoned_orders_due(policy.abandoned_draft_cutoff(now))),
        ),
        ("audit_reasons_purged", _count_of(AdminAuditRow, audit_reasons_due(now))),
        ("audit_rows_deleted", _count_of(AdminAuditRow, audit_rows_due(now))),
        ("admin_sessions_deleted", _count_of(AdminSessionRow, admin_sessions_due(now))),
        (
            "purge_runs_deleted",
            _count_of(PurgeRunRow, _purge_runs_due(now - timedelta(days=PURGE_RUN_RETENTION_DAYS))),
        ),
        (
            "vendor_usage_deleted",
            _count_of(
                VendorUsageRow,
                _vendor_usage_due(now - timedelta(days=VENDOR_USAGE_RETENTION_DAYS)),
            ),
        ),
        (
            "membership_events_deleted",
            _count_of(
                BotMembershipEventRow,
                _membership_events_due(now - timedelta(days=BOT_MEMBERSHIP_RETENTION_DAYS)),
            ),
        ),
        (
            "chat_bodies_purged",
            _count_of(ChatMessageRow, _chat_bodies_due(now)),
        ),
        (
            "chat_messages_deleted",
            _count_of(ChatMessageRow, _chat_messages_due(now)),
        ),
        (
            "payme_rpc_rows_deleted",
            _count_of(
                PaymeRpcLogRow,
                _payme_rpc_log_due(now - timedelta(days=PAYME_RPC_LOG_RETENTION_DAYS)),
            ),
        ),
        (
            "payment_intents_deleted",
            _count_of(
                PaymentIntentRow,
                _terminal_intents_due(now - timedelta(days=PAYMENT_INTENT_RETENTION_DAYS)),
            ),
        ),
        (
            "broadcast_recipients_deleted",
            _count_of(
                BroadcastRecipientRow,
                _broadcast_recipients_due(now - timedelta(days=BROADCAST_RECIPIENT_RETENTION_DAYS)),
            ),
        ),
    )


def _count_of(model: type[Any], predicate: sa.ColumnElement[bool]) -> sa.Select[tuple[int]]:
    return sa.select(sa.func.count()).select_from(model).where(predicate)


async def _ids_due(session: AsyncSession, statement: sa.Select[tuple[UUID]]) -> list[UUID]:
    """Materialise a bounded id list. Selecting ids first keeps the DELETE index-driven."""
    return list((await session.execute(statement)).scalars().all())


async def _purge_assets(
    session: AsyncSession, *, now: datetime, limit: int
) -> tuple[tuple[str, ...], int]:
    """Delete expired asset rows, returning the storage keys the caller must clean up.

    Rows written since ``repository._replace_assets`` learned to record ``storage_key``
    carry the key the archive actually used. Rows written before it do not, and deleting
    them was how archived audio outlived its retention clock: the row was the only record
    of where the bytes were, and it went away without saying. For those the key is
    RECONSTRUCTED from the two columns that do survive — ``order_id`` and ``path`` — through
    the same :func:`bayram.storage.archive_key` the ``put`` used, so the historical archive is
    reachable too rather than only the archive from here on.

    ``Path(path).name`` is validated before it is used. A stored path is data, not code
    (admin plan rule 9), and this function's output is handed straight to an object store's
    delete; a filename carrying a slash or a traversal segment would turn a retention sweep
    into a delete primitive aimed at whatever the caller's key namespace can address.

    Caveat worth knowing at the reading end: a reconstructed key is a well-founded GUESS
    that an object exists, not a record that one does. Archival is best effort, so a
    legacy row may name bytes that were never written.
    """
    rows = (
        await session.execute(
            sa.select(AssetRow.id, AssetRow.storage_key, AssetRow.order_id, AssetRow.path)
            .where(_assets_due(now))
            .order_by(AssetRow.expires_at)
            .limit(limit)
        )
    ).all()
    if not rows:
        return (), 0
    asset_ids = [row_id for row_id, _, _, _ in rows]
    keys = tuple(
        key
        for _, stored, order_id, path in rows
        if (key := stored or _legacy_key(order_id, path)) is not None
    )
    await session.execute(sa.delete(AssetRow).where(AssetRow.id.in_(asset_ids)))
    return keys, len(asset_ids)


#: What a filename written by ``pipeline.assets`` may look like: ``song.mp3``,
#: ``greeting-1.ogg``, ``lyrics.txt``. Deliberately narrow — this is a read of untrusted
#: stored data whose result becomes an object-store key.
_ARCHIVED_FILENAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _legacy_key(order_id: UUID, path: str) -> str | None:
    """The archive key for a row written before ``storage_key`` was recorded, or ``None``.

    ``None`` — rather than a best-effort key — whenever the filename is not a shape the
    pipeline produces. An unrecognised name means the reconstruction's premise does not
    hold, and a purge that reports "no key" is recoverable where one that reports a wrong
    key is a delete aimed somewhere nobody chose.
    """
    filename = PurePosixPath(path).name
    if not _ARCHIVED_FILENAME.match(filename):
        return None
    return archive_key(order_id, filename)


async def _purge_brief_notes(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Clear the recipient's free-text facts — the note AND the approved lyric.

    The predicate is an ``OR`` because a brief may carry only one of the two: a customer
    who skipped the note but approved a lyric must still be swept, and the lyric is free
    text about a real person exactly as the note is.

    **Idempotency rests on the two columns being nulled in the same statement.** Unlike
    :func:`_purge_attempt_identities` this sweep has no ``note_purged_at IS NULL`` guard; a
    purged row is skipped on the next run only because the ``OR`` no longer matches. Nulling
    one column and not the other would make the nightly job re-select the same rows forever.
    """
    due = await _ids_due(
        session,
        sa.select(BriefRow.id)
        .where(_brief_notes_due(now))
        .order_by(BriefRow.note_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(BriefRow)
        .where(BriefRow.id.in_(due))
        .values(note=None, approved_lyrics=None, note_purged_at=now)
    )
    return len(due)


async def _purge_brief_identities(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Clear the recipient's name, script and candidate orthographies.

    ``identity_purged_at`` is set so the row can prove it was purged on schedule. An
    absent name and an absent audit trail look identical, and only one of them is
    defensible to a regulator.

    ``approved_lyrics`` is nulled here as well as in :func:`_purge_brief_notes`. The lyric
    names the recipient in its hook, so it must not outlive the identity clock under a
    policy whose note clock is the longer of the two. This sweep does not stamp
    ``note_purged_at``: the note clock has not necessarily run, and the audit column must
    keep meaning "the note sweep visited this row".
    """
    due = await _ids_due(
        session,
        sa.select(BriefRow.id)
        .where(_brief_identities_due(now))
        .order_by(BriefRow.identity_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(BriefRow)
        .where(BriefRow.id.in_(due))
        .values(
            recipient_name_raw=None,
            recipient_name_display=None,
            recipient_lookup_key=None,
            recipient_script=None,
            recipient_language=None,
            recipient_candidates=None,
            approved_lyrics=None,
            identity_purged_at=now,
        )
    )
    return len(due)


async def _purge_attempt_identities(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Null the name text on render attempts, keeping strategy, rank and verdict.

    This is the whole reason the tuning table survives a retention review: what is deleted
    is the person, and what remains is the measurement.
    """
    due = await _ids_due(
        session,
        sa.select(GenerationAttemptRow.id)
        .where(_attempt_identities_due(now))
        .order_by(GenerationAttemptRow.identity_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(GenerationAttemptRow)
        .where(GenerationAttemptRow.id.in_(due))
        .values(
            name_candidate_text=None,
            stt_transcript=None,
            identity_purged_at=now,
            # The text clock owns ``stt_transcript``, and this sweep is nulling it: stamping
            # only ``identity_purged_at`` left the transcript deleted with no proof of when.
            # That is the backlog case — every historical row on the first run of a system
            # whose 90-day identity clock has already passed — so the transcript sweep never
            # reaches it (its predicate needs ``stt_transcript IS NOT NULL``) and the column
            # stays NULL forever. The data goes either way; only the audit trail was lost.
            text_purged_at=now,
        )
    )
    return len(due)


async def _purge_attempt_transcripts(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Null the song transcript on render attempts, on the free-text clock.

    Separate from :func:`_purge_attempt_identities` because it runs sixty days earlier and
    clears a different thing: the identity sweep is about the recipient's NAME, this one is
    about the words of the song, which the customer may have written themselves. Keeping
    them apart is what lets the name text stay long enough to tune the candidate ladder
    while the free text goes when the brief's free text goes.
    """
    due = await _ids_due(
        session,
        sa.select(GenerationAttemptRow.id)
        .where(_attempt_transcripts_due(now))
        .order_by(GenerationAttemptRow.text_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(GenerationAttemptRow)
        .where(GenerationAttemptRow.id.in_(due))
        .values(stt_transcript=None, text_purged_at=now)
    )
    return len(due)


async def _purge_name_records(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Delete expired dictionary entries.

    Only ``user_confirmed`` rows ever carry an ``expires_at``; a curated entry is a
    licensed work product with no personal data in it and no clock on it, and the
    ``IS NOT NULL`` guard is what keeps the moat from eroding.
    """
    due = await _ids_due(
        session,
        sa.select(NameRecordRow.id)
        .where(_name_records_due(now))
        .order_by(NameRecordRow.expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(NameRecordRow).where(NameRecordRow.id.in_(due)))
    return len(due)


async def _purge_abandoned_orders(session: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Delete drafts the user never completed, with their brief and any part-built assets.

    The child rows are removed explicitly rather than left to ``ON DELETE CASCADE``: SQLite
    does not enforce foreign keys unless asked to, so a cascade that works in Postgres and
    silently does nothing in the test suite is exactly the divergence that lets a bug ship.

    Render attempts are detached, not deleted. They outlive their order on purpose — the
    tuning signal is the point of the table, and it must not evaporate on the first purge.
    """
    due = await _ids_due(
        session,
        sa.select(OrderRow.id)
        .where(_abandoned_orders_due(cutoff))
        .order_by(OrderRow.created_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(GenerationAttemptRow)
        .where(GenerationAttemptRow.order_id.in_(due))
        .values(order_id=None)
    )
    await session.execute(sa.delete(BriefRow).where(BriefRow.order_id.in_(due)))
    await session.execute(sa.delete(AssetRow).where(AssetRow.order_id.in_(due)))
    await session.execute(sa.delete(OrderRow).where(OrderRow.id.in_(due)))
    return len(due)


async def _purge_purge_runs(session: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Delete sweep records older than ``cutoff``. The bookkeeping must not outgrow the data.

    A table written once an hour forever is a table that eventually costs more than the
    rows it accounts for, so the sweep sweeps itself. It is the LAST sweep in the run on
    purpose: the count it produces belongs to the report of the run that produced it, and
    running it first would delete rows that the current run is about to be judged against.

    The row this run is about to write does not exist yet — the job writes it after
    ``purge_expired`` returns — so there is no self-deletion hazard to guard against, and
    ``cutoff`` is a year in the past regardless.
    """
    due = await _ids_due(
        session,
        sa.select(PurgeRunRow.id)
        .where(_purge_runs_due(cutoff))
        .order_by(PurgeRunRow.ran_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(PurgeRunRow).where(PurgeRunRow.id.in_(due)))
    return len(due)


async def _purge_vendor_usage(session: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Delete vendor telemetry older than ``cutoff``. Bounded growth, not a legal clock.

    One row is written per vendor call, which on a busy order is half a dozen, so this table
    grows faster than anything else the sweep touches and would eventually cost more to store
    than the orders it accounts for. Thirteen months is the shortest window that still
    answers "is this month dearer than the same month last year", which is most of what an
    operator opens the Vendors screen to find out.

    Nothing personal is deleted here — see :data:`VENDOR_USAGE_RETENTION_DAYS` — so unlike
    the identity sweeps there is no proof-of-purge column to stamp and nothing to null in
    place: the row goes whole.
    """
    due = await _ids_due(
        session,
        sa.select(VendorUsageRow.id)
        .where(_vendor_usage_due(cutoff))
        .order_by(VendorUsageRow.created_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(VendorUsageRow).where(VendorUsageRow.id.in_(due)))
    return len(due)


async def _purge_membership_events(session: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Delete churn transitions older than ``cutoff``. Bounded growth, not a legal clock.

    Thirteen months is the shortest window that still answers "did we lose more customers
    this March than last March", which is the whole reason the transition log exists rather
    than the denormalised ``users.blocked_bot_at`` gauge alone.

    Nothing here is nulled in place, unlike the identity sweeps: the row goes whole. The
    ``telegram_user_id`` these rows can carry is removed on request by
    ``bayram.db.credit_erasure.forget_account``'s anonymisation arm — see
    :data:`BOT_MEMBERSHIP_RETENTION_DAYS` — and this cutoff bounds how long one can sit here
    at all rather than standing in for that.
    """
    due = await _ids_due(
        session,
        sa.select(BotMembershipEventRow.id)
        .where(_membership_events_due(cutoff))
        .order_by(BotMembershipEventRow.at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(BotMembershipEventRow).where(BotMembershipEventRow.id.in_(due)))
    return len(due)


async def _purge_payme_rpc_log(session: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Delete rail-call journal rows older than ``cutoff``. Bounded growth, not a legal clock.

    Ninety days rather than the thirteen months every other cutoff here uses, because this
    journal answers incident questions rather than historical ones — see
    :data:`PAYME_RPC_LOG_RETENTION_DAYS`. It is also the fastest-growing table on the payment
    path: the rail resends every call it does not get a clean answer to, so a single stuck
    transaction can write dozens of rows on its own.

    Nothing personal is deleted here — the table holds no telegram id, no request body and no
    header — so unlike the identity sweeps there is no proof-of-purge column to stamp and
    nothing to null in place: the row goes whole.
    """
    due = await _ids_due(
        session,
        sa.select(PaymeRpcLogRow.id)
        .where(_payme_rpc_log_due(cutoff))
        .order_by(PaymeRpcLogRow.at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(PaymeRpcLogRow).where(PaymeRpcLogRow.id.in_(due)))
    return len(due)


async def _purge_terminal_intents(session: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Delete abandoned payment intents older than ``cutoff``. **Never a paid one.**

    The predicate is :func:`_terminal_intents_due`, which carries the argument: a ``paid``
    intent is the join between a rail-side transaction and the receipt it paid for, and the
    rail may still ask about that transaction, so deleting one would make us answer "that
    payment never existed" about money somebody really paid. Only ``cancelled`` and
    ``expired`` rows — payment pages that were opened and never paid — are swept.

    ``payme_transactions`` is on NO bound at all and is deliberately untouched by this sweep
    or any other; see the module docstring. The rows deleted here therefore never have a
    transaction pointing at them: a transaction exists only where the rail created one, which
    moves the intent to ``awaiting`` and then to ``paid`` or back to ``pending``, and an
    intent that reached ``paid`` is excluded above. A ``cancelled`` intent CAN have a
    cancelled transaction behind it, and the transaction outliving the intent is the intended
    asymmetry rather than an oversight — the money record survives the offer record, exactly
    as a receipt survives a quote.

    The row goes whole: there is nothing personal to null in place, because ``/forget`` has
    already nulled the only column that could be, months or years earlier.
    """
    due = await _ids_due(
        session,
        sa.select(PaymentIntentRow.id)
        .where(_terminal_intents_due(cutoff))
        .order_by(PaymentIntentRow.created_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(PaymentIntentRow).where(PaymentIntentRow.id.in_(due)))
    return len(due)


async def _purge_broadcast_recipients(
    session: AsyncSession, *, cutoff: datetime, limit: int
) -> int:
    """Delete delivery rows older than ``cutoff``. Bounded growth, not a legal clock.

    Thirteen months for :data:`BROADCAST_RECIPIENT_RETENTION_DAYS`' stated reason, and this
    is the sweep whose ``batch_size`` bound earns its keep: one campaign can write forty
    thousand rows in an afternoon, so an unbounded DELETE here would take a lock on the
    largest table in the schema.

    The row goes whole, unlike the identity sweeps: there is nothing left to null in place,
    because ``/forget`` has already nulled the only column that could be — see
    :func:`bayram.db.credit_erasure.forget_account`, which is the erasure route this cutoff
    stands beside rather than replaces. The ``broadcasts`` parent is deliberately untouched:
    its six counters are the campaign's arithmetic and they must not change retroactively
    because the ledger behind them aged out.
    """
    due = await _ids_due(
        session,
        sa.select(BroadcastRecipientRow.id)
        .where(_broadcast_recipients_due(cutoff))
        .order_by(BroadcastRecipientRow.created_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(BroadcastRecipientRow).where(BroadcastRecipientRow.id.in_(due)))
    return len(due)


async def _purge_chat_bodies(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Null personal text on chat lines past text_expires_at, stamping body_purged_at."""
    due = await _ids_due(
        session,
        sa.select(ChatMessageRow.id)
        .where(_chat_bodies_due(now))
        .order_by(ChatMessageRow.text_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    statement = (
        sa.update(ChatMessageRow)
        .where(ChatMessageRow.id.in_(due))
        .values(body=None, body_purged_at=now)
    )
    await session.execute(statement)
    return len(due)


async def _purge_chat_messages(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Delete the chat message metadata skeleton past expires_at."""
    due = await _ids_due(
        session,
        sa.select(ChatMessageRow.id)
        .where(_chat_messages_due(now))
        .order_by(ChatMessageRow.expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(ChatMessageRow).where(ChatMessageRow.id.in_(due)))
    return len(due)
