"""Helpers every handler uses: read the draft, write the draft, put a screen up.

Navigation lives here rather than in each handler, so "go to step X" is one code path.
That is what makes Back work at every step: Back is not a special case, it is
``show_step(event, state, draft, previous_step(current))``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from uuid import uuid4

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bayram.bot.deps import BotDeps
from bayram.bot.draft import ONBOARDED_KEY, UI_LANGUAGE_KEY, WizardDraft, load_draft
from bayram.bot.i18n import FALLBACK_LANGUAGE, translate
from bayram.bot.keyboards import MENU_LABELS, start_over_keyboard
from bayram.bot.middleware import resolve_language_or_none
from bayram.bot.pricing import CheckoutOffer
from bayram.bot.screens import Screen, render_step, resolve_step
from bayram.bot.states import WizardStep, state_for
from bayram.contracts import Err, Language
from bayram.errors import BayramError
from bayram.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - a type-only import; see below for why it is one.
    # This module is what ``bayram.bot.gate`` reaches into for ``COMMAND_PREFIX``, and it must
    # not be the module that first pulls SQLAlchemy into the middleware's own import chain.
    # The obvious justification — "the bot does not import ``bayram.db``" — is simply false:
    # ``handlers/commands.py`` imports ``bayram.db.retention`` at runtime and is imported by
    # ``handlers/__init__.py``, and ``handlers/menu.py`` does the same. The point is not
    # whether the dependency exists but WHERE it enters: it should arrive through the
    # handler that uses a retention policy, never through the shared helper that everything
    # in the package — including a middleware that runs before any handler is chosen —
    # imports. ``from __future__ import annotations`` makes the annotation a string, so the
    # guard costs nothing at all.
    from bayram.db.retention import RetentionPolicy

__all__ = [
    "Event",
    "COMMAND_PREFIX",
    "read_draft",
    "write_draft",
    "show_step",
    "present",
    "say",
    "clear_keeping_identity",
    "finish_with",
    "expire",
    "reset_to_welcome",
    "is_menu_label",
    "ui_language",
    "error_text",
    "support_text",
    "privacy_text",
]

_LOG = get_logger(__name__)

#: The two update kinds this wizard accepts. Everything else the fallback handles.
type Event = Message | CallbackQuery

#: What every Telegram command starts with.
#:
#: Two steps accept free text — the note and the pasted lyric — and both are bound to ANY
#: text in their state, so a command nothing else claimed reaches them and is stored
#: verbatim as the customer's answer. ``/help`` typed at the note step became the fact we
#: knew about someone's mother, and was sung to her. The known commands are claimed by the
#: routers registered ahead of the steps; this guard is for the rest, because ``/halp``
#: matches no filter at all. It lives here rather than in either handler so the two cannot
#: disagree about what a command looks like.
COMMAND_PREFIX: Final[str] = "/"


async def read_draft(state: FSMContext) -> WizardDraft | None:
    """The current draft, or ``None`` when the session is gone or unreadable."""
    data = await state.get_data()
    result = load_draft(data)
    if isinstance(result, Err):
        _LOG.info("wizard draft unavailable", extra=result.error.to_log_dict())
        return None
    return result.value


async def write_draft(state: FSMContext, draft: WizardDraft) -> None:
    await state.update_data(**draft.to_state_data())


async def show_step(
    event: Event,
    state: FSMContext,
    draft: WizardDraft,
    step: WizardStep,
    *,
    credits_note: str | None = None,
    offer: CheckoutOffer | None = None,
) -> WizardStep:
    """Persist the draft, move the FSM to ``step`` and put its screen up.

    Returns the step actually shown, which can differ from ``step`` when the draft is not
    complete enough to render it.

    ``resolve_step`` downgrades by one rule at a time, and one downgrade is not always
    enough: a summary whose lyric was never approved resolves to the preview, and a preview
    with no lyric in it resolves further to the language question. Stopping after the first
    rule would set the FSM to ``Wizard.lyrics`` and then render the language picker, whose
    buttons are filtered to ``Wizard.output_language`` — a screen whose every button is
    dead. So the downgrade runs to a fixpoint. It terminates because every rule moves
    strictly earlier in ``WIZARD_ORDER``.

    ``credits_note`` is passed straight through to :func:`~bayram.bot.screens.render_step`,
    which uses it on the Confirm screen and ignores it everywhere else — including when the
    downgrade above lands somewhere other than the step the caller asked for. Callers reach
    for ``handlers.balance.show_confirm`` rather than filling this in by hand; the parameter
    exists so that the meter is never read inside a pure rendering function.

    ``offer`` is passed through on exactly the same terms, and for exactly the same reason:
    deciding whether to paywall means reading the meter and holding two ports this function
    does not have, so the decision belongs to ``handlers.balance.build_offer`` and only its
    finished answer arrives here. Nothing else about this function moves for it — the
    fixpoint downgrade and the write-draft / set-state / present ordering are untouched,
    because the checkout is the Confirm screen wearing a second face and not a new step.
    """
    shown = resolve_step(step, draft)
    while (further := resolve_step(shown, draft)) is not shown:
        shown = further
    await write_draft(state, draft)
    await state.set_state(state_for(shown))
    await present(event, render_step(shown, draft, credits_note=credits_note, offer=offer))
    return shown


async def present(event: Event, screen: Screen) -> None:
    """Edit in place when we came from a button; send a new message otherwise."""
    if isinstance(event, CallbackQuery):
        await _edit_or_send(event, screen)
        return
    await event.answer(screen.text, reply_markup=screen.markup)


async def say(event: Event, text: str) -> None:
    """Send one plain sentence without disturbing the screen the user is on."""
    if isinstance(event, CallbackQuery):
        if isinstance(event.message, Message):
            await event.message.answer(text)
        return
    await event.answer(text)


#: Telegram's own words for "this edit would change nothing". Matched as a lower-cased
#: SUBSTRING because there is no machine-readable signal: Telegram returns no error code for
#: it, and aiogram maps every 400 that is not ``retry_after``/``migrate_to_chat_id`` onto a
#: bare ``TelegramBadRequest`` carrying only the description string. A substring survives a
#: prefix change (``"Bad Request: "``) and a lengthened tail, both of which have moved before.
#:
#: **The failure direction is the safe one, and that is the whole reason a prose match is
#: acceptable here.** Bot API descriptions are English whatever language the customer is
#: being spoken to in, so this is not a localisation hazard; and if Telegram ever rewords it
#: entirely, this predicate answers ``False`` and the behaviour degrades to exactly what
#: shipped before it existed — one duplicate message — never to a crash and never to a
#: screen that failed to draw. Nothing would go red, and that is the honest cost of matching
#: on prose: it is written down here rather than discovered later.
_UNCHANGED_MESSAGE: Final[str] = "message is not modified"


def _is_unchanged(exc: TelegramBadRequest) -> bool:
    """Whether Telegram refused an edit because the screen already reads that way."""
    return _UNCHANGED_MESSAGE in (exc.message or "").lower()


async def _edit_or_send(callback: CallbackQuery, screen: Screen) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    if screen.markup is not None and not isinstance(screen.markup, InlineKeyboardMarkup):
        # A reply keyboard cannot be attached by an edit: Telegram's ``editMessageText``
        # accepts inline markup only and answers 400 for anything else. ``RecordingSession``
        # returns a canned ``Message`` for every method name, so this would be a live failure
        # no unit test in this repo could ever see. Send instead — which is also the right
        # UX: the reply keyboard is chat-level state and belongs on a new message, not
        # bolted onto an old one the customer has already scrolled past.
        await message.answer(screen.text, reply_markup=screen.markup)
        return
    try:
        await message.edit_text(screen.text, reply_markup=screen.markup)
    except TelegramBadRequest as exc:
        if _is_unchanged(exc):
            # The message ALREADY reads exactly as we were about to draw it, so there is
            # nothing to do and sending is not a fallback — it is a CLONE. This branch used
            # to send anyway, and on the checkout screen the clone carried a LIVE price
            # button underneath a payment link the customer had not paid yet: one press of
            # 💳 produced the link message and a second paywall below it. The correct
            # redraw of an idempotent redraw is no redraw.
            _LOG.debug(
                "the screen already reads as we would have drawn it; nothing to edit",
                extra={"failure": repr(exc)},
            )
            return
        # A message too old to edit, or one that is no longer ours. Send.
        _LOG.info("could not edit in place, sending a new message", extra={"failure": repr(exc)})
        await message.answer(screen.text, reply_markup=screen.markup)


async def clear_keeping_identity(state: FSMContext) -> None:
    """Throw the session away, but not the two facts that are not part of a session.

    ``FSMContext.clear()`` wipes the data dict wholesale, and two of the keys in it are not
    wizard state at all: ``UI_LANGUAGE_KEY`` is which language to speak, and ``ONBOARDED_KEY``
    is whether we have already asked for a phone number. Clearing those on every cancellation,
    expiry and flow end had two costs, both of which this repo has paid before in other
    shapes. The catch-all filter went back to the database on essentially every idle update —
    inside aiogram's FSM isolation lock — and a returning Russian speaker was answered in
    Uzbek Latin from the first message after any completed flow, because the language had
    nowhere to live between drafts.

    Both keys are CACHES. ``user_profiles`` is the truth, and a cache that is missing costs
    one read, so losing them to a Redis TTL or to the worker's post-delivery wipe
    (``runtime/jobs.py``) is a slow path and never a wrong answer.

    **The five callers**, derived with ``grep -rn "state.clear()" src`` rather than from
    memory, because two of them were missed by the specification that asked for this helper:
    :func:`finish_with` and :func:`reset_to_welcome` here, the entitlement refusal in
    ``handlers.confirm``, the lyric-budget exhaustion in ``handlers.lyrics``, and the end of
    onboarding in ``handlers.onboarding``. The confirm one in particular is not cosmetic: a
    customer refused for credits would otherwise lose their language permanently on a
    deployment with no profile store, and pay an extra read on one that has one.

    ``handlers.commands.handle_forget`` is the deliberate sixth and does NOT call this: it
    keeps a bare ``state.clear()``, because it is the one operation whose whole purpose is to
    return the account to first-contact state, with both questions asked again.
    """
    data = await state.get_data()
    kept = {key: data[key] for key in (UI_LANGUAGE_KEY, ONBOARDED_KEY) if key in data}
    await state.clear()
    if kept:
        await state.update_data(kept)


async def finish_with(event: Event, state: FSMContext, key: str) -> None:
    """Clear the session and say one localised sentence, with a way back in.

    The keyboard is not decoration. This is the last screen of a flow, and until it carried
    one the only exit was a ``/start`` the user had to know about and type — which is the
    shape of a message people abandon. ``start_over_keyboard`` turns the sentence into
    something tappable without changing what it says.

    The clear keeps the customer's identity (:func:`clear_keeping_identity`), which is what
    makes this sentence and the next screen they see agree about what language to be in. A
    bare clear here used to answer "cancelled" in Russian and then greet them in Uzbek Latin
    the moment they tapped the button underneath it.
    """
    draft = await read_draft(state)
    language = draft.ui_language if draft is not None else FALLBACK_LANGUAGE
    await clear_keeping_identity(state)
    await present(
        event, Screen(text=translate(key, language), markup=start_over_keyboard(language))
    )


async def expire(event: Event, state: FSMContext) -> None:
    """The draft is gone. Say so plainly and let the user restart."""
    await finish_with(event, state, "wizard.expired")


async def reset_to_welcome(event: Event, state: FSMContext, deps: BotDeps) -> None:
    """Throw the session away and start a new song. A clean slate, every time.

    **Three entry points, and they are no longer the three this used to have.** They are
    🎵 Make a song on the persistent menu, the ↩️ Start-over button on a dead-end screen, and
    🎂 Make another on the closing message. ``/start`` has left the list: a returning customer
    who types it gets the MENU, not a wizard, because a customer who has already told us their
    language and their number must never be asked a question again to reach the thing they
    came for. The fallback has left it too: a first message from someone with no session at
    all is now the onboarding router's, and answering it with the occasion picker would
    quietly skip both onboarding questions. Everything still funnels through this one function
    so that "begin a song" is one code path rather than three that drift.

    **The first screen is** :attr:`~bayram.bot.states.WizardStep.OCCASION`. The interface language
    has left both step orders: it is asked once, at onboarding, and changed from ⚙️ Settings
    thereafter, so opening a wizard with the language picker would re-ask a settled question
    at the top of every song.

    **The language is seeded from the FSM cache** that :func:`clear_keeping_identity` above
    has just preserved, and only then from ``deps.settings.default_ui_language``. Reading it
    from ``deps.profiles`` here was considered and rejected twice over: this function does not
    hold a ``telegram_user_id`` on every path it is called from, and whoever routed the
    customer here has already paid for that read — a second one inside the FSM isolation lock
    would buy nothing.

    The new draft is stamped with a fresh ``session_id``. That stamp is what makes two
    identical runs two different orders — see :attr:`~bayram.bot.draft.WizardDraft.session_id`
    — so it is minted exactly here, at the one place a run begins, and nowhere a step could
    re-mint it mid-wizard and break the double-tap collision it also has to preserve.
    """
    await clear_keeping_identity(state)
    draft = WizardDraft(session_id=uuid4().hex, ui_language=await ui_language(state, deps))
    await show_step(event, state, draft, WizardStep.OCCASION)


def is_menu_label(text: str) -> bool:
    """True when this text is a button on the persistent reply keyboard, in ANY language.

    The reply keyboard is chat-level state Telegram keeps pinned, so its labels arrive as
    ordinary text messages and land on exactly the steps that accept any text — the note
    about the recipient, the recipient's name, and the pasted lyric. The router order is what
    normally keeps them apart, and the router order is one line in ``handlers/__init__``: this
    is the second brace, and it lives here rather than in each of the three handlers so they
    cannot disagree about what a label looks like. The failure it guards is not cosmetic — a
    menu label written into ``draft.note`` is SUNG TO A REAL PERSON, which is the same shape
    as the ``/help``-at-the-note-step incident ``COMMAND_PREFIX`` above exists for.

    ``MENU_LABELS`` spans all four catalogues because a customer who switches language keeps
    the old keyboard pinned client-side until the next message re-sends it, so a press can
    arrive in a language the account no longer reads.
    """
    return text.strip() in MENU_LABELS


async def ui_language(state: FSMContext, deps: BotDeps) -> Language:
    """The language to speak in, for a handler that holds ``deps``.

    Identical to ``middleware.resolve_language`` except in the last resort: this one falls
    back to ``deps.settings.default_ui_language`` rather than to the module constant. That
    matters in exactly one configuration and it is a shipped one — a deployment with no
    profile store wired at all, where nothing has ever written a language and the operator's
    configured default is the only real answer anywhere in the process.
    ``resolve_language`` keeps the module constant because the gate and the error guard hold
    no ``deps`` and must still be able to say something.
    """
    return await resolve_language_or_none(state) or deps.settings.default_ui_language


def support_text(language: Language, contact: str) -> str:
    """Where to report a song that came out wrong, said the same way everywhere.

    Two surfaces render this — the ``/support`` command and the Report-a-problem button on
    the closing message — and a customer who tries both must not be given two different
    routes to the same inbox, so the branch lives here rather than twice.

    With no contact configured the COPY changes and the destination is never faked: naming
    an address nobody reads would leave someone believing they had reported the problem.
    ``support.no_contact`` asks them to describe it in this chat instead. Neither template
    promises a reply time nobody has committed to.
    """
    trimmed = contact.strip()
    if not trimmed:
        _LOG.warning("support contact is not configured; pointing the customer at this chat")
        return translate("support.no_contact", language)
    return translate("support.text", language, contact=trimmed)


def privacy_text(language: Language, policy: RetentionPolicy) -> str:
    """The retention notice, said the same way from both surfaces that offer it.

    Two surfaces render it — the ``/privacy`` command and the 🔒 button on the Settings
    screen — and ``handle_privacy`` could not be one of them while it took a ``Message`` and
    interpolated four periods inline: a ``CallbackQuery`` handler in ``handlers/menu.py``
    cannot call it, so the alternative was a second copy of the four kwargs, drifting from the
    first the moment a period changed. ``support_text`` was extracted for exactly this reason
    and this follows it.

    The periods are read from the policy rather than written into the catalogues, which is
    what makes the notice provably true: shortening a period in
    :class:`~bayram.db.retention.RetentionPolicy` changes this message in the same commit. The
    module's own rule — a notice that says thirty days while the job runs sixty is worse than
    no notice — is the reason.

    **Four kwargs and no fifth.** ``privacy.text``'s placeholder set is fixed by
    ``tests/test_bot/test_i18n.py``, which asserts placeholder-set equality across the four
    catalogues; a fifth kwarg with no matching placeholder would be silently dropped by
    ``i18n._SafeParams`` and would read, to whoever added it, as a period that simply never
    appeared.
    """
    return translate(
        "privacy.text",
        language,
        recipient_identity_days=policy.recipient_identity_days,
        brief_text_days=policy.brief_text_days,
        paid_audio_days=policy.paid_audio_days,
        abandoned_draft_days=policy.abandoned_draft_days,
    )


def error_text(error: BayramError, language: Language) -> str:
    """Render an error the way the customer should read it.

    Scalar values from the error's context are passed through as template parameters, so a
    message like "keep it under {limit} characters" gets its number from the error that
    knew it, and a template that does not use them is unaffected.
    """
    params = {
        name: value
        for name, value in error.context.items()
        if isinstance(value, str | int | float | bool)
    }
    return translate(error.user_message_key, language, **params)
