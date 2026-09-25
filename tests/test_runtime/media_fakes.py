"""The harness the media stage tests drive the chain through (IMAGE_VIDEO_SPEC §3.3, §10 M2.4).

No network and no Redis: an in-memory SQLite schema, ``LocalFileStorage`` under ``tmp_path``,
the fake provider and moderator, a dict-backed GPU slot and switch store, a messenger that
records instead of sending — and :class:`ArqLikeQueue`, which is the part that matters most.
It **drops an enqueue whose id it has already seen**, exactly as ARQ does for the hour it keeps
a result, so "a deliberate self-re-enqueue runs again" is only green if the stage really does
pick a new id each time.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import wave
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from aiogram.types import InlineKeyboardMarkup
from arq.worker import Retry
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.config import Settings
from bayram.contracts import Err, Language, ProviderHealth, Result, err, ok
from bayram.db.enums import MediaAspect, MediaInputRole, MediaJobState, MediaKind, MediaSku
from bayram.db.media import add_input, create_job
from bayram.db.models import UserRow
from bayram.errors import BayramError, NotFoundError, ValidationError
from bayram.media.contracts import (
    CostEstimate,
    GeneratedMedia,
    JobHandle,
    JobStatus,
    MediaCapabilities,
    MediaRequest,
    QueuedJob,
)
from bayram.media.mux import MuxOutcome, VideoProbe, audio_fit
from bayram.media.narration import NarrationBudget
from bayram.media.stages import (
    MEDIA_CLEANUP_JOB,
    MEDIA_DELIVER_JOB,
    MEDIA_FETCH_JOB,
    MEDIA_MUX_JOB,
    MEDIA_OUTPUT_SCREEN_JOB,
    MEDIA_POLL_JOB,
    MEDIA_PRESCREEN_JOB,
    MEDIA_REVIEW_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_SCRIPT_JOB,
    MEDIA_START_JOB,
    MEDIA_SUBMIT_JOB,
    MEDIA_TTS_JOB,
    MEDIA_VOICE_PREPARE_JOB,
)
from bayram.moderation.fake import FakeModerator
from bayram.moderation.strikes import MemoryStrikeStore
from bayram.providers.media.fake import FakeMediaProvider
from bayram.providers.tts.fakes import FakeNarrationProvider
from bayram.runtime.gpu_lock import MemoryGpuSlotStore
from bayram.runtime.media_jobs import (
    MEDIA_CTX_KEY,
    MediaRuntime,
    media_cleanup,
    media_deliver,
    media_fetch,
    media_mux,
    media_output_screen,
    media_poll,
    media_prescreen,
    media_review_apply,
    media_screen,
    media_script,
    media_start,
    media_submit,
    media_tts,
    media_voice_prepare,
)
from bayram.runtime.media_telegram import TOO_LARGE_KEY
from bayram.storage import LocalFileStorage

USER: Final[int] = 5_550_001_111
TRAY_ID: Final[int] = 77
PROMPT: Final[str] = "a lantern-lit courtyard in Samarkand at dusk"

StageFn = Callable[..., Awaitable[dict[str, Any]]]

STAGES: Final[dict[str, StageFn]] = {
    MEDIA_PRESCREEN_JOB: media_prescreen,
    MEDIA_SCREEN_JOB: media_screen,
    MEDIA_START_JOB: media_start,
    MEDIA_SUBMIT_JOB: media_submit,
    MEDIA_POLL_JOB: media_poll,
    MEDIA_FETCH_JOB: media_fetch,
    MEDIA_OUTPUT_SCREEN_JOB: media_output_screen,
    MEDIA_DELIVER_JOB: media_deliver,
    MEDIA_CLEANUP_JOB: media_cleanup,
    MEDIA_REVIEW_JOB: media_review_apply,
    MEDIA_SCRIPT_JOB: media_script,
    MEDIA_TTS_JOB: media_tts,
    MEDIA_VOICE_PREPARE_JOB: media_voice_prepare,
    MEDIA_MUX_JOB: media_mux,
}


def jpeg_bytes(colour: tuple[int, int, int] = (200, 40, 40), *, exif: bool = True) -> bytes:
    """A small real JPEG, with an EXIF block (orientation + a GPS-ish tag) by default."""
    image = Image.new("RGB", (64, 48), colour)
    buffer = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x0112] = 6  # Orientation: rotate 90° CW to display
        data[0x010F] = "PhoneMaker"
        image.save(buffer, format="JPEG", exif=data.tobytes())
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def animated_gif_bytes() -> bytes:
    frames = [Image.new("RGB", (16, 16), (i * 60, 0, 0)) for i in range(3)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=50)
    return buffer.getvalue()


class MovingClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now = self.now + timedelta(**delta)


@dataclass
class Album:
    chat_id: int
    photos: tuple[Path, ...]
    caption: str


@dataclass
class SentVideo:
    chat_id: int
    path: Path
    caption: str
    width: int | None
    height: int | None
    duration_s: float | None
    data: bytes


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as reader:
        return reader.getnframes() / float(reader.getframerate())


@dataclass
class FakeVideoTools:
    """``VideoTools`` without ffmpeg: copies bytes and answers the shape it is told.

    A WAV is measured for real (the fake narration writes one); anything else is
    :attr:`audio_s`. The render is :attr:`clip`; a mux answers the clip with audio and the
    fit :func:`~bayram.media.mux.audio_fit` gives, so a test reads what would have happened.
    """

    clip: VideoProbe = field(
        default_factory=lambda: VideoProbe(
            width=144,
            height=256,
            duration_s=5.0625,
            codec="h264",
            pix_fmt="yuv420p",
            has_audio=False,
        )
    )
    audio_s: float = 4.0
    muxes: list[tuple[Path, Path, bool]] = field(default_factory=list)
    rewraps: list[Path] = field(default_factory=list)
    #: Failures handed to the next mux or re-wrap calls, in order.
    failures: list[BayramError] = field(default_factory=list)

    def _fail(self) -> Err | None:
        return err(self.failures.pop(0)) if self.failures else None

    async def probe(self, path: Path) -> Result[VideoProbe]:
        return ok(self.clip)

    #: The ``target`` each normalise was asked for (§4.3 geometry), in call order.
    normalise_targets: list[tuple[int, int] | None] = field(default_factory=list)

    async def normalise(
        self, src: Path, dest: Path, *, target: tuple[int, int] | None = None
    ) -> Result[VideoProbe]:
        self.normalise_targets.append(target)
        shutil.copyfile(src, dest)
        return ok(self.clip)

    async def prepare_voice(self, src: Path, dest: Path) -> Result[float]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return ok(self.audio_s)

    async def audio_seconds(self, path: Path) -> Result[float]:
        try:
            return ok(wav_seconds(path))
        except (wave.Error, EOFError):
            return ok(self.audio_s)

    async def mux(
        self, video: Path, audio: Path, dest: Path, *, may_speed_up: bool
    ) -> Result[MuxOutcome]:
        failed = self._fail()
        if failed is not None:
            return failed
        self.muxes.append((video, audio, may_speed_up))
        measured = await self.audio_seconds(audio)
        audio_s = measured.value if not isinstance(measured, Err) else self.audio_s
        shutil.copyfile(video, dest)
        return ok(
            MuxOutcome(
                probe=VideoProbe(
                    width=self.clip.width,
                    height=self.clip.height,
                    duration_s=self.clip.duration_s,
                    codec="h264",
                    pix_fmt="yuv420p",
                    has_audio=True,
                ),
                audio_s=audio_s,
                fit=audio_fit(audio_s, self.clip.duration_s, may_speed_up=may_speed_up),
            )
        )

    async def rewrap(self, src: Path, dest: Path) -> Result[VideoProbe]:
        failed = self._fail()
        if failed is not None:
            return failed
        self.rewraps.append(src)
        shutil.copyfile(src, dest)
        return ok(self.clip)

    async def frames(self, video: Path, outdir: Path) -> Result[tuple[Path, ...]]:
        outdir.mkdir(parents=True, exist_ok=True)
        found = []
        for index in range(2):
            frame = outdir / f"frame-{index}.jpg"
            frame.write_bytes(jpeg_bytes(exif=False))
            found.append(frame)
        return ok(tuple(found))


@dataclass
class FakeScriptWriter:
    """Answers :attr:`lines` in turn (the last one repeats), or :attr:`failure`."""

    lines: list[str] = field(default_factory=lambda: ["Happy birthday, dear friend"])
    failure: BayramError | None = None
    calls: list[tuple[str, Language, NarrationBudget]] = field(default_factory=list)

    async def write(
        self, prompt: str, *, language: Language, budget: NarrationBudget
    ) -> Result[str]:
        self.calls.append((prompt, language, budget))
        if self.failure is not None:
            return err(self.failure)
        index = min(len(self.calls), len(self.lines)) - 1
        return ok(self.lines[index])


@dataclass
class FakeMessenger:
    """Records every screen; serves downloads from :attr:`files` by ``file_id``."""

    files: dict[str, bytes] = field(default_factory=dict)
    sent: list[tuple[int, str, InlineKeyboardMarkup | None]] = field(default_factory=list)
    edits: list[tuple[int, int, str, InlineKeyboardMarkup | None]] = field(default_factory=list)
    albums: list[Album] = field(default_factory=list)
    #: Failures handed to the next deliveries (an album or a video), in order.
    album_failures: list[BayramError] = field(default_factory=list)
    videos: list[SentVideo] = field(default_factory=list)
    _next_id: int = 1000

    async def download(self, file_id: str, dest: Path, *, max_bytes: int) -> Result[int]:
        data = self.files.get(file_id)
        if data is None:
            return err(NotFoundError("no such file"))
        if len(data) > max_bytes:
            return err(ValidationError("too large", context={TOO_LARGE_KEY: True}))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return ok(len(data))

    async def send(
        self, chat_id: int, text: str, markup: InlineKeyboardMarkup | None = None
    ) -> int | None:
        self.sent.append((chat_id, text, markup))
        self._next_id += 1
        return self._next_id

    async def edit(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        self.edits.append((chat_id, message_id, text, markup))
        return True

    async def send_photos(
        self, chat_id: int, photos: Iterable[Path], *, caption: str
    ) -> Result[tuple[str, ...]]:
        if self.album_failures:
            return err(self.album_failures.pop(0))
        listed = tuple(photos)
        for path in listed:
            assert path.exists(), path
        self.albums.append(Album(chat_id=chat_id, photos=listed, caption=caption))
        return ok(tuple(f"tg-photo-{index}" for index in range(len(listed))))

    async def send_video(
        self,
        chat_id: int,
        video: Path,
        *,
        caption: str,
        width: int | None,
        height: int | None,
        duration_s: float | None,
    ) -> Result[str]:
        if self.album_failures:
            return err(self.album_failures.pop(0))
        assert video.exists(), video
        self.videos.append(
            SentVideo(chat_id, video, caption, width, height, duration_s, video.read_bytes())
        )
        return ok(f"tg-video-{len(self.videos)}")

    def tray_texts(self) -> list[str]:
        return [text for _, message_id, text, _ in self.edits if message_id == TRAY_ID]


@dataclass
class MemoryKV:
    """``MediaSwitchStore`` + ``MediaKV`` over a dict."""

    values: dict[str, Any] = field(default_factory=dict)

    async def get(self, name: str) -> Any:
        return self.values.get(name)

    async def set(self, name: str, value: str, *, ex: int | None = None) -> Any:
        self.values[name] = value
        return True

    async def delete(self, *names: str) -> Any:
        for name in names:
            self.values.pop(name, None)
        return len(names)


@dataclass
class QueuedStage:
    name: str
    args: tuple[Any, ...]
    job_id: str
    defer_s: float
    job_try: int = 1


@dataclass
class ArqLikeQueue:
    """ARQ's dedupe: an id seen before is dropped (it would still have a key or a result)."""

    pending: deque[QueuedStage] = field(default_factory=deque)
    seen: set[str] = field(default_factory=set)
    dropped: list[str] = field(default_factory=list)
    ran: list[QueuedStage] = field(default_factory=list)
    unhandled: list[QueuedStage] = field(default_factory=list)
    failure: Exception | None = None

    async def enqueue_job(
        self, function: str, *args: Any, _job_id: str, _defer_by: float = 0.0
    ) -> object | None:
        if self.failure is not None:
            raise self.failure
        if _job_id in self.seen:
            self.dropped.append(_job_id)
            return None
        self.seen.add(_job_id)
        self.pending.append(QueuedStage(function, args, _job_id, float(_defer_by)))
        return object()

    def ran_ids(self, prefix: str = "") -> list[str]:
        return [stage.job_id for stage in self.ran if stage.job_id.startswith(prefix)]

    def ran_named(self, name: str) -> list[QueuedStage]:
        return [stage for stage in self.ran if stage.name == name]


SubmitHook = Callable[[MediaRequest, str], Awaitable[Err | None]]


class HookedProvider:
    """The fake provider with one seam: :attr:`submit_hook` runs before each submit and may
    raise (a killed worker), wait (a slow POST) or answer an ``Err`` in the fake's place."""

    def __init__(self, inner: FakeMediaProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.submit_hook: SubmitHook | None = None
        #: What ``/estimate`` answers for a paid backend (§4.3): a figure, or an error.
        self.estimate_usd: float | None = None
        self.estimate_error: BayramError | None = None
        self.estimates = 0
        #: Answers ``/estimate`` in the fake's place when it returns a result (per request).
        self.estimate_hook: Callable[[MediaRequest], Result[CostEstimate] | None] | None = None
        #: What ``cancel`` answers (``None``: the fake's own ``Ok(False)``), and who asked.
        self.cancel_answer: bool | None = None
        self.cancelled: list[str] = []

    def capabilities(self) -> MediaCapabilities:
        return self.inner.capabilities()

    async def estimate_cost(self, req: MediaRequest) -> Result[CostEstimate]:
        self.estimates += 1
        if self.estimate_hook is not None and (answer := self.estimate_hook(req)) is not None:
            return answer
        if self.estimate_error is not None:
            return err(self.estimate_error)
        if self.estimate_usd is not None:
            return ok(CostEstimate(usd=self.estimate_usd, basis="exact"))
        return await self.inner.estimate_cost(req)

    async def submit(
        self,
        req: MediaRequest,
        *,
        correlation_key: str,
        webhook_url: str | None,
        timeout_s: float,
    ) -> Result[JobHandle]:
        if self.submit_hook is not None:
            answer = await self.submit_hook(req, correlation_key)
            if answer is not None:
                return answer
        return await self.inner.submit(
            req, correlation_key=correlation_key, webhook_url=webhook_url, timeout_s=timeout_s
        )

    async def poll(self, handle: JobHandle, *, timeout_s: float) -> Result[JobStatus]:
        return await self.inner.poll(handle, timeout_s=timeout_s)

    async def fetch(
        self, handle: JobHandle, index: int, dest: Path, *, max_bytes: int, timeout_s: float
    ) -> Result[GeneratedMedia]:
        return await self.inner.fetch(handle, index, dest, max_bytes=max_bytes, timeout_s=timeout_s)

    async def cancel(self, handle: JobHandle) -> Result[bool]:
        self.cancelled.append(handle.remote_id)
        if self.cancel_answer is not None:
            return ok(self.cancel_answer)
        return await self.inner.cancel(handle)

    async def health(self) -> Result[ProviderHealth]:
        return await self.inner.health()

    async def queued_jobs(self, *, timeout_s: float) -> Result[tuple[QueuedJob, ...]]:
        return await self.inner.queued_jobs(timeout_s=timeout_s)


@dataclass
class Harness:
    rt: MediaRuntime
    queue: ArqLikeQueue
    messenger: FakeMessenger
    moderator: FakeModerator
    provider: FakeMediaProvider
    hooked: HookedProvider
    gpu: MemoryGpuSlotStore
    kv: MemoryKV
    strikes: MemoryStrikeStore
    clock: MovingClock
    sessions: async_sessionmaker[AsyncSession]
    storage: LocalFileStorage
    workspace: Path
    video: FakeVideoTools
    narration: FakeNarrationProvider
    writer: FakeScriptWriter

    def ctx(self, job_try: int = 1) -> dict[str, Any]:
        return {MEDIA_CTX_KEY: self.rt, "job_try": job_try}

    async def run(self, name: str, *args: Any, job_try: int = 1) -> dict[str, Any]:
        return await STAGES[name](self.ctx(job_try), *args)

    async def drain(
        self,
        *,
        limit: int = 400,
        duplicate: bool = False,
        stop: Callable[[QueuedStage], bool] | None = None,
    ) -> None:
        """Run every queued stage in order, as a worker would, ignoring ``_defer_by``.

        ``duplicate`` runs each stage a second time straight after the first — a redelivered
        job — which must change nothing. ``stop`` leaves matching stages queued and returns.
        """
        runs = 0
        while self.queue.pending:
            stage = self.queue.pending[0]
            if stop is not None and stop(stage):
                return
            self.queue.pending.popleft()
            runs += 1
            assert runs <= limit, f"the chain did not settle; last {stage}"
            function = STAGES.get(stage.name)
            if function is None:
                self.queue.unhandled.append(stage)
                continue
            self.queue.ran.append(stage)
            try:
                await function(self.ctx(stage.job_try), *stage.args)
            except Retry:
                self.queue.pending.append(
                    QueuedStage(stage.name, stage.args, stage.job_id, 0.0, stage.job_try + 1)
                )
                continue
            if duplicate:
                with contextlib.suppress(Retry):
                    await function(self.ctx(stage.job_try), *stage.args)


def media_settings(settings: Settings, **update: Any) -> Settings:
    values: dict[str, Any] = {
        "use_fake_providers": True,
        "media_moderator": "fake",
        "image_backend": "fake",
        "is_image_offered": True,
        "media_beta_enabled": True,
        "media_beta_allowlist": (USER,),
    }
    values.update(update)
    return settings.model_copy(update=values)


def build_harness(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    start: datetime,
) -> Harness:
    clock = MovingClock(start)
    queue = ArqLikeQueue()
    messenger = FakeMessenger()
    moderator = FakeModerator()
    provider = FakeMediaProvider()
    hooked = HookedProvider(provider)
    gpu = MemoryGpuSlotStore()
    kv = MemoryKV()
    strikes = MemoryStrikeStore()
    storage = LocalFileStorage(tmp_path / "archive")
    workspace = tmp_path / "workspace"
    video = FakeVideoTools()
    narration = FakeNarrationProvider()
    writer = FakeScriptWriter()
    rt = MediaRuntime(
        settings=settings,
        sessions=sessions,
        storage=storage,
        workspace_root=workspace,
        messenger=messenger,
        moderator=moderator,
        providers=lambda backend: hooked,
        gpu=gpu,
        switches=kv,
        memo=kv,
        queue=queue,
        strikes=strikes,
        clock=clock,
        video=video,
        narration=narration,
        script_writer=writer,
    )
    return Harness(
        rt=rt,
        queue=queue,
        messenger=messenger,
        moderator=moderator,
        provider=provider,
        hooked=hooked,
        gpu=gpu,
        kv=kv,
        strikes=strikes,
        clock=clock,
        sessions=sessions,
        storage=storage,
        workspace=workspace,
        video=video,
        narration=narration,
        writer=writer,
    )


async def freeze_job(
    harness: Harness,
    *,
    photos: Iterable[bytes] = (),
    kind: MediaKind = MediaKind.IMAGE,
    prompt: str = PROMPT,
    user: int = USER,
    price_minor: int = 500_000,
) -> UUID:
    """What the bot's aspect pick does (M2.5): a ``screening`` row and its uploads' ids."""
    now = harness.clock()
    async with harness.sessions.begin() as session:
        # A second request from the same account reuses its user row (``telegram_user_id``
        # is unique), as the bot's freeze does.
        existing = await session.scalar(
            sa.select(UserRow.id).where(UserRow.telegram_user_id == user)
        )
        user_id = existing if existing is not None else uuid4()
        if existing is None:
            session.add(UserRow(id=user_id, telegram_user_id=user))
            await session.flush()
        job_id = await create_job(
            session,
            user_id=user_id,
            telegram_user_id=user,
            kind=kind,
            sku=MediaSku.IMAGE if kind is MediaKind.IMAGE else MediaSku.VIDEO_STANDARD,
            state=MediaJobState.SCREENING,
            chat_id=user,
            outputs_requested=2 if kind is MediaKind.IMAGE else 1,
            aspect=MediaAspect.PORTRAIT,
            language=Language.EN,
            prompt=prompt,
            price_minor=price_minor,
            currency="UZS",
            now=now,
            quote_ttl=timedelta(seconds=harness.rt.settings.media_quote_ttl_s),
            tray_message_id=TRAY_ID,
        )
        for ordinal, data in enumerate(photos):
            file_id = f"file-{job_id.hex[:6]}-{ordinal}"
            harness.messenger.files[file_id] = data
            await add_input(
                session,
                job_id=job_id,
                ordinal=ordinal,
                role=MediaInputRole.PHOTO,
                now=now,
                tg_file_id=file_id,
                tg_file_unique_id=f"u-{ordinal}",
            )
    return job_id
