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


def test_a_credit_correction_names_the_account_the_sku_the_direction_and_the_operator() -> None:
    # §7.5: the ledger half of a manual cash refund.
    job = "0b9f1f2e-6f6e-4d53-9a53-0f5d1c1e2a3b"

    revoke = plan(["credit", "7112345678", "video_standard", "--revoke", "--actor", "aziz"])
    grant = plan(["credit", "7112345678", "image", "--grant", "--actor", "aziz", "--job", job])

    assert (revoke.telegram_user_id, revoke.sku, revoke.delta) == (
        7_112_345_678,
        MediaSku.VIDEO_STANDARD,
        -1,
    )
    assert revoke.actor == "admin:aziz" and revoke.job_id is None
    assert (grant.delta, str(grant.job_id)) == (1, job)


@pytest.mark.parametrize(
    "argv",
    [
        ["credit", "7112345678", "image", "--actor", "aziz"],
        ["credit", "7112345678", "image", "--grant", "--revoke", "--actor", "aziz"],
        ["credit", "7112345678", "song", "--grant", "--actor", "aziz"],
        ["credit", "-1", "image", "--grant", "--actor", "aziz"],
        ["credit", "7112345678", "image", "--grant"],
        ["credit", "7112345678", "image", "--grant", "--actor", " "],
        ["credit", "7112345678", "image", "--grant", "--actor", "aziz", "--job", "nope"],
    ],
)
def test_a_malformed_credit_correction_is_refused_before_any_write(argv: list[str]) -> None:
    with pytest.raises(RefusedError):
        plan(argv)
