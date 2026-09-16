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
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
import sqlalchemy as sa
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage

from bayram.bot.draft import WizardDraft
from bayram.bot.handlers.submitting import ORDER_ID_KEY, PROGRESS_MESSAGE_ID_KEY
from bayram.bot.i18n import translate
from bayram.bot.keyboards import paid_late_keyboard, start_over_keyboard
from bayram.bot.order_id import order_id_for
from bayram.bot.progress import queued_text
from bayram.bot.states import Wizard
from bayram.checkout import PaymentIntentState, Product
from bayram.config import Settings
from bayram.contracts import Genre, Language, Occasion, OrderState, VoiceGender, is_ok
from bayram.db.enums import PaymeState as DbPaymeState
from bayram.db.models import CreditLedgerRow, TopupPurchaseRow
from bayram.db.models.payme_transaction import PaymeTransactionRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.payme import SqlPaymeLedger
from bayram.pipeline.worker import KIT_JOB_NAME, job_id_for
from bayram.runtime.container import AppContainer, build_container
from bayram.runtime.jobs import build_kit_worker_settings
from bayram.runtime.payme_jobs import (
    PAID_LATE_PLAN_KEY,
    PAID_LATE_RESUMING_KEY,
    PAID_LATE_SINGLE_KEY,
    PAYME_NOTIFY_JOB_NAME,
    PAYME_NOTIFY_MAX_TRIES,
    PAYME_SWEEP_JOB_NAME,
    notify_payment_settled,
    payme_notify_job_id,
    run_payme_sweep,
    sweep_minutes,
)
from tests.conftest import make_name
from tests.test_bot.conftest import RecordingSession, canned_lyrics
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
def storage() -> MemoryStorage:
    """The FSM storage the WORKER reads and the bot writes.

    ``MemoryStorage`` rather than a fake, because what is under test is the key shape and the
    merge semantics of ``update_data`` — a fake dict would satisfy every assertion below while
    a real ``StorageKey`` mismatch went unnoticed.
    """
    return MemoryStorage()


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


def _ctx(
    container: AppContainer,
    bot: Bot,
    queue: _RecordingQueue | None = None,
    storage: MemoryStorage | None = None,
) -> dict[str, Any]:
    """The worker context, with both optional handles left OUT when not supplied.

    Omitting rather than passing ``None`` is what makes the two "a worker wired without it"
    tests real: the job reads these with ``ctx.get`` and must degrade, not raise, and a ctx
    that always carried the keys could not express the half-wired worker at all.
    """
    ctx: dict[str, Any] = {"container": container, "bot": bot}
    if queue is not None:
        ctx["redis"] = queue
    if storage is not None:
        ctx["fsm_storage"] = storage
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


async def _resumed_at(container: AppContainer, public_ref: str) -> datetime | None:
    """The resume claim, read straight off the column. See the assertion that uses it."""
    rows = await _rows(
        container,
        sa.select(PaymentIntentRow.resumed_at).where(PaymentIntentRow.public_ref == public_ref),
    )
    assert len(rows) == 1
    # `_rows` is list[Any] because the statements it runs return different column types;
    # narrow here, at the one place that knows which column was selected.
    value = rows[0]
    assert value is None or isinstance(value, datetime)
    return value


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
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue), public_ref)

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

    # Assert — and this settlement started NO render. Written before the resume existed, and
    # kept as the guard on the plain announcement: this job used to run with no queue handle
    # in its ctx at all, so an enqueue it grew would have been invisible to the whole suite.
    assert queue.jobs == []

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
    queue = _RecordingQueue()
    await notify_payment_settled(_ctx(container, bot, queue), public_ref)
    assert len(_sent(session)) == 1

    # Act
    await notify_payment_settled(_ctx(container, bot, queue), public_ref)

    # Assert
    assert len(_sent(session)) == 1
    assert queue.jobs == []


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
    import would pull ``bayram.runtime``'s whole graph, and with it the bot and every vendor
    adapter, into the one process that holds the cashbox key. The cost of that restatement is
    that nothing in either process can see both spellings, and the two DID diverge while this
    rail was being built: the gateway minted ``payme-notify:<ref>`` while the sweep's backstop
    minted ``notify_payment_settled:<ref>``. Both are valid ARQ ids, so both jobs queue and
    both run — the customer is told twice about one payment and no check anywhere fails.

    This test is the seam. It is in the WORKER's suite because that is where importing both is
    free, and it is the reason ``bayram.payme.container._NOTIFY_JOB_PREFIX`` is the job name
    rather than a prefix somebody chose to read nicely.
    """
    # Arrange
    from bayram.payme.container import (
        PAYME_NOTIFY_JOB_NAME as GATEWAY_JOB_NAME,
    )
    from bayram.payme.container import (
        notify_job_id as gateway_notify_job_id,
    )

    public_ref = "f1e2d3c4b5a60718293a4b5c"

    # Act / Assert — the name ARQ dispatches on, and the id ARQ deduplicates on.
    assert GATEWAY_JOB_NAME == PAYME_NOTIFY_JOB_NAME
    assert gateway_notify_job_id(public_ref) == payme_notify_job_id(public_ref)


# ---------------------------------------------------------------------------
# The render the payment was made for
# ---------------------------------------------------------------------------
# These drive the other half of ``notify_payment_settled``: a settled redirect payment does
# not merely announce itself, it STARTS the song the customer paid for. The properties under
# test are all properties of ORDERING and of a durable claim, so none of them is mocked —
# a real ledger on a real database, the real FSM storage class the bot writes, and a
# recording queue standing in for ARQ's pool.
#
# ``_RecordingQueue`` is now passed to the notification tests above as well, asserting
# ``queue.jobs == []``. That assertion is not decoration: before this workstream the job ran
# with NO queue handle in its ctx at all, so any enqueue it grew would have been invisible to
# the entire suite.


def _parked(draft: WizardDraft) -> dict[str, Any]:
    return dict(draft.to_state_data())


async def _park_confirm(storage: MemoryStorage, bot: Bot, draft: WizardDraft) -> StorageKey:
    """Leave a complete, lyric-approved draft on the Confirm screen, as the wizard would.

    Written through the same ``StorageKey`` shape ``render_resume`` builds — private chat, so
    the user id IS the chat id — because a test that parked under a different key would prove
    only that the job cannot find a session.
    """
    key = StorageKey(bot_id=bot.id, chat_id=_BUYER, user_id=_BUYER)
    await storage.set_state(key, Wizard.confirm)
    await storage.set_data(key, _parked(draft))
    return key


def _resumable_draft() -> WizardDraft:
    """A draft one press of 🎬 away from a render: complete, with an APPROVED lyric."""
    draft = WizardDraft(
        ui_language=Language.RU,
        occasion=Occasion.BIRTHDAY,
        genre=Genre.RETRO_ESTRADA,
        vocal_gender=VoiceGender.MALE,
        note="Loves the mountains",
        recipient=make_name(),
        output_language=Language.UZ_LATN,
        session_id="session-under-test",
    )
    brief = draft.to_brief()
    assert is_ok(brief), brief
    return draft.model_copy(update={"lyrics": canned_lyrics(brief.value, take=1)})


async def _open_resumable(
    rail: SqlPaymeLedger, *, key: str, draft: WizardDraft, buyer: int = _BUYER
) -> tuple[str, UUID]:
    """Open an intent carrying the render marker, exactly as the bot's pending branch does."""
    order_id = order_id_for(buyer, draft)
    opened = await rail.open_intent(
        telegram_user_id=buyer,
        product=Product.SINGLE,
        amount_minor=_SINGLE_PRICE,
        currency="UZS",
        idempotency_key=key,
        language=draft.ui_language.value,
        merchant_id=_MERCHANT,
        is_sandbox=True,
        resume_order_id=order_id,
    )
    assert is_ok(opened)
    return opened.value.public_ref, order_id


async def test_a_settled_payment_resumes_the_render_it_was_opened_for(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """The feature, end to end: pay, and the song starts.

    **The ORDERING is asserted by index rather than trusted from the source.** The customer
    must read "your payment landed" and THEN watch a progress frame appear; a refactor that
    moved the resume above the announcement would still pass a test that merely checked both
    messages exist, and would show the customer a progress bar for a payment nobody had
    confirmed.
    """
    # Arrange
    draft = _resumable_draft()
    key = await _park_confirm(storage, bot, draft)
    public_ref, order_id = await _open_resumable(rail, key="topup:resume:1", draft=draft)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert — the sentence, with no keyboard: the progress frame lands under it.
    messages = _sent(session)
    assert len(messages) == 2
    assert messages[0].text == translate(PAID_LATE_RESUMING_KEY, Language.RU)
    assert messages[0].reply_markup is None
    # Assert — and it came FIRST.
    assert session.calls.index(messages[0]) < session.calls.index(messages[1])
    # `Brief.recipient` is optional; this draft was built with one, and saying so keeps
    # the attribute access honest rather than relying on it.
    assert draft.recipient is not None
    assert messages[1].text == queued_text(Language.RU, name=draft.recipient.display)

    # Assert — one job, addressed by the id minted at PAY time, carrying the progress message
    # the job will report into. The id is read off the enqueue rather than off the recorded
    # ``SendMessage`` (which is the outgoing METHOD and carries no message id) and is then
    # cross-checked against the FSM park below, so a job and a park that disagreed about which
    # message to draw on would fail here.
    assert len(queue.jobs) == 1
    name, args, job_id = queue.jobs[0]
    progress_message_id = args[2]
    assert (name, args[:2], job_id) == (
        KIT_JOB_NAME,
        (str(order_id), _BUYER),
        job_id_for(order_id),
    )

    # Assert — the order exists and the claim is stamped.
    order = await container.repository.get_order(order_id)
    assert is_ok(order)
    assert order.value.state is OrderState.AUTHORIZED
    # ``resumed_at`` is read off the COLUMN and not off the view, because it is deliberately
    # not on the view: its only reader is the rowcount of the conditional UPDATE that claims
    # it, and a field on the view would invite a read-then-write where a claim belongs.
    assert await _resumed_at(container, public_ref) is not None

    # Assert — the session is parked on it, so ``jobs._release_session`` can un-park it later.
    parked = await storage.get_data(key)
    assert parked[ORDER_ID_KEY] == str(order_id)
    assert parked[PROGRESS_MESSAGE_ID_KEY] == progress_message_id
    assert await storage.get_state(key) == Wizard.submitting.state


async def test_a_second_run_of_the_notification_queues_no_second_render(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """The at-most-once latch, against the failure that actually happens.

    ``notify_payment_settled`` is at-least-once by construction — five ARQ attempts, the
    sweep's backstop, and two processes enqueuing the same name — so this is not a hypothetical
    replay. A second render is a second vendor bill and a second delivered song.
    """
    # Arrange
    draft = _resumable_draft()
    await _park_confirm(storage, bot, draft)
    public_ref, _ = await _open_resumable(rail, key="topup:resume:2", draft=draft)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()
    ctx = _ctx(container, bot, queue, storage)
    await notify_payment_settled(ctx, public_ref)
    assert len(queue.jobs) == 1

    # Act
    await notify_payment_settled(ctx, public_ref)

    # Assert
    assert len(queue.jobs) == 1


async def test_a_draft_that_moved_since_the_link_is_not_resumed(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """The customer edited their note after paying. Render the OLD answers? No.

    And they are not stranded for it: the receipt carries a live 🎬 on the draft they are
    actually holding, which is one tap rather than none.
    """
    # Arrange
    draft = _resumable_draft()
    public_ref, _ = await _open_resumable(rail, key="topup:resume:3", draft=draft)
    await _park_confirm(storage, bot, draft.model_copy(update={"note": "Actually, loves the sea"}))
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert
    assert queue.jobs == []
    messages = _sent(session)
    assert len(messages) == 1
    assert messages[0].reply_markup == paid_late_keyboard(Language.RU)


async def test_a_draft_parked_somewhere_other_than_confirm_is_not_resumed(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """Mid-edit is not mid-wait.

    An unedited draft on the lyrics screen fingerprints EQUAL to the one that was paid for, so
    the id comparison alone would wave this through and yank the customer into
    ``Wizard.submitting`` while they were typing. The state check is the only thing that tells
    "the screen they left" from "the screen they are on".
    """
    # Arrange
    draft = _resumable_draft()
    key = await _park_confirm(storage, bot, draft)
    await storage.set_state(key, Wizard.lyrics)
    public_ref, _ = await _open_resumable(rail, key="topup:resume:4", draft=draft)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert
    assert queue.jobs == []
    assert await storage.get_state(key) == Wizard.lyrics.state


async def test_a_session_already_waiting_on_a_render_is_left_alone(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """The customer pressed 🎬 themselves while the payment was settling."""
    # Arrange
    draft = _resumable_draft()
    key = await _park_confirm(storage, bot, draft)
    await storage.set_state(key, Wizard.submitting)
    await storage.update_data(key, {ORDER_ID_KEY: "an-order-already-in-flight"})
    public_ref, _ = await _open_resumable(rail, key="topup:resume:5", draft=draft)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert — nothing queued, and the park that was there is untouched.
    assert queue.jobs == []
    assert (await storage.get_data(key))[ORDER_ID_KEY] == "an-order-already-in-flight"


async def test_a_second_wizard_run_is_left_untouched(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """The ``_release_session`` bug class, guarded from the other direction.

    ``/start`` does not refuse while a payment is open, so by the time a settlement lands the
    customer may be three screens into a SECOND run. Writing this job's park blind would wipe
    that run's draft, and the customer's next button press would be answered "that session
    expired".
    """
    # Arrange
    paid_for = _resumable_draft()
    public_ref, _ = await _open_resumable(rail, key="topup:resume:6", draft=paid_for)
    second_run = _resumable_draft().model_copy(update={"session_id": "a-completely-new-run"})
    key = await _park_confirm(storage, bot, second_run)
    before = await storage.get_data(key)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert
    assert queue.jobs == []
    assert await storage.get_data(key) == before
    assert await storage.get_state(key) == Wizard.confirm.state


async def test_a_settlement_with_no_marker_queues_nothing_but_still_offers_the_draft(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """A ``/balance`` purchase: no marker is ever minted, so nothing is resumed.

    **But the keyboard is chosen from the SESSION rather than from the marker**, which is what
    covers this population without the bot having to guess which wizard run a balance-screen
    purchase belonged to. One tap, on the draft they were actually working on.
    """
    # Arrange
    await _park_confirm(storage, bot, _resumable_draft())
    public_ref = await _open_single(rail, key="topup:resume:7", language=Language.RU.value)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert
    assert queue.jobs == []
    assert _sent(session)[0].reply_markup == paid_late_keyboard(Language.RU)


async def test_a_settlement_with_no_draft_at_all_still_offers_a_way_back(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """Session gone — expired, cleared, or a Redis flush. ``start_over_keyboard`` is right HERE.

    The paired half of the test above: ↩️ Start over destroys a draft, which is why it is no
    longer the default, and is exactly the right offer for somebody who has no draft to lose.
    """
    # Arrange
    public_ref = await _open_single(rail, key="topup:resume:8", language=Language.RU.value)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert
    assert queue.jobs == []
    assert _sent(session)[0].reply_markup == start_over_keyboard(Language.RU)


async def test_a_blocked_customer_resumes_nothing(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """**The money assertion.** A paid credit must not be spent on a kit that cannot arrive.

    ``entitlements`` settles ``NOT_DELIVERED`` exactly as it settles ``DELIVERED``, so
    rendering for a chat Telegram has told us is unreachable burns the customer's song for
    nothing. "They paid, render it anyway" is rejected, and the ``return`` above the resume in
    ``notify_payment_settled`` is where.
    """
    # Arrange
    draft = _resumable_draft()
    await _park_confirm(storage, bot, draft)
    public_ref, _ = await _open_resumable(rail, key="topup:resume:9", draft=draft)
    await _settle(rail, public_ref, now=clock.now)
    session.failures["SendMessage"] = TelegramForbiddenError(
        method=SendMessage(chat_id=_BUYER, text="x"),
        message="Forbidden: bot was blocked by the user",
    )
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert
    assert queue.jobs == []


async def test_an_erased_buyer_resumes_nothing(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """``/forget`` between the link and the settlement. Erasure also NULLS the marker."""
    # Arrange
    draft = _resumable_draft()
    await _park_confirm(storage, bot, draft)
    public_ref, _ = await _open_resumable(rail, key="topup:resume:10", draft=draft)
    await _settle(rail, public_ref, now=clock.now)
    ledger = container.credits
    assert ledger is not None
    assert is_ok(await ledger.forget(_BUYER))
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert — nobody told, nothing rendered, and the marker is gone from the row.
    assert queue.jobs == []
    assert _sent(session) == []
    found = await rail.intent(public_ref=public_ref)
    assert is_ok(found)
    assert found.value is not None and found.value.resume_order_id is None


async def test_a_worker_without_fsm_storage_still_announces_and_queues_nothing(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """The storage handle is OPTIONAL in the ctx, and a worker wired without it must still tell
    the customer their money landed — degrading the way ``jobs._release_session`` degrades."""
    # Arrange
    draft = _resumable_draft()
    public_ref, _ = await _open_resumable(rail, key="topup:resume:11", draft=draft)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    await notify_payment_settled(_ctx(container, bot, queue), public_ref)

    # Assert
    assert queue.jobs == []
    assert len(_sent(session)) == 1


async def test_a_worker_without_a_queue_handle_announces_and_does_not_raise(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """Raising here would re-enter the retry ladder, and every rung RE-SENDS the announcement."""
    # Arrange
    draft = _resumable_draft()
    await _park_confirm(storage, bot, draft)
    public_ref, _ = await _open_resumable(rail, key="topup:resume:12", draft=draft)
    await _settle(rail, public_ref, now=clock.now)

    # Act — no queue in the ctx at all.
    await notify_payment_settled(_ctx(container, bot, None, storage), public_ref)

    # Assert — the payment sentence landed; the progress frame did not.
    assert [message.text for message in _sent(session)] == [
        translate(PAID_LATE_RESUMING_KEY, Language.RU)
    ]


async def test_the_flag_off_announces_and_queues_nothing(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    """The rollback lever, and the thing it must NOT do on its way out.

    ``BAYRAM_AUTO_RENDER_ON_PAYMENT=false`` restores the old behaviour — but the old behaviour
    put ↩️ Start over under every receipt, which destroys the draft the customer just paid
    for. Rolling back must not ship customers onto that button.
    """
    # Arrange
    draft = _resumable_draft()
    await _park_confirm(storage, bot, draft)
    public_ref, _ = await _open_resumable(rail, key="topup:resume:13", draft=draft)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()
    off = replace(
        container, settings=container.settings.model_copy(update={"auto_render_on_payment": False})
    )

    # Act
    await notify_payment_settled(_ctx(off, bot, queue, storage), public_ref)

    # Assert
    assert queue.jobs == []
    messages = _sent(session)
    assert messages[0].text != translate(PAID_LATE_RESUMING_KEY, Language.RU)
    assert messages[0].reply_markup == paid_late_keyboard(Language.RU)


async def test_every_settlement_says_what_it_decided_about_the_render(
    container: AppContainer,
    rail: SqlPaymeLedger,
    clock: MovableClock,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A DECLINE must say why, and this is the case that shipped silent.

    The decision line first landed inside the ``if assessment.plan is not None`` branch, so it
    fired only when a render had actually been attempted — which is to say it was absent for
    every case an operator is ever asked about. Found by running the real three processes:
    a settlement declined with ``not_on_confirm`` and the worker log said nothing at all,
    while ``06-troubleshooting.md`` §20.4 was telling the reader to grep for exactly this line.

    Driven through the ``not_on_confirm`` path because that is the one that was observed, and
    asserted on the REASON rather than on the mere presence of the line: a line that always
    said ``queued`` would satisfy a presence check and answer nothing.
    """
    # Arrange — a draft that is complete and paid for, but the customer has gone back to an
    # earlier step, which is what somebody who returns from a payment page and starts over
    # actually looks like.
    draft = _resumable_draft()
    key = await _park_confirm(storage, bot, draft)
    await storage.set_state(key, Wizard.occasion)
    public_ref, _ = await _open_resumable(rail, key="topup:resume:14", draft=draft)
    await _settle(rail, public_ref, now=clock.now)
    queue = _RecordingQueue()

    # Act
    with caplog.at_level(logging.INFO, logger="bayram.runtime.payme_jobs"):
        await notify_payment_settled(_ctx(container, bot, queue, storage), public_ref)

    # Assert — nothing queued, and the log says which guard declined it.
    assert queue.jobs == []
    considered = [
        record
        for record in caplog.records
        if record.message == "the settled payment's render was considered"
    ]
    assert len(considered) == 1
    # Fields passed through logging's `extra=` land in the record's __dict__ and are not
    # attributes `logging.LogRecord` declares, so they are read as such rather than pretended
    # to be typed members.
    assert considered[0].__dict__["reason"] == "not_on_confirm"
    assert considered[0].__dict__["is_queued"] is False
