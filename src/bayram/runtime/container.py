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

from bayram.audio.processor import FfmpegAudioPostProcessor
from bayram.bot_chats import BotChatDirectory
from bayram.checkout import (
    STUB_PROVIDER_NAME,
    CheckoutProvider,
    CompositeCheckoutProvider,
    PaymentIntentOpener,
    PurchaseFulfiller,
    StubCheckoutProvider,
)
from bayram.checkout_rails import wired_rails
from bayram.checkoutuz.client import CheckoutUzClient
from bayram.checkoutuz.ports import CHECKOUTUZ_PROVIDER_NAME
from bayram.checkoutuz.provider import (
    CHECKOUTUZ_MERCHANT_ID,
    CheckoutUzCheckoutProvider,
    SqlCheckoutUzPaymentStore,
)
from bayram.churn import BotBlockRecorder
from bayram.config import ENV_PREFIX, Settings
from bayram.contracts import AudioPostProcessor, KitRepository, PaymentProvider, Storage
from bayram.db.base import Base
from bayram.db.bot_chats import SqlBotChats
from bayram.db.churn import SqlBotBlocks
from bayram.db.credits import SqlCreditLedger
from bayram.db.engine import create_engine, create_session_factory
from bayram.db.lyric_budget import SqlLyricBudget
from bayram.db.payme import SqlPaymeLedger
from bayram.db.purchases import SqlPurchaseLedger
from bayram.db.repository import SqlKitRepository
from bayram.db.retention import resolve_retention_policy
from bayram.db.user_profiles import SqlUserProfiles
from bayram.db.vendor_usage import DbUsageSink
from bayram.entitlements import EntitlementStore, resolve_entitlement_policy
from bayram.errors import ConfigError, PipelineError
from bayram.logging import get_logger
from bayram.lyric_budget import LyricBudgetStore, resolve_lyric_budget_policy
from bayram.names import name_similarity
from bayram.payme.link import resolve_base_url
from bayram.payme.provider import PaymeCheckoutProvider
from bayram.payments import CreditGatedPaymentProvider, NoopPaymentProvider
from bayram.pipeline.events import ProgressSink
from bayram.pipeline.moderation import AllowAllModerator
from bayram.pipeline.orchestrator import KitPipeline
from bayram.rhmt.client import RhmtClient
from bayram.rhmt.provider import RhmtCheckoutProvider
from bayram.rhmt.settings import build_rhmt_settings
from bayram.runtime.providers import ProviderSet, build_provider_set
from bayram.storage import LocalFileStorage
from bayram.user_profiles import UserProfileStore

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
    #: one and may never write a credit; see ``bayram.db.lyric_budget.SqlLyricBudget``.
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
    #: surface is reachable only through ``bayram.payme.ports.PaymeLedger``, in the gateway,
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
    #: WHICH GROUPS THE BOT IS IN, AND WHICH ONE OF THEM THE TICKET CARDS GO TO.
    #:
    #: Held by BOTH processes, which puts it in the small company of ``bot_blocks`` rather than
    #: with the bot-only ``profiles``, and for a closely related reason: the fact is learned in
    #: one process and needed in two. The BOT writes the directory (its ``my_chat_member``
    #: registration is the only automatic route by which this system ever learns a group exists
    #: — Telegram has no "list my groups" API) and reads the selection on every group update and
    #: every filed complaint. The WORKER reads the selection when the panel asks it to sync a
    #: card, and it is the only process that writes ``verified_at`` — the ``support:verify_group``
    #: job actually posts into the room, which is a thing no other process holds a token to do.
    #:
    #: The ADMIN process builds it too and never calls it: the panel's reads go through
    #: ``bayram.db.admin.bot_chats`` and its two writes — select and clear — are module-level
    #: functions composed into the request transaction that carries the ``admin_audit_log`` row.
    #: :class:`~bayram.bot_chats.BotChatDirectory` has no method for either, so no process
    #: holding this object can repoint the support inbox without an audit trail.
    #:
    #: Built unconditionally and carrying no policy argument: there is nothing to configure.
    #: The two settings that used to name the group, ``BAYRAM_SUPPORT_GROUP_CHAT_ID`` and
    #: ``BAYRAM_SUPPORT_GROUP_THREAD_ID``, were REMOVED rather than kept as a fallback
    #: (``SUPPORT_TICKETS_SPEC §3.8``), so the selected row is the only authority and there is
    #: no precedence rule for a reader to reason about.
    #:
    #: DEFAULTED for the reason every field above it is, and placed INSIDE the defaulted tail
    #: rather than after it because ``tests/test_runtime/test_purge_cron.py`` pins ``profiles``
    #: as the final field. ``None`` means "this deployment records no chat directory": the bot's
    #: group registration writes nothing, nothing is ever selectable, and the group leg of the
    #: support feature is off while tickets keep working.
    bot_chats: BotChatDirectory | None = None
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
        ``bayram.main`` builds the bot's ``BotDeps.payment`` from ``self.payment`` and the bot
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
        ``SqlPurchaseLedger`` unconditionally and ``bayram.main`` hands that straight to the
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


def _build_rhmt_provider(
    settings: Settings,
    *,
    ledger: PaymentIntentOpener,
    paused: Callable[[], Awaitable[bool]] | None = None,
) -> RhmtCheckoutProvider:
    rhmt_settings = build_rhmt_settings()
    app_id = (
        rhmt_settings.rhmt_application_id or settings.rhmt_application_id or "placeholder_app_id"
    )
    secret = rhmt_settings.rhmt_secret.get_secret_value() or "placeholder_secret"
    store_id = rhmt_settings.rhmt_store_id or settings.rhmt_store_id or 0
    base_url = settings.rhmt_checkout_base_url or rhmt_settings.resolved_base_url
    callback_url = settings.rhmt_callback_url or rhmt_settings.rhmt_callback_url
    return_url = settings.rhmt_return_url or rhmt_settings.rhmt_return_url

    client = RhmtClient(
        application_id=app_id,
        secret=secret,
        base_url=base_url,
        is_sandbox=settings.rhmt_is_sandbox,
    )
    return RhmtCheckoutProvider(
        ledger,
        client,
        store_id=store_id,
        callback_url=callback_url,
        return_url=return_url,
        is_sandbox=settings.rhmt_is_sandbox,
        plan_songs=settings.starter_plan_songs,
        plan_days=settings.starter_plan_days,
        language_of=lambda: settings.default_ui_language,
        paused=paused or _never_paused,
    )


def _gated(
    paused: Callable[[], Awaitable[bool]] | None,
    rail_enabled: Callable[[str], Awaitable[bool]] | None,
    name: str,
) -> Callable[[], Awaitable[bool]] | None:
    """``paused`` OR "the owner switched ``name`` off", as the one callable a provider takes.

    **Composed INTO the existing pause callable rather than wrapped around the provider**
    (DECISIONS.md D28). The Rahmat and Payme providers already refuse a sale when their
    ``paused`` answers true, and already fail OPEN when it raises; a ``Gated…Provider``
    decorator would have re-implemented both and would have broken every test that pins
    ``isinstance(container.checkout, PaymeCheckoutProvider)`` and reads its ``_opener``. The
    price of the composition is the copy: a stale press on a switched-off Rahmat or Payme
    button shows the "paused" sentence, which is true enough — the rail is not selling — and
    the buttons themselves are no longer drawn once the switch is off.

    ``rail_enabled is None`` hands ``paused`` back UNCHANGED, ``None`` included, so a
    composition root that wires no switch reader builds byte-for-byte what it built before
    this existed. :func:`bayram.checkout_rails.read_rail_enabled` never raises and answers
    "enabled" on a Redis error, so this inherits the pause switch's direction: an unreadable
    switch keeps selling.
    """
    if rail_enabled is None:
        return paused
    base = paused or _never_paused

    async def gate() -> bool:
        if await base():
            return True
        return not await rail_enabled(name)

    return gate


def _build_payme_provider(
    settings: Settings,
    *,
    ledger: PaymentIntentOpener,
    merchant_id: str,
    paused: Callable[[], Awaitable[bool]] | None,
) -> PaymeCheckoutProvider:
    """The Payme rail, built in ONE place for ``payme`` alone and for ``both``.

    ``merchant_id`` is passed already resolved: under ``payme`` a blank one has been refused by
    :func:`build_checkout`, and under ``both`` it falls back to a placeholder exactly as the
    composite did before this helper existed.
    """
    return PaymeCheckoutProvider(
        ledger,
        merchant_id=merchant_id,
        base_url=resolve_base_url(
            is_sandbox=settings.payme_is_sandbox,
            override=settings.payme_checkout_base_url,
        ),
        account_field=settings.payme_account_field,
        return_url=settings.payme_return_url,
        is_sandbox=settings.payme_is_sandbox,
        plan_songs=settings.starter_plan_songs,
        plan_days=settings.starter_plan_days,
        language_of=lambda: settings.default_ui_language,
        paused=paused or _never_paused,
    )


def _build_checkoutuz_provider(
    settings: Settings,
    *,
    ledger: PaymentIntentOpener,
    session_factory: async_sessionmaker[AsyncSession],
    paused: Callable[[], Awaitable[bool]] | None,
    enabled: Callable[[], Awaitable[bool]] | None,
) -> CheckoutUzCheckoutProvider:
    """The checkout.uz rail (DECISIONS.md D28). Builds an HTTP client; opens no connection.

    ``enabled`` is checkout.uz's OWN argument rather than a second term folded into
    ``paused`` the way :func:`_gated` does for the other two rails: this provider was written
    after the switch existed, so it can tell the customer the rail is switched off
    (``CheckoutRailDisabledError``) instead of borrowing the pause sentence.

    The intent port is the SAME ``SqlPaymeLedger`` every other rail opens intents through —
    ``payment_intents`` is provider-agnostic and ``provider="checkoutuz"`` is stamped per row by
    the provider itself — and the payment side table is reached through its own store over the
    same session factory.

    The HTTP client is never closed by the container, which is the Rahmat client's standing
    arrangement: it lives exactly as long as the process does. The worker's poll and reconcile
    jobs build their own client per run, so this one is the BOT's alone.
    """
    client = CheckoutUzClient(
        api_key=settings.checkoutuz_api_key,
        base_url=settings.checkoutuz_base_url,
    )
    return CheckoutUzCheckoutProvider(
        ledger,
        client,
        SqlCheckoutUzPaymentStore(session_factory),
        webhook_base_url=settings.checkoutuz_webhook_base_url,
        return_url=settings.checkoutuz_return_url,
        plan_songs=settings.starter_plan_songs,
        plan_days=settings.starter_plan_days,
        language_of=lambda: settings.default_ui_language,
        paused=paused or _never_paused,
        enabled=enabled or _always_enabled,
    )


async def _always_enabled() -> bool:
    """checkout.uz's switch when no reader is wired: ON, for ``_never_paused``'s reason."""
    return True


def build_checkout(
    settings: Settings,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    paused: Callable[[], Awaitable[bool]] | None = None,
    rail_enabled: Callable[[str], Awaitable[bool]] | None = None,
) -> tuple[CheckoutProvider, PaymentIntentOpener | None]:
    """Which rail sells a credit, and the intent port that goes with it. Raises ``ConfigError``.

    **Two return values because they are one decision.** The rail and the intent port are the
    same object when the rail is a redirect one, and building them from two call sites would
    permit the combination that cannot work — a Payme provider over a stub opener, or a wired
    opener under a rail that never opens an intent — to be produced by an edit that looked
    local. Returning the pair from one function means the impossible combinations cannot be
    spelled.

    **The rails come from ONE ordered list**, :func:`bayram.checkout_rails.wired_rails`, and the
    bot draws its buttons from the very same list (``BotDeps.checkout_rails``, wired in
    ``bayram.main``). ``checkout_provider`` contributes ``rhmt`` / ``payme`` / both, and
    checkout.uz is appended when ``BAYRAM_CHECKOUTUZ_ENABLED`` is on with a key. An empty list
    is the stub; one rail is that rail's provider, BARE, so the ``isinstance`` and ``_opener``
    pins on the Payme deployment hold exactly as before; several are a
    :class:`~bayram.checkout.CompositeCheckoutProvider` that routes on the button's exact rail
    name and never falls through (DECISIONS.md D28). A stub never sits inside a composite, so a
    press can never fall through to a free song.

    **The refusals happen HERE, when the rail is actually built, and not at every boot.** That
    is the ``build_llm_provider`` precedent, and it is what lets a deployment on the stub — the
    default, and today's production — boot with no Payme configuration in its environment at
    all. A blank merchant id under ``checkout_provider="payme"`` is a ``ConfigError`` naming
    ``BAYRAM_PAYME_MERCHANT_ID``, because the alternative is a link whose ``m=`` parameter is
    empty: Payme's own checkout answers that with «Поставщик не найден», which is a sentence
    about THEIR system that a customer would read as a sentence about ours. checkout.uz
    switched on with a blank ``BAYRAM_CHECKOUTUZ_API_KEY`` is refused the same way: an operator
    who turned the rail on meant to sell on it, and a boot that quietly left its button off
    would be a go-live nobody could see had failed.

    ``paused`` is injected rather than constructed, so this function opens no Redis connection
    and stays synchronous, and so a test can pause the rail with three lines and no server.
    See :func:`_never_paused` for what the absence of one means. **This parameter is the ONE
    place the operator pause switch is wired**, and it is deliberately a parameter rather than
    something built here: the switch's Redis key is written by ``python -m bayram.payme.cli
    pause`` and read back by ``bayram.payme.pause.is_paused``, and a composition root that reached
    into that module directly would give this function a Redis dependency it does not otherwise
    have — for a feature that is off in every deployment that has not armed it.

    ``rail_enabled`` is the owner's PER-RAIL switch (DECISIONS.md D28), injected for the same
    reason and read the same way: ``rail_enabled("payme")`` over the queue pool in production,
    ``None`` everywhere else. It is composed into Rahmat's and Payme's ``paused`` by
    :func:`_gated` and handed to checkout.uz as its own ``enabled``. Only SALES read it;
    settlement never does, so switching a rail off never strands a payment already started.

    Note what is NOT read from settings here: the transaction timeout and the duplicate-code
    override. Both are the GATEWAY's configuration, on ``bayram.payme.settings.PaymeSettings``,
    in the process that terminates Payme's inbound calls. The ledger built here is handed out
    typed as ``PaymentIntentOpener``, whose one method never reaches either value, so passing
    the bot's guess at them would be passing a number nothing reads and inviting the two
    processes to disagree about one that matters.
    """
    if settings.checkout_provider not in (STUB_PROVIDER_NAME, "payme", "rhmt", "both"):
        raise ConfigError(
            f"unknown checkout rail: '{settings.checkout_provider}'",
            context={"checkout_provider": settings.checkout_provider},
        )
    if settings.checkoutuz_enabled and not settings.checkoutuz_api_key.strip():
        raise ConfigError(
            f"{ENV_PREFIX}CHECKOUTUZ_ENABLED is on but {ENV_PREFIX}CHECKOUTUZ_API_KEY is empty; "
            "checkout.uz cannot create a payment without the merchant's Bearer key. Set the key "
            "in the bot's dotenv, or turn the rail off.",
            context={"checkout_provider": settings.checkout_provider},
        )

    rails = wired_rails(settings)
    if not rails:
        # The default rail, and deliberately not a fallback for a misconfigured one.
        return StubCheckoutProvider(), None

    merchant_id = settings.payme_merchant_id.strip()
    if settings.checkout_provider == "payme" and not merchant_id:
        raise ConfigError(
            f"the checkout rail is set to '{settings.checkout_provider}' but "
            f"{ENV_PREFIX}PAYME_MERCHANT_ID is empty; the cashbox id is what every checkout "
            "link is built from and Payme has no way to identify us without it",
            context={"checkout_provider": settings.checkout_provider},
        )

    # The ledger's own ``merchant_id`` is only its default: every provider passes its own on
    # ``open_intent``. On a stub deployment selling checkout.uz alone there is no cashbox and
    # no Rahmat store, so the default names the rail that actually opens the intents.
    if settings.checkout_provider == STUB_PROVIDER_NAME:
        ledger_merchant_id = CHECKOUTUZ_MERCHANT_ID
    else:
        ledger_merchant_id = merchant_id or str(settings.rhmt_store_id or "rhmt")
    ledger = SqlPaymeLedger(
        session_factory,
        merchant_id=ledger_merchant_id,
        intent_ttl_s=settings.payme_intent_ttl_s,
        account_field=settings.payme_account_field,
    )

    providers: list[CheckoutProvider] = []
    for rail in rails:
        if rail == "rhmt":
            providers.append(
                _build_rhmt_provider(
                    settings, ledger=ledger, paused=_gated(paused, rail_enabled, rail)
                )
            )
        elif rail == "payme":
            providers.append(
                _build_payme_provider(
                    settings,
                    ledger=ledger,
                    # ``both`` has always tolerated a blank cashbox id here; ``payme`` alone
                    # was refused above.
                    merchant_id=merchant_id or "placeholder_merchant_id",
                    paused=_gated(paused, rail_enabled, rail),
                )
            )
        elif rail == CHECKOUTUZ_PROVIDER_NAME:
            providers.append(
                _build_checkoutuz_provider(
                    settings,
                    ledger=ledger,
                    session_factory=session_factory,
                    paused=paused,
                    enabled=_switch_for(rail_enabled, rail),
                )
            )
        else:  # pragma: no cover - wired_rails names only the three rails above
            raise ConfigError(f"unknown checkout rail: '{rail}'", context={"rail": rail})

    provider: CheckoutProvider = (
        providers[0] if len(providers) == 1 else CompositeCheckoutProvider(providers)
    )

    _LOG.info(
        "the checkout rail is live",
        extra={
            "checkout_provider": settings.checkout_provider,
            "rails": list(rails),
            "merchant_id": merchant_id,
            "has_pause_switch": paused is not None,
            "has_rail_switch": rail_enabled is not None,
        },
    )
    return provider, ledger


def _switch_for(
    rail_enabled: Callable[[str], Awaitable[bool]] | None, name: str
) -> Callable[[], Awaitable[bool]] | None:
    """``rail_enabled`` bound to one rail's name, or ``None`` when no reader is wired."""
    if rail_enabled is None:
        return None

    async def read() -> bool:
        return await rail_enabled(name)

    return read


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
    music_provider_resolver: Callable[[], Awaitable[str]] | None = None,
    rail_enabled: Callable[[str], Awaitable[bool]] | None = None,
) -> AppContainer:
    """Build everything. Raises ``ConfigError`` for a misconfiguration and nothing else.

    ``paused`` is threaded straight through to :func:`build_checkout` and is the operator
    pause switch. It is a PARAMETER and not something built here for the reason that function
    states: this container opens no Redis connection of its own. ``bayram.main.run`` passes a
    reader over the queue pool it was already going to open, so arming the switch costs no
    second connection — and a process with no pool (the demo path) passes ``None`` and gets a
    rail that is always open, which is the honest answer where no operator can reach it.

    ``rail_enabled`` is the owner's per-rail switch (DECISIONS.md D28) and travels the same
    road for the same reason: ``bayram.main.run`` passes a reader over the same pool, and
    ``None`` leaves every wired rail switched on.

    Wiring only — it does not probe ffmpeg. That check belongs to *process* startup
    (:func:`bayram.runtime.startup.verify_host`), so a host missing libopus fails one boot
    loudly instead of every order quietly, one customer at a time.

    ``with_providers=False`` builds the same container with no vendor adapter in it. That
    is not a convenience: it is what lets a process hold the database and the object store
    without holding a credential that can spend money, and the resulting container raises a
    named :class:`bayram.errors.PipelineError` from :meth:`AppContainer.pipeline` rather than
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
    # ``bayram.main.run`` passes is a reader over the queue pool it opens anyway, so the switch
    # is armed for free in the process that sells songs; ``None`` — the demo path, and every
    # test that does not care — leaves the rail always open. See ``build_checkout``.
    checkout, intents = build_checkout(
        settings, session_factory=session_factory, paused=paused, rail_enabled=rail_enabled
    )
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
            build_provider_set(
                settings,
                usage=DbUsageSink(session_factory),
                music_provider_resolver=music_provider_resolver,
            )
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
        # that a deployment which lengthened ``BAYRAM_QUEUE_JOB_TIMEOUT_S`` gets a settlement
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
        # ``BAYRAM_CHECKOUT_PROVIDER=stub`` — which is what ships — the object constructed here
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
        # ``bayram.payme.provider``. See DECISIONS.md D11 and PAYME_INTEGRATION §1.
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
        # ``bayram.db.admin`` and the only writers are the bot's membership handler and the
        # worker's send refusal. No policy argument exists to pass: the retention cutoff for
        # this table is ``bayram.db.purge.BOT_MEMBERSHIP_RETENTION_DAYS``, a module constant
        # rather than a knob, because the only thing a knob here could do is lose history.
        bot_blocks=SqlBotBlocks(session_factory),
        # Built unconditionally, including for the ADMIN process, which holds it and never
        # calls it — its reads go through ``bayram.db.admin.bot_chats`` and its two writes are
        # composed into the request transaction that carries the audit row. No policy argument
        # exists to pass and none should: this table has no retention clock (it is a directory
        # of rooms, not a log of events) and no configuration, because the two settings that
        # used to name the support group were removed outright rather than demoted to a
        # fallback. See ``SUPPORT_TICKETS_SPEC §3.8``.
        bot_chats=SqlBotChats(session_factory),
    )


async def _create_schema(engine: AsyncEngine) -> None:
    """SQLite has no migration history to honour, so the schema is materialised directly."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    _LOG.info("sqlite schema created", extra={"tables": len(Base.metadata.tables)})
