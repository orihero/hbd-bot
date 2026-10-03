"""The checkout.uz webhook route: always 200, believes nothing, writes nothing, enqueues at most once.

The real :class:`CheckoutUzWebhookGate` over SQLite and a fake queue. Every request below gets
``200 {"ok": true}``; what differs is whether a reconcile job was enqueued (``DECISIONS.md D28``).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkoutuz.app import (
    CHECKOUTUZ_GATE_STATE_ATTR,
    MAX_WEBHOOK_BODY_BYTES,
    CheckoutUzWebhookGate,
    create_checkoutuz_app,
)
from bayram.checkoutuz.jobs import CHECKOUTUZ_RECONCILE_JOB_NAME, reconcile_job_id
from bayram.db.enums import CheckoutUzPaymentState
from bayram.db.models import CheckoutUzPaymentRow, CreditLedgerRow, PaymentIntentRow
from bayram.db.payme import SqlPaymeLedger
from tests.test_checkoutuz.conftest import ORDER, open_intent, record_payment


class FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], str | None]] = []

    async def enqueue_job(self, function: str, *args: Any, _job_id: str | None = None) -> Any:
        self.jobs.append((function, args, _job_id))
        return None


class RaisingGate:
    async def admit(self, *, order_id: int, public_ref: str | None) -> bool:
        raise RuntimeError("database down")


def _webhook(order_id: Any = ORDER) -> dict[str, Any]:
    return {
        "webhook_type": "version_1_1",
        "status": "success",
        "event": "payment_confirmed",
        "payment_system": "click",
        "shop_id": 3,
        "data": {
            "order_id": order_id,
            "amount": 7000,
            "currency": "UZS",
            "status": "paid",
            "provider_details": {},
            "perform_time": 1784393083895,
        },
        "timestamp": 1784393083,
    }


async def _post(app: Any, path: str, *, content: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            path, content=content, headers={"Content-Type": "application/json"}
        )


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def gate(sessions: async_sessionmaker[AsyncSession], redis: FakeRedis) -> CheckoutUzWebhookGate:
    return CheckoutUzWebhookGate(sessions, redis)


async def _known_pending(
    sessions: async_sessionmaker[AsyncSession], ledger: SqlPaymeLedger, provider: str = "checkoutuz"
) -> str:
    intent = await open_intent(ledger, provider=provider)
    await record_payment(sessions, intent)
    return intent.public_ref


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"[]",
        json.dumps({"data": {}}).encode(),
        json.dumps(_webhook("abc")).encode(),
        json.dumps(_webhook(-5)).encode(),
        json.dumps(_webhook(True)).encode(),
        json.dumps(_webhook(2**70)).encode(),
        json.dumps(_webhook(999)).encode(),  # well-formed, unknown order
    ],
)
async def test_garbage_and_unknown_orders_get_200_and_no_job(
    gate: CheckoutUzWebhookGate, redis: FakeRedis, content: bytes
) -> None:
    response = await _post(create_checkoutuz_app(gate), "/checkoutuz/callback", content=content)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert redis.jobs == []


@pytest.mark.parametrize("suffix", ["", "/"])
async def test_a_known_pending_order_enqueues_one_deterministic_job(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    gate: CheckoutUzWebhookGate,
    redis: FakeRedis,
    suffix: str,
) -> None:
    ref = await _known_pending(sessions, ledger)

    response = await _post(
        create_checkoutuz_app(gate),
        f"/checkoutuz/callback/{ref}{suffix}",
        content=json.dumps(_webhook()).encode(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert redis.jobs == [(CHECKOUTUZ_RECONCILE_JOB_NAME, (ORDER,), reconcile_job_id(ORDER))]
    assert reconcile_job_id(ORDER) == f"checkoutuz_reconcile:{ORDER}"


async def test_the_bare_callback_and_a_string_order_id_are_accepted(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    gate: CheckoutUzWebhookGate,
    redis: FakeRedis,
) -> None:
    await _known_pending(sessions, ledger)

    await _post(
        create_checkoutuz_app(gate),
        "/checkoutuz/callback/",
        content=json.dumps(_webhook(str(ORDER))).encode(),
    )

    assert len(redis.jobs) == 1


async def test_a_public_ref_mismatch_enqueues_nothing(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    gate: CheckoutUzWebhookGate,
    redis: FakeRedis,
) -> None:
    await _known_pending(sessions, ledger)

    response = await _post(
        create_checkoutuz_app(gate),
        "/checkoutuz/callback/someone-elses-ref",
        content=json.dumps(_webhook()).encode(),
    )

    assert response.status_code == 200
    assert redis.jobs == []


async def test_an_order_on_another_rails_intent_enqueues_nothing(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    gate: CheckoutUzWebhookGate,
    redis: FakeRedis,
) -> None:
    await _known_pending(sessions, ledger, provider="payme")

    await _post(
        create_checkoutuz_app(gate), "/checkoutuz/callback", content=json.dumps(_webhook()).encode()
    )

    assert redis.jobs == []


async def test_a_settled_order_enqueues_nothing(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    gate: CheckoutUzWebhookGate,
    redis: FakeRedis,
) -> None:
    await _known_pending(sessions, ledger)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(CheckoutUzPaymentRow).values(state=CheckoutUzPaymentState.PAID)
        )

    await _post(
        create_checkoutuz_app(gate), "/checkoutuz/callback", content=json.dumps(_webhook()).encode()
    )

    assert redis.jobs == []


async def test_a_link_closed_as_expired_still_enqueues_a_reconcile(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    gate: CheckoutUzWebhookGate,
    redis: FakeRedis,
) -> None:
    # A page left open past the final check can still be paid; this webhook is the only
    # signal and it is never retried, so the reconcile must be queued (``DECISIONS.md D28``).
    await _known_pending(sessions, ledger)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(CheckoutUzPaymentRow).values(state=CheckoutUzPaymentState.EXPIRED)
        )

    await _post(
        create_checkoutuz_app(gate), "/checkoutuz/callback", content=json.dumps(_webhook()).encode()
    )

    assert redis.jobs == [(CHECKOUTUZ_RECONCILE_JOB_NAME, (ORDER,), reconcile_job_id(ORDER))]


async def test_an_oversized_body_is_ignored(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    gate: CheckoutUzWebhookGate,
    redis: FakeRedis,
) -> None:
    await _known_pending(sessions, ledger)
    body = _webhook()
    body["padding"] = "x" * MAX_WEBHOOK_BODY_BYTES

    response = await _post(
        create_checkoutuz_app(gate), "/checkoutuz/callback", content=json.dumps(body).encode()
    )

    assert response.status_code == 200
    assert redis.jobs == []


async def test_no_gate_and_a_failing_gate_still_answer_200() -> None:
    content = json.dumps(_webhook()).encode()

    unconfigured = await _post(create_checkoutuz_app(), "/checkoutuz/callback", content=content)
    failing = await _post(
        create_checkoutuz_app(RaisingGate()), "/checkoutuz/callback", content=content
    )

    assert unconfigured.status_code == 200 and unconfigured.json() == {"ok": True}
    assert failing.status_code == 200 and failing.json() == {"ok": True}


async def test_the_gate_is_read_from_app_state(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    gate: CheckoutUzWebhookGate,
    redis: FakeRedis,
) -> None:
    await _known_pending(sessions, ledger)
    app = create_checkoutuz_app()
    setattr(app.state, CHECKOUTUZ_GATE_STATE_ATTR, gate)

    await _post(app, "/checkoutuz/callback", content=json.dumps(_webhook()).encode())

    assert len(redis.jobs) == 1


async def test_the_gateway_never_writes_to_settlement_tables(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    gate: CheckoutUzWebhookGate,
    redis: FakeRedis,
) -> None:
    ref = await _known_pending(sessions, ledger)

    async def _snapshot() -> tuple[Any, ...]:
        async with sessions() as session:
            payment = (await session.execute(sa.select(CheckoutUzPaymentRow))).scalar_one()
            intent = (await session.execute(sa.select(PaymentIntentRow))).scalar_one()
            credits = await session.scalar(sa.select(sa.func.count()).select_from(CreditLedgerRow))
            return (
                payment.state,
                payment.last_polled_at,
                payment.updated_at,
                intent.state,
                intent.updated_at,
                credits,
            )

    before = await _snapshot()
    for _ in range(3):
        await _post(
            create_checkoutuz_app(gate),
            f"/checkoutuz/callback/{ref}",
            content=json.dumps(_webhook()).encode(),
        )

    assert await _snapshot() == before
