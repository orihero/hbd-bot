"""Turning vendor bytes into deliverable files.

Everything here writes to a per-order workspace using *deterministic* file names. That is
the local half of idempotency: a retried job overwrites `song.mp3`, it does not produce
`song-2.mp3` and leave the customer with two of everything.

Post-processing is behind the ``AudioPostProcessor`` seam, so none of this needs ffmpeg to
be tested. Where post-processing fails the raw file still ships — a slightly hot mix beats
no song — and the failure is returned to the caller as a gap rather than swallowed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from hbd.config import Settings
from hbd.contracts import (
    AssetKind,
    AudioPostProcessor,
    Err,
    GeneratedAsset,
    LyricDraft,
    NameCandidate,
    RenderedAudio,
    Result,
    SpokenScript,
    Storage,
    err,
    ok,
)
from hbd.errors import AudioProcessingError, HbdError, StorageError
from hbd.logging import get_logger

__all__ = [
    "song_asset",
    "greeting_asset",
    "lyric_sheet_asset",
    "render_lyric_sheet",
    "archive_assets",
    "storage_key",
    "sha256_of",
    "VOICE_NOTE_MIME",
    "LYRIC_SHEET_MIME",
]

_LOGGER = get_logger(__name__)

VOICE_NOTE_MIME: Final[str] = "audio/ogg"
LYRIC_SHEET_MIME: Final[str] = "text/plain; charset=utf-8"
LYRIC_SHEET_FILENAME: Final[str] = "lyrics.txt"

_EXTENSIONS: Final[dict[str, str]] = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
}
_FALLBACK_EXTENSION: Final[str] = ".bin"


def _extension_for(mime: str) -> str:
    return _EXTENSIONS.get(mime.split(";")[0].strip().lower(), _FALLBACK_EXTENSION)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bytes(path: Path, data: bytes) -> Result[Path]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        return err(
            StorageError(
                "could not write a rendered asset to the workspace",
                context={"path": str(path), "bytes": len(data)},
                cause=exc,
            )
        )
    return ok(path)


def _write_text(path: Path, text: str) -> Result[Path]:
    return _write_bytes(path, text.encode("utf-8"))


async def _probe_or_default(
    post: AudioPostProcessor, path: Path, *, fallback_duration_s: float
) -> tuple[float, float | None]:
    """Measured duration and loudness, or the vendor's numbers when probing fails."""
    probe = await post.probe(path)
    if isinstance(probe, Err):
        _LOGGER.warning(
            "probe failed; falling back to the vendor-reported duration",
            extra={"path": str(path), **probe.error.to_log_dict()},
        )
        return fallback_duration_s, None
    return probe.value.duration_s, probe.value.loudness_lufs


async def _normalized(
    post: AudioPostProcessor, source: Path, *, destination: Path, target_lufs: float
) -> Path:
    """Loudness-normalise, or fall back to the source file. Never fatal."""
    result = await post.normalize_loudness(source, destination=destination, target_lufs=target_lufs)
    if isinstance(result, Err):
        _LOGGER.warning(
            "loudness normalisation failed; shipping the raw render",
            extra={"source": str(source), **result.error.to_log_dict()},
        )
        return source
    return result.value


async def song_asset(
    audio: RenderedAudio,
    *,
    workspace: Path,
    post: AudioPostProcessor,
    settings: Settings,
    name_candidate: NameCandidate,
) -> Result[GeneratedAsset]:
    """Write, normalise and describe the song. The expensive asset — it always ships."""
    extension = _extension_for(audio.mime)
    written = _write_bytes(workspace / f"song-raw{extension}", audio.data)
    if isinstance(written, Err):
        return written

    final = await _normalized(
        post,
        written.value,
        destination=workspace / f"song{extension}",
        target_lufs=settings.loudnorm_song_lufs,
    )
    duration_s, loudness = await _probe_or_default(
        post, final, fallback_duration_s=audio.duration_s
    )
    return ok(
        GeneratedAsset(
            kind=AssetKind.SONG,
            path=final,
            duration_s=duration_s,
            mime=audio.mime,
            sha256=sha256_of(final),
            name_candidate=name_candidate,
            loudness_lufs=loudness,
        )
    )


async def _voice_note(
    audio: RenderedAudio,
    *,
    workspace: Path,
    index: int,
    post: AudioPostProcessor,
    settings: Settings,
) -> Result[Path]:
    """Raw bytes -> loudness-normalised -> OGG/Opus, on deterministic paths."""
    extension = _extension_for(audio.mime)
    stem = f"greeting-{index + 1}"
    written = _write_bytes(workspace / f"{stem}-raw{extension}", audio.data)
    if isinstance(written, Err):
        return written
    normalized = await _normalized(
        post,
        written.value,
        destination=workspace / f"{stem}-norm{extension}",
        target_lufs=settings.loudnorm_speech_lufs,
    )
    return await post.to_voice_note(normalized, destination=workspace / f"{stem}.ogg")


async def greeting_asset(
    audio: RenderedAudio,
    script: SpokenScript,
    *,
    index: int,
    workspace: Path,
    post: AudioPostProcessor,
    settings: Settings,
    name_candidate: NameCandidate,
) -> Result[GeneratedAsset]:
    """Write, normalise and transcode one greeting to an OGG/Opus voice note.

    ``sendVoice`` renders anything that is not OGG/Opus as a file attachment, so a failed
    transcode is a real defect rather than a cosmetic one — it is returned as an error and
    the caller records the greeting as a gap.
    """
    transcoded = await _voice_note(
        audio, workspace=workspace, index=index, post=post, settings=settings
    )
    if isinstance(transcoded, Err):
        return err(
            AudioProcessingError(
                "greeting could not be transcoded to an OGG/Opus voice note",
                context={"persona_id": script.persona_id, "index": index},
                cause=transcoded.error,
            )
        )

    duration_s, loudness = await _probe_or_default(
        post, transcoded.value, fallback_duration_s=audio.duration_s
    )
    return ok(
        GeneratedAsset(
            kind=AssetKind.GREETING,
            path=transcoded.value,
            duration_s=duration_s,
            mime=VOICE_NOTE_MIME,
            sha256=sha256_of(transcoded.value),
            name_candidate=name_candidate,
            loudness_lufs=loudness,
            persona_id=script.persona_id,
        )
    )


def render_lyric_sheet(lyrics: LyricDraft) -> str:
    """Typeset the sheet. This is OUR typography, so the name is the display form."""
    blocks = [lyrics.title, ""]
    for section in lyrics.sections:
        blocks.append(f"[{section.label}]")
        blocks.extend(section.lines)
        blocks.append("")
    blocks.append(f"— {lyrics.name_display}")
    return "\n".join(blocks)


def lyric_sheet_asset(lyrics: LyricDraft, *, workspace: Path) -> Result[GeneratedAsset]:
    written = _write_text(workspace / LYRIC_SHEET_FILENAME, render_lyric_sheet(lyrics))
    if isinstance(written, Err):
        return written
    return ok(
        GeneratedAsset(
            kind=AssetKind.LYRIC_SHEET,
            path=written.value,
            duration_s=0.0,
            mime=LYRIC_SHEET_MIME,
            sha256=sha256_of(written.value),
        )
    )


def storage_key(order_id: object, asset: GeneratedAsset) -> str:
    return f"orders/{order_id}/{asset.path.name}"


async def archive_assets(
    assets: tuple[GeneratedAsset, ...], *, order_id: object, storage: Storage
) -> tuple[HbdError, ...]:
    """Copy finished assets to object storage. Archival, so failures are reported, not raised.

    Delivery reads the local workspace, which is why a storage outage costs the operator a
    backup and costs the customer nothing.
    """
    failures: list[HbdError] = []
    for asset in assets:
        try:
            data = asset.path.read_bytes()
        except OSError as exc:
            failures.append(
                StorageError(
                    "finished asset disappeared before archiving",
                    context={"path": str(asset.path)},
                    cause=exc,
                )
            )
            continue
        result = await storage.put(storage_key(order_id, asset), data, content_type=asset.mime)
        if isinstance(result, Err):
            failures.append(result.error)
    if failures:
        _LOGGER.warning("some assets were not archived", extra={"failed": len(failures)})
    return tuple(failures)
