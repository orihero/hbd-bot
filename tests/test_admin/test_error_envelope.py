"""What a *real* 500 looks like, and where the vendor-credential check is allowed to look.

Two holes an adversarial review of Slice 1a found, both of which only reproduce against an
endpoint that raises for real.

**A 500 must be an ordinary response.** ``add_exception_handler(Exception, ...)`` is not a
handler like the other three: Starlette routes it to ``ServerErrorMiddleware``, which it
installs *outside* every ``add_middleware`` layer. A 500 rendered there is a response no
other middleware ever observes — no ``nosniff``, no CSP, no ``Cache-Control: no-store``
(§12.1 T7 and T10, and Slice 1a acceptance criterion 10), a correlation scope already
unwound so the envelope and the incident line both read ``-``, and no
``http.response.start`` for ``RequestLogMiddleware`` to see, which is why the failure was
logged at INFO with a null status. The tests below assert the whole chain against a route
that raises ``RuntimeError``, because a synthetic ASGI app that merely *sends* a 500 passes
in either design and proves nothing.

**And a credential is present if this host can reach it.** ``.env.admin`` is the file
pydantic-settings reads next; a vendor key written there is exactly as present as one
exported into the environment, and a check that looks only at ``os.environ`` reports
neither the prod refusal nor the dev warning for it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from fastapi import FastAPI
from starlette.types import Message, Receive, Scope, Send

from bayram.admin import app as app_module
from bayram.admin.app import FORBIDDEN_ENV_VARS, create_app, derive_forbidden_env_vars
from bayram.admin.container import AdminContainer
from bayram.admin.errors import (
    STATUS_BY_ADMIN_CODE,
    AdminErrorCode,
    AdminProblem,
    handle_unexpected,
    problem,
    status_for,
)
from bayram.admin.middleware import (
    CORRELATION_HEADER,
    UnhandledErrorMiddleware,
    is_valid_correlation_id,
)
from bayram.admin.settings import ADMIN_ENV_FILE
from bayram.config import FOREIGN_SECRET_ENV_VARS, VENDOR_SECRET_FIELDS
from bayram.errors import ConfigError
from bayram.logging import current_correlation_id
from tests.test_admin.conftest import ORIGIN, make_settings

#: Registered on a per-test application only, so the route-enumerating permission test
#: never sees it.
BOOM_PATH: Final[str] = "/api/_test/boom"
REFUSAL_PATH: Final[str] = "/api/_test/refusal"

_BOOM_MESSAGE: Final[str] = "deliberate failure raised by the regression test"
_SECRET_VALUE: Final[str] = "a-value-that-must-not-be-here"

#: The event names the two log lines a failed request must produce.
_REQUEST_EVENT: Final[str] = "admin.request"
_INCIDENT_EVENT: Final[str] = "admin.request.unhandled"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LoggedLine:
    """One record, plus the correlation id that was bound when it was emitted."""

    logger: str
    level: str
    event: str | None
    correlation_id: str
    status: int | None


class LineCapture(logging.Handler):
    """Capture records with the correlation id bound *at emit time*.

    That is precisely what ``bayram.logging._CorrelationFilter`` stamps onto a record in
    production, so reading it here proves the incident line and the request line are
    joinable without asserting on a formatted string.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[LoggedLine] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(
            LoggedLine(
                logger=record.name,
                level=record.levelname,
                event=getattr(record, "event", None),
                correlation_id=current_correlation_id(),
                status=getattr(record, "status", None),
            )
        )

    def with_event(self, event: str) -> list[LoggedLine]:
        return [line for line in self.lines if line.event == event]


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> Iterator[LineCapture]:
    """Root-handler capture that the lifespan cannot evict.

    ``configure_logging`` replaces every root handler, so it is stubbed out: this test is
    about which level a failure is logged at, not about how logging is configured.
    """
    monkeypatch.setattr("bayram.admin.app.configure_logging", lambda **_: None)
    handler = LineCapture()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def app_with_failing_routes(container: AdminContainer) -> FastAPI:
    """The real application, plus one route that raises and one that refuses."""
    application = create_app(container=container)

    @application.get(BOOM_PATH)
    async def boom() -> None:
        raise RuntimeError(_BOOM_MESSAGE)

    @application.get(REFUSAL_PATH)
    async def refusal() -> None:
        raise problem(AdminErrorCode.CONFLICT, "a route's own refusal")

    return application


async def get(
    application: FastAPI,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    raise_app_exceptions: bool = True,
) -> httpx.Response:
    """One GET through the whole stack, with the lifespan actually entered."""
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=raise_app_exceptions)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            return await http.get(path, headers=dict(headers) if headers else None)


# ---------------------------------------------------------------------------
# Issue 5 - a 500 is an ordinary response
# ---------------------------------------------------------------------------
async def test_a_real_500_carries_every_security_header(container: AdminContainer) -> None:
    # Arrange
    application = app_with_failing_routes(container)

    # Act - exceptions are not re-raised so the *response* can be asserted on either design
    response = await get(application, BOOM_PATH, raise_app_exceptions=False)

    # Assert
    assert response.status_code == 500
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


async def test_a_real_500_carries_a_correlation_id_the_body_repeats(
    container: AdminContainer,
) -> None:
    # Arrange
    application = app_with_failing_routes(container)

    # Act
    response = await get(application, BOOM_PATH, raise_app_exceptions=False)

    # Assert
    header_id = response.headers[CORRELATION_HEADER]
    assert is_valid_correlation_id(header_id)
    body = response.json()["error"]
    assert body["correlationId"] == header_id
    assert body["correlationId"] != "-"


async def test_a_real_500_reuses_an_inbound_correlation_id(container: AdminContainer) -> None:
    # Arrange - the id an operator's SPA already put on the request
    application = app_with_failing_routes(container)
    supplied = "0123456789abcdef0123456789abcdef"

    # Act
    response = await get(
        application,
        BOOM_PATH,
        headers={CORRELATION_HEADER: supplied},
        raise_app_exceptions=False,
    )

    # Assert
    assert response.headers[CORRELATION_HEADER] == supplied
    assert response.json()["error"]["correlationId"] == supplied


async def test_the_request_log_records_a_real_500_at_error_with_status_500(
    container: AdminContainer, captured: LineCapture
) -> None:
    # Arrange
    application = app_with_failing_routes(container)

    # Act
    await get(application, BOOM_PATH, raise_app_exceptions=False)

    # Assert - the status >= 500 branch, reached by an actual failure
    request_lines = captured.with_event(_REQUEST_EVENT)
    assert len(request_lines) == 1
    assert request_lines[0].level == "ERROR"
    assert request_lines[0].status == 500


async def test_the_incident_line_and_the_request_line_join_on_one_correlation_id(
    container: AdminContainer, captured: LineCapture
) -> None:
    # Arrange
    application = app_with_failing_routes(container)
    supplied = "fedcba9876543210fedcba9876543210"

    # Act
    response = await get(
        application,
        BOOM_PATH,
        headers={CORRELATION_HEADER: supplied},
        raise_app_exceptions=False,
    )

    # Assert - three places, one string
    incidents = captured.with_event(_INCIDENT_EVENT)
    assert len(incidents) == 1
    assert incidents[0].level == "ERROR"
    assert incidents[0].correlation_id == supplied
    assert captured.with_event(_REQUEST_EVENT)[0].correlation_id == supplied
    assert response.headers[CORRELATION_HEADER] == supplied


async def test_a_real_500_does_not_escape_the_application(container: AdminContainer) -> None:
    # Arrange - the default transport re-raises anything the app lets through
    application = app_with_failing_routes(container)

    # Act
    response = await get(application, BOOM_PATH)

    # Assert - the code agrees with the status: a bug here is 500/INTERNAL_ERROR, never
    # the 503-mapped SERVICE_UNAVAILABLE that told an SPA to retry a broken code path
    assert response.status_code == 500
    assert response.json()["error"]["code"] == AdminErrorCode.INTERNAL_ERROR.value


def test_the_unexpected_code_is_mapped_to_the_status_it_is_answered_with() -> None:
    """The envelope must not disagree with its own status line.

    ``handle_unexpected`` answered 500 while carrying ``SERVICE_UNAVAILABLE``, which
    :data:`STATUS_BY_ADMIN_CODE` maps to 503 — so a client branching on ``code`` (the field
    the whole taxonomy exists for) read a bug in this process as "retry later". Asserting
    the *table* rather than one response is what stops the pair drifting apart again.
    """
    # Assert
    assert STATUS_BY_ADMIN_CODE[AdminErrorCode.INTERNAL_ERROR] == 500
    assert STATUS_BY_ADMIN_CODE[AdminErrorCode.SERVICE_UNAVAILABLE] == 503
    assert status_for(AdminProblem(code=AdminErrorCode.INTERNAL_ERROR, message="boom")) == 500


async def test_a_real_500_never_leaks_the_exception_text(container: AdminContainer) -> None:
    # Arrange
    application = app_with_failing_routes(container)

    # Act
    response = await get(application, BOOM_PATH, raise_app_exceptions=False)

    # Assert
    assert _BOOM_MESSAGE not in response.text
    assert "Traceback" not in response.text


async def test_a_routes_own_refusal_is_still_rendered_by_its_registered_handler(
    container: AdminContainer, captured: LineCapture
) -> None:
    # Arrange - the catch-all must not intercept what ExceptionMiddleware already answers
    application = app_with_failing_routes(container)

    # Act
    response = await get(application, REFUSAL_PATH)

    # Assert
    assert response.status_code == 409
    assert response.json()["error"]["code"] == AdminErrorCode.CONFLICT.value
    assert response.headers["x-content-type-options"] == "nosniff"
    assert captured.with_event(_INCIDENT_EVENT) == []
    assert captured.with_event(_REQUEST_EVENT)[0].level == "INFO"


# ---------------------------------------------------------------------------
# Issue 10 - a credential is present if this host can reach it
# ---------------------------------------------------------------------------
def write_env_admin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str) -> None:
    """Point the boot check at a throwaway ``.env.admin`` holding exactly ``line``."""
    env_file = tmp_path / ".env.admin"
    env_file.write_text(f"{line}\n", encoding="utf-8")
    monkeypatch.setattr("bayram.admin.app.ADMIN_ENV_FILE", str(env_file))


@pytest.mark.parametrize("variable", FORBIDDEN_ENV_VARS)
async def test_prod_refuses_a_vendor_key_written_only_into_the_env_admin_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variable: str
) -> None:
    # Arrange - nothing in os.environ; the key exists only in the file
    write_env_admin(tmp_path, monkeypatch, f"{variable}={_SECRET_VALUE}")
    prod = make_settings(environment="prod", admin_cookie_secure=True)
    application = create_app(prod)

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - the lifespan must not reach here
    assert variable in caught.value.operator_message
    assert _SECRET_VALUE not in caught.value.operator_message


async def test_prod_refuses_a_lowercase_vendor_key_in_the_env_admin_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange - pydantic-settings reads .env.admin case-insensitively, so this key is live
    variable = FORBIDDEN_ENV_VARS[0]
    write_env_admin(tmp_path, monkeypatch, f"{variable.lower()}={_SECRET_VALUE}")
    prod = make_settings(environment="prod", admin_cookie_secure=True)
    application = create_app(prod)

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - the lifespan must not reach here
    assert variable in caught.value.operator_message


async def test_dev_warns_about_a_vendor_key_in_the_env_admin_file(
    container: AdminContainer,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    # Arrange
    variable = FORBIDDEN_ENV_VARS[-1]
    write_env_admin(tmp_path, monkeypatch, f"{variable}={_SECRET_VALUE}")
    monkeypatch.setattr("bayram.admin.app.configure_logging", lambda **_: None)
    application = create_app(container=container)

    # Act
    with caplog.at_level("WARNING"):
        async with application.router.lifespan_context(application):
            pass

    # Assert - names the variable, never its value
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert any(variable in str(getattr(record, "variables", "")) for record in warnings)
    assert not any(_SECRET_VALUE in record.getMessage() for record in warnings)


async def test_an_empty_value_in_the_env_admin_file_is_not_a_present_credential(
    container: AdminContainer,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    # Arrange - a blanked key is the normal shape of "not set", not of "present"
    write_env_admin(tmp_path, monkeypatch, f"{FORBIDDEN_ENV_VARS[0]}=")
    monkeypatch.setattr("bayram.admin.app.configure_logging", lambda **_: None)
    application = create_app(container=container)

    # Act
    with caplog.at_level("WARNING"):
        async with application.router.lifespan_context(application):
            pass

    # Assert
    assert not any(
        getattr(record, "event", None) == "admin.boot.vendor_env_present"
        for record in caplog.records
    )


async def test_a_missing_env_admin_file_is_not_an_error(
    container: AdminContainer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setattr("bayram.admin.app.ADMIN_ENV_FILE", str(tmp_path / "absent.env"))
    application = create_app(container=container)

    # Act
    response = await get(application, "/healthz")

    # Assert
    assert response.status_code == 200


def refuse_to_read(*_args: object, **_kwargs: object) -> Mapping[str, str | None]:
    """What python-dotenv does when the file exists but this process may not open it."""
    raise PermissionError(13, "Permission denied")


async def test_an_unreadable_env_admin_file_is_reported_rather_than_swallowed(
    container: AdminContainer,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    # Arrange - the file is there; the OS refuses it. A missing file is simply empty, so
    # only a real OSError reaches the handler under test.
    write_env_admin(tmp_path, monkeypatch, f"{FORBIDDEN_ENV_VARS[0]}={_SECRET_VALUE}")
    monkeypatch.setattr("bayram.admin.app.dotenv_values", refuse_to_read)
    monkeypatch.setattr("bayram.admin.app.configure_logging", lambda **_: None)
    application = create_app(container=container)

    # Act - the boot continues on the half of the check that still works
    with caplog.at_level("WARNING"):
        async with application.router.lifespan_context(application):
            pass

    # Assert - the operator is told which half ran; nothing is silently dropped
    assert any(
        getattr(record, "event", None) == "admin.boot.env_file_unreadable"
        for record in caplog.records
    )


def test_the_forbidden_list_is_derived_rather_than_restated() -> None:
    """The list is a spelling of two tuples in ``bayram.config``, not a third hand-written one.

    Read through the module's own helper rather than by restating the derivation here: the
    forbidden set now covers two populations that are different kinds of thing - credentials
    declared as FIELDS on ``Settings``, and environment variable NAMES belonging to a settings
    model this host never loads (``BAYRAM_PAYME_MERCHANT_KEY``) - and a copy of that arithmetic
    living in a test is a copy that keeps passing while the two spellings diverge.
    """
    # Arrange / Act
    derived = derive_forbidden_env_vars()

    # Assert - a sixth credential added to bayram.config is covered without an edit here, and
    # so is a second foreign secret; the length pins that neither population was dropped.
    assert derived == FORBIDDEN_ENV_VARS
    assert len(FORBIDDEN_ENV_VARS) == len(VENDOR_SECRET_FIELDS) + len(FOREIGN_SECRET_ENV_VARS)
    assert set(FOREIGN_SECRET_ENV_VARS) <= set(FORBIDDEN_ENV_VARS)


def test_the_boot_check_reads_the_file_pydantic_settings_reads() -> None:
    # Assert - the model's own constant, not a second hand-written path that could drift
    assert app_module.ADMIN_ENV_FILE == ADMIN_ENV_FILE


# ---------------------------------------------------------------------------
# Issue 5 - the three branches the HTTP tests above cannot reach
# ---------------------------------------------------------------------------
async def empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def http_scope(state: dict[str, object] | None = None) -> Scope:
    """The minimum a ``starlette.requests.Request`` needs, plus optional published state."""
    scope: Scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    if state is not None:
        scope["state"] = state
    return scope


async def drive(app: UnhandledErrorMiddleware, scope: Scope) -> list[Message]:
    """Run one request through the middleware, collecting what it sends."""
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, empty_receive, send)
    return sent


def envelope_of(sent: list[Message]) -> dict[str, Any]:
    """The ``error`` object out of the collected body messages."""
    body = b"".join(bytes(message.get("body", b"")) for message in sent)
    decoded: dict[str, Any] = json.loads(body)
    return dict(decoded["error"])


async def test_a_non_http_scope_is_passed_straight_through() -> None:
    # Arrange - a lifespan or websocket scope has no response to render into
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(str(scope["type"]))

    middleware = UnhandledErrorMiddleware(inner, render=handle_unexpected)

    # Act
    await drive(middleware, {"type": "lifespan"})

    # Assert
    assert seen == ["lifespan"]


async def test_a_failure_after_the_response_started_is_re_raised_not_swallowed() -> None:
    # Arrange - bytes are already on the wire, so a second response.start is impossible
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("died mid-stream")

    middleware = UnhandledErrorMiddleware(inner, render=handle_unexpected)

    # Act / Assert - propagates to Starlette's ServerErrorMiddleware, never dropped
    with pytest.raises(RuntimeError, match="died mid-stream"):
        await drive(middleware, http_scope())


async def test_the_envelope_uses_the_correlation_id_published_on_the_scope() -> None:
    # Arrange - the id CorrelationIdMiddleware puts on scope["state"]
    published = "abcdef0123456789abcdef0123456789"

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("boom")

    middleware = UnhandledErrorMiddleware(inner, render=handle_unexpected)

    # Act
    sent = await drive(middleware, http_scope({"correlation_id": published}))

    # Assert
    assert sent[0]["status"] == 500
    assert envelope_of(sent)["correlationId"] == published


@pytest.mark.parametrize("state", [None, {}, {"correlation_id": ""}])
async def test_a_scope_without_a_published_id_still_renders_an_envelope(
    state: dict[str, object] | None,
) -> None:
    # Arrange - mounted without the correlation middleware in front of it, or with one
    # that published nothing usable
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("boom")

    middleware = UnhandledErrorMiddleware(inner, render=handle_unexpected)

    # Act
    sent = await drive(middleware, http_scope(state))

    # Assert - a 500 without a joinable id is still a 500, never a crash
    assert sent[0]["status"] == 500
    assert envelope_of(sent)["code"] == AdminErrorCode.INTERNAL_ERROR.value
