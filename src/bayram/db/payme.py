"""The redirect rail's state machine: one class, two ports, and one commit that decides money.

``SqlPurchaseLedger`` one file over answers "a customer tapped buy — what does that write?".
This answers the harder half: **a payment that started in one process finishes in another,
minutes later, on an inbound HTTP request nobody is awaiting, and it may arrive twice.**
Exactly-once fulfilment across that gap is a commit boundary, not a promise, which is why the
ordering that makes it so lives here — inside the transaction — rather than in a "pure
decisions" layer that could not have held a lock. :mod:`bayram.payme.rules` holds every decision
that does NOT need one, and the split between the two files is exactly that question.

**THE ONE COMMIT.** :meth:`SqlPaymeLedger.perform` flips the rail transaction, claims the
intent, writes the receipt and writes the credit grant inside a single
``async with self._sessions.begin()``, from ONE clock read, under the SAME bot-minted
``idempotency_key`` the receipt tables and the credit ledger already deduplicate on. Either all
four rows exist or none do. Two of those four steps are conditional ``UPDATE``s whose rowcount
is the lock — see :mod:`bayram.db.payme_sql`, which argues the primitive and names the two
alternatives this repository has already measured and rejected — and the whole sequence is
written so that every refusal after the first write is an EXCEPTION, because an exception is
the only construct that unwinds the flip already made in the same transaction without a single
compensating write.

**ONE CLASS SATISFYING TWO PROTOCOLS, and the asymmetry is the security control.** The same
object is handed to the BOT typed as :class:`bayram.checkout.PaymentIntentOpener`, which declares
``open_intent`` and nothing else, and to the GATEWAY typed as
:class:`bayram.payme.ports.PaymeLedger`, which declares the settlement half. The bot cannot
perform, cancel or force-settle a payment for the same reason it cannot spend a credit: the
method is not on the type it holds, so the compiler refuses the call rather than a reviewer
having to notice it. Neither protocol is inherited — both are satisfied structurally, exactly
as ``SqlPurchaseLedger`` satisfies ``PurchaseFulfiller`` — so a protocol change is a type error
here rather than a silent divergence.

**Every public method is ``run_guarded`` and every refusal is an ``BayramError``.** The
:mod:`bayram.payme.errors` hierarchy inherits ``BayramError`` specifically so the guard's existing
ladder catches it and the refusal reaches the dispatcher as an ``Err`` carrying an
``rpc_code``, rather than as an exception crossing a seam that promised never to raise. The
gateway's whole protocol requires it to answer HTTP 200 with a JSON-RPC error object; an
escaped exception would be a 500, which Payme reads as ``-32400`` and retries, and which also
costs us the request-id echo.

**Two clocks, and neither of them is read here twice.** ``now`` is a PARAMETER on every method
the rail drives, so certification can run the twelve-hour expiry branch in seconds and a unit
test can assert its exact boundary; the injected ``clock`` is used only by ``open_intent``,
whose instant nobody supplies. Inside a settlement the parameter is read once and every row
written carries it — the receipt, the grant, ``perform_time`` and ``settled_at`` — which is
what makes a windowed count of settlements and a windowed count of receipts unable to straddle
a boundary differently.

**Two vocabularies share three names in this file, and the aliases are why.**
``bayram.db.enums`` mirrors ``bayram.checkout`` and ``bayram.payme.protocol`` value-for-value rather
than importing them (a mapped column naming a type from outside persistence is how
``bayram.contracts`` acquired the import cycle ``bayram.entitlements`` documents). This is the one
module where both halves are in scope at once, so the ports' copies are imported under
``Checkout``/``Protocol`` prefixes and the bare names are always the DATABASE's.

See ``DECISIONS.md D11``, ``PAYME_INTEGRATION §3`` for the settlement's ordering argument,
``§5`` for the five replay guarantees and ``§6`` for why no post-perform reversal exists.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import PaymentIntent, Product, Purchase
from bayram.checkout import PaymentIntentState as CheckoutIntentState
from bayram.contracts import Result
from bayram.db.base import utc_now
from bayram.db.enums import IntentProduct, PaymentIntentState, PaymeState
from bayram.db.fulfilment import write_plan_sale, write_single_sale
from bayram.db.guard import not_found, run_guarded
from bayram.db.models.payme_transaction import PaymeTransactionRow
from bayram.db.models.payment_intent import SETTLE_NOTE_LENGTH, PaymentIntentRow
from bayram.db.payme_sql import (
    claim_intent,
    claim_intent_for_operator,
    claim_intent_resume,
    expire_intent,
    hold_intent,
    insert_intent,
    insert_transaction,
    intent_by_id,
    intent_by_key,
    intent_by_ref,
    lapsed_pending_intents,
    mark_cancelled,
    mark_intent_notified,
    mark_performed,
    release_intent,
    settlement_counts,
    stale_created_transactions,
    transaction_by_payme_id,
    transactions_in_period,
    unnotified_settled_intents,
)
from bayram.errors import PaymentError, StorageError
from bayram.logging import get_logger
from bayram.payme.errors import (
    PaymeAccountFault,
    PaymeAmountMismatch,
    PaymeOrderDelivered,
    PaymeStateRefusal,
    PaymeTransactionNotFound,
)
from bayram.payme.ports import (
    OPERATOR_SETTLE_PREFIX,
    PAYME_PROVIDER_NAME,
    PaymeStatementRow,
    PaymeTransactionView,
    SettlementCounts,
)
from bayram.payme.protocol import DEFAULT_ACCOUNT_FIELD, CancelReason, PaymeErrorCode
from bayram.payme.protocol import PaymeState as ProtocolPaymeState
from bayram.payme.rules import DEFAULT_TRANSACTION_TIMEOUT_MS, account_fault_for, is_expired

__all__ = ["SqlPaymeLedger", "DEFAULT_INTENT_TTL_S"]

_log = get_logger(__name__)

#: How long a checkout link stays payable, in seconds. Twelve hours, matching the rail's own
#: transaction window rather than being derived from it: the two clocks measure different
#: things (ours runs from the moment the customer was handed a URL, theirs from the moment a
#: card was presented against it) and a deployment that shortened one must be able to leave the
#: other alone.
#:
#: It is a DEFAULT and not a rule — the composition root passes ``BAYRAM_PAYME_INTENT_TTL_S`` —
#: and it is bounded above by the wizard's own fourteen-day state TTL, because a customer who
#: pays for a draft Redis has already dropped has paid for nothing. That bound is asserted at
#: boot rather than here, where nothing knows what the bot's TTL is.
DEFAULT_INTENT_TTL_S: Final[int] = 43_200

#: ``secrets.token_hex(12)`` — 24 lowercase hex characters, the width
#: ``payment_intents.public_ref`` is sized for. Twelve bytes rather than sixteen because this
#: value is read out loud by support occasionally and is not a capability: guessing one buys an
#: attacker the ability to pay somebody else's bill.
#:
#: Hex, and not base64 or a UUID's dashed form, for a parser reason verified against the rail:
#: a ``;`` anywhere inside a checkout-link value silently TRUNCATES it, and ``=`` terminates a
#: key. An alphabet of ``0-9a-f`` cannot contain either, so the account value is safe by
#: construction rather than by an escaping rule somebody has to remember.
_PUBLIC_REF_BYTES: Final[int] = 12

#: ``payment_intents.settle_note`` for a settlement the rail itself performed. The operator
#: path writes ``operator:<ref>`` instead, so a manually settled row stays distinguishable from
#: an automatic one for the life of the row — the first question of any reconciliation.
_RAIL_SETTLE_NOTE: Final[str] = "payme"
# The ``operator:`` half of that pair is NOT spelled here. It is
# :data:`bayram.payme.ports.OPERATOR_SETTLE_PREFIX`, imported above, because this module is the
# only WRITER of it while the CLI's invariant and the admin read layer are both readers, and a
# prefix spelled once per module is how ``settle_note LIKE 'operator:%'`` starts disagreeing
# with what was stored — at which point the reconciliation identity reports every use of the
# recovery button as a defect. One definition, in the module every reader already imports.


def _intent_view(row: PaymentIntentRow) -> PaymentIntent:
    """The mapped intent as everything outside ``bayram.db`` sees it (Rule 15).

    The two enum conversions go through ``.value`` rather than through a lookup table, matching
    ``bayram.db.purchases._plan_state``: the persistence enums mirror the contract enums
    value-for-value by construction, and ``tests/test_db/test_enum_lengths.py`` plus
    ``mypy --strict`` are what hold the mirror in step. A table would be a third place for the
    two to disagree.
    """
    return PaymentIntent(
        public_ref=row.public_ref,
        idempotency_key=row.idempotency_key,
        telegram_user_id=row.telegram_user_id,
        product=Product(row.product.value),
        amount_minor=row.amount_minor,
        currency=row.currency,
        language=row.language,
        merchant_id=row.merchant_id,
        is_sandbox=row.is_sandbox,
        plan_songs=row.plan_songs,
        plan_days=row.plan_days,
        state=CheckoutIntentState(row.state.value),
        valid_until=row.valid_until,
        settled_at=row.settled_at,
        notified_at=row.notified_at,
        resume_order_id=row.resume_order_id,
    )


def _transaction_view(row: PaymeTransactionRow, *, intent_public_ref: str) -> PaymeTransactionView:
    """The mapped transaction as the wire renderer sees it. Carries all three clocks verbatim.

    ``perform_time`` and ``cancel_time`` stay ``None`` here and are coerced to integer ``0``
    only at the wire, by :func:`bayram.payme.rules.wire_time`. Coercing earlier would make a
    transaction performed at the epoch indistinguishable from one never performed, in the one
    view an operator reads during an incident.
    """
    return PaymeTransactionView(
        payme_transaction_id=row.payme_transaction_id,
        our_id=row.id,
        intent_public_ref=intent_public_ref,
        payme_time=row.payme_time,
        amount_minor=row.amount_minor,
        state=ProtocolPaymeState(row.state.value),
        cancel_reason=row.cancel_reason,
        create_time=row.create_time,
        perform_time=row.perform_time,
        cancel_time=row.cancel_time,
    )


class SqlPaymeLedger:
    """The rail's persistence, satisfying ``PaymentIntentOpener`` and ``PaymeLedger`` at once.

    Built from a session factory plus four values the composition root supplies, and the
    reason each of the four is injected rather than read from settings in here is the same
    reason ``clock`` is: this object is instantiated by two different processes' containers and
    must not reach for a global.

    * ``merchant_id`` — the cashbox this deployment sells through. Compared against the intent's
      OWN stored merchant id at quote and at settlement, so a deployment repointed at a sandbox
      cashbox while a production link is still live in somebody's chat produces a refusal rather
      than a customer charged by an account nobody is reconciling.
    * ``transaction_timeout_ms`` — the rail's twelve-hour window, a SETTING so the expiry branch
      can be driven in seconds during certification. An untested branch on the money path is how
      "cancel first, refuse second" silently becomes "refuse only".
    * ``intent_ttl_s`` — how long our own link stays payable.
    * ``duplicate_code`` — the one place the rail's own materials contradict each other. The
      sandbox text demands ``-31008``, the reference PHP template returns ``-31050``, and three
      third-party packages pick something else again; shipping it as a value means a
      certification finding is an environment variable rather than a release.

    ``account_field`` is here for the same reason: the ``-31050..-31055`` family is the only one
    that carries ``data``, its value is the subfield name a human typed into the cabinet's
    «Настройка Аккаунт» form, and the refusals are raised in here — inside the transaction —
    where no settings object is in scope.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        merchant_id: str,
        clock: Callable[[], datetime] = utc_now,
        transaction_timeout_ms: int = DEFAULT_TRANSACTION_TIMEOUT_MS,
        intent_ttl_s: int = DEFAULT_INTENT_TTL_S,
        duplicate_code: int = PaymeErrorCode.STATE_REFUSAL,
        account_field: str = DEFAULT_ACCOUNT_FIELD,
    ) -> None:
        self._sessions = session_factory
        self._merchant_id = merchant_id
        self._clock = clock
        self._timeout_ms = transaction_timeout_ms
        self._intent_ttl_s = intent_ttl_s
        self._duplicate_code = duplicate_code
        self._account_field = account_field

    # -- PaymentIntentOpener ------------------------------------------------
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
        resume_order_id: UUID | None = None,
    ) -> Result[PaymentIntent]:
        return await run_guarded(
            "payme.open_intent",
            lambda: self._open_intent(
                telegram_user_id=telegram_user_id,
                product=product,
                amount_minor=amount_minor,
                currency=currency,
                idempotency_key=idempotency_key,
                language=language,
                merchant_id=merchant_id,
                is_sandbox=is_sandbox,
                plan_songs=plan_songs,
                plan_days=plan_days,
                resume_order_id=resume_order_id,
            ),
            telegram_user_id=telegram_user_id,
            idempotency_key=idempotency_key,
        )

    # -- PaymeLedger: the six inbound methods -------------------------------
    async def intent(self, *, public_ref: str) -> Result[PaymentIntent | None]:
        return await run_guarded(
            "payme.intent", lambda: self._intent(public_ref), public_ref=public_ref
        )

    async def quote(self, *, public_ref: str, amount_minor: int, now: datetime) -> Result[None]:
        return await run_guarded(
            "payme.quote",
            lambda: self._quote(public_ref=public_ref, amount_minor=amount_minor, now=now),
            public_ref=public_ref,
            amount_minor=amount_minor,
        )

    async def create(
        self,
        *,
        payme_transaction_id: str,
        payme_time: datetime,
        amount_minor: int,
        public_ref: str,
        now: datetime,
    ) -> Result[PaymeTransactionView]:
        return await run_guarded(
            "payme.create",
            lambda: self._create(
                payme_transaction_id=payme_transaction_id,
                payme_time=payme_time,
                amount_minor=amount_minor,
                public_ref=public_ref,
                now=now,
            ),
            payme_transaction_id=payme_transaction_id,
            public_ref=public_ref,
        )

    async def perform(
        self, *, payme_transaction_id: str, now: datetime
    ) -> Result[PaymeTransactionView]:
        return await run_guarded(
            "payme.perform",
            lambda: self._perform(payme_transaction_id=payme_transaction_id, now=now),
            payme_transaction_id=payme_transaction_id,
        )

    async def cancel(
        self, *, payme_transaction_id: str, reason: int, now: datetime
    ) -> Result[PaymeTransactionView]:
        return await run_guarded(
            "payme.cancel",
            lambda: self._cancel(payme_transaction_id=payme_transaction_id, reason=reason, now=now),
            payme_transaction_id=payme_transaction_id,
            reason=reason,
        )

    async def read(self, *, payme_transaction_id: str) -> Result[PaymeTransactionView]:
        return await run_guarded(
            "payme.read",
            lambda: self._read(payme_transaction_id),
            payme_transaction_id=payme_transaction_id,
        )

    async def statement(
        self, *, frm: datetime, to: datetime
    ) -> Result[tuple[PaymeStatementRow, ...]]:
        return await run_guarded(
            "payme.statement", lambda: self._statement(frm=frm, to=to), frm=frm, to=to
        )

    # -- PaymeLedger: the sweeps, the backstop and the recovery button ------
    async def expire_lapsed(self, *, now: datetime, limit: int) -> Result[int]:
        return await run_guarded(
            "payme.expire_lapsed", lambda: self._expire_lapsed(now=now, limit=limit), limit=limit
        )

    async def expire_stale_transactions(self, *, now: datetime, limit: int) -> Result[int]:
        return await run_guarded(
            "payme.expire_stale_transactions",
            lambda: self._expire_stale_transactions(now=now, limit=limit),
            limit=limit,
        )

    async def pending_notifications(
        self, *, older_than: datetime, limit: int
    ) -> Result[tuple[PaymentIntent, ...]]:
        return await run_guarded(
            "payme.pending_notifications",
            lambda: self._pending_notifications(older_than=older_than, limit=limit),
            limit=limit,
        )

    async def mark_notified(self, *, public_ref: str, now: datetime) -> Result[bool]:
        return await run_guarded(
            "payme.mark_notified",
            lambda: self._mark_notified(public_ref=public_ref, now=now),
            public_ref=public_ref,
        )

    async def claim_resume(self, *, public_ref: str, now: datetime) -> Result[bool]:
        return await run_guarded(
            "payme.claim_resume",
            lambda: self._claim_resume(public_ref=public_ref, now=now),
            public_ref=public_ref,
        )

    async def force_settle(
        self, *, public_ref: str, now: datetime, note: str
    ) -> Result[PaymentIntent]:
        return await run_guarded(
            "payme.force_settle",
            lambda: self._force_settle(public_ref=public_ref, now=now, note=note),
            public_ref=public_ref,
        )

    async def settlement_counts(self, *, frm: datetime, to: datetime) -> Result[SettlementCounts]:
        return await run_guarded(
            "payme.settlement_counts",
            lambda: self._settlement_counts(frm=frm, to=to),
            frm=frm,
            to=to,
        )

    # -- implementations ----------------------------------------------------
    async def _open_intent(
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
        plan_songs: int | None,
        plan_days: int | None,
        resume_order_id: UUID | None = None,
    ) -> PaymentIntent:
        """Insert-or-ignore, then read the WINNER back. A replay writes nothing.

        The read-back is not a nicety: ``INSERT … ON CONFLICT DO NOTHING`` reports that it lost
        and cannot report what it lost TO, and the caller needs the winner's ``public_ref``
        because that reference is what goes into the URL. Returning the reference this call
        minted would put two live payment pages in one customer's chat for one purchase, and
        the customer would have no way to tell which of them their money went into.

        The minted reference is therefore discarded on a loss, which is why it is generated
        here and passed IN rather than generated inside the insert.

        **``resume_order_id`` inherits that property, and it answers a question the render
        resume would otherwise have to guess at.** A customer who presses the price button
        twice in one wizard run, having edited their draft in between, mints the same
        ``idempotency_key`` (the counter did not move) and therefore loses the insert — so the
        intent keeps the FIRST press's marker, which is the render the link they are holding
        was opened for. The second press's marker is discarded along with its reference, and
        the mismatch is noticed at settlement, where ``runtime.render_resume`` compares this
        value against the draft it actually finds and declines rather than rendering answers
        the customer has since changed.
        """
        now = self._clock()
        intent_id = uuid4()
        async with self._sessions.begin() as session:
            await insert_intent(
                session,
                intent_id=intent_id,
                public_ref=secrets.token_hex(_PUBLIC_REF_BYTES),
                idempotency_key=idempotency_key,
                telegram_user_id=telegram_user_id,
                product=IntentProduct(product.value),
                amount_minor=amount_minor,
                currency=currency,
                plan_songs=plan_songs,
                plan_days=plan_days,
                provider=PAYME_PROVIDER_NAME,
                merchant_id=merchant_id,
                is_sandbox=is_sandbox,
                language=language,
                valid_until=now + timedelta(seconds=self._intent_ttl_s),
                resume_order_id=resume_order_id,
                now=now,
            )
            row = await intent_by_key(session, idempotency_key)
            if row is None:
                # The insert either wrote the row or lost to one already written under this
                # exact key, so a read-back that finds nothing means the row vanished inside
                # this transaction. That cannot happen today; reporting it as a storage fault
                # rolls the whole open back rather than handing the bot a link to an intent
                # the database does not hold — ``write_plan_sale`` makes the same argument.
                raise StorageError(
                    "the payment intent disappeared between being written and being read back",
                    context={
                        "telegram_user_id": telegram_user_id,
                        "idempotency_key": idempotency_key,
                    },
                )
            return _intent_view(row)

    async def _intent(self, public_ref: str) -> PaymentIntent | None:
        async with self._sessions.begin() as session:
            row = await intent_by_ref(session, public_ref)
            return None if row is None else _intent_view(row)

    async def _quote(self, *, public_ref: str, amount_minor: int, now: datetime) -> None:
        """``CheckPerformTransaction``. **Reads, refuses, and writes nothing at all.**

        Not "writes nothing important" — nothing. Payme calls this while the customer is
        looking at a payment form, possibly repeatedly, before anybody has committed to
        anything; a method that expired a lapsed intent here, or took a hold, would be acting
        on a payment that may never be attempted. ``tests/test_payme/test_state_machine.py``
        asserts it with a full row-set diff taken before and after, because "this function has
        no writes in it today" is not a property a reader can check next year.

        The transaction is opened anyway rather than using a bare session: a read that sees a
        half-applied settlement would answer about a state that never existed, and one
        statement or five, the isolation is what makes the answer a snapshot.
        """
        async with self._sessions.begin() as session:
            self._payable_intent_or_refuse(
                await intent_by_ref(session, public_ref),
                public_ref=public_ref,
                amount_minor=amount_minor,
                now=now,
            )

    async def _create(
        self,
        *,
        payme_transaction_id: str,
        payme_time: datetime,
        amount_minor: int,
        public_ref: str,
        now: datetime,
    ) -> PaymeTransactionView:
        """``CreateTransaction``. **The mutex point, and therefore the whole double-charge story.**

        Three shapes, in this order.

        1. **The transaction already exists.** This is the rail resending a create whose answer
           it never received, and the sandbox's headline assertion is that our second answer
           equals our first. So a live one is returned STORED and unchanged — the stored
           ``create_time``, not ``now`` — and nothing is written. An expired one is cancelled
           and then refused (below); anything else is a state refusal.
        2. **It does not exist and the intent will not take it.** The account ladder runs, and
           an intent already ``awaiting`` is refused through the settable duplicate code.
        3. **It does not exist and the intent is payable.** The row is inserted and then
           :func:`bayram.db.payme_sql.hold_intent` is what actually decides: ``rowcount == 0``
           means another transaction took the hold between our read and our write, so we
           refuse and the whole transaction — including the row we just inserted — rolls back.
           **That is why a second Payme transaction for one intent is refused BEFORE a card is
           charged rather than after**, and it is the single most valuable property in this
           file. A read-then-decide-then-write here would be a double charge on a busy day.
        """
        async with self._sessions.begin() as session:
            existing = await transaction_by_payme_id(session, payme_transaction_id)
            if existing is not None:
                if existing.state is not PaymeState.CREATED:
                    raise PaymeStateRefusal(
                        "a create arrived for a transaction that is no longer open",
                        context={
                            "payme_transaction_id": payme_transaction_id,
                            "state": existing.state.value,
                        },
                    )
                if not is_expired(
                    payme_time=existing.payme_time, now=now, timeout_ms=self._timeout_ms
                ):
                    return await self._view_of(session, existing)
                await self._time_out(session, existing, now=now)
            else:
                intent = self._payable_intent_or_refuse(
                    await intent_by_ref(session, public_ref),
                    public_ref=public_ref,
                    amount_minor=amount_minor,
                    now=now,
                )
                return await self._open_transaction(
                    session,
                    intent=intent,
                    payme_transaction_id=payme_transaction_id,
                    payme_time=payme_time,
                    amount_minor=amount_minor,
                    now=now,
                )
        # Reached only by the expiry branch above, and reached only AFTER the block that
        # cancelled the transaction has COMMITTED. Raising inside it would have rolled the
        # cancellation back and left the row in ``created`` while telling the rail it was
        # refused — the exact divergence between what we say and what we hold that the
        # protocol's "cancel first, refuse second" ordering exists to prevent. The test asserts
        # the ROW after this refusal, not merely the code.
        raise PaymeStateRefusal(
            "a create arrived for a transaction whose twelve-hour window had already closed",
            context={"payme_transaction_id": payme_transaction_id},
        )

    async def _perform(self, *, payme_transaction_id: str, now: datetime) -> PaymeTransactionView:
        """``PerformTransaction``. **The one commit: four rows or none, from one clock.**

        The order below is the correctness argument and every line of it is load-bearing.

        1. Read by THEIR id. **Missing is ``-31003`` and nothing is ever created here** — no
           primary source guarantees a create always precedes a perform, both official
           reference servers answer defensively, and performing an order nobody checked the
           amount, the cashbox or the expiry of would write a receipt and a credit against it.
        2. Already ``performed`` → return the STORED row, with the STORED ``perform_time``.
           Never ``now``, never an error. This is the replay guarantee certification asserts.
        3. Any other state → a state refusal. The legal transitions are three and this is not
           one of them.
        4. Past the window → cancel with reason 4 and release the intent, COMMIT that, and only
           then refuse. Cancel first, error second.
        5. ``mark_performed`` — the first conditional ``UPDATE``. ``False`` is NOT automatically
           a refusal here: the rail retries a perform whose answer was lost, two of its own
           retries can reach us at once, and the loser of that race must re-read and, finding
           the row ``performed``, return the REPLAY. Answering ``-31008`` to "did my money go
           through?" when it did is the worst wrong answer available.
        6. The cashbox check, AFTER the flip and inside the same transaction, so a mismatch
           unwinds it. It is deliberately not earlier: reading the intent before the flip would
           be a read-then-decide, and the flip is what makes this settlement ours to finish.
        7. ``claim_intent`` — the second conditional ``UPDATE``, and the exactly-once guarantee.
           ``rowcount == 0`` usually means this transaction is not the intent's holder any more,
           so we raise and the whole commit unwinds: a second Payme transaction racing for the
           same intent performs NOTHING and is refused, and the rail cancels it. It has one
           benign cause too — an operator force-settled this very intent — and
           :meth:`_already_settled_by_this_transaction_or_refuse` is where the two are told
           apart, by the holder and not by the state alone.
        8. The sale, through the SHARED write primitive
           (:func:`bayram.db.fulfilment.write_single_sale`) under the intent's OWN bot-minted key.
           Two copies of "what a paid sale writes" would be one copy that drifts, and the thing
           it would drift on is money. The key is what makes a replay, and an operator's forced
           settlement followed by a late genuine one, land on the same unique indexes.
        9. Commit. The view returned carries the stored ``perform_time``, which is the value
           every subsequent replay must also return.
        """
        async with self._sessions.begin() as session:
            row = await transaction_by_payme_id(session, payme_transaction_id)
            if row is None:
                raise PaymeTransactionNotFound(
                    "a perform arrived for a transaction we never created",
                    context={"payme_transaction_id": payme_transaction_id},
                )
            if row.state is PaymeState.PERFORMED:
                return await self._view_of(session, row)
            if row.state is not PaymeState.CREATED:
                raise PaymeStateRefusal(
                    "a perform arrived for a transaction that is no longer open",
                    context={
                        "payme_transaction_id": payme_transaction_id,
                        "state": row.state.value,
                    },
                )
            if not is_expired(payme_time=row.payme_time, now=now, timeout_ms=self._timeout_ms):
                return await self._settle(session, row, now=now)
            await self._time_out(session, row, now=now)
        # See ``_create``: the cancellation above is committed by the block we have just left,
        # and only then is the refusal raised. Cancel first, error second, in that order.
        raise PaymeStateRefusal(
            "a perform arrived for a transaction whose twelve-hour window had already closed",
            context={"payme_transaction_id": payme_transaction_id},
        )

    async def _cancel(
        self, *, payme_transaction_id: str, reason: int, now: datetime
    ) -> PaymeTransactionView:
        """``CancelTransaction``. Gives the hold back, or refuses because the goods are delivered.

        From ``created``: cancel and RELEASE the intent to ``pending``, so a customer whose card
        was declined can try another one within seconds rather than waiting out a validity
        window they did not cause to lapse. That release is the reason the intent's failure
        state is ``pending`` and not ``cancelled``.

        Already cancelled: return the STORED ``cancel_time`` and state as a SUCCESS. Never an
        error — the rail resends a cancel whose answer was lost and compares the two replies.

        From ``performed``: ``-31007``, unconditionally, and the absence of a reversal behind it
        is a decision rather than a gap. ``credit_accounts.balance`` is a single fungible scalar
        with no lot structure and ``verify_balances`` asserts it equals the sum of the ledger's
        deltas, so a compensating debit cannot know whether it is burning a credit the customer
        paid for in a DIFFERENT purchase — or one already spent on a song that has been
        delivered. PaycomUZ's own merchant template returns false from ``Order::allowCancel()``
        by default, so this is the reference behaviour. A genuine refund is a cabinet action
        plus an operator credit correction, written down in the runbook. See
        ``PAYME_INTEGRATION §6``.
        """
        async with self._sessions.begin() as session:
            row = await transaction_by_payme_id(session, payme_transaction_id)
            if row is None:
                raise PaymeTransactionNotFound(
                    "a cancel arrived for a transaction we never created",
                    context={"payme_transaction_id": payme_transaction_id},
                )
            if row.state in (PaymeState.CANCELLED, PaymeState.CANCELLED_AFTER_PERFORM):
                return await self._view_of(session, row)
            if row.state is PaymeState.PERFORMED:
                raise PaymeOrderDelivered(
                    "a cancel arrived for a transaction whose credit has already been granted",
                    context={
                        "payme_transaction_id": payme_transaction_id,
                        "reason": reason,
                    },
                )
            await mark_cancelled(
                session,
                transaction_id=row.id,
                now=now,
                reason=reason,
                from_state=PaymeState.CREATED,
                to_state=PaymeState.CANCELLED,
            )
            await release_intent(session, intent_id=row.intent_id, transaction_id=row.id, now=now)
            fresh = await transaction_by_payme_id(session, payme_transaction_id)
            if fresh is None:
                raise StorageError(
                    "the transaction disappeared between being cancelled and being read back",
                    context={"payme_transaction_id": payme_transaction_id},
                )
            return await self._view_of(session, fresh)

    async def _read(self, payme_transaction_id: str) -> PaymeTransactionView:
        """``CheckTransaction``. **Mutates nothing, not even an expiry.**

        The only method with no ``now`` parameter, and the omission is the specification rather
        than an oversight: a status read that could expire what it was asked about would make
        the rail's own poll change the answer it was polling for, and the two of us would then
        disagree about a transaction neither had touched. Expiry happens when a WRITE forces the
        machine to move, and as a scheduled backstop; never here.
        """
        async with self._sessions.begin() as session:
            row = await transaction_by_payme_id(session, payme_transaction_id)
            if row is None:
                raise PaymeTransactionNotFound(
                    "a status check arrived for a transaction we never created",
                    context={"payme_transaction_id": payme_transaction_id},
                )
            return await self._view_of(session, row)

    async def _statement(self, *, frm: datetime, to: datetime) -> tuple[PaymeStatementRow, ...]:
        """``GetStatement``. Inclusive at both ends, ascending on the rail's own clock.

        Includes every transaction whose create succeeded, whatever became of it — a cancelled
        transaction is part of the period's history and omitting it would make the two ledgers
        disagree about a period a human is reconciling line by line.

        It still answers after a ``/forget``: erasure anonymises
        ``payment_intents.telegram_user_id`` and leaves ``public_ref``, the amount, the rail
        reference and every clock intact, precisely so the account object still renders. Telling
        the rail that a transaction they can see never existed would be a worse answer than an
        anonymous one, and it would be an answer about somebody else's money.
        """
        async with self._sessions.begin() as session:
            rows = await transactions_in_period(session, frm=frm, to=to)
            return tuple(
                PaymeStatementRow(
                    transaction=_transaction_view(row, intent_public_ref=public_ref),
                    account_value=public_ref,
                    product=Product(product.value),
                )
                for row, public_ref, product in rows
            )

    async def _expire_lapsed(self, *, now: datetime, limit: int) -> int:
        """Close unpaid windows. ``pending`` only, which is the entire safety argument.

        **An intent under a live rail-side transaction is not in the set this can see.** Not
        protected from it by a check somebody has to remember — structurally absent, because
        taking a hold moves the intent to ``awaiting``. Our clock and the rail's are not the
        same clock, and an intent expired here while a card was being charged there produces
        the single worst outcome this system has.

        The conditional ``UPDATE`` re-evaluates both terms, so an intent that acquired a hold
        between the read and the write is silently skipped rather than expired.
        """
        async with self._sessions.begin() as session:
            rows = await lapsed_pending_intents(session, now=now, limit=limit)
            expired = 0
            for row in rows:
                if await expire_intent(session, intent_id=row.id, now=now):
                    expired += 1
            return expired

    async def _expire_stale_transactions(self, *, now: datetime, limit: int) -> int:
        """Cancel transactions the rail created and then never mentioned again.

        A backstop and not a mechanism: every inbound call already evaluates the same predicate
        before it acts. This exists so a transaction nobody follows up does not sit in
        ``created`` forever, making ``CheckTransaction`` report state 1 about a charge that can
        no longer happen and leaving its intent held by a transaction that will never complete.

        The window is applied TWICE on purpose — once as a SQL cutoff to bound the read, and
        once through :func:`bayram.payme.rules.is_expired` to decide. The SQL comparison is
        inclusive and the predicate's boundary is exclusive (at exactly ``timeout_ms`` the
        window is still open, because refusing a payment we are entitled to take is the worse
        of the two one-millisecond errors), so the read deliberately over-selects by one
        millisecond and the predicate is what actually chooses. One boundary, in one place.
        """
        cutoff = now - timedelta(milliseconds=self._timeout_ms)
        async with self._sessions.begin() as session:
            rows = await stale_created_transactions(session, cutoff=cutoff, limit=limit)
            cancelled = 0
            for row in rows:
                if not is_expired(payme_time=row.payme_time, now=now, timeout_ms=self._timeout_ms):
                    continue
                await self._time_out(session, row, now=now)
                cancelled += 1
            return cancelled

    async def _pending_notifications(
        self, *, older_than: datetime, limit: int
    ) -> tuple[PaymentIntent, ...]:
        async with self._sessions.begin() as session:
            rows = await unnotified_settled_intents(session, older_than=older_than, limit=limit)
            return tuple(_intent_view(row) for row in rows)

    async def _mark_notified(self, *, public_ref: str, now: datetime) -> bool:
        async with self._sessions.begin() as session:
            row = await intent_by_ref(session, public_ref)
            if row is None:
                raise not_found("payment_intent", public_ref=public_ref)
            return await mark_intent_notified(session, intent_id=row.id, now=now)

    async def _claim_resume(self, *, public_ref: str, now: datetime) -> bool:
        async with self._sessions.begin() as session:
            row = await intent_by_ref(session, public_ref)
            if row is None:
                raise not_found("payment_intent", public_ref=public_ref)
            return await claim_intent_resume(session, intent_id=row.id, now=now)

    async def _force_settle(self, *, public_ref: str, now: datetime, note: str) -> PaymentIntent:
        """The recovery button. Settles by hand under the intent's OWN key, so a late rail call
        collapses onto the same unique indexes and grants nothing twice.

        "The customer paid and got nothing" is the commonest real payment incident, and this
        rail has no outbound Merchant API method with which to ask what happened — so the
        answer has to be a local write an operator can make from the cabinet's evidence.

        **Already paid is a no-op that says so**, returning the existing intent with its
        original ``settle_note`` and ``settled_at`` intact, so an operator who presses the
        button twice learns that the first press worked rather than writing a second note over
        the first. Cancelled and expired intents are refused outright by
        :func:`bayram.db.payme_sql.claim_intent_for_operator`'s state terms.

        The note is stamped as ``operator:<text>`` and truncated to the column's width rather
        than refused for length: this is an incident tool, the operator is typing under
        pressure, and losing the tail of a free-text note is a better outcome than losing the
        settlement to a validation error.
        """
        async with self._sessions.begin() as session:
            row = await intent_by_ref(session, public_ref)
            if row is None:
                raise not_found("payment_intent", public_ref=public_ref)
            if row.state is PaymentIntentState.PAID:
                _log.info(
                    "a force-settle was asked for an intent that is already paid; nothing written",
                    extra={"public_ref": public_ref, "settle_note": row.settle_note},
                )
                return _intent_view(row)
            if row.telegram_user_id is None:
                raise PaymentError(
                    "refusing to force-settle an intent whose buyer has been erased",
                    context={"public_ref": public_ref, "state": row.state.value},
                )
            claimed = await claim_intent_for_operator(
                session,
                intent_id=row.id,
                now=now,
                note=f"{OPERATOR_SETTLE_PREFIX}{note}"[:SETTLE_NOTE_LENGTH],
            )
            if not claimed:
                raise PaymentError(
                    "refusing to force-settle an intent that is not open",
                    context={"public_ref": public_ref, "state": row.state.value},
                )
            await self._write_sale(
                session,
                intent=row,
                telegram_user_id=row.telegram_user_id,
                reference=public_ref,
                now=now,
            )
            settled = await intent_by_ref(session, public_ref)
            if settled is None:
                raise StorageError(
                    "the intent disappeared between being settled and being read back",
                    context={"public_ref": public_ref},
                )
            return _intent_view(settled)

    async def _settlement_counts(self, *, frm: datetime, to: datetime) -> SettlementCounts:
        async with self._sessions.begin() as session:
            performed, receipts, grants = await settlement_counts(session, frm=frm, to=to)
            return SettlementCounts(
                transactions_performed=performed,
                receipts_written=receipts,
                grants_written=grants,
            )

    # -- the pieces the methods above are assembled from --------------------
    async def _settle(
        self, session: AsyncSession, row: PaymeTransactionRow, *, now: datetime
    ) -> PaymeTransactionView:
        """Steps 5 to 9 of :meth:`_perform`, in the caller's transaction. Commits nothing.

        Separated from ``_perform`` so that method reads as its own ordered argument, and NOT
        made public: it takes a session it does not own, and a caller outside this class could
        only reach it by breaking the one-transaction guarantee it depends on.
        """
        if not await mark_performed(session, transaction_id=row.id, now=now):
            # The rail's own retry lost a race with itself: another connection flipped this
            # exact transaction between our read and our write. The correct answer is the
            # REPLAY, not ``-31008`` — the money did go through, and telling the rail otherwise
            # about a charge it can see would turn a healthy retry into a support ticket.
            fresh = await transaction_by_payme_id(session, row.payme_transaction_id)
            if fresh is not None and fresh.state is PaymeState.PERFORMED:
                return await self._view_of(session, fresh)
            raise PaymeStateRefusal(
                "the transaction left the created state while it was being performed",
                context={
                    "payme_transaction_id": row.payme_transaction_id,
                    "state": None if fresh is None else fresh.state.value,
                },
            )
        intent = await intent_by_id(session, row.intent_id)
        if intent is None:
            raise StorageError(
                "a transaction points at an intent that does not exist",
                context={
                    "payme_transaction_id": row.payme_transaction_id,
                    "intent_id": str(row.intent_id),
                },
            )
        if intent.merchant_id != self._merchant_id:
            raise PaymeAccountFault(
                "a settlement arrived for a link issued by a different cashbox",
                rpc_code=PaymeErrorCode.ACCOUNT_WRONG_MERCHANT,
                account_field=self._account_field,
                context={
                    "payme_transaction_id": row.payme_transaction_id,
                    "public_ref": intent.public_ref,
                },
            )
        if not await claim_intent(
            session,
            intent_id=intent.id,
            transaction_id=row.id,
            now=now,
            note=_RAIL_SETTLE_NOTE,
        ):
            intent = self._already_settled_by_this_transaction_or_refuse(
                await intent_by_id(session, row.intent_id), row
            )
        if intent.telegram_user_id is None:
            # ``/forget`` ran between the payment being started and it being settled. The money
            # has moved — the rail is telling us so, not asking — and there is nobody left to
            # grant a credit to, so the intent is claimed and NO sale is written. Refusing
            # instead would leave the rail retrying a charge it has already taken, and it would
            # be the one outcome worse than an ungranted credit: a customer debited against an
            # order we keep declining. The three-way settlement invariant surfaces it as a
            # performed transaction with no receipt, which is exactly what an operator must see.
            _log.error(
                "a payment settled for an account that had already been erased; no credit granted",
                extra={
                    "payme_transaction_id": row.payme_transaction_id,
                    "public_ref": intent.public_ref,
                    "amount_minor": intent.amount_minor,
                },
            )
        else:
            await self._write_sale(
                session,
                intent=intent,
                telegram_user_id=intent.telegram_user_id,
                reference=row.payme_transaction_id,
                now=now,
            )
        fresh = await transaction_by_payme_id(session, row.payme_transaction_id)
        if fresh is None:
            raise StorageError(
                "the transaction disappeared between being performed and being read back",
                context={"payme_transaction_id": row.payme_transaction_id},
            )
        return _transaction_view(fresh, intent_public_ref=intent.public_ref)

    def _already_settled_by_this_transaction_or_refuse(
        self, intent: PaymentIntentRow | None, row: PaymeTransactionRow
    ) -> PaymentIntentRow:
        """``claim_intent`` lost. Decide whether that is a refusal or the OPERATOR's settlement.

        A zero rowcount on the claim has two causes and they call for opposite answers.

        **A refusal**, and the common case: another transaction holds the intent, or it was
        released or expired between the flip above and here. Raising unwinds the flip in the
        same commit, so this transaction performs NOTHING and the rail cancels it. That is the
        exactly-once guarantee, expressed as a rollback rather than as a compensating write.

        **Not a refusal**, and the case this method exists for: the intent is already ``paid``
        AND its holder is still THIS transaction. That is what an operator's ``force_settle``
        leaves behind — ``claim_intent_for_operator`` names no holder, so the hold this
        transaction took survives the manual settlement. The money is genuinely ours, the
        receipt and the grant were written under the intent's own bot-minted key, and the
        correct answer to the rail's late-but-genuine ``PerformTransaction`` is **state 2**.
        Refusing it would be the worst outcome the recovery button could produce: an operator
        unsticks a customer, and the rail then cancels the very charge that paid for it.

        The settlement continues past this point on purpose. Every write ahead of it is
        insert-or-ignore on the SAME ``idempotency_key`` the operator's settlement used, so a
        second receipt and a second grant are not written — they are refused by a unique index,
        which is the only place that guarantee is safe to rest. ``settle_note`` keeps the
        operator's ``operator:<ref>`` value, because who moved this money is a fact about the
        past and not about which call arrived last.

        The holder comparison is what makes it safe: an intent paid by a DIFFERENT transaction
        fails it and is refused, which is exactly the concurrent double-charge case.
        """
        if (
            intent is not None
            and intent.state is PaymentIntentState.PAID
            and intent.active_transaction_id == row.id
        ):
            _log.info(
                "a perform arrived for an intent an operator had already settled; replaying it",
                extra={
                    "payme_transaction_id": row.payme_transaction_id,
                    "public_ref": intent.public_ref,
                    "settle_note": intent.settle_note,
                },
            )
            return intent
        raise PaymeStateRefusal(
            "the intent this transaction was holding is no longer claimable by it",
            context={
                "payme_transaction_id": row.payme_transaction_id,
                "intent_id": str(row.intent_id),
                "intent_state": None if intent is None else intent.state.value,
            },
        )

    async def _write_sale(
        self,
        session: AsyncSession,
        *,
        intent: PaymentIntentRow,
        telegram_user_id: int,
        reference: str,
        now: datetime,
    ) -> None:
        """Route the settled intent to the right receipt, through the SHARED write primitive.

        The product on the INTENT decides, not a branch in a handler — which is precisely why
        :func:`bayram.db.fulfilment.write_plan_sale` gained a product guard during the extraction
        that made these functions callable from here. Both write primitives refuse first and
        write second, inside this transaction, so a malformed intent unwinds the rail's state
        flip along with everything else.

        ``reference`` is the RAIL's own id on a genuine settlement and our ``public_ref`` on an
        operator's forced one, because in the second case the rail has minted nothing we can
        quote. Both are what an operator would search for in the cabinet, which is the only
        thing that column is for.

        The ``Purchase`` is built here rather than by the caller so that ``is_paid=True`` is
        asserted in exactly one place on this path, next to the money that justifies it.
        """
        purchase = Purchase(
            product=Product(intent.product.value),
            provider=PAYME_PROVIDER_NAME,
            reference=reference,
            amount_minor=intent.amount_minor,
            currency=intent.currency,
            is_paid=True,
        )
        if intent.product is IntentProduct.SINGLE:
            await write_single_sale(
                session,
                telegram_user_id=telegram_user_id,
                purchase=purchase,
                idempotency_key=intent.idempotency_key,
                now=now,
            )
            return
        if intent.plan_songs is None or intent.plan_days is None:
            # ``ck_payment_intents_plan_fields_present`` makes this unreachable through any
            # write this package performs. It is checked anyway because the alternative is a
            # ``None`` reaching ``plan_purchases.songs_included`` — NOT NULL — as an
            # ``IntegrityError`` raised from inside the money transaction, whose message names
            # a constraint rather than the intent that is malformed.
            raise StorageError(
                "a plan intent reached settlement without its plan snapshot",
                context={
                    "public_ref": intent.public_ref,
                    "plan_songs": intent.plan_songs,
                    "plan_days": intent.plan_days,
                },
            )
        await write_plan_sale(
            session,
            telegram_user_id=telegram_user_id,
            purchase=purchase,
            songs=intent.plan_songs,
            days=intent.plan_days,
            idempotency_key=intent.idempotency_key,
            now=now,
        )

    async def _open_transaction(
        self,
        session: AsyncSession,
        *,
        intent: PaymentIntentRow,
        payme_transaction_id: str,
        payme_time: datetime,
        amount_minor: int,
        now: datetime,
    ) -> PaymeTransactionView:
        """Insert the transaction, then take the hold. **The hold is what decides.**

        See :meth:`_create` for the ordering argument.
        """
        transaction_id = uuid4()
        if not await insert_transaction(
            session,
            transaction_id=transaction_id,
            payme_transaction_id=payme_transaction_id,
            intent_id=intent.id,
            payme_time=payme_time,
            amount_minor=amount_minor,
            create_time=now,
            now=now,
        ):
            # Two of the rail's own retries reached us at once and the other one won the unique
            # index. The correct answer is its row, not a refusal — the same argument
            # ``_settle`` makes about a lost ``mark_performed``: our caller is asking whether
            # this transaction exists, and it does.
            raced = await transaction_by_payme_id(session, payme_transaction_id)
            if raced is not None and raced.state is PaymeState.CREATED:
                return _transaction_view(raced, intent_public_ref=intent.public_ref)
            raise PaymeStateRefusal(
                "a create lost a race and the winning transaction is no longer open",
                context={
                    "payme_transaction_id": payme_transaction_id,
                    "state": None if raced is None else raced.state.value,
                },
            )
        if not await hold_intent(
            session, intent_id=intent.id, transaction_id=transaction_id, now=now
        ):
            # **The mutex.** Another transaction took the hold between the account ladder's
            # read and this write. Raising rolls back the row inserted moments ago, so the
            # second transaction never exists — and the customer is refused on the payment page
            # instead of being charged twice and reconciled afterwards.
            raise PaymeStateRefusal(
                "this order already has another active transaction",
                rpc_code=self._duplicate_code,
                context={
                    "payme_transaction_id": payme_transaction_id,
                    "public_ref": intent.public_ref,
                },
            )
        written = await transaction_by_payme_id(session, payme_transaction_id)
        if written is None:
            raise StorageError(
                "the transaction disappeared between being written and being read back",
                context={"payme_transaction_id": payme_transaction_id},
            )
        return _transaction_view(written, intent_public_ref=intent.public_ref)

    async def _time_out(
        self, session: AsyncSession, row: PaymeTransactionRow, *, now: datetime
    ) -> None:
        """Cancel a lapsed transaction with reason 4 and give its intent back. Commits nothing.

        Both booleans are deliberately ignored. A lost ``mark_cancelled`` means somebody else
        cancelled the same transaction first, and a lost ``release_intent`` means the intent was
        already released or has since been taken by a newer transaction; in every case the
        desired end state is the one that already holds, and re-raising would turn an idempotent
        housekeeping write into an error the rail would retry.

        The caller must COMMIT this before refusing — see :meth:`_create` and :meth:`_perform`.
        The order "cancel, then refuse" is asserted by reading the row after the refusal rather
        than by trusting the returned code.
        """
        await mark_cancelled(
            session,
            transaction_id=row.id,
            now=now,
            reason=int(CancelReason.TIMEOUT),
            from_state=PaymeState.CREATED,
            to_state=PaymeState.CANCELLED,
        )
        await release_intent(session, intent_id=row.intent_id, transaction_id=row.id, now=now)

    def _payable_intent_or_refuse(
        self,
        row: PaymentIntentRow | None,
        *,
        public_ref: str,
        amount_minor: int,
        now: datetime,
    ) -> PaymentIntentRow:
        """The account ladder, shared by ``CheckPerformTransaction`` and ``CreateTransaction``.

        **One ladder and not two**, because the rail calls the first method to find out whether
        the second will succeed, and a check that could pass while the create then failed would
        show a customer a payment form for an order we were about to refuse.

        The order of the rungs is the protocol's, not ours:

        * no such reference, or a reference whose buyer has been erased → ``-31050``. Erasure is
          grouped with "unknown" deliberately: after ``/forget`` we can no longer say whose
          order this is, and continuing to take money against it would settle a purchase for an
          account that has asked to stop existing. The row survives so ``GetStatement`` can
          still answer about transactions the rail already knows of; it just stops being
          payable.
        * a different cashbox → ``-31055``. This rung exists only because the intent stores the
          merchant id it was ISSUED for, and it is what turns a deployment repointed at a
          sandbox account — while a production link is still live in somebody's chat — into a
          refusal instead of a customer charged by an account nobody reconciles.
        * a terminal intent state → ``-31051`` paid, ``-31052`` cancelled, ``-31053`` expired,
          through :func:`bayram.payme.rules.account_fault_for`, which returns ``None`` for the two
          non-terminal states rather than inventing an answer for them.
        * ``awaiting`` → a STATE refusal through the settable duplicate code, not an account
          fault. It is a different kind of "no": the order is fine, another transaction has it.
        * lapsed while still ``pending`` → ``-31053``, evaluated against the caller's ``now``
          rather than against a sweep having run. The machine is therefore correct at every
          instant and the sweep is only a backstop.
        * the wrong amount → ``-31001``. **A refusal and never a re-price**: reading the current
          price out of settings here would let a price change between the tap and the payment
          charge a customer a number they were never shown.

        Raises rather than returning a code, so that a caller inside a transaction unwinds by
        construction rather than by remembering to branch. It hands the row BACK on success for
        the same reason: the alternative shapes are a ``None``-returning guard plus an
        ``assert`` at every call site (an assertion on the money path, and one ``python -O``
        deletes) or two functions that read the same row twice. Returning the narrowed row makes
        ``mypy --strict`` do that work instead, and ``_quote`` — which wants the refusal and not
        the row — simply discards it.
        """
        if row is None or row.telegram_user_id is None:
            raise PaymeAccountFault(
                "no payable order exists under that reference",
                rpc_code=PaymeErrorCode.ACCOUNT_UNKNOWN,
                account_field=self._account_field,
                context={"public_ref": public_ref, "erased": row is not None},
            )
        if row.merchant_id != self._merchant_id:
            raise PaymeAccountFault(
                "that order was issued for a different cashbox",
                rpc_code=PaymeErrorCode.ACCOUNT_WRONG_MERCHANT,
                account_field=self._account_field,
                context={"public_ref": public_ref},
            )
        terminal = account_fault_for(CheckoutIntentState(row.state.value))
        if terminal is not None:
            raise PaymeAccountFault(
                "that order is no longer payable",
                rpc_code=terminal,
                account_field=self._account_field,
                context={"public_ref": public_ref, "state": row.state.value},
            )
        if row.state is PaymentIntentState.AWAITING:
            raise PaymeStateRefusal(
                "this order already has another active transaction",
                rpc_code=self._duplicate_code,
                context={"public_ref": public_ref},
            )
        if row.valid_until <= now:
            raise PaymeAccountFault(
                "that order's payment window has closed",
                rpc_code=PaymeErrorCode.ACCOUNT_EXPIRED,
                account_field=self._account_field,
                context={"public_ref": public_ref},
            )
        if row.amount_minor != amount_minor:
            raise PaymeAmountMismatch(
                "the amount quoted does not match the amount the order was opened for",
                context={
                    "public_ref": public_ref,
                    "quoted_minor": amount_minor,
                    "opened_minor": row.amount_minor,
                },
            )
        return row

    async def _view_of(
        self, session: AsyncSession, row: PaymeTransactionRow
    ) -> PaymeTransactionView:
        """Attach the intent's account reference to a transaction row.

        A second read rather than a column on ``payme_transactions``: ``public_ref`` belongs to
        the intent, duplicating it onto the transaction would be two places for one identifier
        to be true, and every caller of this helper is already inside a transaction where the
        read costs one indexed lookup by primary key.
        """
        intent = await intent_by_id(session, row.intent_id)
        if intent is None:
            raise StorageError(
                "a transaction points at an intent that does not exist",
                context={
                    "payme_transaction_id": row.payme_transaction_id,
                    "intent_id": str(row.intent_id),
                },
            )
        return _transaction_view(row, intent_public_ref=intent.public_ref)
