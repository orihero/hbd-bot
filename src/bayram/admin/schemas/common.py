"""The base model every request and response shares, and the error envelope's shape.

``extra="forbid"`` is the load-bearing setting. A body with an unexpected field is a 422
rather than a silently ignored one, which is what stops a stale SPA build from *appearing*
to send ``confirmTelegramUserId`` while the server acts on a purge without it (§6.1). It is
cheap here and impossible to retrofit once clients rely on the tolerance.

``frozen=True`` for the repo's immutability rule: a response model handed to a serializer
comes back as a new object or not at all.

camelCase is generated rather than spelled per field, so a Python field cannot drift from
its wire name. ``populate_by_name=True`` means server-side construction still uses the
snake_case names, so no handler has to write ``mustChangePassword`` in Python.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

__all__ = [
    "ApiModel",
    "ErrorBody",
    "ErrorEnvelope",
    "MIN_PASSWORD_CHARS",
    "MAX_PASSWORD_CHARS",
]

#: Not a composition rule: length beats classes, and a class rule pushes operators towards
#: ``Password1!``. Lowered from 12 to 8 by product decision on 2026-09-04. At 8 the argon2
#: parameters are doing most of the work against a leaked hash, so keep
#: ``BAYRAM_ADMIN_ARGON2_MEMORY_KIB`` high and leave the login throttle in place.
MIN_PASSWORD_CHARS: Final[int] = 8
#: Bounded well inside ``passwords.MAX_PASSWORD_BYTES`` so a long-but-legal password is
#: rejected by the schema — cheaply, before a request — rather than by the hasher.
MAX_PASSWORD_CHARS: Final[int] = 256


class ApiModel(BaseModel):
    """Base for every model on the admin wire."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
        extra="forbid",
    )


class ErrorBody(ApiModel):
    """The ``error`` object of §6.2. Declared so the envelope appears in the OpenAPI schema.

    Responses are rendered by ``bayram.admin.errors.render_envelope`` rather than through this
    model: one exception handler produces every failure body, and routing it through a
    pydantic model would put a serialisation failure inside the error path.
    """

    code: str
    message: str
    correlation_id: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(ApiModel):
    """``{"error": {...}}`` — the only failure shape this API produces."""

    error: ErrorBody
