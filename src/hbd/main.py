"""The bot process. ``python -m hbd.main``.

Two shapes, one code path:

* **Production** — Redis holds the wizard state and the queue; ARQ workers do the
  generating. ``HBD_USE_FAKE_PROVIDERS`` is off, real keys are read, real money is spent.
* **Offline demo** — ``HBD_USE_FAKE_PROVIDERS=1``. The FSM lives in memory, the order runs
  as a background task inside this process, and every vendor is a fake. One command, one
  terminal, no infrastructure, no keys, no spend.

The branch is exactly one decision (``use_fake_providers``), and everything downstream of
it is the same objects wired the same way, because a demo path that exercises different
code proves nothing about the thing you are demonstrating.

**This process also refuses to start on three configurations that would be silently
expensive** — see :func:`refuse_an_unsafe_checkout_rail`. They run before anything is built,
they are about configuration alone, and each of them protects a failure that nothing else in
the process could ever notice: a live payment rail feeding a credit meter that is switched
off, another process's credential within reach of this one in production, and a checkout link
that outlives the draft it was sold against. Refusing a boot is a heavy answer and is the
right one here for the same reason ``verify_host`` is: the alternative is one customer at a
time discovering it.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiogram import Bot
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from dotenv import dotenv_values

from hbd.bot.app import (
    WIZARD_STATE_TTL,
    build_bot,
    build_dispatcher,
    build_event_isolation,
    build_storage,
    run_polling,
)
from hbd.bot.chatlog import ChatLogOutboundMiddleware, ChatRecorder
from hbd.bot.deps import BotDeps
from hbd.bot.ports import OrderSubmitter
from hbd.bot.pricing import Pricing
from hbd.checkout import STUB_PROVIDER_NAME
from hbd.config import FOREIGN_SECRET_ENV_VARS, Settings, env_file, load_settings
from hbd.errors import ConfigError, HbdError
from hbd.logging import configure_logging, get_logger
from hbd.payme.pause import is_paused
from hbd.pipeline.content import LlmContentWriter
from hbd.runtime.container import AppContainer, build_container
from hbd.runtime.jobs import (
    BOT_CTX_KEY,
    CONTAINER_CTX_KEY,
    STORAGE_CTX_KEY,
    generate_and_deliver,
)
from hbd.runtime.startup import verify_host
from hbd.runtime.submitter import ArqOrderSubmitter, InProcessOrderSubmitter

__all__ = [
    "main",
    "run",
    "build_queue_pool",
    "build_submitter",
    "refuse_an_unsafe_checkout_rail",
]

_LOG = get_logger(__name__)


def _reachable_foreign_secrets() -> tuple[str, ...]:
    """Which credentials belonging to ANOTHER process this one can see. Names, never values.

    Two sources, because both are real: what the deploy exported into the environment, and
    what somebody wrote into the dotenv file THIS process reads. An empty value in either is
    "not set", which is the normal shape of a blanked or commented-out key.

    The file is resolved through :func:`hbd.config.env_file` at call time rather than
    imported as a value, because this is a security control and it has to read the SAME file
    ``load_settings`` read — a check against ``.env`` on a host booting from
    ``/etc/hbd/bot.env`` would clear a process whose forbidden key is sitting in the file it
    actually loaded. This mirrors ``hbd.admin.app._present_vendor_vars`` deliberately; the two
    are the same control pointed at two different processes and two different files.
    """
    path = env_file()
    try:
        parsed = dotenv_values(path)
    except OSError as exc:
        # Not swallowed: the file is unreadable rather than absent, so the check below is
        # weaker than it looks and whoever reads the log has to be told which half ran.
        _LOG.warning(
            "could not read the bot env file; the foreign-credential check saw the process "
            "environment only",
            extra={"path": path, "detail": repr(exc)},
        )
        from_file: frozenset[str] = frozenset()
    else:
        # Upper-cased because pydantic-settings reads these case-insensitively: a lowercase
        # ``hbd_payme_merchant_key`` line is exactly as live as the shouted form.
        from_file = frozenset(name.upper() for name, value in parsed.items() if value)
    return tuple(
        name for name in FOREIGN_SECRET_ENV_VARS if os.environ.get(name) or name in from_file
    )


def refuse_an_unsafe_checkout_rail(settings: Settings) -> None:
    """Three boot refusals about money. Raises ``ConfigError``; returns ``None`` when safe.

    Called before anything is built, because each of these is a statement about configuration
    alone and none of them needs a database, a Redis or a vendor. A process that is going to
    refuse should refuse before it opens a connection pool.

    **1. A live rail over a dark credit meter.** This used to be a WARNING, and the warning
    was right for a stub that reports every purchase paid and takes nothing. It is not right
    for a rail that takes real money: with ``credits_enforced`` false the worker covers a
    short balance with an ``UNENFORCED_RENDER`` grant and renders anyway, so the customer is
    charged 7 000 UZS and would have got the song for nothing. The failure is silent, it is
    on the money path, and nothing else in the process would ever notice it — the bot-side
    paywall deliberately does not read that flag. So the two settings must move in the same
    edit, and this refusal is what makes that mandatory rather than remembered. The warning
    below it survives for the stub, where it is still exactly the right volume.

    **2. The merchant key within reach of the bot, in prod.** The bot builds checkout links
    from the PUBLIC merchant id and must never hold the Merchant API key: that key is an
    inbound verification secret whose theft mints credits, it belongs to one process, and the
    whole reason the gateway is a fourth process is that its blast radius is different in kind
    from the four outbound credentials this one holds. Prod only, and a warning elsewhere, for
    the same reason the admin app's mirror image of this check is: a developer with one dotenv
    on a laptop is not the incident this is about, and a refusal there would only teach people
    to delete the check.

    **3. A payment link that outlives the draft it was bought for.** ``payme_intent_ttl_s``
    must be strictly less than the wizard-state TTL. Otherwise a customer can pay for a draft
    whose recipient name, note and approved lyric have already been swept out of Redis, and
    the money would arrive against an order that cannot be assembled. Checked unconditionally
    rather than only for a live rail, because it is a relationship between two numbers and not
    between two running things: it must already hold on the day somebody flips the rail on,
    not start being checked then. It cannot fail today — the field is bounded at 24 hours and
    the draft clock is fourteen days — and it is here for the day either number moves, which
    is precisely when nobody will be thinking about the other one.
    """
    is_live_rail = settings.checkout_provider != STUB_PROVIDER_NAME
    if is_live_rail and not settings.credits_enforced:
        raise ConfigError(
            f"HBD_CHECKOUT_PROVIDER is '{settings.checkout_provider}' but "
            "HBD_CREDITS_ENFORCED is false: a rail taking real money into a meter nobody "
            "reads sells the song for nothing and charges for it anyway. Set "
            "HBD_CREDITS_ENFORCED=true in the same edit, or set HBD_CHECKOUT_PROVIDER=stub.",
            context={
                "checkout_provider": settings.checkout_provider,
                "credits_enforced": settings.credits_enforced,
            },
        )

    reachable = _reachable_foreign_secrets()
    if reachable:
        listed = ", ".join(reachable)
        if settings.is_production:
            raise ConfigError(
                "The bot process must not hold the Payme Merchant API key, and these are "
                f"within reach of it — in its environment or in {env_file()}: {listed}. The "
                "bot builds checkout links from the PUBLIC merchant id; the key verifies "
                "INBOUND calls and belongs only to the Payme gateway's own env file.",
                context={"variables": list(reachable)},
            )
        _LOG.warning(
            "a credential belonging to another process is within reach of the bot",
            extra={"variables": list(reachable), "environment": settings.environment},
        )

    draft_ttl_s = int(WIZARD_STATE_TTL.total_seconds())
    if settings.payme_intent_ttl_s >= draft_ttl_s:
        raise ConfigError(
            f"HBD_PAYME_INTENT_TTL_S ({settings.payme_intent_ttl_s}s) must be strictly less "
            f"than the wizard-state TTL ({draft_ttl_s}s): a checkout link that outlives the "
            "draft it was bought for takes money for an order that can no longer be "
            "assembled, because the recipient's name, the note and the approved lyric have "
            "already expired out of Redis.",
            context={
                "payme_intent_ttl_s": settings.payme_intent_ttl_s,
                "wizard_state_ttl_s": draft_ttl_s,
            },
        )


def _fsm_storage(settings: Settings) -> BaseStorage:
    """Redis in production so a restart does not throw away a half-typed wizard.

    Delegates to ``bot.app.build_storage`` rather than calling ``RedisStorage.from_url``
    itself. That function is where the retention TTL lives — an abandoned draft holds the
    recipient's name, the note and the approved lyric, and without the TTL that copy
    outlived every sweep in ``hbd.db.purge`` — and having the production path skip it made
    the setting decorative.
    """
    if settings.use_fake_providers:
        return MemoryStorage()
    return build_storage(settings)


async def build_queue_pool(settings: Settings) -> ArqRedis | None:
    """The ONE Redis connection this process opens for the queue, or ``None`` on the demo path.

    Split out of :func:`build_submitter` so it can be opened BEFORE the container, which is
    what lets the same pool be handed to :func:`hbd.runtime.container.build_container` as the
    operator pause switch. Two readers, one connection: the alternative was a second client
    opened purely to read one key, which ``build_checkout`` refuses on the grounds that it
    would be a connection nothing closes.

    Opening it first also moves a Redis outage EARLIER, to before the database engine and the
    object store exist. That is the right direction: a process that is going to die on a
    missing queue should die holding nothing.
    """
    if settings.use_fake_providers:
        return None
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))


def _pause_reader(pool: ArqRedis | None) -> Callable[[], Awaitable[bool]] | None:
    """The pause switch as ``build_checkout`` wants it: one argument-free awaitable.

    ``None`` when there is no pool, which is the demo path — a rail nobody operates is a rail
    that is always open, and inventing a switch there would be a control that reports itself
    deployed when it is not. :func:`hbd.payme.pause.is_paused` never raises and answers "open"
    when Redis cannot be read, so nothing on the checkout path can fail because of this.
    """
    if pool is None:
        return None

    async def read() -> bool:
        return await is_paused(pool)

    return read


async def build_submitter(
    settings: Settings,
    container: AppContainer,
    bot: Bot,
    storage: BaseStorage,
    *,
    pool: ArqRedis | None = None,
) -> tuple[OrderSubmitter, object | None]:
    """The queue seam. Returns the submitter and whatever must be closed with it.

    The demo path runs the job inside this process, so it is handed the very storage the
    dispatcher uses: the job releases the wizard session when the run ends, and it has to
    release the same session the wizard is parked in.

    ``pool`` is the connection :func:`build_queue_pool` already opened. It stays OPTIONAL so a
    caller that only wants a submitter — ``tests/test_runtime/test_entrypoints.py`` — need not
    know about the pause switch to get one; passing ``None`` opens a pool here exactly as this
    function always did.
    """
    if settings.use_fake_providers:
        ctx = {CONTAINER_CTX_KEY: container, BOT_CTX_KEY: bot, STORAGE_CTX_KEY: storage}

        async def run_inline(order_id: str, chat_id: int, progress_message_id: int) -> None:
            summary = await generate_and_deliver(ctx, order_id, chat_id, progress_message_id)
            _LOG.info("inline job finished", extra=summary)

        return (
            InProcessOrderSubmitter(
                container.repository, run_inline, is_production=settings.is_production
            ),
            None,
        )

    redis = (
        pool if pool is not None else await create_pool(RedisSettings.from_dsn(settings.redis_url))
    )
    return ArqOrderSubmitter(redis, container.repository), redis


async def run(settings: Settings, *, data_root: Path | None = None) -> None:
    """Build everything, poll until interrupted, then release it all."""
    # Before anything is built: three statements about configuration alone, each of which
    # would otherwise fail silently and on the money path. See the function's docstring.
    refuse_an_unsafe_checkout_rail(settings)
    verify_host(settings)
    # The queue pool first, so the container can be handed a pause reader over it. See
    # :func:`build_queue_pool` for why one connection serves both and why earlier is better.
    pool = await build_queue_pool(settings)
    container = await build_container(settings, data_root=data_root, paused=_pause_reader(pool))
    bot = build_bot(settings)
    storage = _fsm_storage(settings)
    submitter, closeable = await build_submitter(settings, container, bot, storage, pool=pool)
    chat_recorder = ChatRecorder(container.session_factory) if container.session_factory else None
    if chat_recorder is not None:
        bot.session.middleware(ChatLogOutboundMiddleware(chat_recorder))
    deps = BotDeps(
        settings=settings,
        submitter=submitter,
        # The wizard writes the lyric before the order is queued, so it needs the same
        # writer the pipeline uses. The primary provider only: the fallback exists for the
        # worker's unattended retries, and a customer waiting on a screen is better served
        # by a quick "please try again" than by a second slow vendor call.
        content=LlmContentWriter(container.require_providers().llm, settings),
        # ``container.payment`` is the PLAIN no-op provider. The credit-gated decorator is
        # built per job inside ``AppContainer._render_gate`` and deliberately never reaches
        # here: the bot must not be able to write a debit, because its three early returns
        # after the gate cannot compensate one. What the bot gets instead is the line below.
        payment=container.payment,
        # Read on every gate, spent by none of them. ``handlers.confirm._entitlement_refusal``
        # and ``handlers.balance`` call exactly one method — ``balance_for`` — so a customer
        # learns what they have on the Confirm screen and from ``/balance`` rather than after
        # the progress bar has been running, and nothing on this side spends anything. The
        # only write the bot makes through this seam is ``/forget``, which removes rows and
        # therefore cannot be turned into a free song.
        entitlements=container.credits,
        # The one meter the bot writes. A lyric write is an LLM call made on the
        # customer's screen before any gate the worker enforces, and the per-draft cap
        # is reset by ``/start`` — so without this the free tier had no per-person
        # ceiling at all. It cannot spend a credit or refuse an order; it only bounds
        # how many times a day one account may bill the writer.
        lyric_budget=container.lyric_budget,
        # The onboarding record. Written by the bot and by nothing else — the worker has no
        # customer in front of it — and the one handle ``handle_forget`` needs to erase a
        # phone number and a face along with the credit record.
        profiles=container.profiles,
        # ``amount_minor`` is what the RENDER gate is quoted at — ``confirm._is_authorized``
        # authorises this amount against the plain ``NoopPaymentProvider`` above — while
        # ``pricing`` below is what the CHECKOUT screen quotes on its buttons. They are the
        # same number today and are allowed to diverge: one is per order, the other is a
        # catalogue, and a deployment that discounted the catalogue must not thereby change
        # what the worker's gate authorises.
        amount_minor=settings.single_song_price_minor,
        currency=settings.kit_currency,
        # The purchase rail. A different question from ``payment`` above: that authorises a
        # render, this takes money for one. The shipped provider contacts nothing — and so
        # does the Payme one, which is the surprising part: a redirect rail's ``charge``
        # writes a row and builds a base64 URL, because Payme has no create-payment-link API
        # for the standard checkout. See ``hbd.payme.provider``.
        checkout=container.checkout,
        # The redirect rail's intent port, ``None`` on an inline rail. THE SAME OBJECT the
        # provider above already holds, handed over separately and typed as the narrow
        # ``PaymentIntentOpener`` so that this process can open a payment and structurally
        # cannot settle, cancel or force-settle one — the identical asymmetry ``purchases``
        # below states against the meter, applied one level out against the rail.
        intents=container.intents,
        # THE ONE PLACE THE BOT MAY CAUSE A CREDIT TO BE MINTED, and it only ever happens
        # after ``deps.checkout`` has reported the purchase paid. The port carries no
        # ``charge`` and no ``settle``, so the asymmetry stated on ``payment`` above survives
        # intact: the bot grants what was paid for, and only the worker spends it.
        purchases=container.purchases,
        # What the buttons say. Resolved ONCE, here, so no handler reads ambient settings.
        pricing=Pricing.from_settings(settings),
        # Churn. Note the asymmetry against the two fields above it: ``profiles`` is the
        # bot's alone because the worker never learns anything new about a customer, and the
        # render gate is the worker's alone because the bot may not spend — but BOTH
        # processes hold this one, because a block is learned in two places. The bot gets the
        # ``my_chat_member`` update at the instant it happens; the worker gets a refused
        # ``sendAudio`` some time after. They are not redundant while ``run_polling`` calls
        # ``delete_webhook(drop_pending_updates=True)`` on every start — every membership
        # update that arrived during a deploy window is discarded and never resent, so the
        # worker's arm is the only source that survives a restart.
        bot_blocks=container.bot_blocks,
        chat_recorder=chat_recorder,
    )
    # The lock that makes a state filter a real gate. Built from the same Redis as the
    # storage, so it holds across every process that could handle this chat.
    dispatcher = build_dispatcher(
        deps, storage=storage, events_isolation=build_event_isolation(settings)
    )
    _LOG.info(
        "bot starting",
        extra={
            "environment": settings.environment,
            "is_fake": settings.use_fake_providers,
            "ui_language": settings.default_ui_language.value,
        },
    )
    if container.purchases is not None and not settings.credits_enforced:
        # A warning and deliberately NOT a refusal, and the boundary has moved rather than
        # blurred: with a LIVE rail this combination is now refused outright, up in
        # ``refuse_an_unsafe_checkout_rail``, because real money makes it a defect. What
        # survives here is the STUB case, where a deployment that wants to give songs away
        # must be able to — but the two settings disagreeing is still worth saying out loud at
        # boot, because the symptom is silent: the customer is shown a price, the stub reports
        # it paid, and the worker then covers the shortfall with an ``UNENFORCED_RENDER``
        # grant anyway, so the render happens whether or not a payment did.
        # ``HBD_CREDITS_ENFORCED=true`` is the intended production setting once a price is on
        # screen; the bot-side paywall deliberately does not read that flag, which is exactly
        # why nothing else in the process would ever notice the mismatch.
        _LOG.warning(
            "the checkout is wired but the credit meter is dark",
            extra={"credits_enforced": settings.credits_enforced},
        )
    try:
        await run_polling(bot, dispatcher)
    finally:
        await _shutdown(container, bot, closeable)


async def _shutdown(container: AppContainer, bot: Bot, closeable: object | None) -> None:
    """Release everything, reporting each failure rather than letting one hide the rest."""
    for label, close in (
        ("queue", getattr(closeable, "aclose", None)),
        ("bot", bot.session.close),
        ("container", container.aclose),
    ):
        if close is None:
            continue
        try:
            await close()
        except Exception as exc:
            _LOG.warning("could not close cleanly", extra={"resource": label, "detail": repr(exc)})


def main() -> int:
    """Console entry point. Returns a process exit code; never raises."""
    try:
        settings = load_settings()
    except HbdError as exc:
        # No logging is configured yet, so this is the one place stderr is the right sink.
        print(f"hbd: {exc.operator_message}")
        return 2

    configure_logging(level=settings.log_level, is_json=not settings.is_debug)
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        _LOG.info("bot stopped by operator")
    except HbdError as exc:
        _LOG.error("bot could not start", extra=exc.to_log_dict())
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    with contextlib.suppress(SystemExit):
        raise SystemExit(main())
