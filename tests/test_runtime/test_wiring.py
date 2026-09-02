"""The composition root: does the flag actually swap everything, and is it safe?

These are the tests no module agent could write, because each of them owned one side of a
seam. What is asserted here is the *joins*: the fake flag is all-or-nothing, a live build
names every vendor, the similarity port is bound the right way round, and production
cannot accidentally be served silence.
"""

from __future__ import annotations

from dataclasses import replace
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
from hbd.db.credits import SqlCreditLedger
from hbd.db.lyric_budget import SqlLyricBudget
from hbd.entitlements import EntitlementStore
from hbd.errors import ConfigError
from hbd.payments import CreditGatedPaymentProvider, NoopPaymentProvider
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


# ---------------------------------------------------------------------------
# The render gate — wired on the worker's side of the container, and only there
# ---------------------------------------------------------------------------
async def test_the_entitlement_store_is_wired_whatever_the_enforcement_flag_says(
    settings: Settings, tmp_path: Path
) -> None:
    """Wiring and enforcing are two decisions, and only one of them is a flag.

    The store is always built, so an operator can flip ``HBD_CREDITS_ENFORCED`` without a
    redeploy and so ``/balance`` has an honest number to read while the meter is still dark.
    """
    # Arrange / Act
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Assert
    try:
        assert not container.settings.credits_enforced  # the shipped default
        assert isinstance(container.credits, EntitlementStore)
    finally:
        await container.aclose()


async def test_the_lyric_budget_is_wired_and_reads_its_ceiling_from_settings(
    settings: Settings, tmp_path: Path
) -> None:
    """The one meter the BOT writes, and the only ceiling on pre-gate vendor spend.

    Never behind ``credits_enforced``: that flag covers the credit balance, which refuses a
    paying-intent customer, while this refuses abuse — and the lyric write happens before
    every gate the flag touches, so shipping it dark would leave the free tier uncapped per
    person exactly as it was.
    """
    # Arrange
    configured = _sqlite(settings, tmp_path).model_copy(update={"lyric_writes_per_day": 4})

    # Act
    container = await build_container(configured, data_root=tmp_path)

    # Assert
    try:
        assert not container.settings.credits_enforced  # the shipped default, and irrelevant
        budget = container.lyric_budget
        assert isinstance(budget, SqlLyricBudget)
        assert budget.policy.writes_per_day == 4
    finally:
        await container.aclose()


async def test_the_pipeline_gets_the_credit_gate_and_the_bot_gets_the_bare_provider(
    settings: Settings, tmp_path: Path
) -> None:
    """The asymmetry that keeps a credit from being spent where it cannot be refunded.

    ``hbd.main`` builds ``BotDeps.payment`` from ``container.payment``, so if that field
    were the gated provider the bot would become a writer — and its three early returns
    after the gate (payment declined, ``_start_progress`` returned ``None``,
    ``submitter.submit`` returned ``Err``) can reach no refund, because no order row and no
    ARQ job exist yet. The worker is the only process whose terminal paths can compensate,
    so the gate is built per job inside ``pipeline()`` instead.
    """
    # Arrange
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Act
    try:
        gate = container.pipeline()._payment

        # Assert
        assert isinstance(gate, CreditGatedPaymentProvider)
        # Dark by default, wired all the same — and the flag is read off the STORE's policy
        # now, not off the decorator, so the block gate and the in-flight cap (which need
        # the rows this gate writes) enforce whatever it says.
        assert isinstance(container.credits, SqlCreditLedger)
        assert not container.credits.policy.is_balance_enforced
        assert isinstance(container.payment, NoopPaymentProvider)
        assert not isinstance(container.payment, CreditGatedPaymentProvider)
    finally:
        await container.aclose()


async def test_a_container_without_an_entitlement_store_still_builds_a_working_pipeline(
    settings: Settings, tmp_path: Path
) -> None:
    """``credits=None`` means "not wired at all", which is not the same as "wired, dark".

    Every test that predates the meter constructs a container without one, so the render
    gate has to degrade to the bare seam rather than to an exception at job time.
    """
    # Arrange
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)
    unmetered = replace(container, credits=None)

    # Act / Assert
    try:
        assert unmetered.pipeline()._payment is unmetered.payment
    finally:
        await container.aclose()
