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
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import (
    AssetKind,
    Genre,
    Language,
    NameStrategy,
    Occasion,
    OrderState,
    Script,
    VoiceGender,
)
from hbd.db.admin import attempts as attempt_queries
from hbd.db.admin import metrics, orders, users
from hbd.db.admin.page import PageRequest
from hbd.db.admin.sql import TimeWindow
from hbd.db.admin.views import LatencySummary
from hbd.db.enums import GenerationKind
from hbd.db.mapping import to_order
from hbd.db.models import Base
from hbd.db.models.asset import AssetRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from hbd.db.retention import RetentionClass
from hbd.errors import PipelineError

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
    assert "chat" in {source.value for source in timeline.unavailable_sources}
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
        detail = await users.get_user_detail(session, _TELEGRAM_ID)

    # Assert
    assert detail is not None
    assert dict(detail.orders_by_state) == {OrderState.DELIVERED: 2, OrderState.FAILED: 1}
    assert (detail.delivered_order_count, detail.failed_order_count) == (2, 1)


async def test_a_person_who_never_confirmed_an_order_has_no_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``users`` is written only by ``_ensure_user`` from ``_create_order`` — so: no row."""
    # Act
    async with sessions.begin() as session:
        detail = await users.get_user_detail(session, 12_345)

    # Assert
    assert detail is None


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
    assert capabilities.is_chat_capture is False
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
