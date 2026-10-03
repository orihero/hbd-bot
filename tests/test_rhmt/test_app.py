"""Tests for the Rahmat webhook FastAPI application and router."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import (
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from bayram.checkout import Product
from bayram.contracts import is_ok
from bayram.db.base import Base
from bayram.db.engine import create_session_factory
from bayram.db.payme import SqlPaymeLedger
from bayram.payme.app import create_app as create_payme_app
from bayram.payme.container import PaymeContainer, SqlRpcJournal, build_payme_container
from bayram.payme.service import PaymeService
from bayram.payme.settings import PAYME_ENV_FILE_VAR, build_payme_settings
from bayram.rhmt.app import create_rhmt_app
from bayram.rhmt.ports import RHMT_PROVIDER_NAME

_SECRET = "test_rhmt_secret_98765"


class _FakeService:
    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body or {"success": True}
        self.received_payloads: list[dict[str, Any]] = []

    async def handle_callback(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.received_payloads.append(payload)
        return self.status, self.body


@pytest.mark.anyio
async def test_standalone_rhmt_app_unconfigured_service() -> None:
    app = create_rhmt_app(service=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/rhmt/callback", json={"key": "val"})
        assert resp.status_code == 503
        data = resp.json()
        assert data["success"] is False
        assert "not configured" in data["error"]


@pytest.mark.anyio
async def test_standalone_rhmt_app_invalid_json() -> None:
    fake_service = _FakeService()
    app = create_rhmt_app(service=fake_service)  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/rhmt/callback",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "invalid json body"


@pytest.mark.anyio
async def test_standalone_rhmt_app_delegates_to_service() -> None:
    fake_service = _FakeService(status=200, body={"success": True, "note": "ok"})
    app = create_rhmt_app(service=fake_service)  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"invoice_id": "inv_123", "amount": 700000}
        resp = await client.post("/rhmt/callback", json=payload)
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "note": "ok"}
        assert fake_service.received_payloads == [payload]


@pytest.mark.anyio
async def test_standalone_rhmt_app_trailing_slash() -> None:
    fake_service = _FakeService(status=200, body={"success": True})
    app = create_rhmt_app(service=fake_service)  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/rhmt/callback/", json={"test": 1})
        assert resp.status_code == 200


@pytest.fixture
def _no_local_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    monkeypatch.setenv(PAYME_ENV_FILE_VAR, "/nonexistent/payme.env")


@pytest.mark.anyio
async def test_gateway_app_rhmt_callback_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that the main gateway app mounts /rhmt/callback and settles via RhmtWebhookService."""
    monkeypatch.setenv("BAYRAM_RHMT_SECRET", _SECRET)
    # Pinned: otherwise a developer's .env.rhmt decides which hash this test must send.
    monkeypatch.setenv("BAYRAM_RHMT_CALLBACK_SCHEME", "webhooks")

    built_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with built_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = create_session_factory(built_engine)

    payme_settings = build_payme_settings(
        {
            "_env_file": None,
            "database_url": "sqlite+aiosqlite:///:memory:",
            "payme_enabled": True,
            "payme_merchant_id": "587f72c72cac0d162c722ae2",
            "payme_merchant_key": "d4f1a9c07b2e46d8ab53c1e90f7a2b6c5d3e",
            "payme_basic_login": "Paycom",
        }
    )

    container = await build_payme_container(payme_settings)
    # Point container to our memory engine
    container = PaymeContainer(
        settings=payme_settings,
        engine=built_engine,
        session_factory=session_factory,
        redis=container.redis,
        ledger=SqlPaymeLedger(session_factory, merchant_id=payme_settings.payme_merchant_id),
        service=PaymeService(
            SqlPaymeLedger(session_factory, merchant_id=payme_settings.payme_merchant_id),
            clock=container.clock,
            journal=SqlRpcJournal(session_factory),
            notify=lambda _ref: asyncio.sleep(0),
            account_field=payme_settings.payme_account_field,
            duplicate_code=payme_settings.payme_duplicate_transaction_code,
        ),
        clock=container.clock,
    )

    # Open intent
    res = await container.ledger.open_intent(
        telegram_user_id=123456789,
        product=Product.SINGLE,
        amount_minor=700000,
        currency="UZS",
        idempotency_key=f"topup:123456789:single:{uuid4().hex[:8]}",
        language="uz_latn",
        merchant_id=payme_settings.payme_merchant_id,
        is_sandbox=True,
        provider=RHMT_PROVIDER_NAME,
    )
    assert is_ok(res)
    intent = res.value

    # Create gateway app
    gateway_app = create_payme_app(container=container)

    uuid = "multicard-gw-uuid-1"
    amount = 700000
    sign = hashlib.sha1(f"{uuid}{intent.public_ref}{amount}{_SECRET}".encode()).hexdigest()
    payload = {
        "uuid": uuid,
        "invoice_id": intent.public_ref,
        "amount": amount,
        "status": 1,
        "sign": sign,
    }

    async with gateway_app.router.lifespan_context(gateway_app):
        transport = httpx.ASGITransport(app=gateway_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            resp = await client.post("/rhmt/callback", json=payload)
            assert resp.status_code == 200
            assert resp.json() == {"success": True}

    await container.aclose()
    await built_engine.dispose()
