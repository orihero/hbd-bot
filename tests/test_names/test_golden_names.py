"""The golden-set regression fence, wired as an ordinary pytest so it runs every commit.

Two kinds of assertion here, and the difference matters:

* the **frozen expectations** — display, script, language, lookup key and the full ranked
  candidate list for each of 77 real names. These catch drift.
* the **invariants** — properties that must hold for EVERY name, reviewed or not:
  the display form never leaks a raw keyboard apostrophe, every candidate still sounds like
  the name it was derived from, ranks are dense, and nothing exceeds a vendor limit. These
  catch a new name that nobody thought to add to the table.
"""

from __future__ import annotations

import pytest

from hbd.config import DEFAULT_NAME_CANDIDATE_ORDER
from hbd.contracts import (
    MAX_CANDIDATE_CHARS,
    MAX_RECIPIENT_NAME_CHARS,
    RecipientName,
    is_ok,
)
from hbd.names.marks import APOSTROPHE_VARIANTS, MODIFIER_APOSTROPHE, TURNED_COMMA
from hbd.names.matching import name_similarity
from hbd.names.resolve import resolve_name
from tests.test_names.golden_data import GOLDEN_NAMES, GoldenName

#: The threshold the pipeline ships with. A candidate that scores below it against its own
#: display form would be re-rolled forever, which means it was never a candidate at all.
MIN_SIMILARITY = 0.85

GOLDEN_PARAMS = [pytest.param(golden, id=golden.typed) for golden in GOLDEN_NAMES]


def _resolve(golden: GoldenName) -> RecipientName:
    result = resolve_name(
        golden.typed,
        candidate_order=DEFAULT_NAME_CANDIDATE_ORDER,
        ui_language=golden.ui_language,
    )
    assert is_ok(result), f"{golden.typed} failed to resolve"
    return result.value


def test_the_golden_set_is_large_enough_to_be_a_fence() -> None:
    assert len(GOLDEN_NAMES) >= 60


def test_the_golden_set_has_no_duplicate_entries() -> None:
    typed = [golden.typed for golden in GOLDEN_NAMES]
    assert len(set(typed)) == len(typed)


@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_display_form_matches_the_golden_set(golden: GoldenName) -> None:
    assert _resolve(golden).display == golden.display


@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_script_and_language_match_the_golden_set(golden: GoldenName) -> None:
    # Act
    name = _resolve(golden)

    # Assert
    assert name.script is golden.script
    assert name.language is golden.language


@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_lookup_key_matches_the_golden_set(golden: GoldenName) -> None:
    assert _resolve(golden).lookup_key == golden.lookup_key


@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_the_ranked_candidate_list_matches_the_golden_set(golden: GoldenName) -> None:
    # Act
    name = _resolve(golden)

    # Assert
    actual = tuple((candidate.strategy, candidate.text) for candidate in name.candidates)
    assert actual == golden.candidates


# ---------------------------------------------------------------------------
# Invariants — true for every name, including one nobody added to the table
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_the_display_form_never_contains_a_raw_keyboard_apostrophe(golden: GoldenName) -> None:
    # Arrange — only the two canonical modifier letters may reach a human being
    forbidden = APOSTROPHE_VARIANTS - {TURNED_COMMA, MODIFIER_APOSTROPHE}

    # Act
    display = _resolve(golden).display

    # Assert
    assert not any(character in forbidden for character in display)


@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_every_candidate_still_sounds_like_the_name_it_came_from(golden: GoldenName) -> None:
    # Arrange — a candidate that cannot verify against its own display form is a candidate
    # the acoustic loop would reject no matter how well the model sang it
    name = _resolve(golden)

    # Act / Assert
    for candidate in name.candidates:
        score = name_similarity(name.display, candidate.text)
        assert score >= MIN_SIMILARITY, f"{candidate.strategy} {candidate.text!r} scored {score}"


@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_candidate_ranks_are_dense_and_unique(golden: GoldenName) -> None:
    # Act
    candidates = _resolve(golden).candidates

    # Assert
    assert [candidate.rank for candidate in candidates] == list(range(len(candidates)))
    assert len({candidate.text for candidate in candidates}) == len(candidates)


@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_every_value_respects_its_vendor_limit(golden: GoldenName) -> None:
    # Act
    name = _resolve(golden)

    # Assert
    assert len(name.display) <= MAX_RECIPIENT_NAME_CHARS
    assert all(len(candidate.text) <= MAX_CANDIDATE_CHARS for candidate in name.candidates)


@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_resolution_is_deterministic(golden: GoldenName) -> None:
    assert _resolve(golden) == _resolve(golden)


@pytest.mark.parametrize("golden", GOLDEN_PARAMS)
def test_resolving_the_display_form_again_is_a_fixed_point(golden: GoldenName) -> None:
    # Arrange — the display form is already canonical, so re-resolving must not change it
    name = _resolve(golden)

    # Act
    again = resolve_name(
        name.display,
        candidate_order=DEFAULT_NAME_CANDIDATE_ORDER,
        ui_language=golden.ui_language,
    )

    # Assert
    assert is_ok(again)
    assert again.value.display == name.display
    assert again.value.candidates == name.candidates
