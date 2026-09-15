"""The two worker jobs the redirect rail needs: tell the customer, and catch the backlog.

**Why these are jobs at all, and not code in the process that took the money.** The Payme
gateway is a fourth process (``bayram-payme.service``) and it holds exactly one credential — the
cashbox key — because that key's blast radius is different in kind from the five outbound
credentials the bot holds: stealing it mints credits, it does not impersonate us or spend our
vendor balance. **It holds no Telegram token, and that is the whole point of it existing.** So
the one thing a settlement obviously ought to do — say "your payment went through" — is the
one thing that process cannot do. It enqueues :func:`notify_payment_settled` instead and the
WORKER, which already owns a ``Bot`` that never polls and only sends, performs the delivery.
That is not a workaround; it is the same rule that keeps the admin panel from ever holding a
vendor key (:mod:`bayram.runtime.vendor_balance_job` makes the identical argument from the other
side: the worker polls, the panel selects).

**Why there is a cron here at all, when the design paper says expiry needs none.** Both
claims are true and they are about different things.

*Expiry is a PREDICATE and it stays one.* An intent's window is evaluated against the injected
clock at the instant a request forces the machine to move, so the state machine is correct at
every instant with no scheduler in the picture. The two state arms of :func:`run_payme_sweep`
run that same predicate as a BACKSTOP, for rows the rail creates and then never mentions
again; nothing's correctness depends on them, and if this cron never fired, no customer would
be charged wrongly and no credit would be granted twice.

*Delivery is NOT a predicate, and this is the correction to that paper.* The gateway's
post-commit enqueue is best-effort by design: Payme must receive its HTTP 200 whether or not
Redis answered, so a failed enqueue is logged and swallowed. Without a backstop that decision
turns a Redis blip lasting seconds into a customer who paid 7 000 UZS and was never told —
permanently, because nothing would ever look at the row again. **Arm three is the only arm
here that exists for delivery rather than for state, and it is what makes the swallowed
enqueue an acceptable trade: a Redis outage at Perform time becomes a latency problem bounded
by ``BAYRAM_PAYME_SWEEP_MINUTES``, not a silence.**

**The sweep is NOT gated on ``BAYRAM_CHECKOUT_PROVIDER``, deliberately.** The documented rollback
is "set the provider back to ``stub`` and restart the bot", and the gateway is independent of
that setting — a transaction already in flight still settles, because Payme calls the gateway
and the gateway never reads the bot's provider choice. A sweep that switched itself off with
the bot's rail would stop notifying exactly the customers a rollback stranded. It therefore
runs unconditionally and costs four bounded reads against three empty tables on a deployment
that has never sold anything through Payme.

**The three-way invariant, and what it can and cannot see.** The Merchant API is entirely
INBOUND — there is no method a merchant may call — so nothing in this system can ask Payme
what it believes happened. The counts in arm four are the only automated check that exists on
the newly shared write primitive (:func:`bayram.db.fulfilment.write_single_sale`), which is now
called from two processes instead of one. **Nothing in that arm repairs anything.** A
scheduler that silently corrected a settlement discrepancy would destroy the only evidence
that the primitive had drifted, and its "repair" would be a credit grant written on a guess.

This module builds its OWN ``SqlPaymeLedger`` rather than reading one off the container, and
that is a deliberate boundary rather than laziness. The container carries the rail as
``bayram.checkout.PaymentIntentOpener`` — a port with exactly one method, ``open_intent`` — which
is what the BOT holds, and the narrowness of that handle is a security property: the bot
cannot settle a payment because the object it was handed does not declare a method that could.
The worker needs the WIDE port (:class:`bayram.payme.ports.PaymeLedger`). Widening the container
field to the settling port to serve this module would hand the bot process the settling half
by the same line of code. Constructing one here, from the session factory the container
already owns, costs nothing at all — it is field assignment, no I/O — and keeps the two handles
honestly different. It is the same reasoning by which
:mod:`bayram.runtime.vendor_balance_job` owns its ``httpx.AsyncClient`` instead of borrowing the
``ProviderSet``'s.

See ``PAYME_INTEGRATION §5`` for the five replay guarantees these jobs must not violate, and
``DECISIONS.md D11`` for why the rail exists at all.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup
from arq.worker import Retry

from bayram.bot.delivery import is_blocked_by_customer
from bayram.bot.i18n import parse_language, translate
from bayram.bot.keyboards import paid_late_keyboard, start_over_keyboard
from bayram.checkout import PaymentIntent, PaymentIntentState, PlanState, Product
from bayram.config import Settings
from bayram.contracts import Language, Result, is_err
from bayram.db.base import utc_now
from bayram.db.credit_sql import verify_balances
from bayram.db.payme import SqlPaymeLedger
from bayram.errors import PipelineError
from bayram.logging import get_logger
from bayram.payme.ports import PaymeLedger, SettlementCounts
from bayram.payme.protocol import PaymeState
from bayram.payme.rules import DEFAULT_TRANSACTION_TIMEOUT_MS
from bayram.runtime.container import AppContainer
from bayram.runtime.render_resume import (
    ResumeAssessment,
    ResumeDecision,
    plan_resume,
    resume_render,
)

__all__ = [
    "notify_payment_settled",
    "run_payme_sweep",
    "payme_notify_job_id",
    "build_worker_payme_ledger",
    "sweep_minutes",
    "PAYME_NOTIFY_JOB_NAME",
    "PAYME_SWEEP_JOB_NAME",
    "PAYME_NOTIFY_MAX_TRIES",
    "PAYME_SWEEP_BATCH_SIZE",
    "PAYME_NOTIFY_GRACE_S",
    "PAID_LATE_SINGLE_KEY",
    "PAID_LATE_PLAN_KEY",
    "PAID_LATE_RESUMING_KEY",
    "SweepReport",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function NAME, so the enqueue side — which is in ANOTHER PROCESS here,
#: the Payme gateway — and the worker side must agree on this exact string. Both names are
#: asserted against their functions at the bottom of this module, because the two sides are
#: further apart than usual: a rename that compiled in both would simply stop notifying
#: customers, silently, with the money already banked.
PAYME_NOTIFY_JOB_NAME: Final[str] = "notify_payment_settled"
PAYME_SWEEP_JOB_NAME: Final[str] = "run_payme_sweep"

#: The kit job's context keys, RE-STATED rather than imported from :mod:`bayram.runtime.jobs`.
#: Importing them would make this module depend on the one that registers it, which is a
#: cycle; :mod:`bayram.runtime.retention_job` and :mod:`bayram.runtime.vendor_balance_job` restate
#: the same string for the same reason.
CONTAINER_CTX_KEY: Final[str] = "container"
BOT_CTX_KEY: Final[str] = "bot"
#: ARQ's own key for the pool it hands every job. Present in a real worker and absent in a
#: hand-built context, which is why arm three treats it as optional rather than required.
REDIS_CTX_KEY: Final[str] = "redis"

#: How many attempts the notification gets, and the number this module reads to decide when
#: a retryable failure has become terminal. It has to equal the ``max_tries`` the function is
#: REGISTERED with in :mod:`bayram.runtime.jobs`, because ARQ compares ``job_try > max_tries`` at
#: the top of its own runner — the attempt that would have been the sixth never enters the
#: function at all, so a job that raised ``Retry`` on its last permitted attempt is discarded
#: with nobody told. ``bayram.runtime.jobs._is_final_attempt`` learned this the hard way for the
#: kit job; the same lesson is worth exactly one constant here.
PAYME_NOTIFY_MAX_TRIES: Final[int] = 5

#: Seconds between attempts, multiplied by the attempt number the way ARQ counts them (from
#: 1). Sized for a Telegram hiccup rather than for a vendor rate limit: the customer is
#: waiting and the money is already ours.
PAYME_NOTIFY_BACKOFF_S: Final[float] = 5.0

#: Every arm of the sweep is bounded by this. A backlog is worked off in five-minute bites
#: rather than in one lock-taking run, which is the argument the retention sweep already
#: makes for its own batch size.
PAYME_SWEEP_BATCH_SIZE: Final[int] = 200

#: How old a settled-but-unnotified intent must be before the backstop re-enqueues it. The
#: gateway's own enqueue fires within milliseconds of the commit, so a sweep with no lower
#: bound would double-enqueue every healthy payment it happened to catch mid-flight. The job
#: is idempotent either way — a deterministic ARQ job id plus a conditional ``notified_at``
#: stamp — but a backstop that fired on the HEALTHY path would make its own error rate the
#: one number nobody could read.
PAYME_NOTIFY_GRACE_S: Final[int] = 60

#: The window arm four reconciles over. A day rather than the five minutes between runs,
#: because the counts are cheap and a defect that appeared at 03:00 must still be visible at
#: 09:00 when somebody is awake to read it.
PAYME_INVARIANT_WINDOW_HOURS: Final[int] = 24

#: How many performed transactions the detail scan will name when the counts disagree. The
#: scan runs ONLY on a mismatch (see :func:`_reconcile`), so this bounds an incident and
#: never the healthy path. A fuller audit is ``python -m bayram.payme.cli invariant``.
PAYME_ORPHAN_SCAN_LIMIT: Final[int] = 50

#: The two sentences a settled payment is announced with. They are deliberately NOT
#: ``checkout.paid_single``/``paid_plan``: that copy says "press 🎬 Record it" about a screen
#: the customer is looking at, while these arrive COLD, possibly hours after the payment and
#: from a different process, so they have to re-open the door themselves. Named here rather
#: than spelled at the call site because the writer of the catalogue entry and the reader are
#: in different workstreams, and ``tests/test_bot/test_locale_contract.py``'s AST scan is what
#: holds the four catalogues in step with these two constants.
PAID_LATE_SINGLE_KEY: Final[str] = "checkout.paid_late_single"
PAID_LATE_PLAN_KEY: Final[str] = "checkout.paid_late_plan"

#: The third cold sentence: the payment landed AND the song is already being made.
#:
#: It REPLACES the two above whenever a render is being started, rather than being appended
#: to one of them, and it carries no credit count on purpose — telling somebody they have one
#: song ready and spending it in the same breath is the support ticket ``_announcement``'s
#: docstring warns about. The keyboard under it is ``None``; see :func:`_announcement_keyboard`.
PAID_LATE_RESUMING_KEY: Final[str] = "checkout.paid_late_resuming"


def payme_notify_job_id(public_ref: str) -> str:
    """The deterministic ARQ job id for one intent's notification.

    Deterministic for the reason ``bayram.pipeline.worker.job_id_for`` is: ARQ refuses to queue a
    job id that is already queued, so the gateway's post-commit enqueue and the sweep's
    backstop enqueue for the SAME intent collapse into one job rather than two messages. It
    lives here, exported, because the two callers are in two different processes and a second
    spelling of this string would quietly disable the deduplication rather than break a build.

    Keyed on ``public_ref`` and not on the idempotency key: the idempotency key is
    ``topup:{telegram_user_id}:{scope}:{seq}`` and would put a customer's Telegram id into a
    Redis key name and into the worker's own log lines, which is exactly what ``public_ref``
    was minted to avoid.
    """
    return f"{PAYME_NOTIFY_JOB_NAME}:{public_ref}"


def sweep_minutes(settings: Settings) -> tuple[int, ...]:
    """Which minutes past the hour :func:`run_payme_sweep` fires on.

    SEVERAL minutes rather than one, because this cron is a delivery backstop and its cadence
    is the ceiling on how long a customer who paid during a Redis outage waits to hear about
    it. Every other cron in this worker fires once an hour on a minute chosen to avoid the
    others (:17 retention, :43 balances, :07 the nightly snapshot); this one deliberately fires
    twelve times an hour by default, and the arithmetic below is what turns "every N minutes"
    into the collection ARQ's ``cron()`` takes.

    **A TUPLE and not a set, and the reason is a test rather than a taste.** ARQ accepts
    ``int``, ``set``, ``list`` or ``tuple`` for a cron field and treats all four identically —
    ``arq.cron._get_next_dt`` dispatches on ``isinstance(v, (set, list, tuple))``. But
    ``tests/test_runtime/test_vendor_balance_job.py`` collects every entry's ``minute`` into a
    ``set`` to prove no two scheduled writers collide on one minute, and a ``set`` value is
    unhashable — so returning one would have made a five-minutely delivery backstop break a
    lock-contention test it has nothing to do with. A tuple is hashable, is ordered (so a
    printed schedule reads in clock order) and costs nothing. ``frozenset`` is NOT an option:
    it is a subclass of none of the three arq tests for, so arq would raise at schedule time.

    The bound on the cadence lives on the settings FIELD (``ge=1, le=60``) and is deliberately
    not restated here. Two validators disagreeing about a legal value is how a configuration
    that passed at boot gets silently replaced by a default at schedule time, and sixty — once
    an hour — is a defensible choice for a deployment that would rather batch.
    """
    return tuple(range(0, 60, settings.payme_sweep_minutes))


def build_worker_payme_ledger(container: AppContainer) -> PaymeLedger:
    """The WIDE rail port, built here rather than taken off the container.

    See the module docstring for why: the container's rail handle is the bot's, typed as
    ``bayram.checkout.PaymentIntentOpener``, and it is narrow on purpose. Returning
    :class:`bayram.payme.ports.PaymeLedger` rather than the concrete class is what makes
    ``mypy --strict`` check the structural conformance HERE, at the one place in the worker
    that depends on it, rather than at some later attribute access.

    ``merchant_id`` is carried for completeness and is never compared on any path this module
    reaches: the worker neither quotes a link nor performs a settlement, which are the two
    places the cashbox id is checked. It is passed anyway rather than blanked, because a handle
    that silently disagreed with the gateway's about which cashbox this deployment sells
    through would be a trap for whoever adds the next method.

    ``transaction_timeout_ms`` is the shipped twelve hours and is NOT read from configuration,
    which is a real limitation stated rather than hidden. The rail's window is a
    ``PaymeSettings`` field living in the gateway's own dotenv, reached through its own
    ``BAYRAM_PAYME_ENV_FILE`` variable, and this process deliberately does not load that file —
    it holds no cashbox key and must not be able to. The consequence is bounded and benign:
    the knob exists so a CERTIFICATION run can drive the expiry branch in seconds, and during
    such a run the worker's arm-two backstop would simply keep measuring twelve hours. Every
    request that forces the state machine to move already evaluates the real window inside the
    gateway, so nothing's correctness rides on this number — only how long an abandoned
    transaction sits in ``created`` before the sweep tidies it up.
    """
    return SqlPaymeLedger(
        container.require_session_factory(),
        merchant_id=container.settings.payme_merchant_id,
        transaction_timeout_ms=DEFAULT_TRANSACTION_TIMEOUT_MS,
    )


@dataclass(frozen=True, slots=True)
class SweepReport:
    """What one run of the sweep did, as four independent numbers plus its faults.

    Four counts and never one "rows touched" total: the arms answer four different operational
    questions and an operator reading this line is asking exactly one of them. ``notified`` in
    particular is the only number here that measures a DELIVERY backstop rather than a state
    backstop, so folding it into the others would hide the one arm whose non-zero value means
    something went wrong upstream.

    ``faults`` counts arms that raised rather than answered. It is separate from the counts
    because zero-because-there-was-nothing-to-do and zero-because-the-arm-failed are the two
    readings an operator must never confuse, and a bare ``expired=0`` cannot tell them apart.
    """

    expired: int = 0
    timed_out: int = 0
    notified: int = 0
    faults: int = 0


def _require_container(ctx: Mapping[str, Any]) -> AppContainer:
    container = ctx.get(CONTAINER_CTX_KEY)
    if not isinstance(container, AppContainer):
        raise PipelineError(
            "worker context is missing a usable 'container'",
            context={"key": CONTAINER_CTX_KEY, "found": type(container).__name__},
        )
    return container


def _require_bot(ctx: Mapping[str, Any]) -> Bot:
    bot = ctx.get(BOT_CTX_KEY)
    if not isinstance(bot, Bot):
        raise PipelineError(
            "worker context is missing a usable 'bot'",
            context={"key": BOT_CTX_KEY, "found": type(bot).__name__},
        )
    return bot


def _attempt(ctx: Mapping[str, Any]) -> int:
    """Which attempt this is, counting from 1 the way ARQ does."""
    attempt = ctx.get("job_try", 1)
    return attempt if isinstance(attempt, int) and attempt > 0 else 1


def _retry_or_give_up(ctx: Mapping[str, Any], *, public_ref: str, reason: str) -> None:
    """Ask ARQ for another attempt, unless this was the last one it will honour.

    Raising ``Retry`` on the final permitted attempt is the same defect
    ``bayram.runtime.jobs._is_final_attempt`` exists to prevent: ARQ discards that retry BEFORE
    re-entering the function, so nothing runs, nothing is logged from inside the job, and the
    customer is never told. On the last attempt this logs at ERROR and returns, leaving
    ``notified_at`` NULL — which is exactly the state arm three of the sweep looks for, so the
    backlog catcher picks the intent up again five minutes later. **A notification this job
    gives up on is not lost; it is handed back to the backstop.**
    """
    attempt = _attempt(ctx)
    if attempt < PAYME_NOTIFY_MAX_TRIES:
        raise Retry(defer=PAYME_NOTIFY_BACKOFF_S * attempt)
    _LOG.error(
        "a settled payment could not be announced; the sweep will re-enqueue it",
        extra={
            "public_ref": public_ref,
            "reason": reason,
            "attempt": attempt,
            "max_tries": PAYME_NOTIFY_MAX_TRIES,
        },
    )


async def _announcement(
    container: AppContainer, intent: PaymentIntent, *, telegram_user_id: int, language: Language
) -> str | None:
    """The sentence to send, read from the LIVE meter — or ``None`` when it cannot be read.

    The numbers are read back rather than computed from the intent, because the intent records
    what was BOUGHT and the customer is about to be told what they now HAVE. Those differ by
    everything else on the account: a rolling allowance that has come due, a plan's unminted
    songs, a credit an operator granted while the payment was in flight. Telling somebody they
    have one song when the balance screen they tap next says four is a support ticket.

    ``None`` means the meter could not be read at all, which is a transient database
    condition and therefore a retry rather than a wrong number sent confidently.
    """
    if intent.product is Product.SINGLE:
        return await _single_song_sentence(container, telegram_user_id, language=language)
    return await _plan_sentence(container, intent, telegram_user_id, language=language)


async def _single_song_sentence(
    container: AppContainer, telegram_user_id: int, *, language: Language
) -> str | None:
    ledger = container.credits
    if ledger is None:
        # A container with no meter cannot have settled a payment in the first place; this is
        # a wiring bug and is named as one rather than silently rendering a zero.
        _LOG.error(
            "a settled payment cannot be announced because this worker has no credit ledger",
            extra={"telegram_user_id": telegram_user_id},
        )
        return None
    balance = await ledger.balance_for(telegram_user_id)
    if is_err(balance):
        _LOG.warning("the balance could not be read", extra=balance.error.to_log_dict())
        return None
    return translate(PAID_LATE_SINGLE_KEY, language, credits=balance.value.credits)


async def _plan_sentence(
    container: AppContainer,
    intent: PaymentIntent,
    telegram_user_id: int,
    *,
    language: Language,
) -> str | None:
    """The plan sentence, from the live plan row where there is one and the intent where not.

    The fallback is not defensive padding. ``plan_for`` returning ``None`` for an intent that
    is recorded as PAID means the receipt and the plan row disagree, which is a defect worth an
    ERROR line — but the customer's money is already ours and refusing to speak to them over an
    internal inconsistency is the worse of the two failures. The intent carries ``plan_songs``
    and ``plan_days`` as a SNAPSHOT taken when the link was built, precisely so a later config
    change cannot retro-shrink a plan somebody paid for, and that snapshot is what answers here.
    """
    store = container.purchases
    if store is None:
        _LOG.error(
            "a settled plan cannot be announced because this worker has no purchase ledger",
            extra={"telegram_user_id": telegram_user_id},
        )
        return None
    found = await store.plan_for(telegram_user_id)
    if is_err(found):
        _LOG.warning("the plan could not be read", extra=found.error.to_log_dict())
        return None
    plan: PlanState | None = found.value
    if plan is not None:
        return translate(
            PAID_LATE_PLAN_KEY,
            language,
            songs=plan.songs_left,
            ends_on=plan.ends_at.date().isoformat(),
        )
    _LOG.error(
        "a paid plan intent has no plan row; announcing it from the intent's own snapshot",
        extra={
            "public_ref": intent.public_ref,
            "plan_songs": intent.plan_songs,
            "plan_days": intent.plan_days,
        },
    )
    ends_on = _snapshot_end_date(intent)
    return translate(PAID_LATE_PLAN_KEY, language, songs=intent.plan_songs or 0, ends_on=ends_on)


def _snapshot_end_date(intent: PaymentIntent) -> str:
    """When the intent's own snapshot says the plan ends. Never raises, never guesses wildly.

    Measured from ``settled_at`` — the instant the plan actually started — and from
    ``valid_until`` only when the settlement clock is somehow absent, which cannot happen on a
    PAID row but is cheaper to answer than to assert about inside a customer message.
    """
    started = intent.settled_at or intent.valid_until
    return (started + timedelta(days=intent.plan_days or 0)).date().isoformat()


async def notify_payment_settled(ctx: Mapping[str, Any], public_ref: str) -> None:
    """Tell one customer that their redirect payment landed, and start the song. Enqueued by
    the GATEWAY.

    A job and not a direct send because the process that took the money holds no Telegram
    token — see the module docstring — and because the gateway owes Payme an answer in
    milliseconds, which a ``sendMessage`` round trip is not.

    **It does a SECOND thing now, and it is deliberately the same job rather than a sibling.**
    A settled payment starts the render it was opened for (``DECISIONS.md D17``,
    :mod:`bayram.runtime.render_resume`). "Make it a sibling job" is the obvious review
    comment and it is rejected on the one requirement the customer actually stated: they want
    the payment confirmation and THEN the song starting, and two ARQ jobs cannot order two
    messages. The resume runs LAST, below the stamp, so every retry path in this function
    returns above it and the notification's own ladder behaves exactly as it did before.

    The gateway is untouched by all of this. Its payload is still one string, it still holds no
    Telegram token, and it still cannot settle anything the bot could not.

    **Three silences, each of them correct.**

    * ``telegram_user_id`` is NULL. ``/forget`` ran between the payment and this job. Erasure
      anonymises the intent rather than deleting it (GetStatement must still be able to answer
      Payme about a transaction they can see in their own cabinet), so the row is still here
      and there is simply nobody to tell. Nothing is stamped, because stamping would claim a
      delivery that did not happen — and the backlog query filters this population out by
      itself, so an unstampable row does not become a job re-enqueued forever.
    * ``notified_at`` is already set. A redelivered job, or the sweep and the gateway both
      enqueuing before the deterministic id deduplicated them. Saying it twice is the one
      failure a customer notices.
    * The intent is not PAID. The only way to reach this is a rail that enqueued before its own
      commit, which the gateway is written not to do; it is logged at ERROR and left alone
      rather than announced, because announcing an unsettled payment is how a free song is
      given away.

    **All three silences are shared with the RENDER for free**, because ``_announceable_buyer``
    returns above everything the resume does. That is why this function was not split when the
    resume landed: an unsettled intent, an already-announced one and an erased buyer resume
    nothing by control flow rather than by new code that has to be right.

    A FOURTH decision belongs to the render alone and is not a silence: the customer may have
    no draft parked, or one that has moved since they paid, or one they are still editing. See
    :class:`~bayram.runtime.render_resume.ResumeDecision` for the closed vocabulary that says
    which, and ``06-troubleshooting.md`` §20.4 for reading it back.

    **Send first, stamp second, and the order is deliberate.** Stamping first would make a
    failed send permanent — ``notified_at`` set, the backlog query blind to the row, the
    customer silent forever. Sending first risks a duplicate message if the stamp then fails,
    and a duplicate "your payment went through" is a nuisance where a missing one is an
    incident.
    """
    container = _require_container(ctx)
    bot = _require_bot(ctx)
    ledger = build_worker_payme_ledger(container)

    found = await ledger.intent(public_ref=public_ref)
    if is_err(found):
        _LOG.warning("the settled intent could not be read", extra=found.error.to_log_dict())
        _retry_or_give_up(ctx, public_ref=public_ref, reason="intent_unreadable")
        return
    intent = found.value
    if intent is None:
        # Not retryable and not an error worth a page: an id that names nothing is a stale
        # enqueue, and five more attempts will find the same nothing.
        _LOG.error("no payment intent answers this reference", extra={"public_ref": public_ref})
        return
    telegram_user_id = _announceable_buyer(intent)
    if telegram_user_id is None:
        return

    language = parse_language(intent.language)
    # A PURE READ, and it runs before the sentence is chosen precisely so the sentence can be
    # chosen from it: a customer whose song is about to start must not be told they have one
    # song ready, and a customer whose render was declined must not be handed a button that
    # throws away the draft they just paid for. One read answers both.
    assessment = await plan_resume(ctx, container, bot=bot, intent=intent)
    if assessment.plan is not None:
        text: str | None = translate(PAID_LATE_RESUMING_KEY, language)
    else:
        text = await _announcement(
            container, intent, telegram_user_id=telegram_user_id, language=language
        )
    if text is None:
        _retry_or_give_up(ctx, public_ref=public_ref, reason="meter_unreadable")
        return

    is_sent = await _send(
        bot,
        ledger,
        ctx,
        chat_id=telegram_user_id,
        text=text,
        public_ref=public_ref,
        markup=_announcement_keyboard(assessment, language),
    )
    if not is_sent:
        # **A blocked customer resumes NOTHING, and this ``return`` is where that is
        # decided.** ``_send`` has already stamped ``notified_at`` for a chat nobody can
        # reach. Rendering for them anyway would spend the credit they paid for on a kit that
        # provably cannot arrive — ``entitlements`` settles NOT_DELIVERED exactly as it
        # settles DELIVERED — so "they paid, render it anyway" is rejected outright.
        return
    stamped = await ledger.mark_notified(public_ref=public_ref, now=utc_now())
    if is_err(stamped):
        # The customer HAS been told. Retrying would tell them again, so this failure is
        # recorded and dropped: the worst outcome is one duplicate on the next sweep, and the
        # alternative — raising — guarantees it.
        _LOG.error("the notification was sent but not stamped", extra=stamped.error.to_log_dict())
        return
    _LOG.info(
        "a settled payment was announced",
        extra={
            "public_ref": public_ref,
            "product": intent.product.value,
            "language": intent.language,
            "is_first_stamp": stamped.value,
        },
    )
    # LAST, and after the stamp, so that nothing about the render can cost the customer their
    # notification: every retry path above returns before this line, and the ladder behaves
    # exactly as it did before the resume existed.
    decision = (
        await resume_render(ctx, bot, ledger, container, intent=intent, plan=assessment.plan)
        if assessment.plan is not None
        # A decline that ``plan_resume`` already made. It is reported through the SAME line and
        # the same vocabulary as a decline made while acting, so an operator reading the log
        # cannot tell — and does not need to tell — which of the two passes noticed.
        else ResumeDecision(False, assessment.reason)
    )
    # **Logged unconditionally, and that is the correction to how this first shipped.** The
    # line used to sit inside the ``if`` above, so it fired only when a render was actually
    # attempted — which is to say it was silent for every case an operator would ever be
    # asked about. "The customer paid and no song started" was answered by a log line that
    # only existed when a song HAD started. One line per settled payment is nothing: a
    # settlement is money, and there are never many.
    _LOG.info(
        "the settled payment's render was considered",
        extra={
            "public_ref": public_ref,
            "is_queued": decision.is_queued,
            # The closed vocabulary on ``ResumeDecision``. This field is the operator's
            # whole answer to "the customer paid and no song started; why?".
            "reason": decision.reason,
            "order_id": decision.order_id or "",
        },
    )


def _announcement_keyboard(
    assessment: ResumeAssessment, language: Language
) -> InlineKeyboardMarkup | None:
    """Which keyboard belongs under "your payment landed". Three answers, not one.

    * **About to resume — no keyboard at all.** The progress frame lands a second later, and
      🔄 Start over over a running render is a button ``navigation._refuse_while_running``
      would refuse anyway.
    * **Declined, but a usable draft is sitting there** — ``paid_late_keyboard``: a live 🎬 on
      the draft they paid for. This covers the customer who edited after paying, the one who
      already has a render in flight, and — importantly — the one who bought from
      ``/balance``, where no marker is ever minted. They get one tap instead of none, and
      without this module having to guess which run their money belonged to.
    * **Nothing to point at** — ``start_over_keyboard``, which is correct HERE and was wrong
      everywhere else: it is the right offer for somebody whose session is genuinely gone.

    ``start_over_keyboard``'s ↩️ reaches ``common.reset_to_welcome`` ("a clean slate, every
    time"), so until this function existed the only prominent button under a 15 000 soʻm
    receipt destroyed the draft it was paid for. That was a live defect, independent of the
    auto-render, and it is what ``_send``'s old argument for that keyboard did not foresee.
    """
    if assessment.plan is not None:
        return None
    if assessment.has_live_draft:
        return paid_late_keyboard(language)
    return start_over_keyboard(language)


def _announceable_buyer(intent: PaymentIntent) -> int | None:
    """Who to tell, or ``None`` and the reason why nobody. The three silences, in one place.

    Returns the chat id rather than a boolean so the caller needs no narrowing assertion for a
    field this function has already had to inspect. In a private chat — the only kind this bot
    has — the customer's Telegram user id IS the chat id, which is why ``payment_intents``
    stores one number and not two.
    """
    if intent.state is not PaymentIntentState.PAID:
        _LOG.error(
            "refusing to announce a payment that is not settled",
            extra={"public_ref": intent.public_ref, "state": intent.state.value},
        )
        return None
    if intent.notified_at is not None:
        _LOG.info(
            "a settled payment had already been announced; sending nothing",
            extra={"public_ref": intent.public_ref},
        )
        return None
    if intent.telegram_user_id is None:
        _LOG.info(
            "a settled payment has no one to tell; the account was erased",
            extra={"public_ref": intent.public_ref},
        )
        return None
    return intent.telegram_user_id


async def _send(
    bot: Bot,
    ledger: PaymeLedger,
    ctx: Mapping[str, Any],
    *,
    chat_id: int,
    text: str,
    public_ref: str,
    markup: InlineKeyboardMarkup | None,
) -> bool:
    """Put the sentence in the chat. ``True`` when it landed and the stamp should follow.

    **The keyboard is CHOSEN by the caller now, and the argument this docstring used to make
    for a fixed one is spent.** It said that ``start_over_keyboard`` was right because a cold
    message with no control is a dead end on a phone, and that reusing it kept this workstream
    out of ``keyboards.py`` — a module whose builders are covered by a hand-listed register
    test. The first half is still true; the second was a reason to avoid work rather than a
    reason the button was correct, and the button was not correct: ↩️ Start over reaches
    ``common.reset_to_welcome``, which threw away the draft the customer had just paid to
    record. ``keyboards.py`` therefore does grow one builder, and that builder IS added to the
    register test. See :func:`_announcement_keyboard` for the three cases.

    ``None`` is a legitimate value and means "a progress frame is about to land underneath
    this"; it is not "no keyboard was chosen".

    **A ``Forbidden`` is stamped as delivered, and that is the interesting decision here.**
    Telegram returns it for a customer who blocked the bot and for an account that was deleted;
    neither will ever receive this message. Leaving ``notified_at`` NULL for them would put a
    permanently undeliverable row into the backlog query and re-enqueue this job every five
    minutes for the life of the deployment — one blocked customer becoming an unbounded source
    of work and log noise. ``notified_at`` therefore means "everything that could be done to
    tell them was done", which is the only meaning that stays true for a chat that cannot be
    reached. The classification comes from
    :func:`bayram.bot.delivery.is_blocked_by_customer` so that a block and a deleted account are
    told apart in the log line rather than by reading an exception's ``str``.
    """
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
    except TelegramForbiddenError as exc:
        _LOG.warning(
            "a settled payment could not be announced; the chat is unreachable",
            extra={
                "public_ref": public_ref,
                "chat_id": chat_id,
                "is_blocked_by_customer": is_blocked_by_customer(exc),
                "failure": repr(exc),
            },
        )
        await _stamp_unreachable(ledger, public_ref=public_ref)
        return False
    except TelegramAPIError as exc:
        _LOG.warning(
            "the settled-payment message did not send",
            extra={"public_ref": public_ref, "chat_id": chat_id, "failure": repr(exc)},
        )
        _retry_or_give_up(ctx, public_ref=public_ref, reason="telegram_error")
        return False
    return True


async def _stamp_unreachable(ledger: PaymeLedger, *, public_ref: str) -> None:
    """Close the backlog row for a chat nobody can reach. Never raises; see :func:`_send`."""
    stamped = await ledger.mark_notified(public_ref=public_ref, now=utc_now())
    if is_err(stamped):
        _LOG.error(
            "an unreachable customer's intent could not be stamped",
            extra=stamped.error.to_log_dict(),
        )


async def run_payme_sweep(ctx: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """The four backstop arms, in order. ``max_tries=1``: the NEXT run is the retry.

    ``now`` is injectable for the reason every clock in this repository is: a test advances
    thirteen hours rather than waiting for them.

    Arms one and two are STATE backstops and nothing's correctness depends on them — every
    inbound request already evaluates the same predicates. Arm three is the DELIVERY backstop
    and is the reason this cron exists at all. Arm four writes nothing anywhere, ever.

    Each arm is independent: a failure in one is counted and the others still run. Arm four in
    particular is a diagnostic, and letting a reconciliation query take the two state arms down
    with it would be the tail wagging the dog.

    Returns a JSON-safe summary, which ARQ stores as the job result. The plan for this
    workstream said ``None``; every other cron in this worker returns a summary and an operator
    reading ``arq`` results should not find this one blank.
    """
    container = _require_container(ctx)
    ledger = build_worker_payme_ledger(container)
    at = now or utc_now()
    started = time.monotonic()

    expired, faults = await _count_arm(
        ledger.expire_lapsed(now=at, limit=PAYME_SWEEP_BATCH_SIZE), arm="expire_lapsed"
    )
    timed_out, timeout_faults = await _count_arm(
        ledger.expire_stale_transactions(now=at, limit=PAYME_SWEEP_BATCH_SIZE),
        arm="expire_stale_transactions",
    )
    notified, notify_faults = await _re_enqueue_notifications(ctx, ledger, now=at)
    invariant_faults = await _reconcile(container, ledger, now=at)

    report = SweepReport(
        expired=expired,
        timed_out=timed_out,
        notified=notified,
        faults=faults + timeout_faults + notify_faults + invariant_faults,
    )
    summary: dict[str, Any] = {
        "intents_expired": report.expired,
        "transactions_timed_out": report.timed_out,
        "notifications_re_enqueued": report.notified,
        "faults": report.faults,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    _LOG.info("payme sweep finished", extra=summary)
    return summary


async def _count_arm(awaitable: Awaitable[Result[int]], *, arm: str) -> tuple[int, int]:
    """Run one counting arm and report ``(rows, faults)``. Never raises.

    Both arms it serves return ``Result[int]`` through ``run_guarded``, so a database failure
    arrives as data. It is unpacked here rather than at each call site so that the two arms
    cannot come to disagree about what a failure means.
    """
    outcome = await awaitable
    if is_err(outcome):
        _LOG.error("a payme sweep arm failed", extra={"arm": arm, **outcome.error.to_log_dict()})
        return 0, 1
    counted: int = outcome.value
    return counted, 0


async def _re_enqueue_notifications(
    ctx: Mapping[str, Any], ledger: PaymeLedger, *, now: datetime
) -> tuple[int, int]:
    """ARM THREE — the only arm here that is about DELIVERY rather than about state.

    The gateway's post-commit enqueue is best-effort and must stay that way: Payme is owed an
    HTTP 200 whether or not Redis answered, and a settlement that rolled back because a queue
    was unreachable would be a customer charged with no credit. This arm is what makes that
    trade honest — every paid intent nobody has been told about, older than the grace window,
    gets a job. The deterministic id means a re-enqueue while the original job is still queued
    is a no-op rather than a second message.

    A missing or unreachable Redis is logged and counted, never raised: this arm compensates
    for exactly that outage, and taking the sweep down over it would remove the compensation at
    the moment it is needed.
    """
    cutoff = now - timedelta(seconds=PAYME_NOTIFY_GRACE_S)
    pending = await ledger.pending_notifications(older_than=cutoff, limit=PAYME_SWEEP_BATCH_SIZE)
    if is_err(pending):
        _LOG.error(
            "the notification backlog could not be read",
            extra={"arm": "pending_notifications", **pending.error.to_log_dict()},
        )
        return 0, 1

    intents = pending.value
    if not intents:
        return 0, 0
    redis = ctx.get(REDIS_CTX_KEY)
    enqueue = getattr(redis, "enqueue_job", None)
    if enqueue is None:
        _LOG.error(
            "settled payments are waiting to be announced and this worker has no queue handle",
            extra={"waiting": len(intents)},
        )
        return 0, 1

    queued = 0
    faults = 0
    for intent in intents:
        try:
            await enqueue(
                PAYME_NOTIFY_JOB_NAME,
                intent.public_ref,
                _job_id=payme_notify_job_id(intent.public_ref),
            )
        except (TimeoutError, OSError) as exc:
            # One unreachable enqueue must not strand the other hundred and ninety-nine, and
            # the next run five minutes from now is the retry.
            faults += 1
            _LOG.error(
                "a settled payment could not be re-enqueued for announcement",
                extra={"public_ref": intent.public_ref, "failure": repr(exc)},
            )
            continue
        queued += 1
    _LOG.warning(
        "settled payments were re-enqueued by the backstop rather than at settlement",
        extra={"re_enqueued": queued, "faults": faults, "waiting": len(intents)},
    )
    return queued, faults


async def _reconcile(container: AppContainer, ledger: PaymeLedger, *, now: datetime) -> int:
    """ARM FOUR — the three-way settlement invariant, plus the balance check. Repairs NOTHING.

    **The identity, stated precisely, because "three-way invariant" is not something anyone can
    act on.** ``transactions_performed`` and ``receipts_written`` are written in the SAME commit
    from the SAME clock read, so there is no window in which one has landed and the other has
    not; a difference is a defect and never a race. ``grants_written`` is the single-song SUBSET
    of the receipts by construction — a plan settlement writes a ``plan_purchases`` row and
    grants no credit at all, because plan songs are minted lazily — so asserting three-way
    EQUALITY would report an incident every time somebody bought a plan. What is asserted is
    ``performed == receipts`` and ``grants <= receipts``.

    **The two directions of a mismatch mean different things and are logged as such.**

    * ``performed > receipts`` is the bad one: a payment we told Payme we had taken produced no
      sale row. That is the failure mode the newly shared write primitive could introduce, and
      it is the reason this arm exists. The detail scan below names the transactions.
    * ``receipts > performed`` has one benign cause and it is worth knowing before paging
      anybody: an operator force-settle writes the sale under the intent's own key without any
      performed transaction behind it, and stays visible in this window for a day.
      ``python -m bayram.payme.cli journal --ref <ref>`` shows the ``settle_note`` that says so.

    ``verify_balances`` runs HERE — in the worker, on a schedule — and never inside a JSON-RPC
    request that owes Payme an answer in milliseconds. It is the check that keeps the
    two-representation trade-off in ``credit_accounts.balance`` honest, and it takes no lock
    and writes nothing.

    Nothing in this function repairs anything. A counter that corrected itself would erase the
    only evidence that the write primitive had drifted, and the correction would be a credit
    grant written by a scheduler on a guess.
    """
    frm = now - timedelta(hours=PAYME_INVARIANT_WINDOW_HOURS)
    faults = 0
    counted = await ledger.settlement_counts(frm=frm, to=now)
    if is_err(counted):
        _LOG.error(
            "the settlement invariant could not be computed",
            extra={"arm": "settlement_counts", **counted.error.to_log_dict()},
        )
        faults += 1
    else:
        faults += await _report_counts(ledger, counted.value, frm=frm, to=now)
    return faults + await _report_balance_drift(container)


async def _report_counts(
    ledger: PaymeLedger, counts: SettlementCounts, *, frm: datetime, to: datetime
) -> int:
    """Compare the three numbers and say what a difference means. Writes nothing."""
    numbers = {
        "window_from": frm.isoformat(),
        "window_to": to.isoformat(),
        "transactions_performed": counts.transactions_performed,
        "receipts_written": counts.receipts_written,
        "grants_written": counts.grants_written,
    }
    if counts.transactions_performed > counts.receipts_written:
        _LOG.error(
            "a performed payme transaction produced no sale row; nothing has been repaired",
            extra=numbers,
        )
        await _name_the_orphans(ledger, frm=frm, to=to)
        return 1
    if counts.receipts_written > counts.transactions_performed:
        _LOG.error(
            "more payme sale rows than performed transactions; an operator force-settle is the "
            "one benign cause and carries a settle_note that says so",
            extra=numbers,
        )
        return 1
    if counts.grants_written > counts.receipts_written:
        _LOG.error(
            "more credit grants than payme sale rows; nothing has been repaired", extra=numbers
        )
        return 1
    _LOG.info("the payme settlement invariant holds", extra=numbers)
    return 0


async def _name_the_orphans(ledger: PaymeLedger, *, frm: datetime, to: datetime) -> None:
    """Name the performed transactions whose intents are not PAID. Runs only on a mismatch.

    Bounded, and deliberately not run on the healthy path: this is a per-transaction read and
    the counts above already answer "is anything wrong" in one query. It exists so that the
    ERROR line an operator wakes up to carries references they can put straight into
    ``python -m bayram.payme.cli journal``, rather than three numbers and a database prompt.
    """
    statement = await ledger.statement(frm=frm, to=to)
    if is_err(statement):
        _LOG.error("the mismatched window could not be listed", extra=statement.error.to_log_dict())
        return
    scanned = 0
    for row in statement.value:
        if row.transaction.state is not PaymeState.PERFORMED:
            continue
        if scanned >= PAYME_ORPHAN_SCAN_LIMIT:
            _LOG.error(
                "the orphan scan hit its bound; run the operator CLI for the full window",
                extra={"limit": PAYME_ORPHAN_SCAN_LIMIT},
            )
            return
        scanned += 1
        found = await ledger.intent(public_ref=row.transaction.intent_public_ref)
        if is_err(found) or found.value is None:
            _LOG.error(
                "a performed payme transaction has no intent behind it",
                extra={
                    "payme_transaction_id": row.transaction.payme_transaction_id,
                    "public_ref": row.transaction.intent_public_ref,
                },
            )
            continue
        if found.value.state is not PaymentIntentState.PAID:
            _LOG.error(
                "a performed payme transaction holds an intent that is not paid; not repaired",
                extra={
                    "payme_transaction_id": row.transaction.payme_transaction_id,
                    "public_ref": found.value.public_ref,
                    "intent_state": found.value.state.value,
                },
            )


async def _report_balance_drift(container: AppContainer) -> int:
    """Log every account whose stored balance disagrees with its ledger. Repairs nothing.

    The one call in this module that reaches past the rail's own tables, and the only one
    wrapped in a bare ``except``: ``verify_balances`` is raw SQL rather than a ``Result``-
    returning seam, and a reconciliation query must never take the two state arms down with it.
    """
    try:
        async with container.require_session_factory()() as session:
            drifts = await verify_balances(session)
    except Exception as exc:
        _LOG.error(
            "the credit balance check could not be run", extra={"failure": repr(exc)}, exc_info=exc
        )
        return 1
    if not drifts:
        return 0
    for drift in drifts:
        _LOG.error(
            "a credit balance disagrees with its ledger; nothing has been repaired",
            extra={
                "telegram_user_id": drift.telegram_user_id,
                "balance": drift.balance,
                "ledger_total": drift.ledger_total,
            },
        )
    return 1


assert notify_payment_settled.__name__ == PAYME_NOTIFY_JOB_NAME, (
    "the gateway's enqueue name and the job function have drifted apart; ARQ would never "
    "dispatch, and a paying customer would never be told"
)
assert run_payme_sweep.__name__ == PAYME_SWEEP_JOB_NAME, (
    "the registered name and the sweep function have drifted apart; ARQ would never dispatch"
)
