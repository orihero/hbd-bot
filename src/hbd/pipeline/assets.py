"""Turning vendor bytes into deliverable files.

Everything here writes to a per-order workspace using *deterministic* file names. That is
the local half of idempotency: a retried job overwrites `song.mp3`, it does not produce
`song-2.mp3` and leave the customer with two of everything.

Post-processing is behind the ``AudioPostProcessor`` seam, so none of this needs ffmpeg to
be tested. Where post-processing fails the raw file still ships — a slightly hot mix beats
no song — and the failure is returned to the caller as a gap rather than swallowed.

The watermark is applied HERE, on the rendered artefacts, and nowhere upstream. Two of its
four carriers live in this file: the generated cover art (:func:`cover_asset`, muxed into
the mp3 by :func:`_branded` and attached as the Telegram thumbnail by the delivery layer)
and the rule lines on the archived lyric sheet (:func:`render_lyric_sheet`). Both read from
``hbd.watermark`` and neither touches the ``LyricDraft`` it is handed — a watermark inside
the draft would be posted to the music vendor and SUNG, which is the one failure this
arrangement exists to make structurally impossible rather than merely unlikely.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from hbd.audio.cover import COVER_MIME, COVER_SUFFIX, render_cover
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
from hbd.storage import archive_key
from hbd.watermark import SHEET_RULE, audio_tags

__all__ = [
    "cover_asset",
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
#: The cover's deterministic name, like every other file in a workspace: a re-run of the
#: order overwrites it rather than leaving two of them for the archival step to upload.
COVER_FILENAME: Final[str] = f"cover{COVER_SUFFIX}"
#: The stem of the branded copy of the song. A THIRD name beside ``song-raw`` and ``song``
#: rather than an in-place rewrite, because ffmpeg cannot read and write the same file and
#: because keeping the normalised input around is what lets the branding pass fail without
#: costing the customer their mastering — the caller simply ships the previous file.
BRANDED_STEM: Final[str] = "song-tagged"

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


async def cover_asset(*, workspace: Path) -> GeneratedAsset | None:
    """Draw the watermark cover, or ``None`` when it could not be drawn.

    Returns ``None`` rather than a ``Result`` because there is no caller decision to make:
    a kit with no cover is a complete kit — ``Kit.cover`` has always been optional and
    ``Kit.all_assets`` has always folded a present one in — so a ``Result`` here would only
    invite somebody to propagate a picture's failure into an order's. The reason is logged
    at WARNING, which is where an operator looks when covers stop appearing.

    ``AssetKind.COVER`` and ``Kit.cover`` were modelled long before anything produced one,
    so archival, the assets table and the admin panel already handle this shape; nothing
    downstream needed a change to accept it.

    ``duration_s=0.0`` for the same reason the lyric sheet carries it: the column is not
    nullable and a picture has no duration. That is the existing convention for a text
    asset and this is the second non-audio one.
    """
    rendered = render_cover(workspace / COVER_FILENAME)
    if isinstance(rendered, Err):
        _LOGGER.warning(
            "cover art could not be drawn; shipping the kit without one",
            extra={"workspace": str(workspace), **rendered.error.to_log_dict()},
        )
        return None
    return GeneratedAsset(
        kind=AssetKind.COVER,
        path=rendered.value,
        duration_s=0.0,
        mime=COVER_MIME,
        sha256=sha256_of(rendered.value),
    )


async def _branded(
    post: AudioPostProcessor,
    source: Path,
    *,
    destination: Path,
    cover: Path | None,
    tags: tuple[tuple[str, str], ...],
) -> Path:
    """Attach the cover and the tags, or fall back to the source file. Never fatal.

    The same shape as :func:`_normalized`, and for a stronger reason: normalisation is
    mastering the customer paid for, whereas branding is an advertisement we added. If the
    mux fails, the previous file is already a finished, normalised song, so returning it
    unchanged costs nothing but the watermark.
    """
    result = await post.brand(source, destination=destination, cover=cover, tags=tags)
    if isinstance(result, Err):
        _LOGGER.warning(
            "watermarking failed; shipping the untagged render",
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
    #: ``None`` for a song with no name in it, which is what a nameless order renders.
    #: ``asset_name_candidate_values`` already stores that as three NULL columns.
    name_candidate: NameCandidate | None,
    #: What the phone's lock screen shows. The song's own title, NOT a watermark — the
    #: three watermark tags are fixed and come from ``hbd.watermark.audio_tags``.
    title: str,
    #: The picture to attach, or ``None`` when :func:`cover_asset` could not draw one. The
    #: tags are still written in that case; a missing cover is not a missing watermark.
    cover: Path | None = None,
) -> Result[GeneratedAsset]:
    """Write, normalise, watermark and describe the song. The expensive asset — it always ships.

    Three passes, each of which may fail without failing the order: normalisation falls
    back to the raw render, branding falls back to whatever normalisation produced, and the
    probe falls back to the vendor's own duration. The probe and the hash then run against
    the file that ACTUALLY ships, not the one we hoped to ship — getting that wrong is how
    a kit ends up recording the digest of a file the customer never received.
    """
    extension = _extension_for(audio.mime)
    written = _write_bytes(workspace / f"song-raw{extension}", audio.data)
    if isinstance(written, Err):
        return written

    normalized = await _normalized(
        post,
        written.value,
        destination=workspace / f"song{extension}",
        target_lufs=settings.loudnorm_song_lufs,
    )
    final = await _branded(
        post,
        normalized,
        destination=workspace / f"{BRANDED_STEM}{extension}",
        cover=cover,
        tags=audio_tags(title=title),
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
    name_candidate: NameCandidate | None,
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
    """Typeset the sheet. This is OUR typography, so the name is the display form.

    **This function renders a SHEET, and the ``LyricDraft`` it reads is returned to nobody
    and mutated in no way.** That is the whole reason the watermark rules are safe here:
    the payload posted to the music vendor is built in the orchestrator from
    ``LyricDraft.sections`` and never from this string, so the rules added below are typeset
    onto a text file and can never be sung. Composing them into the draft instead — which
    is the obvious shortcut, because the draft is right there — would hand the vendor
    "Generate yours at @hbduzbot" as a line of the song, and the model would set it to
    music. ``tests/test_pipeline/test_watermark.py`` pins the separation.

    The rule is a header AND a footer because this artefact travels alone: it is forwarded
    as a file, opened in a text editor, and read where no caption goes with it. A reader who
    starts at the bottom needs the same line as one who starts at the top.

    The signature line is dropped entirely for a nameless lyric — the bring-your-own path,
    where the customer wrote the words and was never asked who they are for. An em dash
    followed by nothing is not a smaller version of a dedication, it is a typo on the last
    line of the deliverable.
    """
    blocks = [SHEET_RULE, "", lyrics.title, ""]
    for section in lyrics.sections:
        blocks.append(f"[{section.label}]")
        blocks.extend(section.lines)
        blocks.append("")
    if lyrics.name_display is not None:
        blocks.append(f"— {lyrics.name_display}")
    blocks.extend(("", SHEET_RULE))
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
    """Where this asset's bytes live in the archive.

    Delegates to :func:`hbd.storage.archive_key` rather than spelling the key inline: the
    row that records the key and the sweep that reconstructs it for older rows have to
    produce the same string as the ``put`` that wrote the object, and three independent
    f-strings is how they stop doing that.
    """
    return archive_key(order_id, asset.path.name)


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
