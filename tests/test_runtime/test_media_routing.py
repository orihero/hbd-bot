"""Routing in the stage chain: native references and the fallback (IMAGE_VIDEO_SPEC §3.3, §4;
§10 M6.2).

Over the fakes of ``media_fakes``, with one fake provider per backend so the test can tell
which backend a request went to:

* **several photos go natively on a multi-ref backend** — no collage is built, the request
  carries every photo (O6, §4.4);
* with a one-ref fallback configured, the collage is screened too, the primary still gets the
  originals, and a job moved onto the fallback sends the collage;
* **fallback only on a pre-submit error** (§3.3): an unavailable backend moves the job; an
  ambiguous submit, our own refusal of the request, or no configured fallback do not; and a
  job with anything already posted never moves.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from bayram.config import Settings
from bayram.contracts import Err, Result, err, ok
from bayram.db.engine import create_session_factory
from bayram.db.enums import (
    MediaAttemptStage,
    MediaAttemptStatus,
    MediaBackend,
    MediaJobState,
)
from bayram.db.media import insert_attempt, load_job, set_attempt_status, switch_backend
from bayram.db.models import Base
from bayram.db.models.media_attempt import MediaAttemptRow
from bayram.db.models.media_input import MediaInputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.errors import (
    ProviderAmbiguousError,
    ProviderUnavailableError,
    ValidationError,
)
from bayram.media.contracts import (
    AMBIGUOUS,
    PRE_SUBMIT,
    SUBMIT_PHASE_KEY,
    CostEstimate,
    MediaRequest,
)
from bayram.media.service import BetaStart, start_free_beta
from bayram.media.stages import MEDIA_SCREEN_JOB, MEDIA_SUBMIT_JOB, screen_job_id
from bayram.providers.media.fake import FakeMediaProvider
from bayram.runtime.gpu_lock import queue_member
from tests.conftest import FIXED_NOW
from tests.test_runtime.media_fakes import (
    USER,
    Harness,
    HookedProvider,
    build_harness,
    freeze_job,
    jpeg_bytes,
    media_settings,
)

_THREE_PHOTOS: Final[tuple[bytes, ...]] = (
    jpeg_bytes((200, 40, 40)),
    jpeg_bytes((40, 200, 40)),
    jpeg_bytes((40, 40, 200)),
)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


class Backends:
    """One provider per backend. ``primary`` is the SKU's (the fake backend, taking up to four
    references); ``fallback`` the local gateway's stand-in (one reference, collage path)."""

    def __init__(self) -> None:
        self.primary = HookedProvider(FakeMediaProvider(name="primary", max_reference_images=4))
        self.fallback = HookedProvider(FakeMediaProvider(name="fallback", max_reference_images=1))

    def __call__(self, backend: MediaBackend) -> Any:
        return self.fallback if backend is MediaBackend.LOCAL else self.primary


def _harness(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    **update: Any,
) -> tuple[Harness, Backends]:
    """Real routing, so ``use_fake_providers`` is off: the image SKU renders on ``fake`` (the
    multi-ref primary) and ``update`` may give it a fallback. Nothing here reaches a vendor —
    every backend is a provider object of this module."""
    harness = build_harness(
        media_settings(settings, use_fake_providers=False, **update),
        sessions,
        tmp_path,
        FIXED_NOW,
    )
    backends = Backends()
    harness.rt = dataclasses.replace(harness.rt, providers=backends)
    return harness, backends


async def _job(harness: Harness, job_id: UUID) -> MediaJobRow:
    async with harness.sessions() as session:
        job = await load_job(session, job_id)
    assert job is not None
    return job


async def _roles(harness: Harness, job_id: UUID) -> list[str]:
    async with harness.sessions() as session:
        roles = await session.scalars(
            sa.select(MediaInputRow.role).where(MediaInputRow.job_id == job_id)
        )
        return sorted(role.value for role in roles.all())


async def _attempts(harness: Harness, job_id: UUID) -> list[tuple[int, int, str, str]]:
    async with harness.sessions() as session:
        rows = await session.scalars(
            sa.select(MediaAttemptRow)
            .where(MediaAttemptRow.job_id == job_id)
            .order_by(MediaAttemptRow.variant, MediaAttemptRow.attempt)
        )
        return [(r.variant, r.attempt, r.provider, r.status.value) for r in rows.all()]


async def _quote_and_start(harness: Harness, job_id: UUID) -> None:
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED
    outcome = await start_free_beta(
        harness.sessions,
        harness.queue,
        harness.rt.settings,
        job_id=job_id,
        telegram_user_id=USER,
        is_paused=False,
        now=harness.clock(),
    )
    assert outcome is BetaStart.STARTED


def _unavailable() -> ProviderUnavailableError:
    return ProviderUnavailableError(
        "the backend is down", provider="primary", context={SUBMIT_PHASE_KEY: PRE_SUBMIT}
    )


def _fail_every_submit_with(backends: Backends, make: Any) -> None:
    async def hook(req: MediaRequest, key: str) -> Err | None:
        return err(make())

    backends.primary.submit_hook = hook


# ---------------------------------------------------------------------------
# The native multi-ref path (§4.4, O6)
# ---------------------------------------------------------------------------
async def test_several_photos_go_natively_to_a_multi_ref_backend_with_no_collage(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange — no fallback: the route is the multi-ref primary alone.
    harness, backends = _harness(settings, sessions, tmp_path)
    job_id = await freeze_job(harness, photos=_THREE_PHOTOS)

    # Act
    await _quote_and_start(harness, job_id)
    assert await _roles(harness, job_id) == ["photo", "photo", "photo"]
    await harness.drain()

    # Assert — no collage was made or screened; each variant carried all three photos.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert set(harness.moderator.subjects_screened("image")) == {"upload", "output_image"}
    submits = backends.primary.inner.submits
    assert len(submits) == 2 and all(len(s.request.refs) == 3 for s in submits)
    assert backends.fallback.inner.submits == []


async def test_a_one_ref_fallback_gets_a_screened_collage_while_the_primary_gets_originals(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange
    harness, backends = _harness(settings, sessions, tmp_path, image_fallback_backend="local")
    job_id = await freeze_job(harness, photos=_THREE_PHOTOS)

    # Act
    await _quote_and_start(harness, job_id)

    # Assert — the collage exists and was screened with the uploads before any quote ...
    assert await _roles(harness, job_id) == ["collage", "photo", "photo", "photo"]
    assert set(harness.moderator.subjects_screened("image")) == {"upload", "collage"}
    await harness.drain()

    # ... and the primary still rendered from the originals.
    assert (await _job(harness, job_id)).state is MediaJobState.DELIVERED
    assert all(len(s.request.refs) == 3 for s in backends.primary.inner.submits)
    assert backends.fallback.inner.submits == []


# ---------------------------------------------------------------------------
# Fallback only on a pre-submit error (§3.3)
# ---------------------------------------------------------------------------
async def test_an_unavailable_backend_moves_the_job_to_its_fallback_which_gets_the_collage(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange
    harness, backends = _harness(settings, sessions, tmp_path, image_fallback_backend="local")
    _fail_every_submit_with(backends, _unavailable)
    job_id = await freeze_job(harness, photos=_THREE_PHOTOS)

    # Act
    await _quote_and_start(harness, job_id)
    await harness.drain()

    # Assert — re-stamped onto the fallback, delivered from it, one collage per request.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert job.backend is MediaBackend.LOCAL
    assert job.model_id == harness.rt.settings.genai_image_model
    assert backends.primary.inner.submits == []
    fallback_submits = backends.fallback.inner.submits
    assert len(fallback_submits) == 2 and all(len(s.request.refs) == 1 for s in fallback_submits)
    attempts = await _attempts(harness, job_id)
    assert ("primary", "failed") in {(p, s) for _, _, p, s in attempts}
    assert {(p, s) for _, _, p, s in attempts if p == "fallback"} == {("fallback", "succeeded")}
    assert await harness.gpu.members() == () and await harness.gpu.holder() is None


async def test_an_ambiguous_submit_never_falls_back(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange — the primary answers "maybe" to every POST.
    harness, backends = _harness(settings, sessions, tmp_path, image_fallback_backend="local")
    _fail_every_submit_with(
        backends,
        lambda: ProviderAmbiguousError(
            "no id came back", provider="primary", context={SUBMIT_PHASE_KEY: AMBIGUOUS}
        ),
    )
    job_id = await freeze_job(harness, photos=())

    # Act
    await _quote_and_start(harness, job_id)
    await harness.drain()

    # Assert — the job never left its backend and the fallback was never asked.
    job = await _job(harness, job_id)
    assert job.backend is MediaBackend.FAKE
    assert backends.fallback.inner.submits == []
    assert all(p == "primary" for _, _, p, _ in await _attempts(harness, job_id))


async def test_our_own_refusal_of_the_request_does_not_fall_back(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange — a pre-submit refusal about the REQUEST (a reference the model cannot take).
    harness, backends = _harness(settings, sessions, tmp_path, image_fallback_backend="local")
    _fail_every_submit_with(
        backends,
        lambda: ValidationError("composite first", context={SUBMIT_PHASE_KEY: PRE_SUBMIT}),
    )
    job_id = await freeze_job(harness, photos=())

    # Act
    await _quote_and_start(harness, job_id)
    await harness.drain()

    # Assert — retried where it was, then failed; never moved.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED
    assert job.backend is MediaBackend.FAKE
    assert backends.fallback.inner.submits == []


async def test_with_no_fallback_configured_an_unavailable_backend_retries_where_it_is(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    harness, backends = _harness(settings, sessions, tmp_path)
    _fail_every_submit_with(backends, _unavailable)
    job_id = await freeze_job(harness, photos=())

    await _quote_and_start(harness, job_id)
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.backend is MediaBackend.FAKE
    attempts = await _attempts(harness, job_id)
    assert {p for _, _, p, _ in attempts} == {"primary"}
    assert max(a for _, a, _, _ in attempts) == harness.rt.settings.media_max_attempts


async def test_a_job_with_an_attempt_already_posted_never_moves(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange — variant 1 is already on the primary (submitted, with a remote id).
    harness, _ = _harness(settings, sessions, tmp_path, image_fallback_backend="local")
    job_id = await freeze_job(harness, photos=())
    now = harness.clock()
    async with harness.sessions.begin() as session:
        await session.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job_id)
            .values(state=MediaJobState.GENERATING, backend=MediaBackend.FAKE)
        )
        attempt_id = await insert_attempt(
            session,
            job_id=job_id,
            stage=MediaAttemptStage.IMAGE,
            variant=1,
            attempt=1,
            provider="primary",
            now=now,
        )
        assert attempt_id is not None
        await set_attempt_status(
            session,
            attempt_id,
            expected=(MediaAttemptStatus.SUBMITTING,),
            status=MediaAttemptStatus.SUBMITTED,
            now=now,
            remote_id="primary-1",
        )

    # Act — variant 0's pre-submit failure asks for the move.
    async with harness.sessions.begin() as session:
        moved = await switch_backend(
            session,
            job_id,
            stage=MediaAttemptStage.IMAGE,
            current=MediaBackend.FAKE,
            to=MediaBackend.LOCAL,
            model_id="flux2",
            working=(MediaJobState.QUEUED, MediaJobState.GENERATING),
            now=now,
        )

    # Assert — refused: its poll must keep asking the backend that holds that id.
    assert moved is False
    assert (await _job(harness, job_id)).backend is MediaBackend.FAKE


async def test_a_job_moves_only_from_the_backend_it_is_on(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    harness, _ = _harness(settings, sessions, tmp_path)
    job_id = await freeze_job(harness, photos=())
    async with harness.sessions.begin() as session:
        await session.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job_id)
            .values(state=MediaJobState.QUEUED, backend=MediaBackend.LOCAL)
        )

    async with harness.sessions.begin() as session:
        moved = await switch_backend(
            session,
            job_id,
            stage=MediaAttemptStage.IMAGE,
            current=MediaBackend.FAKE,
            to=MediaBackend.LOCAL,
            model_id="flux2",
            working=(MediaJobState.QUEUED,),
            now=harness.clock(),
        )

    assert moved is False


async def test_a_paid_backend_that_cannot_estimate_falls_back_onto_the_gpu_queue(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange — Higgsfield primary (no GPU), the local gateway as its fallback. Its /estimate
    # answers at the quote and is down by the submit: an estimate creates nothing, so this is
    # a pre-submit refusal (§4.3, §3.3).
    harness, backends = _harness(
        settings,
        sessions,
        tmp_path,
        image_backend="higgsfield",
        image_fallback_backend="local",
        higgsfield_image_usd_per_output=0.02,
        media_uzs_per_usd=12_500.0,
        image_max_cost_usd=0.20,
    )
    job_id = await freeze_job(harness, photos=())

    # Act
    await _quote_and_start(harness, job_id)
    backends.primary.estimate_error = ProviderUnavailableError("down", provider="higgsfield")
    await harness.drain()

    # Assert — nothing was posted to Higgsfield; both images came from the GPU, which the
    # job joined when it moved and left when it finished.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert job.backend is MediaBackend.LOCAL
    assert backends.primary.estimates >= 1 and backends.primary.inner.submits == []
    assert len(backends.fallback.inner.submits) == 2
    assert await harness.gpu.members() == () and await harness.gpu.holder() is None


async def test_a_cost_over_the_ceiling_does_not_fall_back(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    harness, backends = _harness(
        settings,
        sessions,
        tmp_path,
        image_backend="higgsfield",
        image_fallback_backend="local",
        higgsfield_image_usd_per_output=0.02,
        media_uzs_per_usd=12_500.0,
        image_max_cost_usd=0.20,
    )
    job_id = await freeze_job(harness, photos=())

    await _quote_and_start(harness, job_id)
    # The price rose between the quote and the submit: one image alone is now over the whole
    # request's ceiling.
    backends.primary.estimate_usd = 0.50
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED
    assert job.backend is MediaBackend.HIGGSFIELD
    assert backends.fallback.inner.submits == [] and backends.primary.inner.submits == []
    # A ceiling refusal is final: one estimate per variant, never re-estimated (§4.3).
    assert await _attempts(harness, job_id) == [
        (0, 1, "primary", "failed"),
        (1, 1, "primary", "failed"),
    ]
    async with harness.sessions() as session:
        codes = set(
            (
                await session.scalars(
                    sa.select(MediaAttemptRow.error_code).where(MediaAttemptRow.job_id == job_id)
                )
            ).all()
        )
    assert codes == {"cost_ceiling"}


async def test_a_live_estimate_over_the_ceiling_is_busy_at_the_quote_never_paid(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange — the static figure passes boot, but the live /estimate says the price rose
    # (§4.3 "estimate before quote", NFR-20).
    harness, backends = _harness(
        settings,
        sessions,
        tmp_path,
        image_backend="higgsfield",
        higgsfield_image_usd_per_output=0.02,
        media_uzs_per_usd=12_500.0,
        image_max_cost_usd=0.20,
    )
    backends.primary.estimate_usd = 0.15  # × 2 images = 0.30, over the 0.20 ceiling
    job_id = await freeze_job(harness, photos=())

    # Act
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()

    # Assert — busy on the tray, the row still screening, nothing posted.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.SCREENING
    assert backends.primary.estimates == 1 and backends.primary.inner.submits == []


async def test_an_unreadable_estimate_at_the_quote_is_busy(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    harness, backends = _harness(
        settings,
        sessions,
        tmp_path,
        image_backend="higgsfield",
        higgsfield_image_usd_per_output=0.02,
        media_uzs_per_usd=12_500.0,
    )
    backends.primary.estimate_error = ProviderUnavailableError("down", provider="higgsfield")
    job_id = await freeze_job(harness, photos=())

    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()

    assert (await _job(harness, job_id)).state is MediaJobState.SCREENING


async def test_a_photo_order_on_a_text_only_image_model_is_never_quoted(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange — the primary takes no reference (Higgsfield's soul_standard, max_refs=0).
    harness, backends = _harness(
        settings,
        sessions,
        tmp_path,
        image_backend="higgsfield",
        higgsfield_image_usd_per_output=0.02,
        media_uzs_per_usd=12_500.0,
    )
    backends.primary = HookedProvider(FakeMediaProvider(name="primary", max_reference_images=0))
    job_id = await freeze_job(harness, photos=_THREE_PHOTOS[:1])

    # Act
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()

    # Assert — busy before payment; no estimate asked, nothing posted (§4.3, NFR-20).
    assert (await _job(harness, job_id)).state is MediaJobState.SCREENING
    assert backends.primary.estimates == 0 and backends.primary.inner.submits == []


async def test_the_fallback_is_not_taken_on_the_last_attempt(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange — one attempt per variant: a fallback would be attempt 2, past the budget
    # (§3.3 "counts toward media_max_attempts").
    harness, backends = _harness(
        settings, sessions, tmp_path, image_fallback_backend="local", media_max_attempts=1
    )
    _fail_every_submit_with(backends, _unavailable)
    job_id = await freeze_job(harness, photos=())

    # Act
    await _quote_and_start(harness, job_id)
    await harness.drain()

    # Assert — never moved, never an attempt 2.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.backend is MediaBackend.FAKE
    assert backends.fallback.inner.submits == []
    assert {attempt for _, attempt, _, _ in await _attempts(harness, job_id)} == {1}


async def test_a_move_onto_the_gpu_queues_only_the_variant_that_moves(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Arrange — Higgsfield primary, the GPU as fallback. Variant 1 is refused at the cost
    # ceiling first (final, nothing posted); then variant 0's estimate is down and the job
    # moves onto the GPU (§3.3).
    harness, backends = _harness(
        settings,
        sessions,
        tmp_path,
        image_backend="higgsfield",
        image_fallback_backend="local",
        higgsfield_image_usd_per_output=0.02,
        media_uzs_per_usd=12_500.0,
        image_max_cost_usd=0.20,
    )
    job_id = await freeze_job(harness, photos=())
    await _quote_and_start(harness, job_id)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_SUBMIT_JOB)
    base_seed = job_id.int % 2_000_000_000

    def estimate(req: MediaRequest) -> Result[CostEstimate]:
        if req.seed == base_seed + 1:
            return ok(CostEstimate(usd=0.50, basis="exact"))
        return err(ProviderUnavailableError("down", provider="higgsfield"))

    backends.primary.estimate_hook = estimate
    submits = sorted(
        (stage for stage in harness.queue.pending if stage.name == MEDIA_SUBMIT_JOB),
        key=lambda stage: -int(stage.args[1]),
    )
    assert len(submits) == 2
    harness.queue.pending.clear()

    # Act — variant 1's submit, then variant 0's.
    for stage in submits:
        await harness.run(stage.name, *stage.args)

    # Assert — the job moved; only variant 0 waits on the GPU, not the finished variant 1,
    # whose member nothing would ever remove (§3.4).
    job = await _job(harness, job_id)
    assert job.backend is MediaBackend.LOCAL
    assert await harness.gpu.members() == (queue_member(job_id, 0),)
