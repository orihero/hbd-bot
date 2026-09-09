"""Token pricing for the chat-completion leg: a rate the deployment supplies, or none.

A chat completion is billed per token, and the token counts come back on the response —
but the *price* of a token does not, except on OpenRouter, which returns ``usage.cost``
when it is asked to. Everywhere else a dollar figure can only be arithmetic over a rate
card, and a rate card is a deployment fact, not a fact about this code. So it is injected,
it defaults to "unpriced", and an unpriced call has **no** cost.

That last sentence is the whole point of this module. A zero dollar cost is a claim — "this
call was free" — and summing a column of them tells an operator the deployment spent
nothing when the truth is that nobody configured a rate. ``(None, None)`` is the honest
answer, ``vendor_usage.cost_usd`` is nullable precisely so it can be stored, and the panel
renders it as "not priced". :class:`hbd.providers.tts.metering.CharacterPricing` used to
disagree — its unpriced answer was ``(0.0, ESTIMATED)`` — and the vendor-usage work
changed it to ``(None, None)`` too, so the speech leg and this one now answer "unpriced"
the same way and neither contributes a fabricated zero to a cost total.

The source is always :data:`CostSource.DERIVED` when a figure is produced: the token
counts are the vendor's own measurement and only the multiplication is ours. That is a
stronger claim than ESTIMATED (which the music leg uses, where even the duration is what
we ASKED for rather than what was rendered) and a weaker one than VENDOR_REPORTED (which
belongs only to a number the vendor itself put on the response), and the three have to
stay distinguishable on the row or a cost total cannot be trusted differently by grade.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from hbd.contracts import CostSource
from hbd.errors import ConfigError

__all__ = ["TOKENS_PER_PRICING_UNIT", "TokenPricing"]

#: Every vendor quotes its rate card per million tokens, so the setting is spelled that
#: way and the division lives here rather than in four config docstrings.
TOKENS_PER_PRICING_UNIT: Final[int] = 1_000_000

_USD_ROUNDING_PLACES: Final[int] = 6


@dataclass(frozen=True, slots=True)
class TokenPricing:
    """USD per million prompt and completion tokens. Defaults to unpriced.

    Both rates are validated at construction, which is the only place strictness is safe:
    a rate arrives from configuration at startup, where a raise is a readable boot failure,
    while a token count arrives from a vendor mid-call, where a raise would turn a bad
    telemetry field into a lost song. Hence :meth:`cost_for` never raises.
    """

    usd_per_million_prompt: float = 0.0
    usd_per_million_completion: float = 0.0

    def __post_init__(self) -> None:
        if self.usd_per_million_prompt < 0.0:
            raise ConfigError(
                f"usd_per_million_prompt must be >= 0, got {self.usd_per_million_prompt}",
                context={"usd_per_million_prompt": self.usd_per_million_prompt},
            )
        if self.usd_per_million_completion < 0.0:
            raise ConfigError(
                f"usd_per_million_completion must be >= 0, got {self.usd_per_million_completion}",
                context={"usd_per_million_completion": self.usd_per_million_completion},
            )

    @property
    def is_priced(self) -> bool:
        """True when at least one rate was configured. Two zeroes mean "we were not told"."""
        return self.usd_per_million_prompt > 0.0 or self.usd_per_million_completion > 0.0

    def cost_for(
        self, prompt_tokens: int | None, completion_tokens: int | None
    ) -> tuple[float, CostSource] | tuple[None, None]:
        """Return ``(cost_usd, DERIVED)``, or ``(None, None)`` when nothing can be claimed.

        ``(None, None)`` in two cases, both of which mean "unknown" rather than "free":
        no rate is configured, and the vendor reported neither token count. A count that
        is absent on its own contributes nothing, so a response carrying only
        ``prompt_tokens`` yields a figure that is a floor — recorded as DERIVED because it
        is still arithmetic over a measurement, and visibly incomplete because the
        matching token column on the row stays ``NULL`` beside it.

        A negative count is not a measurement and is read as absent. The vendor JSON has
        already been walked with ``read_path`` by the time it gets here, so this is a
        second belt on the same trousers rather than the only one.
        """
        prompt = _measured(prompt_tokens)
        completion = _measured(completion_tokens)
        if not self.is_priced or (prompt is None and completion is None):
            return (None, None)
        units = (prompt or 0) * self.usd_per_million_prompt + (
            completion or 0
        ) * self.usd_per_million_completion
        return (round(units / TOKENS_PER_PRICING_UNIT, _USD_ROUNDING_PLACES), CostSource.DERIVED)


def _measured(count: int | None) -> int | None:
    """A token count we are willing to multiply, or ``None``."""
    return count if count is not None and count >= 0 else None
