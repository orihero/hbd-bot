"""``vendor_balances`` — the last known state of each vendor account, cached for a process
that is forbidden from asking.

Nothing polls OpenRouter or ElevenLabs for remaining credit today. The quota probe that
exists (``providers/tts/elevenlabs_api.subscription_health``) reads
``characters_remaining`` into a live in-memory ``ProviderHealth`` verdict that is never
persisted and never reaches the admin. So "are we about to run out before New Year" is a
question the panel cannot answer at all.

**THE SECURITY BOUNDARY IS THE REASON THIS IS A TABLE.** The admin process must never hold
an HTTP client and a vendor key (ADMIN_PANEL_PLAN §4.2, D10) — that is the whole argument
for running the panel as a third process. So the ARQ worker, which already holds the
credentials, polls and WRITES here, and the admin READS a table whose numbers are already
computed. A "refresh now" button is therefore not implementable as an admin-side fetch; the
only acceptable shape is the one the panel already uses for retries and re-deliveries —
enqueue an ARQ job and let the worker do it.

**WHY THIS TABLE IS MUTABLE WHERE ``vendor_usage`` IS NOT, AND WHY THAT IS NOT A
CONTRADICTION.** ``vendor_usage`` refuses ``TimestampMixin`` because its row is a
measurement of a moment that has passed and an ``updated_at`` could never be true. This row
is the opposite kind of object: a CACHE of a vendor's current state, amended by design,
where ``updated_at`` is the honest field for a row whose whole job is to be overwritten. The
history a cache discards is not lost — every probe also writes an append-only
``vendor_usage`` row with ``operation=HEALTH``, which is what that member was declared for,
and that table already carries the 400-day cutoff. The audit trail lives in the append-only
table, the latest known state lives here, and neither is asked to be the other. A second
``vendor_balance_snapshots`` history table was considered and rejected for exactly that
reason.

**WHY THE PRIMARY KEY IS ``(vendor, is_fallback)`` AND NOT A SURROGATE UUID.** A cache with
exactly one row per billing account should have that fact as its primary key, so a second
row for the same account is IMPOSSIBLE rather than merely unusual — and the upsert names
those two columns as its conflict target, so the primary key IS the ``ON CONFLICT`` target
and no separate unique index is needed. ``is_fallback`` is the same axis ``vendor_usage``
uses to tell the two OpenRouter accounts apart, for the same stated reason: both LLM
adapters report ``name="openai-compat"``. ElevenLabs takes ``(ELEVENLABS, False)`` and one
row covers music, TTS and STT, because that is how the invoice arrives.

**EVERY QUANTITY IS NULLABLE WITH NO DEFAULT, and on this table the rule bites hardest.**
A ``balance_remaining`` defaulted to 0 says "this account is empty" — the most damaging
false statement this schema could make, because OBS-10 raises SEV-1 when a capability's last
healthy provider hits zero and SEV-2 below seven days of cover. A defaulted zero pages an
on-call engineer about a deployment that has merely never polled; it is
``generation_attempts.cost_usd DEFAULT 0.0`` again, except this one reads as "stop
shipping" rather than "free".

**THE ``SubscriptionPayload`` TRAP, NAMED SO IT IS NOT WALKED INTO.**
``hbd.providers.tts.elevenlabs_api.SubscriptionPayload`` declares ``character_count: int =
0`` and ``character_limit: int = 0``. Those defaults are CORRECT there — a partial body
should read as "degraded", not crash a health verdict — and POISON here: they turn a body
that omitted the field into "0 characters remaining". The poller must parse into its own
model whose every field is ``| None``. It should still IMPORT ``SUBSCRIPTION_PATH`` and
``API_KEY_HEADER`` from that module rather than re-spelling them; it must not import that
class.

**``is_unbounded`` IS THREE-VALUED ON PURPOSE.** ``True`` means the vendor told us this key
has no cap (OpenRouter returns ``limit: null``), ``False`` means it told us there is one,
``NULL`` means it did not say. A two-valued NOT NULL column would force "we do not know" to
be spelled as one of the two answers, and both spellings are wrong: ``False`` invents a cap,
``True`` invents an unlimited account.

**THE TWO CLOCKS.** :attr:`fetched_at` answers "when was this number true?";
:attr:`checked_at` answers "when did we last look?". A failed poll advances only the second,
increments :attr:`consecutive_failures`, records the status and the error code, and touches
NOT ONE quantity. The row then reads "$12.40, measured 5h ago, last 4 probes failed" — the
operationally useful sentence. Nulling the balance on an outage would destroy the number at
the exact moment an operator needs it, and would make an outage indistinguishable from a
deployment that never polled. One ``polled_at`` would force a choice between a timestamp
that lies about the figure's age and a figure deleted the moment the vendor goes down.

**THE ONE PERMITTED ZERO.** :attr:`consecutive_failures` is NOT NULL DEFAULT 0 because it is
a COUNT, and "no probe has failed" IS a measurement — the same carve-out revision 0016 makes
for ``purge_runs.vendor_usage_deleted``, and the same one ``hbd.db.admin.vendor_usage``
makes when it exempts counts from the no-coalesce rule. :attr:`checked_at` and
:attr:`is_last_poll_ok` are NOT NULL for a different reason: no row is ever created except by
a poll attempt, so at write time both are known facts rather than measurements that might be
missing. :attr:`vendor`, :attr:`is_fallback`, :attr:`provider` and :attr:`balance_unit` are
NOT NULL because none is a measurement at all — they are the identity and the shape of the
account, known from ``Settings`` before any request leaves the box.

**WHAT IS DELIBERATELY NOT STORED.** (a) OpenRouter's ``data.label`` — the operator's own
free-text name for the API key, which in practice reads like "Sardor laptop dev key". It is
the only field on either vendor's response that could carry a person's name, it buys no tile
anything, and refusing it is what keeps the privacy classification below true rather than
nearly true. (b) "Days of cover", which the panel wants: it is ``songs_remaining ÷
delivered-orders-per-day`` and both halves are already on the wire, so storing it would
freeze a derived-from-derived figure at poll time and let it disagree with the chart beside
it.

**NOT PERSONAL DATA, AND ON NO CLOCK.** Every column is a closed enum, a number, a boolean,
an instant, a machine id, a bounded string from the VENDOR's own vocabulary (tier, status,
reset hint) or a bounded error code from the ``hbd.errors`` taxonomy. No name, no note, no
telegram id, no free text of any kind — the row is about OUR account with a vendor, not
about a customer. So the table is in NEITHER of
``tests/test_db/test_privacy_constraints.py``'s sets, recorded there as a comment rather than
left silent. **No retention cutoff either, and nothing is added to ``hbd.db.purge``:** the
primary key is a five-member enum crossed with a boolean, so the table can hold at most ten
rows ever and holds three in this deployment, and a row is UPDATEd in place rather than
appended. Registering a cutoff would schedule a predicate over a three-row table — a no-op
whose harmlessness every future reader has to re-derive — and would add a ``purge_runs``
counter that is permanently zero. :attr:`quota_resets_at` is NOT a retention clock: it is a
fact the VENDOR reports about ITS billing period, and its name deliberately avoids the
``*_expires_at`` suffix, which obliges a sweep BY NAME in
``tests/test_db/test_audit_retention.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.contracts import BalanceEstimateBasis, BalanceUnit, Vendor
from hbd.db.base import Base, TimestampMixin, UtcDateTime, enum_type

__all__ = [
    "VendorBalanceRow",
    "PROBE_NAME_LENGTH",
    "PLAN_TIER_LENGTH",
    "STATUS_LENGTH",
    "RESET_HINT_LENGTH",
    "ERROR_CODE_LENGTH",
]

#: Mirrors ``vendor_usage.PROVIDER_LENGTH``: the probe's own short name
#: (``openrouter_key``, ``elevenlabs_subscription``), ours and not the vendor's.
PROBE_NAME_LENGTH: Final[int] = 64
#: A vendor's own plan name (``creator``, ``pro``, ``scale``), with room for a longer one.
PLAN_TIER_LENGTH: Final[int] = 48
#: A vendor's own subscription status word (``active``, ``past_due``).
STATUS_LENGTH: Final[int] = 32
#: OpenRouter's ``limit_reset`` is a short phrase (``monthly``), not a sentence.
RESET_HINT_LENGTH: Final[int] = 32
#: Mirrors ``vendor_usage.ERROR_CODE_LENGTH``: a short symbolic name from the ``hbd.errors``
#: taxonomy, never a message and never a response-body excerpt.
ERROR_CODE_LENGTH: Final[int] = 48


class VendorBalanceRow(Base, TimestampMixin):
    """What one vendor account last told us, when it told us, and when we last asked."""

    __tablename__ = "vendor_balances"
    __table_args__ = (
        # The direct descendant of ``ck_vendor_usage_cost_carries_its_source``, one step
        # further on. An estimate with no basis is unreadable — nobody can tell a figure
        # derived from measured USD spend from one derived from TTS characters that exclude
        # the music leg, and the two deserve different trust — and an estimate with no
        # divisor cannot be reproduced when somebody asks why the tile said forty songs.
        # Three columns move together or none of them do, enforced by the database rather
        # than trusted to the one writer, because the writer will eventually be two.
        sa.CheckConstraint(
            "(songs_remaining IS NULL AND per_song_rate IS NULL AND estimate_basis IS NULL)"
            " OR (songs_remaining IS NOT NULL AND per_song_rate IS NOT NULL"
            " AND estimate_basis IS NOT NULL)",
            name="estimate_carries_its_basis",
        ),
        # The schema-level guarantee that makes the whole failure design safe: a quantity may
        # not exist without the instant it was measured at. It forbids the plausible-looking
        # bug — a failure path that clears ``fetched_at`` while leaving the last known
        # balance behind, producing a number with no age that a tile would render as
        # current. With it, the only two legal shapes are "no measurement at all" and "a
        # measurement plus its timestamp", so a stale value is ALWAYS readable as stale.
        # A one-directional implication and NOT a biconditional, on purpose: ``fetched_at``
        # may legitimately be set with every quantity NULL, which is a vendor that answered
        # 200 with a body reporting nothing — a successful poll of an account that told us
        # nothing, a different fact from a failed poll and one that must stay expressible.
        sa.CheckConstraint(
            "(balance_remaining IS NULL AND balance_total IS NULL AND balance_used IS NULL)"
            " OR fetched_at IS NOT NULL",
            name="a_measured_balance_carries_its_time",
        ),
        # The only column whose UPDATE clause carries an increment expression. Costs nothing
        # and makes an arithmetic mistake in the upsert a write failure rather than a
        # nonsense number on a tile.
        sa.CheckConstraint(
            "consecutive_failures >= 0", name="consecutive_failures_is_not_negative"
        ),
        # DELIBERATELY NO CONSTRAINT tying ``error_code`` to ``is_last_poll_ok``, following
        # ``vendor_usage`` exactly: over-constraining a telemetry table loses rows, a lost
        # row is a hole in the record, and a nonsensical pairing is at worst confusing. And
        # DELIBERATELY NONE tying ``is_unbounded`` to ``balance_total``, because the honest
        # combinations include ones a naive rule would reject — an uncapped key reports
        # ``is_unbounded`` TRUE with ``balance_total`` NULL, and a body that omitted the
        # field reports NULL for both.
    )

    # -- identity: the primary key, known before any request leaves the box ---
    vendor: Mapped[Vendor] = mapped_column(enum_type(Vendor), primary_key=True)
    #: The second OpenRouter account. Part of the key because the two are separate billing
    #: relationships wearing one adapter name.
    is_fallback: Mapped[bool] = mapped_column(sa.Boolean, primary_key=True)

    # -- shape: known before any poll, so NOT NULL ---------------------------
    #: Which probe writes this row: ``openrouter_key`` | ``elevenlabs_subscription``.
    provider: Mapped[str] = mapped_column(sa.String(PROBE_NAME_LENGTH), nullable=False)
    #: What the quantities below are counted in. A balance with no unit is unreadable.
    balance_unit: Mapped[BalanceUnit] = mapped_column(enum_type(BalanceUnit), nullable=False)

    # -- quantities. Every one nullable, none defaulted. ----------------------
    # NULL means "not polled", or "polled and not reported". Both are true statements about
    # a measurement nobody has; 0 is a claim nobody made. See the module docstring.
    balance_remaining: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    balance_total: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    balance_used: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    #: Three-valued on purpose — see the module docstring.
    is_unbounded: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    #: When the vendor says its own quota window rolls over. A vendor's fact about a vendor's
    #: billing period; NOT a retention clock, which is why it is not ``*_expires_at``.
    quota_resets_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: The vendor's own word for the reset cadence (``monthly``), when it gives no instant.
    quota_reset_hint: Mapped[str | None] = mapped_column(
        sa.String(RESET_HINT_LENGTH), nullable=True
    )
    plan_tier: Mapped[str | None] = mapped_column(sa.String(PLAN_TIER_LENGTH), nullable=True)
    subscription_status: Mapped[str | None] = mapped_column(sa.String(STATUS_LENGTH), nullable=True)
    #: The estimate, its divisor and its provenance. All three NULL together, or all three
    #: set, under ``ck_vendor_balances_estimate_carries_its_basis``. All three are NULL
    #: whenever the divisor could not be MEASURED — which is the SHIPPED case for
    #: OpenRouter, since all four ``HBD_LLM_*_USD_PER_MILLION_*`` rates default to 0.0, so
    #: every LLM row's ``cost_usd`` is NULL and the trailing sum is NULL. The tile then
    #: reads "needs balances", which is the honest empty state.
    songs_remaining: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    per_song_rate: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    estimate_basis: Mapped[BalanceEstimateBasis | None] = mapped_column(
        enum_type(BalanceEstimateBasis), nullable=True
    )

    # -- the two clocks ------------------------------------------------------
    #: Last SUCCESSFUL measurement. Nullable because "we have never successfully measured
    #: this account" is a real state the row must be able to hold: a row created only after
    #: a first success could not record a poller that has been failing since deploy.
    fetched_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Last ATTEMPT. NOT NULL: no row exists that a poll did not create.
    checked_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    # -- last-probe outcome --------------------------------------------------
    is_last_poll_ok: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    #: ``NULL`` for a transport failure, where no response arrived to carry a status.
    http_status: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: From the closed ``hbd.errors`` taxonomy, never a body excerpt. A ``config_invalid``
    #: with a climbing :attr:`consecutive_failures` is the state that never self-heals — a
    #: rotated or revoked key, leaving a stale figure standing that is now wrong for the new
    #: key rather than merely old — and the panel must render it LOUDER than a transient
    #: outage. Clearing the quantities on a 401 was considered and rejected: it would carve a
    #: hole in the very rule this table is built around, and an auth failure is still "we
    #: could not measure".
    error_code: Mapped[str | None] = mapped_column(sa.String(ERROR_CODE_LENGTH), nullable=True)
    #: The one permitted zero — a measured count, not an unmeasured quantity.
    consecutive_failures: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
