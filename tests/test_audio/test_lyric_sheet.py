"""The lyric sheet — the one deliverable whose orthography we own end to end.

The sheet is the customer-visible proof that we got the name right, so these tests are
about characters, not layout. Three rules are load-bearing:

* after o/g an apostrophe-like mark is U+02BB MODIFIER LETTER TURNED COMMA (oʻ, gʻ);
* everywhere else in Uzbek it is U+02BC MODIFIER LETTER APOSTROPHE, the glottal stop;
* the o/g rule must NOT run for Russian or English, where it would maul "don't".
"""

from __future__ import annotations

from pathlib import Path

from hbd.audio.lyric_sheet import (
    canonicalize_uzbek_latin,
    enforce_display_name,
    render_lyric_sheet,
    write_lyric_sheet,
)
from hbd.contracts import Language, LyricSection, is_err, is_ok
from tests.conftest import UZBEK_NAME_CANONICAL, UZBEK_NAME_TYPED, make_lyrics

TURNED_COMMA = "ʻ"  # MODIFIER LETTER TURNED COMMA — correct in oʻ / gʻ
MODIFIER_APOSTROPHE = "ʼ"  # MODIFIER LETTER APOSTROPHE — the glottal stop
LEFT_QUOTE = "‘"  # what a phone keyboard types
RIGHT_QUOTE = "’"  # what a word processor autocorrects to


# ---------------------------------------------------------------------------
# canonicalize_uzbek_latin
# ---------------------------------------------------------------------------
def test_a_mark_after_o_becomes_the_turned_comma() -> None:
    # Arrange: the typed form uses U+2018.
    assert canonicalize_uzbek_latin(f"o{LEFT_QUOTE}tsa") == f"o{TURNED_COMMA}tsa"


def test_a_mark_after_g_becomes_the_turned_comma() -> None:
    assert canonicalize_uzbek_latin(f"qo{RIGHT_QUOTE}shig{RIGHT_QUOTE}ing") == (
        f"qo{TURNED_COMMA}shig{TURNED_COMMA}ing"
    )


def test_a_mark_after_a_capital_o_or_g_becomes_the_turned_comma() -> None:
    assert canonicalize_uzbek_latin(f"G{LEFT_QUOTE}ulomjon") == f"G{TURNED_COMMA}ulomjon"
    assert canonicalize_uzbek_latin(f"O{LEFT_QUOTE}zbekiston") == f"O{TURNED_COMMA}zbekiston"


def test_a_mark_after_any_other_letter_is_the_glottal_stop_not_the_turned_comma() -> None:
    # Arrange: maʼno takes U+02BC. Blanket-replacing every mark with U+02BB is the
    # common shortcut, and it is wrong.
    assert canonicalize_uzbek_latin("ma'no") == f"ma{MODIFIER_APOSTROPHE}no"


def test_every_apostrophe_variant_a_keyboard_emits_is_canonicalised() -> None:
    for variant in ("'", "\u0060", "\u00b4", LEFT_QUOTE, RIGHT_QUOTE, "\u2032", "\u02b9"):
        assert canonicalize_uzbek_latin(f"o{variant}z") == f"o{TURNED_COMMA}z"


def test_a_correct_mark_survives_canonicalisation_unchanged() -> None:
    assert canonicalize_uzbek_latin(UZBEK_NAME_CANONICAL) == UZBEK_NAME_CANONICAL


def test_a_leading_mark_with_no_letter_before_it_is_a_glottal_stop() -> None:
    assert canonicalize_uzbek_latin("'abc") == f"{MODIFIER_APOSTROPHE}abc"


def test_text_without_any_mark_is_returned_untouched() -> None:
    assert canonicalize_uzbek_latin("Bugun quyosh porlaydi") == "Bugun quyosh porlaydi"


# ---------------------------------------------------------------------------
# enforce_display_name
# ---------------------------------------------------------------------------
def test_a_mis_typed_name_is_rewritten_to_the_display_form() -> None:
    # Arrange: the model wrote the name with U+2018; the sheet must show U+02BB.
    text = f"Baxtli bo'lsin {UZBEK_NAME_TYPED}!"

    result = enforce_display_name(text, UZBEK_NAME_CANONICAL)

    assert UZBEK_NAME_CANONICAL in result
    assert UZBEK_NAME_TYPED not in result


def test_the_rewrite_is_case_insensitive() -> None:
    text = f"g{RIGHT_QUOTE}ulomjon"

    assert enforce_display_name(text, UZBEK_NAME_CANONICAL) == UZBEK_NAME_CANONICAL


def test_a_name_without_a_mark_leaves_ordinary_words_alone() -> None:
    # Arrange: no mark in the name means nothing could have been mistyped, so the
    # function must not touch the surrounding text at all.
    text = "Alisher, don't worry"

    assert enforce_display_name(text, "Alisher") == text


def test_a_name_containing_regex_metacharacters_is_matched_literally() -> None:
    text = f"hello A.B{LEFT_QUOTE}C"

    assert enforce_display_name(text, f"A.B{TURNED_COMMA}C") == f"hello A.B{TURNED_COMMA}C"


# ---------------------------------------------------------------------------
# render_lyric_sheet
# ---------------------------------------------------------------------------
def test_the_sheet_carries_the_title_and_every_section() -> None:
    # Arrange
    lyrics = make_lyrics()

    # Act
    sheet = render_lyric_sheet(lyrics)

    # Assert
    assert lyrics.title in sheet
    for section in lyrics.sections:
        assert f"[{section.label}]" in sheet
        for line in section.lines:
            assert line in sheet


def test_the_sheet_shows_the_display_name_even_when_the_lyrics_mis_spelled_it() -> None:
    # Arrange: the LLM emitted the keyboard form; the display form is canonical.
    lyrics = make_lyrics(
        sections=(
            LyricSection(label="hook", lines=(f"{UZBEK_NAME_TYPED}, tugʻilgan kuning bilan",)),
        )
    )

    sheet = render_lyric_sheet(lyrics)

    assert UZBEK_NAME_CANONICAL in sheet
    assert LEFT_QUOTE not in sheet


def test_uzbek_latin_body_text_is_canonicalised_not_just_the_name() -> None:
    lyrics = make_lyrics(
        sections=(LyricSection(label="verse", lines=(f"Yillar o{LEFT_QUOTE}tsa ham",)),)
    )

    assert f"o{TURNED_COMMA}tsa" in render_lyric_sheet(lyrics)


def test_an_english_sheet_does_not_maul_an_ordinary_contraction() -> None:
    # Arrange: the o/g rule would turn "don't" into "donʼt" if it ran here.
    lyrics = make_lyrics(
        language=Language.EN,
        title="Happy Birthday",
        name_display="Alisher",
        sections=(LyricSection(label="verse", lines=("Don't stop believing, Alisher",)),),
    )

    sheet = render_lyric_sheet(lyrics)

    assert "Don't stop" in sheet
    assert MODIFIER_APOSTROPHE not in sheet


def test_a_russian_sheet_preserves_the_yo_vowel() -> None:
    # Arrange: Алёна is a different name from Алена and must survive typesetting.
    lyrics = make_lyrics(
        language=Language.RU,
        title="С днём рождения",
        name_display="Алёна",
        sections=(LyricSection(label="куплет", lines=("Алёна, поздравляю тебя",)),),
    )

    sheet = render_lyric_sheet(lyrics)

    assert "Алёна" in sheet
    assert "Алена" not in sheet


def test_the_sheet_underlines_the_title_to_its_own_width() -> None:
    lyrics = make_lyrics(title="Kun")

    lines = render_lyric_sheet(lyrics).splitlines()

    assert lines[0] == "Kun"
    assert len(lines[1]) == len("Kun")


def test_windows_line_endings_are_normalised() -> None:
    lyrics = make_lyrics(
        sections=(LyricSection(label="verse", lines=("first\r\nsecond",)),),
    )

    assert "\r" not in render_lyric_sheet(lyrics)


def test_the_sheet_ends_with_exactly_one_newline() -> None:
    sheet = render_lyric_sheet(make_lyrics())

    assert sheet.endswith("\n")
    assert not sheet.endswith("\n\n")


def test_rendering_is_pure_and_repeatable() -> None:
    lyrics = make_lyrics()

    assert render_lyric_sheet(lyrics) == render_lyric_sheet(lyrics)


# ---------------------------------------------------------------------------
# write_lyric_sheet
# ---------------------------------------------------------------------------
def test_the_sheet_is_written_as_utf8_with_the_correct_mark_on_disk(tmp_path: Path) -> None:
    # Arrange
    destination = tmp_path / "lyrics.txt"

    # Act
    result = write_lyric_sheet(make_lyrics(), destination=destination)

    # Assert: the bytes themselves must carry U+02BB (0xCA 0xBB in UTF-8).
    assert is_ok(result)
    assert TURNED_COMMA.encode() in destination.read_bytes()
    assert destination.read_text(encoding="utf-8").startswith("Tugʻilgan kun")


def test_writing_creates_a_missing_directory(tmp_path: Path) -> None:
    destination = tmp_path / "orders" / "42" / "lyrics.txt"

    assert is_ok(write_lyric_sheet(make_lyrics(), destination=destination))
    assert destination.exists()


def test_writing_leaves_no_scratch_directory_behind(tmp_path: Path) -> None:
    write_lyric_sheet(make_lyrics(), destination=tmp_path / "lyrics.txt")

    assert [child.name for child in tmp_path.iterdir()] == ["lyrics.txt"]


def test_an_unwritable_destination_is_an_error_not_an_exception(tmp_path: Path) -> None:
    # Arrange: a directory where the file should go — the write cannot succeed.
    destination = tmp_path / "lyrics.txt"
    destination.mkdir()

    result = write_lyric_sheet(make_lyrics(), destination=destination)

    assert is_err(result)
    assert str(destination) in str(result.error.context["destination"])
