"""Portability primitives: UTC-safe timestamps, value-stable enums, engine construction.

Small surface, disproportionate blast radius. A naive datetime that survives a round trip
makes every retention comparison wrong by an unknown offset; an enum column that stores
member names instead of values makes a Python rename a silent data migration. Both are the
kind of defect that passes review and fails in production a quarter later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import QueuePool

from bayram.contracts import AssetKind, Language, OrderState
from bayram.db.base import Base, UtcDateTime, enum_type, utc_now
from bayram.db.engine import SQLITE_MEMORY_URL, create_engine, ping
from bayram.db.enums import GenerationKind, NameSource
from bayram.db.models import AssetRow, BriefRow, UserRow
from bayram.db.repository import SqlKitRepository
from bayram.db.retention import (
    DEFAULT_RETENTION_POLICY,
    RetentionClass,
    RetentionPolicy,
    resolve_retention_policy,
)
from tests.conftest import FIXED_NOW
from tests.test_db.conftest import MovableClock, new_order


# ---------------------------------------------------------------------------
# UtcDateTime
# ---------------------------------------------------------------------------
def test_utc_datetime_rejects_a_naive_value() -> None:
    # Arrange
    column = UtcDateTime()
    naive = datetime(2026, 3, 21, 9, 0, 0)

    # Act / Assert — guessing the zone is how a retention clock silently drifts.
    with pytest.raises(ValueError, match="naive datetime"):
        column.process_bind_param(naive, sqlite.dialect())


def test_utc_datetime_normalises_an_offset_value_to_utc() -> None:
    # Arrange
    column = UtcDateTime()
    tashkent = datetime(2026, 3, 21, 14, 0, 0, tzinfo=timezone(timedelta(hours=5)))

    # Act
    stored = column.process_bind_param(tashkent, sqlite.dialect())

    # Assert
    assert stored == datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)


def test_utc_datetime_reattaches_utc_on_the_way_out() -> None:
    # Arrange — SQLite hands back a naive value; Postgres does not.
    column = UtcDateTime()
    naive = datetime(2026, 3, 21, 9, 0, 0)

    # Act
    loaded = column.process_result_value(naive, sqlite.dialect())

    # Assert
    assert loaded == datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)


def test_utc_datetime_passes_none_through_in_both_directions() -> None:
    # Arrange
    column = UtcDateTime()
    dialect = sqlite.dialect()

    # Act / Assert — a nullable expiry must stay null, not become the epoch.
    assert column.process_bind_param(None, dialect) is None
    assert column.process_result_value(None, dialect) is None


async def test_a_stored_timestamp_round_trips_as_aware(
    repository: SqlKitRepository, clock: MovableClock
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)

    # Act
    fetched = await repository.get_order(order.id)

    # Assert
    assert fetched.value.created_at.tzinfo is not None  # type: ignore[union-attr]
    assert fetched.value.created_at == FIXED_NOW  # type: ignore[union-attr]


def test_utc_now_is_always_aware() -> None:
    # Act
    now = utc_now()

    # Assert
    assert now.tzinfo is not None


# ---------------------------------------------------------------------------
# enum_type
# ---------------------------------------------------------------------------
def test_enum_columns_store_the_value_not_the_member_name() -> None:
    # Arrange
    column = enum_type(Language)

    # Act
    stored = set(column.enums)

    # Assert — "uz_latn" is what every other layer speaks; "UZ_LATN" is a Python detail.
    assert stored == {"uz_latn", "uz_cyrl", "ru", "en"}


def test_enum_columns_are_not_native_database_enums() -> None:
    # Arrange / Act
    column = enum_type(OrderState)

    # Assert — altering a native Postgres enum in a migration takes a lock for no benefit.
    assert column.native_enum is False


async def test_an_enum_value_survives_a_database_round_trip(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    user_id = uuid4()
    async with sessions.begin() as session:
        session.add(UserRow(id=user_id, telegram_user_id=1, ui_language=Language.UZ_CYRL))

    # Act
    async with sessions() as session:
        stored = await session.scalar(
            sa.text("SELECT ui_language FROM users WHERE id = :id").bindparams(id=user_id)
        )
        loaded = await session.get(UserRow, user_id)

    # Assert
    assert stored == "uz_cyrl"
    assert loaded is not None
    assert loaded.ui_language is Language.UZ_CYRL


def test_a_row_repr_names_its_type_and_id() -> None:
    # Arrange
    row = AssetRow(id=uuid4(), kind=AssetKind.SONG)

    # Act
    text = repr(row)

    # Assert — enough to identify a row in a log line, and nothing personal in it.
    assert text.startswith("AssetRow(id=")


def test_constraint_names_are_deterministic() -> None:
    # Act — without a naming convention, SQLite's batch ALTER cannot drop by name.
    primary_key = Base.metadata.tables["orders"].primary_key

    # Assert
    assert primary_key.name == "pk_orders"


# ---------------------------------------------------------------------------
# Row helper properties
# ---------------------------------------------------------------------------
def test_a_brief_reports_its_identity_as_purged_once_the_sweep_has_stamped_it() -> None:
    """The audit column is the proof, and since the own-lyrics path it is the ONLY proof."""
    # Arrange
    row = BriefRow(recipient_name_display=None, identity_purged_at=datetime.now(UTC))

    # Act / Assert
    assert row.is_identity_purged is True


def test_a_brief_that_never_held_a_name_does_not_claim_to_have_been_purged() -> None:
    """A bring-your-own-lyrics order collects no identity, so there is none to erase.

    This used to report True, because a null display name was taken as proof the 90-day
    sweep had run. It would now tell an operator — and any erasure proof built on this
    property — that personal data was deleted on schedule when none was ever held.
    """
    # Arrange
    row = BriefRow(recipient_name_display=None, identity_purged_at=None)

    # Act / Assert
    assert row.is_identity_purged is False


def test_a_brief_with_a_name_and_no_purge_stamp_is_not_purged() -> None:
    # Arrange
    row = BriefRow(recipient_name_display="Gulomjon", identity_purged_at=None)

    # Act / Assert
    assert row.is_identity_purged is False
    assert row.is_note_purged is False


def test_only_a_user_confirmed_dictionary_entry_is_personal_data() -> None:
    # Act / Assert — provenance decides retention, so this predicate is load-bearing.
    assert NameSource.USER_CONFIRMED.is_personal_data is True
    assert NameSource.CURATED.is_personal_data is False
    assert NameSource.LLM_GENERATED.is_personal_data is False


def test_name_verification_is_a_distinct_generation_kind() -> None:
    # Act / Assert — it is our own verdict, not a vendor render, but shares the table so
    # the tuning query sees a render and its verdict side by side.
    assert GenerationKind.NAME_VERIFICATION.value == "name_verification"
    assert len(set(GenerationKind)) == len(GenerationKind)


# ---------------------------------------------------------------------------
# Engine construction
# ---------------------------------------------------------------------------
def test_create_engine_omits_pool_arguments_for_sqlite() -> None:
    # Act — aiosqlite rejects pool_size, so passing the Postgres tuning would break tests.
    engine = create_engine(SQLITE_MEMORY_URL)

    # Assert
    assert engine.dialect.name == "sqlite"


def test_create_engine_configures_a_pool_for_postgres() -> None:
    # Act — no connection is opened, so this needs no server.
    engine = create_engine("postgresql+asyncpg://user:pw@localhost:5432/db")

    # Assert
    assert engine.dialect.name == "postgresql"
    assert isinstance(engine.pool, QueuePool)
    assert engine.pool.size() > 0


async def test_ping_reports_false_rather_than_raising_when_the_database_is_gone() -> None:
    # Arrange — a health probe that crashes its caller is worse than one that says "down".
    engine = create_engine("postgresql+asyncpg://user:pw@127.0.0.1:1/nope")

    # Act
    is_reachable = await ping(engine)
    await engine.dispose()

    # Assert
    assert is_reachable is False


async def test_ping_reports_true_against_a_live_database(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    engine = sessions.kw["bind"]

    # Act
    is_reachable = await ping(engine)

    # Assert
    assert is_reachable is True


# ---------------------------------------------------------------------------
# Retention policy plumbing
# ---------------------------------------------------------------------------
def test_days_for_maps_every_retention_class() -> None:
    # Arrange
    policy = DEFAULT_RETENTION_POLICY

    # Act / Assert — an unmapped class would silently fall through to None.
    assert policy.days_for(RetentionClass.PAID_AUDIO) == 365
    assert policy.days_for(RetentionClass.FREE_OUTPUT) == 30
    assert policy.days_for(RetentionClass.EPHEMERAL) == 7


def test_policy_rejects_a_non_integer_period() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="positive integer"):
        RetentionPolicy(brief_text_days=True)


def test_resolve_returns_the_legal_defaults_when_no_settings_are_supplied() -> None:
    # Act
    policy = resolve_retention_policy(None)

    # Assert
    assert policy == DEFAULT_RETENTION_POLICY


def test_resolve_ignores_a_settings_object_without_retention_fields(settings: object) -> None:
    # Act — Settings does not carry these yet; the defaults must apply, not a crash.
    policy = resolve_retention_policy(settings)

    # Assert
    assert policy == DEFAULT_RETENTION_POLICY


def test_resolve_honours_retention_fields_once_settings_grows_them() -> None:
    # Arrange — a stand-in for the Settings fields the integrator will add.
    class _SettingsWithRetention:
        retention_paid_audio_days = 400
        retention_recipient_identity_days = 60

    # Act
    policy = resolve_retention_policy(_SettingsWithRetention())

    # Assert
    assert policy.paid_audio_days == 400
    assert policy.recipient_identity_days == 60
    assert policy.free_output_days == DEFAULT_RETENTION_POLICY.free_output_days


def test_the_abandoned_draft_cutoff_looks_backwards() -> None:
    # Arrange
    policy = RetentionPolicy(abandoned_draft_days=14)

    # Act
    cutoff = policy.abandoned_draft_cutoff(FIXED_NOW)

    # Assert
    assert (FIXED_NOW - cutoff).days == 14
