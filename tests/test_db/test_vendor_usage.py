"""``vendor_usage``: the row, the sink that writes it, and the cutoff that bounds it.

Four properties are asserted here and each one is a defect this table exists to avoid:

* the sink writes what the adapter measured AND what the scope attributed, without either
  half being passed through a provider signature;
* a sink whose write fails logs and returns, because a vendor call must never fail because
  a metrics row did not persist;
* ``cost_usd`` and ``cost_source`` are both-or-neither, enforced by the database rather than
  by four adapters remembering;
* rows past 400 days are deleted and newer ones are not, so an append-only telemetry table
  stays bounded without a retention clock it has no right to claim.

The privacy question this table raises is answered in
``tests/test_db/test_privacy_constraints.py``, where its absence from both of that file's
sets is recorded as a decision.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import CostSource, UsageTask, Vendor, VendorOperation, is_ok
from hbd.db.models.vendor_usage import VendorUsageRow
from hbd.db.purge import VENDOR_USAGE_RETENTION_DAYS, purge_expired
from hbd.db.vendor_usage import DbUsageSink
from hbd.logging import correlation_scope
from hbd.usage import VendorUsage, usage_scope

NOW: Final[datetime] = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
_ORDER_ID: Final[UUID] = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _usage(**overrides: object) -> VendorUsage:
    values: dict[str, object] = {
        "vendor": Vendor.OPENROUTER,
        "operation": VendorOperation.CHAT_COMPLETION,
        "provider": "openai-compat",
        "is_success": True,
    }
    values.update(overrides)
    return VendorUsage(**values)  # type: ignore[arg-type]


async def _rows(sessions: async_sessionmaker[AsyncSession]) -> list[VendorUsageRow]:
    async with sessions() as session:
        result = await session.execute(sa.select(VendorUsageRow).order_by(VendorUsageRow.id))
        return list(result.scalars().all())


async def _count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return (
            await session.execute(sa.select(sa.func.count()).select_from(VendorUsageRow))
        ).scalar_one()


# ---------------------------------------------------------------------------
# The sink
# ---------------------------------------------------------------------------
async def test_the_sink_writes_one_row_carrying_everything_the_adapter_measured(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    sink = DbUsageSink(sessions)

    # Act
    await sink.record(
        _usage(
            model_id="google/gemma-4-31b-it:free",
            prompt_tokens=140,
            completion_tokens=60,
            total_tokens=200,
            latency_ms=812,
            http_status=200,
            cost_usd=0.000123,
            cost_source=CostSource.VENDOR_REPORTED,
        )
    )

    # Assert
    rows = await _rows(sessions)
    assert len(rows) == 1
    row = rows[0]
    assert row.vendor is Vendor.OPENROUTER
    assert row.operation is VendorOperation.CHAT_COMPLETION
    assert row.provider == "openai-compat"
    assert row.model_id == "google/gemma-4-31b-it:free"
    assert row.total_tokens == 200
    assert row.latency_ms == 812
    assert row.http_status == 200
    assert row.cost_usd == pytest.approx(0.000123)
    assert row.cost_source is CostSource.VENDOR_REPORTED


async def test_the_sink_reads_the_order_and_the_task_from_the_scope_it_is_called_inside(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the whole point of the contextvar: no provider signature names an order.
    sink = DbUsageSink(sessions)

    # Act
    with usage_scope(order_id=_ORDER_ID), usage_scope(task=UsageTask.SONG):
        await sink.record(_usage(vendor=Vendor.ELEVENLABS))

    # Assert
    row = (await _rows(sessions))[0]
    assert row.order_id == _ORDER_ID
    assert row.task is UsageTask.SONG


async def test_a_call_made_outside_any_scope_stores_two_nulls_rather_than_an_invented_order(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a health probe is a real call and belongs to nobody.
    sink = DbUsageSink(sessions)

    # Act
    await sink.record(_usage(operation=VendorOperation.HEALTH))

    # Assert
    row = (await _rows(sessions))[0]
    assert row.order_id is None
    assert row.task is None


async def test_the_bound_correlation_id_is_stored_so_a_log_line_and_a_row_can_be_joined(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    sink = DbUsageSink(sessions)

    # Act
    with correlation_scope("abc123"):
        await sink.record(_usage())

    # Assert
    row = (await _rows(sessions))[0]
    assert row.correlation_id == "abc123"


async def test_an_unbound_correlation_id_is_stored_as_null_and_never_as_the_dash_sentinel(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — "-" is what hbd.logging returns when nothing is bound. Stored verbatim it
    # would group, sort and join like a real id, and be counted as one request.
    sink = DbUsageSink(sessions)

    # Act
    await sink.record(_usage())

    # Assert
    row = (await _rows(sessions))[0]
    assert row.correlation_id is None


async def test_a_failed_telemetry_write_is_logged_and_does_not_reach_the_caller(
    sessions: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange — a session factory that cannot open a session at all, which is what a database
    # that has gone away looks like from here.
    class _BrokenSessions:
        def begin(self) -> AsyncSession:
            raise OSError("connection refused")

    sink = DbUsageSink(_BrokenSessions())  # type: ignore[arg-type]

    # Act — an adapter awaits this on every return path, including its failure paths, so an
    # exception escaping here would cost the customer their song over a metrics row.
    with caplog.at_level(logging.WARNING, logger="hbd.db.vendor_usage"):
        await sink.record(_usage())

    # Assert — nothing raised, the operator can still see that instrumentation is broken,
    # and no row was written by the working factory either.
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert warnings, "a lost telemetry row must be visible, not silent"
    assert await _count(sessions) == 0


# ---------------------------------------------------------------------------
# The cost constraint
# ---------------------------------------------------------------------------
async def test_a_priced_call_stores_the_figure_and_its_provenance_together(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    async with sessions.begin() as session:
        session.add(
            VendorUsageRow(
                id=uuid4(),
                vendor=Vendor.ELEVENLABS,
                operation=VendorOperation.MUSIC_COMPOSE,
                provider="elevenlabs_music",
                is_success=True,
                cost_usd=0.45,
                cost_source=CostSource.ESTIMATED,
                created_at=NOW,
            )
        )

    # Assert
    row = (await _rows(sessions))[0]
    assert row.cost_usd == pytest.approx(0.45)
    assert row.cost_source is CostSource.ESTIMATED


async def test_an_unpriced_call_stores_no_cost_at_all_rather_than_a_zero(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act — the shipped default: no rate is configured, so transcription and TTS write this.
    async with sessions.begin() as session:
        session.add(
            VendorUsageRow(
                id=uuid4(),
                vendor=Vendor.ELEVENLABS,
                operation=VendorOperation.TRANSCRIPTION,
                provider="elevenlabs_scribe",
                is_success=True,
                request_bytes=48_000,
                created_at=NOW,
            )
        )

    # Assert — NULL means "not priced here"; 0.0 would mean "free", which is a lie.
    row = (await _rows(sessions))[0]
    assert row.cost_usd is None
    assert row.cost_source is None
    assert row.audio_ms is None, "bytes times an assumed bitrate is a fabricated duration"


@pytest.mark.parametrize(
    ("cost_usd", "cost_source"),
    [(0.12, None), (None, CostSource.DERIVED)],
    ids=["a cost with no provenance", "a provenance with no cost"],
)
async def test_the_database_refuses_a_cost_and_a_source_that_do_not_travel_together(
    sessions: async_sessionmaker[AsyncSession],
    cost_usd: float | None,
    cost_source: CostSource | None,
) -> None:
    # Arrange — an operator cannot read a dollar figure whose trust level is unknown, and
    # four adapters remembering the pairing is four places it can stop being true.
    row = VendorUsageRow(
        id=uuid4(),
        vendor=Vendor.GEMINI,
        operation=VendorOperation.CHAT_COMPLETION,
        provider="gemini",
        is_success=True,
        cost_usd=cost_usd,
        cost_source=cost_source,
        created_at=NOW,
    )

    # Act / Assert
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            session.add(row)


# ---------------------------------------------------------------------------
# The cutoff
# ---------------------------------------------------------------------------
async def _seed(
    sessions: async_sessionmaker[AsyncSession], *, created_at: datetime, is_fake: bool = False
) -> UUID:
    row_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            VendorUsageRow(
                id=row_id,
                vendor=Vendor.FAKE if is_fake else Vendor.OPENROUTER,
                operation=VendorOperation.CHAT_COMPLETION,
                provider="fake_llm" if is_fake else "openai-compat",
                is_fake=is_fake,
                is_success=True,
                created_at=created_at,
            )
        )
    return row_id


async def test_a_telemetry_row_past_thirteen_months_is_deleted_by_the_sweep(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await _seed(sessions, created_at=NOW)

    # Act
    outcome = await purge_expired(
        sessions, now=NOW + timedelta(days=VENDOR_USAGE_RETENTION_DAYS + 1)
    )

    # Assert
    assert is_ok(outcome), outcome
    assert outcome.value.vendor_usage_deleted == 1
    assert await _count(sessions) == 0


async def test_a_telemetry_row_inside_the_cutoff_survives_the_sweep_that_deletes_an_older_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one row old enough to go and one written a year later. Thirteen months is
    # chosen so a year-over-year comparison still has last year to compare against.
    await _seed(sessions, created_at=NOW - timedelta(days=VENDOR_USAGE_RETENTION_DAYS + 10))
    survivor = await _seed(sessions, created_at=NOW - timedelta(days=360))

    # Act
    outcome = await purge_expired(sessions, now=NOW)

    # Assert — the sweep is a cutoff, not a truncation.
    assert is_ok(outcome), outcome
    assert outcome.value.vendor_usage_deleted == 1
    remaining = await _rows(sessions)
    assert [row.id for row in remaining] == [survivor]


async def test_the_sweeps_own_record_stores_the_vendor_usage_count(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the panel reads a stored row, never a log line, so a sweep whose count has
    # nowhere to go is a backlog reported as zero.
    from hbd.db.models.purge_run import PurgeRunRow

    # Act / Assert
    assert "vendor_usage_deleted" in PurgeRunRow.__table__.columns


async def test_a_fake_provider_run_is_recorded_and_flagged_rather_than_left_invisible(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act — HBD_USE_FAKE_PROVIDERS still writes rows; no rows at all could not be
    # told apart from a deployment nobody instrumented.
    await _seed(sessions, created_at=NOW, is_fake=True)

    # Assert
    row = (await _rows(sessions))[0]
    assert row.is_fake is True
    assert row.vendor is Vendor.FAKE
