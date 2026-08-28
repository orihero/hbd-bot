"""Assets land on deterministic paths, degrade gracefully, and never need ffmpeg to test."""

from __future__ import annotations

from pathlib import Path

from hbd.config import Settings
from hbd.contracts import (
    AssetKind,
    CostSource,
    Language,
    NameCandidate,
    NameStrategy,
    RenderedAudio,
    SpokenScript,
)
from hbd.errors import ErrorCode
from hbd.pipeline.assets import (
    VOICE_NOTE_MIME,
    archive_assets,
    greeting_asset,
    lyric_sheet_asset,
    render_lyric_sheet,
    song_asset,
)
from tests.conftest import UZBEK_NAME_CANONICAL, make_lyrics
from tests.test_pipeline.conftest import (
    FakeAudioPostProcessor,
    FakeStorage,
    failure_of,
    value_of,
)

CANDIDATE = NameCandidate(text="Gulomjon", strategy=NameStrategy.STRIPPED, rank=0)
SONG = RenderedAudio(
    data=b"song-bytes",
    mime="audio/mpeg",
    duration_s=118.0,
    cost_usd=0.3,
    cost_source=CostSource.DERIVED,
)
GREETING = RenderedAudio(
    data=b"greeting-bytes",
    mime="audio/mpeg",
    duration_s=29.0,
    cost_usd=0.02,
    cost_source=CostSource.ESTIMATED,
)
SCRIPT = SpokenScript(
    persona_id="bobo",
    language=Language.UZ_LATN,
    text="salom",
    name_submitted="Gulomjon",
    target_duration_s=30.0,
)


async def test_song_is_written_normalised_and_described(tmp_path: Path, settings: Settings) -> None:
    # Arrange
    post = FakeAudioPostProcessor()

    # Act
    asset = value_of(
        await song_asset(
            SONG,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
        )
    )

    # Assert
    assert asset.kind is AssetKind.SONG
    assert asset.path.name == "song.mp3"
    assert asset.path.read_bytes() == b"song-bytes|norm"
    assert asset.name_candidate == CANDIDATE
    assert asset.duration_s == 120.0


async def test_song_ships_raw_when_loudness_normalisation_fails(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    post.should_fail_normalize = True

    # Act
    asset = value_of(
        await song_asset(
            SONG, workspace=tmp_path, post=post, settings=settings, name_candidate=CANDIDATE
        )
    )

    # Assert
    assert asset.path.name == "song-raw.mp3"
    assert asset.path.read_bytes() == b"song-bytes"


async def test_song_falls_back_to_the_vendor_duration_when_probing_fails(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    post.should_fail_probe = True

    # Act
    asset = value_of(
        await song_asset(
            SONG, workspace=tmp_path, post=post, settings=settings, name_candidate=CANDIDATE
        )
    )

    # Assert
    assert asset.duration_s == SONG.duration_s
    assert asset.loudness_lufs is None


async def test_a_rerun_overwrites_the_same_path_instead_of_duplicating(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()

    # Act
    first = value_of(
        await song_asset(
            SONG, workspace=tmp_path, post=post, settings=settings, name_candidate=CANDIDATE
        )
    )
    second = value_of(
        await song_asset(
            SONG, workspace=tmp_path, post=post, settings=settings, name_candidate=CANDIDATE
        )
    )

    # Assert
    assert first.path == second.path
    assert first.sha256 == second.sha256
    assert len(list(tmp_path.glob("song*.mp3"))) == 2  # raw + normalised, not four files


async def test_greeting_becomes_an_ogg_voice_note(tmp_path: Path, settings: Settings) -> None:
    # Arrange
    post = FakeAudioPostProcessor()

    # Act
    asset = value_of(
        await greeting_asset(
            GREETING,
            SCRIPT,
            index=0,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
        )
    )

    # Assert
    assert asset.kind is AssetKind.GREETING
    assert asset.mime == VOICE_NOTE_MIME
    assert asset.path.name == "greeting-1.ogg"
    assert asset.persona_id == "bobo"


async def test_greeting_fails_when_the_opus_transcode_fails(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    post.should_fail_voice_note = True

    # Act
    result = await greeting_asset(
        GREETING,
        SCRIPT,
        index=1,
        workspace=tmp_path,
        post=post,
        settings=settings,
        name_candidate=CANDIDATE,
    )

    # Assert
    assert failure_of(result).error_code is ErrorCode.AUDIO_FAILED


def test_the_lyric_sheet_uses_the_display_orthography(tmp_path: Path) -> None:
    # Arrange
    lyrics = make_lyrics()

    # Act
    asset = value_of(lyric_sheet_asset(lyrics, workspace=tmp_path))
    text = asset.path.read_text(encoding="utf-8")

    # Assert
    assert asset.kind is AssetKind.LYRIC_SHEET
    assert UZBEK_NAME_CANONICAL in text
    assert "Gulomjon\n" not in text.replace(UZBEK_NAME_CANONICAL, "")


def test_the_lyric_sheet_lists_every_section_with_its_label() -> None:
    # Arrange
    lyrics = make_lyrics()

    # Act
    sheet = render_lyric_sheet(lyrics)

    # Assert
    assert sheet.startswith(lyrics.title)
    for section in lyrics.sections:
        assert f"[{section.label}]" in sheet


async def test_archiving_reports_failures_without_raising(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    storage = FakeStorage()
    storage.should_fail = True
    asset = value_of(
        await song_asset(
            SONG, workspace=tmp_path, post=post, settings=settings, name_candidate=CANDIDATE
        )
    )

    # Act
    failures = await archive_assets((asset,), order_id="order-1", storage=storage)

    # Assert
    assert len(failures) == 1
    assert failures[0].error_code is ErrorCode.STORAGE_FAILED


async def test_archiving_stores_each_asset_under_the_order(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    storage = FakeStorage()
    asset = value_of(
        await song_asset(
            SONG, workspace=tmp_path, post=post, settings=settings, name_candidate=CANDIDATE
        )
    )

    # Act
    failures = await archive_assets((asset,), order_id="order-1", storage=storage)

    # Assert
    assert failures == ()
    assert "orders/order-1/song.mp3" in storage.objects


async def test_reports_a_missing_file_rather_than_raising(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    storage = FakeStorage()
    asset = value_of(
        await song_asset(
            SONG, workspace=tmp_path, post=post, settings=settings, name_candidate=CANDIDATE
        )
    )
    asset.path.unlink()

    # Act
    failures = await archive_assets((asset,), order_id="order-1", storage=storage)

    # Assert
    assert len(failures) == 1
    assert "disappeared" in failures[0].operator_message
