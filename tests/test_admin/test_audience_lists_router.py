"""``GET /api/metrics/dashboard/audience-lists`` — the one identified route on the dashboard.

Every assertion here guards one half of the trade the owner made. They decided that an
ACCOUNT HOLDER's Telegram identity may be shown to an operator directly, with an audit entry
INSTEAD OF the reveal gate, the step-up and the budget unit. So:

* the identity really is unmasked — a test that only checked the status code would pass
  against a payload that quietly went back to ``77••••55``, which is the failure mode of a
  decision recorded in prose alone;
* **every** call writes exactly one ``audience.list`` row naming the actor, the columns
  disclosed and how many people were on the screen, because that row is the whole control and
  a read that skipped it would be an unrecorded disclosure;
* the route stands on RECORDS_READ and not DASHBOARD_READ, so it cannot be reached with the
  cell the six aggregate sections beside it use;
* ``?limit=`` is bounded at the boundary, because on an identified surface the ceiling is
  what stops a card from being a bulk export;
* the RECIPIENT's name is nowhere in the payload. That is the half of the decision that was
  NOT taken, and it is the one a future field addition is most likely to erode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Final
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.admin import audit_sink
from hbd.admin.container import AdminContainer
from hbd.admin.errors import AdminErrorCode
from hbd.admin.routers.dashboard import AUDIENCE_LISTS_PATH, AUDIENCE_PATH
from hbd.admin.security import permissions
from hbd.admin.security.permissions import RBAC_MATRIX, Permission
from hbd.contracts import Language, OrderState
from hbd.db.admin.audit import verify_chain
from hbd.db.enums import AdminRole, AuditAction, PlanKind
from hbd.db.models.admin_audit import AdminAuditRow, AuditOutcome
from hbd.db.models.order import OrderRow
from hbd.db.models.plan_purchase import PlanPurchaseRow
from hbd.db.models.user import UserRow
from hbd.db.models.user_profile import UserProfileRow
from tests.test_admin.test_dashboard_router import signed_in

DAY_ONE: Final[datetime] = datetime(2026, 3, 20, 9, 0, tzinfo=UTC)
FAR_FUTURE: Final[datetime] = datetime(2027, 1, 1, tzinfo=UTC)

#: The role the guard tests strip the cell from. Named once: the matrix is narrowed and the
#: session is created for the SAME role, and a mismatch between the two would make the
#: refusal come from the wrong half of the check.
VIEWER: Final[AdminRole] = AdminRole.VIEWER

TELEGRAM_ID: Final[int] = 77_000_555
USERNAME: Final[str] = "gulnora_music"
FIRST_NAME: Final[str] = "Gulnora"


async def seed_account(
    session: AsyncSession,
    *,
    telegram_user_id: int = TELEGRAM_ID,
    telegram_username: str | None = USERNAME,
    first_name: str | None = FIRST_NAME,
    deliveries: int = 1,
) -> UserRow:
    """One account with a profile and ``deliveries`` delivered orders."""
    user = UserRow(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        ui_language=Language.UZ_LATN,
        is_blocked=False,
        last_seen_at=DAY_ONE,
        created_at=DAY_ONE,
        updated_at=DAY_ONE,
    )
    session.add(user)
    await session.flush()
    session.add(
        UserProfileRow(
            user_id=user.id,
            telegram_user_id=telegram_user_id,
            phone_e164=None,
            telegram_username=telegram_username,
            first_name=first_name,
            last_name=None,
            avatar_mime=None,
            avatar_stored_at=None,
            phone_shared_at=None,
            onboarded_at=DAY_ONE,
            created_at=DAY_ONE,
            updated_at=DAY_ONE,
        )
    )
    for index in range(deliveries):
        session.add(
            OrderRow(
                id=uuid4(),
                user_id=user.id,
                telegram_user_id=telegram_user_id,
                state=OrderState.DELIVERED,
                correlation_id=f"corr-{telegram_user_id}-{index}",
                is_paid=True,
                delivered_at=DAY_ONE + timedelta(minutes=index + 1),
                created_at=DAY_ONE,
                updated_at=DAY_ONE,
            )
        )
    await session.flush()
    return user


async def seed_plan(
    session: AsyncSession, *, telegram_user_id: int | None = TELEGRAM_ID, key: str = "plan-key-1"
) -> None:
    session.add(
        PlanPurchaseRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            plan=PlanKind.STARTER,
            songs_included=12,
            songs_used=3,
            amount_minor=5_000_000,
            currency="UZS",
            provider="stub",
            reference="stub-ref-1",
            idempotency_key=key,
            plan_ends_at=FAR_FUTURE,
            created_at=DAY_ONE,
            updated_at=DAY_ONE,
        )
    )
    await session.flush()


async def audit_rows(container: AdminContainer) -> list[AdminAuditRow]:
    async with container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.action == AuditAction.AUDIENCE_LIST_READ)
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


# ---------------------------------------------------------------------------
# the guard
# ---------------------------------------------------------------------------
async def test_an_unauthenticated_caller_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Act
    response = await client.get(AUDIENCE_LISTS_PATH)

    # Assert
    assert response.status_code == 401


async def test_no_audit_row_is_written_for_a_call_that_was_never_served(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange / Act — the refusal happens in the router guard, before the handler.
    assert (await client.get(AUDIENCE_LISTS_PATH)).status_code == 401

    # Assert — an ``audience.list`` row means identity was disclosed. Nothing was.
    assert await audit_rows(container) == []


@pytest.mark.parametrize("role", list(AdminRole))
async def test_every_role_is_served_because_records_read_is_the_cell_this_route_borrows(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — §12.2 gives RECORDS_READ as ``M`` to all four roles, so this UNMASKED route
    # is reachable by VIEWER as well as OWNER: a wider audience than the cell it borrows was
    # written to describe. That is the one thing in this change the owner has to confirm, and
    # it is asserted rather than left implicit so the day it stops being acceptable there is
    # a test to change and not a discovery to make in production.
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(AUDIENCE_LISTS_PATH)

    # Assert — served, unmasked, and the row that records it names the role that looked.
    assert response.status_code == 200
    assert response.json()["topGenerators"]["items"] == []
    assert set(RBAC_MATRIX[Permission.RECORDS_READ]) == set(AdminRole)
    rows = await audit_rows(container)
    assert [row.actor_role for row in rows] == [role]


async def test_a_role_without_records_read_is_refused_and_the_dashboard_cell_is_no_substitute(
    container: AdminContainer,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — RECORDS_READ is ``M`` for every shipped role, so the refusal cannot be
    # provoked by choosing one: the matrix itself is narrowed for the length of this test.
    # That is the point being pinned — this route reads the RECORDS_READ cell and no other,
    # so an operator holding only the aggregate DASHBOARD_READ cell that the six sections
    # beside it stand on cannot reach a single Telegram id through it.
    narrowed = dict(permissions.RBAC_MATRIX)
    narrowed[Permission.RECORDS_READ] = MappingProxyType(
        {
            role: cell
            for role, cell in narrowed[Permission.RECORDS_READ].items()
            if role is not VIEWER
        }
    )
    monkeypatch.setattr(permissions, "RBAC_MATRIX", MappingProxyType(narrowed))
    async with container.session_factory.begin() as session:
        await seed_account(session)
        await seed_plan(session)
    await signed_in(container, client, role=VIEWER)

    # Act
    refused = await client.get(AUDIENCE_LISTS_PATH)
    aggregate = await client.get(AUDIENCE_PATH)

    # Assert — 403 by role, the aggregate section still answers on its own cell, and the
    # names are in neither body.
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value
    assert aggregate.status_code == 200
    assert USERNAME not in refused.text + aggregate.text
    assert str(TELEGRAM_ID) not in refused.text + aggregate.text


async def test_a_refusal_is_recorded_as_a_refusal_and_never_as_a_disclosure(
    container: AdminContainer,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — the same narrowing. §12.6's rule is that a refusal is the audit row that
    # matters most; the rule this test adds is that it must not be written as the OTHER row.
    # An ``audience.list`` entry states that a named list reached an operator's screen, and a
    # reader counting disclosures must never find one for a request that was turned away.
    narrowed = dict(permissions.RBAC_MATRIX)
    narrowed[Permission.RECORDS_READ] = MappingProxyType(
        {
            role: cell
            for role, cell in narrowed[Permission.RECORDS_READ].items()
            if role is not VIEWER
        }
    )
    monkeypatch.setattr(permissions, "RBAC_MATRIX", MappingProxyType(narrowed))
    async with container.session_factory.begin() as session:
        await seed_account(session)
    await signed_in(container, client, role=VIEWER)

    # Act
    assert (await client.get(AUDIENCE_LISTS_PATH)).status_code == 403

    # Assert
    assert await audit_rows(container) == []
    async with container.session_factory.begin() as db:
        denials = (
            (
                await db.execute(
                    sa.select(AdminAuditRow).where(
                        AdminAuditRow.action == AuditAction.PERMISSION_DENIED
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [row.outcome for row in denials] == [AuditOutcome.DENIED]


# ---------------------------------------------------------------------------
# the payload — unmasked, by decision
# ---------------------------------------------------------------------------
async def test_the_account_holder_is_named_in_full_rather_than_masked(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    async with container.session_factory.begin() as session:
        await seed_account(session)
        await seed_plan(session)
    await signed_in(container, client)

    # Act
    response = await client.get(AUDIENCE_LISTS_PATH)

    # Assert — the whole point of the route. A masked variant would pass a status check.
    assert response.status_code == 200
    body = response.json()
    generator = body["topGenerators"]["items"][0]
    assert generator["telegramUserId"] == TELEGRAM_ID
    assert generator["telegramUsername"] == USERNAME
    assert generator["firstName"] == FIRST_NAME
    assert generator["deliveredSongs"] == 1
    subscriber = body["recentSubscribers"]["items"][0]
    assert subscriber["telegramUserId"] == TELEGRAM_ID
    assert subscriber["firstName"] == FIRST_NAME
    assert "•" not in response.text


async def test_the_recipients_name_is_not_on_this_payload_at_all(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the decision covers the account holder and explicitly not the song's subject.
    async with container.session_factory.begin() as session:
        await seed_account(session)
        await seed_plan(session)
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_LISTS_PATH)).text

    # Assert — a field-name check, because the value would depend on a brief this test does
    # not seed: what must never appear is a PLACE to put one.
    assert "recipientName" not in body
    assert "recipient" not in body


async def test_the_window_narrows_the_generators_and_not_the_subscribers(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one delivery and one plan sale, both on DAY_ONE.
    async with container.session_factory.begin() as session:
        await seed_account(session)
        await seed_plan(session)
    await signed_in(container, client)
    later = {"from": (DAY_ONE + timedelta(days=30)).isoformat()}

    # Act — a window that starts a month after everything that happened.
    body = (await client.get(AUDIENCE_LISTS_PATH, params=later)).json()

    # Assert — the ranked list is empty and the recency list is NOT: it takes no window, and
    # the response carries no field that would suggest otherwise.
    assert body["topGenerators"]["items"] == []
    assert body["topGenerators"]["window"]["from"] is not None
    assert len(body["recentSubscribers"]["items"]) == 1
    assert "window" not in body["recentSubscribers"]


async def test_the_two_order_counts_are_two_windows_on_two_columns_and_not_a_conversion_rate(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ONE order, placed the day before the window opens and delivered inside it.
    # Both counts are taken over the same window but on different columns —
    # ``delivered_at`` for the ranking, ``created_at`` for the volume beside it — so this
    # single order is in one and not the other.
    async with container.session_factory.begin() as session:
        user = await seed_account(session, deliveries=0)
        session.add(
            OrderRow(
                id=uuid4(),
                user_id=user.id,
                telegram_user_id=TELEGRAM_ID,
                state=OrderState.DELIVERED,
                correlation_id="corr-straddles-the-boundary",
                is_paid=True,
                delivered_at=DAY_ONE + timedelta(days=1),
                created_at=DAY_ONE - timedelta(days=1),
                updated_at=DAY_ONE,
            )
        )
    await signed_in(container, client)
    window = {"from": DAY_ONE.isoformat(), "to": (DAY_ONE + timedelta(days=2)).isoformat()}

    # Act
    generator = (await client.get(AUDIENCE_LISTS_PATH, params=window)).json()["topGenerators"][
        "items"
    ][0]

    # Assert — ``ordersCreated`` is ``0`` beside a delivery, which is the shape that proves
    # the pair is not a ratio: no consumer may divide these two. Both counts are windowed —
    # ``ordersCreated`` on ``created_at``, ``deliveredSongs`` on ``delivered_at`` — because a
    # lifetime number under a caption naming a week is read as a number about that week; the
    # query, the view and the wire model all say so. This assertion is what will fail if that
    # decision is reversed, which may only be done by changing the read and this test
    # together, never by a reader forming the quotient.
    assert generator["deliveredSongs"] == 1
    assert generator["ordersCreated"] == 0


async def test_the_subscriber_rows_carry_the_rail_and_the_remainder(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    async with container.session_factory.begin() as session:
        await seed_account(session)
        await seed_plan(session)
    await signed_in(container, client)

    # Act
    subscriber = (await client.get(AUDIENCE_LISTS_PATH)).json()["recentSubscribers"]["items"][0]

    # Assert — a stub sale is never indistinguishable from a settled one, and the remainder
    # is published with the flag that says whether it is breakage or an obligation.
    assert subscriber["provider"] == "stub"
    assert subscriber["isStubRail"] is True
    assert subscriber["currency"] == "UZS"
    assert subscriber["songsRemaining"] == 9
    assert subscriber["isPlanEnded"] is False


# ---------------------------------------------------------------------------
# the audit row — the whole of the control
# ---------------------------------------------------------------------------
async def test_every_served_read_writes_one_row_naming_what_it_disclosed(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two accounts on the list and one plan sale: three identified rows shown.
    async with container.session_factory.begin() as session:
        await seed_account(session)
        await seed_account(session, telegram_user_id=77_000_666, telegram_username=None)
        await seed_plan(session)
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    assert (await client.get(AUDIENCE_LISTS_PATH)).status_code == 200

    # Assert
    rows = await audit_rows(container)
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_username == "owner-account"
    assert row.actor_role is AdminRole.OWNER
    assert row.subject_type == "system"
    assert row.subject_id is None
    assert row.record_count == 3
    assert row.field_names == [
        "users.telegram_user_id",
        "user_profiles.telegram_username",
        "user_profiles.first_name",
    ]


async def test_a_read_that_showed_nobody_is_still_recorded(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an empty deployment. The row is the record that somebody LOOKED.
    await signed_in(container, client)

    # Act
    assert (await client.get(AUDIENCE_LISTS_PATH)).status_code == 200

    # Assert
    rows = await audit_rows(container)
    assert len(rows) == 1
    assert rows[0].record_count == 0


async def test_two_reads_write_two_rows(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — there is no per-window deduplication here, unlike the asset stream: every
    # request is a fresh disclosure of a list that may have changed between them.
    await signed_in(container, client)

    # Act
    assert (await client.get(AUDIENCE_LISTS_PATH)).status_code == 200
    assert (await client.get(AUDIENCE_LISTS_PATH)).status_code == 200

    # Assert
    assert len(await audit_rows(container)) == 2


async def test_a_read_whose_row_cannot_be_written_discloses_nothing(
    container: AdminContainer,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — the entry is appended into the session the handler read from, so a failure to
    # log is a failure to answer. That ordering is the difference between "audited" and
    # "usually audited": if the payload could be served while the row was lost, this route
    # would be an unlogged identity disclosure on exactly the days the log was broken.
    async def refuse_to_log(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the audit chain is unavailable")

    async with container.session_factory.begin() as session:
        await seed_account(session)
        await seed_plan(session)
    await signed_in(container, client)
    monkeypatch.setattr(audit_sink, "record", refuse_to_log)

    # Act
    response = await client.get(AUDIENCE_LISTS_PATH)

    # Assert — no payload, no names, no row.
    assert response.status_code == 500
    assert str(TELEGRAM_ID) not in response.text
    assert USERNAME not in response.text
    assert await audit_rows(container) == []


async def test_the_row_and_the_payload_it_records_describe_one_instant(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the handler reads ``now`` ONCE and threads it through the subscriber
    # projection and the log entry. If the row were stamped separately, a reader could not
    # line an ``isPlanEnded`` up against the entry that recorded showing it, and two rows
    # either side of a plan's end could have been judged by two different clocks.
    async with container.session_factory.begin() as session:
        await seed_account(session)
        await seed_plan(session)
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_LISTS_PATH)).json()

    # Assert
    rows = await audit_rows(container)
    assert rows[0].at == datetime.fromisoformat(body["recentSubscribers"]["asOf"])


async def test_the_disclosure_row_is_inside_the_verified_audit_chain(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the control is only worth the log's integrity. An ``audience.list`` row that
    # sat outside the HMAC chain could be deleted afterwards and nothing would notice, so the
    # entry has to be written by the same appender every other audited action goes through
    # rather than inserted beside it.
    async with container.session_factory.begin() as session:
        await seed_account(session)
    await signed_in(container, client)
    assert (await client.get(AUDIENCE_LISTS_PATH)).status_code == 200

    # Act
    async with container.session_factory.begin() as db:
        result = await verify_chain(
            db,
            key=container.settings.admin_audit_hmac_key.get_secret_value(),
            is_dsn_configured=False,
        )

    # Assert — and the row really is one of the links that was walked.
    assert result.is_ok is True
    rows = await audit_rows(container)
    assert len(rows) == 1
    assert rows[0].chain_hmac
    assert rows[0].seq <= result.checked_rows


# ---------------------------------------------------------------------------
# ?limit=
# ---------------------------------------------------------------------------
async def test_the_limit_cuts_both_lists(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — three accounts, each with one delivery.
    async with container.session_factory.begin() as session:
        for index in range(3):
            await seed_account(session, telegram_user_id=77_000_100 + index)
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_LISTS_PATH, params={"limit": 2})).json()

    # Assert — and the depth of the cut is echoed, so "the top two" and "everybody, and
    # there were two" are told apart on the wire.
    assert len(body["topGenerators"]["items"]) == 2
    assert body["topGenerators"]["limit"] == 2
    assert body["recentSubscribers"]["limit"] == 2


@pytest.mark.parametrize("limit", [0, -1, 101, 100_000])
async def test_a_limit_outside_the_bounds_is_refused_rather_than_clamped(
    container: AdminContainer, client: httpx.AsyncClient, limit: int
) -> None:
    # Arrange — on an identified surface the ceiling is what stops a card from becoming an
    # export, so it is a 422 naming the parameter rather than a silent narrowing.
    await signed_in(container, client)

    # Act
    response = await client.get(AUDIENCE_LISTS_PATH, params={"limit": limit})

    # Assert
    assert response.status_code == 422


@pytest.mark.parametrize("limit", [1, 100])
async def test_the_two_values_at_the_edges_of_the_range_are_served(
    container: AdminContainer, client: httpx.AsyncClient, limit: int
) -> None:
    # Arrange — the other side of the 422 above. A bound that refused its own endpoints would
    # be an off-by-one nobody notices until an operator asks for the maximum, and 100 is the
    # tighter of the two database ceilings rather than a number spelled again here.
    await signed_in(container, client)

    # Act
    response = await client.get(AUDIENCE_LISTS_PATH, params={"limit": limit})

    # Assert — echoed, not silently clamped: the response says how deep the cut was made.
    assert response.status_code == 200
    assert response.json()["topGenerators"]["limit"] == limit
    assert response.json()["recentSubscribers"]["limit"] == limit


async def test_an_erased_customer_is_rendered_as_erased_rather_than_dropped(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``/forget`` nulls ``plan_purchases.telegram_user_id`` and deletes the profile
    # row, so the receipt survives the erasure and the identity does not.
    async with container.session_factory.begin() as session:
        await seed_plan(session, telegram_user_id=None, key="plan-key-erased")
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_LISTS_PATH)).json()

    # Assert — the row STAYS. Dropping it would be worse than a blank name: the receipt is
    # the ledger, and a sale that vanishes from it because somebody exercised a right is
    # money this deployment can no longer account for. The three nulls are a lawful erasure
    # and never masking — there is no masked variant of this payload to confuse them with.
    subscriber = body["recentSubscribers"]["items"][0]
    assert subscriber["telegramUserId"] is None
    assert subscriber["telegramUsername"] is None
    assert subscriber["firstName"] is None
    assert subscriber["amountMinor"] == 5_000_000
    assert subscriber["currency"] == "UZS"
    # The ranking is keyed to a Telegram id, so an erased account cannot appear there at all.
    assert body["topGenerators"]["items"] == []


async def test_an_empty_list_says_whether_anything_was_ever_sold(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — nothing sold anywhere.
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_LISTS_PATH)).json()

    # Assert — "nothing to show" and "the read is broken" are different screens.
    assert body["recentSubscribers"]["items"] == []
    assert body["recentSubscribers"]["isPlanRevenue"] is False
