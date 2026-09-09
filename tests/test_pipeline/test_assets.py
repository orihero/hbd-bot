"""Assets land on deterministic paths, degrade gracefully, and never need ffmpeg to test.

Three post-processing passes now stand between vendor bytes and a deliverable — normalise,
brand, probe — and every one of them is allowed to fail without failing the order. Most of
what follows measures exactly that: which file ships when a pass gives up, and that the
digest and the duration describe the file that actually shipped rather than the one we
hoped for.
"""

from __future__ import annotations

import stat
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
    cover_asset,
    greeting_asset,
    lyric_sheet_asset,
    render_lyric_sheet,
    sha256_of,
    song_asset,
)
from hbd.watermark import SHEET_RULE, WATERMARK_HANDLE, contains_watermark
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
TITLE = "Tugʻilgan kun"
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
            title=TITLE,
        )
    )

    # Assert
    assert asset.kind is AssetKind.SONG
    assert asset.path.name == "song-tagged.mp3"
    assert asset.path.read_bytes() == b"song-bytes|norm|brand"
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
            SONG,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
            title=TITLE,
        )
    )

    # Assert: the branding pass still runs, on the raw file, so the watermark survives a
    # lost normalisation — but nothing re-levelled the audio, which is the point.
    assert asset.path.name == "song-tagged.mp3"
    assert asset.path.read_bytes() == b"song-bytes|brand"


async def test_song_falls_back_to_the_vendor_duration_when_probing_fails(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    post.should_fail_probe = True

    # Act
    asset = value_of(
        await song_asset(
            SONG,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
            title=TITLE,
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
            SONG,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
            title=TITLE,
        )
    )
    second = value_of(
        await song_asset(
            SONG,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
            title=TITLE,
        )
    )

    # Assert
    assert first.path == second.path
    assert first.sha256 == second.sha256
    # raw + normalised + branded, and the same three on the second run — not six files.
    assert len(list(tmp_path.glob("song*.mp3"))) == 3


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
    assert lyrics.title in sheet
    for section in lyrics.sections:
        assert f"[{section.label}]" in sheet


def test_the_lyric_sheet_carries_the_watermark_rule_top_and_bottom() -> None:
    # Arrange: the sheet is forwarded as a bare text file, with no caption travelling with
    # it, so a reader who starts at the bottom needs the same line as one who starts at the
    # top.
    lyrics = make_lyrics()

    # Act
    sheet = render_lyric_sheet(lyrics)

    # Assert
    assert sheet.startswith(SHEET_RULE)
    assert sheet.endswith(SHEET_RULE)
    assert sheet.count(SHEET_RULE) == 2


def test_the_watermark_rule_never_reaches_the_draft_the_sheet_was_typeset_from() -> None:
    # Arrange
    lyrics = make_lyrics()

    # Act
    render_lyric_sheet(lyrics)

    # Assert: the vendor payload is built from these sections, so a watermark here is a
    # watermark that gets SUNG.
    assert WATERMARK_HANDLE not in lyrics.as_plain_text()
    assert WATERMARK_HANDLE not in lyrics.title


# ---------------------------------------------------------------------------
# cover art and branding
# ---------------------------------------------------------------------------
async def test_the_cover_is_a_jpeg_asset_in_the_workspace(tmp_path: Path) -> None:
    # Act
    cover = await cover_asset(workspace=tmp_path)

    # Assert
    assert cover is not None
    assert cover.kind is AssetKind.COVER
    assert cover.path.name == "cover.jpg"
    assert cover.mime == "image/jpeg"
    assert cover.duration_s == 0.0


async def test_an_undrawable_cover_is_none_rather_than_an_error(tmp_path: Path) -> None:
    # Arrange: an unwritable workspace is the failure an operator actually hits — a full
    # disk or a permissions change on the kit root.
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        # Act
        cover = await cover_asset(workspace=locked)

        # Assert
        assert cover is None
    finally:
        locked.chmod(stat.S_IRWXU)


async def test_the_song_carries_the_four_watermark_tags(tmp_path: Path, settings: Settings) -> None:
    # Arrange
    post = FakeAudioPostProcessor()

    # Act
    await song_asset(
        SONG,
        workspace=tmp_path,
        post=post,
        settings=settings,
        name_candidate=CANDIDATE,
        title=TITLE,
    )

    # Assert: four tags, of which exactly one — the title — is the customer's own song and
    # not an advertisement. ``audio_tags`` folds the title to ASCII on the way through,
    # because an ID3 value's encoding is negotiated by the muxer, so this asserts the shape
    # rather than the exact string.
    _destination, _cover, tags = post.branded[0]
    assert [key for key, _ in tags] == ["title", "artist", "album", "comment"]
    assert dict(tags)["artist"] == WATERMARK_HANDLE
    assert not contains_watermark(dict(tags)["title"])


async def test_a_failing_brand_ships_the_normalised_file_and_still_succeeds(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange: a watermark is worth less than the song, so a lost mux costs the advertising
    # and nothing else.
    post = FakeAudioPostProcessor()
    post.should_fail_brand = True

    # Act
    asset = value_of(
        await song_asset(
            SONG,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
            title=TITLE,
        )
    )

    # Assert
    assert asset.path.name == "song.mp3"
    assert asset.path.read_bytes() == b"song-bytes|norm"
    assert asset.sha256 == sha256_of(asset.path)


async def test_the_song_is_branded_with_the_cover_when_one_was_drawn(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    cover = await cover_asset(workspace=tmp_path)
    assert cover is not None

    # Act
    await song_asset(
        SONG,
        workspace=tmp_path,
        post=post,
        settings=settings,
        name_candidate=CANDIDATE,
        title=TITLE,
        cover=cover.path,
    )

    # Assert
    assert post.branded[0][1] == cover.path


async def test_the_tags_are_still_written_when_no_cover_could_be_drawn(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange: a missing picture is not a missing watermark — three of the four tags are it.
    post = FakeAudioPostProcessor()

    # Act
    await song_asset(
        SONG,
        workspace=tmp_path,
        post=post,
        settings=settings,
        name_candidate=CANDIDATE,
        title=TITLE,
        cover=None,
    )

    # Assert
    _destination, passed_cover, tags = post.branded[0]
    assert passed_cover is None
    assert len(tags) == 4


async def test_archiving_reports_failures_without_raising(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    storage = FakeStorage()
    storage.should_fail = True
    asset = value_of(
        await song_asset(
            SONG,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
            title=TITLE,
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
            SONG,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
            title=TITLE,
        )
    )

    # Act
    failures = await archive_assets((asset,), order_id="order-1", storage=storage)

    # Assert
    assert failures == ()
    assert "orders/order-1/song-tagged.mp3" in storage.objects


async def test_reports_a_missing_file_rather_than_raising(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    storage = FakeStorage()
    asset = value_of(
        await song_asset(
            SONG,
            workspace=tmp_path,
            post=post,
            settings=settings,
            name_candidate=CANDIDATE,
            title=TITLE,
        )
    )
    asset.path.unlink()

    # Act
    failures = await archive_assets((asset,), order_id="order-1", storage=storage)

    # Assert
    assert len(failures) == 1
    assert "disappeared" in failures[0].operator_message
