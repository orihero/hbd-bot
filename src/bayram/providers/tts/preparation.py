"""The step every speech adapter performs before it opens a socket.

Resolving a persona, refusing a language the vendor does not serve, and swapping the
display name for the submitted orthography are the same three decisions for every speech
vendor. Written once per adapter they would drift, and the one that drifted would quietly
stop substituting the name — the single failure this product cannot afford — so they are
written once, here, and every adapter calls it first.

What stays vendor-specific is what *happens* to the mood; this module only resolves which
mood applies.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from bayram.contracts import Language, Result, SpeechRequest, err, ok
from bayram.errors import ValidationError
from bayram.logging import get_logger
from bayram.providers.tts.markup import apply_name, strip_markup
from bayram.providers.tts.registry import VoiceEntry, VoiceRegistry

__all__ = ["PreparedSpeech", "prepare_speech"]

_LOG = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedSpeech:
    """A request resolved against the catalogue, ready to become a vendor payload."""

    entry: VoiceEntry
    #: ``request.text`` with the submitted orthography substituted for the display name.
    text: str
    #: The same text with markup removed — what a listener actually hears. Estimates only.
    spoken_text: str
    is_name_applied: bool
    mood: str | None


def prepare_speech(
    request: SpeechRequest,
    *,
    registry: VoiceRegistry,
    provider: str,
    supported_languages: Iterable[Language],
) -> Result[PreparedSpeech]:
    """Resolve persona and name for one request. Never raises, never calls a vendor."""
    supported = frozenset(supported_languages)
    if request.language not in supported:
        return err(
            ValidationError(
                f"{provider} does not serve {request.language.value}",
                context={
                    "provider": provider,
                    "language": request.language.value,
                    "supported": sorted(language.value for language in supported),
                },
            )
        )

    entry = registry.get(request.persona_id, language=request.language)
    if entry is None:
        return err(
            ValidationError(
                f"unknown persona '{request.persona_id}' for {request.language.value}",
                context={
                    "provider": provider,
                    "persona_id": request.persona_id,
                    "language": request.language.value,
                    "known": [
                        known.persona_id for known in registry.for_language(request.language)
                    ],
                },
            )
        )

    application = apply_name(
        request.text,
        name_submitted=request.name_submitted,
        name_ipa=request.name_ipa,
        is_phoneme_supported=entry.supports_phoneme_override,
    )
    if not application.is_applied:
        # Not fatal: a greeting that says the name imperfectly still beats no greeting.
        # It is, however, exactly the defect this product exists to prevent, so it is
        # logged at WARNING with everything a responder needs to reproduce it.
        _LOG.warning(
            "the submitted name orthography could not be located in the script",
            extra={
                "provider": provider,
                "persona_id": entry.persona_id,
                "language": request.language.value,
                "name_submitted": request.name_submitted,
                "script_excerpt": request.text[:120],
            },
        )

    return ok(
        PreparedSpeech(
            entry=entry,
            text=application.text,
            spoken_text=strip_markup(application.text),
            is_name_applied=application.is_applied,
            mood=request.mood or entry.default_mood,
        )
    )
