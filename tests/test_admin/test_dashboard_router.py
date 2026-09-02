"""The dashboard over the real ASGI stack — the real container, login, guard and SQLite.

The assertions that carry this file are the ones about the numbers this screen refuses to
invent, because every one of them is a number an operator would act on:

* an empty deployment answers ``sampleCount: 0`` with ``p50Seconds: null`` and
  ``successRate: null`` — never ``0.0``, which reads as "nothing works" rather than
  "nothing has happened yet";
* an in-flight order stays out of the ``successRate`` denominator, so the rate does not
  fall the moment traffic arrives;
* ``isCostTelemetry`` is **false** against rows carrying the column defaults and flips to
  true the instant one row carries a real cost — measured, never declared;
* a failure code no class in ``hbd.errors`` claims answers ``isRetryable: null``, which is
  a third answer and not a quiet ``false``;
* a day with no orders is missing from the series rather than present as a zero.

There is no masking test in the usual sense here because there is nothing on this surface to
mask — so the privacy assertion is the stronger one: a known plaintext seeded into the
recipient name, the candidate text, the transcript and an attempt's error MESSAGE appears in
none of the six response bodies, at any of the four roles.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer
from hbd.admin.deps import RequirePermission, require_permission
from hbd.admin.routers.dashboard import (
    CAPABILITIES_PATH,
    FAILURES_PATH,
    LATENCY_PATH,
    NAME_STRATEGIES_PATH,
    ORDERS_BY_DAY_PATH,
    PULSE_PATH,
    build_dashboard_router,
)
from hbd.admin.security.permissions import ROLE_PERMISSIONS, Permission
from hbd.contracts import Genre, Language, NameStrategy, Occasion, OrderState, Script, VoiceGender
from hbd.db.enums import AdminRole, GenerationKind
from hbd.db.models.brief import BriefRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from tests.test_admin.conftest import ORIGIN, PASSWORD, create_account, sign_in

#: Fixed instants: every number here is derived from timestamps, so a wall clock would make
#: the day buckets and the latency sample race the test run.
DAY_ONE: Final[datetime] = datetime(2026, 3, 20, 9, 0, tzinfo=UTC)
#: Deliberately not 3-21: the gap day is what proves the series is not zero-filled.
DAY_THREE: Final[datetime] = datetime(2026, 3, 22, 9, 0, tzinfo=UTC)
FAR_FUTURE: Final[datetime] = datetime(2027, 1, 1, tzinfo=UTC)
#: One minute, so the percentile has an exact expected value rather than an approximate one.
DELIVERY_SECONDS: Final[float] = 60.0

#: ASCII on purpose. A non-ASCII name would come back from ``JSONResponse`` as ``\\uXXXX``
#: escapes and a substring check against the raw body would pass without proving anything.
RECIPIENT: Final[str] = "Gulomjon"
CANDIDATE: Final[str] = "Gulomjonbek"
TRANSCRIPT: Final[str] = "happy birthday dear Gulomjon"
ERROR_MESSAGE: Final[str] = "the vendor refused the lyric about Gulomjon"

ALL_PATHS: Final[tuple[str, ...]] = (
    PULSE_PATH,
    CAPABILITIES_PATH,
    ORDERS_BY_DAY_PATH,
    FAILURES_PATH,
    LATENCY_PATH,
    NAME_STRATEGIES_PATH,
)


# ---------------------------------------------------------------------------
# The application under test
# ---------------------------------------------------------------------------
@pytest.fixture
def dashboard_app(container: AdminContainer) -> FastAPI:
    """``create_app`` plus this router, mounted only if the app factory has not already.

    ``src/hbd/admin/app.py`` is wired in a later step and is not this file's to edit, so the
    router is included here — guarded on the path, so the day ``create_app`` mounts it the
    suite does not end up with two copies of every route.
    """
    application = create_app(container=container)
    mounted = {route.path for route in application.routes if isinstance(route, APIRoute)}
    if PULSE_PATH not in mounted:
        application.include_router(build_dashboard_router())
    return application


@pytest.fixture
async def client(dashboard_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Shadows the package fixture so every request in this file reaches the router."""
    async with dashboard_app.router.lifespan_context(dashboard_app):
        transport = httpx.ASGITransport(app=dashboard_app)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


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
async def seed_user(session: AsyncSession, *, telegram_user_id: int = 77_000_111) -> UserRow:
    row = UserRow(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        ui_language=Language.UZ_LATN,
        is_blocked=False,
        last_seen_at=DAY_ONE,
        created_at=DAY_ONE,
        updated_at=DAY_ONE,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_order(
    session: AsyncSession, *, user: UserRow, created_at: datetime = DAY_ONE, **kw: Any
) -> OrderRow:
    row = OrderRow(
        id=uuid4(),
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        state=kw.pop("state", OrderState.DELIVERED),
        correlation_id=kw.pop("correlation_id", "corr-dashboard"),
        is_paid=kw.pop("is_paid", True),
        delivered_at=kw.pop("delivered_at", None),
        failed_reason=kw.pop("failed_reason", None),
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_delivered_order(
    session: AsyncSession, *, user: UserRow, created_at: datetime = DAY_ONE
) -> OrderRow:
    """A delivered order with a known ``created_at`` → ``delivered_at`` duration."""
    return await seed_order(
        session,
        user=user,
        created_at=created_at,
        state=OrderState.DELIVERED,
        delivered_at=created_at + timedelta(seconds=DELIVERY_SECONDS),
    )


async def seed_brief(session: AsyncSession, *, order: OrderRow) -> BriefRow:
    """A brief carrying the known plaintext, so the privacy assertion has something to find."""
    row = BriefRow(
        id=uuid4(),
        order_id=order.id,
        occasion=Occasion.BIRTHDAY,
        genre=Genre.UZBEK_POP,
        vocal_gender=VoiceGender.FEMALE,
        ui_language=Language.UZ_LATN,
        output_language=Language.UZ_LATN,
        note=f"{RECIPIENT} loves mountains.",
        approved_lyrics=None,
        note_expires_at=FAR_FUTURE,
        note_purged_at=None,
        recipient_name_raw=RECIPIENT,
        recipient_name_display=RECIPIENT,
        recipient_lookup_key=RECIPIENT.casefold(),
        recipient_script=Script.LATIN,
        recipient_language=Language.UZ_LATN,
        recipient_candidates=[{"text": CANDIDATE, "strategy": "stripped", "rank": 0}],
        identity_expires_at=FAR_FUTURE,
        identity_purged_at=None,
        event_day=12,
        event_month=5,
        created_at=order.created_at,
        updated_at=order.created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_attempt(
    session: AsyncSession,
    *,
    order: OrderRow | None = None,
    created_at: datetime = DAY_ONE,
    **kw: Any,
) -> GenerationAttemptRow:
    row = GenerationAttemptRow(
        id=uuid4(),
        order_id=None if order is None else order.id,
        kind=kw.pop("kind", GenerationKind.SONG),
        sequence=0,
        attempt=0,
        provider=kw.pop("provider", "elevenlabs"),
        provider_remote_id=None,
        language=Language.UZ_LATN,
        is_success=kw.pop("is_success", True),
        name_candidate_strategy=kw.pop("name_candidate_strategy", None),
        name_candidate_rank=kw.pop("name_candidate_rank", None),
        is_name_verified=kw.pop("is_name_verified", None),
        match_confidence=None,
        name_candidate_text=kw.pop("name_candidate_text", None),
        stt_transcript=kw.pop("stt_transcript", None),
        error_code=kw.pop("error_code", None),
        error_message=kw.pop("error_message", None),
        cost_usd=kw.pop("cost_usd", 0.0),
        latency_ms=kw.pop("latency_ms", 0),
        identity_expires_at=FAR_FUTURE,
        identity_purged_at=None,
        text_expires_at=FAR_FUTURE,
        text_purged_at=None,
        created_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_failure(
    container: AdminContainer, *, error_code: str | None, created_at: datetime = DAY_ONE
) -> None:
    async with container.session_factory.begin() as session:
        await seed_attempt(session, created_at=created_at, is_success=False, error_code=error_code)


# ---------------------------------------------------------------------------
# Who may read it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_every_role_in_the_matrix_row_may_read_every_dashboard_route(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole, path: str
) -> None:
    # Arrange — §12.2 gives DASHBOARD_READ to all four roles (M/M/M/R).
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(path)

    # Assert
    assert response.status_code == 200


@pytest.mark.parametrize("path", ALL_PATHS)
async def test_an_unauthenticated_caller_gets_401_not_a_metric(
    client: httpx.AsyncClient, path: str
) -> None:
    # Act
    response = await client.get(path)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_the_guard_is_declared_once_on_the_router_and_not_on_a_handler() -> None:
    # Arrange — the 403 case cannot be reached from a signed-in session, because the matrix
    # row grants DASHBOARD_READ to every role that exists. What CAN regress is the guard
    # itself going missing, so that is what is asserted structurally.
    router = build_dashboard_router()

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


@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
def test_no_role_is_refused_because_the_matrix_row_covers_all_four(role: AdminRole) -> None:
    # Arrange / Act — stated here so the absence of a 403 test above is a fact about §12.2
    # rather than an omission. The day a role loses the cell, this fails and the 403 case
    # becomes reachable and testable.

    # Assert
    assert Permission.DASHBOARD_READ in ROLE_PERMISSIONS[role]


async def test_an_unknown_metrics_path_is_a_404_in_the_error_envelope(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get("/api/metrics/orders-by-hour")

    # Assert
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Nothing personal reaches this screen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
async def test_no_known_plaintext_appears_in_any_dashboard_body_at_any_role(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — the name, a candidate orthography, a transcript and a failure's error
    # MESSAGE are all seeded. Only the error CODE is meant to cross this boundary.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_delivered_order(session, user=user)
        await seed_brief(session, order=order)
        await seed_attempt(
            session,
            order=order,
            name_candidate_strategy=NameStrategy.STRIPPED,
            name_candidate_rank=0,
            is_name_verified=True,
            name_candidate_text=CANDIDATE,
            stt_transcript=TRANSCRIPT,
        )
        await seed_attempt(
            session,
            order=order,
            is_success=False,
            error_code="UPSTREAM_TIMEOUT",
            error_message=ERROR_MESSAGE,
        )
    await signed_in(container, client, role=role)

    # Act
    bodies = [(await client.get(path)).text for path in ALL_PATHS]

    # Assert
    for body in bodies:
        assert RECIPIENT not in body
        assert CANDIDATE not in body
        assert TRANSCRIPT not in body
        assert ERROR_MESSAGE not in body
    # And the error CODE does travel, so the assertion above is not passing because the
    # failure never reached the response at all.
    assert "UPSTREAM_TIMEOUT" in bodies[ALL_PATHS.index(FAILURES_PATH)]


async def test_a_viewer_and_an_owner_see_the_identical_pulse(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — §12.2 gives OWNER an R cell here, and R minus M is "unmasked personal data".
    # There is none on this screen, so the two cells must produce the same bytes.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_delivered_order(session, user=user)
        await seed_brief(session, order=order)
    await signed_in(container, client, role=AdminRole.VIEWER)
    as_viewer = await client.get(PULSE_PATH)
    client.cookies.clear()
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    as_owner = await client.get(PULSE_PATH)

    # Assert
    assert as_viewer.status_code == 200
    assert as_owner.json() == as_viewer.json()


# ---------------------------------------------------------------------------
# An empty deployment
# ---------------------------------------------------------------------------
async def test_an_empty_database_answers_with_no_data_rather_than_with_zeros(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    body = (await client.get(PULSE_PATH)).json()

    # Assert — counts are genuinely zero, but the two DERIVED numbers are null: a rate over
    # no terminal orders and a percentile over no samples are not measurements of zero.
    assert body["delivery"] == {
        "total": 0,
        "delivered": 0,
        "failed": 0,
        "cancelled": 0,
        "inFlight": 0,
        "terminalCount": 0,
        "successRate": None,
    }
    assert body["latency"] == {"sampleCount": 0, "p50Seconds": None, "p95Seconds": None}
    assert body["failures"] == []


async def test_the_percentile_path_does_not_crash_on_an_empty_sample(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``nearest_rank_offset`` raises on an empty sample, so the guard in
    # ``delivery_latency`` is what stands between this route and a 500 on a fresh install.
    await signed_in(container, client)

    # Act
    response = await client.get(LATENCY_PATH)

    # Assert
    assert response.status_code == 200
    assert response.json() == {"sampleCount": 0, "p50Seconds": None, "p95Seconds": None}


async def test_an_empty_database_returns_an_empty_series_not_a_zero_filled_one(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(ORDERS_BY_DAY_PATH)

    # Assert
    assert response.json() == []


# ---------------------------------------------------------------------------
# Seeded rows move the right numbers
# ---------------------------------------------------------------------------
async def test_a_delivered_order_moves_delivery_and_latency_together(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        await seed_delivered_order(session, user=user)
    await signed_in(container, client)

    # Act
    body = (await client.get(PULSE_PATH)).json()

    # Assert
    assert body["delivery"]["total"] == 1
    assert body["delivery"]["delivered"] == 1
    assert body["delivery"]["terminalCount"] == 1
    assert body["delivery"]["successRate"] == 1.0
    # The sample size travels with the percentile: one order is not a measurement of p95.
    assert body["latency"]["sampleCount"] == 1
    assert body["latency"]["p50Seconds"] == pytest.approx(DELIVERY_SECONDS, abs=0.01)
    assert body["latency"]["p95Seconds"] == pytest.approx(DELIVERY_SECONDS, abs=0.01)


async def test_an_in_flight_order_is_not_counted_as_a_failure(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one delivered, one still generating. Counting the live one as a failure is
    # what makes the success rate fall every time traffic rises.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        await seed_delivered_order(session, user=user)
        await seed_order(session, user=user, state=OrderState.GENERATING)
    await signed_in(container, client)

    # Act
    delivery = (await client.get(PULSE_PATH)).json()["delivery"]

    # Assert
    assert delivery["total"] == 2
    assert delivery["inFlight"] == 1
    assert delivery["terminalCount"] == 1
    assert delivery["successRate"] == 1.0


async def test_a_failed_order_lands_in_the_denominator(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        await seed_delivered_order(session, user=user)
        await seed_order(session, user=user, state=OrderState.FAILED)
    await signed_in(container, client)

    # Act
    delivery = (await client.get(PULSE_PATH)).json()["delivery"]

    # Assert
    assert delivery["failed"] == 1
    assert delivery["terminalCount"] == 2
    assert delivery["successRate"] == 0.5


async def test_a_failed_attempt_appears_with_its_share_and_a_retryability_verdict(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two codes, one of them twice, so the ordering and the shares both bite.
    await seed_failure(container, error_code="UPSTREAM_TIMEOUT")
    await seed_failure(container, error_code="UPSTREAM_TIMEOUT")
    await seed_failure(container, error_code="NAME_UNVERIFIABLE")
    await signed_in(container, client)

    # Act
    failures = (await client.get(FAILURES_PATH)).json()

    # Assert — largest first, shares over the failures in the window.
    assert failures == [
        {
            "errorCode": "UPSTREAM_TIMEOUT",
            "count": 2,
            "share": pytest.approx(2 / 3),
            "isRetryable": True,
        },
        {
            "errorCode": "NAME_UNVERIFIABLE",
            "count": 1,
            "share": pytest.approx(1 / 3),
            "isRetryable": False,
        },
    ]


@pytest.mark.parametrize("error_code", ["ARTIST_NAME_IN_STYLE", "SOMETHING_NOBODY_DEFINED", None])
async def test_a_code_no_class_claims_is_null_rather_than_not_retryable(
    container: AdminContainer, client: httpx.AsyncClient, error_code: str | None
) -> None:
    # Arrange — three ways to reach "unknown": a code raised with an explicit ``code=`` and
    # no class of its own, a string outside the taxonomy entirely, and no code at all.
    await seed_failure(container, error_code=error_code)
    await signed_in(container, client)

    # Act
    failures = (await client.get(FAILURES_PATH)).json()

    # Assert — null is a third answer. A quiet ``false`` would tell an operator not to retry
    # something nobody has decided about.
    assert failures[0]["errorCode"] == error_code
    assert failures[0]["isRetryable"] is None


async def test_a_successful_attempt_is_not_in_the_failure_breakdown(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    async with container.session_factory.begin() as session:
        await seed_attempt(session, is_success=True, error_code=None)
    await signed_in(container, client)

    # Act
    failures = (await client.get(FAILURES_PATH)).json()

    # Assert
    assert failures == []


# ---------------------------------------------------------------------------
# The series, and the window
# ---------------------------------------------------------------------------
async def test_a_day_with_no_orders_is_absent_from_the_series(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — orders on the 20th and the 22nd. The 21st had none.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        await seed_delivered_order(session, user=user, created_at=DAY_ONE)
        await seed_order(session, user=user, created_at=DAY_THREE, state=OrderState.FAILED)
    await signed_in(container, client)

    # Act
    series = (await client.get(ORDERS_BY_DAY_PATH)).json()

    # Assert — two entries, oldest first, and no invented zero between them.
    assert [entry["day"] for entry in series] == ["2026-03-20", "2026-03-22"]
    assert series[0] == {"day": "2026-03-20", "total": 1, "delivered": 1, "failed": 0, "paid": 1}
    assert series[1]["failed"] == 1


async def test_a_window_restricts_the_series_to_the_days_asked_for(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        await seed_delivered_order(session, user=user, created_at=DAY_ONE)
        await seed_delivered_order(session, user=user, created_at=DAY_THREE)
    await signed_in(container, client)

    # Act
    series = (
        await client.get(
            ORDERS_BY_DAY_PATH,
            params={
                "from": DAY_THREE.isoformat(),
                "to": (DAY_THREE + timedelta(days=1)).isoformat(),
            },
        )
    ).json()

    # Assert
    assert [entry["day"] for entry in series] == ["2026-03-22"]


async def test_a_naive_instant_is_refused_rather_than_guessed_at(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``UtcDateTime`` would raise inside the driver's bind processor, where no
    # handler is waiting, so the refusal has to happen at the boundary.
    await signed_in(container, client)

    # Act
    response = await client.get(
        FAILURES_PATH, params={"from": "2026-03-20T09:00:00", "to": "2026-03-22T09:00:00"}
    )

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


@pytest.mark.parametrize("parameter", ["from", "to"])
async def test_one_end_of_a_window_is_refused_because_the_other_would_be_a_guess(
    container: AdminContainer, client: httpx.AsyncClient, parameter: str
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(LATENCY_PATH, params={parameter: DAY_ONE.isoformat()})

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
        LATENCY_PATH, params={"from": DAY_THREE.isoformat(), "to": DAY_ONE.isoformat()}
    )

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# The name bake-off
# ---------------------------------------------------------------------------
async def test_name_strategies_report_the_verification_rate_over_verified_rows_only(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two verdicts on one strategy, plus a row where verification never ran.
    # Counting the third as a failure would penalise the strategy for a disabled verifier.
    async with container.session_factory.begin() as session:
        for verified in (True, False):
            await seed_attempt(
                session,
                name_candidate_strategy=NameStrategy.STRIPPED,
                name_candidate_rank=0,
                is_name_verified=verified,
            )
        await seed_attempt(
            session, name_candidate_strategy=NameStrategy.STRIPPED, is_name_verified=None
        )
    await signed_in(container, client)

    # Act
    strategies = (await client.get(NAME_STRATEGIES_PATH)).json()

    # Assert
    assert strategies == [
        {"strategy": "stripped", "attempts": 2, "verified": 1, "verificationRate": 0.5}
    ]


# ---------------------------------------------------------------------------
# Capabilities: measured, never declared
# ---------------------------------------------------------------------------
async def test_capabilities_report_no_cost_telemetry_for_rows_at_the_column_defaults(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a real attempt row, written the way every writer writes one today:
    # ``cost_usd`` at its 0.0 default and ``latency_ms`` at its 0.
    async with container.session_factory.begin() as session:
        await seed_attempt(session)
    await signed_in(container, client)

    # Act
    body = (await client.get(CAPABILITIES_PATH)).json()

    # Assert — false, so the SPA renders "not instrumented" instead of charting zeros. And
    # the pulse carries no cost FIGURE at all for the same reason: the only thing on it with
    # "cost" in the name is the capability flag that says there is nothing to report.
    assert body["isCostTelemetry"] is False
    assert body["isLatencyTelemetry"] is False
    assert body["isStateTransitionLog"] is False
    pulse = (await client.get(PULSE_PATH)).json()
    assert set(pulse) == {"delivery", "latency", "failures", "capabilities"}
    assert not [key for key in pulse["delivery"] if "cost" in key.casefold()]


async def test_cost_telemetry_flips_on_the_first_row_that_carries_a_cost(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the whole point of a MEASURED capability: nobody has to flip a constant.
    async with container.session_factory.begin() as session:
        await seed_attempt(session, cost_usd=0.42, latency_ms=1_500)
    await signed_in(container, client)

    # Act
    body = (await client.get(CAPABILITIES_PATH)).json()

    # Assert
    assert body["isCostTelemetry"] is True
    assert body["isLatencyTelemetry"] is True


async def test_the_pulse_carries_the_same_capability_block_as_its_own_route(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two readings of one probe must not be able to disagree; the SPA branches on
    # the block inside the pulse and on the standalone route interchangeably.
    async with container.session_factory.begin() as session:
        await seed_attempt(session)
    await signed_in(container, client)

    # Act
    pulse = (await client.get(PULSE_PATH)).json()
    capabilities = (await client.get(CAPABILITIES_PATH)).json()

    # Assert
    assert pulse["capabilities"] == capabilities
    assert set(capabilities) == {
        "isCostTelemetry",
        "isLatencyTelemetry",
        "isAssetStorageKeyRecorded",
        "isChatCapture",
        "isPaymentLedger",
        "isStateTransitionLog",
    }
