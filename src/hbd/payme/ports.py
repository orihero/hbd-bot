"""The two ports the settlement half of the rail is reached through, and the views it returns.

:mod:`hbd.payme.protocol` says what the wire looks like. This module says what the gateway is
allowed to ASK FOR, and it is deliberately the only file in this package that describes a
capability rather than a byte. Nothing here touches a database, imports one, or knows that one
exists — the implementation lives in ``hbd.db.payme`` and satisfies :class:`PaymeLedger`
structurally, in exactly the direction ``hbd.db.purchases.SqlPurchaseLedger`` satisfies
``hbd.checkout.PurchaseFulfiller``. That direction is the whole architecture: a rail that
imported persistence could not be tested without a database, and the state machine below is
precisely the thing that must be testable without one.

**Why a SECOND port when ``hbd.checkout.PaymentIntentOpener`` already exists.** They are two
halves of one object held by two processes with different blast radii. The bot may open an
intent — a write that grants nothing, promises nothing and costs nothing to abandon — and that
is all its handle can express, because ``PaymentIntentOpener`` declares one method. The
gateway may settle, cancel, expire and force-settle, and it is the only process holding the
credential those calls arrive authenticated with. One implementation satisfies both; what
stops the bot growing the gateway's half is that the bot's reference is TYPED as the narrow
one, so the compiler refuses the call rather than a reviewer having to notice it.

**Every method returns ``Result`` and never raises**, like every seam in this codebase. The
refusals do not START as values — a ``PaymeFault`` is raised INSIDE the settlement transaction
so that raising it rolls the transaction back, which is the one construct that guarantees no
compensating write is needed — but ``hbd.db.guard.run_guarded`` turns each into an ``Err``
before it crosses this boundary. See :mod:`hbd.payme.errors` for the full argument.

**No ``*Row`` ever appears here** (Rule 15). The three frozen views below are what persistence
hands back: a mapped row carries a live session, dies when the transaction closes, and would
make the ASGI layer's rendering depend on whether somebody remembered ``expire_on_commit``.
:class:`hbd.checkout.PaymentIntent` is reused rather than re-declared for the intent, because
the bot and the gateway must be looking at the same object — a second intent view would be a
second place for ``state`` to mean something slightly different.

See ``DECISIONS.md D11`` and ``PAYME_INTEGRATION §1`` for the two seams, ``§3`` for the
one-commit settlement these methods are the surface of, and ``§5`` for the replay guarantees
each of them is required to honour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from hbd.checkout import PaymentIntent, Product
from hbd.contracts import Result
from hbd.payme.protocol import PaymeState

__all__ = [
    "PAYME_PROVIDER_NAME",
    "PaymeTransactionView",
    "PaymeStatementRow",
    "SettlementCounts",
    "PaymeLedger",
]

#: The string written into ``payment_intents.provider``, ``topup_purchases.provider`` and
#: ``plan_purchases.provider`` for every sale this rail settles, and the ``name`` the bot-side
#: ``CheckoutProvider`` reports.
#:
#: It lives HERE, in ``hbd.payme``, rather than in either of the two modules that use it,
#: because those two may not import each other: the bot's provider is in this package and may
#: never import ``hbd.db``, while the ledger is in ``hbd.db`` and imports this package freely.
#: One constant in the one module both can reach is the only arrangement in which "which rail
#: sold this?" cannot come out as two different strings — the identical argument
#: :data:`hbd.db.fulfilment.CHECKOUT_ACTOR` makes for the ledger's actor, and for the identical
#: reason: a provider that said ``payme`` on the receipt and something else on the intent would
#: split one population of paid songs into two and make "what did this rail take?" a ``UNION``.
PAYME_PROVIDER_NAME: Final[str] = "payme"


@dataclass(frozen=True, slots=True)
class PaymeTransactionView:
    """One rail-side transaction as every reply that mentions one is rendered from.

    Frozen and slotted for the reason every value in this integration is: this object is read
    AFTER its transaction committed, by code that is composing an answer to a third party
    about money, and a caller that could mutate ``state`` on a copy would be answering about a
    payment that does not exist.

    **The three clocks are separate columns and they are carried here as three fields**, not
    collapsed into "the last thing that happened". That is the single mechanical requirement
    behind four of the five replay guarantees: a replayed ``CreateTransaction`` must return the
    STORED ``create_time``, a replayed ``PerformTransaction`` the STORED ``perform_time``, and
    a replayed ``CancelTransaction`` the STORED ``cancel_time`` — never ``now()``, in any of
    the three. A view that recomputed any of them would pass every local test and fail
    certification, whose entire headline assertion is that the second answer equals the first.

    ``perform_time`` and ``cancel_time`` are ``None`` rather than ``0`` here on purpose: ``0``
    is the WIRE's representation of "has not happened" and
    :func:`hbd.payme.rules.wire_time` is the one place that coercion is applied. A column
    storing 0 could not tell a transaction performed at the epoch from one never performed,
    and neither could this view.

    ``our_id`` is OUR primary key and ``payme_transaction_id`` is theirs, and the two are never
    interchangeable on the wire: in a ``CheckTransaction`` or ``PerformTransaction`` reply the
    ``transaction`` field is ``str(our_id)``, while in a ``GetStatement`` row the two are
    swapped — ``id`` is theirs and ``transaction`` is ours. Carrying both, always, is what lets
    the renderer be a projection rather than a lookup.
    """

    #: THEIR id: 24 hex characters, a string, never parsed as a number.
    payme_transaction_id: str
    #: OURS. ``str(our_id)`` is the ``transaction`` field in every non-statement reply.
    our_id: UUID
    #: The opaque account reference of the intent this transaction is charging against. The
    #: statement's account object is built from it, and it is the handle a customer and an
    #: operator share when a payment page goes wrong.
    intent_public_ref: str
    #: The instant the RAIL created this transaction, from its own ``params.time``. The clock
    #: the twelve-hour window runs off and the one the statement filters and sorts on — never
    #: ``created_at``, which is ours and differs from it by the network.
    payme_time: datetime
    #: What the rail said the charge was for, in minor units, verbatim.
    amount_minor: int
    state: PaymeState
    #: THEIR reason code, echoed back as an integer. ``None`` on a transaction that was never
    #: cancelled, which is what the wire renders as ``null`` — the one field where ``null`` is
    #: correct and ``0`` would be a lie about a reason code that does not exist.
    cancel_reason: int | None
    create_time: datetime
    perform_time: datetime | None
    cancel_time: datetime | None


@dataclass(frozen=True, slots=True)
class PaymeStatementRow:
    """A statement row: the transaction, plus the account object the rail needs beside it.

    ``GetStatement`` is the one method whose reply carries the ACCOUNT as well as the
    transaction, because it is what a human reconciles a cabinet export against — a list of
    transaction ids with no order references beside them is a list nobody can act on.

    A pair rather than four more fields on :class:`PaymeTransactionView`: the account half is
    needed by exactly one of the six methods, and widening the view every other method returns
    would make five renderers carry two fields they must remember not to emit.

    **It must still render after a ``/forget``.** Erasure anonymises
    ``payment_intents.telegram_user_id`` and leaves ``public_ref``, the amount and every clock
    intact, precisely so this row survives it. Telling Payme that a transaction they can see in
    their own cabinet never existed is worse than holding an anonymous row, which is the whole
    reason erasure on this table is an ``UPDATE`` and not a ``DELETE``.
    """

    transaction: PaymeTransactionView
    #: What ``ac.<field>`` was set to when the link was built — our ``public_ref``. The
    #: renderer pairs it with the configured account field name to build ``{"order_id": ...}``.
    account_value: str
    #: Which product the intent was for. Carried so an operator diffing a statement against a
    #: cabinet export can see a plan sale and a single song apart without a second query.
    product: Product


@dataclass(frozen=True, slots=True)
class SettlementCounts:
    """The three-way reconciliation, as three integers over one window.

    There is no Merchant API method a merchant may call — the protocol is entirely inbound —
    so nothing in this system can ask Payme what it thinks happened. These three counts are
    therefore the ONLY automated check on the newly shared write primitive
    (:func:`hbd.db.fulfilment.write_single_sale`), and their whole purpose is to notice that a
    performed transaction stopped producing a receipt before a customer has to report it.

    **The exact identity, because "three-way invariant" is not precise enough to act on.**

    * ``transactions_performed == receipts_written`` is the equality that must ALWAYS hold.
      Both are written in the same commit from the same clock, so a difference is a defect and
      never a race — there is no window in which one has landed and the other has not.
    * ``grants_written`` is the SINGLE-song subset of ``receipts_written`` by construction, not
      a third independent number. A plan sale writes a ``plan_purchases`` receipt and grants no
      credit at all (``hbd.db.fulfilment.write_plan_sale`` — a plan mints its songs as they are
      used), so the difference between the two is exactly the number of plan settlements in the
      window. A sweep that asserted three-way equality would report an error every time
      somebody bought a plan.

    A mismatch is reported and NEVER self-repaired. A counter that silently corrected itself
    would remove the only evidence that the shared write primitive had drifted, and the repair
    would be a credit grant written by a scheduler on a guess.
    """

    #: Transactions whose ``perform_time`` falls in the window.
    transactions_performed: int
    #: Receipt rows — ``topup_purchases`` plus ``plan_purchases`` — written under the
    #: idempotency keys of the intents settled in the window.
    receipts_written: int
    #: ``credit_ledger`` GRANT rows under those same keys. See the identity above.
    grants_written: int


@runtime_checkable
class PaymeLedger(Protocol):
    """Everything the GATEWAY may ask of the rail's state. Held by one process only.

    The superset of ``hbd.checkout.PaymentIntentOpener``, and the asymmetry is the security
    argument: this protocol can settle a payment, and the bot's handle on the same object
    cannot, because the bot's handle is typed as the narrow one. ``mypy --strict`` is what
    enforces that, since ``runtime_checkable`` verifies member PRESENCE only and would happily
    accept a fake whose signatures had drifted.

    **No method raises, and none of them commits on the caller's behalf either** — each owns
    exactly one transaction, opens it, decides inside it and closes it, which is what makes
    "either all four rows exist or none do" a property of the database rather than a promise
    in a docstring. A method that took a session would have handed that decision to a caller
    answering an inbound HTTP request.

    **``now`` is a parameter on every method that has an opinion about time.** The rail's
    twelve-hour window and our own validity window are both driven by it, which is what lets
    certification run the expiry branch in seconds and a unit test assert its exact boundary.
    The implementation still holds an injected clock, for the writes whose instant nobody
    supplies (``open_intent``); the two never disagree because the ASGI layer reads the clock
    once per request and passes that instant down.
    """

    async def open_intent(
        self,
        *,
        telegram_user_id: int,
        product: Product,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        language: str,
        merchant_id: str,
        is_sandbox: bool,
        plan_songs: int | None = None,
        plan_days: int | None = None,
    ) -> Result[PaymentIntent]:
        """As ``hbd.checkout.PaymentIntentOpener.open_intent``. Idempotent on the key."""
        ...

    async def intent(self, *, public_ref: str) -> Result[PaymentIntent | None]:
        """The intent behind ``public_ref``, or ``Ok(None)`` when there is none.

        A read, and the only way anything outside persistence gets an intent back after the
        one that opened it. The notification job needs the stored language and product to write
        a sentence, and the operator CLI's journal needs the whole row; neither may hold a
        session, so both come through here.

        ``Ok(None)`` rather than a ``NotFoundError``: "there is no such reference" is an
        ordinary answer to a question about a string a third party supplied, and making it an
        ``Err`` would put an expected outcome on the same branch as a database failure.
        """
        ...

    async def quote(self, *, public_ref: str, amount_minor: int, now: datetime) -> Result[None]:
        """``CheckPerformTransaction``: may a charge for this amount be created? **Writes nothing.**

        Read-only, and the assertion behind that word is a full row-set diff before and after,
        not a reviewer's reading. Payme calls this while the customer is still looking at a
        form, possibly several times, and a method that expired an intent or took a hold here
        would be acting on a payment nobody has committed to yet.

        Refuses through the account range (``-31050`` unknown, ``-31051`` paid, ``-31052``
        cancelled, ``-31053`` expired, ``-31055`` issued for another cashbox), through the
        settable duplicate code when a live transaction already holds the intent, and through
        ``-31001`` when the amount does not match. ``Ok(None)`` is the bare ``{"allow": true}``.
        """
        ...

    async def create(
        self,
        *,
        payme_transaction_id: str,
        payme_time: datetime,
        amount_minor: int,
        public_ref: str,
        now: datetime,
    ) -> Result[PaymeTransactionView]:
        """``CreateTransaction``: take an exclusive hold on the intent, or refuse.

        **This is the mutex point of the whole integration.** A second rail-side transaction
        for an intent already held is refused HERE, before a card is touched, rather than at
        settlement after two cards have been charged.

        A replay — the same ``payme_transaction_id`` arriving again because our first answer
        was lost — returns the STORED row unchanged and writes nothing, so the second answer
        equals the first byte for byte.
        """
        ...

    async def perform(
        self, *, payme_transaction_id: str, now: datetime
    ) -> Result[PaymeTransactionView]:
        """``PerformTransaction``: the money is theirs. **One commit, four rows, or nothing.**

        Flips the transaction, claims the intent, writes the receipt and writes the credit
        grant inside a single transaction from a single clock read, under the idempotency key
        the BOT minted — so a settlement arriving twice, and an operator's forced settlement
        followed by a late genuine one, both land on the same unique indexes and write nothing
        the second time.

        **Never creates a transaction.** An unknown id is ``-31003``, always.

        A replay on a performed transaction returns the STORED ``perform_time``, never ``now``.
        """
        ...

    async def cancel(
        self, *, payme_transaction_id: str, reason: int, now: datetime
    ) -> Result[PaymeTransactionView]:
        """``CancelTransaction``: give the intent back, or refuse because it is delivered.

        From ``created`` this cancels and RELEASES the intent to ``pending``, so a customer
        whose card declined can try another one within seconds instead of waiting out a
        validity window they did not cause to lapse.

        From ``performed`` this is ``-31007``, unconditionally, and no reversal exists behind
        it — see :class:`hbd.payme.errors.PaymeOrderDelivered` and ``PAYME_INTEGRATION §6``.

        A replay on an already-cancelled transaction returns the STORED ``cancel_time`` and
        state as a SUCCESS, never an error.
        """
        ...

    async def read(self, *, payme_transaction_id: str) -> Result[PaymeTransactionView]:
        """``CheckTransaction``: report the row. **Mutates nothing — not even an expiry.**

        The one method with no ``now`` parameter, and its absence is the specification: a read
        that could expire what it was asked about would make Payme's own status poll change
        the answer it was polling for. Expiry happens when a WRITE forces the machine to move,
        and as a scheduled backstop; never here.
        """
        ...

    async def statement(
        self, *, frm: datetime, to: datetime
    ) -> Result[tuple[PaymeStatementRow, ...]]:
        """``GetStatement``: every transaction created in ``[frm, to]``, oldest first.

        Inclusive at both ends and sorted ascending on the PAYME-side clock, because that is
        the clock the rail is reconciling against. Includes every transaction whose
        ``CreateTransaction`` succeeded, whatever became of it — a cancelled transaction is
        part of the period's history and omitting it would make the two ledgers disagree.
        An empty period is an empty tuple and never an error.
        """
        ...

    async def expire_lapsed(self, *, now: datetime, limit: int) -> Result[int]:
        """Flip ``pending`` intents past ``valid_until`` to ``expired``. Returns how many.

        The predicate is ``state = 'pending' AND valid_until <= :now`` and that is the entire
        safety argument: **an intent under a live transaction is not in the set this can see.**
        Not "protected from" it by a check somebody has to remember — structurally absent from
        it, because holding an intent moves it to ``awaiting``. Our clock and the rail's are not
        the same clock, and an intent expired here while a card was being charged there is the
        single worst outcome this system has.
        """
        ...

    async def expire_stale_transactions(self, *, now: datetime, limit: int) -> Result[int]:
        """Cancel ``created`` transactions past the window and release their intents.

        A backstop, not a mechanism: every request that forces the machine to move already
        evaluates the same predicate. This exists so that a transaction Payme never mentions
        again does not sit in ``created`` forever, making ``CheckTransaction`` answer state 1
        about a charge that can no longer happen and leaving its intent unpayable.
        """
        ...

    async def pending_notifications(
        self, *, older_than: datetime, limit: int
    ) -> Result[tuple[PaymentIntent, ...]]:
        """Settled intents nobody has been told about, settled before ``older_than``.

        The delivery backstop's input. The post-commit enqueue at settlement is best-effort by
        design — Payme must get its ``200`` whether or not Redis answered — so this is what
        turns a Redis outage at the moment of payment into a latency problem rather than a
        customer who paid and was never told.

        ``older_than`` rather than a bare limit so the sweep cannot race the enqueue it is
        backing up: an intent settled two seconds ago probably has a job in flight already.
        """
        ...

    async def mark_notified(self, *, public_ref: str, now: datetime) -> Result[bool]:
        """Stamp ``notified_at``. ``True`` when this call stamped it, ``False`` when it was set.

        Conditional on the column being NULL, so two deliveries racing produce one stamp and
        the loser knows it lost — which is how the notification job stays safe to retry.
        """
        ...

    async def force_settle(
        self, *, public_ref: str, now: datetime, note: str
    ) -> Result[PaymentIntent]:
        """The recovery button: settle an intent by hand after a callback was lost.

        Writes the sale under the intent's OWN bot-minted idempotency key and stamps
        ``settle_note='operator:<note>'``. Because the key is the same one a genuine
        ``PerformTransaction`` would use, a late genuine settlement collapses onto the same
        unique indexes and grants NOTHING twice — which is the property that makes it safe to
        press this button while still unsure whether the rail will call.
        """
        ...

    async def settlement_counts(self, *, frm: datetime, to: datetime) -> Result[SettlementCounts]:
        """The three reconciliation counts over a window. See :class:`SettlementCounts`."""
        ...
