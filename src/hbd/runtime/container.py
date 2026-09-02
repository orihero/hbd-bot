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

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hbd.audio.processor import FfmpegAudioPostProcessor
from hbd.config import Settings
from hbd.contracts import AudioPostProcessor, KitRepository, PaymentProvider, Storage
from hbd.db.base import Base
from hbd.db.credits import SqlCreditLedger
from hbd.db.engine import create_engine, create_session_factory
from hbd.db.lyric_budget import SqlLyricBudget
from hbd.db.repository import SqlKitRepository
from hbd.db.retention import resolve_retention_policy
from hbd.entitlements import EntitlementStore, resolve_entitlement_policy
from hbd.errors import PipelineError
from hbd.logging import get_logger
from hbd.lyric_budget import LyricBudgetStore, resolve_lyric_budget_policy
from hbd.names import name_similarity
from hbd.payments import CreditGatedPaymentProvider, NoopPaymentProvider
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
    #: ``None`` when the container was built with ``with_providers=False`` — the admin API
    #: and the config-validation path need an engine and a repository without a vendor
    #: adapter anywhere near them. Every read of it goes through :meth:`require_providers`,
    #: which is why this is an honest ``| None`` rather than a cast that would surface as
    #: ``AttributeError: 'NoneType' object has no attribute 'music'`` at an unrelated await.
    providers: ProviderSet | None
    repository: KitRepository
    storage: Storage
    post: AudioPostProcessor
    payment: PaymentProvider
    workspace_root: Path
    engine: AsyncEngine
    music_slots: asyncio.Semaphore
    tts_slots: asyncio.Semaphore
    #: Where entitlement lives. TRAILING and DEFAULTED on purpose: ``AppContainer`` is
    #: frozen and subclassed by tests that construct it positionally-by-keyword with the
    #: original ten fields (tests/test_runtime/test_jobs.py), so a non-defaulted insert
    #: anywhere above would break a test that has nothing to do with credits.
    #:
    #: ``None`` means "the meter is not wired at all" — a container built for a test that
    #: never touches money — and is distinct from ``Settings.credits_enforced=False``, which
    #: means "wired, dark, writing nothing". Both leave the render gate open; only the
    #: second one is the shipped production configuration.
    credits: EntitlementStore | None = None
    #: The session factory the engine above was wrapped in. TRAILING and DEFAULTED for the
    #: same reason as ``credits``: ``AppContainer`` is frozen and subclassed by tests that
    #: construct it with the original fields, so an inserted non-defaulted field anywhere
    #: above would break tests that have nothing to do with retention.
    #:
    #: Promoted to a field because the retention sweep is the first thing that needs raw
    #: session access rather than a repository method — it runs seven bounded ``DELETE``s
    #: and an ``INSERT`` across five tables, which is not a shape ``KitRepository`` has or
    #: should grow. ``None`` means "built without one", and every read goes through
    #: :meth:`require_session_factory`.
    session_factory: async_sessionmaker[AsyncSession] | None = None
    #: The daily lyric-write ceiling, handed to the BOT and to nothing else — the worker
    #: never writes a lyric. TRAILING and DEFAULTED for the same reason as ``credits``.
    #:
    #: A separate store rather than a method on ``credits`` because the bot writes this
    #: one and may never write a credit; see ``hbd.db.lyric_budget.SqlLyricBudget``.
    lyric_budget: LyricBudgetStore | None = None

    def require_providers(self) -> ProviderSet:
        """The vendors, or a named failure. Raises rather than returning a ``Result``.

        A ``None`` here is a wiring bug — some process built a provider-free container and
        then asked it to render — not a runtime condition a caller could recover from, so
        it fails immediately and says which of the two it was.
        """
        if self.providers is None:
            raise PipelineError(
                "container built without providers",
                context={"is_fake": self.settings.use_fake_providers},
            )
        return self.providers

    def require_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """The session factory, or a named failure. Same reasoning as above."""
        if self.session_factory is None:
            raise PipelineError(
                "container built without a session factory",
                context={"database": self.settings.database_url.split("@")[-1]},
            )
        return self.session_factory

    def pipeline(self, *, sink: ProgressSink | None = None) -> KitPipeline:
        """A pipeline aimed at one order's progress message. Cheap: no I/O.

        The provider check happens FIRST, before any other field is read, so a container
        built without vendors names that cause instead of dying later at an await inside
        the orchestrator with a message about ``NoneType``.
        """
        providers = self.require_providers()
        return KitPipeline(
            settings=self.settings,
            music=providers.music,
            tts=providers.tts,
            llm=providers.llm,
            stt=providers.stt,
            payment=self._render_gate(),
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

    def _render_gate(self) -> PaymentProvider:
        """The payment seam AS THE WORKER SEES IT — the one place a credit is spent.

        The gate is built here, per job, and never stored on ``self.payment``, because
        ``hbd.main`` builds the bot's ``BotDeps.payment`` from ``self.payment`` and the bot
        must not be able to write. Its three early returns after the gate (payment declined,
        ``_start_progress`` returned ``None``, ``submitter.submit`` returned ``Err``) cannot
        reach a refund — no order row and no ARQ job exist yet — and ``reset_to_welcome``
        mints a new session id and therefore a new UUID5, so the customer's next attempt
        would be charged all over again. Wrapping here rather than at the field keeps that
        impossible by construction instead of by convention. WU7 gives the bot a read-only
        balance check instead.

        Construction is field assignment on a frozen dataclass, so doing it per job costs
        the same as reading an attribute.
        """
        if self.credits is None:
            return self.payment
        # No flag is passed: ``Settings.credits_enforced`` reaches the store through
        # ``resolve_entitlement_policy`` below, because a gate that owned it could only
        # express "dark" as "do not call the store at all" — which also switched off the
        # block gate and the in-flight cap, both of which count on rows this call writes.
        return CreditGatedPaymentProvider(self.payment, self.credits)

    async def aclose(self) -> None:
        """Release pools and connections. Safe to call twice, and safe with no providers."""
        if self.providers is not None:
            await self.providers.aclose()
        await self.engine.dispose()


def _similarity(heard: str, expected: str) -> float:
    """The pipeline's ``NameSimilarity`` port, bound to the name subsystem's scorer.

    Argument order is deliberate and load-bearing: the port is ``(heard, expected)`` and
    ``name_similarity`` is ``(intended, heard)``. Swapping them silently degrades every
    verification, because the scorer window-scans the *heard* side only.
    """
    return name_similarity(expected, heard)


async def build_container(
    settings: Settings, *, data_root: Path | None = None, with_providers: bool = True
) -> AppContainer:
    """Build everything. Raises ``ConfigError`` for a misconfiguration and nothing else.

    Wiring only — it does not probe ffmpeg. That check belongs to *process* startup
    (:func:`hbd.runtime.startup.verify_host`), so a host missing libopus fails one boot
    loudly instead of every order quietly, one customer at a time.

    ``with_providers=False`` builds the same container with no vendor adapter in it. That
    is not a convenience: it is what lets a process hold the database and the object store
    without holding a credential that can spend money, and the resulting container raises a
    named :class:`hbd.errors.PipelineError` from :meth:`AppContainer.pipeline` rather than
    pretending it could render.
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
            "has_providers": with_providers,
            "workspace": str(workspace),
            "database": settings.database_url.split("@")[-1],
        },
    )
    return AppContainer(
        settings=settings,
        providers=build_provider_set(settings) if with_providers else None,
        repository=SqlKitRepository(session_factory, policy=resolve_retention_policy(settings)),
        storage=LocalFileStorage(archive),
        post=FfmpegAudioPostProcessor.from_settings(settings),
        payment=NoopPaymentProvider(),
        workspace_root=workspace,
        engine=engine,
        music_slots=asyncio.Semaphore(settings.music_max_concurrency),
        tts_slots=asyncio.Semaphore(settings.tts_max_concurrency),
        # Always built, whatever ``credits_enforced`` says — and that flag now arrives HERE,
        # inside the resolved policy, as ``EntitlementPolicy.is_balance_enforced``, rather
        # than on the decorator above. Wiring the store unconditionally is what lets an
        # operator flip the flag without a redeploy, and what gives WU9's ``/balance`` an
        # honest number to read while the meter is still dark. The policy is RESOLVED so
        # that a deployment which lengthened ``HBD_QUEUE_JOB_TIMEOUT_S`` gets a settlement
        # grace that still outlasts its own retry ladder — otherwise the in-flight cap would
        # start releasing orders that are still rendering.
        credits=SqlCreditLedger(session_factory, policy=resolve_entitlement_policy(settings)),
        session_factory=session_factory,
        # Always built, and never behind ``credits_enforced``: this bounds the LYRIC
        # write, which is the first vendor spend in the product and happens before the
        # gates that flag covers. An abuse rail that ships switched off is not a rail.
        lyric_budget=SqlLyricBudget(session_factory, policy=resolve_lyric_budget_policy(settings)),
    )


async def _create_schema(engine: AsyncEngine) -> None:
    """SQLite has no migration history to honour, so the schema is materialised directly."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    _LOG.info("sqlite schema created", extra={"tables": len(Base.metadata.tables)})
