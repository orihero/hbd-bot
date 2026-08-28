"""Pure translation between mapped rows and the frozen models of ``hbd.contracts``.

No session, no I/O, no clock. Every function here is a total function of its arguments,
which is what makes the whole conversion layer testable without a database.

**A stored JSON column is external data.** It was written by an older version of this code,
possibly against an older schema, and the project rule on parsing untrusted text applies to
it exactly as it applies to an LLM payload: never an unchecked cast, always a schema
validation, and a typed error naming what failed. ``candidates_from_json`` and
``lyrics_from_payload`` are those boundaries; nothing else in the package reads a JSON
column directly.

The other invariant this module protects is the display/submitted split. ``display`` comes
out of ``recipient_name_display`` and is the only string a human sees; the candidate texts
come out of ``recipient_candidates`` and are only ever posted to a vendor. They are stored
in different columns because they are different values, and nothing here derives one from
the other.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from pydantic import TypeAdapter

from hbd.contracts import (
    AssetKind,
    Brief,
    GeneratedAsset,
    LyricDraft,
    NameCandidate,
    Order,
    RecipientName,
)
from hbd.db.models.asset import AssetRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.order import OrderRow
from hbd.errors import PipelineError

__all__ = [
    "candidates_to_json",
    "candidates_from_json",
    "lyrics_to_payload",
    "lyrics_from_payload",
    "to_recipient_name",
    "to_brief",
    "to_order",
    "to_generated_asset",
    "brief_identity_values",
    "asset_name_candidate_values",
    "payload_for",
]

_CANDIDATES_ADAPTER: Final[TypeAdapter[tuple[NameCandidate, ...]]] = TypeAdapter(
    tuple[NameCandidate, ...]
)


# ---------------------------------------------------------------------------
# JSON columns — the untrusted boundary
# ---------------------------------------------------------------------------
def candidates_to_json(candidates: tuple[NameCandidate, ...]) -> list[dict[str, Any]]:
    """Serialise ranked candidates for storage. Order is preserved; rank is authoritative."""
    return [candidate.model_dump(mode="json") for candidate in candidates]


def candidates_from_json(raw: object, *, name: str) -> tuple[NameCandidate, ...]:
    """Validate a stored candidate list back into contract models.

    Raises ``pydantic.ValidationError`` on a shape mismatch, which ``run_guarded`` turns
    into a typed ``Err``. It is deliberately not caught here: a silently-dropped candidate
    would change which orthography a re-render picks, and that is the one thing in this
    product that must never fail quietly.
    """
    if raw is None:
        raise PipelineError(
            "stored recipient has no candidate orthographies",
            context={"name_display": name},
        )
    return _CANDIDATES_ADAPTER.validate_python(raw)


def lyrics_to_payload(lyrics: LyricDraft) -> dict[str, Any]:
    """The lyric sheet's content, stored on its own asset row."""
    return lyrics.model_dump(mode="json")


def lyrics_from_payload(raw: object, *, order_id: UUID) -> LyricDraft:
    """Validate a stored lyric sheet back into a ``LyricDraft``."""
    if not isinstance(raw, dict):
        raise PipelineError(
            "lyric sheet asset carries no stored lyric payload",
            context={"order_id": str(order_id), "payload_type": type(raw).__name__},
        )
    return LyricDraft.model_validate(raw)


# ---------------------------------------------------------------------------
# Rows -> contracts
# ---------------------------------------------------------------------------
def to_recipient_name(row: BriefRow) -> RecipientName:
    """Rebuild the recipient from a brief row.

    Raises when the 90-day identity clock has already run. That is the correct answer, not
    a failure to handle: the data was purged on a legal schedule and inventing a
    placeholder would misrepresent a deletion as a value.
    """
    if (
        row.recipient_name_display is None
        or row.recipient_name_raw is None
        or row.recipient_lookup_key is None
        or row.recipient_script is None
        or row.recipient_language is None
    ):
        raise PipelineError(
            "recipient identity has been purged under the FIL-7 retention schedule",
            context={"brief_id": str(row.id), "order_id": str(row.order_id)},
        )
    return RecipientName(
        raw=row.recipient_name_raw,
        display=row.recipient_name_display,
        lookup_key=row.recipient_lookup_key,
        script=row.recipient_script,
        language=row.recipient_language,
        candidates=candidates_from_json(row.recipient_candidates, name=row.recipient_name_display),
    )


def to_brief(row: BriefRow) -> Brief:
    """Rebuild the brief. A purged note reads as empty, which is what ``Brief`` defaults to."""
    return Brief(
        recipient=to_recipient_name(row),
        occasion=row.occasion,
        genre=row.genre,
        vocal_gender=row.vocal_gender,
        note=row.note or "",
        ui_language=row.ui_language,
        output_language=row.output_language,
    )


def to_order(row: OrderRow, brief_row: BriefRow) -> Order:
    """Rebuild the order. ``telegram_user_id`` is denormalised, so no user join is needed."""
    return Order(
        id=row.id,
        telegram_user_id=row.telegram_user_id,
        brief=to_brief(brief_row),
        state=row.state,
        correlation_id=row.correlation_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_generated_asset(row: AssetRow) -> GeneratedAsset:
    """Rebuild a delivered file's descriptor.

    ``name_candidate`` comes back as ``None`` once the identity purge has nulled its text,
    even though the asset itself is retained for twelve months. The two clocks are
    independent by design.
    """
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
    return GeneratedAsset(
        kind=row.kind,
        path=Path(row.path),
        duration_s=row.duration_s,
        mime=row.mime,
        sha256=row.sha256,
        name_candidate=candidate,
        loudness_lufs=row.loudness_lufs,
        persona_id=row.persona_id,
    )


# ---------------------------------------------------------------------------
# Contracts -> row values
# ---------------------------------------------------------------------------
def brief_identity_values(recipient: RecipientName, *, expires_at: datetime) -> dict[str, Any]:
    """The identity half of a ``briefs`` row, ready to assign or to bulk-update."""
    return {
        "recipient_name_raw": recipient.raw,
        "recipient_name_display": recipient.display,
        "recipient_lookup_key": recipient.lookup_key,
        "recipient_script": recipient.script,
        "recipient_language": recipient.language,
        "recipient_candidates": candidates_to_json(recipient.candidates),
        "identity_expires_at": expires_at,
        "identity_purged_at": None,
    }


def asset_name_candidate_values(candidate: NameCandidate | None) -> dict[str, Any]:
    """The three ``assets`` columns that record which orthography produced a take."""
    if candidate is None:
        return {
            "name_candidate_text": None,
            "name_candidate_strategy": None,
            "name_candidate_rank": None,
        }
    return {
        "name_candidate_text": candidate.text,
        "name_candidate_strategy": candidate.strategy,
        "name_candidate_rank": candidate.rank,
    }


def payload_for(asset: GeneratedAsset, lyrics: LyricDraft) -> dict[str, Any] | None:
    """Only the lyric sheet stores its content in the row; everything else stores a path."""
    return lyrics_to_payload(lyrics) if asset.kind is AssetKind.LYRIC_SHEET else None
