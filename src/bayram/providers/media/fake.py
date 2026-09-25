"""A ``MediaGenProvider`` that renders real, decodable files offline. Tests and local dev.

The default backend under ``use_fake_providers`` (IMAGE_VIDEO_SPEC §4.3, §10). What it hands
back is a genuine PNG at the requested size (Pillow, a flat colour derived from the seed, so
the two variants of one image request differ) or a genuine 5.06 s H.264 MP4 vendored beside
this file — because the stages after it run ffprobe, Pillow and Telegram's size checks, and
a placeholder like ``b"fake-image"`` would pass the provider tests and fail the first real
consumer.

It keeps the real adapter's contract where the stage chain depends on it: requests are
validated the same way (:func:`bayram.providers.media.local_gateway.build_generate_payload`
for the local geometry and allowlist), a job stays ``running`` for a configurable number of
polls, ``cancel`` is ``Ok(False)``, and ``max_bytes`` is enforced on fetch. Every submit is
recorded, which is what "a crashed worker re-run submits once" is asserted against (§10 M2.4).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Final

from PIL import Image

from bayram.contracts import HealthState, ProviderHealth, Result, err, is_err, ok
from bayram.errors import (
    BayramError,
    NotFoundError,
    ProviderInvalidResponseError,
    ValidationError,
)
from bayram.media.contracts import (
    PRE_SUBMIT,
    SUBMIT_PHASE_KEY,
    CostEstimate,
    GeneratedMedia,
    JobHandle,
    JobPhase,
    JobStatus,
    MediaCapabilities,
    MediaRequest,
    QueuedJob,
)
from bayram.providers.media.local_gateway import CLIENT_TAG, build_generate_payload

__all__ = ["FakeMediaProvider", "FakeSubmit", "FAKE_PROVIDER_NAME", "fake_clip_bytes"]

FAKE_PROVIDER_NAME: Final[str] = "fake_media"

_CLIP_RESOURCE: Final[str] = "fake_clip.mp4"


def fake_clip_bytes() -> bytes:
    """The vendored clip: 144×256, 16 fps, 81 frames (5.06 s), H.264, silent."""
    return (resources.files("bayram.providers.media") / "assets" / _CLIP_RESOURCE).read_bytes()


def _png(width: int, height: int, seed: int) -> bytes:
    digest = hashlib.sha256(seed.to_bytes(8, "big", signed=True)).digest()
    colour = (digest[0], digest[1], digest[2])
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass(frozen=True, slots=True)
class FakeSubmit:
    """One recorded submit — what the stage asked for, minus the image bytes."""

    remote_id: str
    request: MediaRequest
    correlation_key: str


@dataclass(slots=True)
class _Job:
    request: MediaRequest
    polls: int = 0


@dataclass(slots=True)
class FakeMediaProvider:
    """Deterministic and programmable. Configure the knobs; read ``submits`` afterwards."""

    name: str = FAKE_PROVIDER_NAME
    #: Polls that answer ``running`` before the job reaches :attr:`outcome`.
    polls_until_done: int = 0
    #: The terminal phase every job reaches. ``UNKNOWN`` models the gateway losing a job.
    outcome: JobPhase = JobPhase.SUCCEEDED
    #: 1 mirrors the local gateway (collage path); raise it to exercise native refs (§4.4).
    max_reference_images: int = 1
    #: Errors handed out by the next submits, in order, before any job is created.
    submit_errors: list[BayramError] = field(default_factory=list)
    submits: list[FakeSubmit] = field(default_factory=list)
    #: What ``health`` reports (§7.2 step 1: an unhealthy backend is not quoted).
    health_state: HealthState = HealthState.HEALTHY
    #: Entries ``queued_jobs`` lists beside our own unfinished jobs: somebody else's render
    #: (the owner's marketing), or a job an ambiguous POST queued that we hold no id for.
    foreign_jobs: list[QueuedJob] = field(default_factory=list)
    #: When set, ``queued_jobs`` answers this instead — the gateway's queue is unreadable.
    queue_error: BayramError | None = None
    _jobs: dict[str, _Job] = field(default_factory=dict)

    def capabilities(self) -> MediaCapabilities:
        return MediaCapabilities(
            kinds=frozenset({"image", "video"}),
            max_reference_images=self.max_reference_images,
            native_audio=False,
            durations_s=(81 / 16,),
            aspects=frozenset({"9:16", "1:1", "16:9"}),
            cancel="none",
            estimate="table",
            webhook=False,
            idempotent_submit=False,
            provider_moderation=False,
            output_retention_s=None,
        )

    async def estimate_cost(self, req: MediaRequest) -> Result[CostEstimate]:
        return ok(CostEstimate(usd=0.0, basis="table"))

    async def submit(
        self,
        req: MediaRequest,
        *,
        correlation_key: str,
        webhook_url: str | None,
        timeout_s: float,
    ) -> Result[JobHandle]:
        # The local gateway's own validation, so a request the real adapter would refuse is
        # refused here too. Refs are judged by count only: the fake never reads the file.
        if len(req.refs) > self.max_reference_images:
            return err(_refs_refusal(len(req.refs), self.max_reference_images))
        built = build_generate_payload(
            replace(req, refs=req.refs[:1]),
            image="data:image/jpeg;base64," if req.refs else None,
        )
        if is_err(built):
            return built
        if self.submit_errors:
            return err(self.submit_errors.pop(0))
        remote_id = f"fake-{len(self.submits) + 1}"
        self.submits.append(
            FakeSubmit(remote_id=remote_id, request=req, correlation_key=correlation_key)
        )
        self._jobs[remote_id] = _Job(request=req)
        return ok(
            JobHandle(
                provider=self.name, remote_id=remote_id, kind=req.kind, model_key=req.model_key
            )
        )

    async def poll(self, handle: JobHandle, *, timeout_s: float) -> Result[JobStatus]:
        job = self._jobs.get(handle.remote_id)
        if job is None:
            # What the gateway says about an id it never issued (§4.2).
            return ok(JobStatus(phase=JobPhase.UNKNOWN))
        job.polls += 1
        if job.polls <= self.polls_until_done:
            return ok(JobStatus(phase=JobPhase.RUNNING))
        count = 1 if self.outcome is JobPhase.SUCCEEDED else 0
        return ok(JobStatus(phase=self.outcome, output_count=count))

    async def fetch(
        self,
        handle: JobHandle,
        index: int,
        dest: Path,
        *,
        max_bytes: int,
        timeout_s: float,
    ) -> Result[GeneratedMedia]:
        job = self._jobs.get(handle.remote_id)
        if job is None or index != 0 or self.outcome is not JobPhase.SUCCEEDED:
            return err(NotFoundError("the fake has no such result"))
        request = job.request
        if request.kind == "image":
            data, mime = _png(request.width, request.height, request.seed), "image/png"
        else:
            data, mime = fake_clip_bytes(), "video/mp4"
        if len(data) > max_bytes:
            return err(
                ProviderInvalidResponseError(
                    "the result exceeds the size limit",
                    provider=self.name,
                    is_retryable=False,
                    context={"max_bytes": max_bytes},
                )
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return ok(
            GeneratedMedia(
                path=dest, mime=mime, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
            )
        )

    async def cancel(self, handle: JobHandle) -> Result[bool]:
        return ok(False)

    async def health(self) -> Result[ProviderHealth]:
        return ok(
            ProviderHealth(name=self.name, state=self.health_state, as_of=datetime.now(tz=UTC))
        )

    async def queued_jobs(self, *, timeout_s: float) -> Result[tuple[QueuedJob, ...]]:
        """Our jobs not yet polled to their end, then :attr:`foreign_jobs` — the local
        gateway's ``GET /queue`` (:class:`~bayram.media.contracts.GatewayQueueReader`)."""
        if self.queue_error is not None:
            return err(self.queue_error)
        ours = tuple(
            QueuedJob(job_id=remote_id, model=job.request.model_key, client=CLIENT_TAG)
            for remote_id, job in self._jobs.items()
            if job.polls <= self.polls_until_done
        )
        return ok((*ours, *self.foreign_jobs))


def _refs_refusal(refs: int, limit: int) -> BayramError:
    return ValidationError(
        "more reference images than this backend takes; composite first",
        context={SUBMIT_PHASE_KEY: PRE_SUBMIT, "refs": refs, "limit": limit},
    )
