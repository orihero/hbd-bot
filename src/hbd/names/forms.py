"""Two names, two types. The one place this system refuses to let you be sloppy.

Every name in this product exists twice:

* the **display form** — perfect ``ʻ``, correct casing, the string a customer reads in a
  Telegram message and on the lyric sheet;
* the **submit form** — whatever spelling actually makes the vendor's model pronounce the
  name, which may be ``Gulomjon``, ``Gu-lom-jon``, ``Ghoolomjon`` or ``Ғуломжон``. Nobody
  ever sees it.

Conflating them is the single most expensive bug available in this codebase: ship the
submit form to the user and the product looks illiterate; ship the display form to the
model and the name is mispronounced, which is the entire thing we sell.

So they are two distinct types, not two ``str`` variables. Neither is a ``str`` subclass and
neither defines ``__str__``, so a display form cannot be passed where a submit form is
expected (mypy rejects it) and an accidental ``f"{form}"`` renders
``DisplayForm(text='Gʻulomjon')`` — loud, obvious, and caught in review — instead of
silently looking correct. To get at the characters you must say which form you meant by
reaching for ``.text``.
"""

from __future__ import annotations

from dataclasses import dataclass

from hbd.contracts import MAX_CANDIDATE_CHARS, NameCandidate, NameStrategy

__all__ = ["DisplayForm", "SubmitForm"]


@dataclass(frozen=True, slots=True)
class DisplayForm:
    """The human-facing spelling. U+02BB where Uzbek Latin requires it. Immutable."""

    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("display form must contain a visible character")


@dataclass(frozen=True, slots=True)
class SubmitForm:
    """One vendor-facing spelling plus the strategy that produced it. Immutable.

    ``rank`` is not stored here: rank is a property of the ORDER a caller tries these in,
    which comes from configuration, so it is assigned when the candidate list is built.
    """

    text: str
    strategy: NameStrategy

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError(f"submit form for {self.strategy} must contain a visible character")

    @property
    def is_within_vendor_limit(self) -> bool:
        return len(self.text) <= MAX_CANDIDATE_CHARS

    def as_candidate(self, rank: int) -> NameCandidate:
        """Project into the frozen contract model at a given rank."""
        return NameCandidate(text=self.text, strategy=self.strategy, rank=rank)
