"""The composition root: does the flag actually swap everything, and is it safe?

These are the tests no module agent could write, because each of them owned one side of a
seam. What is asserted here is the *joins*: the fake flag is all-or-nothing, a live build
names every vendor, the similarity port is bound the right way round, and production
cannot accidentally be served silence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hbd.config import Settings
from hbd.contracts import (
    AudioPostProcessor,
    KitRepository,
    LlmProvider,
    MusicProvider,
    PaymentProvider,
    Storage,
    SttProvider,
    TtsProvider,
)
from hbd.errors import ConfigError
from hbd.providers.llm.fake import FakeLlmProvider
from hbd.providers.music.fake import FakeMusicProvider
from hbd.providers.tts.fakes import FakeTtsProvider
from hbd.providers.tts.router import LanguageRoutingTts
from hbd.runtime.container import build_container
from hbd.runtime.fakes import KeytermSttProvider
from hbd.runtime.providers import build_provider_set


def _fake(settings: Settings, **extra: object) -> Settings:
    payload = {**settings.model_dump(), "use_fake_providers": True, **extra}
    return Settings(_env_file=None, **payload)


def _sqlite(settings: Settings, tmp_path: Path, **extra: object) -> Settings:
    return _fake(settings, database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", **extra)


# ---------------------------------------------------------------------------
# ProviderSet
# ---------------------------------------------------------------------------
def test_the_fake_flag_swaps_every_vendor_at_once(settings: Settings) -> None:
    # Arrange / Act
    providers = build_provider_set(_fake(settings))

    # Assert: all six, not some.
    assert providers.is_fake
    assert isinstance(providers.music, FakeMusicProvider)
    assert isinstance(providers.tts, FakeTtsProvider)
    assert isinstance(providers.stt, KeytermSttProvider)
    assert isinstance(providers.llm, FakeLlmProvider)
    assert providers.llm_fallback is None


def test_every_fake_still_satisfies_its_protocol(settings: Settings) -> None:
    # Arrange / Act
    providers = build_provider_set(_fake(settings))

    # Assert
    assert isinstance(providers.music, MusicProvider)
    assert isinstance(providers.tts, TtsProvider)
    assert isinstance(providers.stt, SttProvider)
    assert isinstance(providers.llm, LlmProvider)


def test_fake_providers_are_refused_in_production(settings: Settings) -> None:
    # Arrange / Act / Assert: silence must never reach a paying customer.
    with pytest.raises(ConfigError, match="prod"):
        build_provider_set(_fake(settings, environment="prod"))


async def test_a_live_build_names_a_real_adapter_for_every_leg(settings: Settings) -> None:
    # Arrange / Act: no request is made — construction only.
    providers = build_provider_set(settings)

    # Assert
    assert not providers.is_fake
    assert isinstance(providers.tts, LanguageRoutingTts)
    assert providers.music.name == "elevenlabs_music"
    assert providers.stt.name == "elevenlabs_scribe"
    await providers.aclose()


def test_a_malformed_voice_registry_override_fails_startup_rather_than_defaulting(
    settings: Settings,
) -> None:
    # Arrange: an operator's typo must not silently restore the shipped cast.
    broken = _fake(settings, tts_voice_registry_json="{not json")

    # Act / Assert
    with pytest.raises(ConfigError, match="VOICE_REGISTRY"):
        build_provider_set(broken)


def test_a_malformed_route_table_fails_startup(settings: Settings) -> None:
    # Arrange
    broken = Settings(
        _env_file=None, **{**settings.model_dump(), "tts_routes": "klingon=elevenlabs_tts"}
    )

    # Act / Assert
    with pytest.raises(ConfigError, match="TTS_ROUTES"):
        build_provider_set(broken)


# ---------------------------------------------------------------------------
# AppContainer
# ---------------------------------------------------------------------------
async def test_the_container_satisfies_every_protocol_the_pipeline_asks_for(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange / Act
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Assert
    try:
        assert isinstance(container.repository, KitRepository)
        assert isinstance(container.storage, Storage)
        assert isinstance(container.post, AudioPostProcessor)
        assert isinstance(container.payment, PaymentProvider)
    finally:
        await container.aclose()


async def test_the_container_creates_its_workspace_and_archive_directories(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange / Act
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Assert
    try:
        assert container.workspace_root.is_dir()
        assert (tmp_path / "archive").is_dir()
    finally:
        await container.aclose()


async def test_a_pipeline_can_be_built_per_job_without_touching_the_container(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Act
    try:
        first = container.pipeline()
        second = container.pipeline()

        # Assert: separate pipelines, one shared slot budget.
        assert first is not second
        assert first._music_slots is second._music_slots
    finally:
        await container.aclose()


async def test_the_semaphores_honour_the_configured_vendor_ceilings(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange
    configured = _sqlite(settings, tmp_path, music_max_concurrency=5, tts_max_concurrency=7)

    # Act
    container = await build_container(configured, data_root=tmp_path)

    # Assert
    try:
        assert container.music_slots._value == 5
        assert container.tts_slots._value == 7
    finally:
        await container.aclose()


async def test_closing_the_container_twice_is_harmless(settings: Settings, tmp_path: Path) -> None:
    # Arrange
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Act / Assert: shutdown paths run twice under interrupt; that must not raise.
    await container.aclose()
    await container.aclose()


# ---------------------------------------------------------------------------
# The similarity binding — the one argument order that silently breaks the product
# ---------------------------------------------------------------------------
def test_the_similarity_port_is_bound_the_right_way_round() -> None:
    # Arrange: the port is (heard, expected); hbd.names is (intended, heard).
    from hbd.runtime.container import _similarity

    # Act
    heard_extra_words = _similarity("bugun Gulomjon degan", "Gʻulomjon")
    reversed_arguments = _similarity("Gʻulomjon", "bugun Gulomjon degan")

    # Assert: the scorer window-scans the *heard* side, so only one order finds the name.
    assert heard_extra_words > reversed_arguments
