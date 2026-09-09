"""``/api/segments`` over the real ASGI stack — the registry, the audience count, and ``/users``.

Three things carry this file's weight, and all three are refusals rather than features:

* **No raw Telegram id is on either wire, and no customer row is either.** The preview
  returns counts; ``BROADCAST_SPEC §3.2`` sketched ten masked ``UserView``s beside them and
  this route deliberately has none, because ``UserView`` carries the **unmasked** id by design
  (every ``/users/**`` route keys on it) and §6.1 requires every row this feature puts on the
  wire to be masked. So the assertion is the blunt one: the seeded ids are not substrings of
  either response, at any role.
* **The published vocabulary is the compiler's own allowlist.** The field list is compared
  against :data:`~hbd.db.admin.segment.FIELDS` key for key, and against
  :data:`~hbd.db.admin.segment.SORT_KEYS` flag for flag, so a builder generated from this
  route can never offer a field or an ordering the server refuses — and
  :data:`~hbd.db.admin.segment.SEGMENT_REFUSALS` is asserted absent, which is the check that
  fails the day somebody adds a name predicate back.
* **The same document narrows the Users list.** ``?segment=`` on ``/users`` and
  ``?segment=`` on ``/segments/preview`` run one codec and one compiler, so the count an
  operator approves a send against and the page they check it on cannot be two populations.
  That is asserted by counting both.

There is no role-403 case here and that is the matrix rather than an omission: RECORDS_READ
and BROADCAST_READ are both **M** in all four cells. What is asserted instead is that the two
routes carry *different* guards declared on their own routers, and that both matrix rows
really are full — the test that starts failing on the day somebody narrows one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import uuid4

import httpx
import pytest
from fastapi.routing import APIRoute

from hbd.admin.container import AdminContainer
from hbd.admin.deps import RequirePermission
from hbd.admin.routers.segments import (
    SEGMENT_FIELDS_PATH,
    SEGMENT_PREVIEW_PATH,
    build_segment_fields_router,
    build_segments_router,
)
from hbd.admin.routers.users import USERS_PATH
from hbd.admin.schemas.segment import (
    MAX_SEGMENT_CHARS,
    SEGMENT_SCHEMA_VERSION,
    GroupModel,
    RuleModel,
    SegmentModel,
    SortModel,
    encode_segment,
)
from hbd.admin.security.permissions import RBAC_MATRIX, Permission
from hbd.contracts import Language
from hbd.db.admin.segment import (
    DEFAULT_SORT,
    FIELDS,
    SEGMENT_LIMITS,
    SEGMENT_REFUSALS,
    SORT_KEYS,
    MatchMode,
    SegmentOp,
    segment_capabilities,
)
from hbd.db.enums import AdminRole
from hbd.db.models.user import UserRow
from tests.test_admin.conftest import NOW, PASSWORD, create_account, sign_in

EVERY_ROLE: Final[tuple[AdminRole, ...]] = (
    AdminRole.VIEWER,
    AdminRole.SUPPORT,
    AdminRole.ADMIN,
    AdminRole.OWNER,
)

#: Four distinctive ids, so "the raw id is not on the wire" is a substring test that cannot
#: pass by accident against a masked value or a page of zeros.
REACHABLE_ID: Final[int] = 701_234_567
BLOCKED_ID: Final[int] = 702_345_678
BOT_BLOCKED_ID: Final[int] = 703_456_789
#: Barred by us AND blocked by them. The account that proves the three counts overlap.
BOTH_BLOCKED_ID: Final[int] = 704_567_890

SEEDED_IDS: Final[tuple[int, ...]] = (
    REACHABLE_ID,
    BLOCKED_ID,
    BOT_BLOCKED_ID,
    BOTH_BLOCKED_ID,
)


# ---------------------------------------------------------------------------
# Seeding, through the real model
# ---------------------------------------------------------------------------
async def seed_user(
    container: AdminContainer,
    *,
    telegram_user_id: int,
    ui_language: Language = Language.UZ_LATN,
    is_blocked: bool = False,
    blocked_bot_at: datetime | None = None,
) -> UserRow:
    """One ``users`` row — the row ``users_sql.ensure_user`` and ``credits.touch`` write."""
    row = UserRow(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        ui_language=ui_language,
        is_blocked=is_blocked,
        blocked_bot_at=blocked_bot_at,
        last_seen_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    async with container.session_factory.begin() as db:
        db.add(row)
    return row


async def seed_audience(container: AdminContainer) -> None:
    """The four shapes a broadcast has to tell apart, one account each.

    Two languages, so ``byLanguage`` is a split rather than a single bucket; one account in
    both refusal states, so a reader cannot get the arithmetic right by adding the counts up.
    """
    await seed_user(container, telegram_user_id=REACHABLE_ID)
    await seed_user(container, telegram_user_id=BLOCKED_ID, is_blocked=True)
    await seed_user(
        container,
        telegram_user_id=BOT_BLOCKED_ID,
        ui_language=Language.RU,
        blocked_bot_at=NOW,
    )
    await seed_user(
        container,
        telegram_user_id=BOTH_BLOCKED_ID,
        ui_language=Language.RU,
        is_blocked=True,
        blocked_bot_at=NOW,
    )


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole = AdminRole.ADMIN
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


def token(*rules: RuleModel | GroupModel, sort: SortModel | None = None) -> str:
    """One ``?segment=`` value, built with the codec the SPA uses rather than by hand."""
    return encode_segment(
        SegmentModel(v=SEGMENT_SCHEMA_VERSION, match=MatchMode.ALL, rules=rules, sort=sort)
    )


def field_named(body: dict[str, Any], key: str) -> dict[str, Any]:
    """One entry of the published registry, by key."""
    found: list[dict[str, Any]] = [entry for entry in body["fields"] if entry["key"] == key]
    assert len(found) == 1, key
    return found[0]


# ---------------------------------------------------------------------------
# Who may read them
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_every_role_in_the_matrix_row_may_read_the_field_registry(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — §3.1 gives BROADCAST_READ as M to all four roles: a campaign record holds no
    # customer data, so there is nothing here for a narrower cell to protect.
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(SEGMENT_FIELDS_PATH)

    # Assert
    assert response.status_code == 200
    assert response.json()["fields"]


@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_every_role_in_the_matrix_row_may_read_the_audience_preview(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — the preview counts the population ``/users`` pages, so it carries that route's
    # cell: RECORDS_READ, M in all four.
    await seed_audience(container)
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(SEGMENT_PREVIEW_PATH)

    # Assert
    assert response.status_code == 200
    assert response.json()["matched"] == len(SEEDED_IDS)


async def test_an_unauthenticated_caller_gets_401_from_both_routes(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — both, because a guard on one router is a guard missing from the other.
    await seed_audience(container)

    # Act
    fields = await client.get(SEGMENT_FIELDS_PATH)
    preview = await client.get(SEGMENT_PREVIEW_PATH)

    # Assert
    assert fields.status_code == 401
    assert preview.status_code == 401
    assert fields.json()["error"]["code"] == "UNAUTHENTICATED"
    assert preview.json()["error"]["code"] == "UNAUTHENTICATED"


def test_each_route_carries_exactly_one_guard_and_the_two_are_different() -> None:
    # Arrange — two routers rather than one, because a router carries one permission and
    # these are two cells (§12.1 T3). One router with a handler guard is the shape forbidden.
    fields_router = build_segment_fields_router()
    preview_router = build_segments_router()

    # Act
    declared = {
        Permission.BROADCAST_READ: fields_router,
        Permission.RECORDS_READ: preview_router,
    }

    # Assert
    for permission, router in declared.items():
        guards = [
            depends.dependency
            for depends in router.dependencies
            if isinstance(depends.dependency, RequirePermission)
        ]
        routes = [route for route in router.routes if isinstance(route, APIRoute)]
        assert [guard.permission for guard in guards] == [permission]
        assert len(routes) == 1
        assert all(list(route.dependencies) == list(router.dependencies) for route in routes)


def test_both_routes_are_reads_and_neither_offers_an_unsafe_method() -> None:
    # Arrange — §12.1 T8. A preview that wrote anything would be a state change behind a safe
    # method, and a browser prefetch would fire it.
    routes = [
        route
        for router in (build_segment_fields_router(), build_segments_router())
        for route in router.routes
        if isinstance(route, APIRoute)
    ]

    # Act
    methods = [route.methods for route in routes]

    # Assert — HEAD is Starlette's own free companion to GET.
    assert len(methods) == 2
    assert all(found is not None and found <= {"GET", "HEAD"} for found in methods)


def test_neither_permission_has_a_role_the_matrix_refuses() -> None:
    # Arrange / Act — the reason this file has no role-403 case, asserted rather than argued
    # in prose. The day a role is removed from either row, this fails and the missing test
    # becomes writable.

    # Assert
    assert set(RBAC_MATRIX[Permission.RECORDS_READ]) == set(AdminRole)
    assert set(RBAC_MATRIX[Permission.BROADCAST_READ]) == set(AdminRole)


# ---------------------------------------------------------------------------
# The registry, as the builder reads it
# ---------------------------------------------------------------------------
async def test_the_published_vocabulary_is_exactly_the_compilers_allowlist(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a builder generated from this document must not be able to compose a rule the
    # compiler refuses, nor keep offering a field the compiler withdrew. One list, both ways.
    await signed_in(container, client)

    # Act
    body = await client.get(SEGMENT_FIELDS_PATH)

    # Assert
    published = body.json()
    assert {entry["key"] for entry in published["fields"]} == set(FIELDS)
    assert published["version"] == SEGMENT_SCHEMA_VERSION
    assert published["defaultSort"] == {"key": DEFAULT_SORT.key, "dir": DEFAULT_SORT.direction}
    assert published["limits"]["maxRules"] == SEGMENT_LIMITS.max_rules
    assert published["limits"]["maxDepth"] == SEGMENT_LIMITS.max_depth
    assert published["limits"]["maxValueMembers"] == SEGMENT_LIMITS.max_value_members
    assert published["limits"]["maxAggregateRules"] == SEGMENT_LIMITS.max_aggregate_rules


async def test_no_refused_column_is_offered_as_a_field(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — SEGMENT_REFUSALS names the four columns a caller-steered WHERE would turn into
    # an unmask oracle (§6.1). This is the assertion that fails the day one comes back.
    await signed_in(container, client)

    # Act
    body = await client.get(SEGMENT_FIELDS_PATH)

    # Assert
    assert {entry["key"] for entry in body.json()["fields"]} & SEGMENT_REFUSALS == set()


async def test_each_field_reports_the_operators_and_the_ordering_the_compiler_will_accept(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``sortable`` is read off SORT_KEYS rather than off ``FieldSpec.sortable``,
    # which is only half the condition; ``last_activity_at`` is the field that tells them
    # apart, being filterable and deliberately never orderable.
    await signed_in(container, client)

    # Act
    body = (await client.get(SEGMENT_FIELDS_PATH)).json()

    # Assert
    for entry in body["fields"]:
        spec = FIELDS[entry["key"]]
        assert entry["ops"] == sorted(op.value for op in spec.ops)
        assert entry["sortable"] is (entry["key"] in SORT_KEYS)
        assert entry["isAggregate"] is spec.is_aggregate
        assert entry["capability"] == spec.capability
        assert entry["doc"] == spec.doc
    assert field_named(body, "last_activity_at")["sortable"] is False
    assert field_named(body, "delivered_order_count")["sortable"] is True


async def test_a_capability_gated_field_is_listed_with_this_deployments_answer(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a field whose table is absent stays LISTED and disabled rather than vanishing:
    # a rule on it is a refusal naming the field, and "not installed here" must not look like
    # "nobody matched".
    await signed_in(container, client)
    capabilities = segment_capabilities()
    gated = [key for key, spec in FIELDS.items() if spec.capability is not None]

    # Act
    body = (await client.get(SEGMENT_FIELDS_PATH)).json()

    # Assert
    assert gated, "the capability column is untested if nothing is gated"
    for key in gated:
        entry = field_named(body, key)
        assert entry["isAvailable"] is (entry["capability"] in capabilities)


# ---------------------------------------------------------------------------
# The audience preview
# ---------------------------------------------------------------------------
async def test_the_preview_counts_the_whole_population_when_no_segment_is_given(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an absent document means "everyone", which is what an operator sees before
    # they have written a rule.
    await seed_audience(container)
    await signed_in(container, client)

    # Act
    body = (await client.get(SEGMENT_PREVIEW_PATH)).json()

    # Assert — reachable is a COMPLEMENT, and the two refusal counts overlap on the account
    # that is both, so the four numbers deliberately do not add up to ``matched``.
    assert body["matched"] == 4
    assert body["reachable"] == 1
    assert body["skippedBlocked"] == 2
    assert body["skippedBotBlocked"] == 2


async def test_the_preview_splits_the_audience_by_language_and_omits_empty_ones(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the language is the only personalisation a broadcast has (§6.1), so it is the
    # one split that changes what an operator has to write.
    await seed_audience(container)
    await signed_in(container, client)

    # Act
    body = (await client.get(SEGMENT_PREVIEW_PATH)).json()

    # Assert — two languages seeded, two reported; ``en`` and ``uz_cyrl`` are absent rather
    # than present with a zero.
    assert body["byLanguage"] == [
        {"language": Language.RU.value, "count": 2},
        {"language": Language.UZ_LATN.value, "count": 2},
    ]


async def test_a_segment_narrows_the_preview_the_way_it_narrows_the_list(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one document, one codec, one compiler. The count an operator authorises a send
    # against and the page they check it on must not be two populations.
    await seed_audience(container)
    await signed_in(container, client)
    reachable = token(RuleModel(field="is_reachable", op=SegmentOp.IS_TRUE))

    # Act
    preview = await client.get(SEGMENT_PREVIEW_PATH, params={"segment": reachable})
    listed = await client.get(USERS_PATH, params={"segment": reachable})

    # Assert
    assert preview.json()["matched"] == 1
    assert len(listed.json()["items"]) == 1
    assert listed.json()["items"][0]["telegramUserId"] == REACHABLE_ID


async def test_a_nested_group_is_compiled_rather_than_flattened(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — "Russian speakers, or anyone we have barred": an ANY group inside the root's
    # ALL, which is the shape ``BROADCAST_SPEC §1.5``'s composite example takes.
    await seed_audience(container)
    await signed_in(container, client)
    composite = token(
        GroupModel(
            match=MatchMode.ANY,
            rules=(
                RuleModel(field="ui_language", op=SegmentOp.EQ, value=Language.RU.value),
                RuleModel(field="is_blocked", op=SegmentOp.IS_TRUE),
            ),
        )
    )

    # Act
    body = (await client.get(SEGMENT_PREVIEW_PATH, params={"segment": composite})).json()

    # Assert — the two Russian accounts plus the blocked Uzbek one, counted once each.
    assert body["matched"] == 3


# ---------------------------------------------------------------------------
# What is NOT on the wire (§6.1)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_no_raw_telegram_id_reaches_either_wire_at_any_role(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — the preview has no ``sample`` and the registry has no rows at all, so neither
    # response may contain an account identifier. Asserted as a substring test over the raw
    # bytes, because a masked field added later would still pass a field-by-field check.
    await seed_audience(container)
    await signed_in(container, client, role=role)
    everyone = token()

    # Act
    fields = await client.get(SEGMENT_FIELDS_PATH)
    preview = await client.get(SEGMENT_PREVIEW_PATH, params={"segment": everyone})

    # Assert
    assert preview.json()["matched"] == len(SEEDED_IDS)
    for telegram_user_id in SEEDED_IDS:
        assert str(telegram_user_id) not in fields.text
        assert str(telegram_user_id) not in preview.text


async def test_the_preview_carries_no_row_shaped_key_at_all(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the positive half of the same rule: the response is counts, and a ``sample``
    # or an ``items`` added later is a decision somebody has to make here first.
    await seed_audience(container)
    await signed_in(container, client)

    # Act
    body = (await client.get(SEGMENT_PREVIEW_PATH)).json()

    # Assert
    assert set(body) == {
        "matched",
        "reachable",
        "skippedBlocked",
        "skippedBotBlocked",
        "byLanguage",
    }


# ---------------------------------------------------------------------------
# Refusals — and none of them echoes the caller's value back
# ---------------------------------------------------------------------------
async def test_an_undecodable_token_is_a_422_that_does_not_quote_it_back(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a query string is a browser's, so the codec is a never-throw boundary, and its
    # refusal is one fixed sentence rather than pydantic's own message, which quotes the input
    # that failed. The value a caller sent is the one thing a segment refusal must not carry.
    await signed_in(container, client)
    sentinel = "not-a-document-{}".format("A" * 20)

    # Act
    response = await client.get(SEGMENT_PREVIEW_PATH, params={"segment": sentinel})

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"
    assert response.json()["error"]["message"] == "segment is not decodable"
    assert sentinel not in response.text


async def test_an_oversize_token_is_refused_before_anything_decodes_it(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the bound is declared at the router AND checked again in the codec, so this is
    # a 422 either way; what matters is that it is a refusal rather than a decode.
    await signed_in(container, client)

    # Act
    response = await client.get(
        SEGMENT_PREVIEW_PATH, params={"segment": "A" * (MAX_SEGMENT_CHARS + 1)}
    )

    # Assert
    assert response.status_code == 422


async def test_an_unknown_field_is_refused_by_the_registry(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the document names a KEY, never a column: ``FIELDS[key]`` is a dict lookup, so
    # a field nobody wrote into the registry is unaddressable under any spelling.
    await signed_in(container, client)
    unknown = token(RuleModel(field="phone_e164", op=SegmentOp.IS_NOT_NULL))

    # Act
    response = await client.get(SEGMENT_PREVIEW_PATH, params={"segment": unknown})

    # Assert — the key is named in the error's context for the log, and is deliberately not
    # in the body: an ``HbdError``'s context is never rendered into the envelope.
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "unknown field"
    assert "phone_e164" not in response.text


# ---------------------------------------------------------------------------
# The same document on the Users list (BROADCAST_SPEC §1.6)
# ---------------------------------------------------------------------------
async def test_a_sort_parameter_orders_the_list_without_publishing_the_column(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``?sort=`` names a SORT_KEYS member, which the registry resolves to an
    # expression object: no caller string reaches ORDER BY. Sorting on a field is also not
    # publishing it, so the row shape is the one every other caller gets.
    await seed_audience(container)
    await signed_in(container, client)

    # Act
    response = await client.get(
        USERS_PATH, params={"sort": "order_count", "sortDir": "asc", "limit": 50}
    )

    # Assert
    body = response.json()
    assert response.status_code == 200
    assert len(body["items"]) == len(SEEDED_IDS)
    assert "lastSeenAt" not in body["items"][0]
    assert "orderCount" in body["items"][0]


async def test_a_sort_the_registry_refuses_is_a_422_rather_than_an_order_by(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``last_activity_at`` is filterable and deliberately never orderable: a
    # predicate discloses the bucket the operator chose, an ordering hands over a total
    # activity ranking of identified accounts.
    await seed_audience(container)
    await signed_in(container, client)

    # Act
    refused = await client.get(USERS_PATH, params={"sort": "last_activity_at"})
    invented = await client.get(USERS_PATH, params={"sort": "users.id; drop table users"})

    # Assert
    assert refused.status_code == 422
    assert invented.status_code == 422


async def test_a_total_beside_an_aggregate_sort_is_refused_rather_than_paid_for_twice(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``BROADCAST_SPEC §1.6``: ordering on an aggregate makes the planner evaluate a
    # correlated subquery over the whole filtered set, and a bounded count pays for it again.
    # One request never buys both, and the refusal says which parameter to drop.
    await seed_audience(container)
    await signed_in(container, client)

    # Act
    refused = await client.get(
        USERS_PATH, params={"sort": "delivered_order_count", "withTotal": True}
    )
    allowed = await client.get(USERS_PATH, params={"sort": "delivered_order_count"})
    counted = await client.get(USERS_PATH, params={"withTotal": True})

    # Assert
    assert refused.status_code == 422
    assert "withTotal" in refused.json()["error"]["message"]
    assert allowed.status_code == 200
    assert counted.json()["meta"]["total"] == len(SEEDED_IDS)


async def test_the_default_sort_keeps_the_cursor_the_list_has_always_used(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``joined_at`` IS ``users.created_at`` under the registry's own name, so a
    # document sorted the default way is the walk this list already did: the smaller token
    # keeps working, and every bookmarked "next page" link keeps resolving.
    await seed_audience(container)
    await signed_in(container, client)
    default = token(sort=SortModel(key=DEFAULT_SORT.key, dir=DEFAULT_SORT.direction))

    # Act
    first = await client.get(USERS_PATH, params={"segment": default, "limit": 2})
    cursor = first.json()["meta"]["nextCursor"]
    second = await client.get(USERS_PATH, params={"segment": default, "limit": 2, "cursor": cursor})

    # Assert
    assert cursor
    assert len(first.json()["items"]) == 2
    assert len(second.json()["items"]) == 2
    assert {item["telegramUserId"] for item in first.json()["items"]}.isdisjoint(
        {item["telegramUserId"] for item in second.json()["items"]}
    )


async def test_a_sorted_page_resumes_from_its_own_cursor_and_refuses_another_sort(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a cursor minted under one ordering cannot resume another: the two interleave
    # differently, so continuing silently would drop rows and repeat others.
    await seed_audience(container)
    await signed_in(container, client)
    ordering: dict[str, Any] = {"sort": "order_count", "sortDir": "asc"}

    # Act
    first = await client.get(USERS_PATH, params={**ordering, "limit": 2})
    cursor = first.json()["meta"]["nextCursor"]
    resumed = await client.get(USERS_PATH, params={**ordering, "limit": 2, "cursor": cursor})
    crossed = await client.get(
        USERS_PATH, params={"sort": "topup_count", "sortDir": "asc", "cursor": cursor}
    )

    # Assert
    assert cursor
    assert len(resumed.json()["items"]) == 2
    assert crossed.status_code == 422
    assert {item["telegramUserId"] for item in first.json()["items"]}.isdisjoint(
        {item["telegramUserId"] for item in resumed.json()["items"]}
    )
