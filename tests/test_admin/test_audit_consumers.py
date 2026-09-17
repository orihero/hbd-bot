"""§12.6's first audit consumers actually write rows.

Before this pass the entire audit apparatus — the HMAC chain, the advisory lock, the
``REVOKE``, the anchors, ``/audit/verify`` — protected an empty table. ``append()`` had zero
production callers: a login, a failed login, a logout, a password change, a step-up grant and
a ``bootstrap --reset-owner`` all left no trace anywhere. An audit log with no writers is a
table, not a control, and every downstream control that reads it (the reveal budget, the
dashboard's sparkline, the chain badge) was measuring zero.

Two properties are asserted throughout, and the second is the one that is easy to get wrong:

* every route writes exactly one row, with the right action and outcome;
* a **refused** request still writes its row. Refusals raise, and the request transaction
  rolls back on an exception, so a failure row written inside it would vanish along with the
  failure. Those rows go through their own committed transaction — see
  ``bayram.admin.audit_sink``.
"""

from __future__ import annotations

import httpx
import pytest
import sqlalchemy as sa

from bayram.admin.container import AdminContainer
from bayram.admin.routers.billing import (
    INTENT_NOTIFY_PATH,
    RAIL_PAUSE_PATH,
    RAIL_RESUME_PATH,
)
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import AdminAuditRow, AuditOutcome
from tests.test_admin.conftest import (
    NOW,
    ORIGIN,
    PASSWORD,
    USERNAME,
    create_account,
    csrf_headers,
    sign_in,
)
from tests.test_db.rail_helpers import add, make_intent, make_topup_receipt, settle


async def _rows(container: AdminContainer) -> list[AdminAuditRow]:
    async with container.session_factory.begin() as db:
        statement = sa.select(AdminAuditRow).order_by(AdminAuditRow.seq)
        return list((await db.execute(statement)).scalars().all())


async def _actions(container: AdminContainer) -> list[AuditAction]:
    return [row.action for row in await _rows(container)]


async def test_a_successful_login_is_audited(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await create_account(container)

    # Act
    assert (await sign_in(client)).status_code == 200

    # Assert
    rows = await _rows(container)
    assert [row.action for row in rows] == [AuditAction.LOGIN_SUCCESS]
    assert rows[0].outcome is AuditOutcome.OK
    assert rows[0].actor_username == USERNAME
    assert rows[0].actor_id is not None
    assert rows[0].subject_type == "admin"


async def test_a_failed_login_is_audited_even_though_the_request_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the case a request-scoped write loses: the handler raises, so the
    # transaction that would have carried the row rolls back with it.
    await create_account(container)

    # Act
    response = await client.post(
        "/api/auth/login",
        json={"username": USERNAME, "password": "not-the-password"},
        headers={"Origin": ORIGIN},
    )

    # Assert
    assert response.status_code == 401
    rows = await _rows(container)
    assert [row.action for row in rows] == [AuditAction.LOGIN_FAILURE]
    assert rows[0].outcome is AuditOutcome.DENIED


async def test_a_login_for_an_unknown_account_is_audited_without_inventing_an_actor(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await create_account(container)

    # Act
    response = await client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )

    # Assert — no operator row exists, so ``actor_id`` is NULL and the username is the
    # attempted one. The FK is RESTRICT; a fabricated id would fail the insert.
    assert response.status_code == 401
    rows = await _rows(container)
    assert [row.action for row in rows] == [AuditAction.LOGIN_FAILURE]
    assert rows[0].actor_id is None
    assert rows[0].actor_username == "nobody"


async def test_a_rate_limited_login_is_audited_as_limited_not_as_a_failure(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — §12.6 names three login outcomes, and they are three different incidents.
    await create_account(container)
    for _ in range(30):
        response = await client.post(
            "/api/auth/login",
            json={"username": USERNAME, "password": "wrong"},
            headers={"Origin": ORIGIN},
        )
        if response.status_code == 429:
            break

    # Assert
    assert response.status_code == 429
    actions = await _actions(container)
    assert actions[-1] is AuditAction.LOGIN_RATE_LIMITED
    assert AuditAction.LOGIN_FAILURE in actions


async def test_a_logout_is_audited(container: AdminContainer, client: httpx.AsyncClient) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post("/api/auth/logout", headers=csrf_headers(client))

    # Assert
    assert response.status_code == 204
    assert await _actions(container) == [AuditAction.LOGIN_SUCCESS, AuditAction.LOGOUT]


async def test_a_password_change_is_audited(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post(
        "/api/auth/password",
        json={"currentPassword": PASSWORD, "newPassword": "a-brand-new-password-entirely"},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 200
    rows = await _rows(container)
    assert [row.action for row in rows] == [
        AuditAction.LOGIN_SUCCESS,
        AuditAction.ADMIN_PASSWORD_CHANGE,
    ]
    assert rows[-1].outcome is AuditOutcome.OK
    # The field NAME, never the value (§12.4). A password in an audit row is an incident.
    assert rows[-1].field_names == ["password_hash"]


async def test_a_wrong_current_password_is_audited_as_denied(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post(
        "/api/auth/password",
        json={"currentPassword": "wrong", "newPassword": "a-brand-new-password-entirely"},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 403
    rows = await _rows(container)
    assert rows[-1].action is AuditAction.ADMIN_PASSWORD_CHANGE
    assert rows[-1].outcome is AuditOutcome.DENIED


async def test_a_granted_step_up_is_audited_with_its_scope(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post(
        "/api/auth/step-up",
        json={
            "scope": "reveal",
            "subjectId": "1c9e1a5e-0000-4000-8000-000000000001",
            "password": PASSWORD,
        },
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 200
    rows = await _rows(container)
    assert rows[-1].action is AuditAction.STEP_UP_SUCCESS
    assert rows[-1].outcome is AuditOutcome.OK
    assert rows[-1].subject_id == "1c9e1a5e-0000-4000-8000-000000000001"


async def test_a_refused_step_up_is_audited_as_a_failure(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — this is the row an investigation wants most: somebody holding the cookie
    # tried to escalate and could not produce the password.
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post(
        "/api/auth/step-up",
        json={
            "scope": "reveal",
            "subjectId": "1c9e1a5e-0000-4000-8000-000000000001",
            "password": "not-the-password",
        },
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 403
    rows = await _rows(container)
    assert rows[-1].action is AuditAction.STEP_UP_FAILURE
    assert rows[-1].outcome is AuditOutcome.DENIED


async def test_a_permission_refusal_is_audited(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — §12.2 gives AUDIT_READ to OWNER and ADMIN only.
    await create_account(container, role=AdminRole.VIEWER)
    await sign_in(client)

    # Act
    response = await client.get("/api/audit")

    # Assert
    assert response.status_code == 403
    rows = await _rows(container)
    assert rows[-1].action is AuditAction.PERMISSION_DENIED
    assert rows[-1].outcome is AuditOutcome.DENIED


async def test_the_chain_still_verifies_after_a_login_password_change_and_logout(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the sequence §12.6 names, written through the real routes rather than by a
    # test helper, because a second writer that skipped the HMAC is the failure mode.
    from bayram.db.admin.audit import verify_chain

    await create_account(container)
    await sign_in(client)
    await client.post(
        "/api/auth/password",
        json={"currentPassword": PASSWORD, "newPassword": "a-brand-new-password-entirely"},
        headers=csrf_headers(client),
    )
    await client.post("/api/auth/logout", headers=csrf_headers(client))

    # Act
    async with container.session_factory.begin() as db:
        result = await verify_chain(
            db,
            key=container.settings.admin_audit_hmac_key.get_secret_value(),
            is_dsn_configured=False,
        )

    # Assert
    assert result.is_ok is True
    assert result.checked_rows >= 3


@pytest.mark.parametrize("username", ["a" * 64, "sk-or-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"])
async def test_a_credential_shaped_username_does_not_take_the_login_route_down(
    container: AdminContainer, client: httpx.AsyncClient, username: str
) -> None:
    # Arrange — ``actor_username`` on a failed login is attacker-supplied, and ``append``
    # REFUSES a credential-shaped value by raising. That refusal must not become a 500 on
    # the one unauthenticated route in the API.
    await create_account(container)

    # Act
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )

    # Assert — the sign-in is refused the way every sign-in is refused, not with a 500.
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# The payment rail's two writers — §12.6 for a surface that is not authentication
# ---------------------------------------------------------------------------
async def test_flipping_the_rail_switch_is_audited_against_the_configuration(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """A Redis key with no history at all, made accountable by the one table that has some.

    The switch itself records nothing — ``bayram.payme.pause`` writes a bare key with no TTL and
    no trace of who set it — so this row is the ONLY durable answer to "who paused the rail, and
    why". That is also why pause and resume are two paths rather than one body with a boolean:
    a ``{"isPaused": false}`` would be a resume audited as a pause, and there is nothing else
    anywhere that could contradict it.

    ``subject_type`` is ``"config"`` from the closed vocabulary rather than a member of its own:
    the switch IS configuration, and there is exactly one per deployment, so "every time anybody
    touched it" stays an indexed equality on ``(subject_type, subject_id)``.
    """
    # Arrange
    await create_account(container, role=AdminRole.ADMIN)
    assert (await sign_in(client)).status_code == 200

    # Act — pause, then resume, so the ORDER is asserted as well as the rows.
    for path in (RAIL_PAUSE_PATH, RAIL_RESUME_PATH):
        response = await client.post(
            path,
            json={"reasonCode": AuditReasonCode.INCIDENT.value, "reasonRef": "INC-441"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, path

    # Assert
    rows = [row for row in await _rows(container) if row.action is not AuditAction.LOGIN_SUCCESS]
    assert [row.action for row in rows] == [AuditAction.RAIL_PAUSED, AuditAction.RAIL_RESUMED]
    for row in rows:
        assert row.outcome is AuditOutcome.OK
        assert row.subject_type == "config"
        assert row.subject_id == "payme_rail"
        assert row.actor_id is not None
        assert row.reason_ref == "INC-441"
        # No ``field_names``: the vocabulary names DATABASE columns and what moved is a Redis
        # key no column corresponds to. Naming one would be a shape the log cannot honour.
        assert row.field_names is None


async def test_re_sending_a_confirmation_is_audited_against_the_payment(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """And the ``subject_id`` is asserted as STORED rather than as passed.

    ``db/admin/audit.py::_CREDENTIAL_SHAPES`` refuses any unbroken 40-character
    ``[A-Za-z0-9_-]`` run and any 64 hex characters, and ``audit_sink._append`` answers a
    refusal by logging at ERROR and rewriting the row with ``subject_id=None`` — so an action
    can succeed while its audit trail quietly stops naming what it was about. A dashed 36-char
    UUID is neither shape; the 24-hex ``public_ref`` is the value that would have been closer to
    the line, and the intent's ``idempotency_key`` is not a candidate at all because it contains
    the customer's Telegram id.
    """
    # Arrange — one settled payment nobody has announced, which is the population served.
    intent = settle(make_intent(now=NOW), at=NOW)
    await add(container.session_factory, intent, make_topup_receipt(intent, at=NOW))
    await create_account(container, role=AdminRole.SUPPORT)
    assert (await sign_in(client)).status_code == 200

    # Act
    response = await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=intent.id),
        json={"reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 200
    [row] = [
        entry for entry in await _rows(container) if entry.action is AuditAction.PAYMENT_NOTIFY
    ]
    assert row.subject_type == "payment"
    assert row.subject_id is not None
    assert row.subject_id == str(intent.id)
    assert row.record_count == 1
    assert row.outcome is AuditOutcome.OK
