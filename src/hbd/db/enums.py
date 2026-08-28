"""Enums that belong to persistence rather than to the domain contract.

``hbd.contracts`` owns everything the rest of the system speaks. These three exist only
because a row needs to record something the contract has no opinion about: where a
pronunciation came from, which vendor call produced a row, and how a name was written.
They are deliberately NOT added to ``contracts.py`` — nothing outside the database and
the tuning query needs them.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["NameSource", "GenerationKind"]


class NameSource(StrEnum):
    """Provenance of a ``name_records`` row.

    Provenance is load-bearing, not bookkeeping: a curated entry may be redistributed,
    an LLM-generated one is a guess to be verified, and a user-confirmed one is personal
    data with a retention clock (SoW FR-95, DAT-3).
    """

    CURATED = "curated"
    USER_CONFIRMED = "user_confirmed"
    LLM_GENERATED = "llm_generated"
    G2P = "g2p"

    @property
    def is_personal_data(self) -> bool:
        """True when the row came from a real user and therefore expires."""
        return self is NameSource.USER_CONFIRMED


class GenerationKind(StrEnum):
    """What a ``generation_attempts`` row is an attempt at.

    ``NAME_VERIFICATION`` is not a vendor render — it is the STT verdict on a rendered
    name chunk. It lives in the same table because the tuning question ("did strategy X
    survive verification?") needs the render and its verdict side by side.
    """

    SONG = "song"
    SONG_INPAINT = "song_inpaint"
    GREETING = "greeting"
    LYRICS = "lyrics"
    NAME_PREVIEW = "name_preview"
    NAME_VERIFICATION = "name_verification"
    COVER = "cover"
