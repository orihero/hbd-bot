"""Screens are pure functions of the draft, so they are tested as pure functions."""

from __future__ import annotations

import pytest

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.draft import WizardDraft
from hbd.bot.screens import render_step, resolve_step, welcome_screen
from hbd.bot.states import WIZARD_ORDER, WizardStep
from hbd.contracts import Genre, Language, Occasion, VoiceGender
from tests.conftest import UZBEK_NAME_CANONICAL, make_name
from tests.test_bot.conftest import buttons


def full_draft(**overrides: object) -> WizardDraft:
    base = WizardDraft(
        ui_language=Language.EN,
        occasion=Occasion.ANNIVERSARY,
        genre=Genre.JAZZ_LOUNGE,
        vocal_gender=VoiceGender.DUET,
        note="Adores late-night jazz",
        recipient=make_name(),
        output_language=Language.RU,
    )
    return base.updated(**overrides) if overrides else base


@pytest.mark.parametrize("step", list(WIZARD_ORDER))
def test_every_step_renders_non_empty_text(step: WizardStep) -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(step, draft)

    # Assert
    assert screen.text.strip()


@pytest.mark.parametrize("step", [s for s in WIZARD_ORDER if s is not WizardStep.UI_LANGUAGE])
def test_every_step_after_the_first_draws_a_back_button(step: WizardStep) -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(step, draft)

    # Assert
    assert NavCB(action=NavAction.BACK).pack() in {d for _, d in buttons(screen.markup)}


def test_the_first_step_has_no_back_button() -> None:
    # Arrange / Act
    screen = welcome_screen(Language.EN)

    # Assert
    assert NavCB(action=NavAction.BACK).pack() not in {d for _, d in buttons(screen.markup)}


@pytest.mark.parametrize("step", list(WIZARD_ORDER))
def test_every_step_can_be_cancelled(step: WizardStep) -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(step, draft)

    # Assert
    assert NavCB(action=NavAction.CANCEL).pack() in {d for _, d in buttons(screen.markup)}


def test_only_the_note_step_offers_skip() -> None:
    # Arrange
    draft = full_draft()
    skip = NavCB(action=NavAction.SKIP).pack()

    # Act
    with_skip = {
        step for step in WIZARD_ORDER if skip in {d for _, d in buttons(render_step(step, draft).markup)}
    }

    # Assert
    assert with_skip == {WizardStep.NOTE}


def test_text_is_expected_only_on_the_note_and_name_steps() -> None:
    # Arrange
    draft = full_draft()

    # Act
    typing_steps = {step for step in WIZARD_ORDER if render_step(step, draft).is_text_expected}

    # Assert
    assert typing_steps == {WizardStep.NOTE, WizardStep.NAME}


def test_name_confirmation_shows_the_display_spelling() -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(WizardStep.NAME_CONFIRM, draft)

    # Assert
    assert UZBEK_NAME_CANONICAL in screen.text


def test_name_confirmation_never_shows_a_submitted_candidate() -> None:
    # Arrange
    draft = full_draft()
    submitted = [
        candidate.text
        for candidate in draft.recipient.candidates  # type: ignore[union-attr]
        if candidate.text != UZBEK_NAME_CANONICAL
    ]

    # Act
    screen = render_step(WizardStep.NAME_CONFIRM, draft)

    # Assert
    for spelling in submitted:
        assert spelling not in screen.text


def test_summary_renders_an_empty_note_as_a_dash() -> None:
    # Arrange
    draft = full_draft(note="")

    # Act
    screen = render_step(WizardStep.CONFIRM, draft)

    # Assert
    assert "—" in screen.text


def test_summary_escapes_a_hostile_note() -> None:
    # Arrange
    draft = full_draft(note="<script>alert(1)</script>")

    # Act
    screen = render_step(WizardStep.CONFIRM, draft)

    # Assert
    assert "<script>" not in screen.text
    assert "&lt;script&gt;" in screen.text


def test_resolve_step_downgrades_a_confirmation_with_no_name() -> None:
    # Arrange
    draft = full_draft(recipient=None)

    # Act / Assert
    assert resolve_step(WizardStep.NAME_CONFIRM, draft) is WizardStep.NAME
    assert resolve_step(WizardStep.CONFIRM, draft) is WizardStep.NAME


def test_resolve_step_downgrades_a_summary_with_no_output_language() -> None:
    # Arrange
    draft = full_draft(output_language=None)

    # Act / Assert
    assert resolve_step(WizardStep.CONFIRM, draft) is WizardStep.OUTPUT_LANGUAGE


def test_resolve_step_leaves_a_renderable_step_alone() -> None:
    # Arrange
    draft = full_draft()

    # Act / Assert
    for step in WIZARD_ORDER:
        assert resolve_step(step, draft) is step
