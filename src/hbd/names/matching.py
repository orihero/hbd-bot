# Latin ones are the SUBJECT of this module, not a typo in it.
"""Did the model actually say the name? Comparing an intended name to an STT transcript.

This is step 4 of the name subsystem: the rendered name chunk goes through Scribe, the
transcript comes back, and this module decides whether it is the same name — before the
customer hears anything.

A transcript never comes back byte-identical, and demanding that it does would reject every
correct rendering. So both sides are reduced to a **sound key** first:

1. canonicalise the marks, then fold the Cyrillic letters that carry no pronunciation
   difference for us (``ё`` -> ``е``, ``й`` -> ``и``, ``ў`` -> ``у``, ``ҳ`` -> ``х``);
2. romanise, so a Cyrillic transcript of a Latin name still compares;
3. casefold and throw away everything that is not a letter — the apostrophe class, the
   syllable hyphens we introduced, spaces, punctuation;
4. collapse the confusions this specific pipeline creates or hits in the wild:
   ``gh``/``gʻ`` -> ``g``, ``kh``/``x`` -> ``h``, ``q`` -> ``k``, ``zh``/``j`` -> ``j``,
   ``ee`` -> ``i``, ``oo`` -> ``u``, ``y`` -> ``i``, ``w`` -> ``v``, then squeeze doubles.

Every fold pair earns its place by making two of OUR OWN candidate spellings of one name
agree — ``yoo`` -> ``iu`` exists because the phonetic respelling of ``Yulduz`` is
``Yooldooz``, and ``ў`` folds to ``о`` because Uzbek ``ў`` romanises as ``oʻ``.

Note what step 1 does NOT do: it never changes the display spelling. ``Алёна`` keeps its
``ё`` everywhere a human can see it; the fold exists only so a transcript reading ``Алена``
is not treated as a mispronunciation.

The public answer is a **score**, not a verdict. The threshold lives in configuration
(``HBD_NAME_MATCH_MIN_SIMILARITY``) and is applied by the caller that owns the retry budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from hbd.contracts import Language, NameCandidate, NameVerdict, Transcript
from hbd.names.marks import normalize_input, strip_marks
from hbd.names.translit import cyrillic_to_latin

__all__ = [
    "NameMatch",
    "sound_key",
    "sound_keys",
    "name_similarity",
    "compare_names",
    "judge_transcript",
]

#: Cyrillic letters folded together before romanisation. These pairs are indistinguishable
#: in a sung or spoken rendering, or are routinely typed for one another.
_CYRILLIC_PREFOLD: Final[dict[str, str]] = {
    "ё": "е",
    "й": "и",
    "ў": "о",
    "ғ": "г",
    "қ": "к",
    "ҳ": "х",
    "ы": "и",
    "э": "е",
    "ъ": "",
    "ь": "",
}

#: Latin sequences folded together after romanisation. Longest key wins.
_LATIN_FOLD: Final[dict[str, str]] = {
    "shch": "sh",
    "sch": "sh",
    "sh": "sh",
    "ch": "ch",
    "kh": "h",
    "gh": "g",
    "zh": "j",
    "ph": "f",
    "th": "t",
    "ck": "k",
    "ee": "i",
    "oo": "u",
    "yoo": "iu",
    "yo": "io",
    "yu": "iu",
    "ya": "ia",
    "c": "k",
    "q": "k",
    "x": "h",
    "w": "v",
    "y": "i",
}

_MAX_FOLD_KEY: Final[int] = max(len(key) for key in _LATIN_FOLD)

#: ``ё`` is genuinely ambiguous across scripts: it romanises as ``yo`` (``Alyona``) but ASR
#: routinely returns it as plain ``е`` (``Алена``), and no single fold can satisfy both. So a
#: key containing the glide gets a SECOND key with the glide collapsed, and the comparison
#: takes the best pair. Deliberately limited to the ``e``-glides — folding ``ia``/``iu`` too
#: would make ``Diana`` and ``Dana`` the same name.
_GLIDE_VARIANTS: Final[dict[str, str]] = {"io": "e", "ie": "e"}

#: A transcript of an 8-second sung chunk arrives padded with filler. Comparing every window
#: of up to this many words keeps the search bounded on a pathological transcript.
_MAX_WINDOW_WORDS: Final[int] = 6


def _prefold_cyrillic(text: str) -> str:
    lowered = text.lower()
    return "".join(_CYRILLIC_PREFOLD.get(character, character) for character in lowered)


def _fold_latin(text: str) -> str:
    pieces: list[str] = []
    index = 0
    while index < len(text):
        for length in range(_MAX_FOLD_KEY, 0, -1):
            key = text[index : index + length]
            if len(key) == length and key in _LATIN_FOLD:
                pieces.append(_LATIN_FOLD[key])
                index += length
                break
        else:
            pieces.append(text[index])
            index += 1
    return "".join(pieces)


def _squeeze(text: str) -> str:
    """Collapse runs of the same letter: ``anna`` -> ``ana``, ``iiskander`` -> ``iskander``."""
    squeezed: list[str] = []
    for character in text:
        if not squeezed or squeezed[-1] != character:
            squeezed.append(character)
    return "".join(squeezed)


def sound_key(text: str) -> str:
    """Reduce any spelling of a name, in either script, to one comparable key.

    Pure and total: any input returns a string, possibly empty when the input holds no
    letters we can romanise. Never raises.

    Only ASCII letters survive: a script we have no romanisation for cannot be compared to
    anything, and keeping its characters would produce a key that matches nothing while
    looking like it works.
    """
    prefolded = _prefold_cyrillic(normalize_input(text))
    romanized = cyrillic_to_latin(prefolded, language=Language.RU)
    letters_only = "".join(
        character
        for character in strip_marks(romanized).casefold()
        if character.isascii() and character.isalpha()
    )
    return _squeeze(_fold_latin(letters_only))


def sound_keys(text: str) -> tuple[str, ...]:
    """Every key ``text`` could reasonably reduce to, best-known first.

    One key for an unambiguous name, two when a palatalised ``e`` is in play. Comparisons
    take the best pair, so an extra key can only ever raise a score.
    """
    key = sound_key(text)
    variant = key
    for glide, plain in _GLIDE_VARIANTS.items():
        variant = variant.replace(glide, plain)
    return (key,) if variant == key else (key, variant)


def _levenshtein(left: str, right: str) -> int:
    """Classic edit distance, two rows, no dependencies."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def _ratio(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    longest = max(len(left), len(right))
    if longest == 0:
        return 0.0
    return 1.0 - (_levenshtein(left, right) / longest)


def _windows(words: tuple[str, ...], size: int) -> tuple[str, ...]:
    return tuple("".join(words[start : start + size]) for start in range(len(words) - size + 1))


def _best_ratio(targets: tuple[str, ...], candidate: str) -> float:
    if not candidate:
        return 0.0
    variant = candidate
    for glide, plain in _GLIDE_VARIANTS.items():
        variant = variant.replace(glide, plain)
    heard = (candidate,) if variant == candidate else (candidate, variant)
    return max(_ratio(target, one) for target in targets for one in heard)


def name_similarity(intended: str, heard: str) -> float:
    """How alike two names sound, in ``[0.0, 1.0]``. ``1.0`` is a perfect sound-key match.

    The heard side may carry extra words — an STT pass over a sung chunk returns whatever it
    caught — so every contiguous run of up to six words is scored and the best run wins. An
    intended name with no letters scores ``0.0`` rather than dividing by zero.
    """
    targets = sound_keys(intended)
    if not targets[0]:
        return 0.0
    heard_words = normalize_input(heard).split(" ")
    words = tuple(key for key in (sound_key(word) for word in heard_words) if key)
    best = _best_ratio(targets, sound_key(heard))
    for size in range(1, min(len(words), _MAX_WINDOW_WORDS) + 1):
        for window in _windows(words, size):
            best = max(best, _best_ratio(targets, window))
    return round(best, 6)


@dataclass(frozen=True, slots=True)
class NameMatch:
    """A scored comparison. ``is_match`` is the score read against a configured threshold."""

    score: float
    is_match: bool
    intended_key: str
    heard_key: str
    min_similarity: float


def compare_names(intended: str, heard: str, *, min_similarity: float) -> NameMatch:
    """Score ``heard`` against ``intended`` and apply the caller's threshold."""
    score = name_similarity(intended, heard)
    return NameMatch(
        score=score,
        is_match=score >= min_similarity,
        intended_key=sound_key(intended),
        heard_key=sound_key(heard),
        min_similarity=min_similarity,
    )


def judge_transcript(
    *,
    candidate: NameCandidate,
    intended: str,
    transcript: Transcript,
    attempt: int,
    min_similarity: float,
) -> NameVerdict:
    """Turn an STT transcript into the verdict the re-roll loop branches on.

    ``intended`` is the DISPLAY spelling — what the name should sound like — not the
    candidate that was submitted, because a candidate is by design a distorted spelling and
    scoring the transcript against it would reward the distortion.

    ``confidence`` on the verdict is the sound-key similarity, which is what the retry
    decision is actually made on. The provider's own confidence stays on the ``Transcript``
    so both numbers remain readable in the logs instead of being blended into one.
    """
    match = compare_names(intended, transcript.text, min_similarity=min_similarity)
    return NameVerdict(
        candidate=candidate,
        transcript=transcript.text,
        is_match=match.is_match,
        confidence=match.score,
        attempt=attempt,
    )
