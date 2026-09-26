"""Ranked candidate orthographies — the list the re-roll loop walks down.

Six ways to spell one name, each aimed at a different failure of the vendor's grapheme
model. **The order they are tried in is configuration, never code.** A bake-off is applied
by reordering ``BAYRAM_NAME_CANDIDATE_ORDER``; this module reads whatever order it is handed
and assigns ranks from it. There is no default order in this file and no ``if strategy ==``
chain that privileges one spelling over another.

Duplicates are collapsed. If ``STRIPPED`` and ``CANONICAL`` both yield ``Aziza`` — which
they do for every name without a mark — the second one is dropped, because spending an
acoustic retry re-rendering an identical string is spending money to learn nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

from bayram.contracts import MAX_CANDIDATE_CHARS, Language, NameCandidate, NameStrategy, Script
from bayram.logging import get_logger
from bayram.names.forms import DisplayForm, SubmitForm
from bayram.names.marks import strip_marks, to_ascii_marks
from bayram.names.phonetic import respell_phonetically
from bayram.names.script import detect_script
from bayram.names.syllables import hyphenate
from bayram.names.translit import transliterate

__all__ = ["derive_submit_form", "build_candidates"]

_logger = get_logger(__name__)


def _to_latin(text: str, language: Language) -> str:
    return transliterate(text, target=Script.LATIN, language=language)


def derive_submit_form(
    display: DisplayForm, strategy: NameStrategy, *, language: Language
) -> SubmitForm | None:
    """Derive one vendor-facing spelling, or ``None`` when the strategy yields nothing usable.

    ``None`` is a normal outcome, not an error: a name with no letters left after stripping
    (or a respelling that blows past the vendor's length limit) simply has no candidate for
    that strategy, and the next strategy in the configured order takes the rank.
    """
    text = _derive_text(display.text, strategy, language)
    if not text.strip():
        return None
    if len(text) > MAX_CANDIDATE_CHARS:
        _logger.debug(
            "name candidate discarded: over vendor length limit",
            extra={"strategy": str(strategy), "length": len(text), "limit": MAX_CANDIDATE_CHARS},
        )
        return None
    return SubmitForm(text=text, strategy=strategy)


def _derive_text(display: str, strategy: NameStrategy, language: Language) -> str:
    match strategy:
        case NameStrategy.CANONICAL:
            return display
        case NameStrategy.STRIPPED:
            return strip_marks(display)
        case NameStrategy.ASCII:
            return to_ascii_marks(_to_latin(display, language))
        case NameStrategy.CYRILLIC:
            return transliterate(display, target=Script.CYRILLIC, language=language)
        case NameStrategy.HYPHENATED:
            return hyphenate(_hyphenation_source(display))
        case NameStrategy.PHONETIC:
            return respell_phonetically(display, language=language)


def _hyphenation_source(display: str) -> str:
    """Hyphenate the mark-free spelling in Latin, the Cyrillic spelling as-is.

    Mixing ``ʻ`` and ``-`` in one string gives a model two separator-shaped characters to
    trip over, and the mark is exactly what it already mishandles.
    """
    if detect_script(display).script is Script.CYRILLIC:
        return display
    return strip_marks(display)


def build_candidates(
    display: DisplayForm, *, order: Sequence[NameStrategy], language: Language
) -> tuple[NameCandidate, ...]:
    """Build the ranked candidate list for ``display`` in the configured strategy order.

    Ranks are dense and start at zero, as ``RecipientName`` requires. The result is never
    empty: if every configured strategy is dropped, the display spelling itself is submitted
    as the sole candidate, because delivering a best-effort pronunciation beats delivering
    nothing.
    """
    seen: set[str] = set()
    candidates: list[NameCandidate] = []
    for strategy in order:
        form = derive_submit_form(display, strategy, language=language)
        if form is None or form.text in seen:
            continue
        seen.add(form.text)
        candidates.append(form.as_candidate(len(candidates)))
    if candidates:
        return tuple(candidates)
    _logger.warning(
        "no candidate orthography survived derivation; falling back to the display spelling",
        extra={"order": [str(strategy) for strategy in order], "language": str(language)},
    )
    fallback = SubmitForm(text=display.text, strategy=NameStrategy.CANONICAL)
    return (fallback.as_candidate(0),)
