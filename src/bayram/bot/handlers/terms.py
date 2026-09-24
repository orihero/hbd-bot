"""The Terms of Use + Privacy screen's buttons, and the ``Onboarding.terms`` step.

IMAGE_VIDEO_SPEC §2.1, D26. Every customer accepts the version pair in force before using the
bot: a new account between the language picker and the contact screen, an onboarded one when
``bot.terms_gate.TermsGateMiddleware`` stops their next message.

**Registered inside the onboarding router, above its catch-all, by**
:func:`bayram.bot.handlers.onboarding.build_router` calling :func:`register`. Not a router of
its own: the whole point is the POSITION — below ``commands`` and ``start``, so ``/privacy``,
``/forget`` and ``/start`` are never mistaken for an answer, and above ``NotOnboarded``, which
claims every update from a customer with no phone number and would answer a new customer's ✅
with the Terms screen they were already looking at.

**The two ``trm:*`` callbacks carry no state filter.** The gate screen is drawn in any state
— mid-wizard for an onboarded customer the middleware stopped, ``Onboarding.terms`` for a new
one — and a ✅ from either has to reach the same handler. Which of the two it was is read
from the account (:func:`~bayram.bot.handlers.onboarding.load_identity`), not from the FSM,
and it decides two things only: the ``source`` column of the acceptance, and what comes next.

**Nothing here opens a ``user_profiles`` row** (IMAGE_VIDEO_SPEC §0.3): the acceptance goes
through :class:`bayram.terms.TermsGate` to ``terms_acceptances`` alone, and onboarding goes on
reading "has chosen a language" off the profile exactly as before.
"""

from __future__ import annotations

from typing import Final

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bayram.bot.callbacks import TermsAction, TermsCB
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import error_text, present, ui_language
from bayram.bot.handlers.onboarding import load_identity, present_terms, terms_standing
from bayram.bot.i18n import translate
from bayram.bot.screens import (
    Screen,
    menu_screen,
    onboarding_contact_screen,
    onboarding_language_screen,
    terms_full_screen,
)
from bayram.bot.states import Onboarding
from bayram.contracts import Err
from bayram.logging import get_logger
from bayram.terms import TermsSource, TermsStanding

__all__ = ["register", "TERMS_REQUIRED_KEY"]

_LOG = get_logger(__name__)

#: The one-line refusal: the toast on a blocked button, and the opening of the repeated screen.
TERMS_REQUIRED_KEY: Final[str] = "terms.required"

#: Telegram 400s a callback answer over 200 characters.
_CALLBACK_ANSWER_MAX_CHARS: Final[int] = 200


async def handle_terms_accept(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """✅ — record the acceptance, then carry on to whatever was next.

    **The record first, and a failed record does not advance.** The acceptance row is the
    lawful-basis evidence (D26); answering "thank you" over a failed write would let the
    customer through on a promise with nothing behind it, and they would meet the gate again on
    the next message with no idea why. The error is an alert on the button, the screen stays,
    and the next tap tries again — the write is idempotent.

    **What comes next** is read from the account rather than the FSM: a customer who has not
    finished onboarding goes on to the contact screen (or back to the language screen, in the
    one odd case of a ✅ from a screen that predates the language choice); an onboarded one is
    handed the menu, which is "back to what they were doing" for a customer the middleware
    stopped mid-sentence (IMAGE_VIDEO_SPEC §2.1).

    With no gate wired — the version was unset between the screen being drawn and the tap —
    there is nothing to record and the customer is simply let on.
    """
    user = callback.from_user
    # Identity FIRST: it is what repairs the FSM's language cache from the profile row when the
    # session expired under the screen, so the acceptance records — and the next screen speaks
    # — the language the customer chose rather than the operator default.
    identity = await load_identity(state, deps, user.id)
    language = identity.ui_language or await ui_language(state, deps)
    if deps.terms is not None:
        source: TermsSource = "gate" if identity.is_onboarded else "onboarding"
        accepted = await deps.terms.accept(user.id, language=language, source=source)
        if isinstance(accepted, Err):
            _LOG.error(
                "the terms acceptance could not be recorded", extra=accepted.error.to_log_dict()
            )
            text = error_text(accepted.error, language)
            await callback.answer(text[:_CALLBACK_ANSWER_MAX_CHARS], show_alert=True)
            return
        _LOG.info(
            "terms accepted",
            extra={"source": source, "terms_version": deps.terms.versions.terms},
        )
    await callback.answer()
    # Edited over the Terms screen, so its buttons go with it and a second ✅ has nothing to
    # press. Markup ``None`` is what makes ``_edit_or_send`` edit rather than send.
    await present(callback, Screen(translate("terms.accepted", language)))
    if identity.is_onboarded:
        if await state.get_state() == Onboarding.terms.state:
            # Only reachable through a hand-edited FSM or a profile written behind the bot's
            # back; either way the step is over, and a parked ``Onboarding.terms`` would keep
            # answering this customer's messages with the Terms.
            await state.set_state(None)
        await present(callback, menu_screen(language))
        return
    if not identity.is_language_chosen:
        await state.set_state(Onboarding.language)
        await present(callback, onboarding_language_screen(language))
        return
    await state.set_state(Onboarding.contact)
    # A new message, necessarily: the contact screen carries a reply keyboard, which Telegram
    # will not attach by an edit. ``_edit_or_send`` knows and sends.
    await present(callback, onboarding_contact_screen(language))


async def handle_terms_read_full(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """📄 — the whole Terms of Use, drawn over the summary, with ✅ under it when still owed."""
    await callback.answer()
    identity = await load_identity(state, deps, callback.from_user.id)
    language = identity.ui_language or await ui_language(state, deps)
    gate = deps.terms
    standing = await terms_standing(deps, callback.from_user.id)
    await present(
        callback,
        terms_full_screen(
            language,
            version=gate.versions.label if gate is not None else "",
            is_accept_offered=gate is not None and standing is not TermsStanding.ACCEPTED,
        ),
    )


async def handle_terms_reprompt_message(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Anything typed on the Terms step. Declining is just not accepting: the screen repeats.

    It matches a mistyped command too — the real ones are claimed by ``commands`` and ``start``
    above this router — and answers it with the question actually being asked, as the contact
    step does.
    """
    _LOG.info("no answer at the terms step", extra={"content_type": message.content_type})
    await _repeat_or_move_on(message, state, deps)


async def handle_terms_reprompt_callback(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps
) -> None:
    """A stale button on the Terms step. Answered first, so the client's spinner stops."""
    await callback.answer(translate(TERMS_REQUIRED_KEY, await ui_language(state, deps)))
    _LOG.info("an unmatched button at the terms step", extra={"data": callback.data})
    await _repeat_or_move_on(callback, state, deps)


async def _repeat_or_move_on(
    event: Message | CallbackQuery, state: FSMContext, deps: BotDeps
) -> None:
    """Repeat the Terms; or, when the gate was switched off under a parked customer, move on.

    The second branch keeps a customer from being stranded on a step whose only button now
    records nothing: with no gate they belong on the contact screen, which is where onboarding
    without the gate always went next.
    """
    language = await ui_language(state, deps)
    if deps.terms is None:
        await state.set_state(Onboarding.contact)
        await present(event, onboarding_contact_screen(language))
        return
    await present_terms(event, deps, language, is_repeat=True)


def register(router: Router) -> None:
    """Put the Terms handlers on ``router`` — the onboarding router, before anything else on it.

    The two ``trm:*`` registrations first and with no state filter; the two ``Onboarding.terms``
    registrations after them, so a ✅ pressed on the step is an acceptance and not a repeat.
    """
    router.callback_query.register(
        handle_terms_accept, TermsCB.filter(F.action == TermsAction.ACCEPT)
    )
    router.callback_query.register(
        handle_terms_read_full, TermsCB.filter(F.action == TermsAction.READ_FULL)
    )
    router.message.register(handle_terms_reprompt_message, Onboarding.terms)
    router.callback_query.register(handle_terms_reprompt_callback, Onboarding.terms)
