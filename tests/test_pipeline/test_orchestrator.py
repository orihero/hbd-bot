"""End to end, with fakes: the integration test that proves the product works.

Every path that matters commercially is here — the happy one, the silent name re-roll, the
partial delivery, and the replay that must not buy a second song.
"""

from __future__ import annotations

from pathlib import Path

from hbd.contracts import (
    AssetKind,
    Err,
    LyricDraft,
    NameStrategy,
    Order,
    OrderState,
    RecipientName,
    Script,
)
from hbd.errors import (
    ErrorCode,
    ProviderTimeoutError,
    StorageError,
)
from hbd.pipeline.events import PipelineStage, ProgressStatus
from hbd.pipeline.outcome import PipelineOutcome
from tests.conftest import (
    UZBEK_NAME_CANONICAL,
    make_brief,
    make_candidates,
    make_lyrics,
    make_order,
)
from tests.test_pipeline.conftest import SpyContentWriter, Studio, failure_of, value_of

STRIPPED = "Gulomjon"
#: Deliberately not the title the fake LLM writes, so "whose words are these?" is decidable
#: from the kit alone.
APPROVED_TITLE = "Sen uchun qoʻshiq"


async def _run(studio: Studio, order: Order) -> PipelineOutcome:
    return value_of(await studio.pipeline().run(order))


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------
async def test_delivers_a_complete_kit(studio: Studio, ready_order: Order) -> None:
    # Arrange / Act
    outcome = await _run(studio, ready_order)

    # Assert
    kit = outcome.kit
    assert kit.order_id == ready_order.id
    assert kit.song.kind is AssetKind.SONG
    assert len(kit.greetings) == studio.settings.greetings_per_kit
    assert kit.lyric_sheet.kind is AssetKind.LYRIC_SHEET
    assert outcome.is_complete is True


async def test_every_delivered_file_exists_on_disk(studio: Studio, ready_order: Order) -> None:
    # Arrange / Act
    outcome = await _run(studio, ready_order)

    # Assert
    assert all(asset.path.exists() for asset in outcome.kit.all_assets)


async def test_walks_the_order_through_its_states_to_delivered(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange / Act
    await _run(studio, ready_order)

    # Assert
    assert studio.repository.states == [
        OrderState.LYRICS_READY,
        OrderState.AUTHORIZED,
        OrderState.GENERATING,
        OrderState.DELIVERED,
    ]


async def test_emits_a_progress_event_for_every_stage(studio: Studio, ready_order: Order) -> None:
    # Arrange / Act
    await _run(studio, ready_order)

    # Assert
    started = {stage for stage, status in studio.sink.stages() if status == "started"}
    assert started >= {stage.value for stage in PipelineStage} - {"delivering"}
    # The pipeline stops at "persisted". DELIVERING belongs to ``runtime.jobs._send_kit``,
    # which brackets the real send — this used to emit SUCCEEDED for it here, i.e. put
    # "Done — sending it now" on screen before a byte had left the worker.
    assert studio.sink.stages()[-1] == (
        PipelineStage.PERSISTING.value,
        ProgressStatus.SUCCEEDED.value,
    )
    assert PipelineStage.DELIVERING.value not in {stage for stage, _ in studio.sink.stages()}


async def test_records_a_timing_for_every_stage_it_ran(studio: Studio, ready_order: Order) -> None:
    # Arrange / Act
    outcome = await _run(studio, ready_order)

    # Assert
    timed = {timing.stage for timing in outcome.timings}
    assert PipelineStage.COMPOSING_SONG in timed
    assert PipelineStage.PERSISTING in timed
    assert outcome.total_duration_ms > 0


async def test_totals_the_provider_cost(studio: Studio, ready_order: Order) -> None:
    # Arrange / Act
    outcome = await _run(studio, ready_order)

    # Assert: one song at 0.30 plus three greetings at 0.02
    assert round(outcome.total_cost_usd, 2) == 0.36


async def test_archives_every_asset_to_storage(studio: Studio, ready_order: Order) -> None:
    # Arrange / Act
    outcome = await _run(studio, ready_order)

    # Assert
    assert len(studio.storage.objects) == len(outcome.kit.all_assets)


async def test_the_lyric_sheet_shows_the_display_orthography_not_the_submitted_one(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange / Act
    outcome = await _run(studio, ready_order)

    # Assert
    sheet = outcome.kit.lyric_sheet.path.read_text(encoding="utf-8")
    assert UZBEK_NAME_CANONICAL in sheet
    assert STRIPPED not in sheet


# ---------------------------------------------------------------------------
# The name loop
# ---------------------------------------------------------------------------
async def test_silently_re_rolls_the_name_and_still_delivers(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.stt.pronunciations[STRIPPED] = "Zamira"

    # Act
    outcome = await _run(studio, ready_order)

    # Assert
    assert len(outcome.name_verdicts) == 2
    assert outcome.name_verdicts[-1].is_match is True
    assert outcome.kit.song.name_candidate is not None
    assert outcome.kit.song.name_candidate.strategy is NameStrategy.CANONICAL
    assert outcome.is_complete is True


async def test_records_a_gap_when_no_orthography_is_ever_heard_correctly(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    for spelling in (STRIPPED, UZBEK_NAME_CANONICAL, "Gu-lom-jon"):
        studio.stt.pronunciations[spelling] = "Zamira"

    # Act
    outcome = await _run(studio, ready_order)

    # Assert
    codes = [gap.error_code for gap in outcome.gaps]
    assert ErrorCode.NAME_UNVERIFIABLE in codes
    assert outcome.kit.song.path.exists()


async def test_does_not_record_a_name_gap_when_verification_is_switched_off(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.settings = studio.settings.model_copy(update={"is_name_verification_enabled": False})

    # Act
    outcome = await _run(studio, ready_order)

    # Assert
    assert outcome.gaps == ()
    assert outcome.name_verdicts == ()


# ---------------------------------------------------------------------------
# Partial delivery
# ---------------------------------------------------------------------------
async def test_delivers_the_kit_when_one_greeting_fails(studio: Studio, ready_order: Order) -> None:
    # Arrange
    studio.tts.failing_personas = {"persona-2"}

    # Act
    outcome = await _run(studio, ready_order)

    # Assert
    assert len(outcome.kit.greetings) == 2
    assert len(outcome.gaps) == 1
    assert outcome.gaps[0].stage is PipelineStage.RENDERING_GREETINGS


async def test_delivers_the_kit_when_one_greeting_fails_post_processing(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.post.should_fail_voice_note = True

    # Act
    result = await studio.pipeline().run(ready_order)

    # Assert: every greeting failed to transcode, so there is no kit — but the song survived
    error = failure_of(result)
    assert Path(error.context["song_path"]).exists()


async def test_fails_the_order_when_every_greeting_fails(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.tts.failing_personas = {"persona-1", "persona-2", "persona-3"}

    # Act
    result = await studio.pipeline().run(ready_order)

    # Assert
    assert isinstance(result, Err)
    assert studio.repository.states[-1] is OrderState.FAILED


async def test_a_storage_outage_is_a_gap_not_a_failure(studio: Studio, ready_order: Order) -> None:
    # Arrange
    studio.storage.should_fail = True

    # Act
    outcome = await _run(studio, ready_order)

    # Assert
    assert outcome.gaps
    assert all(gap.stage is PipelineStage.PERSISTING for gap in outcome.gaps)
    assert outcome.kit.song.path.exists()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
async def test_a_replayed_job_does_not_buy_a_second_song(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    first = await _run(studio, ready_order)
    calls_after_first = len(studio.music.compose_calls)

    # Act
    second = await _run(studio, ready_order)

    # Assert
    assert len(studio.music.compose_calls) == calls_after_first
    assert second.kit.song.sha256 == first.kit.song.sha256


async def test_a_replay_reconstructs_the_name_gap_it_cannot_read_back(
    studio: Studio, ready_order: Order
) -> None:
    """A redelivery must carry the pronunciation disclosure the first delivery carried.

    Gaps are not persisted, so the replay used to report none and the second closing
    message silently claimed a clean run. The stored verdicts still prove this one.
    """
    # Arrange — no orthography is ever heard correctly, so the first run records the gap
    for spelling in (STRIPPED, UZBEK_NAME_CANONICAL, "Gu-lom-jon"):
        studio.stt.pronunciations[spelling] = "Zamira"
    first = await _run(studio, ready_order)
    assert [gap.error_code for gap in first.gaps] == [ErrorCode.NAME_UNVERIFIABLE]

    # Act
    second = await _run(studio, ready_order)

    # Assert
    assert [gap.stage for gap in second.gaps] == [PipelineStage.VERIFYING_NAME]
    assert second.gaps[0].error_code is ErrorCode.NAME_UNVERIFIABLE
    assert second.is_complete is False


async def test_a_replay_reconstructs_a_greeting_the_stored_kit_is_short_of(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange — one persona fails, so the kit is one greeting short of what was asked for
    studio.tts.failing_personas = {"persona-2"}
    first = await _run(studio, ready_order)
    assert len(first.kit.greetings) == studio.settings.greetings_per_kit - 1

    # Act
    second = await _run(studio, ready_order)

    # Assert
    assert [gap.stage for gap in second.gaps] == [PipelineStage.RENDERING_GREETINGS]


async def test_a_replay_of_a_clean_run_reports_no_gaps(studio: Studio, ready_order: Order) -> None:
    """The reconstruction must not invent an apology for a run that had nothing wrong."""
    # Arrange
    first = await _run(studio, ready_order)
    assert first.is_complete is True

    # Act
    second = await _run(studio, ready_order)

    # Assert
    assert second.gaps == ()
    assert second.is_complete is True


async def test_a_replay_cannot_reconstruct_an_archival_gap(
    studio: Studio, ready_order: Order
) -> None:
    """The one gap kind that does not survive the round trip, pinned so nobody is surprised.

    An asset that failed to ARCHIVE at PERSISTING leaves no trace in the stored kit, so a
    replay cannot see it. It is also the only gap with no consequence the customer can
    hear — the files were delivered from the worker's disk either way — so the replay's
    claim of a clean delivery is still one it can prove.
    """
    # Arrange
    studio.storage.should_fail = True
    first = await _run(studio, ready_order)
    assert all(gap.stage is PipelineStage.PERSISTING for gap in first.gaps)
    assert first.gaps

    # Act
    second = await _run(studio, ready_order)

    # Assert
    assert second.gaps == ()


async def test_retried_provider_calls_reuse_one_idempotency_key(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.music.failures = [ProviderTimeoutError("slow", provider="fake")]

    # Act
    await _run(studio, ready_order)

    # Assert
    assert len(studio.music.idempotency_keys) == 2
    assert len(set(studio.music.idempotency_keys)) == 1


# ---------------------------------------------------------------------------
# Terminal failures
# ---------------------------------------------------------------------------
async def test_a_rejected_brief_never_reaches_a_vendor(studio: Studio) -> None:
    # Arrange
    order = studio.enrol(make_order(brief=make_brief(note="I will kill him")))

    # Act
    result = await studio.pipeline().run(order)

    # Assert
    assert failure_of(result).error_code is ErrorCode.CONTENT_REJECTED
    assert studio.music.compose_calls == []
    assert studio.repository.states == [OrderState.FAILED]


async def test_a_blank_display_name_is_refused_at_the_boundary(studio: Studio) -> None:
    # Arrange
    blank = RecipientName(
        raw="   ",
        display="   ",
        lookup_key="blank",
        script=Script.LATIN,
        language=studio.settings.default_ui_language,
        candidates=make_candidates(),
    )
    order = studio.enrol(make_order(brief=make_brief(recipient=blank)))

    # Act
    result = await studio.pipeline().run(order)

    # Assert
    assert failure_of(result).error_code is ErrorCode.INVALID_INPUT


async def test_the_kit_price_comes_from_configuration_not_a_baked_in_constant(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange — payment is out of scope, but the amount the seam is handed is configuration.
    # The orchestrator used to pass its own KIT_PRICE_MINOR / KIT_CURRENCY module constants,
    # so HBD_KIT_PRICE_AMOUNT_MINOR and HBD_KIT_CURRENCY did nothing at all.
    priced = studio.settings.model_copy(
        update={"kit_price_amount_minor": 25_000, "kit_currency": "USD"}
    )

    # Act
    await studio.pipeline(settings=priced).run(ready_order)

    # Assert
    assert studio.payment.charges == [(25_000, "USD")]


async def test_the_worker_gate_is_told_which_telegram_user_the_order_belongs_to(
    studio: Studio, ready_order: Order
) -> None:
    """The worker re-runs the gate, and it must name the same payer the bot named.

    ``Order.id`` is a UUID5 over one draft (``hbd.bot.handlers.confirm._order_id_for``), so
    a provider that meters per person cannot recover the payer from it. The worker runs long
    after the tap, on a job carrying no user of its own, so the only honest source is the
    order — take it from anywhere else and the retry meters against the wrong human.
    """
    # Arrange / Act
    await studio.pipeline().run(ready_order)

    # Assert
    assert studio.payment.payers == [ready_order.telegram_user_id]


async def test_a_declined_payment_stops_the_run(studio: Studio, ready_order: Order) -> None:
    # Arrange
    studio.payment.is_authorized = False

    # Act
    result = await studio.pipeline().run(ready_order)

    # Assert
    assert failure_of(result).error_code is ErrorCode.UNKNOWN
    assert studio.music.compose_calls == []


async def test_a_voice_catalogue_outage_stops_the_run_before_the_song(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.tts.voices_failure = StorageError("catalogue unavailable")

    # Act
    result = await studio.pipeline().run(ready_order)

    # Assert
    assert isinstance(result, Err)
    assert studio.music.compose_calls == []


async def test_retries_a_transient_lyric_failure_and_carries_on(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.llm.fail_next("LyricsPayload", ProviderTimeoutError("slow", provider="fake"))

    # Act
    outcome = await _run(studio, ready_order)

    # Assert
    lyric_timing = next(
        timing for timing in outcome.timings if timing.stage is PipelineStage.WRITING_LYRICS
    )
    assert lyric_timing.attempts == 2
    assert outcome.kit.song.path.exists()


async def test_a_repository_that_cannot_save_fails_the_order(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.repository.save_failures = [
        StorageError("db is down"),
        StorageError("db is still down"),
    ]

    # Act
    result = await studio.pipeline().run(ready_order)

    # Assert
    assert failure_of(result).error_code is ErrorCode.STORAGE_FAILED
    assert studio.repository.states[-1] is OrderState.FAILED


# ---------------------------------------------------------------------------
# The lyric the customer approved in the wizard
# ---------------------------------------------------------------------------
def _approved_lyric() -> LyricDraft:
    """A lyric the customer already saw and said yes to, before anything was queued."""
    return make_lyrics(title=APPROVED_TITLE)


def _approved_order(studio: Studio, lyric: LyricDraft) -> Order:
    return studio.enrol(make_order(brief=make_brief(approved_lyrics=lyric)))


async def _run_with(studio: Studio, order: Order, writer: SpyContentWriter) -> PipelineOutcome:
    return value_of(await studio.pipeline(content_writer=writer).run(order))


async def test_an_approved_lyric_is_never_rewritten_by_the_content_writer(
    studio: Studio,
) -> None:
    """The customer paid for the words they read. Writing new ones would swap the product."""
    # Arrange
    writer = studio.content_spy()
    order = _approved_order(studio, _approved_lyric())

    # Act
    await _run_with(studio, order, writer)

    # Assert: the greetings still had to be written, so this is a silent stage, not a dead one
    assert writer.lyric_briefs == []
    assert len(writer.script_briefs) == 1


async def test_the_kit_carries_the_approved_lyric_word_for_word(studio: Studio) -> None:
    # Arrange
    lyric = _approved_lyric()
    writer = studio.content_spy()
    order = _approved_order(studio, lyric)

    # Act
    outcome = await _run_with(studio, order, writer)

    # Assert
    assert outcome.kit.lyrics == lyric
    assert outcome.kit.lyrics.title == APPROVED_TITLE
    assert len(outcome.kit.lyrics.name_hook_sections) == 1
    assert outcome.kit.lyrics.name_hook_sections[0].label == "hook"


async def test_the_delivered_lyric_sheet_is_the_one_the_customer_approved(
    studio: Studio,
) -> None:
    # Arrange
    lyric = _approved_lyric()
    writer = studio.content_spy()
    order = _approved_order(studio, lyric)

    # Act
    outcome = await _run_with(studio, order, writer)

    # Assert
    sheet = outcome.kit.lyric_sheet.path.read_text(encoding="utf-8")
    assert APPROVED_TITLE in sheet
    for section in lyric.sections:
        for line in section.lines:
            assert line in sheet


async def test_an_approved_lyric_still_walks_the_order_through_lyrics_ready(
    studio: Studio,
) -> None:
    """The stage becomes instant, not absent: the order still reports the same milestones."""
    # Arrange
    writer = studio.content_spy()
    order = _approved_order(studio, _approved_lyric())

    # Act
    await _run_with(studio, order, writer)

    # Assert
    assert studio.repository.states == [
        OrderState.LYRICS_READY,
        OrderState.AUTHORIZED,
        OrderState.GENERATING,
        OrderState.DELIVERED,
    ]


async def test_the_writing_lyrics_stage_is_still_narrated_when_the_lyric_was_approved(
    studio: Studio,
) -> None:
    """The progress bar must look identical on both paths, only faster on this one."""
    # Arrange
    writer = studio.content_spy()
    order = _approved_order(studio, _approved_lyric())

    # Act
    outcome = await _run_with(studio, order, writer)

    # Assert
    stages = studio.sink.stages()
    assert (PipelineStage.WRITING_LYRICS.value, ProgressStatus.STARTED.value) in stages
    assert (PipelineStage.WRITING_LYRICS.value, ProgressStatus.SUCCEEDED.value) in stages
    lyric_timing = next(
        timing for timing in outcome.timings if timing.stage is PipelineStage.WRITING_LYRICS
    )
    assert lyric_timing.attempts == 1


async def test_an_approved_lyric_delivers_even_when_the_writer_could_not_have_written_one(
    studio: Studio,
) -> None:
    """Proof by sabotage: every lyric attempt the LLM could be asked for is primed to fail.

    ``llm_parse_max_attempts`` is 2 here, so two queued failures would exhaust the retry
    and fail the order outright. The run finishing is the assertion.
    """
    # Arrange
    for _ in range(studio.settings.llm_parse_max_attempts):
        studio.llm.fail_next("LyricsPayload", ProviderTimeoutError("slow", provider="fake"))
    writer = studio.content_spy()
    order = _approved_order(studio, _approved_lyric())

    # Act
    outcome = await _run_with(studio, order, writer)

    # Assert
    assert outcome.kit.lyrics.title == APPROVED_TITLE
    assert outcome.kit.song.path.exists()


async def test_a_brief_with_no_approved_lyric_still_has_one_written_for_it(
    studio: Studio, ready_order: Order
) -> None:
    """The unchanged path: nothing was approved, so the writer is asked exactly once."""
    # Arrange
    writer = studio.content_spy()

    # Act
    outcome = await _run_with(studio, ready_order, writer)

    # Assert
    assert writer.lyric_briefs == [ready_order.brief]
    assert outcome.kit.lyrics.title != APPROVED_TITLE
    assert len(outcome.kit.lyrics.name_hook_sections) == 1
    assert outcome.is_complete is True
