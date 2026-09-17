"""The API error envelope, and the second taxonomy the HTTP surface needs.

**This does not reuse ``bayram.errors.ErrorCode``, and that is a decision rather than an
oversight.** That enum is closed around what the *pipeline* can fail at, and it has no
member for 401, for 403, for step-up-required, for a CSRF rejection, for 409 or for 415.
Extending it would be worse than useless: ``BayramError`` carries a ``user_message_key`` and
the bot renders customer-facing copy from it (``runtime/jobs.py`` ``_tell_the_customer_why``),
so an admin-only member would leak an operator concept into a customer-facing taxonomy in
four languages. So :class:`AdminErrorCode` is **disjoint** from ``ErrorCode`` — asserted by
test — and the envelope's ``code`` carries the union of the two (ADMIN_PANEL_PLAN §6.2).

Routes do not write ``try``/``except``. A failure is raised as one
:class:`ProblemError` carrying either an ``BayramError`` or an :class:`AdminProblem`, and
one handler renders it. That is what keeps ruff's ``TRY`` ruleset satisfied without any
route deciding a status code for itself. (The plan calls the class ``ProblemException``;
ruff's ``N818`` requires an ``Error`` suffix, and CI is not negotiable.)

Every message is passed through ``bayram.logging.redact`` and capped before it reaches the
body. Two of the messages this envelope will eventually carry are built by interpolating an
operator-submitted value (``bayram.config``'s ``_describe_failure`` and
``_candidates_must_be_unique``), and ``/config/validate`` exists precisely to accept such
values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from bayram.contracts import Result, is_ok
from bayram.errors import BayramError, ErrorCode
from bayram.logging import current_correlation_id, get_logger, redact

__all__ = [
    "AdminErrorCode",
    "AdminProblem",
    "ProblemError",
    "MAX_MESSAGE_CHARS",
    "STATUS_BY_ADMIN_CODE",
    "STATUS_BY_ERROR_CODE",
    "DEFAULT_STATUS",
    "status_for",
    "problem",
    "unwrap",
    "render_envelope",
    "handle_unexpected",
    "install_error_handlers",
]

_LOGGER: Final = get_logger(__name__)

#: Long enough for a real explanation, short enough that a message built by interpolating an
#: operator-submitted value cannot become a body of its own.
MAX_MESSAGE_CHARS: Final[int] = 300


class AdminErrorCode(StrEnum):
    """The HTTP surface's own closed taxonomy. Disjoint from ``bayram.errors.ErrorCode``."""

    UNAUTHENTICATED = "UNAUTHENTICATED"  # 401
    FORBIDDEN = "FORBIDDEN"  # 403
    STEP_UP_REQUIRED = "STEP_UP_REQUIRED"  # 403
    CSRF_REJECTED = "CSRF_REJECTED"  # 403
    ORIGIN_REJECTED = "ORIGIN_REJECTED"  # 403
    CONFLICT = "CONFLICT"  # 409
    PRECONDITION_FAILED = "PRECONDITION_FAILED"  # 409
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"  # 415
    RANGE_NOT_SATISFIABLE = "RANGE_NOT_SATISFIABLE"  # 416
    REVEAL_BUDGET_EXHAUSTED = "REVEAL_BUDGET_EXHAUSTED"  # 429
    LOGIN_RATE_LIMITED = "LOGIN_RATE_LIMITED"  # 429
    #: The re-auth budget on ``/auth/password`` and ``/auth/step-up``. Its own member
    #: because only this one has a remedy the operator can act on — the counter is scoped to
    #: the session, so signing in again mints a fresh budget. An SPA that could not tell it
    #: from ``LOGIN_RATE_LIMITED`` could not render that remedy from the code, which is what
    #: the carefully split key namespaces were for.
    REAUTH_RATE_LIMITED = "REAUTH_RATE_LIMITED"  # 429
    CONFIG_FIELD_NOT_EDITABLE = "CONFIG_FIELD_NOT_EDITABLE"  # 422
    CAPABILITY_DISABLED = "CAPABILITY_DISABLED"  # 409
    #: A dependency this process needs is not answering, and the caller should retry. Never
    #: used for a bug in this process — that is :attr:`INTERNAL_ERROR`.
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"  # 503
    #: A bug here. Its own member rather than a reused ``SERVICE_UNAVAILABLE``, because the
    #: two mean opposite things to a client: an SPA that branches on the code would read an
    #: internal failure as "retry later", retry it, and get the same failure — while the
    #: real incident never surfaces as one. The status and the code now agree at 500.
    INTERNAL_ERROR = "INTERNAL_ERROR"  # 500


#: §6.2's mapping, as data. Anything absent is a bug in this table, not a 500 by default:
#: :func:`status_for` falls back to :data:`DEFAULT_STATUS` and says so in the log.
STATUS_BY_ADMIN_CODE: Final[Mapping[AdminErrorCode, int]] = {
    AdminErrorCode.UNAUTHENTICATED: 401,
    AdminErrorCode.FORBIDDEN: 403,
    AdminErrorCode.STEP_UP_REQUIRED: 403,
    AdminErrorCode.CSRF_REJECTED: 403,
    AdminErrorCode.ORIGIN_REJECTED: 403,
    AdminErrorCode.CONFLICT: 409,
    AdminErrorCode.PRECONDITION_FAILED: 409,
    AdminErrorCode.CAPABILITY_DISABLED: 409,
    AdminErrorCode.UNSUPPORTED_MEDIA_TYPE: 415,
    AdminErrorCode.RANGE_NOT_SATISFIABLE: 416,
    AdminErrorCode.CONFIG_FIELD_NOT_EDITABLE: 422,
    AdminErrorCode.LOGIN_RATE_LIMITED: 429,
    AdminErrorCode.REAUTH_RATE_LIMITED: 429,
    AdminErrorCode.REVEAL_BUDGET_EXHAUSTED: 429,
    AdminErrorCode.SERVICE_UNAVAILABLE: 503,
    AdminErrorCode.INTERNAL_ERROR: 500,
}

#: The pipeline taxonomy's half of the same table.
STATUS_BY_ERROR_CODE: Final[Mapping[ErrorCode, int]] = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.INVALID_INPUT: 422,
    ErrorCode.CONFIG_INVALID: 422,
    ErrorCode.CONTENT_REJECTED: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.QUOTA_EXHAUSTED: 402,
    ErrorCode.UPSTREAM_TIMEOUT: 502,
    ErrorCode.UPSTREAM_5XX: 502,
    ErrorCode.UPSTREAM_MALFORMED: 502,
    ErrorCode.STORAGE_FAILED: 503,
}

DEFAULT_STATUS: Final[int] = 500


@dataclass(frozen=True, slots=True)
class AdminProblem:
    """One failure, ready to render. Immutable, like every value here.

    ``code`` is the **union** of the two taxonomies, which is what lets a body-validation
    failure answer with ``INVALID_INPUT`` — the code the rest of the system already uses for
    exactly that — without adding a member to ``AdminErrorCode`` that would break its
    disjointness from ``ErrorCode``.
    """

    code: AdminErrorCode | ErrorCode
    message: str
    details: Mapping[str, Any] | None = None
    #: Response headers this failure needs to carry — ``Retry-After`` on a 429, and nothing
    #: else so far. A refusal that tells the client *when* to come back is the difference
    #: between a throttle and a mystery.
    headers: Mapping[str, str] | None = None


class ProblemError(Exception):
    """The only exception a route raises. Carries whichever taxonomy applies.

    Not an ``BayramError`` subclass: an ``BayramError`` promises a ``user_message_key`` that a
    customer-facing catalogue can render, and nothing in this package has one.
    """

    def __init__(self, failure: AdminProblem | BayramError) -> None:
        super().__init__(_describe(failure))
        self._failure = failure

    @property
    def failure(self) -> AdminProblem | BayramError:
        return self._failure


def _describe(failure: AdminProblem | BayramError) -> str:
    if isinstance(failure, BayramError):
        return failure.operator_message
    return failure.message


def problem(
    code: AdminErrorCode,
    message: str,
    *,
    headers: Mapping[str, str] | None = None,
    **details: Any,
) -> ProblemError:
    """Build the exception a route raises. Keyword arguments become ``error.details``."""
    return ProblemError(
        AdminProblem(code=code, message=message, details=details or None, headers=headers)
    )


def status_for(failure: AdminProblem | BayramError) -> int:
    """The HTTP status for a failure from either taxonomy."""
    if isinstance(failure, BayramError):
        return STATUS_BY_ERROR_CODE.get(failure.error_code, DEFAULT_STATUS)
    if isinstance(failure.code, ErrorCode):
        return STATUS_BY_ERROR_CODE.get(failure.code, DEFAULT_STATUS)
    return STATUS_BY_ADMIN_CODE.get(failure.code, DEFAULT_STATUS)


def unwrap[T](result: Result[T]) -> T:
    """The value, or a :class:`ProblemError` carrying the ``Err``'s ``BayramError``.

    The repo's boundary type is a ``Result`` and its rule is that an error never crosses a
    boundary as an exception. An HTTP handler *is* the boundary: converting once, here,
    is what lets every route read as a straight line and still render the envelope.
    """
    if is_ok(result):
        return result.value
    raise ProblemError(result.error)


def _clean(message: str) -> str:
    """Redact, then cap. In that order — a truncated secret is still a secret prefix."""
    redacted = redact(message)
    text = redacted if isinstance(redacted, str) else str(redacted)
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[:MAX_MESSAGE_CHARS]


def _code_of(failure: AdminProblem | BayramError) -> str:
    return str(failure.error_code) if isinstance(failure, BayramError) else str(failure.code)


def _details_of(failure: AdminProblem | BayramError) -> Mapping[str, Any] | None:
    if isinstance(failure, BayramError):
        return None
    return failure.details


def render_envelope(
    failure: AdminProblem | BayramError, *, status: int | None = None
) -> JSONResponse:
    """The one body shape every failure comes back as (§6.2).

    ``correlationId`` is read from the context variable the correlation middleware bound, so
    the id in the body, the id in the response header and the id in the log line are the
    same string without any route passing it around.
    """
    resolved = status_for(failure) if status is None else status
    body: dict[str, Any] = {
        "code": _code_of(failure),
        "message": _clean(_describe(failure)),
        "correlationId": current_correlation_id(),
    }
    details = _details_of(failure)
    if details:
        body["details"] = redact(dict(details))
    headers = failure.headers if isinstance(failure, AdminProblem) else None
    return JSONResponse(
        status_code=resolved, content={"error": body}, headers=dict(headers) if headers else None
    )


_REFUSED: Final[AdminProblem] = AdminProblem(
    code=AdminErrorCode.FORBIDDEN, message="request refused"
)


async def _handle_problem(request: Request, exc: Exception) -> JSONResponse:
    """Render a route's own refusal. Not logged as an incident — it is a normal answer."""
    del request
    failure = exc.failure if isinstance(exc, ProblemError) else _REFUSED
    return render_envelope(failure)


async def _handle_validation(request: Request, exc: Exception) -> JSONResponse:
    """A malformed body is 422 in the same envelope, never FastAPI's own shape.

    The pydantic report is summarised to the field **locations** only. Its messages are
    built from the submitted document, and echoing an attacker-chosen value back into a JSON
    body is the reflection this envelope's redaction exists to prevent.
    """
    del request
    return render_envelope(
        AdminProblem(
            code=ErrorCode.INVALID_INPUT,
            message="request body failed validation",
            details={"fields": _validation_fields(exc)},
        ),
        status=422,
    )


def _validation_fields(exc: Exception) -> list[str]:
    if not isinstance(exc, RequestValidationError):
        return []
    return [".".join(str(part) for part in issue["loc"]) for issue in exc.errors()]


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Starlette's own 404/405 answers, rendered in this envelope instead of its default."""
    del request
    status = exc.status_code if isinstance(exc, HTTPException) else DEFAULT_STATUS
    detail = exc.detail if isinstance(exc, HTTPException) else "error"
    code = _ADMIN_CODE_BY_STATUS.get(status, ErrorCode.NOT_FOUND)
    return render_envelope(AdminProblem(code=code, message=str(detail)), status=status)


#: Starlette raises bare ``HTTPException``s for routing failures; these are the only statuses
#: it can produce here, and each one is given a code from one of the two enums so no response
#: ever carries a code that is not in a closed taxonomy.
_ADMIN_CODE_BY_STATUS: Final[Mapping[int, AdminErrorCode | ErrorCode]] = {
    401: AdminErrorCode.UNAUTHENTICATED,
    403: AdminErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: AdminErrorCode.CONFLICT,
    415: AdminErrorCode.UNSUPPORTED_MEDIA_TYPE,
}


async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """The last resort. Logged with the traceback, answered without one.

    An unexpected exception is an incident, so it is logged at ERROR with its cause; the
    body carries a constant string, because a traceback rendered into a response is how an
    internal path becomes public knowledge.

    **Public, and deliberately not registered by** :func:`install_error_handlers`. Starlette
    routes an ``Exception`` handler to ``ServerErrorMiddleware``, which sits outside every
    ``add_middleware`` layer — a 500 answered from there carries no security header, no
    correlation id and no request-log line (see
    :mod:`bayram.admin.middleware.unhandled`). ``create_app`` installs this as that middleware's
    renderer instead, so the correlation scope is still bound when this line is written and
    the ``correlationId`` in the body is the one the response header echoes.

    **The code is** :attr:`AdminErrorCode.INTERNAL_ERROR`, **not** ``SERVICE_UNAVAILABLE``.
    This used to answer 500 while carrying the code :data:`STATUS_BY_ADMIN_CODE` maps to
    **503**, so the envelope contradicted its own status line — and ``code`` is the field
    this taxonomy exists to be branched on, so an SPA read a bug in this process as "a
    dependency is down, try again later", retried it, and buried the incident in a retry
    loop. The two agree now, which is also why the ``status`` override below is gone: the
    table is the single source of the status, rather than a second one that can drift.
    """
    _LOGGER.exception(
        "unhandled error in an admin request",
        extra={"event": "admin.request.unhandled", "method": request.method},
        exc_info=exc,
    )
    return render_envelope(
        AdminProblem(code=AdminErrorCode.INTERNAL_ERROR, message="internal error")
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register the three handlers Starlette's ``ExceptionMiddleware`` answers in-stack.

    The catch-all on ``Exception`` is **not** among them, and that absence is the fix for
    the 500 that arrived with no headers and no correlation id:
    :func:`handle_unexpected` is mounted by ``create_app`` as a middleware instead.
    """
    app.add_exception_handler(ProblemError, _handle_problem)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(HTTPException, _handle_http_exception)
