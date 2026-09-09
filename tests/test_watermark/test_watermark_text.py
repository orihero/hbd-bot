"""The watermark strings, and the two properties that make them safe to put in an argv.

Three things are pinned here and each one has a specific, expensive failure behind it:

* **The tag keys are exactly title / artist / album / comment.** Players disagree about
  which field they surface — a car stereo shows artist, a phone lock screen shows title, a
  file manager shows comment — so the handle is put in three of them deliberately. A key
  dropped or renamed silently removes the watermark from whichever players read that one.
* **No tag value contains a newline or an ``=``.** These become
  ``ffmpeg -metadata key=value`` argv elements: an ``=`` truncates the tag at the wrong
  place and a newline is unrepresentable in the log line somebody will use to debug the mux.
* **The module is a HARD LEAF.** The bot process, the delivery layer, the pipeline and the
  ffmpeg argv builders all import it, and those already sit on opposite sides of every
  layering rule in this codebase, so the only import edge that can never cycle is none at
  all. Asserted from the parsed SOURCE rather than from ``sys.modules``, because a lazy
  import inside a function is still a back-edge and would not show up at runtime.

What is NOT tested here is the invariant the module exists for — that no watermark reaches a
``LyricDraft`` or a vendor payload. That belongs to the packages that BUILD those payloads,
and :func:`hbd.watermark.contains_watermark` is the predicate they assert with.
"""

from __future__ import annotations

import ast
from pathlib import Path

import hbd.watermark as watermark
from hbd.watermark import (
    COVER_LINES,
    SHEET_RULE,
    WATERMARK_HANDLE,
    WATERMARK_INVITE_TAG,
    WATERMARK_SONG_TAG,
    audio_tags,
    contains_watermark,
)

#: The keys, in order, that every downstream ffmpeg argv builder expects to receive.
_EXPECTED_TAG_KEYS = ("title", "artist", "album", "comment")


# ---------------------------------------------------------------------------
# The tags
# ---------------------------------------------------------------------------
def test_the_audio_tags_are_exactly_title_artist_album_and_comment() -> None:
    # Arrange / Act
    tags = audio_tags(title="Happy Birthday, Aziz")

    # Assert — a tuple of pairs and not a mapping, because the caller turns each pair into
    # two ordered argv elements and a dict would leave that order to the next edit.
    assert tuple(key for key, _ in tags) == _EXPECTED_TAG_KEYS


def test_the_title_tag_is_the_song_and_every_other_tag_carries_the_handle() -> None:
    # Arrange — the title is the ONE value that is not a watermark: it is what a phone's lock
    # screen shows, so it must be the customer's song and not an advertisement.
    title = "Happy Birthday, Aziz"

    # Act
    values = dict(audio_tags(title=title))

    # Assert
    assert values["title"] == title
    assert values["artist"] == WATERMARK_HANDLE
    assert WATERMARK_HANDLE in values["album"]
    assert WATERMARK_HANDLE in values["comment"]


def test_no_tag_value_can_carry_a_newline_or_an_equals_sign() -> None:
    # Arrange — a hostile title standing in for a recipient name or a locale string, since
    # both reach this function unvalidated. Sanitised rather than refused: losing the whole
    # song over a cosmetic tag is the worse failure.
    tags = audio_tags(title="a=b\nc=d")

    # Act
    values = [value for _, value in tags]

    # Assert
    for value in values:
        assert "=" not in value
        assert "\n" not in value
        assert "\r" not in value
        assert value == value.encode("ascii", "ignore").decode("ascii")


def test_a_title_that_needed_no_sanitising_is_passed_through_unchanged() -> None:
    # Arrange / Act / Assert — the sanitiser must be invisible in the ordinary case, or every
    # song in the catalogue quietly gains mangled whitespace.
    assert dict(audio_tags(title="Song Number 3"))["title"] == "Song Number 3"
    assert dict(audio_tags(title="Happy Birthday, Aziz!"))["title"] == "Happy Birthday, Aziz!"


def test_a_non_ascii_title_is_transliterated_away_rather_than_refused() -> None:
    # Arrange — the ID3 frame's text encoding is negotiated by the muxer, and a non-ASCII
    # byte turns a cosmetic tag into an encoding question somebody has to own under pressure.
    # Dropping the character is a visible cost paid in a tag; refusing to mux is a song the
    # customer does not get. U+02BB is the character this whole product exists to get right,
    # which is exactly why it may not be smuggled into an argv element.
    tags = dict(audio_tags(title="Tugʻilgan kun"))

    # Act / Assert
    assert tags["title"] == "Tugilgan kun"


# ---------------------------------------------------------------------------
# The strings
# ---------------------------------------------------------------------------
def test_the_sheet_rule_is_recognised_as_a_watermark_and_a_lyric_line_is_not() -> None:
    # Arrange — this predicate is what other packages assert the vendor payload against, so
    # it has to be true of what we add and false of what a customer wrote.
    lyric = "Bugun sening tugʻilgan kuning, quvonchli kun"

    # Act / Assert
    assert contains_watermark(SHEET_RULE)
    assert contains_watermark(WATERMARK_SONG_TAG)
    assert contains_watermark(WATERMARK_INVITE_TAG)
    assert not contains_watermark(lyric)


def test_the_watermark_is_recognised_whatever_case_it_arrives_in() -> None:
    # Arrange — captions pass through locale catalogues and title-casing, and a case-
    # sensitive check would let a reworded caption leak into a payload unnoticed.
    # Act / Assert
    assert contains_watermark("THIS SONG HAS BEEN GENERATED BY @HBDUZBOT")
    assert contains_watermark("...generated By someone")


def test_the_cover_prints_the_invitation_and_ends_on_the_handle() -> None:
    # Arrange / Act / Assert — the lines are split by hand rather than wrapped, because the
    # image is 320x320 and has to stay legible as a Telegram thumbnail.
    assert COVER_LINES[-1] == WATERMARK_HANDLE
    assert contains_watermark("\n".join(COVER_LINES))


# ---------------------------------------------------------------------------
# The leaf guarantee
# ---------------------------------------------------------------------------
def test_the_watermark_module_has_no_first_party_imports_at_all() -> None:
    # Arrange — four modules on four different layers import this one (the bot's captions,
    # the delivery layer's lyric sheet, the pipeline's cover art and the ffmpeg argv
    # builders' metadata). The source is parsed rather than the runtime inspected, because a
    # lazily-imported module inside a function would still be a back-edge and would not show
    # up in ``sys.modules``. Same idiom as
    # ``tests/test_entitlements/test_errors.py::test_the_entitlements_module_imports_nothing…``.
    source = Path(watermark.__file__).read_text(encoding="utf-8")

    # Act
    tree = ast.parse(source)
    from_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    plain_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    # Assert — the empty set, not a permitted subset. There is deliberately nothing in this
    # codebase this module is allowed to import.
    first_party = {name for name in from_imports | plain_imports if name.split(".")[0] == "hbd"}
    assert first_party == set()
