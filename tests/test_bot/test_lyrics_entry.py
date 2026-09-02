"""Parsing a pasted lyric — the boundary between typed text and a composable draft.

``parse_typed_lyrics`` was previously only ever driven through the dispatcher, which meant
its bounds and its section cap were exercised incidentally or not at all. They are
load-bearing: the section cap is what keeps a paste inside the plan builder's chunk budget,
and the two length bounds are the only thing standing between "ok" and a song.
"""

from __future__ import annotations

import pytest

from hbd.bot.lyrics_entry import (
    LYRICS_TOO_LONG_KEY,
    LYRICS_TOO_SHORT_KEY,
    MAX_LYRIC_CHARS,
    MIN_LYRIC_CHARS,
    parse_typed_lyrics,
)
from hbd.contracts import Err, Language, LyricDraft, Ok, Result
from hbd.pipeline.lyric_shape import MAX_LINES_PER_SECTION, MAX_LYRIC_SECTIONS

DISPLAY = "Gʻulomjon"  # U+02BB, the canonical spelling the hook must carry


def parse(text: str, *, title: str = "Tugʻilgan kun") -> Result[LyricDraft]:
    return parse_typed_lyrics(text, language=Language.UZ_LATN, name_display=DISPLAY, title=title)


def value_of(result: Result[LyricDraft]) -> LyricDraft:
    assert isinstance(result, Ok), f"expected a draft, got {result}"
    return result.value


# ---------------------------------------------------------------------------
# bounds
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("typed", ["ok", "yes please", "   ", "x" * (MIN_LYRIC_CHARS - 1)])
def test_a_message_too_short_to_be_a_song_is_refused(typed: str) -> None:
    """The approve button is right there, so "ok" is a misdirected press, not a lyric."""
    # Arrange / Act
    result = parse(typed)

    # Assert
    assert isinstance(result, Err)
    assert result.error.user_message_key == LYRICS_TOO_SHORT_KEY
    assert result.error.context["limit"] == MIN_LYRIC_CHARS


def test_a_message_too_long_to_be_a_song_is_refused_with_its_own_limit() -> None:
    """The two rejections must not report each other's number: the user acts on it."""
    # Arrange / Act
    result = parse("la " * MAX_LYRIC_CHARS)

    # Assert
    assert isinstance(result, Err)
    assert result.error.user_message_key == LYRICS_TOO_LONG_KEY
    assert result.error.context["limit"] == MAX_LYRIC_CHARS


def test_a_lyric_exactly_on_the_lower_bound_is_accepted() -> None:
    # Arrange / Act
    draft = value_of(parse("a" * MIN_LYRIC_CHARS))

    # Assert
    assert draft.sections


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------
def test_more_verses_than_the_plan_can_hold_are_clamped_not_carried() -> None:
    """The section cap is what keeps a paste inside the composition plan's chunk budget.

    ``build_composition_plan`` gives one chunk per section and a plan tops out well before
    a customer's patience does, so a paste of twelve verses has to be cut to eight here
    rather than discovered downstream. Nothing else in the suite pastes more than two.
    """
    # Arrange
    verses = "\n\n".join(f"Verse {index} for you\nand for tonight" for index in range(1, 13))

    # Act
    draft = value_of(parse(verses))

    # Assert
    assert len(draft.sections) == MAX_LYRIC_SECTIONS
    assert "Verse 12" not in draft.as_plain_text()


def test_a_verse_with_more_lines_than_a_section_holds_is_clamped() -> None:
    # Arrange
    verse = "\n".join(f"line {index}" for index in range(MAX_LINES_PER_SECTION + 5))

    # Act
    draft = value_of(parse(verse))

    # Assert
    assert all(len(section.lines) <= MAX_LINES_PER_SECTION for section in draft.sections)


def test_blank_lines_between_verses_become_sections_and_stray_blanks_do_not() -> None:
    # Arrange — two verses, separated by a blank line carrying stray spaces
    typed = "First verse here\nand its second line\n   \nSecond verse here\nand its second line"

    # Act
    draft = value_of(parse(typed))

    # Assert
    assert len(draft.sections) == 2


def test_a_pasted_lyric_gets_the_same_name_hook_guarantee_as_a_written_one() -> None:
    """Downstream isolates the name into its own chunk, so exactly one hook must exist."""
    # Arrange — the customer's words never mention the recipient
    typed = "The candles are lit and the table is laid\nand the night is long"

    # Act
    draft = value_of(parse(typed))

    # Assert
    hooks = draft.name_hook_sections
    assert len(hooks) == 1
    assert any(DISPLAY in line for line in hooks[0].lines)


def test_the_title_comes_from_the_caller_and_is_never_guessed_from_the_paste() -> None:
    """A title taken from the first line of someone's poem is a guess nobody asked for."""
    # Arrange / Act
    draft = value_of(parse("A first line that is not a title\nand a second", title="Bir kun"))

    # Assert
    assert draft.title == "Bir kun"
