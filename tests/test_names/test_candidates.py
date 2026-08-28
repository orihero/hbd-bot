
# Latin ones are the SUBJECT of this module, not a typo in it.
"""Candidate generation — and the guarantee that the RANKING comes from configuration."""

from __future__ import annotations

import pytest

from hbd.config import DEFAULT_NAME_CANDIDATE_ORDER, Settings
from hbd.contracts import MAX_CANDIDATE_CHARS, Language, NameStrategy, RecipientName, Script
from hbd.names.candidates import build_candidates, derive_submit_form
from hbd.names.forms import DisplayForm

GULOMJON = DisplayForm(text="Gʻulomjon")

EXPECTED_TEXT = {
    NameStrategy.CANONICAL: "Gʻulomjon",
    NameStrategy.STRIPPED: "Gulomjon",
    NameStrategy.ASCII: "G'ulomjon",
    NameStrategy.CYRILLIC: "Ғуломжон",
    NameStrategy.HYPHENATED: "Gu-lom-jon",
    NameStrategy.PHONETIC: "Ghoolomjon",
}


@pytest.mark.parametrize("strategy", list(NameStrategy))
def test_every_strategy_derives_its_documented_spelling(strategy: NameStrategy) -> None:
    # Act
    form = derive_submit_form(GULOMJON, strategy, language=Language.UZ_LATN)

    # Assert
    assert form is not None
    assert form.text == EXPECTED_TEXT[strategy]
    assert form.strategy is strategy


def test_the_candidate_order_comes_from_the_caller_not_from_the_module() -> None:
    # Arrange — a bake-off result is applied by reordering configuration, nothing else
    order = (NameStrategy.PHONETIC, NameStrategy.CYRILLIC, NameStrategy.CANONICAL)

    # Act
    candidates = build_candidates(GULOMJON, order=order, language=Language.UZ_LATN)

    # Assert
    assert [candidate.strategy for candidate in candidates] == list(order)


def test_reversing_the_configured_order_reverses_the_ranks() -> None:
    # Arrange
    forward = (NameStrategy.STRIPPED, NameStrategy.CANONICAL, NameStrategy.PHONETIC)
    backward = tuple(reversed(forward))

    # Act
    first = build_candidates(GULOMJON, order=forward, language=Language.UZ_LATN)
    second = build_candidates(GULOMJON, order=backward, language=Language.UZ_LATN)

    # Assert
    assert [candidate.text for candidate in first] == list(
        reversed([candidate.text for candidate in second])
    )


def test_the_default_configured_order_is_honoured_verbatim() -> None:
    # Arrange — the shipped default, read from config rather than restated here
    settings = Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url="d",
        elevenlabs_api_key="e",
        llm_api_key="l",
    )

    # Act
    candidates = build_candidates(
        GULOMJON, order=settings.name_candidate_order, language=Language.UZ_LATN
    )

    # Assert
    assert [candidate.strategy for candidate in candidates] == list(DEFAULT_NAME_CANDIDATE_ORDER)


def test_ranks_are_dense_and_start_at_zero() -> None:
    # Act
    candidates = build_candidates(
        GULOMJON, order=DEFAULT_NAME_CANDIDATE_ORDER, language=Language.UZ_LATN
    )

    # Assert
    assert [candidate.rank for candidate in candidates] == list(range(len(candidates)))


def test_ranks_stay_dense_when_a_duplicate_is_dropped() -> None:
    # Arrange — Aziza has no mark, so STRIPPED and CANONICAL produce the same string
    aziza = DisplayForm(text="Aziza")
    order = (NameStrategy.STRIPPED, NameStrategy.CANONICAL, NameStrategy.HYPHENATED)

    # Act
    candidates = build_candidates(aziza, order=order, language=Language.UZ_LATN)

    # Assert
    assert [candidate.rank for candidate in candidates] == [0, 1]
    assert [candidate.strategy for candidate in candidates] == [
        NameStrategy.STRIPPED,
        NameStrategy.HYPHENATED,
    ]


def test_the_result_is_accepted_by_the_frozen_contract_model() -> None:
    # Arrange — RecipientName validates that ranks are 0..n-1 in order
    candidates = build_candidates(
        GULOMJON, order=DEFAULT_NAME_CANDIDATE_ORDER, language=Language.UZ_LATN
    )

    # Act
    name = RecipientName(
        raw="Gʻulomjon",
        display="Gʻulomjon",
        lookup_key="gulomjon",
        script=Script.LATIN,
        language=Language.UZ_LATN,
        candidates=candidates,
    )

    # Assert
    assert name.candidate_at(0) == candidates[0]


def test_a_duplicate_keeps_the_earlier_ranked_strategy() -> None:
    # Arrange
    aziza = DisplayForm(text="Aziza")

    # Act
    candidates = build_candidates(
        aziza,
        order=(NameStrategy.CANONICAL, NameStrategy.STRIPPED),
        language=Language.UZ_LATN,
    )

    # Assert
    assert len(candidates) == 1
    assert candidates[0].strategy is NameStrategy.CANONICAL


def test_a_candidate_over_the_vendor_length_limit_is_dropped() -> None:
    # Arrange — every i becomes "ee" and every u becomes "oo" in the respelling
    long_name = DisplayForm(text="i" * (MAX_CANDIDATE_CHARS // 2 + 1))

    # Act
    form = derive_submit_form(long_name, NameStrategy.PHONETIC, language=Language.UZ_LATN)

    # Assert
    assert form is None


def test_a_strategy_that_derives_nothing_yields_no_candidate() -> None:
    # Arrange — a display form that is nothing but the mark has no stripped spelling
    mark_only = DisplayForm(text="ʻ")

    # Act
    form = derive_submit_form(mark_only, NameStrategy.STRIPPED, language=Language.UZ_LATN)

    # Assert
    assert form is None


def test_an_empty_order_still_yields_one_usable_candidate() -> None:
    # Arrange — a misconfiguration must not leave the pipeline with nothing to submit
    candidates = build_candidates(GULOMJON, order=(), language=Language.UZ_LATN)

    # Assert
    assert len(candidates) == 1
    assert candidates[0].text == "Gʻulomjon"
    assert candidates[0].rank == 0


def test_a_cyrillic_name_hyphenates_in_its_own_script() -> None:
    # Arrange
    alyona = DisplayForm(text="Алёна")

    # Act
    form = derive_submit_form(alyona, NameStrategy.HYPHENATED, language=Language.RU)

    # Assert
    assert form is not None
    assert form.text == "А-лё-на"


def test_a_cyrillic_name_produces_a_latin_ascii_candidate() -> None:
    # Arrange
    alyona = DisplayForm(text="Алёна")

    # Act
    form = derive_submit_form(alyona, NameStrategy.ASCII, language=Language.RU)

    # Assert
    assert form is not None
    assert form.text == "Alyona"


def test_the_hyphenated_candidate_never_mixes_a_hyphen_with_the_turned_comma() -> None:
    # Arrange — two separator-shaped characters in one string is what the model trips on
    form = derive_submit_form(GULOMJON, NameStrategy.HYPHENATED, language=Language.UZ_LATN)

    # Assert
    assert form is not None
    assert "ʻ" not in form.text
