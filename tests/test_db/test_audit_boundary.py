"""The three audit columns that bypassed the boundary that is supposed to guard them.

``correlation_id``, ``ip`` and ``user_agent_hash`` were written straight into the row with
no check at all. ``hbd.db.admin.audit``'s module docstring says "no secret ever enters this
table"; the function enforcing it skipped three columns, and every credential shape below
landed verbatim — in the table with the longest clock in the system.

It was not yet a live leak, because no caller passed those fields, and that is exactly why
it is worth closing now: the first call site that passes a raw ``X-Forwarded-For`` element
or a raw User-Agent writes it into a 730-day row. A boundary that trusts its callers is not
a boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.db.admin.audit import AuditEntry, AuditValueRejectedError, append
from hbd.db.enums import AdminRole, AuditAction, AuditReasonCode

KEY: Final[str] = "a-test-hmac-key-of-more-than-32-characters"
NOW: Final[datetime] = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

#: The shapes the other nine fields already refuse.
_CREDENTIALS: Final[tuple[str, ...]] = (
    "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "postgresql+asyncpg://hbd_app:hunter2@db.internal:5432/hbd",
    "sk-or-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "Bearer aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
)


def _entry(**overrides: object) -> AuditEntry:
    values: dict[str, object] = {
        "action": AuditAction.LOGIN_SUCCESS,
        "actor_username": "owner",
        "actor_role": AdminRole.OWNER,
        "subject_type": "admin",
        "reason_code": AuditReasonCode.ROUTINE_OPS,
    }
    values.update(overrides)
    return AuditEntry(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["correlation_id", "ip", "user_agent_hash"])
@pytest.mark.parametrize("credential", _CREDENTIALS)
async def test_a_credential_is_refused_in_every_column_not_only_the_operator_facing_ones(
    sessions: async_sessionmaker[AsyncSession], field: str, credential: str
) -> None:
    # Arrange / Act / Assert
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError):
            await append(db, _entry(**{field: credential}), key=KEY, now=NOW)


async def test_a_raw_user_agent_is_refused_because_the_column_holds_a_digest(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the likeliest call-site bug: passing the header instead of its sha256. A
    # User-Agent is a fingerprint; a digest is a correlation key.
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError):
            await append(
                db,
                _entry(user_agent_hash="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"),
                key=KEY,
                now=NOW,
            )


async def test_a_legitimate_digest_ip_and_correlation_id_are_stored(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the guard must not refuse the values the real call sites pass. A sha256 of
    # the User-Agent is 64 hex characters, which is also the shape of a stolen session
    # digest, so this column cannot go through the generic credential filter.
    async with sessions.begin() as db:
        row = await append(
            db,
            _entry(
                correlation_id="1c6037fc4a3b4d9e8f0a1b2c3d4e5f60",
                ip="203.0.113.7",
                user_agent_hash="a" * 64,
            ),
            key=KEY,
            now=NOW,
        )

    # Assert
    assert row.ip == "203.0.113.7"
    assert row.user_agent_hash == "a" * 64
    assert row.correlation_id == "1c6037fc4a3b4d9e8f0a1b2c3d4e5f60"


@pytest.mark.parametrize("value", ["not-an-address", "999.1.1.1", "a" * 77])
async def test_a_non_address_in_the_ip_column_is_refused(
    sessions: async_sessionmaker[AsyncSession], value: str
) -> None:
    # Arrange — SQLite does not enforce the column's 45-character cap, so without this a
    # 77-character argon2 string persists where only an address belongs.
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError):
            await append(db, _entry(ip=value), key=KEY, now=NOW)
