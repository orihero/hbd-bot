"""Parsing a pasted lyric — the boundary between typed text and a composable draft.

``parse_typed_lyrics`` was previously only ever driven through the dispatcher, which meant
its bounds and its section cap were exercised incidentally or not at all. They are
load-bearing: the section cap is what keeps a paste inside the plan builder's chunk budget,
and the two length bounds are the only thing standing between "ok" and a song.

The watermark block at the bottom pins the newer and sharper reason this boundary matters.
The bot prints its own watermark into the customer's chat — under the lyric preview, around
every delivered lyric sheet — immediately above a screen that says "send me your own as a
message". Selecting all of it and pasting it back is ordinary behaviour, and it used to put
"✨ Generate yours at @bayram_uzbot" into a ``LyricSection`` and from there into the vendor
chunk text, where it would have been sung. Nothing in the suite pasted anything before, so
the leak was green.
"""

from __future__ import annotations

import pytest

from bayram.bot.i18n import translate
from bayram.bot.lyrics_entry import (
    LYRICS_TOO_LONG_KEY,
    LYRICS_TOO_SHORT_KEY,
    MAX_LYRIC_CHARS,
    MIN_LYRIC_CHARS,
    parse_typed_lyrics,
)
from bayram.contracts import Err, Language, LyricDraft, Ok, Result
from bayram.pipeline.lyric_shape import MAX_LINES_PER_SECTION, MAX_LYRIC_SECTIONS
from bayram.watermark import SHEET_RULE, WATERMARK_HANDLE, contains_watermark

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


# ---------------------------------------------------------------------------
# the watermark boundary
# ---------------------------------------------------------------------------
# This is the one place untrusted text becomes a ``LyricDraft``, and the bot has put its own
# watermark into the customer's chat directly above a screen inviting a paste. The defect
# these tests pin: nothing filtered, so "✨ Generate yours at @bayram_uzbot" pasted back became a
# section, then a vendor chunk, and was sung. ``contains_watermark`` is the assertion because
# it is the same predicate the vendor-payload tests use — if it is ever widened, this
# boundary is widened with it.
LOCALISED_WATERMARK_KEYS = ("watermark.invite", "watermark.song")


def watermark_line(key: str, language: Language) -> str:
    """The exact line the bot itself printed, in one locale. Rendered, never hand-typed."""
    return translate(key, language, handle=WATERMARK_HANDLE)


@pytest.mark.parametrize("language", list(Language))
@pytest.mark.parametrize("key", LOCALISED_WATERMARK_KEYS)
def test_the_watermark_the_bot_printed_never_survives_a_paste_in_any_locale(
    key: str, language: Language
) -> None:
    """All four locales, both sentences: pasted back, none of it reaches the draft.

    ``watermark.invite`` and ``watermark.song`` are catalogue entries, so a Russian customer
    pastes back Russian watermark text and an Uzbek one pastes back Uzbek. A filter written
    against the English sentence would leak in three locales out of four; the strings are
    therefore rendered here through ``translate`` exactly as the bot renders them, rather
    than typed into this file where they could drift from the catalogue.
    """
    # Arrange — the shape of a real paste: the preview's blockquote, then the bot's line
    mark = watermark_line(key, language)
    typed = f"The candles are lit tonight\nand the table is laid\n\n{mark}"

    # Act
    draft = value_of(parse_typed_lyrics(typed, language=language, name_display=None, title="T"))

    # Assert — the customer's words are intact, the bot's are gone
    sung = draft.as_plain_text()
    assert "The candles are lit tonight" in sung
    assert not contains_watermark(sung)
    assert all(not contains_watermark(line) for section in draft.sections for line in section.lines)


@pytest.mark.parametrize("language", list(Language))
def test_a_forwarded_lyric_sheet_pasted_back_loses_its_rules_and_keeps_its_song(
    language: Language,
) -> None:
    """The archived sheet is wrapped header-and-footer, and forwarding it is the plan.

    ``SHEET_RULE`` is generated rather than translated — the ``lyrics.txt`` artefact carries
    no language — so it arrives identically whichever locale the recipient then pastes it
    in. Before the filter this paste produced ``'--- Generate yours at @bayram_uzbot ---'`` as
    both the first and the last chunk of the vendor plan.
    """
    # Arrange
    typed = f"{SHEET_RULE}\n\nBir kun keladi\nva shamlar yonadi\n\n{SHEET_RULE}"

    # Act
    draft = value_of(parse_typed_lyrics(typed, language=language, name_display=None, title="T"))

    # Assert
    assert not contains_watermark(draft.as_plain_text())
    assert len(draft.sections) == 1
    assert draft.sections[0].lines == ("Bir kun keladi", "va shamlar yonadi")


@pytest.mark.parametrize("language", list(Language))
def test_a_paste_that_is_nothing_but_watermark_is_refused_as_too_short(
    language: Language,
) -> None:
    """Stripping can empty a paste, and the module already knows how to say that.

    A customer who selects only the invite line and sends it has sent no song. Rather than a
    fourth rejection message to write and translate in four catalogues, the emptied text
    falls through to the existing lower bound — which is also the honest description of what
    is wrong with it. What must NOT happen is an ``Ok`` carrying a draft of pure watermark,
    or a ``pydantic`` error escaping a module that promises never to raise.
    """
    # Arrange — both lines the bot could have printed, and nothing else
    typed = "\n".join(watermark_line(key, language) for key in LOCALISED_WATERMARK_KEYS)
    assert len(typed) > MIN_LYRIC_CHARS, "the paste must clear the floor before filtering"

    # Act
    result = parse_typed_lyrics(typed, language=language, name_display=None, title="T")

    # Assert
    assert isinstance(result, Err)
    assert result.error.user_message_key == LYRICS_TOO_SHORT_KEY
    assert result.error.context["length"] == 0


def test_a_customers_own_sentence_naming_the_bot_loses_that_line_and_keeps_the_rest() -> None:
    """DECIDED: the line goes, whoever typed it. The rest of the lyric is untouched.

    ``contains_watermark`` is deliberately generous, so "thanks to @bayram_uzbot for this" —
    genuinely the customer's own words, in the customer's own thank-you verse — is dropped
    along with the pasted-back ones. That is the choice, and the reason is that the
    invariant is about what gets SUNG, not about who typed it: a voice singing "at bayram_uzbot"
    ruins the song identically either way, and there is no signal in a Telegram message that
    could tell the two apart. The cost is one line of a multi-line paste, silently; the cost
    of the other choice is a customer hearing an advertisement in their birthday song.
    Rejecting the whole paste was considered and refused — the customer did nothing wrong
    and could not be told which of the words on their screen we objected to.
    """
    # Arrange
    typed = "The candles are lit tonight\nthanks to @bayram_uzbot for this\nand the table is laid"

    # Act
    draft = value_of(parse(typed))

    # Assert
    sung = draft.as_plain_text()
    assert "The candles are lit tonight" in sung
    assert "and the table is laid" in sung
    assert not contains_watermark(sung)


def test_the_filter_leaves_verse_breaks_alone_including_a_desktop_paste() -> None:
    """Dropping lines must not fuse verses, and rejoining normalises a CRLF paste.

    Blank lines are the section separator, and ``contains_watermark("")`` is False, so they
    survive the filter untouched. Rejoining the survivors with ``\\n`` additionally repairs
    the CRLF a desktop client pastes: the blank-line pattern is ``\\n[ \\t]*\\n`` and it
    never matched ``"\\r\\n\\r\\n"``, so before this a CRLF paste of two verses arrived as
    one section.
    """
    # Arrange
    invite = watermark_line("watermark.invite", Language.EN)
    typed = f"First verse here\r\nand its second line\r\n\r\nSecond verse here\r\n{invite}"

    # Act
    draft = value_of(parse(typed))

    # Assert
    assert len(draft.sections) == 2
    assert not contains_watermark(draft.as_plain_text())
