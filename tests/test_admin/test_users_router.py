"""The ``/users`` READS over the real ASGI stack — real container, login and guard.

The two writes on this namespace — ``POST /block`` and ``POST /unblock``, built by
:func:`~bayram.admin.routers.users.build_user_block_router` — live in
``test_user_actions_router.py``, because everything they need (a scoped step-up, an audit row,
a rolled-back transaction) is machinery no read here touches. The ledger read and the grant
that hang off the same path are in ``test_credits_router.py`` for the same reason.


The assertion this file exists for is the negative one. ``/users/{id}/wizard-state`` is a
reveal surface wearing a read's clothes: the FSM draft holds the recipient's display name,
the free-text note and the whole approved lyric, and for a session somebody abandoned it is
the only copy of any of it that exists anywhere. So the draft seeded here is a **real**
:class:`~bayram.bot.draft.WizardDraft`, written through aiogram's own storage, carrying a note
and a name distinctive enough that a substring test cannot pass by accident — and neither
string may appear in the response body at any role, OWNER included. §12.3 has no unmasked
variant of this screen; the plaintext is reachable only through ``POST /reveal`` in Phase 2.

**There is no 403 case in this file, and that is the matrix rather than an omission.** §12.2
gives RECORDS_READ and WIZARD_STATE_READ as **M** in all four cells, so no role is refused.
What is asserted instead is that each router carries exactly one guard, that the two guards
name *different* permissions, and that the matrix rows really are full — which is the test
that starts failing on the day somebody narrows one of them.

**The avatar route is the one place a customer's face crosses this wire, and PD-1 decided
what that costs.** It is an ordinary ``RECORDS_READ`` on the same router as the row it
belongs to: no step-up, no reveal budget unit, **no per-view audit row**, and no probe. That
absence is a decision rather than an oversight, so it is pinned here by
:func:`test_reading_an_avatar_writes_no_audit_row` — otherwise the first person to read the
route would "restore" the missing write and quietly change the product owner's answer. The
positive half of the same trade is asserted just as hard: every role in the matrix row may
read it, because a face is visible to everyone who can already list the account.

The four refusals around it are asserted in the order the handler makes them — row, then
MIME, then bytes — because that order is the control. In particular the two 404 arms must be
**indistinguishable**: an id nobody has ever seen and an account with no photo answer the
same body, or the route becomes an existence oracle for a Telegram id that anybody may guess.
The SPA's ``<img onError>`` draws the monogram, so a 404 is the designed answer here and not
a failure to handle.

The routers are included here rather than assumed: a later step wires them into
``create_app``, and this file must pass on either side of that.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Final, cast
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from fastapi import FastAPI
from fastapi.routing import APIRoute
from redis.asyncio import Redis

from bayram.admin.container import AdminContainer
from bayram.admin.deps import RequirePermission
from bayram.admin.routers.users import (
    AVATAR_MIMES,
    USER_AVATAR_PATH,
    USER_ORDERS_PATH,
    USER_PATH,
    USER_STATS_PATH,
    USERS_PATH,
    WIZARD_STATE_PATH,
    build_users_router,
    build_wizard_state_router,
)
from bayram.admin.schemas import users as user_schemas
from bayram.admin.schemas.segment import (
    SEGMENT_SCHEMA_VERSION,
    RuleModel,
    SegmentModel,
    encode_segment,
)
from bayram.admin.security.permissions import RBAC_MATRIX, Permission
from bayram.admin.serializers.redaction import mask_name, mask_phone, mask_username
from bayram.contracts import Err, Language, OrderState, Result
from bayram.db.admin.segment import MatchMode, SegmentOp
from bayram.db.admin.sql import MAX_SEARCH_CHARS
from bayram.db.base import utc_now
from bayram.db.enums import AdminRole, CreditEntryKind, CreditReason
from bayram.db.models.admin_audit import AdminAuditRow
from bayram.db.models.credit_account import CreditAccountRow
from bayram.db.models.credit_ledger import CreditLedgerRow
from bayram.db.models.order import OrderRow
from bayram.db.models.user import UserRow
from bayram.db.models.user_profile import UserProfileRow
from bayram.storage import LocalFileStorage
from bayram.user_profiles import AVATAR_MIME, avatar_key
from tests.test_admin.conftest import (
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    make_settings,
    open_client,
    open_container,
    sign_in,
)
from tests.test_admin.test_wizard_state import NOTE, RECIPIENT_DISPLAY, make_draft

#: A fixed instant, so the window and ordering assertions are not races.
NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)
TELEGRAM_USER_ID: Final[int] = 987_654_321
OTHER_USER_ID: Final[int] = 123_456_789
#: A third seeded account, for the assertions that need all THREE credit shapes at once —
#: metered with credits, metered to zero, and no ``credit_accounts`` row at all.
NEVER_METERED_USER_ID: Final[int] = 111_222_333
#: A fourth account, barred by US and blocking the bot at the same time. It exists for the
#: stat strip alone: ``blocked`` and ``botBlocked`` are opposite facts about opposite subjects
#: and an account can carry both, so without this row the two counts would look like a
#: partition and "``matched`` is not the sum" would be prose nothing checks.
BOTH_BARRED_USER_ID: Final[int] = 444_555_666
#: An id no seeded row uses, for the 404 paths.
UNKNOWN_USER_ID: Final[int] = 555_000_222

USER_URL: Final[str] = USER_PATH.format(telegram_user_id=TELEGRAM_USER_ID)
USER_ORDERS_URL: Final[str] = USER_ORDERS_PATH.format(telegram_user_id=TELEGRAM_USER_ID)
WIZARD_STATE_URL: Final[str] = WIZARD_STATE_PATH.format(telegram_user_id=TELEGRAM_USER_ID)
AVATAR_URL: Final[str] = USER_AVATAR_PATH.format(telegram_user_id=TELEGRAM_USER_ID)

#: What one account told us about itself. The names carry U+02BB — correct Uzbek Latin
#: orthography — so a masker that normalised on its way to the wire would show up here as a
#: changed letter rather than as a passing test, and the number is a real Uzbek mobile so the
#: mask assertions are about a value ``normalise_phone`` would actually have produced.
PROFILE_PHONE: Final[str] = "+998901234542"
PROFILE_USERNAME: Final[str] = "gulomjon"
PROFILE_FIRST_NAME: Final[str] = "Gʻulom"
PROFILE_LAST_NAME: Final[str] = "Oʻktamov"
#: Every plaintext the profile holds, as the substrings a leak would show up as. §12.3 has no
#: unmasked variant of this screen at any role, OWNER included.
PROFILE_PLAINTEXTS: Final[tuple[str, ...]] = (
    PROFILE_PHONE,
    PROFILE_USERNAME,
    PROFILE_FIRST_NAME,
    PROFILE_LAST_NAME,
)

#: The stored photo, as bytes the response is compared against exactly. Not a real JPEG and
#: deliberately so: the route serves what the volume holds under a key it rebuilt, and never
#: sniffs, re-encodes or validates it — the ``Content-Type`` comes from the allowlist check on
#: the column, which is the assertion :func:`test_a_stored_mime_the_route_does_not_serve_is_415`
#: is about. A real JPEG here would let a future re-encode pass unnoticed.
AVATAR_BYTES: Final[bytes] = b"\xff\xd8\xff\xe0" + b"the exact bytes that were stored" * 4
#: A different photo, written under a different account's key, so "the route rebuilt its own
#: key" is asserted against a volume that holds a wrong answer to serve.
DECOY_BYTES: Final[bytes] = b"\xff\xd8\xff\xe0" + b"a photograph of somebody else" * 4

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
    blocked_bot_at: datetime | None = None,
    created_at: datetime | None = None,
) -> UserRow:
    """One ``users`` row through the real model — the row ``_ensure_user`` would write.

    ``is_blocked`` and ``blocked_bot_at`` are two arguments and never one, because they are
    two facts with opposite subjects: the first is OUR bar on the account and the second is
    the customer blocking the bot. One account can carry both, and the stat-strip assertions
    below exist precisely to pin that the two counts overlap rather than partition — see
    :func:`test_the_strip_counts_an_account_barred_both_ways_in_both_figures`.
    """
    async with container.session_factory.begin() as db:
        row = UserRow(
            telegram_user_id=telegram_user_id,
            ui_language=ui_language,
            is_blocked=is_blocked,
            blocked_bot_at=blocked_bot_at,
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


async def seed_profile(
    container: AdminContainer,
    user: UserRow,
    *,
    phone_e164: str | None = PROFILE_PHONE,
    telegram_username: str | None = PROFILE_USERNAME,
    first_name: str | None = PROFILE_FIRST_NAME,
    last_name: str | None = PROFILE_LAST_NAME,
    avatar_mime: str | None = AVATAR_MIME,
    avatar_stored_at: datetime | None = NOW,
) -> UserProfileRow:
    """One ``user_profiles`` row — what the bot writes when somebody finishes onboarding.

    Every column is defaulted to "present" so a test that wants an absence has to say which
    one it is removing. The two avatar columns move together by convention and apart by
    argument: ``avatar_stored_at=None`` is the account that never sent a photo, and an
    ``avatar_mime`` the route refuses is a row a future writer could produce, which is
    exactly the case the 415 exists for.
    """
    async with container.session_factory.begin() as db:
        row = UserProfileRow(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            phone_e164=phone_e164,
            telegram_username=telegram_username,
            first_name=first_name,
            last_name=last_name,
            avatar_mime=avatar_mime,
            avatar_stored_at=avatar_stored_at,
            phone_shared_at=NOW,
            onboarded_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(row)
        await db.flush()
        return row


async def store_avatar(
    container: AdminContainer, user: UserRow, *, data: bytes = AVATAR_BYTES
) -> str:
    """Write the bytes where the route will look for them, and return that key.

    Built through :func:`~bayram.user_profiles.avatar_key` rather than spelled out, because a
    literal here would pass while the route and the writer disagreed — which is the one
    failure the absence of an ``avatar_storage_key`` column makes structurally impossible and
    a hand-written key in a test would quietly reintroduce.
    """
    key = avatar_key(user.id)
    stored = await container.storage.put(key, data, content_type=AVATAR_MIME)
    assert not isinstance(stored, Err), stored
    return key


@dataclass(frozen=True, slots=True)
class AvatarPanel:
    """A running panel whose object store is a temporary directory.

    The shared ``container`` fixture points :class:`LocalFileStorage` at the configured data
    root, and a test that wrote a photograph there would leave one in the working tree. The
    volume moves with ``dataclasses.replace`` so the engine, the pool and the schema shortcut
    stay exactly production's and only the archive is a test's — the same shape
    ``test_asset_stream.py`` uses, for the same reason.
    """

    container: AdminContainer
    client: httpx.AsyncClient
    archive: Path


@pytest.fixture
async def avatar_panel(tmp_path: Path) -> AsyncIterator[AvatarPanel]:
    archive = tmp_path / "archive"
    archive.mkdir()
    async with open_container(make_settings(), FakeRedis(), MemoryRateLimits()) as built:
        container = dataclasses.replace(built, storage=LocalFileStorage(archive))
        async with open_client(container) as http:
            yield AvatarPanel(container=container, client=http, archive=archive)


async def seeded_avatar(panel: AvatarPanel, *, role: AdminRole = AdminRole.ADMIN) -> UserRow:
    """The ordinary case: an account, a profile claiming a photo, the bytes, a signed-in operator."""
    user = await seed_user(panel.container)
    await seed_profile(panel.container, user)
    await store_avatar(panel.container, user)
    await signed_in(panel.container, panel.client, role=role)
    return user


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


@pytest.mark.parametrize(
    "path", [USERS_PATH, USER_STATS_PATH, USER_URL, USER_ORDERS_URL, WIZARD_STATE_URL], ids=str
)
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
    # Arrange — two orders, one of them paid, three hours apart, and the profile the join
    # picks up beside them.
    user = await seed_user(container)
    await seed_profile(container, user)
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
    # Assert — the nine profile fields, every one of them masked or a stamp. The join is
    # OUTER, so a row appearing at all is not evidence that it was read; these are.
    assert row["isProfilePresent"] is True
    assert row["telegramUsernameMasked"] == mask_username(PROFILE_USERNAME)
    assert row["firstNameMasked"] == mask_name(PROFILE_FIRST_NAME)
    assert row["lastNameMasked"] == mask_name(PROFILE_LAST_NAME)
    assert row["phoneMasked"] == mask_phone(PROFILE_PHONE)
    assert row["phoneSharedAt"].startswith("2026-03-21")
    assert row["avatarFetchedAt"].startswith("2026-03-21")
    assert row["hasAvatar"] is True
    assert row["avatarUrl"] == AVATAR_URL


async def test_a_user_with_no_profile_row_reports_absence_rather_than_omitting_the_fields(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — somebody who has answered the language question and nothing else, and also
    # somebody whose ``/forget`` deleted the row: PD-3 leaves no purge stamp, so the panel
    # sees one shape for both and must not imply there is more to know.
    await seed_user(container)
    await signed_in(container, client)

    # Act
    row = (await client.get(USERS_PATH)).json()["items"][0]

    # Assert — present-and-null, never absent. A missing key is SCHEMA_DRIFT in the SPA,
    # because the nine fields are ``.nullable()`` and not ``.nullish()``: "the API stopped
    # sending this" and "this customer has not told us" must not render the same.
    assert row["isProfilePresent"] is False
    assert row["telegramUsernameMasked"] is None
    assert row["firstNameMasked"] is None
    assert row["lastNameMasked"] is None
    assert row["phoneMasked"] is None
    assert row["phoneSharedAt"] is None
    assert row["avatarFetchedAt"] is None
    assert row["hasAvatar"] is False
    assert row["avatarUrl"] is None


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
    ("half", "expected"),
    [("from", OTHER_USER_ID), ("to", TELEGRAM_USER_ID)],
    ids=["from-runs-to-now", "to-is-open-below"],
)
async def test_one_sided_windows_are_answered_rather_than_refused(
    container: AdminContainer, client: httpx.AsyncClient, half: str, expected: int
) -> None:
    # Arrange — "accounts created since the campaign started" has no upper bound an operator
    # would type, and used to be a 422 (AUDIT_AND_REDESIGN §2.2). ``NOW`` is a fixed instant in
    # the past, so the end the server supplies for the open ``from`` is later than both rows
    # and cannot be what excludes the older one.
    await seed_user(container, created_at=NOW - timedelta(days=30))
    await seed_user(container, telegram_user_id=OTHER_USER_ID, created_at=NOW)
    await signed_in(container, client)

    # Act
    boundary = (NOW - timedelta(days=1)).isoformat()
    body = (await client.get(USERS_PATH, params={half: boundary})).json()

    # Assert
    assert [row["telegramUserId"] for row in body["items"]] == [expected]


async def test_the_search_matches_the_telegram_id_and_nothing_the_reveal_gate_protects(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``?q=`` over the wire: what it finds, and the far more important half of what it does not.

    Every free-text column ``/users`` can reach lives on ``user_profiles``, is masked at all
    four roles, and is reachable only through ``POST /reveal``. A substring filter over any of
    them would let an operator confirm a customer's name or phone number a few characters at a
    time, with no step-up, no budget unit and no audit row — which is a reveal bypass wearing a
    search box. The Telegram id is searchable precisely because this same response already
    prints it in full, so matching a substring of it discloses nothing the caller did not have.
    """
    # Arrange — one fully onboarded account, so every masked value is really in the row.
    user = await seed_user(container, created_at=NOW)
    await seed_profile(container, user)
    await seed_user(container, telegram_user_id=OTHER_USER_ID, created_at=NOW)
    await signed_in(container, client)

    # Act
    async def search(term: str) -> list[int]:
        body = (await client.get(USERS_PATH, params={"q": term})).json()
        return [row["telegramUserId"] for row in body["items"]]

    # Assert — a substring of the id finds it…
    assert await search(str(TELEGRAM_USER_ID)[2:8]) == [TELEGRAM_USER_ID]
    # …and every masked value, probed with the exact string the row holds, finds nobody.
    for masked in PROFILE_PLAINTEXTS:
        assert await search(masked) == [], masked


async def test_a_search_longer_than_the_cap_is_refused_by_name(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """The cap is declared on the route so an over-long ``q`` is a 422 naming the parameter.

    ``search_clause`` truncates as a backstop, and a truncated substring pattern *widens* the
    match — so without this the operator would get extra rows and nothing on the page to
    explain them.
    """
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(USERS_PATH, params={"q": "9" * (MAX_SEARCH_CHARS + 1)})

    # Assert
    assert response.status_code == 422
    assert "q" in response.text


async def test_the_row_carries_the_credit_account_and_nulls_where_there_is_none(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``null`` is a third value on this wire and the SPA must be able to see it.

    A customer with no ``credit_accounts`` row has never been metered and is still owed a whole
    rolling allowance; ``0`` says they have spent everything. The detail additionally carries
    ``creditsProjected``, which is what the BOT would tell them.

    Under the shipped paywall the two AGREE, and this assertion used to say they differ. It
    read ``detail["creditsProjected"] == DEFAULT_ENTITLEMENT_POLICY.allowance_credits`` — a
    fact about a dataclass default dressed as a fact about a customer's balance — and it was
    the pin that made the projection's 3-credit overstatement green. ``free_allowance_credits``
    ships at 0, so a stored 0 projects to 0. The pair is still published because it *can*
    differ, on a deployment that grants an allowance; that half is asserted by
    :func:`test_the_projection_is_computed_with_this_deployments_free_allowance`, which is
    where the deliberate divergence now lives.
    """
    # Arrange — one metered account, one that has never been charged or granted.
    await seed_user(container, created_at=NOW)
    await seed_user(container, telegram_user_id=OTHER_USER_ID, created_at=NOW)
    async with container.session_factory.begin() as db:
        db.add(
            CreditAccountRow(
                telegram_user_id=TELEGRAM_USER_ID,
                balance=0,
                lifetime_granted=3,
                allowance_period_index=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    await signed_in(container, client)

    # Act
    listed = (await client.get(USERS_PATH)).json()["items"]
    detail = (await client.get(USER_URL)).json()

    # Assert
    rows = {row["telegramUserId"]: row for row in listed}
    assert rows[TELEGRAM_USER_ID]["creditBalance"] == 0
    assert rows[TELEGRAM_USER_ID]["lifetimeCreditsGranted"] == 3
    assert rows[TELEGRAM_USER_ID]["allowancePeriod"] is None
    assert rows[OTHER_USER_ID]["creditBalance"] is None
    assert rows[OTHER_USER_ID]["lifetimeCreditsGranted"] is None

    # The stored column says nothing left, and so does the projection: nothing is given away.
    assert detail["user"]["creditBalance"] == 0
    assert detail["creditsProjected"] == 0
    assert detail["inFlightRenderCount"] == 0


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, [NEVER_METERED_USER_ID, OTHER_USER_ID, TELEGRAM_USER_ID]),
        ({"hasBalance": "true"}, [TELEGRAM_USER_ID]),
        ({"hasBalance": "false"}, [NEVER_METERED_USER_ID, OTHER_USER_ID]),
    ],
    ids=["absent-does-not-filter", "true-is-strictly-positive", "false-is-the-complement"],
)
async def test_the_has_balance_chip_splits_the_list_in_two_with_nobody_left_over(
    container: AdminContainer,
    client: httpx.AsyncClient,
    params: dict[str, Any],
    expected: list[int],
) -> None:
    """``?hasBalance=`` over the wire — and the account with no ``credit_accounts`` row.

    There are THREE shapes here and only two values of the filter, so where the never-metered
    account lands is the decision this asserts: it is **not** a positive balance (the row is
    opened by the first charge or grant, so its absence means nobody has ever metered them),
    and ``false`` is the literal complement of ``true`` — never metered and spent-to-zero both
    land there. The parametrisation asserts the two halves add back up to the unfiltered page,
    which is what stops a future narrowing from stranding a customer no chip can reach.
    """
    # Arrange — one account with credits, one metered down to zero, one never metered at all.
    await seed_user(container, created_at=NOW - timedelta(days=2))
    await seed_user(container, telegram_user_id=OTHER_USER_ID, created_at=NOW - timedelta(days=1))
    await seed_user(container, telegram_user_id=NEVER_METERED_USER_ID, created_at=NOW)
    async with container.session_factory.begin() as db:
        db.add(
            CreditAccountRow(
                telegram_user_id=TELEGRAM_USER_ID,
                balance=2,
                lifetime_granted=5,
                allowance_period_index=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        db.add(
            CreditAccountRow(
                telegram_user_id=OTHER_USER_ID,
                balance=0,
                lifetime_granted=3,
                allowance_period_index=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    await signed_in(container, client)

    # Act
    body = (await client.get(USERS_PATH, params=params)).json()

    # Assert — newest account first.
    assert [row["telegramUserId"] for row in body["items"]] == expected


async def test_the_has_balance_total_is_counted_with_the_same_predicate_as_the_page(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``?withTotal=true`` must narrow by ``hasBalance`` too.

    The filter lives in ``_filtered``, which ``count_users`` and ``list_users`` share, for
    exactly this: a total computed without the predicate would label a one-row page "2" and an
    operator would go looking for the row the panel says it is hiding.
    """
    # Arrange
    await seed_user(container, created_at=NOW - timedelta(days=1))
    await seed_user(container, telegram_user_id=OTHER_USER_ID, created_at=NOW)
    async with container.session_factory.begin() as db:
        db.add(
            CreditAccountRow(
                telegram_user_id=TELEGRAM_USER_ID,
                balance=1,
                lifetime_granted=1,
                allowance_period_index=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    await signed_in(container, client)

    # Act
    body = (await client.get(USERS_PATH, params={"hasBalance": "true", "withTotal": "true"})).json()

    # Assert
    assert [row["telegramUserId"] for row in body["items"]] == [TELEGRAM_USER_ID]
    assert body["meta"]["total"] == 1


@pytest.mark.parametrize(
    ("published_grace", "expected"),
    [(None, 1), (300, 0)],
    ids=["unpublished-uses-the-shipped-default", "published-matches-the-worker"],
)
async def test_the_in_flight_count_is_counted_with_this_deployments_settlement_grace(
    published_grace: int | None, expected: int
) -> None:
    """``inFlightRenderCount`` must agree with the gate that actually refused the customer.

    The gate counts unsettled debits newer than ``now - settlement_grace_s``, and that grace
    is the WORKER's — ``BAYRAM_SETTLEMENT_GRACE_S`` or derived from its queue ladder. This read
    used to default it to ``DEFAULT_ENTITLEMENT_POLICY``, so on a deployment that lowered the
    grace to five minutes the panel counted a half-hour-old debit the customer's own gate had
    already forgotten, and reported a refusal that was not happening. Under shipped defaults
    the two agree, which is exactly why nothing was red.

    One debit, thirty minutes old, and the two graces bracket it: 4550s counts it, 300s does
    not. The instant is taken from the real clock because the route reads ``utc_now()``.
    """
    # Arrange
    overrides: dict[str, Any] = (
        {} if published_grace is None else {"admin_settlement_grace_s": published_grace}
    )
    async with (
        open_container(make_settings(**overrides), FakeRedis(), MemoryRateLimits()) as container,
        open_client(container) as client,
    ):
        await seed_user(container, created_at=NOW)
        async with container.session_factory.begin() as db:
            db.add(
                CreditLedgerRow(
                    id=uuid4(),
                    telegram_user_id=TELEGRAM_USER_ID,
                    kind=CreditEntryKind.DEBIT,
                    reason=CreditReason.ORDER_RENDER,
                    delta=-1,
                    order_id=uuid4(),
                    generation=0,
                    idempotency_key=f"debit:{uuid4()}:0",
                    actor="pipeline",
                    created_at=utc_now() - timedelta(minutes=30),
                )
            )
        await signed_in(container, client)

        # Act
        detail = (await client.get(USER_URL)).json()

    # Assert
    assert detail["inFlightRenderCount"] == expected


@pytest.mark.parametrize(
    ("published_allowance", "expected"),
    [(0, 1), (3, 4)],
    ids=["the-shipped-paywall-gives-nothing-away", "a-legacy-free-tier"],
)
async def test_the_projection_is_computed_with_this_deployments_free_allowance(
    published_allowance: int, expected: int
) -> None:
    """``creditsProjected`` must be the number the CUSTOMER is shown, not a dataclass default.

    This is the router-level pin for the divergence that shipped with the paywall. The route
    used to build its :class:`~bayram.entitlements.EntitlementPolicy` without an allowance, so it
    carried the dataclass's 3 while :func:`bayram.entitlements.resolve_entitlement_policy` read
    ``free_allowance_credits``, which went to 0. Both numbers land in
    :func:`bayram.db.credit_sql.read_balance`, which adds the allowance whenever one is due — and
    with the worker's 0 nothing ever stamps ``allowance_period_index``, so "due" is
    permanently true and the overstatement never expired. A customer who had paid 7 000 UZS
    for one song read 1 on their Confirm screen while the operator opening their record read
    4: exactly the ticket ``creditsProjected`` was published to close.

    So the arithmetic is asserted against the MIRROR rather than against a constant. One
    stored, paid credit and no minted allowance period: the shipped 0 leaves it at 1, and a
    deployment that still grants three adds them back. The second case is what keeps the pair
    honest — ``creditBalance`` and ``creditsProjected`` are two columns because they *can*
    disagree, and this is the configuration where they do.

    Built through a container of its own, like the settlement-grace case above, because the
    number comes from ``AdminSettings`` and the shared fixture publishes the defaults.
    """
    # Arrange — one credit bought and paid for, and no allowance window ever opened.
    async with (
        open_container(
            make_settings(admin_free_allowance_credits=published_allowance),
            FakeRedis(),
            MemoryRateLimits(),
        ) as container,
        open_client(container) as client,
    ):
        await seed_user(container, created_at=NOW)
        async with container.session_factory.begin() as db:
            db.add(
                CreditAccountRow(
                    telegram_user_id=TELEGRAM_USER_ID,
                    balance=1,
                    lifetime_granted=1,
                    allowance_period_index=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        await signed_in(container, client)

        # Act
        detail = (await client.get(USER_URL)).json()

    # Assert — the stored column never moves; only the projection follows the mirror.
    assert detail["user"]["creditBalance"] == 1
    assert detail["creditsProjected"] == expected


@pytest.mark.parametrize(
    "params",
    [
        {"uiLanguage": "klingon"},
        {"from": "2026-03-21T09:00:00", "to": "2026-03-22T09:00:00"},
        {"from": "2026-03-22T09:00:00Z", "to": "2026-03-21T09:00:00Z"},
    ],
    ids=["unknown-language", "naive-instant", "backwards"],
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
# The stat strip
# ---------------------------------------------------------------------------
def segment_token(*rules: RuleModel) -> str:
    """One ``?segment=`` value, built with the codec the SPA uses rather than by hand.

    Spelled out here rather than imported from ``test_segments_router``: that module's helper
    also takes a ``sort``, which this route deliberately does not accept, and a shared helper
    whose extra argument is meaningless on one of its two callers is how the next reader comes
    to believe ``/users/stats`` can be ordered.
    """
    return encode_segment(SegmentModel(v=SEGMENT_SCHEMA_VERSION, match=MatchMode.ALL, rules=rules))


async def seed_the_four_shapes(container: AdminContainer) -> None:
    """One account of each reachability shape — and the fourth is the whole point.

    Reachable, barred by us, blocking us, and **both at once**. The fourth account is what
    makes ``blocked`` and ``botBlocked`` provably overlapping counts rather than a partition
    somebody may later "simplify" into three numbers that add up. Ages descend by a day each
    so the window assertions below have something to cut.
    """
    await seed_user(container, created_at=NOW - timedelta(days=3))
    await seed_user(
        container,
        telegram_user_id=OTHER_USER_ID,
        ui_language=Language.RU,
        is_blocked=True,
        created_at=NOW - timedelta(days=2),
    )
    await seed_user(
        container,
        telegram_user_id=NEVER_METERED_USER_ID,
        blocked_bot_at=NOW,
        created_at=NOW - timedelta(days=1),
    )
    await seed_user(
        container,
        telegram_user_id=BOTH_BARRED_USER_ID,
        ui_language=Language.RU,
        is_blocked=True,
        blocked_bot_at=NOW,
        created_at=NOW,
    )


async def test_the_strip_reports_the_four_counts_and_nothing_else(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_the_four_shapes(container)
    await signed_in(container, client)

    # Act
    response = await client.get(USER_STATS_PATH)

    # Assert — the whole body, so a fifth field cannot arrive unnoticed. §6.1: an aggregate
    # surface carries counts and nothing else, and this route's four counts are exactly the
    # four ``SegmentBreakdown`` holds minus the language split ``/segments/preview`` publishes.
    assert response.status_code == 200
    assert response.json() == {"matched": 4, "reachable": 1, "blocked": 2, "botBlocked": 2}


async def test_the_strip_counts_an_account_barred_both_ways_in_both_figures(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``matched`` is not the sum, and this is the account that proves it.

    ``blocked`` is our bar and ``botBlocked`` is the customer's; the fourth seeded account has
    both, so the two counts overlap by one and only ``reachable`` is a complement. A client —
    or a future refactor — that added the three refusal figures to ``reachable`` would get five
    for a population of four, which is the arithmetic ``UserStatsView`` warns about in prose and
    this test pins in code.
    """
    # Arrange
    await seed_the_four_shapes(container)
    await signed_in(container, client)

    # Act
    body = (await client.get(USER_STATS_PATH)).json()

    # Assert
    assert body["matched"] == 4
    assert body["reachable"] + body["blocked"] + body["botBlocked"] == 5
    assert body["reachable"] == body["matched"] - 3


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"isBlocked": "true"},
        {"uiLanguage": ["ru"]},
        {"telegramUserId": OTHER_USER_ID},
        {"from": (NOW - timedelta(days=1, hours=12)).isoformat()},
        {"to": (NOW - timedelta(days=1, hours=12)).isoformat()},
        {"q": str(OTHER_USER_ID)[:4]},
        {"uiLanguage": ["ru"], "isBlocked": "true"},
    ],
    ids=[
        "unfiltered",
        "one-chip",
        "one-language",
        "by-id",
        "window-open-above",
        "window-open-below",
        "search",
        "two-chips-are-and",
    ],
)
async def test_the_strip_and_the_list_are_one_population_under_every_chip(
    container: AdminContainer, client: httpx.AsyncClient, params: dict[str, Any]
) -> None:
    """The strip is a caption for the rows, so the two must never describe different sets.

    Asserted against the LIST rather than against a hand-counted expectation, because the claim
    being made is an agreement between two endpoints and a literal on the right-hand side would
    let both drift together. ``matched`` is checked against the page's own length **and** against
    its ``meta.total``: the length is what an operator can see, and the total is the other
    aggregate over the same ``_filtered()``, so all three moving as one is the property
    :func:`~bayram.db.admin.users.segment_breakdown` exists to give.
    """
    # Arrange
    await seed_the_four_shapes(container)
    await signed_in(container, client)

    # Act — the same query string to both, the list's limit high enough that no row is paged out.
    stats = (await client.get(USER_STATS_PATH, params=params)).json()
    listing = (
        await client.get(USERS_PATH, params={**params, "limit": 50, "withTotal": "true"})
    ).json()

    # Assert
    assert listing["meta"]["isTotalExact"] is True
    assert stats["matched"] == listing["meta"]["total"] == len(listing["items"])


async def test_the_strip_honours_the_segment_document_the_list_pages(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``?segment=`` narrows the strip too, and it is the narrowing an operator cannot see.

    The six chips are on the screen; the segment document is a base64url token on the URL. So
    it is the one filter whose absence from an aggregate would look entirely correct — the
    strip would simply report a bigger population than the rows under it, with nothing on the
    page to explain the difference. ``build_filters`` does not resolve the token (``build_query``
    does, because the sort that rides on it also chooses the cursor), which is why the handler
    takes ``?segment=`` itself and folds it into the same ``UserFilters``.
    """
    # Arrange — the two Russian-speaking accounts, one of which is also barred both ways.
    await seed_the_four_shapes(container)
    await signed_in(container, client)
    token = segment_token(RuleModel(field="ui_language", op=SegmentOp.EQ, value=Language.RU.value))

    # Act
    stats = (await client.get(USER_STATS_PATH, params={"segment": token})).json()
    listing = (await client.get(USERS_PATH, params={"segment": token, "withTotal": "true"})).json()

    # Assert — and the unfiltered strip is bigger, so the token is what did the narrowing
    # rather than an empty database flattering the comparison.
    assert stats == {"matched": 2, "reachable": 0, "blocked": 2, "botBlocked": 1}
    assert stats["matched"] == listing["meta"]["total"] == len(listing["items"])
    assert (await client.get(USER_STATS_PATH)).json()["matched"] == 4


async def test_a_segment_token_this_route_cannot_read_is_refused_the_way_the_list_refuses_it(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the strip shares the codec and the compiler with the list, so it must share
    # their refusal: a token that decodes to nothing meaningful is a 422 naming the parameter,
    # never a strip quietly describing everybody.
    await signed_in(container, client)

    # Act
    response = await client.get(USER_STATS_PATH, params={"segment": "not-a-segment"})

    # Assert
    assert response.status_code == 422


def test_the_strip_declares_no_parameter_it_cannot_honour() -> None:
    """The OpenAPI document is the assertion, because it is the thing that would be lying.

    FastAPI ignores an undeclared query parameter, so a handler that took ``limit`` and
    discarded it could never be caught by sending one — the damage is done in the schema every
    generated client and every operator reads. ``?limit=``, ``?cursor=``, ``?sort=`` and
    ``?sortDir=`` are therefore asserted ABSENT from this route and present on the list, and
    the eight the two share are asserted equal, so a chip added to ``build_filters`` reaches
    both or fails here.
    """
    # Arrange — the router alone; no container, no database, no session.
    application = FastAPI()
    application.include_router(build_users_router())

    # Act
    document = application.openapi()

    def query_names(path: str) -> set[str]:
        return {item["name"] for item in document["paths"][path]["get"].get("parameters", [])}

    # Assert
    paging = {"limit", "cursor", "sort", "sortDir"}
    assert query_names(USER_STATS_PATH) & paging == set()
    assert paging <= query_names(USERS_PATH)
    # ``withTotal`` is the list's alone: ``matched`` IS this route's total, and it is exact.
    assert query_names(USERS_PATH) - query_names(USER_STATS_PATH) == paging | {"withTotal"}
    assert query_names(USER_STATS_PATH) - query_names(USERS_PATH) == set()


def test_the_literal_stats_route_is_registered_before_the_route_that_takes_an_int() -> None:
    """Route matching is registration order, so this ordering is the route's existence.

    ``USER_PATH`` takes an ``int`` and ``stats`` is not one, so a ``/users/stats`` that reached
    it first would answer 422 about a ``telegramUserId`` the caller never sent. The same note
    sits beside ``ORDER_STATE_COUNTS_PATH``. Asserted here on the router rather than only
    behaviourally below, because the behavioural half passes for the wrong reason the day
    somebody makes the path parameter a ``str``.
    """
    # Arrange / Act
    paths = [route.path for route in build_users_router().routes if isinstance(route, APIRoute)]

    # Assert
    assert paths.index(USER_STATS_PATH) < paths.index(USER_PATH)


async def test_users_stats_does_not_resolve_to_the_by_id_route(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the behavioural half of the assertion above: what an operator's browser does.
    await seed_the_four_shapes(container)
    await signed_in(container, client)

    # Act
    response = await client.get(USER_STATS_PATH)

    # Assert — the counts, and not a 422 about an unparseable ``telegramUserId``.
    assert response.status_code == 200
    assert "matched" in response.json()
    assert "telegramUserId" not in response.json()


@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_every_role_in_the_matrix_row_may_read_the_strip(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — the strip is mounted on ``build_users_router`` and inherits its RECORDS_READ
    # guard, which §12.2 gives as M to all four roles: an operator who may page these rows may
    # certainly be told how many there are.
    await seed_the_four_shapes(container)
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(USER_STATS_PATH)

    # Assert
    assert response.status_code == 200


def test_the_strip_carries_the_routers_own_guard_and_not_a_handler_one() -> None:
    # Arrange — §12.1 T3: the guard is declared on the router so a route added next quarter
    # inherits it. ``/users/stats`` is that route, and this is the assertion that it inherited
    # rather than declared one of its own.
    router = build_users_router()
    stats = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == USER_STATS_PATH
    ]

    # Assert
    assert _router_permissions(router) == [Permission.RECORDS_READ]
    assert len(stats) == 1
    # ``APIRoute.dependencies`` is the router's list COPIED and then extended with the
    # decorator's own, so a guard declared on the handler reads back through it as an extra
    # entry. Equality with the router's single guard is therefore the assertion that this route
    # inherited one and declared none — which is the substitution §12.1 T3 forbids.
    assert _router_permissions(stats[0]) == [Permission.RECORDS_READ]


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


# ---------------------------------------------------------------------------
# The avatar — a face, at RECORDS_READ, with nothing recorded about the viewing
# ---------------------------------------------------------------------------
async def audit_row_count(container: AdminContainer) -> int:
    """How many audit rows exist, whatever wrote them."""
    async with container.session_factory.begin() as db:
        statement = sa.select(sa.func.count()).select_from(AdminAuditRow)
        return int((await db.execute(statement)).scalar_one())


async def _refuse_a_whole_object_read(self: LocalFileStorage, key: str) -> Result[bytes]:
    """A ``Storage.get`` that cannot be called by accident. See the test that installs it."""
    raise AssertionError(f"the avatar route must stream {key}, never read it whole")


async def test_the_avatar_route_streams_the_stored_image(avatar_panel: AvatarPanel) -> None:
    # Arrange — the ordinary case, end to end: a profile claiming a photo and the bytes on
    # the volume under the key the handler will rebuild.
    await seeded_avatar(avatar_panel)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert — the exact bytes, and the content type from the ALLOWLIST rather than from the
    # column: it is the membership test, never the stored string, that decides what the
    # browser is handed. Byte-exact because nothing on this path may re-encode; a route that
    # decoded and re-emitted the image would be doing image processing inside a request.
    assert response.status_code == 200
    assert response.headers["content-type"] == AVATAR_MIME
    assert response.content == AVATAR_BYTES
    assert response.headers["content-length"] == str(len(AVATAR_BYTES))


async def test_an_account_with_no_avatar_is_a_404_that_does_not_echo_the_id(
    avatar_panel: AvatarPanel,
) -> None:
    # Arrange — a real account with a real profile that never captured a photo. This is the
    # commonest answer this route gives, so it must be the cheap one: a 404 the SPA's
    # ``<img onError>`` turns into the monogram, never a 204, never a generated placeholder.
    # An invented picture is one the panel made up and an operator will read it as the
    # customer's.
    user = await seed_user(avatar_panel.container)
    await seed_profile(avatar_panel.container, user, avatar_mime=None, avatar_stored_at=None)
    await signed_in(avatar_panel.container, avatar_panel.client)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert — and the error body is a JSON payload, so §12.3 applies to it: the one value
    # this whole slice masks must not be repeated back in the one response nobody masked.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert str(TELEGRAM_USER_ID) not in response.text
    for plaintext in PROFILE_PLAINTEXTS:
        assert plaintext not in response.text


async def test_an_unknown_telegram_id_is_the_same_404(avatar_panel: AvatarPanel) -> None:
    # Arrange — the two absences the handler can see must be indistinguishable from outside,
    # or the route is an existence oracle: an id is a guessable integer, and a caller who
    # could tell "no such account" from "that account has no photo" could enumerate who has
    # an account here without ever loading a byte.
    user = await seed_user(avatar_panel.container)
    await seed_profile(avatar_panel.container, user, avatar_mime=None, avatar_stored_at=None)
    await signed_in(avatar_panel.container, avatar_panel.client)

    # Act
    known = await avatar_panel.client.get(AVATAR_URL)
    unknown = await avatar_panel.client.get(
        USER_AVATAR_PATH.format(telegram_user_id=UNKNOWN_USER_ID)
    )

    # Assert — same status and same message. The correlation id differs by design, so the
    # comparison is on the two halves an operator (or an enumerator) can read.
    assert known.status_code == unknown.status_code == 404
    assert known.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert known.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert str(UNKNOWN_USER_ID) not in unknown.text


async def test_a_stored_mime_the_route_does_not_serve_is_415_and_not_a_guess(
    avatar_panel: AvatarPanel,
) -> None:
    # Arrange — a row carrying a content type with a parameter on it. The idiom two files
    # away in the asset pipeline is ``mime.split(";")[0]``, which gives the right answer here
    # and quietly widens the allowlist to any ``image/jpeg; something-nobody-reviewed``. The
    # membership test is a WHOLE match, so this is a refusal rather than a byte stream whose
    # type the browser gets to sniff at.
    user = await seed_user(avatar_panel.container)
    await seed_profile(avatar_panel.container, user, avatar_mime="image/jpeg; charset=binary")
    await store_avatar(avatar_panel.container, user)
    await signed_in(avatar_panel.container, avatar_panel.client)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert — 415 before the bytes are ever opened, and the allowlist is one string long.
    assert response.status_code == 415
    assert frozenset({AVATAR_MIME}) == AVATAR_MIMES
    assert AVATAR_BYTES not in response.content


async def test_a_row_claiming_bytes_the_volume_does_not_hold_is_a_404_and_not_a_503(
    avatar_panel: AvatarPanel,
) -> None:
    # Arrange — the row says there is a photo and the archive disagrees, which is what a
    # half-finished write or a restored database over a fresh volume looks like. It must be a
    # 404 and not a 503: the first sends an operator looking for a retention bug, the second
    # for a mount that did not come up, and answering "storage failed" for an object that was
    # simply never written would send every one of them to the wrong place at once.
    user = await seed_user(avatar_panel.container)
    await seed_profile(avatar_panel.container, user)
    await signed_in(avatar_panel.container, avatar_panel.client)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert str(TELEGRAM_USER_ID) not in response.text


async def test_a_zero_byte_object_is_a_404_rather_than_a_422_about_the_request(
    avatar_panel: AvatarPanel,
) -> None:
    # Arrange — a zero-byte object is not a photograph, and it is the one absence that cannot
    # be reported by falling through: ``open_range`` refuses every range of an empty object
    # with a ValidationError, which ``unwrap`` would render as a 422 blaming a caller whose
    # request was perfectly well formed. The operator would then debug their own URL.
    user = await seed_user(avatar_panel.container)
    await seed_profile(avatar_panel.container, user)
    await store_avatar(avatar_panel.container, user, data=b"")
    await signed_in(avatar_panel.container, avatar_panel.client)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_the_avatar_route_rebuilds_its_own_storage_key(avatar_panel: AvatarPanel) -> None:
    # Arrange — a decoy object under another account's key, so the volume holds a wrong
    # answer to serve. There is no ``avatar_storage_key`` column and there must never be a
    # client-supplied path: the key is ``avatar_key(user_id)`` of a UUID this handler read
    # out of the database, and the path parameter is an ``int`` that reaches no key at all.
    user = await seeded_avatar(avatar_panel)
    other = await seed_user(avatar_panel.container, telegram_user_id=OTHER_USER_ID)
    await store_avatar(avatar_panel.container, other, data=DECOY_BYTES)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert
    assert response.content == AVATAR_BYTES
    assert response.content != DECOY_BYTES
    assert avatar_key(user.id) != avatar_key(other.id)


async def test_the_avatar_route_reads_through_size_and_open_range_and_never_get(
    avatar_panel: AvatarPanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — ``Storage.get`` reads a whole object into memory and is the shape a fifty-row
    # page cannot afford. More importantly, ``size``/``open_range`` are the two public members
    # the panel is allowed to reach for (§12.7): they keep confinement inside
    # ``LocalFileStorage._resolve``'s traversal guard rather than restating it here. A route
    # that fell back to ``get`` would still pass every other test in this section, so the
    # method is removed rather than counted.
    await seeded_avatar(avatar_panel)
    monkeypatch.setattr(LocalFileStorage, "get", _refuse_a_whole_object_read)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert
    assert response.status_code == 200
    assert response.content == AVATAR_BYTES


async def test_the_avatar_response_carries_no_cache_headers(avatar_panel: AvatarPanel) -> None:
    # Arrange — two halves, and the docstring says both so nobody "fixes" the missing ETag
    # later. First: ``SecurityHeadersMiddleware`` REPLACES ``Cache-Control`` outside
    # ``IMMUTABLE_PATH_PREFIX = "/assets/"`` rather than appending, so a handler-set value is
    # discarded on its way out and adding one would be dead code that looks load-bearing.
    # Second: it must stay that way. Any positive freshness — a max-age, an ETag a proxy can
    # revalidate against — would leave a customer's face in a shared cache after the session
    # that fetched it was revoked, which is precisely the disclosure the panel exists to
    # bound. The fifty-thumbnail cost is bounded at the SPA instead, by rendering the ``<img>``
    # only when ``hasAvatar`` and lazily.
    await seeded_avatar(avatar_panel)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert
    assert response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers
    assert "vary" not in response.headers
    assert "max-age" not in response.headers["cache-control"]


@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_every_role_in_the_matrix_row_may_read_the_avatar(
    avatar_panel: AvatarPanel, role: AdminRole
) -> None:
    # Arrange — PD-1's trade, stated as the assertion it is: the masked half of the record
    # and the picture of the person it describes are the same permission, so RECORDS_READ's
    # four **M** cells all reach the face. Narrowing this row is a product decision, and the
    # day somebody makes it this fails and they write the refusal test that must exist.
    await seeded_avatar(avatar_panel, role=role)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert
    assert response.status_code == 200
    assert response.content == AVATAR_BYTES


async def test_reading_an_avatar_writes_no_audit_row(avatar_panel: AvatarPanel) -> None:
    # Arrange — PD-1 removed the per-view audit row along with the step-up and the budget
    # unit, and an absence is exactly the kind of decision that gets "restored" by the next
    # person to read the handler. Counted around the request rather than asserted as an empty
    # table, because signing in writes rows of its own and a test that ignored them would
    # have to be rewritten the first time authentication changed.
    await seeded_avatar(avatar_panel)
    before = await audit_row_count(avatar_panel.container)

    # Act
    response = await avatar_panel.client.get(AVATAR_URL)

    # Assert — the bytes crossed and the log says nothing, which is the trade PD-1 chose.
    assert response.status_code == 200
    assert await audit_row_count(avatar_panel.container) == before


# ---------------------------------------------------------------------------
# The wire the profile crosses on — masked at every role, and one URL for the photo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_the_user_view_has_no_unmasked_name_or_number_at_any_role_including_owner(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — §12.3 has no unmasked variant of this screen, and ``UserView`` is
    # ``frozen=True, extra="forbid"``, so there is no field for one to arrive in. This is the
    # test that keeps it that way: the four plaintexts are asserted absent from the raw text
    # of both the list and the detail, at every role, so a leak nested under a key nobody
    # expected fails here rather than rendering on somebody's screen.
    user = await seed_user(container)
    await seed_profile(container, user)
    await signed_in(container, client, role=role)

    # Act
    listing = await client.get(USERS_PATH)
    detail = await client.get(USER_URL)

    # Assert
    assert listing.status_code == detail.status_code == 200
    for response in (listing, detail):
        for plaintext in PROFILE_PLAINTEXTS:
            assert plaintext not in response.text, (plaintext, role)
    # And the positive half: a body with neither the plaintext nor the mask would pass the
    # sweep above by carrying nothing at all. The maskers answer ``None`` for a value that
    # was never given, so the two are unwrapped rather than compared through an optional —
    # a ``None`` slipping into an ``in`` test is how this half stops asserting anything.
    masked_phone, masked_username = mask_phone(PROFILE_PHONE), mask_username(PROFILE_USERNAME)
    assert masked_phone is not None and masked_username is not None
    assert masked_phone in listing.text
    assert masked_username in detail.text


async def test_the_avatar_url_is_present_only_when_there_is_an_avatar(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two accounts, one with a photo and one without. ``avatarUrl`` is ``None`` for
    # the second so the panel can skip the request entirely rather than issue fifty that 404.
    with_photo = await seed_user(container)
    await seed_profile(container, with_photo)
    without = await seed_user(container, telegram_user_id=OTHER_USER_ID)
    await seed_profile(container, without, avatar_mime=None, avatar_stored_at=None)
    await signed_in(container, client)

    # Act
    rows = {row["telegramUserId"]: row for row in (await client.get(USERS_PATH)).json()["items"]}

    # Assert — formatted by the ROUTER from its own path constant, so the SPA never builds a
    # path and a prefix change cannot be missed in TypeScript.
    assert rows[TELEGRAM_USER_ID]["avatarUrl"] == AVATAR_URL
    assert rows[TELEGRAM_USER_ID]["avatarUrl"] == USER_AVATAR_PATH.format(
        telegram_user_id=TELEGRAM_USER_ID
    )
    assert rows[OTHER_USER_ID]["hasAvatar"] is False
    assert rows[OTHER_USER_ID]["avatarUrl"] is None


def executable_string_literals(module: ModuleType) -> tuple[str, ...]:
    """Every string a module EVALUATES, with its prose left out.

    Docstrings and ``#:`` comments are excluded deliberately: the rule being enforced is
    that no second module builds this path, not that no second module may describe it — and
    the descriptions are how a reader learns why the rule exists. Comments never reach the
    AST at all; a docstring is a bare ``Expr`` whose value is a string constant, which is the
    one shape excluded here. A ``getsource`` substring test cannot make that distinction and
    would force the schema module to stop explaining itself in order to stay green.
    """
    tree = ast.parse(inspect.getsource(module))
    prose = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return tuple(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose
    )


def test_the_avatar_literal_has_exactly_one_home() -> None:
    # Arrange — C1-6. The path is declared once, in ``routers/users.py`` beside ``USER_PATH``,
    # and the schema module is handed the formatted URL. A second spelling in the schema
    # would drift from the route the day either moves, and every ``avatarUrl`` on the wire
    # would be a 404 nobody could attribute — the SPA would just draw monograms. It is also
    # not merely a style rule: ``USER_PATH`` is built from ``API_PREFIX``, which lives in
    # ``bayram.admin.deps`` and drags the container, the session factory and the permission
    # machinery behind it, so a schema module importing it is an import cycle waiting for the
    # next route.

    # Act
    literals = executable_string_literals(user_schemas)

    # Assert — the helper found something, so a parse that returned nothing cannot pass this
    # by asserting over an empty tuple.
    assert literals
    assert [text for text in literals if "avatar" in text] == []
    assert USER_AVATAR_PATH.endswith("/avatar")
    assert USER_AVATAR_PATH.startswith(USER_PATH)
