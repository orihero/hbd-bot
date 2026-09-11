"""The wizard's step order, and the aiogram FSM states that mirror it.

The ORDER is the single source of truth for "what comes before this" and "what comes
next". Back is implemented from it, and so is every handler's forward move, so a step
inserted here gets working navigation in both directions for free and there is no second
list to keep in sync.

There are two orders, because there are two products behind one wizard.

:data:`WIZARD_ORDER` is the bot writing a song for a named person: four structured
questions, a note about them, their name, and the language it is sung in — and the name is
asked for because the name being pronounced correctly IS the product.

:data:`OWN_LYRICS_ORDER` is the customer writing the song. It asks for the words
immediately, second screen, and then asks only what is still genuinely unanswered: the
genre and the voice, which shape the music rather than the text, and the language. The
three steps it drops are dropped because they have stopped meaning anything:

* **NOTE** existed to feed the lyric writer ("tell me one thing about them — I write it
  into the words"). Nothing writes the words now, so the question is a promise the bot
  cannot keep.
* **NAME** and **NAME_CONFIRM** existed to put the recipient's name into a hook section and
  verify its pronunciation acoustically. A customer who wrote their own lyric already put
  whatever name they wanted where they wanted it, and a name we asked for separately would
  be woven into their words on top of that — so the whole name subsystem is skipped for
  these orders, all the way down to ``Brief.recipient`` being ``None``.

Both orders start at OCCASION and end at CONFIRM, and every step in the shorter one
appears in the longer one, which is what lets one set of handlers serve both.

The interface language used to be the first step of both. It is not a step any more: it is
asked once, at first contact, by :class:`Onboarding`, because a customer who has already
told us which language to speak should not be asked again at the top of every wizard run.
:data:`WizardStep.UI_LANGUAGE` survives that move — see :data:`PARKED_ONLY_STEPS` for the
only two things it still buys and for why deleting it would be worse than keeping it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from aiogram.fsm.state import State, StatesGroup

__all__ = [
    "WizardStep",
    "Wizard",
    "Onboarding",
    "WIZARD_ORDER",
    "OWN_LYRICS_ORDER",
    "PARKED_ONLY_STEPS",
    "order_for",
    "previous_step",
    "next_step",
    "state_for",
    "step_for_state",
]


class WizardStep(StrEnum):
    """One screen of the intake wizard."""

    #: No longer a screen of any run. It is in neither order and it is kept for the two
    #: reasons :data:`PARKED_ONLY_STEPS` sets out — do not delete it, and do not read it as
    #: evidence that a customer is ever sent here.
    UI_LANGUAGE = "ui_language"
    OCCASION = "occasion"
    GENRE = "genre"
    VOCAL_GENDER = "vocal_gender"
    NOTE = "note"
    NAME = "name"
    NAME_CONFIRM = "name_confirm"
    OUTPUT_LANGUAGE = "output_language"
    LYRICS = "lyrics"
    CONFIRM = "confirm"


class Wizard(StatesGroup):
    """aiogram states, one per :class:`WizardStep`, plus a terminal submitting state."""

    ui_language = State()
    occasion = State()
    genre = State()
    vocal_gender = State()
    note = State()
    name = State()
    name_confirm = State()
    output_language = State()
    lyrics = State()
    confirm = State()
    submitting = State()


class Onboarding(StatesGroup):
    """First contact: which language to speak, and the phone number. NOT wizard steps.

    These two screens are deliberately a separate :class:`StatesGroup` rather than two more
    members of :class:`Wizard`, and the reason is that everything in this module treats a
    ``Wizard`` member as a step of an order. :data:`_STATE_BY_STEP` maps a step to a state
    and :func:`state_for` reads it as an UNDEFAULTED dict lookup, so a state with no step
    behind it is a ``KeyError`` in a handler rather than a screen; :func:`step_for_state`
    would answer ``None`` for these two and the navigation router would read that as "not in
    a wizard"; ``screens.render_step``'s ``match`` is total over :class:`WizardStep` and
    would need two arms for screens that have no draft to render from; and
    ``test_navigation`` pins the enum and the order against each other, so a member added
    here without a place in an order fails the build. Onboarding is not a step of the
    wizard. It is the thing that has to have happened before the wizard is offered at all,
    which is exactly why it is reached from its own router and its own catch-all.

    There is deliberately no ``Settings`` group beside it. The settings submenu is
    reachable from the persistent menu keyboard at any moment, including halfway through a
    wizard run, and a screen that set its own FSM state would overwrite the ``Wizard.*``
    state a half-finished draft is parked in — losing the draft to a customer who only
    wanted to change their language. Settings is therefore stateless callbacks, and which
    picker a ``LanguageCB`` came from is carried in its payload (``LanguageSlot.SETTINGS``)
    rather than inferred from the state.
    """

    language = State()
    contact = State()


WIZARD_ORDER: Final[tuple[WizardStep, ...]] = (
    WizardStep.OCCASION,
    WizardStep.GENRE,
    WizardStep.VOCAL_GENDER,
    WizardStep.NOTE,
    WizardStep.NAME,
    WizardStep.NAME_CONFIRM,
    WizardStep.OUTPUT_LANGUAGE,
    WizardStep.LYRICS,
    WizardStep.CONFIRM,
)

#: The bring-your-own-lyrics order. See the module docstring for what it drops and why.
#:
#: LYRICS sits SECOND, before the genre and before the language, which is the point: the
#: customer said they had the words, so the very next thing asked for is the words. The
#: lyric is built with the interface language as a provisional tag and re-tagged when the
#: output language is finally chosen — see ``handlers.lyrics._relabelled_for`` — because the
#: alternative is to hold raw text on the draft and delay the preview to the end of the
#: wizard, which would put the one screen the customer came for last.
OWN_LYRICS_ORDER: Final[tuple[WizardStep, ...]] = (
    WizardStep.OCCASION,
    WizardStep.LYRICS,
    WizardStep.GENRE,
    WizardStep.VOCAL_GENDER,
    WizardStep.OUTPUT_LANGUAGE,
    WizardStep.CONFIRM,
)

#: Steps that no longer belong to either order but whose STATE must still resolve.
#:
#: There is exactly one, and it is :attr:`WizardStep.UI_LANGUAGE`. The interface language is
#: asked once, at first contact, by :class:`Onboarding`; it stopped being a wizard step and
#: left both orders above. The enum member, ``Wizard.ui_language``, its
#: :data:`_STATE_BY_STEP` entry and ``screens.render_step``'s arm for it all survive anyway,
#: and it is worth being precise about what that buys, because it is NOT a live screen.
#:
#: It buys two things, both true. ``bayram.bot.app`` gives the Redis storage
#: ``state_ttl=data_ttl=WIZARD_STATE_TTL`` — fourteen days, sized to
#: ``RetentionPolicy.abandoned_draft_days`` — so for two weeks after this deploys Redis
#: keeps handing back the state name ``Wizard:ui_language``, and :func:`step_for_state` must
#: resolve it to something rather than answering ``None`` and reporting an expired session
#: for a state the bot itself wrote. And ``render_step`` stays TOTAL over
#: :class:`WizardStep`, which is what mypy's exhaustive ``match`` checks and what stops a
#: forgotten arm becoming a runtime hole.
#:
#: It does NOT buy a customer a screen. There is no backfill of ``user_profiles``, so
#: everyone parked in ``Wizard:ui_language`` on deploy day has no profile row: their next
#: tap is claimed by the onboarding router's not-onboarded catch-all, which sits above
#: ``questions`` in the router order, and they are re-asked their language by
#: ``screens.onboarding_language_screen``. The parked draft — a session id and a default,
#: since UI_LANGUAGE was the FIRST step and nothing after it had been answered — is
#: discarded when onboarding ends. The one live reader of the arm is an already-onboarded
#: customer holding a stale Redis state.
#:
#: This constant exists so the exception is WRITTEN DOWN in the source rather than
#: subtracted inside a test: ``test_every_step_has_a_state_and_a_place_in_the_order``
#: asserts ``set(WIZARD_ORDER) | PARKED_ONLY_STEPS == set(WizardStep)``, which still fails
#: when a NEW step is forgotten from the order by accident — which a subset check, or a test
#: that simply subtracted this member, would quietly allow. No special case is needed in
#: :func:`previous_step` or :func:`next_step`, and a reader will look for one: both already
#: answer ``None`` for a step that is not in the order they were handed.
PARKED_ONLY_STEPS: Final[frozenset[WizardStep]] = frozenset({WizardStep.UI_LANGUAGE})

_STATE_BY_STEP: Final[dict[WizardStep, State]] = {
    WizardStep.UI_LANGUAGE: Wizard.ui_language,
    WizardStep.OCCASION: Wizard.occasion,
    WizardStep.GENRE: Wizard.genre,
    WizardStep.VOCAL_GENDER: Wizard.vocal_gender,
    WizardStep.NOTE: Wizard.note,
    WizardStep.NAME: Wizard.name,
    WizardStep.NAME_CONFIRM: Wizard.name_confirm,
    WizardStep.OUTPUT_LANGUAGE: Wizard.output_language,
    WizardStep.LYRICS: Wizard.lyrics,
    WizardStep.CONFIRM: Wizard.confirm,
}

_STEP_BY_STATE_NAME: Final[dict[str, WizardStep]] = {
    state.state: step for step, state in _STATE_BY_STEP.items() if state.state is not None
}


def order_for(*, is_own_lyrics: bool) -> tuple[WizardStep, ...]:
    """Which of the two orders this draft is walking.

    Takes a bool rather than the draft itself so this module keeps depending on nothing but
    aiogram and its own enum — ``bayram.bot.draft`` imports the contracts and the i18n
    catalogue, and a step list that needed those could not be read by a test that only
    wanted to know what follows what.
    """
    return OWN_LYRICS_ORDER if is_own_lyrics else WIZARD_ORDER


def previous_step(step: WizardStep, *, is_own_lyrics: bool = False) -> WizardStep | None:
    """The step Back returns to, or ``None`` at the first screen.

    A step that is not in this draft's order has no predecessor in it, and answering with
    one from the other order would send the customer to a screen their path never shows.
    ``None`` is the honest answer, and callers already treat it as "stay here" — which is
    what Back on the first screen has always done.
    """
    order = order_for(is_own_lyrics=is_own_lyrics)
    if step not in order:
        return None
    index = order.index(step)
    return order[index - 1] if index > 0 else None


def next_step(step: WizardStep, *, is_own_lyrics: bool = False) -> WizardStep | None:
    """The step that follows, or ``None`` at the last screen (or off this path)."""
    order = order_for(is_own_lyrics=is_own_lyrics)
    if step not in order:
        return None
    index = order.index(step)
    return order[index + 1] if index + 1 < len(order) else None


def state_for(step: WizardStep) -> State:
    return _STATE_BY_STEP[step]


def step_for_state(state_name: str | None) -> WizardStep | None:
    """Map a raw aiogram state name back to a step. ``None`` when it is not a wizard step."""
    if state_name is None:
        return None
    return _STEP_BY_STATE_NAME.get(state_name)
