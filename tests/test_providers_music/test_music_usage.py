"""The measured usage line, and the cost figure derived from it."""

from __future__ import annotations

import logging

import pytest

from hbd.providers.music.usage import (
    DEFAULT_MUSIC_USD_PER_MINUTE,
    USAGE_EVENT,
    MusicUsage,
    estimate_cost_usd,
    log_usage,
)
from tests.test_providers_music.conftest import usage_line


def test_cost_scales_linearly_with_rendered_duration() -> None:
    # Arrange / Act
    one_minute = estimate_cost_usd(60_000, usd_per_minute=0.15)
    two_minutes = estimate_cost_usd(120_000, usd_per_minute=0.15)

    # Assert
    assert one_minute == 0.15
    assert two_minutes == 0.30


def test_cost_is_zero_for_a_zero_length_render() -> None:
    assert estimate_cost_usd(0, usd_per_minute=DEFAULT_MUSIC_USD_PER_MINUTE) == 0.0


def test_cost_is_never_negative_for_nonsense_input() -> None:
    assert estimate_cost_usd(-5, usd_per_minute=0.15) == 0.0
    assert estimate_cost_usd(60_000, usd_per_minute=-1.0) == 0.0


def test_usage_line_carries_every_quantity_the_invoice_is_computed_from(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    logger = logging.getLogger("hbd.test.usage")
    usage = MusicUsage(
        provider="elevenlabs_music",
        operation="compose",
        model_id="music_v2",
        output_format="mp3_44100_128",
        chunk_count=7,
        total_duration_ms=120_000,
        elapsed_ms=41_000,
        outcome="ok",
        http_status=200,
        response_bytes=1_048_576,
        remote_id="song_abc123",
        estimated_cost_usd=0.3,
        name_chunk_index=3,
    )

    # Act
    with caplog.at_level(logging.INFO, logger="hbd.test.usage"):
        log_usage(logger, usage)

    # Assert
    line = usage_line(caplog.records, USAGE_EVENT)
    assert line["chunk_count"] == 7
    assert line["total_duration_ms"] == 120_000
    assert line["model_id"] == "music_v2"
    assert line["estimated_cost_usd"] == 0.3
    assert line["response_bytes"] == 1_048_576


def test_usage_is_immutable() -> None:
    # Arrange
    usage = MusicUsage(
        provider="p",
        operation="compose",
        model_id="m",
        output_format="f",
        chunk_count=1,
        total_duration_ms=3_000,
        elapsed_ms=1,
        outcome="ok",
    )

    # Act / Assert
    with pytest.raises((AttributeError, TypeError)):
        usage.chunk_count = 2  # type: ignore[misc]
