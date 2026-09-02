"""``/api/generations`` over the real ASGI stack — the real container, login and guard.

The render ledger is the one screen where an operator decides what the name pipeline should
cost and which orthography to try first, so the assertions that carry this file's weight are
the ones about what it refuses to round off or to leak:

* a candidate written ``Gʻulom`` comes back as ``G•••`` — cut at a grapheme cluster, with
  the U+02BB modifier letter neither split nor normalised — and the plaintext is not a
  substring of the body at **any** of the four roles §12.2 grants RECORDS_READ to;
* an attempt carrying an ``stt_transcript`` reports its LENGTH and nothing else: the
  transcript is a near-verbatim copy of the whole song, and §6.7 routes free text through
  ``POST /reveal`` alone;
* ``costUsd`` and ``latencyMs`` are ``null`` on an uninstrumented row rather than ``0.0`` and
  ``0``, which is what the columns actually hold today;
* ``isOrphaned`` finds an attempt with no order and cannot tell a pre-order name preview
  from a render whose order was deleted, because ``ON DELETE SET NULL`` makes them the same
  row shape.

There is deliberately no "a role without the permission gets a 403" case: RECORDS_READ is
granted to all four roles, so no role can be refused, and a test asserting otherwise would be
asserting a matrix this repo does not have. What is asserted instead is that the guard is
declared **on the router** — which is what makes a future matrix change take effect on both
routes at once — and the one 403 these routes really can answer, the forced-rotation gate.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer
from hbd.admin.deps import RequirePermission
from hbd.admin.routers.generations import (
    GENERATIONS_PATH,
    build_generations_router,
)
from hbd.admin.security.permissions import RBAC_MATRIX, Permission
from hbd.admin.serializers.redaction import MASK
from hbd.contracts import CostSource, NameStrategy, OrderState
from hbd.db.enums import AdminRole, GenerationKind
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from tests.test_admin.conftest import NOW, PASSWORD, create_account, sign_in

#: The name §12.3 names as the case that breaks naive slicing. U+02BB MODIFIER LETTER TURNED
#: COMMA is three UTF-8 bytes, its own code point and category ``Lm`` — a letter — so the
#: first grapheme cluster is the bare ``G``.
KNOWN_NAME: Final[str] = "Gʻulom"
MASKED_NAME: Final[str] = f"G{MASK}"
#: A transcript of the whole song, which is what verification actually hears: inpainting is
#: enterprise-gated, so this echoes a lyric the customer may have written themselves.
TRANSCRIPT: Final[str] = "Tugʻilgan kuning bilan Gʻulom, sen eng zoʻr insonsan"

TELEGRAM_USER_ID: Final[int] = 587_231_904
_IDENTITY_DAYS: Final[int] = 90
_TEXT_DAYS: Final[int] = 30


def attempt_path(attempt_id: UUID) -> str:
    return f"{GENERATIONS_PATH}/{attempt_id}"


# ---------------------------------------------------------------------------
# The application under test
# ---------------------------------------------------------------------------
def api_routes(application: FastAPI) -> list[APIRoute]:
    """Every ``APIRoute`` the application serves, however it stores its included routers.

    ``app.routes`` is not flat on this FastAPI: ``include_router`` appends one wrapper per
    router and keeps the router it was built from on ``original_router``. Read tolerantly so
    this file asserts what the application serves rather than which of the two shapes the
    installed version happens to use.
    """
    found: list[APIRoute] = []
    for route in application.routes:
        if isinstance(route, APIRoute):
            found.append(route)
            continue
        included = getattr(route, "original_router", None)
        if isinstance(included, APIRouter):
            found.extend(nested for nested in included.routes if isinstance(nested, APIRoute))
    return found


@pytest.fixture
def admin_app(container: AdminContainer) -> FastAPI:
    """``create_app`` plus this router, until the wiring step includes it there.

    The guard is not decoration. Once ``create_app`` includes the generations router, an
    unconditional second ``include_router`` here would register a shadow copy of every route
    ahead of — or behind — the real one, and this file would then be testing the copy it
    installed rather than the one the application serves.
    """
    application = create_app(container=container)
    paths = {route.path for route in api_routes(application)}
    if GENERATIONS_PATH not in paths:
        application.include_router(build_generations_router())
    return application


# ---------------------------------------------------------------------------
# Seeding, through the real models
# ---------------------------------------------------------------------------
async def seed_order(container: AdminContainer) -> UUID:
    """One user and one order, so a non-orphaned attempt has a real row to point at."""
    user_id, order_id = uuid4(), uuid4()
    async with container.session_factory.begin() as db:
        db.add(UserRow(id=user_id, telegram_user_id=TELEGRAM_USER_ID, last_seen_at=NOW))
        db.add(
            OrderRow(
                id=order_id,
                user_id=user_id,
                telegram_user_id=TELEGRAM_USER_ID,
                state=OrderState.GENERATING,
                correlation_id="corr-generations-1",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return order_id


async def seed_attempt(
    container: AdminContainer,
    *,
    kind: GenerationKind = GenerationKind.SONG,
    order_id: UUID | None = None,
    provider: str | None = "elevenlabs",
    is_success: bool = True,
    error_code: str | None = None,
    strategy: NameStrategy | None = None,
    name_candidate_text: str | None = None,
    stt_transcript: str | None = None,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
    created_at: datetime = NOW,
) -> GenerationAttemptRow:
    """One ``generation_attempts`` row, written through the model the pipeline writes."""
    row = GenerationAttemptRow(
        id=uuid4(),
        order_id=order_id,
        kind=kind,
        provider=provider,
        is_success=is_success,
        error_code=error_code,
        name_candidate_strategy=strategy,
        name_candidate_text=name_candidate_text,
        stt_transcript=stt_transcript,
        identity_expires_at=created_at + timedelta(days=_IDENTITY_DAYS),
        text_expires_at=created_at + timedelta(days=_TEXT_DAYS),
        cost_usd=cost_usd,
        cost_source=CostSource.VENDOR_REPORTED,
        latency_ms=latency_ms,
        created_at=created_at,
    )
    async with container.session_factory.begin() as db:
        db.add(row)
    return row


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole = AdminRole.ADMIN
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Who may read it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
async def test_every_role_in_the_matrix_row_may_read_the_render_ledger(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — §12.2 gives RECORDS_READ as M to all four roles, OWNER included.
    await seed_attempt(container)
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(GENERATIONS_PATH)

    # Assert
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_an_unauthenticated_caller_gets_401_not_the_ledger(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    attempt = await seed_attempt(container, name_candidate_text=KNOWN_NAME)

    # Act
    listed = await client.get(GENERATIONS_PATH)
    detail = await client.get(attempt_path(attempt.id))

    # Assert — both routes, because a guard on one handler is a guard missing from the next.
    assert listed.status_code == 401
    assert detail.status_code == 401
    assert listed.json()["error"]["code"] == "UNAUTHENTICATED"
    assert KNOWN_NAME not in detail.text


async def test_an_operator_who_still_owes_a_password_change_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the only 403 these routes can answer: RECORDS_READ has no un-granted role.
    await create_account(container, username="fresh", must_change_password=True)
    assert (await sign_in(client, username="fresh", password=PASSWORD)).status_code == 200

    # Act
    response = await client.get(GENERATIONS_PATH)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "password_change_required"


def test_the_permission_is_declared_on_the_router_rather_than_on_a_handler() -> None:
    # Arrange — a router-level dependency reaches every route added after it; a per-handler
    # one is the guard somebody forgets on the next route (§12.1 T3).
    router = build_generations_router()

    # Act
    declared = [
        depends.dependency
        for depends in router.dependencies
        if isinstance(depends.dependency, RequirePermission)
    ]
    routes = [route for route in router.routes if isinstance(route, APIRoute)]

    # Assert — the router declares exactly one guard, and no route added a second of its
    # own: FastAPI hands each route the router's list, so an equal list means nothing local.
    assert len(routes) == 2
    assert [guard.permission for guard in declared] == [Permission.RECORDS_READ]
    assert all(list(route.dependencies) == list(router.dependencies) for route in routes)


def test_both_routes_are_reads_and_neither_offers_an_unsafe_method() -> None:
    # Arrange — §12.1 T8: no state change behind a safe method, and nothing in this slice
    # writes at all. HEAD is Starlette's own free companion to GET.
    router = build_generations_router()

    # Act
    methods = [route.methods for route in router.routes if isinstance(route, APIRoute)]

    # Assert
    assert methods
    assert all(found is not None and found <= {"GET", "HEAD"} for found in methods)


def test_records_read_has_no_role_the_matrix_refuses() -> None:
    # Arrange / Act — the reason this file has no role-403 case, asserted rather than
    # asserted in prose. The day a role is removed from this row, this fails and the
    # missing test becomes writable.

    # Assert
    assert set(RBAC_MATRIX[Permission.RECORDS_READ]) == set(AdminRole)


# ---------------------------------------------------------------------------
# Masking (§12.3)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
async def test_the_candidate_name_is_masked_at_every_role_including_owner(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — there is no unmasked variant in this slice. Plaintext is POST /reveal only.
    attempt = await seed_attempt(
        container, kind=GenerationKind.NAME_PREVIEW, name_candidate_text=KNOWN_NAME
    )
    await signed_in(container, client, role=role)

    # Act
    listed = await client.get(GENERATIONS_PATH)
    detail = await client.get(attempt_path(attempt.id))

    # Assert — the mask is right AND the plaintext is not in the bytes, which is the rule.
    assert detail.json()["nameCandidate"] == MASKED_NAME
    assert listed.json()["items"][0]["nameCandidate"] == MASKED_NAME
    assert KNOWN_NAME not in listed.text
    assert KNOWN_NAME not in detail.text


async def test_a_purged_identity_reads_as_absent_rather_than_as_something_to_reveal(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the sweep nulled the text and left the tuning signal standing.
    attempt = await seed_attempt(
        container,
        kind=GenerationKind.NAME_VERIFICATION,
        provider=None,
        strategy=NameStrategy.STRIPPED,
        name_candidate_text=None,
    )
    await signed_in(container, client)

    # Act
    body = (await client.get(attempt_path(attempt.id))).json()

    # Assert — ``null``, not ``"•••"``: a mask would promise a reveal that finds nothing.
    assert body["nameCandidate"] is None
    assert body["nameCandidateStrategy"] == NameStrategy.STRIPPED.value


async def test_a_transcript_is_a_character_count_and_never_a_value(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the transcript is the whole song, so it is free text about a real person.
    attempt = await seed_attempt(
        container, kind=GenerationKind.NAME_VERIFICATION, stt_transcript=TRANSCRIPT
    )
    await signed_in(container, client)

    # Act
    listed = await client.get(GENERATIONS_PATH)
    detail = await client.get(attempt_path(attempt.id))

    # Assert
    item = listed.json()["items"][0]
    assert detail.json()["sttTranscriptChars"] == len(TRANSCRIPT)
    assert item["sttTranscriptChars"] == len(TRANSCRIPT)
    assert "sttTranscript" not in item
    assert TRANSCRIPT not in listed.text
    assert TRANSCRIPT not in detail.text


# ---------------------------------------------------------------------------
# Instrumentation, told apart from a column default
# ---------------------------------------------------------------------------
async def test_an_uninstrumented_row_reports_null_rather_than_free_and_instant(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — today's shape: nothing in src/ writes either column, so both hold defaults.
    attempt = await seed_attempt(container, cost_usd=0.0, latency_ms=0)
    await signed_in(container, client)

    # Act
    body = (await client.get(attempt_path(attempt.id))).json()

    # Assert — "$0.00 / 0 ms" would be indistinguishable from a real free, instant call.
    assert body["costUsd"] is None
    assert body["latencyMs"] is None
    assert body["costSource"] is None
    assert body["isInstrumented"] is False


async def test_a_measured_row_reports_its_numbers_and_says_it_was_measured(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — what Phase 5 will write. Nothing in the router changes on that day.
    attempt = await seed_attempt(container, cost_usd=0.42, latency_ms=8_300)
    await signed_in(container, client)

    # Act
    body = (await client.get(attempt_path(attempt.id))).json()

    # Assert
    assert body["costUsd"] == pytest.approx(0.42)
    assert body["latencyMs"] == 8_300
    assert body["costSource"] == CostSource.VENDOR_REPORTED.value
    assert body["isInstrumented"] is True


# ---------------------------------------------------------------------------
# Shape and paging
# ---------------------------------------------------------------------------
async def test_the_list_comes_back_newest_first_and_pages_on_its_own_cursor(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    for minutes in range(3):
        await seed_attempt(container, created_at=NOW - timedelta(minutes=minutes))
    await signed_in(container, client)

    # Act
    first = (await client.get(GENERATIONS_PATH, params={"limit": 2})).json()
    second = (
        await client.get(
            GENERATIONS_PATH, params={"limit": 2, "cursor": first["meta"]["nextCursor"]}
        )
    ).json()

    # Assert
    stamps = [item["createdAt"] for item in first["items"]]
    assert stamps == sorted(stamps, reverse=True)
    assert len(second["items"]) == 1
    assert second["meta"]["nextCursor"] is None
    assert {item["id"] for item in first["items"]}.isdisjoint(
        {item["id"] for item in second["items"]}
    )


async def test_the_total_is_absent_unless_it_was_asked_for(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``total`` and ``isTotalExact`` travel together or not at all.
    for _ in range(3):
        await seed_attempt(container)
    await signed_in(container, client)

    # Act
    without = (await client.get(GENERATIONS_PATH, params={"limit": 1})).json()
    with_total = (
        await client.get(GENERATIONS_PATH, params={"limit": 1, "withTotal": "true"})
    ).json()

    # Assert
    assert without["meta"]["total"] is None
    assert without["meta"]["isTotalExact"] is None
    assert with_total["meta"]["total"] == 3
    assert with_total["meta"]["isTotalExact"] is True


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
async def test_repeated_kinds_are_or_within_the_field(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_attempt(container, kind=GenerationKind.SONG)
    await seed_attempt(container, kind=GenerationKind.LYRICS)
    await seed_attempt(container, kind=GenerationKind.COVER)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(GENERATIONS_PATH, params=[("kind", "song"), ("kind", "lyrics")])
    ).json()

    # Assert
    assert {item["kind"] for item in body["items"]} == {"song", "lyrics"}


async def test_filters_are_and_across_fields(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — only one row satisfies both halves.
    await seed_attempt(
        container, provider="elevenlabs", is_success=False, error_code="UPSTREAM_5XX"
    )
    await seed_attempt(container, provider="openai", is_success=False, error_code="UPSTREAM_5XX")
    await seed_attempt(container, provider="elevenlabs", is_success=True)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(GENERATIONS_PATH, params={"provider": "elevenlabs", "isSuccess": "false"})
    ).json()

    # Assert
    assert len(body["items"]) == 1
    assert body["items"][0]["errorCode"] == "UPSTREAM_5XX"
    assert body["items"][0]["isRetryable"] is True


async def test_the_strategy_filter_selects_one_orthography(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — this filter is the bake-off: which orthography survived verification.
    await seed_attempt(container, strategy=NameStrategy.CANONICAL)
    await seed_attempt(container, strategy=NameStrategy.CYRILLIC)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(GENERATIONS_PATH, params={"strategy": NameStrategy.CYRILLIC.value})
    ).json()

    # Assert
    assert [item["nameCandidateStrategy"] for item in body["items"]] == ["cyrillic"]


async def test_an_error_code_filter_finds_the_failures_it_names(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_attempt(container, is_success=False, error_code="UPSTREAM_TIMEOUT")
    await seed_attempt(container, is_success=False, error_code="CONTENT_REJECTED")
    await signed_in(container, client)

    # Act
    body = (await client.get(GENERATIONS_PATH, params={"errorCode": "UPSTREAM_TIMEOUT"})).json()

    # Assert
    assert [item["errorCode"] for item in body["items"]] == ["UPSTREAM_TIMEOUT"]


async def test_orphaned_selects_attempts_with_no_order_and_cannot_tell_the_two_causes_apart(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a pre-order name preview and a render whose order was deleted both arrive
    # as ``order_id IS NULL``, because the FK is ON DELETE SET NULL so the tuning signal
    # outlives the order. That they are indistinguishable is the design, not a gap.
    await seed_attempt(container, kind=GenerationKind.NAME_PREVIEW, order_id=None)
    order_id = await seed_order(container)
    await seed_attempt(container, kind=GenerationKind.SONG, order_id=order_id)
    await signed_in(container, client)

    # Act
    orphaned = (await client.get(GENERATIONS_PATH, params={"isOrphaned": "true"})).json()
    attached = (await client.get(GENERATIONS_PATH, params={"isOrphaned": "false"})).json()

    # Assert
    assert [item["kind"] for item in orphaned["items"]] == ["name_preview"]
    assert all(item["isOrphaned"] is True for item in orphaned["items"])
    assert [item["orderId"] for item in attached["items"]] == [str(order_id)]
    assert attached["items"][0]["isOrphaned"] is False


async def test_the_window_restricts_the_page_to_the_interval_it_names(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    inside = await seed_attempt(container, created_at=NOW - timedelta(days=1))
    await seed_attempt(container, created_at=NOW - timedelta(days=30))
    await signed_in(container, client)

    # Act
    body = (
        await client.get(
            GENERATIONS_PATH,
            params={
                "from": (NOW - timedelta(days=7)).isoformat(),
                "to": (NOW + timedelta(days=1)).isoformat(),
            },
        )
    ).json()

    # Assert
    assert [item["id"] for item in body["items"]] == [str(inside.id)]


# ---------------------------------------------------------------------------
# Refusals at the boundary
# ---------------------------------------------------------------------------
async def test_a_naive_datetime_is_refused_rather_than_bound_to_a_timestamptz(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``UtcDateTime.process_bind_param`` raises inside the driver, where nothing
    # is waiting to catch it. §6.1 makes this a 422 at the boundary instead.
    await signed_in(container, client)

    # Act
    response = await client.get(
        GENERATIONS_PATH,
        params={"from": "2026-03-01T00:00:00", "to": "2026-04-01T00:00:00+00:00"},
    )

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


@pytest.mark.parametrize("half", ["from", "to"])
async def test_half_a_window_is_refused_rather_than_completed_with_an_invented_bound(
    container: AdminContainer, client: httpx.AsyncClient, half: str
) -> None:
    # Arrange — ``now`` as the missing bound is re-evaluated per request, so a keyset walk
    # would widen its own filter between pages.
    await signed_in(container, client)

    # Act
    response = await client.get(GENERATIONS_PATH, params={half: NOW.isoformat()})

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
        GENERATIONS_PATH,
        params={"from": NOW.isoformat(), "to": (NOW - timedelta(days=1)).isoformat()},
    )

    # Assert
    assert response.status_code == 422


async def test_an_unknown_kind_is_a_422_not_a_filter_that_matches_nothing(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the reason the parameter is typed as an enum.
    await seed_attempt(container)
    await signed_in(container, client)

    # Act
    response = await client.get(GENERATIONS_PATH, params={"kind": "orchestral"})

    # Assert
    assert response.status_code == 422


async def test_an_unknown_attempt_id_is_a_404_in_the_error_envelope(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    missing = uuid4()
    await signed_in(container, client)

    # Act
    response = await client.get(attempt_path(missing))

    # Assert
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["details"]["attemptId"] == str(missing)
    assert error["correlationId"]
