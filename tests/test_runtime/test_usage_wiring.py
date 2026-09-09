"""Does the usage sink actually reach every vendor, and is it the SAME one?

The composition root is the only place that can answer either question. Each adapter
defaults its ``usage`` parameter to the logging sink, so an adapter that is never handed
the persisting one is not broken — it is quietly correct, writes a log line, and leaves a
hole in ``vendor_usage`` that reads exactly like a vendor nobody called. That is the
failure this module exists to catch, and it can only be caught here.

The five live constructions are replaced with recorders rather than inspected after the
fact. What is being asserted is the WIRING — which object was handed to whom — and the
recorder makes that a fact about this file rather than a fact about five adapters' private
attribute names, which belong to the adapters and may be refactored without warning.

Identity, not equality. Two sinks over the same session factory would compare equal to
nobody and would still both work, so ``is`` is the only assertion that says what is meant:
one sink per process, shared, and therefore one table an operator has to read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hbd.config import Settings
from hbd.db.vendor_usage import DbUsageSink
from hbd.providers.tts.elevenlabs import PROVIDER_NAME as ELEVENLABS_TTS_NAME
from hbd.runtime import providers as providers_module
from hbd.runtime.container import build_container
from hbd.runtime.providers import build_provider_set
from hbd.usage import LOGGING_USAGE_SINK, UsageSink, VendorUsage

#: The five live legs, by the name each is constructed under in ``runtime.providers``.
_LIVE_LEGS: tuple[str, ...] = ("music", "tts", "stt", "llm", "llm_fallback")
#: The four fake ones. Fewer legs, same rule: a demo is recorded, not invisible.
_FAKE_LEGS: tuple[str, ...] = ("music", "tts", "stt", "llm")


class RecordingUsageSink:
    """A sink that keeps what it is given. Never raises, like the real ones."""

    def __init__(self) -> None:
        self.recorded: list[VendorUsage] = []

    async def record(self, usage: VendorUsage) -> None:
        self.recorded.append(usage)


class StubAdapter:
    """Stands in for one adapter, remembering the sink it was constructed with.

    It carries a ``name`` because ``build_router`` binds the TTS route table by adapter
    name, so the stub standing in for ``ElevenLabsTts`` has to answer to the name the
    shipped routes point at or the live build fails before it reaches the assertion.
    """

    def __init__(self, name: str, usage: UsageSink) -> None:
        self.name = name
        self.usage = usage


def _recorder(sinks: dict[str, UsageSink], leg: str, name: str) -> Any:
    """A stand-in constructor that files the ``usage`` it was handed under ``leg``.

    Keyword-only in the signature on purpose: a wiring site that passed the sink
    positionally, or forgot it entirely, fails here with a ``TypeError`` naming the leg
    rather than silently recording ``None``.
    """

    def build(*_args: Any, usage: UsageSink, **_kwargs: Any) -> StubAdapter:
        sinks[leg] = usage
        return StubAdapter(name, usage)

    return build


@pytest.fixture
def live_sinks(monkeypatch: pytest.MonkeyPatch) -> dict[str, UsageSink]:
    """Replace the five live constructions; hand back what each was given."""
    sinks: dict[str, UsageSink] = {}
    for leg, attribute, name in (
        ("music", "build_music_provider", "elevenlabs_music"),
        ("tts", "ElevenLabsTts", ELEVENLABS_TTS_NAME),
        ("stt", "ElevenLabsScribe", "elevenlabs_scribe"),
        ("llm", "build_llm_provider", "openai-compat"),
        ("llm_fallback", "build_fallback_llm_provider", "openai-compat"),
    ):
        monkeypatch.setattr(providers_module, attribute, _recorder(sinks, leg, name))
    return sinks


@pytest.fixture
def fake_sinks(monkeypatch: pytest.MonkeyPatch) -> dict[str, UsageSink]:
    """The same, for the four fakes."""
    sinks: dict[str, UsageSink] = {}
    for leg, attribute, name in (
        ("music", "FakeMusicProvider", "fake_music"),
        ("tts", "FakeTtsProvider", "fake_tts"),
        ("stt", "KeytermSttProvider", "fake_stt"),
        ("llm", "FakeLlmProvider", "fake_llm"),
    ):
        monkeypatch.setattr(providers_module, attribute, _recorder(sinks, leg, name))
    return sinks


def _fake(settings: Settings, **extra: object) -> Settings:
    payload = {**settings.model_dump(), "use_fake_providers": True, **extra}
    return Settings(_env_file=None, **payload)


# ---------------------------------------------------------------------------
# build_provider_set
# ---------------------------------------------------------------------------
def test_every_live_adapter_is_handed_the_same_sink_object(
    settings: Settings, live_sinks: dict[str, UsageSink]
) -> None:
    # Arrange
    sink = RecordingUsageSink()

    # Act
    build_provider_set(settings, usage=sink)

    # Assert: all five, and one object — not five sinks over one table.
    assert tuple(sorted(live_sinks)) == tuple(sorted(_LIVE_LEGS))
    assert all(recorded is sink for recorded in live_sinks.values())


def test_a_caller_that_names_no_sink_still_measures_through_the_logging_one(
    settings: Settings, live_sinks: dict[str, UsageSink]
) -> None:
    """The default is a working sink, not ``None``.

    A test, a one-shot operator tool or the demo runner holds no database and must still
    build a provider set that measures itself. Defaulting to ``None`` would push a
    ``if self._usage is not None`` into every adapter's every return path.
    """
    # Arrange / Act
    build_provider_set(settings)

    # Assert
    assert all(recorded is LOGGING_USAGE_SINK for recorded in live_sinks.values())


def test_the_fakes_are_handed_the_sink_too_so_a_demo_is_recorded_not_invisible(
    settings: Settings, fake_sinks: dict[str, UsageSink]
) -> None:
    """A fake run writes rows and excludes itself by ``is_fake``, not by absence.

    Skipping the sink in fake mode would make an offline demo indistinguishable from a
    deployment nobody ever instrumented — precisely the distinction ``isVendorUsage``
    exists to draw.
    """
    # Arrange
    sink = RecordingUsageSink()

    # Act
    providers = build_provider_set(_fake(settings), usage=sink)

    # Assert
    assert providers.is_fake
    assert tuple(sorted(fake_sinks)) == tuple(sorted(_FAKE_LEGS))
    assert all(recorded is sink for recorded in fake_sinks.values())


# ---------------------------------------------------------------------------
# The container
# ---------------------------------------------------------------------------
@pytest.fixture
def handed_to_the_vendors(monkeypatch: pytest.MonkeyPatch) -> list[UsageSink]:
    """Whatever ``build_container`` passes as the provider set's sink.

    The real function is still called through, so the container under test is the one the
    worker boots: the spy observes the argument rather than replacing the wiring.
    """
    handed: list[UsageSink] = []
    original = providers_module.build_provider_set

    def spy(built: Settings, *, usage: UsageSink) -> Any:
        handed.append(usage)
        return original(built, usage=usage)

    monkeypatch.setattr("hbd.runtime.container.build_provider_set", spy)
    return handed


async def _sqlite_container(settings: Settings, tmp_path: Path) -> Any:
    return await build_container(
        _fake(settings, database_url=f"sqlite+aiosqlite:///{tmp_path / 'usage.db'}"),
        data_root=tmp_path,
    )


async def test_the_container_hands_the_vendors_a_database_backed_sink(
    settings: Settings, tmp_path: Path, handed_to_the_vendors: list[UsageSink]
) -> None:
    """The one place the logging default is replaced by a persisting sink.

    Asserted on the container rather than on the sink's own behaviour because this is the
    only seam at which the substitution can be forgotten: every adapter would keep working,
    every call would keep logging, and ``vendor_usage`` would stay empty forever.
    """
    # Arrange / Act
    container = await _sqlite_container(settings, tmp_path)

    # Assert
    try:
        assert len(handed_to_the_vendors) == 1
        assert isinstance(handed_to_the_vendors[0], DbUsageSink)
    finally:
        await container.aclose()


async def test_the_container_builds_the_sink_on_its_own_session_factory(
    settings: Settings, tmp_path: Path, handed_to_the_vendors: list[UsageSink]
) -> None:
    """No provider opens its own connection to record what it did.

    A sink that made its own engine would double the pools a worker holds and would put
    "where do measurements go" in five files instead of one, so the factory it writes
    through has to be the one the container already owns.
    """
    # Arrange / Act
    container = await _sqlite_container(settings, tmp_path)

    # Assert
    try:
        sink = handed_to_the_vendors[0]
        assert isinstance(sink, DbUsageSink)
        # Reaching into the sink's own factory is the whole assertion: any public surface
        # it grew for this would be a surface production code could then write through.
        assert sink._sessions is container.session_factory
    finally:
        await container.aclose()
