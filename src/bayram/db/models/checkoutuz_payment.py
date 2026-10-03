"""``checkoutuz_payments`` — every payment link checkout.uz minted for one of our intents.

The checkout.uz rail is a redirect rail of a different shape from Payme. Payme calls US: it
creates a transaction against our account number and resends every call until it gets an
answer, so ``payme_transactions`` is a mirror of what the rail told us. checkout.uz is called
BY us: ``create_payment`` hands back an order id and a page URL, the customer pays on that
page, and the only authoritative answer about whether money moved is a ``status_payment``
call WE make later. Its webhook is unsigned and is never retried, so it is an accelerator for
that call and never a substitute for it. This table is what the poller walks
(DECISIONS.md D28).

**WHY A SIDE TABLE AND NOT COLUMNS ON ``payment_intents``.** A checkout.uz link lives one hour
(its ``_lifteme``); an intent lives twelve. A customer who comes back after an hour gets a
NEW link for the SAME intent, and the old one does not stop being payable just because we
stopped showing it — a page left open in a browser tab past its advertised lifetime and then
paid is undocumented but possible. Columns on the intent overwritten "when the link expires"
would forget the old order id, and a payment through it would then arrive as an order nobody
recognises: money taken, nothing granted. One row per link keeps every order id we ever
issued pollable until a final status check has looked at it after the link lapsed.

**WHY ``order_id`` IS THE PRIMARY KEY, AND IS NOT AUTOINCREMENTED.** It is checkout.uz's own
integer ``_id`` for the payment, assigned by them, and it is the one value every inbound
webhook and every status call is keyed by. Making it the key means the lookup the webhook
gate does is a primary-key probe, and a second INSERT for the same order — a retried create
whose first response was lost — is a key violation rather than a silent duplicate. It is a
``BigInteger`` because it is theirs to grow.

**WHY ``intent_id`` HAS A FOREIGN KEY, UNLIKE EVERY TABLE IN THE PAYME AREA.** Those tables
refuse one because their rows are written in the same commit as the intent and a constraint
would be a second, weaker opinion about an ordering the commit already guarantees. This row
is written in a LATER transaction, after an HTTP call that happens between the intent being
opened and the link being recorded, so there is no shared commit to lean on — and the row is
meaningless without its intent, because the intent carries the amount, the product, the
customer and the idempotency key the settlement writes the sale under. ``ON DELETE RESTRICT``,
not CASCADE: the only path that deletes an intent is the 400-day sweep of terminal intents,
and an ``expired`` intent CAN sit behind real money — an ``orphan_paid`` link from an amount
mismatch leaves its intent pending, the Payme sweep then expires it, and that link is the only
record of a refund we owe. ``bayram.db.purge`` therefore never takes an intent that has a
``paid`` or ``orphan_paid`` link, and deletes the remaining (``expired``) links of the intents
it does take explicitly, child first; RESTRICT is the backstop that makes any other path that
tries to delete such an intent fail loudly instead of erasing the money record with it.

**WHY THE AMOUNT IS IN SOʻM HERE AND IN TIYIN ON THE INTENT.** ``amount_som`` is what
checkout.uz echoed back when the link was minted, stored verbatim, in their unit. The
settlement compares the status call's amount against THIS and ``amount_som * 100`` against
the intent's ``amount_minor``; a mismatch anywhere is a refusal and an ERROR, never a
re-price. Keeping both is what makes a dispute answerable from our own database.

**WHY ``link_valid_until`` IS NOT NAMED ``link_expires_at``.** The suffix ``expires_at`` is this
codebase's word for a RETENTION clock: ``tests/test_db/test_audit_retention.py`` collects every
column so named and demands a purge sweep reads it. This is a BUSINESS clock — how long the
checkout.uz page stays payable — named exactly as ``payment_intents.valid_until`` is and for the
same reason.

**PRIVACY — in NEITHER of ``tests/test_db/test_privacy_constraints.py``'s two sets, on
``payme_transactions``' argument: IT HOLDS NO TELEGRAM ID AT ALL.** Every column is the
rail's integer order id, its UUID, the URL of its own payment page, an integer amount, a
closed enum or a clock. The URL is checkout.uz's page and carries nothing of ours but an
opaque order number. A person is reachable from this row only by joining through
``payment_intents``, which is the join ``/forget`` breaks by nulling that table's
``telegram_user_id`` — so there is nothing here to null and no erasure arm to write.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import Base, TimestampMixin, UtcDateTime, enum_type
from bayram.db.enums import CheckoutUzPaymentState

__all__ = [
    "CheckoutUzPaymentRow",
    "CHECKOUTUZ_PAYMENT_UUID_LENGTH",
    "CHECKOUTUZ_PAY_URL_LENGTH",
    "CHECKOUTUZ_STATE_LENGTH",
]

#: checkout.uz's ``_uuid`` is a 36-character UUID today. Sized with headroom because the
#: format is theirs, and a longer identifier must be a failed INSERT we notice rather than a
#: truncation we do not — but the value is informational (nothing is keyed on it), so the
#: margin costs nothing.
CHECKOUTUZ_PAYMENT_UUID_LENGTH: Final[int] = 64
#: The payment page URL checkout.uz returns. Theirs, not ours, and handed to the customer as
#: the button's target — so a stored link that a re-press reuses must be the whole URL.
CHECKOUTUZ_PAY_URL_LENGTH: Final[int] = 512
#: ``orphan_paid`` is the longest value at 11 characters.
CHECKOUTUZ_STATE_LENGTH: Final[int] = 16


class CheckoutUzPaymentRow(Base, TimestampMixin):
    """One checkout.uz order, and whether it has been looked at for the last time.

    ``TimestampMixin`` IS used, on ``payme_transactions``' footing: the row is genuinely
    UPDATEd — polled, then marked paid, expired or orphaned, each by a conditional statement —
    so ``updated_at`` can be true. ``created_at`` also orders the poller's batch after
    ``last_polled_at``, so a link never polled before goes first.
    """

    __tablename__ = "checkoutuz_payments"
    __table_args__ = (
        # checkout.uz refuses amounts under 1 000 soʻm; zero or negative here is a bug in the
        # conversion from tiyin, and the column must not be able to hold it.
        sa.CheckConstraint("amount_som > 0", name="amount_positive"),
        # Hand-named, and spelled identically in revision 0030 because
        # ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES. It serves
        # both of the poller's reads — ``state = 'pending'`` with a range on the link's clock,
        # one on each side of the grace boundary.
        sa.Index("ix_checkoutuz_payments_state_valid_until", "state", "link_valid_until"),
    )

    #: checkout.uz's own integer ``_id`` for this payment. The key every webhook and every
    #: status call carries. Never generated here — see the module docstring.
    order_id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    #: The intent this link is a way of paying. Indexed: a re-press looks for a live link by
    #: intent, and the webhook gate joins through it. Deliberately NOT unique — one intent,
    #: several links, one per lapsed hour.
    intent_id: Mapped[UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("payment_intents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: checkout.uz's ``_uuid``. Informational: shown in their dashboard, so an operator can
    #: match a refund request to a row. Nothing reads it as a key.
    payment_uuid: Mapped[str] = mapped_column(
        sa.String(CHECKOUTUZ_PAYMENT_UUID_LENGTH), nullable=False
    )
    #: The page the customer is sent to. Reused by a re-press while the link is still live.
    pay_url: Mapped[str] = mapped_column(sa.String(CHECKOUTUZ_PAY_URL_LENGTH), nullable=False)
    #: checkout.uz's ``_pay_via`` as ``[[method, url], ...]`` in the order it was sent: one
    #: page per enabled payment method, so a re-press within the hour draws the same method
    #: buttons as the first press. NULL when the reply carried none. Display-only — nothing
    #: settles on it — so a reader treats NULL or a malformed value as "no per-method pages".
    #: ``none_as_null`` for the reason ``briefs.approved_lyrics`` gives.
    pay_via: Mapped[list[Any] | None] = mapped_column(sa.JSON(none_as_null=True), nullable=True)
    #: What checkout.uz echoed back as the amount, in whole soʻm. See the module docstring.
    amount_som: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: Where this LINK has got to. Moved only by conditional ``UPDATE``s naming the state
    #: they expect — see :class:`bayram.db.enums.CheckoutUzPaymentState`.
    state: Mapped[CheckoutUzPaymentState] = mapped_column(
        enum_type(CheckoutUzPaymentState, length=CHECKOUTUZ_STATE_LENGTH), nullable=False
    )
    #: When checkout.uz says the page stops being payable: our clock at mint time plus their
    #: ``_lifteme``. A business clock, not a retention clock — see the module docstring.
    link_valid_until: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: When the poller last asked checkout.uz about this order. NULL until it first did, and
    #: NULLs sort first in the poll batch so a fresh link is never starved by old ones.
    last_polled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: When WE confirmed it paid — the instant of the claim, the same one the intent's
    #: ``settled_at`` carries. Also stamped on ``orphan_paid``, because a second payment is
    #: still money that moved and the refund needs to know when. NULL on the other states.
    paid_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
