"""Wire models for ``/orders``, and the point at which §12.3's masking becomes bytes.

Everything here is masked, at every role, with no unmasked variant — and that is a reading
of the matrix rather than a shortcut. §12.2 gives ``RECORDS_READ`` as **M** to all four
roles including OWNER, so there is no cell that returns a name in the clear from this
namespace. Plaintext is reachable only through ``POST /reveal``, which is a different
permission, a different route, a step-up, a reason code, an audit row and a record budget.
A ``to_view(..., is_unmasked=True)`` parameter here would be an argument that exists to be
passed ``True`` by the first caller who finds masking inconvenient, so the functions below
do not take one.

**Three fields carry the purge story and all three are always present.** ``recipientName``
is the masked name or ``null``; ``identityPurgedAt`` is when the 90-day sweep cleared it;
``isIdentityPurged`` is the derived flag. §12.3 is explicit that ``identity_purged_at`` is
always displayed, because "no name" and "name erased on schedule on 2026-05-14" are
different facts about a record and a panel that renders them the same way cannot answer the
question a data-subject request asks.

**Free text is a count.** ``noteChars`` and ``sttTranscriptChars`` are lengths, never
values; ``hasApprovedLyrics`` is a flag. The customer's note is what they wrote about a real
third party, and the lyric is the song itself.

The two purge clocks are independent, so ``noteExpiresAt`` and ``identityExpiresAt`` are
both on the wire: a brief whose note is gone and whose name is not is the normal state of a
30-to-90-day-old order, and one timestamp cannot describe it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from hbd.admin.schemas.common import ApiModel
from hbd.admin.schemas.page import PageMeta
from hbd.admin.serializers.redaction import mask_name, mask_telegram_user_id
from hbd.admin.serializers.retryability import is_retryable_code
from hbd.admin.serializers.stage_plan import (
    GreetingEvidence,
    StageOutcome,
    StagePlan,
    build_stage_plan,
)
from hbd.contracts import (
    AssetKind,
    Genre,
    Language,
    NameStrategy,
    Occasion,
    OrderState,
    Script,
    VoiceGender,
)
from hbd.db.admin.views import (
    AssetView,
    AttemptView,
    BriefView,
    OrderDetail,
    OrderListItem,
    Timeline,
    TimelineEvent,
    TimelineEventKind,
    TimelineSource,
)
from hbd.db.enums import GenerationKind
from hbd.db.retention import RetentionClass
from hbd.pipeline.events import PipelineStage

__all__ = [
    "OrderView",
    "OrdersPage",
    "BriefWireView",
    "AssetWireView",
    "AttemptWireView",
    "AttemptsPage",
    "AssetsPage",
    "StageStatusView",
    "StagePlanView",
    "TimelineEventView",
    "TimelineView",
    "OrderDetailView",
    "to_order_view",
    "to_brief_view",
    "to_asset_view",
    "to_attempt_view",
    "to_stage_plan_view",
    "to_timeline_view",
    "to_order_detail_view",
]


class OrderView(ApiModel):
    """One row of ``/orders``. Masked, and honest about what a purge removed."""

    id: UUID
    telegram_user_id: int
    telegram_user_id_masked: str
    state: OrderState
    is_paid: bool
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None
    #: Operator triage text from a closed vocabulary — never a customer's words.
    failed_reason: str | None
    is_failed_reason_retryable: bool | None
    is_brief_present: bool
    #: First grapheme cluster + ``•••``, or ``null`` when the identity was purged.
    recipient_name: str | None
    is_identity_purged: bool
    identity_purged_at: datetime | None
    note_purged_at: datetime | None
    occasion: Occasion | None
    genre: Genre | None
    output_language: Language | None
    asset_count: int
    has_assets: bool


class OrdersPage(ApiModel):
    items: list[OrderView]
    meta: PageMeta


class BriefWireView(ApiModel):
    """The brief, with both retention clocks and no free text."""

    id: UUID
    occasion: Occasion
    genre: Genre
    vocal_gender: VoiceGender
    ui_language: Language
    output_language: Language
    event_day: int | None
    event_month: int | None

    recipient_name: str | None
    recipient_script: Script | None
    recipient_language: Language | None
    #: How many ranked orthographies were stored. The texts are vendor input and never cross.
    candidate_count: int
    identity_expires_at: datetime
    identity_purged_at: datetime | None
    is_identity_purged: bool

    #: Length of the customer's note. The note itself needs ``POST /reveal``.
    note_chars: int | None
    has_approved_lyrics: bool
    note_expires_at: datetime
    note_purged_at: datetime | None
    is_note_purged: bool


class AssetWireView(ApiModel):
    """Metadata for one delivered file. Never its bytes, never the lyric-sheet payload."""

    id: UUID
    order_id: UUID
    kind: AssetKind
    variant_index: int
    mime: str
    size_bytes: int
    duration_s: float
    sha256: str
    loudness_lufs: float | None
    persona_id: str | None
    #: ``false`` for assets written before ``_replace_assets`` recorded the key. The retention
    #: sweep cannot delete archived bytes it has no key for, so this is surfaced rather than
    #: hidden: an asset without one is a file that will outlive its row.
    is_storage_key_recorded: bool
    has_telegram_file_id: bool
    name_candidate_strategy: NameStrategy | None
    name_candidate_rank: int | None
    retention_class: RetentionClass
    expires_at: datetime
    created_at: datetime


class AssetsPage(ApiModel):
    items: list[AssetWireView]
    meta: PageMeta


class AttemptWireView(ApiModel):
    """One row of the render ledger.

    ``costUsd`` and ``latencyMs`` are ``null`` rather than ``0`` for every row written before
    Phase 5 instruments them, and ``isInstrumented`` says which kind of row this is. The
    column defaults are ``0.0`` and ``0``; rendering those as money would be a confident lie
    in the one screen an operator uses to decide what to spend.
    """

    id: UUID
    order_id: UUID | None
    kind: GenerationKind
    sequence: int
    attempt: int
    provider: str | None
    provider_remote_id: str | None
    language: Language | None
    is_success: bool
    is_orphaned: bool

    name_candidate_strategy: NameStrategy | None
    name_candidate_rank: int | None
    is_name_verified: bool | None
    match_confidence: float | None

    #: Masked like any other name: this is the orthography a vendor was asked to sing.
    name_candidate: str | None
    identity_purged_at: datetime | None
    #: Length only — the transcript is a near-verbatim copy of the whole song.
    stt_transcript_chars: int | None
    text_purged_at: datetime | None

    error_code: str | None
    #: The operator message the raising layer wrote. A closed-vocabulary code plus our own
    #: prose; never a customer's words.
    error_message: str | None
    is_retryable: bool | None

    cost_usd: float | None
    cost_source: str | None
    latency_ms: int | None
    is_instrumented: bool
    created_at: datetime


class AttemptsPage(ApiModel):
    items: list[AttemptWireView]
    meta: PageMeta


class StageStatusView(ApiModel):
    """One stage of the reconstructed plan."""

    stage: PipelineStage
    outcome: StageOutcome
    attempt_count: int
    failed_attempt_count: int
    error_code: str | None
    is_retryable: bool | None
    is_greeting_stage: bool


class StagePlanView(ApiModel):
    """The plan, and everything the reconstruction cannot promise.

    ``isInferred`` is always ``true`` and the SPA renders it as a caption, not as a debug
    flag: there is no order-event table, so the path through the pipeline is deduced from
    attempts, assets and four mutable timestamps.
    """

    stages: list[StageStatusView]
    greeting_evidence: GreetingEvidence
    is_conclusive: bool
    scheduled_stage_count: int
    is_inferred: bool


class TimelineEventView(ApiModel):
    """One point on the merged timeline. ``label`` is closed-vocabulary, never free text."""

    at: datetime
    kind: TimelineEventKind
    source: TimelineSource
    is_inferred: bool
    label: str | None
    reference_id: UUID | None


class TimelineView(ApiModel):
    """The events, plus which sources this deployment could have contributed.

    ``unavailableSources`` is what lets the SPA render "chat capture is not enabled in this
    deployment" instead of an empty section that reads as "nothing was said".
    """

    events: list[TimelineEventView]
    available_sources: list[TimelineSource]
    unavailable_sources: list[TimelineSource]


class OrderDetailView(ApiModel):
    """``/orders/{id}`` — everything the detail screen renders, in one response."""

    order: OrderView
    brief: BriefWireView | None
    assets: list[AssetWireView]
    attempts: list[AttemptWireView]
    stage_plan: StagePlanView
    timeline: TimelineView


# ---------------------------------------------------------------------------
# projections
# ---------------------------------------------------------------------------
def to_order_view(item: OrderListItem) -> OrderView:
    """Project one order onto the wire. Masked; there is no unmasked variant by design."""
    return OrderView(
        id=item.id,
        telegram_user_id=item.telegram_user_id,
        telegram_user_id_masked=mask_telegram_user_id(item.telegram_user_id),
        state=item.state,
        is_paid=item.is_paid,
        correlation_id=item.correlation_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        delivered_at=item.delivered_at,
        failed_reason=item.failed_reason,
        is_failed_reason_retryable=is_retryable_code(item.failed_reason),
        is_brief_present=item.is_brief_present,
        recipient_name=mask_name(item.recipient_name_display),
        is_identity_purged=item.is_identity_purged,
        identity_purged_at=item.identity_purged_at,
        note_purged_at=item.note_purged_at,
        occasion=item.occasion,
        genre=item.genre,
        output_language=item.output_language,
        asset_count=item.asset_count,
        has_assets=item.has_assets,
    )


def to_brief_view(brief: BriefView) -> BriefWireView:
    return BriefWireView(
        id=brief.id,
        occasion=brief.occasion,
        genre=brief.genre,
        vocal_gender=brief.vocal_gender,
        ui_language=brief.ui_language,
        output_language=brief.output_language,
        event_day=brief.event_day,
        event_month=brief.event_month,
        recipient_name=mask_name(brief.recipient_name_display),
        recipient_script=brief.recipient_script,
        recipient_language=brief.recipient_language,
        candidate_count=brief.candidate_count,
        identity_expires_at=brief.identity_expires_at,
        identity_purged_at=brief.identity_purged_at,
        is_identity_purged=brief.is_identity_purged,
        note_chars=brief.note_chars,
        has_approved_lyrics=brief.has_approved_lyrics,
        note_expires_at=brief.note_expires_at,
        note_purged_at=brief.note_purged_at,
        is_note_purged=brief.is_note_purged,
    )


def to_asset_view(asset: AssetView) -> AssetWireView:
    return AssetWireView(
        id=asset.id,
        order_id=asset.order_id,
        kind=asset.kind,
        variant_index=asset.variant_index,
        mime=asset.mime,
        size_bytes=asset.size_bytes,
        duration_s=asset.duration_s,
        sha256=asset.sha256,
        loudness_lufs=asset.loudness_lufs,
        persona_id=asset.persona_id,
        is_storage_key_recorded=asset.storage_key is not None,
        has_telegram_file_id=asset.has_telegram_file_id,
        name_candidate_strategy=asset.name_candidate_strategy,
        name_candidate_rank=asset.name_candidate_rank,
        retention_class=asset.retention_class,
        expires_at=asset.expires_at,
        created_at=asset.created_at,
    )


def to_attempt_view(attempt: AttemptView) -> AttemptWireView:
    """Project one attempt. The candidate text is a name and is masked like every other."""
    telemetry = attempt.telemetry
    return AttemptWireView(
        id=attempt.id,
        order_id=attempt.order_id,
        kind=attempt.kind,
        sequence=attempt.sequence,
        attempt=attempt.attempt,
        provider=attempt.provider,
        provider_remote_id=attempt.provider_remote_id,
        language=attempt.language,
        is_success=attempt.is_success,
        is_orphaned=attempt.is_orphaned,
        name_candidate_strategy=attempt.name_candidate_strategy,
        name_candidate_rank=attempt.name_candidate_rank,
        is_name_verified=attempt.is_name_verified,
        match_confidence=attempt.match_confidence,
        name_candidate=mask_name(attempt.name_candidate_text),
        identity_purged_at=attempt.identity_purged_at,
        stt_transcript_chars=attempt.stt_transcript_chars,
        text_purged_at=attempt.text_purged_at,
        error_code=attempt.error_code,
        error_message=attempt.error_message,
        is_retryable=is_retryable_code(attempt.error_code),
        cost_usd=telemetry.cost_usd,
        cost_source=(None if telemetry.cost_source is None else str(telemetry.cost_source)),
        latency_ms=telemetry.latency_ms,
        is_instrumented=telemetry.is_instrumented,
        created_at=attempt.created_at,
    )


def to_stage_plan_view(plan: StagePlan) -> StagePlanView:
    return StagePlanView(
        stages=[
            StageStatusView(
                stage=status.stage,
                outcome=status.outcome,
                attempt_count=status.attempt_count,
                failed_attempt_count=status.failed_attempt_count,
                error_code=status.error_code,
                is_retryable=status.is_retryable,
                is_greeting_stage=status.is_greeting_stage,
            )
            for status in plan.stages
        ],
        greeting_evidence=plan.greeting_evidence,
        is_conclusive=plan.is_conclusive,
        scheduled_stage_count=plan.scheduled_stage_count,
        is_inferred=plan.is_inferred,
    )


def _to_timeline_event(event: TimelineEvent) -> TimelineEventView:
    return TimelineEventView(
        at=event.at,
        kind=event.kind,
        source=event.source,
        is_inferred=event.is_inferred,
        label=event.label,
        reference_id=event.reference_id,
    )


def to_timeline_view(timeline: Timeline) -> TimelineView:
    return TimelineView(
        events=[_to_timeline_event(event) for event in timeline.events],
        available_sources=list(timeline.available_sources),
        unavailable_sources=list(timeline.unavailable_sources),
    )


def to_order_detail_view(detail: OrderDetail) -> OrderDetailView:
    """Assemble the detail response, including the reconstructed stage plan."""
    return OrderDetailView(
        order=to_order_view(detail.order),
        brief=None if detail.brief is None else to_brief_view(detail.brief),
        assets=[to_asset_view(asset) for asset in detail.assets],
        attempts=[to_attempt_view(attempt) for attempt in detail.attempts],
        stage_plan=to_stage_plan_view(
            build_stage_plan(detail.order, detail.assets, detail.attempts)
        ),
        timeline=to_timeline_view(detail.timeline),
    )
