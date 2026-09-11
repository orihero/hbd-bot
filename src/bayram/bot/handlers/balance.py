"""The meter, as the customer sees it: ``/balance`` and the note on the Confirm screen.

A metered product that never shows its meter until the meter is empty is the part a
customer would rightly call dishonest. Until this module existed the entitlement layer had
exactly one customer-visible surface — the refusal — so the first time anyone learned that
songs were counted was the moment they were told they had run out. That is the whole reason
this ships in the same change as the enforcement it describes.

**The number is shown only when it is true.** Both surfaces below are silent unless the
meter is wired AND ``EntitlementPolicy.is_balance_enforced`` (that is,
``Settings.credits_enforced``) is on, because that flag is precisely the difference between
a count that can refuse a customer and one that cannot. A dark deployment still keeps the
count — the ledger runs in full, so the in-flight cap and the block gate have the rows they
need — but an account that has run out is covered by a grant and renders anyway, so its
balance sits at zero while nothing is ever denied. Printing "0 of your 3 songs left" to
someone the product will happily keep serving is a more expensive lie than saying nothing: a
customer budgets against a number. ``credits.balance_none`` says what is actually true
there — no limit is being applied to you — and that is what a dark meter is.

**One thing is shown regardless of the flag: a song already in the studio.** The in-flight
cap and the block gate enforce from the day they merged, flag or no flag (D-B), so an
account holding an unsettled render will be refused at Confirm whatever the balance says.
A ``/balance`` that omitted it would answer "yes, go ahead" to someone about to be told no.

**A deployment that SELLS songs is a third configuration, and it is the shipped one.** With
``BotDeps.purchases`` and ``BotDeps.pricing`` wired, both surfaces stop describing an
allowance and start describing a price: ``/balance`` answers with ``credits.balance_metered``
and carries the two purchase buttons when the account cannot afford a render, and the Confirm
screen wears the checkout face that :func:`build_offer` decides on. That decision lives HERE,
in the module that already owns the only funnel onto the Confirm screen and already reads the
meter for it — a second owner would mean a second read, and two reads of one meter are two
answers that are free to disagree inside one screen.

**Nothing here writes.** ``balance_for`` is the only non-writing member of
:class:`~bayram.entitlements.EntitlementStore`, and it is the only method this module calls —
the same property ``handlers.confirm._entitlement_refusal`` rests on, for the same reason:
the single debit lives in the worker, which is the only process whose terminal paths can
refund one.

``show_confirm`` lives here rather than in ``handlers.confirm`` because ``handlers.lyrics``
needs it too and ``confirm`` already imports ``lyrics`` — putting it there would close the
cycle. Keeping it in one place is also what makes the note appear on every route onto that
screen instead of only the first.

``show_balance`` is here for the mirror-image reason. ``handlers.checkout`` has to redraw
this screen after a purchase made FROM it — the 💳 and 🌟 buttons are drawn on the
``/balance`` answer, not only on the Confirm screen — and a checkout that assembled the
balance text itself would be a second renderer of one screen, free to disagree with this
one about what the account holds. See :func:`show_balance`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bayram.bot.deps import BotDeps
from bayram.bot.draft import WizardDraft
from bayram.bot.handlers.common import Event, error_text, present, show_step
from bayram.bot.i18n import translate
from bayram.bot.keyboards import checkout_keyboard
from bayram.bot.middleware import resolve_language
from bayram.bot.pricing import CheckoutOffer
from bayram.bot.screens import Screen
from bayram.bot.states import WizardStep
from bayram.contracts import Err, Language, Result
from bayram.entitlements import (
    CreditBalance,
    EntitlementPolicy,
    period_index_for,
    period_start,
    resolve_entitlement_policy,
)
from bayram.logging import get_logger

__all__ = ["handle_balance", "show_balance", "show_confirm", "build_offer", "RENDER_COST"]

_LOG = get_logger(__name__)

#: What one render costs, restated on the read-only side of the seam for the same reason
#: ``handlers.confirm._RENDER_COST`` is: the only method that knows the real number —
#: ``EntitlementStore.charge`` — is a WRITE. Mirrors ``bayram.db.credits.DEFAULT_COST``.
RENDER_COST: Final[int] = 1


async def handle_balance(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """How many songs are left, when the next one opens, and whether one is being made.

    Never a state filter and never a draft write: this answers a question about the account
    and must work mid-wizard without disturbing the answer half-typed on the screen behind
    it — the same rule the rest of ``handlers.commands`` follows.

    On a SELLING deployment the answer also carries the two purchase buttons whenever the
    account cannot afford a render, so "you are out" and "here is how to buy" are one
    message rather than two screens the customer has to find their way between. On every
    other deployment ``deps.purchases`` is ``None``, ``build_offer`` answers ``None``, and
    every branch below is exactly what it was.
    """
    await show_balance(message, state, deps)


async def show_balance(event: Event, state: FSMContext, deps: BotDeps) -> None:
    """The balance screen, sent for a command and edited in place for a button press.

    Split out of :func:`handle_balance` so that ``handlers.checkout`` can redraw THIS screen
    after a purchase made from it. The defect that made the split necessary is worth naming:
    the 💳 and 🌟 buttons were drawn here by :func:`handle_balance` and the two handlers
    that answer them were registered behind a ``Wizard.confirm`` state filter, so a customer
    who opened ``/balance`` to see what they had left pressed Buy and was told their session
    had expired. A button that cannot work must not be drawn — and the right fix was to make
    it work, because ``/balance`` is exactly where somebody who is out of songs looks first.

    ``present`` rather than ``message.answer``, and the difference is the whole point of the
    redraw. For a ``Message`` it sends, which is byte-for-byte what ``/balance`` did before
    this function existed. For a ``CallbackQuery`` it EDITS the message the button was on —
    so a paid-for balance replaces the paywalled one in place and the purchase buttons go
    with it, rather than leaving a stale price under a screen the customer has already paid
    past and could press again.

    The meter is read ONCE, and the count line, the plan note and the keyboard all come off
    that one read, for the reason :func:`show_confirm` gives: two reads of one meter are two
    answers that are free to disagree inside a single message.
    """
    language = await resolve_language(state)
    user = event.from_user
    balance = None if user is None else await _read(deps, user.id)
    offer = build_offer(balance, deps)
    markup = None
    if offer is not None and offer.is_paywalled:
        markup = checkout_keyboard(language, offer)
    await present(event, Screen(_balance_text(balance, deps, language, offer), markup))


async def show_confirm(event: Event, state: FSMContext, deps: BotDeps, draft: WizardDraft) -> None:
    """Put the Confirm screen up, with the credits note when there is a true one to show.

    Every route onto that screen goes through here — the lyric approval that first reaches
    it and each of ``handlers.confirm``'s early returns that comes back to it — so the
    screen a customer re-reads after a declined payment says the same thing it said the
    first time. When the meter is unwired or dark the note is ``None``, the offer is
    ``None``, and the rendered text is BYTE-IDENTICAL to what it was before this module
    existed, which is what keeps the existing wizard-screen assertions honest rather than
    merely passing.

    **The meter is read exactly once here**, and both the note and the offer are derived
    from that one read. A second read would be a second answer: the two halves of one screen
    would be free to disagree about the balance, so the summary could say "you have 1" under
    a paywall that had just decided there were none — and it would cost a database round
    trip inside aiogram's FSM isolation lock to do it.
    """
    user = event.from_user
    balance = None if user is None else await _read(deps, user.id)
    await show_step(
        event,
        state,
        draft,
        WizardStep.CONFIRM,
        credits_note=_confirm_note(balance, deps, draft.ui_language),
        offer=build_offer(balance, deps),
    )


def build_offer(balance: Result[CreditBalance] | None, deps: BotDeps) -> CheckoutOffer | None:
    """What this account may buy, or ``None`` for "draw the screen this bot drew yesterday".

    ``None`` means the checkout does not exist for this update, and there are three ways to
    reach it, only one of which is a configuration:

    * ``deps.purchases`` or ``deps.pricing`` is unset — this deployment does not sell.
      Every ``BotDeps`` built outside ``bayram.main`` wires neither, which is precisely what
      keeps every pre-existing screen assertion byte-identical rather than merely passing;
    * there is no meter to read at all;
    * the read FAILED. **This is the one branch that is not what it looks like, and the
      distinction is worth reading before changing either half.** The SCREEN still fails
      open — no price is put in front of somebody whose balance nobody could check, because
      "you must pay" is a claim we have no evidence for and a customer holding ten credits
      would be shown a bill. The ACT does not: ``handlers.confirm._entitlement_refusal``
      now REFUSES a selling deployment's Confirm press on an unreadable meter and says the
      service is temporarily unavailable. That asymmetry is the fix for a real defect —
      this function returning ``None`` on an ``Err`` used to leave 🎬 Record it on the
      screen AND satisfy ``confirm._second_line``, and since ``credits_enforced`` ships
      false the worker charged the shortfall and sang the song for nothing. So: unknown
      balance, no price shown, and no render queued either.

    **This predicate deliberately does NOT consult ``EntitlementPolicy.is_balance_enforced``.**
    That flag governs whether the WORKER refuses a render it cannot pay for; the paywall is
    the product. Gating on it would make the buttons invisible in the shipped configuration
    (it defaults False), which is the opposite of what was decided, and it would mix
    allowance copy — "your allowance refills on the 7th" — with price buttons on one screen.
    The two settings do belong together in production, which is why ``bayram.main`` warns at
    boot when a selling deployment leaves the meter dark.

    ``is_blocked`` suppresses the paywall as well. A blocked account is not a customer who
    needs to pay; it is one an operator has stopped, and selling them a song they will then
    be refused is the one outcome worse than the refusal.
    """
    store = deps.purchases
    pricing = deps.pricing
    if store is None or pricing is None or balance is None or isinstance(balance, Err):
        return None
    state = balance.value
    ends_at = state.plan_ends_at
    return CheckoutOffer(
        is_paywalled=not state.is_blocked and state.credits < RENDER_COST,
        credits=state.credits,
        plan_songs_left=state.plan_songs_left,
        plan_ends_on=None if ends_at is None else ends_at.date().isoformat(),
        # A plan is offered only when none is running. ``plan_ends_at`` is set for a
        # SPENT-but-unexpired plan too, which is exactly the case the fulfiller refuses to
        # sell a second plan for — so the button that would take that money is not drawn.
        is_plan_offered=ends_at is None,
        pricing=pricing,
    )


async def _read(deps: BotDeps, telegram_user_id: int) -> Result[CreditBalance] | None:
    """The account, the failure, or ``None`` for "there is no meter to read".

    A failed read is kept distinct from an absent one rather than folded into it, because
    they are different answers to a customer: an unwired meter means "nothing is counted"
    and an unreadable one means "I cannot tell you right now". Saying the first when the
    second is true would be the same dishonesty this module exists to remove, one layer
    down.
    """
    store = deps.entitlements
    if store is None:
        return None
    balance = await store.balance_for(telegram_user_id)
    if isinstance(balance, Err):
        _LOG.error("the entitlement meter could not be read", extra=balance.error.to_log_dict())
    return balance


def _balance_text(
    balance: Result[CreditBalance] | None,
    deps: BotDeps,
    language: Language,
    offer: CheckoutOffer | None,
) -> str:
    """The whole message, assembled from the lines that are true for this account."""
    if isinstance(balance, Err):
        return error_text(balance.error, language)
    state = None if balance is None else balance.value
    lines = [_count_line(state, deps, language, offer)]
    if offer is not None and offer.plan_ends_on is not None:
        lines.append(
            translate(
                "checkout.plan_note",
                language,
                songs=offer.plan_songs_left,
                ends_on=offer.plan_ends_on,
            )
        )
    if state is not None and state.in_flight > 0:
        lines.append(translate("credits.balance_in_flight", language))
    return "\n\n".join(lines)


def _count_line(
    state: CreditBalance | None,
    deps: BotDeps,
    language: Language,
    offer: CheckoutOffer | None,
) -> str:
    """The number, or the honest absence of one. See the module docstring for the branch.

    A SELLING deployment takes the first branch and it is not a variation on the second: the
    allowance copy is written around a number that refills on its own, and
    ``Settings.free_allowance_credits`` ships at 0 there, so ``credits.balance`` would tell a
    customer their allowance was "0 every 30 days" and that there was nothing to buy — on
    the very account the next screen is about to sell to. ``credits.balance_metered`` says
    the true thing instead: each song costs one, and here is how to get more. It is chosen
    on ``offer`` rather than on ``deps.purchases`` directly so that the read failure and the
    unwired meter keep the old, honest wording rather than promising a shop we could not
    confirm the customer needs.

    ``credits.next_opens`` is deliberately NOT appended on the metered branch. It names the
    day a ROLLING ALLOWANCE reopens, and a deployment that sells every song has none — the
    date would be a promise that the calendar will hand over a free song it never will.
    """
    policy = resolve_entitlement_policy(deps.settings)
    if state is not None and offer is not None:
        return translate("credits.balance_metered", language, credits=state.credits)
    if state is None or not policy.is_balance_enforced:
        return translate("credits.balance_none", language)
    line = translate(
        "credits.balance",
        language,
        credits=state.credits,
        allowance=policy.allowance_credits,
        period_days=policy.allowance_period_days,
    )
    if state.credits >= RENDER_COST:
        return line
    return f"{line}\n\n{_next_opens(policy, deps.clock(), language)}"


def _next_opens(policy: EntitlementPolicy, now: datetime, language: Language) -> str:
    """The day this account can order again — the same sentence the refusal ends on.

    Derived here rather than passed in because the allowance window is anchored to a fixed
    epoch (:func:`bayram.entitlements.period_index_for`), not to this customer's last song, so
    "in 30 days" would be wrong for everyone who did not spend their last credit on the day
    the window opened. A plain ``YYYY-MM-DD``: the window turns over at midnight UTC and a
    full ISO timestamp would put a time zone in front of a fact accurate only to the day.
    """
    index = period_index_for(now, period_days=policy.allowance_period_days)
    opens = period_start(index + 1, period_days=policy.allowance_period_days)
    return translate("credits.next_opens", language, next_grant_at=opens.date().isoformat())


def _confirm_note(
    balance: Result[CreditBalance] | None, deps: BotDeps, language: Language
) -> str | None:
    """The one line the Confirm screen adds, or ``None`` when there is nothing true to add.

    A failed read produces ``None`` rather than a warning. The customer is one tap from
    ordering and the gate behind this screen refuses them properly if the meter really is
    unreadable, so an apology here would cost a sale to report a problem they cannot act on.
    """
    if balance is None or isinstance(balance, Err):
        return None
    if not resolve_entitlement_policy(deps.settings).is_balance_enforced:
        return None
    return translate("credits.confirm_note", language, credits=balance.value.credits)
