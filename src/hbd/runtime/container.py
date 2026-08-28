"""One object that owns every long-lived resource the processes share.

Both entry points build the same container: the bot needs the repository (to persist an
order before queueing it) and the worker needs all of it. Building it twice from the same
function is what keeps them from drifting apart.

The pipeline is created *per job*, not once, because its progress sink targets one
Telegram message. Construction is field assignment — no I/O — so this costs nothing; the
expensive things (HTTP pools, the database engine) live on the container and are shared.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncEngine

from hbd.audio.processor import FfmpegAudioPostProcessor
from hbd.config import Settings
from hbd.contracts import AudioPostProcessor, KitRepository, PaymentProvider, Storage
from hbd.db.base import Base
from hbd.db.engine import create_engine, create_session_factory
from hbd.db.repository import SqlKitRepository
from hbd.db.retention import resolve_retention_policy
from hbd.logging import get_logger
from hbd.names import name_similarity
from hbd.payments import NoopPaymentProvider
from hbd.pipeline.events import ProgressSink
from hbd.pipeline.moderation import AllowAllModerator
from hbd.pipeline.orchestrator import KitPipeline
from hbd.runtime.providers import ProviderSet, build_provider_set
from hbd.storage import LocalFileStorage

__all__ = ["AppContainer", "build_container", "WORKSPACE_DIRNAME", "ARCHIVE_DIRNAME"]

_LOG = get_logger(__name__)

#: Where a run writes the files it is still working on, and where delivery reads them.
WORKSPACE_DIRNAME: Final[str] = "workspace"
#: Where finished assets are archived by the ``Storage`` leg.
ARCHIVE_DIRNAME: Final[str] = "archive"

#: Fake mode needs a schema without an Alembic run against a real server, so it creates
#: the tables directly. Never done for a live database — migrations own that.
_SQLITE_PREFIX: Final[str] = "sqlite"


@dataclass(frozen=True, slots=True)
class AppContainer:
    """Every shared resource, already built. Immutable; the pipeline is made per job."""

    settings: Settings
    providers: ProviderSet
    repository: KitRepository
    storage: Storage
    post: AudioPostProcessor
    payment: PaymentProvider
    workspace_root: Path
    engine: AsyncEngine
    music_slots: asyncio.Semaphore
    tts_slots: asyncio.Semaphore

    def pipeline(self, *, sink: ProgressSink | None = None) -> KitPipeline:
        """A pipeline aimed at one order's progress message. Cheap: no I/O."""
        return KitPipeline(
            settings=self.settings,
            music=self.providers.music,
            tts=self.providers.tts,
            llm=self.providers.llm,
            stt=self.providers.stt,
            payment=self.payment,
            post=self.post,
            storage=self.storage,
            repository=self.repository,
            similarity=_similarity,
            workspace_root=self.workspace_root,
            moderator=None if self.settings.is_moderation_enabled else AllowAllModerator(),
            sink=sink,
            music_slots=self.music_slots,
            tts_slots=self.tts_slots,
        )

    async def aclose(self) -> None:
        """Release pools and connections. Safe to call twice."""
        await self.providers.aclose()
        await self.engine.dispose()


def _similarity(heard: str, expected: str) -> float:
    """The pipeline's ``NameSimilarity`` port, bound to the name subsystem's scorer.

    Argument order is deliberate and load-bearing: the port is ``(heard, expected)`` and
    ``name_similarity`` is ``(intended, heard)``. Swapping them silently degrades every
    verification, because the scorer window-scans the *heard* side only.
    """
    return name_similarity(expected, heard)


async def build_container(settings: Settings, *, data_root: Path | None = None) -> AppContainer:
    """Build everything. Raises ``ConfigError`` for a misconfiguration and nothing else.

    Wiring only — it does not probe ffmpeg. That check belongs to *process* startup
    (:func:`hbd.runtime.startup.verify_host`), so a host missing libopus fails one boot
    loudly instead of every order quietly, one customer at a time.
    """
    root = (data_root or Path.cwd() / "var").resolve()
    workspace = root / WORKSPACE_DIRNAME
    archive = root / ARCHIVE_DIRNAME
    workspace.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)

    engine = create_engine(settings.database_url)
    if settings.database_url.startswith(_SQLITE_PREFIX):
        await _create_schema(engine)
    session_factory = create_session_factory(engine)

    _LOG.info(
        "container built",
        extra={
            "is_fake": settings.use_fake_providers,
            "workspace": str(workspace),
            "database": settings.database_url.split("@")[-1],
        },
    )
    return AppContainer(
        settings=settings,
        providers=build_provider_set(settings),
        repository=SqlKitRepository(session_factory, policy=resolve_retention_policy(settings)),
        storage=LocalFileStorage(archive),
        post=FfmpegAudioPostProcessor.from_settings(settings),
        payment=NoopPaymentProvider(),
        workspace_root=workspace,
        engine=engine,
        music_slots=asyncio.Semaphore(settings.music_max_concurrency),
        tts_slots=asyncio.Semaphore(settings.tts_max_concurrency),
    )


async def _create_schema(engine: AsyncEngine) -> None:
    """SQLite has no migration history to honour, so the schema is materialised directly."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    _LOG.info("sqlite schema created", extra={"tables": len(Base.metadata.tables)})
