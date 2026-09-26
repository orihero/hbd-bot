"""The broadcast read layer: one row per CAMPAIGN, and one ledger paged inside one campaign.

Four things go wrong in a read layer over a parent table and a forty-thousand-row child, and
none of them raises anything:

* **A campaign list that is really a recipient list.** A join to ``broadcast_bodies`` or to
  ``broadcast_recipients`` multiplies the parent's rows, and a keyset ``LIMIT`` over
  multiplied rows silently drops campaigns off the end of the page. The fixture below gives
  one campaign two bodies and several recipients precisely so a page of it must still be one
  row long.
* **A ledger read across campaigns.** ``broadcast_id`` narrows the largest table in the
  schema, so a filter that forgot it would page somebody else's send onto this campaign's
  screen — asserted with two campaigns whose rows are interleaved in time.
* **A progress bar computed from the wrong source.** ``broadcasts`` carries six counters the
  worker's rollup writes and ``broadcast_recipients`` carries the truth. The detail must
  recount the rows, so the two are seeded to DISAGREE here: a stale rollup is the one state
  where a bar drawn from the parent row lies to an operator watching a send.
* **A state that vanishes from the bar.** Every :class:`~bayram.contracts.BroadcastRecipientState`
  is seeded once and the total is compared against ``len(...)``, so adding a member to the
  enum without teaching :class:`~bayram.db.admin.views.BroadcastProgress` about it fails here
  rather than rounding a possibly-delivered message away in production.

Rows are written through the ORM with every clock stated, following ``test_admin_queries.py``
and ``test_audience_lists.py``. Nothing here goes through a repository: the counters, the
frozen audience size and the timestamps are the fixture, and they are only meaningful if they
are exactly what the test says rather than whatever a writer's clock chose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import (
    BroadcastKind,
    BroadcastRecipientState,
    BroadcastState,
    Language,
    is_ok,
)
from bayram.db.admin import broadcasts
from bayram.db.admin.page import PageRequest, page_request
from bayram.db.admin.sql import TimeWindow
from bayram.db.enums import AuditReasonCode
from bayram.db.models.broadcast import BroadcastRow
from bayram.db.models.broadcast_body import BroadcastBodyRow
from bayram.db.models.broadcast_recipient import BroadcastRecipientRow

_DAY_ONE: Final[datetime] = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
_DAY_TWO: Final[datetime] = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
_DAY_THREE: Final[datetime] = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
#: The document a campaign was composed against, stored verbatim on the row. Its shape is
#: ``bayram.admin.schemas.segment``'s business; this layer only has to hand it back unchanged.
_SEGMENT: Final[dict[str, Any]] = {
    "root": {"match": "all", "rules": [{"field": "is_reachable", "op": "is_true"}]},
    "sort": {"key": "joined_at", "direction": "desc"},
}


async def seed_broadcast(session: AsyncSession, *, created_at: datetime, **kw: Any) -> BroadcastRow:
    """One campaign. Every counter is stated, so a test that asserts one cannot be lucky."""
    row = BroadcastRow(
        id=uuid4(),
        title=kw.pop("title", "September outage notice"),
        kind=kw.pop("kind", BroadcastKind.SERVICE),
        state=kw.pop("state", BroadcastState.DRAFT),
        segment=kw.pop("segment", _SEGMENT),
        segment_hash=kw.pop("segment_hash", "a" * 64),
        audience_size=kw.pop("audience_size", 0),
        audience_evaluated_at=kw.pop("audience_evaluated_at", created_at),
        expand_cursor=kw.pop("expand_cursor", None),
        scheduled_for=kw.pop("scheduled_for", None),
        started_at=kw.pop("started_at", None),
        finished_at=kw.pop("finished_at", None),
        recipient_count=kw.pop("recipient_count", 0),
        sent_count=kw.pop("sent_count", 0),
        failed_count=kw.pop("failed_count", 0),
        skipped_count=kw.pop("skipped_count", 0),
        undeliverable_count=kw.pop("undeliverable_count", 0),
        unknown_count=kw.pop("unknown_count", 0),
        created_by_admin_id=kw.pop("created_by_admin_id", None),
        created_by_username=kw.pop("created_by_username", None),
        scheduled_by_admin_id=kw.pop("scheduled_by_admin_id", None),
        scheduled_by_username=kw.pop("scheduled_by_username", None),
        reason_code=kw.pop("reason_code", None),
        reason_ref=kw.pop("reason_ref", None),
        error_code=kw.pop("error_code", None),
        created_at=created_at,
        updated_at=kw.pop("updated_at", created_at),
    )
    session.add(row)
    await session.flush()
    return row


async def seed_body(
    session: AsyncSession, *, broadcast: BroadcastRow, **kw: Any
) -> BroadcastBodyRow:
    """One language's message for one campaign."""
    row = BroadcastBodyRow(
        id=uuid4(),
        broadcast_id=broadcast.id,
        language=kw.pop("language", Language.UZ_LATN),
        text=kw.pop("text", "Bugun kechqurun tizim yangilanadi."),
        media_storage_key=kw.pop("media_storage_key", None),
        media_file_id=kw.pop("media_file_id", None),
        button_label=kw.pop("button_label", None),
        button_url=kw.pop("button_url", None),
        created_at=broadcast.created_at,
        updated_at=broadcast.created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_recipient(
    session: AsyncSession, *, broadcast: BroadcastRow, **kw: Any
) -> BroadcastRecipientRow:
    """One account's place in one campaign. ``telegram_user_id=None`` is an erased row."""
    created_at = kw.pop("created_at", broadcast.created_at)
    row = BroadcastRecipientRow(
        id=uuid4(),
        broadcast_id=broadcast.id,
        telegram_user_id=kw.pop("telegram_user_id", 5_000_001),
        language=kw.pop("language", Language.UZ_LATN),
        state=kw.pop("state", BroadcastRecipientState.PENDING),
        attempts=kw.pop("attempts", 0),
        error_code=kw.pop("error_code", None),
        settled_at=kw.pop("settled_at", None),
        created_at=created_at,
        updated_at=kw.pop("updated_at", created_at),
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# THE trap: the campaign list is one row per campaign
# ---------------------------------------------------------------------------
async def test_a_campaign_with_many_bodies_and_recipients_is_still_one_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The mistake this module exists to make impossible.

    A join to either child would return two bodies × four recipients = eight rows for one
    campaign, and a ``LIMIT`` over those is a page that drops whatever came after them.
    """
    # Arrange — one campaign, two language bodies, four recipient rows.
    async with sessions.begin() as session:
        campaign = await seed_broadcast(session, created_at=_DAY_ONE)
        await seed_body(session, broadcast=campaign, language=Language.UZ_LATN)
        await seed_body(session, broadcast=campaign, language=Language.RU)
        for index in range(4):
            await seed_recipient(session, broadcast=campaign, telegram_user_id=5_000_100 + index)

    # Act
    async with sessions.begin() as session:
        page = await broadcasts.list_broadcasts(
            session, filters=broadcasts.BroadcastFilters(), request=PageRequest(limit=10)
        )
        total = await broadcasts.count_broadcasts(session, filters=broadcasts.BroadcastFilters())

    # Assert — one row, and the children are counted rather than multiplied into it.
    assert [item.id for item in page.items] == [campaign.id]
    assert page.items[0].body_count == 2
    assert (total.total, total.is_exact) == (1, True)


async def test_the_campaign_list_publishes_the_rows_own_counters_and_the_frozen_audience(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``audience_size`` and ``recipient_count`` are two numbers, and the gap is the point.

    A half-expanded campaign is a state the list has to render as arithmetic — 40 counted at
    creation, 25 rows written — because "why did fewer people get this" has no other answer.
    """
    # Arrange
    async with sessions.begin() as session:
        campaign = await seed_broadcast(
            session,
            created_at=_DAY_ONE,
            state=BroadcastState.EXPANDING,
            kind=BroadcastKind.MARKETING,
            audience_size=40,
            audience_evaluated_at=_DAY_ONE,
            recipient_count=25,
            sent_count=20,
            failed_count=3,
            skipped_count=1,
            undeliverable_count=1,
            unknown_count=0,
            created_by_username="operator",
            reason_code=AuditReasonCode.ROUTINE_OPS,
            reason_ref="OPS-4120",
        )

    # Act
    async with sessions.begin() as session:
        page = await broadcasts.list_broadcasts(
            session, filters=broadcasts.BroadcastFilters(), request=PageRequest(limit=10)
        )

    # Assert
    item = page.items[0]
    assert (item.id, item.state, item.kind) == (
        campaign.id,
        BroadcastState.EXPANDING,
        BroadcastKind.MARKETING,
    )
    assert (item.audience_size, item.recipient_count) == (40, 25)
    assert item.audience_evaluated_at == _DAY_ONE
    assert (item.sent_count, item.failed_count) == (20, 3)
    assert (item.skipped_count, item.undeliverable_count, item.unknown_count) == (1, 1, 0)
    assert (item.reason_code, item.reason_ref) == (AuditReasonCode.ROUTINE_OPS, "OPS-4120")
    assert item.created_by_username == "operator"
    assert item.body_count == 0


async def test_campaign_filters_are_and_across_fields_and_or_within_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three campaigns that differ in exactly one dimension each.
    async with sessions.begin() as session:
        drafted = await seed_broadcast(
            session, created_at=_DAY_ONE, state=BroadcastState.DRAFT, title="Draft one"
        )
        sending = await seed_broadcast(
            session, created_at=_DAY_TWO, state=BroadcastState.SENDING, title="Outage notice"
        )
        promoted = await seed_broadcast(
            session,
            created_at=_DAY_THREE,
            state=BroadcastState.COMPLETED,
            kind=BroadcastKind.MARKETING,
            title="Autumn sale",
        )

    # Act
    async with sessions.begin() as session:
        by_states = await broadcasts.list_broadcasts(
            session,
            filters=broadcasts.BroadcastFilters(
                states=(BroadcastState.DRAFT, BroadcastState.SENDING)
            ),
            request=PageRequest(limit=10),
        )
        by_kind = await broadcasts.list_broadcasts(
            session,
            filters=broadcasts.BroadcastFilters(kinds=(BroadcastKind.MARKETING,)),
            request=PageRequest(limit=10),
        )
        windowed = await broadcasts.list_broadcasts(
            session,
            filters=broadcasts.BroadcastFilters(
                window=TimeWindow(start=_DAY_TWO, end=_DAY_TWO + timedelta(days=1))
            ),
            request=PageRequest(limit=10),
        )
        # AND across fields: the marketing campaign is outside the DRAFT/SENDING set.
        crossed = await broadcasts.list_broadcasts(
            session,
            filters=broadcasts.BroadcastFilters(
                states=(BroadcastState.DRAFT, BroadcastState.SENDING),
                kinds=(BroadcastKind.MARKETING,),
            ),
            request=PageRequest(limit=10),
        )

    # Assert — OR within a field, AND across them.
    assert {item.id for item in by_states.items} == {drafted.id, sending.id}
    assert [item.id for item in by_kind.items] == [promoted.id]
    assert [item.id for item in windowed.items] == [sending.id]
    assert crossed.items == ()


async def test_the_campaign_search_matches_the_title_and_narrows_the_total_with_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``?q=`` must narrow the page and the count identically, or the total labels a lie.

    The metacharacter case is asserted in the same test because it is the same predicate:
    ``100%`` is a title an operator will write, and an unescaped ``%`` matches everything.
    """
    # Arrange
    async with sessions.begin() as session:
        sale = await seed_broadcast(session, created_at=_DAY_ONE, title="Autumn sale")
        await seed_broadcast(session, created_at=_DAY_TWO, title="Outage notice")
        literal = await seed_broadcast(session, created_at=_DAY_THREE, title="100% uptime week")

    # Act
    async with sessions.begin() as session:
        matched = await broadcasts.list_broadcasts(
            session,
            filters=broadcasts.BroadcastFilters(search="sale"),
            request=PageRequest(limit=10),
        )
        counted = await broadcasts.count_broadcasts(
            session, filters=broadcasts.BroadcastFilters(search="sale")
        )
        escaped = await broadcasts.list_broadcasts(
            session,
            filters=broadcasts.BroadcastFilters(search="100%"),
            request=PageRequest(limit=10),
        )
        blank = await broadcasts.list_broadcasts(
            session,
            filters=broadcasts.BroadcastFilters(search="   "),
            request=PageRequest(limit=10),
        )

    # Assert
    assert [item.id for item in matched.items] == [sale.id]
    assert (counted.total, counted.is_exact) == (1, True)
    assert [item.id for item in escaped.items] == [literal.id]
    # Blank means NO FILTER, never an empty page.
    assert len(blank.items) == 3


async def test_the_campaign_walk_visits_every_row_once_newest_first(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — five campaigns, a minute apart, oldest first.
    async with sessions.begin() as session:
        expected = [
            (
                await seed_broadcast(
                    session, created_at=_DAY_ONE + timedelta(minutes=index), title=f"Run {index}"
                )
            ).id
            for index in range(5)
        ]

    # Act — page all the way through with a limit of two.
    seen: list[UUID] = []
    cursor: str | None = None
    pages = 0
    while True:
        request = page_request(limit=2, cursor=cursor)
        assert is_ok(request)
        async with sessions.begin() as session:
            page = await broadcasts.list_broadcasts(
                session, filters=broadcasts.BroadcastFilters(), request=request.value
            )
        seen.extend(item.id for item in page.items)
        pages += 1
        cursor = page.next_cursor
        if cursor is None:
            break

    # Assert
    assert seen == list(reversed(expected))
    assert len(set(seen)) == 5
    assert pages == 3


# ---------------------------------------------------------------------------
# The strip: one count per state, the reach, and the last send
# ---------------------------------------------------------------------------
async def test_the_strip_zero_fills_every_campaign_state_and_never_omits_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A state with no campaigns is ``0``, in enum order, always.

    ``BroadcastState`` is a closed vocabulary, so the strip's tiles are decided by the enum
    and never by the data: a tile that appeared from nowhere as the first campaign reached a
    state would re-lay-out the page under the operator's cursor. Comparing the keys against
    ``list(BroadcastState)`` is also what makes adding a member to the enum fail HERE rather
    than silently dropping a state out of the strip in production.
    """
    # Arrange — two of the eight states are occupied; six are not.
    async with sessions.begin() as session:
        await seed_broadcast(session, created_at=_DAY_ONE, state=BroadcastState.DRAFT)
        await seed_broadcast(session, created_at=_DAY_TWO, state=BroadcastState.COMPLETED)
        await seed_broadcast(session, created_at=_DAY_THREE, state=BroadcastState.COMPLETED)

    # Act
    async with sessions.begin() as session:
        stats = await broadcasts.broadcast_stats(session, filters=broadcasts.BroadcastFilters())

    # Assert — every member, in declaration order, and the empty ones are zeroes not absences.
    assert [item.state for item in stats.by_state] == list(BroadcastState)
    counted = {item.state: item.count for item in stats.by_state}
    assert counted[BroadcastState.DRAFT] == 1
    assert counted[BroadcastState.COMPLETED] == 2
    assert counted[BroadcastState.SENDING] == 0
    assert counted[BroadcastState.FAILED] == 0
    # ``total`` is the sum of the segments and is exact — no ``bounded_total`` cap.
    assert stats.total == 3


async def test_the_strip_reports_the_reach_as_two_integers_and_never_as_a_rate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Settled recipients over frozen audience, summed from the campaign rows' own rollup.

    The two campaigns below disagree with each other on purpose: one finished everybody, one
    is halfway and holds rows still ``pending``. Only the five TERMINAL counters are reach —
    a row still moving has not arrived anywhere — and the denominator is ``audience_size``,
    the number a human authorised, rather than ``recipient_count``, which a half-written
    expansion would shrink until the strip flattered itself.
    """
    # Arrange
    async with sessions.begin() as session:
        await seed_broadcast(
            session,
            created_at=_DAY_ONE,
            state=BroadcastState.COMPLETED,
            audience_size=100,
            recipient_count=100,
            sent_count=90,
            failed_count=5,
            skipped_count=3,
            undeliverable_count=1,
            unknown_count=1,
        )
        await seed_broadcast(
            session,
            created_at=_DAY_TWO,
            state=BroadcastState.SENDING,
            audience_size=40,
            recipient_count=40,
            sent_count=10,
            failed_count=0,
            skipped_count=0,
            undeliverable_count=0,
            unknown_count=0,
        )

    # Act
    async with sessions.begin() as session:
        stats = await broadcasts.broadcast_stats(session, filters=broadcasts.BroadcastFilters())

    # Assert — 100 settled on the finished campaign, 10 on the running one; 140 authorised.
    assert stats.settled_recipients == 110
    assert stats.audience_total == 140


async def test_the_strip_narrows_through_the_same_filters_the_list_does(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The strip and the page beneath it must never describe two different populations.

    Both go through ``_filtered``, so a window, a kind and a search narrow them identically —
    asserted against the list's own row count rather than against a literal, because the
    claim is that the two agree and not that either is three.
    """
    # Arrange — three campaigns differing in kind and in when they were composed.
    async with sessions.begin() as session:
        await seed_broadcast(
            session,
            created_at=_DAY_ONE,
            kind=BroadcastKind.MARKETING,
            state=BroadcastState.COMPLETED,
            title="Autumn sale",
            audience_size=10,
            sent_count=10,
        )
        await seed_broadcast(
            session,
            created_at=_DAY_TWO,
            kind=BroadcastKind.SERVICE,
            state=BroadcastState.COMPLETED,
            title="Outage notice",
            audience_size=20,
            sent_count=20,
        )
        await seed_broadcast(
            session,
            created_at=_DAY_THREE,
            kind=BroadcastKind.MARKETING,
            state=BroadcastState.DRAFT,
            title="Winter sale",
            audience_size=30,
            sent_count=0,
        )

    marketing = broadcasts.BroadcastFilters(kinds=(BroadcastKind.MARKETING,))
    windowed = broadcasts.BroadcastFilters(
        window=TimeWindow(start=_DAY_TWO, end=_DAY_THREE + timedelta(days=1))
    )
    searched = broadcasts.BroadcastFilters(search="sale")

    # Act
    async with sessions.begin() as session:
        by_kind = await broadcasts.broadcast_stats(session, filters=marketing)
        by_window = await broadcasts.broadcast_stats(session, filters=windowed)
        by_search = await broadcasts.broadcast_stats(session, filters=searched)
        listed = await broadcasts.list_broadcasts(
            session, filters=marketing, request=PageRequest(limit=10)
        )

    # Assert — the kind filter selects the two sales, and the strip sums only those two.
    assert by_kind.total == len(listed.items) == 2
    assert (by_kind.settled_recipients, by_kind.audience_total) == (10, 40)
    # The window is half-open from day two, so day one's campaign is outside it.
    assert by_window.total == 2
    assert by_window.audience_total == 50
    # ``?q=`` matches the title, and narrows the strip with it.
    assert by_search.total == 2
    assert by_search.audience_total == 40
    # A filtered-to-one-state strip reports zeroes for the rest; that is the honest answer to
    # what was asked, not a strip quietly widened to look fuller.
    drafts = {item.state: item.count for item in by_search.by_state}
    assert (drafts[BroadcastState.DRAFT], drafts[BroadcastState.COMPLETED]) == (1, 1)


async def test_the_strip_reports_no_last_send_rather_than_an_epoch(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``started_at`` is NULL until a run's first message leaves, and the null crosses whole.

    Three cases in one test because they are one claim: a deployment with no campaigns at
    all, a deployment whose campaigns have never started, and one where exactly one has. A
    zero-filled strip with an invented instant would render as a send nobody made — which is
    precisely the reading an epoch or a fallback to ``created_at`` would produce.
    """
    # Act — nothing seeded at all.
    async with sessions.begin() as session:
        empty = await broadcasts.broadcast_stats(session, filters=broadcasts.BroadcastFilters())

    # Assert — zeroes over the closed enum, and an ABSENT instant rather than a zero one.
    assert empty.total == 0
    assert [item.count for item in empty.by_state] == [0] * len(list(BroadcastState))
    assert (empty.settled_recipients, empty.audience_total) == (0, 0)
    assert empty.last_send_at is None

    # Arrange — two drafts that have never started, then one campaign that has.
    async with sessions.begin() as session:
        await seed_broadcast(session, created_at=_DAY_ONE, state=BroadcastState.DRAFT)
        await seed_broadcast(session, created_at=_DAY_TWO, state=BroadcastState.READY)

    async with sessions.begin() as session:
        unstarted = await broadcasts.broadcast_stats(session, filters=broadcasts.BroadcastFilters())

    assert unstarted.total == 2
    assert unstarted.last_send_at is None

    # Arrange — two runs, started a day apart, and the LATER one is the answer. They are in
    # different states on purpose: the MAX is folded across the groups, not within one.
    async with sessions.begin() as session:
        await seed_broadcast(
            session,
            created_at=_DAY_TWO,
            state=BroadcastState.COMPLETED,
            started_at=_DAY_TWO,
            finished_at=_DAY_TWO + timedelta(hours=1),
        )
        await seed_broadcast(
            session, created_at=_DAY_THREE, state=BroadcastState.SENDING, started_at=_DAY_THREE
        )

    async with sessions.begin() as session:
        started = await broadcasts.broadcast_stats(session, filters=broadcasts.BroadcastFilters())

    assert started.last_send_at == _DAY_THREE


# ---------------------------------------------------------------------------
# The detail: bodies, the frozen segment, and progress counted from the rows
# ---------------------------------------------------------------------------
async def test_the_detail_recounts_progress_from_the_rows_and_keeps_the_stale_rollup_beside_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The rows are the truth; the campaign's counters are the worker's summary of them.

    Seeded to DISAGREE on purpose: a rollup that has not caught up (or a worker that died
    between the settlement and the rollup) is exactly the state an operator is watching the
    bar during, and a detail screen that read the parent row would show them a number the
    database itself does not agree with.
    """
    # Arrange — the rollup says nothing has been sent; three rows say otherwise.
    async with sessions.begin() as session:
        campaign = await seed_broadcast(
            session,
            created_at=_DAY_ONE,
            state=BroadcastState.SENDING,
            audience_size=4,
            recipient_count=4,
            sent_count=0,
        )
        for index in range(3):
            await seed_recipient(
                session,
                broadcast=campaign,
                telegram_user_id=5_000_200 + index,
                state=BroadcastRecipientState.SENT,
                attempts=1,
                settled_at=_DAY_TWO,
            )
        await seed_recipient(
            session,
            broadcast=campaign,
            telegram_user_id=5_000_299,
            state=BroadcastRecipientState.FAILED,
            attempts=3,
            error_code="tg_500",
            settled_at=_DAY_TWO,
        )

    # Act
    async with sessions.begin() as session:
        detail = await broadcasts.get_broadcast(session, campaign.id)

    # Assert
    assert detail is not None
    assert detail.progress.sent == 3
    assert detail.progress.failed == 1
    assert (detail.progress.total, detail.progress.settled) == (4, 4)
    # The parent row's own (stale) counter still travels, so the drift is visible.
    assert detail.broadcast.sent_count == 0
    assert detail.broadcast.recipient_count == 4


async def test_the_detail_hands_back_the_stored_segment_verbatim_and_the_bodies_by_language(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The frozen document is returned as stored, and the cached ``file_id`` never is.

    ``media_file_id`` is the worker's cache of what Telegram called our upload; it is
    meaningless to any other token, so it crosses as a boolean the way ``AssetView`` publishes
    ``tg_file_id``. ``media_storage_key`` — the thing an operator can actually fetch the image
    back from — crosses whole.
    """
    # Arrange
    async with sessions.begin() as session:
        campaign = await seed_broadcast(session, created_at=_DAY_ONE)
        await seed_body(
            session,
            broadcast=campaign,
            language=Language.RU,
            text="Сегодня вечером обновление.",
            media_storage_key="broadcasts/2026/09/notice.jpg",
            media_file_id="AgACAgIAAxkBAA",
            button_label="Подробнее",
            button_url="https://example.uz/status",
        )
        await seed_body(session, broadcast=campaign, language=Language.EN, text="Update tonight.")

    # Act
    async with sessions.begin() as session:
        detail = await broadcasts.get_broadcast(session, campaign.id)

    # Assert
    assert detail is not None
    assert detail.segment == _SEGMENT
    assert [body.language for body in detail.bodies] == sorted(
        (Language.RU, Language.EN), key=lambda language: language.value
    )
    russian = next(body for body in detail.bodies if body.language is Language.RU)
    assert russian.media_storage_key == "broadcasts/2026/09/notice.jpg"
    assert russian.has_media_file_id is True
    assert (russian.button_label, russian.button_url) == ("Подробнее", "https://example.uz/status")
    english = next(body for body in detail.bodies if body.language is Language.EN)
    assert (english.media_storage_key, english.has_media_file_id) == (None, False)
    assert detail.broadcast.body_count == 2


async def test_the_detail_is_none_for_an_unknown_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    async with sessions.begin() as session:
        detail = await broadcasts.get_broadcast(session, uuid4())

    # Assert
    assert detail is None


# ---------------------------------------------------------------------------
# Progress: every state, always, counted from the ledger
# ---------------------------------------------------------------------------
async def test_progress_reports_every_recipient_state_it_could_be_asked_about(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One row per member of the enum, so a member added without a counter is caught here.

    ``BroadcastProgress.total`` sums the named fields; comparing it against
    ``len(BroadcastRecipientState)`` is what makes an eighth state a failing test rather than
    a number that silently disappears from a progress bar.
    """
    # Arrange — exactly one recipient in each state.
    async with sessions.begin() as session:
        campaign = await seed_broadcast(session, created_at=_DAY_ONE)
        for index, state in enumerate(BroadcastRecipientState):
            await seed_recipient(
                session,
                broadcast=campaign,
                telegram_user_id=5_000_300 + index,
                state=state,
            )

    # Act
    async with sessions.begin() as session:
        progress = await broadcasts.broadcast_progress(session, campaign.id)

    # Assert — every state counted once, and the two derived numbers agree with them.
    assert progress.total == len(BroadcastRecipientState)
    assert (progress.pending, progress.sending, progress.sent) == (1, 1, 1)
    assert (progress.failed, progress.skipped_blocked) == (1, 1)
    assert (progress.undeliverable, progress.unknown) == (1, 1)
    # Everything but PENDING and SENDING has stopped moving.
    assert progress.settled == len(BroadcastRecipientState) - 2


async def test_progress_is_zero_filled_for_a_campaign_with_no_rows_and_for_an_unknown_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A bar whose segments do not appear from nowhere as the first row lands."""
    # Arrange
    async with sessions.begin() as session:
        campaign = await seed_broadcast(session, created_at=_DAY_ONE)

    # Act
    async with sessions.begin() as session:
        empty = await broadcasts.broadcast_progress(session, campaign.id)
        unknown = await broadcasts.broadcast_progress(session, uuid4())

    # Assert — seven zeros in both cases; existence is ``get_broadcast``'s answer to give.
    assert (empty.total, empty.settled) == (0, 0)
    assert empty == unknown


async def test_progress_counts_only_the_campaign_it_was_asked_about(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two campaigns whose rows are in the same states.
    async with sessions.begin() as session:
        mine = await seed_broadcast(session, created_at=_DAY_ONE, title="Mine")
        theirs = await seed_broadcast(session, created_at=_DAY_TWO, title="Theirs")
        await seed_recipient(
            session, broadcast=mine, telegram_user_id=5_001_001, state=BroadcastRecipientState.SENT
        )
        for index in range(4):
            await seed_recipient(
                session,
                broadcast=theirs,
                telegram_user_id=5_002_000 + index,
                state=BroadcastRecipientState.SENT,
            )

    # Act
    async with sessions.begin() as session:
        progress = await broadcasts.broadcast_progress(session, mine.id)

    # Assert
    assert (progress.sent, progress.total) == (1, 1)


# ---------------------------------------------------------------------------
# The ledger: paged inside one campaign, and honest about an erased row
# ---------------------------------------------------------------------------
async def test_the_ledger_is_paged_inside_one_campaign_and_never_across_two(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Interleaved in time on purpose: an unnarrowed keyset walk would mix the two.

    The other campaign's rows are NEWER, so a read that lost its ``broadcast_id`` would fill
    the first page with them and look entirely plausible.
    """
    # Arrange
    async with sessions.begin() as session:
        mine = await seed_broadcast(session, created_at=_DAY_ONE, title="Mine")
        theirs = await seed_broadcast(session, created_at=_DAY_ONE, title="Theirs")
        expected = [
            (
                await seed_recipient(
                    session,
                    broadcast=mine,
                    telegram_user_id=5_003_000 + index,
                    created_at=_DAY_TWO + timedelta(minutes=index),
                )
            ).id
            for index in range(3)
        ]
        for index in range(3):
            await seed_recipient(
                session,
                broadcast=theirs,
                telegram_user_id=5_004_000 + index,
                created_at=_DAY_THREE + timedelta(minutes=index),
            )

    # Act
    async with sessions.begin() as session:
        page = await broadcasts.list_recipients(
            session,
            mine.id,
            filters=broadcasts.RecipientFilters(),
            request=PageRequest(limit=10),
        )
        total = await broadcasts.count_recipients(
            session, mine.id, filters=broadcasts.RecipientFilters()
        )

    # Assert — this campaign's three rows, newest first, and nobody else's.
    assert [item.id for item in page.items] == list(reversed(expected))
    assert all(item.broadcast_id == mine.id for item in page.items)
    assert (total.total, total.is_exact) == (3, True)


async def test_the_ledger_walk_survives_a_chunk_that_shares_one_instant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """An expansion writes thousands of rows in one statement, so ``created_at`` ties are the rule.

    The primary key is the tie-break that makes ``(created_at, id)`` a total order; without it
    a page boundary landing inside the tie-block repeats or loses rows, and nothing raises.
    """
    # Arrange — five rows, one instant.
    async with sessions.begin() as session:
        campaign = await seed_broadcast(session, created_at=_DAY_ONE)
        expected = {
            (
                await seed_recipient(
                    session,
                    broadcast=campaign,
                    telegram_user_id=5_005_000 + index,
                    created_at=_DAY_TWO,
                )
            ).id
            for index in range(5)
        }

    # Act
    seen: list[UUID] = []
    cursor: str | None = None
    pages = 0
    while True:
        request = page_request(limit=2, cursor=cursor)
        assert is_ok(request)
        async with sessions.begin() as session:
            page = await broadcasts.list_recipients(
                session,
                campaign.id,
                filters=broadcasts.RecipientFilters(),
                request=request.value,
            )
        seen.extend(item.id for item in page.items)
        pages += 1
        cursor = page.next_cursor
        if cursor is None:
            break

    # Assert — every row exactly once, in three pages, ending on a null cursor.
    assert set(seen) == expected
    assert len(seen) == 5
    assert pages == 3


async def test_ledger_filters_narrow_by_state_language_and_account(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        campaign = await seed_broadcast(session, created_at=_DAY_ONE)
        failed = await seed_recipient(
            session,
            broadcast=campaign,
            telegram_user_id=5_006_001,
            state=BroadcastRecipientState.FAILED,
            error_code="tg_429",
            attempts=2,
            settled_at=_DAY_TWO,
        )
        russian = await seed_recipient(
            session,
            broadcast=campaign,
            telegram_user_id=5_006_002,
            language=Language.RU,
            state=BroadcastRecipientState.SENT,
            settled_at=_DAY_TWO,
        )
        await seed_recipient(
            session,
            broadcast=campaign,
            telegram_user_id=5_006_003,
            state=BroadcastRecipientState.PENDING,
        )

    # Act
    async with sessions.begin() as session:
        by_state = await broadcasts.list_recipients(
            session,
            campaign.id,
            filters=broadcasts.RecipientFilters(states=(BroadcastRecipientState.FAILED,)),
            request=PageRequest(limit=10),
        )
        by_language = await broadcasts.list_recipients(
            session,
            campaign.id,
            filters=broadcasts.RecipientFilters(languages=(Language.RU,)),
            request=PageRequest(limit=10),
        )
        by_account = await broadcasts.list_recipients(
            session,
            campaign.id,
            filters=broadcasts.RecipientFilters(telegram_user_id=5_006_002),
            request=PageRequest(limit=10),
        )
        counted = await broadcasts.count_recipients(
            session,
            campaign.id,
            filters=broadcasts.RecipientFilters(states=(BroadcastRecipientState.FAILED,)),
        )

    # Assert
    assert [item.id for item in by_state.items] == [failed.id]
    assert by_state.items[0].error_code == "tg_429"
    assert by_state.items[0].attempts == 2
    assert by_state.items[0].settled_at == _DAY_TWO
    assert [item.id for item in by_language.items] == [russian.id]
    assert [item.id for item in by_account.items] == [russian.id]
    assert (counted.total, counted.is_exact) == (1, True)


async def test_an_erased_recipient_row_is_listed_with_its_id_gone(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``/forget`` anonymises the row; it does not delete it.

    A delivery record that vanished because somebody exercised a right takes "was this person
    sent that campaign?" away from every other row in the campaign too — so the row is
    RENDERED, with ``telegram_user_id`` ``None`` and :attr:`is_erased` saying why.
    """
    # Arrange
    async with sessions.begin() as session:
        campaign = await seed_broadcast(session, created_at=_DAY_ONE)
        erased = await seed_recipient(
            session,
            broadcast=campaign,
            telegram_user_id=None,
            state=BroadcastRecipientState.SENT,
            settled_at=_DAY_TWO,
        )
        kept = await seed_recipient(
            session,
            broadcast=campaign,
            telegram_user_id=5_007_001,
            state=BroadcastRecipientState.SENT,
            settled_at=_DAY_TWO,
        )

    # Act
    async with sessions.begin() as session:
        page = await broadcasts.list_recipients(
            session,
            campaign.id,
            filters=broadcasts.RecipientFilters(),
            request=PageRequest(limit=10),
        )
        progress = await broadcasts.broadcast_progress(session, campaign.id)

    # Assert — both rows are there, and the erasure is a state rather than an absence.
    assert {item.id for item in page.items} == {erased.id, kept.id}
    anonymised = next(item for item in page.items if item.id == erased.id)
    assert anonymised.telegram_user_id is None
    assert anonymised.is_erased is True
    assert next(item for item in page.items if item.id == kept.id).is_erased is False
    # And it still counts towards the campaign it was sent.
    assert progress.sent == 2
