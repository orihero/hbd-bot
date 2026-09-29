"""The narration budget, the voice-note length rule and the transcript's trust (IMAGE_VIDEO_SPEC
§2.4.2, §5.3, §5.4; M4.1). Pure: no ffmpeg, no guard."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from bayram.config import Settings
from bayram.contracts import Language
from bayram.media.narration import (
    budget_language,
    fits_budget,
    is_voice_note_too_long,
    narration_budget,
    narration_words,
)
from bayram.media.voice_probe import silencedetect_args, silent_seconds
from bayram.moderation.contracts import VoiceTranscript
from bayram.moderation.voice import UntrustedTranscript, untrusted_transcript

NINE_WORDS: Final[str] = "one two three four five six seven eight nine"


def test_the_budgets_ship_as_the_spec_starts_them(settings: Settings) -> None:
    budgets = {language: narration_budget(settings, language) for language in Language}

    assert (budgets[Language.UZ_LATN].words, budgets[Language.UZ_LATN].chars) == (8, 60)
    assert budgets[Language.UZ_CYRL] == budgets[Language.UZ_LATN]
    assert (budgets[Language.RU].words, budgets[Language.RU].chars) == (10, 70)
    assert (budgets[Language.EN].words, budgets[Language.EN].chars) == (12, 80)
    assert {budget.seconds for budget in budgets.values()} == {5}
    assert budget_language(Language.UZ_CYRL) == "uz"


def test_nine_words_are_over_the_uzbek_budget_and_within_the_english(settings: Settings) -> None:
    assert not fits_budget(NINE_WORDS, narration_budget(settings, Language.UZ_LATN))
    assert fits_budget(NINE_WORDS, narration_budget(settings, Language.EN))


def test_the_character_budget_binds_too(settings: Settings) -> None:
    long_words = "Tugʻilgan kuningiz muborak boʻlsin, aziz va qadrdon Dilnozaxonimiz!"

    assert narration_words(long_words) <= 8
    assert not fits_budget(long_words, narration_budget(settings, Language.UZ_LATN))


def test_an_empty_line_never_fits(settings: Settings) -> None:
    assert not fits_budget("   ​ ", narration_budget(settings, Language.EN))


def test_invisible_and_doubled_spaces_do_not_count_as_words(settings: Settings) -> None:
    assert narration_words("Happy​   birthday  Dilnoza") == 3


@pytest.mark.parametrize(
    ("duration", "too_long"), [(5.0, False), (5.25, False), (5.26, True), (5.6, True)]
)
def test_a_note_is_refused_only_above_the_clip_plus_a_quarter_second(
    settings: Settings, duration: float, too_long: bool
) -> None:
    assert is_voice_note_too_long(duration, settings) is too_long


# ---------------------------------------------------------------------------
# silencedetect
# ---------------------------------------------------------------------------
def test_silence_spans_are_summed_and_an_open_one_runs_to_the_end() -> None:
    log = "\n".join(
        (
            "[silencedetect @ 0x1] silence_start: 0",
            "[silencedetect @ 0x1] silence_end: 0.8 | silence_duration: 0.8",
            "[silencedetect @ 0x1] silence_start: 3.5",
        )
    )

    assert silent_seconds(log, 5.0) == pytest.approx(0.8 + 1.5)


def test_the_silencedetect_call_writes_nothing() -> None:
    args = silencedetect_args("ffmpeg", Path("note.ogg"))

    assert args[-3:] == ("-f", "null", "-")


# ---------------------------------------------------------------------------
# The transcript's trust (§5.4)
# ---------------------------------------------------------------------------
def _heard(text: str = "happy birthday dear friend", **values: object) -> VoiceTranscript:
    fields: dict[str, object] = {
        "text": text,
        "language": "en",
        "avg_logprob": -0.3,
        "no_speech_prob": 0.01,
        "max_compression_ratio": 1.2,
    }
    fields.update(values)
    return VoiceTranscript(**fields)  # type: ignore[arg-type]


def test_a_clean_transcript_is_trusted() -> None:
    assert untrusted_transcript(_heard(), voiced_s=4.0) is None


@pytest.mark.parametrize(
    ("transcript", "voiced", "reason"),
    [
        (_heard(""), 4.0, UntrustedTranscript.EMPTY),
        (_heard(no_speech_prob=0.9), 4.0, UntrustedTranscript.NO_SPEECH),
        (_heard(avg_logprob=-1.4), 4.0, UntrustedTranscript.LOW_LOGPROB),
        (_heard(max_compression_ratio=2.6), 4.0, UntrustedTranscript.COMPRESSION),
        (_heard(language="de"), 4.0, UntrustedTranscript.LANGUAGE),
        (_heard("mmm"), 4.5, UntrustedTranscript.WORD_RATE),
    ],
)
def test_each_hallucination_sign_refuses(
    transcript: VoiceTranscript, voiced: float, reason: UntrustedTranscript
) -> None:
    assert untrusted_transcript(transcript, voiced_s=voiced) is reason


def test_a_high_no_speech_prob_over_real_silence_is_not_the_no_speech_rule() -> None:
    # Whisper says "no speech" and silencedetect agrees: nothing was hidden, the rule is about
    # whisper denying speech that IS there.
    assert untrusted_transcript(_heard("hi", no_speech_prob=0.9), voiced_s=0.2) is None


def test_whisper_may_name_the_language() -> None:
    assert untrusted_transcript(_heard(language="Uzbek"), voiced_s=3.0) is None
