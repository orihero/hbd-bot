"""Row/contract translation and the never-throw boundary. No database needed for most of it."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError, OperationalError

from hbd.contracts import (
    AssetKind,
    Language,
    NameCandidate,
    NameStrategy,
    Script,
    is_err,
    is_ok,
)
from hbd.db.guard import NotFoundError, not_found, run_guarded
from hbd.db.mapping import (
    asset_name_candidate_values,
    brief_identity_values,
    candidates_from_json,
    candidates_to_json,
    lyrics_from_payload,
    lyrics_to_payload,
    payload_for,
    to_generated_asset,
    to_recipient_name,
)
from hbd.db.models import AssetRow, BriefRow
from hbd.db.retention import RetentionClass, RetentionPolicy
from hbd.errors import ErrorCode, PipelineError, StorageError
from tests.conftest import (
    FIXED_NOW,
    UZBEK_NAME_CANONICAL,
    make_asset,
    make_lyrics,
    make_name,
)


# ---------------------------------------------------------------------------
# Candidate serialisation — the untrusted JSON boundary
# ---------------------------------------------------------------------------
def test_candidates_round_trip_with_ranks_preserved() -> None:
    # Arrange
    original = make_name().candidates

    # Act
    restored = candidates_from_json(candidates_to_json(original), name="x")

    # Assert
    assert restored == original


def test_candidates_from_json_rejects_a_malformed_stored_list() -> None:
    # Arrange — a row written by an older schema is external data, not a safe cast.
    corrupt = [{"text": "Gulomjon", "strategy": "not-a-strategy", "rank": 0}]

    # Act / Assert
    with pytest.raises(PydanticValidationError):
        candidates_from_json(corrupt, name="Gulomjon")


def test_candidates_from_json_rejects_a_null_column() -> None:
    # Act / Assert — a purged identity must fail loudly, not silently return ().
    with pytest.raises(PipelineError):
        candidates_from_json(None, name="Gulomjon")


def test_candidate_json_keeps_the_submitted_text_distinct_from_the_display_form() -> None:
    # Arrange
    name = make_name()

    # Act
    payload = candidates_to_json(name.candidates)

    # Assert — the submitted orthography is internal; the display form is not in it.
    assert name.display == UZBEK_NAME_CANONICAL
    assert payload[0]["text"] == "Gulomjon"
    assert payload[0]["text"] != name.display


# ---------------------------------------------------------------------------
# Lyrics
# ---------------------------------------------------------------------------
def test_lyrics_round_trip_through_the_asset_payload() -> None:
    # Arrange
    lyrics = make_lyrics()

    # Act
    restored = lyrics_from_payload(lyrics_to_payload(lyrics), order_id=uuid4())

    # Assert
    assert restored == lyrics
    assert restored.name_hook_sections[0].lines == (UZBEK_NAME_CANONICAL,)


def test_lyrics_from_payload_rejects_a_missing_payload() -> None:
    # Act / Assert
    with pytest.raises(PipelineError):
        lyrics_from_payload(None, order_id=uuid4())


def test_only_the_lyric_sheet_stores_a_payload(tmp_path: Path) -> None:
    # Arrange
    song = make_asset(tmp_path, path=tmp_path / "s.mp3", kind=AssetKind.SONG)
    sheet = make_asset(
        tmp_path,
        path=tmp_path / "l.txt",
        kind=AssetKind.LYRIC_SHEET,
        mime="text/plain",
        duration_s=0.0,
        loudness_lufs=None,
    )
    lyrics = make_lyrics()

    # Act / Assert — audio content lives in object storage, never in a row.
    assert payload_for(song, lyrics) is None
    assert payload_for(sheet, lyrics) is not None


# ---------------------------------------------------------------------------
# Asset mapping
# ---------------------------------------------------------------------------
def test_an_asset_row_without_a_candidate_maps_to_none() -> None:
    # Arrange — this is what a row looks like after the 90-day identity purge.
    row = AssetRow(
        kind=AssetKind.SONG,
        path="/tmp/song.mp3",
        mime="audio/mpeg",
        duration_s=120.0,
        sha256="a" * 64,
        name_candidate_text=None,
        name_candidate_strategy=None,
        name_candidate_rank=None,
    )

    # Act
    asset = to_generated_asset(row)

    # Assert
    assert asset.name_candidate is None
    assert asset.path == Path("/tmp/song.mp3")


def test_an_asset_row_with_a_candidate_maps_it_back() -> None:
    # Arrange
    row = AssetRow(
        kind=AssetKind.GREETING,
        path="/tmp/g.ogg",
        mime="audio/ogg",
        duration_s=30.0,
        sha256="b" * 64,
        name_candidate_text="Gulomjon",
        name_candidate_strategy=NameStrategy.STRIPPED,
        name_candidate_rank=0,
    )

    # Act
    asset = to_generated_asset(row)

    # Assert
    assert asset.name_candidate == NameCandidate(
        text="Gulomjon", strategy=NameStrategy.STRIPPED, rank=0
    )


def test_asset_name_candidate_values_nulls_all_three_columns_together() -> None:
    # Act
    values = asset_name_candidate_values(None)

    # Assert — a half-written candidate would map back to a broken NameCandidate.
    assert set(values.values()) == {None}


# ---------------------------------------------------------------------------
# Brief identity mapping
# ---------------------------------------------------------------------------
def test_brief_identity_values_keeps_display_and_lookup_key_apart() -> None:
    # Arrange
    name = make_name()

    # Act
    values = brief_identity_values(name, expires_at=FIXED_NOW)

    # Assert
    assert values["recipient_name_display"] == UZBEK_NAME_CANONICAL
    assert values["recipient_lookup_key"] == "gulomjon"
    assert values["recipient_script"] is Script.LATIN
    assert values["recipient_language"] is Language.UZ_LATN
    assert values["identity_purged_at"] is None


def test_a_purged_brief_row_cannot_be_mapped_back_to_a_recipient() -> None:
    # Arrange
    row = BriefRow(
        id=uuid4(),
        order_id=uuid4(),
        recipient_name_display=None,
        recipient_name_raw=None,
        recipient_lookup_key=None,
    )

    # Act / Assert
    with pytest.raises(PipelineError):
        to_recipient_name(row)


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------
async def test_run_guarded_wraps_a_success_in_ok() -> None:
    # Act
    result = await run_guarded("noop", _returning(7))

    # Assert
    assert is_ok(result)
    assert result.value == 7


async def test_run_guarded_passes_a_typed_error_through_unchanged() -> None:
    # Arrange
    original = not_found("order", order_id="abc")

    # Act
    result = await run_guarded("get", _raising(original))

    # Assert
    assert is_err(result)
    assert result.error is original
    assert result.error.is_retryable is False


async def test_run_guarded_marks_an_infrastructure_failure_retryable() -> None:
    # Arrange
    failure = OperationalError("SELECT 1", {}, Exception("connection reset"))

    # Act
    result = await run_guarded("get", _raising(failure))

    # Assert — a dropped connection succeeds on the next attempt.
    assert is_err(result)
    assert isinstance(result.error, StorageError)
    assert result.error.is_retryable is True


async def test_run_guarded_marks_a_constraint_violation_terminal() -> None:
    # Arrange
    failure = IntegrityError("INSERT", {}, Exception("duplicate key"))

    # Act
    result = await run_guarded("create", _raising(failure))

    # Assert — retrying a duplicate key just burns the retry budget.
    assert is_err(result)
    assert result.error.is_retryable is False


async def test_run_guarded_reports_a_schema_mismatch_as_invalid_input() -> None:
    # Arrange
    def _bad() -> None:
        candidates_from_json([{"text": "x", "strategy": "nope", "rank": 0}], name="x")

    async def _call() -> None:
        _bad()

    # Act
    result = await run_guarded("read", _call)

    # Assert
    assert is_err(result)
    assert result.error.error_code is ErrorCode.INVALID_INPUT


async def test_run_guarded_records_the_operation_name_in_context() -> None:
    # Arrange
    failure = OperationalError("SELECT 1", {}, Exception("boom"))

    # Act
    result = await run_guarded("list_orders_for_user", _raising(failure), telegram_user_id=5)

    # Assert — an operator needs to know which call failed, not just that one did.
    assert is_err(result)
    assert result.error.context["operation"] == "list_orders_for_user"
    assert result.error.context["telegram_user_id"] == 5


def test_not_found_is_terminal_and_user_safe() -> None:
    # Act
    error = not_found("kit", order_id="abc")

    # Assert
    assert isinstance(error, NotFoundError)
    assert error.is_terminal is True
    assert error.user_message_key == "error.invalid_input"


# ---------------------------------------------------------------------------
# Retention policy arithmetic
# ---------------------------------------------------------------------------
def test_policy_rejects_a_zero_day_period() -> None:
    # Act / Assert — a zero-day retention would purge on write.
    with pytest.raises(ValueError, match="positive integer"):
        RetentionPolicy(paid_audio_days=0)


def test_policy_expiry_is_derived_from_the_anchor() -> None:
    # Arrange
    policy = RetentionPolicy(paid_audio_days=10)

    # Act
    expiry = policy.expires_at(FIXED_NOW, RetentionClass.PAID_AUDIO)

    # Assert
    assert (expiry - FIXED_NOW).days == 10


def test_policy_is_frozen() -> None:
    # Arrange
    policy = RetentionPolicy()

    # Act / Assert
    with pytest.raises((AttributeError, TypeError)):
        policy.paid_audio_days = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _returning[T](value: T) -> Callable[[], Coroutine[Any, Any, T]]:
    """A zero-argument coroutine factory in the shape ``run_guarded`` expects."""

    async def _call() -> T:
        return value

    return _call


def _raising(error: BaseException) -> Callable[[], Coroutine[Any, Any, None]]:
    async def _call() -> None:
        raise error

    return _call
