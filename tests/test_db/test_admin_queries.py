"""The admin read layer, against a real (in-memory) database.

The test this module exists for is
:func:`test_a_list_page_containing_an_identity_purged_order_returns_it`. ``mapping.to_order``
raises ``PipelineError`` when ``recipient_name_display IS NULL``, which is exactly the state
the 90-day sweep leaves an order in — so ``SqlKitRepository.get_order`` cannot read a purged
order at all, and any admin list built on it would fail a whole page because one row on it
was lawfully erased. Everything else here is in service of that: a query layer that reads
``OrderRow``/``BriefRow`` directly and treats a purge as a state.

Rows are inserted by hand rather than through ``SqlKitRepository`` on purpose. The metric
tests assert numbers computed by hand from a fixture, and that is only meaningful if the
fixture's timestamps, purge markers and telemetry columns are exactly what the test says
they are rather than whatever a repository's clock and retention policy chose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bayram.contracts import (
    AssetKind,
    Genre,
    Language,
    NameStrategy,
    Occasion,
    OrderState,
    Script,
    VoiceGender,
    is_ok,
)
from bayram.db.admin import attempts as attempt_queries
from bayram.db.admin import metrics, orders, users
from bayram.db.admin import page as page_module
from bayram.db.admin.page import (
    Cursor,
    PageRequest,
    SortedCursor,
    SortSpec,
    SortValueKind,
    decode_sorted_cursor,
)
from bayram.db.admin.segment import (
    DEFAULT_SORT,
    FIELDS,
    SORT_KEYS,
    CompiledSegment,
    MatchMode,
    Segment,
    SegmentError,
    SegmentGroup,
    SegmentOp,
    SegmentRule,
    compile_segment,
    segment_capabilities,
)
from bayram.db.admin.segment import SortSpec as SegmentSortSpec
from bayram.db.admin.sql import TimeWindow
from bayram.db.admin.views import (
    LatencySummary,
    OrderLedgerStatus,
    OrderListItem,
    OrderPaymentRail,
)
from bayram.db.credits import unenforced_key_prefix
from bayram.db.enums import CreditEntryKind, CreditReason, GenerationKind
from bayram.db.mapping import to_order
from bayram.db.models import Base
from bayram.db.models.asset import AssetRow
from bayram.db.models.brief import BriefRow
from bayram.db.models.generation_attempt import GenerationAttemptRow
from bayram.db.models.order import OrderRow
from bayram.db.models.user import UserRow
from bayram.db.models.user_profile import UserProfileRow
from bayram.db.retention import RetentionClass
from bayram.entitlements import EntitlementPolicy
from bayram.errors import PipelineError
from tests.test_db.test_admin_credits import seed_account, seed_entry

#: Every index migration ``0009`` is responsible for, restated here so the test fails if the
#: migration quietly loses one rather than only if it fails to run.
#: The read-layer indexes, as ``(index name, table, ordered columns)``.
#:
#: ``ix_generation_attempts_kind_created_at`` is deliberately absent: ``kind`` has four
#: values, Postgres never chose the composite at any selectivity (not even with
#: ``enable_seqscan=off``), and it was pure write cost on an only-grows table. The partial
#: failures index replaces the half of the error-code index that was claimed for
#: ``metrics.failure_breakdown`` and could never have served it.
_EXPECTED_INDEXES: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    ("ix_orders_state_created_at", "orders", ("state", "created_at", "id")),
    (
        "ix_orders_telegram_user_id_created_at",
        "orders",
        ("telegram_user_id", "created_at", "id"),
    ),
    (
        "ix_generation_attempts_error_code_created_at",
        "generation_attempts",
        ("error_code", "created_at", "id"),
    ),
    (
        "ix_generation_attempts_provider_created_at",
        "generation_attempts",
        ("provider", "created_at", "id"),
    ),
    (
        "ix_generation_attempts_failures_created_at",
        "generation_attempts",
        ("created_at",),
    ),
)

_DAY_ONE: Final[datetime] = datetime(2026, 3, 20, 9, 0, tzinfo=UTC)
_DAY_TWO: Final[datetime] = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)
_FAR_FUTURE: Final[datetime] = datetime(2027, 1, 1, tzinfo=UTC)
_TELEGRAM_ID: Final[int] = 99_000_111

#: One canonical E.164 number, in the spelling ``bayram.user_profiles.normalise_phone`` produces.
#: A formatted variant here would be a fixture asserting a normalisation this layer does not
#: perform: the read model hands back exactly what the store wrote.
_PHONE: Final[str] = "+998901234542"


# ---------------------------------------------------------------------------
# Seed helpers — explicit values, no clocks, no policies
# ---------------------------------------------------------------------------
async def seed_user(
    session: AsyncSession, *, telegram_user_id: int = _TELEGRAM_ID, created_at: datetime, **kw: Any
) -> UserRow:
    row = UserRow(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        ui_language=kw.pop("ui_language", Language.UZ_LATN),
        is_blocked=kw.pop("is_blocked", False),
        last_seen_at=kw.pop("last_seen_at", created_at),
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_profile(session: AsyncSession, *, user: UserRow, **kw: Any) -> UserProfileRow:
    """A ``user_profiles`` row, written by hand for the same reason every other seed is.

    ``SqlUserProfiles`` reads a clock and would decide these timestamps itself, and the join
    tests below assert that ``phone_shared_at`` and ``avatar_stored_at`` arrive as two
    DIFFERENT instants — a store-written fixture would set them from one ``now`` and the
    assertion would pass even if the read layer mapped one column onto the other.
    """
    row = UserProfileRow(
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        phone_e164=kw.pop("phone_e164", _PHONE),
        # Stored WITHOUT the ``@``: the sigil is drawn, never persisted.
        telegram_username=kw.pop("telegram_username", "gulomjon"),
        first_name=kw.pop("first_name", "Gʻulomjon"),
        last_name=kw.pop("last_name", "Toshmatov"),
        avatar_file_unique_id=kw.pop("avatar_file_unique_id", "AgADBAADq6cxG"),
        avatar_mime=kw.pop("avatar_mime", "image/jpeg"),
        avatar_stored_at=kw.pop("avatar_stored_at", _DAY_TWO),
        language_chosen_at=kw.pop("language_chosen_at", _DAY_ONE),
        phone_shared_at=kw.pop("phone_shared_at", _DAY_ONE),
        onboarded_at=kw.pop("onboarded_at", _DAY_ONE),
        created_at=kw.pop("created_at", _DAY_ONE),
        updated_at=kw.pop("updated_at", _DAY_ONE),
    )
    session.add(row)
    await session.flush()
    return row


async def seed_order(
    session: AsyncSession, *, user: UserRow, created_at: datetime, **kw: Any
) -> OrderRow:
    row = OrderRow(
        id=kw.pop("id", uuid4()),
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        state=kw.pop("state", OrderState.DELIVERED),
        correlation_id=kw.pop("correlation_id", "corr-default"),
        is_paid=kw.pop("is_paid", True),
        delivered_at=kw.pop("delivered_at", None),
        failed_reason=kw.pop("failed_reason", None),
        created_at=created_at,
        updated_at=kw.pop("updated_at", created_at),
    )
    session.add(row)
    await session.flush()
    return row


async def seed_brief(session: AsyncSession, *, order: OrderRow, **kw: Any) -> BriefRow:
    """A brief. Pass ``recipient_name_display=None`` plus ``identity_purged_at`` for a purge."""
    row = BriefRow(
        id=uuid4(),
        order_id=order.id,
        occasion=kw.pop("occasion", Occasion.BIRTHDAY),
        genre=kw.pop("genre", Genre.UZBEK_POP),
        vocal_gender=VoiceGender.FEMALE,
        ui_language=Language.UZ_LATN,
        output_language=kw.pop("output_language", Language.UZ_LATN),
        note=kw.pop("note", "Loves mountains."),
        approved_lyrics=kw.pop("approved_lyrics", None),
        note_expires_at=kw.pop("note_expires_at", _FAR_FUTURE),
        note_purged_at=kw.pop("note_purged_at", None),
        recipient_name_raw=kw.pop("recipient_name_raw", "Gʻulomjon"),
        recipient_name_display=kw.pop("recipient_name_display", "Gʻulomjon"),
        recipient_lookup_key=kw.pop("recipient_lookup_key", "gulomjon"),
        recipient_script=kw.pop("recipient_script", Script.LATIN),
        recipient_language=kw.pop("recipient_language", Language.UZ_LATN),
        recipient_candidates=kw.pop(
            "recipient_candidates",
            [{"text": "Gulomjon", "strategy": "stripped", "rank": 0}],
        ),
        identity_expires_at=kw.pop("identity_expires_at", _FAR_FUTURE),
        identity_purged_at=kw.pop("identity_purged_at", None),
        event_day=kw.pop("event_day", 12),
        event_month=kw.pop("event_month", 5),
        created_at=order.created_at,
        updated_at=order.created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_asset(session: AsyncSession, *, order: OrderRow, **kw: Any) -> AssetRow:
    row = AssetRow(
        id=uuid4(),
        order_id=order.id,
        kind=kw.pop("kind", AssetKind.SONG),
        variant_index=kw.pop("variant_index", 0),
        path=kw.pop("path", "/var/kits/song.mp3"),
        storage_key=kw.pop("storage_key", None),
        mime=kw.pop("mime", "audio/mpeg"),
        size_bytes=kw.pop("size_bytes", 1_024),
        duration_s=kw.pop("duration_s", 90.0),
        sha256=kw.pop("sha256", "a" * 64),
        loudness_lufs=kw.pop("loudness_lufs", -14.0),
        tg_file_id=kw.pop("tg_file_id", None),
        name_candidate_strategy=kw.pop("name_candidate_strategy", NameStrategy.STRIPPED),
        name_candidate_rank=kw.pop("name_candidate_rank", 0),
        retention_class=RetentionClass.PAID_AUDIO,
        expires_at=kw.pop("expires_at", _FAR_FUTURE),
        created_at=kw.pop("created_at", order.created_at),
    )
    session.add(row)
    await session.flush()
    return row


async def seed_attempt(
    session: AsyncSession, *, created_at: datetime, order: OrderRow | None = None, **kw: Any
) -> GenerationAttemptRow:
    row = GenerationAttemptRow(
        id=uuid4(),
        order_id=None if order is None else order.id,
        kind=kw.pop("kind", GenerationKind.SONG),
        sequence=kw.pop("sequence", 0),
        attempt=kw.pop("attempt", 0),
        provider=kw.pop("provider", "elevenlabs"),
        provider_remote_id=kw.pop("provider_remote_id", None),
        language=kw.pop("language", Language.UZ_LATN),
        is_success=kw.pop("is_success", True),
        name_candidate_strategy=kw.pop("name_candidate_strategy", None),
        name_candidate_rank=kw.pop("name_candidate_rank", None),
        is_name_verified=kw.pop("is_name_verified", None),
        match_confidence=kw.pop("match_confidence", None),
        name_candidate_text=kw.pop("name_candidate_text", None),
        stt_transcript=kw.pop("stt_transcript", None),
        error_code=kw.pop("error_code", None),
        error_message=kw.pop("error_message", None),
        cost_usd=kw.pop("cost_usd", 0.0),
        latency_ms=kw.pop("latency_ms", 0),
        identity_expires_at=kw.pop("identity_expires_at", _FAR_FUTURE),
        identity_purged_at=kw.pop("identity_purged_at", None),
        text_expires_at=kw.pop("text_expires_at", _FAR_FUTURE),
        text_purged_at=kw.pop("text_purged_at", None),
        created_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# THE trap: an identity-purged order is a state, not an error
# ---------------------------------------------------------------------------
async def test_a_list_page_containing_an_identity_purged_order_returns_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one live order and one whose 90-day identity sweep has run.
    purged_at = datetime(2026, 6, 20, 9, 0, tzinfo=UTC)
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        live = await seed_order(session, user=user, created_at=_DAY_TWO)
        await seed_brief(session, order=live)
        purged = await seed_order(session, user=user, created_at=_DAY_ONE)
        await seed_brief(
            session,
            order=purged,
            recipient_name_raw=None,
            recipient_name_display=None,
            recipient_lookup_key=None,
            recipient_script=None,
            recipient_language=None,
            recipient_candidates=None,
            identity_purged_at=purged_at,
        )

    # Act
    async with sessions.begin() as session:
        page = await orders.list_orders(
            session, filters=orders.OrderFilters(), request=PageRequest(limit=10)
        )

    # Assert — the page came back whole, and the purge is a readable state on the row.
    assert [item.id for item in page.items] == [live.id, purged.id]
    erased = page.items[1]
    assert erased.recipient_name_display is None
    assert erased.identity_purged_at == purged_at
    assert erased.is_identity_purged is True
    assert erased.is_brief_present is True
    assert page.items[0].recipient_name_display == "Gʻulomjon"


async def test_the_pipeline_mapper_still_raises_on_the_same_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The trap is real: this is why the admin layer may not go through ``to_order``."""
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(session, user=user, created_at=_DAY_ONE)
        brief = await seed_brief(
            session,
            order=order,
            recipient_name_display=None,
            identity_purged_at=_DAY_TWO,
        )

        # Act / Assert
        with pytest.raises(PipelineError):
            to_order(order, brief)


async def test_order_detail_reads_a_purged_order(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(session, user=user, created_at=_DAY_ONE)
        await seed_brief(
            session,
            order=order,
            note=None,
            note_purged_at=_DAY_TWO,
            recipient_name_display=None,
            recipient_candidates=None,
            identity_purged_at=_DAY_TWO,
        )
        await seed_asset(session, order=order)

    # Act
    async with sessions.begin() as session:
        detail = await orders.get_order_detail(session, order.id)

    # Assert
    assert detail is not None
    assert detail.brief is not None
    assert detail.brief.recipient_name_display is None
    assert detail.brief.is_identity_purged is True
    assert detail.brief.is_note_purged is True
    assert detail.brief.note_chars is None
    assert detail.brief.candidate_count == 0
    assert len(detail.assets) == 1


async def test_an_order_with_no_brief_is_distinguishable_from_a_purged_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a DRAFT that never got a brief row.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_ONE, state=OrderState.DRAFT)

    # Act
    async with sessions.begin() as session:
        page = await orders.list_orders(
            session, filters=orders.OrderFilters(), request=PageRequest(limit=10)
        )

    # Assert — no brief is not the same claim as "the identity was erased".
    item = page.items[0]
    assert item.is_brief_present is False
    assert item.recipient_name_display is None
    assert item.is_identity_purged is False


async def test_a_malformed_candidates_column_counts_as_zero_rather_than_failing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a legacy row whose JSON column is not a list at all.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(session, user=user, created_at=_DAY_ONE)
        await seed_brief(session, order=order, recipient_candidates={"oops": True})

    # Act
    async with sessions.begin() as session:
        detail = await orders.get_order_detail(session, order.id)

    # Assert — a damaged row is exactly the row an operator opens the panel to look at.
    assert detail is not None
    assert detail.brief is not None
    assert detail.brief.candidate_count == 0


# ---------------------------------------------------------------------------
# Orders — filters, detail, timeline
# ---------------------------------------------------------------------------
async def test_order_filters_are_and_across_fields_and_or_within_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        delivered = await seed_order(
            session, user=user, created_at=_DAY_TWO, state=OrderState.DELIVERED
        )
        failed = await seed_order(
            session, user=user, created_at=_DAY_TWO, state=OrderState.FAILED, is_paid=False
        )
        await seed_order(session, user=user, created_at=_DAY_TWO, state=OrderState.DRAFT)

    # Act
    async with sessions.begin() as session:
        both = await orders.list_orders(
            session,
            filters=orders.OrderFilters(states=(OrderState.DELIVERED, OrderState.FAILED)),
            request=PageRequest(limit=10),
        )
        paid_only = await orders.list_orders(
            session,
            filters=orders.OrderFilters(
                states=(OrderState.DELIVERED, OrderState.FAILED), is_paid=True
            ),
            request=PageRequest(limit=10),
        )

    # Assert
    assert {item.id for item in both.items} == {delivered.id, failed.id}
    assert [item.id for item in paid_only.items] == [delivered.id]


async def test_order_filters_narrow_by_correlation_user_window_and_assets(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        other = await seed_user(session, telegram_user_id=42, created_at=_DAY_ONE)
        target = await seed_order(
            session, user=user, created_at=_DAY_TWO, correlation_id="corr-target"
        )
        await seed_asset(session, order=target)
        await seed_order(session, user=other, created_at=_DAY_ONE, correlation_id="corr-other")

    # Act
    async with sessions.begin() as session:
        by_correlation = await orders.list_orders(
            session,
            filters=orders.OrderFilters(correlation_id="corr-target"),
            request=PageRequest(limit=10),
        )
        by_user = await orders.list_orders(
            session,
            filters=orders.OrderFilters(telegram_user_id=_TELEGRAM_ID),
            request=PageRequest(limit=10),
        )
        in_window = await orders.list_orders(
            session,
            filters=orders.OrderFilters(
                window=TimeWindow(start=_DAY_TWO, end=_DAY_TWO + timedelta(days=1))
            ),
            request=PageRequest(limit=10),
        )
        without_assets = await orders.list_orders(
            session,
            filters=orders.OrderFilters(has_assets=False),
            request=PageRequest(limit=10),
        )

    # Assert
    assert [item.id for item in by_correlation.items] == [target.id]
    assert [item.id for item in by_user.items] == [target.id]
    assert [item.id for item in in_window.items] == [target.id]
    assert [item.asset_count for item in by_user.items] == [1]
    assert target.id not in {item.id for item in without_assets.items}


async def test_count_orders_is_exact_below_the_cap(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        for _ in range(3):
            await seed_order(session, user=user, created_at=_DAY_ONE)

    # Act
    async with sessions.begin() as session:
        total = await orders.count_orders(session, filters=orders.OrderFilters())

    # Assert
    assert (total.total, total.is_exact) == (3, True)


async def test_order_detail_is_none_for_an_unknown_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    async with sessions.begin() as session:
        detail = await orders.get_order_detail(session, uuid4())

    # Assert
    assert detail is None


async def test_the_timeline_merges_sources_and_flags_what_is_inferred(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — created, attempted, asset stored, delivered.
    delivered_at = _DAY_ONE + timedelta(minutes=5)
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(
            session,
            user=user,
            created_at=_DAY_ONE,
            delivered_at=delivered_at,
            updated_at=delivered_at,
        )
        await seed_brief(session, order=order)
        await seed_attempt(session, order=order, created_at=_DAY_ONE + timedelta(minutes=1))
        await seed_asset(session, order=order, created_at=_DAY_ONE + timedelta(minutes=4))

    # Act
    async with sessions.begin() as session:
        detail = await orders.get_order_detail(session, order.id)

    # Assert
    assert detail is not None
    timeline = detail.timeline
    assert [event.kind.value for event in timeline.events] == [
        "order_created",
        "brief_recorded",
        "attempt_succeeded",
        "asset_stored",
        "order_delivered",
    ]
    # Delivery is read off a mutable column, so it is inferred; an attempt row is not.
    inferred = {event.kind.value for event in timeline.events if event.is_inferred}
    assert inferred == {"order_delivered"}
    assert "chat" not in {source.value for source in timeline.unavailable_sources}
    assert "audit" in {source.value for source in timeline.unavailable_sources}


async def test_a_failed_order_reports_its_failure_on_the_timeline(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    failed_at = _DAY_ONE + timedelta(minutes=2)
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(
            session,
            user=user,
            created_at=_DAY_ONE,
            state=OrderState.FAILED,
            failed_reason="UPSTREAM_5XX",
            updated_at=failed_at,
        )

    # Act
    async with sessions.begin() as session:
        detail = await orders.get_order_detail(session, order.id)

    # Assert
    assert detail is not None
    last = detail.timeline.events[-1]
    assert (last.kind.value, last.label, last.is_inferred) == ("order_failed", "UPSTREAM_5XX", True)


# ---------------------------------------------------------------------------
# Order financials — the ledger algebra, asserted against the gate's own arithmetic
# ---------------------------------------------------------------------------
async def _debit(session: AsyncSession, order: OrderRow, *, generation: int = 0) -> None:
    """What ``credits.charge`` writes when the render gate authorises this order."""
    await seed_entry(
        session,
        created_at=order.created_at,
        telegram_user_id=order.telegram_user_id,
        kind=CreditEntryKind.DEBIT,
        reason=CreditReason.ORDER_RENDER,
        delta=-1,
        order_id=order.id,
        generation=generation,
        idempotency_key=f"debit:{order.id}:{generation}",
    )


async def _refund(session: AsyncSession, order: OrderRow, *, generation: int = 0) -> None:
    """What ``credit_settlement.refund`` writes when the render failed terminally."""
    await seed_entry(
        session,
        created_at=order.created_at,
        telegram_user_id=order.telegram_user_id,
        kind=CreditEntryKind.REFUND,
        reason=CreditReason.ORDER_FAILED,
        delta=1,
        order_id=order.id,
        generation=generation,
        idempotency_key=f"refund:{order.id}:{generation}",
    )


async def _consume(session: AsyncSession, order: OrderRow, *, generation: int = 0) -> None:
    """What ``credit_settlement.consume`` writes when the kit reached the customer."""
    await seed_entry(
        session,
        created_at=order.created_at,
        telegram_user_id=order.telegram_user_id,
        kind=CreditEntryKind.CONSUME,
        reason=CreditReason.ORDER_DELIVERED,
        delta=0,
        order_id=order.id,
        generation=generation,
        idempotency_key=f"consume:{order.id}:{generation}",
    )


async def _top_up(session: AsyncSession, order: OrderRow, *, generation: int = 0) -> None:
    """What ``credits._cover_the_shortfall`` writes with the meter shipped dark.

    Note the two things this row does NOT have, both deliberate and both load-bearing here:
    no ``order_id`` (``net_position`` sums that column, and a grant hanging off the order
    would net it to zero) and therefore no link to the render except its idempotency key.
    """
    await seed_entry(
        session,
        created_at=order.created_at,
        telegram_user_id=order.telegram_user_id,
        kind=CreditEntryKind.GRANT,
        reason=CreditReason.UNENFORCED_RENDER,
        delta=1,
        order_id=None,
        generation=generation,
        idempotency_key=f"{unenforced_key_prefix(order.id)}{generation}",
    )


async def _only_item(sessions: async_sessionmaker[AsyncSession], order_id: UUID) -> OrderListItem:
    """The list row for one order, so every assertion below runs against the LIST query.

    The detail path is asserted to agree in
    :func:`test_the_detail_and_the_list_report_the_same_financial_position`; everything else
    goes through ``list_orders`` because that is the query that must not N+1 and the one a
    correlated subquery could silently mis-correlate.
    """
    async with sessions.begin() as session:
        page = await orders.list_orders(
            session, filters=orders.OrderFilters(), request=PageRequest(limit=10)
        )
    (item,) = [row for row in page.items if row.id == order_id]
    return item


async def test_an_order_with_no_ledger_rows_is_unmetered_rather_than_free(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The state most orders in this deployment are in, and the fourth member of the enum.

    ``credits_enforced`` ships ``False`` and a DRAFT never reaches the gate at all, so "no
    ledger row" is the common case rather than the corner. Reporting it as ``pending`` would
    claim a credit is held against an order that holds none; reporting it as ``settled``
    would invent a sale.
    """
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(session, user=user, created_at=_DAY_ONE)
        order_id = order.id

    # Act
    item = await _only_item(sessions, order_id)

    # Assert
    assert item.ledger.credit_cost == 0
    assert item.ledger.status is OrderLedgerStatus.UNMETERED
    assert item.ledger.payment_rail is OrderPaymentRail.NONE


async def test_an_open_debit_is_pending_and_a_settled_one_is_settled(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``net < 0`` split by the presence of a CONSUME — the whole of the two live states."""
    # Arrange — same charge, one closed and one not.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        open_order = await seed_order(session, user=user, created_at=_DAY_ONE)
        closed_order = await seed_order(session, user=user, created_at=_DAY_TWO)
        await _debit(session, open_order)
        await _debit(session, closed_order)
        await _consume(session, closed_order)
        open_id, closed_id = open_order.id, closed_order.id

    # Act
    pending = await _only_item(sessions, open_id)
    settled = await _only_item(sessions, closed_id)

    # Assert — the cost is the same in both; only whether it is closed differs.
    assert (pending.ledger.credit_cost, pending.ledger.status) == (1, OrderLedgerStatus.PENDING)
    assert (settled.ledger.credit_cost, settled.ledger.status) == (1, OrderLedgerStatus.SETTLED)
    assert settled.ledger.payment_rail is OrderPaymentRail.CREDITS


async def test_a_refunded_order_costs_nothing_and_costs_again_when_it_is_recharged(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The regression a "sum of the DEBIT rows" cost would fail, in both of its halves.

    A refund returns the order to net 0, which is exactly what makes it chargeable again at
    ``generation + 1`` — so the re-authorised order below carries two debits and one refund
    and has cost the customer **one** credit, not two. A naive sum of debits would say two,
    and an operator would refund a credit that was never taken.
    """
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        given_back = await seed_order(session, user=user, created_at=_DAY_ONE)
        recharged = await seed_order(session, user=user, created_at=_DAY_TWO)
        await _debit(session, given_back)
        await _refund(session, given_back)
        await _debit(session, recharged)
        await _refund(session, recharged)
        await _debit(session, recharged, generation=1)
        await _consume(session, recharged, generation=1)
        refunded_id, recharged_id = given_back.id, recharged.id

    # Act
    refunded = await _only_item(sessions, refunded_id)
    again = await _only_item(sessions, recharged_id)

    # Assert
    assert (refunded.ledger.credit_cost, refunded.ledger.status) == (
        0,
        OrderLedgerStatus.REFUNDED,
    )
    # Refunded is not unmetered: the rail still says credits moved for this order.
    assert refunded.ledger.payment_rail is OrderPaymentRail.CREDITS
    assert (again.ledger.credit_cost, again.ledger.status) == (1, OrderLedgerStatus.SETTLED)


async def test_a_dark_deployment_reports_the_render_as_comped_not_as_paid(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The rail an ``order_id`` predicate cannot see, and the reason the extra query exists.

    With ``credits_enforced=False`` the shortfall grant and the debit it funds are both
    written, so the ledger algebra alone reads this as an ordinary settled sale. It is not:
    the customer's balance did not pay, a configuration flag topped it up to exactly the
    cost. The grant carries no ``order_id``, so only its idempotency key can say which render
    it belonged to.
    """
    # Arrange — one comped render and one ordinary one, same account, same shape otherwise.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        comped = await seed_order(session, user=user, created_at=_DAY_ONE)
        paid = await seed_order(session, user=user, created_at=_DAY_TWO)
        await _top_up(session, comped)
        await _debit(session, comped)
        await _consume(session, comped)
        await _debit(session, paid)
        await _consume(session, paid)
        comped_id, paid_id = comped.id, paid.id

    # Act
    dark = await _only_item(sessions, comped_id)
    ordinary = await _only_item(sessions, paid_id)

    # Assert — the status is identical for the two; only the rail tells them apart.
    assert dark.ledger.status is ordinary.ledger.status is OrderLedgerStatus.SETTLED
    assert dark.ledger.payment_rail is OrderPaymentRail.UNENFORCED
    assert ordinary.ledger.payment_rail is OrderPaymentRail.CREDITS


async def test_one_order_never_reports_another_orders_credits(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A subquery that forgot to correlate reports the deployment's ledger on every row.

    The two orders below belong to the same account and differ only in their movements, so a
    ``SUM(delta)`` that lost its ``order_id`` predicate — or a top-up prefix match that
    matched on the account rather than the render — would give both the same numbers and
    every other test in this section would still pass.
    """
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        charged = await seed_order(session, user=user, created_at=_DAY_ONE)
        untouched = await seed_order(session, user=user, created_at=_DAY_TWO)
        await _top_up(session, charged)
        await _debit(session, charged)
        charged_id, untouched_id = charged.id, untouched.id

    # Act
    mine = await _only_item(sessions, charged_id)
    theirs = await _only_item(sessions, untouched_id)

    # Assert
    assert (mine.ledger.credit_cost, mine.ledger.payment_rail) == (
        1,
        OrderPaymentRail.UNENFORCED,
    )
    assert (theirs.ledger.credit_cost, theirs.ledger.payment_rail) == (0, OrderPaymentRail.NONE)


async def test_an_erased_ledger_row_still_counts_towards_the_order_it_charged(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``/forget`` nulls ``telegram_user_id`` and keeps the row — the order's cost survives.

    The mirror of ``db/admin/credits.py``'s "erased rows appear on nobody's page": that page
    keys on the account, this aggregate keys on the order, and the whole reason erasure keeps
    the row is that the count answers a billing question months later. An aggregate that
    filtered on the account too would erase the answer along with the identity.
    """
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(session, user=user, created_at=_DAY_ONE)
        await seed_entry(
            session,
            created_at=_DAY_ONE,
            telegram_user_id=None,
            kind=CreditEntryKind.DEBIT,
            reason=CreditReason.ORDER_RENDER,
            delta=-1,
            order_id=order.id,
            idempotency_key=f"debit:{order.id}:0",
        )
        order_id = order.id

    # Act
    item = await _only_item(sessions, order_id)

    # Assert
    assert (item.ledger.credit_cost, item.ledger.status) == (1, OrderLedgerStatus.PENDING)


async def test_the_detail_and_the_list_report_the_same_financial_position(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Two code paths, one answer. A detail screen that dropped the extra query would lie."""
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(session, user=user, created_at=_DAY_ONE)
        await _top_up(session, order)
        await _debit(session, order)
        await seed_attempt(session, order=order, created_at=_DAY_ONE)
        await seed_attempt(session, order=order, created_at=_DAY_ONE, attempt=1)
        order_id = order.id

    # Act
    listed = await _only_item(sessions, order_id)
    async with sessions.begin() as session:
        detail = await orders.get_order_detail(session, order_id)

    # Assert
    assert detail is not None
    assert detail.order.ledger == listed.ledger
    assert detail.order.attempt_count == listed.attempt_count == 2


async def test_the_attempt_count_counts_rows_and_an_order_with_none_reports_zero(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``retryCount``'s honest meaning: rows in ``generation_attempts``, nothing more.

    Today every row it can count is a name-verification verdict, because no vendor-render
    attempt writer exists in ``src/``. A delivered order with three songs behind it therefore
    reports ``0`` here, which is why the wire field's docstring forbids the label "render
    retries". The fixture below writes the rows explicitly rather than through the pipeline
    for exactly that reason — there is no pipeline path that would write them.
    """
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        verified = await seed_order(session, user=user, created_at=_DAY_ONE)
        silent = await seed_order(session, user=user, created_at=_DAY_TWO)
        for attempt in range(3):
            await seed_attempt(
                session,
                order=verified,
                created_at=_DAY_ONE,
                attempt=attempt,
                kind=GenerationKind.NAME_VERIFICATION,
            )
        verified_id, silent_id = verified.id, silent.id

    # Act
    counted = await _only_item(sessions, verified_id)
    none = await _only_item(sessions, silent_id)

    # Assert
    assert counted.attempt_count == 3
    assert none.attempt_count == 0


# ---------------------------------------------------------------------------
# Dataset-scoped state counts — the distribution bar's real numbers
# ---------------------------------------------------------------------------
async def test_state_counts_describe_the_whole_filter_set_and_not_one_page(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The bug this endpoint exists for: a bar computed from the fifty rows the browser holds.

    The fixture is deliberately lopsided — six delivered, one failed — so a count taken over a
    two-row page could not accidentally equal the count taken over the dataset.
    """
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        for _ in range(6):
            await seed_order(session, user=user, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_ONE, state=OrderState.FAILED)

    # Act — a page of two, and the counts for the same (empty) filter set.
    async with sessions.begin() as session:
        page = await orders.list_orders(
            session, filters=orders.OrderFilters(), request=PageRequest(limit=2)
        )
        totals = await orders.count_orders_by_state(session, filters=orders.OrderFilters())

    # Assert
    assert len(page.items) == 2
    counted = {total.state: total.count for total in totals}
    assert counted[OrderState.DELIVERED] == 6
    assert counted[OrderState.FAILED] == 1


async def test_state_counts_are_zero_filled_in_enum_order(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Every state, always, in declaration order — a bar whose segments do not move.

    ``UserDetail.orders_by_state`` makes the opposite promise on purpose, which is why these
    are two types and not one. A segment that appears from nowhere as the first FAILED order
    of the day lands is a bar that re-lays-out under the operator's cursor.
    """
    # Arrange — one state has rows; the rest must still be reported.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_ONE)

    # Act
    async with sessions.begin() as session:
        totals = await orders.count_orders_by_state(session, filters=orders.OrderFilters())

    # Assert
    assert [total.state for total in totals] == list(OrderState)
    assert sum(total.count for total in totals) == 1
    assert all(total.count == 0 for total in totals if total.state is not OrderState.DELIVERED)


async def test_state_counts_respect_every_filter_including_the_state_filter(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """It answers for exactly the rows ``GET /api/orders`` with the same query string returns.

    Including ``?state=``, which zeroes every other segment. That reads as useless until you
    ask what the alternative is: a server that quietly dropped one filter to draw a prettier
    bar would be describing a set the operator is not looking at, and the two numbers on the
    screen would disagree with nothing to explain why. Which distribution the SPA wants is
    settled by which parameters it sends.
    """
    # Arrange — the window and the state filter each exclude a different row.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_TWO)
        await seed_order(session, user=user, created_at=_DAY_TWO, state=OrderState.FAILED)

    # Act
    async with sessions.begin() as session:
        windowed = await orders.count_orders_by_state(
            session,
            filters=orders.OrderFilters(
                window=TimeWindow(start=_DAY_TWO, end=_DAY_TWO + timedelta(days=1))
            ),
        )
        narrowed = await orders.count_orders_by_state(
            session, filters=orders.OrderFilters(states=(OrderState.FAILED,))
        )

    # Assert
    by_window = {total.state: total.count for total in windowed}
    assert (by_window[OrderState.DELIVERED], by_window[OrderState.FAILED]) == (1, 1)
    by_state = {total.state: total.count for total in narrowed}
    assert by_state[OrderState.FAILED] == 1
    assert by_state[OrderState.DELIVERED] == 0


# ---------------------------------------------------------------------------
# ``?q=`` on orders — the operational identifiers, and the name that is not one
# ---------------------------------------------------------------------------
async def test_the_order_search_matches_the_correlation_id_and_the_telegram_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two orders sharing no substring in either searchable column.
    async with sessions.begin() as session:
        mine = await seed_user(session, created_at=_DAY_ONE)
        theirs = await seed_user(session, telegram_user_id=44_555_666, created_at=_DAY_ONE)
        await seed_order(session, user=mine, created_at=_DAY_ONE, correlation_id="abc123def")
        await seed_order(session, user=theirs, created_at=_DAY_TWO, correlation_id="zzz999zzz")

    # Act
    async with sessions.begin() as session:
        by_correlation = await orders.list_orders(
            session, filters=orders.OrderFilters(search="123de"), request=PageRequest(limit=10)
        )
        by_telegram = await orders.list_orders(
            session, filters=orders.OrderFilters(search="000111"), request=PageRequest(limit=10)
        )
        counted = await orders.count_orders(session, filters=orders.OrderFilters(search="123de"))
        blank = await orders.list_orders(
            session, filters=orders.OrderFilters(search="  "), request=PageRequest(limit=10)
        )

    # Assert — and the bounded total agrees with the page it labels, which a search applied
    # to only one of the two statements would break.
    assert [item.correlation_id for item in by_correlation.items] == ["abc123def"]
    assert [item.telegram_user_id for item in by_telegram.items] == [_TELEGRAM_ID]
    assert counted.total == 1
    assert len(blank.items) == 2


async def test_the_order_search_matches_a_whole_order_id_but_not_a_fragment_of_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The boundary ``_matches_order_id`` draws, and it is a portability one, not a privacy one.

    A substring of a UUID would need ``CAST(id AS VARCHAR)``, which renders 32 undashed hex
    characters on SQLite and a dashed native value on Postgres — a filter that would match in
    production and never in this suite. A whole id needs no cast, is served by the primary key
    and is accepted in every spelling ``UUID()`` parses.
    """
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        wanted = await seed_order(session, user=user, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_TWO)
        order_id = wanted.id

    # Act
    async with sessions.begin() as session:
        found = {
            probe: await orders.list_orders(
                session, filters=orders.OrderFilters(search=probe), request=PageRequest(limit=10)
            )
            for probe in (str(order_id), order_id.hex, str(order_id)[:8])
        }

    # Assert
    assert [item.id for item in found[str(order_id)].items] == [order_id]
    assert [item.id for item in found[order_id.hex].items] == [order_id]
    # A fragment is not an id and is not a substring of anything else here either.
    assert found[str(order_id)[:8]].items == ()


async def test_the_order_search_matches_no_recipient_name(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The refusal, asserted rather than assumed — this is a reveal bypass if it regresses.

    ``briefs.recipient_name_display`` is ``M`` at all four roles and its plaintext is reachable
    only through ``POST /reveal``: step-up, reason code, audit row, record budget. A
    ``LIKE '%…%'`` an operator steers over this ungated list endpoint would recover the same
    plaintext a few characters at a time and pay none of them. The probes carry U+02BB, correct
    Uzbek Latin orthography, so this cannot pass merely because the query folded a character
    the column did not.
    """
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(session, user=user, created_at=_DAY_ONE)
        await seed_brief(
            session, order=order, recipient_name_display="Gʻulom", note="Loves Chimgan."
        )

    # Act
    async with sessions.begin() as session:
        found = {
            probe: await orders.list_orders(
                session, filters=orders.OrderFilters(search=probe), request=PageRequest(limit=10)
            )
            for probe in ("Gʻulom", "ulom", "Chimgan")
        }

    # Assert
    for probe, page in found.items():
        assert page.items == (), probe


async def test_the_order_search_escapes_like_metacharacters_rather_than_widening(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``q=%`` must match nothing, not every order. The escaping is ``escape_like``'s job."""
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_ONE, correlation_id="plain")

    # Act
    async with sessions.begin() as session:
        wildcard = await orders.list_orders(
            session, filters=orders.OrderFilters(search="%"), request=PageRequest(limit=10)
        )

    # Assert
    assert wildcard.items == ()


# ---------------------------------------------------------------------------
# Attempts — instrumentation honesty and the strategy bake-off
# ---------------------------------------------------------------------------
async def test_an_uninstrumented_attempt_reports_no_cost_rather_than_zero(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — exactly what ``_replace_verdicts`` writes today: both columns defaulted.
    async with sessions.begin() as session:
        await seed_attempt(session, created_at=_DAY_ONE, provider=None, cost_usd=0.0, latency_ms=0)

    # Act
    async with sessions.begin() as session:
        page = await attempt_queries.list_attempts(
            session, filters=attempt_queries.AttemptFilters(), request=PageRequest(limit=10)
        )
        is_instrumented = await attempt_queries.is_cost_instrumented(session)

    # Assert — "$0.00" would be a confident lie; None is the truth.
    telemetry = page.items[0].telemetry
    assert telemetry.cost_usd is None
    assert telemetry.cost_source is None
    assert telemetry.latency_ms is None
    assert telemetry.is_instrumented is False
    assert is_instrumented is False


async def test_an_instrumented_attempt_reports_its_cost(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a Phase 5 row.
    async with sessions.begin() as session:
        await seed_attempt(session, created_at=_DAY_ONE, cost_usd=0.42, latency_ms=1_500)

    # Act
    async with sessions.begin() as session:
        page = await attempt_queries.list_attempts(
            session, filters=attempt_queries.AttemptFilters(), request=PageRequest(limit=10)
        )
        capabilities = await metrics.read_capabilities(session)

    # Assert
    telemetry = page.items[0].telemetry
    assert (telemetry.cost_usd, telemetry.latency_ms) == (0.42, 1_500)
    assert telemetry.is_instrumented is True
    assert capabilities.is_cost_telemetry is True
    assert capabilities.is_latency_telemetry is True


async def test_a_transcript_crosses_as_a_length_not_as_text(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    transcript = "Bugun quyosh boshqacha porlaydi Gulomjon"
    async with sessions.begin() as session:
        await seed_attempt(
            session,
            created_at=_DAY_ONE,
            kind=GenerationKind.NAME_VERIFICATION,
            stt_transcript=transcript,
        )

    # Act
    async with sessions.begin() as session:
        page = await attempt_queries.list_attempts(
            session, filters=attempt_queries.AttemptFilters(), request=PageRequest(limit=10)
        )

    # Assert — §6.7 routes free text through POST /reveal, never through a list page.
    item = page.items[0]
    assert item.stt_transcript_chars == len(transcript)
    assert transcript not in repr(item)


async def test_attempt_filters_including_orphaned_and_kind(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(session, user=user, created_at=_DAY_ONE)
        attached = await seed_attempt(session, order=order, created_at=_DAY_ONE)
        orphan = await seed_attempt(
            session, created_at=_DAY_ONE, kind=GenerationKind.NAME_PREVIEW, provider="openai"
        )
        await seed_attempt(
            session,
            order=order,
            created_at=_DAY_ONE,
            is_success=False,
            error_code="UPSTREAM_5XX",
        )

    # Act
    async with sessions.begin() as session:
        orphaned = await attempt_queries.list_attempts(
            session,
            filters=attempt_queries.AttemptFilters(is_orphaned=True),
            request=PageRequest(limit=10),
        )
        by_kind = await attempt_queries.list_attempts(
            session,
            filters=attempt_queries.AttemptFilters(kinds=(GenerationKind.SONG,)),
            request=PageRequest(limit=10),
        )
        failures = await attempt_queries.list_attempts(
            session,
            filters=attempt_queries.AttemptFilters(is_success=False, error_code="UPSTREAM_5XX"),
            request=PageRequest(limit=10),
        )
        by_provider = await attempt_queries.list_attempts(
            session,
            filters=attempt_queries.AttemptFilters(provider="openai", order_id=None),
            request=PageRequest(limit=10),
        )
        for_order = await attempt_queries.list_attempts(
            session,
            filters=attempt_queries.AttemptFilters(order_id=order.id, is_orphaned=False),
            request=PageRequest(limit=10),
        )
        one = await attempt_queries.get_attempt(session, attached.id)
        missing = await attempt_queries.get_attempt(session, uuid4())
        total = await attempt_queries.count_attempts(
            session, filters=attempt_queries.AttemptFilters()
        )

    # Assert
    assert [item.id for item in orphaned.items] == [orphan.id]
    assert orphaned.items[0].is_orphaned is True
    assert len(by_kind.items) == 2
    assert len(failures.items) == 1
    assert [item.id for item in by_provider.items] == [orphan.id]
    assert len(for_order.items) == 2
    assert one is not None and one.id == attached.id
    assert missing is None
    assert (total.total, total.is_exact) == (3, True)


async def test_strategy_outcomes_rank_by_rate_then_volume_inside_a_window(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — hand-computed: STRIPPED 3/4 = 0.75, CANONICAL 1/2 = 0.5, and one CYRILLIC
    # verdict outside the window that must not be counted.
    async with sessions.begin() as session:
        verdicts = (
            (NameStrategy.STRIPPED, True),
            (NameStrategy.STRIPPED, True),
            (NameStrategy.STRIPPED, True),
            (NameStrategy.STRIPPED, False),
            (NameStrategy.CANONICAL, True),
            (NameStrategy.CANONICAL, False),
        )
        for strategy, is_verified in verdicts:
            await seed_attempt(
                session,
                created_at=_DAY_TWO,
                kind=GenerationKind.NAME_VERIFICATION,
                name_candidate_strategy=strategy,
                name_candidate_rank=0,
                is_name_verified=is_verified,
            )
        # Runs where verification never ran must not count as failures.
        await seed_attempt(
            session,
            created_at=_DAY_TWO,
            name_candidate_strategy=NameStrategy.STRIPPED,
            name_candidate_rank=0,
            is_name_verified=None,
        )
        await seed_attempt(
            session,
            created_at=_DAY_ONE,
            kind=GenerationKind.NAME_VERIFICATION,
            name_candidate_strategy=NameStrategy.CYRILLIC,
            name_candidate_rank=1,
            is_name_verified=True,
        )

    # Act
    async with sessions.begin() as session:
        windowed = await metrics.strategy_outcomes(
            session, window=TimeWindow(start=_DAY_TWO, end=_DAY_TWO + timedelta(days=1))
        )
        all_time = await metrics.strategy_outcomes(session)

    # Assert
    assert [(o.strategy, o.attempts, o.verified) for o in windowed] == [
        (NameStrategy.STRIPPED, 4, 3),
        (NameStrategy.CANONICAL, 2, 1),
    ]
    assert windowed[0].verification_rate == pytest.approx(0.75)
    assert windowed[1].verification_rate == pytest.approx(0.5)
    # The CYRILLIC verdict is 1/1, so all-time it outranks both.
    assert all_time[0].strategy is NameStrategy.CYRILLIC


async def test_name_analytics_keeps_the_two_denominators_apart(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A verdict without a score counts in the bake-off and not in the histogram.

    ``is_name_verified`` and ``match_confidence`` are written together by
    ``verdict_row_values`` today, but nothing in the schema requires it — so ``scored`` is
    measured rather than assumed equal to ``attempts``. Reporting one as the other would put
    a denominator under the histogram that its bars do not add up to.
    """
    # Arrange
    async with sessions.begin() as session:
        await seed_attempt(
            session,
            created_at=_DAY_TWO,
            kind=GenerationKind.NAME_VERIFICATION,
            name_candidate_strategy=NameStrategy.STRIPPED,
            name_candidate_rank=0,
            is_name_verified=True,
            match_confidence=0.9,
        )
        await seed_attempt(
            session,
            created_at=_DAY_TWO,
            kind=GenerationKind.NAME_VERIFICATION,
            name_candidate_strategy=NameStrategy.STRIPPED,
            name_candidate_rank=0,
            is_name_verified=True,
            match_confidence=None,
        )

    # Act
    async with sessions.begin() as session:
        analytics = await attempt_queries.name_analytics(session)

    # Assert
    assert (analytics.attempts, analytics.verified, analytics.scored) == (2, 2, 1)
    assert analytics.strategies[0].scored == 1
    assert sum(bucket.count for bucket in analytics.buckets) == 1


async def test_name_analytics_clamps_a_score_the_verifier_returned_out_of_range(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``1.0000000002`` is not a reason to lose a sample — the SPA's rule, server-side."""
    # Arrange
    async with sessions.begin() as session:
        for confidence in (-0.5, 1.5):
            await seed_attempt(
                session,
                created_at=_DAY_TWO,
                kind=GenerationKind.NAME_VERIFICATION,
                name_candidate_strategy=NameStrategy.STRIPPED,
                name_candidate_rank=0,
                is_name_verified=True,
                match_confidence=confidence,
            )

    # Act
    async with sessions.begin() as session:
        analytics = await attempt_queries.name_analytics(session)

    # Assert — one in the first bar, one in the last, none lost.
    assert analytics.scored == 2
    assert analytics.buckets[0].count == 1
    assert analytics.buckets[-1].count == 1


async def test_the_near_threshold_band_is_inclusive_at_both_edges(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The count is "how many would a move of this size reach", so both edges are in."""
    # Arrange — band of 0.1 around 0.5: 0.4 and 0.6 are in, 0.39 and 0.61 are not.
    async with sessions.begin() as session:
        for confidence in (0.39, 0.4, 0.5, 0.6, 0.61):
            await seed_attempt(
                session,
                created_at=_DAY_TWO,
                kind=GenerationKind.NAME_VERIFICATION,
                name_candidate_strategy=NameStrategy.STRIPPED,
                name_candidate_rank=0,
                is_name_verified=True,
                match_confidence=confidence,
            )

    # Act
    async with sessions.begin() as session:
        analytics = await attempt_queries.name_analytics(session, threshold=0.5, band=0.1)

    # Assert
    assert analytics.near_threshold == 3
    assert analytics.band == 0.1


async def test_a_threshold_of_one_does_not_describe_a_band_reaching_past_a_perfect_score(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The band is clamped into ``[0, 1]``; nothing scores 1.05 and the count must not imply it."""
    # Arrange
    async with sessions.begin() as session:
        for confidence in (0.9, 0.96, 1.0):
            await seed_attempt(
                session,
                created_at=_DAY_TWO,
                kind=GenerationKind.NAME_VERIFICATION,
                name_candidate_strategy=NameStrategy.STRIPPED,
                name_candidate_rank=0,
                is_name_verified=True,
                match_confidence=confidence,
            )

    # Act
    async with sessions.begin() as session:
        analytics = await attempt_queries.name_analytics(session, threshold=1.0)

    # Assert — 0.96 and 1.0 are within 0.05 of a perfect score; 0.9 is not.
    assert analytics.near_threshold == 2


async def test_name_analytics_refuses_a_histogram_it_could_not_draw(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A programming error, raised rather than divided by zero halfway through a chart."""
    # Act / Assert
    async with sessions.begin() as session:
        with pytest.raises(ValueError, match="bucket"):
            await attempt_queries.name_analytics(session, bucket_count=0)
        with pytest.raises(ValueError, match="band"):
            await attempt_queries.name_analytics(session, band=-0.1)


# ---------------------------------------------------------------------------
# Users — honest field names
# ---------------------------------------------------------------------------
async def test_user_list_reports_last_order_not_last_seen(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three orders; the newest is the "last order".
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_ONE, state=OrderState.DELIVERED)
        await seed_order(
            session, user=user, created_at=_DAY_TWO, state=OrderState.FAILED, is_paid=False
        )
        await seed_order(session, user=user, created_at=_DAY_TWO, state=OrderState.GENERATING)

    # Act
    async with sessions.begin() as session:
        page = await users.list_users(
            session, filters=users.UserFilters(), request=PageRequest(limit=10)
        )
        total = await users.count_users(session, filters=users.UserFilters())

    # Assert — hand-computed: 3 orders, 2 of them paid states, first/last are the two days.
    item = page.items[0]
    assert (item.order_count, item.paid_order_count) == (3, 2)
    assert item.first_order_at == _DAY_ONE
    assert item.last_order_at == _DAY_TWO
    assert item.account_created_at == _DAY_ONE
    assert not hasattr(item, "last_seen_at")
    assert (total.total, total.is_exact) == (1, True)


async def test_user_detail_breaks_orders_down_by_state(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_ONE, state=OrderState.DELIVERED)
        await seed_order(session, user=user, created_at=_DAY_TWO, state=OrderState.DELIVERED)
        await seed_order(session, user=user, created_at=_DAY_TWO, state=OrderState.FAILED)

    # Act
    async with sessions.begin() as session:
        detail = await users.get_user_detail(session, _TELEGRAM_ID, now=_DAY_TWO)

    # Assert
    assert detail is not None
    assert dict(detail.orders_by_state) == {OrderState.DELIVERED: 2, OrderState.FAILED: 1}
    assert (detail.delivered_order_count, detail.failed_order_count) == (2, 1)


async def test_a_person_who_never_confirmed_an_order_has_no_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Still ``None``, but this test's subject changed under it and the old wording was false.

    It used to read "``users`` is written only by ``_ensure_user`` from ``_create_order``",
    and every clause of that is now wrong (C0-12). There are three writers —
    ``users_sql.ensure_user`` from ``_create_order`` AND from
    ``SqlUserProfiles.record_language``, ``credits.touch`` on every inbound update, and
    ``credits.set_blocked`` — so a ``users`` row is born at FIRST CONTACT. The subject of this
    test is therefore no longer somebody who chatted and abandoned a wizard: chatting is what
    mints the row. It is somebody who has never reached the bot at all, not even far enough to
    answer the language question.

    Which makes ``None`` a stronger claim than it was, and worth keeping: it must mean "we
    have never met this person", so the router's 404 is honest rather than an invented empty
    profile implying we hold nothing on somebody we do hold something on.
    """
    # Act
    async with sessions.begin() as session:
        detail = await users.get_user_detail(session, 12_345, now=_DAY_TWO)

    # Assert
    assert detail is None


async def test_the_user_list_left_joins_the_profile_and_still_lists_a_user_who_has_none(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """An INNER join here would be data loss wearing a filter's clothes.

    Two whole populations have a ``users`` row and no ``user_profiles`` row: everybody who has
    touched the bot since onboarding shipped without finishing it, and everybody whose
    ``/forget`` ran. An INNER join deletes both from the panel — and the second is the account
    most likely to be the subject of the support ticket that opened this screen, so the
    operator would be looking for a person the query has silently decided does not exist.

    ``is_profile_present`` is asserted as well as the nulls because a null phone number alone
    cannot tell "no profile row" from "a profile row that has not reached the contact step".
    """
    # Arrange — an account with no profile row at all.
    async with sessions.begin() as session:
        await seed_user(session, created_at=_DAY_ONE)

    # Act
    async with sessions.begin() as session:
        page = await users.list_users(
            session, filters=users.UserFilters(), request=PageRequest(limit=10)
        )

    # Assert — listed, flagged, and every profile field empty.
    assert [item.telegram_user_id for item in page.items] == [_TELEGRAM_ID]
    item = page.items[0]
    assert item.is_profile_present is False
    assert item.telegram_username is None
    assert item.first_name is None
    assert item.last_name is None
    assert item.phone_e164 is None
    assert item.phone_shared_at is None
    assert item.avatar_mime is None
    assert item.avatar_stored_at is None
    assert item.has_avatar is False


async def test_the_user_list_reports_the_profile_fields_when_there_is_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The join's positive half, field by field, because a silent ``None`` reads as "no data".

    A join that resolves but maps the wrong column is indistinguishable, on the screen, from a
    customer who shared nothing — the panel draws an empty row either way and nobody files a
    bug about a person who told us nothing. So every field the join carries is asserted
    against a value that could only have come from the profile row.

    ``telegram_username`` is asserted WITHOUT its ``@``: the sigil is a rendering decision and
    a stored one would make an operator's search for ``gulom`` miss the row it is on.
    """
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_profile(session, user=user)

    # Act
    async with sessions.begin() as session:
        page = await users.list_users(
            session, filters=users.UserFilters(), request=PageRequest(limit=10)
        )

    # Assert
    item = page.items[0]
    assert item.is_profile_present is True
    assert item.telegram_username == "gulomjon"
    assert (item.first_name, item.last_name) == ("Gʻulomjon", "Toshmatov")
    assert item.phone_e164 == _PHONE
    assert item.phone_shared_at == _DAY_ONE
    assert item.avatar_mime == "image/jpeg"
    assert item.avatar_stored_at == _DAY_TWO
    assert item.has_avatar is True


async def test_load_avatar_answers_none_for_an_unknown_user_and_for_one_with_no_photo(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The two arms the avatar route turns into its single 404, kept separable in the data.

    ``load_avatar`` answers ``None`` only when there is no ``users`` row at all; an account
    that exists and has never had a photo answers ``(user_id, None, None)``. The route
    collapses both into one 404 that does not echo the id, but the distinction has to live in
    the query rather than in a future rewrite, because "we have never heard of this account"
    and "this account has no avatar" are different facts and only one of them is about a
    person we know.

    The third row here is the one that matters most: a profile row that exists but never
    stored bytes must NOT report an avatar, or the panel draws an ``<img>`` at a URL that
    404s for every customer who has not set a profile photo.
    """
    # Arrange — an account with a profile row that has no avatar on it.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_profile(
            session, user=user, avatar_mime=None, avatar_stored_at=None, avatar_file_unique_id=None
        )

    # Act
    async with sessions.begin() as session:
        unknown = await users.load_avatar(session, 4_040_404)
        known = await users.load_avatar(session, _TELEGRAM_ID)

    # Assert
    assert unknown is None
    assert known == (user.id, None, None)


async def test_counting_users_does_not_pay_for_the_join(
    sessions: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    """``?withTotal=true`` must not join a table whose columns it does not select.

    ``count_users`` and ``list_users`` share ``_filtered``; only the list adds the profile
    (CONTRACTS §6). The count is the one query on this screen that can touch every row the
    filters match, up to the bounded cap, so a join added there is paid ten thousand times to
    answer a question about a number. It is also the easiest join in the codebase to add by
    accident, because the obvious refactor is to make both callers share one statement builder
    — which is why this is asserted against the SQL that actually executes rather than against
    a helper's source.

    ``credit_accounts`` is held to the same rule and for a sharper reason: it arrived as a
    THIRD outer join on the list, and the obvious way to add it — to ``_filtered``, where the
    filters already are — would have put it on the count as well, where nothing selects a
    column from it.

    Both directions are checked: a count that mentions either joined table is the regression,
    and a list that does NOT mention them would mean the assertion had stopped reading real SQL.
    """
    # Arrange — record every statement the engine sends to the driver.
    executed: list[str] = []

    def _record(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        executed.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        async with sessions.begin() as session:
            user = await seed_user(session, created_at=_DAY_ONE)
            await seed_profile(session, user=user)
            await seed_account(session, telegram_user_id=user.telegram_user_id)

        # Act
        async with sessions.begin() as session:
            executed.clear()
            await users.count_users(session, filters=users.UserFilters())
            counted = list(executed)
            executed.clear()
            await users.list_users(
                session, filters=users.UserFilters(), request=PageRequest(limit=10)
            )
            listed = list(executed)
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", _record)

    # Assert
    assert counted, "the count issued no statement at all"
    for joined in ("user_profiles", "credit_accounts"):
        assert not any(joined in statement for statement in counted), (joined, counted)
        assert any(joined in statement for statement in listed), (joined, listed)


async def test_user_filters_narrow_by_block_language_and_window(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        await seed_user(session, created_at=_DAY_ONE, is_blocked=True)
        await seed_user(session, telegram_user_id=7, created_at=_DAY_TWO, ui_language=Language.RU)

    # Act
    async with sessions.begin() as session:
        blocked = await users.list_users(
            session, filters=users.UserFilters(is_blocked=True), request=PageRequest(limit=10)
        )
        russian = await users.list_users(
            session,
            filters=users.UserFilters(ui_languages=(Language.RU,)),
            request=PageRequest(limit=10),
        )
        recent = await users.list_users(
            session,
            filters=users.UserFilters(
                window=TimeWindow(start=_DAY_TWO, end=_DAY_TWO + timedelta(days=1))
            ),
            request=PageRequest(limit=10),
        )
        exact = await users.list_users(
            session,
            filters=users.UserFilters(telegram_user_id=7),
            request=PageRequest(limit=10),
        )

    # Assert — a user with no orders at all still lists, with zeroed rollups.
    assert [item.telegram_user_id for item in blocked.items] == [_TELEGRAM_ID]
    assert [item.telegram_user_id for item in russian.items] == [7]
    assert [item.telegram_user_id for item in recent.items] == [7]
    assert exact.items[0].order_count == 0
    assert exact.items[0].last_order_at is None


async def test_has_balance_splits_the_list_and_never_metered_is_not_a_positive_balance(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The predicate behind the panel's "Has balance > 0" chip, on all three credit shapes.

    ``credit_accounts`` has no row until an account's first charge or grant, so there are three
    populations here and only two values of the filter. ``True`` is strictly positive and the
    never-metered account is excluded from it — the same call ``_list_item`` makes when it
    publishes ``credit_balance=None`` rather than ``0``. ``False`` is the literal complement, so
    the two answers add back up to the unfiltered page and no customer is stranded between the
    chip's on and off states.

    ``count_users`` is asserted beside ``list_users`` because the two share ``_filtered``: the
    predicate is a correlated ``EXISTS`` precisely so the count can narrow by it without the
    ``credit_accounts`` join ``test_counting_users_does_not_pay_for_the_join`` forbids there.
    """
    # Arrange — credits, metered to zero, and never metered at all.
    async with sessions.begin() as session:
        await seed_user(session, created_at=_DAY_ONE)
        await seed_user(session, telegram_user_id=7, created_at=_DAY_TWO)
        await seed_user(session, telegram_user_id=8, created_at=_DAY_TWO + timedelta(days=1))
        await seed_account(session, telegram_user_id=_TELEGRAM_ID, balance=2)
        await seed_account(session, telegram_user_id=7, balance=0)

    # Act
    async with sessions.begin() as session:

        async def listed(has_balance: bool | None) -> list[int]:
            page = await users.list_users(
                session,
                filters=users.UserFilters(has_balance=has_balance),
                request=PageRequest(limit=10),
            )
            return [item.telegram_user_id for item in page.items]

        unfiltered = await listed(None)
        positive = await listed(True)
        rest = await listed(False)
        counted = await users.count_users(session, filters=users.UserFilters(has_balance=True))

    # Assert — newest account first, and the two halves reassemble the whole.
    assert unfiltered == [8, 7, _TELEGRAM_ID]
    assert positive == [_TELEGRAM_ID]
    assert rest == [8, 7]
    assert sorted(positive + rest) == sorted(unfiltered)
    assert counted.total == 1


# ---------------------------------------------------------------------------
# Credits on the user row — the join, and the null that is not a zero
# ---------------------------------------------------------------------------
async def test_the_user_row_carries_its_credit_account_and_nulls_where_there_is_none(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``None`` and ``0`` are different answers, and the list must be able to say both.

    A user with no ``credit_accounts`` row has never been metered — the row is opened by the
    first charge or grant — and is still owed a whole rolling allowance. Reporting ``0`` for
    them says the opposite: that they have spent everything. The account exists for exactly
    one of the two users here, so a mapping that hardcoded either answer fails.
    """
    # Arrange
    async with sessions.begin() as session:
        await seed_user(session, created_at=_DAY_ONE)
        await seed_user(session, telegram_user_id=7, created_at=_DAY_TWO)
        await seed_account(
            session,
            telegram_user_id=_TELEGRAM_ID,
            balance=2,
            lifetime_granted=5,
            allowance_period_index=4,
        )

    # Act
    async with sessions.begin() as session:
        page = await users.list_users(
            session, filters=users.UserFilters(), request=PageRequest(limit=10)
        )
        detail = await users.get_user_detail(session, _TELEGRAM_ID, now=_DAY_TWO)

    # Assert
    by_id = {item.telegram_user_id: item for item in page.items}
    metered = by_id[_TELEGRAM_ID]
    assert (metered.credit_balance, metered.lifetime_credits_granted) == (2, 5)
    assert metered.allowance_period_index == 4
    assert metered.has_credit_account

    unmetered = by_id[7]
    assert unmetered.credit_balance is None
    assert unmetered.lifetime_credits_granted is None
    assert unmetered.allowance_period_index is None
    assert not unmetered.has_credit_account

    assert detail is not None
    assert detail.user.credit_balance == 2


@pytest.mark.parametrize(
    "granted", [0, 3], ids=["the-shipped-paywall-gives-nothing-away", "a-legacy-free-tier"]
)
async def test_the_detail_reports_the_projection_the_customer_is_shown_beside_the_stored_balance(
    sessions: async_sessionmaker[AsyncSession], granted: int
) -> None:
    """``creditsProjected`` is ``read_balance``'s answer under the CALLER's policy.

    Two things are asserted here and the second one was a bug this test pinned. First, the
    projection is computed from something other than the stored column: an account with a
    stored balance of ``0`` and no allowance yet minted is shown its whole free allowance by
    the bot, and an operator who saw only the column would tell the customer they have none.

    Second — and this is the correction — the allowance that appears is the POLICY'S, not a
    constant. This test used to call ``get_user_detail`` with no policy at all and assert
    ``credits_projected == DEFAULT_ENTITLEMENT_POLICY.allowance_credits``, which read as a
    fact about the customer's balance and was really a fact about a dataclass default. It
    made the admin router's real defect green: that router built its policy without an
    allowance, so once ``Settings.free_allowance_credits`` went to 0 with the paywall the
    panel added three songs to every customer forever — and because a zero allowance never
    stamps ``allowance_period_index``, "an allowance is due" never stops being true, so the
    overstatement was permanent rather than once a period. Parametrised over the shipped
    paywalled policy and a legacy free-tier one, the assertion is now about the number the
    caller asked for.
    """
    # Arrange — an opened account that has spent everything and has never had an allowance.
    async with sessions.begin() as session:
        await seed_user(session, created_at=_DAY_ONE)
        await seed_account(
            session, telegram_user_id=_TELEGRAM_ID, balance=0, allowance_period_index=None
        )

    # Act
    async with sessions.begin() as session:
        detail = await users.get_user_detail(
            session, _TELEGRAM_ID, now=_DAY_TWO, policy=EntitlementPolicy(allowance_credits=granted)
        )

    # Assert — the stored column says nothing left; the projection says what this deployment
    # actually gives away, which on the shipped paywall is nothing either.
    assert detail is not None
    assert detail.user.credit_balance == 0
    assert detail.credits_projected == granted
    assert detail.in_flight_render_count == 0


# ---------------------------------------------------------------------------
# ``?q=`` — what it matches, and the far more important half of what it does not
# ---------------------------------------------------------------------------
async def test_the_search_matches_a_substring_of_the_telegram_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two ids that share no substring, so a match cannot be an accident.
    async with sessions.begin() as session:
        await seed_user(session, created_at=_DAY_ONE)  # 99_000_111
        await seed_user(session, telegram_user_id=44_555_666, created_at=_DAY_TWO)

    # Act
    async with sessions.begin() as session:
        middle = await users.list_users(
            session, filters=users.UserFilters(search="000111"), request=PageRequest(limit=10)
        )
        counted = await users.count_users(session, filters=users.UserFilters(search="000111"))
        blank = await users.list_users(
            session, filters=users.UserFilters(search="   "), request=PageRequest(limit=10)
        )

    # Assert — and the count agrees with the page it labels, which is what a search applied
    # to only one of the two statements would break.
    assert [item.telegram_user_id for item in middle.items] == [_TELEGRAM_ID]
    assert counted.total == 1
    # A search box that has not been typed into must not empty the table.
    assert len(blank.items) == 2


async def test_the_search_matches_no_profile_column_at_all(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The refusal, asserted rather than assumed — this is a reveal bypass if it regresses.

    Every free-text column ``/users`` can reach lives on ``user_profiles`` and is masked at all
    four roles; §12.3 routes their plaintext through ``POST /reveal`` alone. A ``LIKE '%…%'``
    over any of them would let an operator with no reveal cell confirm a name or a phone number
    a few characters at a time, with no step-up, no budget unit and no audit row — so each one
    is probed here with a value that IS in the row and must still match nothing.

    The names carry U+02BB, correct Uzbek Latin orthography, so this cannot pass merely because
    the query folded a character the column did not.
    """
    # Arrange — one fully onboarded account, whose profile holds every searchable-looking value.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_profile(
            session,
            user=user,
            telegram_username="gulomjon",
            first_name="Gʻulom",
            last_name="Oʻktamov",
            phone_e164=_PHONE,
        )

    # Act
    async with sessions.begin() as session:
        found = {
            probe: await users.list_users(
                session, filters=users.UserFilters(search=probe), request=PageRequest(limit=10)
            )
            for probe in ("gulomjon", "Gʻulom", "Oʻktamov", "901234542", _PHONE)
        }

    # Assert
    for probe, page in found.items():
        assert page.items == (), probe


async def test_the_search_escapes_like_metacharacters_rather_than_widening(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``q=%`` must match nothing, not everything. The escaping is ``escape_like``'s job.

    Asserted here as well as in ``test_admin_sql.py`` because this is the caller that binds
    the pattern: a query that built its own ``LIKE`` without the ``ESCAPE`` clause would pass
    that unit test and return the whole table here.
    """
    # Arrange
    async with sessions.begin() as session:
        await seed_user(session, created_at=_DAY_ONE)

    # Act
    async with sessions.begin() as session:
        wildcard = await users.list_users(
            session, filters=users.UserFilters(search="%"), request=PageRequest(limit=10)
        )
        single = await users.list_users(
            session, filters=users.UserFilters(search="_"), request=PageRequest(limit=10)
        )

    # Assert — neither metacharacter appears in a decimal id, so both match nothing.
    assert wildcard.items == ()
    assert single.items == ()


# ---------------------------------------------------------------------------
# Segments on the user list — the document, the sort, and the exact count
# ---------------------------------------------------------------------------
#: A day after ``_DAY_THREE``, so every relative operator below measures from an instant the
#: fixture is entirely behind. Threaded into the compiler, never read from a clock.
_SEGMENT_NOW: Final[datetime] = datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
_DAY_THREE: Final[datetime] = datetime(2026, 3, 22, 9, 0, tzinfo=UTC)


def _segment(*rules: SegmentRule, sort: SegmentSortSpec = DEFAULT_SORT) -> CompiledSegment:
    """Compile a root ``all`` group.

    The compiler's own semantics are ``test_admin_segment.py``'s subject; what these tests
    need from it is a real predicate object — one the query layer can only apply or fail to
    apply, never reinterpret.
    """
    document = Segment(root=SegmentGroup(match=MatchMode.ALL, rules=rules), sort=sort)
    compiled = compile_segment(document, now=_SEGMENT_NOW, capabilities=segment_capabilities())
    assert is_ok(compiled), compiled
    return compiled.value


async def _walk(session: AsyncSession, *, filters: users.UserFilters, limit: int) -> list[int]:
    """Page a sorted list to its end, resuming through the tokens it mints. Ids, in order."""
    assert filters.sort is not None
    sort, kind = users.page_sort(
        SegmentSortSpec(key=filters.sort.key, direction=filters.sort.direction)
    )
    seen: list[int] = []
    cursor: SortedCursor | None = None
    while True:
        page = await users.list_users(
            session, filters=filters, request=PageRequest(limit=limit), cursor=cursor
        )
        seen.extend(item.telegram_user_id for item in page.items)
        if page.next_cursor is None:
            return seen
        decoded = decode_sorted_cursor(page.next_cursor, sort=sort, kind=kind)
        assert is_ok(decoded), decoded
        cursor = decoded.value


async def test_a_segment_narrows_the_page_and_the_count_and_is_anded_with_the_chips(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``BROADCAST_SPEC §1.7``: the document is a second filter, never a replacement.

    The chips are untouched, so a bookmarked URL keeps working; a segment beside one narrows
    further rather than winning. ``count_users`` is asserted next to every page because the
    two share ``_filtered`` — a segment applied to the list alone is how a two-row page gets
    labelled with the unfiltered total.
    """
    # Arrange — one account with no orders, one buyer, one barred buyer.
    async with sessions.begin() as session:
        quiet = await seed_user(session, created_at=_DAY_ONE)
        buyer = await seed_user(session, telegram_user_id=7, created_at=_DAY_TWO)
        barred = await seed_user(
            session, telegram_user_id=8, created_at=_DAY_THREE, is_blocked=True
        )
        await seed_order(session, user=buyer, created_at=_DAY_TWO)
        await seed_order(session, user=barred, created_at=_DAY_THREE)
        assert quiet.telegram_user_id == _TELEGRAM_ID

    has_ordered = _segment(SegmentRule("order_count", SegmentOp.GTE, 1))
    everyone = _segment()

    # Act
    async with sessions.begin() as session:

        async def listed(filters: users.UserFilters) -> list[int]:
            page = await users.list_users(session, filters=filters, request=PageRequest(limit=10))
            return [item.telegram_user_id for item in page.items]

        segmented = users.UserFilters(segment=has_ordered)
        with_chip = users.UserFilters(segment=has_ordered, is_blocked=True)
        chip_only = users.UserFilters(is_blocked=True)
        buyers = await listed(segmented)
        both = await listed(with_chip)
        chipped = await listed(chip_only)
        unfiltered = await listed(users.UserFilters(segment=everyone))
        counted = await users.count_users(session, filters=with_chip)

    # Assert — newest account first, and the intersection is narrower than either side.
    assert buyers == [8, 7]
    assert chipped == [8]
    assert both == [8]
    assert counted.total == 1
    # An empty root group compiles to no predicate at all, so it costs what no segment costs.
    assert everyone.predicate is None
    assert unfiltered == [8, 7, _TELEGRAM_ID]


async def test_the_audience_count_is_exact_where_the_screen_count_saturates(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``count_segment_exactly`` answers the one question a bounded total cannot.

    ``count_users`` stops at ``TOTAL_COUNT_CAP`` and says so, which is right for a screen and
    useless for "how many people will receive this": an operator authorising a send against
    "10,000+" is authorising a number the system knows is not the number. The cap is lowered
    to two here rather than ten thousand rows being seeded — the saturation is the behaviour
    under test, not the constant.
    """
    # Arrange — three accounts, all of them buyers.
    async with sessions.begin() as session:
        for offset, telegram_user_id in enumerate((_TELEGRAM_ID, 7, 8)):
            user = await seed_user(
                session,
                telegram_user_id=telegram_user_id,
                created_at=_DAY_ONE + timedelta(days=offset),
            )
            await seed_order(session, user=user, created_at=_DAY_TWO)
    monkeypatch.setattr(page_module, "TOTAL_COUNT_CAP", 2)
    filters = users.UserFilters(segment=_segment(SegmentRule("order_count", SegmentOp.GTE, 1)))

    # Act
    async with sessions.begin() as session:
        bounded = await users.count_users(session, filters=filters)
        exact = await users.count_segment_exactly(session, filters=filters)

    # Assert
    assert (bounded.total, bounded.is_exact) == (2, False)
    assert exact == 3


async def test_the_exact_count_narrows_by_the_same_filters_the_page_does(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The preview and the page must be one population, or the wizard previews a fiction."""
    # Arrange
    async with sessions.begin() as session:
        quiet = await seed_user(session, created_at=_DAY_ONE)
        buyer = await seed_user(session, telegram_user_id=7, created_at=_DAY_TWO)
        await seed_order(session, user=buyer, created_at=_DAY_TWO)
        assert quiet.telegram_user_id == _TELEGRAM_ID

    filters = users.UserFilters(segment=_segment(SegmentRule("order_count", SegmentOp.GTE, 1)))

    # Act
    async with sessions.begin() as session:
        page = await users.list_users(session, filters=filters, request=PageRequest(limit=10))
        exact = await users.count_segment_exactly(session, filters=filters)
        everyone = await users.count_segment_exactly(session, filters=users.UserFilters())

    # Assert
    assert [item.telegram_user_id for item in page.items] == [7]
    assert exact == 1
    assert everyone == 2


async def test_sorting_by_an_aggregate_orders_the_page_and_pages_through_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A registry sort key, walked one row at a time, losing and repeating nothing.

    The heaviest account is the OLDEST one, so the sorted order is not the default order
    reappearing under another name. The account that has never been delivered to is still on
    the list: every sortable expression is ``COALESCE``-d, so "never" sorts as zero rather
    than dropping out of an ordering it has no value for.
    """
    # Arrange — three delivered, one delivered, none; oldest account first.
    async with sessions.begin() as session:
        heavy = await seed_user(session, created_at=_DAY_ONE)
        light = await seed_user(session, telegram_user_id=7, created_at=_DAY_TWO)
        await seed_user(session, telegram_user_id=8, created_at=_DAY_THREE)
        for _ in range(3):
            await seed_order(session, user=heavy, created_at=_DAY_ONE)
        await seed_order(session, user=light, created_at=_DAY_TWO)

    ranked = _segment(sort=SegmentSortSpec(key="delivered_order_count", direction="desc"))
    sort, kind = users.page_sort(ranked.sort)
    filters = users.UserFilters(segment=ranked, sort=sort)

    # Act
    async with sessions.begin() as session:
        default_order = await users.list_users(
            session, filters=users.UserFilters(), request=PageRequest(limit=10)
        )
        whole = await users.list_users(session, filters=filters, request=PageRequest(limit=10))
        walked = await _walk(session, filters=filters, limit=1)
        narrowed = _segment(
            SegmentRule("delivered_order_count", SegmentOp.GTE, 1),
            sort=SegmentSortSpec(key="delivered_order_count", direction="desc"),
        )
        with_predicate = await _walk(
            session, filters=users.UserFilters(segment=narrowed, sort=sort), limit=1
        )

    # Assert — the sort is a different order from the default, and the walk agrees with it.
    assert kind is SortValueKind.INTEGER
    assert [item.telegram_user_id for item in default_order.items] == [8, 7, _TELEGRAM_ID]
    assert [item.telegram_user_id for item in whole.items] == [_TELEGRAM_ID, 7, 8]
    assert walked == [_TELEGRAM_ID, 7, 8]
    # The predicate still applies under a sort: the never-delivered account is gone, and the
    # order of the two that remain is unchanged.
    assert with_predicate == [_TELEGRAM_ID, 7]


async def test_sorting_by_an_instant_carries_an_aware_value_through_the_cursor(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The instant half of the sorted walk, ascending, with the epoch block at the front.

    A naive datetime coming back out of ``COALESCE`` would be caught by ``SortedCursor``'s own
    constructor rather than silently paging wrong, which is exactly why the walk below resumes
    through real tokens instead of asserting one page.
    """
    # Arrange — never ordered, ordered on day one, ordered on day two.
    async with sessions.begin() as session:
        early = await seed_user(session, created_at=_DAY_ONE)
        late = await seed_user(session, telegram_user_id=7, created_at=_DAY_TWO)
        await seed_user(session, telegram_user_id=8, created_at=_DAY_THREE)
        await seed_order(session, user=early, created_at=_DAY_ONE)
        await seed_order(session, user=late, created_at=_DAY_TWO)

    oldest_first = _segment(sort=SegmentSortSpec(key="last_order_at", direction="asc"))
    sort, kind = users.page_sort(oldest_first.sort)
    filters = users.UserFilters(segment=oldest_first, sort=sort)

    # Act
    async with sessions.begin() as session:
        whole = await users.list_users(session, filters=filters, request=PageRequest(limit=10))
        walked = await _walk(session, filters=filters, limit=1)

    # Assert — "never ordered" sorts as the epoch, which is the front of an ascending list.
    assert kind is SortValueKind.INSTANT
    assert [item.telegram_user_id for item in whole.items] == [8, _TELEGRAM_ID, 7]
    assert walked == [8, _TELEGRAM_ID, 7]


async def test_a_cursor_minted_under_one_ordering_cannot_resume_the_other(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Two orderings, two token shapes, and no way to hand one walk the other's position.

    ``decode_sorted_cursor`` is the boundary that turns this into a 422 for a request; a
    caller that reaches the query layer with the wrong token skipped that boundary, so this is
    a ``ValueError`` about our own code rather than a refusal aimed at an operator.
    """
    # Arrange
    async with sessions.begin() as session:
        await seed_user(session, created_at=_DAY_ONE)
    ranked = _segment(sort=SegmentSortSpec(key="order_count", direction="desc"))
    sort, _ = users.page_sort(ranked.sort)

    # Act / Assert
    async with sessions.begin() as session:
        with pytest.raises(ValueError, match="sorted cursor"):
            await users.list_users(
                session,
                filters=users.UserFilters(),
                request=PageRequest(limit=1),
                cursor=SortedCursor(k="order_count", d="desc", v=0, id=uuid4()),
            )
        with pytest.raises(ValueError, match="unsorted cursor"):
            await users.list_users(
                session,
                filters=users.UserFilters(segment=ranked, sort=sort),
                request=PageRequest(limit=1, cursor=Cursor(at=_DAY_ONE, id=uuid4())),
            )


def test_a_sort_that_contradicts_the_compiled_segment_is_refused() -> None:
    """One document, one order. A page ordered by a key the stored document does not name is a
    campaign preview describing an audience nobody will ever see in that order."""
    # Arrange
    ranked = _segment(sort=SegmentSortSpec(key="order_count", direction="desc"))
    agreeing, kind = users.page_sort(ranked.sort)

    # Act / Assert
    with pytest.raises(ValueError, match="contradicts"):
        users.UserFilters(segment=ranked, sort=SortSpec(key="joined_at", direction="desc"))
    with pytest.raises(ValueError, match="contradicts"):
        users.UserFilters(segment=ranked, sort=SortSpec(key="order_count", direction="asc"))
    assert users.UserFilters(segment=ranked, sort=agreeing).sort == agreeing
    assert kind is SortValueKind.INTEGER


def test_page_sort_translates_a_registry_sort_and_names_its_cursor_kind() -> None:
    """The bridge between two identically-shaped ``SortSpec`` dataclasses, in one place."""
    # Arrange / Act
    instant, instant_kind = users.page_sort(SegmentSortSpec(key="last_order_at", direction="asc"))
    integer, integer_kind = users.page_sort(
        SegmentSortSpec(key="topup_spend_minor", direction="desc")
    )

    # Assert
    assert (instant.key, instant.direction) == ("last_order_at", "asc")
    assert instant_kind is SortValueKind.INSTANT
    assert (integer.key, integer.direction) == ("topup_spend_minor", "desc")
    assert integer_kind is SortValueKind.INTEGER
    with pytest.raises(SegmentError):
        users.page_sort(SegmentSortSpec(key="ui_language", direction="asc"))


async def test_last_seen_at_is_filterable_but_never_sortable_and_never_published(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The registry's one asymmetry, asserted on all three of its halves.

    A PREDICATE over ``users.last_seen_at`` discloses only the bucket the operator themself
    chose — "quiet for 90 days" is the whole of a re-engagement campaign. A COLUMN or an
    ORDERING hands over a total activity ranking of identified accounts, which is the
    surveillance ``touch``-driven ``last_seen_at`` is withheld to prevent. Adding it to
    ``SORT_KEYS`` is a one-word edit, which is why this test exists.
    """
    # Arrange — one account silent since day one, one seen the day the window opens.
    async with sessions.begin() as session:
        await seed_user(session, created_at=_DAY_ONE, last_seen_at=_DAY_ONE - timedelta(days=200))
        await seed_user(session, telegram_user_id=7, created_at=_DAY_TWO, last_seen_at=_DAY_TWO)

    quiet = _segment(SegmentRule("last_activity_at", SegmentOp.NOT_WITHIN_LAST_DAYS, 90))

    # Act
    async with sessions.begin() as session:
        page = await users.list_users(
            session, filters=users.UserFilters(segment=quiet), request=PageRequest(limit=10)
        )
        counted = await users.count_segment_exactly(
            session, filters=users.UserFilters(segment=quiet)
        )

        # Assert — filterable …
        assert [item.telegram_user_id for item in page.items] == [_TELEGRAM_ID]
        assert counted == 1

        # … never sortable, at the registry and at the query builder …
        assert "last_activity_at" not in SORT_KEYS
        assert "last_activity_at" in FIELDS
        with pytest.raises(SegmentError):
            await users.list_users(
                session,
                filters=users.UserFilters(sort=SortSpec(key="last_activity_at", direction="desc")),
                request=PageRequest(limit=10),
            )

    # … and never on the row, no matter which filter put the row there.
    item = page.items[0]
    assert not hasattr(item, "last_seen_at")
    assert not hasattr(item, "last_activity_at")
    assert item.last_order_at is None


# ---------------------------------------------------------------------------
# Metrics — every number computed by hand from the fixture
# ---------------------------------------------------------------------------
async def test_orders_per_day_buckets_by_utc_day(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — day one: 2 orders, 1 delivered, 1 paid. Day two: 3 orders, 1 failed, 2 paid.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_ONE, state=OrderState.DELIVERED)
        await seed_order(
            session, user=user, created_at=_DAY_ONE, state=OrderState.DRAFT, is_paid=False
        )
        await seed_order(session, user=user, created_at=_DAY_TWO, state=OrderState.DELIVERED)
        await seed_order(session, user=user, created_at=_DAY_TWO, state=OrderState.GENERATING)
        await seed_order(
            session, user=user, created_at=_DAY_TWO, state=OrderState.FAILED, is_paid=False
        )

    # Act
    async with sessions.begin() as session:
        series = await metrics.orders_per_day(session)

    # Assert
    assert [
        (row.day.isoformat(), row.total, row.delivered, row.failed, row.paid) for row in series
    ] == [
        ("2026-03-20", 2, 1, 0, 1),
        ("2026-03-21", 3, 1, 1, 2),
    ]


async def test_delivery_outcome_divides_by_terminal_states_only(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — 2 delivered, 1 failed, 1 cancelled, 2 in flight. Terminal = 4, rate = 0.5.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        for state in (
            OrderState.DELIVERED,
            OrderState.DELIVERED,
            OrderState.FAILED,
            OrderState.CANCELLED,
            OrderState.GENERATING,
            OrderState.BRIEF_READY,
        ):
            await seed_order(session, user=user, created_at=_DAY_ONE, state=state)

    # Act
    async with sessions.begin() as session:
        outcome = await metrics.delivery_outcome(session)

    # Assert
    assert (outcome.total, outcome.delivered, outcome.failed, outcome.cancelled) == (6, 2, 1, 1)
    assert outcome.in_flight == 2
    assert outcome.success_rate == pytest.approx(0.5)


async def test_delivery_latency_takes_nearest_rank_percentiles(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — durations 10s, 20s, 30s, 40s. n=4, so p50 is rank ceil(2)=2 -> 20s and p95 is
    # rank ceil(3.8)=4 -> 40s.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        for seconds in (10, 20, 30, 40):
            await seed_order(
                session,
                user=user,
                created_at=_DAY_ONE,
                state=OrderState.DELIVERED,
                delivered_at=_DAY_ONE + timedelta(seconds=seconds),
            )
        # An order still in flight has no latency and must not join the sample.
        await seed_order(session, user=user, created_at=_DAY_ONE, state=OrderState.GENERATING)

    # Act
    async with sessions.begin() as session:
        latency = await metrics.delivery_latency(session)

    # Assert
    assert latency.sample_count == 4
    assert latency.p50_seconds == pytest.approx(20.0, abs=0.01)
    assert latency.p95_seconds == pytest.approx(40.0, abs=0.01)


async def test_delivery_latency_is_empty_when_nothing_was_delivered(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    async with sessions.begin() as session:
        latency = await metrics.delivery_latency(session)

    # Assert — no sample means no percentile, never a zero.
    assert latency == LatencySummary(sample_count=0, p50_seconds=None, p95_seconds=None)


async def test_failure_breakdown_shares_sum_to_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — 3 UPSTREAM_5XX, 2 RATE_LIMITED, 1 uncoded. Total 6.
    async with sessions.begin() as session:
        codes = ("UPSTREAM_5XX", "UPSTREAM_5XX", "UPSTREAM_5XX", "RATE_LIMITED", "RATE_LIMITED")
        for code in codes:
            await seed_attempt(session, created_at=_DAY_ONE, is_success=False, error_code=code)
        await seed_attempt(session, created_at=_DAY_ONE, is_success=False, error_code=None)
        # A success must never appear in a failure breakdown.
        await seed_attempt(session, created_at=_DAY_ONE, is_success=True)

    # Act
    async with sessions.begin() as session:
        breakdown = await metrics.failure_breakdown(session)

    # Assert
    assert [(row.error_code, row.count) for row in breakdown] == [
        ("UPSTREAM_5XX", 3),
        ("RATE_LIMITED", 2),
        (None, 1),
    ]
    assert breakdown[0].share == pytest.approx(0.5)
    assert sum(row.share for row in breakdown) == pytest.approx(1.0)


async def test_metrics_respect_their_window(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        await seed_order(session, user=user, created_at=_DAY_ONE, state=OrderState.DELIVERED)
        await seed_order(session, user=user, created_at=_DAY_TWO, state=OrderState.DELIVERED)
        await seed_attempt(session, created_at=_DAY_ONE, is_success=False, error_code="A")
        await seed_attempt(session, created_at=_DAY_TWO, is_success=False, error_code="B")

    # Act — the half-open window covers day two only.
    window = TimeWindow(start=_DAY_TWO, end=_DAY_TWO + timedelta(days=1))
    async with sessions.begin() as session:
        outcome = await metrics.delivery_outcome(session, window=window)
        series = await metrics.orders_per_day(session, window=window)
        breakdown = await metrics.failure_breakdown(session, window=window)

    # Assert
    assert outcome.total == 1
    assert [row.day.isoformat() for row in series] == ["2026-03-21"]
    assert [row.error_code for row in breakdown] == ["B"]


async def test_capabilities_are_measured_not_declared(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — an asset that records where its bytes live, and one that does not.
    async with sessions.begin() as session:
        user = await seed_user(session, created_at=_DAY_ONE)
        order = await seed_order(session, user=user, created_at=_DAY_ONE)
        await seed_asset(session, order=order, storage_key="kits/song.mp3")

    # Act
    async with sessions.begin() as session:
        capabilities = await metrics.read_capabilities(session)

    # Assert — the two false flags are Phase 3 and Phase 5; when their migrations land, this
    # assertion, the timeline's unavailable_sources and the SPA copy all change together.
    assert capabilities.is_asset_storage_key_recorded is True
    assert capabilities.is_cost_telemetry is False
    assert capabilities.is_latency_telemetry is False
    assert capabilities.is_chat_capture is True
    assert capabilities.is_payment_ledger is False
    assert capabilities.is_state_transition_log is False


# ---------------------------------------------------------------------------
# Migration 0009 — the index set, asserted without running the chain
# ---------------------------------------------------------------------------
def test_every_read_index_is_declared_on_the_model_not_only_in_the_migration() -> None:
    """The declaration site is the metadata, so ``create_all`` builds what production has.

    This used to grep migration 0009's source text, which is the shape of guard a bad edit
    changes in lockstep — and it passed while three of the five indexes it named were never
    chosen by Postgres and while ``create_all`` built none of them at all. Asserting against
    ``Base.metadata`` instead is what makes the unit suite's query plans the same plans the
    migrated schema has; ``test_migrations.py`` then compares the migrated database's
    indexes to this same metadata.
    """
    # Arrange / Act
    declared = {
        index.name: (table_name, tuple(column.name for column in index.columns))
        for table_name, table in Base.metadata.tables.items()
        for index in table.indexes
    }

    # Assert
    for name, table_name, columns in _EXPECTED_INDEXES:
        assert name in declared, f"{name} is not declared on a model"
        assert declared[name] == (table_name, columns), name


def test_no_index_leads_with_a_four_value_column() -> None:
    """``generation_attempts.kind`` has four members, so an index leading with it is a
    quarter of the table and Postgres walks ``created_at`` backwards instead. It was
    reviewed in only because SQLite's planner does take it."""
    # Arrange / Act
    declared = {index.name for index in Base.metadata.tables["generation_attempts"].indexes}

    # Assert
    assert "ix_generation_attempts_kind_created_at" not in declared


def test_the_index_columns_lead_with_the_filter_then_created_at_then_id() -> None:
    """A keyset list query orders by ``(created_at DESC, id DESC)``. An index that stops at
    ``created_at`` leaves the last sort term to a runtime sort on every page."""
    # Assert
    for name, _, columns in _EXPECTED_INDEXES:
        if name.endswith("failures_created_at"):
            # The partial index serves an aggregate, not a keyset page: no id term is wanted.
            continue
        assert columns[-2:] == ("created_at", "id"), name
