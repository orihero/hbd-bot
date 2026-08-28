"""Shared fixtures for every module's tests.

Ground rule: **nothing here touches the network, Redis, Postgres or ffmpeg.** Anything
that would is marked ``@pytest.mark.integration`` in the module that needs it.

Module agents: build on these rather than re-inventing a ``Brief``. The factories
(``make_name``, ``make_brief``, ``make_order``) take keyword overrides so a test can vary
exactly the one field it cares about.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from hbd.config import ENV_PREFIX, Settings
from hbd.contracts import (
    AssetKind,
    Brief,
    Chunk,
    CompositionPlan,
    CostSource,
    GeneratedAsset,
    Genre,
    Kit,
    Language,
    LyricDraft,
    LyricSection,
    NameCandidate,
    NameStrategy,
    Occasion,
    Order,
    OrderState,
    RecipientName,
    RenderedAudio,
    Script,
    SpokenScript,
    VoiceGender,
)
from hbd.logging import configure_logging

# A fixed instant so any snapshot involving timestamps is stable.
FIXED_NOW = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)

#: Real Uzbek Latin: oʻ and gʻ use U+02BB MODIFIER LETTER TURNED COMMA.
UZBEK_NAME_CANONICAL = "Gʻulomjon"
#: What actually arrives from a phone keyboard (U+2018 LEFT SINGLE QUOTATION MARK).
UZBEK_NAME_TYPED = "G‘ulomjon"


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _quiet_logging() -> None:
    configure_logging(level="WARNING", is_json=True)


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    """Keep a test that reconfigures logging from leaking into the next one."""
    root = logging.getLogger()
    saved = (tuple(root.handlers), root.level)
    yield
    root.handlers = list(saved[0])
    root.setLevel(saved[1])


@pytest.fixture
def settings_env() -> dict[str, str]:
    """The minimum set of required variables, as they appear in the environment."""
    return {
        "HBD_TELEGRAM_BOT_TOKEN": "123456:test-token-value-for-unit-tests-only",
        "HBD_DATABASE_URL": "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test",
        "HBD_ELEVENLABS_API_KEY": "test-elevenlabs-key",
        "HBD_LLM_API_KEY": "test-llm-key",
    }


@pytest.fixture
def settings(settings_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Settings:
    """A fully valid Settings built in-process.

    Isolated twice over: the real ``.env`` is disabled, and every ``HBD_`` variable is
    stripped from the environment, so a developer's shell cannot change a test outcome.
    """
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    return Settings(
        _env_file=None,
        telegram_bot_token=settings_env["HBD_TELEGRAM_BOT_TOKEN"],
        database_url=settings_env["HBD_DATABASE_URL"],
        elevenlabs_api_key=settings_env["HBD_ELEVENLABS_API_KEY"],
        llm_api_key=settings_env["HBD_LLM_API_KEY"],
    )


@pytest.fixture
def fixed_now() -> datetime:
    return FIXED_NOW


# ---------------------------------------------------------------------------
# Domain factories
# ---------------------------------------------------------------------------
def make_candidates(
    *,
    base: str = "Gulomjon",
    order: tuple[NameStrategy, ...] = (
        NameStrategy.STRIPPED,
        NameStrategy.CANONICAL,
        NameStrategy.HYPHENATED,
    ),
) -> tuple[NameCandidate, ...]:
    """Ranked candidates in the given strategy order, ranks dense from zero."""
    texts = {
        NameStrategy.STRIPPED: base,
        NameStrategy.CANONICAL: UZBEK_NAME_CANONICAL,
        NameStrategy.ASCII: "G'ulomjon",
        NameStrategy.CYRILLIC: "Ғуломжон",
        NameStrategy.HYPHENATED: "Gu-lom-jon",
        NameStrategy.PHONETIC: "Ghoolomjon",
    }
    return tuple(
        NameCandidate(text=texts[strategy], strategy=strategy, rank=rank)
        for rank, strategy in enumerate(order)
    )


def make_name(**overrides: Any) -> RecipientName:
    defaults: dict[str, Any] = {
        "raw": UZBEK_NAME_TYPED,
        "display": UZBEK_NAME_CANONICAL,
        "lookup_key": "gulomjon",
        "script": Script.LATIN,
        "language": Language.UZ_LATN,
        "candidates": make_candidates(),
    }
    return RecipientName(**{**defaults, **overrides})


def make_brief(**overrides: Any) -> Brief:
    defaults: dict[str, Any] = {
        "recipient": make_name(),
        "occasion": Occasion.BIRTHDAY,
        "genre": Genre.UZBEK_POP,
        "vocal_gender": VoiceGender.FEMALE,
        "note": "Loves mountains and his grandmother's plov.",
        "ui_language": Language.UZ_LATN,
        "output_language": Language.UZ_LATN,
    }
    return Brief(**{**defaults, **overrides})


def make_order(**overrides: Any) -> Order:
    defaults: dict[str, Any] = {
        "id": uuid4(),
        "telegram_user_id": 99_000_111,
        "brief": make_brief(),
        "state": OrderState.BRIEF_READY,
        "correlation_id": "test-correlation-id",
        "created_at": FIXED_NOW,
        "updated_at": FIXED_NOW,
    }
    return Order(**{**defaults, **overrides})


def make_lyrics(**overrides: Any) -> LyricDraft:
    defaults: dict[str, Any] = {
        "title": "Tugʻilgan kun",
        "language": Language.UZ_LATN,
        "sections": (
            LyricSection(label="verse-1", lines=("Bugun quyosh boshqacha porlaydi",)),
            LyricSection(label="hook", lines=(UZBEK_NAME_CANONICAL,), is_name_hook=True),
            LyricSection(label="chorus", lines=("Yillar oʻtsa ham qoʻshigʻing yangraydi",)),
        ),
        "name_display": UZBEK_NAME_CANONICAL,
    }
    return LyricDraft(**{**defaults, **overrides})


def make_plan(**overrides: Any) -> CompositionPlan:
    """A three-chunk plan whose middle chunk is the name chunk."""
    defaults: dict[str, Any] = {
        "chunks": (
            Chunk(text="Bugun quyosh boshqacha porlaydi", duration_ms=20_000),
            Chunk(text="Gulomjon", duration_ms=8_000, is_name_chunk=True),
            Chunk(text="Yillar oʻtsa ham qoʻshigʻing yangraydi", duration_ms=20_000),
        ),
        "language": Language.UZ_LATN,
        "seed": 1234,
    }
    return CompositionPlan(**{**defaults, **overrides})


def make_asset(tmp_path: Path, **overrides: Any) -> GeneratedAsset:
    path = overrides.pop("path", None) or (tmp_path / "song.mp3")
    if not path.exists():
        path.write_bytes(b"fake-audio-bytes")
    defaults: dict[str, Any] = {
        "kind": AssetKind.SONG,
        "path": path,
        "duration_s": 120.0,
        "mime": "audio/mpeg",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "loudness_lufs": -14.0,
    }
    return GeneratedAsset(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# Fixture wrappers over the factories
# ---------------------------------------------------------------------------
@pytest.fixture
def recipient_name() -> RecipientName:
    return make_name()


@pytest.fixture
def brief() -> Brief:
    return make_brief()


@pytest.fixture
def order() -> Order:
    return make_order()


@pytest.fixture
def lyrics() -> LyricDraft:
    return make_lyrics()


@pytest.fixture
def composition_plan() -> CompositionPlan:
    return make_plan()


@pytest.fixture
def spoken_script() -> SpokenScript:
    return SpokenScript(
        persona_id="ovozli-bobo",
        language=Language.UZ_LATN,
        text=f"Assalomu alaykum, {UZBEK_NAME_CANONICAL}! Tugʻilgan kuningiz bilan!",
        name_submitted="Gulomjon",
        target_duration_s=30.0,
    )


@pytest.fixture
def rendered_audio() -> RenderedAudio:
    return RenderedAudio(
        data=b"fake-audio-bytes",
        mime="audio/mpeg",
        duration_s=120.0,
        remote_id="song_test_0001",
        cost_usd=0.30,
        cost_source=CostSource.DERIVED,
    )


@pytest.fixture
def kit(tmp_path: Path, lyrics: LyricDraft) -> Kit:
    order_id: UUID = uuid4()
    song = make_asset(tmp_path, path=tmp_path / "song.mp3")
    greeting = make_asset(
        tmp_path,
        path=tmp_path / "greeting-1.ogg",
        kind=AssetKind.GREETING,
        mime="audio/ogg",
        duration_s=30.0,
        persona_id="ovozli-bobo",
        loudness_lufs=-16.0,
    )
    sheet = make_asset(
        tmp_path,
        path=tmp_path / "lyrics.txt",
        kind=AssetKind.LYRIC_SHEET,
        mime="text/plain",
        duration_s=0.0,
        loudness_lufs=None,
    )
    return Kit(
        order_id=order_id,
        song=song,
        greetings=(greeting,),
        lyric_sheet=sheet,
        lyrics=lyrics,
    )


@pytest.fixture
def audio_bytes() -> bytes:
    """Deterministic non-empty bytes for anything that just needs a payload."""
    return b"RIFF----WAVEfmt fake-audio-payload"
