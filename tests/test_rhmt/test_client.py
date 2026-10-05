"""Tests for RhmtClient HTTP client and authentication."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from bayram.contracts import Err, Ok
from bayram.errors import PaymentError
from bayram.rhmt.client import RhmtClient, RhmtInvoice, _checkout_lang


class HandlerTransport(httpx.MockTransport):
    def __init__(self) -> None:
        self.handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            key = (request.method, request.url.path)
            if key in self.handlers:
                return self.handlers[key](request)
            return httpx.Response(404, json={"error": "not found"})

        super().__init__(_handler)


@pytest.fixture
def mock_transport() -> HandlerTransport:
    return HandlerTransport()


async def test_auth_success_and_caching(mock_transport: HandlerTransport) -> None:
    auth_calls = 0

    def handle_auth(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        auth_calls += 1
        data = json.loads(request.content)
        assert data["application_id"] == "app_123"
        assert data["secret"] == "sec_456"
        return httpx.Response(
            200,
            json={
                "token": "token_abc_123",
                "expiry": "2030-01-01 12:00:00",
            },
        )

    mock_transport.handlers[("POST", "/auth")] = handle_auth

    http_client = httpx.AsyncClient(transport=mock_transport)
    client = RhmtClient(
        application_id="app_123",
        secret="sec_456",
        base_url="https://mesh.multicard.uz",
        http_client=http_client,
    )

    # First call: hits /auth
    res1 = await client.authenticate()
    assert isinstance(res1, Ok)
    assert res1.value == "token_abc_123"
    assert auth_calls == 1

    # Second call: cached, does not hit /auth
    res2 = await client.authenticate()
    assert isinstance(res2, Ok)
    assert res2.value == "token_abc_123"
    assert auth_calls == 1

    # Force refresh: hits /auth again
    res3 = await client.authenticate(force_refresh=True)
    assert isinstance(res3, Ok)
    assert auth_calls == 2

    await client.aclose()


async def test_auth_non_200_failure(mock_transport: HandlerTransport) -> None:
    def handle_auth(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    mock_transport.handlers[("POST", "/auth")] = handle_auth

    http_client = httpx.AsyncClient(transport=mock_transport)
    client = RhmtClient(
        application_id="app_123",
        secret="wrong_secret",
        http_client=http_client,
    )

    res = await client.authenticate()
    assert isinstance(res, Err)
    assert isinstance(res.error, PaymentError)
    assert "status 401" in str(res.error)


async def test_auth_missing_token_in_body(mock_transport: HandlerTransport) -> None:
    def handle_auth(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True})

    mock_transport.handlers[("POST", "/auth")] = handle_auth

    http_client = httpx.AsyncClient(transport=mock_transport)
    client = RhmtClient(application_id="app_123", secret="sec_456", http_client=http_client)

    res = await client.authenticate()
    assert isinstance(res, Err)
    assert "no token" in str(res.error)


async def test_create_invoice_success(mock_transport: HandlerTransport) -> None:
    mock_transport.handlers[("POST", "/auth")] = lambda req: httpx.Response(
        200, json={"token": "tok_xyz", "expiry": "2030-01-01 00:00:00"}
    )

    def handle_invoice(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer tok_xyz"
        assert request.headers.get("X-Access-Token") == "tok_xyz"
        payload = json.loads(request.content)
        assert payload["store_id"] == 1234
        assert payload["amount"] == 700000
        assert payload["invoice_id"] == "inv_test_1"
        assert payload["callback_url"] == "https://pay.bayrambot.uz/rhmt/callback"
        assert payload["return_url"] == "https://t.me/BayramBot"
        assert payload["lang"] == "uz"
        assert payload["ttl"] == 43_200

        return httpx.Response(
            200,
            json={
                "data": {
                    "uuid": "uuid-1111-2222",
                    "checkout_url": "https://app.rhmt.uz/uuid-1111-2222",
                    "amount": 700000,
                    "invoice_id": "inv_test_1",
                    "status": "created",
                }
            },
        )

    mock_transport.handlers[("POST", "/payment/invoice")] = handle_invoice

    http_client = httpx.AsyncClient(transport=mock_transport)
    client = RhmtClient(application_id="app_123", secret="sec_456", http_client=http_client)

    invoice_res = await client.create_invoice(
        store_id=1234,
        amount_minor=700000,
        invoice_id="inv_test_1",
        callback_url="https://pay.bayrambot.uz/rhmt/callback",
        return_url="https://t.me/BayramBot",
        language="uz",
        ttl_s=43_200,
    )

    assert isinstance(invoice_res, Ok)
    inv = invoice_res.value
    assert isinstance(inv, RhmtInvoice)
    assert inv.uuid == "uuid-1111-2222"
    assert inv.checkout_url == "https://app.rhmt.uz/uuid-1111-2222"
    assert inv.amount_minor == 700000
    assert inv.invoice_id == "inv_test_1"


async def test_create_invoice_401_recovery(mock_transport: HandlerTransport) -> None:
    auth_tokens = ["old_expired_token", "fresh_new_token"]
    auth_call_count = 0

    def handle_auth(request: httpx.Request) -> httpx.Response:
        nonlocal auth_call_count
        token = auth_tokens[min(auth_call_count, len(auth_tokens) - 1)]
        auth_call_count += 1
        return httpx.Response(200, json={"token": token, "expiry": "2030-01-01 00:00:00"})

    invoice_call_count = 0

    def handle_invoice(request: httpx.Request) -> httpx.Response:
        nonlocal invoice_call_count
        invoice_call_count += 1
        token = request.headers.get("X-Access-Token")
        if token == "old_expired_token":
            return httpx.Response(401, json={"error": "token expired"})
        return httpx.Response(
            200,
            json={
                "data": {
                    "uuid": "uuid-retry-ok",
                    "checkout_url": "https://app.rhmt.uz/uuid-retry-ok",
                }
            },
        )

    mock_transport.handlers[("POST", "/auth")] = handle_auth
    mock_transport.handlers[("POST", "/payment/invoice")] = handle_invoice

    http_client = httpx.AsyncClient(transport=mock_transport)
    client = RhmtClient(application_id="app_123", secret="sec_456", http_client=http_client)

    invoice_res = await client.create_invoice(
        store_id=1234,
        amount_minor=700000,
        invoice_id="inv_retry",
        callback_url="https://pay.bayrambot.uz/rhmt/callback",
        return_url="https://t.me/BayramBot",
    )

    assert isinstance(invoice_res, Ok)
    assert invoice_res.value.uuid == "uuid-retry-ok"
    assert auth_call_count == 2
    assert invoice_call_count == 2


async def test_create_invoice_error_envelope(mock_transport: HandlerTransport) -> None:
    mock_transport.handlers[("POST", "/auth")] = lambda req: httpx.Response(
        200, json={"token": "tok_ok", "expiry": "2030-01-01 00:00:00"}
    )
    mock_transport.handlers[("POST", "/payment/invoice")] = lambda req: httpx.Response(
        400,
        json={
            "success": False,
            "error": {"details": "Store not found or disabled"},
        },
    )

    http_client = httpx.AsyncClient(transport=mock_transport)
    client = RhmtClient(application_id="app_123", secret="sec_456", http_client=http_client)

    res = await client.create_invoice(
        store_id=9999,
        amount_minor=700000,
        invoice_id="inv_err",
        callback_url="https://pay.bayrambot.uz/rhmt/callback",
        return_url="https://t.me/BayramBot",
    )
    assert isinstance(res, Err)
    assert "Store not found" in str(res.error)


async def test_get_payment(mock_transport: HandlerTransport) -> None:
    mock_transport.handlers[("POST", "/auth")] = lambda req: httpx.Response(
        200, json={"token": "tok_ok", "expiry": "2030-01-01 00:00:00"}
    )
    mock_transport.handlers[("GET", "/payment/uuid-test-123")] = lambda req: httpx.Response(
        200, json={"status": "success", "amount": 700000}
    )

    http_client = httpx.AsyncClient(transport=mock_transport)
    client = RhmtClient(application_id="app_123", secret="sec_456", http_client=http_client)

    res = await client.get_payment("uuid-test-123")
    assert isinstance(res, Ok)
    assert res.value["status"] == "success"


def test_the_checkout_page_language_follows_the_customer() -> None:
    assert _checkout_lang("ru") == "ru"
    assert _checkout_lang("en") == "en"
    assert _checkout_lang("uz_latn") == "uz"
    assert _checkout_lang("uz_cyrl") == "uz"
