"""The operator's Redis switches (IMAGE_VIDEO_SPEC §4.5)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from bayram.db.enums import MediaBackend, MediaSku
from bayram.errors import StorageError
from bayram.media.overrides import (
    GPU_RESERVED_KEY,
    backend_key,
    paused_key,
    read_backend_override,
    read_gpu_reserved_until,
    read_overrides,
    read_paused,
    set_backend_override,
    set_gpu_reserved_until,
    set_paused,
)
from tests.test_media.conftest import MemorySwitchStore

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def test_the_keys_are_spelled_as_the_spec_spells_them() -> None:
    assert backend_key(MediaSku.IMAGE) == "media:backend:image"
    assert paused_key(MediaSku.VIDEO_STANDARD) == "media:paused:video_standard"
    assert GPU_RESERVED_KEY == "media:gpu:reserved_until"


async def test_nothing_set_means_no_override() -> None:
    overrides = await read_overrides(MemorySwitchStore(), MediaSku.IMAGE)

    assert overrides.backend is None
    assert overrides.is_paused is False
    assert overrides.gpu_reserved_until is None
    assert not overrides.is_gpu_reserved(NOW)


async def test_a_round_trip_through_the_writers() -> None:
    store = MemorySwitchStore()
    until = NOW + timedelta(hours=2)

    await set_backend_override(store, MediaSku.IMAGE, MediaBackend.FAKE)
    await set_paused(store, MediaSku.IMAGE, paused=True)
    await set_gpu_reserved_until(store, until)
    overrides = await read_overrides(store, MediaSku.IMAGE)

    assert overrides.backend is MediaBackend.FAKE
    assert overrides.is_paused
    assert overrides.gpu_reserved_until == until
    assert overrides.is_gpu_reserved(NOW)


async def test_resuming_and_clearing_delete_the_keys() -> None:
    store = MemorySwitchStore()
    await set_paused(store, MediaSku.IMAGE, paused=True)
    await set_backend_override(store, MediaSku.IMAGE, MediaBackend.LOCAL)
    await set_gpu_reserved_until(store, NOW)

    await set_paused(store, MediaSku.IMAGE, paused=False)
    await set_backend_override(store, MediaSku.IMAGE, None)
    await set_gpu_reserved_until(store, None)

    assert store.values == {}


async def test_an_unknown_backend_value_is_ignored_loudly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = MemorySwitchStore({backend_key(MediaSku.IMAGE): b"replicate"})

    with caplog.at_level(logging.ERROR):
        assert await read_backend_override(store, MediaSku.IMAGE) is None
    assert "names no known backend" in caplog.text


@pytest.mark.parametrize("raw", [b"0", b"false", b"off", b""])
async def test_a_hand_typed_falsy_pause_does_not_pause(raw: bytes) -> None:
    store = MemorySwitchStore({paused_key(MediaSku.IMAGE): raw})

    assert await read_paused(store, MediaSku.IMAGE) is False


async def test_a_dead_redis_pauses_media_and_reserves_the_gpu_but_keeps_the_env_backend() -> None:
    dead = MemorySwitchStore(fail=True)

    overrides = await read_overrides(dead, MediaSku.IMAGE)

    assert overrides.is_paused is True
    assert overrides.is_gpu_reserved(NOW)
    assert overrides.backend is None


async def test_an_unparseable_reserved_window_counts_as_reserved() -> None:
    store = MemorySwitchStore({GPU_RESERVED_KEY: b"tomorrow-ish"})

    until = await read_gpu_reserved_until(store)

    assert until is not None and until > NOW


async def test_a_write_that_does_not_land_raises() -> None:
    with pytest.raises(StorageError):
        await set_paused(MemorySwitchStore(fail=True), MediaSku.IMAGE, paused=True)


async def test_a_naive_reserved_instant_is_refused() -> None:
    with pytest.raises(StorageError):
        await set_gpu_reserved_until(MemorySwitchStore(), datetime(2026, 9, 24, 12, 0))
