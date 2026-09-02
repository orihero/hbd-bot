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

**Nothing here writes.** ``balance_for`` is the only non-writing member of
:class:`~hbd.entitlements.EntitlementStore`, and it is the only method this module calls —
the same property ``handlers.confirm._entitlement_refusal`` rests on, for the same reason:
the single debit lives in the worker, which is the only process whose terminal paths can
refund one.

``show_confirm`` lives here rather than in ``handlers.confirm`` because ``handlers.lyrics``
needs it too and ``confirm`` already imports ``lyrics`` — putting it there would close the
cycle. Keeping it in one place is also what makes the note appear on every route onto that
screen instead of only the first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from hbd.bot.deps import BotDeps
from hbd.bot.draft import WizardDraft
from hbd.bot.handlers.common import Event, error_text, show_step
from hbd.bot.i18n import translate
from hbd.bot.middleware import resolve_language
from hbd.bot.states import WizardStep
from hbd.contracts import Err, Language, Result
from hbd.entitlements import (
    CreditBalance,
    EntitlementPolicy,
    period_index_for,
    period_start,
    resolve_entitlement_policy,
)
from hbd.logging import get_logger

__all__ = ["handle_balance", "show_confirm", "RENDER_COST"]

_LOG = get_logger(__name__)

#: What one render costs, restated on the read-only side of the seam for the same reason
#: ``handlers.confirm._RENDER_COST`` is: the only method that knows the real number —
#: ``EntitlementStore.charge`` — is a WRITE. Mirrors ``hbd.db.credits.DEFAULT_COST``.
RENDER_COST: Final[int] = 1


async def handle_balance(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """How many songs are left, when the next one opens, and whether one is being made.

    Never a state filter and never a draft write: this answers a question about the account
    and must work mid-wizard without disturbing the answer half-typed on the screen behind
    it — the same rule the rest of ``handlers.commands`` follows.
    """
    language = await resolve_language(state)
    user = message.from_user
    balance = None if user is None else await _read(deps, user.id)
    await message.answer(_balance_text(balance, deps, language))


async def show_confirm(event: Event, state: FSMContext, deps: BotDeps, draft: WizardDraft) -> None:
    """Put the Confirm screen up, with the credits note when there is a true one to show.

    Every route onto that screen goes through here — the lyric approval that first reaches
    it and each of ``handlers.confirm``'s early returns that comes back to it — so the
    screen a customer re-reads after a declined payment says the same thing it said the
    first time. When the meter is unwired or dark the note is ``None`` and the rendered
    text is BYTE-IDENTICAL to what it was before this module existed, which is what keeps
    the existing wizard-screen assertions honest rather than merely passing.
    """
    user = event.from_user
    balance = None if user is None else await _read(deps, user.id)
    await show_step(
        event,
        state,
        draft,
        WizardStep.CONFIRM,
        credits_note=_confirm_note(balance, deps, draft.ui_language),
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


def _balance_text(balance: Result[CreditBalance] | None, deps: BotDeps, language: Language) -> str:
    """The whole message, assembled from the lines that are true for this account."""
    if isinstance(balance, Err):
        return error_text(balance.error, language)
    state = None if balance is None else balance.value
    lines = [_count_line(state, deps, language)]
    if state is not None and state.in_flight > 0:
        lines.append(translate("credits.balance_in_flight", language))
    return "\n\n".join(lines)


def _count_line(state: CreditBalance | None, deps: BotDeps, language: Language) -> str:
    """The number, or the honest absence of one. See the module docstring for the branch."""
    policy = resolve_entitlement_policy(deps.settings)
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
    epoch (:func:`hbd.entitlements.period_index_for`), not to this customer's last song, so
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
