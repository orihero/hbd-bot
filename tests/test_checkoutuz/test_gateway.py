"""The checkout.uz webhook as the GATEWAY mounts it: the route is there, and the gate is armed.

``test_app.py`` proves the route against a gate it hands in. These prove the composition
(``DECISIONS.md D28``): ``bayram.payme.app.create_app`` includes the router, and its lifespan
sets the :class:`~bayram.checkoutuz.app.CheckoutUzWebhookGate` over the container's own session
factory and queue — unconditionally, because the gate holds no secret. A gateway that mounted
the route and forgot the gate would answer 200 to every webhook and enqueue nothing, which is
indistinguishable from a working one until somebody counts the minutes a paid customer waited
for the poller.

Built over in-memory SQLite and a fake queue, in the shape ``tests/test_rhmt/test_app.py``
established for the Rahmat route. Nothing here reaches checkout.uz, Payme or a real Redis.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bayram.checkoutuz.app import CHECKOUTUZ_GATE_STATE_ATTR, CheckoutUzWebhookGate
from bayram.checkoutuz.jobs import CHECKOUTUZ_RECONCILE_JOB_NAME, reconcile_job_id
from bayram.db.payme import SqlPaymeLedger
from bayram.payme.app import create_app as create_payme_app
from bayram.payme.container import PaymeContainer, SqlRpcJournal
from bayram.payme.service import PaymeService
from bayram.payme.settings import PAYME_ENV_FILE_VAR, PaymeSettings, build_payme_settings
from tests.test_checkoutuz.conftest import ORDER, Clock, open_intent, record_payment


class _FakeQueue:
    """``ArqRedis`` as far as the gate and the container's ``aclose`` reach into it."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], str | None]] = []

    async def enqueue_job(self, function: str, *args: Any, _job_id: str | None = None) -> Any:
        self.jobs.append((function, args, _job_id))
        return None

    async def aclose(self) -> None:
        return None


@pytest.fixture
def payme_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> PaymeSettings:
    # A dotenv that does not exist, so a developer's own payme.env decides nothing here.
    monkeypatch.setenv(PAYME_ENV_FILE_VAR, str(tmp_path / "there-is-no-payme.env"))
    return build_payme_settings(
        {
            "_env_file": None,
            "database_url": "sqlite+aiosqlite:///:memory:",
            "payme_enabled": True,
            "payme_merchant_id": "587f72c72cac0d162c722ae2",
            "payme_merchant_key": "d4f1a9c07b2e46d8ab53c1e90f7a2b6c5d3e",
            "payme_basic_login": "Paycom",
        }
    )


@pytest.fixture
def queue() -> _FakeQueue:
    return _FakeQueue()


@pytest.fixture
def container(
    payme_settings: PaymeSettings,
    engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    queue: _FakeQueue,
    clock: Clock,
) -> PaymeContainer:
    ledger = SqlPaymeLedger(sessions, merchant_id=payme_settings.payme_merchant_id)
    return PaymeContainer(
        settings=payme_settings,
        engine=engine,
        session_factory=sessions,
        redis=queue,  # type: ignore[arg-type]
        ledger=ledger,
        service=PaymeService(
            ledger,
            clock=clock,
            journal=SqlRpcJournal(sessions),
            notify=lambda _ref: asyncio.sleep(0),
            account_field=payme_settings.payme_account_field,
            duplicate_code=payme_settings.payme_duplicate_transaction_code,
        ),
        clock=clock,
    )


def _webhook(order_id: Any = ORDER) -> bytes:
    return json.dumps(
        {
            "webhook_type": "version_1_1",
            "status": "success",
            "event": "payment_confirmed",
            "data": {"order_id": order_id, "amount": 7000, "currency": "UZS", "status": "paid"},
        }
    ).encode()


async def _post(container: PaymeContainer, path: str, *, content: bytes) -> httpx.Response:
    gateway = create_payme_app(container=container)
    async with gateway.router.lifespan_context(gateway):
        # The lifespan is what arms the gate; without this assertion a missing ``setattr``
        # would read as "unknown order" in every test below.
        assert isinstance(getattr(gateway.state, CHECKOUTUZ_GATE_STATE_ATTR), CheckoutUzWebhookGate)
        transport = httpx.ASGITransport(app=gateway)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            headers = {"Content-Type": "application/json"}
            return await client.post(path, content=content, headers=headers)


async def test_a_known_pending_order_on_the_gateway_enqueues_exactly_one_reconcile(
    container: PaymeContainer,
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    queue: _FakeQueue,
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)

    # Act
    response = await _post(
        container, f"/checkoutuz/callback/{intent.public_ref}", content=_webhook()
    )

    # Assert — 200 with the ack, and ONE job under the deterministic id, so a burst of
    # identical webhooks collapses to one reconcile in arq.
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert queue.jobs == [(CHECKOUTUZ_RECONCILE_JOB_NAME, (ORDER,), reconcile_job_id(ORDER))]


async def test_an_unknown_order_on_the_gateway_is_acknowledged_and_queues_nothing(
    container: PaymeContainer, queue: _FakeQueue
) -> None:
    # Act — the unsigned body names an order this deployment never created.
    response = await _post(container, "/checkoutuz/callback", content=_webhook(999))

    # Assert — always 200 (the webhook is never retried, so an error buys nothing), no job.
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert queue.jobs == []


async def test_the_payme_endpoint_is_untouched_by_the_new_mount(container: PaymeContainer) -> None:
    # The JSON-RPC fault middleware is scoped to ``/payme`` alone, and the checkout.uz mount
    # must not have widened or narrowed that: an unauthenticated Payme call still gets the
    # JSON-RPC envelope at HTTP 200, not the checkout.uz ack.
    response = await _post(
        container,
        "/payme",
        content=json.dumps({"id": 1, "method": "CheckPerformTransaction", "params": {}}).encode(),
    )

    assert response.status_code == 200
    assert "error" in response.json()
    assert response.json() != {"ok": True}
