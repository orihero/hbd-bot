"""The worker's checkout.uz jobs: the poll is the source of truth, and it never reads a sale switch.

A hand-built worker context (container with settings and a session factory, plus a fake queue)
and a scripted vendor. Settlement itself is pinned in ``test_settle.py``; these tests pin which
orders each arm picks up and what it does with the answer (``DECISIONS.md D28``).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkoutuz import jobs as jobs_module
from bayram.checkoutuz.jobs import (
    CHECKOUTUZ_POLL_JOB_NAME,
    CHECKOUTUZ_RECONCILE_JOB_NAME,
    reconcile_checkoutuz_order,
    run_checkoutuz_poll,
)
from bayram.checkoutuz.ports import FINAL_CHECK_GIVE_UP_S, POLL_GRACE_S
from bayram.contracts import err
from bayram.db.enums import CheckoutUzPaymentState, PaymentIntentState
from bayram.db.models import CheckoutUzPaymentRow, CreditLedgerRow, PaymentIntentRow
from bayram.db.payme import SqlPaymeLedger
from bayram.errors import CheckoutError, PipelineError
from tests.test_checkoutuz.conftest import (
    ORDER,
    USER,
    Clock,
    FakeCheckoutUz,
    open_intent,
    record_payment,
)


class FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], str | None]] = []

    async def enqueue_job(self, function: str, *args: Any, _job_id: str | None = None) -> Any:
        self.jobs.append((function, args, _job_id))
        return None


class FakeContainer:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], **settings: Any) -> None:
        values: dict[str, Any] = {
            "checkoutuz_api_key": "key",
            "checkoutuz_base_url": "https://checkout.invalid/api/v1",
            "checkoutuz_poll_batch": 50,
            # The sale-side flag is OFF in every test here: settlement must not read it.
            "checkoutuz_enabled": False,
        }
        values.update(settings)
        self.settings = SimpleNamespace(**values)
        self._sessions = sessions

    def require_session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._sessions


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def ctx(sessions: async_sessionmaker[AsyncSession], redis: FakeRedis) -> dict[str, Any]:
    return {"container": FakeContainer(sessions), "redis": redis}


async def _payment(sessions: async_sessionmaker[AsyncSession], order_id: int = ORDER) -> Any:
    async with sessions() as session:
        return (
            await session.execute(
                sa.select(CheckoutUzPaymentRow).where(CheckoutUzPaymentRow.order_id == order_id)
            )
        ).scalar_one()


def test_the_job_names_are_the_registered_function_names() -> None:
    assert reconcile_checkoutuz_order.__name__ == CHECKOUTUZ_RECONCILE_JOB_NAME
    assert run_checkoutuz_poll.__name__ == CHECKOUTUZ_POLL_JOB_NAME


async def test_the_poll_settles_a_paid_order_and_queues_the_announcement(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    ctx: dict[str, Any],
    redis: FakeRedis,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 7_000)

    summary = await run_checkoutuz_poll(ctx, now=clock.now, client=vendor)

    assert summary["polled"] == 1
    assert summary["settled"] == 1
    assert summary["faults"] == 0
    assert (await _payment(sessions)).state is CheckoutUzPaymentState.PAID
    assert redis.jobs == [
        (
            "notify_payment_settled",
            (intent.public_ref,),
            f"notify_payment_settled:{intent.public_ref}",
        )
    ]


async def test_a_pending_order_is_stamped_and_left_pending(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    ctx: dict[str, Any],
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    clock.advance(seconds=300)

    summary = await run_checkoutuz_poll(ctx, now=clock.now, client=vendor)

    assert summary["not_paid"] == 1
    payment = await _payment(sessions)
    assert payment.state is CheckoutUzPaymentState.PENDING
    assert payment.last_polled_at == clock.now


async def test_the_final_check_closes_a_lapsed_unpaid_link_and_leaves_the_intent(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    ctx: dict[str, Any],
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    clock.advance(seconds=3600 + POLL_GRACE_S)

    summary = await run_checkoutuz_poll(ctx, now=clock.now, client=vendor)

    assert summary["polled"] == 0
    assert summary["final_checked"] == 1
    assert summary["expired"] == 1
    assert vendor.asked == [ORDER]
    assert (await _payment(sessions)).state is CheckoutUzPaymentState.EXPIRED
    async with sessions() as session:
        state = await session.scalar(sa.select(PaymentIntentRow.state))
    assert state is PaymentIntentState.PENDING


async def test_the_final_check_still_settles_a_lapsed_link_that_was_paid(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    ctx: dict[str, Any],
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 7_000)
    clock.advance(seconds=3600 + POLL_GRACE_S)

    summary = await run_checkoutuz_poll(ctx, now=clock.now, client=vendor)

    assert summary["settled"] == 1
    assert summary["expired"] == 0
    assert (await _payment(sessions)).state is CheckoutUzPaymentState.PAID


async def test_the_final_check_keeps_a_link_it_could_not_ask_about(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    ctx: dict[str, Any],
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.status_error = CheckoutError("down", is_retryable=True)
    clock.advance(seconds=3600 + POLL_GRACE_S)

    summary = await run_checkoutuz_poll(ctx, now=clock.now, client=vendor)

    assert summary["retry_later"] == 1
    assert summary["expired"] == 0 and summary["unresolved"] == 0
    payment = await _payment(sessions)
    assert payment.state is CheckoutUzPaymentState.PENDING
    assert payment.last_polled_at == clock.now


@pytest.mark.parametrize("retryable", [True, False])
async def test_the_final_check_gives_up_a_day_after_the_link_and_says_so_at_error(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    ctx: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    retryable: bool,
) -> None:
    """Bounded: an order checkout.uz never answers for is not re-asked forever. It is closed
    ``expired`` — the intent untouched — with an ERROR naming the order for a manual check."""
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.status_error = CheckoutError("refused", is_retryable=retryable)

    # Just inside the give-up window: still pending.
    clock.advance(seconds=3600 + FINAL_CHECK_GIVE_UP_S - 1)
    inside = await run_checkoutuz_poll(ctx, now=clock.now, client=vendor)
    assert inside["unresolved"] == 0
    assert (await _payment(sessions)).state is CheckoutUzPaymentState.PENDING

    clock.advance(seconds=1)
    with caplog.at_level(logging.INFO, logger="bayram.checkoutuz.jobs"):
        summary = await run_checkoutuz_poll(ctx, now=clock.now, client=vendor)

    assert summary["retry_later"] == 1
    assert summary["expired"] == 1
    assert summary["unresolved"] == 1
    assert (await _payment(sessions)).state is CheckoutUzPaymentState.EXPIRED
    async with sessions() as session:
        state = await session.scalar(sa.select(PaymentIntentRow.state))
    assert state is PaymentIntentState.PENDING
    (record,) = [
        r for r in caplog.records if r.__dict__.get("event") == "checkoutuz.final_check_unresolved"
    ]
    assert record.levelno == logging.ERROR
    assert record.__dict__["order_id"] == ORDER


async def test_failing_rows_do_not_starve_the_final_check_batch(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    redis: FakeRedis,
) -> None:
    """With a batch of one and the oldest lapsed link failing every time, the next run still
    reaches the newer lapsed link — and expires it — because a failed attempt is stamped."""
    intent = await open_intent(ledger)
    await record_payment(sessions, intent, order_id=ORDER)
    await record_payment(sessions, intent, order_id=ORDER + 1, lifetime_s=3700)
    ctx = {"container": FakeContainer(sessions, checkoutuz_poll_batch=1), "redis": redis}

    class OneBadOrder(FakeCheckoutUz):
        async def status_payment(self, *, order_id: int) -> Any:
            if order_id == ORDER:
                self.asked.append(order_id)
                return err(CheckoutError("purged", is_retryable=False))
            return await super().status_payment(order_id=order_id)

    bad = OneBadOrder()
    clock.advance(seconds=3700 + POLL_GRACE_S)

    first = await run_checkoutuz_poll(ctx, now=clock.now, client=bad)
    second = await run_checkoutuz_poll(ctx, now=clock.advance(seconds=300), client=bad)

    assert bad.asked == [ORDER, ORDER + 1]
    assert first["retry_later"] == 1
    assert second["expired"] == 1
    assert (await _payment(sessions, ORDER + 1)).state is CheckoutUzPaymentState.EXPIRED
    assert (await _payment(sessions, ORDER)).state is CheckoutUzPaymentState.PENDING


async def test_the_poll_runs_with_the_sale_flag_and_owner_switch_off(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    redis: FakeRedis,
) -> None:
    """Neither the env flag nor the Redis switch is read: the context below has no switch at
    all, the flag is False, and a payment in flight still settles."""
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 7_000)
    ctx = {"container": FakeContainer(sessions, checkoutuz_enabled=False), "redis": redis}

    summary = await run_checkoutuz_poll(ctx, now=clock.now, client=vendor)

    assert summary["settled"] == 1
    async with sessions() as session:
        credits = await session.scalar(sa.select(sa.func.count()).select_from(CreditLedgerRow))
    assert credits == 1


@pytest.mark.parametrize("key", ["", "   "])
async def test_a_blank_key_skips_both_jobs(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    redis: FakeRedis,
    key: str,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    ctx = {"container": FakeContainer(sessions, checkoutuz_api_key=key), "redis": redis}

    poll = await run_checkoutuz_poll(ctx, now=clock.now, client=vendor)
    one = await reconcile_checkoutuz_order(ctx, ORDER, client=vendor, now=clock.now)

    assert poll == {"skipped": "no key"}
    assert one == {"skipped": "no key"}
    assert vendor.asked == []


async def test_reconcile_settles_one_order(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    ctx: dict[str, Any],
) -> None:
    intent = await open_intent(ledger, key=f"topup:{USER}:single:9")
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 7_000)

    result = await reconcile_checkoutuz_order(ctx, ORDER, client=vendor, now=clock.now)

    assert result == {"order_id": ORDER, "status": "settled"}


async def test_a_job_builds_its_own_client_and_always_closes_it(
    sessions: async_sessionmaker[AsyncSession],
    vendor: FakeCheckoutUz,
    clock: Clock,
    ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[Any] = []

    class _Built(FakeCheckoutUz):
        def __init__(self, *, api_key: str, base_url: str) -> None:
            super().__init__()
            self.api_key = api_key
            self.base_url = base_url
            self.closed = False
            built.append(self)

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr(jobs_module, "CheckoutUzClient", _Built)

    await run_checkoutuz_poll(ctx, now=clock.now)
    await reconcile_checkoutuz_order(ctx, ORDER, now=clock.now)

    assert len(built) == 2
    assert all(c.closed for c in built)
    assert built[0].api_key == "key"
    assert built[0].base_url == "https://checkout.invalid/api/v1"


async def test_a_missing_container_is_a_pipeline_error() -> None:
    with pytest.raises(PipelineError):
        await run_checkoutuz_poll({})


async def test_no_queue_handle_still_settles(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 7_000)

    summary = await run_checkoutuz_poll(
        {"container": FakeContainer(sessions)}, now=clock.now, client=vendor
    )

    assert summary["settled"] == 1
