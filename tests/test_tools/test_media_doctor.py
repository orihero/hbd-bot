"""``python -m bayram.tools.media doctor`` against a fake gateway (IMAGE_VIDEO_SPEC §9.1 item 4).

No socket is opened: the gateway is an ``httpx.MockTransport``, and the contract diff is fed
a hand-written ``/openapi.json`` shaped like the live one. The live contract smoke is the CLI
run by hand (``make gateway-contract``) and is never part of ``pytest``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import orjson
import pytest

from bayram.config import Settings
from bayram.providers.media.local_gateway import (
    ACCESS_CLIENT_ID_HEADER,
    ACCESS_CLIENT_SECRET_HEADER,
    API_KEY_HEADER,
    GENERATE_PAYLOAD_KEYS,
)
from bayram.tools.media import EXIT_REFUSED, main, plan
from bayram.tools.media_doctor import (
    Check,
    CheckStatus,
    DoctorReport,
    config_checks,
    contract_checks,
    run_doctor,
)

BASE_URL = "https://genai.example.test"
API_KEY = "test-gateway-key-not-real"
CLIENT_ID = "test-access-id.access"
CLIENT_SECRET = "test-access-secret-not-real"

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def gateway_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "genai_base_url": BASE_URL,
            "genai_api_key": API_KEY,
            "genai_access_client_id": CLIENT_ID,
            "genai_access_client_secret": CLIENT_SECRET,
        }
    )


def _gateway(
    *,
    models: list[str] | None = None,
    keyless_status: int = 401,
    guard_status: int = 404,
    health_status: int = 200,
    openapi: dict[str, Any] | None = None,
) -> tuple[Handler, list[httpx.Request]]:
    served = ["flux2", "wan", "zootopia"] if models is None else models
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/health":
            return httpx.Response(health_status, json={"status": "ok"})
        if path == "/v1/models":
            if request.headers.get(API_KEY_HEADER) != API_KEY:
                return httpx.Response(keyless_status, json={"detail": "no key"})
            return httpx.Response(200, json={"object": "list", "data": [{"id": m} for m in served]})
        if path == "/v1/moderate/health":
            return httpx.Response(guard_status, json={})
        if path == "/openapi.json" and openapi is not None:
            return httpx.Response(200, content=orjson.dumps(openapi))
        return httpx.Response(404, json={"detail": "Not Found"})

    return handler, seen


async def _doctor(settings: Settings, handler: Handler, *, contract: bool = False) -> DoctorReport:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await run_doctor(settings, contract=contract, client=client)


def _status(report: DoctorReport, name: str) -> CheckStatus:
    return next(check.status for check in report.checks if check.name == name)


def _param(name: str, where: str) -> dict[str, Any]:
    return {"name": name, "in": where, "required": False, "schema": {"type": "string"}}


def _openapi(
    *,
    query_key: bool = False,
    additional: bool = True,
    extra_props: tuple[str, ...] = (),
    with_delete: bool = False,
) -> dict[str, Any]:
    """Shaped like the live gateway's export: ``GenReq`` without ``length``/``client``."""
    params = [_param("x-api-key", "header"), *([_param("api_key", "query")] if query_key else [])]
    op: dict[str, Any] = {"parameters": params, "responses": {}}
    body = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/GenReq"}}}}
    props = ["type", "model", "prompt", "width", "height", "steps", "seed", "frames", "fps"]
    props += ["image", "denoise", *extra_props]
    result: dict[str, Any] = {"get": op}
    if with_delete:
        result["delete"] = op
    return {
        "paths": {
            "/generate": {"post": {**op, "requestBody": body}},
            "/jobs/{job_id}": {"get": op},
            "/result/{job_id}": result,
            "/queue": {"get": op},
            "/health": {"get": {"responses": {}}},
            "/v1/models": {"get": op},
        },
        "components": {
            "schemas": {
                "GenReq": {
                    "properties": {p: {} for p in props},
                    "additionalProperties": additional,
                }
            }
        },
    }


# -- the verb ---------------------------------------------------------------


def test_doctor_parses_and_rejects_stray_arguments() -> None:
    assert plan(["doctor"]).contract is False
    assert plan(["doctor", "--contract"]).contract is True
    assert main(["doctor", "--frobnicate"]) == EXIT_REFUSED


# -- config -----------------------------------------------------------------


def test_a_well_configured_gateway_has_no_config_failure(gateway_settings: Settings) -> None:
    assert all(c.status is CheckStatus.OK for c in config_checks(gateway_settings))


@pytest.mark.parametrize(
    ("update", "name"),
    [
        ({"genai_base_url": "http://203.0.113.7:5174"}, "base url"),
        ({"genai_base_url": f"{BASE_URL}/?api_key=leak"}, "key in url"),
        ({"genai_api_key": ""}, "api key"),
        ({"genai_image_model": "zootopia"}, "image model"),
        ({"genai_video_model": "flux2"}, "video model"),
        ({"genai_access_client_secret": ""}, "access token"),
    ],
)
async def test_a_config_failure_contacts_nobody(
    gateway_settings: Settings, update: dict[str, str], name: str
) -> None:
    handler, seen = _gateway()
    report = await _doctor(gateway_settings.model_copy(update=update), handler)

    assert _status(report, name) is CheckStatus.FAIL
    assert not report.is_green
    assert seen == []


async def test_no_access_token_is_a_warning_not_a_failure(gateway_settings: Settings) -> None:
    bare = gateway_settings.model_copy(
        update={"genai_access_client_id": "", "genai_access_client_secret": ""}
    )
    handler, seen = _gateway()
    report = await _doctor(bare, handler)

    assert _status(report, "access token") is CheckStatus.WARN
    assert report.is_green
    assert all(ACCESS_CLIENT_ID_HEADER not in r.headers for r in seen)


async def test_an_unconfigured_gateway_nothing_uses_is_skipped(settings: Settings) -> None:
    handler, seen = _gateway()
    report = await _doctor(settings.model_copy(update={"genai_base_url": ""}), handler)

    assert [c.status for c in report.checks] == [CheckStatus.SKIP]
    assert report.is_green
    assert seen == []


async def test_an_offered_local_sku_without_a_gateway_is_red(settings: Settings) -> None:
    offered = settings.model_copy(
        update={"genai_base_url": "", "is_image_offered": True, "image_backend": "local"}
    )
    handler, _ = _gateway()
    assert not (await _doctor(offered, handler)).is_green


# -- live -------------------------------------------------------------------


async def test_a_hardened_gateway_is_green(gateway_settings: Settings) -> None:
    handler, seen = _gateway()
    report = await _doctor(gateway_settings, handler)

    assert report.is_green, report.render()
    for name in ("reachable", "auth", "models", "keyless refused"):
        assert _status(report, name) is CheckStatus.OK
    assert _status(report, "G4 guards") is CheckStatus.WARN
    assert "1 model(s) we never select" in report.render()
    assert "doctor: green" in report.render()


async def test_the_key_rides_in_a_header_and_never_in_a_url(gateway_settings: Settings) -> None:
    handler, seen = _gateway(openapi=_openapi())
    report = await _doctor(gateway_settings, handler, contract=True)

    assert seen
    for request in seen:
        assert API_KEY not in str(request.url)
        assert "api_key" not in str(request.url)
        assert request.headers[ACCESS_CLIENT_ID_HEADER] == CLIENT_ID
        assert request.headers[ACCESS_CLIENT_SECRET_HEADER] == CLIENT_SECRET
    assert API_KEY not in report.render()
    assert CLIENT_SECRET not in report.render()


async def test_a_gateway_that_serves_without_a_key_is_red(gateway_settings: Settings) -> None:
    handler, _ = _gateway(keyless_status=200)
    report = await _doctor(gateway_settings, handler)

    assert _status(report, "keyless refused") is CheckStatus.FAIL
    assert not report.is_green


async def test_a_missing_model_is_red(gateway_settings: Settings) -> None:
    handler, _ = _gateway(models=["flux2", "zootopia"])
    report = await _doctor(gateway_settings, handler)

    assert _status(report, "models") is CheckStatus.FAIL


async def test_an_access_redirect_names_the_service_token(gateway_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://team.example/cdn-cgi/access"})

    report = await _doctor(gateway_settings, handler)

    assert _status(report, "reachable") is CheckStatus.FAIL
    assert "ACCESS_CLIENT_ID" in report.render()
    assert report.checks[-1].status is CheckStatus.SKIP


async def test_an_unreachable_gateway_is_red_and_stops(gateway_settings: Settings) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    report = await _doctor(gateway_settings, handler)

    assert _status(report, "reachable") is CheckStatus.FAIL
    assert "ConnectError" in report.render()
    assert len(calls) == 1


async def test_installed_guards_are_green(gateway_settings: Settings) -> None:
    handler, _ = _gateway(guard_status=200)
    assert _status(await _doctor(gateway_settings, handler), "G4 guards") is CheckStatus.OK


# -- contract ---------------------------------------------------------------


def _by_name(checks: list[Check]) -> dict[str, CheckStatus]:
    return {check.name: check.status for check in checks}


def test_todays_gateway_shape_warns_on_undeclared_keys() -> None:
    statuses = _by_name(contract_checks(_openapi()))

    assert statuses["contract routes"] is CheckStatus.OK
    assert statuses["contract body"] is CheckStatus.WARN
    assert statuses["header-only auth"] is CheckStatus.OK
    assert statuses["G5 priority"] is CheckStatus.WARN
    assert statuses["G6 delete"] is CheckStatus.WARN


def test_a_query_string_key_fails_the_contract() -> None:
    checks = contract_checks(_openapi(query_key=True))
    assert _by_name(checks)["header-only auth"] is CheckStatus.FAIL


def test_a_closed_schema_that_lacks_our_keys_fails_the_contract() -> None:
    checks = contract_checks(_openapi(additional=False))
    detail = next(c.detail for c in checks if c.name == "contract body")

    assert _by_name(checks)["contract body"] is CheckStatus.FAIL
    assert "length" in detail


def test_a_fully_declared_hardened_gateway_passes_the_contract() -> None:
    doc = _openapi(additional=False, extra_props=("length", "client", "priority"), with_delete=True)
    assert all(c.status is CheckStatus.OK for c in contract_checks(doc))


def test_a_missing_route_fails_the_contract() -> None:
    doc = _openapi()
    del doc["paths"]["/queue"]
    assert _by_name(contract_checks(doc))["contract routes"] is CheckStatus.FAIL


def test_the_payload_keys_cover_what_the_builder_can_write() -> None:
    # The contract diff is only as good as this set; the builder test pins it from the other side.
    assert {"length", "fps", "client", "denoise", "image", "model"} <= GENERATE_PAYLOAD_KEYS
    assert "frames" not in GENERATE_PAYLOAD_KEYS


async def test_contract_mode_reads_the_live_schema(gateway_settings: Settings) -> None:
    handler, seen = _gateway(openapi=_openapi(query_key=True))
    report = await _doctor(gateway_settings, handler, contract=True)

    assert any(r.url.path == "/openapi.json" for r in seen)
    assert _status(report, "header-only auth") is CheckStatus.FAIL
    assert not report.is_green
