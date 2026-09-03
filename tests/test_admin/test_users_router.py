"""The four ``/users`` routes over the real ASGI stack — real container, login and guard.

The assertion this file exists for is the negative one. ``/users/{id}/wizard-state`` is a
reveal surface wearing a read's clothes: the FSM draft holds the recipient's display name,
the free-text note and the whole approved lyric, and for a session somebody abandoned it is
the only copy of any of it that exists anywhere. So the draft seeded here is a **real**
:class:`~hbd.bot.draft.WizardDraft`, written through aiogram's own storage, carrying a note
and a name distinctive enough that a substring test cannot pass by accident — and neither
string may appear in the response body at any role, OWNER included. §12.3 has no unmasked
variant of this screen; the plaintext is reachable only through ``POST /reveal`` in Phase 2.

**There is no 403 case in this file, and that is the matrix rather than an omission.** §12.2
gives RECORDS_READ and WIZARD_STATE_READ as **M** in all four cells, so no role is refused.
What is asserted instead is that each router carries exactly one guard, that the two guards
name *different* permissions, and that the matrix rows really are full — which is the test
that starts failing on the day somebody narrows one of them.

The routers are included here rather than assumed: a later step wires them into
``create_app``, and this file must pass on either side of that.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast
from uuid import uuid4

import httpx
import pytest
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from hbd.admin.container import AdminContainer
from hbd.admin.deps import RequirePermission
from hbd.admin.routers.users import (
    USER_ORDERS_PATH,
    USER_PATH,
    USERS_PATH,
    WIZARD_STATE_PATH,
    build_users_router,
    build_wizard_state_router,
)
from hbd.admin.security.permissions import RBAC_MATRIX, Permission
from hbd.contracts import Language, OrderState
from hbd.db.enums import AdminRole
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from tests.test_admin.conftest import PASSWORD, FakeRedis, create_account, sign_in
from tests.test_admin.test_wizard_state import NOTE, RECIPIENT_DISPLAY, make_draft

#: A fixed instant, so the window and ordering assertions are not races.
NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)
TELEGRAM_USER_ID: Final[int] = 987_654_321
OTHER_USER_ID: Final[int] = 123_456_789
#: An id no seeded row uses, for the 404 paths.
UNKNOWN_USER_ID: Final[int] = 555_000_222

USER_URL: Final[str] = USER_PATH.format(telegram_user_id=TELEGRAM_USER_ID)
USER_ORDERS_URL: Final[str] = USER_ORDERS_PATH.format(telegram_user_id=TELEGRAM_USER_ID)
WIZARD_STATE_URL: Final[str] = WIZARD_STATE_PATH.format(telegram_user_id=TELEGRAM_USER_ID)

EVERY_ROLE: Final[tuple[AdminRole, ...]] = (
    AdminRole.VIEWER,
    AdminRole.SUPPORT,
    AdminRole.ADMIN,
    AdminRole.OWNER,
)


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole = AdminRole.ADMIN
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


async def seed_user(
    container: AdminContainer,
    *,
    telegram_user_id: int = TELEGRAM_USER_ID,
    ui_language: Language = Language.UZ_LATN,
    is_blocked: bool = False,
    created_at: datetime | None = None,
) -> UserRow:
    """One ``users`` row through the real model — the row ``_ensure_user`` would write."""
    async with container.session_factory.begin() as db:
        row = UserRow(
            telegram_user_id=telegram_user_id,
            ui_language=ui_language,
            is_blocked=is_blocked,
            last_seen_at=created_at or NOW,
            created_at=created_at or NOW,
            updated_at=created_at or NOW,
        )
        db.add(row)
        await db.flush()
        return row


async def seed_order(
    container: AdminContainer,
    user: UserRow,
    *,
    state: OrderState = OrderState.DELIVERED,
    is_paid: bool = True,
    created_at: datetime | None = None,
) -> OrderRow:
    """One order for ``user``. ``orders`` has no default id, so the caller mints one."""
    stamp = created_at or NOW
    async with container.session_factory.begin() as db:
        row = OrderRow(
            id=uuid4(),
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            state=state,
            correlation_id=uuid4().hex,
            is_paid=is_paid,
            created_at=stamp,
            updated_at=stamp,
        )
        db.add(row)
        await db.flush()
        return row


async def seed_wizard_session(
    fake_redis: FakeRedis, *, telegram_user_id: int = TELEGRAM_USER_ID, **overrides: Any
) -> None:
    """Write a live session the way the bot writes it: aiogram's storage, aiogram's key."""
    storage = RedisStorage(redis=cast("Redis[str]", fake_redis))
    key = StorageKey(bot_id=1, chat_id=telegram_user_id, user_id=telegram_user_id)
    await storage.set_state(key, "Wizard:note")
    await storage.set_data(key, make_draft(**overrides).to_state_data())


# ---------------------------------------------------------------------------
# Who may read it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_every_role_in_the_matrix_row_may_read_the_user_record(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — §12.2 gives RECORDS_READ as M to all four roles.
    await seed_user(container)
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(USER_URL)

    # Assert
    assert response.status_code == 200


@pytest.mark.parametrize("path", [USERS_PATH, USER_URL, USER_ORDERS_URL, WIZARD_STATE_URL], ids=str)
async def test_an_unauthenticated_caller_gets_401_from_every_route(
    client: httpx.AsyncClient, path: str
) -> None:
    # Act
    response = await client.get(path)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_each_router_declares_exactly_one_guard_and_they_are_different_permissions() -> None:
    # Arrange — the guard is on the router so a route added later inherits it. One router
    # carrying both permissions could only guard the second one per handler, which is the
    # shape §12.1 T3 forbids.
    records = _router_permissions(build_users_router())
    wizard = _router_permissions(build_wizard_state_router())

    # Assert
    assert records == [Permission.RECORDS_READ]
    assert wizard == [Permission.WIZARD_STATE_READ]


def test_neither_matrix_row_has_an_empty_cell_so_no_role_is_refused_here() -> None:
    # Arrange / Act — why this file asserts no 403. The day either row is narrowed, this
    # fails and whoever narrowed it writes the refusal test that has to exist.

    # Assert
    assert set(RBAC_MATRIX[Permission.RECORDS_READ]) == set(AdminRole)
    assert set(RBAC_MATRIX[Permission.WIZARD_STATE_READ]) == set(AdminRole)


def _router_permissions(router: object) -> list[Permission]:
    dependencies = getattr(router, "dependencies", [])
    guards = [dependency.dependency for dependency in dependencies]
    return [guard.permission for guard in guards if isinstance(guard, RequirePermission)]


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------
async def test_the_list_reports_the_order_rollups_and_a_masked_id(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two orders, one of them paid, three hours apart.
    user = await seed_user(container)
    await seed_order(container, user, state=OrderState.DRAFT, is_paid=False, created_at=NOW)
    await seed_order(
        container, user, state=OrderState.DELIVERED, created_at=NOW + timedelta(hours=3)
    )
    await signed_in(container, client)

    # Act
    body = (await client.get(USERS_PATH)).json()

    # Assert
    row = body["items"][0]
    assert row["telegramUserIdMasked"] == "•••••321"
    assert row["orderCount"] == 2
    assert row["paidOrderCount"] == 1
    assert row["firstOrderAt"] < row["lastOrderAt"]
    assert row["accountCreatedAt"].startswith("2026-03-21")
    # "last order", never "last seen": the column has no writer that measures presence.
    assert "lastSeenAt" not in row


async def test_a_user_with_no_orders_reports_zero_rather_than_omitting_the_counts(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_user(container)
    await signed_in(container, client)

    # Act
    row = (await client.get(USERS_PATH)).json()["items"][0]

    # Assert — a missing key would let the panel render "unknown" for a counted zero.
    assert row["orderCount"] == 0
    assert row["firstOrderAt"] is None
    assert row["lastOrderAt"] is None


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"telegramUserId": OTHER_USER_ID}, [OTHER_USER_ID]),
        ({"isBlocked": "true"}, [OTHER_USER_ID]),
        ({"uiLanguage": ["ru"]}, [OTHER_USER_ID]),
        ({"uiLanguage": ["ru", "uz_latn"]}, [OTHER_USER_ID, TELEGRAM_USER_ID]),
    ],
    ids=["by-id", "by-blocked", "one-language", "two-languages-are-or"],
)
async def test_each_filter_narrows_to_the_rows_it_names(
    container: AdminContainer,
    client: httpx.AsyncClient,
    params: dict[str, Any],
    expected: list[int],
) -> None:
    # Arrange — repeated values are OR within a field, AND across fields (§6.1).
    await seed_user(container, created_at=NOW - timedelta(days=1))
    await seed_user(
        container,
        telegram_user_id=OTHER_USER_ID,
        ui_language=Language.RU,
        is_blocked=True,
        created_at=NOW,
    )
    await signed_in(container, client)

    # Act
    body = (await client.get(USERS_PATH, params=params)).json()

    # Assert — newest account first.
    assert [row["telegramUserId"] for row in body["items"]] == expected


async def test_the_window_filters_on_when_the_account_was_created(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_user(container, created_at=NOW - timedelta(days=30))
    await seed_user(container, telegram_user_id=OTHER_USER_ID, created_at=NOW)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(
            USERS_PATH,
            params={
                "from": (NOW - timedelta(days=1)).isoformat(),
                "to": (NOW + timedelta(days=1)).isoformat(),
            },
        )
    ).json()

    # Assert
    assert [row["telegramUserId"] for row in body["items"]] == [OTHER_USER_ID]


@pytest.mark.parametrize(
    "params",
    [
        {"uiLanguage": "klingon"},
        {"from": "2026-03-21T09:00:00", "to": "2026-03-22T09:00:00"},
        {"from": "2026-03-21T09:00:00Z"},
        {"to": "2026-03-21T09:00:00Z"},
        {"from": "2026-03-22T09:00:00Z", "to": "2026-03-21T09:00:00Z"},
    ],
    ids=["unknown-language", "naive-instant", "only-from", "only-to", "backwards"],
)
async def test_a_parameter_the_endpoint_cannot_honour_is_refused_at_the_boundary(
    container: AdminContainer, client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    # Arrange — a filter that quietly matches nothing is worse than a refusal: the operator
    # reads an empty page as an answer about the customer.
    await signed_in(container, client)

    # Act
    response = await client.get(USERS_PATH, params=params)

    # Assert
    assert response.status_code == 422


async def test_the_total_is_present_only_when_it_was_asked_for(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_user(container)
    await signed_in(container, client)

    # Act
    without = (await client.get(USERS_PATH)).json()["meta"]
    with_total = (await client.get(USERS_PATH, params={"withTotal": "true"})).json()["meta"]

    # Assert — ``total`` and ``isTotalExact`` travel as a pair or not at all.
    assert without["total"] is None
    assert without["isTotalExact"] is None
    assert with_total == {"nextCursor": None, "total": 1, "isTotalExact": True}


async def test_a_full_page_hands_back_a_cursor_that_fetches_the_rest(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — three accounts, one per page.
    for offset in range(3):
        await seed_user(
            container,
            telegram_user_id=TELEGRAM_USER_ID + offset,
            created_at=NOW - timedelta(days=offset),
        )
    await signed_in(container, client)

    # Act
    first = (await client.get(USERS_PATH, params={"limit": 1})).json()
    second = (
        await client.get(USERS_PATH, params={"limit": 1, "cursor": first["meta"]["nextCursor"]})
    ).json()

    # Assert
    assert first["meta"]["nextCursor"] is not None
    assert second["items"][0]["telegramUserId"] != first["items"][0]["telegramUserId"]


# ---------------------------------------------------------------------------
# One person's record
# ---------------------------------------------------------------------------
async def test_the_detail_breaks_the_orders_down_by_the_states_they_reached(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    user = await seed_user(container)
    await seed_order(container, user, state=OrderState.DELIVERED)
    await seed_order(container, user, state=OrderState.FAILED, is_paid=False)
    await signed_in(container, client)

    # Act
    body = (await client.get(USER_URL)).json()

    # Assert — states with no orders are absent, never zero-filled.
    assert body["user"]["telegramUserId"] == TELEGRAM_USER_ID
    assert {entry["state"]: entry["count"] for entry in body["ordersByState"]} == {
        "delivered": 1,
        "failed": 1,
    }
    assert body["deliveredOrderCount"] == 1
    assert body["failedOrderCount"] == 1


@pytest.mark.parametrize(
    "path",
    [
        USER_PATH.format(telegram_user_id=UNKNOWN_USER_ID),
        USER_ORDERS_PATH.format(telegram_user_id=UNKNOWN_USER_ID),
    ],
    ids=["detail", "orders"],
)
async def test_an_id_this_database_has_never_seen_is_a_404_that_does_not_echo_it(
    container: AdminContainer, client: httpx.AsyncClient, path: str
) -> None:
    # Arrange — an empty orders page would read as "this customer has never ordered", which
    # is a claim about a person we hold nothing about.
    await signed_in(container, client)

    # Act
    response = await client.get(path)

    # Assert — and the error body is a JSON payload, so §12.3 applies to it too.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert str(UNKNOWN_USER_ID) not in response.text


async def test_the_orders_route_returns_this_users_orders_and_nobody_elses(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    user = await seed_user(container)
    other = await seed_user(container, telegram_user_id=OTHER_USER_ID)
    mine = await seed_order(container, user)
    await seed_order(container, other)
    await signed_in(container, client)

    # Act
    body = (await client.get(USER_ORDERS_URL, params={"withTotal": "true"})).json()

    # Assert
    assert [item["id"] for item in body["items"]] == [str(mine.id)]
    assert body["meta"]["total"] == 1


# ---------------------------------------------------------------------------
# The wizard state — the reveal surface that is not one
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_no_role_sees_a_character_of_the_draft(
    container: AdminContainer,
    client: httpx.AsyncClient,
    fake_redis: FakeRedis,
    role: AdminRole,
) -> None:
    # Arrange — a real draft, written by aiogram's storage, holding a real note and name.
    # For an abandoned session this is the only copy of either that exists anywhere.
    await seed_wizard_session(fake_redis)
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(WIZARD_STATE_URL)

    # Assert — the literal text, and the ``\uXXXX`` form a JSON encoder might emit.
    assert response.status_code == 200
    assert NOTE not in response.text
    assert RECIPIENT_DISPLAY not in response.text
    assert json.dumps(RECIPIENT_DISPLAY)[1:-1] not in response.text
    assert json.dumps(NOTE)[1:-1] not in response.text


async def test_the_wizard_state_reports_lengths_and_closed_vocabulary_answers(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange
    await seed_wizard_session(fake_redis)
    await signed_in(container, client)

    # Act
    body = (await client.get(WIZARD_STATE_URL)).json()

    # Assert — presence plus a count for the text, the enum verbatim for the choice.
    assert body["isStatePresent"] is True
    assert body["state"] == "Wizard:note"
    assert body["sessionId"] == "sess-1234"
    assert body["choices"]["occasion"] == "birthday"
    assert body["lyricWrites"] == 2
    fields = {field["key"]: field for field in body["textFields"]}
    assert fields["note"]["charCount"] == len(NOTE)
    assert fields["recipient"]["charCount"] == len(RECIPIENT_DISPLAY)
    assert fields["lyrics"] == {"key": "lyrics", "isPresent": False, "charCount": None}


async def test_a_person_with_no_users_row_still_gets_their_wizard_state(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange — the case the screen exists for: mid-wizard, never confirmed, so
    # ``_ensure_user`` has never run for them and they have no database row at all.
    await seed_wizard_session(fake_redis)
    await signed_in(container, client)

    # Act
    response = await client.get(WIZARD_STATE_URL)

    # Assert — a 404 here would make the screen useless in exactly its own use case.
    assert response.status_code == 200
    assert response.json()["isStatePresent"] is True


async def test_nobody_mid_flow_is_an_answer_rather_than_a_404(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the normal state of everyone who is not in the wizard right now, and also
    # what an expired abandoned-draft TTL leaves behind.
    await seed_user(container)
    await signed_in(container, client)

    # Act
    body = (await client.get(WIZARD_STATE_URL)).json()

    # Assert
    assert body["isStatePresent"] is False
    assert body["state"] is None
    assert [field["isPresent"] for field in body["textFields"]] == [False, False, False]


async def test_an_unreachable_wizard_store_is_a_503_and_not_an_empty_session(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange — sign in first: the session mirror is in the same Redis, and the point of
    # this test is the wizard read, not the authentication path.
    await signed_in(container, client)
    fake_redis.is_down = True

    # Act
    response = await client.get(WIZARD_STATE_URL)

    # Assert — "no session" for every user in the panel would be the wrong answer to
    # "is Redis up?", and nothing else would say so.
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
