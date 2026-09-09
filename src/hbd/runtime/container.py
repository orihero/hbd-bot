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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hbd.audio.processor import FfmpegAudioPostProcessor
from hbd.checkout import (
    STUB_PROVIDER_NAME,
    CheckoutProvider,
    PaymentIntentOpener,
    PurchaseFulfiller,
    StubCheckoutProvider,
)
from hbd.churn import BotBlockRecorder
from hbd.config import ENV_PREFIX, Settings
from hbd.contracts import AudioPostProcessor, KitRepository, PaymentProvider, Storage
from hbd.db.base import Base
from hbd.db.churn import SqlBotBlocks
from hbd.db.credits import SqlCreditLedger
from hbd.db.engine import create_engine, create_session_factory
from hbd.db.lyric_budget import SqlLyricBudget
from hbd.db.payme import SqlPaymeLedger
from hbd.db.purchases import SqlPurchaseLedger
from hbd.db.repository import SqlKitRepository
from hbd.db.retention import resolve_retention_policy
from hbd.db.user_profiles import SqlUserProfiles
from hbd.db.vendor_usage import DbUsageSink
from hbd.entitlements import EntitlementStore, resolve_entitlement_policy
from hbd.errors import ConfigError, PipelineError
from hbd.logging import get_logger
from hbd.lyric_budget import LyricBudgetStore, resolve_lyric_budget_policy
from hbd.names import name_similarity
from hbd.payme.link import resolve_base_url
from hbd.payme.provider import PaymeCheckoutProvider
from hbd.payments import CreditGatedPaymentProvider, NoopPaymentProvider
from hbd.pipeline.events import ProgressSink
from hbd.pipeline.moderation import AllowAllModerator
from hbd.pipeline.orchestrator import KitPipeline
from hbd.runtime.providers import ProviderSet, build_provider_set
from hbd.storage import LocalFileStorage
from hbd.user_profiles import UserProfileStore

__all__ = [
    "AppContainer",
    "build_container",
    "build_checkout",
    "WORKSPACE_DIRNAME",
    "ARCHIVE_DIRNAME",
]

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
    #: THE PAYME SEAM. Handed to the BOT and to nothing else: buying happens in front of a
    #: customer, and the worker has none. See the construction site below for why this one
    #: line is the whole of a future rail change.
    #:
    #: DEFAULTED for the same reason as ``credits``, and placed inside the defaulted tail
    #: rather than after it: ``tests/test_runtime/test_purge_cron.py:470`` pins ``profiles``
    #: as the final field, and the property that pin actually protects is "every field past
    #: the required head defaults", which a field inserted anywhere in the tail satisfies
    #: exactly as well as one appended to it. Every construction site is keyword-by-keyword.
    checkout: CheckoutProvider = field(default_factory=StubCheckoutProvider)
    #: What a paid button writes. A SEPARATE store from ``credits`` above even though both
    #: sit on the same session factory and the same tables, because this one is the handle
    #: the BOT holds and it must not be able to debit: ``EntitlementStore`` carries ``charge``
    #: and ``settle``, and handing the bot all three methods to get the one it needs is how
    #: "only the worker may spend" becomes a comment rather than a fact.
    #:
    #: ``None`` on the same condition ``credits`` is ``None`` — no session factory, no ledger
    #: of any kind — because a deployment that can grant but cannot read a balance would
    #: paywall a customer it had just taken money from.
    purchases: PurchaseFulfiller | None = None
    #: Where a customer's block is recorded. Held by the BOT and the WORKER both, which is
    #: the asymmetry worth knowing: ``profiles`` is bot-only because the worker has no
    #: customer in front of it, and the render gate is worker-only because the bot may not
    #: spend — but a block is LEARNED in two places, from the ``my_chat_member`` update the
    #: bot receives and from the ``sendAudio`` the worker is refused, and neither source
    #: subsumes the other while ``run_polling`` drops pending updates on every restart.
    #:
    #: TRAILING and DEFAULTED for the same reason as every field above it: ``AppContainer``
    #: is frozen and constructed field-by-keyword by tests that know nothing about churn. It
    #: sits INSIDE the tail rather than at the end of it for ``checkout``'s stated reason —
    #: ``tests/test_runtime/test_purge_cron.py`` pins ``profiles`` as the last field, and the
    #: property that pin protects is "every field past the required head defaults", which a
    #: field placed anywhere in the tail satisfies exactly as well.
    #:
    #: ``None`` means "this deployment does not record churn"; the membership handler then
    #: returns without writing and the worker's delivery arm skips its record.
    bot_blocks: BotBlockRecorder | None = None
    #: The redirect rail's ADDITIVE-ONLY intent port, or ``None`` when the wired rail settles
    #: inline. It is the SAME OBJECT as the one behind :attr:`checkout` when the rail is
    #: Payme — one ``SqlPaymeLedger`` satisfying two protocols — and that is the design rather
    #: than an accident: the bot's reference is typed as ``PaymentIntentOpener``, which
    #: declares ``open_intent`` and nothing else, so the process that can START a payment
    #: structurally cannot settle, cancel or force-settle one. The other half of that object's
    #: surface is reachable only through ``hbd.payme.ports.PaymeLedger``, in the gateway,
    #: which is the only process holding the credential those calls arrive authenticated with.
    #:
    #: It is a field in its own right rather than something reached for through ``checkout``,
    #: because ``CheckoutProvider`` has one method and must keep having one: the six Payme
    #: methods are INBOUND, and none of them is a thing the bot asks a provider to do. Two
    #: ports stay two ports by being two fields.
    #:
    #: ``None`` on the stub, and nothing downstream treats that as degraded — the bot's
    #: pending-payment branch is reached only when a ``charge`` returns unpaid WITH a URL,
    #: which an inline rail never produces.
    #:
    #: DEFAULTED for the reason every field above it is — ``AppContainer`` is frozen and built
    #: field-by-keyword by tests that know nothing about payment rails — and placed INSIDE the
    #: defaulted tail rather than after it, for ``checkout``'s stated reason:
    #: ``tests/test_runtime/test_purge_cron.py`` pins ``profiles`` as the final field, and the
    #: property that pin actually protects is "every field past the required head defaults",
    #: which a field inserted anywhere in the tail satisfies exactly as well.
    intents: PaymentIntentOpener | None = None
    #: The onboarding record — which language the customer chose, the number they shared, and
    #: the username, name and profile photo behind it. Written by the BOT and by nothing else:
    #: the worker has no customer in front of it and never learns anything new about one, so
    #: handing it a writer here would only widen the surface that can rewrite a phone number.
    #:
    #: TRAILING and DEFAULTED for the same reason as ``credits``, ``session_factory`` and
    #: ``lyric_budget``: ``AppContainer`` is frozen and is constructed field-by-keyword by
    #: tests that know nothing about onboarding (``tests/test_runtime/test_jobs.py``, and
    #: ``tests/test_runtime/test_purge_cron.py:432`` builds one directly), so a non-defaulted
    #: field anywhere above would break a test that has nothing to do with a profile.
    #:
    #: ``None`` means "no profile store wired at all", and the bot's onboarding gate then lets
    #: everyone through — the same fail-open posture ``gate.InboundGateMiddleware`` takes,
    #: because a store that cannot be read is not a reason to stop selling songs. It is
    #: therefore also the configuration in which the onboarding flow is never exercised: a
    #: developer smoke-testing the language question wants the wired container this module
    #: builds, not a hand-assembled one.
    profiles: UserProfileStore | None = None

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
        must not be able to SPEND. Its three early returns after the gate (payment declined,
        ``_start_progress`` returned ``None``, ``submitter.submit`` returned ``Err``) cannot
        reach a refund — no order row and no ARQ job exist yet — and ``reset_to_welcome``
        mints a new session id and therefore a new UUID5, so the customer's next attempt
        would be charged all over again. Wrapping here rather than at the field keeps that
        impossible by construction instead of by convention. WU7 gives the bot a read-only
        balance CHECK: ``BotDeps.entitlements`` is consulted through ``balance_for`` and
        nothing else on any gate.

        SPEND and not "write", and the correction matters. Since the checkout shipped,
        ``build_container`` fills the fulfiller field on this container with a
        ``SqlPurchaseLedger`` unconditionally and ``hbd.main`` hands that straight to the
        bot, which does write ``credit_ledger`` rows with it — GRANT rows signed
        ``CHECKOUT_ACTOR``, one per song the customer has already paid for. This paragraph
        said "must not be able to write" and the code contradicted it from that day; the rule
        it was always defending is the one about DEBITS. A grant is additive and
        idempotency-keyed, so a redelivered update lands on the row the unique index already
        holds and there is nothing to compensate. A charge and its settlement do have
        something to compensate, which is why they are minted HERE, per job, in the only
        process that can finish them. That field is named nowhere in this method on purpose —
        ``test_the_render_gate_never_reaches_the_purchase_ledger`` reads this source text and
        asserts as much, because a gate that merely HELD the fulfiller could mint the credit
        it is about to spend and would still pass the behavioural half of that test.

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


async def _never_paused() -> bool:
    """The default pause reader: the rail is always open.

    A named coroutine rather than an inline lambda so that the ONE wiring site for the
    operator pause switch is greppable, and so that a deployment with no switch reads as a
    deliberate configuration instead of an omission.

    **It is also the correct fallback and not merely a placeholder.** The Redis-backed reader
    answers "not paused" when Redis cannot be read, for the reason stated on
    ``PaymeCheckoutProvider._is_rail_paused``: an unreachable Redis silently stopping every
    sale is a far worse outage than a paused rail briefly taking a payment. So "no switch
    wired" and "switch unreadable" produce the same answer by design, and the switch is
    therefore not a security control and must never be documented as one.
    """
    return False


def build_checkout(
    settings: Settings,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    paused: Callable[[], Awaitable[bool]] | None = None,
) -> tuple[CheckoutProvider, PaymentIntentOpener | None]:
    """Which rail sells a credit, and the intent port that goes with it. Raises ``ConfigError``.

    **Two return values because they are one decision.** The rail and the intent port are the
    same object when the rail is a redirect one, and building them from two call sites would
    permit the combination that cannot work — a Payme provider over a stub opener, or a wired
    opener under a rail that never opens an intent — to be produced by an edit that looked
    local. Returning the pair from one function means the impossible combinations cannot be
    spelled.

    **The refusal happens HERE, when the rail is actually built, and not at every boot.** That
    is the ``build_llm_provider`` precedent, and it is what lets a deployment on the stub — the
    default, and today's production — boot with no Payme configuration in its environment at
    all. A blank merchant id under ``checkout_provider="payme"`` is a ``ConfigError`` naming
    ``HBD_PAYME_MERCHANT_ID``, because the alternative is a link whose ``m=`` parameter is
    empty: Payme's own checkout answers that with «Поставщик не найден», which is a sentence
    about THEIR system that a customer would read as a sentence about ours.

    ``paused`` is injected rather than constructed, so this function opens no Redis connection
    and stays synchronous, and so a test can pause the rail with three lines and no server.
    See :func:`_never_paused` for what the absence of one means. **This parameter is the ONE
    place the operator pause switch is wired**, and it is deliberately a parameter rather than
    something built here: the switch's Redis key is written by ``python -m hbd.payme.cli
    pause`` and read back by ``hbd.payme.pause.is_paused``, and a composition root that reached
    into that module directly would give this function a Redis dependency it does not otherwise
    have — for a feature that is off in every deployment that has not armed it.

    Note what is NOT read from settings here: the transaction timeout and the duplicate-code
    override. Both are the GATEWAY's configuration, on ``hbd.payme.settings.PaymeSettings``,
    in the process that terminates Payme's inbound calls. The ledger built here is handed out
    typed as ``PaymentIntentOpener``, whose one method never reaches either value, so passing
    the bot's guess at them would be passing a number nothing reads and inviting the two
    processes to disagree about one that matters.
    """
    if settings.checkout_provider == STUB_PROVIDER_NAME:
        # Byte-identical to what shipped before any of this landed, and deliberately the first
        # branch: the stub is not a fallback for a misconfigured rail, it is the default rail.
        return StubCheckoutProvider(), None

    merchant_id = settings.payme_merchant_id.strip()
    if not merchant_id:
        raise ConfigError(
            f"the checkout rail is set to '{settings.checkout_provider}' but "
            f"{ENV_PREFIX}PAYME_MERCHANT_ID is empty; the cashbox id is what every checkout "
            "link is built from and Payme has no way to identify us without it",
            context={"checkout_provider": settings.checkout_provider},
        )

    ledger = SqlPaymeLedger(
        session_factory,
        merchant_id=merchant_id,
        intent_ttl_s=settings.payme_intent_ttl_s,
        account_field=settings.payme_account_field,
    )
    provider = PaymeCheckoutProvider(
        # The SAME object, handed over twice under two types. See ``AppContainer.intents``.
        ledger,
        merchant_id=merchant_id,
        base_url=resolve_base_url(
            is_sandbox=settings.payme_is_sandbox,
            override=settings.payme_checkout_base_url,
        ),
        account_field=settings.payme_account_field,
        return_url=settings.payme_return_url,
        is_sandbox=settings.payme_is_sandbox,
        # The catalogue's numbers, snapshotted onto every plan intent at the moment of sale so
        # a later package change cannot retroactively shrink what somebody already paid for.
        plan_songs=settings.starter_plan_songs,
        plan_days=settings.starter_plan_days,
        # The deployment's default UI language, not the individual customer's: nothing on the
        # charge path carries one today. Stated as a limitation on the provider's ``__init__``
        # rather than hidden here, and a callable so the fix is this line when it arrives.
        language_of=lambda: settings.default_ui_language,
        paused=paused or _never_paused,
    )
    _LOG.info(
        "the checkout rail is live",
        extra={
            "checkout_provider": settings.checkout_provider,
            "merchant_id": merchant_id,
            "is_sandbox": settings.payme_is_sandbox,
            "intent_ttl_s": settings.payme_intent_ttl_s,
            "account_field": settings.payme_account_field,
            "has_pause_switch": paused is not None,
        },
    )
    return provider, ledger


def _similarity(heard: str, expected: str) -> float:
    """The pipeline's ``NameSimilarity`` port, bound to the name subsystem's scorer.

    Argument order is deliberate and load-bearing: the port is ``(heard, expected)`` and
    ``name_similarity`` is ``(intended, heard)``. Swapping them silently degrades every
    verification, because the scorer window-scans the *heard* side only.
    """
    return name_similarity(expected, heard)


async def build_container(
    settings: Settings,
    *,
    data_root: Path | None = None,
    with_providers: bool = True,
    paused: Callable[[], Awaitable[bool]] | None = None,
) -> AppContainer:
    """Build everything. Raises ``ConfigError`` for a misconfiguration and nothing else.

    ``paused`` is threaded straight through to :func:`build_checkout` and is the operator
    pause switch. It is a PARAMETER and not something built here for the reason that function
    states: this container opens no Redis connection of its own. ``hbd.main.run`` passes a
    reader over the queue pool it was already going to open, so arming the switch costs no
    second connection — and a process with no pool (the demo path) passes ``None`` and gets a
    rail that is always open, which is the honest answer where no operator can reach it.

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
    # ONE instance, shared by the archive leg and the profile store. The avatar the bot
    # writes and the object the admin panel streams have to be the same key under the same
    # root: the admin host mounts that root read-only and never holds the Telegram bot token,
    # so a second ``LocalFileStorage`` over a different path would give the panel a 404 nobody
    # could explain — the row says an avatar was stored, and the bytes are on another disk.
    storage = LocalFileStorage(archive)
    # The rail and its intent port, as ONE decision — see :func:`build_checkout`. Built here,
    # before the container, because it is the one piece of wiring that can REFUSE: a rail
    # named ``payme`` with no cashbox id raises ``ConfigError`` rather than building a
    # provider whose every link would carry an empty ``m=``.
    #
    # ``paused`` arrives from the caller and is never built here: nothing in this function
    # holds a Redis client, and opening one purely to read a key that is unset in every
    # deployment that has not armed the switch would be a connection nothing closes. What
    # ``hbd.main.run`` passes is a reader over the queue pool it opens anyway, so the switch
    # is armed for free in the process that sells songs; ``None`` — the demo path, and every
    # test that does not care — leaves the rail always open. See ``build_checkout``.
    checkout, intents = build_checkout(settings, session_factory=session_factory, paused=paused)
    return AppContainer(
        settings=settings,
        # The vendors, each holding the SAME persisting usage sink. The sink is built here
        # — from the factory this container already owns — and never inside a provider,
        # because a provider that made its own session would open a second connection pool
        # nothing closes, and would put the decision "where does measurement go" in five
        # files instead of one. It is passed even when the set is fake: a fake run writes
        # rows stamped ``is_fake=True`` and is excluded from spend by that flag rather than
        # by leaving a gap in the table.
        providers=(
            build_provider_set(settings, usage=DbUsageSink(session_factory))
            if with_providers
            else None
        ),
        repository=SqlKitRepository(session_factory, policy=resolve_retention_policy(settings)),
        storage=storage,
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
        # Always built, and holding the SAME ``storage`` object the archive leg above holds,
        # so the avatar the bot writes and the object the admin panel streams are one file.
        # No policy argument exists to pass: this table is on no clock (PD-2) — ``/forget``
        # DELETEs the row and the absence IS the erasure record — so a ``retention=`` here
        # would be a sweep that never runs, which is how a reader concludes one was forgotten.
        profiles=SqlUserProfiles(session_factory, storage=storage),
        # THIS WAS THE PAYME SEAM, AND THE RAIL HAS LANDED. What stood here for the life of
        # the repository was a promise — "the day a real rail lands, this line is the whole
        # change" — and it is replaced by a record of what actually happened, including the
        # part of the promise that did not hold.
        #
        # WHAT HELD: this is still one line, the branch is still a factory above rather than
        # anything smeared through the container, and the DEFAULT is still the stub. With
        # ``HBD_CHECKOUT_PROVIDER=stub`` — which is what ships — the object constructed here
        # is byte-for-byte the one that was constructed before, so production behaviour did
        # not move and the rollback is that variable plus one restart.
        #
        # WHAT DID NOT HOLD: "nothing in ``handlers.checkout`` names a provider" was true and
        # was not enough. That handler collapsed ``Err`` and "unpaid" into one failure branch,
        # which is the correct reading for an INLINE rail and a lie for a redirect one — it
        # would have told a customer nothing was charged at the exact moment their payment
        # successfully started. So one branch and one return type did change there (``bool``
        # became ``SettleOutcome``). The lesson is narrower than "the seam was wrong": a seam
        # can be perfectly abstract over WHO answers and still be shaped by WHEN they answer.
        #
        # ``charge`` still opens no socket. Payme has no create-payment-link API for the
        # standard checkout, so a redirect rail is a row and a base64 string — see
        # ``hbd.payme.provider``. See DECISIONS.md D11 and PAYME_INTEGRATION §1.
        checkout=checkout,
        # The other half of the pair above, and never built separately. ``None`` on the stub.
        intents=intents,
        # Built beside ``credits``, on the same session factory, and never handed to the
        # worker. It resolves the SAME policy the ledger above does, because
        # ``credit_sql.read_balance`` projects a due allowance and a live plan's unminted
        # songs, and it can only project what the WORKER will actually mint if both sides
        # agree on the numbers — a store that defaulted its policy here would answer the
        # Confirm screen with a balance the render gate then disagreed with.
        purchases=SqlPurchaseLedger(session_factory, policy=resolve_entitlement_policy(settings)),
        # Built unconditionally, including for the ADMIN process — which builds its container
        # with ``with_providers=False`` and holds this object without ever calling it, because
        # no admin route writes churn. The panel READS ``bot_membership_events`` through
        # ``hbd.db.admin`` and the only writers are the bot's membership handler and the
        # worker's send refusal. No policy argument exists to pass: the retention cutoff for
        # this table is ``hbd.db.purge.BOT_MEMBERSHIP_RETENTION_DAYS``, a module constant
        # rather than a knob, because the only thing a knob here could do is lose history.
        bot_blocks=SqlBotBlocks(session_factory),
    )


async def _create_schema(engine: AsyncEngine) -> None:
    """SQLite has no migration history to honour, so the schema is materialised directly."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    _LOG.info("sqlite schema created", extra={"tables": len(Base.metadata.tables)})
