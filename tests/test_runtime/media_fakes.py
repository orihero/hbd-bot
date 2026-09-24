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
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

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
)
from bayram.media.stages import (
    MEDIA_CLEANUP_JOB,
    MEDIA_DELIVER_JOB,
    MEDIA_FETCH_JOB,
    MEDIA_OUTPUT_SCREEN_JOB,
    MEDIA_POLL_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_START_JOB,
    MEDIA_SUBMIT_JOB,
)
from bayram.moderation.fake import FakeModerator
from bayram.providers.media.fake import FakeMediaProvider
from bayram.runtime.gpu_lock import MemoryGpuSlotStore
from bayram.runtime.media_jobs import (
    MEDIA_CTX_KEY,
    MediaRuntime,
    media_cleanup,
    media_deliver,
    media_fetch,
    media_output_screen,
    media_poll,
    media_screen,
    media_start,
    media_submit,
)
from bayram.runtime.media_telegram import TOO_LARGE_KEY
from bayram.storage import LocalFileStorage

USER: Final[int] = 5_550_001_111
TRAY_ID: Final[int] = 77
PROMPT: Final[str] = "a lantern-lit courtyard in Samarkand at dusk"

StageFn = Callable[..., Awaitable[dict[str, Any]]]

STAGES: Final[dict[str, StageFn]] = {
    MEDIA_SCREEN_JOB: media_screen,
    MEDIA_START_JOB: media_start,
    MEDIA_SUBMIT_JOB: media_submit,
    MEDIA_POLL_JOB: media_poll,
    MEDIA_FETCH_JOB: media_fetch,
    MEDIA_OUTPUT_SCREEN_JOB: media_output_screen,
    MEDIA_DELIVER_JOB: media_deliver,
    MEDIA_CLEANUP_JOB: media_cleanup,
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
class FakeMessenger:
    """Records every screen; serves downloads from :attr:`files` by ``file_id``."""

    files: dict[str, bytes] = field(default_factory=dict)
    sent: list[tuple[int, str, InlineKeyboardMarkup | None]] = field(default_factory=list)
    edits: list[tuple[int, int, str, InlineKeyboardMarkup | None]] = field(default_factory=list)
    albums: list[Album] = field(default_factory=list)
    album_failures: list[BayramError] = field(default_factory=list)
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

    def capabilities(self) -> MediaCapabilities:
        return self.inner.capabilities()

    async def estimate_cost(self, req: MediaRequest) -> Result[CostEstimate]:
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
        return await self.inner.cancel(handle)

    async def health(self) -> Result[ProviderHealth]:
        return await self.inner.health()


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
    clock: MovingClock
    sessions: async_sessionmaker[AsyncSession]
    storage: LocalFileStorage
    workspace: Path

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
    storage = LocalFileStorage(tmp_path / "archive")
    workspace = tmp_path / "workspace"
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
        clock=clock,
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
        clock=clock,
        sessions=sessions,
        storage=storage,
        workspace=workspace,
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
        user_id = uuid4()
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
