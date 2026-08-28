"""The startup capability check.

A worker with no ffmpeg on its PATH, or an ffmpeg built without libopus, fails EVERY
order — and without this check it fails them one paying customer at a time, deep inside a
job, minutes after the boot that should have caught it.

So the check runs at process start and raises ``ConfigError`` exactly like a missing API
key does: named variable, actionable message, no service comes up.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable

from hbd.audio.constants import REQUIRED_ENCODERS, STARTUP_PROBE_TIMEOUT_S
from hbd.config import ENV_PREFIX
from hbd.errors import ConfigError
from hbd.logging import get_logger

__all__ = ["ensure_ffmpeg_available", "missing_encoders"]

_LOG = get_logger(__name__)


def _env_var(setting_name: str) -> str:
    return f"{ENV_PREFIX}{setting_name.upper()}"


def _require_on_path(binary: str, *, setting_name: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise ConfigError(
            f"{binary!r} was not found on PATH. Install ffmpeg, or point "
            f"{_env_var(setting_name)} at the binary. Audio post-processing cannot run "
            "without it and every order would fail.",
            context={"binary": binary, "setting": setting_name},
        )
    return resolved


def missing_encoders(
    encoders_output: str, required: Iterable[str] = REQUIRED_ENCODERS
) -> tuple[str, ...]:
    """Which required encoders are absent from an ``ffmpeg -encoders`` table."""
    return tuple(name for name in required if name not in encoders_output)


def _encoder_table(binary: str, *, timeout_s: float) -> str:
    try:
        # argv list, never a shell string, and the path is operator-configured.
        completed = subprocess.run(
            [binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except OSError as exc:
        raise ConfigError(
            f"{binary!r} is on PATH but could not be executed: {exc}",
            context={"binary": binary},
            cause=exc,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ConfigError(
            f"{binary!r} did not answer -encoders within {timeout_s}s; the binary looks broken.",
            context={"binary": binary},
            cause=exc,
        ) from exc

    if completed.returncode != 0:
        raise ConfigError(
            f"{binary!r} exited {completed.returncode} listing its encoders; "
            "the binary looks broken.",
            context={"binary": binary, "stderr": completed.stderr[-500:]},
        )
    return completed.stdout


def ensure_ffmpeg_available(
    *,
    ffmpeg_binary: str,
    ffprobe_binary: str,
    probe_timeout_s: float = STARTUP_PROBE_TIMEOUT_S,
) -> None:
    """Verify both binaries exist and ffmpeg can encode Opus. Raises ``ConfigError`` only.

    Call once during application start, before the bot accepts an update. Returns ``None``
    on success — there is nothing useful to hand back, and a failure stops the process.
    """
    ffmpeg_path = _require_on_path(ffmpeg_binary, setting_name="ffmpeg_binary")
    ffprobe_path = _require_on_path(ffprobe_binary, setting_name="ffprobe_binary")

    absent = missing_encoders(_encoder_table(ffmpeg_path, timeout_s=probe_timeout_s))
    if absent:
        raise ConfigError(
            f"{ffmpeg_binary!r} was built without {', '.join(absent)}. Telegram's sendVoice "
            "only renders a voice note for OGG/Opus; without this encoder every greeting "
            "would arrive as a file attachment. Install an ffmpeg build that includes it.",
            context={"binary": ffmpeg_path, "missing_encoders": list(absent)},
        )

    _LOG.info(
        "audio.startup.ready",
        extra={"ffmpeg": ffmpeg_path, "ffprobe": ffprobe_path},
    )
