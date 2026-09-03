"""``orders.failed_reason``: triage vocabulary, never a word the customer wrote.

Split out of ``test_orchestrator.py``, which had grown past the repo's 800-line cap. This is
a self-contained concern with a self-contained rule, so it is a clean seam: everything here
is about ONE column and the one thing that column must never contain.

The order row outlives the brief purge (SoW DAT-3) — the recipient's name, the sender's note
and the lyric are deleted on their own clocks while this row survives forever as the tax
record — so anything written to ``failed_reason`` escapes the purge. That is why the ABSENCE
assertions below are the point rather than a garnish.
"""

from __future__ import annotations

from hbd.contracts import Brief, Err, Order, OrderState, Result, err
from hbd.db.models.order import FAILED_REASON_LENGTH
from hbd.errors import (
    ErrorCode,
    ModerationRejectedError,
    StorageError,
)
from hbd.pipeline.events import PipelineStage
from hbd.pipeline.outcome import PipelineOutcome
from tests.conftest import UZBEK_NAME_CANONICAL, make_brief, make_order, recipient_of
from tests.test_pipeline.conftest import Studio, value_of


async def _run(studio: Studio, order: Order) -> PipelineOutcome:
    """Run the pipeline and unwrap. Same helper ``test_orchestrator.py`` keeps for itself —
    two lines duplicated is cheaper than a third module for one call."""
    return value_of(await studio.pipeline().run(order))


# ---------------------------------------------------------------------------
# orders.failed_reason
#
# Order 1251314e-2138-4d4e-a263-2874a0c08601 died at MODERATING with failed_reason NULL,
# so a content rejection and a vendor timeout were the same row and telling them apart
# meant replaying the customer's brief against the model by hand. These tests pin both
# halves of the fix: the reason is there, and it is triage vocabulary ONLY. The order row
# outlives the brief purge (SoW DAT-3), so anything personal written here escapes the
# purge — which is why the absence assertions below are the point, not a garnish.
# ---------------------------------------------------------------------------
#: The real note, near enough. Affectionate ribbing about a friend's beer habit.
INCIDENT_NOTE = "Pivo ichishni yqotiradi, logistica kompaniyasida ishlaydi!"

#: The real verdict the model returned, quoting the customer straight back at us.
INCIDENT_MODEL_REASON = (
    "Sender note references alcohol consumption ('Pivo ichishni yqotiradi' - loves "
    "drinking beer), which promotes alcohol and is not allowed."
)


class IncidentModerator:
    """The live rejection, frozen — context and all.

    ``LlmModerator`` really does put 200 characters of the note under ``note`` and the
    model's quote of it under ``reason``. That is right for the log, where redaction
    happens downstream, and catastrophic for a column that outlives the purge. A double
    that carried a sanitised context would be testing nothing at all.
    """

    async def review(self, brief: Brief) -> Result[None]:
        return err(
            ModerationRejectedError(
                "brief rejected by the moderation model",
                context={"reason": INCIDENT_MODEL_REASON, "note": INCIDENT_NOTE},
            )
        )


async def _failed_reason_of(studio: Studio, order: Order, **overrides: object) -> str:
    """Run the order to its death and hand back the reason the pipeline recorded."""
    await studio.pipeline(**overrides).run(order)
    assert studio.repository.states[-1] is OrderState.FAILED
    reason = studio.repository.failed_reasons[-1]
    assert reason is not None, "a FAILED transition must carry a reason"
    return reason


async def test_a_content_rejection_names_its_code_class_and_stage_on_the_order_row(
    studio: Studio,
) -> None:
    # Arrange
    order = studio.enrol(make_order(brief=make_brief(note=INCIDENT_NOTE)))

    # Act
    reason = await _failed_reason_of(studio, order, moderator=IncidentModerator())

    # Assert — the row alone now answers "why did this order die?".
    assert reason.startswith("CONTENT_REJECTED: ModerationRejectedError at moderating")
    assert ErrorCode.CONTENT_REJECTED.value in reason


async def test_a_failure_reason_never_carries_the_note_the_name_or_the_models_quote(
    studio: Studio,
) -> None:
    # Arrange
    order = studio.enrol(make_order(brief=make_brief(note=INCIDENT_NOTE)))

    # Act
    reason = await _failed_reason_of(studio, order, moderator=IncidentModerator())

    # Assert — THIS is the assertion the test exists for. Every one of these strings is
    # sitting in HbdError.context at the moment the reason is composed.
    assert INCIDENT_NOTE not in reason
    assert INCIDENT_MODEL_REASON not in reason
    assert UZBEK_NAME_CANONICAL not in reason
    assert recipient_of(order.brief).raw not in reason
    assert recipient_of(order.brief).lookup_key not in reason
    for word in INCIDENT_NOTE.replace(",", " ").split():
        assert word.casefold() not in reason.casefold(), f"{word!r} leaked out of the brief"
    for word in ("alcohol", "beer", "drinking"):
        assert word not in reason.casefold()


async def test_a_denylist_rejection_records_which_field_tripped_it_not_what_was_in_it(
    studio: Studio,
) -> None:
    # Arrange — the local denylist puts ``hit_in`` (a field label, ours) and
    # ``pattern_hit`` (the matched substring, the customer's) side by side in context.
    order = studio.enrol(make_order(brief=make_brief(note="I will kill him")))

    # Act
    reason = await _failed_reason_of(studio, order)

    # Assert
    assert "hit_in=note" in reason
    assert "kill" not in reason.casefold()


async def test_a_failure_after_the_song_names_the_stage_it_actually_died_in(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange — a storage outage at PERSISTING, which is nine stages past MODERATING.
    studio.repository.save_failures = [
        StorageError("db is down"),
        StorageError("db is still down"),
    ]

    # Act
    reason = await _failed_reason_of(studio, ready_order)

    # Assert
    assert reason.startswith("STORAGE_FAILED: StorageError at persisting")


async def test_a_failure_reason_fits_the_column_it_is_written_to(studio: Studio) -> None:
    # Arrange
    order = studio.enrol(make_order(brief=make_brief(note=INCIDENT_NOTE)))

    # Act
    reason = await _failed_reason_of(studio, order, moderator=IncidentModerator())

    # Assert — a reason too long for the column would abort the failure path itself.
    assert len(reason) <= FAILED_REASON_LENGTH


async def test_a_delivered_order_is_never_handed_a_failure_reason(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange / Act — the happy path walks LYRICS_READY, AUTHORIZED, GENERATING, DELIVERED.
    await _run(studio, ready_order)

    # Assert — nothing on a successful run may leave a rejection notice behind it.
    assert studio.repository.states[-1] is OrderState.DELIVERED
    assert studio.repository.failed_reasons == [None] * len(studio.repository.states)


async def test_a_retried_order_that_finally_delivers_clears_its_stale_reason(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange — the retry ladder: ARQ requeues a job that already failed once, so the
    # order carries a reason from the first attempt when the second one starts.
    studio.repository.save_failures = [
        StorageError("db is down"),
        StorageError("db is still down"),
    ]
    await studio.pipeline().run(ready_order)
    assert studio.repository.failed_reasons[-1] is not None

    # Act — the outage clears and the same order is run again.
    studio.repository.kits.pop(ready_order.id, None)
    await _run(studio, ready_order)

    # Assert — the last word on the order is DELIVERED with no reason attached.
    assert studio.repository.states[-1] is OrderState.DELIVERED
    assert studio.repository.failed_reasons[-1] is None


async def test_a_broken_progress_sink_does_not_stop_delivery(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.sink.should_raise = True

    # Act
    outcome = await _run(studio, ready_order)

    # Assert
    assert outcome.kit.song.path.exists()
    assert studio.sink.events == []


async def test_delivers_a_song_only_kit_when_greetings_are_switched_off(
    studio: Studio, ready_order: Order
) -> None:
    """``HBD_GREETINGS_PER_KIT=0`` sells the song and the sheet, and buys no speech.

    Zero is a deliberate product setting, not a failure: it must not be confused with
    "every greeting failed", which still fails the order.
    """
    # Arrange
    studio.settings = studio.settings.model_copy(update={"greetings_per_kit": 0})

    # Act
    outcome = await _run(studio, ready_order)

    # Assert
    kit = outcome.kit
    assert kit.greetings == ()
    assert kit.song is not None
    assert kit.lyric_sheet is not None
    assert studio.repository.states[-1] is OrderState.DELIVERED
    # No greetings means no speech was bought, and no voice catalogue was even fetched.
    assert studio.tts.calls == []


async def test_switching_greetings_off_still_fails_nothing_else(
    studio: Studio, ready_order: Order
) -> None:
    """The all-greetings-failed guard must keep working when greetings ARE requested."""
    # Arrange
    studio.settings = studio.settings.model_copy(update={"greetings_per_kit": 3})
    studio.tts.failing_personas = {"persona-1", "persona-2", "persona-3"}

    # Act
    result = await studio.pipeline().run(ready_order)

    # Assert
    assert isinstance(result, Err)
    assert studio.repository.states[-1] is OrderState.FAILED


async def test_no_greeting_stage_is_narrated_when_greetings_are_off(
    studio: Studio, ready_order: Order
) -> None:
    """The progress bar must not report writing or recording speech that never happens."""
    # Arrange
    studio.settings = studio.settings.model_copy(update={"greetings_per_kit": 0})

    # Act
    outcome = await _run(studio, ready_order)

    # Assert
    narrated = {stage for stage, _status in studio.sink.stages()}
    assert PipelineStage.WRITING_SCRIPTS.value not in narrated
    assert PipelineStage.RENDERING_GREETINGS.value not in narrated
    assert PipelineStage.COMPOSING_SONG.value in narrated
    assert outcome.kit.greetings == ()
