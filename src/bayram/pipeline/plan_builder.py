"""Lyric draft -> composition plan, with the name isolated in its own chunk.

This is where the display/submitted split becomes physical. The lyric sheet the customer
reads carries ``RecipientName.display`` — perfect U+02BB. The chunk posted to the music
vendor carries ``NameCandidate.text``, which may be stripped, hyphenated or respelled into
something that looks wrong and *sounds* right. The substitution happens here and nowhere
else.

The hook section becomes a short chunk of its own so a bad take costs one inpaint instead
of a whole track, and the body is packed to fit the configured song length without ever
crossing a vendor bound.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final
from uuid import UUID

from bayram.config import Settings
from bayram.contracts import (
    MAX_CHUNK_DURATION_MS,
    MAX_CHUNKS_PER_PLAN,
    MIN_CHUNK_DURATION_MS,
    Brief,
    Chunk,
    CompositionPlan,
    Genre,
    LyricDraft,
    LyricSection,
    NameCandidate,
    Result,
    VoiceGender,
    err,
    ok,
)
from bayram.errors import ValidationError
from bayram.logging import get_logger
from bayram.providers.music.styles import (
    BODY_CHUNK_CONTEXT_ADHERENCE,
    NAME_CHUNK_CONTEXT_ADHERENCE,
)

__all__ = [
    "build_composition_plan",
    "with_name_candidate",
    "substitute_name",
    "GENRE_STYLES",
    "NEGATIVE_STYLES",
]

_LOGGER = get_logger(__name__)

GENRE_STYLES: Final[dict[Genre, tuple[str, ...]]] = {
    Genre.POP: ("pop", "bright", "catchy chorus"),
    Genre.RETRO_ESTRADA: ("retro estrada", "1980s", "warm analog synths"),
    Genre.HIP_HOP: ("hip hop", "boom bap", "clear rhythmic vocal"),
    Genre.ROCK: ("rock", "electric guitar", "anthemic"),
    Genre.ACOUSTIC_BALLAD: ("acoustic ballad", "fingerpicked guitar", "intimate"),
    Genre.DANCE_ELECTRONIC: ("dance", "four on the floor", "electronic"),
    Genre.UZBEK_POP: ("uzbek pop", "estrada", "doira percussion"),
    Genre.UZBEK_FOLK: ("uzbek folk", "dutar", "traditional"),
    Genre.SHASHMAQOM: ("shashmaqom", "maqom ornamentation", "ceremonial"),
    Genre.JAZZ_LOUNGE: ("lounge jazz", "brushed drums", "upright bass"),
}

_VOCAL_STYLES: Final[dict[VoiceGender, tuple[str, ...]]] = {
    VoiceGender.FEMALE: ("female lead vocal",),
    VoiceGender.MALE: ("male lead vocal",),
    VoiceGender.DUET: ("male and female duet",),
    VoiceGender.ANY: (),
}

#: Applied to every chunk. Keeps the vendor away from the failure modes we have seen.
NEGATIVE_STYLES: Final[tuple[str, ...]] = (
    "lo-fi",
    "muffled vocals",
    "spoken word",
    "instrumental only",
)

#: The name chunk is the product. Hold the vendor as close to the text as it allows.
#: These live in ``providers.music.styles`` — the vendor owns the scale, and a second copy
#: here is how the two drifted (0.75 against 0.7) before the enum landed.
#: Extra styles pushed onto the name chunk so it lands clean and forward in the mix.
NAME_CHUNK_STYLES: Final[tuple[str, ...]] = ("clear diction", "vocal forward", "sustained")

#: Seeds are derived from the order id so a retried compose is bit-identical, not a
#: second, differently-random song billed to the same customer.
_SEED_MODULUS: Final[int] = 2**31


def derive_seed(order_id: UUID) -> int:
    digest = hashlib.sha256(str(order_id).encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % _SEED_MODULUS


def substitute_name(text: str, *, display: str, submitted: str) -> str:
    """Swap the display orthography for the submitted one, case-insensitively.

    If the display form is absent (a hook the model wrote without the name, already
    repaired upstream, or a re-roll on text that no longer holds it), the text comes back
    untouched — the caller decides what that means.
    """
    if not display or display == submitted:
        return text
    return re.sub(re.escape(display), submitted, text, flags=re.IGNORECASE)


def _section_text(section: LyricSection) -> str:
    return "\n".join(section.lines)


def _styles_for(brief: Brief) -> tuple[str, ...]:
    return (*GENRE_STYLES[brief.genre], *_VOCAL_STYLES[brief.vocal_gender])


def _body_durations(*, budget_ms: int, count: int) -> tuple[int, ...]:
    """Split ``budget_ms`` across ``count`` chunks, each inside the vendor's bounds."""
    if count <= 0:
        return ()
    share = max(MIN_CHUNK_DURATION_MS, min(MAX_CHUNK_DURATION_MS, budget_ms // count))
    durations = [share] * count
    leftover = budget_ms - share * count
    if leftover > 0:
        durations[0] = min(MAX_CHUNK_DURATION_MS, durations[0] + leftover)
    return tuple(durations)


def _max_body_chunks(*, budget_ms: int, available: int, has_name_chunk: bool) -> int:
    """How many body chunks fit. One slot is held back for the name chunk when there is one.

    ``MAX_CHUNKS_PER_PLAN - 1`` was unconditional, which quietly cost a nameless song one
    section it had the budget and the plan room to sing.
    """
    affordable = budget_ms // MIN_CHUNK_DURATION_MS
    ceiling = MAX_CHUNKS_PER_PLAN - 1 if has_name_chunk else MAX_CHUNKS_PER_PLAN
    return max(0, min(available, ceiling, affordable))


def _durations_by_index(
    lyrics: LyricDraft, *, hook_index: int | None, settings: Settings
) -> dict[int, int]:
    """How long each body section gets, dropping the ones the song has no room for.

    ``hook_index`` is ``None`` for a nameless lyric. Then every section is body, and the
    whole song budget is theirs — nothing is reserved for a name chunk that does not exist.
    Reserving it anyway would hand the customer a song shorter than the one they paid for,
    with the missing seconds spent on nothing.
    """
    body_indices = tuple(index for index in range(len(lyrics.sections)) if index != hook_index)
    reserved_ms = settings.name_chunk_duration_ms if hook_index is not None else 0
    budget_ms = max(0, settings.song_length_ms - reserved_ms)
    count = _max_body_chunks(
        budget_ms=budget_ms, available=len(body_indices), has_name_chunk=hook_index is not None
    )
    durations = _body_durations(budget_ms=budget_ms, count=count)
    return dict(zip(body_indices[:count], durations, strict=True))


def _name_chunk_ms(*, settings: Settings, has_body: bool) -> int:
    """How long the name chunk runs, given whether anything else is being sung.

    Normally the name gets a short chunk of its own so a bad take costs one inpaint instead
    of the whole track. But a lyric can consist of the hook alone — a customer who pastes
    four lines with no blank line between them gets exactly one section, and so does a
    sparse model payload — and then there is no body to carry the rest of the song. Left
    alone the plan would total ``name_chunk_duration_ms``: a valid plan, above
    ``MIN_SONG_DURATION_MS``, silently delivering eight seconds of a two-minute song that
    the customer already paid for. Nothing downstream would notice, because nothing is
    wrong except the length.

    So when the body is empty the sole chunk takes the whole song budget, clamped to the
    vendor's per-chunk ceiling.
    """
    if has_body:
        return settings.name_chunk_duration_ms
    return min(MAX_CHUNK_DURATION_MS, settings.song_length_ms)


def _assemble_chunks(
    lyrics: LyricDraft,
    *,
    brief: Brief,
    candidate: NameCandidate | None,
    hook_index: int | None,
    name_ms: int,
    duration_by_index: dict[int, int],
) -> tuple[Chunk, ...]:
    styles = _styles_for(brief)
    chunks: list[Chunk] = []
    for index, section in enumerate(lyrics.sections):
        if hook_index is not None and index == hook_index:
            # Guarded by ``build_composition_plan``: a hook index exists only when the lyric
            # has a name and a candidate to sing it under, so neither narrowing can fail.
            assert candidate is not None and lyrics.name_display is not None
            chunks.append(
                _name_chunk(
                    section,
                    display=lyrics.name_display,
                    submitted=candidate.text,
                    duration_ms=name_ms,
                    styles=styles,
                )
            )
            continue
        duration_ms = duration_by_index.get(index)
        if duration_ms is None:
            continue
        chunks.append(
            Chunk(
                text=_section_text(section),
                duration_ms=duration_ms,
                positive_styles=styles,
                negative_styles=NEGATIVE_STYLES,
                context_adherence=BODY_CHUNK_CONTEXT_ADHERENCE,
            )
        )
    return tuple(chunks)


def build_composition_plan(
    lyrics: LyricDraft,
    *,
    brief: Brief,
    candidate: NameCandidate | None,
    settings: Settings,
    seed: int | None = None,
) -> Result[CompositionPlan]:
    """Build the plan for one song. Exactly one chunk carries the name — if there is one.

    A NAMELESS lyric — the bring-your-own path, where the wizard never asks who the song is
    for — produces a plan of body chunks only. There is no name to isolate, so isolating one
    would reserve seconds and a chunk slot for nothing, and ``should_store_for_inpainting``
    goes off with it: storing the render costs the vendor's retention and buys a re-roll
    that can never be asked for.

    The missing-hook ERROR is kept for the case it was written about. A lyric that HAS a
    name but no hook is a broken lyric — ``lyric_shape`` guarantees the pairing, so reaching
    here means that guarantee has been violated upstream, and composing anyway would sing
    the name with no chunk boundary around it and no way to re-render it. The two states are
    told apart by the name, which is why this reads ``name_display`` rather than the hooks.
    """
    hooks = lyrics.name_hook_sections
    is_named = lyrics.name_display is not None and candidate is not None
    if is_named and not hooks:
        return err(
            ValidationError(
                "lyric draft has no name-hook section, so the name cannot be isolated",
                context={"title": lyrics.title, "sections": len(lyrics.sections)},
            )
        )

    hook_index = (
        next(index for index, section in enumerate(lyrics.sections) if section is hooks[0])
        if is_named and hooks
        else None
    )
    duration_by_index = _durations_by_index(lyrics, hook_index=hook_index, settings=settings)
    chunks = _assemble_chunks(
        lyrics,
        brief=brief,
        candidate=candidate,
        hook_index=hook_index,
        name_ms=_name_chunk_ms(settings=settings, has_body=bool(duration_by_index)),
        duration_by_index=duration_by_index,
    )
    return _plan_or_error(
        chunks,
        brief=brief,
        seed=seed,
        should_store=settings.is_name_verification_enabled and hook_index is not None,
    )


def _name_chunk(
    hook: LyricSection,
    *,
    display: str,
    submitted: str,
    duration_ms: int,
    styles: tuple[str, ...],
) -> Chunk:
    text = substitute_name(_section_text(hook), display=display, submitted=submitted)
    return Chunk(
        text=text,
        duration_ms=duration_ms,
        positive_styles=(*styles, *NAME_CHUNK_STYLES),
        negative_styles=NEGATIVE_STYLES,
        context_adherence=NAME_CHUNK_CONTEXT_ADHERENCE,
        is_name_chunk=True,
    )


def _plan_or_error(
    chunks: tuple[Chunk, ...],
    *,
    brief: Brief,
    seed: int | None,
    should_store: bool,
) -> Result[CompositionPlan]:
    try:
        plan = CompositionPlan(
            chunks=chunks,
            language=brief.output_language,
            seed=seed,
            should_store_for_inpainting=should_store,
        )
    except ValueError as exc:
        return err(
            ValidationError(
                "assembled composition plan violated a vendor bound",
                context={
                    "chunk_count": len(chunks),
                    "total_duration_ms": sum(chunk.duration_ms for chunk in chunks),
                },
                cause=exc,
            )
        )
    _LOGGER.info(
        "composition plan built",
        extra={
            "chunks": len(plan.chunks),
            "total_duration_ms": plan.total_duration_ms,
            "name_chunk_index": plan.name_chunk_index,
        },
    )
    return ok(plan)


def with_name_candidate(
    plan: CompositionPlan,
    *,
    previous: NameCandidate,
    candidate: NameCandidate,
) -> Result[CompositionPlan]:
    """Return a NEW plan whose name chunk uses ``candidate`` instead of ``previous``."""
    index = plan.name_chunk_index
    if index is None:
        return err(
            ValidationError(
                "cannot re-roll the name on a plan that has no name chunk",
                context={"chunk_count": len(plan.chunks)},
            )
        )

    original = plan.chunks[index]
    swapped = substitute_name(original.text, display=previous.text, submitted=candidate.text)
    text = swapped
    if candidate.text not in swapped:
        # The previous spelling is not in the chunk, so there was nothing to swap. Singing
        # the bare name still sells the product; singing the PREVIOUS orthography again
        # does not. So the hook is sacrificed — loudly, because it means an upstream
        # invariant (the hook carries the name) has been broken and wants fixing there.
        _LOGGER.warning(
            "name re-roll found no previous spelling to replace; falling back to the bare "
            "name and losing this chunk's lyric",
            extra={
                "chunk_index": index,
                "previous_strategy": previous.strategy.value,
                "strategy": candidate.strategy.value,
                "chunk_chars": len(original.text),
            },
        )
        text = candidate.text
    try:
        return ok(plan.with_chunk_replaced(index, original.model_copy(update={"text": text})))
    except (ValueError, IndexError) as exc:
        return err(
            ValidationError(
                "re-rolled composition plan violated a vendor bound",
                context={"chunk_index": index, "strategy": candidate.strategy.value},
                cause=exc,
            )
        )
