"""Bodies for the five authentication routes.

Every password field carries ``repr=False``. Pydantic renders a model in a validation error,
in a debugger and in any log line that interpolates it, and a login body is the one object in
this system whose ``repr`` must never contain what it carries — the redaction layer in
``bayram.logging`` masks by *key name*, and ``password`` would be masked, but only once the value
has already been turned into a string somewhere it might be kept.

There is no ``displayName`` on :class:`MeResponse`. §6.3 lists one, but ``admin_users`` has no
such column in the shipped schema, and inventing a field that is always the username would be
a promise the database does not keep.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import Field

from bayram.admin.schemas.common import MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS, ApiModel
from bayram.admin.security.permissions import StepUpAction
from bayram.db.enums import AdminRole

__all__ = [
    "MAX_USERNAME_CHARS",
    "MAX_SUBJECT_ID_CHARS",
    "LoginRequest",
    "LoginResponse",
    "MeResponse",
    "PasswordChangeRequest",
    "StepUpRequest",
    "StepUpResponse",
]

#: Matches ``admin_users.username``'s ``String(64)``: a longer value cannot name an account,
#: so it is refused before it reaches a query or a rate-limit key.
MAX_USERNAME_CHARS: Final[int] = 64
#: Matches ``admin_sessions.step_up_scope``'s ``String(128)`` less the action and separator.
MAX_SUBJECT_ID_CHARS: Final[int] = 96


class LoginRequest(ApiModel):
    """``{username, password}``. The only unauthenticated body this API accepts."""

    username: str = Field(min_length=1, max_length=MAX_USERNAME_CHARS)
    #: No minimum length: an existing password predates any rule this schema could impose,
    #: and refusing to *check* a short one would tell an attacker where the boundary is.
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS, repr=False)


class LoginResponse(ApiModel):
    """What the SPA needs to decide which screen to render next, and nothing else."""

    must_change_password: bool


class MeResponse(ApiModel):
    """The signed-in operator. No password material, no session token, at any role."""

    id: UUID
    username: str
    role: AdminRole
    last_login_at: datetime | None
    must_change_password: bool


class PasswordChangeRequest(ApiModel):
    """Rotating your own credential. The current password is required even when forced.

    Requiring it on the forced-rotation path too is the point: without it, a session stolen
    from a freshly bootstrapped account could set a password of its own and lock the real
    operator out of the panel they were handed.
    """

    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS, repr=False)
    new_password: str = Field(
        min_length=MIN_PASSWORD_CHARS, max_length=MAX_PASSWORD_CHARS, repr=False
    )


class StepUpRequest(ApiModel):
    """Re-authentication for **one action on one subject** (§12.1 T2).

    ``scope`` is the action class and ``subjectId`` is what it is being taken against; the
    stored grant is the pair, compared whole. A body that named only the action would grant a
    door onto every subject the role can reach, which is the confused deputy the scope exists
    to close.
    """

    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS, repr=False)
    scope: StepUpAction
    subject_id: str = Field(min_length=1, max_length=MAX_SUBJECT_ID_CHARS)


class StepUpResponse(ApiModel):
    """The grant, so the SPA can show what it covers and when it lapses."""

    scope: str
    granted_at: datetime
    expires_at: datetime
