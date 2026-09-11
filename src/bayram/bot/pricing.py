"""What the checkout screen quotes, and how a number in tiyin becomes a number a person reads.

Pure. No I/O, no awaits, no clock. Everything here is a value the screen layer can render
without asking anything else a question, which is the property that keeps
``bayram.bot.screens`` a pure function of the draft — the thing that lets thirty-odd screen
tests assert on exact strings instead of building a database.

**Prices are stored in MINOR units and only ever formatted at the edge.**
``kit_price_amount_minor`` and ``PaymentAuthorization.amount_minor`` are already minor units
and Payme quotes tiyin, so 700_000 is already the number a real rail will be sent. Storing
7000 and multiplying at the rail is precisely how a rounding bug becomes a pricing bug, and
it is a bug that is invisible until someone has been charged the wrong amount.

**Formatting never produces a currency word.** ``format_amount`` returns "7 000" and never
"7 000 UZS", because the word differs per language — soʻm, сум, сўм — and lives in the four
locale catalogues where translators can reach it. A price baked into those catalogues would
silently disagree with ``BAYRAM_SINGLE_SONG_PRICE_MINOR`` the day an operator changes it; a
price interpolated INTO them cannot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from bayram.config import Settings

__all__ = [
    "GROUPING_SPACE",
    "format_amount",
    "Pricing",
    "CheckoutOffer",
]

#: U+00A0 NO-BREAK SPACE, and no other separator. A price is the one string on the checkout
#: screen that must not be split across a line: "49" at the end of one line and "000 soʻm" at
#: the start of the next reads as a different, much cheaper product, and Telegram wraps
#: button labels and message bodies at whatever width the customer's phone happens to be.
#: A comma was rejected because none of the four locales groups with one, and a plain space
#: was rejected because it is exactly the character that wraps.
GROUPING_SPACE: Final[str] = " "

#: Minor units per major unit. UZS has exponent 2 (tiyin), like almost every currency this
#: product will ever quote, and it is spelled once here rather than as a bare ``100`` inside
#: the arithmetic so the assumption is greppable the day a zero-exponent currency appears.
_MINOR_PER_MAJOR: Final[int] = 100

#: Digits per group, from the right.
_GROUP_SIZE: Final[int] = 3


def format_amount(amount_minor: int) -> str:
    """Render ``amount_minor`` as grouped major units, with no currency word.

    Floor division, deliberately, and it truncates rather than rounds: 99 tiyin renders as
    "0". Every price this product quotes is a whole number of soʻm, so the fractional part is
    always zero in practice and the only way to reach this branch is a misconfiguration — in
    which case showing LESS than was configured is the direction that cannot overcharge
    anybody, and rounding 99 up to "1" would put a price on screen that the rail then does
    not charge.

    Grouping is done by hand rather than with ``f"{n:,}"`` because the format spec's only
    separators are ``,`` and ``_``, and the separator this needs is U+00A0 — see
    :data:`GROUPING_SPACE`. Post-processing a comma out of a formatted string would work and
    would also silently mangle any locale-aware formatting somebody added later.
    """
    major = amount_minor // _MINOR_PER_MAJOR
    digits = str(major)
    groups = []
    while len(digits) > _GROUP_SIZE:
        groups.append(digits[-_GROUP_SIZE:])
        digits = digits[:-_GROUP_SIZE]
    groups.append(digits)
    return GROUPING_SPACE.join(reversed(groups))


@dataclass(frozen=True, slots=True)
class Pricing:
    """This deployment's catalogue, resolved once at boot and injected.

    Read off ``Settings`` at the composition root and carried on ``BotDeps`` rather than
    re-read per screen, for the same reason every other policy in this codebase is: a handler
    that reached for ambient settings would be a handler no test could price differently
    without patching an import.

    ``None`` on ``BotDeps.pricing`` means "this deployment does not sell", and that is what
    keeps every pre-existing screen byte-identical — a deployment that wires no pricing draws
    no checkout.
    """

    single_amount_minor: int
    plan_amount_minor: int
    plan_songs: int
    plan_days: int
    #: ISO-4217, three letters. Shared with ``kit_currency``: the render gate and the
    #: checkout quote the same currency, and a deployment that made them differ would be
    #: showing a customer one currency and sending a rail another.
    currency: str

    @classmethod
    def from_settings(cls, settings: Settings) -> Pricing:
        """Build the catalogue from configuration. The ONE place these five fields are read.

        Importing ``bayram.config`` is fine here and is not fine in ``bayram.checkout``: this module
        lives under ``bayram.bot``, which is already the layer that owns composition-shaped
        values, while ``bayram.checkout`` is a leaf that ``bayram.db`` imports.
        """
        return cls(
            single_amount_minor=settings.single_song_price_minor,
            plan_amount_minor=settings.starter_plan_price_minor,
            plan_songs=settings.starter_plan_songs,
            plan_days=settings.starter_plan_days,
            currency=settings.kit_currency,
        )

    @property
    def single_amount(self) -> str:
        """The single-song price as a person reads it, e.g. ``"7 000"``. No currency word."""
        return format_amount(self.single_amount_minor)

    @property
    def plan_amount(self) -> str:
        """The plan price as a person reads it, e.g. ``"49 000"``. No currency word."""
        return format_amount(self.plan_amount_minor)


@dataclass(frozen=True, slots=True)
class CheckoutOffer:
    """Everything the Confirm screen needs in order to wear its checkout face, and no more.

    This exists so ``bayram.bot.screens`` stays a pure function of the draft. Every field below
    is FINISHED — already read, already decided, already formatted — so the renderer performs
    no lookups, awaits nothing and cannot differ between a test and production. The moment
    one of these becomes a store handle instead of a value, the screen tests need a database
    and stop being screen tests.

    It is a value object passed INTO ``render_step`` rather than a new ``WizardStep``,
    because a new step would force members in ``Wizard``, entries in both step orders, a
    ``_STATE_BY_STEP`` row and a ``resolve_step`` downgrade that must strictly move earlier or
    ``show_step``'s fixpoint loop never terminates — for a screen that is the same screen
    wearing a different face.
    """

    #: Whether to draw the checkout face at all. False renders the ordinary Confirm summary.
    #: Decided by the caller, not here, because it depends on ports this module cannot see.
    is_paywalled: bool
    #: Spendable credits, INCLUDING a live plan's unminted songs — the same projection
    #: ``CreditBalance.credits`` carries, for the same reason: a read-only gate must not
    #: paywall a customer the writer would have minted a song for a second later.
    credits: int
    #: Songs the running plan can still mint. 0 for a spent plan and for no plan at all;
    #: ``plan_ends_on`` is what distinguishes those two.
    plan_songs_left: int
    #: A plain ``YYYY-MM-DD``, following ``credits.next_opens``' precedent, or ``None`` when
    #: no plan is running. A date string and not a ``datetime``, because formatting a date is
    #: a rendering decision and this object exists so the renderer makes none.
    plan_ends_on: str | None
    #: Whether the plan button is drawn. False while a plan is already running, spent or not:
    #: a second plan would overwrite an end date the customer has already paid for, so a
    #: spent plan is offered the single song only.
    is_plan_offered: bool
    #: What the two buttons cost.
    pricing: Pricing
