"""Request and response models for the admin API. One module per resource.

Everything inherits :class:`hbd.admin.schemas.common.ApiModel`, which fixes the three things
that must not vary per endpoint: camelCase on the wire, ``extra="forbid"`` on the way in, and
frozen instances so a serializer cannot quietly edit a response it was handed.
"""

from __future__ import annotations

from hbd.admin.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    PasswordChangeRequest,
    StepUpRequest,
    StepUpResponse,
)
from hbd.admin.schemas.common import (
    MAX_PASSWORD_CHARS,
    MIN_PASSWORD_CHARS,
    ApiModel,
    ErrorBody,
    ErrorEnvelope,
)

__all__ = [
    "ApiModel",
    "ErrorBody",
    "ErrorEnvelope",
    "MIN_PASSWORD_CHARS",
    "MAX_PASSWORD_CHARS",
    "LoginRequest",
    "LoginResponse",
    "MeResponse",
    "PasswordChangeRequest",
    "StepUpRequest",
    "StepUpResponse",
]
