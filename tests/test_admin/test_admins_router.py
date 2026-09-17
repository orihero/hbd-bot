"""``/api/admins`` over the real ASGI stack — the real container, login, guard and step-up.

Three assertions carry this file: one about who reaches the roster, and two about what it
refuses to put on the wire.

**The credential is absent.** A row is seeded with a recognisable argon2 PHC string and the
whole response body is searched for it as text. That is a stronger check than reading a key
off the JSON: it also fails if the hash arrives inside a nested object, behind a
masked-looking prefix, or in an error message somebody adds later.

**A deactivated account is still listed.** It is the assertion an "active operators only"
refactor would break, and the reason it must break: those accounts own audit rows, they can
be reactivated, and a roster that omits them answers "who has access?" with a number smaller
than the number of credentials that exist.

**An OWNER reads it without re-authenticating, and that is asserted first.** The guard is
``require_permission(ADMIN_READ)``, whose cell is §6.8 line 949's bare owner ``W`` — no
``+S``. It matters that the assertion is a 200 over the real stack rather than a decision
from ``check_role``: the router guard resolves to ``check_role``, which holds no grant and
answers ``STEP_UP_REQUIRED`` to any cell carrying a step-up requirement, so had the roster
stayed on ``ADMIN_MANAGE``'s ``W+S`` cell it would be unreachable by everybody — a granted,
unexpired, correctly-scoped ``admin.manage`` grant included. ``ADMIN_MANAGE`` keeps that
cell for the four account writes; this route no longer declares it, and every test below
signs in as an ordinary OWNER through the real login rather than standing a dependency down.

RBAC is otherwise one cell, not a row: the read is OWNER's alone, so the other three roles
are asserted to be ``FORBIDDEN`` — a different refusal, for a different reason, which the
SPA must not turn into a re-authentication prompt.

The create half below adds four claims of its own, each driven through the real
``POST /api/auth/step-up`` rather than by writing a grant into a session row:

**The step-up is scoped to the username, and a grant for another one does not spend here.**
It is the only subject-scoped action in the panel whose subject does not exist yet, so the
scope is the name the operator typed — which means changing that name after re-authenticating
has to stop the create rather than quietly produce a different account.

**The account that comes out can sign in exactly once before it must replace its password.**
That is the whole point of an owner-chosen credential, and it is asserted end to end: the
real login route, the real argon2 verify, and ``mustChangePassword`` coming back true.

**OWNER is refused with a sentence.** ``ix_admin_users_active_owner`` permits one active
owner, and the panel is not where a handover happens; the refusal names the CLI that is.

**Nothing on any path puts the password anywhere it could be read back.** The response body
and every audit row written by the whole flow are searched for it as text, which also fails
if it arrives inside a nested object or in an error message somebody adds later.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

import httpx
import pytest
import sqlalchemy as sa

from bayram.admin.container import AdminContainer
from bayram.admin.routers.admins import ADMINS_PATH
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import AdminAuditRow, AuditOutcome
from bayram.db.models.admin_user import AdminUserRow
from tests.test_admin.conftest import NOW, PASSWORD, create_account, csrf_headers, sign_in

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
async def test_an_owner_reads_the_roster_with_no_step_up_at_all(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an ordinary OWNER session: signed in through the real login, holding no
    # step-up grant and never offered one. §6.8 line 949 lists this GET as ``W``, with the
    # ``+S`` reserved for the four writes beneath it, so this must be a 200 and not the
    # STEP_UP_REQUIRED a single collapsed ``W+S`` cell would answer for ever.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    response = await client.get(ADMINS_PATH)

    # Assert
    assert response.status_code == 200
    assert [item["username"] for item in response.json()["items"]] == ["owner-account"]


@pytest.mark.parametrize("role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN])
async def test_a_role_without_admin_read_is_refused_for_its_role_not_for_a_step_up(
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
    client: httpx.AsyncClient,
) -> None:
    # Arrange — nothing. ``RequirePermission`` depends on ``get_current_admin``, so the
    # 401 has to come out before the matrix is consulted at all; an anonymous caller must
    # never learn which role would have been allowed.

    # Act
    response = await client.get(ADMINS_PATH)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_an_unrouted_path_under_admins_answers_in_the_error_envelope(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — there is no ``/admins/{id}`` in this slice, and a 404 must still be the one
    # body shape every failure comes back as rather than FastAPI's own.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    response = await client.get(f"{ADMINS_PATH}/00000000-0000-0000-0000-000000000000")

    # Assert
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# The credential
# ---------------------------------------------------------------------------
async def test_the_password_hash_is_absent_from_the_body_rather_than_masked(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a recognisable PHC string on a row the roster is about to return.
    await seed_account(container, username="viewer-with-a-hash")
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    response = await client.get(ADMINS_PATH)

    # Assert — searched as text, so a hash nested anywhere in the payload still fails.
    assert response.status_code == 200
    assert SENTINEL_HASH not in response.text
    assert "$argon2id$" not in response.text
    for item in response.json()["items"]:
        assert FORBIDDEN_KEYS.isdisjoint(item)


async def test_the_view_carries_exactly_the_fields_the_panel_renders(
    container: AdminContainer, client: httpx.AsyncClient
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
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(ADMINS_PATH)).json()

    # Assert
    seeded = next(item for item in body["items"] if item["username"] == "support-account")
    assert set(seeded) == EXPECTED_KEYS
    assert seeded["role"] == AdminRole.SUPPORT.value
    assert seeded["isActive"] is True
    assert seeded["mustChangePassword"] is True
    assert seeded["lastLoginAt"] is not None


async def test_an_account_that_has_never_signed_in_reports_null_rather_than_a_stamp(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — "never signed in" and "signed in long ago" are different facts after a
    # handover, and only one of them is a credential nobody has ever used.
    await seed_account(container, username="never-used")
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(ADMINS_PATH)).json()

    # Assert
    seeded = next(item for item in body["items"] if item["username"] == "never-used")
    assert seeded["lastLoginAt"] is None


# ---------------------------------------------------------------------------
# Who is on it
# ---------------------------------------------------------------------------
async def test_a_deactivated_account_is_listed_rather_than_hidden(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — it still owns audit rows and can be reactivated, so it is a credential that
    # exists. A roster that omitted it would undercount who has access.
    await seed_account(container, username="departed", role=AdminRole.ADMIN, is_active=False)
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(ADMINS_PATH)).json()

    # Assert
    departed = next(item for item in body["items"] if item["username"] == "departed")
    assert departed["isActive"] is False


async def test_the_roster_is_oldest_first_so_adding_an_account_does_not_reshuffle_it(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — usernames are what an operator scans, but sorting by them would move every
    # row each time somebody is added.
    await seed_account(container, username="zulu", created_at=NOW - timedelta(days=3))
    await seed_account(container, username="alpha", created_at=NOW - timedelta(days=1))
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(ADMINS_PATH)).json()

    # Assert
    assert [item["username"] for item in body["items"]][:2] == ["zulu", "alpha"]


async def test_the_reader_sees_their_own_account_on_the_roster(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the owner is an operator too, and a roster that filtered ``self`` would
    # answer "who has access?" one short.
    await seed_account(container, username="a-viewer")
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(ADMINS_PATH)).json()

    # Assert
    assert {item["username"] for item in body["items"]} == {"a-viewer", "owner-account"}


# ---------------------------------------------------------------------------
# POST /api/admins — adding an operator
# ---------------------------------------------------------------------------
#: The account every create test asks for. Lowercase, hyphenated and short: the charset is
#: ``ADMIN_USERNAME_PATTERN``'s, which is the step-up scope's and the audit subject's.
NEW_USERNAME: Final[str] = "dilnoza"
#: What the new operator is handed. Distinct from ``PASSWORD`` so a test that finds it in a
#: response body has found *this* credential and not the signed-in owner's.
NEW_PASSWORD: Final[str] = "a-password-somebody-else-chose"


async def step_up(
    client: httpx.AsyncClient, *, subject: str, scope: str = "admin.manage"
) -> httpx.Response:
    """The real ``/auth/step-up`` — the only thing that writes ``step_up_scope``."""
    return await client.post(
        "/api/auth/step-up",
        json={"password": PASSWORD, "scope": scope, "subjectId": subject},
        headers=csrf_headers(client),
    )


async def post_create(client: httpx.AsyncClient, **overrides: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "username": NEW_USERNAME,
        "password": NEW_PASSWORD,
        "role": AdminRole.SUPPORT.value,
        "reasonCode": AuditReasonCode.ROUTINE_OPS.value,
        **overrides,
    }
    return await client.post(ADMINS_PATH, json=body, headers=csrf_headers(client))


async def audit_rows(container: AdminContainer, action: AuditAction) -> list[AdminAuditRow]:
    async with container.session_factory.begin() as db:
        rows = await db.scalars(
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.action == action)
            .order_by(AdminAuditRow.seq)
        )
        return list(rows.all())


async def usernames(container: AdminContainer) -> set[str]:
    async with container.session_factory.begin() as db:
        rows = await db.scalars(sa.select(AdminUserRow.username))
        return set(rows.all())


async def owner_with_grant(
    container: AdminContainer, client: httpx.AsyncClient, *, subject: str = NEW_USERNAME
) -> None:
    """A signed-in OWNER holding a live ``admin.manage:<subject>`` grant."""
    await signed_in(container, client, role=AdminRole.OWNER)
    assert (await step_up(client, subject=subject)).status_code == 200


async def test_an_owner_with_a_scoped_step_up_creates_an_operator(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await owner_with_grant(container, client)

    # Act
    response = await post_create(client)

    # Assert — 201 and the row the database wrote, not an echo of the request.
    assert response.status_code == 201
    created = response.json()
    assert set(created) == EXPECTED_KEYS
    assert created["username"] == NEW_USERNAME
    assert created["role"] == AdminRole.SUPPORT.value
    assert created["isActive"] is True
    # The credential was chosen by somebody else, so the account cannot do anything with it
    # until it has been replaced. Never negotiable from the wire.
    assert created["mustChangePassword"] is True
    assert created["lastLoginAt"] is None
    assert await usernames(container) == {"owner-account", NEW_USERNAME}


async def test_the_create_is_audited_in_the_transaction_that_wrote_the_account(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — §9.1's first rule: one transaction, so an unaudited account is impossible
    # rather than unlikely.
    await owner_with_grant(container, client)

    # Act
    assert (await post_create(client, reasonRef="TICKET-9")).status_code == 201

    # Assert — the subject is the USERNAME, which is what a refused attempt can also name.
    rows = await audit_rows(container, AuditAction.ADMIN_CREATE)
    assert len(rows) == 1
    assert rows[0].outcome is AuditOutcome.OK
    assert rows[0].subject_type == "admin"
    assert rows[0].subject_id == NEW_USERNAME
    assert rows[0].record_count == 1
    assert rows[0].reason_ref == "TICKET-9"
    assert rows[0].actor_username == "owner-account"
    # The column NAMES, never the values (§12.4). ``password_hash`` is here because "a
    # credential was written" is the fact, and nothing in the name could be replayed.
    assert rows[0].field_names == [
        "admin_users.username",
        "admin_users.role",
        "admin_users.password_hash",
    ]


async def test_the_created_operator_signs_in_and_is_made_to_replace_the_password(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — end to end through the real login and the real argon2 verify: an account the
    # panel created that cannot sign in is a handover that silently failed.
    await owner_with_grant(container, client)
    assert (await post_create(client)).status_code == 201

    # Act
    response = await sign_in(client, username=NEW_USERNAME, password=NEW_PASSWORD)

    # Assert
    assert response.status_code == 200
    assert response.json()["mustChangePassword"] is True


async def test_a_create_with_no_step_up_at_all_writes_nothing(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an ordinary OWNER session passes the router's role half and must still be
    # refused by the handler, which is the whole reason the ``W+S`` row is split in two.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    response = await post_create(client)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "STEP_UP_REQUIRED"
    assert await usernames(container) == {"owner-account"}
    assert await audit_rows(container, AuditAction.ADMIN_CREATE) == []


async def test_a_grant_for_another_username_does_not_create_this_one(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the grant is for the name the owner first typed; the body carries the one
    # they typed after. A scope compared whole is what stops the second from riding on the
    # first, and there is no id here to fall back on.
    await owner_with_grant(container, client, subject="somebody-else")

    # Act
    response = await post_create(client)

    # Assert
    # STEP_UP_REQUIRED and not a mismatch-specific code: ``AdminErrorCode`` has no member
    # for a scope mismatch, and deliberately — the SPA's remedy for both is the same prompt,
    # and the distinction that matters (a role refusal offers no prompt at all) is kept.
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "STEP_UP_REQUIRED"
    assert await usernames(container) == {"owner-account"}


async def test_a_grant_for_another_action_on_this_username_does_not_create_it(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``require_step_up`` compares the action too: re-authenticating to bar an
    # abuser must not also mint somebody an operator account.
    await signed_in(container, client, role=AdminRole.OWNER)
    assert (await step_up(client, subject=NEW_USERNAME, scope="user.block")).status_code == 200

    # Act
    response = await post_create(client)

    # Assert
    assert response.status_code == 403
    assert await usernames(container) == {"owner-account"}


@pytest.mark.parametrize("role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN])
async def test_a_role_below_owner_is_refused_for_its_role_not_for_a_step_up(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — ADMIN_MANAGE_WRITE is OWNER's alone. The refusal must offer no remedy: an
    # ADMIN who saw STEP_UP_REQUIRED here would re-authenticate and be refused again.
    await signed_in(container, client, role=role)

    # Act
    response = await post_create(client)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert await audit_rows(container, AuditAction.ADMIN_CREATE) == []


async def test_an_owner_account_cannot_be_created_from_the_panel(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``ix_admin_users_active_owner`` permits one active owner, so this would be
    # refused by the database anyway; what the route adds is a sentence naming the CLI that
    # does hand ownership over.
    await owner_with_grant(container, client)

    # Act
    response = await post_create(client, role=AdminRole.OWNER.value)

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"
    assert "--reset-owner" in response.json()["error"]["message"]
    assert await usernames(container) == {"owner-account"}


async def test_a_username_that_is_already_taken_is_refused_with_a_conflict(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the ordinary case is an owner retyping a name that is on the roster in front
    # of them.
    await seed_account(container, username=NEW_USERNAME, role=AdminRole.VIEWER)
    await owner_with_grant(container, client)

    # Act
    response = await post_create(client)

    # Assert — and the seeded row is untouched: its role did not become SUPPORT.
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    async with container.session_factory.begin() as db:
        existing = await db.scalar(
            sa.select(AdminUserRow).where(AdminUserRow.username == NEW_USERNAME)
        )
    assert existing is not None
    assert existing.role is AdminRole.VIEWER


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"role": AdminRole.OWNER.value}, "owner"),
        ({"username": "dilnoza"}, "taken"),
    ],
    ids=["owner", "taken"],
)
async def test_a_refusal_past_the_step_up_still_writes_a_row(
    container: AdminContainer,
    client: httpx.AsyncClient,
    overrides: dict[str, Any],
    why: str,
) -> None:
    """§12.6: the log records what operators did, not what succeeded.

    Somebody re-authenticated in order to create an operator and did not get one, and that
    is the attempt a "successes only" log would not have. ``record_count=0`` is what tells
    it apart from a create that landed, by a query rather than by reading reasons.
    """
    # Arrange
    if why == "taken":
        await seed_account(container, username=NEW_USERNAME, role=AdminRole.VIEWER)
    await owner_with_grant(container, client)

    # Act
    response = await post_create(client, **overrides)

    # Assert
    assert response.status_code in (409, 422)
    rows = await audit_rows(container, AuditAction.ADMIN_CREATE)
    assert len(rows) == 1
    assert rows[0].outcome is AuditOutcome.ERROR
    assert rows[0].subject_id == NEW_USERNAME
    assert rows[0].record_count == 0


@pytest.mark.parametrize(
    "username",
    ["Dilnoza", "dilnoza@bayram.uz", "ab", "-dilnoza", "dilnoza:admin", "d" * 33],
    ids=["uppercase", "email", "too-short", "leading-dash", "scope-separator", "too-long"],
)
async def test_a_username_a_step_up_scope_could_not_hold_is_refused_before_anything_moves(
    container: AdminContainer, client: httpx.AsyncClient, username: str
) -> None:
    # Arrange — a signed-in OWNER and no grant, because none of these names could have one:
    # the scope and the audit subject are both closed charsets, and ``/auth/step-up`` itself
    # answers 422 to a subject it could not store. Uppercase is in the list because a scope
    # is compared byte for byte — ``admin.manage:Dilnoza`` would never match the ``dilnoza``
    # the database stores.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    response = await post_create(client, username=username)

    # Assert — 422 and not the 403 a missing grant would earn: the body is validated before
    # the handler runs, so a name this route could never accept is refused without the
    # operator being sent off to re-authenticate for it first.
    assert response.status_code == 422
    assert await usernames(container) == {"owner-account"}


async def test_a_password_below_the_floor_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``MIN_PASSWORD_CHARS``, the same floor a rotation is held to. ``LoginRequest``
    # has none, because an existing password predates any rule a schema could impose.
    await owner_with_grant(container, client)

    # Act
    response = await post_create(client, password="short")

    # Assert
    assert response.status_code == 422
    assert await usernames(container) == {"owner-account"}


async def test_the_new_password_reaches_neither_the_response_nor_the_audit_log(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — searched as text rather than by key, so it fails too if the value arrives
    # inside a nested object, in an error message, or on an audit row's reason text.
    await owner_with_grant(container, client)

    # Act
    response = await post_create(client, reasonText="handing the account to a new hire")

    # Assert
    assert response.status_code == 201
    assert NEW_PASSWORD not in response.text
    async with container.session_factory.begin() as db:
        rows = list((await db.scalars(sa.select(AdminAuditRow))).all())
    assert rows
    for row in rows:
        assert NEW_PASSWORD not in str(row.__dict__)
