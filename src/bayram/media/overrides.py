"""The operator's Redis switches for media (IMAGE_VIDEO_SPEC §4.5). Three keys, spelled once.

* ``media:backend:<sku>`` — overrides the env backend for NEW submits; an unknown value is
  ignored, loudly;
* ``media:paused:<sku>`` — the kill switch: SKU hidden from the picker, open quotes answer
  ``media.busy``, paid jobs continue;
* ``media:gpu:reserved_until`` — an ISO instant; while it is in the future every SKU on
  ``local`` refuses at Done/quote (O11).

The ``bayram.payme.pause`` pattern — one writer (``python -m bayram.tools.media``, and the admin
panel when §8 lands), one set of readers, a three-method store Protocol so the failure modes
are testable without Redis — with **one deliberate difference in how a failed read is read**:

* the payme pause fails OPEN, because a cache outage must not stop every song sale;
* a media pause and the GPU window fail CLOSED (paused / reserved). Nothing about a media job
  works without Redis anyway — the GPU lock, the fair queue and every ARQ stage live there
  (§3.3, §3.4) — so answering "busy" costs no sale that could have been delivered, and it
  never takes money for a job the pipeline could not run (NFR-20).
* a backend override that cannot be read is simply absent: the env backend is the one the
  deployment was configured and boot-checked with.

Writes raise :class:`~bayram.errors.StorageError`, exactly as ``set_paused`` does: an operator
who flips a kill switch is about to act on believing it flipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol, runtime_checkable

from bayram.db.enums import MediaBackend, MediaSku
from bayram.errors import StorageError
from bayram.logging import get_logger

__all__ = [
    "MediaSwitchStore",
    "MediaOverrides",
    "BACKEND_KEY_PREFIX",
    "PAUSED_KEY_PREFIX",
    "GPU_RESERVED_KEY",
    "backend_key",
    "paused_key",
    "read_backend_override",
    "read_paused",
    "read_gpu_reserved_until",
    "read_overrides",
    "set_backend_override",
    "set_paused",
    "set_gpu_reserved_until",
]

_LOG = get_logger(__name__)

BACKEND_KEY_PREFIX: Final[str] = "media:backend:"
PAUSED_KEY_PREFIX: Final[str] = "media:paused:"
GPU_RESERVED_KEY: Final[str] = "media:gpu:reserved_until"

_PAUSED_VALUE: Final[str] = "1"
#: Hand-typed values that mean "not paused" — ``SET media:paused:image 0`` must not pause.
_OPEN_VALUES: Final[frozenset[str]] = frozenset({"", "0", "false", "no", "off"})


@runtime_checkable
class MediaSwitchStore(Protocol):
    """The three Redis commands used here. ``ArqRedis`` satisfies it with no adapter."""

    async def get(self, name: str) -> Any: ...

    async def set(self, name: str, value: str) -> Any: ...

    async def delete(self, *names: str) -> Any: ...


def backend_key(sku: MediaSku) -> str:
    return f"{BACKEND_KEY_PREFIX}{sku.value}"


def paused_key(sku: MediaSku) -> str:
    return f"{PAUSED_KEY_PREFIX}{sku.value}"


@dataclass(frozen=True, slots=True)
class MediaOverrides:
    """Everything the operator has said about one SKU, read in one go."""

    backend: MediaBackend | None
    is_paused: bool
    gpu_reserved_until: datetime | None

    def is_gpu_reserved(self, now: datetime) -> bool:
        return self.gpu_reserved_until is not None and self.gpu_reserved_until > now


def _text(stored: object) -> str | None:
    """``decode_responses`` differs between clients; accept bytes and str alike."""
    if stored is None:
        return None
    if isinstance(stored, bytes | bytearray):
        return stored.decode("utf-8", "replace").strip()
    return str(stored).strip()


async def read_backend_override(store: MediaSwitchStore, sku: MediaSku) -> MediaBackend | None:
    """The override, or ``None``. An unreadable or unknown value is ignored LOUDLY."""
    key = backend_key(sku)
    try:
        raw = _text(await store.get(key))
    except Exception as exc:
        _LOG.warning(
            "a media backend override could not be read; using the env backend",
            extra={"key": key, "detail": repr(exc)},
        )
        return None
    if not raw:
        return None
    try:
        return MediaBackend(raw.lower())
    except ValueError:
        # §4.5: "unknown → ignored + alert". ERROR, because somebody meant to reroute paid
        # traffic and it is not happening.
        _LOG.error(
            "a media backend override names no known backend; ignored",
            extra={"key": key, "value": raw[:32]},
        )
        return None


async def read_paused(store: MediaSwitchStore, sku: MediaSku) -> bool:
    """Is the SKU's kill switch on? **A read that fails answers ``True``** (module docstring)."""
    key = paused_key(sku)
    try:
        raw = _text(await store.get(key))
    except Exception as exc:
        _LOG.warning(
            "a media pause switch could not be read; treating the SKU as paused",
            extra={"key": key, "detail": repr(exc)},
        )
        return True
    return raw is not None and raw.lower() not in _OPEN_VALUES


def _parse_instant(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def read_gpu_reserved_until(store: MediaSwitchStore) -> datetime | None:
    """The end of the operator's GPU window, or ``None``.

    Fails CLOSED: an unreadable key or an unparseable value answers ``datetime.max`` (UTC),
    i.e. "reserved", because the window exists so a marketing render is not pre-empted by a
    sale we then could not render in time (O11).
    """
    try:
        raw = _text(await store.get(GPU_RESERVED_KEY))
    except Exception as exc:
        _LOG.warning(
            "the GPU reserved window could not be read; treating the GPU as reserved",
            extra={"key": GPU_RESERVED_KEY, "detail": repr(exc)},
        )
        return datetime.max.replace(tzinfo=UTC)
    if not raw:
        return None
    parsed = _parse_instant(raw)
    if parsed is None:
        _LOG.error(
            "the GPU reserved window is not an ISO instant; treating the GPU as reserved",
            extra={"key": GPU_RESERVED_KEY, "value": raw[:40]},
        )
        return datetime.max.replace(tzinfo=UTC)
    return parsed


async def read_overrides(store: MediaSwitchStore, sku: MediaSku) -> MediaOverrides:
    """All three switches for ``sku``. Never raises."""
    return MediaOverrides(
        backend=await read_backend_override(store, sku),
        is_paused=await read_paused(store, sku),
        gpu_reserved_until=await read_gpu_reserved_until(store),
    )


async def _write(store: MediaSwitchStore, key: str, value: str | None) -> None:
    try:
        if value is None:
            await store.delete(key)
        else:
            await store.set(key, value)
    except Exception as exc:
        raise StorageError(
            "a media switch could not be written, so it is unchanged",
            is_retryable=True,
            context={"key": key, "detail": repr(exc)},
            cause=exc,
        ) from exc
    _LOG.info("an operator changed a media switch", extra={"key": key, "value": value})


async def set_backend_override(
    store: MediaSwitchStore, sku: MediaSku, backend: MediaBackend | None
) -> None:
    """Route new submits for ``sku`` to ``backend``; ``None`` returns to the env backend.

    Not boot-checked the way the env backend is, so an operator switching to a backend
    that costs money should re-run ``status``; every quote still runs the margin check
    against the effective backend (§4.3).
    """
    await _write(store, backend_key(sku), None if backend is None else backend.value)


async def set_paused(store: MediaSwitchStore, sku: MediaSku, *, paused: bool) -> None:
    """The kill switch. Resuming DELETES the key, so nothing is left to be misread."""
    await _write(store, paused_key(sku), _PAUSED_VALUE if paused else None)


async def set_gpu_reserved_until(store: MediaSwitchStore, until: datetime | None) -> None:
    """Open (``until`` in the future) or close (``None``) the GPU reserved window (O11)."""
    if until is not None and until.tzinfo is None:
        raise StorageError(
            "the GPU reserved window needs a timezone-aware instant",
            context={"key": GPU_RESERVED_KEY},
        )
    await _write(store, GPU_RESERVED_KEY, None if until is None else until.isoformat())
