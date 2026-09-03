"""``GET /api/assets`` over the real ASGI stack — the real container, login and guard.

Two assertions carry this file and the rest is scaffolding around them.

**The lyric sheet does not leak.** ``assets.payload`` is the whole song. Every seeded asset
carries :data:`RECIPIENT_NAME` in ``name_candidate_text``, and the leak tests put
:data:`LYRIC_SHEET_LINE` in a ``payload``; both are then searched for in the raw body of
both routes, at every role, because §12.2 gives RECORDS_READ as **M** to all four. There is
no cell in this namespace that returns customer text in the clear, so a plaintext hit at any
role is a bug rather than a permissions question.

**An overdue asset is on the ``expiringWithinDays`` page.** The window has no lower bound on
purpose (``db/admin/assets.py``): a row past ``expires_at`` that the sweep has not collected
is the most urgent line an operator can be shown, and a filter that quietly started at ``now``
would hide exactly the backlog it exists to surface. That is asserted against a row 400 days
overdue, which no "next 7 days" reading of the parameter would return.

There is no 403-by-role test here and its absence is deliberate: §12.2 gives RECORDS_READ to
VIEWER, SUPPORT, ADMIN and OWNER alike, so no role can be refused this route. The row is
asserted as data instead, so the day somebody narrows it the missing test is a failing
assertion rather than a silent gap. The 403 that *is* reachable — the forced-rotation gate —
is covered.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest

from hbd.admin.container import AdminContainer
from hbd.admin.routers.assets import ASSETS_PATH
from hbd.admin.security.permissions import RBAC_MATRIX, Permission
from hbd.contracts import AssetKind, Language, NameStrategy, OrderState
from hbd.db.admin.assets import MAX_EXPIRING_WITHIN_DAYS
from hbd.db.base import utc_now
from hbd.db.enums import AdminRole
from hbd.db.models.asset import AssetRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from hbd.db.retention import RetentionClass
from tests.test_admin.conftest import PASSWORD, create_account, sign_in

#: Anchored to the wall clock, because ``expiringWithinDays`` is measured against the
#: route's own ``utc_now()`` — a frozen instant here would put a fixture on one side of the
#: horizon by accident rather than on purpose.
NOW: Final[datetime] = utc_now()
FAR_FUTURE: Final[datetime] = NOW + timedelta(days=300)
#: Long past its expiry and still in the table: the unswept backlog, which is the row the
#: retention screen exists to show.
LONG_OVERDUE: Final[datetime] = NOW - timedelta(days=400)

#: The two strings that must never appear in a response body. ``payload`` is the lyric sheet
#: and ``name_candidate_text`` is the recipient's name.
LYRIC_SHEET_LINE: Final[str] = "Gulomjonga tugilgan kuningiz muborak bolsin"
RECIPIENT_NAME: Final[str] = "Gulomjon"

_TELEGRAM_ID: Final[int] = 99_000_222


def asset_path(asset_id: UUID) -> str:
    return f"{ASSETS_PATH}/{asset_id}"


# ---------------------------------------------------------------------------
# Seed helpers — explicit values, no clocks, no policies
# ---------------------------------------------------------------------------
async def seed_order(container: AdminContainer) -> OrderRow:
    """One user and one order for the assets to hang off. Both FKs are mandatory."""
    async with container.session_factory.begin() as db:
        user = UserRow(
            id=uuid4(),
            telegram_user_id=_TELEGRAM_ID,
            ui_language=Language.UZ_LATN,
            is_blocked=False,
            last_seen_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(user)
        await db.flush()
        order = OrderRow(
            id=uuid4(),
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            state=OrderState.DELIVERED,
            correlation_id="corr-assets",
            is_paid=True,
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(order)
        await db.flush()
        return order


async def seed_asset(container: AdminContainer, *, order: OrderRow, **kw: Any) -> AssetRow:
    """One asset row, written through the real model so the columns are the real ones."""
    async with container.session_factory.begin() as db:
        row = AssetRow(
            id=kw.pop("id", uuid4()),
            order_id=order.id,
            kind=kw.pop("kind", AssetKind.SONG),
            variant_index=kw.pop("variant_index", 0),
            path=kw.pop("path", "/var/kits/song.mp3"),
            storage_key=kw.pop("storage_key", None),
            mime=kw.pop("mime", "audio/mpeg"),
            size_bytes=kw.pop("size_bytes", 2_048),
            duration_s=kw.pop("duration_s", 91.5),
            sha256=kw.pop("sha256", "a" * 64),
            loudness_lufs=kw.pop("loudness_lufs", -14.0),
            persona_id=kw.pop("persona_id", "persona-1"),
            tg_file_id=kw.pop("tg_file_id", None),
            name_candidate_text=kw.pop("name_candidate_text", RECIPIENT_NAME),
            name_candidate_strategy=kw.pop("name_candidate_strategy", NameStrategy.STRIPPED),
            name_candidate_rank=kw.pop("name_candidate_rank", 0),
            payload=kw.pop("payload", None),
            retention_class=kw.pop("retention_class", RetentionClass.PAID_AUDIO),
            expires_at=kw.pop("expires_at", FAR_FUTURE),
            created_at=kw.pop("created_at", NOW),
        )
        db.add(row)
        await db.flush()
        return row


async def signed_in(
    container: AdminContainer,
    client: httpx.AsyncClient,
    *,
    role: AdminRole = AdminRole.ADMIN,
    must_change_password: bool = False,
) -> None:
    username = f"{role.value}-account"
    await create_account(
        container, username=username, role=role, must_change_password=must_change_password
    )
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


def assert_no_customer_text(response: httpx.Response) -> None:
    """Substring, over the raw body — a projection that leaked would fail this, not a key
    check that only knows the field names somebody remembered to list."""
    assert LYRIC_SHEET_LINE not in response.text
    assert RECIPIENT_NAME not in response.text


# ---------------------------------------------------------------------------
# Who may read it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
async def test_every_role_in_the_matrix_row_may_list_assets(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — §12.2 gives RECORDS_READ as M to all four roles.
    order = await seed_order(container)
    await seed_asset(container, order=order)
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(ASSETS_PATH)

    # Assert
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_the_matrix_row_grants_records_read_to_every_role() -> None:
    # Arrange / Act — the reason there is no 403-by-role test in this file. If a role is
    # ever dropped from this row, this fails and the missing refusal test becomes visible.

    # Assert
    assert set(RBAC_MATRIX[Permission.RECORDS_READ]) == set(AdminRole)


async def test_an_unauthenticated_caller_gets_401_not_the_asset_list(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.get(ASSETS_PATH)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_an_unauthenticated_caller_gets_401_on_the_detail_route(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.get(asset_path(uuid4()))

    # Assert — 401 before 404: an unauthenticated caller must not learn whether an id exists.
    assert response.status_code == 401


async def test_an_operator_owing_a_password_change_is_refused_with_403(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the one 403 this route can produce, since no role lacks RECORDS_READ.
    order = await seed_order(container)
    await seed_asset(container, order=order)
    await signed_in(container, client, role=AdminRole.ADMIN, must_change_password=True)

    # Act
    response = await client.get(ASSETS_PATH)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "password_change_required"


# ---------------------------------------------------------------------------
# Nothing the customer wrote crosses the wire
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
async def test_the_lyric_sheet_payload_is_absent_from_the_list_at_every_role(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — ``payload`` is the whole song. There is no unmasked cell to hide behind.
    order = await seed_order(container)
    await seed_asset(
        container,
        order=order,
        kind=AssetKind.LYRIC_SHEET,
        mime="text/plain",
        payload={"lyrics": LYRIC_SHEET_LINE, "title": RECIPIENT_NAME},
    )
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(ASSETS_PATH)

    # Assert
    assert response.status_code == 200
    assert_no_customer_text(response)
    assert "payload" not in response.json()["items"][0]


async def test_the_lyric_sheet_payload_is_absent_from_the_detail_response(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order = await seed_order(container)
    asset = await seed_asset(
        container,
        order=order,
        kind=AssetKind.LYRIC_SHEET,
        payload={"lyrics": LYRIC_SHEET_LINE},
    )
    await signed_in(container, client)

    # Act
    response = await client.get(asset_path(asset.id))

    # Assert
    assert response.status_code == 200
    assert_no_customer_text(response)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------
async def test_the_list_carries_the_metadata_an_operator_triages_on(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order = await seed_order(container)
    await seed_asset(
        container,
        order=order,
        kind=AssetKind.GREETING,
        variant_index=2,
        storage_key="kits/greeting-2.mp3",
        tg_file_id="tg-file-id",
        retention_class=RetentionClass.FREE_OUTPUT,
        expires_at=FAR_FUTURE,
    )
    await signed_in(container, client)

    # Act
    response = await client.get(ASSETS_PATH)

    # Assert — the orthography that produced the take is named by strategy and rank; the
    # text itself is a name and does not appear.
    assert_no_customer_text(response)
    item = response.json()["items"][0]
    assert item["orderId"] == str(order.id)
    assert item["kind"] == AssetKind.GREETING.value
    assert item["variantIndex"] == 2
    assert item["mime"] == "audio/mpeg"
    assert item["sizeBytes"] == 2_048
    assert item["durationS"] == pytest.approx(91.5)
    assert item["sha256"] == "a" * 64
    assert item["loudnessLufs"] == pytest.approx(-14.0)
    assert item["personaId"] == "persona-1"
    assert item["isStorageKeyRecorded"] is True
    assert item["hasTelegramFileId"] is True
    assert item["nameCandidateStrategy"] == NameStrategy.STRIPPED.value
    assert item["nameCandidateRank"] == 0
    assert item["retentionClass"] == RetentionClass.FREE_OUTPUT.value


async def test_an_asset_with_no_storage_key_says_so_rather_than_looking_healthy(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``purge._purge_assets`` filters ``if key`` (purge.py:194), so a row with no
    # key is a file that outlives it. That is the fact this flag exists to surface.
    order = await seed_order(container)
    await seed_asset(container, order=order, storage_key=None)
    await signed_in(container, client)

    # Act
    body = (await client.get(ASSETS_PATH)).json()

    # Assert
    assert body["items"][0]["isStorageKeyRecorded"] is False


async def test_the_detail_route_answers_with_the_same_projection_as_the_list(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one mapping of an ``AssetRow`` to the wire, shared with the order detail.
    order = await seed_order(container)
    asset = await seed_asset(container, order=order)
    await signed_in(container, client)

    # Act
    listed = await client.get(ASSETS_PATH)
    detail = await client.get(asset_path(asset.id))

    # Assert
    assert_no_customer_text(detail)
    assert detail.json() == listed.json()["items"][0]


async def test_an_unknown_asset_id_is_a_404_in_the_error_envelope(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(asset_path(uuid4()))

    # Assert
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_an_identifier_that_is_not_a_uuid_is_refused_at_the_boundary(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(f"{ASSETS_PATH}/not-a-uuid")

    # Assert
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
async def test_repeated_kinds_are_or_within_the_field(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order = await seed_order(container)
    await seed_asset(container, order=order, kind=AssetKind.SONG)
    await seed_asset(container, order=order, kind=AssetKind.GREETING)
    await seed_asset(container, order=order, kind=AssetKind.COVER)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(ASSETS_PATH, params={"kind": [AssetKind.SONG, AssetKind.COVER]})
    ).json()

    # Assert
    assert {item["kind"] for item in body["items"]} == {"song", "cover"}


async def test_two_different_filters_are_and_across_fields(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — only one row satisfies both halves.
    order = await seed_order(container)
    await seed_asset(
        container, order=order, kind=AssetKind.SONG, retention_class=RetentionClass.PAID_AUDIO
    )
    await seed_asset(
        container,
        order=order,
        kind=AssetKind.GREETING,
        retention_class=RetentionClass.EPHEMERAL,
    )
    await signed_in(container, client)

    # Act
    body = (
        await client.get(
            ASSETS_PATH,
            params={"kind": AssetKind.SONG.value, "retentionClass": RetentionClass.EPHEMERAL},
        )
    ).json()

    # Assert
    assert body["items"] == []


async def test_an_unknown_kind_is_a_422_rather_than_a_filter_matching_nothing(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(ASSETS_PATH, params={"kind": "karaoke"})

    # Assert
    assert response.status_code == 422


async def test_expiring_within_days_includes_a_row_that_is_already_overdue(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the window has no lower bound on purpose: an unswept overdue asset is the
    # most urgent row on the page, and a "next 7 days" reading would drop it.
    order = await seed_order(container)
    await seed_asset(container, order=order, kind=AssetKind.SONG, expires_at=LONG_OVERDUE)
    await seed_asset(
        container,
        order=order,
        kind=AssetKind.GREETING,
        expires_at=NOW + timedelta(days=2),
    )
    await seed_asset(container, order=order, kind=AssetKind.COVER, expires_at=FAR_FUTURE)
    await signed_in(container, client)

    # Act
    body = (await client.get(ASSETS_PATH, params={"expiringWithinDays": 7})).json()

    # Assert
    assert {item["kind"] for item in body["items"]} == {"song", "greeting"}


@pytest.mark.parametrize("days", [0, -1, MAX_EXPIRING_WITHIN_DAYS + 1])
async def test_an_expiry_horizon_outside_the_bounds_is_refused(
    container: AdminContainer, client: httpx.AsyncClient, days: int
) -> None:
    # Arrange — past a year the filter selects the whole table, which an operator would read
    # as a narrowed page.
    await signed_in(container, client)

    # Act
    response = await client.get(ASSETS_PATH, params={"expiringWithinDays": days})

    # Assert
    assert response.status_code == 422


async def test_the_creation_window_filters_on_created_at(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order = await seed_order(container)
    await seed_asset(
        container, order=order, kind=AssetKind.SONG, created_at=NOW - timedelta(days=10)
    )
    await seed_asset(container, order=order, kind=AssetKind.GREETING, created_at=NOW)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(
            ASSETS_PATH,
            params={
                "from": (NOW - timedelta(days=1)).isoformat(),
                "to": (NOW + timedelta(days=1)).isoformat(),
            },
        )
    ).json()

    # Assert
    assert [item["kind"] for item in body["items"]] == ["greeting"]


async def test_a_naive_instant_is_refused_rather_than_reaching_the_column(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``UtcDateTime.process_bind_param`` raises inside the driver, where nothing
    # is waiting to turn it into an answer.
    await signed_in(container, client)

    # Act
    response = await client.get(
        ASSETS_PATH, params={"from": "2026-03-01T00:00:00", "to": "2026-03-02T00:00:00"}
    )

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_half_a_window_is_refused_rather_than_silently_completed(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an implicit second bound is a value the operator never typed.
    await signed_in(container, client)

    # Act
    response = await client.get(ASSETS_PATH, params={"from": NOW.isoformat()})

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_a_window_that_ends_before_it_starts_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(
        ASSETS_PATH,
        params={"from": NOW.isoformat(), "to": (NOW - timedelta(days=1)).isoformat()},
    )

    # Assert
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------
async def test_a_full_page_carries_a_cursor_that_fetches_the_rest(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order = await seed_order(container)
    for index, kind in enumerate((AssetKind.SONG, AssetKind.GREETING, AssetKind.COVER)):
        await seed_asset(
            container, order=order, kind=kind, created_at=NOW - timedelta(minutes=index)
        )
    await signed_in(container, client)

    # Act
    first = (await client.get(ASSETS_PATH, params={"limit": 2})).json()
    second = (
        await client.get(ASSETS_PATH, params={"limit": 2, "cursor": first["meta"]["nextCursor"]})
    ).json()

    # Assert — newest first, no row seen twice, and the last page ends the loop.
    assert [item["kind"] for item in first["items"]] == ["song", "greeting"]
    assert [item["kind"] for item in second["items"]] == ["cover"]
    assert second["meta"]["nextCursor"] is None


async def test_the_total_is_absent_unless_it_was_asked_for(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``total`` and ``isTotalExact`` travel as a pair or not at all.
    order = await seed_order(container)
    await seed_asset(container, order=order, kind=AssetKind.SONG)
    await seed_asset(container, order=order, kind=AssetKind.GREETING)
    await signed_in(container, client)

    # Act
    without = (await client.get(ASSETS_PATH)).json()
    with_total = (await client.get(ASSETS_PATH, params={"withTotal": True})).json()

    # Assert
    assert without["meta"]["total"] is None
    assert without["meta"]["isTotalExact"] is None
    assert with_total["meta"]["total"] == 2
    assert with_total["meta"]["isTotalExact"] is True


async def test_the_total_counts_the_same_filtered_set_as_the_page(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a count over the unfiltered table would read as "there is more here".
    order = await seed_order(container)
    await seed_asset(container, order=order, kind=AssetKind.SONG)
    await seed_asset(container, order=order, kind=AssetKind.GREETING)
    await seed_asset(container, order=order, kind=AssetKind.COVER)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(ASSETS_PATH, params={"withTotal": True, "kind": AssetKind.SONG.value})
    ).json()

    # Assert
    assert body["meta"]["total"] == 1


@pytest.mark.parametrize("limit", [0, 201])
async def test_a_page_limit_outside_the_bounds_is_refused_at_the_boundary(
    container: AdminContainer, client: httpx.AsyncClient, limit: int
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(ASSETS_PATH, params={"limit": limit})

    # Assert
    assert response.status_code == 422


async def test_a_cursor_this_endpoint_did_not_issue_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(ASSETS_PATH, params={"cursor": "not-a-cursor"})

    # Assert
    assert response.status_code == 422
