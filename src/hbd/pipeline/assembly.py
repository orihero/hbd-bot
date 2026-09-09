"""Boundary validation, and turning rendered audio into a persisted ``Kit``.

Split out of the orchestrator so the orchestrator stays a readable sequence of stages and
this file can hold the fiddly part: which failures are fatal and which are gaps.

The rule this file encodes: **the song and the lyric are the kit; the greetings are
best-effort.** A greeting that will not transcode is recorded and skipped. Only losing the
song, the sheet, or every last greeting can fail an order. The watermark cover art is one
step further down that scale again: it is not even a gap, because a kit without one is a
complete kit, so :func:`~hbd.pipeline.assets.cover_asset` returns ``None`` and the ledger
records nothing.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from hbd.config import Settings
from hbd.contracts import (
    AudioPostProcessor,
    Brief,
    Err,
    GeneratedAsset,
    Kit,
    KitRepository,
    LyricDraft,
    Result,
    Storage,
    err,
    ok,
)
from hbd.errors import PipelineError, ValidationError
from hbd.logging import get_logger
from hbd.pipeline.assets import (
    archive_assets,
    cover_asset,
    greeting_asset,
    lyric_sheet_asset,
    song_asset,
)
from hbd.pipeline.events import PipelineStage
from hbd.pipeline.greetings import GreetingBatch
from hbd.pipeline.name_stage import SongRender
from hbd.pipeline.outcome import RunLedger
from hbd.pipeline.ports import Sleeper
from hbd.pipeline.retry import RetryPolicy, call_with_retry

__all__ = ["order_workspace", "validate_brief", "assemble_kit", "persist_kit"]

_LOGGER = get_logger(__name__)


def order_workspace(root: Path, order_id: UUID) -> Path:
    """Deterministic per-order directory. Re-running an order reuses it by design."""
    return root / str(order_id)


def validate_brief(brief: Brief) -> Result[None]:
    """Re-check the brief at the pipeline boundary. The bot is not the only caller.

    A brief with NO recipient is valid. That is the bring-your-own path, where the wizard
    asks for the words and never asks who the song is for, so there is no name to check —
    as opposed to a name that is present and blank, which is the corruption this guard was
    written to catch and still catches.
    """
    recipient = brief.recipient
    if recipient is None:
        return ok(None)
    if not recipient.display.strip():
        return err(
            ValidationError(
                "recipient display name is blank",
                context={"raw": recipient.raw, "lookup_key": recipient.lookup_key},
            )
        )
    if recipient.language.script is not recipient.script:
        _LOGGER.info(
            "recipient script does not match the name language; continuing",
            extra={"script": recipient.script.value, "language": recipient.language.value},
        )
    return ok(None)


async def _greeting_assets(
    song: SongRender,
    batch: GreetingBatch,
    *,
    workspace: Path,
    post: AudioPostProcessor,
    settings: Settings,
    ledger: RunLedger,
) -> tuple[GeneratedAsset, ...]:
    """Post-process what rendered. A transcode failure costs one greeting, not the kit."""
    built: list[GeneratedAsset] = []
    for render in batch.renders:
        asset = await greeting_asset(
            render.audio,
            render.script,
            index=render.index,
            workspace=workspace,
            post=post,
            settings=settings,
            name_candidate=song.candidate,
        )
        if isinstance(asset, Err):
            ledger.record_gap(
                PipelineStage.POST_PROCESSING,
                asset.error,
                detail=f"greeting {render.index + 1} failed post-processing",
            )
            continue
        built.append(asset.value)
    return tuple(built)


async def assemble_kit(
    *,
    order_id: UUID,
    lyrics: LyricDraft,
    song: SongRender,
    greetings: GreetingBatch,
    workspace_root: Path,
    post: AudioPostProcessor,
    settings: Settings,
    ledger: RunLedger,
) -> Result[Kit]:
    """Post-process every rendered asset and bind them into one deliverable."""
    workspace = order_workspace(workspace_root, order_id)
    # The cover comes FIRST because the song's branding pass muxes it in, and that pass is
    # part of building the song asset. A cover that could not be drawn is ``None`` and
    # changes nothing else: the tags are still written, the kit is still complete, and
    # ``Kit.cover`` has always been optional.
    cover = await cover_asset(workspace=workspace)
    rendered_song = await song_asset(
        song.audio,
        workspace=workspace,
        post=post,
        settings=settings,
        name_candidate=song.candidate,
        title=lyrics.title,
        cover=cover.path if cover is not None else None,
    )
    if isinstance(rendered_song, Err):
        return rendered_song

    voice_notes = await _greeting_assets(
        song, greetings, workspace=workspace, post=post, settings=settings, ledger=ledger
    )
    # An empty batch means none were requested (greetings_per_kit=0) — a product setting,
    # not a failure. Only a batch that ATTEMPTED greetings and produced none is fatal.
    was_attempted = bool(greetings.renders or greetings.failures)
    if not voice_notes and was_attempted:
        return err(
            PipelineError(
                "every greeting failed, so no kit can be assembled",
                context={
                    "song_path": str(rendered_song.value.path),
                    "order_id": str(order_id),
                },
            )
        )

    sheet = lyric_sheet_asset(lyrics, workspace=workspace)
    if isinstance(sheet, Err):
        return sheet
    return ok(
        Kit(
            order_id=order_id,
            song=rendered_song.value,
            greetings=voice_notes,
            lyric_sheet=sheet.value,
            lyrics=lyrics,
            # ``Kit`` is frozen, so the cover has to arrive at construction; there is no
            # later point at which one could be attached.
            cover=cover,
            name_verdicts=song.verdicts,
        )
    )


async def persist_kit(
    kit: Kit,
    *,
    order_id: UUID,
    storage: Storage,
    repository: KitRepository,
    policy: RetryPolicy,
    sleeper: Sleeper,
    ledger: RunLedger,
) -> Result[Kit]:
    """Archive the files, then save the record. Only the save is allowed to fail the order."""
    for failure in await archive_assets(kit.all_assets, order_id=order_id, storage=storage):
        ledger.record_gap(PipelineStage.PERSISTING, failure, detail="asset was not archived")

    async def call() -> Result[Kit]:
        return await repository.save_kit(kit)

    saved, _report = await call_with_retry(
        call, label="repository.save_kit", policy=policy, sleeper=sleeper
    )
    return saved
