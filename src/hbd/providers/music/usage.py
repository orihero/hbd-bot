"""One measured usage line per vendor call, so spend can be reconciled later.

``POST /v1/music`` answers with audio bytes and no cost field, so there is no
vendor-reported price to record. What we CAN record is every quantity the invoice is
computed from — chunk count, billed milliseconds, model id, output format — plus the
transport facts that explain an anomalous line. That is why ``cost_usd`` on a music render
is ``CostSource.ESTIMATED`` and not ``VENDOR_REPORTED``: claiming otherwise would put a
made-up number into the ledger wearing a vendor's authority.

The estimate is deliberately a single rate constant. When the dashboard says otherwise,
change the rate (or lift it into ``Settings``) and every past log line still replays,
because the measured quantities were recorded alongside the derived figure.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Final

__all__ = [
    "MusicUsage",
    "estimate_cost_usd",
    "log_usage",
    "DEFAULT_MUSIC_USD_PER_MINUTE",
    "USAGE_EVENT",
]

#: Placeholder list price per rendered minute, in USD. Reconcile against the dashboard.
#: It is deliberately non-zero, which makes music the one leg that is priced before anybody
#: configures anything: a fresh deployment's first render carries a real dollar figure,
#: honestly labelled ``CostSource.ESTIMATED`` and rendered beside its provenance. An
#: operator who would rather say nothing than say a placeholder sets
#: ``HBD_MUSIC_USD_PER_MINUTE=0``, and the ledger then records the render with no cost.
DEFAULT_MUSIC_USD_PER_MINUTE: Final[float] = 0.15

MS_PER_MINUTE: Final[int] = 60_000

#: Grep-able event name. One line per vendor call, success or failure.
USAGE_EVENT: Final[str] = "music.usage"


def estimate_cost_usd(total_duration_ms: int, *, usd_per_minute: float) -> float:
    """Estimated spend for one render. Never negative, never raises."""
    if total_duration_ms <= 0 or usd_per_minute <= 0:
        return 0.0
    return round(total_duration_ms / MS_PER_MINUTE * usd_per_minute, 6)


@dataclass(frozen=True, slots=True)
class MusicUsage:
    """Everything needed to reconcile one call against the vendor's invoice."""

    provider: str
    operation: str
    model_id: str
    output_format: str
    chunk_count: int
    total_duration_ms: int
    elapsed_ms: int
    outcome: str
    http_status: int | None = None
    response_bytes: int = 0
    remote_id: str | None = None
    estimated_cost_usd: float = 0.0
    name_chunk_index: int | None = None
    source_song_id: str | None = None


def log_usage(logger: logging.Logger, usage: MusicUsage) -> None:
    """Emit the usage line. The JSON formatter folds ``extra`` into ``context``."""
    logger.info(USAGE_EVENT, extra=asdict(usage))
