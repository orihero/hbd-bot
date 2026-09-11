"""``POST /users/{telegramUserId}/block`` and ``/unblock`` over the real ASGI stack.

These are the first mutations in the panel that are not about the operator's own session, so
three things are asserted here that no read test can assert, and each one has a specific
failure it exists to catch:

**1. The split row really needs both halves.** §12.2's cell is ``W+S`` and a router guard
cannot enforce it — :func:`~bayram.admin.security.permissions.check_role` holds no subject, so it
would answer ``STEP_UP_REQUIRED`` to a correctly re-authenticated ADMIN for ever. The routers
therefore declare ``USER_BLOCK_WRITE`` and the handlers enforce ``USER_BLOCK``. Both refusals
are asserted, and they are asserted as *different codes*: a SUPPORT operator gets
``FORBIDDEN`` (a dead end the SPA must not turn into a prompt) and an ADMIN without a grant
gets ``STEP_UP_REQUIRED``.

**2. The step-up is scoped to the subject.** A grant taken for one Telegram id must not block
another, and a grant taken for ``reveal`` must not block anybody. Both are driven through the
real ``POST /api/auth/step-up`` rather than by writing ``step_up_scope`` by hand, because a
hand-built grant cannot catch the two failures that actually happen: an action spelled as a
``Permission`` value rather than a ``StepUpAction``, and a subject id stringified differently
on the two sides of a whole-string comparison.

**3. §9.1's first rule, from the side that would break.** Block/unblock is a single database
transaction, so the audit row goes *inside* it and an unaudited state change must be
impossible. A test shaped "block, then assert the row exists" passes under an implementation
that writes the audit row in its own transaction too, so the assertion here is the converse:
the audit write is broken, and ``users.is_blocked`` must come back unchanged.

**There is no 404 anywhere in this file**, and that is the writer's design rather than an
omission: ``db.credits.set_blocked`` is an UPSERT precisely because the account an operator
reaches for this button often has no ``users`` row at all, which is the exact population a
rowcount-checked ``UPDATE`` would silently fail for (§5.11).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Final

import httpx
import pytest
import sqlalchemy as sa

from bayram.admin import audit_sink
from bayram.admin.container import AdminContainer
from bayram.admin.errors import AdminErrorCode
from bayram.admin.routers.users import USER_BLOCK_PATH, USER_UNBLOCK_PATH
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import AdminAuditRow, AuditOutcome
from bayram.db.models.user import UserRow
from tests.test_admin.conftest import (
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
from tests.test_admin.test_users_router import NOW, seed_user

TELEGRAM_USER_ID: Final[int] = 987_654_321
#: An id with no ``users`` row anywhere — the account the UPSERT exists for.
UNSEEN_USER_ID: Final[int] = 555_000_222

BLOCK_URL: Final[str] = USER_BLOCK_PATH.format(telegram_user_id=TELEGRAM_USER_ID)
UNBLOCK_URL: Final[str] = USER_UNBLOCK_PATH.format(telegram_user_id=TELEGRAM_USER_ID)


@dataclass(frozen=True, slots=True)
class Panel:
    container: AdminContainer
    http: httpx.AsyncClient


@pytest.fixture
async def panel() -> AsyncIterator[Panel]:
    async with (
        open_container(make_settings(), FakeRedis(), MemoryRateLimits()) as container,
        open_client(container) as http,
    ):
        yield Panel(container=container, http=http)


async def signed_in(panel: Panel, *, role: AdminRole = AdminRole.ADMIN) -> str:
    """Sign in as ``role``. ADMIN by default: §12.2's block row starts there, so a file that
    only ever used OWNER would not notice the cell narrowing."""
    username = f"{role.value}-account"
    await create_account(panel.container, username=username, role=role)
    assert (await sign_in(panel.http, username=username, password=PASSWORD)).status_code == 200
    return username


async def step_up(panel: Panel, *, subject: int, scope: str = "user.block") -> httpx.Response:
    """``POST /api/auth/step-up`` the way the SPA does — the only writer of ``step_up_scope``."""
    return await panel.http.post(
        "/api/auth/step-up",
        json={"password": PASSWORD, "scope": scope, "subjectId": str(subject)},
        headers=csrf_headers(panel.http),
    )


async def post_block(panel: Panel, url: str = BLOCK_URL, **body: Any) -> httpx.Response:
    payload: dict[str, Any] = {"reasonCode": AuditReasonCode.ABUSE_REPORT.value, **body}
    return await panel.http.post(url, json=payload, headers=csrf_headers(panel.http))


async def is_blocked(container: AdminContainer, telegram_user_id: int) -> bool | None:
    """``users.is_blocked``, or ``None`` when there is no row at all."""
    async with container.session_factory.begin() as db:
        found = await db.scalar(
            sa.select(UserRow.is_blocked).where(UserRow.telegram_user_id == telegram_user_id)
        )
        return None if found is None else bool(found)


async def audit_rows(container: AdminContainer, action: AuditAction) -> list[AdminAuditRow]:
    async with container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.action == action)
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


async def seed_account_row(panel: Panel, *, is_barred: bool = False) -> None:
    """One ``users`` row, through ``test_users_router``'s own seeder so both files agree."""
    await seed_user(
        panel.container, telegram_user_id=TELEGRAM_USER_ID, is_blocked=is_barred, created_at=NOW
    )


# ---------------------------------------------------------------------------
# The two halves of the split row
# ---------------------------------------------------------------------------
async def test_a_role_with_no_cell_is_forbidden_rather_than_prompted(panel: Panel) -> None:
    # Arrange — SUPPORT holds no block cell at all, so no grant would ever help them and the
    # SPA must not open a re-authentication prompt.
    await seed_account_row(panel)
    await signed_in(panel, role=AdminRole.SUPPORT)

    # Act
    response = await post_block(panel)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value
    assert await is_blocked(panel.container, TELEGRAM_USER_ID) is False


async def test_an_eligible_role_without_a_grant_is_asked_to_re_authenticate(
    panel: Panel,
) -> None:
    # Arrange — the other half: ADMIN holds the cell and reaches the handler, which refuses
    # for want of a scoped grant. A router guarded by USER_BLOCK itself would answer this
    # same code to an operator who HAD one, for ever.
    await seed_account_row(panel)
    await signed_in(panel)

    # Act
    response = await post_block(panel)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value
    assert await is_blocked(panel.container, TELEGRAM_USER_ID) is False


@pytest.mark.parametrize(
    ("subject", "scope"),
    [(UNSEEN_USER_ID, "user.block"), (TELEGRAM_USER_ID, "reveal")],
    ids=["another-subject", "another-action"],
)
async def test_a_grant_for_something_else_does_not_block_this_account(
    panel: Panel, subject: int, scope: str
) -> None:
    # Arrange — the confused deputy the scope exists to close, in both directions.
    await seed_account_row(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=subject, scope=scope)).status_code == 200

    # Act
    response = await post_block(panel)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value
    assert await is_blocked(panel.container, TELEGRAM_USER_ID) is False


# ---------------------------------------------------------------------------
# The action itself
# ---------------------------------------------------------------------------
async def test_a_scoped_step_up_blocks_the_account_and_audits_it(panel: Panel) -> None:
    # Arrange
    await seed_account_row(panel)
    username = await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200

    # Act
    response = await post_block(panel, reasonRef="TICKET-41")

    # Assert — the state moved, the response says so, and the row that proves who did it is
    # there with the column name and not its value.
    assert response.status_code == 200
    body = response.json()
    assert body["isBlocked"] is True
    assert body["telegramUserId"] == TELEGRAM_USER_ID
    assert body["telegramUserIdMasked"].endswith("321")
    assert await is_blocked(panel.container, TELEGRAM_USER_ID) is True

    rows = await audit_rows(panel.container, AuditAction.USER_BLOCK)
    assert len(rows) == 1
    assert rows[0].subject_type == "user"
    assert rows[0].subject_id == str(TELEGRAM_USER_ID)
    assert rows[0].actor_username == username
    assert rows[0].outcome is AuditOutcome.OK
    assert rows[0].reason_code is AuditReasonCode.ABUSE_REPORT
    assert rows[0].reason_ref == "TICKET-41"
    assert rows[0].field_names == ["users.is_blocked"]


async def test_unblocking_is_its_own_action_rather_than_a_flag_on_the_first(
    panel: Panel,
) -> None:
    """Two routes and two audit actions, because §12.4 queries ``action`` by equality.

    "Show me every block this week" has to be an indexed filter rather than a read of every
    row's fields, and a single route taking ``{"isBlocked": false}`` would audit an unblock as
    a block the first time somebody sent the wrong body.
    """
    # Arrange — an already-barred account.
    await seed_account_row(panel, is_barred=True)
    await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200

    # Act
    response = await post_block(
        panel, UNBLOCK_URL, reasonCode=AuditReasonCode.CUSTOMER_REQUEST.value
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["isBlocked"] is False
    assert await is_blocked(panel.container, TELEGRAM_USER_ID) is False
    assert len(await audit_rows(panel.container, AuditAction.USER_UNBLOCK)) == 1
    assert await audit_rows(panel.container, AuditAction.USER_BLOCK) == []


async def test_blocking_an_account_that_has_no_users_row_creates_one(panel: Panel) -> None:
    """The whole reason ``set_blocked`` is an UPSERT (§5.11), asserted from the API.

    An account that has not spoken to the bot since the onboarding deploy has no ``users``
    row, and that is exactly the account an operator reaches for this button. A 404 — or a
    rowcount-checked ``UPDATE`` — would refuse the population the action exists to serve.
    """
    # Arrange — nothing seeded at all.
    await signed_in(panel)
    assert (await step_up(panel, subject=UNSEEN_USER_ID)).status_code == 200
    url = USER_BLOCK_PATH.format(telegram_user_id=UNSEEN_USER_ID)

    # Act
    response = await post_block(panel, url)

    # Assert
    assert response.status_code == 200
    assert await is_blocked(panel.container, UNSEEN_USER_ID) is True


async def test_blocking_a_blocked_account_is_a_no_op_that_still_writes_a_row(
    panel: Panel,
) -> None:
    """§9.2: "naturally idempotent; pressing it twice is information"."""
    # Arrange
    await seed_account_row(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200

    # Act
    first = await post_block(panel)
    second = await post_block(panel)

    # Assert — one state, two rows.
    assert (first.status_code, second.status_code) == (200, 200)
    assert await is_blocked(panel.container, TELEGRAM_USER_ID) is True
    assert len(await audit_rows(panel.container, AuditAction.USER_BLOCK)) == 2


async def test_a_body_without_a_reason_code_is_refused_before_anything_moves(
    panel: Panel,
) -> None:
    # Arrange — §12.4: every destructive action requires a reason, and a default would make
    # the accountability optional.
    await seed_account_row(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200

    # Act
    response = await panel.http.post(BLOCK_URL, json={}, headers=csrf_headers(panel.http))

    # Assert
    assert response.status_code == 422
    assert await is_blocked(panel.container, TELEGRAM_USER_ID) is False


async def test_control_characters_are_stripped_from_the_operators_reason(panel: Panel) -> None:
    # Arrange — ``reasonText`` reaches a 90-day column, and a newline in it is either a paste
    # accident or an attempt to forge a second line in whatever renders it.
    await seed_account_row(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200

    # Act — one with text to clean, one with an explicit ``null``, which the SPA sends for an
    # untouched optional field and which must reach the column as ``NULL`` rather than as "".
    cleaned = await post_block(panel, reasonText="  spamming\nthe bot\r  ")
    explicit_null = await post_block(panel, reasonText=None)

    # Assert
    assert (cleaned.status_code, explicit_null.status_code) == (200, 200)
    rows = await audit_rows(panel.container, AuditAction.USER_BLOCK)
    assert [row.reason_text for row in rows] == ["spammingthe bot", None]


async def test_a_block_whose_audit_row_cannot_be_written_changes_nothing(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9.1's first rule, asserted from the side that would break.

    The audit row rides the request's transaction, which ``deps.get_db_session`` rolls back on
    any exception — so an implementation that wrote the row in a transaction of its own, or
    that swallowed the failure, would leave a blocked account with nothing recording who
    blocked it. The converse test ("block, then assert the row exists") passes under both
    implementations and proves nothing.
    """

    # Arrange
    async def _refuse(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the audit log is unavailable")

    await seed_account_row(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200
    monkeypatch.setattr(audit_sink, "record", _refuse)

    # Act
    response = await post_block(panel)

    # Assert — the request failed and the account is exactly as it was.
    assert response.status_code == 500
    assert await is_blocked(panel.container, TELEGRAM_USER_ID) is False
