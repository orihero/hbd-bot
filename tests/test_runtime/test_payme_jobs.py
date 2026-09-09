"""The two rail jobs, driven end to end against a real database and a recording transport.

These are deliberately not mocked. The properties under test are the ones that only appear
when a real ledger, a real clock and a real ``Bot`` are in the same room:

* the notification is IDEMPOTENT because ``notified_at`` is a conditional stamp on a real
  column, not because a fake remembered being called;
* the sweep's expiry arm leaves an ``awaiting`` intent alone because the SQL predicate cannot
  see it, not because a branch checks — so the test advances the clock past ``valid_until``
  with a live transaction holding the intent and asserts nothing moved, which is the single
  worst outcome this integration could have;
* the invariant arm reports and REPAIRS NOTHING, which can only be asserted by counting rows
  before and after a hand-broken window.

The container is the same real, provider-free shape ``tests/test_runtime/test_purge_cron.py``
uses: SQLite on disk, no vendor adapter anywhere near it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
import sqlalchemy as sa
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from hbd.bot.i18n import translate
from hbd.bot.keyboards import start_over_keyboard
from hbd.checkout import PaymentIntentState, Product
from hbd.config import Settings
from hbd.contracts import Language, is_ok
from hbd.db.enums import PaymeState as DbPaymeState
from hbd.db.models import CreditLedgerRow, TopupPurchaseRow
from hbd.db.models.payme_transaction import PaymeTransactionRow
from hbd.db.payme import SqlPaymeLedger
from hbd.runtime.container import AppContainer, build_container
from hbd.runtime.jobs import build_kit_worker_settings
from hbd.runtime.payme_jobs import (
    PAID_LATE_PLAN_KEY,
    PAID_LATE_SINGLE_KEY,
    PAYME_NOTIFY_JOB_NAME,
    PAYME_NOTIFY_MAX_TRIES,
    PAYME_SWEEP_JOB_NAME,
    notify_payment_settled,
    payme_notify_job_id,
    run_payme_sweep,
    sweep_minutes,
)
from tests.test_bot.conftest import RecordingSession
from tests.test_db.conftest import MovableClock

#: Outside the 32-bit range, so a column that was accidentally ``Integer`` fails loudly
#: rather than truncating a customer's id into somebody else's account.
_BUYER: Final[int] = 8_100_000_000_017

_MERCHANT: Final[str] = "5e730e8e0b852a417aa49ceb"
_SINGLE_PRICE: Final[int] = 700_000
_TWELVE_HOURS_MS: Final[int] = 43_200_000
#: Five minutes, and deliberately far SHORTER than the rail's own twelve-hour transaction
#: window. The two clocks measure different things — ours runs from the moment a customer was
#: handed a URL, theirs from the moment a card was presented against it — and a fixture that
#: set them equal could not tell the expiry arm and the timeout arm apart, because both would
#: fire on the same advance.
_INTENT_TTL_S: Final[int] = 300
_START: Final[datetime] = datetime(2026, 9, 9, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures: a real container, a real rail, a recording bot
# ---------------------------------------------------------------------------
def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'payme_jobs.db'}",
        elevenlabs_api_key="k",
        llm_api_key="k",
    )


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[AppContainer]:
    """A real, provider-free container — the §4.3 shape both jobs actually run against."""
    built = await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    yield built
    await built.aclose()


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock(_START)


@pytest.fixture
def rail(container: AppContainer, clock: MovableClock) -> SqlPaymeLedger:
    """The SETUP ledger, on a movable clock so a test can mint an intent that expires soon.

    Deliberately a second instance rather than the one the job builds for itself: the job's
    ledger is built inside ``build_worker_payme_ledger`` on the real clock, which is exactly
    what production does, and a test that reached into it would be asserting about its own
    wiring rather than about the job's.
    """
    return SqlPaymeLedger(
        container.require_session_factory(),
        merchant_id=_MERCHANT,
        clock=clock,
        transaction_timeout_ms=_TWELVE_HOURS_MS,
        intent_ttl_s=_INTENT_TTL_S,
    )


class _RecordingQueue:
    """A stand-in for ARQ's pool that records what the sweep asked to enqueue."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], str | None]] = []
        self.failure: Exception | None = None

    async def enqueue_job(self, name: str, *args: Any, _job_id: str | None = None) -> None:
        if self.failure is not None:
            raise self.failure
        self.jobs.append((name, args, _job_id))


def _ctx(container: AppContainer, bot: Bot, queue: _RecordingQueue | None = None) -> dict[str, Any]:
    ctx: dict[str, Any] = {"container": container, "bot": bot}
    if queue is not None:
        ctx["redis"] = queue
    return ctx


async def _open_single(
    rail: SqlPaymeLedger, *, key: str, buyer: int = _BUYER, language: str = "en"
) -> str:
    opened = await rail.open_intent(
        telegram_user_id=buyer,
        product=Product.SINGLE,
        amount_minor=_SINGLE_PRICE,
        currency="UZS",
        idempotency_key=key,
        language=language,
        merchant_id=_MERCHANT,
        is_sandbox=True,
    )
    assert is_ok(opened)
    return opened.value.public_ref


async def _open_plan(rail: SqlPaymeLedger, *, key: str, buyer: int = _BUYER) -> str:
    opened = await rail.open_intent(
        telegram_user_id=buyer,
        product=Product.STARTER,
        amount_minor=_SINGLE_PRICE * 4,
        currency="UZS",
        idempotency_key=key,
        language="ru",
        merchant_id=_MERCHANT,
        is_sandbox=True,
        plan_songs=12,
        plan_days=30,
    )
    assert is_ok(opened)
    return opened.value.public_ref


async def _settle(rail: SqlPaymeLedger, public_ref: str, *, now: datetime) -> None:
    """Settle by the operator path, which writes the same rows a real Perform writes."""
    settled = await rail.force_settle(public_ref=public_ref, now=now, note="fixture")
    assert is_ok(settled)


async def _hold(rail: SqlPaymeLedger, public_ref: str, *, payme_id: str, now: datetime) -> None:
    """Put a live rail-side transaction on the intent, moving it to ``awaiting``."""
    created = await rail.create(
        payme_transaction_id=payme_id,
        payme_time=now,
        amount_minor=_SINGLE_PRICE,
        public_ref=public_ref,
        now=now,
    )
    assert is_ok(created)


async def _intent_state(rail: SqlPaymeLedger, public_ref: str) -> PaymentIntentState:
    found = await rail.intent(public_ref=public_ref)
    assert is_ok(found)
    assert found.value is not None
    return found.value.state


async def _rows(container: AppContainer, statement: sa.Select[Any]) -> list[Any]:
    async with container.require_session_factory()() as session:
        return list((await session.execute(statement)).scalars().all())


def _sent(session: RecordingSession) -> list[SendMessage]:
    return [call for call in session.calls if isinstance(call, SendMessage)]


# ---------------------------------------------------------------------------
# The notification
# ---------------------------------------------------------------------------
async def test_a_settled_payment_is_announced_once_in_the_language_it_was_bought_in(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """The whole point of the job: money landed, and the customer hears about it.

    The LANGUAGE assertion rides on the keyboard rather than on the sentence deliberately.
    The two ``checkout.paid_late_*`` keys are written by the bot-UX workstream, and until
    that catalogue edit lands ``translate`` returns the key itself in every locale — which
    would make a language assertion on the text pass for the wrong reason. The nav labels
    under it come from keys that already exist in all four catalogues, so they differ per
    language today and will keep differing tomorrow.
    """
    # Arrange
    public_ref = await _open_single(rail, key="topup:1", language=Language.RU.value)
    await _settle(rail, public_ref, now=clock.now)

    # Act
    await notify_payment_settled(_ctx(container, bot), public_ref)

    # Assert — one message, to the buyer, and it is not the English one.
    messages = _sent(session)
    assert len(messages) == 1
    assert messages[0].chat_id == _BUYER
    ledger = container.credits
    assert ledger is not None
    balance = await ledger.balance_for(_BUYER)
    assert is_ok(balance)
    assert messages[0].text == translate(
        PAID_LATE_SINGLE_KEY, Language.RU, credits=balance.value.credits
    )
    assert messages[0].reply_markup == start_over_keyboard(Language.RU)
    assert messages[0].reply_markup != start_over_keyboard(Language.EN)

    # Assert — and the stamp landed, which is what stops it being said twice.
    found = await rail.intent(public_ref=public_ref)
    assert is_ok(found)
    assert found.value is not None
    assert found.value.notified_at is not None


async def test_a_second_run_of_the_same_notification_sends_nothing(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """A redelivered job, or the sweep and the gateway both firing. Saying it twice is the
    one failure a customer actually notices."""
    # Arrange
    public_ref = await _open_single(rail, key="topup:2")
    await _settle(rail, public_ref, now=clock.now)
    await notify_payment_settled(_ctx(container, bot), public_ref)
    assert len(_sent(session)) == 1

    # Act
    await notify_payment_settled(_ctx(container, bot), public_ref)

    # Assert
    assert len(_sent(session)) == 1


async def test_an_erased_buyer_is_not_told_and_nothing_raises(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """``/forget`` ran between the payment and the job. There is nobody to tell.

    The intent survives erasure — anonymised, not deleted — because ``GetStatement`` must
    still be able to answer Payme about a transaction they can see in their own cabinet. So
    the row is here, the money columns are here, and the only missing thing is the person.
    """
    # Arrange
    public_ref = await _open_single(rail, key="topup:3")
    await _settle(rail, public_ref, now=clock.now)
    ledger = container.credits
    assert ledger is not None
    erased = await ledger.forget(_BUYER)
    assert is_ok(erased)

    # Act
    await notify_payment_settled(_ctx(container, bot), public_ref)

    # Assert — silence, no exception, and no stamp claiming a delivery that never happened.
    assert _sent(session) == []
    found = await rail.intent(public_ref=public_ref)
    assert is_ok(found)
    assert found.value is not None
    assert found.value.telegram_user_id is None
    assert found.value.notified_at is None


async def test_an_unpaid_intent_is_never_announced(
    container: AppContainer,
    rail: SqlPaymeLedger,
    bot: Bot,
    session: RecordingSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Announcing an unsettled payment is how a free song is given away."""
    # Arrange
    public_ref = await _open_single(rail, key="topup:4")

    # Act
    with caplog.at_level(logging.ERROR):
        await notify_payment_settled(_ctx(container, bot), public_ref)

    # Assert
    assert _sent(session) == []
    assert any("not settled" in record.message for record in caplog.records)


async def test_a_plan_settlement_is_announced_from_the_live_plan(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """A plan grants no credit at purchase, so the sentence is about songs and an end date."""
    # Arrange
    public_ref = await _open_plan(rail, key="plan:1")
    await _settle(rail, public_ref, now=clock.now)

    # Act
    await notify_payment_settled(_ctx(container, bot), public_ref)

    # Assert — the plan's own numbers, read back from the meter rather than from the intent.
    store = container.purchases
    assert store is not None
    plan = await store.plan_for(_BUYER)
    assert is_ok(plan)
    assert plan.value is not None
    messages = _sent(session)
    assert len(messages) == 1
    assert messages[0].text == translate(
        PAID_LATE_PLAN_KEY,
        Language.RU,
        songs=plan.value.songs_left,
        ends_on=plan.value.ends_at.date().isoformat(),
    )


async def test_a_blocked_customer_is_stamped_rather_than_re_enqueued_forever(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """A chat nobody can reach must not become an unbounded source of work.

    ``notified_at`` means "everything that could be done to tell them was done", which is the
    only reading that stays true for a customer who blocked the bot. Leaving it NULL would put
    a permanently undeliverable row in the backlog query and re-enqueue this job every five
    minutes for the life of the deployment.
    """
    # Arrange
    public_ref = await _open_single(rail, key="topup:5")
    await _settle(rail, public_ref, now=clock.now)
    session.failures["SendMessage"] = TelegramForbiddenError(
        method=SendMessage(chat_id=_BUYER, text="x"),
        message="Forbidden: bot was blocked by the user",
    )

    # Act
    await notify_payment_settled(_ctx(container, bot), public_ref)

    # Assert
    found = await rail.intent(public_ref=public_ref)
    assert is_ok(found)
    assert found.value is not None
    assert found.value.notified_at is not None


async def test_a_reference_that_names_nothing_is_not_retried(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    """A stale enqueue. Five more attempts would find the same nothing."""
    # Act / Assert — no ``Retry`` escapes, and no message goes out.
    await notify_payment_settled(_ctx(container, bot), "0" * 24)
    assert _sent(session) == []


async def test_a_context_without_a_container_names_the_wiring_bug(bot: Bot) -> None:
    # Act / Assert
    with pytest.raises(Exception, match="missing a usable 'container'"):
        await notify_payment_settled({"bot": bot}, "deadbeef")


async def test_a_context_without_a_bot_names_the_wiring_bug(container: AppContainer) -> None:
    # Act / Assert
    with pytest.raises(Exception, match="missing a usable 'bot'"):
        await notify_payment_settled({"container": container}, "deadbeef")


# ---------------------------------------------------------------------------
# The sweep — arm one and two, the STATE backstops
# ---------------------------------------------------------------------------
async def test_the_sweep_expires_a_lapsed_pending_intent(
    container: AppContainer, rail: SqlPaymeLedger, clock: MovableClock, bot: Bot
) -> None:
    # Arrange
    public_ref = await _open_single(rail, key="topup:6")

    # Act — a day later, with nobody having paid.
    summary = await run_payme_sweep(_ctx(container, bot), now=clock.advance(days=1))

    # Assert
    assert summary["intents_expired"] == 1
    assert await _intent_state(rail, public_ref) is PaymentIntentState.EXPIRED


async def test_an_intent_holding_a_live_transaction_is_never_expired_by_our_clock(
    container: AppContainer, rail: SqlPaymeLedger, clock: MovableClock, bot: Bot
) -> None:
    """THE ONE THAT MATTERS. Our clock and the rail's are not the same clock.

    An intent expired here while a card was being charged there is the worst outcome this
    integration has, and the protection is structural rather than conditional: taking a hold
    moves the intent to ``awaiting``, and the expiry predicate reads ``pending`` only, so the
    row is not in the set the sweep can see at all.
    """
    # Arrange — held, and then the clock is pushed well past ``valid_until``.
    public_ref = await _open_single(rail, key="topup:7")
    await _hold(rail, public_ref, payme_id="a" * 24, now=clock.now)
    assert await _intent_state(rail, public_ref) is PaymentIntentState.AWAITING

    # Act — past ``valid_until`` and deliberately NOT past the rail's twelve-hour window,
    # because arm two would then legitimately time the transaction out and release the intent,
    # which is a different property and is asserted in its own test below.
    summary = await run_payme_sweep(
        _ctx(container, bot), now=clock.advance(seconds=_INTENT_TTL_S * 2)
    )

    # Assert — untouched by the expiry arm, whatever our clock says.
    assert summary["intents_expired"] == 0
    assert await _intent_state(rail, public_ref) is PaymentIntentState.AWAITING


async def test_the_sweep_times_out_a_stale_transaction_and_releases_its_intent(
    container: AppContainer, rail: SqlPaymeLedger, clock: MovableClock, bot: Bot
) -> None:
    """Thirteen hours past the rail's own twelve-hour window, with Payme never calling again.

    Cancelled to state -1 with reason 4 (timeout) and the intent released to ``pending``, so
    ``CheckTransaction`` stays honest and the customer can be sold to again.
    """
    # Arrange
    public_ref = await _open_single(rail, key="topup:8")
    await _hold(rail, public_ref, payme_id="b" * 24, now=clock.now)

    # Act
    summary = await run_payme_sweep(_ctx(container, bot), now=clock.advance(seconds=13 * 60 * 60))

    # Assert — the transaction and the intent both moved, and in the right directions.
    assert summary["transactions_timed_out"] == 1
    rows = await _rows(container, sa.select(PaymeTransactionRow))
    assert len(rows) == 1
    assert rows[0].state is DbPaymeState.CANCELLED
    assert rows[0].cancel_reason == 4
    assert await _intent_state(rail, public_ref) is PaymentIntentState.PENDING


# ---------------------------------------------------------------------------
# The sweep — arm three, the DELIVERY backstop
# ---------------------------------------------------------------------------
async def test_the_sweep_re_enqueues_an_old_unnotified_settlement(
    container: AppContainer, rail: SqlPaymeLedger, clock: MovableClock, bot: Bot
) -> None:
    """The backstop that turns a Redis outage at Perform time into a latency problem."""
    # Arrange — settled ninety seconds ago and nobody told.
    public_ref = await _open_single(rail, key="topup:9")
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    summary = await run_payme_sweep(_ctx(container, bot, queue), now=clock.advance(seconds=90))

    # Assert — one job, under the deterministic id that makes a double enqueue a no-op.
    assert summary["notifications_re_enqueued"] == 1
    assert queue.jobs == [(PAYME_NOTIFY_JOB_NAME, (public_ref,), payme_notify_job_id(public_ref))]


async def test_the_sweep_leaves_a_fresh_settlement_to_the_gateways_own_enqueue(
    container: AppContainer, rail: SqlPaymeLedger, clock: MovableClock, bot: Bot
) -> None:
    """Thirty seconds old: the gateway's own job is almost certainly still in flight.

    A backstop that fired on the healthy path would make its own error rate the one number
    nobody could read.
    """
    # Arrange
    public_ref = await _open_single(rail, key="topup:10")
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    summary = await run_payme_sweep(_ctx(container, bot, queue), now=clock.advance(seconds=30))

    # Assert
    assert summary["notifications_re_enqueued"] == 0
    assert queue.jobs == []
    assert public_ref  # the row is still there, simply not yet due


async def test_an_already_notified_settlement_is_never_re_enqueued(
    container: AppContainer, rail: SqlPaymeLedger, clock: MovableClock, bot: Bot
) -> None:
    # Arrange
    public_ref = await _open_single(rail, key="topup:11")
    await _settle(rail, public_ref, now=clock.now)
    await notify_payment_settled(_ctx(container, bot), public_ref)
    queue = _RecordingQueue()

    # Act
    await run_payme_sweep(_ctx(container, bot, queue), now=clock.advance(seconds=600))

    # Assert
    assert queue.jobs == []


async def test_a_queue_that_cannot_be_reached_is_counted_and_never_raised(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """This arm exists to compensate for a Redis outage; it must not die in one."""
    # Arrange
    await _settle(rail, await _open_single(rail, key="topup:12"), now=clock.now)
    queue = _RecordingQueue()
    queue.failure = OSError("redis is down")

    # Act
    with caplog.at_level(logging.ERROR):
        summary = await run_payme_sweep(_ctx(container, bot, queue), now=clock.advance(seconds=120))

    # Assert — the other arms still ran, and the fault is on the record.
    assert summary["notifications_re_enqueued"] == 0
    assert summary["faults"] >= 1


async def test_a_worker_with_no_queue_handle_says_so_rather_than_failing_quietly(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    await _settle(rail, await _open_single(rail, key="topup:13"), now=clock.now)

    # Act — no ``redis`` in the context at all.
    with caplog.at_level(logging.ERROR):
        summary = await run_payme_sweep(_ctx(container, bot), now=clock.advance(seconds=120))

    # Assert
    assert summary["faults"] >= 1
    assert any("no queue handle" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# The sweep — arm four, the invariant that repairs nothing
# ---------------------------------------------------------------------------
async def test_the_invariant_holds_after_an_ordinary_settlement(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One performed transaction, one receipt, one grant — reported and not complained about.

    Settled through a real ``PerformTransaction`` rather than the operator path, because the
    operator path deliberately writes a receipt with no performed transaction behind it and
    is therefore the one benign way to move these counts apart.
    """
    # Arrange
    public_ref = await _open_single(rail, key="topup:14")
    await _hold(rail, public_ref, payme_id="c" * 24, now=clock.now)
    performed = await rail.perform(payme_transaction_id="c" * 24, now=clock.now)
    assert is_ok(performed)

    # Act
    with caplog.at_level(logging.ERROR):
        await run_payme_sweep(_ctx(container, bot), now=clock.advance(seconds=120))

    # Assert — no complaint about the counts.
    assert not [record for record in caplog.records if "sale row" in record.message]


async def test_a_receipt_deleted_by_hand_is_reported_at_error_and_never_repaired(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The failure the arm exists for: a performed transaction that produced no sale row.

    There is no outbound Merchant API method a merchant may call, so this local count is the
    only automated way to notice that the shared write primitive has drifted. It must SAY so
    and must not write anything — a scheduler that repaired this would be granting a credit on
    a guess and destroying the evidence at the same time.
    """
    # Arrange — one real settlement, then the receipt is removed behind the ledger's back.
    public_ref = await _open_single(rail, key="topup:15")
    await _hold(rail, public_ref, payme_id="d" * 24, now=clock.now)
    assert is_ok(await rail.perform(payme_transaction_id="d" * 24, now=clock.now))
    async with container.require_session_factory().begin() as session:
        await session.execute(sa.delete(TopupPurchaseRow))

    # Act
    with caplog.at_level(logging.ERROR):
        await run_payme_sweep(_ctx(container, bot), now=clock.advance(seconds=120))

    # Assert — reported...
    assert any("produced no sale row" in record.message for record in caplog.records)
    # ...and nothing was written to put it back.
    assert await _rows(container, sa.select(TopupPurchaseRow)) == []
    assert await _intent_state(rail, public_ref) is PaymentIntentState.PAID


async def test_an_operator_force_settle_is_reported_as_the_benign_direction(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """More receipts than performed transactions has exactly one benign cause, and the log
    line names it so nobody is paged over a recovery they performed themselves."""
    # Arrange
    await _settle(rail, await _open_single(rail, key="topup:16"), now=clock.now)

    # Act
    with caplog.at_level(logging.ERROR):
        await run_payme_sweep(_ctx(container, bot), now=clock.advance(seconds=120))

    # Assert
    assert any("force-settle" in record.message for record in caplog.records)


async def test_a_balance_that_disagrees_with_its_ledger_is_reported_and_not_corrected(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``verify_balances`` runs HERE, on a schedule, and never inside a JSON-RPC request that
    owes Payme an answer in milliseconds."""
    # Arrange — a grant with its ledger row removed, which is exactly the drift shape.
    await _settle(rail, await _open_single(rail, key="topup:17"), now=clock.now)
    async with container.require_session_factory().begin() as session:
        await session.execute(sa.delete(CreditLedgerRow))

    # Act
    with caplog.at_level(logging.ERROR):
        summary = await run_payme_sweep(_ctx(container, bot), now=clock.advance(seconds=120))

    # Assert
    assert summary["faults"] >= 1
    assert any("disagrees with its ledger" in record.message for record in caplog.records)


async def test_a_sweep_over_an_empty_rail_is_four_quiet_zeroes(
    container: AppContainer, bot: Bot, caplog: pytest.LogCaptureFixture
) -> None:
    """A deployment still on the stub rail runs this cron twelve times an hour and must pay
    nothing for it — no faults, no ERROR lines, no rows."""
    # Act
    with caplog.at_level(logging.ERROR):
        summary = await run_payme_sweep(_ctx(container, bot), now=_START)

    # Assert
    assert summary["intents_expired"] == 0
    assert summary["transactions_timed_out"] == 0
    assert summary["notifications_re_enqueued"] == 0
    assert summary["faults"] == 0
    assert caplog.records == []


async def test_a_context_without_a_container_names_the_wiring_bug_for_the_sweep_too() -> None:
    # Act / Assert
    with pytest.raises(Exception, match="missing a usable 'container'"):
        await run_payme_sweep({})


# ---------------------------------------------------------------------------
# Registration: a job ARQ cannot dispatch is a schedule with nothing behind it
# ---------------------------------------------------------------------------
def test_both_rail_jobs_are_registered_under_the_names_the_gateway_enqueues(
    tmp_path: Path,
) -> None:
    """The enqueue side of one of these is ANOTHER PROCESS, so the name is the whole contract.

    ARQ dispatches by function name. A notification job that is not in ``functions`` under
    exactly ``notify_payment_settled`` would leave every settled payment silently unannounced
    with the money already banked — no exception anywhere, because the gateway swallows a
    failed enqueue by design.
    """

    async def _dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )

    # Assert — by NAME, which is what ARQ actually looks up.
    registered = {
        getattr(entry, "name", getattr(entry, "__name__", "")) for entry in worker.functions
    }
    assert PAYME_NOTIFY_JOB_NAME in registered
    assert PAYME_SWEEP_JOB_NAME in registered
    assert run_payme_sweep in [job.coroutine for job in worker.cron_jobs]


def test_the_notification_is_registered_with_the_retry_budget_the_job_itself_reads(
    tmp_path: Path,
) -> None:
    """ARQ compares ``job_try > max_tries`` BEFORE entering the function, so the attempt that
    would have been the sixth never runs. The job reads the same constant to decide when to
    stop raising ``Retry``; two places holding different numbers is how a customer ends up
    never told."""

    async def _dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )
    notify = next(
        entry for entry in worker.functions if getattr(entry, "name", "") == PAYME_NOTIFY_JOB_NAME
    )

    # Assert
    assert notify.max_tries == PAYME_NOTIFY_MAX_TRIES


def test_the_shipped_cadence_is_five_minutes(tmp_path: Path) -> None:
    """A LITERAL five, on purpose. This number is the ceiling on how long somebody who paid
    during a Redis outage waits to be told, which makes it a customer-facing promise rather
    than a technical default — so it is pinned here rather than read back from the settings
    field it comes from, which would assert nothing at all."""
    # Act
    minutes = sweep_minutes(_settings(tmp_path))

    # Assert — twelve firings an hour, and a HASHABLE collection, because a sibling test
    # collects every cron's ``minute`` into a set to prove no two scheduled writers collide.
    assert minutes == (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55)
    assert hash(minutes)


def test_a_declared_cadence_is_honoured(tmp_path: Path) -> None:
    """The knob is a real settings field, so an operator can lengthen the customer's worst-case
    wait without a release — which is the whole reason it is configuration and not a constant."""
    # Arrange
    settings = Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'cadence.db'}",
        elevenlabs_api_key="k",
        llm_api_key="k",
        payme_sweep_minutes=10,
    )

    # Act
    minutes = sweep_minutes(settings)

    # Assert
    assert minutes == (0, 10, 20, 30, 40, 50)


def test_an_hourly_cadence_is_a_single_minute_and_still_schedulable(tmp_path: Path) -> None:
    """Sixty is the settings field's own ceiling and means "once an hour", which is a
    defensible choice for a deployment that would rather batch. It must produce a schedule
    rather than an empty one — a cron with no minutes is a job that never runs."""
    # Arrange
    settings = Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'hourly.db'}",
        elevenlabs_api_key="k",
        llm_api_key="k",
        payme_sweep_minutes=60,
    )

    # Act / Assert
    assert sweep_minutes(settings) == (0,)


def test_the_notification_job_id_is_deterministic_and_carries_no_telegram_id() -> None:
    """Two processes enqueue this job for the same intent; the id is what collapses them.

    Keyed on ``public_ref`` and never on the idempotency key, which is
    ``topup:{telegram_user_id}:{scope}:{seq}`` and would put a customer's Telegram id into a
    Redis key name and into every log line that mentions the job.
    """
    # Act
    job_id = payme_notify_job_id("f1e2d3c4b5a60718293a4b5c")

    # Assert
    assert job_id == payme_notify_job_id("f1e2d3c4b5a60718293a4b5c")
    assert job_id.startswith(f"{PAYME_NOTIFY_JOB_NAME}:")
    assert str(_BUYER) not in job_id


def test_the_gateway_and_the_worker_mint_the_same_notification_job_id() -> None:
    """The deduplication is BETWEEN TWO PROCESSES, so the id has to be one string.

    The gateway deliberately restates the job name rather than importing this module — an
    import would pull ``hbd.runtime``'s whole graph, and with it the bot and every vendor
    adapter, into the one process that holds the cashbox key. The cost of that restatement is
    that nothing in either process can see both spellings, and the two DID diverge while this
    rail was being built: the gateway minted ``payme-notify:<ref>`` while the sweep's backstop
    minted ``notify_payment_settled:<ref>``. Both are valid ARQ ids, so both jobs queue and
    both run — the customer is told twice about one payment and no check anywhere fails.

    This test is the seam. It is in the WORKER's suite because that is where importing both is
    free, and it is the reason ``hbd.payme.container._NOTIFY_JOB_PREFIX`` is the job name
    rather than a prefix somebody chose to read nicely.
    """
    # Arrange
    from hbd.payme.container import (
        PAYME_NOTIFY_JOB_NAME as GATEWAY_JOB_NAME,
    )
    from hbd.payme.container import (
        notify_job_id as gateway_notify_job_id,
    )

    public_ref = "f1e2d3c4b5a60718293a4b5c"

    # Act / Assert — the name ARQ dispatches on, and the id ARQ deduplicates on.
    assert GATEWAY_JOB_NAME == PAYME_NOTIFY_JOB_NAME
    assert gateway_notify_job_id(public_ref) == payme_notify_job_id(public_ref)
