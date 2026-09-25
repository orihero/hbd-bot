"""How much a video's voice may say, and how long a voice note may run (IMAGE_VIDEO_SPEC §5.3).

The clip is ``narration_max_seconds`` long (5 s now), and O14 caps the audio at the clip: a
line we accept before payment must be one a voice can actually speak in it. So a line is
measured the same way everywhere it is checked — the bot at ``voice_text``, the worker's
``media_screen`` as a backstop, and the script writer (§5.5) on what it produced:

* normalised first through the D10 layer (``names.marks.normalize_input``: NFC, invisibles,
  whitespace, the Uzbek apostrophes), so a pasted line and a typed one count alike;
* counted in whitespace tokens and characters against the **per-language** budget
  (§2.4.2): uz ≤ 8 words / 60 chars, ru ≤ 10 / 70, en ≤ 12 / 80 by default, all under the
  owner's 12-word ceiling. Uzbek is one budget for both scripts.

An own voice note is measured by ffprobe, not by Telegram's whole-second ``duration``
(IMAGE_VIDEO_SPEC §5.4): anything above the clip length plus :data:`VOICE_NOTE_TOLERANCE_S`
is refused before payment; a note inside the tolerance is trimmed with a fade at render time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from bayram.config import Settings
from bayram.contracts import Language
from bayram.names.marks import normalize_input

__all__ = [
    "VOICE_NOTE_TOLERANCE_S",
    "NarrationBudget",
    "budget_language",
    "narration_budget",
    "normalise_narration",
    "narration_words",
    "fits_budget",
    "is_voice_note_too_long",
]

#: §5.4: a note up to a quarter-second over the clip is trimmed with a fade, not refused.
VOICE_NOTE_TOLERANCE_S: Final[float] = 0.25

type BudgetLanguage = Literal["uz", "ru", "en"]


@dataclass(frozen=True, slots=True)
class NarrationBudget:
    """The most a line may be in one language, and the clip it has to fit (§2.4.2)."""

    words: int
    chars: int
    seconds: int


def budget_language(language: Language) -> BudgetLanguage:
    """The budget a UI language is measured by. Both Uzbek scripts share one."""
    match language:
        case Language.UZ_LATN | Language.UZ_CYRL:
            return "uz"
        case Language.RU:
            return "ru"
        case Language.EN:
            return "en"


def narration_budget(settings: Settings, language: Language) -> NarrationBudget:
    code = budget_language(language)
    return NarrationBudget(
        words=int(getattr(settings, f"narration_max_words_{code}")),
        chars=int(getattr(settings, f"narration_max_chars_{code}")),
        seconds=settings.narration_max_seconds,
    )


def normalise_narration(text: str) -> str:
    """The line as it will be spoken and stored: the D10 normalisation, trimmed."""
    return normalize_input(text)


def narration_words(text: str) -> int:
    return len(normalise_narration(text).split())


def fits_budget(text: str, budget: NarrationBudget) -> bool:
    """True for a non-empty line within both the word and the character budget."""
    line = normalise_narration(text)
    return bool(line) and len(line.split()) <= budget.words and len(line) <= budget.chars


def is_voice_note_too_long(duration_s: float, settings: Settings) -> bool:
    """§5.4: refused before payment above the clip length plus the tolerance."""
    return duration_s > settings.narration_max_seconds + VOICE_NOTE_TOLERANCE_S
