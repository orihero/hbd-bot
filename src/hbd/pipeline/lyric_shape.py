"""What a well-formed lyric looks like. The single place that decides.

Two paths now produce a ``LyricDraft``: the LLM writer in ``content.py``, and the wizard,
where a customer can paste their own words instead of keeping the generated ones. If each
path clamped its own lines, invented its own section labels and chose its own name hook,
the two would drift apart the first time either was tuned — and a pasted lyric would be
composed under different rules than a written one, for no reason the customer could see.
So the clamps, the fallbacks and the hook guarantee live here and both paths call in.

A note on a name collision that has already caused confusion: ``hbd.providers.llm.schemas``
defines its *own* ``MAX_LYRIC_SECTIONS`` and ``MAX_LINES_PER_SECTION`` with wider values.
Those bound what a provider payload is allowed to *contain*. The constants below are the
domain limits — they decide what is actually sung. Import lyric shape from here, never
from the provider package.
"""

from __future__ import annotations

from typing import Final

from hbd.contracts import Language, LyricDraft, LyricSection

__all__ = [
    "MAX_LYRIC_SECTIONS",
    "MAX_LINES_PER_SECTION",
    "MAX_LINE_CHARS",
    "MAX_TITLE_CHARS",
    "MAX_LABEL_CHARS",
    "DEFAULT_SECTION_LABEL",
    "DEFAULT_TITLE",
    "clean_lines",
    "clean_label",
    "hook_index",
    "build_sections",
    "build_lyric_draft",
]

#: A composition plan tops out at 30 chunks; a lyric never needs anywhere near that.
MAX_LYRIC_SECTIONS: Final[int] = 8
MAX_LINES_PER_SECTION: Final[int] = 8
MAX_LINE_CHARS: Final[int] = 160
MAX_TITLE_CHARS: Final[int] = 120
MAX_LABEL_CHARS: Final[int] = 40
#: Fallback label when the model returns a blank one.
DEFAULT_SECTION_LABEL: Final[str] = "section"
DEFAULT_TITLE: Final[str] = "Tabrik"


def clean_lines(lines: tuple[str, ...]) -> tuple[str, ...]:
    """Trim, clamp and drop the blanks. The survivors are what gets sung."""
    trimmed = (line.strip()[:MAX_LINE_CHARS] for line in lines)
    return tuple(line for line in trimmed if line)[:MAX_LINES_PER_SECTION]


def clean_label(label: str, *, index: int) -> str:
    """A section always ends up with a label; position is the fallback for a blank one."""
    cleaned = label.strip()[:MAX_LABEL_CHARS]
    return cleaned or f"{DEFAULT_SECTION_LABEL}-{index + 1}"


def hook_index(sections: tuple[tuple[str, tuple[str, ...], bool], ...], name: str) -> int:
    """Pick exactly one hook: the model's first flag, else the first mention of the name."""
    for index, (_, _, is_hook) in enumerate(sections):
        if is_hook:
            return index
    folded = name.casefold()
    for index, (_, lines, _) in enumerate(sections):
        if any(folded in line.casefold() for line in lines):
            return index
    return 0


def build_sections(
    sections: tuple[tuple[str, tuple[str, ...], bool], ...], *, name: str, hook_index: int
) -> tuple[LyricSection, ...]:
    """Materialise domain sections, guaranteeing the hook actually carries the name."""
    built: list[LyricSection] = []
    for index, (label, lines, _) in enumerate(sections):
        is_hook = index == hook_index
        final_lines = lines
        if is_hook and not any(name.casefold() in line.casefold() for line in lines):
            final_lines = (name, *lines)[:MAX_LINES_PER_SECTION]
        built.append(LyricSection(label=label, lines=final_lines, is_name_hook=is_hook))
    return tuple(built)


def build_lyric_draft(
    sections: tuple[tuple[str, tuple[str, ...], bool], ...],
    *,
    title: str,
    language: Language,
    name_display: str,
) -> LyricDraft:
    """Assemble a draft from already-cleaned ``(label, lines, is_name_hook)`` triples.

    PRECONDITION: ``sections`` is non-empty and every line tuple inside it is non-empty.
    ``LyricDraft.sections`` and ``LyricSection.lines`` both declare ``min_length=1``, so an
    empty harvest raises ``pydantic.ValidationError`` here rather than returning a typed
    ``Err``. That is deliberate rather than an oversight of the Result rule: both callers
    already have to reject an empty harvest with an error phrased in their own vocabulary
    — an ``LlmParseError`` for the writer, a wizard message for a paste — so making this a
    ``Result`` would only add an unwrap that can never fail. Guard before you call.

    The title is stripped before it is clamped: a whitespace-only title must collapse to
    ``DEFAULT_TITLE``, not ship three spaces as the name of the song.
    """
    hook = hook_index(sections, name_display)
    return LyricDraft(
        title=(title.strip()[:MAX_TITLE_CHARS] or DEFAULT_TITLE),
        language=language,
        sections=build_sections(sections, name=name_display, hook_index=hook),
        name_display=name_display,
    )
