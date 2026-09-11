"""The wire, through the real ASGI stack. **Every reply is HTTP 200, without exception.**

That single sentence is what this file exists to hold. Payme reads any other status as
transport error ``-32400`` and retries it, and a 500 costs the ``id`` echo as well — so a
merchant that answers 405 to a GET, 422 to a malformed body or 500 to its own defect turns
every one of those into an unmatched retry against a payment that may already have happened.
The rule therefore has to be asserted against the framework, not against a function: a 405 is
something FastAPI produces on its own, and only a request that actually travelled through the
router can prove it does not.

The suite needs **no network, no Redis, no Postgres and no marker**. The merchant key is only
ever compared against itself, so a made-up 36-character string is a fully functional gateway;
the database is in-memory SQLite built by the container's own schema shortcut; and the queue
handle is never touched, because nothing here performs a transaction.

``raise_app_exceptions=False`` on the transport is deliberate. With the default, an exception
that escaped the gateway's own middleware would surface as a pytest error, and the assertion
``status_code == 200`` would never run. With it off, an escape becomes a 500 — which is
precisely the failure these tests are written to catch.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from arq import ArqRedis

from bayram.payme.app import PAYME_PATH, create_app
from bayram.payme.container import PaymeContainer, build_payme_container
from bayram.payme.protocol import JSONRPC_VERSION, PaymeErrorCode, RpcRequest
from bayram.payme.service import PaymeService
from bayram.payme.settings import PAYME_ENV_FILE_VAR, PaymeSettings, build_payme_settings

_MEMORY_URL: Final[str] = "sqlite+aiosqlite:///:memory:"
#: 36 characters, invented. See the module docstring.
_KEY: Final[str] = "d4f1a9c07b2e46d8ab53c1e90f7a2b6c5d3e"
_LOGIN: Final[str] = "Paycom"
_MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"

#: Payme's own documented ``Content-Type``. No framework body parser recognises it as JSON,
#: which is one of the two reasons the gateway parses the raw body itself.
_PAYME_CONTENT_TYPE: Final[str] = "text/json; charset=UTF-8"


def _basic(login: str, key: str) -> str:
    return "Basic " + base64.b64encode(f"{login}:{key}".encode()).decode()


@pytest.fixture(autouse=True)
def _no_local_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The boot credential scan reads a file that does not exist, on every machine."""
    monkeypatch.setenv(PAYME_ENV_FILE_VAR, str(tmp_path / "absent.env"))


@pytest.fixture
def settings() -> PaymeSettings:
    return build_payme_settings(
        {
            "_env_file": None,
            "database_url": _MEMORY_URL,
            "payme_enabled": True,
            "payme_merchant_id": _MERCHANT,
            "payme_merchant_key": _KEY,
            "payme_basic_login": _LOGIN,
        }
    )


@pytest.fixture
async def container(settings: PaymeSettings) -> AsyncIterator[PaymeContainer]:
    built = await build_payme_container(settings)
    yield built
    await built.aclose()


@pytest.fixture
async def client(container: PaymeContainer) -> AsyncIterator[httpx.AsyncClient]:
    """A client over the real application, with its lifespan entered.

    The lifespan runs here, in the setup phase, and not in a test body — ``configure_logging``
    strips every root handler, which would take pytest's own capture handler with it if it ran
    during the call phase and leave the ``caplog`` assertions below testing nothing.
    """
    application = create_app(container=container)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as opened:
            yield opened


async def _post(
    client: httpx.AsyncClient,
    body: bytes,
    *,
    login: str = _LOGIN,
    key: str = _KEY,
    content_type: str = "application/json",
) -> httpx.Response:
    return await client.post(
        PAYME_PATH,
        content=body,
        headers={"Authorization": _basic(login, key), "Content-Type": content_type},
    )


def _envelope(response: httpx.Response) -> dict[str, Any]:
    """Every reply is a 200 carrying a well-formed JSON-RPC envelope. Asserted every time."""
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["jsonrpc"] == JSONRPC_VERSION
    assert "id" in body
    assert ("result" in body) != ("error" in body)
    return body


# ---------------------------------------------------------------------------
# The transport rules
# ---------------------------------------------------------------------------
async def test_a_get_is_minus_32300_at_status_200_and_never_a_405(
    client: httpx.AsyncClient,
) -> None:
    """FastAPI would answer 405 on its own. That is why the route claims every method."""
    # Act
    response = await client.get(PAYME_PATH)

    # Assert
    assert _envelope(response)["error"]["code"] == PaymeErrorCode.TRANSPORT


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
async def test_no_other_verb_reaches_the_dispatcher_either(
    client: httpx.AsyncClient, method: str
) -> None:
    # Act
    response = await client.request(method.upper(), PAYME_PATH)

    # Assert
    assert _envelope(response)["error"]["code"] == PaymeErrorCode.TRANSPORT


async def test_a_body_that_is_not_json_is_minus_32700_at_status_200(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await _post(client, b"{not json at all")

    # Assert
    body = _envelope(response)
    assert body["error"]["code"] == PaymeErrorCode.PARSE
    assert body["id"] is None


async def test_a_body_with_no_method_is_minus_32600_and_still_echoes_the_id(
    client: httpx.AsyncClient,
) -> None:
    """The envelope failed, but the id did not — losing it turns their retry into an orphan."""
    # Act
    response = await _post(client, b'{"params": {}, "id": 4242}')

    # Assert
    body = _envelope(response)
    assert body["error"]["code"] == PaymeErrorCode.ENVELOPE
    assert body["id"] == 4242


async def test_an_unknown_method_is_minus_32601_carrying_the_name_in_data(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await _post(client, b'{"method": "MakeMeRich", "params": {}, "id": 9}')

    # Assert
    error = _envelope(response)["error"]
    assert error["code"] == PaymeErrorCode.METHOD_NOT_FOUND
    assert error["data"] == "MakeMeRich"


async def test_the_request_id_is_echoed_verbatim(client: httpx.AsyncClient) -> None:
    # Act
    response = await _post(
        client, b'{"method": "CheckTransaction", "params": {"id": "x"}, "id": 987654321}'
    )

    # Assert
    assert _envelope(response)["id"] == 987654321


@pytest.mark.parametrize(
    "body",
    [
        b'{"method": "CheckTransaction", "params": {"id": "x"}, "id": 1}',
        b'{"jsonrpc": "2.0", "method": "CheckTransaction", "params": {"id": "x"}, "id": 1}',
    ],
    ids=["without-jsonrpc", "with-jsonrpc"],
)
async def test_a_jsonrpc_member_is_accepted_present_or_absent(
    client: httpx.AsyncClient, body: bytes
) -> None:
    """Every documented request example omits it; their sandbox sends it. Both must parse."""
    # Act
    response = await _post(client, body)

    # Assert — a real refusal from the ledger, not an envelope complaint.
    assert _envelope(response)["error"]["code"] == PaymeErrorCode.TRANSACTION_NOT_FOUND


async def test_paymes_own_content_type_parses(client: httpx.AsyncClient) -> None:
    """``text/json; charset=UTF-8`` is what the documentation says they send."""
    # Act
    response = await _post(
        client,
        b'{"method": "CheckTransaction", "params": {"id": "x"}, "id": 2}',
        content_type=_PAYME_CONTENT_TYPE,
    )

    # Assert
    assert _envelope(response)["error"]["code"] == PaymeErrorCode.TRANSACTION_NOT_FOUND


# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------
async def test_the_right_pair_gets_through(client: httpx.AsyncClient) -> None:
    # Act
    response = await _post(client, b'{"method": "GetStatement", "params": {"from": 0, "to": 1}, "id": 3}')

    # Assert
    assert _envelope(response)["result"] == {"transactions": []}


async def test_the_right_key_with_the_wrong_login_is_refused(client: httpx.AsyncClient) -> None:
    """The PayTechUz weakening, pinned as a regression test.

    That widely installed package splits the decoded credential on ``:`` and compares only the
    trailing half, which accepts any username at all. The whole pair is compared here.
    """
    # Act
    response = await _post(client, b'{"method": "GetStatement", "params": {}, "id": 3}', login="admin")

    # Assert
    assert _envelope(response)["error"]["code"] == PaymeErrorCode.UNAUTHORISED


async def test_a_missing_authorization_header_is_minus_32504_at_status_200(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.post(PAYME_PATH, content=b'{"method": "GetStatement", "params": {}, "id": 1}')

    # Assert
    assert _envelope(response)["error"]["code"] == PaymeErrorCode.UNAUTHORISED


async def test_the_refusal_log_line_records_the_login_and_never_the_key(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The undocumented username is learned from the first sandbox call, not a support ticket.

    The key must appear in no record at all — not in the message, not in an extra, not in a
    formatted argument. These logs have no retention clock and this is the one secret on the
    host.
    """
    # Arrange
    caplog.set_level(logging.WARNING)

    # Act
    await _post(client, b'{"method": "GetStatement", "params": {}, "id": 1}', login="paycom-uz")

    # Assert
    refusals = [
        record for record in caplog.records if getattr(record, "event", "") == "payme.auth.refused"
    ]
    assert len(refusals) == 1
    assert refusals[0].__dict__["presented_login"] == "paycom-uz"
    for record in caplog.records:
        assert _KEY not in str(record.__dict__)


async def test_a_malformed_authorization_header_is_refused_without_raising(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.post(
        PAYME_PATH,
        content=b'{"method": "GetStatement", "params": {}, "id": 1}',
        headers={"Authorization": "Basic not-base64!!"},
    )

    # Assert
    assert _envelope(response)["error"]["code"] == PaymeErrorCode.UNAUTHORISED


# ---------------------------------------------------------------------------
# The middleware: a defect of ours is still a 200
# ---------------------------------------------------------------------------
async def test_an_exception_inside_a_handler_renders_minus_32400_at_status_200(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule the gateway's own middleware exists for, proved by breaking the dispatcher.

    Without it FastAPI answers 500 through ``ServerErrorMiddleware``, Payme reads that as
    ``-32400``, retries — and the retry cannot be matched to the original, because the id echo
    went with the exception.
    """

    # Arrange
    async def _explode(
        self: PaymeService, request: RpcRequest, *, peer_ip: str | None
    ) -> tuple[dict[str, object], int]:
        raise RuntimeError("a deliberate defect on the money path")

    monkeypatch.setattr(PaymeService, "dispatch", _explode)

    # Act
    response = await _post(client, b'{"method": "CheckTransaction", "params": {"id": "x"}, "id": 8}')

    # Assert
    body = _envelope(response)
    assert body["error"]["code"] == PaymeErrorCode.INTERNAL
    assert body["id"] is None


async def test_the_envelope_never_carries_both_a_result_and_an_error(
    client: httpx.AsyncClient,
) -> None:
    """Asserted on every reply by ``_envelope``; stated once here so the rule has a name."""
    # Act
    ok_reply = _envelope(
        await _post(client, b'{"method": "GetStatement", "params": {"from": 0, "to": 1}, "id": 1}')
    )
    error_reply = _envelope(await _post(client, b"garbage"))

    # Assert
    assert "result" in ok_reply and "error" not in ok_reply
    assert "error" in error_reply and "result" not in error_reply


# ---------------------------------------------------------------------------
# The other two routes
# ---------------------------------------------------------------------------
async def test_healthz_is_a_bare_200_that_touches_nothing(client: httpx.AsyncClient) -> None:
    """Liveness must not depend on Postgres: a probe that does turns a blip into a restart loop."""
    # Act
    response = await client.get("/healthz")

    # Assert
    assert response.status_code == 200
    assert response.content == b""


async def test_readyz_tells_an_unauthenticated_caller_a_constant_word(
    client: httpx.AsyncClient,
) -> None:
    """"degraded" is the same fleet telemetry as ``{"database": false}`` with fewer characters."""
    # Act
    response = await client.get("/readyz")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_details_need_the_probe_token(container: PaymeContainer) -> None:
    """A token that matches under ``compare_digest`` — an empty setting authorises nobody."""
    # Arrange
    settings = build_payme_settings(
        {
            "_env_file": None,
            "database_url": _MEMORY_URL,
            "payme_enabled": True,
            "payme_merchant_key": _KEY,
            "payme_probe_token": "a-monitor-token",
        }
    )
    application = create_app(container=_with(container, settings))
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as probe:
            # Act
            refused = await probe.get("/readyz", headers={"X-Probe-Token": "wrong"})
            allowed = await probe.get("/readyz", headers={"X-Probe-Token": "a-monitor-token"})

    # Assert
    assert refused.json() == {"status": "ok"}
    assert allowed.json()["database"] is True
    assert "isSandbox" in allowed.json()


def _with(container: PaymeContainer, settings: PaymeSettings) -> PaymeContainer:
    """The same container under different settings, reusing its engine.

    ``dataclasses.replace`` rather than a second ``build_payme_container``: the engine is an
    in-memory SQLite database behind one connection, and building a second one would give the
    probe an empty schema to report on.
    """
    return replace(container, settings=settings)


# ---------------------------------------------------------------------------
# Caller identification — off in every shipped configuration, and tested anyway
# ---------------------------------------------------------------------------
def _behind_a_proxy(container: PaymeContainer) -> PaymeContainer:
    """The same container, configured as if one trusted proxy sat in front of it.

    Both halves are needed to switch the filter on: a CIDR list alone does nothing, because
    with no declared hop the address it would match is the terminator's rather than the
    caller's — which is the whole reason the allowlist belongs at the terminator.
    """
    return _with(
        container,
        build_payme_settings(
            {
                "_env_file": None,
                "database_url": _MEMORY_URL,
                "payme_enabled": True,
                "payme_merchant_key": _KEY,
                "payme_trusted_proxy_hops": 1,
                "payme_allowed_cidrs": "185.234.113.0/28",
            }
        ),
    )


@pytest.mark.parametrize(
    ("forwarded", "expected"),
    [
        ("185.234.113.5", None),
        ("185.234.113.5:41234", None),
        ("203.0.113.9", PaymeErrorCode.UNAUTHORISED),
        (None, PaymeErrorCode.UNAUTHORISED),
    ],
    ids=["payme-range", "payme-range-with-port", "somebody-else", "no-header-so-the-peer"],
)
async def test_a_configured_allowlist_refuses_a_caller_outside_it(
    container: PaymeContainer, forwarded: str | None, expected: int | None
) -> None:
    """Refused at HTTP 200 like everything else, and the peer is journalled either way."""
    # Arrange
    application = create_app(container=_behind_a_proxy(container))
    headers = {"Authorization": _basic(_LOGIN, _KEY)}
    if forwarded is not None:
        headers["X-Forwarded-For"] = forwarded

    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as proxied:
            # Act
            response = await proxied.post(
                PAYME_PATH,
                content=b'{"method": "GetStatement", "params": {"from": 0, "to": 1}, "id": 1}',
                headers=headers,
            )

    # Assert
    body = _envelope(response)
    if expected is None:
        assert body["result"] == {"transactions": []}
    else:
        assert body["error"]["code"] == expected


async def test_the_shipped_configuration_consults_no_allowlist_at_all(
    client: httpx.AsyncClient,
) -> None:
    """Zero hops and no CIDRs: the filter is not merely empty, it is never reached."""
    # Act
    response = await _post(
        client,
        b'{"method": "GetStatement", "params": {"from": 0, "to": 1}, "id": 1}',
        # A header an attacker would set. With no declared hop it is not read at all.
    )

    # Assert
    assert _envelope(response)["result"] == {"transactions": []}


async def test_readyz_reports_degraded_rather_than_raising_when_redis_is_down(
    container: PaymeContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe that crashes its caller reports nothing at all."""

    # Arrange
    async def _refuse(self: ArqRedis, *args: object, **kwargs: object) -> bool:
        raise ConnectionError("no redis here")

    monkeypatch.setattr(ArqRedis, "ping", _refuse)
    settings = build_payme_settings(
        {
            "_env_file": None,
            "database_url": _MEMORY_URL,
            "payme_enabled": True,
            "payme_merchant_key": _KEY,
            "payme_probe_token": "a-monitor-token",
        }
    )
    application = create_app(container=_with(container, settings))

    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as probe:
            # Act
            response = await probe.get("/readyz", headers={"X-Probe-Token": "a-monitor-token"})

    # Assert
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["redis"] is False


# ---------------------------------------------------------------------------
# The parameter mapping table, pinned
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "params", "expected"),
    [
        ("CheckPerformTransaction", {"account": {"order_id": "x"}}, PaymeErrorCode.WRONG_AMOUNT),
        (
            "CheckPerformTransaction",
            {"amount": True, "account": {"order_id": "x"}},
            PaymeErrorCode.WRONG_AMOUNT,
        ),
        ("CheckPerformTransaction", {"amount": 700000}, PaymeErrorCode.ACCOUNT_UNKNOWN),
        (
            "CheckPerformTransaction",
            {"amount": 700000, "account": "not-an-object"},
            PaymeErrorCode.ACCOUNT_UNKNOWN,
        ),
        ("CreateTransaction", {"amount": 1, "time": 1}, PaymeErrorCode.TRANSACTION_NOT_FOUND),
        (
            "CreateTransaction",
            {"id": "a" * 24, "amount": 1, "account": {"order_id": "x"}},
            PaymeErrorCode.ENVELOPE,
        ),
        ("PerformTransaction", {}, PaymeErrorCode.TRANSACTION_NOT_FOUND),
        ("CancelTransaction", {"reason": 1}, PaymeErrorCode.TRANSACTION_NOT_FOUND),
        ("CheckTransaction", {"id": ""}, PaymeErrorCode.TRANSACTION_NOT_FOUND),
        ("GetStatement", {"to": 1}, PaymeErrorCode.ENVELOPE),
        ("GetStatement", {"from": 0, "to": "yesterday"}, PaymeErrorCode.ENVELOPE),
    ],
)
async def test_malformed_parameters_map_to_business_codes_and_not_to_a_422(
    client: httpx.AsyncClient, method: str, params: dict[str, Any], expected: int
) -> None:
    """The table in :mod:`bayram.payme.service`'s docstring, asserted rather than described.

    ``"amount": true`` is on the list for a specific Python trap: ``isinstance(True, int)`` is
    ``True``, so a body carrying a boolean amount would otherwise be read as one tiyin.
    """
    # Act
    response = await client.post(
        PAYME_PATH,
        json={"method": method, "params": params, "id": 1},
        headers={"Authorization": _basic(_LOGIN, _KEY)},
    )

    # Assert
    assert _envelope(response)["error"]["code"] == expected
