"""``generation_attempts`` — the ledger every render writes to, and the tuning query.

Why this table is not bookkeeping: ``HBD_NAME_CANDIDATE_ORDER`` is configuration rather
than code specifically so a finding can be applied by reordering an environment variable.
:meth:`GenerationAttemptRepository.strategy_stats` is the query that produces the finding.
Without these rows the config knob has nothing to be informed by, and the ranking stays
whatever the first guess was forever.

The privacy seam runs through the middle of a row and is the reason the table survives the
purge at all:

* ``strategy`` / ``rank`` / ``is_name_verified`` are the signal. "``stripped`` ranked 0 and
  passed verification" identifies nobody, so it is kept and the analysis stays honest.
* ``name_candidate_text`` / ``stt_transcript`` **are** the recipient's name. They carry the
  90-day identity clock and :func:`hbd.db.purge.purge_expired` nulls them in place.

So the tuning data outlives the personal data, which is exactly the behaviour a data
protection review asks for and rarely gets.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import (
    CostSource,
    Language,
    NameCandidate,
    NameStrategy,
    NameVerdict,
    Result,
)
from hbd.db.base import utc_now
from hbd.db.enums import GenerationKind
from hbd.db.guard import run_guarded
from hbd.db.models.generation_attempt import TRANSCRIPT_LENGTH, GenerationAttemptRow
from hbd.db.retention import DEFAULT_RETENTION_POLICY, RetentionPolicy

__all__ = [
    "GenerationAttempt",
    "StrategyStat",
    "GenerationAttemptRepository",
    "verdict_row_values",
    "name_verdicts_from_rows",
    "truncate_transcript",
]

#: A verdict row records our own judgement, not a vendor call, so it has no provider.
_VERDICT_PROVIDER: str | None = None


def truncate_transcript(transcript: str | None) -> str | None:
    """Clip a transcript to what the column holds.

    A transcript is DIAGNOSTIC. Losing its tail costs a little tuning signal; letting it
    overflow costs the customer their kit, because the insert fails after the song and all
    three greetings have been generated and paid for. A live order died exactly that way.
    Clipping here rather than widening alone means a longer song can never resurrect it.
    """
    if transcript is None or len(transcript) <= TRANSCRIPT_LENGTH:
        return transcript
    return transcript[:TRANSCRIPT_LENGTH]


class GenerationAttempt(BaseModel):
    """One render attempt, as the pipeline reports it. Frozen like every other model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: GenerationKind
    order_id: UUID | None = None
    sequence: int = Field(default=0, ge=0)
    attempt: int = Field(default=0, ge=0)
    provider: str | None = None
    provider_remote_id: str | None = None
    language: Language | None = None
    is_success: bool = False
    candidate: NameCandidate | None = None
    is_name_verified: bool | None = None
    match_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    stt_transcript: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    cost_usd: float = Field(default=0.0, ge=0.0)
    cost_source: CostSource = CostSource.ESTIMATED
    latency_ms: int = Field(default=0, ge=0)


class StrategyStat(BaseModel):
    """How one candidate orthography performed. The output of the bake-off query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: NameStrategy
    attempts: int = Field(ge=0)
    verified: int = Field(ge=0)

    @property
    def verification_rate(self) -> float:
        """Share of attempts that survived STT verification. Zero attempts reads as 0.0."""
        if self.attempts <= 0:
            return 0.0
        return self.verified / self.attempts


def verdict_row_values(verdict: NameVerdict) -> dict[str, Any]:
    """Column values for a ``NAME_VERIFICATION`` row built from a contract verdict."""
    return {
        "kind": GenerationKind.NAME_VERIFICATION,
        "sequence": 0,
        "attempt": verdict.attempt,
        "provider": _VERDICT_PROVIDER,
        "is_success": verdict.is_match,
        "name_candidate_text": verdict.candidate.text,
        "name_candidate_strategy": verdict.candidate.strategy,
        "name_candidate_rank": verdict.candidate.rank,
        "is_name_verified": verdict.is_match,
        "match_confidence": verdict.confidence,
        "stt_transcript": truncate_transcript(verdict.transcript),
    }


def name_verdicts_from_rows(rows: Sequence[GenerationAttemptRow]) -> tuple[NameVerdict, ...]:
    """Rebuild verdicts, skipping rows whose identity columns the purge has already nulled.

    Skipping is the honest answer. A purged row can no longer say which text was submitted,
    and a ``NameVerdict`` without its candidate would be a fabrication.
    """
    verdicts: list[NameVerdict] = []
    for row in rows:
        if (
            row.name_candidate_text is None
            or row.name_candidate_strategy is None
            or row.name_candidate_rank is None
            or row.is_name_verified is None
        ):
            continue
        verdicts.append(
            NameVerdict(
                candidate=NameCandidate(
                    text=row.name_candidate_text,
                    strategy=row.name_candidate_strategy,
                    rank=row.name_candidate_rank,
                ),
                transcript=row.stt_transcript or "",
                is_match=row.is_name_verified,
                confidence=row.match_confidence or 0.0,
                attempt=row.attempt,
            )
        )
    return tuple(verdicts)


class GenerationAttemptRepository:
    """Append-only writer and reader for the render ledger."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = session_factory
        self._policy = policy
        self._clock = clock

    async def record(self, attempt: GenerationAttempt) -> Result[UUID]:
        """Persist one attempt. Returns the new row id."""
        return await run_guarded(
            "record_attempt",
            lambda: self._record(attempt),
            kind=str(attempt.kind),
            order_id=str(attempt.order_id) if attempt.order_id else None,
        )

    async def list_for_order(self, order_id: UUID) -> Result[tuple[GenerationAttempt, ...]]:
        """Every attempt made for one order, oldest first."""
        return await run_guarded(
            "list_attempts", lambda: self._list_for_order(order_id), order_id=str(order_id)
        )

    async def strategy_stats(self) -> Result[tuple[StrategyStat, ...]]:
        """Verification rate per candidate strategy, best first.

        This is the bake-off, run continuously against production traffic. Ordering by
        rate then volume means a strategy with one lucky success does not outrank one with
        four hundred attempts at the same rate.
        """
        return await run_guarded("strategy_stats", self._strategy_stats)

    # -- implementations ----------------------------------------------------
    async def _record(self, attempt: GenerationAttempt) -> UUID:
        now = self._clock()
        row_id = uuid4()
        candidate = attempt.candidate
        async with self._sessions.begin() as session:
            session.add(
                GenerationAttemptRow(
                    id=row_id,
                    order_id=attempt.order_id,
                    kind=attempt.kind,
                    sequence=attempt.sequence,
                    attempt=attempt.attempt,
                    provider=attempt.provider,
                    provider_remote_id=attempt.provider_remote_id,
                    language=attempt.language,
                    is_success=attempt.is_success,
                    name_candidate_text=candidate.text if candidate else None,
                    name_candidate_strategy=candidate.strategy if candidate else None,
                    name_candidate_rank=candidate.rank if candidate else None,
                    is_name_verified=attempt.is_name_verified,
                    match_confidence=attempt.match_confidence,
                    stt_transcript=truncate_transcript(attempt.stt_transcript),
                    error_code=attempt.error_code,
                    error_message=attempt.error_message,
                    cost_usd=attempt.cost_usd,
                    cost_source=attempt.cost_source,
                    latency_ms=attempt.latency_ms,
                    identity_expires_at=self._policy.identity_expires_at(now),
                    text_expires_at=self._policy.brief_text_expires_at(now),
                    created_at=now,
                )
            )
        return row_id

    async def _list_for_order(self, order_id: UUID) -> tuple[GenerationAttempt, ...]:
        async with self._sessions.begin() as session:
            rows = (
                (
                    await session.execute(
                        sa.select(GenerationAttemptRow)
                        .where(GenerationAttemptRow.order_id == order_id)
                        .order_by(GenerationAttemptRow.created_at, GenerationAttemptRow.attempt)
                    )
                )
                .scalars()
                .all()
            )
            return tuple(_row_to_attempt(row) for row in rows)

    async def _strategy_stats(self) -> tuple[StrategyStat, ...]:
        verified = sa.func.sum(
            sa.case((GenerationAttemptRow.is_name_verified.is_(True), 1), else_=0)
        )
        async with self._sessions.begin() as session:
            rows = (
                await session.execute(
                    sa.select(
                        GenerationAttemptRow.name_candidate_strategy,
                        sa.func.count().label("attempts"),
                        verified.label("verified"),
                    )
                    .where(
                        GenerationAttemptRow.name_candidate_strategy.is_not(None),
                        GenerationAttemptRow.is_name_verified.is_not(None),
                    )
                    .group_by(GenerationAttemptRow.name_candidate_strategy)
                )
            ).all()
        stats = tuple(
            StrategyStat(strategy=strategy, attempts=int(attempts), verified=int(verified_count))
            for strategy, attempts, verified_count in rows
            if strategy is not None
        )
        return tuple(sorted(stats, key=lambda s: (s.verification_rate, s.attempts), reverse=True))


def _row_to_attempt(row: GenerationAttemptRow) -> GenerationAttempt:
    candidate: NameCandidate | None = None
    if (
        row.name_candidate_text is not None
        and row.name_candidate_strategy is not None
        and row.name_candidate_rank is not None
    ):
        candidate = NameCandidate(
            text=row.name_candidate_text,
            strategy=row.name_candidate_strategy,
            rank=row.name_candidate_rank,
        )
    return GenerationAttempt(
        kind=row.kind,
        order_id=row.order_id,
        sequence=row.sequence,
        attempt=row.attempt,
        provider=row.provider,
        provider_remote_id=row.provider_remote_id,
        language=row.language,
        is_success=row.is_success,
        candidate=candidate,
        is_name_verified=row.is_name_verified,
        match_confidence=row.match_confidence,
        stt_transcript=row.stt_transcript,
        error_code=row.error_code,
        error_message=row.error_message,
        cost_usd=row.cost_usd,
        cost_source=row.cost_source,
        latency_ms=row.latency_ms,
    )
