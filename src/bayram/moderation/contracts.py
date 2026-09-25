"""The media moderation contract (IMAGE_VIDEO_SPEC §6.2, §6.3).

Three rules carry the design, and each is a line of §6:

* **no default decision.** :class:`MediaVerdict` has no field with a default and forbids
  extra keys, so a guard reply that omits the decision, or carries one we do not know, is a
  parse error — and a parse error is ``unavailable``, never ``allow`` (§6.3; the song
  moderator's ``is_allowed: bool = True`` is the failure this is shaped against, §0.3);
* **closed category codes.** Only :class:`CategoryCode` members are ever stored
  (``media_jobs.screen_categories``), never guard prose — an unknown code fails validation;
* **an ``Err`` is ``unavailable``.** Every method returns a ``Result`` and never raises; the
  stage that called it turns an ``Err`` into ``unavailable``, which is ``media.busy`` before
  payment and a two-minute retry after it (§6.4). Fail closed (O10).

The decision is computed in OUR code from the guard's output (M3.1, ``moderation/policy.py``);
a :class:`MediaModerator` implementation hands back the verdict it computed, so the stage
chain reads one shape whatever sits behind it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from bayram.contracts import Language, Result
from bayram.db.enums import MediaScreenDecision

__all__ = [
    "CategoryCode",
    "VerdictSubject",
    "MEDIA_POLICY_VERSION",
    "MediaVerdict",
    "TextItem",
    "ImageItem",
    "VoiceTranscript",
    "MediaModerator",
    "DECISION_PRECEDENCE",
    "strictest",
    "unavailable_verdict",
    "lang_hint_for",
]

#: The policy the stored decisions were made under (§6.3). ``media_start`` refuses a job whose
#: ``screen_policy_version`` is not this one (§2.3.1), so bumping it re-screens every unpaid
#: quote rather than letting an old verdict start a render. It versions everything in
#: ``moderation/policy.py`` (label mapping, thresholds, the hard rule) and
#: ``moderation/lexicon.py`` (the denylist and youth lexicon): change either, bump this.
#: Defined here rather than in ``policy`` because every verdict carries it.
MEDIA_POLICY_VERSION: Final[str] = "m3.r-2026-09-25"


class CategoryCode(StrEnum):
    """The closed category taxonomy (§6.3). Nothing outside it is ever stored."""

    SEXUAL = "sexual"
    SEXUAL_MINORS = "sexual_minors"
    VIOLENCE = "violence"
    SELF_HARM = "self_harm"
    HATE = "hate"
    EXTREMISM = "extremism"
    POLITICS_OFFICIALS = "politics_officials"
    RELIGION = "religion"
    ILLEGAL_DRUGS = "illegal_drugs"
    WEAPONS = "weapons"
    JAILBREAK = "jailbreak"
    PII = "pii"
    COPYRIGHT_CHARACTER = "copyright_character"
    OTHER_UNSAFE = "other_unsafe"


type VerdictSubject = Literal[
    "prompt",
    "narration",
    "transcript",
    "script",
    "upload",
    "collage",
    "upload_text",
    "output_image",
    "output_frame",
    "output_text",
]


class MediaVerdict(BaseModel):
    """One screening answer (§6.3). Frozen, strict, no defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: MediaScreenDecision
    categories: tuple[CategoryCode, ...]
    scores: Mapping[CategoryCode, float]
    subject: VerdictSubject
    model_id: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class TextItem:
    """One piece of text to screen. ``id`` is ours (an ordinal), never the content."""

    id: str
    subject: VerdictSubject
    content: str


@dataclass(frozen=True, slots=True)
class ImageItem:
    """One image to screen, already on disk — the screened copy itself (§3.3)."""

    id: str
    subject: VerdictSubject
    path: Path


@dataclass(frozen=True, slots=True)
class VoiceTranscript:
    """What whisper heard in an own voice note (§5.4). M4 reads the quality numbers.

    Each number is the WORST segment's, since §5.4's hallucination checks refuse a note when
    any one segment fails them — except ``avg_logprob``, the mean over segments."""

    text: str
    language: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    #: The highest ``compression_ratio`` of any segment (§5.4: above 2.4 → refused).
    max_compression_ratio: float | None = None


@runtime_checkable
class MediaModerator(Protocol):
    """A guard stack (IMAGE_VIDEO_SPEC §6.2). Nothing here raises across the boundary."""

    name: str

    async def screen_text(
        self, items: Sequence[TextItem], *, policy: str, lang_hint: str | None = None
    ) -> Result[MediaVerdict]: ...

    async def screen_images(
        self, items: Sequence[ImageItem], *, policy: str, lang_hint: str | None = None
    ) -> Result[MediaVerdict]: ...

    async def transcribe(self, audio: Path, *, language_hint: str) -> Result[VoiceTranscript]: ...


#: Strictest first. ``block`` and ``review`` both refuse before payment (§6.4), and either
#: outranks ``unavailable``: a definite refusal is an answer, and "one guard was down" must not
#: turn a request another guard refused into a ``busy`` the customer can simply retry.
DECISION_PRECEDENCE: Final[tuple[MediaScreenDecision, ...]] = (
    MediaScreenDecision.BLOCK,
    MediaScreenDecision.REVIEW,
    MediaScreenDecision.UNAVAILABLE,
    MediaScreenDecision.ALLOW,
)


def strictest(
    decisions: Iterable[MediaScreenDecision],
) -> MediaScreenDecision:
    """The strictest of several decisions. **Nothing to judge is ``allow``** — callers only
    pass the verdicts of subjects that exist, and a request with no photos has no image
    verdict to weigh."""
    present = set(decisions)
    for decision in DECISION_PRECEDENCE:
        if decision in present:
            return decision
    return MediaScreenDecision.ALLOW


def unavailable_verdict(subject: VerdictSubject, *, model_id: str, policy: str) -> MediaVerdict:
    """The fail-closed answer: nothing was judged."""
    return MediaVerdict(
        decision=MediaScreenDecision.UNAVAILABLE,
        categories=(),
        scores={},
        subject=subject,
        model_id=model_id,
        policy_version=policy,
    )


def lang_hint_for(language: Language) -> str:
    """G1's ``lang_hint`` (§6.5) for a job's language: the ISO 639-1 code, so both Uzbek
    scripts are ``uz`` — the guard is told the language, and reads the script itself."""
    match language:
        case Language.UZ_LATN | Language.UZ_CYRL:
            return "uz"
        case Language.RU:
            return "ru"
        case Language.EN:
            return "en"
