"""The fake renders REAL silence — bytes ffmpeg can actually decode."""

from __future__ import annotations

from hbd.contracts import Chunk, HealthState, MusicProvider, is_err, is_ok
from hbd.errors import ProviderUnavailableError
from hbd.providers.music.fake import (
    MP3_FRAME_DURATION_S,
    SILENT_MP3_FRAME,
    FakeMusicProvider,
    silent_mp3,
)
from tests.test_providers_music.conftest import simple_plan

MP3_SYNC_WORD = b"\xff\xfb"


# ---------------------------------------------------------------------------
# The bytes
# ---------------------------------------------------------------------------
def test_the_clip_starts_with_a_valid_mpeg_layer_iii_frame_header() -> None:
    # Arrange / Act
    data = silent_mp3(1.0)

    # Assert: sync word plus MPEG-1 Layer III, no CRC.
    assert data.startswith(MP3_SYNC_WORD)


def test_every_frame_is_the_length_its_own_header_declares() -> None:
    # Arrange: 32 kbps at 44.1 kHz means 104-byte frames.
    data = silent_mp3(1.0)

    # Assert
    assert len(SILENT_MP3_FRAME) == 104
    assert len(data) % 104 == 0
    for offset in range(0, len(data), 104):
        assert data[offset : offset + 2] == MP3_SYNC_WORD


def test_the_clip_length_tracks_the_requested_duration() -> None:
    # Arrange / Act: frames are 26.12ms, so a clip lands within one frame of the ask.
    one_second = silent_mp3(1.0)
    two_seconds = silent_mp3(2.0)

    # Assert
    assert len(two_seconds) > len(one_second)
    for data, requested in ((one_second, 1.0), (two_seconds, 2.0)):
        rendered = len(data) / len(SILENT_MP3_FRAME) * MP3_FRAME_DURATION_S
        assert 0 <= rendered - requested < MP3_FRAME_DURATION_S


def test_a_zero_length_request_still_yields_one_playable_frame() -> None:
    assert silent_mp3(0.0) == SILENT_MP3_FRAME
    assert silent_mp3(-5.0) == SILENT_MP3_FRAME


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------
def test_the_fake_satisfies_the_frozen_music_provider_protocol() -> None:
    assert isinstance(FakeMusicProvider(), MusicProvider)


async def test_compose_returns_audio_whose_duration_matches_its_own_bytes() -> None:
    # Arrange
    provider = FakeMusicProvider(clip_duration_s=2.0)

    # Act
    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=1.0)

    # Assert
    assert is_ok(result)
    frames = len(result.value.data) // len(SILENT_MP3_FRAME)
    assert result.value.duration_s == frames * MP3_FRAME_DURATION_S
    assert result.value.mime == "audio/mpeg"


async def test_each_render_gets_its_own_stored_song_handle() -> None:
    # Arrange
    provider = FakeMusicProvider()

    # Act
    first = await provider.compose(simple_plan(), idempotency_key="a", timeout_s=1.0)
    second = await provider.compose(simple_plan(), idempotency_key="b", timeout_s=1.0)

    # Assert
    assert is_ok(first) and is_ok(second)
    assert first.value.remote_id != second.value.remote_id


async def test_calls_are_recorded_so_a_pipeline_test_can_assert_on_them() -> None:
    # Arrange
    provider = FakeMusicProvider()
    plan = simple_plan()

    # Act
    await provider.compose(plan, idempotency_key="order-1", timeout_s=1.0)
    await provider.inpaint(
        plan, source_song_id="s1", chunk_index=1, idempotency_key="order-1-reroll", timeout_s=1.0
    )

    # Assert
    assert [call.operation for call in provider.calls] == ["compose", "inpaint"]
    assert provider.calls[1].source_song_id == "s1"
    assert provider.calls[1].chunk_index == 1
    assert "FakeCall" in repr(provider.calls[0])


async def test_the_recorded_call_list_is_a_snapshot_not_the_live_list() -> None:
    # Arrange
    provider = FakeMusicProvider()
    await provider.compose(simple_plan(), idempotency_key="k", timeout_s=1.0)

    # Act
    snapshot = provider.calls
    await provider.compose(simple_plan(), idempotency_key="k2", timeout_s=1.0)

    # Assert
    assert len(snapshot) == 1
    assert len(provider.calls) == 2


async def test_the_fake_applies_the_same_plan_guard_as_the_real_adapter() -> None:
    # Arrange: a blank name chunk must fail at test speed, not in production.
    provider = FakeMusicProvider()
    plan = simple_plan().with_chunk_replaced(
        1, Chunk(text=" ", duration_ms=8_000, is_name_chunk=True)
    )

    # Act
    result = await provider.compose(plan, idempotency_key="k", timeout_s=1.0)

    # Assert
    assert is_err(result)


async def test_an_injected_failure_lets_a_caller_exercise_its_retry_ladder() -> None:
    # Arrange
    failure = ProviderUnavailableError("vendor is down", provider="fake_music")
    provider = FakeMusicProvider(failure=failure)

    # Act
    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=1.0)

    # Assert
    assert is_err(result)
    assert result.is_retryable


async def test_inpaint_rejects_a_chunk_index_that_does_not_exist() -> None:
    # Arrange
    provider = FakeMusicProvider()

    # Act
    result = await provider.inpaint(
        simple_plan(), source_song_id="s1", chunk_index=7, idempotency_key="k", timeout_s=1.0
    )

    # Assert
    assert is_err(result)


async def test_regenerate_chunk_records_the_new_orthography_it_was_given() -> None:
    # Arrange
    provider = FakeMusicProvider()
    plan = simple_plan(name_text="Gulomjon")

    # Act
    result = await provider.regenerate_chunk(
        plan,
        source_song_id="s1",
        chunk_index=1,
        new_text="Ghoolomjon",
        idempotency_key="k",
        timeout_s=1.0,
    )

    # Assert
    assert is_ok(result)
    assert provider.calls[-1].plan.chunks[1].text == "Ghoolomjon"
    assert plan.chunks[1].text == "Gulomjon"


async def test_regenerate_chunk_rejects_blank_text() -> None:
    # Arrange
    provider = FakeMusicProvider()

    # Act
    result = await provider.regenerate_chunk(
        simple_plan(),
        source_song_id="s1",
        chunk_index=1,
        new_text="",
        idempotency_key="k",
        timeout_s=1.0,
    )

    # Assert
    assert is_err(result)


async def test_health_is_reportable_and_configurable() -> None:
    # Arrange
    provider = FakeMusicProvider(health_state=HealthState.DEGRADED)

    # Act
    result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.DEGRADED


async def test_aclose_is_a_no_op_so_callers_need_no_type_check() -> None:
    # Arrange
    provider = FakeMusicProvider()

    # Act
    await provider.aclose()

    # Assert: closing is safe and leaves the fake usable.
    assert is_ok(await provider.compose(simple_plan(), idempotency_key="k", timeout_s=1.0))


async def test_the_fake_guards_the_plan_on_inpaint_too() -> None:
    # Arrange
    provider = FakeMusicProvider()
    plan = simple_plan().with_chunk_replaced(
        1, Chunk(text="", duration_ms=8_000, is_name_chunk=True)
    )

    # Act
    result = await provider.inpaint(
        plan, source_song_id="s1", chunk_index=1, idempotency_key="k", timeout_s=1.0
    )

    # Assert
    assert is_err(result)


async def test_an_injected_failure_applies_to_the_re_roll_path_as_well() -> None:
    # Arrange
    provider = FakeMusicProvider(
        failure=ProviderUnavailableError("vendor is down", provider="fake_music")
    )

    # Act
    result = await provider.inpaint(
        simple_plan(), source_song_id="s1", chunk_index=1, idempotency_key="k", timeout_s=1.0
    )

    # Assert
    assert is_err(result)
    assert result.is_retryable
