"""``/api/audit`` and ``/api/audit/verify`` over the real ASGI stack.

The router is mounted here rather than by ``create_app``: ``src/hbd/admin/app.py`` belongs to
the slice that mounts every read-only router at once, and this slice ships the router and its
tests. Everything else is the production path — the real container, the real login, the real
permission guard, the real session cookies.

Three assertions carry the section's weight:

* an ADMIN gets ``hasReasonText: true`` and **no** ``reasonText`` — §12.2's **M** cell is one
  column wide, and the field is absent rather than blanked so "you may not read it" and "none
  was recorded" stay different answers;
* ``chainProtection`` reads ``hmac-only`` on this deployment, because it is, and the panel
  renders that verbatim;
* a row edited with raw SQL comes back as ``ok: false`` with the offending ``seq``.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI

from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer
from hbd.admin.errors import ProblemError
from hbd.admin.routers.audit import AUDIT_PATH, VERIFY_PATH, build_audit_router
from hbd.admin.window import require_aware
from hbd.db.admin.audit import AuditEntry, append
from hbd.db.enums import AdminRole, AuditAction, AuditReasonCode
from hbd.db.models.admin_audit import AdminAuditRow
from tests.test_admin.conftest import (
    HMAC_KEY,
    ORIGIN,
    PASSWORD,
    USERNAME,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    make_settings,
    open_container,
    sign_in,
)

NOW: Final[datetime] = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def encode_wrong_shape() -> str:
    """Well-formed base64url JSON that is not one of ours — the shape check, not the codec."""
    return base64.urlsafe_b64encode(b'{"page":2}').decode("ascii").rstrip("=")


REASON_TEXT: Final[str] = "the customer called about their order"


@pytest.fixture
def audit_app(container: AdminContainer) -> FastAPI:
    """The application with the audit router mounted. See the module docstring."""
    application = create_app(container=container)
    application.include_router(build_audit_router())
    return application


@asynccontextmanager
async def open_audit_client(container: AdminContainer) -> AsyncIterator[httpx.AsyncClient]:
    """A client for a container a test built itself — the settings-varying cases need one."""
    application = create_app(container=container)
    application.include_router(build_audit_router())
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


@pytest.fixture
async def audit_client(audit_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with audit_app.router.lifespan_context(audit_app):
        transport = httpx.ASGITransport(app=audit_app)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


async def seed(container: AdminContainer, count: int = 3, **overrides: Any) -> list[AdminAuditRow]:
    """``count`` audited actions through the one supported writer."""
    rows: list[AdminAuditRow] = []
    for index in range(count):
        async with container.session_factory.begin() as db:
            values: dict[str, Any] = {
                "action": AuditAction.REVEAL_PERSONAL,
                "actor_username": USERNAME,
                "actor_role": AdminRole.OWNER,
                "subject_type": "order",
                "subject_id": f"order-{index}",
                "reason_code": AuditReasonCode.SUPPORT_INVESTIGATION,
                "reason_text": REASON_TEXT,
            }
            values.update(overrides)
            rows.append(
                await append(
                    db,
                    AuditEntry(**values),
                    key=HMAC_KEY,
                    now=NOW + timedelta(minutes=index),
                )
            )
    return rows


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Who may read it, and how much of it
# ---------------------------------------------------------------------------
async def test_an_owner_reads_the_operator_free_text(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange — seeded AFTER signing in, because signing in now writes its own audit row
    # (§12.6) and the page is newest-first.
    await signed_in(container, audit_client, role=AdminRole.OWNER)
    await seed(container, 1)

    # Act
    response = await audit_client.get(AUDIT_PATH)

    # Assert
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["reasonText"] == REASON_TEXT
    assert item["hasReasonText"] is True


async def test_an_admin_learns_a_reason_exists_but_not_what_it_says(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange — seeded after signing in; the login row is newer than anything seeded first.
    await signed_in(container, audit_client, role=AdminRole.ADMIN)
    await seed(container, 1)

    # Act
    response = await audit_client.get(AUDIT_PATH)

    # Assert — §12.2's M cell, and the fixture's plaintext appears nowhere in the body.
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["reasonText"] is None
    assert item["hasReasonText"] is True
    assert REASON_TEXT not in response.text


@pytest.mark.parametrize("role", [AdminRole.VIEWER, AdminRole.SUPPORT])
async def test_a_role_without_the_cell_is_refused(
    container: AdminContainer, audit_client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange
    await seed(container, 1)
    await signed_in(container, audit_client, role=role)

    # Act
    response = await audit_client.get(AUDIT_PATH)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_an_unauthenticated_caller_gets_401_not_a_page(
    audit_client: httpx.AsyncClient,
) -> None:
    # Act
    response = await audit_client.get(AUDIT_PATH)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# Paging and filtering
# ---------------------------------------------------------------------------
async def test_the_cursor_round_trips_and_terminates_with_a_null(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange — the login row is filtered out so this test still measures three rows and
    # not four; the cursor mechanics are what is under test, not the corpus.
    await signed_in(container, audit_client, role=AdminRole.OWNER)
    await seed(container, 3)
    page: dict[str, int | list[str]] = {"limit": 2, "action": ["reveal.personal"]}

    # Act
    first = (await audit_client.get(AUDIT_PATH, params=page)).json()
    second = (
        await audit_client.get(AUDIT_PATH, params={**page, "cursor": first["meta"]["nextCursor"]})
    ).json()

    # Assert
    assert [item["seq"] for item in first["items"]] == sorted(
        (item["seq"] for item in first["items"]), reverse=True
    )
    assert first["meta"]["nextCursor"] is not None
    assert len(second["items"]) == 1
    assert second["meta"]["nextCursor"] is None


@pytest.mark.parametrize(
    ("label", "cursor"),
    [
        ("not base64 at all", "not-a-cursor"),
        ("longer than any cursor we issue", "A" * 200),
        ("valid base64 JSON without a sequence", encode_wrong_shape()),
    ],
)
async def test_a_forged_cursor_is_a_422_and_not_a_stack_trace(
    container: AdminContainer, audit_client: httpx.AsyncClient, label: str, cursor: str
) -> None:
    # Arrange
    await signed_in(container, audit_client, role=AdminRole.OWNER)

    # Act
    response = await audit_client.get(AUDIT_PATH, params={"cursor": cursor})

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_a_naive_timestamp_is_refused(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, audit_client, role=AdminRole.OWNER)

    # Act — §6.1: a value with no offset means whatever the reader assumes, which is a
    # retention question answered wrongly rather than a filter answered loosely.
    response = await audit_client.get(AUDIT_PATH, params={"from": "2026-08-30T12:00:00"})

    # Assert
    assert response.status_code == 422
    # And the wording is the SHARED validator's, byte for byte. This route carried a private
    # sixth copy of ``_aware`` that ``hbd.admin.window`` was written to delete: identical,
    # untested against the other five, and therefore the exact drift the extraction was for
    # — reword ``require_aware`` and only this endpoint would keep the old refusal.
    with pytest.raises(ProblemError) as refused:
        require_aware("from", datetime(2026, 8, 30, 12, 0, 0))
    assert response.json()["error"]["message"] == str(refused.value)


async def test_filters_narrow_the_page(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed(container, 2)
    await seed(container, 1, action=AuditAction.USER_BLOCK, subject_type="user")
    await signed_in(container, audit_client, role=AdminRole.OWNER)

    # Act
    filtered = await audit_client.get(AUDIT_PATH, params={"action": ["user.block"]})
    by_subject = await audit_client.get(AUDIT_PATH, params={"subjectId": "order-1"})

    # Assert
    assert [item["action"] for item in filtered.json()["items"]] == ["user.block"]
    assert len(by_subject.json()["items"]) == 1


async def test_an_unknown_action_filter_is_refused_rather_than_matching_nothing(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, audit_client, role=AdminRole.OWNER)

    # Act
    response = await audit_client.get(AUDIT_PATH, params={"action": ["order.explode"]})

    # Assert
    assert response.status_code == 422


async def test_the_actor_filter_accepts_an_id_and_a_username(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed(container, 1)
    await seed(container, 1, actor_username="someone-else")
    await signed_in(container, audit_client, role=AdminRole.OWNER)

    # Act
    by_name = await audit_client.get(AUDIT_PATH, params={"actor": "someone-else"})
    by_missing_id = await audit_client.get(
        AUDIT_PATH, params={"actor": "1c9e1a5e-0000-4000-8000-0000000000ff"}
    )

    # Assert
    assert len(by_name.json()["items"]) == 1
    assert by_missing_id.json()["items"] == []


# ---------------------------------------------------------------------------
# /audit/verify
# ---------------------------------------------------------------------------
async def test_verify_reports_a_clean_chain_and_the_protection_it_actually_has(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange — four rows, not three: signing in writes its own (§12.6).
    await signed_in(container, audit_client, role=AdminRole.OWNER)
    await seed(container, 3)

    # Act
    response = await audit_client.get(VERIFY_PATH)

    # Assert — no two-role setup here, so the honest answer is hmac-only (§12.4).
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["firstBreakSeq"] is None
    assert body["chainProtection"] == "hmac-only"
    assert body["checkedRows"] == 4
    assert body["isComplete"] is True


async def test_verify_names_the_row_somebody_edited(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange
    rows = await seed(container, 3)
    async with container.session_factory.begin() as db:
        await db.execute(
            sa.text("UPDATE admin_audit_log SET record_count = 99 WHERE seq = :seq"),
            {"seq": rows[1].seq},
        )
    await signed_in(container, audit_client, role=AdminRole.OWNER)

    # Act
    response = await audit_client.get(VERIFY_PATH)

    # Assert
    body = response.json()
    assert body["ok"] is False
    assert body["firstBreakSeq"] == rows[1].seq


async def test_a_configured_audit_dsn_alone_does_not_earn_the_stronger_claim() -> None:
    # Arrange — the DSN is set, so this deployment CLAIMS the two-role setup of §4.5. The
    # database is SQLite, which has no privilege to revoke, so the claim is not honoured.
    settings = make_settings(admin_audit_dsn="postgresql+asyncpg://owner:pw@db:5432/hbd")
    async with open_container(settings, FakeRedis(), MemoryRateLimits()) as container:
        await seed(container, 1)
        async with open_audit_client(container) as client:
            await signed_in(container, client, role=AdminRole.OWNER)

            # Act
            response = await client.get(VERIFY_PATH)

    # Assert — the answer comes from asking the database, not from reading the setting.
    assert response.json()["chainProtection"] == "hmac-only"


async def test_verify_is_refused_to_a_role_without_the_cell(
    container: AdminContainer, audit_client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, audit_client, role=AdminRole.VIEWER)

    # Act
    response = await audit_client.get(VERIFY_PATH)

    # Assert
    assert response.status_code == 403
