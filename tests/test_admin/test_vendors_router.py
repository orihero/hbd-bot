"""``/metrics/vendor-*`` over the real ASGI stack — the real container, login, guard, SQLite.

This is the first surface in the panel that prints money, so the assertions that carry this
file are the ones about the figures it refuses to invent:

* a group in which nobody recorded tokens answers ``totalTokens: null`` — asserted with
  ``is None`` rather than falsy, because ``0`` is the exact wrong answer and the exact one a
  ``COALESCE`` anywhere in the read layer would produce;
* a group holding one estimated and one derived call answers ``costSource: "mixed"``, not
  whichever of the two the database happened to sort first;
* a day nobody called a vendor is ABSENT from the by-day series rather than present at
  ``$0.00``, which would be a claim about spend on a day this deployment may not have had;
* an empty deployment answers ``isInstrumented: false``, and a deployment writing rows with
  no rate configured answers ``isInstrumented: true`` with ``isCostPriced: false`` — three
  empties, three sentences, one of which is "widen the window" and none of which is a zero;
* ``costUsd`` travels with ``costedCalls``, so a total covering one call in three cannot be
  read as covering three.

The privacy assertion is the dashboard's, for the same reason: there is nothing on this
screen to mask, so the stronger claim is that a known plaintext seeded into the recipient
name, the note and the candidate text of an order this spend is attributed to appears in
none of the three bodies at any of the four roles.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.admin.container import AdminContainer
from bayram.admin.deps import RequirePermission, require_permission
from bayram.admin.routers.vendors import (
    VENDOR_ERRORS_PATH,
    VENDOR_USAGE_BY_DAY_PATH,
    VENDOR_USAGE_PATH,
    build_vendors_router,
)
from bayram.admin.security.permissions import Permission
from bayram.contracts import CostSource, UsageTask, Vendor, VendorOperation
from bayram.db.enums import AdminRole
from bayram.db.models.vendor_usage import VendorUsageRow
from tests.test_admin.conftest import PASSWORD, create_account, sign_in
from tests.test_admin.test_dashboard_router import (
    CANDIDATE,
    RECIPIENT,
    seed_brief,
    seed_order,
    seed_user,
)

#: Fixed instants. Every number here is bucketed by UTC day, so a wall clock would race the
#: day boundaries and make one assertion in this file fail once a year at 23:59.
DAY_ONE: Final[datetime] = datetime(2026, 3, 20, 9, 0, tzinfo=UTC)
#: Deliberately not 3-21: the gap day is what proves the series is not zero-filled.
DAY_THREE: Final[datetime] = datetime(2026, 3, 22, 9, 0, tzinfo=UTC)
#: Half-open, so it holds both days above and nothing after them.
WINDOW_END: Final[datetime] = datetime(2026, 3, 23, tzinfo=UTC)

ALL_PATHS: Final[tuple[str, ...]] = (
    VENDOR_USAGE_PATH,
    VENDOR_USAGE_BY_DAY_PATH,
    VENDOR_ERRORS_PATH,
)

ALL_ROLES: Final[tuple[AdminRole, ...]] = (
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


# ---------------------------------------------------------------------------
# Seed helpers — explicit values, no clocks, no policies
# ---------------------------------------------------------------------------
async def seed_call(
    session: AsyncSession,
    *,
    vendor: Vendor = Vendor.ELEVENLABS,
    operation: VendorOperation = VendorOperation.SPEECH_SYNTHESIS,
    created_at: datetime = DAY_ONE,
    **kw: Any,
) -> VendorUsageRow:
    """One ``vendor_usage`` row, with every quantity left unset unless a test asks for it.

    Unset means ``NULL``, which is the whole point of the table: a helper that defaulted
    ``latency_ms`` to ``0`` the way ``seed_attempt`` has to would make every assertion in
    this file about "nobody measured this" untestable.
    """
    row = VendorUsageRow(
        id=uuid4(),
        vendor=vendor,
        operation=operation,
        provider=kw.pop("provider", "elevenlabs_tts"),
        model_id=kw.pop("model_id", "eleven_v3"),
        is_fallback=kw.pop("is_fallback", False),
        is_fake=kw.pop("is_fake", False),
        task=kw.pop("task", UsageTask.GREETING_SPEECH),
        order_id=kw.pop("order_id", None),
        correlation_id=kw.pop("correlation_id", "corr-vendors"),
        is_success=kw.pop("is_success", True),
        http_status=kw.pop("http_status", 200),
        error_code=kw.pop("error_code", None),
        latency_ms=kw.pop("latency_ms", None),
        prompt_tokens=kw.pop("prompt_tokens", None),
        completion_tokens=kw.pop("completion_tokens", None),
        total_tokens=kw.pop("total_tokens", None),
        billed_characters=kw.pop("billed_characters", None),
        audio_ms=kw.pop("audio_ms", None),
        request_bytes=kw.pop("request_bytes", None),
        response_bytes=kw.pop("response_bytes", None),
        cost_usd=kw.pop("cost_usd", None),
        cost_source=kw.pop("cost_source", None),
        created_at=created_at,
    )
    assert not kw, f"unused seed arguments: {sorted(kw)}"
    session.add(row)
    await session.flush()
    return row


def window_params(**extra: str | list[str]) -> dict[str, Any]:
    """The window every windowed assertion here sends, plus whatever the test adds."""
    return {"from": DAY_ONE.isoformat(), "to": WINDOW_END.isoformat(), **extra}


# ---------------------------------------------------------------------------
# Who may read it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_an_unauthenticated_caller_gets_401_not_a_spend_figure(
    client: httpx.AsyncClient, path: str
) -> None:
    # Act
    response = await client.get(path)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_every_role_in_the_matrix_row_may_read_every_vendor_route(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole, path: str
) -> None:
    # Arrange — §12.2 gives DASHBOARD_READ to all four roles, and §12.3 classes costs and
    # latencies as always-visible non-personal data, which is why there is no new member.
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(path)

    # Assert
    assert response.status_code == 200


def test_the_guard_is_declared_once_on_the_router_and_not_on_a_handler() -> None:
    # Arrange — the 403 case is unreachable from a signed-in session because every role
    # holds DASHBOARD_READ. What can regress is the guard going missing, or a handler
    # growing a second one, so both are asserted structurally.
    router = build_vendors_router()

    # Act
    guards = [
        dependency.dependency
        for dependency in router.dependencies
        if isinstance(dependency.dependency, RequirePermission)
    ]
    handler_guards = [
        dependency
        for route in router.routes
        if isinstance(route, APIRoute)
        for dependency in route.dependant.dependencies
        if isinstance(dependency.call, RequirePermission)
    ]

    # Assert
    assert guards == [require_permission(Permission.DASHBOARD_READ)]
    # The router-level guard is inherited by each route, so a HANDLER-declared one would be
    # a second copy — which is how a route later loses the only guard it had.
    assert len(handler_guards) == len(router.routes)


# ---------------------------------------------------------------------------
# Absent measurements are null, and never zero
# ---------------------------------------------------------------------------
async def test_a_group_nobody_recorded_tokens_for_reports_null_rather_than_zero(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a speech synthesis has characters and never has tokens. A zero for tokens
    # would say the vendor billed us for a completion that used none.
    async with container.session_factory.begin() as session:
        await seed_call(session, billed_characters=412)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert — ``is None``, deliberately, because ``0`` is falsy and is the wrong answer.
    (row,) = body["rows"]
    assert row["billedCharacters"] == 412
    assert row["totalTokens"] is None
    assert row["promptTokens"] is None
    assert row["audioMs"] is None
    assert row["avgLatencyMs"] is None
    assert body["totals"]["totalTokens"] is None


async def test_an_unpriced_group_carries_no_cost_and_no_source(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the out-of-the-box deployment: rows written, no rate configured.
    async with container.session_factory.begin() as session:
        await seed_call(session, billed_characters=100)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    (row,) = body["rows"]
    assert row["costUsd"] is None
    assert row["costSource"] is None
    # A count, not a quantity: "no call in this group was priced" IS a measurement.
    assert row["costedCalls"] == 0
    assert body["totals"]["costUsd"] is None
    assert body["totals"]["costedCalls"] == 0


async def test_the_cost_total_covers_only_priced_calls_and_says_how_many(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one priced call and two unpriced ones in the same group. Without
    # ``costedCalls`` on the wire, "$0.25 over three calls" is a budget nobody can check.
    async with container.session_factory.begin() as session:
        await seed_call(session, cost_usd=0.25, cost_source=CostSource.ESTIMATED)
        await seed_call(session)
        await seed_call(session)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    (row,) = body["rows"]
    assert row["calls"] == 3
    assert row["costUsd"] == pytest.approx(0.25)
    assert row["costedCalls"] == 1
    assert body["totals"]["costUsd"] == pytest.approx(0.25)
    assert body["totals"]["costedCalls"] == 1


async def test_a_group_holding_two_cost_sources_reports_mixed(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one call priced from the vendor's own arithmetic and one from ours, in the
    # same (vendor, operation, model) group.
    async with container.session_factory.begin() as session:
        await seed_call(session, cost_usd=0.10, cost_source=CostSource.ESTIMATED)
        await seed_call(session, cost_usd=0.20, cost_source=CostSource.DERIVED)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert — naming either source would tell the panel every call in the group was
    # arrived at that way, and the panel tints the three differently on purpose.
    (row,) = body["rows"]
    assert row["costSource"] == "mixed"
    assert row["costUsd"] == pytest.approx(0.30)
    assert row["costedCalls"] == 2


async def test_a_group_whose_priced_calls_agree_names_its_one_source(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the same shape as above with one provenance, so "mixed" cannot be a
    # constant that happens to pass the test above.
    async with container.session_factory.begin() as session:
        await seed_call(session, cost_usd=0.10, cost_source=CostSource.ESTIMATED)
        await seed_call(session, cost_usd=0.20, cost_source=CostSource.ESTIMATED)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    (row,) = body["rows"]
    assert row["costSource"] == "estimated"


async def test_the_rollup_groups_by_vendor_operation_and_model_busiest_first(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two models of one operation, and one call of another. The group key is the
    # invoice's shape: a rate card is quoted per model, so two models cannot share a row.
    async with container.session_factory.begin() as session:
        await seed_call(session, model_id="eleven_v3")
        await seed_call(session, model_id="eleven_v3")
        await seed_call(session, model_id="eleven_v2")
        await seed_call(
            session,
            vendor=Vendor.OPENROUTER,
            operation=VendorOperation.CHAT_COMPLETION,
            provider="openai-compat",
            model_id="google/gemma-4-31b-it:free",
            prompt_tokens=900,
            completion_tokens=100,
            total_tokens=1_000,
        )
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert — calls DESC, then vendor/operation/model ASC. Never ordered by cost, whose
    # NULLs sort differently on SQLite and Postgres.
    assert [(row["modelId"], row["calls"]) for row in body["rows"]] == [
        ("eleven_v3", 2),
        ("eleven_v2", 1),
        ("google/gemma-4-31b-it:free", 1),
    ]
    assert body["rows"][2]["totalTokens"] == 1_000
    # And the totals are the window's, not one group's.
    assert body["totals"]["calls"] == 4


async def test_successes_and_failures_are_counted_and_the_rate_is_theirs(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    async with container.session_factory.begin() as session:
        await seed_call(session)
        await seed_call(session, is_success=False, http_status=503, error_code="UPSTREAM_TIMEOUT")
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    (row,) = body["rows"]
    assert (row["successes"], row["failures"]) == (1, 1)
    assert row["successRate"] == pytest.approx(0.5)
    assert body["totals"]["successRate"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Three empties, three answers
# ---------------------------------------------------------------------------
async def test_an_empty_database_is_not_instrumented_and_holds_no_rows_in_the_window(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — nothing seeded at all.
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert — "no worker in this deployment has written a row", which is a different
    # screen from "nothing in the range you chose" and has a different remedy.
    assert body["isInstrumented"] is False
    assert body["isCostPriced"] is False
    assert body["hasRowsInWindow"] is False
    assert body["rows"] == []
    assert body["totals"]["calls"] == 0
    assert body["totals"]["successRate"] is None
    assert body["totals"]["costUsd"] is None


async def test_rows_outside_the_window_still_read_as_instrumented(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the discrimination the two window-blind flags exist for: a deployment that
    # records vendor calls but made none in the range being looked at.
    async with container.session_factory.begin() as session:
        await seed_call(session, created_at=datetime(2025, 1, 1, tzinfo=UTC))
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    assert body["isInstrumented"] is True
    assert body["hasRowsInWindow"] is False
    assert body["rows"] == []


async def test_recorded_rows_with_no_cost_are_instrumented_but_not_priced(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the shipping default: ``BAYRAM_ELEVENLABS_USD_PER_CHARACTER`` is 0.0 and no
    # LLM rate is configured, so a correctly instrumented deployment writes exactly this.
    async with container.session_factory.begin() as session:
        await seed_call(session, billed_characters=250)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert — the panel says "not priced" from these two, and prints no $0.00 anywhere.
    assert body["isInstrumented"] is True
    assert body["isCostPriced"] is False
    assert body["hasRowsInWindow"] is True


async def test_the_cost_flag_flips_on_the_first_row_that_carries_one(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — measured, never declared: nobody has to flip a constant.
    async with container.session_factory.begin() as session:
        await seed_call(session, cost_usd=0.01, cost_source=CostSource.VENDOR_REPORTED)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    assert body["isCostPriced"] is True


async def test_the_window_is_echoed_so_an_empty_state_can_name_its_range(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params={"to": WINDOW_END.isoformat()})).json()

    # Assert — ``from`` is null for a one-sided range, which is the honest rendering of
    # "since the first row there is" rather than an epoch nobody typed.
    assert body["window"]["from"] is None
    assert datetime.fromisoformat(body["window"]["to"]) == WINDOW_END


async def test_no_window_at_all_echoes_null(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH)).json()

    # Assert
    assert body["window"] is None


# ---------------------------------------------------------------------------
# The day series
# ---------------------------------------------------------------------------
async def test_a_day_with_no_calls_is_absent_from_the_series(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two days with traffic and one without between them. A zero bar on the gap
    # day would be a claim about money on a day nobody called anybody.
    async with container.session_factory.begin() as session:
        await seed_call(session, created_at=DAY_ONE)
        await seed_call(session, created_at=DAY_THREE)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_BY_DAY_PATH, params=window_params())).json()

    # Assert
    assert [entry["day"] for entry in body] == ["2026-03-20", "2026-03-22"]
    assert all(entry["vendor"] == "elevenlabs" for entry in body)


async def test_the_day_series_splits_by_vendor_and_carries_its_priced_count(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one priced ElevenLabs call and one unpriced OpenRouter call on one day.
    async with container.session_factory.begin() as session:
        await seed_call(session, cost_usd=0.40, cost_source=CostSource.ESTIMATED)
        await seed_call(
            session,
            vendor=Vendor.OPENROUTER,
            operation=VendorOperation.CHAT_COMPLETION,
            provider="openai-compat",
            model_id="google/gemma-4-31b-it:free",
        )
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_BY_DAY_PATH, params=window_params())).json()

    # Assert — day ASC then vendor ASC, and the unpriced vendor's cost is null, not zero.
    assert body == [
        {
            "day": "2026-03-20",
            "vendor": "elevenlabs",
            "calls": 1,
            "costUsd": pytest.approx(0.40),
            "costedCalls": 1,
        },
        {
            "day": "2026-03-20",
            "vendor": "openrouter",
            "calls": 1,
            "costUsd": None,
            "costedCalls": 0,
        },
    ]


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------
async def test_a_vendors_error_share_is_of_its_own_failures(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two failures for one vendor and one for another. A share computed against
    # every vendor's failures would answer a question nobody asked.
    async with container.session_factory.begin() as session:
        await seed_call(session, is_success=False, error_code="UPSTREAM_TIMEOUT")
        await seed_call(session, is_success=False, error_code="UPSTREAM_TIMEOUT")
        await seed_call(session, is_success=False, error_code="RATE_LIMITED")
        await seed_call(
            session,
            vendor=Vendor.OPENROUTER,
            operation=VendorOperation.CHAT_COMPLETION,
            provider="openai-compat",
            is_success=False,
            error_code="PROVIDER_ERROR",
        )
        # A success, which must not appear in this breakdown at all.
        await seed_call(session)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_ERRORS_PATH, params=window_params())).json()

    # Assert — count DESC, then vendor and code ASC.
    assert body == [
        {
            "vendor": "elevenlabs",
            "errorCode": "UPSTREAM_TIMEOUT",
            "count": 2,
            "share": pytest.approx(2 / 3),
        },
        {
            "vendor": "elevenlabs",
            "errorCode": "RATE_LIMITED",
            "count": 1,
            "share": pytest.approx(1 / 3),
        },
        {
            "vendor": "openrouter",
            "errorCode": "PROVIDER_ERROR",
            "count": 1,
            "share": pytest.approx(1.0),
        },
    ]


async def test_a_failure_that_recorded_no_code_is_grouped_under_null(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a transport failure that never reached a taxonomy code.
    async with container.session_factory.begin() as session:
        await seed_call(session, is_success=False, http_status=None, error_code=None)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_ERRORS_PATH, params=window_params())).json()

    # Assert
    assert body[0]["errorCode"] is None
    assert body[0]["count"] == 1


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
async def test_repeating_the_vendor_parameter_narrows_to_those_vendors(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — three vendors, two asked for. OR within the field (§6.1).
    async with container.session_factory.begin() as session:
        await seed_call(session, vendor=Vendor.ELEVENLABS)
        await seed_call(
            session,
            vendor=Vendor.OPENROUTER,
            operation=VendorOperation.CHAT_COMPLETION,
            provider="openai-compat",
        )
        await seed_call(
            session,
            vendor=Vendor.GEMINI,
            operation=VendorOperation.CHAT_COMPLETION,
            provider="gemini",
        )
    await signed_in(container, client)

    # Act
    response = await client.get(
        VENDOR_USAGE_PATH, params=window_params(vendor=["elevenlabs", "openrouter"])
    )

    # Assert
    body = response.json()
    assert sorted(row["vendor"] for row in body["rows"]) == ["elevenlabs", "openrouter"]
    assert body["totals"]["calls"] == 2


async def test_no_vendor_parameter_means_every_vendor_and_never_none(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the asymmetry ``apply_in`` exists for: an absent filter must not be ``IN ()``.
    async with container.session_factory.begin() as session:
        await seed_call(session, vendor=Vendor.ELEVENLABS)
        await seed_call(
            session,
            vendor=Vendor.GEMINI,
            operation=VendorOperation.CHAT_COMPLETION,
            provider="gemini",
        )
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    assert body["totals"]["calls"] == 2


@pytest.mark.parametrize("path", ALL_PATHS)
async def test_an_unknown_vendor_is_a_422_and_not_a_filter_matching_nothing(
    container: AdminContainer, client: httpx.AsyncClient, path: str
) -> None:
    # Arrange — typed as the enum, so a typo is refused rather than silently emptying the
    # screen and leaving an operator to conclude the vendor had no traffic.
    await signed_in(container, client)

    # Act
    response = await client.get(path, params={"vendor": "elevenlabz"})

    # Assert
    assert response.status_code == 422


@pytest.mark.parametrize("path", ALL_PATHS)
async def test_a_naive_from_is_refused_by_name(
    container: AdminContainer, client: httpx.AsyncClient, path: str
) -> None:
    # Arrange — §6.1. Without this the value would raise inside the driver's bind processor,
    # where no handler is waiting and the operator gets a 500.
    await signed_in(container, client)

    # Act
    response = await client.get(path, params={"from": "2026-03-20T09:00:00"})

    # Assert
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_INPUT"
    assert "UTC offset" in error["message"]


@pytest.mark.parametrize("path", ALL_PATHS)
async def test_an_inverted_range_is_refused(
    container: AdminContainer, client: httpx.AsyncClient, path: str
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(
        path, params={"from": WINDOW_END.isoformat(), "to": DAY_ONE.isoformat()}
    )

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Nothing personal reaches this screen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ALL_ROLES)
async def test_no_known_plaintext_appears_in_any_vendor_body_at_any_role(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — the spend is attributed to a real order whose brief carries the recipient's
    # name, a note about them and a candidate orthography. ``vendor_usage`` holds that
    # order's id and nothing else about it, and none of the three responses even carries the
    # id: they are counts grouped by closed enums.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_order(session, user=user, created_at=DAY_ONE)
        await seed_brief(session, order=order)
        order_id: UUID = order.id
        await seed_call(session, order_id=order_id, cost_usd=0.05, cost_source=CostSource.ESTIMATED)
        await seed_call(session, order_id=order_id, is_success=False, error_code="UPSTREAM_TIMEOUT")
    await signed_in(container, client, role=role)

    # Act
    bodies = [(await client.get(path, params=window_params())).text for path in ALL_PATHS]

    # Assert — ASCII plaintext, so a substring check against the raw body is meaningful
    # (a non-ASCII name would arrive as ``\\uXXXX`` escapes and pass without proving anything).
    for body in bodies:
        assert RECIPIENT not in body
        assert CANDIDATE not in body
        assert str(order_id) not in body
    # And the spend really was recorded, so the sweep above is not passing over empty bodies.
    usage = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()
    assert usage["totals"]["calls"] == 2


async def test_a_delivered_window_holds_only_closed_vocabularies(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — stated as a shape assertion so a field added to the rollup later has to be
    # justified here rather than appearing on a screen nobody re-read.
    async with container.session_factory.begin() as session:
        await seed_call(session, latency_ms=1_200, billed_characters=90)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    assert set(body) == {
        "window",
        "isInstrumented",
        "isCostPriced",
        "hasRowsInWindow",
        "totals",
        "rows",
    }
    assert set(body["rows"][0]) == {
        "vendor",
        "operation",
        "modelId",
        "calls",
        "successes",
        "failures",
        "successRate",
        "promptTokens",
        "completionTokens",
        "totalTokens",
        "billedCharacters",
        "audioMs",
        "costUsd",
        "costSource",
        "costedCalls",
        "avgLatencyMs",
        "maxLatencyMs",
    }
    # The one derived latency figure: an average the database took, rounded to whole
    # milliseconds, and ``maxLatencyMs`` beside it rather than a percentile nobody can
    # compute portably in one round trip.
    assert body["rows"][0]["avgLatencyMs"] == 1_200
    assert body["rows"][0]["maxLatencyMs"] == 1_200


async def test_an_average_latency_is_rounded_and_never_invented(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one call that recorded a latency and one that did not. AVG ignores the
    # NULL, which is the correct denominator: the unmeasured call is not a zero-latency one.
    async with container.session_factory.begin() as session:
        await seed_call(session, latency_ms=1_001)
        await seed_call(session, latency_ms=1_002)
        await seed_call(session, latency_ms=None)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    (row,) = body["rows"]
    assert row["calls"] == 3
    assert row["avgLatencyMs"] == 1_002  # 1001.5 rounded, over the two that were measured
    assert row["maxLatencyMs"] == 1_002


async def test_a_call_recorded_before_any_order_existed_is_still_counted(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the wizard's lyric preview: a real cost with no order to charge it to. A
    # foreign key would have rejected this row and the spend would be invisible.
    async with container.session_factory.begin() as session:
        await seed_call(
            session,
            vendor=Vendor.OPENROUTER,
            operation=VendorOperation.CHAT_COMPLETION,
            provider="openai-compat",
            task=UsageTask.LYRICS_PREVIEW,
            order_id=None,
            total_tokens=550,
        )
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    (row,) = body["rows"]
    assert row["vendor"] == "openrouter"
    assert row["totalTokens"] == 550


async def test_a_window_excludes_the_instant_it_ends_on(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — half-open ``[start, end)``, so two adjacent windows tile without both
    # claiming the call that landed exactly on the boundary.
    async with container.session_factory.begin() as session:
        await seed_call(session, created_at=WINDOW_END)
        await seed_call(session, created_at=WINDOW_END - timedelta(seconds=1))
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_USAGE_PATH, params=window_params())).json()

    # Assert
    assert body["totals"]["calls"] == 1
