"""The ``AudioPostProcessor`` implementation: ffmpeg, wired together.

This is the only class in the package. Everything it needs is pure and already tested in
isolation — the filter chains, the argv, the two parsers — so what is left here is the
orchestration and the failure handling:

* every ffmpeg run goes through :func:`hbd.audio.runner.run_command`, so a non-zero exit,
  a hang, a missing binary and an OS refusal are all already ``Err`` with the stderr tail
  attached;
* every write happens inside a scratch directory that is removed however the call ends,
  and lands at the destination only via an atomic move, so a failure leaves neither a temp
  file nor a half-written deliverable;
* no method raises. A failure is an ``Err(AudioProcessingError)``, always.

The loudness targets are NOT hardcoded here. ``normalize_loudness`` takes the target per
call because the song (-14 LUFS) and the greetings (-16 LUFS) differ, and both values come
from ``hbd.config``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from hbd.audio.commands import (
    brand_command,
    loudnorm_apply_command,
    loudnorm_measure_command,
    silence_trim_command,
    voice_note_command,
)
from hbd.audio.constants import (
    DEFAULT_FFMPEG_TIMEOUT_S,
    INTERMEDIATE_SUFFIX,
    VOICE_NOTE_SUFFIX,
)
from hbd.audio.loudnorm import LoudnormMeasurement, parse_loudnorm_report
from hbd.audio.probe import ffprobe_args, parse_ffprobe_report, with_loudness
from hbd.audio.runner import run_command
from hbd.audio.tempfiles import publish, scratch_dir
from hbd.config import Settings
from hbd.contracts import AudioProbe, Err, Result, err, ok
from hbd.errors import AudioProcessingError
from hbd.logging import get_logger

__all__ = ["FfmpegAudioPostProcessor"]

_LOG = get_logger(__name__)

# Operation slugs. They identify which pass failed, in the log and in the error context.
_OP_PROBE = "ffprobe"
_OP_TRIM = "loudnorm.trim"
_OP_MEASURE = "loudnorm.measure"
_OP_APPLY = "loudnorm.apply"
_OP_VOICE_NOTE = "voice_note.encode"
_OP_BRAND = "brand.mux"

_TRIMMED_STEM = "trimmed"
_NORMALIZED_STEM = "normalized"
_VOICE_NOTE_STEM = "voice"
_BRANDED_STEM = "branded"


@dataclass(frozen=True, slots=True)
class FfmpegAudioPostProcessor:
    """Satisfies ``hbd.contracts.AudioPostProcessor`` structurally. Immutable.

    Build it with :meth:`from_settings`; the explicit constructor exists so a test can
    vary one knob without assembling a whole ``Settings``.
    """

    ffmpeg_binary: str
    ffprobe_binary: str
    true_peak_db: float
    fade_in_ms: int
    fade_out_ms: int
    silence_trim_threshold_db: float
    opus_bitrate_bps: int
    opus_sample_rate_hz: int
    timeout_s: float = DEFAULT_FFMPEG_TIMEOUT_S

    @classmethod
    def from_settings(cls, settings: Settings) -> FfmpegAudioPostProcessor:
        """Every tunable comes from config. Nothing below is a literal."""
        return cls(
            ffmpeg_binary=settings.ffmpeg_binary,
            ffprobe_binary=settings.ffprobe_binary,
            true_peak_db=settings.loudnorm_true_peak_db,
            fade_in_ms=settings.fade_in_ms,
            fade_out_ms=settings.fade_out_ms,
            silence_trim_threshold_db=settings.silence_trim_threshold_db,
            opus_bitrate_bps=settings.opus_bitrate_bps,
            opus_sample_rate_hz=settings.opus_sample_rate_hz,
            timeout_s=settings.ffmpeg_timeout_s,
        )

    # -- protocol ------------------------------------------------------------
    async def probe(self, source: Path) -> Result[AudioProbe]:
        """Duration, sample rate and channel count. Cheap: no decode."""
        outcome = await run_command(
            ffprobe_args(self.ffprobe_binary, source),
            operation=_OP_PROBE,
            timeout_s=self.timeout_s,
        )
        if isinstance(outcome, Err):
            return outcome
        return parse_ffprobe_report(outcome.value.stdout, source=source)

    async def normalize_loudness(
        self, source: Path, *, destination: Path, target_lufs: float
    ) -> Result[Path]:
        """Silence-trim, two-pass loudnorm to ``target_lufs``, fade in and out."""
        try:
            with scratch_dir(destination) as scratch:
                outcome = await self._normalize(
                    source, scratch=scratch, destination=destination, target_lufs=target_lufs
                )
                if isinstance(outcome, Err):
                    return outcome
                publish(outcome.value, destination)
        except OSError as exc:
            return err(_filesystem_failure(_OP_APPLY, destination, exc))
        return ok(destination)

    async def to_voice_note(self, source: Path, *, destination: Path) -> Result[Path]:
        """Transcode to OGG/Opus mono so Telegram renders a voice note, not a file."""
        if destination.suffix.lower() != VOICE_NOTE_SUFFIX:
            return err(
                AudioProcessingError(
                    f"a voice note destination must end in {VOICE_NOTE_SUFFIX!r}, got "
                    f"{destination.name!r}; Telegram keys off the filename as well as the "
                    "container and would render this as a file attachment",
                    is_retryable=False,
                    context={"destination": str(destination)},
                )
            )
        try:
            with scratch_dir(destination) as scratch:
                staged = scratch / f"{_VOICE_NOTE_STEM}{VOICE_NOTE_SUFFIX}"
                outcome = await run_command(
                    voice_note_command(
                        self.ffmpeg_binary,
                        source,
                        staged,
                        bitrate_bps=self.opus_bitrate_bps,
                        sample_rate_hz=self.opus_sample_rate_hz,
                    ),
                    operation=_OP_VOICE_NOTE,
                    timeout_s=self.timeout_s,
                )
                if isinstance(outcome, Err):
                    return outcome
                publish(staged, destination)
        except OSError as exc:
            return err(_filesystem_failure(_OP_VOICE_NOTE, destination, exc))
        return ok(destination)

    async def brand(
        self,
        source: Path,
        *,
        destination: Path,
        cover: Path | None,
        tags: tuple[tuple[str, str], ...],
    ) -> Result[Path]:
        """Mux the cover picture and the metadata tags in, copying the audio untouched.

        Refuses — with an ``Err``, never a raise — when there is nothing to write. An empty
        ``tags`` with no ``cover`` would build an argv that spends a full container rewrite
        producing a byte-for-byte copy of its input, and the caller would then ship that
        copy believing it had been branded. Saying so is cheaper than debugging why the
        watermark is missing from a file that was demonstrably "processed".

        Shaped exactly like :meth:`to_voice_note`: scratch directory beside the
        destination, ffmpeg writes into it, atomic publish only on a zero exit. The staged
        name carries the destination's suffix because ffmpeg picks its muxer from it, and
        an mp3 written through a suffix-less path gets guessed at.
        """
        if not tags and cover is None:
            return err(
                AudioProcessingError(
                    "branding was asked for with no tags and no cover, which would be a "
                    "full copy that changes nothing",
                    is_retryable=False,
                    context={"source": str(source), "destination": str(destination)},
                )
            )
        try:
            with scratch_dir(destination) as scratch:
                staged = scratch / f"{_BRANDED_STEM}{_suffix_of(destination)}"
                outcome = await run_command(
                    brand_command(
                        self.ffmpeg_binary,
                        source,
                        destination=staged,
                        cover=cover,
                        tags=tags,
                    ),
                    operation=_OP_BRAND,
                    timeout_s=self.timeout_s,
                )
                if isinstance(outcome, Err):
                    return outcome
                publish(staged, destination)
        except OSError as exc:
            return err(_filesystem_failure(_OP_BRAND, destination, exc))
        return ok(destination)

    # -- beyond the protocol -------------------------------------------------
    async def probe_with_loudness(self, source: Path, *, target_lufs: float) -> Result[AudioProbe]:
        """A probe carrying measured integrated loudness, so the pipeline can assert on it.

        Costs a full decode, unlike :meth:`probe`. ``target_lufs`` does not change the
        measured value; it only sets the reference the report's offset is relative to.
        """
        base = await self.probe(source)
        if isinstance(base, Err):
            return base
        measurement = await self._measure(source, target_lufs=target_lufs)
        loudness = measurement.input_i if measurement is not None else None
        return ok(with_loudness(base.value, loudness))

    # -- internals -----------------------------------------------------------
    async def _normalize(
        self, source: Path, *, scratch: Path, destination: Path, target_lufs: float
    ) -> Result[Path]:
        """Run the three passes inside ``scratch``. Returns the staged file, not the destination."""
        trimmed = scratch / f"{_TRIMMED_STEM}{INTERMEDIATE_SUFFIX}"
        trim = await run_command(
            silence_trim_command(
                self.ffmpeg_binary, source, trimmed, threshold_db=self.silence_trim_threshold_db
            ),
            operation=_OP_TRIM,
            timeout_s=self.timeout_s,
        )
        if isinstance(trim, Err):
            return trim

        # The trim is an enhancement, not a requirement. On a very quiet source it can strip
        # every sample, leaving a file with no duration. Failing the whole normalisation there
        # would throw away a good render over a cosmetic pass, so fall back to the untrimmed
        # source instead and carry on. Only an unreadable *source* is a real failure.
        working = trimmed
        probed = await self.probe(trimmed)
        if isinstance(probed, Err):
            probed = await self.probe(source)
            if isinstance(probed, Err):
                return err(
                    probed.error.with_context(
                        stage=_OP_TRIM,
                        source=str(source),
                        hint="neither the trimmed file nor the source could be probed",
                    )
                )
            working = source
            _LOG.warning(
                "audio.trim.left_no_audio",
                extra={"source": str(source), "detail": "normalising the untrimmed source"},
            )

        measurement = await self._measure(working, target_lufs=target_lufs)
        staged = scratch / f"{_NORMALIZED_STEM}{_suffix_of(destination)}"

        # A measurement that came back non-finite means the source carries no measurable
        # loudness at all — digital silence, or a render that failed upstream. Normalising it
        # is undefined, and ffmpeg aborts rather than declining, so pass the audio through
        # untouched. This is NOT the `measurement is None` case: that one means pass one
        # failed for a transient reason and single-pass dynamic normalisation still applies.
        if measurement is not None and not measurement.is_usable:
            _LOG.warning(
                "audio.loudnorm.skipped_silent_source",
                extra={"source": str(source), "detail": "no measurable loudness; passing through"},
            )
            copied = _copy_through(working, staged)
            return copied if isinstance(copied, Err) else ok(staged)

        applied = await run_command(
            loudnorm_apply_command(
                self.ffmpeg_binary,
                working,
                staged,
                target_lufs=target_lufs,
                true_peak_db=self.true_peak_db,
                measurement=measurement,
                duration_s=probed.value.duration_s,
                fade_in_ms=self.fade_in_ms,
                fade_out_ms=self.fade_out_ms,
            ),
            operation=_OP_APPLY,
            timeout_s=self.timeout_s,
        )
        if isinstance(applied, Err):
            return applied
        return ok(staged)

    async def _measure(self, source: Path, *, target_lufs: float) -> LoudnormMeasurement | None:
        """Loudnorm pass one, degrading to ``None`` rather than failing the whole render.

        A missing measurement costs precision, not the deliverable: pass two falls back to
        single-pass dynamic normalisation. It is never silent — the reason is logged with
        full context before it is dropped.
        """
        outcome = await run_command(
            loudnorm_measure_command(
                self.ffmpeg_binary,
                source,
                target_lufs=target_lufs,
                true_peak_db=self.true_peak_db,
            ),
            operation=_OP_MEASURE,
            timeout_s=self.timeout_s,
        )
        if isinstance(outcome, Err):
            _LOG.warning("audio.loudnorm.measure_failed", extra=outcome.error.to_log_dict())
            return None

        parsed = parse_loudnorm_report(outcome.value.stderr)
        if isinstance(parsed, Err):
            _LOG.warning("audio.loudnorm.report_unusable", extra=parsed.error.to_log_dict())
            return None
        return parsed.value


def _suffix_of(destination: Path) -> str:
    """A staged file must carry the destination's suffix — ffmpeg picks the muxer from it."""
    return destination.suffix or INTERMEDIATE_SUFFIX


def _copy_through(source: Path, staged: Path) -> Result[Path]:
    """Stage ``source`` unchanged, for when normalisation is undefined rather than broken."""
    try:
        shutil.copyfile(source, staged)
    except OSError as exc:
        return err(_filesystem_failure(_OP_APPLY, staged, exc))
    return ok(staged)


def _filesystem_failure(operation: str, destination: Path, exc: OSError) -> AudioProcessingError:
    _LOG.warning(
        "audio.filesystem_failed",
        extra={"operation": operation, "destination": str(destination), "reason": str(exc)},
    )
    return AudioProcessingError(
        f"{operation}: the filesystem refused the work at {destination}: {exc}",
        context={"operation": operation, "destination": str(destination)},
        cause=exc,
    )
