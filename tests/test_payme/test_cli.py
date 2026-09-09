"""The operator CLI, driven against a real database. **The recovery mechanism, proved.**

This suite exists because the CLI is not a convenience: it is the whole of the incident response
for this rail on day one, and a recovery tool that has never been run is a recovery tool that
does not work. Every test below is written as the sentence an operator would say during the
incident it belongs to.

**The load-bearing test is
``test_a_late_genuine_perform_after_a_force_settle_grants_nothing_twice``.** Everything else here
is about legibility; that one is about money. Force-settling writes the sale under the intent's
OWN bot-minted idempotency key — the same string a genuine ``PerformTransaction`` would use — so
the two collapse onto one unique index. If that ever stops being true, an operator pressing the
recovery button while unsure whether the rail will call would double-grant, and the tool's entire
premise ("it is safe to press this") would be false. It is asserted against a real engine, a real
unique index and a real ``PerformTransaction``, because it is a property of a commit boundary and
cannot be checked with a fake.

**The second is
``test_the_pause_switch_is_never_read_on_an_inbound_perform``.** The switch stops NEW checkouts
and must never refuse money already in flight — refusing a charge a customer's bank has already
moved is how an incident becomes a dispute, and this rail cannot reverse a performed transaction
(``-31007`` by design). The test asserts the mechanism rather than the outcome: a counting switch
that records every read, and zero reads across a full settlement.

Everything runs against in-memory SQLite from a ``MovableClock``, with a fake pause switch and a
recording notifier, so no Redis and no Postgres are needed. The one thing not exercised here is
``main`` reaching a real container, which needs a database URL in the environment; the parsing
half of ``main`` is exercised directly, because that is the half that refuses.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from hbd.checkout import PaymentIntent, Product, PurchaseRequest
from hbd.contracts import Language, is_err, is_ok
from hbd.db.engine import create_session_factory
from hbd.db.enums import CreditEntryKind
from hbd.db.models import Base, CreditLedgerRow
from hbd.db.models.payme_rpc_log import PaymeRpcLogRow
from hbd.db.models.payment_intent import PaymentIntentRow
from hbd.db.models.topup_purchase import TopupPurchaseRow
from hbd.db.payme import SqlPaymeLedger
from hbd.errors import CheckoutPausedError, StorageError
from hbd.payme.cli import (
    EXIT_MISMATCH,
    EXIT_OK,
    EXIT_REFUSED,
    OPERATOR_SETTLE_PREFIX,
    Invariant,
    Journal,
    Notify,
    OperatorConsole,
    Pause,
    Reconcile,
    RefusedError,
    Settle,
    Statement,
    Status,
    apply,
    main,
    plan,
)
from hbd.payme.pause import PAUSED_VALUE, PAYME_PAUSE_KEY, is_paused, set_paused
from hbd.payme.protocol import CancelReason
from hbd.payme.provider import PaymeCheckoutProvider
from tests.conftest import FIXED_NOW
from tests.test_db.conftest import MovableClock

#: Well outside 2**31, matching the rest of this package's suites: an accidental ``Integer``
#: column on the payment path would not fail loudly, it would truncate the id of whoever paid.
_USER: Final[int] = 8_912_345_678_901
#: A 24-character ObjectId, the shape a real cashbox id has.
_MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"
#: 7 000 soʻm in tiyin. Already the number the rail is sent; nothing on this path multiplies.
_PRICE: Final[int] = 700_000
_ACCOUNT_FIELD: Final[str] = "order_id"


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------
class FakeSwitch:
    """A Redis stand-in for the pause key that can be made to fail on command.

    A dict rather than a real client because the two properties under test — "a read that fails
    is not a pause" and "a write that fails is loud" — are unreachable against a healthy Redis
    and would otherwise be asserted by reading the source. ``reads`` counts every ``get``, which
    is how the settlement path proves it never consults the switch at all.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.reads: int = 0
        self.read_fails: bool = False
        self.write_fails: bool = False

    async def get(self, name: str) -> Any:
        self.reads += 1
        if self.read_fails:
            raise ConnectionError("redis is unwell")
        return self.values.get(name)

    async def set(self, name: str, value: str) -> Any:
        if self.write_fails:
            raise ConnectionError("redis is unwell")
        self.values[name] = value
        return True

    async def delete(self, *names: str) -> Any:
        if self.write_fails:
            raise ConnectionError("redis is unwell")
        for name in names:
            self.values.pop(name, None)
        return len(names)


class RecordingNotifier:
    """Stands in for the ARQ enqueue and records which intents were announced."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fails: bool = False

    async def __call__(self, public_ref: str) -> None:
        if self.fails:
            raise ConnectionError("redis is unwell")
        self.calls.append(public_ref)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    built = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with built.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield built
    await built.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock(FIXED_NOW)


@pytest.fixture
def ledger(sessions: async_sessionmaker[AsyncSession], clock: MovableClock) -> SqlPaymeLedger:
    return SqlPaymeLedger(sessions, merchant_id=_MERCHANT, clock=clock)


@pytest.fixture
def switch() -> FakeSwitch:
    return FakeSwitch()


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def console(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    switch: FakeSwitch,
    notifier: RecordingNotifier,
    clock: MovableClock,
) -> OperatorConsole:
    """The production object graph with two edges swapped for doubles. Nothing else is faked."""
    return OperatorConsole(
        ledger=ledger,
        sessions=sessions,
        switch=switch,
        notify=notifier,
        clock=clock,
        merchant_id=_MERCHANT,
        account_field=_ACCOUNT_FIELD,
        is_sandbox=True,
        is_enabled=True,
    )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def payme_id() -> str:
    """A 24-character hex id, the shape of the Mongo ObjectId the rail actually sends."""
    return uuid4().hex[:24]


async def open_intent(
    ledger: SqlPaymeLedger,
    *,
    product: Product = Product.SINGLE,
    plan_songs: int | None = None,
    plan_days: int | None = None,
) -> PaymentIntent:
    opened = await ledger.open_intent(
        telegram_user_id=_USER,
        product=product,
        amount_minor=_PRICE,
        currency="UZS",
        idempotency_key=f"topup:{_USER}:single:{uuid4().hex[:8]}",
        language="uz_latn",
        merchant_id=_MERCHANT,
        is_sandbox=True,
        plan_songs=plan_songs,
        plan_days=plan_days,
    )
    assert is_ok(opened), opened
    return opened.value


async def settled_by_the_rail(
    ledger: SqlPaymeLedger, intent: PaymentIntent, *, now: datetime
) -> str:
    """A genuine create-then-perform. Returns the rail-side id it settled under."""
    identifier = payme_id()
    created = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=now,
        amount_minor=intent.amount_minor,
        public_ref=intent.public_ref,
        now=now,
    )
    assert is_ok(created), created
    performed = await ledger.perform(payme_transaction_id=identifier, now=now)
    assert is_ok(performed), performed
    return identifier


async def count_of(sessions: async_sessionmaker[AsyncSession], table: type[Any]) -> int:
    async with sessions() as session:
        return int(await session.scalar(sa.select(sa.func.count()).select_from(table)) or 0)


async def grants_in(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(CreditLedgerRow)
                .where(CreditLedgerRow.kind == CreditEntryKind.GRANT)
            )
            or 0
        )


def counted(text: str, label: str) -> int:
    """The number this report printed against ``label``.

    Reports are aligned with padding, so asserting on the rendered spacing would make every
    count test fail the day a longer label widens the column. This reads the number instead,
    which is the thing under test — the layout is not.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(label):
            return int(stripped.removeprefix(label).split()[0])
    raise AssertionError(f"no line for {label!r} in:\n{text}")


async def intent_row(
    sessions: async_sessionmaker[AsyncSession], public_ref: str
) -> PaymentIntentRow:
    async with sessions() as session:
        return (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == public_ref)
            )
        ).scalar_one()


# ---------------------------------------------------------------------------
# settle — the recovery button
# ---------------------------------------------------------------------------
async def test_settle_writes_one_receipt_and_one_grant_under_the_intents_own_key(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a customer whose money reached the cabinet and whose callback never arrived.
    intent = await open_intent(ledger)

    # Act
    report = await apply(console, Settle(public_ref=intent.public_ref, note="cabinet 4471"))

    # Assert — exactly one sale, one grant, and the key they landed under is the intent's own.
    assert report.exit_code == EXIT_OK
    assert await count_of(sessions, TopupPurchaseRow) == 1
    assert await grants_in(sessions) == 1
    async with sessions() as session:
        receipt = (await session.execute(sa.select(TopupPurchaseRow))).scalar_one()
    assert receipt.idempotency_key == intent.idempotency_key
    row = await intent_row(sessions, intent.public_ref)
    assert row.state is not None
    assert row.settle_note is not None
    assert row.settle_note.startswith(OPERATOR_SETTLE_PREFIX)
    assert "cabinet 4471" in row.settle_note
    assert "Settled." in report.text()


async def test_a_late_genuine_perform_after_a_force_settle_grants_nothing_twice(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    """**The load-bearing property.** Press the button, then let the rail call anyway.

    This is the exact sequence an operator produces in a real incident: the customer says they
    paid, the callback has not arrived, the operator settles from the cabinet's evidence, and
    forty minutes later Payme's retry finally lands. Both write under the intent's own
    idempotency key, so the second write is insert-or-ignore on a unique index that already has
    a row — one receipt, one grant, one credit.
    """
    # Arrange — a rail-side transaction exists and its Perform has not reached us.
    intent = await open_intent(ledger)
    identifier = payme_id()
    created = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=intent.public_ref,
        now=clock.now,
    )
    assert is_ok(created), created

    # Act — the operator settles by hand, and only then does the genuine Perform arrive.
    settled = await apply(console, Settle(public_ref=intent.public_ref, note="cabinet 4471"))
    assert settled.exit_code == EXIT_OK
    later = clock.advance(seconds=2400)
    performed = await ledger.perform(payme_transaction_id=identifier, now=later)

    # Assert — the rail is answered successfully and nothing was written a second time.
    assert is_ok(performed), performed
    assert await count_of(sessions, TopupPurchaseRow) == 1
    assert await grants_in(sessions) == 1
    async with sessions() as session:
        total = await session.scalar(
            sa.select(sa.func.sum(CreditLedgerRow.delta)).where(
                CreditLedgerRow.telegram_user_id == _USER
            )
        )
    assert int(total or 0) == 1


async def test_settle_on_an_already_paid_intent_writes_nothing_and_says_so(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — the rail already settled this one.
    intent = await open_intent(ledger)
    await settled_by_the_rail(ledger, intent, now=clock.now)
    before = await count_of(sessions, TopupPurchaseRow)

    # Act
    report = await apply(console, Settle(public_ref=intent.public_ref, note="just in case"))

    # Assert — the first settlement stands, with its own note, and no second one was written.
    assert report.exit_code == EXIT_OK
    assert "already paid" in report.text()
    assert await count_of(sessions, TopupPurchaseRow) == before
    row = await intent_row(sessions, intent.public_ref)
    assert row.settle_note is not None
    assert not row.settle_note.startswith(OPERATOR_SETTLE_PREFIX)


async def test_settle_without_a_note_refuses_before_anything_is_built() -> None:
    """A missing ``--note`` never reaches a database, and neither does an empty one.

    Two refusals with two shapes, deliberately. ``argparse`` handles the ABSENT flag and exits
    the way every POSIX tool does; the empty string is ours, because ``--note ""`` satisfies
    argparse and would otherwise write a hand-settled sale with no recorded reason — an
    unexplained credit that an auditor reads months later with nothing to go on.
    """
    with pytest.raises(SystemExit):
        plan(["settle", "--ref", "a" * 24])
    with pytest.raises(RefusedError, match="empty --note"):
        plan(["settle", "--ref", "a" * 24, "--note", "   "])


async def test_settle_refuses_a_reference_that_could_never_be_ours() -> None:
    # Arrange / Act / Assert — a mistyped reference is a sentence, not a round trip.
    with pytest.raises(RefusedError, match="lowercase hexadecimal"):
        plan(["settle", "--ref", "ORDER-1234", "--note", "x"])


async def test_settle_refuses_an_unknown_reference_and_writes_nothing(
    console: OperatorConsole, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Arrange — a well-formed reference that no intent was ever opened under.
    with pytest.raises(RefusedError):
        await apply(console, Settle(public_ref="ab" * 12, note="cabinet 1"))

    # Assert
    assert await count_of(sessions, TopupPurchaseRow) == 0
    assert await grants_in(sessions) == 0


# ---------------------------------------------------------------------------
# pause — stops NEW checkouts, and never a payment in flight
# ---------------------------------------------------------------------------
async def test_pause_stops_a_new_checkout_and_resume_restores_it(
    console: OperatorConsole, ledger: SqlPaymeLedger, switch: FakeSwitch
) -> None:
    """The switch, end to end: the CLI writes it and the bot's own provider reads it."""
    # Arrange — the real provider, reading the real switch through the real reader.
    provider = PaymeCheckoutProvider(
        ledger,
        merchant_id=_MERCHANT,
        base_url="https://test.paycom.uz",
        account_field=_ACCOUNT_FIELD,
        return_url="",
        is_sandbox=True,
        plan_songs=4,
        plan_days=30,
        language_of=lambda: Language.UZ_LATN,
        paused=lambda: is_paused(switch),
    )
    request = PurchaseRequest(
        telegram_user_id=_USER,
        product=Product.SINGLE,
        amount_minor=_PRICE,
        currency="UZS",
        idempotency_key=f"topup:{_USER}:single:1",
    )

    # Act / Assert — paused, the sale is refused; resumed, the same request gets a link.
    paused_report = await apply(console, Pause(paused=True))
    assert switch.values[PAYME_PAUSE_KEY] == PAUSED_VALUE
    assert "PAUSED" in paused_report.text()

    refused = await provider.charge(request)
    assert is_err(refused)
    assert isinstance(refused.error, CheckoutPausedError)

    resumed_report = await apply(console, Pause(paused=False))
    assert PAYME_PAUSE_KEY not in switch.values
    assert "OPEN" in resumed_report.text()

    allowed = await provider.charge(request)
    assert is_ok(allowed), allowed
    assert allowed.value.is_paid is False
    assert allowed.value.checkout_url is not None


async def test_the_pause_switch_is_never_read_on_an_inbound_perform(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    switch: FakeSwitch,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    """**Refusing money already in flight is how an incident becomes a dispute.**

    Asserted as a mechanism, not an outcome: the switch counts its reads, and a full
    create-then-perform against a PAUSED rail must produce zero of them. An outcome assertion
    ("the perform succeeded") would still pass on the day somebody added a pause check that
    happened to be evaluated after the settlement.
    """
    # Arrange — an intent opened before the pause, and a paused rail.
    intent = await open_intent(ledger)
    await apply(console, Pause(paused=True))
    reads_before = switch.reads

    # Act — Payme charges the card and calls us.
    await settled_by_the_rail(ledger, intent, now=clock.now)

    # Assert — the money landed and the switch was never consulted.
    assert switch.reads == reads_before
    assert await count_of(sessions, TopupPurchaseRow) == 1
    assert await grants_in(sessions) == 1


async def test_a_pause_switch_that_cannot_be_read_is_not_a_pause(
    switch: FakeSwitch, caplog: pytest.LogCaptureFixture
) -> None:
    """An unreachable Redis silently stopping every sale is the worse outage. See the module."""
    # Arrange
    switch.values[PAYME_PAUSE_KEY] = PAUSED_VALUE
    switch.read_fails = True

    # Act
    with caplog.at_level(logging.WARNING):
        answer = await is_paused(switch)

    # Assert — open, and loudly enough to be findable afterwards.
    assert answer is False
    assert any("could not be read" in record.message for record in caplog.records)


async def test_a_pause_that_cannot_be_written_refuses_instead_of_lying(
    switch: FakeSwitch,
) -> None:
    """The write may not guess. An operator is about to act on believing the rail is shut."""
    # Arrange
    switch.write_fails = True

    # Act / Assert
    with pytest.raises(StorageError):
        await set_paused(switch, paused=True)
    assert PAYME_PAUSE_KEY not in switch.values


async def test_a_hand_written_zero_in_redis_does_not_pause_the_rail(switch: FakeSwitch) -> None:
    # Arrange — somebody typed `redis-cli SET hbd:payme:paused 0` meaning "off".
    switch.values[PAYME_PAUSE_KEY] = "0"

    # Act / Assert — it means what they meant.
    assert await is_paused(switch) is False


# ---------------------------------------------------------------------------
# status — the screen an operator opens first
# ---------------------------------------------------------------------------
async def test_status_tells_an_abandoned_intent_from_one_whose_payment_started(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    """Two very different incidents that would otherwise look identical in one ``expired`` count.

    An expired intent that never held a rail-side transaction is a customer who never reached
    the payment form — a funnel problem. One that DID hold a transaction is a payment that
    started and did not finish — a rail problem. The split is a read-time predicate, so it needs
    no column and cannot drift out of step with the rows it describes.
    """
    # Arrange — one customer walks away from the link, one starts paying and the card declines.
    walked_away = await open_intent(ledger)
    tried_to_pay = await open_intent(ledger)
    identifier = payme_id()
    created = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=tried_to_pay.public_ref,
        now=clock.now,
    )
    assert is_ok(created), created
    cancelled = await ledger.cancel(
        payme_transaction_id=identifier, reason=int(CancelReason.DEBIT_ERROR), now=clock.now
    )
    assert is_ok(cancelled), cancelled
    # Both intents are now `pending` and both lapse when their validity window closes.
    later = clock.advance(days=1)
    expired = await ledger.expire_lapsed(now=later, limit=10)
    assert is_ok(expired), expired
    assert expired.value == 2

    # Act
    report = await apply(console, Status(hours=48))

    # Assert
    text = report.text()
    assert counted(text, "expired, never started") == 1
    assert counted(text, "expired, payment started") == 1
    assert counted(text, "opened") == 2
    assert walked_away.public_ref != tried_to_pay.public_ref
    assert await count_of(sessions, TopupPurchaseRow) == 0


async def test_status_reports_the_pause_switch_and_that_payme_has_never_called(
    console: OperatorConsole, switch: FakeSwitch
) -> None:
    # Arrange
    await apply(console, Pause(paused=True))

    # Act
    report = await apply(console, Status(hours=24))

    # Assert — the two facts an operator needs before doing anything else.
    text = report.text()
    assert "PAUSED" in text
    assert "never reached this endpoint" in text
    assert switch.reads >= 1


# ---------------------------------------------------------------------------
# invariant — the three-way settlement count
# ---------------------------------------------------------------------------
async def test_invariant_balances_after_one_rail_settlement(
    console: OperatorConsole, ledger: SqlPaymeLedger, clock: MovableClock
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    await settled_by_the_rail(ledger, intent, now=clock.now)

    # Act
    report = await apply(console, Invariant(hours=24))

    # Assert
    assert report.exit_code == EXIT_OK
    text = report.text()
    assert counted(text, "performed transactions") == 1
    assert counted(text, "receipts written") == 1
    assert counted(text, "credit grants written") == 1
    assert "Balanced." in text


async def test_invariant_reports_a_mismatch_when_a_receipt_is_deleted_by_hand(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    """The defect this count exists to catch, simulated the only way a test can: by hand.

    A real occurrence would be the shared paid-sale write primitive drifting so that a performed
    transaction stopped producing a receipt. Deleting the receipt reaches the same state, and
    the exit code is what makes this reachable from a monitoring cron.
    """
    # Arrange
    intent = await open_intent(ledger)
    await settled_by_the_rail(ledger, intent, now=clock.now)
    async with sessions.begin() as session:
        await session.execute(sa.delete(TopupPurchaseRow))

    # Act
    report = await apply(console, Invariant(hours=24))

    # Assert — reported, exit 3, and explicitly not repaired.
    assert report.exit_code == EXIT_MISMATCH
    assert "MISMATCH" in report.text()
    assert "NOT self-repaired" in report.text()
    assert await count_of(sessions, TopupPurchaseRow) == 0


async def test_invariant_counts_an_operator_settlement_so_recovery_is_not_an_alert(
    console: OperatorConsole, ledger: SqlPaymeLedger
) -> None:
    """A hand-settled intent has no performed transaction. Reporting three raw numbers would
    make every use of the recovery button look like a defect, which is how an alert gets muted.
    """
    # Arrange
    intent = await open_intent(ledger)
    await apply(console, Settle(public_ref=intent.public_ref, note="cabinet 4471"))

    # Act
    report = await apply(console, Invariant(hours=24))

    # Assert
    assert report.exit_code == EXIT_OK
    text = report.text()
    assert counted(text, "performed transactions") == 0
    assert counted(text, "settled by an operator") == 1
    assert counted(text, "receipts written") == 1
    assert "Balanced." in text


# ---------------------------------------------------------------------------
# journal — "did Payme ever call us about this, and what did we say?"
# ---------------------------------------------------------------------------
async def test_journal_shows_the_intent_its_transactions_the_receipt_and_the_rpc_calls(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — a settled payment, plus the journal row the gateway writes per inbound call.
    intent = await open_intent(ledger)
    identifier = await settled_by_the_rail(ledger, intent, now=clock.now)
    async with sessions.begin() as session:
        session.add(
            PaymeRpcLogRow(
                at=clock.now,
                method="PerformTransaction",
                payme_transaction_id=identifier,
                public_ref=intent.public_ref,
                reply_code=0,
                peer_ip="185.234.113.4",
                duration_ms=31,
            )
        )

    # Act
    report = await apply(
        console,
        Journal(public_ref=intent.public_ref, payme_transaction_id=None, since=None, limit=10),
    )

    # Assert — all six tables, in one answer.
    text = report.text()
    assert intent.public_ref in text
    assert identifier in text
    assert intent.idempotency_key in text
    assert "performed" in text
    assert "topup" in text
    assert "PerformTransaction" in text
    assert "185.234.113.4" in text


async def test_journal_by_paymes_own_id_finds_the_same_payment(
    console: OperatorConsole, ledger: SqlPaymeLedger, clock: MovableClock
) -> None:
    """The id an operator has in front of them is usually the rail's, not ours."""
    # Arrange
    intent = await open_intent(ledger)
    identifier = await settled_by_the_rail(ledger, intent, now=clock.now)

    # Act
    report = await apply(
        console, Journal(public_ref=None, payme_transaction_id=identifier, since=None, limit=10)
    )

    # Assert
    assert intent.public_ref in report.text()


async def test_journal_says_plainly_when_payme_never_called_about_an_intent(
    console: OperatorConsole, ledger: SqlPaymeLedger
) -> None:
    """The sentence that tells an operator this is a ``settle`` case rather than a bug hunt."""
    # Arrange
    intent = await open_intent(ledger)

    # Act
    report = await apply(
        console,
        Journal(public_ref=intent.public_ref, payme_transaction_id=None, since=None, limit=10),
    )

    # Assert
    text = report.text()
    assert "never opened a transaction" in text
    assert "never called this endpoint" in text
    assert "no sale has been written" in text


async def test_journal_refuses_a_payme_id_nothing_was_ever_created_under(
    console: OperatorConsole,
) -> None:
    with pytest.raises(RefusedError, match="ever been created here"):
        await apply(
            console,
            Journal(public_ref=None, payme_transaction_id=payme_id(), since=None, limit=10),
        )


async def test_journal_since_lists_recent_intents_newest_first(
    console: OperatorConsole, ledger: SqlPaymeLedger, clock: MovableClock
) -> None:
    # Arrange
    first = await open_intent(ledger)
    clock.advance(seconds=60)
    second = await open_intent(ledger)

    # Act
    report = await apply(
        console,
        Journal(
            public_ref=None,
            payme_transaction_id=None,
            since=FIXED_NOW - timedelta(hours=1),
            limit=10,
        ),
    )

    # Assert
    text = report.text()
    assert first.public_ref in text
    assert second.public_ref in text
    assert text.index(second.public_ref) < text.index(first.public_ref)


# ---------------------------------------------------------------------------
# statement — the row set a human diffs against a cabinet export
# ---------------------------------------------------------------------------
async def test_statement_prints_the_rows_get_statement_would_return(
    console: OperatorConsole, ledger: SqlPaymeLedger, clock: MovableClock
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    identifier = await settled_by_the_rail(ledger, intent, now=clock.now)

    # Act
    report = await apply(
        console, Statement(frm=clock.now - timedelta(hours=1), to=clock.now + timedelta(hours=1))
    )

    # Assert — the rail's id, our reference and the account field name Payme was told to use.
    text = report.text()
    assert "1 transaction(s)." in text
    assert identifier in text
    assert f"{_ACCOUNT_FIELD}={intent.public_ref}" in text


async def test_statement_refuses_a_period_that_runs_backwards() -> None:
    with pytest.raises(RefusedError, match="falls before"):
        plan(["statement", "--from", "2026-09-09T10:00:00Z", "--to", "2026-09-09T09:00:00Z"])


async def test_a_naive_instant_is_read_as_utc_rather_than_refused() -> None:
    """An operator during an incident types ``2026-09-09T14:00``. Pedantry costs attention."""
    # Act
    request = plan(["statement", "--from", "2026-09-09T14:00", "--to", "2026-09-09T15:00"])

    # Assert
    assert isinstance(request, Statement)
    assert request.frm == datetime(2026, 9, 9, 14, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# notify — re-enqueue an announcement, and refuse the cases that would do nothing
# ---------------------------------------------------------------------------
async def test_notify_queues_a_settled_payment_for_the_worker_to_announce(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    notifier: RecordingNotifier,
    clock: MovableClock,
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    await settled_by_the_rail(ledger, intent, now=clock.now)

    # Act
    report = await apply(console, Notify(public_ref=intent.public_ref))

    # Assert — queued, not sent: this process holds no Telegram token.
    assert report.exit_code == EXIT_OK
    assert notifier.calls == [intent.public_ref]
    assert "no Telegram token" in report.text()


async def test_notify_refuses_an_unpaid_intent_and_queues_nothing(
    console: OperatorConsole, ledger: SqlPaymeLedger, notifier: RecordingNotifier
) -> None:
    # Arrange
    intent = await open_intent(ledger)

    # Act / Assert
    with pytest.raises(RefusedError, match="not paid"):
        await apply(console, Notify(public_ref=intent.public_ref))
    assert notifier.calls == []


async def test_notify_refuses_an_intent_that_was_already_announced(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    notifier: RecordingNotifier,
    clock: MovableClock,
) -> None:
    """The job stops on the stamp, so re-enqueuing would be a silent no-op. Say so instead."""
    # Arrange
    intent = await open_intent(ledger)
    await settled_by_the_rail(ledger, intent, now=clock.now)
    stamped = await ledger.mark_notified(public_ref=intent.public_ref, now=clock.now)
    assert is_ok(stamped), stamped

    # Act / Assert
    with pytest.raises(RefusedError, match="already announced"):
        await apply(console, Notify(public_ref=intent.public_ref))
    assert notifier.calls == []


# ---------------------------------------------------------------------------
# reconcile — the sweep's arms, run by hand
# ---------------------------------------------------------------------------
async def test_reconcile_expires_a_lapsed_intent_and_re_enqueues_a_waiting_announcement(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    notifier: RecordingNotifier,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — one abandoned intent and one settled intent nobody has been told about.
    abandoned = await open_intent(ledger)
    settled = await open_intent(ledger)
    await settled_by_the_rail(ledger, settled, now=clock.now)
    clock.advance(days=1)

    # Act
    report = await apply(console, Reconcile(limit=50))

    # Assert
    assert report.exit_code == EXIT_OK
    assert notifier.calls == [settled.public_ref]
    row = await intent_row(sessions, abandoned.public_ref)
    assert row.state.value == "expired"


async def test_reconcile_never_expires_an_intent_holding_a_live_transaction(
    sessions: async_sessionmaker[AsyncSession],
    switch: FakeSwitch,
    notifier: RecordingNotifier,
    clock: MovableClock,
) -> None:
    """Our clock may never refuse a payment the rail still considers open.

    Structural rather than guarded: holding an intent moves it to ``awaiting``, and the expiry
    predicate only sees ``pending``. Asserted here as well as in the ledger's own suite because
    ``reconcile`` is a human pressing the sweep by hand, often during the incident in which this
    would do the most damage.

    The link's own validity is shortened to a minute so that OUR window closes while the RAIL's
    twelve-hour one is still wide open — the only arrangement in which the two clocks disagree,
    and therefore the only one in which this property can fail. At the shipped defaults the two
    are both twelve hours and the test would prove nothing.
    """
    # Arrange
    ledger = SqlPaymeLedger(sessions, merchant_id=_MERCHANT, clock=clock, intent_ttl_s=60)
    console = OperatorConsole(
        ledger=ledger,
        sessions=sessions,
        switch=switch,
        notify=notifier,
        clock=clock,
        merchant_id=_MERCHANT,
        account_field=_ACCOUNT_FIELD,
        is_sandbox=True,
        is_enabled=True,
    )
    intent = await open_intent(ledger)
    identifier = payme_id()
    created = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=intent.public_ref,
        now=clock.now,
    )
    assert is_ok(created), created
    later = clock.advance(seconds=120)

    # Act — our validity window has closed; the rail's has not.
    await apply(console, Reconcile(limit=50))

    # Assert — untouched, and still payable.
    row = await intent_row(sessions, intent.public_ref)
    assert row.state.value == "awaiting"
    performed = await ledger.perform(payme_transaction_id=identifier, now=later)
    assert is_ok(performed), performed


async def test_reconcile_reports_a_failed_announcement_without_stopping_the_state_arms(
    console: OperatorConsole,
    ledger: SqlPaymeLedger,
    notifier: RecordingNotifier,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    """A failing queue must not stop a state sweep: they are unrelated jobs that share a cron."""
    # Arrange
    abandoned = await open_intent(ledger)
    settled = await open_intent(ledger)
    await settled_by_the_rail(ledger, settled, now=clock.now)
    clock.advance(days=1)
    notifier.fails = True

    # Act
    report = await apply(console, Reconcile(limit=50))

    # Assert — exit 3 so a cron notices, and the expiry still happened.
    assert report.exit_code == EXIT_MISMATCH
    assert "arm(s) failed" in report.text()
    row = await intent_row(sessions, abandoned.public_ref)
    assert row.state.value == "expired"


# ---------------------------------------------------------------------------
# The command line itself
# ---------------------------------------------------------------------------
async def test_main_refuses_a_malformed_reference_without_opening_a_database() -> None:
    """The refusing half of ``main`` runs before any container is built. No engine, no DSN.

    This is what makes a mistyped command safe to run on a production host: it cannot reach a
    connection pool, so it cannot print a traceback carrying the database password.
    """
    # Act
    code = main(["settle", "--ref", "not-hex", "--note", "x"])

    # Assert
    assert code == EXIT_REFUSED


async def test_every_subcommand_parses_into_its_own_request_shape() -> None:
    """One assertion per verb, so a renamed flag is a failing test rather than a broken runbook."""
    assert isinstance(plan(["journal", "--ref", "ab" * 12]), Journal)
    assert isinstance(plan(["journal", "--payme-id", "a" * 24]), Journal)
    assert isinstance(
        plan(["statement", "--from", "2026-09-01T00:00:00Z", "--to", "2026-09-02T00:00:00Z"]),
        Statement,
    )
    assert isinstance(plan(["settle", "--ref", "ab" * 12, "--note", "cabinet 1"]), Settle)
    assert isinstance(plan(["notify", "--ref", "ab" * 12]), Notify)
    assert plan(["pause"]) == Pause(paused=True)
    assert plan(["resume"]) == Pause(paused=False)
    assert isinstance(plan(["status"]), Status)
    assert isinstance(plan(["invariant", "--hours", "6"]), Invariant)
    assert isinstance(plan(["reconcile"]), Reconcile)


async def test_journal_selectors_are_mutually_exclusive() -> None:
    """``--ref`` plus ``--since`` has no meaning, so it is refused rather than resolved."""
    with pytest.raises(SystemExit):
        plan(["journal", "--ref", "ab" * 12, "--since", "2026-09-01T00:00:00Z"])


async def test_a_window_out_of_range_is_a_sentence_and_not_a_traceback() -> None:
    with pytest.raises(RefusedError, match="whole number"):
        plan(["invariant", "--hours", "-1"])
    with pytest.raises(RefusedError, match="whole number"):
        plan(["reconcile", "--limit", "0x10"])
