"""Tests for the local lyric card image renderer."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from bayram.audio.lyrics_image import (
    IMAGE_WIDTH,
    LYRICS_IMAGE_FILENAME,
    render_lyrics_image,
)
from bayram.contracts import Language, LyricSection, Ok
from tests.conftest import UZBEK_NAME_CANONICAL, make_lyrics


def test_render_lyrics_image_produces_valid_png(tmp_path: Path) -> None:
    lyrics = make_lyrics(
        name_display=UZBEK_NAME_CANONICAL,
        sections=(
            LyricSection(label="verse", lines=("Birinchi qator", "Ikkinchi qator")),
            LyricSection(label="chorus", lines=("Naqarot boshlandi", "Bayramingiz bilan!")),
        ),
    )
    dest = tmp_path / LYRICS_IMAGE_FILENAME
    res = render_lyrics_image(lyrics, dest, language=Language.UZ_LATN)

    assert isinstance(res, Ok)
    assert dest.exists()
    assert dest.stat().st_size > 0

    with Image.open(dest) as img:
        assert img.format == "PNG"
        assert img.size[0] == IMAGE_WIDTH
        assert img.size[1] >= IMAGE_WIDTH  # at least square or taller


def test_render_lyrics_image_handles_all_languages(tmp_path: Path) -> None:
    for lang in Language:
        lyrics = make_lyrics(
            title=f"Song Title in {lang.value}",
            name_display="С днём рождения!",
            sections=(
                LyricSection(label="verse", lines=("Строка один", "Строка два")),
            ),
        )
        dest = tmp_path / f"lyrics_{lang.value}.png"
        res = render_lyrics_image(lyrics, dest, language=lang)
        assert isinstance(res, Ok)
        assert dest.exists()
        assert dest.stat().st_size > 0


def test_render_lyrics_image_handles_long_lyrics(tmp_path: Path) -> None:
    many_sections = tuple(
        LyricSection(label=f"verse_{i}", lines=(f"Line 1 of verse {i}", f"Line 2 of verse {i}"))
        for i in range(10)
    )
    lyrics = make_lyrics(sections=many_sections)
    dest = tmp_path / "long_lyrics.png"
    res = render_lyrics_image(lyrics, dest, language=Language.EN)

    assert isinstance(res, Ok)
    assert dest.exists()
    with Image.open(dest) as img:
        assert img.size[0] == IMAGE_WIDTH
        assert img.size[1] > IMAGE_WIDTH  # expanded for height
