"""The display/submit split — the one distinction the type system has to enforce."""

from __future__ import annotations

import dataclasses

import pytest

from hbd.contracts import MAX_CANDIDATE_CHARS, NameStrategy
from hbd.names.forms import DisplayForm, SubmitForm


def test_a_display_form_carries_the_canonical_spelling() -> None:
    assert DisplayForm(text="Gʻulomjon").text == "Gʻulomjon"


def test_a_submit_form_carries_its_strategy_alongside_the_text() -> None:
    # Arrange / Act
    form = SubmitForm(text="Ghoolomjon", strategy=NameStrategy.PHONETIC)

    # Assert
    assert form.text == "Ghoolomjon"
    assert form.strategy is NameStrategy.PHONETIC


def test_a_display_form_is_frozen() -> None:
    # Arrange
    form = DisplayForm(text="Gʻulomjon")

    # Act / Assert
    with pytest.raises(dataclasses.FrozenInstanceError):
        form.text = "Gulomjon"  # type: ignore[misc]


def test_a_submit_form_is_frozen() -> None:
    # Arrange
    form = SubmitForm(text="Gulomjon", strategy=NameStrategy.STRIPPED)

    # Act / Assert
    with pytest.raises(dataclasses.FrozenInstanceError):
        form.text = "Gʻulomjon"  # type: ignore[misc]


def test_the_two_forms_are_never_equal_even_with_identical_text() -> None:
    # Arrange — this is the whole point: same characters, different meanings.
    # The type: ignore comments below ARE the guarantee: under mypy --strict these two
    # comparisons are rejected as non-overlapping, so conflating the forms cannot compile.
    display = DisplayForm(text="Gulomjon")
    submit = SubmitForm(text="Gulomjon", strategy=NameStrategy.STRIPPED)

    # Assert
    assert display != submit  # type: ignore[comparison-overlap]
    assert not isinstance(display, type(submit))  # type: ignore[unreachable]


def test_neither_form_is_a_string_so_it_cannot_be_used_as_one_by_accident() -> None:
    # Arrange — an accidental f-string renders the repr, which is loud rather than silent
    display = DisplayForm(text="Gʻulomjon")

    # Assert
    assert not isinstance(display, str)  # type: ignore[unreachable]
    assert "DisplayForm" in f"{display}"


def test_an_empty_display_form_is_rejected() -> None:
    with pytest.raises(ValueError, match="visible character"):
        DisplayForm(text="   ")


def test_an_empty_submit_form_is_rejected_and_names_its_strategy() -> None:
    with pytest.raises(ValueError, match="phonetic"):
        SubmitForm(text="", strategy=NameStrategy.PHONETIC)


def test_a_submit_form_within_the_vendor_limit_reports_it() -> None:
    assert SubmitForm(text="Gulomjon", strategy=NameStrategy.STRIPPED).is_within_vendor_limit


def test_a_submit_form_over_the_vendor_limit_reports_it() -> None:
    # Arrange
    too_long = "a" * (MAX_CANDIDATE_CHARS + 1)

    # Act
    form = SubmitForm(text=too_long, strategy=NameStrategy.PHONETIC)

    # Assert
    assert form.is_within_vendor_limit is False


def test_as_candidate_projects_into_the_frozen_contract_model() -> None:
    # Arrange
    form = SubmitForm(text="Gu-lom-jon", strategy=NameStrategy.HYPHENATED)

    # Act
    candidate = form.as_candidate(2)

    # Assert
    assert candidate.text == "Gu-lom-jon"
    assert candidate.strategy is NameStrategy.HYPHENATED
    assert candidate.rank == 2
