"""Turn a ``LyricDraft`` into a ``CompositionPlan``: intro, body, ISOLATED NAME CHUNK.

The load-bearing decision lives here. The recipient's name is given its own short chunk so
a mispronunciation costs one chunk to re-render via inpainting, not the whole track.

Two invariants this module guarantees, and which the tests pin:

* **Exactly one chunk carries the name**, and its text always contains the SUBMITTED
  orthography — never the display form. ``LyricDraft.name_display`` is what a human reads;
  ``name_submitted`` is the candidate orthography we post to the vendor. Every occurrence of
  the display form anywhere in the plan is replaced, because nobody ever sees these strings.
* **Every duration comes from configuration.** ``PlanShape`` is built from ``Settings``;
  there is not a single duration literal below that is not a published vendor bound.

Chunk count is derived from the configured body-chunk target rather than from the number of
lyric sections, so a three-section lyric still fills a two-minute song. Section texts are
cycled to fill the extra slots, which is what a real song does with a chorus anyway.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError as PydanticValidationError

from hbd.contracts import (
    MAX_CHUNK_DURATION_MS,
    MAX_CHUNKS_PER_PLAN,
    MIN_CHUNK_DURATION_MS,
    Chunk,
    CompositionPlan,
    Genre,
    LyricDraft,
    Result,
    err,
    ok,
)
from hbd.errors import ValidationError
from hbd.providers.music.styles import (
    BODY_CHUNK_CONTEXT_ADHERENCE,
    NAME_CHUNK_CONTEXT_ADHERENCE,
    negative_styles_for,
    positive_styles_for,
)

if TYPE_CHECKING:
    from hbd.config import Settings

__all__ = [
    "PlanShape",
    "plan_shape_from_settings",
    "build_composition_plan",
    "plan_with_chunk_text",
    "plan_with_name_text",
    "INTRO_CHUNK_TEXT",
]

#: An instrumental lead-in carries no lyric. Eleven Music reads an empty chunk text as
#: "play, do not sing", which is exactly what an intro is.
INTRO_CHUNK_TEXT: Final[str] = ""

#: One chunk of the plan is always the name chunk, so the body may use at most this many.
MAX_BODY_CHUNKS: Final[int] = MAX_CHUNKS_PER_PLAN - 1


@dataclass(frozen=True, slots=True)
class PlanShape:
    """The three durations that decide a plan's shape. All of them are configuration."""

    song_length_ms: int
    name_chunk_duration_ms: int
    body_chunk_target_ms: int


def plan_shape_from_settings(settings: Settings) -> PlanShape:
    """Read the shape out of ``Settings``. The only place these three are read together."""
    return PlanShape(
        song_length_ms=settings.song_length_ms,
        name_chunk_duration_ms=settings.name_chunk_duration_ms,
        body_chunk_target_ms=settings.song_body_chunk_duration_ms,
    )


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def _substitute_name(text: str, *, display: str, submitted: str) -> str:
    """Return NEW text with the display orthography swapped for the submitted one."""
    if display == submitted:
        return text
    return text.replace(display, submitted)


def _section_texts(lyrics: LyricDraft, *, submitted: str) -> tuple[tuple[str, ...], int]:
    """Non-hook section texts (name-substituted) plus the hook's index in the full list."""
    texts: list[str] = []
    hook_index = 0
    for index, section in enumerate(lyrics.sections):
        if section.is_name_hook:
            hook_index = index
            continue
        joined = "\n".join(section.lines)
        texts.append(_substitute_name(joined, display=lyrics.name_display, submitted=submitted))
    return tuple(texts), hook_index


def _name_chunk_text(lyrics: LyricDraft, *, submitted: str) -> str:
    """The name chunk's text, guaranteed to contain the submitted orthography."""
    for section in lyrics.sections:
        if not section.is_name_hook:
            continue
        candidate = _substitute_name(
            "\n".join(section.lines), display=lyrics.name_display, submitted=submitted
        )
        return candidate if submitted in candidate else submitted
    return submitted


def _group_texts(texts: tuple[str, ...], count: int) -> tuple[str, ...]:
    """Merge contiguous texts into exactly ``count`` groups. Order is preserved."""
    if count <= 0 or count >= len(texts):
        return texts
    size, remainder = divmod(len(texts), count)
    groups: list[str] = []
    start = 0
    for index in range(count):
        take = size + (1 if index < remainder else 0)
        groups.append("\n".join(part for part in texts[start : start + take] if part))
        start += take
    return tuple(groups)


def _body_texts(lyric_texts: tuple[str, ...], count: int) -> tuple[str, ...]:
    """Exactly ``count`` body texts: an instrumental intro, then the lyric, cycled or merged."""
    if count <= 1 or not lyric_texts:
        return (INTRO_CHUNK_TEXT,) * count
    slots = count - 1
    if slots < len(lyric_texts):
        return (INTRO_CHUNK_TEXT, *_group_texts(lyric_texts, slots))
    cycled = tuple(lyric_texts[index % len(lyric_texts)] for index in range(slots))
    return (INTRO_CHUNK_TEXT, *cycled)


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------
def _body_chunk_count(body_budget_ms: int, target_ms: int) -> int:
    """How many body chunks the budget wants, clamped into the vendor's legal range."""
    lowest = max(1, math.ceil(body_budget_ms / MAX_CHUNK_DURATION_MS))
    highest = max(lowest, min(MAX_BODY_CHUNKS, body_budget_ms // MIN_CHUNK_DURATION_MS))
    desired = max(1, round(body_budget_ms / target_ms)) if target_ms > 0 else lowest
    return min(max(desired, lowest), highest)


def _split_duration(budget_ms: int, count: int) -> tuple[int, ...]:
    """Split a budget into ``count`` legal chunk durations, remainder onto the last."""
    if count <= 0:
        return ()
    share = min(max(budget_ms // count, MIN_CHUNK_DURATION_MS), MAX_CHUNK_DURATION_MS)
    durations = [share] * count
    leftover = budget_ms - share * count
    if leftover > 0:
        durations[-1] = min(share + leftover, MAX_CHUNK_DURATION_MS)
    return tuple(durations)


def _name_slot(hook_index: int, section_count: int, body_count: int) -> int:
    """Where the name chunk lands, proportional to where the hook sat in the lyric."""
    ratio = hook_index / max(1, section_count)
    return min(max(1, 1 + round(ratio * (body_count - 1))), body_count)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _body_chunk(text: str, duration_ms: int, *, genre: Genre, is_intro: bool) -> Chunk:
    return Chunk(
        text=text,
        duration_ms=duration_ms,
        positive_styles=positive_styles_for(genre, is_intro=is_intro),
        negative_styles=negative_styles_for(),
        context_adherence=BODY_CHUNK_CONTEXT_ADHERENCE,
    )


def _name_chunk(text: str, duration_ms: int, *, genre: Genre) -> Chunk:
    return Chunk(
        text=text,
        duration_ms=duration_ms,
        positive_styles=positive_styles_for(genre, is_name_chunk=True),
        negative_styles=negative_styles_for(is_name_chunk=True),
        context_adherence=NAME_CHUNK_CONTEXT_ADHERENCE,
        is_name_chunk=True,
    )


def build_composition_plan(
    lyrics: LyricDraft,
    *,
    shape: PlanShape,
    genre: Genre,
    name_submitted: str,
    seed: int | None = None,
) -> Result[CompositionPlan]:
    """Build the plan for one song. Never raises; a bad shape comes back as ``Err``."""
    submitted = name_submitted.strip()
    if not submitted:
        return err(
            ValidationError(
                "name_submitted is blank; the name chunk would carry no name",
                context={"lyric_title": lyrics.title},
            )
        )

    body_budget = max(MIN_CHUNK_DURATION_MS, shape.song_length_ms - shape.name_chunk_duration_ms)
    body_count = _body_chunk_count(body_budget, shape.body_chunk_target_ms)
    durations = _split_duration(body_budget, body_count)
    lyric_texts, hook_index = _section_texts(lyrics, submitted=submitted)
    texts = _body_texts(lyric_texts, body_count)

    body = tuple(
        _body_chunk(text, duration, genre=genre, is_intro=index == 0)
        for index, (text, duration) in enumerate(zip(texts, durations, strict=True))
    )
    slot = _name_slot(hook_index, len(lyrics.sections), body_count)
    name = _name_chunk(
        _name_chunk_text(lyrics, submitted=submitted), shape.name_chunk_duration_ms, genre=genre
    )
    chunks = (*body[:slot], name, *body[slot:])

    try:
        plan = CompositionPlan(chunks=chunks, language=lyrics.language, seed=seed)
    except PydanticValidationError as exc:
        return err(
            ValidationError(
                "assembled composition plan failed contract validation",
                context={
                    "chunk_count": len(chunks),
                    "total_duration_ms": sum(chunk.duration_ms for chunk in chunks),
                    "shape": repr(shape),
                },
                cause=exc,
            )
        )
    return ok(plan)


def plan_with_chunk_text(
    plan: CompositionPlan, index: int, new_text: str
) -> Result[CompositionPlan]:
    """Return a NEW plan with one chunk's text swapped. Never raises, never mutates."""
    if not 0 <= index < len(plan.chunks):
        return err(
            ValidationError(
                f"chunk index {index} is out of range for a {len(plan.chunks)}-chunk plan",
                context={"chunk_index": index, "chunk_count": len(plan.chunks)},
            )
        )
    text = new_text.strip()
    if not text:
        return err(
            ValidationError(
                "refusing to replace a chunk with blank text",
                context={"chunk_index": index},
            )
        )
    replaced = plan.chunks[index].model_copy(update={"text": text})
    try:
        return ok(plan.with_chunk_replaced(index, replaced))
    except (PydanticValidationError, IndexError) as exc:
        return err(
            ValidationError(
                "replacing the chunk produced a plan that fails contract validation",
                context={"chunk_index": index},
                cause=exc,
            )
        )


def plan_with_name_text(plan: CompositionPlan, new_text: str) -> Result[CompositionPlan]:
    """Return a NEW plan whose name chunk carries ``new_text``. The re-roll entry point."""
    index = plan.name_chunk_index
    if index is None:
        return err(
            ValidationError(
                "cannot re-roll the name: this plan has no name chunk",
                context={"chunk_count": len(plan.chunks)},
            )
        )
    return plan_with_chunk_text(plan, index, new_text)
