"""Checks a process must pass before it accepts its first customer.

Separate from the container on purpose. Building the wiring is cheap and pure; probing the
host shells out to ffmpeg. Keeping them apart means the composition root stays unit-testable
and the probe still runs exactly once per process, at the only moment it is useful — before
anything is accepted that could fail because of it.
"""

from __future__ import annotations

from hbd.audio.startup import ensure_ffmpeg_available
from hbd.config import Settings
from hbd.i18n import get_translator
from hbd.logging import get_logger

__all__ = ["verify_host"]

_LOG = get_logger(__name__)


def verify_host(settings: Settings) -> None:
    """Fail fast on anything the host cannot do. Raises ``ConfigError`` only."""
    ensure_ffmpeg_available(
        ffmpeg_binary=settings.ffmpeg_binary, ffprobe_binary=settings.ffprobe_binary
    )
    # Loading the catalogues here turns a malformed locale file into one startup failure
    # rather than a broken message in front of a customer.
    translator = get_translator()
    _LOG.info(
        "host verified",
        extra={
            "ffmpeg": settings.ffmpeg_binary,
            "locales": len(settings.supported_languages),
            "catalogue_languages": len(translator.catalogs),
        },
    )
