"""§12.2 as an *outcome* table, parameterised over all four roles — §14 Slice 1c.

``test_permissions.py`` already restates the plan's table cell by cell in the plan's own
``M``/``R``/``W``/``W+S`` notation and compares it to :data:`RBAC_MATRIX`. This file asks the
other question, the one an operator would recognise: **for each capability and each role,
what actually happens?** :data:`EXPECTED_DECISIONS` is that answer written down once — one
:class:`AccessDecision` per cell, in role order — and everything below is checked against it,
first as a pure function and then over HTTP against every route ``create_app`` serves.

The two are not the same assertion. A cell can be transcribed correctly and still produce
the wrong refusal: ``FORBIDDEN`` and ``STEP_UP_REQUIRED`` are both 403 and differ only in
what the SPA does next — one is a dead end, the other opens a re-authentication prompt at
somebody who was never eligible in the first place. So the two refusals are distinguished
everywhere here, never collapsed into "not 200".

**Two rows come from §6.8 rather than §12.2, and the split is the point.** §12.2 folded the
roster read and the four account writes into one ``W+S`` row; read literally that makes ``GET /api/admins`` reachable by nobody, because a router-level guard holds no subject
and therefore no grant to weigh, and answers ``STEP_UP_REQUIRED`` to an OWNER for ever. §6.8
line 949 lists that GET as a bare owner ``W`` and marks each of the four writes ``W +S``
separately. The endpoint table was ruled the authority, so ``ADMIN_READ`` carries the read
(OWNER → ``ALLOWED``) and ``ADMIN_MANAGE`` keeps the ``W+S`` cell the Phase 2 writes will
declare (OWNER → ``STEP_UP_REQUIRED`` until one presents a grant). Both rows are below, and
``test_admins_router`` asserts the same 200 from the other side.

Roles are never compared or ordered. ``AdminRole`` is a ``StrEnum`` whose ordering is
documentation only, and a test that derived "OWNER may do at least what ADMIN may" would be
asserting a ladder the matrix deliberately does not have (VIEWER holds ``SESSION_SELF`` as
``W``; OWNER's ``AUDIT_READ`` is ``R`` where ADMIN's is ``M``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Final
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI

from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer
from hbd.admin.deps import require_permission
from hbd.admin.errors import AdminErrorCode
from hbd.admin.routers.admins import ADMINS_PATH
from hbd.admin.routers.audit import AUDIT_PATH
from hbd.admin.routers.reveal import REVEAL_PATH
from hbd.admin.routers.users import WIZARD_STATE_PATH
from hbd.admin.security.permissions import (
    RBAC_MATRIX,
    ROLE_PERMISSIONS,
    AccessDecision,
    Permission,
    check_role,
    grant_for,
    is_permitted,
)
from hbd.db.enums import AdminRole, AuditAction, AuditReasonCode
from hbd.db.models.admin_audit import AdminAuditRow, AuditOutcome
from tests.test_admin.conftest import (
    ORIGIN,
    PASSWORD,
    create_account,
    csrf_headers,
    sign_in,
)
from tests.test_admin.test_routes_enumeration import EXEMPT_PATHS, MOUNTED_ROUTES

#: §12.2's column order. Named rather than inferred, because :data:`EXPECTED_DECISIONS` is
#: positional and a silent reordering would move every cell one role to the left.
ROLES: Final[tuple[AdminRole, ...]] = (
    AdminRole.VIEWER,
    AdminRole.SUPPORT,
    AdminRole.ADMIN,  # the plan's OPERATOR; see ``permissions.py``'s module docstring.
    AdminRole.OWNER,
)

#: Shorthands for the three answers a router-level guard can give.
_OK: Final[AccessDecision] = AccessDecision.ALLOWED
_NO: Final[AccessDecision] = AccessDecision.FORBIDDEN_ROLE
_SU: Final[AccessDecision] = AccessDecision.STEP_UP_REQUIRED

#: §12.2, as the decision each cell produces. ``—`` (no cell) is :data:`_NO`; a read or a
#: plain write is :data:`_OK`; anything carrying ``+S`` — ``W+S``, ``W+S (fresh)`` or
#: ``A+S`` — is :data:`_SU`, because a guard with no subject has no grant to weigh and says
#: so rather than pretending to have checked one.
#:
#: §12.2 row 14 is one line reading ``A+S / W+S``; the code splits it into
#: ``MODERATION_REVEAL`` and ``MODERATION_DECIDE``, which is a refinement rather than a
#: disagreement — both cells land on the same decision either way.
EXPECTED_DECISIONS: Final[
    Mapping[Permission, tuple[AccessDecision, AccessDecision, AccessDecision, AccessDecision]]
] = {
    Permission.SESSION_SELF: (_OK, _OK, _OK, _OK),
    Permission.DASHBOARD_READ: (_OK, _OK, _OK, _OK),
    Permission.RECORDS_READ: (_OK, _OK, _OK, _OK),
    Permission.CHAT_INDEX_READ: (_OK, _OK, _OK, _OK),
    Permission.WIZARD_STATE_READ: (_OK, _OK, _OK, _OK),
    Permission.MODERATION_QUEUE_READ: (_OK, _OK, _OK, _OK),
    Permission.CONFIG_READ: (_OK, _OK, _OK, _OK),
    Permission.RETENTION_READ: (_OK, _OK, _OK, _OK),
    # ``POST /api/reveal``'s row, split in two for the reason the media pair below is —
    # except that this one had no §6.8 fallback: §12.2 line 1886 routes every ``A`` cell
    # through the one endpoint and §6.8 line 928 gives it one ``S +S`` row. So
    # REVEAL_PERSONAL_DATA_READ is the role half the router declares: SUPPORT and above get
    # through to the handler, VIEWER is FORBIDDEN — a dead end the SPA must not turn into a
    # re-authentication prompt, because no grant would ever help them.
    Permission.REVEAL_PERSONAL_DATA_READ: (_NO, _OK, _OK, _OK),
    # …and this is what a *router* guard would answer for the ``A+S`` half, which is why it
    # is still ``_SU``: no route declares this cell. ``POST /api/reveal``'s handler enforces
    # it with ``deps.enforce_step_up`` on the subject in the body, and
    # ``test_reveal.py`` drives that through the real ``/auth/step-up`` route.
    Permission.REVEAL_PERSONAL_DATA: (_NO, _SU, _SU, _SU),
    # §12.2 row 10 split in two, exactly as the roster row below was, and for exactly the
    # same reason: an ``A+S`` cell decided by ``check_role`` is a permanent 403, because a
    # router guard holds no subject and therefore no grant. REVEAL_MEDIA_READ is the role
    # half that ``GET /api/assets/{id}/stream`` and ``/text`` declare at the router — SUPPORT
    # and above, no step-up, so an eligible operator gets through to the handler…
    Permission.REVEAL_MEDIA_READ: (_NO, _OK, _OK, _OK),
    # …and REVEAL_MEDIA keeps the ``A+S`` cell, which those handlers enforce themselves on
    # the asset id they have read. The decision below is what a *router* guard would answer,
    # which is why it is still ``_SU``: no route declares this cell.
    Permission.REVEAL_MEDIA: (_NO, _SU, _SU, _SU),
    Permission.ORDER_RETRY: (_NO, _NO, _OK, _OK),
    Permission.ORDER_FORCE_DELIVER: (_NO, _NO, _SU, _SU),
    # …and this is what a router guard would answer for it, which is why it is ``_SU``: no
    # route declares this cell. ``POST /users/{id}/block`` and ``/unblock`` declare the role
    # half below and enforce this one in the handler, on the Telegram id in the path.
    Permission.USER_BLOCK: (_NO, _NO, _SU, _SU),
    # The role half the two block routes actually declare: ADMIN and OWNER reach the handler,
    # VIEWER and SUPPORT are FORBIDDEN — a dead end the SPA must not turn into a
    # re-authentication prompt, because no grant would ever help them.
    Permission.USER_BLOCK_WRITE: (_NO, _NO, _OK, _OK),
    # The pair §12.2 has no row for at all; ``permissions.py`` argues the cell. Same shape:
    # the ``W+S`` half is enforced by ``POST /users/{id}/credits/grant``'s handler and the
    # role half is what its router declares.
    Permission.CREDIT_GRANT: (_NO, _NO, _SU, _SU),
    Permission.CREDIT_GRANT_WRITE: (_NO, _NO, _OK, _OK),
    # The broadcast trio (BROADCAST_SPEC §3.1). The read is allowed at every role — a
    # campaign record carries no customer data and reviewing what went out is the VIEWER's
    # whole job. The write pair is split like the two above it: BROADCAST_WRITE is what the
    # write routes declare, and BROADCAST_SEND is the ``W+S`` cell
    # ``POST /broadcasts/{id}/schedule`` enforces in the handler on the campaign id, which is
    # why a router guard would answer ``_SU`` for it.
    Permission.BROADCAST_READ: (_OK, _OK, _OK, _OK),
    Permission.BROADCAST_WRITE: (_NO, _NO, _OK, _OK),
    Permission.BROADCAST_SEND: (_NO, _NO, _SU, _SU),
    Permission.MODERATION_REVEAL: (_NO, _NO, _SU, _SU),
    Permission.MODERATION_DECIDE: (_NO, _NO, _SU, _SU),
    Permission.RETENTION_SWEEP: (_NO, _NO, _OK, _OK),
    Permission.AUDIT_READ: (_NO, _NO, _OK, _OK),
    Permission.REVEAL_VOLUME_READ: (_NO, _NO, _OK, _OK),
    Permission.EXPORT_AGGREGATE: (_NO, _NO, _OK, _OK),
    Permission.USER_PURGE: (_NO, _NO, _NO, _SU),
    Permission.CONFIG_WRITE: (_NO, _NO, _NO, _SU),
    Permission.ORDER_EVIDENCE_EXPORT: (_NO, _NO, _NO, _SU),
    Permission.AUDIT_EXPORT: (_NO, _NO, _NO, _SU),
    # The §6.8 pair — see the module docstring. The roster read is an owner ``W`` with no
    # ``+S``, so OWNER is ALLOWED and the other three are refused for their ROLE, which is
    # the refusal the SPA must not turn into a re-authentication prompt.
    Permission.ADMIN_READ: (_NO, _NO, _NO, _OK),
    # The four account writes' cell. No route declares it in this slice; the decision it
    # produces is asserted here and over HTTP by ``step_up_guarded_client`` below.
    Permission.ADMIN_MANAGE: (_NO, _NO, _NO, _SU),
}

#: Every ``(permission, role)`` pair, flattened once so the parameter list is the matrix.
_CELLS: Final[tuple[tuple[Permission, AdminRole, AccessDecision], ...]] = tuple(
    (permission, role, decision)
    for permission, decisions in EXPECTED_DECISIONS.items()
    for role, decision in zip(ROLES, decisions, strict=True)
)

#: The status and code the HTTP layer answers for each decision (§6.2, ``deps.ACCESS_ERROR_CODES``).
_REFUSALS: Final[Mapping[AccessDecision, AdminErrorCode]] = {
    AccessDecision.FORBIDDEN_ROLE: AdminErrorCode.FORBIDDEN,
    AccessDecision.STEP_UP_REQUIRED: AdminErrorCode.STEP_UP_REQUIRED,
}

#: Path parameters for the sweep. Deliberately identifiers no row uses: this file is about
#: who is refused, and a 404 from a handler that ran is as good an "allowed" as a 200.
_IDENTIFIERS: Final[Mapping[str, object]] = {
    "order_id": uuid4(),
    "asset_id": uuid4(),
    "attempt_id": uuid4(),
    "telegram_user_id": 770_000_123,
    "broadcast_id": uuid4(),
}


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


@pytest.fixture
def step_up_guarded_app(container: AdminContainer) -> FastAPI:
    """The application with one route moved onto a cell that demands a step-up.

    Every route this slice mounts is a read, and after the §6.8 split none of their cells
    carries ``+S`` — so ``STEP_UP_REQUIRED`` has no mounted route left to come out of, and
    the two refusals would stop being told apart anywhere on the wire. Rather than assert
    that distinction against a pure function only, the roster's guard is swapped for
    ``require_permission(ADMIN_MANAGE)``: the same ``RequirePermission`` class, the same
    ``check_role`` call, the same audit and envelope path, on the very cell the four Phase 2
    account writes will declare. ``RequirePermission`` is a frozen dataclass, so the key
    built here compares and hashes equal to the instance ``build_admins_router`` declared.

    Only the cell is swapped. The session, the transaction and the handler are the real ones,
    and when a route that genuinely carries a ``W+S`` cell ships, this fixture goes away.
    """
    application = create_app(container=container)
    application.dependency_overrides[require_permission(Permission.ADMIN_READ)] = (
        require_permission(Permission.ADMIN_MANAGE)
    )
    return application


@pytest.fixture
async def step_up_guarded_client(step_up_guarded_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with step_up_guarded_app.router.lifespan_context(step_up_guarded_app):
        transport = httpx.ASGITransport(app=step_up_guarded_app)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


async def refusals(container: AdminContainer) -> list[AdminAuditRow]:
    """Every ``PERMISSION_DENIED`` row, oldest first."""
    async with container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.action == AuditAction.PERMISSION_DENIED)
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


# ---------------------------------------------------------------------------
# The table against the module that ships it
# ---------------------------------------------------------------------------
def test_the_outcome_table_covers_every_permission_and_no_others() -> None:
    # Arrange / Act — a permission added to the enum with no row here would be silently
    # unasserted, which is how a new capability reaches a role nobody reviewed.

    # Assert
    assert set(EXPECTED_DECISIONS) == set(Permission) == set(RBAC_MATRIX)


@pytest.mark.parametrize(("permission", "role", "expected"), _CELLS)
def test_the_router_level_guard_answers_the_table(
    permission: Permission, role: AdminRole, expected: AccessDecision
) -> None:
    # Arrange / Act — ``check_role`` is what ``deps.RequirePermission`` calls, so this is the
    # decision every mounted route makes before any handler runs.
    decision = check_role(permission, role)

    # Assert
    assert decision is expected, (permission, role)


@pytest.mark.parametrize(("permission", "role", "expected"), _CELLS)
def test_a_cell_exists_exactly_where_the_table_is_not_a_role_refusal(
    permission: Permission, role: AdminRole, expected: AccessDecision
) -> None:
    # Arrange / Act — the em dash of §12.2 and the absent cell of ``RBAC_MATRIX`` must be
    # the same thing, or one of the two tables is describing a role the other does not.
    granted = grant_for(permission, role) is not None

    # Assert
    assert granted is (expected is not AccessDecision.FORBIDDEN_ROLE)
    assert is_permitted(permission, role) is granted
    assert (permission in ROLE_PERMISSIONS[role]) is granted


def test_no_row_is_a_denial_for_every_role() -> None:
    # Arrange / Act — an all-``—`` row is a permission nobody can ever hold, which is a bug
    # rather than a strict setting: the route behind it is dead at every role.

    # Assert
    for permission, decisions in EXPECTED_DECISIONS.items():
        assert set(decisions) != {AccessDecision.FORBIDDEN_ROLE}, permission


# ---------------------------------------------------------------------------
# Every mounted route, every role, over HTTP
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ROLES, ids=[role.value for role in ROLES])
async def test_every_mounted_route_answers_the_matrix_at_this_role(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — one sign-in, then every GET the application serves. The routes come from the
    # enumeration test's frozen table, so a route added without a matrix decision fails
    # there first and here second.
    await signed_in(container, client, role=role)

    # Act / Assert
    for method, template, permission in sorted(MOUNTED_ROUTES):
        if method != "GET" or template in EXEMPT_PATHS:
            continue
        assert permission is not None, template
        path = template.format(**_IDENTIFIERS)
        response = await client.get(path)
        expected = EXPECTED_DECISIONS[permission][ROLES.index(role)]
        if expected is AccessDecision.ALLOWED:
            # 200, 404 and 422 are all "the handler ran"; 401 and 403 are not.
            assert response.status_code not in (401, 403), (path, role)
            continue
        assert response.status_code == 403, (path, role)
        assert response.json()["error"]["code"] == _REFUSALS[expected].value, (path, role)


@pytest.mark.parametrize("role", ROLES, ids=[role.value for role in ROLES])
async def test_the_reveal_route_answers_both_halves_of_its_split_row(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — the sweep above walks GETs only, and ``POST /api/reveal`` is the one route
    # whose §12.2 row was split across two permissions, so neither half is asserted over HTTP
    # anywhere else. The two answers must stay distinguishable: VIEWER holds no reveal cell
    # at all and gets FORBIDDEN, which the SPA must NOT turn into a re-authentication prompt
    # because no grant would ever help them; the other three hold the cell, reach the
    # handler, and are refused there for want of a scoped grant. A handler that forgot
    # ``enforce_step_up`` would answer 404 or 200 here instead.
    await signed_in(container, client, role=role)

    # Act — a well-shaped body, so a 403 is the guard's answer and not the request model's.
    response = await client.post(
        REVEAL_PATH,
        json={
            "subjectType": "order",
            "subjectId": str(_IDENTIFIERS["order_id"]),
            "fields": ["briefs.note"],
            "reasonCode": AuditReasonCode.SUPPORT_INVESTIGATION.value,
        },
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    # Assert
    role_half = EXPECTED_DECISIONS[Permission.REVEAL_PERSONAL_DATA_READ][ROLES.index(role)]
    expected = AccessDecision.STEP_UP_REQUIRED if role_half is AccessDecision.ALLOWED else role_half
    assert response.status_code == 403, role
    assert response.json()["error"]["code"] == _REFUSALS[expected].value, role


async def test_an_owner_reads_the_roster_without_re_authenticating(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — §6.8 line 949's ``W`` with no ``+S``, over the real stack. Asserted here as
    # well as in ``test_admins_router`` because this is the file that would have to change
    # if anyone folded ADMIN_READ back into ADMIN_MANAGE's ``W+S`` cell.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    audit = await client.get(AUDIT_PATH)
    roster = await client.get(ADMINS_PATH)

    # Assert
    assert audit.status_code == 200
    assert roster.status_code == 200
    assert await refusals(container) == []


async def test_a_role_refusal_and_a_step_up_refusal_are_told_apart_on_the_wire(
    container: AdminContainer, step_up_guarded_client: httpx.AsyncClient
) -> None:
    # Arrange — the distinction the SPA branches on: FORBIDDEN is a dead end, and
    # STEP_UP_REQUIRED opens a re-authentication prompt. Both answers come from one route
    # here, standing on the ADMIN_MANAGE cell (see ``step_up_guarded_app``), because the two
    # roles are what separate them: a SUPPORT holds no cell at all, and an OWNER holds one
    # whose step-up this request has not presented.
    await signed_in(container, step_up_guarded_client, role=AdminRole.SUPPORT)
    forbidden = await step_up_guarded_client.get(ADMINS_PATH)
    step_up_guarded_client.cookies.clear()
    await signed_in(container, step_up_guarded_client, role=AdminRole.OWNER)

    # Act
    step_up = await step_up_guarded_client.get(ADMINS_PATH)

    # Assert
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value
    assert step_up.status_code == 403
    assert step_up.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value


# ---------------------------------------------------------------------------
# §12.6 — the refusal is the audit row that matters most
# ---------------------------------------------------------------------------
async def test_a_role_refusal_writes_its_own_audit_row(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a VIEWER has no AUDIT_READ cell at all.
    await signed_in(container, client, role=AdminRole.VIEWER)

    # Act
    response = await client.get(AUDIT_PATH)

    # Assert — written in its own committed transaction, so it survives the rollback the
    # refusal itself causes.
    assert response.status_code == 403
    rows = await refusals(container)
    assert len(rows) == 1
    assert rows[0].outcome is AuditOutcome.DENIED
    assert rows[0].actor_role is AdminRole.VIEWER
    assert rows[0].error_code == AdminErrorCode.FORBIDDEN.value


async def test_a_step_up_refusal_is_audited_as_a_step_up_rather_than_a_role_failure(
    container: AdminContainer, step_up_guarded_client: httpx.AsyncClient
) -> None:
    # Arrange — the audit row has to carry the same distinction the response does, or the
    # log cannot tell "was never eligible" from "did not re-authenticate". Taken against the
    # ADMIN_MANAGE cell, which is the one that still produces this refusal.
    await signed_in(container, step_up_guarded_client, role=AdminRole.OWNER)

    # Act
    response = await step_up_guarded_client.get(ADMINS_PATH)

    # Assert
    assert response.status_code == 403
    rows = await refusals(container)
    assert len(rows) == 1
    assert rows[0].actor_role is AdminRole.OWNER
    assert rows[0].error_code == AdminErrorCode.STEP_UP_REQUIRED.value


async def test_an_allowed_request_writes_no_refusal_row(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a refusal log that also records successes is a log nobody reads.
    await signed_in(container, client, role=AdminRole.VIEWER)

    # Act
    response = await client.get(WIZARD_STATE_PATH.format(**_IDENTIFIERS))

    # Assert
    assert response.status_code == 200
    assert await refusals(container) == []
