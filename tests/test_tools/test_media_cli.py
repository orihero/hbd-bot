"""``python -m bayram.tools.media`` — parsing and the writes it makes (IMAGE_VIDEO_SPEC §4.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bayram.config import Settings
from bayram.db.enums import MediaBackend, MediaSku
from bayram.media.overrides import read_overrides
from bayram.tools.media import RefusedError, apply, plan
from tests.test_media.conftest import MemorySwitchStore

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "argv",
    [
        ["pause", "song"],
        ["backend", "image", "replicate"],
        ["reserve", "--minutes", "0"],
        ["reserve", "--minutes", "1441"],
        ["reserve", "--minutes", "-5"],
        ["frobnicate"],
    ],
)
def test_bad_input_is_refused_before_any_write(argv: list[str]) -> None:
    with pytest.raises(RefusedError):
        plan(argv)


async def test_pause_backend_and_reserve_write_through_the_overrides(settings: Settings) -> None:
    store = MemorySwitchStore()

    await apply(store, settings, plan(["pause", "image"]), now=NOW)
    await apply(store, settings, plan(["backend", "image", "fal"]), now=NOW)
    await apply(store, settings, plan(["reserve", "--minutes", "30"]), now=NOW)
    overrides = await read_overrides(store, MediaSku.IMAGE)

    assert overrides.is_paused
    assert overrides.backend is MediaBackend.FAL
    assert overrides.gpu_reserved_until == NOW + timedelta(minutes=30)


async def test_resume_env_and_release_clear_everything(settings: Settings) -> None:
    store = MemorySwitchStore()
    for argv in (["pause", "image"], ["backend", "image", "fal"], ["reserve", "--minutes", "5"]):
        await apply(store, settings, plan(argv), now=NOW)

    for argv in (["resume", "image"], ["backend", "image", "env"], ["release"]):
        await apply(store, settings, plan(argv), now=NOW)

    assert store.values == {}


async def test_status_names_every_sku(settings: Settings) -> None:
    report = await apply(MemorySwitchStore(), settings, plan(["status"]), now=NOW)

    for sku in MediaSku:
        assert f"{sku.value}: env=" in report
    assert "GPU not reserved" in report


async def test_the_fake_backend_is_refused_outside_a_fake_deployment(settings: Settings) -> None:
    # §4.5: the worker would ignore it anyway; the operator must not believe traffic moved.
    store = MemorySwitchStore()

    with pytest.raises(RefusedError, match="fake"):
        await apply(store, settings, plan(["backend", "image", "fake"]), now=NOW)
    assert store.values == {}

    faked = settings.model_copy(update={"use_fake_providers": True})
    await apply(store, faked, plan(["backend", "image", "fake"]), now=NOW)
    assert (await read_overrides(store, MediaSku.IMAGE)).backend is MediaBackend.FAKE


def test_doctor_release_is_parsed() -> None:
    assert plan(["doctor", "--release"]).release is True
    assert plan(["doctor"]).release is False
