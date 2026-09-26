"""``/api/support/groups`` over the real ASGI stack — the directory, and the two presses.

Six properties carry this file, and every one of them is a thing that would be invisible if it
broke.

**1. One endpoint takes a known chat and a typed-in one.** Telegram has no "list my groups"
API, so a group the bot was already sitting in when this shipped can never be discovered and a
pasted id is the only route to it. An id the table has never heard of must become a
``source=manual`` row selected by the same call — and must be honest about being a claim
(``botStatus`` ``unknown``, ``verifiedAt`` null), because a pasted number that rendered like a
Telegram-confirmed group would present a typo with the confidence of a fact.

**2. The selection MOVES rather than accumulating.** The writer clears before it sets, inside
one transaction, and ``ix_bot_chats_selected_support_group`` is what makes "at most one" true
rather than intended. A test that only ever selected into an empty directory could not tell a
clear-then-set from a set-and-hope, which is the bug that ends with two rows claiming the inbox
and a worker posting to whichever it read first.

**3. A press that cannot be recorded is not reported as a success — and one that CAN is not
reported as a verified one.** This process cannot talk to Telegram (``ADMIN_PANEL_PLAN D10 /
§4.2``), so a selection is a row plus an ARQ job, and the response says what was recorded, never
that it works. ``verifiedAt`` stays null until a job that actually tried says otherwise.

**4. The row is COMMITTED before the worker is told the chat exists.** The verification job
opens its own session and reads the chat by id; a job that overtook the request's commit would
find no such row and either do nothing or write a verdict about a selection nobody can see. That
is the race ``routers/support.py`` learned the hard way this morning, and ``CommitProbeQueue``
at the bottom of this file asserts the ordering the way the worker experiences it — from a
second connection, which is why those tests need a FILE database.

**5. Selecting enqueues; clearing does not.** There is nothing to verify about a room nobody is
posting to. Asserted as the absence of a call rather than assumed, because "the seam carries
work the worker must do, never news it might like" is a rule a future convenience breaks
quietly.

**6. SUPPORT is refused, and that is the cell worth a witness.** ``SUPPORT_GROUP_WRITE`` is the
only permission in the panel whose SUPPORT cell is empty while its neighbour's is full: a
support operator works the queue, and choosing which Telegram room every future complaint is
published into is a different act. The refusal must be a flat FORBIDDEN and never a step-up
prompt — no grant would ever help them.

Roles are swept over all four for both surfaces, because this cell is a ruling §12.2 has no row
for, and a widened or narrowed cell should fail here rather than in review.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from bayram.admin.container import AdminContainer
from bayram.admin.errors import AdminErrorCode
from bayram.admin.queue import VERIFY_GROUP_JOB_NAME, NullAdminQueue
from bayram.admin.routers import support_groups as router_module
from bayram.admin.routers.support_groups import (
    BOT_CHAT_SUBJECT_TYPE,
    SUPPORT_GROUP_CLEAR_PATH,
    SUPPORT_GROUP_REASON,
    SUPPORT_GROUP_SELECT_PATH,
    SUPPORT_GROUPS_PATH,
)
from bayram.contracts import BotChatSource, BotChatStatus, BotChatType
from bayram.db.enums import AdminRole, AuditAction
from bayram.db.models.admin_audit import AdminAuditRow
from bayram.db.models.bot_chat import BotChatRow
from tests.test_admin.conftest import (
    NOW,
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    csrf_headers,
    make_settings,
    open_client,
    open_container,
    sign_in,
)

#: Every role in the matrix, so a widened or narrowed cell fails here rather than in review.
EVERY_ROLE: Final[tuple[AdminRole, ...]] = (
    AdminRole.VIEWER,
    AdminRole.SUPPORT,
    AdminRole.ADMIN,
    AdminRole.OWNER,
)

#: The two roles ``SUPPORT_GROUP_WRITE`` reaches, and the two it does not. SUPPORT being on the
#: refused list is the whole point of the row and is the cell most worth a witness: it holds
#: ``SUPPORT_WRITE`` one permission along and may answer any customer in the queue.
WRITE_ROLES: Final[tuple[AdminRole, ...]] = (AdminRole.ADMIN, AdminRole.OWNER)
REFUSED_ROLES: Final[tuple[AdminRole, ...]] = (AdminRole.VIEWER, AdminRole.SUPPORT)

#: Two supergroups the bot really is in, and one number an operator typed. All NEGATIVE and all
#: wider than 32 bits: a chat id truncated to an ``int32`` is a different chat with a plausible
#: prefix, so a value that survived the truncation would let that bug pass.
SUPPORT_GROUP_ID: Final[int] = -1_001_987_654_321
OTHER_GROUP_ID: Final[int] = -1_001_222_333_444
PASTED_GROUP_ID: Final[int] = -1_001_555_666_777
#: A forum topic inside a group — a Telegram MESSAGE id, so positive.
TOPIC_ID: Final[int] = 4242
OTHER_TOPIC_ID: Final[int] = 9999


@dataclass(frozen=True, slots=True)
class Panel:
    container: AdminContainer
    http: httpx.AsyncClient
    queue: NullAdminQueue


@asynccontextmanager
async def open_panel(*, refusing: bool = False, **settings: Any) -> AsyncIterator[Panel]:
    """One panel, with its queue chosen by the caller.

    A context manager rather than a parametrised fixture, for ``test_support``'s reason: exactly
    one test needs a deployment with no worker, and parametrising would put that configuration
    in front of every test in the file.
    """
    queue = NullAdminQueue(refusing=refusing)
    async with (
        open_container(
            make_settings(**settings), FakeRedis(), MemoryRateLimits(), queue
        ) as container,
        open_client(container) as http,
    ):
        yield Panel(container=container, http=http, queue=queue)


@pytest.fixture
async def panel() -> AsyncIterator[Panel]:
    async with open_panel() as opened:
        yield opened


async def signed_in(panel: Panel, *, role: AdminRole = AdminRole.ADMIN) -> str:
    """Sign in as ``role``. **ADMIN by default**, and the default is itself an assertion.

    ADMIN is where this cell starts. Running the file at OWNER would still pass if somebody
    narrowed the row to OWNER alone — which would mean the operator on shift could not repoint
    a dead inbox without waking the owner up, the failure the permission's note argues against.
    """
    username = f"{role.value}-account"
    await create_account(panel.container, username=username, role=role)
    assert (await sign_in(panel.http, username=username, password=PASSWORD)).status_code == 200
    return username


# ---------------------------------------------------------------------------
# Seeding, through the real model
# ---------------------------------------------------------------------------
async def seed_chat(panel: Panel, chat_id: int, **overrides: Any) -> BotChatRow:
    """One ``bot_chats`` row, with every column the model does not default in Python stated.

    Seeded directly rather than through the bot's ``my_chat_member`` handler, because that
    handler lives in another process entirely; a panel test that ran it would be testing the bot.
    ``membership_event`` by default — the ordinary row, Telegram's own word — so the tests that
    want an operator's unverified claim say ``source=manual`` and get a witness rather than a
    default.
    """
    values: dict[str, Any] = {
        "chat_id": chat_id,
        "chat_type": BotChatType.SUPERGROUP,
        "title": f"A group numbered {chat_id}",
        "username": None,
        "bot_status": BotChatStatus.MEMBER,
        "source": BotChatSource.MEMBERSHIP_EVENT,
        "is_support_group": False,
        "thread_id": None,
        "verified_at": None,
        "verification_error": None,
        "selected_by_username": None,
        "selected_at": None,
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    row = BotChatRow(**values)
    async with panel.container.session_factory.begin() as db:
        db.add(row)
    return row


async def chat_rows(panel: Panel) -> list[BotChatRow]:
    """Every row as it now stands, read outside the request that may have changed it."""
    async with panel.container.session_factory.begin() as db:
        statement = sa.select(BotChatRow).order_by(BotChatRow.chat_id)
        return list((await db.execute(statement)).scalars().all())


async def selected_rows(panel: Panel) -> list[BotChatRow]:
    """Every row claiming to be the support group. **A list, so "two" is a visible failure.**"""
    return [row for row in await chat_rows(panel) if row.is_support_group]


async def audit_rows(panel: Panel) -> list[AdminAuditRow]:
    """Every support-group audit row, oldest first. Login rows are filtered out."""
    async with panel.container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.subject_type == BOT_CHAT_SUBJECT_TYPE)
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


def post(panel: Panel, url: str, body: dict[str, Any] | None = None) -> Any:
    """A CSRF-bearing POST, since every mutation here goes through ``get_current_admin``."""
    return panel.http.post(url, json=body or {}, headers=csrf_headers(panel.http))


def select(panel: Panel, chat_id: int, **extra: Any) -> Any:
    return post(panel, SUPPORT_GROUP_SELECT_PATH, {"chatId": chat_id, **extra})


# ---------------------------------------------------------------------------
# The directory
# ---------------------------------------------------------------------------
async def test_the_directory_is_unpaged_and_carries_no_cursor(panel: Panel) -> None:
    # Arrange — every other list in this API is a keyset page with a ``meta``. This one is not,
    # because Telegram has no "list my groups" API: the table fills one row at a time and its
    # population is a handful, ever. A cursor over four rows would answer the screen's one
    # question on page two.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID)
    await seed_chat(panel, OTHER_GROUP_ID)

    # Act
    response = await panel.http.get(SUPPORT_GROUPS_PATH)

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"groups"}
    assert len(body["groups"]) == 2


async def test_the_selected_chat_is_first_and_says_so_on_its_own_row(panel: Panel) -> None:
    # Arrange — the ordering is the answer to the question the screen exists for. A list
    # ordered only by ``lastSeenAt`` would push the selected group down the moment the bot is
    # added to anything else, which is precisely when an operator is looking.
    await signed_in(panel)
    await seed_chat(panel, OTHER_GROUP_ID, last_seen_at=NOW + timedelta(hours=1))
    await seed_chat(panel, SUPPORT_GROUP_ID, is_support_group=True)

    # Act
    groups = (await panel.http.get(SUPPORT_GROUPS_PATH)).json()["groups"]

    # Assert — first, and flagged. There is no separate ``selected`` field beside the list: a
    # second answer to "which one is it?" is a second thing to disagree with the first.
    assert [group["chatId"] for group in groups] == [SUPPORT_GROUP_ID, OTHER_GROUP_ID]
    assert [group["isSupportGroup"] for group in groups] == [True, False]


async def test_the_directory_publishes_the_source_and_the_verification_state(
    panel: Panel,
) -> None:
    # Arrange — a pasted claim and a Telegram-confirmed group, side by side. The panel has to
    # be able to draw them differently: ``manual`` may be a typo, a room the bot was thrown out
    # of, or a chat that never existed, and rendering it like the other one presents a guess
    # with the confidence of a fact.
    await signed_in(panel)
    await seed_chat(
        panel,
        PASTED_GROUP_ID,
        source=BotChatSource.MANUAL,
        bot_status=BotChatStatus.UNKNOWN,
        title=None,
        verification_error="the bot is not a member of this chat",
    )
    await seed_chat(panel, SUPPORT_GROUP_ID, verified_at=NOW)

    # Act
    by_id = {
        group["chatId"]: group
        for group in (await panel.http.get(SUPPORT_GROUPS_PATH)).json()["groups"]
    }

    # Assert — and ``botStatus`` is published beside them rather than instead of them: it is
    # evidence of what Telegram last said, never permission to post.
    pasted = by_id[PASTED_GROUP_ID]
    assert pasted["source"] == BotChatSource.MANUAL.value
    assert pasted["botStatus"] == BotChatStatus.UNKNOWN.value
    assert pasted["verifiedAt"] is None
    assert pasted["verificationError"] == "the bot is not a member of this chat"
    assert pasted["title"] is None

    proved = by_id[SUPPORT_GROUP_ID]
    assert proved["source"] == BotChatSource.MEMBERSHIP_EVENT.value
    assert proved["verifiedAt"] is not None
    assert proved["verificationError"] is None


async def test_a_chat_id_crosses_at_full_width(panel: Panel) -> None:
    # Arrange — 64 bits the whole way to the wire. A client that parsed one of these into a
    # 32-bit integer would be naming a chat that does not exist, and the failure would look
    # like "the bot is not a member" rather than like a truncation.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID, thread_id=TOPIC_ID)

    # Act
    group = (await panel.http.get(SUPPORT_GROUPS_PATH)).json()["groups"][0]

    # Assert
    assert group["chatId"] == SUPPORT_GROUP_ID
    assert group["threadId"] == TOPIC_ID


# ---------------------------------------------------------------------------
# Selecting
# ---------------------------------------------------------------------------
async def test_selecting_a_known_chat_records_it_and_asks_for_a_verification(
    panel: Panel,
) -> None:
    # Arrange — the ordinary press: a group the bot was added to, chosen from the list.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID)

    # Act
    response = await select(panel, SUPPORT_GROUP_ID, threadId=TOPIC_ID)

    # Assert — the row moved, and the answer says what was recorded rather than that it works.
    assert response.status_code == 200
    body = response.json()
    assert body["selection"] == {
        "chatId": SUPPORT_GROUP_ID,
        "previousChatId": None,
        "threadId": TOPIC_ID,
        "created": False,
        "moved": False,
    }
    assert [row.chat_id for row in await selected_rows(panel)] == [SUPPORT_GROUP_ID]

    # Assert — and the worker was asked to find out whether it actually works. On its
    # ARGUMENTS, not on a counter: a seam that enqueued the wrong chat would satisfy a count.
    assert [call.job for call in panel.queue.calls] == [VERIFY_GROUP_JOB_NAME]
    assert panel.queue.calls[0].chat_id == SUPPORT_GROUP_ID
    assert panel.queue.calls[0].arguments == (str(SUPPORT_GROUP_ID),)


async def test_a_fresh_selection_is_never_reported_as_verified(panel: Panel) -> None:
    # Arrange — the response carries the directory as it now stands, and the row in it must be
    # honest: nothing has checked this chat, because checking means asking Telegram and this
    # process is structurally forbidden to. A panel that drew a green badge from the 200 would
    # be claiming a capability nobody has tested.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID)

    # Act
    groups = (await select(panel, SUPPORT_GROUP_ID)).json()["groups"]

    # Assert
    assert groups[0]["isSupportGroup"] is True
    assert groups[0]["verifiedAt"] is None
    assert groups[0]["verificationError"] is None


async def test_selecting_a_chat_verified_last_month_answers_with_checking_and_not_a_green_tick(
    panel: Panel,
) -> None:
    # Arrange — the seed that every other select test in this file was missing. Those all start
    # from a row whose verification columns are already null, so "a fresh selection is never
    # reported as verified" passed against code that simply left whatever was there. This row
    # ALREADY carries a verdict: it was the inbox in August, it was proved then, and the bot has
    # since been removed from it by somebody in Telegram.
    await signed_in(panel)
    await seed_chat(
        panel,
        SUPPORT_GROUP_ID,
        bot_status=BotChatStatus.KICKED,
        verified_at=NOW - timedelta(days=45),
        selected_by_username="dilnoza",
        selected_at=NOW - timedelta(days=45),
    )
    await seed_chat(panel, OTHER_GROUP_ID, is_support_group=True)

    # Act — an operator points the inbox back at it.
    response = await select(panel, SUPPORT_GROUP_ID)

    # Assert — the response is what the panel draws from, and the panel does not poll: whatever
    # is said here stands until somebody presses something. So it must say "nobody has checked
    # this", on the row AND in the table, rather than publishing a clock from before this press.
    assert response.status_code == 200
    chosen = next(
        group for group in response.json()["groups"] if group["chatId"] == SUPPORT_GROUP_ID
    )
    assert chosen["isSupportGroup"] is True
    assert chosen["verifiedAt"] is None
    assert chosen["verificationError"] is None
    # ... and the row itself, because a response that was correct over a row that was not would
    # be a lie the next GET tells.
    selected = await selected_rows(panel)
    assert [row.chat_id for row in selected] == [SUPPORT_GROUP_ID]
    assert (selected[0].verified_at, selected[0].verification_error) == (None, None)
    # The check that will answer it was actually asked for.
    assert [call.chat_id for call in panel.queue.calls] == [SUPPORT_GROUP_ID]


async def test_checking_again_on_a_failed_chat_clears_the_sentence_it_is_meant_to_answer(
    panel: Panel,
) -> None:
    # Arrange — "Check again" is this same endpoint pressed on the row that is already selected;
    # there is no other route to a fresh verdict. The chat carries the failure an operator has
    # just gone and fixed in Telegram.
    await signed_in(panel)
    await seed_chat(
        panel,
        SUPPORT_GROUP_ID,
        is_support_group=True,
        thread_id=TOPIC_ID,
        verification_error="the bot cannot post in this chat",
        selected_by_username="dilnoza",
        selected_at=NOW,
    )

    # Act
    response = await select(panel, SUPPORT_GROUP_ID, threadId=TOPIC_ID)

    # Assert — the red sentence is gone and the row is back to "checking…". Leaving it would
    # answer a fixed permission with the identical words, and an operator would have no way to
    # tell whether the re-check ran, whether their fix worked, or whether the button does
    # anything at all.
    assert response.status_code == 200
    body = response.json()
    assert body["selection"]["moved"] is False
    assert body["groups"][0]["verificationError"] is None
    assert body["groups"][0]["verifiedAt"] is None
    selected = await selected_rows(panel)
    assert (selected[0].verified_at, selected[0].verification_error) == (None, None)
    assert selected[0].thread_id == TOPIC_ID
    assert [call.chat_id for call in panel.queue.calls] == [SUPPORT_GROUP_ID]


async def test_an_id_the_directory_has_never_heard_of_becomes_a_manual_row(
    panel: Panel,
) -> None:
    # Arrange — an empty directory and a number somebody typed. This is not an edge case: a
    # group the bot was already in when this feature shipped produces no ``my_chat_member``
    # update and can NEVER be discovered, so the paste is the only route that exists for it.
    # One endpoint, not two: a row nobody selected is a row nobody looks at.
    await signed_in(panel)

    # Act
    response = await select(panel, PASTED_GROUP_ID)

    # Assert — created, and honest about what it is.
    assert response.status_code == 200
    assert response.json()["selection"]["created"] is True
    rows = await chat_rows(panel)
    assert [row.chat_id for row in rows] == [PASTED_GROUP_ID]
    assert rows[0].source is BotChatSource.MANUAL
    assert rows[0].bot_status is BotChatStatus.UNKNOWN
    assert rows[0].is_support_group is True
    assert rows[0].verified_at is None
    # And the verification job is what will tell the truth about the claim.
    assert [call.chat_id for call in panel.queue.calls] == [PASTED_GROUP_ID]


async def test_the_selection_moves_and_never_accumulates(panel: Panel) -> None:
    # Arrange — a group already receiving the cards, and an operator repointing them. The
    # writer clears before it sets inside one transaction; a set-and-hope would leave two rows
    # claiming the inbox, which is the failure the partial unique index exists to refuse.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID, is_support_group=True, thread_id=TOPIC_ID)
    await seed_chat(panel, OTHER_GROUP_ID)

    # Act
    body = (await select(panel, OTHER_GROUP_ID)).json()

    # Assert — exactly one row selected, and the answer names the room the tickets were taken
    # away from. That is the ``before`` half of the audit entry and is unreadable afterwards.
    assert [row.chat_id for row in await selected_rows(panel)] == [OTHER_GROUP_ID]
    assert body["selection"]["previousChatId"] == SUPPORT_GROUP_ID
    assert body["selection"]["moved"] is True


async def test_unselecting_leaves_the_old_row_saying_who_chose_it(panel: Panel) -> None:
    # Arrange — only the boolean moves. "This was once the support group, chosen by this
    # person, on that day, in that topic" is the most useful thing to know about a chat
    # somebody is looking at while wondering where last month's tickets went.
    username = await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID)
    await seed_chat(panel, OTHER_GROUP_ID)
    await select(panel, SUPPORT_GROUP_ID, threadId=TOPIC_ID)

    # Act
    await select(panel, OTHER_GROUP_ID)

    # Assert
    previous = next(row for row in await chat_rows(panel) if row.chat_id == SUPPORT_GROUP_ID)
    assert previous.is_support_group is False
    assert previous.selected_by_username == username
    assert previous.selected_at is not None
    assert previous.thread_id == TOPIC_ID


async def test_reselecting_the_same_chat_changes_the_topic_and_is_not_a_move(
    panel: Panel,
) -> None:
    # Arrange — re-selecting to change the forum topic is an ordinary act, not a no-op, and it
    # is NOT a move: the tickets are not going anywhere new. ``moved`` exists precisely so the
    # panel's sentence and the audit row's cannot disagree about that case.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID, is_support_group=True, thread_id=TOPIC_ID)

    # Act
    body = (await select(panel, SUPPORT_GROUP_ID, threadId=OTHER_TOPIC_ID)).json()

    # Assert
    assert body["selection"]["previousChatId"] == SUPPORT_GROUP_ID
    assert body["selection"]["moved"] is False
    assert (await selected_rows(panel))[0].thread_id == OTHER_TOPIC_ID


async def test_a_selection_without_a_topic_clears_the_one_that_was_there(panel: Panel) -> None:
    # Arrange — the topic travels WITH the selection, so omitting it means the group itself.
    # That has to be expressible, and the cost is stated where a client author reads it: a form
    # that drops the field on an edit meaning "leave it alone" moves the inbox out of its topic.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID, is_support_group=True, thread_id=TOPIC_ID)

    # Act
    body = (await select(panel, SUPPORT_GROUP_ID)).json()

    # Assert
    assert body["selection"]["threadId"] is None
    assert (await selected_rows(panel))[0].thread_id is None


async def test_selecting_writes_one_audit_row_naming_the_chat_and_the_columns(
    panel: Panel,
) -> None:
    # Arrange — the audit row is what the permission's "no step-up" trade is paid for with, so
    # it has to carry the chat, the columns and the operator. Not the TITLE: that is a string
    # other people change, and the 730-day table is not where copies of it accumulate.
    username = await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID)

    # Act
    await select(panel, SUPPORT_GROUP_ID, threadId=TOPIC_ID)

    # Assert
    rows = await audit_rows(panel)
    assert len(rows) == 1
    assert rows[0].action is AuditAction.SUPPORT_GROUP_SELECT
    assert rows[0].subject_type == BOT_CHAT_SUBJECT_TYPE
    assert rows[0].subject_id == str(SUPPORT_GROUP_ID)
    assert rows[0].field_names == ["bot_chats.is_support_group", "bot_chats.thread_id"]
    assert rows[0].actor_username == username
    # ``ROUTINE_OPS`` and not ``SUPPORT_INVESTIGATION``: configuring the desk is not
    # investigating a customer, and the neighbouring namespace's code must keep meaning what it
    # says. The router constant argues the divergence.
    assert rows[0].reason_code is SUPPORT_GROUP_REASON


async def test_a_non_negative_chat_id_is_refused_before_anything_is_written(
    panel: Panel,
) -> None:
    # Arrange — a POSITIVE Telegram id is a private chat: a person. ``BotChatType`` has no
    # ``private`` member precisely so one cannot be recorded here, and an operator who pastes
    # their own user id must be told they pasted a person — not have the support inbox quietly
    # pointed at a direct-message thread where every ticket card is visible to one human being.
    await signed_in(panel)

    # Act
    response = await select(panel, 987_654_321)

    # Assert — a 422 naming the field, from the schema, before a session opens. ``chatId``
    # appears in the detail because the SPA renders the failure against the input.
    assert response.status_code == 422
    assert "chatId" in response.text
    assert await chat_rows(panel) == []
    assert panel.queue.calls == []


async def test_a_zero_topic_is_refused_rather_than_stored(panel: Panel) -> None:
    # Arrange — ``null`` is how this API says "the group itself". A zero in ``thread_id`` would
    # be a topic id Telegram has never issued, posted into by a worker with no way to tell it
    # apart from a real one.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID)

    # Act
    response = await select(panel, SUPPORT_GROUP_ID, threadId=0)

    # Assert
    assert response.status_code == 422
    assert await selected_rows(panel) == []


async def test_an_unknown_field_is_refused(panel: Panel) -> None:
    # Arrange — ``ApiModel`` is ``extra="forbid"``, which is what stops a stale SPA build from
    # APPEARING to send a field the server then ignores. Here the plausible mistake is a client
    # that still sends the pre-0028 ``chatIdString`` or a ``reasonCode`` this body does not take.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID)

    # Act
    response = await select(panel, SUPPORT_GROUP_ID, reasonCode="routine_ops")

    # Assert
    assert response.status_code == 422
    assert await selected_rows(panel) == []


async def test_a_concurrent_double_press_is_a_conflict_and_not_a_crash(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the race itself is closed by ``ix_bot_chats_selected_support_group`` and is
    # proved against a real session in ``tests/test_db/test_bot_chats.py``; what THIS asserts is
    # the handler's translation of it. Under READ COMMITTED two operators pressing Select in the
    # same instant each read one selected row, each clear the row they read, each set their own,
    # and the index refuses the second at commit. The loser must be told to look again — a 409 —
    # rather than handed a 500 that reads like a bug in the panel.
    #
    # The failure is injected rather than raced, because this suite runs on an in-memory SQLite
    # served from a StaticPool: one connection, so there is no second transaction to race with.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID)

    async def _lost_the_race(*_: object, **__: object) -> None:
        raise IntegrityError("UNIQUE constraint failed", None, Exception("index"))

    monkeypatch.setattr(router_module, "select_support_group", _lost_the_race)

    # Act
    response = await select(panel, SUPPORT_GROUP_ID)

    # Assert — a 409 that names neither chat (this request lost and cannot read what won), and
    # NO audit row: the transaction is already aborted, so a row could not go in it.
    assert response.status_code == 409
    assert response.json()["error"]["code"] == AdminErrorCode.CONFLICT.value
    assert await audit_rows(panel) == []
    assert panel.queue.calls == []


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------
async def test_clearing_unselects_and_asks_the_worker_for_nothing(panel: Panel) -> None:
    # Arrange — clearing is a supported state and not a broken one: the ticket row is still
    # written, the customer is still answered and the board still fills. Only the group post
    # stops. And there is nothing to verify about a room nobody is posting to.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID, is_support_group=True)

    # Act
    response = await post(panel, SUPPORT_GROUP_CLEAR_PATH)

    # Assert
    assert response.status_code == 200
    assert response.json()["clearedChatId"] == SUPPORT_GROUP_ID
    assert await selected_rows(panel) == []
    assert panel.queue.calls == []


async def test_clearing_when_nothing_is_selected_is_a_200_and_not_a_404(panel: Panel) -> None:
    # Arrange — the caller asked for "no group selected" and that is what they have. Answering
    # a second press with an error would report a failure for arriving at exactly the outcome
    # that was wanted, which is the tidy-looking mistake this test exists to keep out.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID)

    # Act
    response = await post(panel, SUPPORT_GROUP_CLEAR_PATH)

    # Assert — and no audit row: the log records what was DONE, and nothing was. A row with no
    # subject is exactly the shape ``audit_sink`` produces when it swallows a rejected subject
    # type and retries, so writing one deliberately would make that bug unrecognisable.
    assert response.status_code == 200
    assert response.json()["clearedChatId"] is None
    assert await audit_rows(panel) == []


async def test_clearing_writes_one_audit_row_naming_the_chat_it_took_the_tickets_from(
    panel: Panel,
) -> None:
    # Arrange — "who turned the support inbox off, and when" is the first question of the
    # incident that follows, and it has to be an indexed equality on ``action`` rather than a
    # scan that parses a field. The subject is the chat that WAS selected, because "nothing" is
    # not a subject.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID, is_support_group=True)

    # Act
    await post(panel, SUPPORT_GROUP_CLEAR_PATH)

    # Assert
    rows = await audit_rows(panel)
    assert len(rows) == 1
    assert rows[0].action is AuditAction.SUPPORT_GROUP_CLEAR
    assert rows[0].subject_type == BOT_CHAT_SUBJECT_TYPE
    assert rows[0].subject_id == str(SUPPORT_GROUP_ID)
    assert rows[0].field_names == ["bot_chats.is_support_group"]


async def test_clearing_keeps_the_topic_so_reselecting_restores_it(panel: Panel) -> None:
    # Arrange — ``thread_id`` survives a clear on purpose. An operator who unselects a group
    # during an incident and selects it again afterwards expects the cards to go back into the
    # topic they were in, not into the group at large where everybody in the room reads them.
    await signed_in(panel)
    await seed_chat(panel, SUPPORT_GROUP_ID, is_support_group=True, thread_id=TOPIC_ID)

    # Act
    await post(panel, SUPPORT_GROUP_CLEAR_PATH)

    # Assert
    assert (await chat_rows(panel))[0].thread_id == TOPIC_ID


# ---------------------------------------------------------------------------
# The cell — and it is the one place the two support permissions disagree
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE, ids=str)
async def test_every_role_may_see_where_the_tickets_go(panel: Panel, role: AdminRole) -> None:
    # Arrange — ``SUPPORT_READ``, the same cell the queue stands on. "Where do my tickets go?"
    # is a question an operator must be able to answer without being able to change the answer,
    # and the row it is answered from holds no customer at all.
    await signed_in(panel, role=role)
    await seed_chat(panel, SUPPORT_GROUP_ID, is_support_group=True)

    # Act / Assert
    assert (await panel.http.get(SUPPORT_GROUPS_PATH)).status_code == 200


@pytest.mark.parametrize("role", WRITE_ROLES, ids=str)
async def test_the_two_write_roles_may_repoint_the_inbox(panel: Panel, role: AdminRole) -> None:
    # Arrange — ADMIN and OWNER, not OWNER alone. Re-pointing the inbox after a group is
    # migrated, renamed or deleted is ordinary operational work done by whoever is awake, and an
    # action only the owner can take is an action the owner gets woken up for.
    await signed_in(panel, role=role)
    await seed_chat(panel, SUPPORT_GROUP_ID)

    # Act / Assert
    assert (await select(panel, SUPPORT_GROUP_ID)).status_code == 200, role
    assert (await post(panel, SUPPORT_GROUP_CLEAR_PATH)).status_code == 200, role


@pytest.mark.parametrize("role", REFUSED_ROLES, ids=str)
async def test_a_support_operator_may_read_the_directory_and_not_repoint_it(
    panel: Panel, role: AdminRole
) -> None:
    # Arrange — THE cell of this feature. SUPPORT holds ``SUPPORT_WRITE`` and may answer any
    # customer in the queue; it does not hold this one, because choosing which Telegram room
    # every future complaint is published into has a different blast radius — the wrong room
    # shows a customer's words to people who should not see them, and the board looks fine.
    await signed_in(panel, role=role)
    await seed_chat(panel, SUPPORT_GROUP_ID, is_support_group=True)

    # Act
    refused = await select(panel, OTHER_GROUP_ID)

    # Assert — FORBIDDEN and never STEP_UP_REQUIRED: no grant would ever help them, and an SPA
    # that opened a re-authentication box at somebody permanently ineligible is the confusion
    # the two decisions are kept apart to prevent.
    assert refused.status_code == 403, role
    assert refused.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value
    assert (await post(panel, SUPPORT_GROUP_CLEAR_PATH)).status_code == 403, role
    # Nothing moved, and the read they DO hold still works.
    assert [row.chat_id for row in await selected_rows(panel)] == [SUPPORT_GROUP_ID]
    assert (await panel.http.get(SUPPORT_GROUPS_PATH)).status_code == 200


# ---------------------------------------------------------------------------
# A deployment with no worker
# ---------------------------------------------------------------------------
async def test_a_dead_worker_is_a_503_over_a_selection_that_stays_put(panel: Panel) -> None:
    # Arrange — the ordering's price, stated rather than hidden. The enqueue used to be able to
    # undo the write; it cannot any more, because an enqueue that can undo the write has to
    # happen before the commit and an enqueue before the commit is the race this file's
    # docstring describes. So a refused verification leaves a committed selection and TELLS the
    # operator, which is the tolerable half.
    async with open_panel(refusing=True) as refusing_panel:
        await signed_in(refusing_panel)
        # Seeded WITH an old verdict on purpose. The committed-then-enqueued order is only
        # tolerable because the row it leaves behind is honest, and a row that kept August's
        # green tick through a refused enqueue would be the worst state this feature can reach:
        # nothing will ever check it, and the screen says it was checked.
        await seed_chat(refusing_panel, SUPPORT_GROUP_ID, verified_at=NOW - timedelta(days=45))

        # Act
        response = await select(refusing_panel, SUPPORT_GROUP_ID)

        # Assert — a 503 (an unavailable dependency, not a malformed request), and the inbox is
        # pointed where the operator asked with nothing having checked it. The panel's job is to
        # render "never checked" as its own state; both verification columns are empty. The way
        # out is the same button: "Check again" is this endpoint, so a deployment that gets its
        # worker back is one press from a verdict.
        assert response.status_code == 503
        selected = await selected_rows(refusing_panel)
        assert [row.chat_id for row in selected] == [SUPPORT_GROUP_ID]
        assert (selected[0].verified_at, selected[0].verification_error) == (None, None)
        # The audit row committed with the selection: the act happened and is recorded.
        assert len(await audit_rows(refusing_panel)) == 1


async def test_a_dead_worker_does_not_stop_an_operator_clearing(panel: Panel) -> None:
    # Arrange — clearing enqueues nothing, so a deployment with no worker can still turn the
    # group post off. That is the one control it would be worst to make unavailable during an
    # incident: a control that makes stopping harder than starting is the wrong way round.
    async with open_panel(refusing=True) as refusing_panel:
        await signed_in(refusing_panel)
        await seed_chat(refusing_panel, SUPPORT_GROUP_ID, is_support_group=True)

        # Act
        response = await post(refusing_panel, SUPPORT_GROUP_CLEAR_PATH)

        # Assert
        assert response.status_code == 200
        assert await selected_rows(refusing_panel) == []
        assert refusing_panel.queue.calls == []


# ---------------------------------------------------------------------------
# COMMIT, then enqueue — asserted the way the worker experiences it
# ---------------------------------------------------------------------------
class CommitProbeQueue(NullAdminQueue):
    """Records what a SECOND connection could see at the instant the job was handed over.

    ``test_support``'s probe one namespace along, one job further: the verification worker opens
    its own session and reads the chat by id, so the question that matters is not "was the row
    written" but "was it COMMITTED". Those are different facts, and only a second connection can
    tell them apart — which is why the panel this probe runs in is on a file database.
    """

    def __init__(self) -> None:
        super().__init__()
        self.container: AdminContainer | None = None
        self.visible_selection: list[int | None] = []

    async def enqueue_support_group_verification(self, chat_id: int) -> Any:
        assert self.container is not None, "the probe was never given its container"
        async with self.container.session_factory() as db:
            selected = await db.scalar(
                sa.select(BotChatRow.chat_id).where(BotChatRow.is_support_group.is_(True))
            )
        self.visible_selection.append(selected)
        return await super().enqueue_support_group_verification(chat_id)


@asynccontextmanager
async def open_probed_panel(tmp_path: Path) -> AsyncIterator[Panel]:
    """A panel on a FILE database, because the probe needs a second real connection.

    The rest of this package runs on ``sqlite+aiosqlite:///:memory:``, which SQLAlchemy serves
    from a ``StaticPool`` — one connection shared by every session in the process. That is right
    for every other test here and useless for this one: with a single connection an uncommitted
    row is visible to the "other" session, so the race cannot be reproduced at all.
    """
    probe = CommitProbeQueue()
    async with (
        open_container(
            make_settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'panel.db'}"),
            FakeRedis(),
            MemoryRateLimits(),
            probe,
        ) as container,
        open_client(container) as http,
    ):
        probe.container = container
        yield Panel(container=container, http=http, queue=probe)


async def test_a_selection_is_committed_before_the_worker_is_told_to_verify_it(
    tmp_path: Path,
) -> None:
    # Arrange — THE regression, inherited rather than rediscovered. ``get_db_session`` commits
    # on a clean exit of the REQUEST, tens of milliseconds after a handler's last statement,
    # and ARQ polls every half second — so a worker really can open its own session inside that
    # window. For this job that means reading the chat it was handed, finding no such row, and
    # either doing nothing at all or writing a verdict about a selection nobody can see.
    async with open_probed_panel(tmp_path) as panel:
        await signed_in(panel)
        await seed_chat(panel, SUPPORT_GROUP_ID)

        # Act
        response = await select(panel, SUPPORT_GROUP_ID)
        assert response.status_code == 200

        # Assert — the chat the worker was handed was the selected chat as far as ANOTHER
        # transaction was concerned, at the moment it was handed over.
        probe = panel.queue
        assert isinstance(probe, CommitProbeQueue)
        assert probe.visible_selection == [SUPPORT_GROUP_ID]


async def test_a_manual_row_exists_for_other_connections_before_it_is_verified(
    tmp_path: Path,
) -> None:
    # Arrange — the same ordering on the path where the row did not exist a moment ago, which
    # is the one where "written" and "committed" diverge most visibly: the verification job's
    # first act is to load the chat, and ``record_verified`` / ``record_verification_failed``
    # both answer ``False`` and create nothing for a chat the directory does not hold. A job
    # that overtook this commit would therefore record NOTHING and complete successfully,
    # leaving a pasted id nobody ever checked.
    async with open_probed_panel(tmp_path) as panel:
        await signed_in(panel)

        # Act
        response = await select(panel, PASTED_GROUP_ID)
        assert response.status_code == 200

        # Assert
        probe = panel.queue
        assert isinstance(probe, CommitProbeQueue)
        assert probe.visible_selection == [PASTED_GROUP_ID]
