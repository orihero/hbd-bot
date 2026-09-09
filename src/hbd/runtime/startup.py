"""Checks a process must pass before it accepts its first customer.

Separate from the container on purpose. Building the wiring is cheap and pure; probing the
host shells out to ffmpeg. Keeping them apart means the composition root stays unit-testable
and the probe still runs exactly once per process, at the only moment it is useful — before
anything is accepted that could fail because of it.
"""

from __future__ import annotations

from hbd.audio.startup import ensure_ffmpeg_available
from hbd.config import Settings, env_file
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
    # ``environment`` and ``env_file`` are here because ``HBD_ENV_FILE`` makes it possible to
    # boot a PRODUCTION configuration from a development checkout — that is the point of the
    # variable — and the only thing standing between that and a real bot token pointed at a
    # real database is an operator noticing. One line, at INFO, naming both. Never the DSN.
    _LOG.info(
        "host verified",
        extra={
            "environment": settings.environment,
            "env_file": env_file(),
            "ffmpeg": settings.ffmpeg_binary,
            "locales": len(settings.supported_languages),
            "catalogue_languages": len(translator.catalogs),
        },
    )
