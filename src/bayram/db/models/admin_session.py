"""``admin_sessions`` — one row per signed-in admin browser.

**The raw session token is never stored.** ``token_sha256`` is the only copy this table
holds, so a database dump yields nothing that can be replayed as a cookie. Lookup is by
digest, which is why the column is uniquely indexed rather than merely unique: the digest
is the hot path of every authenticated request.

Revocation and expiry are two different columns on purpose. ``expires_at`` is the absolute
cap the sweep scans (hence its own index); ``revoked_at`` is an operator or a password
change killing a session early, and it must remain visible after the row has also expired
so "when did this session die, and why" is answerable.

``TimestampMixin`` is deliberately not used. A session's ``created_at`` is meaningful and
an ``updated_at`` would be a second, misleading clock next to ``last_seen_at`` — the same
reason ``AssetRow`` and ``GenerationAttemptRow`` declare their own.

The IP columns are **recorded, not enforced**. Binding a session to an address breaks every
operator on a mobile network and buys pressure to disable the control rather than security.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import SHA256_LENGTH, Base, UtcDateTime

__all__ = [
    "AdminSessionRow",
    "CSRF_TOKEN_LENGTH",
    "IP_LENGTH",
    "STEP_UP_SCOPE_LENGTH",
    "USER_AGENT_LENGTH",
]

#: 32 random bytes rendered as hex.
CSRF_TOKEN_LENGTH: Final[int] = 64
#: The longest textual IPv6 address, including an IPv4-mapped tail.
IP_LENGTH: Final[int] = 45
#: ``<action>:<subject>`` — see the step-up scope rule in the admin plan §5.3.
STEP_UP_SCOPE_LENGTH: Final[int] = 128
#: Truncated on the way in; a User-Agent is diagnostic context, not a key.
USER_AGENT_LENGTH: Final[int] = 256


class AdminSessionRow(Base):
    """A live (or once-live) admin session.

    ``step_up_scope`` carries the action class the re-authentication was granted for, so a
    step-up obtained to reveal one order cannot silently authorise a purge. A single
    ``step_up_at`` with no scope would make the one control designed to survive session
    theft the one control that does not scope itself.
    """

    __tablename__ = "admin_sessions"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    admin_user_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: ``sha256(token)``. The raw token exists only in the operator's cookie jar.
    token_sha256: Mapped[str] = mapped_column(
        sa.String(SHA256_LENGTH), nullable=False, unique=True, index=True
    )
    #: The server-side value the ``X-CSRF-Token`` header is compared against.
    csrf_token: Mapped[str] = mapped_column(sa.String(CSRF_TOKEN_LENGTH), nullable=False)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: Sliding idle window. Bumped on every authenticated request.
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: Absolute cap. Indexed because the expiry sweep scans exactly this column.
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    created_ip: Mapped[str | None] = mapped_column(sa.String(IP_LENGTH), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(sa.String(IP_LENGTH), nullable=True)

    step_up_scope: Mapped[str | None] = mapped_column(
        sa.String(STEP_UP_SCOPE_LENGTH), nullable=True
    )
    step_up_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    user_agent: Mapped[str | None] = mapped_column(sa.String(USER_AGENT_LENGTH), nullable=True)
