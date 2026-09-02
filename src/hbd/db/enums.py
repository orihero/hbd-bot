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
    # --- admin audit log (ADMIN_PANEL_PLAN §5.1) -------------------------------
    "AuditAction",
    "AuditReasonCode",
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

    Values are dotted and deliberately short — the longest is ``moderation.approve`` at 18
    characters, comfortably inside ``ENUM_LENGTH`` (32). ``tests/test_db/test_enum_lengths.py``
    asserts that rather than trusting it: SQLite would store an over-length value and only
    Postgres raises.
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
