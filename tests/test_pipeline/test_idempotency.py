"""Keys must be stable across retries and different across genuinely different requests."""

from __future__ import annotations

from uuid import uuid4

from bayram.pipeline.events import PipelineStage
from bayram.pipeline.idempotency import KEY_DIGEST_CHARS, idempotency_key


def test_the_same_request_produces_the_same_key_every_time() -> None:
    # Arrange
    order_id = uuid4()

    # Act
    first = idempotency_key(order_id, PipelineStage.COMPOSING_SONG, 0)
    second = idempotency_key(order_id, PipelineStage.COMPOSING_SONG, 0)

    # Assert
    assert first == second


def test_a_name_re_roll_is_a_different_request() -> None:
    # Arrange
    order_id = uuid4()

    # Act
    first_take = idempotency_key(order_id, PipelineStage.COMPOSING_SONG, 0)
    re_roll = idempotency_key(order_id, PipelineStage.COMPOSING_SONG, 1)

    # Assert
    assert first_take != re_roll


def test_orders_never_share_a_key() -> None:
    # Arrange / Act
    left = idempotency_key(uuid4(), PipelineStage.RENDERING_GREETINGS, "bobo", 0)
    right = idempotency_key(uuid4(), PipelineStage.RENDERING_GREETINGS, "bobo", 0)

    # Assert
    assert left != right


def test_stages_never_share_a_key() -> None:
    # Arrange
    order_id = uuid4()

    # Act
    song = idempotency_key(order_id, PipelineStage.COMPOSING_SONG, 0)
    greeting = idempotency_key(order_id, PipelineStage.RENDERING_GREETINGS, 0)

    # Assert
    assert song != greeting


def test_the_key_is_short_enough_for_a_header_and_names_its_stage() -> None:
    # Arrange / Act
    key = idempotency_key(uuid4(), PipelineStage.COMPOSING_SONG, 0)

    # Assert
    assert key.startswith("bayram-composing_song-")
    assert len(key.rsplit("-", 1)[-1]) == KEY_DIGEST_CHARS
