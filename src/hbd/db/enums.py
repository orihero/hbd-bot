"""Enums that belong to persistence rather than to the domain contract.

``hbd.contracts`` owns everything the rest of the system speaks. These exist only because
a row needs to record something the contract has no opinion about: where a pronunciation
came from, which vendor call produced a row, who an operator is, and what set a retention
sweep going. They are deliberately NOT added to ``contracts.py`` — nothing outside the
database, the admin panel and the tuning query needs them.

Every value here is stored through ``hbd.db.base.enum_type``, which is a
``VARCHAR(ENUM_LENGTH)``: SQLite accepts an over-length value silently and Postgres
rejects it, so ``tests/test_db/test_enum_lengths.py`` asserts the fit rather than trusting
the unit suite to notice.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "NameSource",
    "GenerationKind",
    "AdminRole",
    "PurgeTrigger",
    "CreditEntryKind",
    "CreditReason",
    "PlanKind",
    "TopupKind",
    # --- the redirect rail (DECISIONS.md D11, PAYME_INTEGRATION §2) -------------
    "IntentProduct",
    "PaymentIntentState",
    "PaymeState",
    # --- admin audit log (ADMIN_PANEL_PLAN §5.1) -------------------------------
    "AuditAction",
    "AuditReasonCode",
    # --- chat logging (ADMIN_PANEL_PLAN §5.7) ----------------------------------
    "ChatDirection",
    "ChatMessageKind",
]


class NameSource(StrEnum):
    """Provenance of a ``name_records`` row.

    Provenance is load-bearing, not bookkeeping: a curated entry may be redistributed,
    an LLM-generated one is a guess to be verified, and a user-confirmed one is personal
    data with a retention clock (SoW FR-95, DAT-3).
    """

    CURATED = "curated"
    USER_CONFIRMED = "user_confirmed"
    LLM_GENERATED = "llm_generated"
    G2P = "g2p"

    @property
    def is_personal_data(self) -> bool:
        """True when the row came from a real user and therefore expires."""
        return self is NameSource.USER_CONFIRMED


class GenerationKind(StrEnum):
    """What a ``generation_attempts`` row is an attempt at.

    ``NAME_VERIFICATION`` is not a vendor render — it is the STT verdict on a rendered
    name chunk. It lives in the same table because the tuning question ("did strategy X
    survive verification?") needs the render and its verdict side by side.
    """

    SONG = "song"
    SONG_INPAINT = "song_inpaint"
    GREETING = "greeting"
    LYRICS = "lyrics"
    NAME_PREVIEW = "name_preview"
    NAME_VERIFICATION = "name_verification"
    COVER = "cover"


class AdminRole(StrEnum):
    """What an ``admin_users`` row is allowed to reach.

    Ordered most-privileged first because that is how the RBAC matrix reads, not because
    the values are comparable — ``StrEnum`` compares as text, and a permission check that
    relies on ordering is a bug waiting for a fifth role.
    """

    OWNER = "owner"
    ADMIN = "admin"
    SUPPORT = "support"
    VIEWER = "viewer"


class PurgeTrigger(StrEnum):
    """What set a retention sweep going.

    Recorded because the three are accountable differently: ``CRON`` is the routine clock,
    ``MANUAL`` is an operator who must appear in the audit log, and ``USER_REQUEST`` is a
    person exercising erasure, whose request has to be evidenced long after their data is
    gone.
    """

    CRON = "cron"
    MANUAL = "manual"
    USER_REQUEST = "user_request"


class CreditEntryKind(StrEnum):
    """What a ``credit_ledger`` row did to the balance.

    The four members are not interchangeable labels — each one is a different arithmetic
    sign, which is why ``ck_credit_ledger_delta_matches_kind`` exists: a ``DEBIT`` that
    somehow carried a positive ``delta`` would mint credits, and a ``REFUND`` with a
    negative one would burn them, and neither is a mistake a reviewer reliably spots in a
    diff. The database refuses both.

    ``CONSUME`` is the one that looks redundant and is not. It moves nothing (``delta``
    is exactly 0); it exists to mark a debit *settled*, which is what frees the in-flight
    slot derived from unsettled debits. Without a zero-delta member the only way to close
    a debit would be to refund it, and refunding a song the customer actually received is
    the exploit the settlement policy is written to avoid.
    """

    GRANT = "grant"
    DEBIT = "debit"
    REFUND = "refund"
    CONSUME = "consume"


class CreditReason(StrEnum):
    """Why a ``credit_ledger`` row was written.

    Deliberately a closed enum rather than a free-text note. Two reasons, both load-bearing:
    an operator reading a customer's history needs values a query can group by, and — more
    sharply — free text here would be text *about a person*, which would drag the ledger
    into ``tests/test_db/test_privacy_constraints.py``'s ``tables_with_personal_data`` and
    therefore onto a retention clock. An audit trail that deletes itself on a schedule
    cannot answer "why is this balance what it is" for the period that matters, so the
    ledger holds no personal data and outlives every purge instead.

    The longest value is ``order_not_delivered`` at 19 characters, comfortably inside
    ``ENUM_LENGTH`` (32) — ``tests/test_db/test_enum_lengths.py`` asserts that rather than
    trusting it, because SQLite would store an over-length value and only Postgres raises.
    """

    #: The one-off welcome allowance, minted the first time an account is opened.
    SIGNUP_ALLOWANCE = "signup_allowance"
    #: The rolling per-period allowance, keyed on a deterministic period index so a replay
    #: within the same window mints nothing.
    PERIOD_ALLOWANCE = "period_allowance"
    #: An operator comping a customer through the credits CLI.
    ADMIN_GRANT = "admin_grant"
    #: The debit taken when the worker gate authorises a render.
    ORDER_RENDER = "order_render"
    #: Terminal failure: the customer got nothing, so the debit is refunded.
    ORDER_FAILED = "order_failed"
    #: The kit reached the customer; the debit is consumed, not refunded.
    ORDER_DELIVERED = "order_delivered"
    #: The kit exists and is redeliverable but Telegram would not take it. Still consumed —
    #: refunding here is what would let someone block the bot mid-render for free songs.
    ORDER_NOT_DELIVERED = "order_not_delivered"
    #: The sweep closing a debit whose job never came back at all.
    STALE_SETTLEMENT = "stale_settlement"
    #: The shortfall covered so that a render could proceed while
    #: ``Settings.credits_enforced`` is off. The meter runs in full — account, allowance,
    #: block gate, in-flight cap, debit and settlement — but nobody is refused for having
    #: run out, so a customer whose balance is already 0 is topped up by exactly what the
    #: render costs. Counting these rows is how an operator sees what enforcement would
    #: have refused before switching it on.
    UNENFORCED_RENDER = "unenforced_render"
    #: A single song the customer BOUGHT, minted the moment a checkout provider reported the
    #: charge paid. It never expires: a top-up is money already spent, so nothing may take it
    #: back off the balance — which is exactly why plan songs are minted lazily rather than
    #: granted in a lump this reason could no longer be told apart from.
    TOPUP_PURCHASE = "topup_purchase"
    #: One song minted out of a LIVE ``plan_purchases`` row, at the instant it is charged for.
    #: There is deliberately no matching expiry reason and no sweep: a plan that runs out of
    #: days simply stops minting, so an unused plan song never became a credit and there is
    #: nothing to claw back. See :mod:`hbd.db.plan_sql`.
    PLAN_SONG = "plan_song"


class PlanKind(StrEnum):
    """Which subscription a ``plan_purchases`` row records.

    Mirrors :class:`hbd.checkout.Plan` value for value rather than importing it: ``hbd.db``
    may import ``hbd.checkout`` (it implements that module's ports), but a mapped column
    naming a type from outside persistence is how ``hbd.contracts`` acquired the import cycle
    ``hbd.entitlements`` exists to document. The two are kept in step by
    ``hbd.db.purchases``, which is the one place a :class:`hbd.checkout.Plan` becomes one of
    these.

    **A second plan needs NO migration.** ``hbd.db.base.enum_type`` renders
    ``sa.Enum(..., native_enum=False, length=32)`` — a plain ``VARCHAR(32)`` with
    ``create_constraint`` off — so adding a member changes Python validation and no DDL. That
    is the same property that lets ``CreditReason.UNENFORCED_RENDER`` exist in the enum while
    being absent from migration 0006's literal reason list, and it is why revision 0015 adds
    two ``CreditReason`` members without touching a column.
    """

    STARTER = "starter"


class TopupKind(StrEnum):
    """Which one-off product a ``topup_purchases`` row is the receipt for.

    The counterpart to :class:`PlanKind`, and split from it for the reason
    :class:`hbd.checkout.Product` is split from :class:`hbd.checkout.Plan`: a top-up has a
    price and a credit count and NO duration, so it can never be a plan row — a
    ``plan_purchases`` row for a single song would be seen by ``plan_sql.live_plan``, would
    block the sale of a starter plan for the life of an invented end date, and would let
    ``claim_plan_song`` mint a SECOND song out of a purchase that already granted a credit
    directly.

    Mirrors the one-off half of :class:`hbd.checkout.Product` value for value rather than
    importing it, exactly as :class:`PlanKind` mirrors :class:`hbd.checkout.Plan`: a mapped
    column naming a type from outside persistence is how ``hbd.contracts`` acquired the
    import cycle ``hbd.entitlements`` exists to document.

    **A second one-off product needs NO migration.** ``hbd.db.base.enum_type`` renders a
    plain ``VARCHAR(32)`` with ``create_constraint`` off, so a member is Python validation
    and no DDL.
    """

    SINGLE = "single"


# ---------------------------------------------------------------------------
# The redirect rail (DECISIONS.md D11, PAYME_INTEGRATION §2)
# ---------------------------------------------------------------------------
# A redirect rail is a payment STARTED in one process and FINISHED in another, minutes
# later, on an inbound request nobody in the first process is awaiting. The three enums
# below are the persistence half of that vocabulary. Two of them mirror a type in
# ``hbd.checkout`` value-for-value and DO NOT import it, for the reason
# :class:`PlanKind` states: ``hbd.db`` may import ``hbd.checkout`` (it implements that
# module's ports), but a MAPPED COLUMN naming a type from outside persistence is how
# ``hbd.contracts`` acquired the import cycle ``hbd.entitlements`` exists to document. The
# third has no counterpart outside this package at all, deliberately: it is the RAIL's
# state machine, and the rail's own wire integers live in ``hbd.payme.protocol`` where the
# wire is.
# ---------------------------------------------------------------------------
class IntentProduct(StrEnum):
    """Which product a ``payment_intents`` row is an unfinished purchase of.

    Mirrors :class:`hbd.checkout.Product` value for value rather than importing it — see the
    note above this block — and mirrors the WHOLE of it rather than the one-off half,
    unlike :class:`TopupKind`. That is the one respect in which this enum is not simply a
    third copy of the same idea, and it is worth saying why: an intent is a payment for
    something not yet sold, and BOTH a single song and a starter plan are sold down a
    redirect rail, so the intent has to be able to name either. Which receipt table the
    settlement then writes — ``topup_purchases`` or ``plan_purchases`` — is decided from
    this column at Perform time, which is exactly why the two members must not be collapsed
    into one "it is a purchase" value.

    The longest value is ``starter`` at 7 characters, far inside ``ENUM_LENGTH`` (32).
    ``tests/test_db/test_enum_lengths.py`` asserts that rather than trusting it: SQLite
    stores an over-length value silently and only Postgres raises.

    **A second product needs NO migration.** ``hbd.db.base.enum_type`` renders a plain
    ``VARCHAR(32)`` with ``create_constraint`` off, so a member is Python validation and no
    DDL — the same property revision 0015 relies on for ``CreditReason``.
    """

    SINGLE = "single"
    STARTER = "starter"


class PaymentIntentState(StrEnum):
    """Where one started-but-unfinished payment has got to. Five states, one of them subtle.

    Mirrors :class:`hbd.checkout.PaymentIntentState` value for value rather than importing
    it, for the reason stated above this block. The full argument for each member lives on
    that class, because that is the one the rest of the system reads; what belongs HERE is
    the property the DATABASE is responsible for, which is that ``AWAITING`` is a HOLD:

    ``AWAITING`` means a live rail-side transaction is charging a card against this exact
    intent. Every state transition out of it is written as a CONDITIONAL ``UPDATE`` whose
    ``rowcount`` is the lock — the ``credit_sql.debit_balance`` / ``plan_sql.claim_plan_song``
    primitive this schema already uses — so a second rail-side transaction for an intent
    already in this state loses the ``UPDATE`` and is refused BEFORE a second card is
    touched, rather than after. That is the whole reason the state lives in a column instead
    of being inferred from the presence of a transaction row.

    It is also what makes merchant-side expiry structurally unable to refuse a payment the
    rail still considers open: the expiry predicate is ``state = 'pending' AND valid_until
    <= :now``, so an intent under a live transaction is not in the set the sweep can see.

    The longest value is ``cancelled`` at 9 characters, well inside ``ENUM_LENGTH`` (32).
    """

    #: Handed to the customer as a URL; nothing has happened since. The ONLY state a
    #: merchant-side clock may act on.
    PENDING = "pending"
    #: A live rail-side transaction holds this intent. Exclusive; see the class docstring.
    AWAITING = "awaiting"
    #: The money is ours, and the receipt and the credit grant were written in the same
    #: transaction that moved the intent here. Terminal.
    PAID = "paid"
    #: The rail gave up, or the card declined after the hold was released. Terminal.
    CANCELLED = "cancelled"
    #: The validity window lapsed with nobody paying. Terminal.
    EXPIRED = "expired"


class PaymeState(StrEnum):
    """What the RAIL thinks of one of its own transactions, spelled as text.

    The wire carries integers — 1 created, 2 performed, -1 cancelled, -2 cancelled after a
    performed charge — and this column deliberately does not. Two reasons, and the second is
    the one that matters. (1) A ``VARCHAR`` state is readable in a ``psql`` session at three
    in the morning, when the question is "what happened to this customer's payment" and
    nobody wants to remember whether -2 means refunded or expired. (2) The integers are the
    RAIL's vocabulary and belong at the wire boundary, in ``hbd.payme.protocol``, where a
    change to them is a protocol change; if they were the stored representation, every
    migration and every ad-hoc query would silently depend on a third party's numbering.

    ``cancel_reason`` on the same table takes the OPPOSITE decision and stays a bare integer.
    That is not an inconsistency: see :class:`hbd.db.models.payme_transaction.PaymeTransactionRow`,
    which argues it. The short version is that a state is OURS to name and a cancel reason is
    theirs to define, and mirroring theirs in a VARCHAR would be a translation table whose
    only possible failure mode is emitting a value the rail does not recognise.

    The longest value is ``cancelled_after_perform`` at 23 characters — the tightest fit of
    any enum in this module against ``ENUM_LENGTH`` (32), which is precisely why
    ``tests/test_db/test_enum_lengths.py`` asserts the fit rather than eyeballing it.
    """

    #: The rail has created a transaction and is charging a card. Wire state 1.
    CREATED = "created"
    #: The charge succeeded and the money is ours. Wire state 2. Terminal.
    PERFORMED = "performed"
    #: Cancelled from ``CREATED`` — a declined card, a timeout, or the customer walking
    #: away. No money moved. Wire state -1. Terminal.
    CANCELLED = "cancelled"
    #: Cancelled AFTER a successful charge — a refund made in the rail's own cabinet. Wire
    #: state -2. Terminal, and this deployment never writes it from an inbound request: a
    #: cancel of a performed transaction is refused, because ``credit_accounts.balance`` is
    #: a single fungible scalar with no lot structure (``plan_sql``) and a reversal could
    #: debit a credit the customer paid for in a different purchase. The member exists so a
    #: manually reconciled refund has somewhere true to be recorded.
    CANCELLED_AFTER_PERFORM = "cancelled_after_perform"


# ---------------------------------------------------------------------------
# Admin audit log (ADMIN_PANEL_PLAN §5.1 and §12.4)
# ---------------------------------------------------------------------------
class AuditAction(StrEnum):
    """What an ``admin_audit_log`` row records an operator (or the system) doing.

    A **closed** taxonomy, not a free-text verb. The audit log is the one table an
    investigation reads under time pressure, and "show me every reveal this week" has to be
    an indexed equality filter rather than a guess about which spelling that quarter's code
    used. It is also what lets §12.2's matrix and this table be cross-checked: every
    step-up-gated permission has an action here that records its use.

    Values are dotted and deliberately short — the longest are ``moderation.approve`` and
    ``broadcast.schedule`` at 18 characters, comfortably inside ``ENUM_LENGTH`` (32).
    ``tests/test_db/test_enum_lengths.py`` asserts that rather than trusting it: SQLite would
    store an over-length value and only Postgres raises.
    """

    LOGIN_SUCCESS = "login.success"
    LOGIN_FAILURE = "login.failure"
    LOGIN_RATE_LIMITED = "login.limited"
    LOGOUT = "logout"
    STEP_UP_SUCCESS = "step_up.success"
    STEP_UP_FAILURE = "step_up.failure"
    SESSION_REVOKED = "session.revoked"
    REVEAL_PERSONAL = "reveal.personal"
    ASSET_STREAM = "asset.stream"
    #: One read of the dashboard's identified lists (``GET /api/metrics/dashboard/
    #: audience-lists``), which shows an ACCOUNT HOLDER's Telegram id, handle and first name
    #: with no reveal gate and no step-up. Its OWN action rather than a reuse of
    #: ``reveal.personal``, and the distinction is the reason both exist: a reveal row is a
    #: gated, budgeted, subject-scoped disclosure of one record, and an investigator filtering
    #: on ``reveal.personal`` is asking which of those were spent. These reads are neither
    #: gated nor budgeted — the log is the entire control the owner accepted in their place —
    #: so folding them in would make every reveal count a lie in the direction that hides the
    #: gated ones among the ungated. ``record_count`` carries how many identified rows the
    #: caller was shown; ``subject_type`` is ``"system"`` because the subject is a LIST and not
    #: one of the people on it.
    AUDIENCE_LIST_READ = "audience.list"
    ORDER_RETRY = "order.retry"
    ORDER_REENQUEUE = "order.reenqueue"
    ORDER_FORCE_DELIVER = "order.deliver"
    ORDER_CANCEL = "order.cancel"
    USER_BLOCK = "user.block"
    USER_UNBLOCK = "user.unblock"
    USER_PURGE_REQUESTED = "user.purge.req"
    USER_PURGE_COMPLETED = "user.purge.done"
    USER_PURGE_FAILED = "user.purge.fail"
    MODERATION_APPROVE = "moderation.approve"
    MODERATION_REJECT = "moderation.reject"
    CONFIG_VALIDATE = "config.validate"
    CONFIG_COMMIT = "config.commit"
    CONFIG_ROLLBACK = "config.rollback"
    RETENTION_EXTENDED = "retention.extended"
    RETENTION_RUN = "retention.run"
    EXPORT_AGGREGATE = "export.aggregate"
    EXPORT_ORDER = "export.order"
    EXPORT_AUDIT = "export.audit"
    ADMIN_CREATE = "admin.create"
    ADMIN_UPDATE_ROLE = "admin.role"
    ADMIN_DEACTIVATE = "admin.deactivate"
    ADMIN_PASSWORD_CHANGE = "admin.password"
    PERMISSION_DENIED = "permission.denied"
    CREDIT_GRANT = "credit.grant"
    BROADCAST_CREATE = "broadcast.create"
    BROADCAST_REVISE = "broadcast.revise"
    #: The INTENT row, written in the request transaction: an operator authorised a message
    #: to ``record_count`` accounts. Whether it landed is a different fact — see
    #: :data:`BROADCAST_SENT`.
    BROADCAST_SCHEDULE = "broadcast.schedule"
    BROADCAST_PAUSE = "broadcast.pause"
    BROADCAST_RESUME = "broadcast.resume"
    BROADCAST_CANCEL = "broadcast.cancel"
    #: The OUTCOME row, written by the worker when the run finishes, with the operator who
    #: scheduled it as the actor. Two rows and not one, because "we tried" is knowable in the
    #: request and "it landed" is only knowable an hour later.
    BROADCAST_SENT = "broadcast.sent"
    BROADCAST_TEST = "broadcast.test"


class AuditReasonCode(StrEnum):
    """Why an operator did it — structured, because the free-text version is a privacy leak.

    Every destructive action requires a reason, and the row carrying it lives 730 days in the
    one table ``purge_user`` deliberately does not touch and ``REVOKE`` makes undeletable
    (§12.4). Real support reasons read *"Dilnoza asked us to delete her mother's song"*, so a
    free-text-only reason would make the longest-clocked, purge-immune table in the system the
    place customer names accumulate. The accountability is carried by this code plus
    ``reason_ref`` (a ticket id); the optional ``reason_text`` beside them is capped, excluded
    from the chain HMAC and swept at 90 days.
    """

    CUSTOMER_REQUEST = "customer_request"
    GDPR_ERASURE = "gdpr_erasure"
    ABUSE_REPORT = "abuse_report"
    SUPPORT_INVESTIGATION = "support_investigation"
    INCIDENT = "incident"
    BAKE_OFF = "bake_off"
    ROUTINE_OPS = "routine_ops"
    OTHER = "other"


class ChatDirection(StrEnum):
    """Direction of a chat line (ADMIN_PANEL_PLAN §5.7)."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class ChatMessageKind(StrEnum):
    """Format and intent of a chat message (ADMIN_PANEL_PLAN §5.7)."""

    TEXT = "text"
    CALLBACK = "callback"
    SCREEN = "screen"
    AUDIO = "audio"
    VOICE = "voice"
    TOAST = "toast"
    ACTION = "action"

