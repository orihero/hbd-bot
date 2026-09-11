"""The generation pipeline: a ``Brief`` in, a ``Kit`` out.

Import surface for the rest of the system. The bot needs ``ProgressEvent`` (to render its
in-place progress message), ``JOB_NAME``/``job_id_for`` (to enqueue), and ``KitPipeline``
plus its ports (to wire everything together at startup). Nothing else in here is public.
"""

from __future__ import annotations

from bayram.pipeline.assembly import order_workspace
from bayram.pipeline.content import LlmContentWriter
from bayram.pipeline.events import (
    STAGE_MESSAGE_KEYS,
    STAGE_ORDER,
    NullProgressSink,
    PipelineStage,
    ProgressEvent,
    ProgressReporter,
    ProgressSink,
    ProgressStatus,
)
from bayram.pipeline.greetings import GreetingBatch, render_greetings
from bayram.pipeline.idempotency import idempotency_key
from bayram.pipeline.moderation import AllowAllModerator, LlmModerator
from bayram.pipeline.name_stage import SongRender, best_similarity, render_song
from bayram.pipeline.orchestrator import KitPipeline
from bayram.pipeline.outcome import PipelineGap, PipelineOutcome, RunLedger, StepTiming
from bayram.pipeline.personas import select_voices
from bayram.pipeline.plan_builder import build_composition_plan, with_name_candidate
from bayram.pipeline.ports import Clock, ContentWriter, Moderator, NameSimilarity, Sleeper
from bayram.pipeline.retry import RetryPolicy, call_with_retry
from bayram.pipeline.worker import JOB_NAME, build_worker_settings, generate_kit, job_id_for

__all__ = [
    # Orchestration
    "KitPipeline",
    "order_workspace",
    "PipelineOutcome",
    "PipelineGap",
    "StepTiming",
    "RunLedger",
    # Progress
    "PipelineStage",
    "ProgressStatus",
    "ProgressEvent",
    "ProgressSink",
    "ProgressReporter",
    "NullProgressSink",
    "STAGE_ORDER",
    "STAGE_MESSAGE_KEYS",
    # Ports and their shipped implementations
    "ContentWriter",
    "Moderator",
    "NameSimilarity",
    "Clock",
    "Sleeper",
    "LlmContentWriter",
    "LlmModerator",
    "AllowAllModerator",
    # Stages, exposed for targeted reuse and testing
    "build_composition_plan",
    "with_name_candidate",
    "render_song",
    "SongRender",
    "best_similarity",
    "render_greetings",
    "GreetingBatch",
    "select_voices",
    "RetryPolicy",
    "call_with_retry",
    "idempotency_key",
    # Queue
    "JOB_NAME",
    "job_id_for",
    "generate_kit",
    "build_worker_settings",
]
