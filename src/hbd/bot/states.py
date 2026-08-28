"""The wizard's step order, and the aiogram FSM states that mirror it.

``WIZARD_ORDER`` is the single source of truth for "what comes before this". The Back
button is implemented from it, so a step inserted here gets working navigation for free
and there is no second list to keep in sync.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from aiogram.fsm.state import State, StatesGroup

__all__ = [
    "WizardStep",
    "Wizard",
    "WIZARD_ORDER",
    "previous_step",
    "next_step",
    "state_for",
    "step_for_state",
]


class WizardStep(StrEnum):
    """One screen of the intake wizard."""

    UI_LANGUAGE = "ui_language"
    OCCASION = "occasion"
    GENRE = "genre"
    VOCAL_GENDER = "vocal_gender"
    NOTE = "note"
    NAME = "name"
    NAME_CONFIRM = "name_confirm"
    OUTPUT_LANGUAGE = "output_language"
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
    confirm = State()
    submitting = State()


WIZARD_ORDER: Final[tuple[WizardStep, ...]] = (
    WizardStep.UI_LANGUAGE,
    WizardStep.OCCASION,
    WizardStep.GENRE,
    WizardStep.VOCAL_GENDER,
    WizardStep.NOTE,
    WizardStep.NAME,
    WizardStep.NAME_CONFIRM,
    WizardStep.OUTPUT_LANGUAGE,
    WizardStep.CONFIRM,
)

_STATE_BY_STEP: Final[dict[WizardStep, State]] = {
    WizardStep.UI_LANGUAGE: Wizard.ui_language,
    WizardStep.OCCASION: Wizard.occasion,
    WizardStep.GENRE: Wizard.genre,
    WizardStep.VOCAL_GENDER: Wizard.vocal_gender,
    WizardStep.NOTE: Wizard.note,
    WizardStep.NAME: Wizard.name,
    WizardStep.NAME_CONFIRM: Wizard.name_confirm,
    WizardStep.OUTPUT_LANGUAGE: Wizard.output_language,
    WizardStep.CONFIRM: Wizard.confirm,
}

_STEP_BY_STATE_NAME: Final[dict[str, WizardStep]] = {
    state.state: step for step, state in _STATE_BY_STEP.items() if state.state is not None
}


def previous_step(step: WizardStep) -> WizardStep | None:
    """The step Back returns to, or ``None`` at the first screen."""
    index = WIZARD_ORDER.index(step)
    return WIZARD_ORDER[index - 1] if index > 0 else None


def next_step(step: WizardStep) -> WizardStep | None:
    """The step that follows, or ``None`` at the last screen."""
    index = WIZARD_ORDER.index(step)
    return WIZARD_ORDER[index + 1] if index + 1 < len(WIZARD_ORDER) else None


def state_for(step: WizardStep) -> State:
    return _STATE_BY_STEP[step]


def step_for_state(state_name: str | None) -> WizardStep | None:
    """Map a raw aiogram state name back to a step. ``None`` when it is not a wizard step."""
    if state_name is None:
        return None
    return _STEP_BY_STATE_NAME.get(state_name)
