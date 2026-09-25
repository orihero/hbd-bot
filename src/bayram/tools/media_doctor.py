"""``python -m bayram.tools.media doctor`` — is the local gateway fit to take a customer's photo?

IMAGE_VIDEO_SPEC §9.1 item 4: run from the production host, at install and after every
release, it reads the settings the bot and worker boot with and asks the gateway, through the
tunnel, the questions whose wrong answer would otherwise surface as a failed paid render:

* **config** — a base URL on HTTPS with no key in it, a key, allowlisted models, and the
  Cloudflare Access service token as both halves or neither (§9.1 items 2–3);
* **reachable** — ``GET /health`` answers 200 through the tunnel;
* **auth** — ``GET /v1/models`` answers 200 with the key in its header, and is REFUSED without
  it (a gateway that serves anyone is a public GPU with our customers' photos on it);
* **models** — the configured ``flux2``/``wan`` are installed; anything else the gateway serves
  (``zootopia``…) is named, and is unreachable from us by ``LOCAL_MODEL_ALLOWLIST``;
* **guards** — G4 ``GET /v1/moderate/health`` (§6.5): a warning until M3, not a failure.

``--contract`` adds the smoke the spec calls ``make gateway-contract`` (§4.2): it fetches the
live ``/openapi.json`` and diffs it against what the adapter sends. It needs the network, so
it runs by hand and never in ``pytest``; the diff itself (:func:`contract_checks`) is pure and
is what the unit tests exercise.

The key never goes into a URL — not even to prove the gateway still accepts ``?api_key=``; the
contract check reads that from the schema instead. Nothing printed carries a key or a body.

Exit codes (``bayram.tools.media``): ``0`` no check failed (warnings allowed), ``2`` the
settings could not be loaded, ``3`` at least one check failed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

import httpx
import orjson

from bayram.config import Settings
from bayram.db.enums import MediaBackend
from bayram.media.offering import env_backend, offered_skus
from bayram.providers.media.local_gateway import (
    API_KEY_HEADER,
    GENERATE_PAYLOAD_KEYS,
    LOCAL_MODEL_ALLOWLIST,
    MODEL_KINDS,
    access_headers,
)

__all__ = [
    "Check",
    "CheckStatus",
    "DoctorReport",
    "config_checks",
    "contract_checks",
    "run_doctor",
]

HEALTH_PATH: Final[str] = "/health"
MODELS_PATH: Final[str] = "/v1/models"
GUARD_HEALTH_PATH: Final[str] = "/v1/moderate/health"
OPENAPI_PATH: Final[str] = "/openapi.json"

#: Every route the adapter calls, with its method. A missing one is a failed contract.
REQUIRED_OPERATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("post", "/generate"),
    ("get", "/jobs/{job_id}"),
    ("get", "/result/{job_id}"),
    ("get", "/queue"),
    ("get", HEALTH_PATH),
    ("get", MODELS_PATH),
)
#: G6 (§6.5): until it exists the box's sweeper (§9.2) is the only control on kept inputs.
G6_OPERATION: Final[tuple[str, str]] = ("delete", "/result/{job_id}")

DEFAULT_TIMEOUT_S: Final[float] = 15.0
_HTTP_OK: Final[int] = 200
_HTTP_NOT_FOUND: Final[int] = 404
_AUTH_STATUSES: Final[frozenset[int]] = frozenset({401, 403})
_LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})


class CheckStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[Check, ...]

    @property
    def is_green(self) -> bool:
        return all(check.status is not CheckStatus.FAIL for check in self.checks)

    def render(self) -> str:
        lines = [f"[{c.status.value:>4}] {c.name}: {c.detail}" for c in self.checks]
        verdict = "green" if self.is_green else "RED"
        lines.append(f"doctor: {verdict} ({summarise(self.checks)})")
        return "\n".join(lines)


def _ok(name: str, detail: str) -> Check:
    return Check(name, CheckStatus.OK, detail)


def _warn(name: str, detail: str) -> Check:
    return Check(name, CheckStatus.WARN, detail)


def _fail(name: str, detail: str) -> Check:
    return Check(name, CheckStatus.FAIL, detail)


def _skip(name: str, detail: str) -> Check:
    return Check(name, CheckStatus.SKIP, detail)


def _uses_the_gateway(settings: Settings) -> bool:
    """An offered SKU routed to ``local`` needs the gateway; nothing else does today."""
    return any(env_backend(settings, sku) is MediaBackend.LOCAL for sku in offered_skus(settings))


def config_checks(settings: Settings) -> list[Check]:
    """What the settings alone say. Pure; no IO."""
    checks: list[Check] = []
    base_url = settings.genai_base_url.strip()
    parts = urlsplit(base_url)
    if parts.scheme == "https":
        checks.append(_ok("base url", f"https://{parts.hostname}"))
    elif parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS:
        checks.append(_warn("base url", "plain HTTP on loopback: a development gateway"))
    else:
        checks.append(
            _fail(
                "base url",
                "BAYRAM_GENAI_BASE_URL is not an https:// URL; the gateway is reached through "
                "the Cloudflare Tunnel, never over plain HTTP (IMAGE_VIDEO_SPEC §9.1 item 2)",
            )
        )
    if "api_key" in parse_qs(parts.query):
        checks.append(
            _fail("key in url", "BAYRAM_GENAI_BASE_URL carries ?api_key=; header only (§9.1)")
        )
    if settings.genai_api_key.strip():
        checks.append(_ok("api key", f"set, sent as {API_KEY_HEADER}"))
    else:
        checks.append(_fail("api key", "BAYRAM_GENAI_API_KEY is unset"))
    for field, kind in (("genai_image_model", "image"), ("genai_video_model", "video")):
        model = str(getattr(settings, field))
        if model in LOCAL_MODEL_ALLOWLIST and MODEL_KINDS[model] == kind:
            checks.append(_ok(f"{kind} model", f"{model} (allowlisted)"))
        else:
            checks.append(
                _fail(
                    f"{kind} model",
                    f"BAYRAM_{field.upper()}={model!r} is not an allowlisted {kind} model; "
                    f"one of {sorted(m for m, k in MODEL_KINDS.items() if k == kind)}",
                )
            )
    has_id = bool(settings.genai_access_client_id.strip())
    has_secret = bool(settings.genai_access_client_secret.strip())
    if has_id and has_secret:
        checks.append(_ok("access token", "Cloudflare Access service token set"))
    elif has_id or has_secret:
        checks.append(
            _fail(
                "access token",
                "only one of BAYRAM_GENAI_ACCESS_CLIENT_ID / _SECRET is set; both or neither",
            )
        )
    else:
        checks.append(
            _warn(
                "access token",
                "no Cloudflare Access service token: nothing but the gateway key stands in "
                "front of the gateway (IMAGE_VIDEO_SPEC §9.1 item 2)",
            )
        )
    return checks


def _operation(doc: Mapping[str, Any], method: str, path: str) -> Mapping[str, Any] | None:
    paths = doc.get("paths")
    item = paths.get(path) if isinstance(paths, Mapping) else None
    op = item.get(method) if isinstance(item, Mapping) else None
    return op if isinstance(op, Mapping) else None


def _generate_schema(doc: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The ``POST /generate`` body schema, following one local ``$ref``."""
    op = _operation(doc, "post", "/generate")
    try:
        schema = op["requestBody"]["content"]["application/json"]["schema"]  # type: ignore[index]
    except (KeyError, TypeError):
        return None
    if not isinstance(schema, Mapping):
        return None
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        schemas = doc.get("components", {}).get("schemas", {})
        schema = schemas.get(ref.rsplit("/", 1)[-1]) if isinstance(schemas, Mapping) else None
    return schema if isinstance(schema, Mapping) else None


def _query_key_routes(doc: Mapping[str, Any]) -> list[str]:
    """Every operation that still declares a query parameter named ``api_key``."""
    routes: list[str] = []
    paths = doc.get("paths")
    if not isinstance(paths, Mapping):
        return routes
    for path, item in paths.items():
        if not isinstance(item, Mapping):
            continue
        for method, op in item.items():
            params = op.get("parameters") if isinstance(op, Mapping) else None
            if not isinstance(params, list):
                continue
            if any(
                isinstance(p, Mapping) and p.get("in") == "query" and p.get("name") == "api_key"
                for p in params
            ):
                routes.append(f"{str(method).upper()} {path}")
    return sorted(routes)


def contract_checks(doc: Mapping[str, Any]) -> list[Check]:
    """Diff a gateway ``/openapi.json`` against what the adapter sends (§4.2). Pure; no IO."""
    checks: list[Check] = []
    missing = [f"{m.upper()} {p}" for m, p in REQUIRED_OPERATIONS if _operation(doc, m, p) is None]
    if missing:
        checks.append(_fail("contract routes", f"missing: {', '.join(missing)}"))
    else:
        checks.append(_ok("contract routes", "every route the adapter calls is declared"))

    schema = _generate_schema(doc)
    if schema is None:
        checks.append(_fail("contract body", "no JSON body schema on POST /generate"))
    else:
        props = schema.get("properties")
        declared = set(props) if isinstance(props, Mapping) else set()
        undeclared = sorted(GENERATE_PAYLOAD_KEYS - declared)
        if not undeclared:
            checks.append(_ok("contract body", "every key we send is declared"))
        elif schema.get("additionalProperties") is True:
            checks.append(
                _warn(
                    "contract body",
                    f"we send undeclared keys {undeclared}; accepted only while the schema "
                    "says additionalProperties: true",
                )
            )
        else:
            checks.append(
                _fail(
                    "contract body",
                    f"we send {undeclared}, which the schema neither declares nor allows",
                )
            )
        if "priority" in declared:
            checks.append(_ok("G5 priority", "POST /generate declares priority"))
        else:
            checks.append(
                _warn("G5 priority", "no priority field yet; marketing renders yield by hand")
            )

    query_routes = _query_key_routes(doc)
    if query_routes:
        shown = ", ".join(query_routes[:3]) + (" …" if len(query_routes) > 3 else "")
        checks.append(
            _fail(
                "header-only auth",
                f"{len(query_routes)} route(s) still accept ?api_key= ({shown}); "
                "IMAGE_VIDEO_SPEC §9.1 item 3",
            )
        )
    else:
        checks.append(_ok("header-only auth", "no route declares a query-string key"))

    if _operation(doc, *G6_OPERATION) is not None:
        checks.append(_ok("G6 delete", "DELETE /result/{job_id} is declared"))
    else:
        checks.append(
            _warn("G6 delete", "no delete route; the box's api_in_* sweeper is the only control")
        )
    return checks


def _json(response: httpx.Response) -> object:
    try:
        return orjson.loads(response.content)
    except orjson.JSONDecodeError:
        return None


def _model_ids(body: object) -> set[str]:
    """``/v1/models`` is OpenAI-shaped (``{data:[{id}]}``); a bare list or ``models`` also works."""
    entries: object = body
    if isinstance(body, Mapping):
        entries = body.get("data", body.get("models"))
    ids: set[str] = set()
    if not isinstance(entries, list):
        return ids
    for entry in entries:
        if isinstance(entry, str):
            ids.add(entry)
        elif isinstance(entry, Mapping):
            ids.update(v for k in ("id", "name", "model") if isinstance(v := entry.get(k), str))
    return ids


async def _get(
    client: httpx.AsyncClient, url: str, headers: Mapping[str, str], timeout_s: float
) -> httpx.Response | str:
    """The response, or the transport exception's type name. Redirects are NOT followed: a
    302 from the tunnel is Cloudflare Access sending us to a login page."""
    try:
        return await client.get(
            url, headers=dict(headers), timeout=httpx.Timeout(timeout_s), follow_redirects=False
        )
    except httpx.HTTPError as exc:
        return type(exc).__name__


def _refusal(response: httpx.Response) -> str:
    status = response.status_code
    if response.is_redirect:
        return (
            f"redirected ({status}): Cloudflare Access did not accept the service token "
            "(BAYRAM_GENAI_ACCESS_CLIENT_ID / _SECRET)"
        )
    if status in _AUTH_STATUSES:
        return f"refused ({status}): the Access service token or the gateway key is wrong"
    return f"http {status}"


async def _live_checks(
    settings: Settings, client: httpx.AsyncClient, *, contract: bool, timeout_s: float
) -> list[Check]:
    checks: list[Check] = []
    base = settings.genai_base_url.strip().rstrip("/")
    edge = access_headers(settings.genai_access_client_id, settings.genai_access_client_secret)
    keyed = {**edge, API_KEY_HEADER: settings.genai_api_key.strip(), "accept": "application/json"}

    health = await _get(client, f"{base}{HEALTH_PATH}", keyed, timeout_s)
    if isinstance(health, str):
        checks.append(_fail("reachable", f"GET {HEALTH_PATH} did not connect ({health})"))
        return [*checks, _skip("gateway", "unreachable; nothing further was asked")]
    if health.status_code != _HTTP_OK:
        checks.append(_fail("reachable", f"GET {HEALTH_PATH}: {_refusal(health)}"))
        return [*checks, _skip("gateway", "unreachable; nothing further was asked")]
    checks.append(_ok("reachable", f"GET {HEALTH_PATH} 200 through {urlsplit(base).hostname}"))

    models = await _get(client, f"{base}{MODELS_PATH}", keyed, timeout_s)
    if isinstance(models, str) or models.status_code != _HTTP_OK:
        why = models if isinstance(models, str) else _refusal(models)
        checks.append(_fail("auth", f"GET {MODELS_PATH} with the key: {why}"))
    else:
        checks.append(_ok("auth", f"GET {MODELS_PATH} 200 with the key in {API_KEY_HEADER}"))
        checks.append(_models_check(settings, _model_ids(_json(models))))

    anonymous = await _get(client, f"{base}{MODELS_PATH}", edge, timeout_s)
    if isinstance(anonymous, str):
        checks.append(_warn("keyless refused", f"could not ask ({anonymous})"))
    elif anonymous.status_code in _AUTH_STATUSES:
        checks.append(_ok("keyless refused", f"{anonymous.status_code} without the key"))
    elif anonymous.status_code == _HTTP_OK:
        checks.append(_fail("keyless refused", f"GET {MODELS_PATH} answers 200 with no key"))
    else:
        checks.append(_warn("keyless refused", f"http {anonymous.status_code} without the key"))

    guards = await _get(client, f"{base}{GUARD_HEALTH_PATH}", keyed, timeout_s)
    if not isinstance(guards, str) and guards.status_code == _HTTP_OK:
        checks.append(_ok("G4 guards", f"GET {GUARD_HEALTH_PATH} 200"))
    elif not isinstance(guards, str) and guards.status_code == _HTTP_NOT_FOUND:
        checks.append(_warn("G4 guards", "not installed yet (IMAGE_VIDEO_SPEC §6.5; M3 needs it)"))
    else:
        why = guards if isinstance(guards, str) else _refusal(guards)
        checks.append(_warn("G4 guards", f"GET {GUARD_HEALTH_PATH}: {why}"))

    if contract:
        checks.extend(await _contract_live(client, f"{base}{OPENAPI_PATH}", keyed, timeout_s))
    return checks


def _models_check(settings: Settings, served: set[str]) -> Check:
    wanted = {settings.genai_image_model, settings.genai_video_model}
    missing = sorted(wanted - served)
    if missing:
        return _fail("models", f"the gateway does not serve {missing}")
    others = sorted(served - LOCAL_MODEL_ALLOWLIST)
    also = f"; also serves {len(others)} model(s) we never select" if others else ""
    return _ok("models", f"{sorted(wanted)} installed{also}")


async def _contract_live(
    client: httpx.AsyncClient, url: str, headers: Mapping[str, str], timeout_s: float
) -> list[Check]:
    response = await _get(client, url, headers, timeout_s)
    if isinstance(response, str) or response.status_code != _HTTP_OK:
        why = response if isinstance(response, str) else _refusal(response)
        return [_fail("contract", f"GET {OPENAPI_PATH}: {why}")]
    doc = _json(response)
    if not isinstance(doc, Mapping):
        return [_fail("contract", f"{OPENAPI_PATH} is not a JSON object")]
    return contract_checks(doc)


async def run_doctor(
    settings: Settings,
    *,
    contract: bool = False,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> DoctorReport:
    """Every check, in order. Never raises on a gateway answer; a failure is a ``FAIL`` row."""
    if not settings.genai_base_url.strip():
        if _uses_the_gateway(settings):
            return DoctorReport(
                (_fail("base url", "an offered SKU routes to local; BAYRAM_GENAI_BASE_URL unset"),)
            )
        return DoctorReport(
            (_skip("gateway", "BAYRAM_GENAI_BASE_URL is unset and no offered SKU uses it"),)
        )
    checks = config_checks(settings)
    if any(check.status is CheckStatus.FAIL for check in checks):
        # Plain HTTP, or a key in the URL, is exactly what must not be sent anywhere.
        checks.append(_skip("gateway", "not contacted: fix the configuration first"))
        return DoctorReport(tuple(checks))
    owns_client = client is None
    http = client if client is not None else httpx.AsyncClient()
    try:
        checks.extend(await _live_checks(settings, http, contract=contract, timeout_s=timeout_s))
    finally:
        if owns_client:
            await http.aclose()
    return DoctorReport(tuple(checks))


def summarise(checks: Sequence[Check]) -> str:
    """One line: how many of each status. Used in the CLI's last line."""
    counts = {status: sum(c.status is status for c in checks) for status in CheckStatus}
    return ", ".join(f"{n} {s.value}" for s, n in counts.items() if n)
