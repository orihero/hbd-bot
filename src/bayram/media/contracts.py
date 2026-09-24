"""The generation-backend contract every media provider is held to (IMAGE_VIDEO_SPEC §4.1).

The same house rules as :mod:`bayram.contracts`, restated because they carry the design:

* every method is ``async`` and returns a ``Result``; **no method raises across the
  boundary** — an escaped ``httpx`` exception would bypass the stage's retry decision, which
  is the only thing that tells "try again" from "reconcile";
* the value objects are frozen, and a :class:`MediaRequest` is built by our own code from
  screened inputs — ``model_key`` comes from an allowlist and never from a customer.

**Pre-submit versus ambiguous is the distinction the whole stage chain turns on**, so it is
carried on the error rather than guessed from its class: a submit failure's
``context["submit_phase"]`` is :data:`PRE_SUBMIT` (no job exists; another backend may be
tried — §3.3 "fallback only on a pre-submit error") or :data:`AMBIGUOUS` (a job may exist; the
attempt is marked ``ambiguous`` and reconciled, never re-posted). :func:`is_pre_submit` and
:func:`is_ambiguous` are the two readers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, Protocol, runtime_checkable

from bayram.contracts import ProviderHealth, Result
from bayram.db.enums import MediaAttemptStatus
from bayram.errors import BayramError, ProviderAmbiguousError

__all__ = [
    "MediaKindName",
    "MediaCapabilities",
    "MediaRequest",
    "JobHandle",
    "JobPhase",
    "JobStatus",
    "GeneratedMedia",
    "CostEstimate",
    "MediaGenProvider",
    "SUBMIT_PHASE_KEY",
    "PRE_SUBMIT",
    "AMBIGUOUS",
    "is_pre_submit",
    "is_ambiguous",
    "ATTEMPT_STATUS_FOR_PHASE",
]

type MediaKindName = Literal["image", "video"]

#: The error-context key a submit failure is classified under, and its two values.
SUBMIT_PHASE_KEY: Final[str] = "submit_phase"
PRE_SUBMIT: Final[str] = "pre_submit"
AMBIGUOUS: Final[str] = "ambiguous"


@dataclass(frozen=True, slots=True)
class MediaCapabilities:
    """What a backend can do, read by routing and by the collage decision (§4.4)."""

    kinds: frozenset[MediaKindName]
    #: The local gateway takes one ``image`` string, so several photos become a collage.
    max_reference_images: int
    #: Whether the model can make sound. We always request silent and mux our own (§5.6).
    native_audio: bool
    durations_s: tuple[float, ...]
    aspects: frozenset[str]
    cancel: Literal["none", "queued_only", "any"]
    estimate: Literal["exact", "table", "none"]
    webhook: bool
    #: False for every backend we have: a repeated POST is a second job (R7).
    idempotent_submit: bool
    provider_moderation: bool
    output_retention_s: int | None


@dataclass(frozen=True, slots=True)
class MediaRequest:
    """One generation job — one output. An image request's two variants are two of these."""

    kind: MediaKindName
    #: From the backend's allowlist, never user input (§4.2).
    model_key: str
    #: The screened prompt, verbatim. Never logged.
    prompt: str
    #: Already composited when the backend takes fewer references than there are photos.
    refs: tuple[Path, ...]
    width: int
    height: int
    length_frames: int | None
    fps: int | None
    steps: int
    seed: int
    denoise: float | None


@dataclass(frozen=True, slots=True)
class JobHandle:
    """What a successful submit returns and every later call is keyed on."""

    provider: str
    remote_id: str
    kind: MediaKindName
    model_key: str


class JobPhase(StrEnum):
    """A backend job's state in our vocabulary. Nothing downstream reads a vendor string."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED_CONTENT = "rejected_content"
    #: The backend does not know the id (the local gateway answers 200 ``{status:"unknown"}``).
    #: **Terminal** — a poll loop that waited for it to change would spin until the deadline.
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self not in (JobPhase.QUEUED, JobPhase.RUNNING)


#: What a terminal phase makes of the ``media_attempts`` row (§3.3 ``media_poll``). ``UNKNOWN``
#: is ``ambiguous``, never ``failed``: a failed attempt may be retried, an ambiguous one is
#: reconciled first (§4.2). The two live phases are absent — the attempt stays ``submitted``.
ATTEMPT_STATUS_FOR_PHASE: Final[Mapping[JobPhase, MediaAttemptStatus]] = MappingProxyType(
    {
        JobPhase.SUCCEEDED: MediaAttemptStatus.SUCCEEDED,
        JobPhase.FAILED: MediaAttemptStatus.FAILED,
        JobPhase.REJECTED_CONTENT: MediaAttemptStatus.REJECTED,
        JobPhase.UNKNOWN: MediaAttemptStatus.AMBIGUOUS,
    }
)


@dataclass(frozen=True, slots=True)
class JobStatus:
    phase: JobPhase
    #: How many results ``fetch`` may ask for; 0 until the job succeeds.
    output_count: int = 0
    #: Short, vendor-free operator text. Never a response body (it can quote the prompt).
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class GeneratedMedia:
    """A fetched result, already on disk. Bytes are never held in memory (§3.6)."""

    path: Path
    mime: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """One submit's expected cash cost. ``usd=None`` is "not known", never "free"."""

    usd: float | None
    basis: Literal["exact", "table", "none"]


@runtime_checkable
class MediaGenProvider(Protocol):
    """An image/video generation backend (IMAGE_VIDEO_SPEC §4.1). Nothing here raises."""

    name: str

    def capabilities(self) -> MediaCapabilities: ...

    async def estimate_cost(self, req: MediaRequest) -> Result[CostEstimate]: ...

    async def submit(
        self,
        req: MediaRequest,
        *,
        correlation_key: str,
        webhook_url: str | None,
        timeout_s: float,
    ) -> Result[JobHandle]:
        """Start one job. A failure is classified :data:`PRE_SUBMIT` or :data:`AMBIGUOUS`."""
        ...

    async def poll(self, handle: JobHandle, *, timeout_s: float) -> Result[JobStatus]: ...

    async def fetch(
        self,
        handle: JobHandle,
        index: int,
        dest: Path,
        *,
        max_bytes: int,
        timeout_s: float,
    ) -> Result[GeneratedMedia]: ...

    async def cancel(self, handle: JobHandle) -> Result[bool]:
        """``Ok(False)`` means "not cancellable", which is a normal answer, not a failure."""
        ...

    async def health(self) -> Result[ProviderHealth]: ...


def _submit_phase(error: BayramError) -> object:
    return error.context.get(SUBMIT_PHASE_KEY)


def is_pre_submit(error: BayramError) -> bool:
    """No job exists at the backend; falling back to another backend is safe (§3.3)."""
    return _submit_phase(error) == PRE_SUBMIT


def is_ambiguous(error: BayramError) -> bool:
    """A job may exist; the attempt must be reconciled, never re-posted (§4.1)."""
    return isinstance(error, ProviderAmbiguousError) or _submit_phase(error) == AMBIGUOUS
