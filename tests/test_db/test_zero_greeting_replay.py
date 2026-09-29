"""A song-only kit must replay from the database, not be bought again.

``BAYRAM_GREETINGS_PER_KIT=0`` is the shipped default, and ``_build_kit`` used to demand at
least one greeting row. So ``get_kit`` answered ``not_found`` for every kit that setting
produced, the orchestrator's replay read that as "no kit yet", and a redelivered ARQ job
re-ran the whole pipeline and paid the music vendor a second time (IMAGE_VIDEO_SPEC §0.3).

The orchestrator's own replay tests could not see it: they run against
``FakeKitRepository``, which hands back the ``Kit`` object it was given and never
reassembles one from rows. These run the real ``SqlKitRepository`` under the pipeline.
"""

from __future__ import annotations

from pathlib import Path

from bayram.config import Settings
from bayram.contracts import is_ok
from bayram.db.repository import SqlKitRepository
from tests.test_db.conftest import build_kit, new_order
from tests.test_pipeline.conftest import Studio, value_of


async def test_a_zero_greeting_kit_round_trips_through_get_kit(
    repository: SqlKitRepository, tmp_path: Path
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)
    kit = build_kit(tmp_path, order.id, greeting_count=0)

    # Act
    saved = await repository.save_kit(kit)
    fetched = await repository.get_kit(order.id)

    # Assert
    assert is_ok(saved)
    assert is_ok(fetched)
    assert fetched.value.greetings == ()
    assert fetched.value.song.sha256 == kit.song.sha256


async def test_a_redelivered_song_only_job_replays_without_a_second_vendor_call(
    repository: SqlKitRepository, settings: Settings, tmp_path: Path
) -> None:
    # Arrange — the shipped configuration: a song with no greetings
    studio = Studio(
        settings.model_copy(
            update={
                "provider_max_attempts": 2,
                "provider_backoff_base_s": 0.01,
                "llm_parse_max_attempts": 2,
                "greetings_per_kit": 0,
            }
        ),
        tmp_path / "workspace",
    )
    order = new_order()
    await repository.create_order(order)
    first = value_of(await studio.pipeline(repository=repository).run(order))
    assert first.kit.greetings == ()
    assert len(studio.music.compose_calls) == 1

    # Act — ARQ redelivers the same job after a crash or a timeout
    second = value_of(await studio.pipeline(repository=repository).run(order))

    # Assert — the stored kit came back; the vendor was not paid again
    assert len(studio.music.compose_calls) == 1
    assert second.kit.song.sha256 == first.kit.song.sha256
    assert second.gaps == ()
