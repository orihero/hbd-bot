"""The pipeline stage plan for one order, reconstructed from the rows that survived it.

An operator's first question about a failed order is "how far did it get?", and the system
does not record the answer. There is no order-event table: ``orders`` carries ``state``,
``created_at``, ``updated_at`` and ``delivered_at`` and nothing else, so a run's path through
:data:`~bayram.pipeline.events.STAGE_ORDER` has to be **reconstructed** from the attempts it
wrote and the assets it produced. Everything this module returns is therefore inferred, and
:class:`StagePlan` says so in a field rather than in a comment nobody serialises.

Two inferences are worth stating outright, because both can be wrong in a way that matters.

**Absence of evidence is not evidence of absence, and the plan distinguishes them.** With
``greetings_per_kit`` at zero the orchestrator skips ``WRITING_SCRIPTS`` and
``RENDERING_GREETINGS`` entirely (:func:`~bayram.pipeline.events.scheduled_stages`), so a
nine-stage run is the normal shape of the song-only kit this product now sells. But an order
that failed at ``WRITING_LYRICS`` also has no greeting rows — and it had no chance to write
any. The admin process cannot tell the two apart from configuration, because it does not load
``Settings`` at all (D10) and, more fundamentally, because the setting's value *today* is not
the value the order ran under. So the plan reports what it saw
(:class:`GreetingEvidence`) and whether the order has finished
(:attr:`StagePlan.is_conclusive`); a still-running order's missing greetings are labelled
unobserved, not skipped.

**A stage with no attempt row is not a stage that did not run.** ``VALIDATING``,
``AUTHORIZING``, ``MODERATING``, ``WRITING_SCRIPTS``, ``POST_PROCESSING``, ``PERSISTING`` and
``DELIVERING`` write no ``generation_attempts`` row of their own, so they can never be
observed here — only the four stages that make a vendor call can. Those seven report
:attr:`StageOutcome.NOT_OBSERVED` for every order that ever ran, including successful ones,
and the panel renders that as "no record", never as "did not run".

The one thing that is *not* inferred is the failure itself: ``orders.failed_reason`` and the
failed attempt's ``error_code`` are recorded values, and :func:`~is_retryable_code` reads the
retry verdict off the class that owns the code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from bayram.admin.serializers.retryability import is_retryable_code
from bayram.contracts import AssetKind, OrderState
from bayram.db.admin.views import AssetView, AttemptView, OrderListItem
from bayram.db.enums import GenerationKind
from bayram.pipeline.events import GREETING_STAGES, STAGE_ORDER, PipelineStage

__all__ = [
    "StageOutcome",
    "GreetingEvidence",
    "StageStatus",
    "StagePlan",
    "build_stage_plan",
]

#: Which stage a ``generation_attempts`` row is evidence of. Only the vendor-calling stages
#: appear: the rest write no attempt and are unobservable here by construction.
#:
#: ``NAME_PREVIEW`` is deliberately absent. It is a pre-order render — the attempt carries no
#: ``order_id`` — so attributing it to ``VERIFYING_NAME`` would put work that happened before
#: the order existed inside the order's own timeline. ``COVER`` is absent for the opposite
#: reason: it is an asset kind with no stage of its own in ``STAGE_ORDER``.
_STAGE_OF_KIND: Final[dict[GenerationKind, PipelineStage]] = {
    GenerationKind.LYRICS: PipelineStage.WRITING_LYRICS,
    GenerationKind.SONG: PipelineStage.COMPOSING_SONG,
    GenerationKind.SONG_INPAINT: PipelineStage.COMPOSING_SONG,
    GenerationKind.NAME_VERIFICATION: PipelineStage.VERIFYING_NAME,
    GenerationKind.GREETING: PipelineStage.RENDERING_GREETINGS,
}

#: Reaching one of these means the order stopped moving, which is what makes a missing
#: greeting stage conclusive rather than merely unobserved.
_TERMINAL_STATES: Final[frozenset[OrderState]] = frozenset(
    {OrderState.DELIVERED, OrderState.FAILED, OrderState.CANCELLED}
)


class StageOutcome(StrEnum):
    """What the surviving rows say about one stage.

    ``NOT_OBSERVED`` is the honest default and by far the most common value: seven of the
    eleven stages write nothing, so it means "this layer has no record", never "it was
    skipped". ``SKIPPED`` is reserved for the greeting stages of a conclusively finished
    order that produced no greeting of any kind.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_OBSERVED = "not_observed"
    SKIPPED = "skipped"


class GreetingEvidence(StrEnum):
    """Whether this order left any trace of the two greeting stages.

    ``ABSENT`` on a finished order is the song-only kit. ``ABSENT`` on an order still in
    flight means nothing at all yet, which is why the two are one enum with
    :attr:`StagePlan.is_conclusive` beside it rather than a bare boolean.
    """

    PRESENT = "present"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class StageStatus:
    """One row of the plan."""

    stage: PipelineStage
    outcome: StageOutcome
    #: Attempts attributed to this stage, successful and failed alike. Zero for every stage
    #: that writes no attempt row.
    attempt_count: int
    failed_attempt_count: int
    #: The last failure's code, when this stage has one. Recorded, not inferred.
    error_code: str | None
    #: ``None`` when no class in ``bayram.errors`` claims the code — see
    #: :mod:`bayram.admin.serializers.retryability`.
    is_retryable: bool | None
    #: True for the two stages a song-only kit does not run, so the SPA can ghost them
    #: without restating :data:`~bayram.pipeline.events.GREETING_STAGES`.
    is_greeting_stage: bool


@dataclass(frozen=True, slots=True)
class StagePlan:
    """Every stage in display order, plus what the reconstruction can and cannot claim."""

    stages: tuple[StageStatus, ...]
    greeting_evidence: GreetingEvidence
    #: The order has reached a terminal state, so "no greeting rows" means the kit had none.
    #: While false, a missing stage is a stage that has not happened *yet*.
    is_conclusive: bool
    #: How many stages this run is understood to have scheduled — nine for a song-only kit,
    #: eleven with greetings. The denominator the progress bar used, reconstructed.
    scheduled_stage_count: int
    #: Always true. There is no order-event table; every ordering and every outcome here is
    #: deduced from attempts, assets and four mutable timestamps.
    is_inferred: bool = True


def build_stage_plan(
    order: OrderListItem, assets: tuple[AssetView, ...], attempts: tuple[AttemptView, ...]
) -> StagePlan:
    """Reconstruct the plan. Pure — no session, no clock, no settings."""
    evidence = _greeting_evidence(assets, attempts)
    is_conclusive = order.state in _TERMINAL_STATES
    is_greetings_scheduled = evidence is GreetingEvidence.PRESENT
    by_stage = _attempts_by_stage(attempts)
    stages = tuple(
        _status(
            stage,
            by_stage.get(stage, ()),
            order=order,
            is_greetings_scheduled=is_greetings_scheduled,
            is_conclusive=is_conclusive,
        )
        for stage in STAGE_ORDER
    )
    return StagePlan(
        stages=stages,
        greeting_evidence=evidence,
        is_conclusive=is_conclusive,
        scheduled_stage_count=(
            len(STAGE_ORDER)
            if is_greetings_scheduled or not is_conclusive
            else len(STAGE_ORDER) - len(GREETING_STAGES)
        ),
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _greeting_evidence(
    assets: tuple[AssetView, ...], attempts: tuple[AttemptView, ...]
) -> GreetingEvidence:
    """Both halves count. A greeting that rendered and then failed to store left an attempt
    and no asset; one restored from a ``tg_file_id`` on a re-delivery could leave the
    reverse. Either trace proves the kit was configured to carry greetings."""
    has_asset = any(asset.kind is AssetKind.GREETING for asset in assets)
    has_attempt = any(attempt.kind is GenerationKind.GREETING for attempt in attempts)
    if has_asset or has_attempt:
        return GreetingEvidence.PRESENT
    return GreetingEvidence.ABSENT


def _attempts_by_stage(
    attempts: tuple[AttemptView, ...],
) -> dict[PipelineStage, tuple[AttemptView, ...]]:
    """Group attempts under the stage that made them, dropping kinds no stage claims."""
    grouped: dict[PipelineStage, list[AttemptView]] = {}
    for attempt in attempts:
        stage = _STAGE_OF_KIND.get(attempt.kind)
        if stage is not None:
            grouped.setdefault(stage, []).append(attempt)
    return {stage: tuple(rows) for stage, rows in grouped.items()}


def _status(
    stage: PipelineStage,
    attempts: tuple[AttemptView, ...],
    *,
    order: OrderListItem,
    is_greetings_scheduled: bool,
    is_conclusive: bool,
) -> StageStatus:
    """One stage's verdict, and the failure that explains it when there is one."""
    is_greeting_stage = stage in GREETING_STAGES
    failures = tuple(attempt for attempt in attempts if not attempt.is_success)
    # The newest failure explains the stage: an earlier one was retried past, and showing
    # the first would name a code the operator has already seen recovered from.
    last_failure = max(failures, key=lambda a: a.created_at, default=None)
    error_code = last_failure.error_code if last_failure is not None else None
    return StageStatus(
        stage=stage,
        outcome=_outcome(
            attempts,
            failures,
            stage=stage,
            order=order,
            is_greeting_stage=is_greeting_stage,
            is_greetings_scheduled=is_greetings_scheduled,
            is_conclusive=is_conclusive,
        ),
        attempt_count=len(attempts),
        failed_attempt_count=len(failures),
        error_code=error_code,
        is_retryable=is_retryable_code(error_code),
        is_greeting_stage=is_greeting_stage,
    )


def _outcome(
    attempts: tuple[AttemptView, ...],
    failures: tuple[AttemptView, ...],
    *,
    stage: PipelineStage,
    order: OrderListItem,
    is_greeting_stage: bool,
    is_greetings_scheduled: bool,
    is_conclusive: bool,
) -> StageOutcome:
    """A recorded success beats a recorded failure: the stage was retried and got through."""
    if attempts:
        return StageOutcome.SUCCEEDED if len(failures) < len(attempts) else StageOutcome.FAILED
    if is_greeting_stage and is_conclusive and not is_greetings_scheduled:
        return StageOutcome.SKIPPED
    # ``DELIVERING`` writes no attempt row, but ``delivered_at`` is a recorded fact about it
    # — the one unobservable stage this layer can still speak to.
    if stage is PipelineStage.DELIVERING and order.delivered_at is not None:
        return StageOutcome.SUCCEEDED
    return StageOutcome.NOT_OBSERVED
