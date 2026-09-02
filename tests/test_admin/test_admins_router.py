"""``GET /api/admins`` over the real ASGI stack — the real container, login and guard.

Two assertions carry this file, and both are about what the roster refuses to do.

**The credential is absent.** A row is seeded with a recognisable argon2 PHC string and the
whole response body is searched for it as text. That is a stronger check than reading a key
off the JSON: it also fails if the hash arrives inside a nested object, behind a
masked-looking prefix, or in an error message somebody adds later.

**A deactivated account is still listed.** It is the assertion an "active operators only"
refactor would break, and the reason it must break: those accounts own audit rows, they can
be reactivated, and a roster that omits them answers "who has access?" with a number smaller
than the number of credentials that exist.

**A defect in §12.2 is pinned here rather than papered over.** ``ADMIN_MANAGE``'s only cell
is ``_WS`` — write, step-up REQUIRED — and the router guard resolves to ``check_role``,
which holds no grant and therefore answers ``STEP_UP_REQUIRED`` to *every* caller, OWNER
included. So the roster is unreachable until the matrix grows a read cell for it, which is a
change to :mod:`hbd.admin.security.permissions` and not to this router. That refusal is
asserted as it stands, and :func:`stepped_up_app` overrides exactly that one dependency so
the projection this file exists to pin is still exercised end to end. When the cell lands,
the override comes out and nothing else here changes.

RBAC is otherwise one cell, not a row: §12.2 gives ADMIN_MANAGE to OWNER alone, so the other
three roles are asserted to be ``FORBIDDEN`` — a different refusal, for a different reason,
which the SPA must not turn into a re-authentication prompt.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Final

import httpx
import pytest
from fastapi import FastAPI

from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer
from hbd.admin.deps import get_current_admin, require_permission
from hbd.admin.routers.admins import ADMINS_PATH, build_admins_router
from hbd.admin.security.permissions import Permission
from hbd.db.enums import AdminRole
from hbd.db.models.admin_user import AdminUserRow
from tests.test_admin.conftest import NOW, ORIGIN, PASSWORD, create_account, sign_in

#: A real-shaped argon2id PHC string, distinctive enough that finding it anywhere in a
#: response body is unambiguous. It is never verified against — nothing signs in as this row.
SENTINEL_HASH: Final[str] = (
    "$argon2id$v=19$m=32768,t=2,p=1$c2VudGluZWxzYWx0YWFh$dGhpc2hhc2htdXN0bmV2ZXJzaGlw"
)

#: Field names the wire must not carry, in both spellings, since ``ApiModel`` emits camel.
FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset({"passwordHash", "password_hash"})

#: The whole field set of ``AdminAccountView``, asserted as a set: adding a field to a
#: response that deliberately withholds a credential is a decision, never a default.
EXPECTED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "username",
        "role",
        "isActive",
        "mustChangePassword",
        "lastLoginAt",
        "passwordChangedAt",
        "createdAt",
    }
)


def _mount(container: AdminContainer) -> FastAPI:
    """``create_app`` plus this router, with **no** ``prefix``.

    ``app.py`` does not include it yet — the wiring is a later step of the slice — and the
    router declares full paths because the forced-rotation gate compares
    ``scope["route"].path`` against absolute ones. The path check keeps this correct rather
    than double-registering the route on the day ``create_app`` grows the same line.
    """
    application = create_app(container=container)
    if not any(getattr(route, "path", None) == ADMINS_PATH for route in application.routes):
        application.include_router(build_admins_router())
    return application


@pytest.fixture
def admin_app(container: AdminContainer) -> FastAPI:
    """The application exactly as it will ship. Nothing overridden."""
    return _mount(container)


@pytest.fixture
def stepped_up_app(container: AdminContainer) -> FastAPI:
    """The same application with the step-up half of the router guard stood down.

    See the module docstring: §12.2 has no read cell for ADMIN_MANAGE, so ``check_role``
    refuses the OWNER too and the handler would never run. The override is keyed by a second
    ``require_permission(Permission.ADMIN_MANAGE)`` — ``RequirePermission`` is a frozen
    dataclass, so it compares and hashes equal to the instance the router declared — and it
    is replaced with ``get_current_admin``, which still authenticates. Only the matrix cell
    is bypassed; the session, the transaction and the projection are the real ones.
    """
    application = _mount(container)
    application.dependency_overrides[require_permission(Permission.ADMIN_MANAGE)] = (
        get_current_admin
    )
    return application


@pytest.fixture
async def stepped_up_client(stepped_up_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with stepped_up_app.router.lifespan_context(stepped_up_app):
        transport = httpx.ASGITransport(app=stepped_up_app)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


async def seed_account(
    container: AdminContainer,
    *,
    username: str,
    role: AdminRole = AdminRole.VIEWER,
    is_active: bool = True,
    must_change_password: bool = False,
    last_login_at: datetime | None = None,
    created_at: datetime = NOW,
) -> AdminUserRow:
    """Insert one operator through the model, so a deactivated row is reachable.

    ``accounts.create`` always writes ``is_active=True`` and there is no deactivate helper
    yet — that is a Phase 2 write — so the row is built directly. Its password hash is the
    sentinel: this account is never signed into.
    """
    async with container.session_factory.begin() as db:
        row = AdminUserRow(
            username=username,
            password_hash=SENTINEL_HASH,
            role=role,
            is_active=is_active,
            must_change_password=must_change_password,
            password_changed_at=created_at,
            last_login_at=last_login_at,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(row)
        await db.flush()
        return row


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Who may read it
# ---------------------------------------------------------------------------
async def test_the_roster_is_unreachable_until_admin_manage_grows_a_read_cell(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — §12.2's only ADMIN_MANAGE cell is _WS, and ``check_role`` holds no grant to
    # weigh, so it answers STEP_UP_REQUIRED to the OWNER as well. Pinned, not accepted: the
    # fix is a read cell in ``permissions.py``, and this assertion is what will fail — in
    # the direction that gets noticed — on the day it lands.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    response = await client.get(ADMINS_PATH)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "STEP_UP_REQUIRED"


@pytest.mark.parametrize("role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN])
async def test_a_role_without_admin_manage_is_refused_for_its_role_not_for_a_step_up(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — the two refusals must stay distinguishable: FORBIDDEN offers no remedy,
    # STEP_UP_REQUIRED opens a re-authentication prompt, and a VIEWER must not see one.
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(ADMINS_PATH)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_an_unauthenticated_caller_gets_401_not_the_roster(
    stepped_up_client: httpx.AsyncClient,
) -> None:
    # Arrange — asserted against the app whose matrix cell is stood down, so this proves
    # authentication refuses on its own rather than being masked by the step-up refusal.

    # Act
    response = await stepped_up_client.get(ADMINS_PATH)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_an_unrouted_path_under_admins_answers_in_the_error_envelope(
    container: AdminContainer, stepped_up_client: httpx.AsyncClient
) -> None:
    # Arrange — there is no ``/admins/{id}`` in this slice, and a 404 must still be the one
    # body shape every failure comes back as rather than FastAPI's own.
    await signed_in(container, stepped_up_client, role=AdminRole.OWNER)

    # Act
    response = await stepped_up_client.get(f"{ADMINS_PATH}/00000000-0000-0000-0000-000000000000")

    # Assert
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# The credential
# ---------------------------------------------------------------------------
async def test_the_password_hash_is_absent_from_the_body_rather_than_masked(
    container: AdminContainer, stepped_up_client: httpx.AsyncClient
) -> None:
    # Arrange — a recognisable PHC string on a row the roster is about to return.
    await seed_account(container, username="viewer-with-a-hash")
    await signed_in(container, stepped_up_client, role=AdminRole.OWNER)

    # Act
    response = await stepped_up_client.get(ADMINS_PATH)

    # Assert — searched as text, so a hash nested anywhere in the payload still fails.
    assert response.status_code == 200
    assert SENTINEL_HASH not in response.text
    assert "$argon2id$" not in response.text
    for item in response.json()["items"]:
        assert FORBIDDEN_KEYS.isdisjoint(item)


async def test_the_view_carries_exactly_the_fields_the_panel_renders(
    container: AdminContainer, stepped_up_client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_account(
        container,
        username="support-account",
        role=AdminRole.SUPPORT,
        must_change_password=True,
        last_login_at=NOW - timedelta(hours=3),
        created_at=NOW - timedelta(days=2),
    )
    await signed_in(container, stepped_up_client, role=AdminRole.OWNER)

    # Act
    body = (await stepped_up_client.get(ADMINS_PATH)).json()

    # Assert
    seeded = next(item for item in body["items"] if item["username"] == "support-account")
    assert set(seeded) == EXPECTED_KEYS
    assert seeded["role"] == AdminRole.SUPPORT.value
    assert seeded["isActive"] is True
    assert seeded["mustChangePassword"] is True
    assert seeded["lastLoginAt"] is not None


async def test_an_account_that_has_never_signed_in_reports_null_rather_than_a_stamp(
    container: AdminContainer, stepped_up_client: httpx.AsyncClient
) -> None:
    # Arrange — "never signed in" and "signed in long ago" are different facts after a
    # handover, and only one of them is a credential nobody has ever used.
    await seed_account(container, username="never-used")
    await signed_in(container, stepped_up_client, role=AdminRole.OWNER)

    # Act
    body = (await stepped_up_client.get(ADMINS_PATH)).json()

    # Assert
    seeded = next(item for item in body["items"] if item["username"] == "never-used")
    assert seeded["lastLoginAt"] is None


# ---------------------------------------------------------------------------
# Who is on it
# ---------------------------------------------------------------------------
async def test_a_deactivated_account_is_listed_rather_than_hidden(
    container: AdminContainer, stepped_up_client: httpx.AsyncClient
) -> None:
    # Arrange — it still owns audit rows and can be reactivated, so it is a credential that
    # exists. A roster that omitted it would undercount who has access.
    await seed_account(container, username="departed", role=AdminRole.ADMIN, is_active=False)
    await signed_in(container, stepped_up_client, role=AdminRole.OWNER)

    # Act
    body = (await stepped_up_client.get(ADMINS_PATH)).json()

    # Assert
    departed = next(item for item in body["items"] if item["username"] == "departed")
    assert departed["isActive"] is False


async def test_the_roster_is_oldest_first_so_adding_an_account_does_not_reshuffle_it(
    container: AdminContainer, stepped_up_client: httpx.AsyncClient
) -> None:
    # Arrange — usernames are what an operator scans, but sorting by them would move every
    # row each time somebody is added.
    await seed_account(container, username="zulu", created_at=NOW - timedelta(days=3))
    await seed_account(container, username="alpha", created_at=NOW - timedelta(days=1))
    await signed_in(container, stepped_up_client, role=AdminRole.OWNER)

    # Act
    body = (await stepped_up_client.get(ADMINS_PATH)).json()

    # Assert
    assert [item["username"] for item in body["items"]][:2] == ["zulu", "alpha"]


async def test_the_reader_sees_their_own_account_on_the_roster(
    container: AdminContainer, stepped_up_client: httpx.AsyncClient
) -> None:
    # Arrange — the owner is an operator too, and a roster that filtered ``self`` would
    # answer "who has access?" one short.
    await seed_account(container, username="a-viewer")
    await signed_in(container, stepped_up_client, role=AdminRole.OWNER)

    # Act
    body = (await stepped_up_client.get(ADMINS_PATH)).json()

    # Assert
    assert {item["username"] for item in body["items"]} == {"a-viewer", "owner-account"}
