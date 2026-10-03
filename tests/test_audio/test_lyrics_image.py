"""Tests for the local lyric card image renderer."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from bayram.audio.lyrics_image import (
    IMAGE_WIDTH,
    LYRICS_IMAGE_FILENAME,
    is_google_music_provider,
    localize_section_label,
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
            sections=(LyricSection(label="verse", lines=("Строка один", "Строка два")),),
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


def test_localize_section_label_uzbek_latin() -> None:
    assert localize_section_label("verse-1", Language.UZ_LATN) == "1-BAND"
    assert localize_section_label("verse 2", Language.UZ_LATN) == "2-BAND"
    assert localize_section_label("verse", Language.UZ_LATN) == "BAND"
    assert localize_section_label("chorus", Language.UZ_LATN) == "NAQAROT"
    assert localize_section_label("chorus-1", Language.UZ_LATN) == "1-NAQAROT"
    assert localize_section_label("pre-chorus", Language.UZ_LATN) == "NAQAROT OLDI"
    assert localize_section_label("intro", Language.UZ_LATN) == "KIRISH"
    assert localize_section_label("outro", Language.UZ_LATN) == "XOTIMA"
    assert localize_section_label("bridge", Language.UZ_LATN) == "OʻTISH"
    assert localize_section_label("hook", Language.UZ_LATN) == "NAQAROT"
    # Handles already-native labels
    assert localize_section_label("1-band", Language.UZ_LATN) == "1-BAND"
    assert localize_section_label("naqarot", Language.UZ_LATN) == "NAQAROT"


def test_localize_section_label_uzbek_cyrillic() -> None:
    assert localize_section_label("verse-1", Language.UZ_CYRL) == "1-БАНД"
    assert localize_section_label("verse-2", Language.UZ_CYRL) == "2-БАНД"
    assert localize_section_label("verse", Language.UZ_CYRL) == "БАНД"
    assert localize_section_label("chorus", Language.UZ_CYRL) == "НАҚАРОТ"
    assert localize_section_label("chorus-1", Language.UZ_CYRL) == "1-НАҚАРОТ"
    assert localize_section_label("pre-chorus", Language.UZ_CYRL) == "НАҚАРОТ ОЛДИ"
    assert localize_section_label("intro", Language.UZ_CYRL) == "КИРИШ"
    assert localize_section_label("outro", Language.UZ_CYRL) == "ХОТИМА"
    assert localize_section_label("bridge", Language.UZ_CYRL) == "ЎТИШ"


def test_localize_section_label_russian() -> None:
    assert localize_section_label("verse-1", Language.RU) == "КУПЛЕТ 1"
    assert localize_section_label("verse-2", Language.RU) == "КУПЛЕТ 2"
    assert localize_section_label("verse", Language.RU) == "КУПЛЕТ"
    assert localize_section_label("chorus", Language.RU) == "ПРИПЕВ"
    assert localize_section_label("chorus-1", Language.RU) == "ПРИПЕВ 1"
    assert localize_section_label("pre-chorus", Language.RU) == "ПРЕДПРИПЕВ"
    assert localize_section_label("intro", Language.RU) == "ВСТУПЛЕНИЕ"
    assert localize_section_label("outro", Language.RU) == "ФИНАЛ"
    assert localize_section_label("bridge", Language.RU) == "БРИДЖ"
    assert localize_section_label("куплет 1", Language.RU) == "КУПЛЕТ 1"
    assert localize_section_label("припев", Language.RU) == "ПРИПЕВ"


def test_localize_section_label_english() -> None:
    assert localize_section_label("verse-1", Language.EN) == "VERSE 1"
    assert localize_section_label("verse-2", Language.EN) == "VERSE 2"
    assert localize_section_label("verse", Language.EN) == "VERSE"
    assert localize_section_label("chorus", Language.EN) == "CHORUS"
    assert localize_section_label("chorus-1", Language.EN) == "CHORUS 1"
    assert localize_section_label("pre-chorus", Language.EN) == "PRE-CHORUS"
    assert localize_section_label("intro", Language.EN) == "INTRO"
    assert localize_section_label("outro", Language.EN) == "OUTRO"
    assert localize_section_label("bridge", Language.EN) == "BRIDGE"
    assert localize_section_label("hook", Language.EN) == "HOOK"


def test_is_google_music_provider() -> None:
    assert is_google_music_provider("gemini") is True
    assert is_google_music_provider("gemini_music") is True
    assert is_google_music_provider("google") is True
    assert is_google_music_provider("google_flow") is True
    assert is_google_music_provider("lyria") is True
    assert is_google_music_provider("lyria-3.5") is True
    assert is_google_music_provider("GEMINI") is True

    assert is_google_music_provider("elevenlabs") is False
    assert is_google_music_provider("elevenlabs_music") is False
    assert is_google_music_provider("fake_music") is False
    assert is_google_music_provider("") is False
    assert is_google_music_provider(None) is False


def test_render_lyrics_image_background_by_provider(tmp_path: Path) -> None:
    lyrics = make_lyrics(
        name_display="Sherzodbek",
        sections=(LyricSection(label="verse", lines=("Birinchi qator", "Ikkinchi qator")),),
    )

    # 1. Default (no provider) -> navy background (18, 20, 32)
    dest_default = tmp_path / "lyrics_default.png"
    render_lyrics_image(lyrics, dest_default)
    with Image.open(dest_default) as img:
        top_pixel = img.getpixel((0, 0))
        assert top_pixel == (18, 20, 32)

    # 2. ElevenLabs provider -> stays same navy background (18, 20, 32)
    dest_eleven = tmp_path / "lyrics_elevenlabs.png"
    render_lyrics_image(lyrics, dest_eleven, provider="elevenlabs_music")
    with Image.open(dest_eleven) as img:
        top_pixel = img.getpixel((0, 0))
        assert top_pixel == (18, 20, 32)

    # 3. Google / Gemini / Lyria provider -> vibrant orange background (220, 90, 20)
    dest_gemini = tmp_path / "lyrics_gemini.png"
    render_lyrics_image(lyrics, dest_gemini, provider="gemini_music")
    with Image.open(dest_gemini) as img:
        top_pixel = img.getpixel((0, 0))
        assert top_pixel == (220, 90, 20)
        # Red channel is high, green is medium-high, blue is low
        assert top_pixel[0] > 200
        assert top_pixel[1] > 70
        assert top_pixel[2] < 50

    # 4. Explicit theme="orange" -> orange background
    dest_theme = tmp_path / "lyrics_orange_theme.png"
    render_lyrics_image(lyrics, dest_theme, theme="orange")
    with Image.open(dest_theme) as img:
        top_pixel = img.getpixel((0, 0))
        assert top_pixel == (220, 90, 20)
