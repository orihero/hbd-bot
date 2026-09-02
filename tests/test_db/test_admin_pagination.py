"""Keyset pagination: the cursor round trip, the untrusted boundary, and termination.

Two things are being proved here, and they are different.

*The primitives are total.* :func:`hbd.db.admin.page.decode_cursor` takes a string a browser
sent and must never raise — every malformed shape becomes a typed ``Err``, because a 500 on
a hand-edited query parameter is a denial of service anybody can trigger.

*The walk terminates and loses nothing.* Paging a fixed table with a small limit must visit
every row exactly once and end with ``next_cursor is None``. That is asserted against real
rows rather than against a mock, including the case the tie-break exists for: several rows
sharing one ``created_at``.

The seed helpers come from ``test_admin_queries`` rather than being copied: two definitions
of "an order row" is how two test modules end up disagreeing about what the fixture means.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import OrderState, is_err, is_ok
from hbd.db.admin import orders
from hbd.db.admin.page import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    TOTAL_COUNT_CAP,
    Cursor,
    Page,
    PageRequest,
    build_page,
    decode_cursor,
    encode_cursor,
    page_request,
)
from hbd.db.admin.views import OrderListItem
from tests.test_db.test_admin_queries import seed_order, seed_user

_AT: Final[datetime] = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)
_ID: Final[UUID] = UUID("11111111-2222-3333-4444-555555555555")


def _token(payload: object) -> str:
    """Encode an arbitrary payload the way a cursor is encoded, to forge a bad one."""
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# The cursor round trip
# ---------------------------------------------------------------------------
def test_a_cursor_round_trips_through_encode_and_decode() -> None:
    # Arrange
    cursor = Cursor(at=_AT, id=_ID)

    # Act
    decoded = decode_cursor(encode_cursor(cursor))

    # Assert
    assert is_ok(decoded)
    assert decoded.value == cursor


def test_the_encoded_cursor_is_opaque() -> None:
    """It carries no readable field names or values a client could be tempted to build."""
    # Act
    token = encode_cursor(Cursor(at=_AT, id=_ID))

    # Assert
    assert "2026" not in token
    assert str(_ID) not in token


def test_a_cursor_rejects_a_naive_timestamp_at_construction() -> None:
    # Act
    try:
        Cursor(at=datetime(2026, 3, 21, 9, 0), id=_ID)
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - the constructor must reject this
        message = ""

    # Assert
    assert "timezone-aware" in message


# ---------------------------------------------------------------------------
# The untrusted boundary — every failure is a value, never an exception
# ---------------------------------------------------------------------------
def test_decode_rejects_a_token_that_is_not_base64() -> None:
    # Act
    decoded = decode_cursor("!!!! not base64 !!!!")

    # Assert
    assert is_err(decoded)


def test_decode_rejects_a_token_that_is_not_utf8() -> None:
    # Act
    decoded = decode_cursor(base64.urlsafe_b64encode(b"\xff\xfe\xfd").decode("ascii"))

    # Assert
    assert is_err(decoded)


def test_decode_rejects_a_token_that_is_not_json() -> None:
    # Act
    decoded = decode_cursor(base64.urlsafe_b64encode(b"not json at all").decode("ascii"))

    # Assert
    assert is_err(decoded)


def test_decode_rejects_a_payload_that_is_not_an_object() -> None:
    # Act
    decoded = decode_cursor(_token([1, 2, 3]))

    # Assert
    assert is_err(decoded)


def test_decode_rejects_a_payload_missing_its_position_fields() -> None:
    # Act
    decoded = decode_cursor(_token({"at": _AT.isoformat()}))

    # Assert
    assert is_err(decoded)


def test_decode_rejects_non_string_position_fields() -> None:
    # Act
    decoded = decode_cursor(_token({"at": 1, "id": 2}))

    # Assert
    assert is_err(decoded)


def test_decode_rejects_an_unparseable_uuid() -> None:
    # Act
    decoded = decode_cursor(_token({"at": _AT.isoformat(), "id": "not-a-uuid"}))

    # Assert
    assert is_err(decoded)


def test_decode_rejects_a_naive_timestamp() -> None:
    """``UtcDateTime`` would raise inside the driver, where nothing is waiting to catch it."""
    # Act
    decoded = decode_cursor(_token({"at": "2026-03-21T09:00:00", "id": str(_ID)}))

    # Assert
    assert is_err(decoded)


def test_decode_rejects_an_oversized_token() -> None:
    # Act
    decoded = decode_cursor("A" * 5_000)

    # Assert
    assert is_err(decoded)


def test_a_rejected_cursor_never_echoes_the_attacker_supplied_value() -> None:
    """The value would otherwise land in a log line and an error body verbatim."""
    # Arrange
    hostile = _token({"at": "<script>alert(1)</script>", "id": str(_ID)})

    # Act
    decoded = decode_cursor(hostile)

    # Assert
    assert is_err(decoded)
    assert "script" not in str(decoded.error.context)
    assert "script" not in str(decoded.error)


# ---------------------------------------------------------------------------
# The page request
# ---------------------------------------------------------------------------
def test_page_request_defaults_to_fifty_with_no_cursor() -> None:
    # Act
    request = page_request()

    # Assert
    assert is_ok(request)
    assert request.value == PageRequest(limit=DEFAULT_PAGE_LIMIT, cursor=None)


def test_page_request_rejects_a_limit_above_the_ceiling() -> None:
    # Act
    request = page_request(limit=MAX_PAGE_LIMIT + 1)

    # Assert — rejected rather than clamped, so a client bug surfaces now.
    assert is_err(request)


def test_page_request_rejects_a_limit_below_one() -> None:
    # Act
    request = page_request(limit=0)

    # Assert
    assert is_err(request)


def test_page_request_propagates_a_bad_cursor() -> None:
    # Act
    request = page_request(limit=10, cursor="!!!!")

    # Assert
    assert is_err(request)


def test_page_request_carries_a_good_cursor_through() -> None:
    # Arrange
    cursor = Cursor(at=_AT, id=_ID)

    # Act
    request = page_request(limit=10, cursor=encode_cursor(cursor))

    # Assert
    assert is_ok(request)
    assert request.value.cursor == cursor
    assert request.value.fetch_limit == 11


def test_the_page_request_dataclass_refuses_an_out_of_range_limit() -> None:
    """Belt and braces: the validated constructor is not the only way in."""
    # Act
    try:
        PageRequest(limit=MAX_PAGE_LIMIT + 1)
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - the constructor must reject this
        message = ""

    # Assert
    assert str(MAX_PAGE_LIMIT) in message


# ---------------------------------------------------------------------------
# build_page — the probe row and termination
# ---------------------------------------------------------------------------
def _item(at: datetime, item_id: UUID) -> OrderListItem:
    return OrderListItem(
        id=item_id,
        telegram_user_id=1,
        state=OrderState.DELIVERED,
        is_paid=True,
        correlation_id="c",
        created_at=at,
        updated_at=at,
        delivered_at=None,
        failed_reason=None,
        is_brief_present=False,
        recipient_name_display=None,
        identity_purged_at=None,
        note_purged_at=None,
        occasion=None,
        genre=None,
        output_language=None,
        asset_count=0,
    )


def test_build_page_returns_no_cursor_when_the_probe_row_is_absent() -> None:
    # Arrange — two rows for a limit of two means there is no third.
    rows = [_item(_AT, uuid4()), _item(_AT, uuid4())]

    # Act
    page = build_page(
        rows, PageRequest(limit=2), lambda item: Cursor(at=item.created_at, id=item.id)
    )

    # Assert
    assert page == Page(items=tuple(rows), next_cursor=None)
    assert page.has_more is False


def test_build_page_drops_the_probe_row_and_emits_a_cursor_from_the_last_kept_one() -> None:
    # Arrange
    kept_last = _item(_AT - timedelta(minutes=1), uuid4())
    probe = _item(_AT - timedelta(minutes=2), uuid4())
    rows = [_item(_AT, uuid4()), kept_last, probe]

    # Act
    page = build_page(
        rows, PageRequest(limit=2), lambda item: Cursor(at=item.created_at, id=item.id)
    )

    # Assert — the probe never reaches the caller, and the cursor points at the last kept row.
    assert len(page.items) == 2
    assert probe not in page.items
    assert page.next_cursor is not None
    resumed = decode_cursor(page.next_cursor)
    assert is_ok(resumed)
    assert resumed.value == Cursor(at=kept_last.created_at, id=kept_last.id)


# ---------------------------------------------------------------------------
# The walk, against real rows
# ---------------------------------------------------------------------------
async def _walk(
    sessions: async_sessionmaker[AsyncSession], *, limit: int
) -> tuple[list[UUID], int]:
    """Page all the way through ``/orders`` and report what was seen and how many pages."""
    seen: list[UUID] = []
    cursor: str | None = None
    pages = 0
    while True:
        request = page_request(limit=limit, cursor=cursor)
        assert is_ok(request)
        async with sessions.begin() as session:
            page = await orders.list_orders(
                session, filters=orders.OrderFilters(), request=request.value
            )
        seen.extend(item.id for item in page.items)
        pages += 1
        cursor = page.next_cursor
        if cursor is None:
            return seen, pages


async def test_the_keyset_walk_visits_every_row_once_and_terminates(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — five orders, one minute apart, newest last.
    base = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=base)
        expected = [
            (await seed_order(session, user=user, created_at=base + timedelta(minutes=index))).id
            for index in range(5)
        ]

    # Act
    seen, pages = await _walk(sessions, limit=2)

    # Assert — newest first, every id exactly once, three pages, ending on a null cursor.
    assert seen == list(reversed(expected))
    assert len(set(seen)) == 5
    assert pages == 3


async def test_the_tie_break_reaches_rows_that_share_one_timestamp(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``created_at`` alone is not unique; without the id tie-break a row goes missing."""
    # Arrange — four orders at the identical instant, paged one at a time.
    base = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=base)
        expected = {(await seed_order(session, user=user, created_at=base)).id for _ in range(4)}

    # Act
    seen, pages = await _walk(sessions, limit=1)

    # Assert
    assert set(seen) == expected
    assert len(seen) == 4
    # Four pages, not five: the fourth returns the last row with no probe behind it, so
    # it already carries the null cursor. The walk never fetches an empty page to stop.
    assert pages == 4


async def test_an_empty_table_pages_once_and_stops(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    seen, pages = await _walk(sessions, limit=50)

    # Assert
    assert (seen, pages) == ([], 1)


async def test_a_bounded_total_is_exact_well_below_the_cap(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    base = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=base)
        for index in range(4):
            await seed_order(session, user=user, created_at=base + timedelta(minutes=index))

    # Act
    async with sessions.begin() as session:
        total = await orders.count_orders(session, filters=orders.OrderFilters())

    # Assert
    assert total.total == 4
    assert total.is_exact is True
    assert total.total < TOTAL_COUNT_CAP
