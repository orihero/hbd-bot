"""Keyset pagination as one property, asserted across every list the panel serves — §6.1.

The per-endpoint tests already in this package each fetch two pages of their own resource.
That catches a broken cursor; it does not catch the failure this file is about, which is a
**page boundary that drops or repeats a row**. A keyset predicate written as
``created_at < :at`` instead of ``at < :at OR (at = :at AND id < :id)`` passes a two-page
test on rows with distinct timestamps and silently loses every row that shares a timestamp
with the last one of a page — the rows a bulk insert, a backfill or a burst of renders
produces, which is exactly when an operator is looking.

So the world seeded here gives the five attempts and the five assets **one identical
``created_at``**, and the assertion is not "page two differs from page one" but "walking the
whole list two rows at a time reproduces the single-page result exactly, in order, with no
duplicate". That can only hold if ``(created_at, id)`` is a total order.

``/api/audit`` is the eighth list and is **excluded from the parameterised sweep on
purpose**: it pages on ``seq``, the monotonic key the hash chain already depends on, with
its own ``AuditPageMeta`` (``schemas/audit.py``). §14's bullet says "keyset pagination"
without naming endpoints, so it gets its own test rather than being forced into an envelope
that means something different for it.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest

from bayram.admin.container import AdminContainer
from bayram.admin.routers.assets import ASSETS_PATH
from bayram.admin.routers.audit import AUDIT_PATH
from bayram.admin.routers.generations import GENERATIONS_PATH
from bayram.admin.routers.orders import ORDER_ASSETS_PATH, ORDER_ATTEMPTS_PATH, ORDERS_PATH
from bayram.admin.routers.users import USER_ORDERS_PATH, USERS_PATH
from bayram.contracts import is_err, is_ok
from bayram.db.admin.page import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MIN_PAGE_LIMIT,
    Cursor,
    decode_cursor,
    encode_cursor,
    page_request,
)
from bayram.db.enums import AdminRole
from tests.test_admin.conftest import NOW, PASSWORD, create_account, sign_in
from tests.test_admin.test_audit_router import seed as seed_audit_entries
from tests.test_admin.test_orders_router import (
    seed_asset,
    seed_attempt,
    seed_brief,
    seed_order,
    seed_user,
)

#: The customer every keyset endpoint is walked through.
HUB_TELEGRAM_ID: Final[int] = 880_000_100
#: How many rows each list holds at minimum, and the page size the walk uses. Five over two
#: is three pages: a first, a middle and a short last one, which is the shape that catches a
#: cursor that is only ever built from the first page.
SEEDED_ROWS: Final[int] = 5
PAGE: Final[int] = 2
#: A ceiling on the walk. A cursor that never terminates is the bug; hanging the suite is
#: not how it should report itself.
MAX_PAGES: Final[int] = 20

#: The seven lists that page on ``(created_at, id)``. Formatted with the seeded world's
#: identifiers, so adding an endpoint here is one line.
KEYSET_LISTS: Final[tuple[str, ...]] = (
    ORDERS_PATH,
    ORDER_ATTEMPTS_PATH,
    ORDER_ASSETS_PATH,
    USERS_PATH,
    USER_ORDERS_PATH,
    GENERATIONS_PATH,
    ASSETS_PATH,
)

#: Cursors that did not come from this API. Every one must be a 422 in the error envelope —
#: never a 500, and never a page. ``page.py``'s docstring calls this a never-throw boundary.
FORGED_CURSORS: Final[tuple[tuple[str, str], ...]] = (
    ("not-base64", "!!!not base64 at all!!!"),
    ("not-json", base64.urlsafe_b64encode(b"\xff\xfe not utf-8").decode("ascii")),
    ("not-an-object", base64.urlsafe_b64encode(b"[]").decode("ascii")),
    (
        "naive-timestamp",
        base64.urlsafe_b64encode(
            json.dumps({"at": "2026-01-01T00:00:00", "id": str(uuid4())}).encode()
        ).decode("ascii"),
    ),
    (
        "missing-id",
        base64.urlsafe_b64encode(json.dumps({"at": "2026-01-01T00:00:00Z"}).encode()).decode(
            "ascii"
        ),
    ),
    (
        "id-is-not-a-uuid",
        base64.urlsafe_b64encode(
            json.dumps({"at": "2026-01-01T00:00:00Z", "id": "the-third-one"}).encode()
        ).decode("ascii"),
    ),
    (
        "an-extra-field",
        base64.urlsafe_b64encode(
            json.dumps({"at": "2026-01-01T00:00:00Z", "id": str(uuid4()), "role": "owner"}).encode()
        ).decode("ascii"),
    ),
    ("too-long", "A" * 300),
)


async def signed_in(container: AdminContainer, client: httpx.AsyncClient) -> None:
    """OWNER, because this file is about paging rather than about who may page."""
    await create_account(container, role=AdminRole.OWNER)
    response = await sign_in(client, password=PASSWORD)
    assert response.status_code == 200


async def seed_world(container: AdminContainer) -> dict[str, object]:
    """Five rows reachable from every keyset list, with the ties the tie-break exists for.

    The five attempts and the five assets all carry ``NOW`` as their ``created_at``. That is
    not a shortcut: it is the case a ``created_at``-only predicate gets wrong, and it is why
    the walk below can prove the predicate is a total order rather than merely a filter.
    """
    async with container.session_factory.begin() as db:
        hub = await seed_user(db, telegram_user_id=HUB_TELEGRAM_ID)
        first: Any = None
        for index in range(SEEDED_ROWS):
            order = await seed_order(
                db,
                user=hub,
                correlation_id=f"corr-hub-{index}",
                created_at=NOW - timedelta(hours=index),
            )
            await seed_brief(db, order=order)
            first = first or order
        for index in range(SEEDED_ROWS):
            await seed_attempt(db, order=first, sequence=index, created_at=NOW)
            await seed_asset(db, order=first, variant_index=index, created_at=NOW)
        # Four more customers, so ``/users`` has five rows of its own without giving the hub
        # more orders than ``/users/{tg}/orders`` is supposed to page through.
        for index in range(1, SEEDED_ROWS):
            other = await seed_user(db, telegram_user_id=HUB_TELEGRAM_ID + index)
            await seed_order(
                db,
                user=other,
                correlation_id=f"corr-other-{index}",
                created_at=NOW - timedelta(days=index),
            )
        return {"order_id": first.id, "telegram_user_id": HUB_TELEGRAM_ID}


async def fetch(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await client.get(path, params=params)
    assert response.status_code == 200, (path, params, response.text)
    body: dict[str, Any] = response.json()
    return body


async def walk(client: httpx.AsyncClient, path: str, *, limit: int) -> tuple[list[str], int]:
    """Follow the cursors to the end. Returns the ids in the order they arrived, and the
    number of pages it took."""
    ids: list[str] = []
    cursor: str | None = None
    for page in range(1, MAX_PAGES + 1):
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        body = await fetch(client, path, **params)
        ids.extend(str(item["id"]) for item in body["items"])
        meta = body["meta"]
        # ``nextCursor`` is the one termination signal, and it is a key that is always there.
        assert "nextCursor" in meta, path
        cursor = meta["nextCursor"]
        if cursor is None:
            return ids, page
        assert isinstance(cursor, str) and cursor, path
    raise AssertionError(f"{path} never terminated within {MAX_PAGES} pages")


# ---------------------------------------------------------------------------
# The round trip, over every list that shares the envelope
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("template", KEYSET_LISTS, ids=str)
async def test_walking_the_cursors_reproduces_the_single_page_exactly(
    container: AdminContainer, client: httpx.AsyncClient, template: str
) -> None:
    # Arrange
    world = await seed_world(container)
    await signed_in(container, client)
    path = template.format(**world)

    # Act — the whole list in one request, and the same list two rows at a time.
    whole = [str(item["id"]) for item in (await fetch(client, path, limit=MAX_PAGE_LIMIT))["items"]]
    walked, pages = await walk(client, path, limit=PAGE)

    # Assert — same rows, same order, no repeat, no gap. Order equality is the assertion
    # that a shared ``created_at`` did not make one row unreachable and another duplicate.
    assert len(whole) >= SEEDED_ROWS, path
    assert walked == whole, path
    assert len(set(walked)) == len(walked), path
    assert pages > 1, f"{path} fitted in one page; the walk asserted nothing"


@pytest.mark.parametrize("template", KEYSET_LISTS, ids=str)
async def test_the_last_page_terminates_with_a_null_cursor_rather_than_an_empty_string(
    container: AdminContainer, client: httpx.AsyncClient, template: str
) -> None:
    # Arrange — nothing else means "the end", so a client's loop terminates on one
    # condition. ``""`` would be falsy in JavaScript and truthy in a Python ``is not None``.
    world = await seed_world(container)
    await signed_in(container, client)
    path = template.format(**world)

    # Act
    meta = (await fetch(client, path, limit=MAX_PAGE_LIMIT))["meta"]

    # Assert
    assert "nextCursor" in meta
    assert meta["nextCursor"] is None


@pytest.mark.parametrize("template", KEYSET_LISTS, ids=str)
async def test_a_full_page_hands_back_a_cursor_and_the_next_page_does_not_repeat_it(
    container: AdminContainer, client: httpx.AsyncClient, template: str
) -> None:
    # Arrange — the two-page shape §14's bullet names, asserted per endpoint so a failure
    # names the resource rather than the walk.
    world = await seed_world(container)
    await signed_in(container, client)
    path = template.format(**world)

    # Act
    first = await fetch(client, path, limit=PAGE)
    second = await fetch(client, path, limit=PAGE, cursor=first["meta"]["nextCursor"])

    # Assert
    assert len(first["items"]) == PAGE
    assert isinstance(first["meta"]["nextCursor"], str)
    assert not {str(row["id"]) for row in first["items"]} & {
        str(row["id"]) for row in second["items"]
    }


@pytest.mark.parametrize("template", KEYSET_LISTS, ids=str)
async def test_the_total_and_its_exactness_travel_together_or_not_at_all(
    container: AdminContainer, client: httpx.AsyncClient, template: str
) -> None:
    # Arrange — ``total`` alone would be read as a measurement when it is a ceiling.
    world = await seed_world(container)
    await signed_in(container, client)
    path = template.format(**world)

    # Act
    without = (await fetch(client, path, limit=PAGE))["meta"]
    counted = (await fetch(client, path, limit=PAGE, withTotal="true"))["meta"]

    # Assert
    assert without["total"] is None
    assert without["isTotalExact"] is None
    assert counted["total"] >= SEEDED_ROWS
    assert counted["isTotalExact"] is True


# ---------------------------------------------------------------------------
# The two query parameters, at the boundary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("limit", [0, -1, MAX_PAGE_LIMIT + 1, 5_000])
@pytest.mark.parametrize("template", KEYSET_LISTS, ids=str)
async def test_a_limit_outside_the_bounds_is_refused_rather_than_clamped(
    container: AdminContainer, client: httpx.AsyncClient, template: str, limit: int
) -> None:
    # Arrange — clamping would hide the client bug that will surface later as a timeout.
    world = await seed_world(container)
    await signed_in(container, client)

    # Act
    response = await client.get(template.format(**world), params={"limit": limit})

    # Assert
    assert response.status_code == 422


@pytest.mark.parametrize("limit", [MIN_PAGE_LIMIT, MAX_PAGE_LIMIT])
@pytest.mark.parametrize("template", KEYSET_LISTS, ids=str)
async def test_the_bounds_themselves_are_accepted(
    container: AdminContainer, client: httpx.AsyncClient, template: str, limit: int
) -> None:
    # Arrange — the companion to the test above: an off-by-one in the validator would
    # otherwise show up as a refusal nobody notices until a page of 200 is needed.
    world = await seed_world(container)
    await signed_in(container, client)

    # Act
    response = await client.get(template.format(**world), params={"limit": limit})

    # Assert
    assert response.status_code == 200


@pytest.mark.parametrize("template", KEYSET_LISTS, ids=str)
async def test_a_request_with_no_limit_returns_at_most_the_default_page(
    container: AdminContainer, client: httpx.AsyncClient, template: str
) -> None:
    # Arrange — standing rule 12: every list query is bounded, with or without a parameter.
    world = await seed_world(container)
    await signed_in(container, client)

    # Act
    body = await fetch(client, template.format(**world))

    # Assert
    assert len(body["items"]) <= DEFAULT_PAGE_LIMIT


@pytest.mark.parametrize(
    ("label", "cursor"), FORGED_CURSORS, ids=[name for name, _ in FORGED_CURSORS]
)
@pytest.mark.parametrize("template", [ORDERS_PATH, USERS_PATH, GENERATIONS_PATH], ids=str)
async def test_a_cursor_this_api_did_not_issue_is_a_422_in_the_envelope(
    container: AdminContainer,
    client: httpx.AsyncClient,
    template: str,
    label: str,
    cursor: str,
) -> None:
    # Arrange — the cursor arrives as a query string from a browser, so it is parsed at a
    # never-throw boundary. A 500 here is the failure mode; so is a page.
    world = await seed_world(container)
    await signed_in(container, client)

    # Act
    response = await client.get(template.format(**world), params={"cursor": cursor})

    # Assert
    assert response.status_code == 422, (template, label)
    assert response.json()["error"]["code"] == "INVALID_INPUT", (template, label)


async def test_a_cursor_is_a_position_rather_than_a_capability(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``/orders`` and ``/users`` both page on ``(created_at, id)``, so a cursor
    # from one is structurally valid at the other. It must simply resume the users list:
    # nothing about a cursor authorises anything, and no order may come back through it
    # (§12.1 T3 — an id is never treated as a capability).
    await seed_world(container)
    await signed_in(container, client)
    borrowed = (await fetch(client, ORDERS_PATH, limit=PAGE))["meta"]["nextCursor"]
    everyone = {
        str(row["id"]) for row in (await fetch(client, USERS_PATH, limit=MAX_PAGE_LIMIT))["items"]
    }

    # Act
    body = await fetch(client, USERS_PATH, limit=MAX_PAGE_LIMIT, cursor=borrowed)

    # Assert — users, or none, but never somebody else's resource.
    assert {str(row["id"]) for row in body["items"]} <= everyone
    assert all("telegramUserId" in row for row in body["items"])


# ---------------------------------------------------------------------------
# The audit log, which pages on ``seq`` and says so
# ---------------------------------------------------------------------------
async def test_the_audit_log_pages_on_its_own_key_and_terminates_the_same_way(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a different cursor shape and a different envelope, but the same contract at
    # the end of the list: ``nextCursor`` is ``null`` and nothing else means "the end".
    await seed_audit_entries(container, SEEDED_ROWS)
    await signed_in(container, client)

    # Act
    first = await fetch(client, AUDIT_PATH, limit=PAGE)
    second = await fetch(client, AUDIT_PATH, limit=PAGE, cursor=first["meta"]["nextCursor"])
    rest = await fetch(client, AUDIT_PATH, limit=MAX_PAGE_LIMIT)

    # Assert
    assert len(first["items"]) == PAGE
    assert isinstance(first["meta"]["nextCursor"], str)
    assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}
    assert rest["meta"]["nextCursor"] is None


# ---------------------------------------------------------------------------
# The codec, without HTTP
# ---------------------------------------------------------------------------
def test_a_cursor_survives_a_round_trip_through_its_own_encoding() -> None:
    # Arrange
    cursor = Cursor(at=NOW, id=uuid4())

    # Act
    decoded = decode_cursor(encode_cursor(cursor))

    # Assert
    assert is_ok(decoded)
    assert decoded.value == cursor


def test_a_naive_position_cannot_be_constructed_at_all() -> None:
    # Arrange / Act / Assert — ``UtcDateTime`` would raise inside the driver, where no
    # handler is looking, so the refusal is moved to the point the value is built.
    with pytest.raises(ValueError, match="timezone-aware"):
        Cursor(at=datetime(2026, 3, 21, 9, 0, 0), id=uuid4())


def test_the_encoded_form_is_opaque_but_not_a_secret() -> None:
    # Arrange — base64url of a two-field JSON object: no padding to break a query string,
    # and nothing in it a caller could not have derived from the page it came from.
    cursor = Cursor(at=NOW, id=UUID("3f2b9c1e-0a5d-4f61-9c2a-7b18d4e6f0a3"))

    # Act
    encoded = encode_cursor(cursor)

    # Assert
    assert set(json.loads(base64.urlsafe_b64decode(encoded + "=="))) == {"at", "id"}
    assert "/" not in encoded and "+" not in encoded


@pytest.mark.parametrize("limit", [0, -1, MAX_PAGE_LIMIT + 1])
def test_the_page_request_refuses_an_impossible_limit_below_http_too(limit: int) -> None:
    # Arrange / Act — the bounds are declared twice on purpose: once by FastAPI for the
    # 422 that names the parameter, and once here for every caller that never sees HTTP.
    result = page_request(limit=limit)

    # Assert
    assert is_err(result)


@pytest.mark.parametrize(
    ("label", "cursor"), FORGED_CURSORS, ids=[name for name, _ in FORGED_CURSORS]
)
def test_every_forged_cursor_is_an_err_rather_than_an_exception(label: str, cursor: str) -> None:
    # Arrange / Act — the same corpus the HTTP tests send, at the layer that parses it.
    result = decode_cursor(cursor)

    # Assert
    assert is_err(result), label
