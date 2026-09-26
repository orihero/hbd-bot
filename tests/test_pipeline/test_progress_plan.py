"""Where AUTHORIZING sits in the plan the customer watches, and why it sits there.

Moving the render gate from fifth to second is the one change in this work that a customer
can see: the progress bar narrates a different second step and reaches every later step at a
different percentage. That makes it exactly the sort of change a reviewer skims, so the new
order is pinned here rather than left implicit in a tuple literal.

Two invariants are asserted, not one. The ORDER is the money decision — the gate must run
before anything that costs vendor money. The DERIVATIONS are the safety net: the display
plan, the progress denominator and the locale keys are all computed from ``STAGE_ORDER``, so
this test is what proves the move did not leave one of them behind.
"""

from __future__ import annotations

from bayram.bot.i18n import translate
from bayram.contracts import Language
from bayram.pipeline.events import (
    GREETING_STAGES,
    STAGE_MESSAGE_KEYS,
    STAGE_ORDER,
    PipelineStage,
    scheduled_stages,
)

#: Everything the pipeline pays a vendor for. VALIDATING is local, so it is not here — and
#: it is the only stage that may precede the gate.
_STAGES_THAT_SPEND_MONEY = (
    PipelineStage.MODERATING,
    PipelineStage.WRITING_LYRICS,
    PipelineStage.WRITING_SCRIPTS,
    PipelineStage.COMPOSING_SONG,
    PipelineStage.RENDERING_GREETINGS,
)


def test_the_gate_runs_before_anything_that_costs_vendor_money() -> None:
    """The whole reason the stage moved. Read this one before changing ``STAGE_ORDER``.

    AUTHORIZING used to be fifth, behind MODERATING and WRITING_SCRIPTS, so an account that
    was blocked or out of credits still bought two LLM calls on every confirm before being
    told no — and it could keep confirming.
    """
    # Arrange
    gate = STAGE_ORDER.index(PipelineStage.AUTHORIZING)

    # Act / Assert
    assert all(STAGE_ORDER.index(stage) > gate for stage in _STAGES_THAT_SPEND_MONEY)


def test_only_local_validation_precedes_the_gate() -> None:
    # Arrange / Act / Assert — one free step, then the answer. Nothing may be inserted
    # between them without a reason as good as the one above.
    assert STAGE_ORDER[:2] == (PipelineStage.VALIDATING, PipelineStage.AUTHORIZING)


def test_every_other_stage_kept_its_relative_order() -> None:
    """The move lifted one stage out; it did not reshuffle the run.

    Anything else changing here means the customer's narrative changed for a reason nobody
    wrote down.
    """
    # Arrange
    without_the_gate = tuple(
        stage for stage in STAGE_ORDER if stage is not PipelineStage.AUTHORIZING
    )

    # Act / Assert
    assert without_the_gate == (
        PipelineStage.VALIDATING,
        PipelineStage.MODERATING,
        PipelineStage.WRITING_LYRICS,
        PipelineStage.WRITING_SCRIPTS,
        PipelineStage.COMPOSING_SONG,
        PipelineStage.VERIFYING_NAME,
        PipelineStage.RENDERING_GREETINGS,
        PipelineStage.POST_PROCESSING,
        PipelineStage.PERSISTING,
        PipelineStage.DELIVERING,
    )


def test_the_shipped_plan_still_reaches_the_gate_second() -> None:
    """With ``greetings_per_kit`` at 0 two stages are skipped — neither of them the gate."""
    # Arrange / Act
    plan = scheduled_stages(has_greetings=False)

    # Assert
    assert plan.index(PipelineStage.AUTHORIZING) == 1
    assert set(STAGE_ORDER) - set(plan) == GREETING_STAGES


def test_the_gate_is_an_early_frame_of_the_bar_rather_than_a_middle_one() -> None:
    """The number the customer actually sees. It moved, and it moved in the right direction.

    Eleven display stages, so the gate is now the second of them instead of the fifth: a
    refusal arrives while the bar is still near the start, which is when "nothing was made
    and nothing is lost" is a sentence a customer can believe.
    """
    # Arrange
    gate = STAGE_ORDER.index(PipelineStage.AUTHORIZING)

    # Act / Assert
    assert gate / len(STAGE_ORDER) < 0.2


def test_the_locale_key_for_every_stage_survived_the_move() -> None:
    """``STAGE_MESSAGE_KEYS`` is derived from ``STAGE_ORDER``, so this is a real risk.

    A stage that lost its key renders a raw ``progress.*`` string into a customer's chat.
    Asserted in one language because the four catalogues are held in key-set lockstep by
    ``tests/test_bot/test_i18n.py``; what is checked here is that the keys still exist at all.
    """
    # Arrange / Act / Assert
    assert set(STAGE_MESSAGE_KEYS) == set(STAGE_ORDER)
    for stage in STAGE_ORDER:
        rendered = translate(STAGE_MESSAGE_KEYS[stage], Language.EN)
        assert rendered != STAGE_MESSAGE_KEYS[stage], stage
