"""Tests for the Chats admin router (ADMIN_PANEL_PLAN §5.7, §6.7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from hbd.admin.container import AdminContainer
from hbd.admin.routers.chats import CHATS_PATH
from hbd.db.admin.chats import ChatLineDraft, record_chat_batch
from hbd.db.enums import AdminRole, ChatDirection, ChatMessageKind
from hbd.db.models.user import UserRow
from hbd.db.models.user_profile import UserProfileRow
from tests.test_admin.conftest import PASSWORD, create_account, sign_in


async def signed_in(
    container: AdminContainer,
    client: httpx.AsyncClient,
    *,
    role: AdminRole = AdminRole.ADMIN,
) -> None:
    username = f"{role.value}-operator"
    await create_account(container, username=username, role=role)
    res = await sign_in(client, username=username, password=PASSWORD)
    assert res.status_code == 200


@pytest.fixture
async def sample_chat_data(
    container: AdminContainer,
) -> dict[str, int]:
    """Seed sample chat messages across two users."""
    u1_tg = 987654321
    u2_tg = 123456789
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)

    async with container.session_factory.begin() as session:
        # Create users
        u1 = UserRow(id=uuid4(), telegram_user_id=u1_tg, created_at=now)
        u2 = UserRow(id=uuid4(), telegram_user_id=u2_tg, created_at=now)
        session.add_all([u1, u2])
        await session.flush()

        # Profiles
        p1 = UserProfileRow(
            user_id=u1.id,
            telegram_user_id=u1_tg,
            telegram_username="alice_test",
            first_name="Alice",
            last_name="Wonderland",
            phone_e164="+998901234567",
            avatar_stored_at=now,
        )
        p2 = UserProfileRow(
            user_id=u2.id,
            telegram_user_id=u2_tg,
            telegram_username="bob_builder",
            first_name="Bob",
            last_name="Builder",
            phone_e164="+998907654321",
        )
        session.add_all([p1, p2])
        await session.flush()

        # Chat messages for Alice
        drafts = [
            ChatLineDraft(
                telegram_user_id=u1_tg,
                chat_id=u1_tg,
                user_id=u1.id,
                direction=ChatDirection.INBOUND,
                kind=ChatMessageKind.TEXT,
                body="/start",
                wizard_step="welcome",
                created_at=now - timedelta(minutes=10),
            ),
            ChatLineDraft(
                telegram_user_id=u1_tg,
                chat_id=u1_tg,
                user_id=u1.id,
                direction=ChatDirection.OUTBOUND,
                kind=ChatMessageKind.SCREEN,
                body="Welcome to Birthday Song Bot!",
                wizard_step="occasion",
                created_at=now - timedelta(minutes=9),
            ),
            ChatLineDraft(
                telegram_user_id=u1_tg,
                chat_id=u1_tg,
                user_id=u1.id,
                direction=ChatDirection.INBOUND,
                kind=ChatMessageKind.CALLBACK,
                callback_data="occ:birthday",
                wizard_step="occasion",
                created_at=now - timedelta(minutes=8),
            ),
            ChatLineDraft(
                telegram_user_id=u1_tg,
                chat_id=u1_tg,
                user_id=u1.id,
                direction=ChatDirection.OUTBOUND,
                kind=ChatMessageKind.AUDIO,
                body="Here is your birthday song!",
                wizard_step="delivered",
                created_at=now - timedelta(minutes=5),
            ),
            # Chat messages for Bob
            ChatLineDraft(
                telegram_user_id=u2_tg,
                chat_id=u2_tg,
                user_id=u2.id,
                direction=ChatDirection.INBOUND,
                kind=ChatMessageKind.TEXT,
                body="Hello there",
                wizard_step="welcome",
                created_at=now - timedelta(minutes=2),
            ),
        ]
        await record_chat_batch(session, drafts)

    return {"user1": u1_tg, "user2": u2_tg}


async def test_list_conversations_empty(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    await signed_in(container, client, role=AdminRole.ADMIN)
    res = await client.get(CHATS_PATH)
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["total"] == 0


async def test_list_conversations_returns_recent_threads(
    container: AdminContainer, client: httpx.AsyncClient, sample_chat_data: dict[str, int]
) -> None:
    await signed_in(container, client, role=AdminRole.ADMIN)
    res = await client.get(CHATS_PATH)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    items = data["items"]

    # Bob's message was 2m ago, Alice was 5m ago -> Bob first
    assert items[0]["telegramUserId"] == sample_chat_data["user2"]
    assert items[0]["username"] == "bob_builder"
    assert items[0]["firstName"] == "Bob"
    assert items[0]["lastMessageText"] == "Hello there"
    assert items[0]["messageCount"] == 1

    assert items[1]["telegramUserId"] == sample_chat_data["user1"]
    assert items[1]["username"] == "alice_test"
    assert items[1]["firstName"] == "Alice"
    assert items[1]["hasAvatar"] is True
    assert items[1]["messageCount"] == 4


async def test_list_conversations_search(
    container: AdminContainer, client: httpx.AsyncClient, sample_chat_data: dict[str, int]
) -> None:
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Search by username
    res = await client.get(f"{CHATS_PATH}?q=alice")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["username"] == "alice_test"

    # Search by phone
    res = await client.get(f"{CHATS_PATH}?q=7654321")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["username"] == "bob_builder"

    # Search by telegram ID
    res = await client.get(f"{CHATS_PATH}?q={sample_chat_data['user1']}")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["telegramUserId"] == sample_chat_data["user1"]


async def test_get_chat_transcript_chronological(
    container: AdminContainer, client: httpx.AsyncClient, sample_chat_data: dict[str, int]
) -> None:
    await signed_in(container, client, role=AdminRole.ADMIN)
    u1_tg = sample_chat_data["user1"]

    res = await client.get(f"{CHATS_PATH}/{u1_tg}/messages")
    assert res.status_code == 200
    data = res.json()
    assert data["telegramUserId"] == u1_tg
    assert data["total"] == 4
    messages = data["messages"]

    # Oldest first: /start -> Welcome -> Callback -> Audio
    assert messages[0]["body"] == "/start"
    assert messages[0]["direction"] == "inbound"
    assert messages[0]["kind"] == "text"

    assert messages[1]["direction"] == "outbound"
    assert messages[1]["kind"] == "screen"
    assert "Welcome" in messages[1]["body"]

    assert messages[2]["direction"] == "inbound"
    assert messages[2]["kind"] == "callback"
    assert messages[2]["callbackData"] == "occ:birthday"

    assert messages[3]["direction"] == "outbound"
    assert messages[3]["kind"] == "audio"


@pytest.mark.parametrize("role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER])
async def test_all_roles_have_access(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    await signed_in(container, client, role=role)
    res = await client.get(CHATS_PATH)
    assert res.status_code == 200


async def test_unauthenticated_request_rejected(
    client: httpx.AsyncClient,
) -> None:
    res = await client.get(CHATS_PATH)
    assert res.status_code == 401
