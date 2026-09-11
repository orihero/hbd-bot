"""The acoustic loop: render, listen, re-roll, and never fail the order because of it."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

import pytest

from bayram.config import Settings
from bayram.contracts import (
    Brief,
    CompositionPlan,
    NameCandidate,
    NameStrategy,
    RecipientName,
    Result,
    Script,
)
from bayram.errors import (
    ProviderRejectedContentError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from bayram.pipeline.events import PipelineStage, ProgressReporter, ProgressStatus
from bayram.pipeline.name_stage import (
    VERIFICATION_EVENT,
    SongRender,
    best_similarity,
    render_song,
)
from bayram.pipeline.plan_builder import build_composition_plan
from bayram.pipeline.retry import RetryPolicy
from tests.conftest import UZBEK_NAME_CANONICAL, candidate_of, make_brief, make_lyrics, recipient_of
from tests.test_pipeline.conftest import (
    FakeMusicProvider,
    FakeSttProvider,
    RecordingSink,
    Studio,
    failure_of,
    fake_similarity,
    no_sleep,
    ticking_clock,
    value_of,
)

STRIPPED = "Gulomjon"
HYPHENATED = "Gu-lom-jon"


def _brief() -> Brief:
    return make_brief()


def _plan(settings: Settings, brief: Brief) -> CompositionPlan:
    return value_of(
        build_composition_plan(
            make_lyrics(),
            brief=brief,
            candidate=recipient_of(brief).candidates[0],
            settings=settings,
            seed=7,
        )
    )


async def _run(
    studio: Studio,
    *,
    brief: Brief | None = None,
    settings: Settings | None = None,
) -> Result[SongRender]:
    resolved_brief = brief or _brief()
    resolved_settings = settings or studio.settings
    sink = RecordingSink()
    order_id = uuid4()
    return await render_song(
        _plan(resolved_settings, resolved_brief),
        order_id=order_id,
        brief=resolved_brief,
        music=studio.music,
        stt=studio.stt,
        similarity=fake_similarity,
        settings=resolved_settings,
        policy=RetryPolicy(max_attempts=2, backoff_base_s=0.01, jitter=0.0),
        sleeper=no_sleep,
        reporter=ProgressReporter(sink, order_id=order_id, correlation_id="corr"),
        clock=ticking_clock(),
        slots=asyncio.Semaphore(2),
    )


async def test_accepts_the_first_orthography_when_it_is_heard_correctly(
    studio: Studio,
) -> None:
    # Arrange: the fake STT echoes whatever spelling was submitted

    # Act
    render = value_of(await _run(studio))

    # Assert
    assert render.is_verified is True
    assert render.renders == 1
    assert candidate_of(render).strategy is NameStrategy.STRIPPED
    assert studio.music.inpaint_calls == []


async def test_re_rolls_only_the_name_chunk_with_the_next_orthography(
    studio: Studio,
) -> None:
    # Arrange: the stripped spelling comes back as something else entirely
    studio.stt.pronunciations[STRIPPED] = "Zamira"

    # Act
    render = value_of(await _run(studio))

    # Assert
    assert render.is_verified is True
    assert render.renders == 2
    assert candidate_of(render).strategy is NameStrategy.CANONICAL
    assert studio.music.inpaint_calls == [("song-remote-1", 1)]


async def test_verdicts_record_every_attempt_including_the_rejected_take(
    studio: Studio,
) -> None:
    # Arrange
    studio.stt.pronunciations[STRIPPED] = "Zamira"

    # Act
    render = value_of(await _run(studio))

    # Assert
    assert [verdict.is_match for verdict in render.verdicts] == [False, True]
    assert render.verdicts[0].candidate.text == STRIPPED
    assert render.verdicts[0].attempt == 0


async def test_delivers_the_closest_take_when_every_orthography_misses(
    studio: Studio,
) -> None:
    # Arrange: nothing is ever heard correctly
    for spelling in (STRIPPED, UZBEK_NAME_CANONICAL, HYPHENATED):
        studio.stt.pronunciations[spelling] = "Zamira"

    # Act
    render = value_of(await _run(studio))

    # Assert
    assert render.is_verified is False
    assert render.was_checked is True
    assert len(render.verdicts) == studio.settings.name_verification_max_attempts


async def test_stops_at_the_configured_attempt_budget(studio: Studio) -> None:
    # Arrange
    for spelling in (STRIPPED, UZBEK_NAME_CANONICAL, HYPHENATED):
        studio.stt.pronunciations[spelling] = "Zamira"
    capped = studio.settings.model_copy(update={"name_verification_max_attempts": 2})

    # Act
    render = value_of(await _run(studio, settings=capped))

    # Assert
    assert len(render.verdicts) == 2
    assert len(studio.music.compose_calls) + len(studio.music.inpaint_calls) == 2


async def test_stops_when_the_candidate_ladder_runs_out_before_the_budget(
    studio: Studio,
) -> None:
    # Arrange: one candidate only, three attempts allowed
    lonely = make_brief(
        recipient=RecipientName(
            raw="Ali",
            display="Ali",
            lookup_key="ali",
            script=Script.LATIN,
            language=studio.settings.default_ui_language,
            candidates=(NameCandidate(text="Ali", strategy=NameStrategy.STRIPPED, rank=0),),
        )
    )
    studio.stt.pronunciations["Ali"] = "Zamira"

    # Act
    render = value_of(await _run(studio, brief=lonely))

    # Assert
    assert len(render.verdicts) == 1
    assert render.is_verified is False


async def test_ships_the_take_when_stt_is_unavailable(studio: Studio) -> None:
    # Arrange
    studio.stt.failures = [
        ProviderUnavailableError("scribe is down", provider="fake"),
        ProviderUnavailableError("scribe is still down", provider="fake"),
    ]

    # Act
    render = value_of(await _run(studio))

    # Assert
    assert render.was_checked is False
    assert render.is_verified is False
    assert render.verdicts == ()


async def test_skips_verification_entirely_when_it_is_switched_off(
    studio: Studio,
) -> None:
    # Arrange
    disabled = studio.settings.model_copy(update={"is_name_verification_enabled": False})

    # Act
    render = value_of(await _run(studio, settings=disabled))

    # Assert
    assert render.was_checked is False
    assert studio.stt.calls == []


async def test_returns_the_error_when_the_very_first_render_fails(
    studio: Studio,
) -> None:
    # Arrange
    studio.music.failures = [
        ProviderRejectedContentError("policy", provider="fake"),
    ]

    # Act
    result = await _run(studio)

    # Assert
    assert failure_of(result).is_terminal is True


async def test_keeps_the_earlier_take_when_a_re_roll_render_fails(
    studio: Studio,
) -> None:
    # Arrange: the first take is heard wrong, then the inpaint fails outright
    studio.stt.pronunciations[STRIPPED] = "Zamira"
    studio.music.failures = [None, ProviderRejectedContentError("policy", provider="fake")]

    # Act
    render_result = await _run(studio)

    # Assert: the first compose succeeded, so we ship it rather than fail the order
    render = value_of(render_result)
    assert render.is_verified is False
    assert candidate_of(render).text == STRIPPED


async def test_composes_from_scratch_when_the_vendor_did_not_store_the_song(
    studio: Studio,
) -> None:
    # Arrange
    studio.music.remote_id = None
    studio.stt.pronunciations[STRIPPED] = "Zamira"

    # Act
    value_of(await _run(studio))

    # Assert
    assert studio.music.inpaint_calls == []
    assert len(studio.music.compose_calls) == 2


async def test_a_retryable_render_failure_is_retried_before_giving_up(
    studio: Studio,
) -> None:
    # Arrange
    studio.music.failures = [ProviderTimeoutError("slow", provider="fake")]

    # Act
    render = value_of(await _run(studio))

    # Assert
    assert render.is_verified is True
    assert len(studio.music.idempotency_keys) == 2
    assert len(set(studio.music.idempotency_keys)) == 1


def test_best_similarity_finds_the_name_inside_a_whole_song_transcript() -> None:
    # Arrange
    transcript = "bugun quyosh porlaydi Gulomjon yashasin do'stlar"

    # Act
    score = best_similarity(transcript, UZBEK_NAME_CANONICAL, fake_similarity)

    # Assert
    assert score == 1.0


def test_best_similarity_is_zero_for_an_empty_transcript() -> None:
    # Arrange / Act
    score = best_similarity("   ", UZBEK_NAME_CANONICAL, fake_similarity)

    # Assert
    assert score == 0.0


async def test_announces_the_re_roll_and_the_final_verdict(studio: Studio) -> None:
    # Arrange
    sink = RecordingSink()
    brief = _brief()
    studio.stt.pronunciations[STRIPPED] = "Zamira"
    order_id = uuid4()

    # Act
    await render_song(
        _plan(studio.settings, brief),
        order_id=order_id,
        brief=brief,
        music=studio.music,
        stt=studio.stt,
        similarity=fake_similarity,
        settings=studio.settings,
        policy=RetryPolicy(max_attempts=1, backoff_base_s=0.01, jitter=0.0),
        sleeper=no_sleep,
        reporter=ProgressReporter(sink, order_id=order_id, correlation_id="corr"),
        clock=ticking_clock(),
        slots=asyncio.Semaphore(1),
    )

    # Assert
    assert (PipelineStage.VERIFYING_NAME.value, ProgressStatus.RETRYING.value) in sink.stages()
    assert (PipelineStage.VERIFYING_NAME.value, ProgressStatus.SUCCEEDED.value) in sink.stages()


def test_fakes_satisfy_the_frozen_protocols() -> None:
    # Arrange / Act / Assert — structural conformance, no inheritance
    assert hasattr(FakeMusicProvider(), "inpaint")
    assert hasattr(FakeSttProvider(), "transcribe")


# ---------------------------------------------------------------------------
# Observability: the two facts nobody could previously read off a running system
# ---------------------------------------------------------------------------
async def test_a_missing_stored_song_handle_is_reported_once_not_silently(
    studio: Studio, caplog: pytest.LogCaptureFixture
) -> None:
    """Without a handle every re-roll re-composes the whole track. That must not be silent.

    ``_render`` falls back from inpaint to compose when there is no stored-song id, which
    is a three-fold music bill wearing the costume of a cheap chunk re-roll.
    """
    # Arrange: a vendor that returns audio but no song id, and a name never heard right,
    # so the loop takes every re-roll it is allowed and could warn once per render.
    studio.music.remote_id = None
    for spelling in (STRIPPED, UZBEK_NAME_CANONICAL, HYPHENATED):
        studio.stt.pronunciations[spelling] = "Zamira"

    # Act
    with caplog.at_level(logging.WARNING, logger="bayram.pipeline.name_stage"):
        result = await _run(studio)

    # Assert
    assert value_of(result).renders > 1
    warnings = [
        record for record in caplog.records if "no stored-song handle" in record.getMessage()
    ]
    assert len(warnings) == 1


async def test_a_stored_song_handle_produces_no_warning(
    studio: Studio, caplog: pytest.LogCaptureFixture
) -> None:
    # Act
    with caplog.at_level(logging.WARNING, logger="bayram.pipeline.name_stage"):
        await _run(studio)

    # Assert
    assert not [
        record for record in caplog.records if "no stored-song handle" in record.getMessage()
    ]


async def test_every_completed_loop_emits_one_verification_line(
    studio: Studio, caplog: pytest.LogCaptureFixture
) -> None:
    """The re-roll rate is read from this line; ``verdicts`` is aggregated nowhere else."""
    # Act
    with caplog.at_level(logging.INFO, logger="bayram.pipeline.name_stage"):
        result = await _run(studio)

    # Assert
    lines = [record for record in caplog.records if record.getMessage() == VERIFICATION_EVENT]
    assert len(lines) == 1
    # ``extra=`` values land on the LogRecord itself, which is untyped; reading them
    # through ``__dict__`` keeps the assertion honest without lying to the type checker.
    fields = dict(lines[0].__dict__)
    render = value_of(result)
    assert fields["renders"] == render.renders
    assert fields["attempts"] == len(render.verdicts)
    assert fields["did_inpaint"] is True
