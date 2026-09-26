"""Choosing which characters speak the three greetings.

The product promise is three *different* characters, so the selection round-robins across
gender groups rather than taking the first three voices the provider happens to list —
otherwise a provider whose catalogue is sorted by gender hands us three identical-sounding
grandfathers.

Degrading is allowed and never fatal: if only two voices exist for the output language, the
customer gets two greetings and the run records a gap. Losing a finished song because the
catalogue is thin would be the worse outcome by far.
"""

from __future__ import annotations

from bayram.contracts import Language, Result, VoiceDescriptor, VoiceGender, err, ok
from bayram.errors import PipelineError

__all__ = ["select_voices", "NO_VOICE_USER_MESSAGE_KEY"]

NO_VOICE_USER_MESSAGE_KEY = "error.service_unavailable"

#: Order the gender buckets are drained in when the caller expressed no preference.
_DEFAULT_GENDER_ORDER = (VoiceGender.FEMALE, VoiceGender.MALE, VoiceGender.ANY, VoiceGender.DUET)


def _gender_order(preferred: VoiceGender) -> tuple[VoiceGender, ...]:
    if preferred is VoiceGender.ANY:
        return _DEFAULT_GENDER_ORDER
    rest = tuple(gender for gender in _DEFAULT_GENDER_ORDER if gender is not preferred)
    return (preferred, *rest)


def _bucket(
    voices: tuple[VoiceDescriptor, ...], gender: VoiceGender
) -> tuple[VoiceDescriptor, ...]:
    return tuple(voice for voice in voices if voice.gender is gender)


def _round_robin(
    buckets: tuple[tuple[VoiceDescriptor, ...], ...], *, count: int
) -> tuple[VoiceDescriptor, ...]:
    """Take one voice from each bucket in turn until ``count`` is reached."""
    picked: list[VoiceDescriptor] = []
    depth = 0
    deepest = max((len(bucket) for bucket in buckets), default=0)
    while len(picked) < count and depth < deepest:
        for bucket in buckets:
            if depth < len(bucket) and len(picked) < count:
                picked.append(bucket[depth])
        depth += 1
    return tuple(picked)


def select_voices(
    voices: tuple[VoiceDescriptor, ...],
    *,
    language: Language,
    preferred_gender: VoiceGender,
    count: int,
) -> Result[tuple[VoiceDescriptor, ...]]:
    """Pick up to ``count`` distinct personas for ``language``, most varied first."""
    in_language = tuple(voice for voice in voices if voice.language is language)
    if not in_language:
        return err(
            PipelineError(
                "the TTS provider offers no voice for the requested output language",
                user_message_key=NO_VOICE_USER_MESSAGE_KEY,
                context={"language": language.value, "catalogue_size": len(voices)},
            )
        )

    # The gender order covers every enum member, so the buckets partition `in_language`
    # and a non-empty catalogue always yields at least one pick.
    buckets = tuple(_bucket(in_language, gender) for gender in _gender_order(preferred_gender))
    return ok(_round_robin(buckets, count=count))
