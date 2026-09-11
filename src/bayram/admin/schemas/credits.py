"""Wire models for the entitlement ledger: what an account holds, and every movement of it.

**Nothing on this wire is masked, and that is a property of the table rather than a decision
taken lightly.** ``credit_accounts`` and ``credit_ledger`` hold a Telegram id, two closed
enums, integers, machine-built keys and a subsystem name — no free text anywhere — which is
why both are deliberately absent from ``tables_with_personal_data`` in
``tests/test_db/test_privacy_constraints.py``. There is therefore nothing here for
``POST /reveal`` to gate and nothing for :mod:`bayram.admin.serializers.redaction` to hide; the
one identifier that appears, the Telegram id, is the value every ``/users/**`` route keys on
and that :class:`~bayram.admin.schemas.users.UserView` already ships in the clear beside its own
mask. It travels with its mask here too, so a screen that renders masked ids everywhere else
does not have to special-case this one.

**``actor`` is published, including ``admin:{username}``.** That is the column's whole purpose
— "was this account comped, and by whom?" is the question an operator opens this screen to
answer, and an answer of ``admin:•••`` sends them to the audit log for every grant. It is a
real trade and worth naming: ``admin_audit_log`` is gated at ``AUDIT_READ`` (ADMIN and above)
while this endpoint sits at ``RECORDS_READ`` (VIEWER and above), so a colleague's login name
is visible one rung lower here than in the audit trail. What is *not* visible is anything the
audit log exists to protect — no subject, no reason code, no IP, no field names — and an
operator's own username is not customer data. The alternative, masking it, was rejected
because it would make the column unable to answer the only question it is on the screen for.

**A grant is idempotent when the caller says it is.** ``requestId`` becomes the ledger's
``grant:admin:{uuid4}`` key — the shape ``models/credit_ledger.py`` already reserves — so a
retry after a timeout tops the account up once instead of twice. Omit it and the server mints
one, which is the right default for a human pressing a button and the wrong one for anything
that retries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from pydantic import Field

from bayram.admin.schemas.actions import ReasonedRequest
from bayram.admin.schemas.common import ApiModel
from bayram.admin.schemas.page import PageMeta
from bayram.admin.serializers.redaction import mask_telegram_user_id
from bayram.db.admin.views import CreditAccountState, CreditLedgerItem
from bayram.db.enums import CreditEntryKind, CreditReason

__all__ = [
    "MAX_GRANT_CREDITS",
    "CreditAccountView",
    "CreditLedgerEntryView",
    "CreditLedgerPage",
    "CreditGrantRequest",
    "CreditGrantResultView",
    "to_credit_account_view",
    "to_credit_entry_view",
]

#: The most credits one call may add. A credit is one render and one render is real vendor
#: spend, so this is a blast radius rather than a validation nicety: an operator comping a
#: failed order types ``1``, and the number this cap exists to refuse is the ``1000`` that was
#: meant to be ``10``. It is deliberately far below anything a legitimate campaign would need
#: — a campaign is a migration or a script with its own review, not fifty presses of a button
#: in the panel — and every call lands on the audit log, so raising it later is a decision
#: somebody makes in a diff rather than a limit nobody notices is missing.
MAX_GRANT_CREDITS: Final[int] = 100


class CreditAccountView(ApiModel):
    """One ``credit_accounts`` row: what the ledger can prove this account holds.

    ``balance`` is the stored column and **not** the number the customer sees. The bot's gate
    projects a rolling allowance that is due but not yet minted, and that projection is
    ``creditsProjected`` on :class:`~bayram.admin.schemas.users.UserDetailView`. Both are on the
    wire because an operator settling "they say they have three songs and you say zero" needs
    the pair; a single number would be right for one of the two conversations and wrong for
    the other.
    """

    telegram_user_id: int
    telegram_user_id_masked: str
    balance: int
    #: Every credit ever added, allowances included. Monotone, never decremented — which is
    #: what makes "has this account already been comped?" answerable without replaying the
    #: whole ledger.
    lifetime_granted: int
    #: The last rolling-allowance window minted for this account, as a period index. ``null``
    #: until the first allowance lands, which is also how "opened but never granted" stays
    #: distinguishable from "granted in period 0".
    allowance_period: int | None


class CreditLedgerEntryView(ApiModel):
    """One movement. Append-only: no row on this wire was ever updated after it was written."""

    id: UUID
    kind: CreditEntryKind
    reason: CreditReason
    #: Signed and constrained to agree with ``kind`` at the database: positive for a grant or
    #: refund, negative for a debit, exactly ``0`` for a consume — which settles a debit
    #: without moving anything, and would desynchronise the balance if it were anything else.
    delta: int
    order_id: UUID | None
    #: Which charge attempt for that order, bumped by each refund. It is what makes a
    #: refunded order chargeable again rather than free.
    generation: int
    #: The key that makes a duplicate impossible rather than unlikely — see the module docs.
    idempotency_key: str
    actor: str | None
    created_at: datetime


class CreditLedgerPage(ApiModel):
    """``GET /users/{telegramUserId}/credits``.

    ``account`` is ``null`` when ``credit_accounts`` holds no row, which happens for two
    populations an operator must be able to tell apart from "spent everything": a customer
    who has never been charged or granted anything (the row is opened by the first movement),
    and a customer whose ``/forget`` deleted the row. In the second case ``items`` may still
    be empty even though movements exist — erasure keeps the rows and nulls their Telegram
    id, so they belong to nobody and match no account.
    """

    account: CreditAccountView | None
    items: list[CreditLedgerEntryView]
    meta: PageMeta


class CreditGrantRequest(ReasonedRequest):
    """``POST /users/{telegramUserId}/credits/grant``: how many, why, and optionally under
    which key.

    The Telegram id is **not** in the body. It is the path parameter the step-up scope was
    built from, and a second copy here is a second answer to "who is being credited" — the
    shape that grants one account under another account's re-authentication.
    """

    #: ``ge=1`` mirrors ``db.credits.grant``'s own refusal, which exists because a
    #: non-positive delta would otherwise be caught by ``ck_credit_ledger_delta_matches_kind``
    #: and reach the operator as a constraint name. Declaring it here makes it a 422 that
    #: names the field, and leaves that check as the backstop it was written to be.
    credits: Annotated[int, Field(ge=1, le=MAX_GRANT_CREDITS)]
    #: The idempotency key's variable half. Supply the same value on a retry and the account
    #: is topped up once; omit it and the server mints one, so two presses of the button are
    #: two grants — which is the honest reading of two presses, and why the response says
    #: which of the two happened.
    request_id: UUID | None = None


class CreditGrantResultView(ApiModel):
    """What the grant did, and what the account looks like now.

    ``isReplay`` is the field that makes a retry safe to interpret: ``true`` means this exact
    ``requestId`` had already been granted and nothing moved, so a client that retried a
    timed-out request can tell "it worked the first time" from "it worked just now" without
    guessing from the balance.
    """

    telegram_user_id: int
    telegram_user_id_masked: str
    #: What this call asked for. On a replay it is what the ORIGINAL call asked for only if
    #: the caller sent the same number; the ledger row is authoritative and the page beside
    #: this one shows it.
    granted_credits: int
    is_replay: bool
    idempotency_key: str
    #: Read back inside the same transaction, after the write. A response that echoed the
    #: request's arithmetic instead would be a prediction rather than a reading, and would
    #: disagree with the ledger the moment anything else moved the balance concurrently.
    account: CreditAccountView


def to_credit_account_view(account: CreditAccountState) -> CreditAccountView:
    """Project the account row, masking the id beside its plaintext."""
    return CreditAccountView(
        telegram_user_id=account.telegram_user_id,
        telegram_user_id_masked=mask_telegram_user_id(account.telegram_user_id),
        balance=account.balance,
        lifetime_granted=account.lifetime_granted,
        allowance_period=account.allowance_period_index,
    )


def to_credit_entry_view(item: CreditLedgerItem) -> CreditLedgerEntryView:
    """Project one ledger row. A straight copy: there is nothing here to mask or derive."""
    return CreditLedgerEntryView(
        id=item.id,
        kind=item.kind,
        reason=item.reason,
        delta=item.delta,
        order_id=item.order_id,
        generation=item.generation,
        idempotency_key=item.idempotency_key,
        actor=item.actor,
        created_at=item.created_at,
    )
