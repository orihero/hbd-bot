"""``CheckoutUzClient`` against an ``httpx.MockTransport`` — strict parsing, never raising, no key leaks.

The parser is the security property: a reply is accepted only when it is a 2xx, says
``status == "success"``, carries real integer ids and — for ``status_payment`` — names the
order that was asked about (``DECISIONS.md D28``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from bayram.checkoutuz.client import (
    DEFAULT_LINK_LIFETIME_S,
    MAX_PAY_VIA_ENTRIES,
    CheckoutUzClient,
)
from bayram.contracts import Err, Ok
from bayram.errors import CheckoutError

_KEY = "ck_live_secret_key_123"
_BASE = "https://checkout.uz/api/v1"


class HandlerTransport(httpx.MockTransport):
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[httpx.Request] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            handler = self.handlers.get(request.url.path)
            if handler is None:
                return httpx.Response(404, json={"status": "error", "message": "not found"})
            return handler(request)

        super().__init__(_handler)


def _created(**overrides: Any) -> dict[str, Any]:
    payment: dict[str, Any] = {
        "_id": 152,
        "_uuid": "550e8400-e29b-41d4-a716-446655440000",
        "_url": "https://checkout.uz/pay/550e8400-e29b-41d4-a716-446655440000",
        "_amount": 7000,
        "_status": "pending",
        "_pay_via": {"click": "https://checkout.uz/pay/x/click"},
        "_lifteme": {"_second": 3600, "_hour": 1},
    }
    payment.update(overrides)
    return {"status": "success", "payment": payment}


def _status(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": 152,
        "amount": 7000,
        "status": "paid",
        "created_at": "2026-01-31 10:00:00",
        "paid_at": "2026-01-31 10:05:22",
    }
    data.update(overrides)
    return {"status": "success", "data": data}


@pytest.fixture
def transport() -> HandlerTransport:
    return HandlerTransport()


@pytest.fixture
def client(transport: HandlerTransport) -> CheckoutUzClient:
    return CheckoutUzClient(
        api_key=f"  {_KEY} ",
        base_url=f"{_BASE}/",
        http_client=httpx.AsyncClient(transport=transport),
    )


async def _create(client: CheckoutUzClient) -> Any:
    return await client.create_payment(
        amount_som=7000,
        description="Bayram #abcdef12",
        webhook_url="https://pay.bayrambot.uz/checkoutuz/callback/ref",
        return_url="https://t.me/BayramBot",
    )


async def test_create_payment_sends_bearer_som_and_urls_and_parses_the_reply(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(200, json=_created())

    result = await _create(client)

    assert isinstance(result, Ok)
    payment = result.value
    assert payment.order_id == 152
    assert payment.url.startswith("https://checkout.uz/pay/")
    assert payment.amount_som == 7000
    assert payment.status == "pending"
    assert payment.lifetime_s == 3600
    sent = transport.requests[0]
    assert sent.method == "POST"
    assert sent.headers["Authorization"] == f"Bearer {_KEY}"
    assert json.loads(sent.content) == {
        "amount": 7000,
        "description": "Bayram #abcdef12",
        "webhook_url": "https://pay.bayrambot.uz/checkoutuz/callback/ref",
        "return_url": "https://t.me/BayramBot",
    }


async def test_a_missing_lifetime_falls_back_to_the_documented_hour(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    body = _created()
    del body["payment"]["_lifteme"]
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(200, json=body)

    result = await _create(client)

    assert isinstance(result, Ok)
    assert result.value.lifetime_s == DEFAULT_LINK_LIFETIME_S


async def test_pay_via_is_read_in_the_vendors_order(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    pages = {
        "click": "https://checkout.uz/pay/x/click",
        "payme": "https://checkout.uz/pay/x/payme",
        "card": "https://checkout.uz/pay/x/card",
        "oson": "https://checkout.uz/pay/x/oson",
    }
    body = _created(_pay_via=pages)
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(200, json=body)

    result = await _create(client)

    assert isinstance(result, Ok)
    assert result.value.pay_via == tuple(pages.items())


@pytest.mark.parametrize("pay_via", ["absent", None, [], "https://checkout.uz/pay/x", 5])
async def test_a_missing_or_non_object_pay_via_is_empty_and_never_a_refusal(
    transport: HandlerTransport,
    client: CheckoutUzClient,
    pay_via: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = _created()
    if pay_via == "absent":
        del body["payment"]["_pay_via"]
    else:
        body["payment"]["_pay_via"] = pay_via
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(200, json=body)

    result = await _create(client)

    assert isinstance(result, Ok)
    assert result.value.pay_via == ()
    assert any(
        getattr(r, "event", None) == "checkoutuz.client.pay_via_missing" for r in caplog.records
    )


async def test_bad_pay_via_entries_are_dropped_and_logged_once(
    transport: HandlerTransport, client: CheckoutUzClient, caplog: pytest.LogCaptureFixture
) -> None:
    body = _created(
        _pay_via={
            "click": "https://checkout.uz/pay/x/click",
            "Payme": "https://checkout.uz/pay/x/payme",
            "card": "http://checkout.uz/pay/x/card",
            "plum": None,
            "a" * 33: "https://checkout.uz/pay/x/long",
            "has space": "https://checkout.uz/pay/x/space",
            "oson": "https://checkout.uz/pay/x/oson",
        }
    )
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(200, json=body)

    result = await _create(client)

    assert isinstance(result, Ok)
    assert result.value.pay_via == (
        ("click", "https://checkout.uz/pay/x/click"),
        ("oson", "https://checkout.uz/pay/x/oson"),
    )
    dropped = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "checkoutuz.client.pay_via_dropped"
    ]
    assert len(dropped) == 1
    assert getattr(dropped[0], "dropped", None) == 5


async def test_pay_via_is_capped(transport: HandlerTransport, client: CheckoutUzClient) -> None:
    pages = {f"m{i}": f"https://checkout.uz/pay/x/m{i}" for i in range(MAX_PAY_VIA_ENTRIES + 3)}
    body = _created(_pay_via=pages)
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(200, json=body)

    result = await _create(client)

    assert isinstance(result, Ok)
    assert len(result.value.pay_via) == MAX_PAY_VIA_ENTRIES
    assert result.value.pay_via[0] == ("m0", "https://checkout.uz/pay/x/m0")


@pytest.mark.parametrize(
    "override",
    [
        {"_id": "-152"},
        {"_id": " 152"},
        {"_id": True},
        {"_id": 0},
        {"_uuid": ""},
        {"_url": "http://checkout.uz/pay/x"},
        {"_amount": 7000.5},
        {"_amount": "7000.50"},
        {"_status": None},
    ],
)
async def test_create_payment_refuses_a_malformed_payment(
    transport: HandlerTransport, client: CheckoutUzClient, override: dict[str, Any]
) -> None:
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(
        200, json=_created(**override)
    )

    result = await _create(client)

    assert isinstance(result, Err)
    assert isinstance(result.error, CheckoutError)


async def test_an_integral_float_amount_is_accepted(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(
        200, json=_created(_amount=7000.0)
    )

    result = await _create(client)

    assert isinstance(result, Ok)
    assert result.value.amount_som == 7000


@pytest.mark.parametrize(
    ("code", "body", "retryable"),
    [
        (200, {"status": "error", "message": "bad amount"}, False),
        (401, {"status": "error", "message": "unauthorised"}, False),
        (500, {"status": "error"}, True),
        (200, ["not", "an", "object"], False),
    ],
)
async def test_a_refusal_is_an_err_never_an_exception(
    transport: HandlerTransport,
    client: CheckoutUzClient,
    code: int,
    body: Any,
    retryable: bool,
) -> None:
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(code, json=body)

    result = await _create(client)

    assert isinstance(result, Err)
    assert result.error.is_retryable is retryable


async def test_a_non_json_body_is_an_err(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    transport.handlers["/api/v1/status_payment"] = lambda _: httpx.Response(502, text="<html>")

    result = await client.status_payment(order_id=152)

    assert isinstance(result, Err)
    assert result.error.is_retryable is True


async def test_a_transport_failure_is_a_retryable_err(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport.handlers["/api/v1/status_payment"] = _boom

    result = await client.status_payment(order_id=152)

    assert isinstance(result, Err)
    assert result.error.is_retryable is True


async def test_status_payment_asks_by_id_and_parses_the_answer(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    transport.handlers["/api/v1/status_payment"] = lambda _: httpx.Response(200, json=_status())

    result = await client.status_payment(order_id=152)

    assert isinstance(result, Ok)
    assert result.value.order_id == 152
    assert result.value.amount_som == 7000
    assert result.value.status == "paid"
    assert result.value.paid_at == "2026-01-31 10:05:22"
    assert json.loads(transport.requests[0].content) == {"id": 152}


async def test_status_payment_refuses_an_answer_about_another_order(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    transport.handlers["/api/v1/status_payment"] = lambda _: httpx.Response(
        200, json=_status(id=153)
    )

    result = await client.status_payment(order_id=152)

    assert isinstance(result, Err)
    assert result.error.context["answered"] == 153


@pytest.mark.parametrize(
    "override",
    [
        {"id": "152x"},
        {"id": "1e3"},
        {"amount": "7000.01"},
        {"amount": "7,000"},
        {"amount": "-7000"},
        {"status": 1},
    ],
)
async def test_status_payment_refuses_a_malformed_answer(
    transport: HandlerTransport, client: CheckoutUzClient, override: dict[str, Any]
) -> None:
    transport.handlers["/api/v1/status_payment"] = lambda _: httpx.Response(
        200, json=_status(**override)
    )

    result = await client.status_payment(order_id=152)

    assert isinstance(result, Err)


async def test_status_payment_accepts_the_live_string_shape(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    # Captured from the live API on 2026-10-03: ids and amounts arrive as strings, unlike
    # the documented example. Refusing them left a paid order unsettled.
    transport.handlers["/api/v1/status_payment"] = lambda _: httpx.Response(
        200, json=_status(id="152", amount="7000.00")
    )

    result = await client.status_payment(order_id=152)

    assert isinstance(result, Ok)
    assert result.value.order_id == 152
    assert result.value.amount_som == 7000
    assert result.value.status == "paid"


async def test_create_payment_accepts_string_ids_and_amounts(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(
        200, json=_created(_id="152", _amount="7000.00")
    )

    result = await _create(client)

    assert isinstance(result, Ok)
    assert result.value.order_id == 152
    assert result.value.amount_som == 7000


async def test_the_api_key_never_reaches_an_error_or_the_repr(
    transport: HandlerTransport, client: CheckoutUzClient
) -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed sending {request.headers['Authorization']}")

    transport.handlers["/api/v1/status_payment"] = _boom
    transport.handlers["/api/v1/create_payment"] = lambda _: httpx.Response(
        401, json={"status": "error", "message": "bad key"}
    )

    failures = [await client.status_payment(order_id=152), await _create(client)]

    for failure in failures:
        assert isinstance(failure, Err)
        assert _KEY not in str(failure.error.to_log_dict())
        assert _KEY not in str(failure.error)
    assert _KEY not in repr(client)


async def test_aclose_closes_only_a_client_it_built() -> None:
    injected = httpx.AsyncClient(transport=HandlerTransport())
    await CheckoutUzClient(api_key=_KEY, http_client=injected).aclose()
    assert injected.is_closed is False
    await injected.aclose()

    owned = CheckoutUzClient(api_key=_KEY)
    await owned.aclose()
    assert owned._http.is_closed is True
