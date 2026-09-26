"""Closing the loop acoustically: scoring an STT transcript against the intended name."""

from __future__ import annotations

import pytest

from bayram.contracts import Language, NameCandidate, NameStrategy, Transcript
from bayram.names.matching import (
    compare_names,
    judge_transcript,
    name_similarity,
    sound_key,
    sound_keys,
)

THRESHOLD = 0.85

#: Every candidate orthography of one name must reduce to the same sound key. If this ever
#: stops holding, the re-roll loop starts rejecting its own correct renderings.
SAME_NAME_SPELLINGS = [
    pytest.param("Gulomjon", id="stripped"),
    pytest.param("Gʻulomjon", id="canonical"),
    pytest.param("G'ulomjon", id="ascii"),
    pytest.param("Gu-lom-jon", id="hyphenated"),
    pytest.param("Ghoolomjon", id="phonetic"),
    pytest.param("Ғуломжон", id="uzbek-cyrillic"),
    pytest.param("Гуломжон", id="russian-cyrillic"),
    pytest.param("gulomjon", id="lowercase"),
    pytest.param("GULOMJON", id="uppercase"),
    pytest.param("  Gulomjon  ", id="padded"),
]


@pytest.mark.parametrize("spelling", SAME_NAME_SPELLINGS)
def test_every_spelling_of_one_name_reduces_to_the_same_sound_key(spelling: str) -> None:
    assert sound_key(spelling) == "gulomjon"


@pytest.mark.parametrize("spelling", SAME_NAME_SPELLINGS)
def test_every_spelling_of_one_name_scores_a_perfect_match(spelling: str) -> None:
    assert name_similarity("Gʻulomjon", spelling) == 1.0


def test_a_different_name_scores_zero() -> None:
    assert name_similarity("Gʻulomjon", "Vladimir") == 0.0


def test_a_mispronounced_consonant_scores_below_the_threshold() -> None:
    # Arrange — the model sang "Никора" for Nigora: a real re-roll trigger
    score = name_similarity("Nigora", "Никора")

    # Assert
    assert score < THRESHOLD


def test_an_empty_intended_name_scores_zero_rather_than_dividing_by_zero() -> None:
    assert name_similarity("", "Gulomjon") == 0.0


def test_an_empty_transcript_scores_zero() -> None:
    assert name_similarity("Gulomjon", "") == 0.0


def test_a_transcript_with_no_letters_scores_zero() -> None:
    assert name_similarity("Gulomjon", "... 123 !!!") == 0.0


def test_the_name_is_found_inside_a_padded_transcript() -> None:
    # Arrange — an STT pass over a sung chunk returns whatever else it caught
    score = name_similarity("Nigora", "happy birthday dear Nigora")

    # Assert
    assert score == 1.0


def test_a_two_word_name_is_found_across_a_word_boundary() -> None:
    assert name_similarity("Ali Vali", "salom Ali Vali aka") == 1.0


def test_a_repeated_name_in_the_transcript_still_scores_perfectly() -> None:
    assert name_similarity("Aziza", "Aziza Aziza Aziza") == 1.0


@pytest.mark.parametrize(
    ("intended", "heard"),
    [
        pytest.param("Xurshid", "Хуршид", id="x-vs-cyrillic-kha"),
        pytest.param("Xurshid", "Khurshid", id="x-vs-kh"),
        pytest.param("Qodir", "Kodir", id="q-vs-k"),
        pytest.param("Ulugʻbek", "Ulugbek", id="turned-comma-dropped"),
        pytest.param("Oʻktam", "Oktam", id="o-digraph-dropped"),
        pytest.param("Jasur", "Zhasur", id="j-vs-zh"),
        pytest.param("Anna", "Ana", id="doubled-consonant"),
        pytest.param("Vali", "Wali", id="v-vs-w"),
        pytest.param("Nigora", "Neegora", id="i-vs-ee"),
        pytest.param("Jasur", "Jasoor", id="u-vs-oo"),
        pytest.param("Sanʼat", "Санъат", id="tutuq-belgisi-vs-hard-sign"),
    ],
)
def test_known_transcription_confusions_are_treated_as_matches(intended: str, heard: str) -> None:
    assert name_similarity(intended, heard) == 1.0


def test_the_yo_vowel_is_preserved_in_display_but_folded_for_matching() -> None:
    # Arrange — Алёна must keep its ё on screen; an ASR that drops it is still a match
    assert name_similarity("Алёна", "Алена") == 1.0


def test_a_cyrillic_yo_name_matches_its_latin_romanisation() -> None:
    assert name_similarity("Алёна", "Alyona") == 1.0
    assert name_similarity("Alyona", "Алёна") == 1.0


def test_a_yo_name_gets_a_second_sound_key_and_an_unambiguous_one_gets_one() -> None:
    # Arrange / Act / Assert
    assert len(sound_keys("Alyona")) == 2
    assert len(sound_keys("Gulomjon")) == 1


def test_two_genuinely_different_russian_names_do_not_match() -> None:
    assert name_similarity("Алёна", "Елена") < THRESHOLD


def test_similarity_is_symmetric() -> None:
    assert name_similarity("Gʻulomjon", "Гуломжон") == name_similarity("Гуломжон", "Gʻulomjon")


def test_scores_are_bounded_to_the_unit_interval() -> None:
    # Arrange
    pairs = [("Aziza", "Aziza"), ("Aziza", "Vladimir"), ("Aziza", "Azeeza"), ("", "")]

    # Act / Assert
    assert all(0.0 <= name_similarity(a, b) <= 1.0 for a, b in pairs)


def test_compare_names_applies_the_configured_threshold() -> None:
    # Arrange — the threshold is configuration, so the same score can decide either way
    lenient = compare_names("Nigora", "Никора", min_similarity=0.5)
    strict = compare_names("Nigora", "Никора", min_similarity=0.99)

    # Assert
    assert lenient.score == strict.score
    assert lenient.is_match is True
    assert strict.is_match is False


def test_compare_names_exposes_both_sound_keys_for_the_logs() -> None:
    # Act
    match = compare_names("Gʻulomjon", "Ғуломжон", min_similarity=THRESHOLD)

    # Assert
    assert match.intended_key == "gulomjon"
    assert match.heard_key == "gulomjon"
    assert match.min_similarity == THRESHOLD


def _candidate(text: str = "Gulomjon") -> NameCandidate:
    return NameCandidate(text=text, strategy=NameStrategy.STRIPPED, rank=0)


def _transcript(text: str, confidence: float = 0.9) -> Transcript:
    return Transcript(text=text, language=Language.UZ_LATN, confidence=confidence)


def test_a_good_take_produces_a_matching_verdict() -> None:
    # Arrange
    candidate = _candidate()

    # Act
    verdict = judge_transcript(
        candidate=candidate,
        intended="Gʻulomjon",
        transcript=_transcript("Гуломжон"),
        attempt=0,
        min_similarity=THRESHOLD,
    )

    # Assert
    assert verdict.is_match is True
    assert verdict.confidence == 1.0
    assert verdict.candidate == candidate
    assert verdict.attempt == 0


def test_a_bad_take_produces_a_non_matching_verdict_that_keeps_the_transcript() -> None:
    # Act
    verdict = judge_transcript(
        candidate=_candidate(),
        intended="Nigora",
        transcript=_transcript("Никора"),
        attempt=1,
        min_similarity=THRESHOLD,
    )

    # Assert
    assert verdict.is_match is False
    assert verdict.transcript == "Никора"
    assert verdict.attempt == 1


def test_the_verdict_scores_the_display_name_not_the_distorted_candidate() -> None:
    # Arrange — the phonetic candidate is deliberately misspelled; scoring the transcript
    # against it would reward the distortion instead of measuring the pronunciation
    candidate = NameCandidate(text="Neegora", strategy=NameStrategy.PHONETIC, rank=0)

    # Act
    verdict = judge_transcript(
        candidate=candidate,
        intended="Nigora",
        transcript=_transcript("Nigora"),
        attempt=0,
        min_similarity=THRESHOLD,
    )

    # Assert
    assert verdict.is_match is True
    assert verdict.confidence == 1.0


def test_the_provider_confidence_is_not_blended_into_the_match_confidence() -> None:
    # Arrange — a shaky STT confidence must not silently lower the similarity score
    high = judge_transcript(
        candidate=_candidate(),
        intended="Aziza",
        transcript=_transcript("Aziza", confidence=0.99),
        attempt=0,
        min_similarity=THRESHOLD,
    )
    low = judge_transcript(
        candidate=_candidate(),
        intended="Aziza",
        transcript=_transcript("Aziza", confidence=0.10),
        attempt=0,
        min_similarity=THRESHOLD,
    )

    # Assert
    assert high.confidence == low.confidence == 1.0


def test_a_long_transcript_is_bounded_and_still_finds_the_name() -> None:
    # Arrange — a pathological transcript must not blow up the window search
    noise = " ".join(["lorem"] * 200)

    # Act
    score = name_similarity("Aziza", f"{noise} Aziza {noise}")

    # Assert
    assert score == 1.0
