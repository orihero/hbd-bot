"""``SqlPaymeLedger``'s persistence contracts: idempotent opens, one-winner UPDATEs, recovery.

``tests/test_payme/test_state_machine.py`` drives the PROTOCOL — the replay guarantees and the
races, in the vocabulary Payme speaks. This file is the other half: the promises the ledger
makes to the rest of this repository rather than to the rail. Three of them, and each has cost
somebody money somewhere:

* an open is idempotent on the bot's own key, so a double tap is one payment page and not two;
* every state transition is a conditional ``UPDATE`` that exactly ONE caller can win, whatever
  order N callers arrive in;
* an operator can settle a payment by hand and the rail's late, genuine settlement then grants
  nothing twice — which is what makes the recovery button safe to press before anybody knows
  whether the rail will call.

It lives in ``tests/test_db`` rather than beside the protocol suite because it uses that
package's ``sessions`` and ``clock`` fixtures and asserts against columns, not against wire
codes. Every Telegram id is outside the 32-bit range, for the reason
``tests/test_db/test_payme_tables.py`` gives.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import PaymentIntent, PaymentIntentOpener, Product
from bayram.contracts import is_err, is_ok
from bayram.db.enums import CreditEntryKind, PaymentIntentState, PaymeState
from bayram.db.models import CreditAccountRow, CreditLedgerRow
from bayram.db.models.payme_rpc_log import RPC_METHOD_LENGTH, PaymeRpcLogRow
from bayram.db.models.payme_transaction import PaymeTransactionRow
from bayram.db.models.payment_intent import SETTLE_NOTE_LENGTH, PaymentIntentRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.db.payme import SqlPaymeLedger
from bayram.db.payme_sql import (
    anonymise_intents,
    claim_intent,
    hold_intent,
    insert_rpc_log,
    intent_by_ref,
    settlement_counts,
    transaction_count_for_intent,
)
from bayram.payme.ports import PaymeLedger
from tests.test_db.conftest import MovableClock

_USER: Final[int] = 8_912_345_678_901
_MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"
_PRICE: Final[int] = 700_000


def _ledger(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock, **overrides: Any
) -> SqlPaymeLedger:
    return SqlPaymeLedger(sessions, merchant_id=_MERCHANT, clock=clock, **overrides)


async def _open(ledger: SqlPaymeLedger, *, key: str = f"topup:{_USER}:single:1") -> PaymentIntent:
    opened = await ledger.open_intent(
        telegram_user_id=_USER,
        product=Product.SINGLE,
        amount_minor=_PRICE,
        currency="UZS",
        idempotency_key=key,
        language="uz_latn",
        merchant_id=_MERCHANT,
        is_sandbox=True,
    )
    assert is_ok(opened), opened
    return opened.value


async def _count(sessions: async_sessionmaker[AsyncSession], table: type[Any]) -> int:
    async with sessions() as session:
        total = await session.scalar(sa.select(sa.func.count()).select_from(table))
        return int(total or 0)


async def _balance(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        found = await session.scalar(
            sa.select(CreditAccountRow.balance).where(CreditAccountRow.telegram_user_id == _USER)
        )
        return int(found or 0)


async def _row(sessions: async_sessionmaker[AsyncSession], public_ref: str) -> PaymentIntentRow:
    async with sessions() as session:
        found = await intent_by_ref(session, public_ref)
        assert found is not None
        return found


# ---------------------------------------------------------------------------
# Two ports, one class — and the asymmetry between them is a security control
# ---------------------------------------------------------------------------
def _the_bots_handle(opener: PaymentIntentOpener) -> PaymentIntentOpener:
    """Accept the ledger as the narrow port. **``mypy --strict`` is the real assertion here.**

    ``runtime_checkable`` verifies member PRESENCE only and would happily accept an object
    whose ``open_intent`` had drifted to a different signature, so the ``isinstance`` check
    below is worth little on its own. Passing the ledger through a parameter ANNOTATED as the
    protocol is what makes the type checker compare every argument name, default and return
    type — the same mechanism ``bayram.checkout.PaymentIntentOpener``'s own docstring names.
    """
    return opener


def _the_gateways_handle(ledger: PaymeLedger) -> PaymeLedger:
    """The same object as the WIDE port. See :func:`_the_bots_handle`."""
    return ledger


async def test_one_ledger_satisfies_both_ports_and_the_bots_half_cannot_settle(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)

    # Act — hand the same object to both seams, each typed as its own port.
    narrow = _the_bots_handle(ledger)
    wide = _the_gateways_handle(ledger)

    # Assert — structurally both, by construction and not by inheritance, exactly as
    # ``SqlPurchaseLedger`` satisfies ``PurchaseFulfiller``.
    assert isinstance(ledger, PaymentIntentOpener)
    assert isinstance(ledger, PaymeLedger)
    assert narrow is wide is ledger
    # ...and the narrow port genuinely cannot settle: the bot process holds a reference typed
    # as ``PaymentIntentOpener``, and ``perform`` is absent from it. This is the runtime shadow
    # of a compile-time guarantee — ``narrow.perform(...)`` is a mypy error, which is what
    # actually stops it, and the attribute check is what a reader can see from here.
    assert not hasattr(PaymentIntentOpener, "perform")
    assert {"open_intent"} == {
        name for name in vars(PaymentIntentOpener) if not name.startswith("_")
    }


# ---------------------------------------------------------------------------
# open_intent is idempotent on the BOT's key
# ---------------------------------------------------------------------------
async def test_a_replayed_open_writes_nothing_and_returns_the_same_public_ref(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — one key, three taps, which is what a redelivered Telegram update looks like.
    ledger = _ledger(sessions, clock)

    # Act
    first = await _open(ledger)
    clock.advance(seconds=30)
    second = await _open(ledger)
    third = await _open(ledger)

    # Assert — the SAME reference, therefore the same URL, therefore one payment page. A second
    # reference would put two live pages in one chat and the customer could not tell which of
    # them took their money.
    assert first.public_ref == second.public_ref == third.public_ref
    assert first.valid_until == second.valid_until
    assert await _count(sessions, PaymentIntentRow) == 1


async def test_two_different_keys_open_two_intents_with_different_references(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act — a deliberate second purchase, minted under a fresh key by the bot.
    ledger = _ledger(sessions, clock)
    first = await _open(ledger, key=f"topup:{_USER}:single:1")
    second = await _open(ledger, key=f"topup:{_USER}:single:2")

    # Assert
    assert first.public_ref != second.public_ref
    assert await _count(sessions, PaymentIntentRow) == 2


async def test_the_intent_records_the_cashbox_and_the_sandbox_flag_it_was_issued_under(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act — both are stored rather than derived at read time, so the answer is the one
    # that was true when the LINK was built and not the one that is true when it is settled.
    intent = await _open(_ledger(sessions, clock))

    # Assert
    row = await _row(sessions, intent.public_ref)
    assert row.merchant_id == _MERCHANT
    assert row.is_sandbox is True
    assert row.provider == "payme"
    assert row.state is PaymentIntentState.PENDING
    assert row.valid_until == clock.now + timedelta(hours=12)


# ---------------------------------------------------------------------------
# The rowcount IS the lock: exactly one winner across N callers
# ---------------------------------------------------------------------------
async def test_hold_intent_returns_true_exactly_once_across_many_callers(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent = await _open(_ledger(sessions, clock))
    row = await _row(sessions, intent.public_ref)

    # Act — five different rail-side transactions all try to take the hold.
    outcomes: list[bool] = []
    for _ in range(5):
        async with sessions.begin() as session:
            outcomes.append(
                await hold_intent(session, intent_id=row.id, transaction_id=uuid4(), now=clock.now)
            )

    # Assert — one winner. This is the statement that stops a second card being charged.
    assert outcomes.count(True) == 1
    assert outcomes[0] is True
    held = await _row(sessions, intent.public_ref)
    assert held.state is PaymentIntentState.AWAITING
    assert held.active_transaction_id is not None


async def test_claim_intent_returns_true_exactly_once_and_only_for_the_holder(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — one holder, and an impostor that never held anything.
    intent = await _open(_ledger(sessions, clock))
    row = await _row(sessions, intent.public_ref)
    holder = uuid4()
    impostor = uuid4()
    async with sessions.begin() as session:
        assert await hold_intent(session, intent_id=row.id, transaction_id=holder, now=clock.now)

    # Act
    outcomes: list[bool] = []
    for claimant in (impostor, holder, holder, impostor):
        async with sessions.begin() as session:
            outcomes.append(
                await claim_intent(
                    session,
                    intent_id=row.id,
                    transaction_id=claimant,
                    now=clock.now,
                    note="payme",
                )
            )

    # Assert — the impostor never wins even before the holder has claimed, and the holder wins
    # once. Conditioning on the HOLDER and not on the state alone is what makes that true.
    assert outcomes == [False, True, False, False]
    claimed = await _row(sessions, intent.public_ref)
    assert claimed.state is PaymentIntentState.PAID
    assert claimed.settled_at == clock.now


# ---------------------------------------------------------------------------
# The recovery button
# ---------------------------------------------------------------------------
async def test_force_settle_grants_under_the_intents_own_key_and_stamps_an_operator_note(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the customer paid, the cabinet shows the money, our Perform never arrived.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)

    # Act
    settled = await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-42")

    # Assert — one receipt, one grant, one credit, keyed on the string the BOT minted.
    assert is_ok(settled)
    assert settled.value.state.value == "paid"
    row = await _row(sessions, intent.public_ref)
    assert row.settle_note == "operator:INC-42"
    assert row.settled_at == clock.now
    assert await _balance(sessions) == 1
    async with sessions() as session:
        receipt = (await session.execute(sa.select(TopupPurchaseRow))).scalar_one()
        entry = (await session.execute(sa.select(CreditLedgerRow))).scalar_one()
    assert receipt.idempotency_key == intent.idempotency_key
    assert receipt.provider == "payme"
    assert receipt.reference == intent.public_ref
    assert entry.idempotency_key == intent.idempotency_key
    assert entry.kind is CreditEntryKind.GRANT


async def test_a_late_genuine_perform_after_a_force_settle_grants_nothing_twice(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The load-bearing property of the recovery button, and the reason it uses the SAME key.

    An operator presses ``settle`` because the rail has gone quiet. The rail then wakes up and
    performs the very transaction they settled around. Both must be true afterwards: the rail
    is told **state 2** — refusing here would cancel the charge that paid for the credit an
    operator just handed over — and there is still exactly ONE credit, because both writes land
    on the same unique index.
    """
    # Arrange — a live rail-side transaction holds the intent when the operator intervenes.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    identifier = uuid4().hex[:24]
    created = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=intent.public_ref,
        now=clock.now,
    )
    assert is_ok(created)
    forced = await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-42")
    assert is_ok(forced)

    # Act — the rail's genuine settlement arrives ten minutes later.
    clock.advance(seconds=600)
    performed = await ledger.perform(payme_transaction_id=identifier, now=clock.now)

    # Assert
    assert is_ok(performed)
    assert performed.value.state.value == "performed"
    assert await _count(sessions, TopupPurchaseRow) == 1
    assert await _count(sessions, CreditLedgerRow) == 1
    assert await _balance(sessions) == 1
    # The note records WHO moved the money, and that is a fact about the past: the rail's later
    # call does not rewrite it.
    assert (await _row(sessions, intent.public_ref)).settle_note == "operator:INC-42"


async def test_force_settling_an_already_paid_intent_writes_nothing_and_keeps_the_first_note(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — an operator presses the button twice under pressure.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    assert is_ok(
        await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-42")
    )

    # Act
    clock.advance(seconds=60)
    again = await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-43")

    # Assert — a no-op that says so, rather than a second note over the first.
    assert is_ok(again)
    row = await _row(sessions, intent.public_ref)
    assert row.settle_note == "operator:INC-42"
    assert await _balance(sessions) == 1
    assert await _count(sessions, TopupPurchaseRow) == 1


async def test_force_settling_an_expired_intent_is_refused_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    clock.advance(days=1)
    assert is_ok(await ledger.expire_lapsed(now=clock.now, limit=10))

    # Act
    refused = await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-42")

    # Assert — ``claim_intent_for_operator``'s state terms exclude every terminal state, so a
    # dead intent cannot be resurrected by an operator any more than by the rail.
    assert is_err(refused)
    assert await _count(sessions, TopupPurchaseRow) == 0
    assert await _balance(sessions) == 0


async def test_force_settling_an_unknown_reference_is_a_not_found_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act
    refused = await _ledger(sessions, clock).force_settle(
        public_ref="deadbeef" * 3, now=clock.now, note="INC-42"
    )

    # Assert
    assert is_err(refused)
    assert await _count(sessions, TopupPurchaseRow) == 0


# ---------------------------------------------------------------------------
# The notification backstop
# ---------------------------------------------------------------------------
async def test_settled_intents_appear_in_the_notification_backlog_once_and_only_once(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    assert is_ok(
        await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-42")
    )
    settled_at = clock.now
    clock.advance(seconds=120)

    # Act
    backlog = await ledger.pending_notifications(older_than=clock.now, limit=10)
    stamped = await ledger.mark_notified(public_ref=intent.public_ref, now=clock.now)
    again = await ledger.mark_notified(public_ref=intent.public_ref, now=clock.now)
    after = await ledger.pending_notifications(older_than=clock.now, limit=10)

    # Assert — the second stamp loses, which is how two deliveries racing send one message.
    assert is_ok(backlog)
    assert [held.public_ref for held in backlog.value] == [intent.public_ref]
    assert backlog.value[0].settled_at == settled_at
    assert backlog.value[0].language == "uz_latn"
    assert is_ok(stamped)
    assert stamped.value is True
    assert is_ok(again)
    assert again.value is False
    assert is_ok(after)
    assert after.value == ()


async def test_a_settlement_newer_than_the_cutoff_is_left_to_its_own_enqueue(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the post-commit enqueue fires within milliseconds; a backstop that also fired
    # would double-enqueue every healthy payment and make its own error rate unreadable.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    assert is_ok(
        await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-42")
    )

    # Act
    fresh = await ledger.pending_notifications(
        older_than=clock.now - timedelta(seconds=60), limit=10
    )

    # Assert
    assert is_ok(fresh)
    assert fresh.value == ()


# ---------------------------------------------------------------------------
# Erasure
# ---------------------------------------------------------------------------
async def test_anonymise_intents_nulls_the_buyer_and_keeps_every_money_column(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a settled intent, because that is the row erasure is most tempted to delete.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    assert is_ok(
        await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-42")
    )

    # Act
    async with sessions.begin() as session:
        touched = await anonymise_intents(session, telegram_user_id=_USER)

    # Assert — the person goes, the payment stays. A DELETE here would make ``GetStatement``
    # tell the rail that a transaction they can see in their own cabinet never existed.
    assert touched == 1
    row = await _row(sessions, intent.public_ref)
    assert row.telegram_user_id is None
    assert row.public_ref == intent.public_ref
    assert row.idempotency_key == intent.idempotency_key
    assert row.amount_minor == _PRICE
    assert row.currency == "UZS"
    assert row.merchant_id == _MERCHANT
    assert row.settle_note == "operator:INC-42"
    assert row.settled_at is not None
    assert row.valid_until is not None


async def test_an_erased_intent_drops_out_of_the_notification_backlog(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — ``/forget`` between the payment and the notification. Nobody is left to tell,
    # so ``notified_at`` will never be stamped; leaving the row in the backlog would re-enqueue
    # it every five minutes for the life of the deployment.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    assert is_ok(
        await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-42")
    )
    async with sessions.begin() as session:
        await anonymise_intents(session, telegram_user_id=_USER)
    clock.advance(seconds=120)

    # Act
    backlog = await ledger.pending_notifications(older_than=clock.now, limit=10)

    # Assert
    assert is_ok(backlog)
    assert backlog.value == ()


async def test_an_erased_intent_is_no_longer_payable(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    async with sessions.begin() as session:
        await anonymise_intents(session, telegram_user_id=_USER)

    # Act
    refused = await ledger.quote(public_ref=intent.public_ref, amount_minor=_PRICE, now=clock.now)

    # Assert — grouped with "unknown order", because after erasure we can no longer say whose
    # order this is, and taking money against it would settle a purchase for an account that
    # asked to stop existing. The row survives so a statement can still answer about it.
    assert is_err(refused)
    assert await _count(sessions, PaymentIntentRow) == 1


# ---------------------------------------------------------------------------
# The operator's two read primitives
# ---------------------------------------------------------------------------
async def test_the_transaction_count_tells_an_abandoned_intent_from_a_failed_payment(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — two intents that both end up ``expired``, for opposite reasons. One customer
    # never opened the payment page; the other's charge was attempted and never completed.
    ledger = _ledger(sessions, clock)
    abandoned = await _open(ledger, key=f"topup:{_USER}:single:1")
    attempted = await _open(ledger, key=f"topup:{_USER}:single:2")
    identifier = uuid4().hex[:24]
    assert is_ok(
        await ledger.create(
            payme_transaction_id=identifier,
            payme_time=clock.now,
            amount_minor=_PRICE,
            public_ref=attempted.public_ref,
            now=clock.now,
        )
    )

    # Act
    async with sessions() as session:
        never_tried = await transaction_count_for_intent(
            session, intent_id=(await _row(sessions, abandoned.public_ref)).id
        )
        tried = await transaction_count_for_intent(
            session, intent_id=(await _row(sessions, attempted.public_ref)).id
        )

    # Assert — a read-time predicate, which is why the distinction needs no column and cannot
    # drift from what the transaction table actually holds. Zero is a funnel problem; more than
    # zero is a rail problem, and an operator has to be able to tell them apart.
    assert never_tried == 0
    assert tried == 1


async def test_the_rpc_journal_records_one_call_and_truncates_a_hostile_method_name(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — an UNKNOWN method is exactly the thing this journal exists to record, so the
    # column is a VARCHAR and the writer truncates rather than a closed enum raising and losing
    # the row an incident needs.
    hostile = "A" * (RPC_METHOD_LENGTH * 4)

    # Act
    async with sessions.begin() as session:
        await insert_rpc_log(
            session,
            at=clock.now,
            method="CheckPerformTransaction",
            payme_transaction_id=None,
            public_ref="deadbeefdeadbeefdeadbeef",
            reply_code=0,
            peer_ip="185.234.113.1",
            duration_ms=7,
        )
        await insert_rpc_log(
            session,
            at=clock.now,
            method=hostile,
            payme_transaction_id=None,
            public_ref=None,
            reply_code=-32601,
            peer_ip=None,
            duration_ms=1,
        )

    # Assert — two rows, no key to collapse them onto (two identical retries are two genuinely
    # different events), and no body, header or Telegram id anywhere on the table.
    async with sessions() as session:
        rows = (
            (await session.execute(sa.select(PaymeRpcLogRow).order_by(PaymeRpcLogRow.reply_code)))
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert rows[0].reply_code == -32601
    assert rows[0].method == "A" * RPC_METHOD_LENGTH
    assert rows[0].peer_ip is None
    assert rows[1].method == "CheckPerformTransaction"
    assert rows[1].peer_ip == "185.234.113.1"
    assert rows[1].duration_ms == 7
    assert not hasattr(PaymeRpcLogRow, "telegram_user_id")


async def test_marking_an_unknown_reference_notified_is_an_error_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act — distinct from "already stamped", which is a legitimate ``False``. A
    # reference nobody issued is a bug in the caller, not an outcome of the delivery race.
    stamped = await _ledger(sessions, clock).mark_notified(public_ref="deadbeef" * 3, now=clock.now)

    # Assert
    assert is_err(stamped)


async def test_force_settling_an_erased_buyer_is_refused_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — ``/forget`` ran, so there is no account to grant to. An operator pressing the
    # recovery button must be told that rather than have a credit written to nobody.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    async with sessions.begin() as session:
        await anonymise_intents(session, telegram_user_id=_USER)

    # Act
    refused = await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="INC-42")

    # Assert — and the intent is untouched, so a statement can still answer about it.
    assert is_err(refused)
    assert (await _row(sessions, intent.public_ref)).state is PaymentIntentState.PENDING
    assert await _count(sessions, TopupPurchaseRow) == 0


async def test_an_operator_note_longer_than_the_column_is_truncated_not_refused(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — an incident tool used under pressure. Losing the tail of a free-text note is a
    # better outcome than losing the settlement to a validation error.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)

    # Act
    settled = await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="x" * 500)

    # Assert
    assert is_ok(settled)
    row = await _row(sessions, intent.public_ref)
    assert row.settle_note is not None
    assert row.settle_note.startswith("operator:x")
    assert len(row.settle_note) == SETTLE_NOTE_LENGTH
    assert await _balance(sessions) == 1


# ---------------------------------------------------------------------------
# The three-way reconciliation
# ---------------------------------------------------------------------------
async def test_the_settlement_counts_agree_after_one_genuine_settlement(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    identifier = uuid4().hex[:24]
    assert is_ok(
        await ledger.create(
            payme_transaction_id=identifier,
            payme_time=clock.now,
            amount_minor=_PRICE,
            public_ref=intent.public_ref,
            now=clock.now,
        )
    )
    assert is_ok(await ledger.perform(payme_transaction_id=identifier, now=clock.now))

    # Act
    counted = await ledger.settlement_counts(
        frm=clock.now - timedelta(hours=1), to=clock.now + timedelta(hours=1)
    )

    # Assert — one performed transaction, one receipt, one grant. The equality that must always
    # hold is the first two; the third is the single-song subset.
    assert is_ok(counted)
    assert counted.value.transactions_performed == 1
    assert counted.value.receipts_written == 1
    assert counted.value.grants_written == 1


async def test_a_deleted_receipt_shows_up_as_a_settlement_mismatch(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the defect the invariant exists to catch, injected by hand: a performed
    # transaction whose receipt is gone. There is no outbound Merchant API method to ask the
    # rail what it thinks, so this local count is the only automated check on the shared write
    # primitive.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    identifier = uuid4().hex[:24]
    assert is_ok(
        await ledger.create(
            payme_transaction_id=identifier,
            payme_time=clock.now,
            amount_minor=_PRICE,
            public_ref=intent.public_ref,
            now=clock.now,
        )
    )
    assert is_ok(await ledger.perform(payme_transaction_id=identifier, now=clock.now))
    async with sessions.begin() as session:
        await session.execute(sa.delete(TopupPurchaseRow))

    # Act
    async with sessions() as session:
        performed, receipts, grants = await settlement_counts(
            session, frm=clock.now - timedelta(hours=1), to=clock.now + timedelta(hours=1)
        )

    # Assert — reported, never self-repaired: a scheduler that silently wrote the missing
    # receipt back would destroy the only evidence that the primitive had drifted.
    assert (performed, receipts, grants) == (1, 0, 1)


async def test_a_cancelled_transaction_counts_towards_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    identifier = uuid4().hex[:24]
    assert is_ok(
        await ledger.create(
            payme_transaction_id=identifier,
            payme_time=clock.now,
            amount_minor=_PRICE,
            public_ref=intent.public_ref,
            now=clock.now,
        )
    )
    assert is_ok(await ledger.cancel(payme_transaction_id=identifier, reason=2, now=clock.now))

    # Act
    counted = await ledger.settlement_counts(
        frm=clock.now - timedelta(hours=1), to=clock.now + timedelta(hours=1)
    )

    # Assert
    assert is_ok(counted)
    assert counted.value.transactions_performed == 0
    assert counted.value.receipts_written == 0
    assert counted.value.grants_written == 0
    assert await _count(sessions, PaymeTransactionRow) == 1
    async with sessions() as session:
        row = (await session.execute(sa.select(PaymeTransactionRow))).scalar_one()
    assert row.state is PaymeState.CANCELLED


# ---------------------------------------------------------------------------
# the resume claim
# ---------------------------------------------------------------------------
async def test_the_resume_claim_succeeds_once_and_refuses_thereafter(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """**The only durable at-most-once latch the auto-render has.**

    ``notify_payment_settled`` is at-least-once by construction — five ARQ attempts, the
    sweep's backstop, and two processes enqueuing the same job name — so a side effect placed
    in that job with no latch of its own fires once per attempt. This one bills a vendor and
    delivers a song, so "once" has to be a property of the ROW rather than of whichever caller
    read it first.
    """
    # Arrange
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)
    assert is_ok(await ledger.force_settle(public_ref=intent.public_ref, now=clock.now, note="x"))

    # Act
    first = await ledger.claim_resume(public_ref=intent.public_ref, now=clock.now)
    second = await ledger.claim_resume(public_ref=intent.public_ref, now=clock.now)

    # Assert — and the second is ``Ok(False)``, not an error: a redelivered job is ordinary.
    assert is_ok(first) and first.value is True
    assert is_ok(second) and second.value is False


async def test_the_resume_claim_refuses_an_intent_that_is_not_paid(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``state = 'paid'`` is a CONJUNCT of the claim, not an assumption about the caller.

    ``resumed_at IS NULL`` alone would let a stale read of a not-yet-settled intent take the
    claim and start a render for money that has not arrived — which is how a free song is
    given away. The row refuses it, so no caller has to remember to.
    """
    # Arrange — opened, never settled.
    ledger = _ledger(sessions, clock)
    intent = await _open(ledger)

    # Act
    claimed = await ledger.claim_resume(public_ref=intent.public_ref, now=clock.now)

    # Assert
    assert is_ok(claimed) and claimed.value is False


async def test_claiming_a_resume_for_an_unknown_reference_is_an_error(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act — the same distinction ``mark_notified`` draws: a reference nobody issued
    # is a bug in the caller, while an already-claimed one is a legitimate ``False``.
    claimed = await _ledger(sessions, clock).claim_resume(public_ref="deadbeef" * 3, now=clock.now)

    # Assert
    assert is_err(claimed)


async def test_an_opened_intent_carries_the_render_it_was_opened_for(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)
    order_id = uuid4()

    # Act
    opened = await ledger.open_intent(
        telegram_user_id=_USER,
        product=Product.SINGLE,
        amount_minor=_PRICE,
        currency="UZS",
        idempotency_key=f"topup:{_USER}:marker:1",
        language="uz_latn",
        merchant_id=_MERCHANT,
        is_sandbox=True,
        resume_order_id=order_id,
    )

    # Assert
    assert is_ok(opened)
    assert opened.value.resume_order_id == order_id


async def test_a_replayed_open_returns_the_first_presss_marker(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The winner's marker, and this is the answer to "what if the draft changed in between?".

    A customer who presses the price button twice in one wizard run, having edited their draft
    between the presses, mints the SAME ``idempotency_key`` — the counter did not move — so the
    second insert is ignored and the intent keeps the render the link they are holding was
    opened for. The second press's marker is discarded along with its reference, and the
    mismatch is noticed at settlement rather than silently overwriting the first here.
    """
    # Arrange
    ledger = _ledger(sessions, clock)
    key = f"topup:{_USER}:marker:2"
    first_draft, second_draft = uuid4(), uuid4()

    async def open_with(order_id: UUID) -> PaymentIntent:
        opened = await ledger.open_intent(
            telegram_user_id=_USER,
            product=Product.SINGLE,
            amount_minor=_PRICE,
            currency="UZS",
            idempotency_key=key,
            language="uz_latn",
            merchant_id=_MERCHANT,
            is_sandbox=True,
            resume_order_id=order_id,
        )
        assert is_ok(opened)
        return opened.value

    # Act
    first = await open_with(first_draft)
    replayed = await open_with(second_draft)

    # Assert — one intent, one reference, and the FIRST press's render.
    assert replayed.public_ref == first.public_ref
    assert replayed.resume_order_id == first_draft
