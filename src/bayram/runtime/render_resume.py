"""Start the song a settled redirect payment was made for. Plan, claim, act — in that order.

**The problem this solves.** On an inline rail the customer pays and is looking at the
screen, so "pay, then press 🎬" is two taps in one sitting. On a redirect rail they leave
Telegram for a payment page, and settlement arrives minutes or hours later at a different
process. The bot used to answer that by announcing the payment and leaving a button, which
means a customer who paid and closed the app came back to a song that had never started. This
module is the other half: when the money lands, the render the customer was paying for
begins, and the first thing they see is a progress frame rather than a chore.

That reverses a decision this repository wrote down — see ``handlers.checkout``'s module
docstring, whose "paying does NOT queue a render" paragraph was amended rather than deleted,
because half of it is still true — so it is reversed behind
``BAYRAM_AUTO_RENDER_ON_PAYMENT``, whose false value restores the old behaviour exactly, with
a restart and no deploy. ``DECISIONS.md D17``.

WHY THE MARKER IS ON THE INTENT
-------------------------------
The bot records ``payment_intents.resume_order_id`` when it builds the link: the UUID5
:func:`bayram.bot.order_id.order_id_for` takes over the customer's own answers. One value does
three jobs at once, which is the whole reason this design is short:

* it is the ADDRESS of the render — the ``orders`` primary key and the seed of
  ``pipeline.worker.job_id_for`` — so nothing here needs an identity scheme of its own;
* it is the PROOF the draft has not moved. The fingerprint covers every field of
  ``WizardDraft``, the approved lyric and ``session_id`` included, so recomputing it from
  whatever draft is parked now and comparing is a complete answer to "is this still the song
  they paid for?";
* it is EXACTLY-ONCE against the customer's own thumb. A 🎬 press racing this job computes
  the same value, so the ``orders`` primary key, the ARQ job id and ``credits.charge``'s
  already-paid probe all collide on it. Two attempts, one song.

The honest counter-argument, recorded rather than left for a reviewer to raise: the draft
itself lives in Redis either way, so putting the marker in Postgres buys no extra durability
for the customer. What it buys is an operator answer — "which render did this payment expect,
and did anything start it?" is two columns rather than an archaeology of logs — and a claim
that survives a Redis flush. A cheaper variant that kept a ticket in FSM data was considered
and rejected on those two grounds alone; it is named in D17 so the judgement stays visible.

WHY THE ORDER ID AND NOT ``session_id``, OR THE IDEMPOTENCY KEY
---------------------------------------------------------------
``idempotency_key`` already carries the ``session_id`` — it is spelled
``topup:{tg}:{session}:{seq}`` — so parsing one out of the other would have needed no schema
change at all. It was rejected because a session id is a TOKEN, not an address: it says which
run the money belongs to and nothing whatever about whether the answers in that run are still
the answers that were paid for. The customer who edits their note after paying is not a
hypothetical; they are the ordinary case this must decline, and only a fingerprint can see
them.

CLAIM BEFORE ACT, PARK AFTER SUBMIT
-----------------------------------
``payme_jobs.notify_payment_settled`` is at-least-once by construction: five ARQ attempts, the
sweep's third arm as a backstop, and two processes that enqueue the same job name. A side
effect placed in that job with no latch of its own therefore fires once per attempt — and
this side effect bills a vendor and delivers a song.

So the claim (:meth:`bayram.payme.ports.PaymeLedger.claim_resume`) is taken before every
SIDE EFFECT — before the progress message and before the enqueue. Claim-then-act is
at-most-once; act-then-claim is at-least-once. Exactly one thing runs ahead of it, the
queue-handle check, and only because it is a local read of a dict that touches nothing: a
worker wired without a queue would otherwise burn the one resume attempt on a wiring fault
that a correctly wired attempt could still have served.

**The cost of choosing at-most-once is stated plainly: a process that dies
between the claim and the enqueue renders nothing, permanently, with no automated recovery.**
That customer is left exactly where this product left every customer yesterday — told they
have a song, one 🎬 press away — which is why it is the right direction to fail in. The
opposite failure is a second vendor bill and a second delivered kit: ``credits.charge``
short-circuits on its ``ALREADY_PAID`` probe for the same order id, so a duplicate keyed on
that id cannot double-DEBIT, but ``jobs.py`` already records that a replay past the latches
"finds the order still paid for and renders it again".

The park is the mirror image: the FSM is written AFTER the submit, copying
``handlers.confirm._queue``, so that ``jobs._release_session``'s order-id comparison finds the
id it expects. A park that never happened leaves the customer behind
``navigation._refuse_while_running`` for a song that has already arrived.

WHY NOT SYNTHESISE AN UPDATE AND LET THE REAL HANDLER RUN
----------------------------------------------------------
This is the first thing a reviewer proposes, and it is worth four sentences because it sounds
much safer than it is:

1. the worker has no dispatcher. Building one duplicates the bot's entire composition root in
   a second process;
2. a fabricated ``callback_query.id`` earns ``QUERY_ID_INVALID`` at ``handle_confirm``'s
   second await — which sits outside any ``try``/``finally`` — stranding the session in
   ``Wizard.submitting`` with no ``ORDER_ID_KEY``, which is the un-leaveable state
   ``_release_session`` exists to prevent;
3. ``callback.message`` has to be a real message anyway, so the progress frame would have to
   be sent first regardless;
4. **decisively: aiogram's event isolation lock is per-dispatcher and in-process.** A second
   dispatcher in the worker would hold a DIFFERENT lock over the SAME Redis FSM key, so a
   real tap and a synthesised one could both read ``Wizard:confirm`` and both proceed. That is
   a second charge, not a flaky test.

Hence the direct, compare-and-write storage access below — which is the same discipline
``jobs._release_session`` has used since it shipped, and carries the same known weakness: no
per-chat lock. It is narrow and it is real, and it cannot be closed without moving this work
back into the bot process.

WHICH OF ``handle_confirm``'s GATES SURVIVE
--------------------------------------------
Written as a table because "did the resume skip the lyric gate?" is the question a reviewer
must be able to answer without reading two files:

=== ====================================== ==========================================
#   ``handle_confirm`` gate                 Under resume
=== ====================================== ==========================================
1   inbound gate / throttle                 bypassed — replaced by the claim + marker
2   onboarding gate                         bypassed — irrelevant to money already banked
3   state filter + per-chat lock            NOT held — compare-and-write only (above)
4   ``Wizard.submitting`` flip              replaced by the claim
5   draft present                           checked (plan step 6, re-checked act step 1)
6   brief completeness                      checked at link time AND at plan step 7
7   **lyric approved**                      checked at link time; RE-VERIFIED by the
                                            order-id equality, since the fingerprint
                                            covers ``lyrics``. The worst one, closed exactly
8   blocked / in-flight / balance           re-run worker-side by ``credits.charge``
9   paywall second line                     N/A — the payment IS the paywall satisfied
10  ``deps.payment.authorize``              the bot's is a no-op; the worker's gate still runs
11  progress message before submit          reproduced (act step 3)
12  deterministic order id                  PINNED at pay time — stronger than reproduced
13  FSM parked                              reproduced (act step 6)
--  moderation                              unchanged; runs in the pipeline at its own stage
=== ====================================== ==========================================
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from bayram.bot.draft import load_draft
from bayram.bot.handlers.submitting import ORDER_ID_KEY, PROGRESS_MESSAGE_ID_KEY
from bayram.bot.order_id import order_id_for
from bayram.bot.progress import queued_text
from bayram.bot.states import Wizard
from bayram.checkout import PaymentIntent
from bayram.contracts import Err, Language, Order, OrderState, is_err
from bayram.db.base import utc_now
from bayram.logging import correlation_scope, current_correlation_id, get_logger, new_correlation_id
from bayram.payme.ports import PaymeLedger
from bayram.runtime.container import AppContainer
from bayram.runtime.submitter import ArqOrderSubmitter

__all__ = ["ResumeAssessment", "ResumeDecision", "ResumePlan", "plan_resume", "resume_render"]

_LOG = get_logger(__name__)

#: Restated rather than imported from :mod:`bayram.runtime.jobs`, which imports
#: :mod:`bayram.runtime.payme_jobs`, which imports this module — the same cycle-avoidance
#: ``payme_jobs`` documents for its own copies of these two names. A drift would be caught by
#: the ctx-key tests in ``tests/test_runtime/test_wiring.py``, which assert the literals.
STORAGE_CTX_KEY: Final[str] = "fsm_storage"
REDIS_CTX_KEY: Final[str] = "redis"


@dataclass(frozen=True, slots=True)
class ResumeDecision:
    """What the settlement decided about the render, and WHY. Never raises.

    ``reason`` is a closed vocabulary rather than free text, and that is what turns "grep the
    job's log lines and guess which of the checks declined" into a queryable field. It is the
    operator's answer to the only question this feature generates — "the customer paid and
    says no song started; what happened?" — and it is the reason the plan/act split below
    returns a reason even when it returns no plan.

    The vocabulary:

    ``queued``
        A render was started. The only value for which ``order_id`` is not ``None``.
    ``disabled``
        ``BAYRAM_AUTO_RENDER_ON_PAYMENT`` is false. Nothing was read.
    ``no_marker``
        The intent carries no ``resume_order_id``: bought from ``/balance``, opened against a
        draft that could not render, or opened before revision 0026.
    ``no_storage``
        The worker has no FSM storage handle, or reading it failed. Degrades the way
        ``jobs._release_session`` degrades.
    ``no_draft``
        No draft is parked, or it is unreadable, incomplete, or has no approved lyric.
    ``draft_moved``
        A draft is parked and it is NOT the one that was paid for.
    ``not_on_confirm``
        The customer is mid-wizard somewhere else. Resuming would hijack the screen they are
        looking at rather than the one they left.
    ``already_queued``
        The session is already parked on a render — the customer pressed 🎬 themselves, or an
        earlier attempt resumed.
    ``order_exists``
        An ``orders`` row already holds this id.
    ``already_claimed``
        Another run of this job took the claim. The ordinary answer to a redelivery.
    ``no_progress_message``
        Telegram refused the progress frame, so nothing was enqueued.
    ``no_queue``
        The worker has no queue handle.
    ``enqueue_failed``
        The claim or the submit reported an error.
    """

    is_queued: bool
    reason: str
    order_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResumePlan:
    """Everything :func:`resume_render` needs, gathered by a read that wrote nothing.

    Split out so the ANNOUNCEMENT can be chosen before it is sent: the customer whose song is
    about to start reads a different sentence, under a different keyboard, from the one whose
    draft moved — and both decisions are made from this one read rather than from a second
    trip to storage.
    """

    order: Order
    name: str | None
    language: Language
    storage: BaseStorage
    key: StorageKey


@dataclass(frozen=True, slots=True)
class ResumeAssessment:
    """What one pure read of the session established. Two questions, one trip to storage.

    ``plan`` answers "may a render start?" and ``has_live_draft`` answers "is there a draft
    worth pointing a button at?", and they are genuinely different questions: the customer who
    bought from ``/balance`` has no marker and can never be resumed, but may well have a
    finished draft parked one screen back — and the right thing to put under their receipt is
    a live 🎬, not a button that throws that draft away.

    Both are decided here, before anything is sent, so the announcement's sentence and its
    keyboard are chosen from the same read rather than from two that could disagree.
    """

    plan: ResumePlan | None
    reason: str
    #: A complete, lyric-approved draft is parked at ``Wizard.confirm`` with no render in
    #: flight — i.e. one press of 🎬 would start a song. True on the resume path too.
    has_live_draft: bool


async def plan_resume(
    ctx: Mapping[str, Any], container: AppContainer, *, bot: Bot, intent: PaymentIntent
) -> ResumeAssessment:
    """Decide whether this settlement may start a render. **Writes nothing, anywhere.**

    The purity is load-bearing rather than tidy: this runs BEFORE the payment announcement is
    composed, so that the announcement can say "I'm starting your song now" only when that is
    true, and so that a decline can put a live 🎬 under the receipt instead of a button that
    throws the draft away. A read that wrote would have to be undone when the send then failed.

    **The session is read even when no render can possibly start** — no marker, or the flag
    off — because ``has_live_draft`` is needed either way, and one extra Redis GET on a path
    that has just taken somebody's money is not a cost worth optimising. It is what covers the
    ``/balance`` purchase without minting a marker on that surface.

    Two of the checks look redundant and are not; see steps 4 and 5.
    """
    telegram_user_id = intent.telegram_user_id
    if telegram_user_id is None:
        # Unreachable in practice — ``_announceable_buyer`` returns above this — but the type
        # says it can be ``None`` after erasure, and a resume for nobody is not a thing.
        return ResumeAssessment(None, "no_marker", has_live_draft=False)

    storage = ctx.get(STORAGE_CTX_KEY)
    if not isinstance(storage, BaseStorage):
        _LOG.warning(
            "no FSM storage in the worker context; a paid render cannot be resumed",
            extra={"public_ref": intent.public_ref},
        )
        return ResumeAssessment(None, "no_storage", has_live_draft=False)
    # In a private chat — the only kind this bot has — the customer's user id IS the chat id,
    # which is why ``payment_intents`` stores one number and not two.
    key = StorageKey(bot_id=bot.id, chat_id=telegram_user_id, user_id=telegram_user_id)
    try:
        data = await storage.get_data(key)
        parked_state = await storage.get_state(key)
    except Exception as exc:
        # Deliberately broad, and deliberately NOT re-raised. Raising here would put the job
        # back on ARQ's retry ladder, and every attempt on that ladder RE-SENDS the payment
        # announcement — so a storage blip would cost the customer three copies of "your
        # payment landed" to buy back a render they can still start with one tap.
        _LOG.warning(
            "the wizard session could not be read; a paid render will not be resumed",
            extra={"public_ref": intent.public_ref, "failure": repr(exc)},
        )
        return ResumeAssessment(None, "no_storage", has_live_draft=False)

    # 1. A render is already in flight for this session — the customer pressed 🎬 themselves
    #    while the payment was settling, or an earlier attempt of this job resumed it. Touch
    #    nothing at all: the park belongs to that order.
    if data.get(ORDER_ID_KEY) is not None:
        return ResumeAssessment(None, "already_queued", has_live_draft=False)
    # 2. **A POSITIVE check, and not merely the negative one above.** A customer sitting on
    #    the lyrics screen with an as-yet-unedited draft fingerprints EQUAL to what was paid
    #    for, so the comparison below would wave them through and this job would yank them
    #    into ``Wizard.submitting`` in the middle of an edit. This is the line between
    #    resuming the screen they LEFT and hijacking the screen they are ON.
    if parked_state != Wizard.confirm.state:
        return ResumeAssessment(None, "not_on_confirm", has_live_draft=False)
    # 3. The draft itself, re-checked even though ``checkout._resumable_order_id`` checked
    #    both halves at link time: that was a different read of a draft that has had hours to
    #    change. The lyric half is the one that matters — the pipeline writes its own words
    #    when the draft carries none, and delivers them.
    loaded = load_draft(data)
    if isinstance(loaded, Err):
        return ResumeAssessment(None, "no_draft", has_live_draft=False)
    draft = loaded.value
    brief = draft.to_brief()
    if isinstance(brief, Err) or draft.lyrics is None:
        return ResumeAssessment(None, "no_draft", has_live_draft=False)

    # From here on a press of 🎬 would start a song, whatever this function decides about
    # starting one itself.
    if not container.settings.auto_render_on_payment:
        return ResumeAssessment(None, "disabled", has_live_draft=True)
    if intent.resume_order_id is None:
        # The ``/balance`` surface, a draft that could not render when the link was built, or
        # an intent opened before the marker column existed. Not a fault: on a deployment that
        # sells from ``/balance`` this is most settlements.
        return ResumeAssessment(None, "no_marker", has_live_draft=True)
    # 4. The customer edited something after paying. ONE equality closes ``handle_confirm``'s
    #    gates 6, 7 and 12 at once, because the fingerprint covers every field of the draft —
    #    so this is also what stops a payment made for one wizard run resuming a later one.
    if order_id_for(telegram_user_id, draft) != intent.resume_order_id:
        _LOG.info(
            "the parked draft is not the one this payment was opened for; not resuming",
            extra={"public_ref": intent.public_ref},
        )
        return ResumeAssessment(None, "draft_moved", has_live_draft=True)
    # 5. Read explicitly rather than sniffing ``create_order``'s IntegrityError, so that
    #    "this render already exists" never reaches an operator dressed as a storage fault.
    existing = await container.repository.get_order(intent.resume_order_id)
    if not is_err(existing):
        return ResumeAssessment(None, "order_exists", has_live_draft=True)

    now = utc_now()
    recipient = brief.value.recipient
    return ResumeAssessment(
        ResumePlan(
            order=Order(
                id=intent.resume_order_id,
                telegram_user_id=telegram_user_id,
                brief=brief.value,
                state=OrderState.DRAFT,
                correlation_id=current_correlation_id() or new_correlation_id(),
                created_at=now,
                updated_at=now,
            ),
            name=None if recipient is None else recipient.display,
            # From the DRAFT and not from ``intent.language``. The intent's language is the
            # one the payment PAGE was rendered in; the wizard's is the one the progress
            # frames and the kit itself will speak.
            language=draft.ui_language,
            storage=storage,
            key=key,
        ),
        "planned",
        has_live_draft=True,
    )


async def resume_render(
    ctx: Mapping[str, Any],
    bot: Bot,
    ledger: PaymeLedger,
    container: AppContainer,
    *,
    intent: PaymentIntent,
    plan: ResumePlan,
) -> ResumeDecision:
    """Re-verify, claim, post the progress frame, submit, park. Never raises.

    The ordering is the design and every step is load-bearing; see the module docstring for
    the claim-before-act argument and for what this deliberately does NOT do.
    """
    with correlation_scope(plan.order.correlation_id):
        return await _resume(ctx, bot, ledger, container, intent=intent, plan=plan)


async def _resume(
    ctx: Mapping[str, Any],
    bot: Bot,
    ledger: PaymeLedger,
    container: AppContainer,
    *,
    intent: PaymentIntent,
    plan: ResumePlan,
) -> ResumeDecision:
    order_id = str(plan.order.id)

    # 1. RE-VERIFY. ``plan_resume`` ran before a Telegram round trip, and a draft edited in
    #    that window must not be rendered from a stale plan.
    fresh, reason = await _still_the_same_draft(plan, telegram_user_id=plan.order.telegram_user_id)
    if not fresh:
        return ResumeDecision(False, reason)

    # 2. The queue handle, read tolerantly — the same ``getattr`` shape the sweep's third arm
    #    uses, and read BEFORE the claim because it is the only check here with no side effect
    #    of its own. A worker wired without a queue must decline the render rather than raise
    #    inside a job that has already told the customer their money landed; checking it after
    #    the claim would burn the one resume attempt on a wiring fault, and checking it after
    #    the progress frame would leave a "your song is in the studio" message that nothing
    #    will ever update.
    #
    # ``redis is None`` first so the handle narrows away from ``None`` for the constructor
    # below; the ``getattr`` is what makes the check duck-typed.
    redis = ctx.get(REDIS_CTX_KEY)
    if redis is None or getattr(redis, "enqueue_job", None) is None:
        _LOG.error(
            "a paid render is ready to start and this worker has no queue handle",
            extra={"public_ref": intent.public_ref, "order_id": order_id},
        )
        return ResumeDecision(False, "no_queue")

    # 3. CLAIM, before any side effect that can reach the customer or a vendor. See the
    #    module docstring.
    claimed = await ledger.claim_resume(public_ref=intent.public_ref, now=utc_now())
    if is_err(claimed):
        _LOG.error(
            "the resume claim could not be taken; no render was started",
            extra={"public_ref": intent.public_ref, **claimed.error.to_log_dict()},
        )
        return ResumeDecision(False, "enqueue_failed")
    if not claimed.value:
        # The ordinary answer to a redelivered job, and not an error.
        return ResumeDecision(False, "already_claimed")

    # 4. The progress frame, BEFORE the submit — the same ordering ``confirm._queue`` uses,
    #    so the worker's events land in a message that already exists. A job queued with a
    #    message id we never got would report progress into nothing.
    try:
        sent = await bot.send_message(
            chat_id=plan.order.telegram_user_id, text=queued_text(plan.language, name=plan.name)
        )
    except TelegramAPIError as exc:
        # The claim STAYS taken. Releasing it would reopen the double-render window for the
        # sake of a customer who can already start the song with one tap.
        _LOG.error(
            "a paid render could not be started: the progress message did not send",
            extra={"public_ref": intent.public_ref, "failure": repr(exc)},
        )
        return ResumeDecision(False, "no_progress_message")

    # 5. Persist, then enqueue — through the one class that owns that sequence, rather than
    #    restating it here. See ``runtime.submitter``'s docstring on why the order matters.
    # ``chat_id`` is the id we SENT to, not ``sent.chat.id`` which is the id Telegram echoed
    # back. In a private chat they are the same number; taking our own removes a round trip's
    # worth of trust from the one argument the render job uses to find the customer again.
    submitted = await ArqOrderSubmitter(redis, container.repository).submit(
        plan.order.with_state(OrderState.AUTHORIZED, now=utc_now()),
        chat_id=plan.order.telegram_user_id,
        progress_message_id=sent.message_id,
    )
    if is_err(submitted):
        _LOG.error(
            "a paid render could not be queued",
            extra={"public_ref": intent.public_ref, **submitted.error.to_log_dict()},
        )
        return ResumeDecision(False, "enqueue_failed")

    # 6. Park the session, AFTER the submit and in ONE write.
    await _park(plan, order_id=order_id, progress_message_id=sent.message_id)
    return ResumeDecision(True, "queued", order_id)


async def _still_the_same_draft(plan: ResumePlan, *, telegram_user_id: int) -> tuple[bool, str]:
    """Re-read and re-compare, closing the window a Telegram round trip opened.

    Returns the reason alongside the answer so the caller reports the same closed vocabulary
    a first-pass decline would have reported — an operator reading the log should not be able
    to tell which of the two passes noticed.
    """
    try:
        data = await plan.storage.get_data(plan.key)
        parked_state = await plan.storage.get_state(plan.key)
    except Exception as exc:
        _LOG.warning(
            "the wizard session could not be re-read; no render was started",
            extra={"order_id": str(plan.order.id), "failure": repr(exc)},
        )
        return False, "no_storage"
    if data.get(ORDER_ID_KEY) is not None:
        return False, "already_queued"
    if parked_state != Wizard.confirm.state:
        return False, "not_on_confirm"
    loaded = load_draft(data)
    if isinstance(loaded, Err):
        return False, "no_draft"
    if order_id_for(telegram_user_id, loaded.value) != plan.order.id:
        return False, "draft_moved"
    return True, "planned"


async def _park(plan: ResumePlan, *, order_id: str, progress_message_id: int) -> None:
    """Leave the session waiting on the render, exactly as ``confirm._queue`` leaves it.

    **One ``update_data`` and not two writes**, because FSM storage gives no transaction
    across writes and a half-written park is a session the customer can neither use nor
    leave. ``update_data`` MERGES, so a second wizard run's draft is not wiped — the defect
    class ``jobs._release_session`` documents from the other direction.

    Compare-and-write once more before writing: without the dispatcher's per-chat lock this
    is the only defence there is, and the race it accepts — the bot writing between this read
    and this write — is named as a known weakness in the module docstring rather than papered
    over. Never raises: the render is already queued by the time this runs, and failing to
    park is a session the customer can leave with ``/start``, while raising would re-enter the
    retry ladder and re-send the announcement.
    """
    try:
        data = await plan.storage.get_data(plan.key)
        parked_on = data.get(ORDER_ID_KEY)
        if parked_on not in (None, order_id):
            _LOG.info(
                "the session moved onto another order while the render was queued; not parking",
                extra={"order_id": order_id},
            )
            return
        if await plan.storage.get_state(plan.key) != Wizard.confirm.state:
            _LOG.info(
                "the session left the confirm screen while the render was queued; not parking",
                extra={"order_id": order_id},
            )
            return
        await plan.storage.set_state(plan.key, Wizard.submitting)
        await plan.storage.update_data(
            plan.key,
            {ORDER_ID_KEY: order_id, PROGRESS_MESSAGE_ID_KEY: progress_message_id},
        )
    except Exception as exc:
        _LOG.warning(
            "a resumed render was queued but its session could not be parked",
            extra={"order_id": order_id, "failure": repr(exc)},
        )
