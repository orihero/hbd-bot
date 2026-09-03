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
``GenerationAttemptRepository.strategy_stats``: that query is the bot's own, answers a
``Result`` and is not shaped for a screen, and the whole point of the bake-off is deciding
what ``HBD_NAME_CANDIDATE_ORDER`` should be *now*.

**3. A bake-off bar and a similarity histogram drawn from two different reads argue with
each other.** :func:`strategy_outcomes` answers the first half of "what should
``HBD_NAME_CANDIDATE_ORDER`` be" and nothing answers the second — where the verifier's
scores actually pile up relative to ``name_match_min_similarity``, and therefore whether the
threshold that decided every one of those verdicts is deciding coin flips.
:func:`name_analytics` answers both from ONE window over ONE population, plus the number the
screen exists for: how many scored attempts sit within :data:`NEAR_THRESHOLD_BAND` of the
threshold. That count is what makes moving the threshold a decision rather than a gamble —
it is the size of the population whose verdict would flip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
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
from hbd.db.admin.views import (
    AttemptView,
    CostTelemetry,
    NameAnalytics,
    SimilarityBucket,
    StrategyAnalysis,
    StrategyOutcome,
)
from hbd.db.enums import GenerationKind
from hbd.db.models.generation_attempt import GenerationAttemptRow

__all__ = [
    "AttemptFilters",
    "NEAR_THRESHOLD_BAND",
    "SIMILARITY_BUCKET_COUNT",
    "attempt_view",
    "list_attempts",
    "count_attempts",
    "get_attempt",
    "strategy_outcomes",
    "name_analytics",
    "is_cost_instrumented",
    "is_latency_instrumented",
]

#: How near the threshold counts as "near", from the Phase 2 acceptance. On the wire as
#: ``thresholdBand`` so the SPA reads the number rather than restating it, and inclusive at
#: BOTH edges: an attempt scoring exactly ``threshold + 0.05`` is one a five-hundredths move
#: would reach, which is the population the operator is being asked about.
NEAR_THRESHOLD_BAND: Final[float] = 0.05

#: Bars in the similarity histogram. Twenty because that is what the SPA's
#: ``buildSimilarityBuckets`` has always used — the server taking over the bucketing must
#: not silently redraw the chart at a different resolution — and because 0.05-wide bins make
#: the band above exactly one bucket either side of the threshold.
SIMILARITY_BUCKET_COUNT: Final[int] = 20


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


async def name_analytics(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    threshold: float | None = None,
    band: float = NEAR_THRESHOLD_BAND,
    bucket_count: int = SIMILARITY_BUCKET_COUNT,
) -> NameAnalytics:
    """The whole of ``/generations/names`` — bake-off, distribution and the cliff count.

    Three round trips, and each one is a different question that cannot be folded into the
    others:

    1. counts per strategy — attempts, verified, scored, and how many sit near the cliff;
    2. the histogram, grouped by strategy AND bucket, so one screen can draw the overall
       distribution and a per-strategy one without asking twice;
    3. an existence probe, deliberately ignoring ``window``, which is the ONLY thing that
       separates "nothing happened in the range you chose" from "verification has never run
       here". §11.4 renders those two as different screens and a zero cannot tell them apart.

    **The population is one predicate, used by all three**: a row with a candidate strategy
    on which verification actually ran. Rows where the verifier did not run are excluded
    from every count here — counting them as failures would penalise every orthography for a
    disabled verifier — and a scored row with no strategy cannot inform a candidate ORDER,
    so it is outside this endpoint's question. ``scored`` is therefore always ``<= attempts``
    and is reported separately rather than assumed equal: a verdict can be recorded without
    a similarity score, and the histogram's denominator is not the bake-off's.

    ``threshold`` is ``None`` when the deployment has not published
    ``name_match_min_similarity``. Then ``near_threshold`` is ``None`` — never ``0``, which
    would read as "nothing is near the cliff" — and the SPA draws the distribution with no
    marker rather than a marker nobody configured.

    Nothing personal is read: strategies, counts and the verifier's own scores. No name, no
    candidate text, no transcript, at any role.
    """
    if bucket_count < 1:
        raise ValueError("a histogram needs at least one bucket")
    if band < 0.0:
        raise ValueError("the near-threshold band cannot be negative")

    counts = await _strategy_counts(session, window=window, threshold=threshold, band=band)
    histograms = await _strategy_histograms(session, window=window, bucket_count=bucket_count)
    has_recorded = await _exists(session, sa.and_(*_BAKE_OFF_POPULATION))

    strategies = tuple(
        StrategyAnalysis(
            strategy=strategy,
            attempts=count.attempts,
            verified=count.verified,
            scored=count.scored,
            near_threshold=None if threshold is None else count.near_threshold,
            buckets=_buckets_of(histograms.get(strategy, {}), bucket_count),
        )
        for strategy, count in counts.items()
    )
    # Same ordering as ``strategy_outcomes``: rate first, volume breaking the tie.
    ranked = tuple(
        sorted(strategies, key=lambda s: (s.verification_rate, s.attempts), reverse=True)
    )
    overall: dict[int, int] = {}
    for buckets in histograms.values():
        for index, count_at in buckets.items():
            overall[index] = overall.get(index, 0) + count_at
    return NameAnalytics(
        strategies=ranked,
        buckets=_buckets_of(overall, bucket_count),
        attempts=sum(item.attempts for item in ranked),
        verified=sum(item.verified for item in ranked),
        scored=sum(item.scored for item in ranked),
        near_threshold=(
            None if threshold is None else sum(item.near_threshold or 0 for item in ranked)
        ),
        threshold=threshold,
        band=band,
        bucket_count=bucket_count,
        has_recorded_attempts=has_recorded,
    )


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
#: The bake-off's population, spelled once: a candidate orthography on which verification
#: actually ran. Every count in :func:`name_analytics` and the probe behind
#: ``has_recorded_attempts`` share it, because a distribution over one population and a rate
#: over another is how two halves of the same screen come to disagree.
_BAKE_OFF_POPULATION: Final[tuple[sa.ColumnElement[bool], ...]] = (
    GenerationAttemptRow.name_candidate_strategy.is_not(None),
    GenerationAttemptRow.is_name_verified.is_not(None),
)


@dataclass(frozen=True, slots=True)
class _StrategyCounts:
    """The four counts one ``GROUP BY`` returns for one orthography."""

    attempts: int
    verified: int
    scored: int
    near_threshold: int


def _near_threshold_condition(threshold: float | None, band: float) -> sa.ColumnElement[bool]:
    """Scores within ``band`` of ``threshold``, both edges inclusive.

    The bounds are clamped into ``[0, 1]`` so a threshold of ``0.98`` does not describe a
    band reaching past the strongest score a verifier can return. With no published
    threshold the condition is ``false`` rather than absent: the column stays in the select,
    the count comes back ``0``, and the caller replaces it with ``None`` — which keeps "not
    knowable" and "none near the cliff" from being the same wire value by accident.
    """
    if threshold is None:
        return sa.false()
    lower = max(0.0, threshold - band)
    upper = min(1.0, threshold + band)
    return sa.and_(
        GenerationAttemptRow.match_confidence >= lower,
        GenerationAttemptRow.match_confidence <= upper,
    )


def _bucket_index(bucket_count: int) -> sa.ColumnElement[int]:
    """Which histogram bar a score falls in, as a ``CASE`` the database evaluates.

    A ``CASE`` ladder rather than arithmetic, because the arithmetic is not portable: SQLite
    ships ``floor()`` only when compiled with ``SQLITE_ENABLE_MATH_FUNCTIONS``, and
    ``CAST(x AS INTEGER)`` truncates on SQLite while Postgres ROUNDS it — which would put
    every score in the bucket above its neighbour's on one dialect and not the other, in a
    chart whose whole job is where a pile sits relative to a line.

    Values outside ``[0, 1]`` are clamped rather than dropped, matching the SPA's
    ``buildSimilarityBuckets``: a provider returning ``1.0000000002`` is not a reason to
    lose a sample.
    """
    width = 1.0 / bucket_count
    ladder = [
        (GenerationAttemptRow.match_confidence < (index + 1) * width, index)
        for index in range(bucket_count - 1)
    ]
    return sa.case(*ladder, else_=bucket_count - 1)


def _buckets_of(counts: dict[int, int], bucket_count: int) -> tuple[SimilarityBucket, ...]:
    """Every bar, zeros included. A histogram with holes in it cannot be read."""
    width = 1.0 / bucket_count
    return tuple(
        SimilarityBucket(lower=index * width, upper=(index + 1) * width, count=counts.get(index, 0))
        for index in range(bucket_count)
    )


async def _strategy_counts(
    session: AsyncSession, *, window: TimeWindow | None, threshold: float | None, band: float
) -> dict[NameStrategy, _StrategyCounts]:
    """One ``GROUP BY``: attempts, verified, scored and near-the-cliff, per orthography."""
    statement = sa.select(
        GenerationAttemptRow.name_candidate_strategy,
        sa.func.count().label("attempts"),
        count_where(GenerationAttemptRow.is_name_verified.is_(True)).label("verified"),
        count_where(GenerationAttemptRow.match_confidence.is_not(None)).label("scored"),
        count_where(_near_threshold_condition(threshold, band)).label("near_threshold"),
    ).where(*_BAKE_OFF_POPULATION)
    statement = apply_window(statement, GenerationAttemptRow.created_at, window)
    rows = (
        await session.execute(statement.group_by(GenerationAttemptRow.name_candidate_strategy))
    ).all()
    return {
        strategy: _StrategyCounts(
            attempts=int(attempts),
            verified=int(verified),
            scored=int(scored),
            near_threshold=int(near),
        )
        for strategy, attempts, verified, scored, near in rows
        if strategy is not None
    }


async def _strategy_histograms(
    session: AsyncSession, *, window: TimeWindow | None, bucket_count: int
) -> dict[NameStrategy, dict[int, int]]:
    """The distribution, grouped by orthography and bucket in the database.

    Grouped rather than fetched: the alternative is pulling every score in the window into
    Python to bin it, which is the one thing this package does not do — and it is exactly
    how the SPA's current histogram ended up describing "the most recent two hundred rows"
    while claiming to describe the window.
    """
    index = _bucket_index(bucket_count)
    statement = sa.select(
        GenerationAttemptRow.name_candidate_strategy,
        index.label("bucket"),
        sa.func.count().label("count"),
    ).where(*_BAKE_OFF_POPULATION, GenerationAttemptRow.match_confidence.is_not(None))
    statement = apply_window(statement, GenerationAttemptRow.created_at, window)
    rows = (
        await session.execute(
            statement.group_by(GenerationAttemptRow.name_candidate_strategy, index)
        )
    ).all()
    histograms: dict[NameStrategy, dict[int, int]] = {}
    for strategy, bucket, count in rows:
        if strategy is None:
            continue
        histograms.setdefault(strategy, {})[int(bucket)] = int(count)
    return histograms


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
