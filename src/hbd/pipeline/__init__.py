"""The generation pipeline: a ``Brief`` in, a ``Kit`` out.

Import surface for the rest of the system. The bot needs ``ProgressEvent`` (to render its
in-place progress message), ``JOB_NAME``/``job_id_for`` (to enqueue), and ``KitPipeline``
plus its ports (to wire everything together at startup). Nothing else in here is public.
"""

from __future__ import annotations

from hbd.pipeline.assembly import order_workspace
from hbd.pipeline.content import LlmContentWriter
from hbd.pipeline.events import (
    STAGE_MESSAGE_KEYS,
    STAGE_ORDER,
    NullProgressSink,
    PipelineStage,
    ProgressEvent,
    ProgressReporter,
    ProgressSink,
    ProgressStatus,
)
from hbd.pipeline.greetings import GreetingBatch, render_greetings
from hbd.pipeline.idempotency import idempotency_key
from hbd.pipeline.moderation import AllowAllModerator, LlmModerator
from hbd.pipeline.name_stage import SongRender, best_similarity, render_song
from hbd.pipeline.orchestrator import KitPipeline
from hbd.pipeline.outcome import PipelineGap, PipelineOutcome, RunLedger, StepTiming
from hbd.pipeline.personas import select_voices
from hbd.pipeline.plan_builder import build_composition_plan, with_name_candidate
from hbd.pipeline.ports import Clock, ContentWriter, Moderator, NameSimilarity, Sleeper
from hbd.pipeline.retry import RetryPolicy, call_with_retry
from hbd.pipeline.worker import JOB_NAME, build_worker_settings, generate_kit, job_id_for

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
