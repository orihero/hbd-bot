"""What a well-formed lyric looks like — the rules both paths now share.

These helpers used to be private to ``content.py`` and were only ever exercised through
the LLM writer. Since the wizard gained a paste-your-own path they decide the shape of a
lyric nobody generated, so they are tested here directly: the clamps, the label fallback,
the title fallback, and above all the guarantee the whole name subsystem rests on — that
exactly one section is the hook and that the hook actually says the name.
"""

from __future__ import annotations

from bayram.contracts import Language, LyricDraft
from bayram.pipeline.lyric_shape import (
    DEFAULT_TITLE,
    MAX_LABEL_CHARS,
    MAX_LINE_CHARS,
    MAX_LINES_PER_SECTION,
    MAX_TITLE_CHARS,
    build_lyric_draft,
    build_sections,
    clean_label,
    clean_lines,
    hook_index,
)
from tests.conftest import UZBEK_NAME_CANONICAL

Section = tuple[str, tuple[str, ...], bool]


def _draft(
    *sections: Section, title: str = "Bayram", name: str = UZBEK_NAME_CANONICAL
) -> LyricDraft:
    """Build a draft from loose section triples, so a test states only what it varies."""
    return build_lyric_draft(sections, title=title, language=Language.UZ_LATN, name_display=name)


# ---------------------------------------------------------------------------
# clean_lines
# ---------------------------------------------------------------------------
def test_clean_lines_trims_each_line_and_drops_the_blank_ones() -> None:
    # Arrange
    raw = ("  Bugun quyosh porlaydi  ", "", "   ", "\tYillar oʻtsa ham\n")

    # Act
    cleaned = clean_lines(raw)

    # Assert
    assert cleaned == ("Bugun quyosh porlaydi", "Yillar oʻtsa ham")


def test_clean_lines_clamps_a_runaway_line_to_the_character_limit() -> None:
    # Arrange
    raw = ("a" * (MAX_LINE_CHARS + 40),)

    # Act
    cleaned = clean_lines(raw)

    # Assert
    assert cleaned == ("a" * MAX_LINE_CHARS,)


def test_clean_lines_strips_before_it_clamps_so_padding_costs_no_real_characters() -> None:
    # Arrange: the padding must not eat into the budget the real text is allowed
    raw = ("   " + "a" * MAX_LINE_CHARS + "   ",)

    # Act
    cleaned = clean_lines(raw)

    # Assert
    assert cleaned == ("a" * MAX_LINE_CHARS,)


def test_clean_lines_keeps_only_the_first_lines_a_section_is_allowed() -> None:
    # Arrange
    raw = tuple(f"line {index}" for index in range(MAX_LINES_PER_SECTION + 5))

    # Act
    cleaned = clean_lines(raw)

    # Assert
    assert len(cleaned) == MAX_LINES_PER_SECTION
    assert cleaned[0] == "line 0"


def test_clean_lines_counts_only_the_survivors_towards_the_line_limit() -> None:
    # Arrange: blanks are dropped first, so they must not push real lines out
    raw = ("", "  ", *(f"line {index}" for index in range(MAX_LINES_PER_SECTION)))

    # Act
    cleaned = clean_lines(raw)

    # Assert
    assert len(cleaned) == MAX_LINES_PER_SECTION
    assert cleaned[-1] == f"line {MAX_LINES_PER_SECTION - 1}"


# ---------------------------------------------------------------------------
# clean_label
# ---------------------------------------------------------------------------
def test_clean_label_trims_a_padded_label() -> None:
    # Arrange / Act
    label = clean_label("  chorus  ", index=0)

    # Assert
    assert label == "chorus"


def test_clean_label_falls_back_to_the_one_based_position_when_it_is_blank() -> None:
    # Arrange / Act
    label = clean_label("   ", index=2)

    # Assert
    assert label == "section-3"


def test_clean_label_clamps_a_long_label_to_the_column_it_has_to_fit() -> None:
    # Arrange / Act
    label = clean_label("x" * (MAX_LABEL_CHARS + 20), index=0)

    # Assert
    assert label == "x" * MAX_LABEL_CHARS


# ---------------------------------------------------------------------------
# hook_index
# ---------------------------------------------------------------------------
def test_hook_index_takes_the_first_flag_even_when_a_later_section_is_flagged_too() -> None:
    # Arrange
    sections: tuple[Section, ...] = (
        ("verse", ("quyosh porlaydi",), False),
        ("hook", ("bir kuni",), True),
        ("outro", ("yana bir kuni",), True),
    )

    # Act / Assert
    assert hook_index(sections, UZBEK_NAME_CANONICAL) == 1


def test_hook_index_prefers_the_flag_over_a_section_that_merely_says_the_name() -> None:
    # Arrange
    sections: tuple[Section, ...] = (
        ("verse", (f"{UZBEK_NAME_CANONICAL} bugun kuladi",), False),
        ("hook", ("bir kuni",), True),
    )

    # Act / Assert
    assert hook_index(sections, UZBEK_NAME_CANONICAL) == 1


def test_hook_index_falls_back_to_the_first_section_that_says_the_name() -> None:
    # Arrange
    sections: tuple[Section, ...] = (
        ("verse", ("quyosh porlaydi",), False),
        ("chorus", (f"yashasin {UZBEK_NAME_CANONICAL}",), False),
    )

    # Act / Assert
    assert hook_index(sections, UZBEK_NAME_CANONICAL) == 1


def test_hook_index_matches_the_name_regardless_of_case() -> None:
    # Arrange
    sections: tuple[Section, ...] = (
        ("verse", ("quyosh porlaydi",), False),
        ("chorus", (UZBEK_NAME_CANONICAL.upper(),), False),
    )

    # Act / Assert
    assert hook_index(sections, UZBEK_NAME_CANONICAL) == 1


def test_hook_index_settles_on_the_first_section_when_nothing_points_at_one() -> None:
    # Arrange
    sections: tuple[Section, ...] = (
        ("verse", ("quyosh porlaydi",), False),
        ("chorus", ("yillar oʻtadi",), False),
    )

    # Act / Assert
    assert hook_index(sections, UZBEK_NAME_CANONICAL) == 0


# ---------------------------------------------------------------------------
# build_sections
# ---------------------------------------------------------------------------
def test_build_sections_flags_exactly_the_chosen_section_and_no_other() -> None:
    # Arrange: the model flagged two, which the composition plan cannot honour
    sections: tuple[Section, ...] = (
        ("verse", ("quyosh porlaydi",), True),
        ("hook", (UZBEK_NAME_CANONICAL,), True),
        ("outro", ("xayr",), True),
    )

    # Act
    built = build_sections(sections, name=UZBEK_NAME_CANONICAL, hook_index=1)

    # Assert
    assert [section.is_name_hook for section in built] == [False, True, False]


def test_build_sections_puts_the_name_into_a_hook_that_forgot_it() -> None:
    # Arrange
    sections: tuple[Section, ...] = (("hook", ("bugun bayram",), True),)

    # Act
    built = build_sections(sections, name=UZBEK_NAME_CANONICAL, hook_index=0)

    # Assert
    assert built[0].lines == (UZBEK_NAME_CANONICAL, "bugun bayram")


def test_build_sections_leaves_a_hook_that_already_says_the_name_alone() -> None:
    # Arrange: a differently-cased mention still counts, so nothing is prepended
    lines = (f"{UZBEK_NAME_CANONICAL.upper()} bilan",)
    sections: tuple[Section, ...] = (("hook", lines, True),)

    # Act
    built = build_sections(sections, name=UZBEK_NAME_CANONICAL, hook_index=0)

    # Assert
    assert built[0].lines == lines


def test_build_sections_keeps_a_repaired_hook_within_the_line_limit() -> None:
    # Arrange: a full hook with no name has nowhere to put one without dropping a line
    lines = tuple(f"line {index}" for index in range(MAX_LINES_PER_SECTION))
    sections: tuple[Section, ...] = (("hook", lines, True),)

    # Act
    built = build_sections(sections, name=UZBEK_NAME_CANONICAL, hook_index=0)

    # Assert
    assert len(built[0].lines) == MAX_LINES_PER_SECTION
    assert built[0].lines[0] == UZBEK_NAME_CANONICAL
    assert built[0].lines[-1] == f"line {MAX_LINES_PER_SECTION - 2}"


def test_build_sections_does_not_touch_the_lines_of_a_section_that_is_not_the_hook() -> None:
    # Arrange
    sections: tuple[Section, ...] = (
        ("verse", ("quyosh porlaydi",), False),
        ("hook", (UZBEK_NAME_CANONICAL,), True),
    )

    # Act
    built = build_sections(sections, name=UZBEK_NAME_CANONICAL, hook_index=1)

    # Assert
    assert built[0].lines == ("quyosh porlaydi",)
    assert built[0].label == "verse"


# ---------------------------------------------------------------------------
# build_lyric_draft
# ---------------------------------------------------------------------------
def test_build_lyric_draft_always_ends_up_with_exactly_one_hook_that_says_the_name() -> None:
    # Arrange: nothing is flagged and nobody mentions the recipient at all
    sections: tuple[Section, ...] = (
        ("verse", ("quyosh porlaydi",), False),
        ("chorus", ("yillar oʻtadi",), False),
    )

    # Act
    draft = _draft(*sections)

    # Assert
    assert len(draft.name_hook_sections) == 1
    assert UZBEK_NAME_CANONICAL in draft.name_hook_sections[0].lines


def test_build_lyric_draft_hooks_the_section_the_writer_flagged() -> None:
    # Arrange
    sections: tuple[Section, ...] = (
        ("verse", ("quyosh porlaydi",), False),
        ("hook", (f"{UZBEK_NAME_CANONICAL} bilan",), True),
    )

    # Act
    draft = _draft(*sections)

    # Assert
    assert draft.sections[1].is_name_hook is True
    assert draft.name_hook_sections[0].label == "hook"


def test_build_lyric_draft_carries_the_language_and_the_display_name_through() -> None:
    # Arrange / Act
    draft = _draft(("hook", (UZBEK_NAME_CANONICAL,), True))

    # Assert
    assert draft.language is Language.UZ_LATN
    assert draft.name_display == UZBEK_NAME_CANONICAL


def test_build_lyric_draft_keeps_a_real_title_and_trims_its_padding() -> None:
    # Arrange / Act
    draft = _draft(("hook", (UZBEK_NAME_CANONICAL,), True), title="  Sen uchun  ")

    # Assert
    assert draft.title == "Sen uchun"


def test_build_lyric_draft_falls_back_when_the_title_is_only_whitespace() -> None:
    # Arrange: three spaces would otherwise pass min_length=1 and ship as the song's name
    # Act
    draft = _draft(("hook", (UZBEK_NAME_CANONICAL,), True), title="   ")

    # Assert
    assert draft.title == DEFAULT_TITLE


def test_build_lyric_draft_falls_back_when_there_is_no_title_at_all() -> None:
    # Arrange / Act
    draft = _draft(("hook", (UZBEK_NAME_CANONICAL,), True), title="")

    # Assert
    assert draft.title == DEFAULT_TITLE


def test_build_lyric_draft_clamps_a_title_that_would_not_fit_the_field() -> None:
    # Arrange / Act
    draft = _draft(("hook", (UZBEK_NAME_CANONICAL,), True), title="t" * (MAX_TITLE_CHARS + 50))

    # Assert
    assert draft.title == "t" * MAX_TITLE_CHARS


def test_build_lyric_draft_shapes_a_pasted_lyric_exactly_like_a_written_one() -> None:
    """The whole reason the module exists: two callers, one set of rules.

    A paste arrives as generically labelled blocks with nothing flagged. It must still come
    out with the same one-hook-carries-the-name guarantee the composition plan relies on.
    """
    # Arrange
    pasted: tuple[Section, ...] = (
        ("section-1", ("Bugun bayram, hamma kuladi",), False),
        ("section-2", ("Yillar oʻtsa ham esda qolasan",), False),
    )

    # Act
    draft = _draft(*pasted, title="Mening qoʻshigʻim")

    # Assert
    assert len(draft.name_hook_sections) == 1
    assert draft.name_hook_sections[0].lines[0] == UZBEK_NAME_CANONICAL
    assert [section.label for section in draft.sections] == ["section-1", "section-2"]


# ---------------------------------------------------------------------------
# Orthography canonicalisation
# ---------------------------------------------------------------------------
def test_uzbek_latin_lines_are_canonicalised_whatever_mark_the_writer_used() -> None:
    """The one character this product lives or dies by is not left to the model.

    A model asked for U+02BB obeys inconsistently and a customer's phone keyboard emits
    U+2019 regardless, so both producers are normalised here rather than trusted.
    """
    # Arrange
    mixed = "Bugun o'g'lim tug'ilgan kun, san'at bilan"

    # Act
    draft = _draft(("verse-1", (mixed,), False), ("hook", (UZBEK_NAME_CANONICAL,), True))

    # Assert
    assert draft.sections[0].lines[0] == "Bugun oʻgʻlim tugʻilgan kun, sanʼat bilan"
    assert "'" not in draft.sections[0].lines[0]


def test_the_title_is_canonicalised_before_it_is_clamped() -> None:
    # Arrange / Act
    draft = _draft(("hook", (UZBEK_NAME_CANONICAL,), True), title="Tug’ilgan kun")

    # Assert
    assert draft.title == "Tugʻilgan kun"


def test_a_curly_apostrophe_is_canonicalised_so_the_hook_still_finds_the_name() -> None:
    """Marks are fixed BEFORE the hook is chosen, or the name match silently misses."""
    # Arrange / Act
    draft = build_lyric_draft(
        (("verse-1", ("Bayram keldi",), False), ("chorus", ("G‘ulomjon, bugun bayram",), False)),
        title="Bayram",
        language=Language.UZ_LATN,
        name_display=UZBEK_NAME_CANONICAL,
    )

    # Assert
    assert draft.name_hook_sections[0].label == "chorus"
    assert draft.name_hook_sections[0].lines[0] == f"{UZBEK_NAME_CANONICAL}, bugun bayram"


def test_non_uzbek_languages_keep_their_apostrophes_untouched() -> None:
    """``marks.py`` maps a mark after o/g to U+02BB — which would mangle an English possessive."""
    # Arrange / Act
    draft = build_lyric_draft(
        (("verse-1", ("It's Bob's day, go's and all",), False),),
        title="Bob's song",
        language=Language.EN,
        name_display="Bob",
    )

    # Assert
    assert draft.sections[0].lines[0] == "It's Bob's day, go's and all"
    assert draft.title == "Bob's song"
