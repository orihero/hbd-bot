"""Enums that belong to persistence rather than to the domain contract.

``bayram.contracts`` owns everything the rest of the system speaks. These exist only because
a row needs to record something the contract has no opinion about: where a pronunciation
came from, which vendor call produced a row, who an operator is, and what set a retention
sweep going. They are deliberately NOT added to ``contracts.py`` — nothing outside the
database, the admin panel and the tuning query needs them.

Every value here is stored through ``bayram.db.base.enum_type``, which is a
``VARCHAR(ENUM_LENGTH)``: SQLite accepts an over-length value silently and Postgres
rejects it, so ``tests/test_db/test_enum_lengths.py`` asserts the fit rather than trusting
the unit suite to notice.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

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
    # --- terms gate (IMAGE_VIDEO_SPEC §2.1) ------------------------------------
    "TermsAcceptanceSource",
    # --- image and video products (IMAGE_VIDEO_SPEC §3.2) ----------------------
    "MediaKind",
    "MediaTier",
    "MediaSku",
    "MediaJobState",
    "MediaAspect",
    "MediaBackend",
    "MediaVoiceMode",
    "MediaVoiceGender",
    "MediaScreenDecision",
    "MediaPaidVia",
    "MediaRefundState",
    "MediaInputRole",
    "MediaOutputRole",
    "MediaAttemptStage",
    "MediaAttemptStatus",
    "MediaPurchaseProvider",
    "MediaCreditReason",
    "MEDIA_OPEN_STATES",
    "MEDIA_PREPAY_STATES",
    "MEDIA_IN_FLIGHT_STATES",
    "MEDIA_TERMINAL_STATES",
    "MEDIA_UNPAID_TERMINAL_STATES",
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
    #: nothing to claw back. See :mod:`bayram.db.plan_sql`.
    PLAN_SONG = "plan_song"


class PlanKind(StrEnum):
    """Which subscription a ``plan_purchases`` row records.

    Mirrors :class:`bayram.checkout.Plan` value for value rather than importing it: ``bayram.db``
    may import ``bayram.checkout`` (it implements that module's ports), but a mapped column
    naming a type from outside persistence is how ``bayram.contracts`` acquired the import cycle
    ``bayram.entitlements`` exists to document. The two are kept in step by
    ``bayram.db.purchases``, which is the one place a :class:`bayram.checkout.Plan` becomes one of
    these.

    **A second plan needs NO migration.** ``bayram.db.base.enum_type`` renders
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
    :class:`bayram.checkout.Product` is split from :class:`bayram.checkout.Plan`: a top-up has a
    price and a credit count and NO duration, so it can never be a plan row — a
    ``plan_purchases`` row for a single song would be seen by ``plan_sql.live_plan``, would
    block the sale of a starter plan for the life of an invented end date, and would let
    ``claim_plan_song`` mint a SECOND song out of a purchase that already granted a credit
    directly.

    Mirrors the one-off half of :class:`bayram.checkout.Product` value for value rather than
    importing it, exactly as :class:`PlanKind` mirrors :class:`bayram.checkout.Plan`: a mapped
    column naming a type from outside persistence is how ``bayram.contracts`` acquired the
    import cycle ``bayram.entitlements`` exists to document.

    **A second one-off product needs NO migration.** ``bayram.db.base.enum_type`` renders a
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
# ``bayram.checkout`` value-for-value and DO NOT import it, for the reason
# :class:`PlanKind` states: ``bayram.db`` may import ``bayram.checkout`` (it implements that
# module's ports), but a MAPPED COLUMN naming a type from outside persistence is how
# ``bayram.contracts`` acquired the import cycle ``bayram.entitlements`` exists to document. The
# third has no counterpart outside this package at all, deliberately: it is the RAIL's
# state machine, and the rail's own wire integers live in ``bayram.payme.protocol`` where the
# wire is.
# ---------------------------------------------------------------------------
class IntentProduct(StrEnum):
    """Which product a ``payment_intents`` row is an unfinished purchase of.

    Mirrors :class:`bayram.checkout.Product` value for value rather than importing it — see the
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

    **A second product needs NO migration.** ``bayram.db.base.enum_type`` renders a plain
    ``VARCHAR(32)`` with ``create_constraint`` off, so a member is Python validation and no
    DDL — the same property revision 0015 relies on for ``CreditReason``.
    """

    SINGLE = "single"
    STARTER = "starter"


class PaymentIntentState(StrEnum):
    """Where one started-but-unfinished payment has got to. Five states, one of them subtle.

    Mirrors :class:`bayram.checkout.PaymentIntentState` value for value rather than importing
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
    RAIL's vocabulary and belong at the wire boundary, in ``bayram.payme.protocol``, where a
    change to them is a protocol change; if they were the stored representation, every
    migration and every ad-hoc query would silently depend on a third party's numbering.

    ``cancel_reason`` on the same table takes the OPPOSITE decision and stays a bare integer.
    That is not an inconsistency: see
    :class:`bayram.db.models.payme_transaction.PaymeTransactionRow`, which argues it. The short
    version is that a state is OURS to name and a cancel reason is theirs to define, and
    mirroring theirs in a VARCHAR would be a translation table whose only possible failure mode
    is emitting a value the rail does not recognise.

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
    #: The media review queue (IMAGE_VIDEO_SPEC §6.6, §8). A release is ``moderation.approve``
    #: against ``subject_type="media_job"``. ``moderation.hold`` is an operator stopping a
    #: screened output on its way out. A refund is TWO rows, per D14/D25: the INTENT
    #: (``moderation.refund``) written in the transaction that records the decision, and the
    #: OUTCOME (``moderation.refund.outcome``) written after the worker was asked to carry it
    #: out — ``ok``, or ``error`` when the enqueue failed and ``media_sweep`` will. Longest is
    #: 25 characters, inside ``ENUM_LENGTH`` (32).
    MODERATION_HOLD = "moderation.hold"
    MODERATION_REFUND = "moderation.refund"
    MODERATION_REFUND_OUTCOME = "moderation.refund.outcome"
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
    #: An operator closed the redirect rail to NEW checkouts, and opened it again. Two
    #: members rather than one with a boolean payload, because the audit log's whole value is
    #: that "who switched sales off, and when" is an indexed equality filter on ``action``
    #: instead of a scan that has to parse a field. ``subject_type`` is ``"config"`` with
    #: ``subject_id="payme_rail"``: the pause is a Redis key the bot's checkout path consults,
    #: which is configuration and is not a payment — filing it under ``payment`` would put a
    #: deployment-wide switch in the same population as one customer's money.
    RAIL_PAUSED = "rail.paused"
    RAIL_RESUMED = "rail.resumed"
    #: An operator re-enqueued the settlement confirmation for ONE paid intent — the message
    #: the customer was already owed and did not get. It mints nothing and moves no money, so
    #: it is deliberately not a ``credit.grant``; the row exists because "who told this
    #: customer, and when" is the first question of the support call that follows.
    PAYMENT_NOTIFY = "payment.notify"
    #: The four things an operator does to a support ticket from the panel. Four members
    #: rather than one ``ticket.update`` with the verb in a field, for this enum's founding
    #: reason: "show me every reply we sent this week" has to be an indexed equality on
    #: ``action``, and an investigation under time pressure must not have to parse
    #: ``field_names`` to tell a note nobody saw from a message we put in a customer's phone.
    #:
    #: ``ticket.reply`` is the one of the four that leaves the building, and it is filed here
    #: rather than under a reveal or a broadcast action because it is neither: it discloses
    #: nothing about anybody and it reaches exactly one person, who asked. ``ticket.note`` is
    #: its deliberate opposite — an internal line the customer never sees — and keeping the
    #: two apart in the taxonomy is what makes "was this ever actually answered?" a query.
    #:
    #: All four are ``subject_type="ticket"`` with the ticket's UUID as the subject; see
    #: ``bayram.db.admin.audit.SUBJECT_TYPES``. Longest value is 13 characters, well inside
    #: ``ENUM_LENGTH`` (32).
    TICKET_STATUS = "ticket.status"
    TICKET_NOTE = "ticket.note"
    TICKET_REPLY = "ticket.reply"
    TICKET_ASSIGN = "ticket.assign"
    #: Where every FUTURE ticket card is posted, chosen and unchosen from the panel
    #: (``SUPPORT_TICKETS_SPEC §3.8``). Not a ``ticket.*`` member and not filed under them:
    #: those four are one operator acting on ONE customer's complaint, and these two are a
    #: deployment-wide setting that decides where the next thousand complaints are published.
    #: Folding them in would make "show me everything we did to tickets this week" return the
    #: act that redirected all of them, which is the opposite of what that filter is for.
    #:
    #: **Two members and not one ``support.group.set`` with the chat in a field**, for this
    #: enum's founding reason: "who turned the support inbox off, and when" has to be an
    #: indexed equality on ``action`` rather than a scan that parses ``field_names``. Clearing
    #: is the one that stops cards being posted at all, so it is the one an incident review
    #: looks for first, and it must not be hidden inside the same value as a routine move.
    #:
    #: ``subject_type`` is ``"bot_chat"`` with ``bot_chats.chat_id`` as the subject — for the
    #: clear, the chat that WAS selected, because "nothing" is not a subject and a row whose
    #: subject is null has lost the only fact worth having. Not ``"config"``: the pause switch
    #: is a Redis key with no row behind it, while this names a row in a table the panel lists.
    #: See ``bayram.db.admin.audit.SUBJECT_TYPES``. Longest value is 20 characters, inside
    #: ``ENUM_LENGTH`` (32).
    SUPPORT_GROUP_SELECT = "support.group.select"
    SUPPORT_GROUP_CLEAR = "support.group.clear"


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


class TermsAcceptanceSource(StrEnum):
    """Which screen a ``terms_acceptances`` row was accepted on (IMAGE_VIDEO_SPEC §2.1, §3.2.1).

    ``ONBOARDING`` is the ``Onboarding.terms`` step a new account passes through between the
    language picker and the contact screen; ``GATE`` is the inbound gate that stops an
    account already onboarded until it accepts the current versions. The column is
    ``VARCHAR(16)`` with no CHECK, so a third screen is Python validation and no DDL.
    """

    ONBOARDING = "onboarding"
    GATE = "gate"


# ---------------------------------------------------------------------------
# Image and video products (IMAGE_VIDEO_SPEC §3.2, D20–D25)
# ---------------------------------------------------------------------------
# Every column below is ``VARCHAR`` with no CHECK (``enum_type``), so a new member is Python
# validation and no DDL — the same footing as every other enum in this module.


class MediaKind(StrEnum):
    """What a ``media_jobs`` row produces. One open request per (account, kind) (§7.6)."""

    IMAGE = "image"
    VIDEO = "video"


class MediaTier(StrEnum):
    """The video tier (D22, O2). ``STANDARD`` is the local Wan render; ``FAST`` is Higgsfield."""

    STANDARD = "standard"
    FAST = "fast"


class MediaSku(StrEnum):
    """What is sold, and the scope a refund credit is spendable in (§7.1, D25).

    A media credit is SKU-scoped: a failed video refunds a video, never an image and never a
    song, which is why ``media_credit_balances`` is keyed on (account, sku).
    """

    IMAGE = "image"
    VIDEO_STANDARD = "video_standard"
    VIDEO_FAST = "video_fast"


class MediaJobState(StrEnum):
    """The job state machine (IMAGE_VIDEO_SPEC §3.3). ``DRAFTING`` is video-only (§2.4.1).

    Forward-only. Every move after ``PAID`` is a conditional ``UPDATE … WHERE state IN
    (expected)``, and no path moves a terminal row back into :data:`MEDIA_OPEN_STATES` — the
    partial unique index over those states could otherwise fire inside the Payme money
    commit (§3.2.2, §7.2). The one backward move is pre-pay and between open states: a video
    whose own voice note ffprobe finds over the clip goes ``screening → drafting`` for 🎙
    record again (§5.4, M4.1).
    """

    DRAFTING = "drafting"
    SCREENING = "screening"
    QUOTED = "quoted"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    QUEUED = "queued"
    GENERATING = "generating"
    POST = "post"
    HELD = "held"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


#: Nothing has been paid for yet: ``/forget`` cancels these, and freezing a new draft cancels
#: an earlier one (§2.3.1, §9.3).
MEDIA_PREPAY_STATES: Final[frozenset[MediaJobState]] = frozenset(
    {
        MediaJobState.DRAFTING,
        MediaJobState.SCREENING,
        MediaJobState.QUOTED,
        MediaJobState.AWAITING_PAYMENT,
    }
)

#: Paid and not finished: ``/forget`` stamps ``forget_requested_at`` and the next stage
#: boundary purges instead of delivering (§9.3).
MEDIA_IN_FLIGHT_STATES: Final[frozenset[MediaJobState]] = frozenset(
    {
        MediaJobState.PAID,
        MediaJobState.QUEUED,
        MediaJobState.GENERATING,
        MediaJobState.POST,
        MediaJobState.HELD,
        MediaJobState.DELIVERING,
    }
)

#: The partial unique index's predicate set: one OPEN request per (account, kind) (§7.6).
MEDIA_OPEN_STATES: Final[frozenset[MediaJobState]] = MEDIA_PREPAY_STATES | MEDIA_IN_FLIGHT_STATES

#: Where a job ends. Setting any of these also moves ``text_expires_at`` to terminal + 30 d.
MEDIA_TERMINAL_STATES: Final[frozenset[MediaJobState]] = frozenset(
    {
        MediaJobState.DELIVERED,
        MediaJobState.FAILED,
        MediaJobState.REJECTED,
        MediaJobState.CANCELLED,
        MediaJobState.ABANDONED,
    }
)

#: Terminal rows no money ever reached. The purge deletes them whole after their text clock
#: runs out (§3.2.4); a delivered or failed job is a paid job's record and keeps its row.
MEDIA_UNPAID_TERMINAL_STATES: Final[frozenset[MediaJobState]] = frozenset(
    {MediaJobState.REJECTED, MediaJobState.CANCELLED, MediaJobState.ABANDONED}
)


class MediaAspect(StrEnum):
    """The customer's aspect pick (O15). Default ``PORTRAIT``; the value is the ratio itself."""

    PORTRAIT = "9:16"
    SQUARE = "1:1"
    LANDSCAPE = "16:9"


class MediaBackend(StrEnum):
    """Which generation backend a job was submitted to, stamped at submit (O18, §4.5)."""

    LOCAL = "local"
    HIGGSFIELD = "higgsfield"
    FAL = "fal"
    FAKE = "fake"


class MediaVoiceMode(StrEnum):
    """Video narration (O3, D23): none, AI voice on the customer's text or on LLM text, or
    the customer's own voice note muxed as-is. Never a clone."""

    NONE = "none"
    AI_USER = "ai_user"
    AI_LLM = "ai_llm"
    OWN = "own"


class MediaVoiceGender(StrEnum):
    """Which house voice an AI narration uses (§2.4.2, Q14)."""

    FEMALE = "female"
    MALE = "male"


class MediaScreenDecision(StrEnum):
    """A guard verdict as stored on the job (IMAGE_VIDEO_SPEC §6.3). Fail-closed: only
    ``ALLOW`` lets a job proceed; ``UNAVAILABLE`` is a guard that did not answer."""

    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"
    UNAVAILABLE = "unavailable"


class MediaPaidVia(StrEnum):
    """How a job was paid for (§7.2). **There is no ``stub`` member**: a media SKU is never
    charged on the stub rail — it is free beta (``BETA``) or it is not offered (§7.4)."""

    PAYME = "payme"
    CREDIT = "credit"
    BETA = "beta"


class MediaRefundState(StrEnum):
    """The refund latch (§3.2.2). NULL → ``DUE`` is claimed by a conditional UPDATE before
    the ledger row is written, so a job refunds at most once whatever the reason."""

    DUE = "due"
    GRANTED = "granted"


class MediaInputRole(StrEnum):
    """What an uploaded or derived input is. ``COLLAGE`` is built from the photos (§4.4)."""

    PHOTO = "photo"
    VOICE_NOTE = "voice_note"
    COLLAGE = "collage"


class MediaOutputRole(StrEnum):
    """What a stored output is. ``VIDEO_RAW`` and ``NARRATION`` are intermediates with a
    24-hour clock; ``IMAGE`` and ``VIDEO`` are what the customer receives (§3.2.4)."""

    IMAGE = "image"
    VIDEO_RAW = "video_raw"
    NARRATION = "narration"
    VIDEO = "video"


class MediaAttemptStage(StrEnum):
    """Which stage a ``media_attempts`` row measures (§3.2.2)."""

    SCREEN = "screen"
    SCRIPT = "script"
    IMAGE = "image"
    VIDEO = "video"
    TTS = "tts"
    STT = "stt"
    MUX = "mux"
    OUTPUT_SCREEN = "output_screen"


class MediaAttemptStatus(StrEnum):
    """One attempt's lifecycle (§3.3). ``SUBMITTING`` is written BEFORE the POST; a
    ``SUBMITTING`` row with no ``remote_id`` found on re-entry is never re-POSTed but marked
    ``AMBIGUOUS`` and reconciled (R7)."""

    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"


class MediaPurchaseProvider(StrEnum):
    """The rail on a ``media_purchases`` receipt. No ``stub``, for :class:`MediaPaidVia`'s
    reason."""

    PAYME = "payme"
    BETA = "beta"
    CREDIT = "credit"


class MediaCreditReason(StrEnum):
    """Why a ``media_credit_ledger`` row moved a kind-scoped balance (§3.2.2, §7.5, O13).

    Every reason but ``SPENT`` is a +1 refund; ``ADMIN_CORRECTION`` may go either way and is
    the one refund reason outside the one-refund-per-job unique index.
    """

    GENERATION_FAILED = "generation_failed"
    OUTPUT_BLOCKED = "output_blocked"
    DEADLINE = "deadline"
    LATE_SETTLEMENT = "late_settlement"
    SPENT = "spent"
    ADMIN_CORRECTION = "admin_correction"


class MediaReviewSource(StrEnum):
    """Why a ``moderation_reviews`` row was opened (IMAGE_VIDEO_SPEC §6.6).

    ``OUTPUT_REVIEW`` is the L4 guard answering ``review``; ``GUARD_UNAVAILABLE`` is the L4
    guard not answering for 30 minutes (§6.4); ``MANUAL`` is an operator's hold. Appeals and
    the 2% sampled audit are later sources and need no DDL (``VARCHAR``, no CHECK).
    """

    OUTPUT_REVIEW = "output_review"
    GUARD_UNAVAILABLE = "guard_unavailable"
    MANUAL = "manual"


class MediaReviewDecision(StrEnum):
    """How a review ended. NULL on the row is *pending* (§6.6).

    ``RELEASED`` delivers the held outputs; ``BLOCKED`` confirms the block — the job fails
    and a paid one gets one SKU-scoped credit (§7.5, D25); ``EXPIRED`` is the 24 h SLA
    running out with nobody deciding, which ends exactly like ``BLOCKED``.
    """

    RELEASED = "released"
    BLOCKED = "blocked"
    EXPIRED = "expired"


class MediaLegalHoldDecision(StrEnum):
    """The escalation owner's reporting decision on a CSAM-class hold (IMAGE_VIDEO_SPEC §6.7).

    Recorded with ``python -m bayram.tools.media legal-hold``. ``HANDOVER`` — the bytes go to
    the authorities — stops the legal-hold purge from deleting them at
    ``legal_hold_expires_at``; ``DELETE`` brings that clock forward to now. Either way the
    rows keep the hash and metadata. NULL is "not decided yet": the 72 h clock runs.
    """

    HANDOVER = "handover"
    DELETE = "delete"
