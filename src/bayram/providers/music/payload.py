"""The ONLY place Eleven Music's field names appear.

``bayram.contracts`` is vendor-neutral on purpose. This module is the seam: a
``CompositionPlan`` goes in, the vendor's documented request body comes out. If Eleven
renames a field, exactly one file changes.

It also holds ``guard_plan``, the last check before bytes leave the process. The contract
models already enforce the vendor's published numeric bounds at construction time, so this
guard covers what they cannot: a name chunk that lost its name, and a plan with nothing to
sing. Cheap, and it turns a 422 round-trip into a local ``Err``.
"""

from __future__ import annotations

from typing import Any, Final

from bayram.contracts import (
    MAX_CHUNKS_PER_PLAN,
    MAX_SONG_DURATION_MS,
    MIN_AUDIO_RANGE_MS,
    MIN_SONG_DURATION_MS,
    AudioRange,
    Chunk,
    CompositionPlan,
    Result,
    SongReference,
    err,
    ok,
)
from bayram.errors import ValidationError

__all__ = [
    "MUSIC_PATH",
    "SUBSCRIPTION_PATH",
    "build_compose_body",
    "build_inpaint_body",
    "guard_plan",
]

#: Composition and inpainting share one endpoint: an inpaint is a plan that references a
#: previously stored song via ``source_song_id``, which is exactly what
#: ``CompositionPlan.source_song_id`` is documented to mean.
MUSIC_PATH: Final[str] = "/v1/music"
SUBSCRIPTION_PATH: Final[str] = "/v1/user/subscription"


def _chunk_body(chunk: Chunk) -> dict[str, Any]:
    """One ``composition_plan.chunks[]`` entry. Optional keys are omitted, never null."""
    body: dict[str, Any] = {
        "text": chunk.text,
        "duration_ms": chunk.duration_ms,
        "positive_styles": list(chunk.positive_styles),
        "negative_styles": list(chunk.negative_styles),
    }
    if chunk.context_adherence is not None:
        # .value, not the member: orjson would serialise a StrEnum fine, but an explicit
        # string keeps the body a plain dict that a test can compare without coercion.
        body["context_adherence"] = chunk.context_adherence.value
    if chunk.conditioning_ref is not None:
        body["conditioning_ref"] = _reference_body(chunk.conditioning_ref)
    if chunk.condition_strength is not None:
        body["condition_strength"] = chunk.condition_strength.value
    return body


def _reference_body(reference: SongReference) -> dict[str, Any]:
    """A stored-song slice: ``{"song_id": ..., "range": {"start_ms", "end_ms"}}``."""
    return {
        "song_id": reference.song_id,
        "range": {
            "start_ms": reference.range.start_ms,
            "end_ms": reference.range.end_ms,
        },
    }


def _chunk_offsets(plan: CompositionPlan) -> list[int]:
    """Start offset of each chunk, plus the plan's total as a final entry."""
    offsets = [0]
    for chunk in plan.chunks:
        offsets.append(offsets[-1] + chunk.duration_ms)
    return offsets


def build_compose_body(plan: CompositionPlan, *, model_id: str) -> dict[str, Any]:
    """Render the POST body for a full-track compose. Pure; never mutates ``plan``.

    ``output_format`` is deliberately absent: the vendor reads it as a QUERY parameter and
    ignores a body field of that name, so putting it here silently left the account default
    (``mp3_48000_192`` on music_v2) in force. The transport adds it to the URL — the same
    way the TTS adapter in this repo already does.
    """
    # No ``music_length_ms``: the vendor rejects it outright when a ``composition_plan`` is
    # present, because the chunk durations already state the length. Sending both is a 422.
    body: dict[str, Any] = {
        "composition_plan": {"chunks": [_chunk_body(chunk) for chunk in plan.chunks]},
        "model_id": model_id,
        "force_instrumental": plan.is_instrumental,
        "store_for_inpainting": plan.should_store_for_inpainting,
    }
    if plan.seed is not None:
        body["seed"] = plan.seed
    if plan.source_song_id is not None:
        body["source_song_id"] = plan.source_song_id
    return body


def build_inpaint_body(
    plan: CompositionPlan,
    *,
    source_song_id: str,
    chunk_index: int,
    model_id: str,
) -> dict[str, Any]:
    """Render the POST body that re-renders ONE chunk of an already-stored song.

    Inpainting is expressed entirely inside the plan: the sections we are keeping become
    **audio-reference chunks** naming a slice of the stored song, and only the target chunk
    is a generation chunk. There is no top-level ``source_song_id`` or ``chunk_index`` —
    sending those is what made an earlier build silently regenerate the whole track, because
    ``POST /v1/music`` ignores fields it does not honour rather than rejecting them.

    A reference is omitted when it would be empty (the target is the first or last chunk),
    since a zero-length range is below the vendor's ``MIN_AUDIO_RANGE_MS`` floor.

    The stored song stays stored: a re-roll may need a second attempt with the next
    candidate orthography, and losing the handle would cost a whole track.
    """
    offsets = _chunk_offsets(plan)
    target_start, target_end = offsets[chunk_index], offsets[chunk_index + 1]
    total = offsets[-1]

    chunks: list[dict[str, Any]] = []
    if target_start >= MIN_AUDIO_RANGE_MS:
        chunks.append(
            _reference_body(
                SongReference(
                    song_id=source_song_id,
                    range=AudioRange(start_ms=0, end_ms=target_start),
                )
            )
        )
    chunks.append(_chunk_body(plan.chunks[chunk_index]))
    if total - target_end >= MIN_AUDIO_RANGE_MS:
        chunks.append(
            _reference_body(
                SongReference(
                    song_id=source_song_id,
                    range=AudioRange(start_ms=target_end, end_ms=total),
                )
            )
        )

    body: dict[str, Any] = {
        "composition_plan": {"chunks": chunks},
        "model_id": model_id,
        "force_instrumental": plan.is_instrumental,
        "store_for_inpainting": True,
    }
    if plan.seed is not None:
        body["seed"] = plan.seed
    return body


def _blank_name_chunk(plan: CompositionPlan) -> bool:
    index = plan.name_chunk_index
    return index is not None and not plan.chunks[index].text.strip()


def guard_plan(plan: CompositionPlan) -> Result[CompositionPlan]:
    """Final local check before the request leaves. Never raises."""
    total = plan.total_duration_ms
    if not MIN_SONG_DURATION_MS <= total <= MAX_SONG_DURATION_MS:
        return err(
            ValidationError(
                f"plan duration {total}ms is outside the vendor's accepted range",
                context={"total_duration_ms": total, "chunk_count": len(plan.chunks)},
            )
        )
    if len(plan.chunks) > MAX_CHUNKS_PER_PLAN:
        return err(
            ValidationError(
                f"plan has {len(plan.chunks)} chunks, vendor accepts {MAX_CHUNKS_PER_PLAN}",
                context={"chunk_count": len(plan.chunks)},
            )
        )
    if _blank_name_chunk(plan):
        return err(
            ValidationError(
                "the name chunk is blank; this plan would render a song with no name in it",
                context={"name_chunk_index": plan.name_chunk_index},
            )
        )
    if not plan.is_instrumental and not any(chunk.text.strip() for chunk in plan.chunks):
        return err(
            ValidationError(
                "a vocal plan has no lyric text in any chunk",
                context={"chunk_count": len(plan.chunks)},
            )
        )
    return ok(plan)
