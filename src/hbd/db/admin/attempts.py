"""``/generations`` — the render-attempt explorer and the name-verification bake-off.

Two honesty problems shape this module.

**1. Cost and latency are not instrumented, and the panel must say so rather than show a
number.** ``generation_attempts.cost_usd`` defaults to ``0.0`` and ``latency_ms`` to ``0``.
The only writer in ``src/`` is ``repository._replace_verdicts``, through
``attempts.verdict_row_values``, which sets neither; ``GenerationAttemptRepository.record()``
has no call site at all. So every row in production reads ``$0.00`` / ``0 ms`` — which is
indistinguishable from a genuinely free, instantaneous vendor call, and rendering it as
money would be a confident lie in the one place an operator is deciding what to spend.
:func:`attempt_view` therefore reports ``None`` for both unless the row carries evidence of
having been measured, and :func:`is_cost_instrumented` gives the SPA the
``costTelemetry`` capability flag to branch on. Phase 5 turns both true by writing the
columns; nothing here has to change when it does.

**2. The transcript is the whole song.** Inpainting is enterprise-gated, so
``stt_transcript`` is a near-verbatim copy of a lyric the customer may have written. §6.7
routes free text through ``POST /reveal`` alone, so this module exposes its LENGTH and the
purge timestamps, never the text.

The name-verification analytics deliberately supersede
``GenerationAttemptRepository.strategy_stats``: that query has no time window, so a strategy
retired six months ago still drags on today's ranking, and the whole point of the bake-off
is deciding what ``HBD_NAME_CANDIDATE_ORDER`` should be *now*.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from hbd.contracts import NameStrategy
from hbd.db.admin.page import (
    BoundedTotal,
    Cursor,
    Page,
    PageRequest,
    bounded_total,
    build_page,
    keyset_order,
    keyset_predicate,
)
from hbd.db.admin.sql import TimeWindow, apply_in, apply_window, count_where
from hbd.db.admin.views import AttemptView, CostTelemetry, StrategyOutcome
from hbd.db.enums import GenerationKind
from hbd.db.models.generation_attempt import GenerationAttemptRow

__all__ = [
    "AttemptFilters",
    "attempt_view",
    "list_attempts",
    "count_attempts",
    "get_attempt",
    "strategy_outcomes",
    "is_cost_instrumented",
    "is_latency_instrumented",
]


@dataclass(frozen=True, slots=True)
class AttemptFilters:
    """§6.7's filter set for the generation explorer."""

    kinds: tuple[GenerationKind, ...] = ()
    provider: str | None = None
    is_success: bool | None = None
    error_code: str | None = None
    strategy: NameStrategy | None = None
    order_id: UUID | None = None
    #: ``True`` selects attempts whose order is gone or never existed — a name preview, or a
    #: render whose order was deleted. ``ON DELETE SET NULL`` makes both look the same, which
    #: is deliberate: the tuning signal must outlive the order.
    is_orphaned: bool | None = None
    window: TimeWindow | None = None


def attempt_view(row: GenerationAttemptRow) -> AttemptView:
    """Build one attempt view. Total over every purge state and every instrumentation state."""
    return AttemptView(
        id=row.id,
        order_id=row.order_id,
        kind=row.kind,
        sequence=row.sequence,
        attempt=row.attempt,
        provider=row.provider,
        provider_remote_id=row.provider_remote_id,
        language=row.language,
        is_success=row.is_success,
        name_candidate_strategy=row.name_candidate_strategy,
        name_candidate_rank=row.name_candidate_rank,
        is_name_verified=row.is_name_verified,
        match_confidence=row.match_confidence,
        name_candidate_text=row.name_candidate_text,
        identity_purged_at=row.identity_purged_at,
        stt_transcript_chars=(len(row.stt_transcript) if row.stt_transcript is not None else None),
        text_purged_at=row.text_purged_at,
        error_code=row.error_code,
        error_message=row.error_message,
        telemetry=_telemetry(row),
        created_at=row.created_at,
    )


async def list_attempts(
    session: AsyncSession, *, filters: AttemptFilters, request: PageRequest
) -> Page[AttemptView]:
    """One keyset page of attempts, newest first."""
    statement = _filtered(filters)
    resume = keyset_predicate(
        GenerationAttemptRow.created_at, GenerationAttemptRow.id, request.cursor
    )
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(
        *keyset_order(GenerationAttemptRow.created_at, GenerationAttemptRow.id)
    ).limit(request.fetch_limit)
    rows = (await session.execute(statement)).scalars().all()
    return build_page([attempt_view(row) for row in rows], request, _cursor_of)


async def count_attempts(session: AsyncSession, *, filters: AttemptFilters) -> BoundedTotal:
    """``?withTotal=true`` for the same filter set."""
    return await bounded_total(session, _filtered(filters))


async def get_attempt(session: AsyncSession, attempt_id: UUID) -> AttemptView | None:
    """One attempt by id, or ``None`` — the caller answers 404."""
    row = await session.get(GenerationAttemptRow, attempt_id)
    return None if row is None else attempt_view(row)


async def strategy_outcomes(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[StrategyOutcome, ...]:
    """Verification rate per candidate orthography, best first, over an optional window.

    One ``GROUP BY``, no Python arithmetic over rows: the ratio is computed from two counts
    the database returns, and the ordering is applied to the handful of grouped results.
    Rows where verification did not run (``is_name_verified IS NULL``) are excluded from
    BOTH counts — counting them as failures would penalise every strategy for a disabled
    verifier, which is the exact opposite of what the bake-off is measuring.
    """
    statement = sa.select(
        GenerationAttemptRow.name_candidate_strategy,
        sa.func.count().label("attempts"),
        count_where(GenerationAttemptRow.is_name_verified.is_(True)).label("verified"),
    ).where(
        GenerationAttemptRow.name_candidate_strategy.is_not(None),
        GenerationAttemptRow.is_name_verified.is_not(None),
    )
    statement = apply_window(statement, GenerationAttemptRow.created_at, window)
    rows = (
        await session.execute(statement.group_by(GenerationAttemptRow.name_candidate_strategy))
    ).all()
    outcomes = tuple(
        StrategyOutcome(strategy=strategy, attempts=int(attempts), verified=int(verified))
        for strategy, attempts, verified in rows
        if strategy is not None
    )
    # Volume breaks a rate tie so one lucky success never outranks four hundred attempts.
    return tuple(sorted(outcomes, key=lambda o: (o.verification_rate, o.attempts), reverse=True))


async def is_cost_instrumented(session: AsyncSession) -> bool:
    """True once any attempt row carries a cost. The ``costTelemetry`` capability.

    ``LIMIT 1`` on an existence probe rather than a ``COUNT``: the answer is a boolean and
    the table has no index on ``cost_usd``, so stopping at the first hit is the difference
    between a scan that ends immediately and one that does not.
    """
    return await _exists(session, GenerationAttemptRow.cost_usd > 0.0)


async def is_latency_instrumented(session: AsyncSession) -> bool:
    """True once any attempt row carries a latency.

    Reported separately from cost because Phase 5 could plausibly land one without the
    other, and a UI that shows p95 latency while cost reads "not instrumented" is telling
    the truth twice rather than averaging two different claims into one flag.
    """
    return await _exists(session, GenerationAttemptRow.latency_ms > 0)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _telemetry(row: GenerationAttemptRow) -> CostTelemetry:
    """What this row can honestly say about money and time.

    A zero is treated as "never written" rather than as a measurement. That costs nothing
    real — a vendor call that genuinely took zero milliseconds or cost exactly zero dollars
    does not happen — and it is the only reading that does not fabricate a data point out
    of a column default.
    """
    has_cost = row.cost_usd > 0.0
    has_latency = row.latency_ms > 0
    return CostTelemetry(
        cost_usd=row.cost_usd if has_cost else None,
        cost_source=row.cost_source if has_cost else None,
        latency_ms=row.latency_ms if has_latency else None,
    )


def _filtered(filters: AttemptFilters) -> Select[tuple[GenerationAttemptRow]]:
    statement = sa.select(GenerationAttemptRow)
    statement = apply_in(statement, GenerationAttemptRow.kind, filters.kinds)
    statement = apply_window(statement, GenerationAttemptRow.created_at, filters.window)
    if filters.provider is not None:
        statement = statement.where(GenerationAttemptRow.provider == filters.provider)
    if filters.is_success is not None:
        statement = statement.where(GenerationAttemptRow.is_success.is_(filters.is_success))
    if filters.error_code is not None:
        statement = statement.where(GenerationAttemptRow.error_code == filters.error_code)
    if filters.strategy is not None:
        statement = statement.where(
            GenerationAttemptRow.name_candidate_strategy == filters.strategy
        )
    if filters.order_id is not None:
        statement = statement.where(GenerationAttemptRow.order_id == filters.order_id)
    if filters.is_orphaned is not None:
        statement = statement.where(
            GenerationAttemptRow.order_id.is_(None)
            if filters.is_orphaned
            else GenerationAttemptRow.order_id.is_not(None)
        )
    return statement


def _cursor_of(item: AttemptView) -> Cursor:
    return Cursor(at=item.created_at, id=item.id)


async def _exists(session: AsyncSession, condition: sa.ColumnElement[bool]) -> bool:
    probe = await session.scalar(
        sa.select(sa.literal(1)).select_from(GenerationAttemptRow).where(condition).limit(1)
    )
    return probe is not None
