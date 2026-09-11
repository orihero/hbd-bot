"""Persistence for the admin panel's own tables.

Split from ``bayram.db.repository`` on purpose. The kit repository owns customer data behind
a ``Result``-returning facade because a bot handler must never see an exception; these
functions instead take an ``AsyncSession`` and let it propagate, because every admin call
site already runs inside one request-scoped transaction that must roll back as a whole —
an authentication that half-succeeded is worse than one that failed loudly.

For the same reason nothing here commits. The caller owns the transaction boundary, so a
login that writes a session row and then fails to write its audit entry leaves neither.
"""

from __future__ import annotations

from bayram.db.admin import accounts, sessions
from bayram.db.admin.audience_lists import recent_subscribers, top_generators
from bayram.db.admin.balances import has_polled_vendor_balances, vendor_balances
from bayram.db.admin.credits import ledger_for_key
from bayram.db.admin.overview import (
    account_totals,
    active_accounts,
    activity_history,
    churn_counts,
    has_recorded_activity_history,
    has_recorded_churn,
    language_mix,
    new_accounts,
    new_accounts_per_bucket,
)
from bayram.db.admin.payme_rpc_log import (
    CallFilters,
    call_totals,
    calls_for_intent,
    count_calls,
    fault_clusters,
    has_recorded_inbound_call,
    last_inbound_call,
    list_calls,
)
from bayram.db.admin.payme_transactions import (
    has_recorded_transaction,
    transaction_funnel,
    transactions_for_intent,
)
from bayram.db.admin.payment_intents import (
    AttentionPopulation,
    IntentFilters,
    SettleSource,
    attention_counts,
    count_intents,
    has_opened_any_intent,
    has_settled_any_intent,
    intent_by_id,
    intent_funnel,
    latest_checkout_seen,
    list_intents,
    resolve_intent_reference,
    settlement_snapshot,
)
from bayram.db.admin.plan_purchases import (
    has_recorded_plan_revenue,
    plan_bookings_per_bucket,
    plan_liability,
    plan_revenue_totals,
    plan_utilisation,
    subscription_churn,
)
from bayram.db.admin.plan_purchases import receipt_for_key as plan_receipt_for_key
from bayram.db.admin.topup_purchases import (
    count_unpriced_topups,
    has_recorded_topup_revenue,
    topup_bookings_per_bucket,
    topup_revenue_totals,
)
from bayram.db.admin.topup_purchases import receipt_for_key as topup_receipt_for_key
from bayram.db.admin.vendor_usage import (
    cost_per_delivered_song,
    cost_per_delivered_song_by_vendor,
    cost_provenance,
    fake_call_count,
    has_priced_vendor_usage,
    has_recorded_vendor_usage,
    unattributed_spend,
    units_per_delivered_song_by_vendor,
    vendor_error_breakdown,
    vendor_operation_latency,
    vendor_spend_per_bucket,
    vendor_spend_split,
    vendor_usage_per_day,
    vendor_usage_rollup,
    vendor_usage_totals,
)

__all__ = [
    "accounts",
    "sessions",
    # The vendor spend reads, exported by name rather than as a module: they are the whole
    # of what ``bayram.db.admin.vendor_usage`` offers, and naming them here is what makes a
    # read added to that module without a caller visible from outside it.
    "vendor_usage_rollup",
    "vendor_usage_totals",
    "vendor_usage_per_day",
    "vendor_error_breakdown",
    "has_recorded_vendor_usage",
    "has_priced_vendor_usage",
    # The dashboard's aggregates, exported by name for the same reason: a read added to one
    # of these modules without a caller is visible from outside it. Grouped by the section of
    # the page each one answers, because "which card breaks if this changes" is the question
    # a reader of this list actually has.
    "vendor_spend_per_bucket",
    "vendor_spend_split",
    "cost_per_delivered_song",
    "unattributed_spend",
    "vendor_operation_latency",
    "fake_call_count",
    # The Vendor section's three: the per-vendor cut of the cost-per-song figure, the same
    # cut in the vendors' own units, and the provenance partition that says how any of it
    # was arrived at. Grouped with the spend reads above rather than with the dashboard
    # sections, because a change to ``_narrow`` moves all nine of them together.
    "cost_per_delivered_song_by_vendor",
    "units_per_delivered_song_by_vendor",
    "cost_provenance",
    "account_totals",
    "active_accounts",
    "new_accounts",
    "new_accounts_per_bucket",
    "churn_counts",
    "has_recorded_churn",
    "has_recorded_activity_history",
    # The Audience section's other two. ``language_mix`` carries its own denominator;
    # ``activity_history`` is the recorded history of ``active_accounts``' three tiles and
    # is empty rather than zero-filled on a deployment whose snapshot job has not run.
    "language_mix",
    "activity_history",
    "plan_bookings_per_bucket",
    "plan_revenue_totals",
    "plan_liability",
    "plan_utilisation",
    "has_recorded_plan_revenue",
    # Renewal over the starter plan — a RATE over ended plans, and not the same quantity as
    # ``churn_counts`` above, which counts passages through ``bot_membership_events``. The
    # panel renders both in one card; see ``AudienceResponse``'s two churn fields.
    "subscription_churn",
    "topup_bookings_per_bucket",
    "topup_revenue_totals",
    "count_unpriced_topups",
    "has_recorded_topup_revenue",
    "vendor_balances",
    "has_polled_vendor_balances",
    # The two IDENTIFIED reads, listed apart from everything above them because the
    # separation is a control and not a filing decision: every other read in this package is
    # personal-data-free and is served on ``DASHBOARD_READ`` with no masking branch, and
    # these two carry a Telegram id, a handle and a first name. They are served on
    # ``RECORDS_READ`` from their own route, which writes an audit row on every call — the
    # owner's decision was "show identity, the log is the control", so a caller that reaches
    # these functions from anywhere else has skipped the whole of that control.
    "top_generators",
    "recent_subscribers",
    # -- the redirect payment rail (PAYME_INTEGRATION §2, DECISIONS.md D11) ---------
    # Three modules, one per TABLE, exported by name for the reason the vendor block above
    # states: a read added to one of them without a caller is visible from outside it. They
    # are grouped together because a change to what the rail board asks moves all of them at
    # once, and split by the question each answers rather than by module — which is the
    # question a reader of this list actually has.
    #
    # The armed-and-idle header: what the newest intent was issued with, and the four ROW
    # probes that keep a zero from meaning two things. Every one of the probes deliberately
    # ignores the window.
    "latest_checkout_seen",
    "has_opened_any_intent",
    "has_settled_any_intent",
    "has_recorded_transaction",
    "has_recorded_inbound_call",
    "last_inbound_call",
    # The board's numbers: where payments got to, what the rail did, what settled, and what
    # is stuck. ``settlement_snapshot`` deliberately CALLS ``payme_sql.settlement_counts``
    # rather than re-deriving it, so the panel and the five-minute sweep cannot disagree.
    "intent_funnel",
    "transaction_funnel",
    "settlement_snapshot",
    "attention_counts",
    "call_totals",
    "fault_clusters",
    # The two lists and their optional totals, plus the filter shapes. ``IntentFilters``
    # carries the attention population, whose predicate is SHARED with ``attention_counts``
    # so a chip and the list it links to cannot compute one population two ways.
    "IntentFilters",
    "SettleSource",
    "AttentionPopulation",
    "list_intents",
    "count_intents",
    "CallFilters",
    "list_calls",
    "count_calls",
    # The dossier's five reads. The ROUTER makes all five inside ONE request transaction, so
    # an operator can trust the receipt and the transaction were true at the same instant —
    # the property ``payme.cli._dossier`` argues at length and the reason these are five
    # functions rather than one join. ``resolve_intent_reference`` accepts ``public_ref`` and
    # a rail transaction id and NEVER ``idempotency_key``, which embeds a Telegram id.
    "intent_by_id",
    "resolve_intent_reference",
    "transactions_for_intent",
    "topup_receipt_for_key",
    "plan_receipt_for_key",
    "ledger_for_key",
    "calls_for_intent",
]
