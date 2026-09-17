"""One celebration kit, start to finish, with no keys and no network. ``python -m bayram.demo``.

This is not a test double of the pipeline — it *is* the pipeline, the real orchestrator
with the real name subsystem, the real ffmpeg passes and the real repository, with only the
six vendor adapters swapped for fakes. What it prints is therefore evidence about the
shipped code path, not about a rehearsal of it.

It exists for two audiences. An operator gets to watch the product work before spending a
cent. An integrator gets a single command that fails loudly the moment two modules stop
agreeing — which no unit test can do, because every unit test mocks the seam that broke.

The default recipient is ``Gʻulomjon`` typed the way a real phone types it (U+2018), so
the run also demonstrates the thing the product exists for: canonicalisation, the ranked
candidate orthographies, and the acoustic re-roll when the first take is misheard.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

from bayram.config import Settings
from bayram.contracts import (
    Brief,
    Err,
    Genre,
    Language,
    Occasion,
    Order,
    OrderState,
    VoiceGender,
)
from bayram.errors import BayramError
from bayram.logging import configure_logging, get_logger, new_correlation_id
from bayram.names import resolve_name
from bayram.pipeline.events import ProgressEvent, ProgressStatus
from bayram.pipeline.outcome import PipelineOutcome
from bayram.runtime.container import AppContainer, build_container
from bayram.runtime.startup import verify_host

__all__ = ["main", "run_demo", "DEMO_NAME", "DEMO_NOTE"]

_LOG = get_logger(__name__)

#: Typed with U+2018, the way a phone keyboard actually produces it. The name subsystem
#: canonicalises it to U+02BB for display and derives the submitted orthographies itself.
DEMO_NAME: Final[str] = "G‘ulomjon"
DEMO_NOTE: Final[str] = "Mehribon aka, futbolni yaxshi koʻradi."

_DEMO_CHAT_ID: Final[int] = 1
_RULE: Final[str] = "-" * 72


class _PrintingSink:
    """A ``ProgressSink`` that writes to the terminal instead of editing a message."""

    async def emit(self, event: ProgressEvent) -> None:
        marker = {
            ProgressStatus.STARTED: "..",
            ProgressStatus.SUCCEEDED: "ok",
            ProgressStatus.FAILED: "!!",
            ProgressStatus.RETRYING: "->",
        }.get(event.status, "  ")
        step = f"{event.step_index}/{event.step_count}"
        _say(f"  [{marker}] {step:>6}  {event.stage.value}")


def _say(line: str) -> None:
    print(line, flush=True)


def _demo_settings(data_root: Path) -> Settings:
    """Real settings, forced offline. Anything already in the environment still wins."""
    return Settings(
        _env_file=None,
        use_fake_providers=True,
        environment="dev",
        telegram_bot_token="0:demo-token-never-sent-anywhere",
        database_url=f"sqlite+aiosqlite:///{data_root / 'demo.db'}",
        elevenlabs_api_key="demo",
        llm_api_key="demo",
        # Two minutes of silence takes ffmpeg real time to normalise three times over,
        # and the demo is about wiring, not duration.
        song_length_ms=30_000,
    )


def _build_order(settings: Settings) -> Order | BayramError:
    resolved = resolve_name(
        DEMO_NAME,
        candidate_order=settings.name_candidate_order,
        ui_language=Language.UZ_LATN,
    )
    if isinstance(resolved, Err):
        return resolved.error
    recipient = resolved.value
    brief = Brief(
        recipient=recipient,
        occasion=Occasion.BIRTHDAY,
        genre=Genre.UZBEK_POP,
        vocal_gender=VoiceGender.MALE,
        note=DEMO_NOTE,
        ui_language=Language.UZ_LATN,
        output_language=Language.UZ_LATN,
    )
    now = datetime.now(tz=UTC)
    return Order(
        id=uuid4(),
        telegram_user_id=_DEMO_CHAT_ID,
        brief=brief,
        state=OrderState.AUTHORIZED,
        correlation_id=new_correlation_id(),
        created_at=now,
        updated_at=now,
    )


def _report_name(order: Order) -> None:
    recipient = order.brief.recipient
    _say(_RULE)
    if recipient is None:
        # The demo builds a named order, so this is here to keep the reporter total rather
        # than because the offline run can reach it.
        _say("NAME SUBSYSTEM — skipped: this order names nobody")
        return
    _say("NAME SUBSYSTEM")
    _say(f"  typed      {DEMO_NAME!r}")
    _say(f"  display    {recipient.display!r}   <- what the customer sees")
    _say(f"  lookup key {recipient.lookup_key!r}")
    _say("  candidates (rank order comes from BAYRAM_NAME_CANDIDATE_ORDER):")
    for candidate in recipient.candidates:
        _say(f"    {candidate.rank}. {candidate.strategy.value:<11} {candidate.text!r}")


def _report_outcome(outcome: PipelineOutcome) -> None:
    _say(_RULE)
    _say("NAME VERIFICATION (compose -> STT -> compare -> re-roll)")
    for verdict in outcome.name_verdicts:
        state = "MATCH" if verdict.is_match else "no match"
        _say(
            f"  attempt {verdict.attempt}: {verdict.candidate.strategy.value:<11} "
            f"heard {verdict.transcript!r} -> {state}"
        )
    _say(_RULE)
    _say("KIT")
    kit = outcome.kit
    for asset in kit.all_assets:
        size = asset.path.stat().st_size if asset.path.exists() else 0
        _say(
            f"  {asset.kind.value:<12} {asset.duration_s:>6.1f}s  {size:>9,d} B  "
            f"{asset.mime:<24} {asset.path}"
        )
    _say(_RULE)
    _say("LYRIC SHEET")
    for line in kit.lyrics.as_plain_text().splitlines():
        _say(f"  {line}")
    if outcome.gaps:
        _say(_RULE)
        _say("GAPS (delivered anyway — partial beats nothing)")
        for gap in outcome.gaps:
            _say(f"  {gap.stage.value}: {gap.detail}")
    _say(_RULE)
    _say(
        f"total {outcome.total_duration_ms / 1000:.1f}s  "
        f"cost ${outcome.total_cost_usd:.4f}  gaps {len(outcome.gaps)}"
    )


async def run_demo(*, data_root: Path) -> int:
    """Generate one kit into ``data_root``. Returns a process exit code."""
    settings = _demo_settings(data_root)
    container: AppContainer | None = None
    try:
        verify_host(settings)
        container = await build_container(settings, data_root=data_root)
        order = _build_order(settings)
        if isinstance(order, BayramError):
            _say(f"the demo name could not be resolved: {order.operator_message}")
            return 1
        _report_name(order)

        created = await container.repository.create_order(order)
        if isinstance(created, Err):
            _say(f"could not persist the order: {created.error.operator_message}")
            return 1

        _say(_RULE)
        _say("PIPELINE")
        outcome = await container.pipeline(sink=_PrintingSink()).run(order)
        if isinstance(outcome, Err):
            _say(_RULE)
            _say(f"FAILED: {outcome.error.operator_message}")
            _LOG.error("demo run failed", extra=outcome.error.to_log_dict())
            return 1
        _report_outcome(outcome.value)
        return 0
    finally:
        if container is not None:
            await container.aclose()


def main() -> int:
    """``python -m bayram.demo [output-directory]``. Never raises."""
    configure_logging(level="WARNING", is_json=False)
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return asyncio.run(run_demo(data_root=root))

    with tempfile.TemporaryDirectory(prefix="bayram-demo-") as scratch:
        _say(f"working in {scratch} (pass a directory to keep the files)")
        return asyncio.run(run_demo(data_root=Path(scratch)))


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
