"""Character metering: what a synthesis cost, and roughly how long it will play.

Speech vendors bill per character — ElevenLabs in USD-denominated credits, others in their
own currency. None returns a price with the audio, so a rate has to come from somewhere. It
comes from the caller: :class:`CharacterPricing` is injected and defaults to "unpriced".
There is no exchange rate or price list hardcoded in this package.

An unpriced call has **no** cost, and :meth:`CharacterPricing.cost_for` says so by
returning ``(None, None)``. It used to return ``(0.0, ESTIMATED)``, which is the exact lie
the vendor-usage work exists to remove: a zero dollars figure and an unknown dollars figure
are different facts, and summing a column of defaulted zeroes reads as "this vendor cost us
nothing" when the truth is "nobody configured a rate". ``elevenlabs_usd_per_character``
ships at ``0.0``, so out of the box every speech row carries a NULL cost and the panel says
"not priced" rather than "$0.00".

Provenance is likewise not a constant. A priced call is ``DERIVED`` when the character
count came from the vendor's own ``character-cost`` header — arithmetic over a number the
vendor billed — and ``ESTIMATED`` when we fell back to counting the submitted string
ourselves, because then both halves of the product are ours. The caller knows which
happened and must say so; there is no default for ``is_vendor_counted`` for that reason.

Duration is likewise unknowable without decoding the audio, and this package must not
shell out to ffmpeg. We return a documented estimate; ``AudioPostProcessor.probe``
replaces it with the truth later in the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from hbd.contracts import CostSource
from hbd.errors import ConfigError

__all__ = [
    "DEFAULT_SPEECH_CHARS_PER_SECOND",
    "MIN_ESTIMATED_DURATION_S",
    "CharacterPricing",
    "estimate_speech_duration_s",
]

#: Conversational TTS lands near this rate across ru/en/uz in our own samples. It is an
#: estimate by construction — the probe stage overwrites it with the measured duration.
DEFAULT_SPEECH_CHARS_PER_SECOND: Final[float] = 14.0

#: ``RenderedAudio.duration_s`` must be > 0, so an estimate can never round to zero.
MIN_ESTIMATED_DURATION_S: Final[float] = 0.5

_USD_ROUNDING_PLACES: Final[int] = 6


@dataclass(frozen=True, slots=True)
class CharacterPricing:
    """Per-character billing in an arbitrary currency unit.

    ``rate_per_character`` is expressed in ``units``; ``units_per_usd`` converts them.
    For a USD-denominated vendor leave ``units_per_usd`` at 1.0; for one that bills in
    another currency pass that currency's per-USD rate. A zero rate means "we were not
    told the price", and the answer to "what did that cost" is then ``None`` — not zero,
    and never a fabricated figure.
    """

    rate_per_character: float = 0.0
    units_per_usd: float = 1.0

    def __post_init__(self) -> None:
        if self.rate_per_character < 0.0:
            raise ConfigError(
                f"rate_per_character must be >= 0, got {self.rate_per_character}",
                context={"rate_per_character": self.rate_per_character},
            )
        if self.units_per_usd <= 0.0:
            raise ConfigError(
                f"units_per_usd must be > 0, got {self.units_per_usd}",
                context={"units_per_usd": self.units_per_usd},
            )

    @property
    def is_priced(self) -> bool:
        return self.rate_per_character > 0.0

    def cost_for(
        self, character_count: int, *, is_vendor_counted: bool
    ) -> tuple[float, CostSource] | tuple[None, None]:
        """``(cost_usd, source)`` for a billed character count, or ``(None, None)``.

        ``is_vendor_counted`` is where the count came from, not where the rate came from:
        pass ``True`` when the vendor's ``character-cost`` header supplied it (the product
        is then arithmetic over a vendor-reported quantity, so ``DERIVED``) and ``False``
        when we counted the submitted string ourselves (``ESTIMATED``). It is keyword-only
        and has no default because a caller that has not thought about it would otherwise
        silently claim the stronger provenance.
        """
        if character_count < 0:
            raise ConfigError(
                f"character_count must be >= 0, got {character_count}",
                context={"character_count": character_count},
            )
        if not self.is_priced:
            return (None, None)
        units = character_count * self.rate_per_character
        source = CostSource.DERIVED if is_vendor_counted else CostSource.ESTIMATED
        return (round(units / self.units_per_usd, _USD_ROUNDING_PLACES), source)

    def units_for(self, character_count: int) -> float:
        """Cost in the vendor's own currency unit — what its invoice will show."""
        return round(character_count * self.rate_per_character, _USD_ROUNDING_PLACES)


def estimate_speech_duration_s(
    text: str, *, chars_per_second: float = DEFAULT_SPEECH_CHARS_PER_SECOND
) -> float:
    """Estimate playback length from spoken text. Always strictly positive."""
    if chars_per_second <= 0.0:
        raise ConfigError(
            f"chars_per_second must be > 0, got {chars_per_second}",
            context={"chars_per_second": chars_per_second},
        )
    return max(len(text) / chars_per_second, MIN_ESTIMATED_DURATION_S)
