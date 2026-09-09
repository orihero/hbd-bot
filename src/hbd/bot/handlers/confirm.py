"""Confirmation, the payment gate, and handing the order to the queue.

The payment gate is a real call to a real ``PaymentProvider`` that happens to be a no-op in
this build. It is written the way a paid flow is written — authorise, branch on the result,
only then spend money — so switching to a live rail is a wiring change in the composition
root and not a rewrite of this file.

Ahead of the payment gate sits the entitlement gate, and it is READ-ONLY by construction:
it calls ``EntitlementStore.balance_for`` and nothing else, so the customer is told they
are out of credits, blocked or already rendering while they are still on the Confirm
screen — and no failure on this side of the seam can consume a credit, because nothing
here can write one. The single debit lives in the worker, which is the only process whose
terminal paths can refund. See :func:`_entitlement_refusal`.

**On a deployment that SELLS, both reads of that meter fail CLOSED.** They used to fail
open, and the reasoning for that is preserved in :func:`_entitlement_refusal` because it is
still correct for a deployment that sells nothing. It stopped being correct the day a
render cost 7 000 UZS: the shipped configuration leaves ``credits_enforced`` false, so the
worker covers a shortfall rather than refusing it, and the bot's read is then the only
thing between an unreadable database and a paid song given away. A customer who meets that
failure is told the service is temporarily unavailable and left on the Confirm screen to
press again — never that they are out of songs, which is a claim about a number nobody
could read.

The message the user is looking at when they press Confirm becomes the progress message:
it is edited into the first frame and its id travels with the job, so the worker's events
land in a message that already exists instead of racing to create one.

Four things here are load-bearing against a double tap, and none of them may be reordered:

* the dispatcher holds a per-chat lock for the whole update. That lock is what makes the
  state filter on the Confirm registration a real gate: aiogram reads ``raw_state`` once
  per update, inside the lock, and hands it to every filter — so without the lock two taps
  arriving in one ``getUpdates`` batch both read ``Wizard:confirm`` before either handler
  runs, and no ordering of awaits in this file can close that window. It is wired in
  ``bot.app.build_dispatcher``; this handler cannot defend itself without it;
* the FSM is flipped to ``Wizard.submitting`` as the FIRST await of the handler, before the
  draft is read and long before the payment round-trip. Each early return that leaves the
  user on the confirm screen has to put the state back, which ``show_confirm`` already
  does through ``show_step`` — the paths that route through it need nothing extra;
* ``callback.answer()`` comes after the flip, so Telegram keeps the button's spinner up for
  the length of the authorisation instead of clearing it and inviting a second press;
* the order id is DERIVED from the draft rather than minted fresh. A tap that still slips
  through — two bot processes, a state write that lost a race — produces the same id, which
  becomes the same ``job_id_for`` in the submitter, and ARQ refuses to queue an id it is
  already running. The collision is the design, not an accident. It is scoped to one run
  through the wizard by ``WizardDraft.session_id``: see :func:`_order_id_for`.

The FSM is NOT cleared once the order is queued. It stays parked in ``Wizard.submitting``
with the order id and the progress message id in its data, so ``handlers.submitting`` can
answer "still being made" for the whole generation window. Clearing here is what used to
make the bot tell a customer their session had expired while it was singing for them.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid5

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.draft import WizardDraft
from hbd.bot.handlers.balance import build_offer, show_confirm
from hbd.bot.handlers.common import (
    clear_keeping_identity,
    error_text,
    expire,
    present,
    read_draft,
    say,
    support_text,
)
from hbd.bot.handlers.lyrics import enter_lyrics_step
from hbd.bot.handlers.submitting import remember_submission
from hbd.bot.i18n import translate
from hbd.bot.keyboards import start_over_keyboard
from hbd.bot.progress import queued_text
from hbd.bot.screens import Screen
from hbd.bot.states import Wizard
from hbd.config import Settings
from hbd.contracts import Brief, Err, Language, Order, OrderState
from hbd.entitlements import (
    CreditBalance,
    EntitlementError,
    EntitlementPolicy,
    InsufficientCreditsError,
    TooManyOrdersInFlightError,
    period_index_for,
    period_start,
    resolve_entitlement_policy,
)
from hbd.errors import HbdError, StorageError
from hbd.logging import current_correlation_id, get_logger, new_correlation_id

__all__ = ["build_router"]

_LOG = get_logger(__name__)

#: Namespace for :func:`_order_id_for`. An arbitrary constant whose only requirement is
#: that it never changes: a new namespace would mint a second id for a draft that has
#: already been queued under the old one, which is precisely the collision this exists to
#: cause. Not a secret and not a key — a UUID5 namespace is public by construction.
_ORDER_NAMESPACE: Final[UUID] = UUID("aa9941d0-85de-4c03-9e82-059b15b28fb7")

#: What one render costs the account. Restated here rather than asked of the store, because
#: the only method that knows it — ``EntitlementStore.charge`` — is a WRITE, and this side
#: of the seam may not write. It mirrors the ``cost`` default of ``hbd.db.credits.charge``;
#: a divergence would make the confirm screen refuse a customer the worker would have let
#: through, or promise one the worker then refuses, and never a wrong charge.
_RENDER_COST: Final[int] = 1


async def handle_confirm(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    # The gate against a double tap. Nothing may be awaited before it: see the module
    # docstring. ``show_confirm`` restores ``Wizard.confirm`` on every path that comes back.
    await state.set_state(Wizard.submitting)
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    brief_result = draft.to_brief()
    if isinstance(brief_result, Err):
        _LOG.info("confirm pressed on an incomplete draft", extra=brief_result.error.to_log_dict())
        await say(callback, error_text(brief_result.error, draft.ui_language))
        await show_confirm(callback, state, deps, draft)
        return
    if draft.lyrics is None:
        # The last gate before money and vendors: this order must carry the words the
        # customer read. ``REQUIRED_ANSWERS`` deliberately excludes the lyric, so
        # ``to_brief()`` succeeds without one and nothing else on this path consults
        # ``is_complete`` — and FSM storage outlives a deploy, so a session parked on this
        # screen by the previous build arrives here with ``lyrics=None``. Queueing it would
        # hand the worker a brief to write from and deliver a song nobody approved, with no
        # error to show for it. Write one and put it in front of them instead.
        _LOG.info("confirm pressed before a lyric was approved; showing the preview first")
        await enter_lyrics_step(callback, state, deps, draft)
        return
    await _authorize_and_submit(callback, state, deps, draft, brief_result.value)


async def _authorize_and_submit(
    callback: CallbackQuery,
    state: FSMContext,
    deps: BotDeps,
    draft: WizardDraft,
    brief: Brief,
) -> None:
    """The two gates, then the queue. Nothing past here can un-spend what a gate let through.

    The FSM is already in ``Wizard.submitting`` when this is called, so the rollback on a
    failure is ``show_confirm``'s doing rather than an explicit flip: it sets the state for the
    step it renders, and every early return that comes BACK renders CONFIRM. The entitlement
    refusals that do not come back — no credits, blocked — are the one exception, and
    :func:`_refuse` owns that decision rather than this function.

    Both gates are reads. The entitlement gate cannot write by construction (see
    :func:`_entitlement_refusal`) and the payment gate is handed the plain no-op provider
    from ``hbd.main``, never the credit-gated decorator, so the three early returns below
    have nothing to compensate for.
    """
    language = draft.ui_language
    order = _build_order(callback, deps, draft, brief)
    refusal = await _entitlement_refusal(deps, order)
    if refusal is not None:
        await _refuse(callback, state, deps, draft, order, refusal)
        return
    second_line = await _second_line(deps, order)
    if second_line is _SecondLine.PAYWALL:
        # A customer can be holding a keyboard drawn BEFORE they spent their last credit —
        # a stale message, a second tab, a redelivered update — and that keyboard still
        # carries 🎬 Record it. This is what stops such a tap queueing a render nobody paid
        # for: ``show_confirm`` redraws the very same screen wearing the paywall, so the
        # customer sees the price instead of a progress bar, and the button that should not
        # have been there is gone from the message they are looking at.
        await show_confirm(callback, state, deps, draft)
        return
    if second_line is _SecondLine.UNREADABLE:
        # Said out loud rather than redrawn in silence. The paywall branch above needs no
        # sentence because the screen it draws IS the sentence — a price where a Record it
        # button used to be. This one redraws the screen unchanged, so a customer given no
        # message would press the same button again and watch nothing happen.
        await say(callback, error_text(_meter_unreadable(order), language))
        await show_confirm(callback, state, deps, draft)
        return
    if not await _is_authorized(deps, order, language, callback):
        await show_confirm(callback, state, deps, draft)
        return
    await _queue(
        callback,
        state,
        deps,
        draft,
        order,
        name=None if brief.recipient is None else brief.recipient.display,
    )


async def _queue(
    callback: CallbackQuery,
    state: FSMContext,
    deps: BotDeps,
    draft: WizardDraft,
    order: Order,
    *,
    name: str | None,
) -> None:
    """Turn the confirm screen into the first progress frame and hand the order to ARQ.

    Split out of :func:`_authorize_and_submit` only for size; the sequencing is unchanged
    and still load-bearing. The progress message is created BEFORE the submit so its id can
    travel with the job — the worker's events then land in a message that already exists
    instead of racing to create one.
    """
    language = draft.ui_language
    target = await _start_progress(callback, language, name=name)
    if target is None:
        await say(callback, translate("wizard.enqueue_failed", language))
        await show_confirm(callback, state, deps, draft)
        return

    chat_id, message_id = target
    authorized = order.with_state(OrderState.AUTHORIZED, now=deps.clock())
    submitted = await deps.submitter.submit(
        authorized, chat_id=chat_id, progress_message_id=message_id
    )
    if isinstance(submitted, Err):
        _LOG.error("order could not be queued", extra=submitted.error.to_log_dict())
        await say(callback, translate("wizard.enqueue_failed", language))
        await show_confirm(callback, state, deps, draft)
        return
    _LOG.info(
        "order queued",
        extra={
            "order_id": str(authorized.id),
            "job_id": submitted.value,
            "chat_id": chat_id,
            "progress_message_id": message_id,
        },
    )
    # NOT ``state.clear()``. The session stays parked so the customer can be answered
    # truthfully for the several minutes this takes; the delivery path is what clears it.
    await remember_submission(state, order_id=authorized.id, progress_message_id=message_id)


async def _entitlement_refusal(deps: BotDeps, order: Order) -> HbdError | None:
    """Read the meter and decide. **This gate writes nothing**, and that is its whole point.

    The customer learns on the Confirm screen instead of after the progress bar has been
    running for a minute, and no bot-side failure can consume a credit — because there is
    nothing here to consume it. That is a property of the control flow rather than of a
    comment: the only call made is :meth:`~hbd.entitlements.EntitlementStore.balance_for`,
    which is the one method on the protocol that does not write. The single debit lives in
    the worker (``runtime.container._render_gate``), the only process whose terminal paths
    can compensate — ``_authorize_and_submit`` has three early returns after this point
    (payment declined, ``_start_progress`` returned ``None``, ``submitter.submit`` returned
    ``Err``) and not one of them could reach a refund, since no ``orders`` row and no ARQ
    job exist yet.

    ``exclude_order_id`` leaves this order out of the in-flight count, so a customer who
    re-confirms the same draft after a queue failure is never refused by their own debit.

    **A read that FAILS now depends on whether this deployment SELLS, and that is a change
    from the fail-open this function used to do unconditionally.** The old argument was
    sound for what it covered: this was a read-only refusal gate in FRONT of a worker gate
    that read the same rows inside the transaction that charges, so failing open cost a
    refused customer one extra minute and failing closed would have stopped every order in
    the product over a database blip. That argument does not survive a PAYWALL. Once the
    customer has paid 7 000 UZS for a render, the bot-side read is the only thing standing
    between a blip and a song given away — ``.env.example`` ships ``credits_enforced=false``,
    so ``hbd.db.credits.charge`` covers the shortfall with an ``UNENFORCED_RENDER`` grant and
    sings it. Proven end to end: with the store injected with a ``StorageError`` the Confirm
    screen drew 🎬 Record it, the press was queued, and the balance never moved.

    So: a deployment that sells fails CLOSED, and says the service is temporarily
    unavailable — a ``StorageError``, not an ``EntitlementError``, because the customer is
    not being refused for a business reason and must never be told they are out of songs
    when the truth is simply unknown (a customer holding ten credits reads the same
    sentence). A deployment that sells nothing keeps the old fail-open exactly, because
    there the worker gate really is the defence and nothing has been paid for.

    The return type widened to ``HbdError`` for that sentence. :func:`_refusal_for` still
    answers ``EntitlementError | None`` — the business refusals have not changed — and
    :func:`_refuse` is what routes the two kinds to their two shapes of screen.
    """
    store = deps.entitlements
    if store is None:
        return None
    balance = await store.balance_for(order.telegram_user_id, exclude_order_id=order.id)
    if isinstance(balance, Err):
        _LOG.error("the entitlement meter could not be read", extra=balance.error.to_log_dict())
        return _meter_unreadable(order) if _sells(deps) else None
    return _refusal_for(balance.value, settings=deps.settings, now=deps.clock())


def _sells(deps: BotDeps) -> bool:
    """Does this deployment take money for a render? The one test both gates branch on.

    Written once because the two of them must never disagree: a build where the first gate
    thought it was selling and the second did not would fail closed on one read and open on
    the next, which is the shape of a bug that shows up as "it only happens sometimes".
    It mirrors ``handlers.balance.build_offer``'s first condition — both ports, not either.
    """
    return deps.purchases is not None and deps.pricing is not None


def _meter_unreadable(order: Order) -> StorageError:
    """The refusal an unreadable meter earns on a SELLING deployment. See the two gates.

    A ``StorageError`` deliberately, so ``error_text`` renders ``error.generic`` — "something
    went wrong on our side, please try again in a moment". Every ``EntitlementError`` key
    says something about the ACCOUNT ("you have used every song", "you are blocked"), and
    saying any of them here would be a claim about a balance nobody could read.
    """
    return StorageError(
        "the entitlement meter could not be read on a selling deployment",
        context={"order_id": str(order.id), "telegram_user_id": order.telegram_user_id},
    )


class _SecondLine(StrEnum):
    """What the second read of the meter decided. Three answers, three different screens.

    A tri-state rather than the boolean this was, because "not paywalled" and "we could not
    tell" used to be the same ``False`` and that collapse was the defect: a meter that
    failed on the second read let a render through on an account with no credits. The names
    are the customer-visible outcomes, not the internal condition.
    """

    #: Nothing here refuses the order; go on to the payment gate.
    ALLOW = "allow"
    #: The account cannot afford this render. Redraw the screen wearing the paywall.
    PAYWALL = "paywall"
    #: The meter could not be read at all on a deployment that sells. Refuse and say why.
    UNREADABLE = "unreadable"


async def _second_line(deps: BotDeps, order: Order) -> _SecondLine:
    """Would the Confirm screen be drawn as a CHECKOUT right now? A read; writes nothing.

    This is the second line of the "no render is queued unpaid" defence. The first is
    structural — the paywall keyboard carries no 🎬 Record it button at all — and it is the
    one that holds for every screen this build draws. This one covers the screen it did not
    draw: a message from before the last credit was spent, still on the customer's phone,
    still carrying ``nav:confirm``.

    **It short-circuits before awaiting anything when the deployment does not sell**, which
    is every deployment and every test that wires neither ``purchases`` nor ``pricing``. That
    ordering is not tidiness. Three tests in ``tests/test_bot/test_submitting.py`` park the
    first of two taps on ``deps.payment.authorize`` with a ``GatedPaymentProvider`` and feed
    the second while it waits; an ``await`` that fired ahead of it for THEM would move the
    suspension point they measure and quietly stop them testing a double tap at all. See
    :func:`_is_authorized`.

    It reads the meter a second time, after ``_entitlement_refusal`` has already read it, and
    that is a deliberate cost paid only on a selling deployment. The alternative was to
    thread the balance out of that function, which would turn the one call site of the
    codebase's most carefully argued read-only gate into a two-value return in order to save
    a round trip on a path that is about to spend several minutes in a vendor. The two reads
    cannot disagree in a way that matters, either: both fail open, and a balance that moved
    between them moved in the customer's favour or is caught by the worker's own gate.

    ``exclude_order_id`` matches ``_entitlement_refusal``'s, so a customer re-confirming
    after a queue failure is never paywalled by their own in-flight debit.

    **The failed read is UNREADABLE and not ALLOW, and the residual hole it closes is worth
    stating because it survives the fix to the gate above.** ``build_offer`` answers ``None``
    for an ``Err`` balance — deliberately, so no price is shown to somebody whose balance
    nobody could read — and this function used to turn that ``None`` into ``False``. With
    ``credits_enforced`` off, ``_refusal_for`` never looks at the balance at all, so a first
    read that SUCCEEDS on a zero-credit account passes the gate above, and a second read
    that then failed handed the customer a free render. Two reads means two chances to fail,
    and both of them now stop the order.
    """
    store = deps.entitlements
    if not _sells(deps) or store is None:
        return _SecondLine.ALLOW
    balance = await store.balance_for(order.telegram_user_id, exclude_order_id=order.id)
    if isinstance(balance, Err):
        _LOG.error("the entitlement meter could not be re-read", extra=balance.error.to_log_dict())
        return _SecondLine.UNREADABLE
    offer = build_offer(balance, deps)
    if offer is not None and offer.is_paywalled:
        return _SecondLine.PAYWALL
    return _SecondLine.ALLOW


def _refusal_for(
    state: CreditBalance, *, settings: Settings, now: datetime
) -> EntitlementError | None:
    """Which refusal this account has earned, if any. Pure — no I/O, no clock of its own.

    The order of the three is the order of severity, and only the last of them is behind a
    flag. A block and the in-flight cap refuse ABUSE and enforce from the day this merges;
    the balance check refuses a paying-intent CUSTOMER, so it stays dark until an operator
    sets ``HBD_CREDITS_ENFORCED=true``. One boolean, one branch.

    That boolean is read off the RESOLVED policy rather than off ``Settings`` directly, so
    this screen and ``hbd.db.credits.charge`` cannot end up disagreeing about what "dark"
    means — they now consult the same field, filled in one place.
    """
    policy = resolve_entitlement_policy(settings)
    if state.is_blocked:
        return EntitlementError(
            "a blocked account reached the confirm screen",
            context={"telegram_user_id": state.telegram_user_id},
        )
    if state.in_flight >= policy.max_orders_in_flight:
        return TooManyOrdersInFlightError(
            "the account already has an unsettled render",
            context={"in_flight": state.in_flight, "limit": policy.max_orders_in_flight},
        )
    if policy.is_balance_enforced and state.credits < _RENDER_COST:
        return _insufficient_credits(state, policy=policy, now=now)
    return None


def _insufficient_credits(
    state: CreditBalance, *, policy: EntitlementPolicy, now: datetime
) -> InsufficientCreditsError:
    """The out-of-credits refusal, carrying the date that makes it actionable.

    The allowance is ROLLING — ``policy.allowance_credits`` every
    ``policy.allowance_period_days`` — so there is a real day on which this customer can
    order again, and saying it is the difference between a refusal and a dead end. The
    window is anchored to a fixed epoch rather than to this customer's last song (see
    :func:`hbd.entitlements.period_index_for`), so the next one opens at the start of the
    window after the one ``now`` falls in.

    A plain ``YYYY-MM-DD`` date, not the instant: the window opens at midnight UTC, and an
    ISO timestamp would put a time zone and a seconds field in front of a customer to
    express a fact that is only ever accurate to the day.
    """
    index = period_index_for(now, period_days=policy.allowance_period_days)
    opens = period_start(index + 1, period_days=policy.allowance_period_days)
    return InsufficientCreditsError(
        "the account cannot afford this render",
        context={
            "balance": state.credits,
            "needed": _RENDER_COST,
            "next_grant_at": opens.date().isoformat(),
        },
    )


async def _refuse(
    callback: CallbackQuery,
    state: FSMContext,
    deps: BotDeps,
    draft: WizardDraft,
    order: Order,
    error: HbdError,
) -> None:
    """Say no in the shape the refusal actually has. Two shapes, and the split is the point.

    A render already in flight is a WAIT, not a refusal: the song this account is holding a
    credit for is being made right now, and pressing Confirm again once it lands genuinely
    works. So that one is said as a sentence and the customer is put back on the Confirm
    screen, exactly as a declined payment is — ``show_confirm`` restores ``Wizard.confirm``,
    which the handler's own state filter needs to match the next tap.

    A block and a spent allowance are neither. Nothing the customer can do inside this
    wizard changes either answer — only an operator or the calendar does — so re-arming a
    Confirm button that cannot succeed would be a dead end dressed as a working screen,
    which this codebase designs against everywhere else (see the ``NavAction`` docstring).
    The session is cleared and the confirm screen is replaced by the reason, a route to a
    human, and the one button that still leads somewhere.

    **On a SELLING deployment, out-of-credits stops being terminal**, and that is the third
    shape. There is now something the customer can do inside this wizard about it: buy a
    song. ``show_confirm`` redraws the same screen as the paywall, so a stale message still
    carrying ``nav:confirm`` — one drawn before the last credit was spent, pressed a minute
    later — is self-healing: the read-only gate refuses it and the customer lands on the buy
    screen rather than in a dead end with their lyric cleared away. The branch is keyed on
    ``deps.purchases`` and not on the error, so a deployment with no purchase store keeps the
    clear-and-start-over behaviour exactly as it was; a BLOCK stays terminal in both, because
    money does not lift an operator's block.

    **A ``StorageError`` is the fourth shape and it is retryable**, which is why the branch
    below tests for it by type rather than folding it in with the business refusals. It is
    what :func:`_entitlement_refusal` answers when a selling deployment cannot read the
    meter, and nothing about it is the customer's fault or the customer's to fix: clearing
    their session and throwing away a lyric they have just approved because a database was
    briefly down would turn a blip into a lost sale. They stay on the Confirm screen and can
    press again in a moment, exactly as the in-flight wait does.
    """
    _LOG.info(
        "the confirm screen refused the order",
        extra={"order_id": str(order.id), **error.to_log_dict()},
    )
    language = draft.ui_language
    if isinstance(error, TooManyOrdersInFlightError | StorageError) or (
        isinstance(error, InsufficientCreditsError) and deps.purchases is not None
    ):
        await say(callback, error_text(error, language))
        await show_confirm(callback, state, deps, draft)
        return
    # ``clear_keeping_identity``, not a bare clear. A block or a spent allowance ends the
    # session, but it does not end the relationship: the calendar or an operator lifts it and
    # the customer comes back. Their language and the fact that they have already given us a
    # phone number are not part of the session that just failed, and a bare clear threw both
    # away — which on a deployment with no profile store loses the language for good, and on
    # one with a store buys a database read inside the FSM isolation lock on their very next
    # message. The other five sites, so the list stays derivable with
    # ``grep -rn "state.clear()" src``: ``common.finish_with``, ``common.reset_to_welcome``,
    # the lyric-budget exhaustion in ``handlers.lyrics``, the end of onboarding, and
    # ``commands.handle_forget`` — the deliberate bare one, because a data-subject request
    # is precisely the case where the identity must go too.
    await clear_keeping_identity(state)
    await present(
        callback,
        Screen(text=_refusal_text(error, deps, language), markup=start_over_keyboard(language)),
    )


def _refusal_text(error: HbdError, deps: BotDeps, language: Language) -> str:
    """The reason, the date it lifts if it lifts on its own, and where to write if it does not.

    ``next_grant_at`` is a SEPARATE line rather than a placeholder inside
    ``error.credits_exhausted``, because the worker renders that same key with no parameters
    at all (``runtime.jobs._tell_the_customer_why``) — a placeholder in it would reach a
    customer as the literal ``{next_grant_at}`` on the path this gate exists to pre-empt but
    can never fully replace.
    """
    lines = [error_text(error, language)]
    opens = error.context.get("next_grant_at")
    if isinstance(opens, str):
        lines.append(translate("credits.next_opens", language, next_grant_at=opens))
    lines.append(support_text(language, deps.settings.support_contact))
    return "\n\n".join(lines)


def _order_fingerprint(telegram_user_id: int, draft: WizardDraft) -> str:
    """A canonical string standing for "this person's answers, exactly as they are now".

    Sorted keys and no whitespace, so two dumps of one draft are byte-identical; the whole
    draft rather than a chosen subset, so a field added to ``WizardDraft`` cannot silently
    stop distinguishing two orders that differ only by it.
    """
    return json.dumps(
        {"telegram_user_id": telegram_user_id, "draft": draft.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _order_id_for(telegram_user_id: int, draft: WizardDraft) -> UUID:
    """The id this draft always gets, so a second submission of it is a duplicate.

    ``uuid4()`` made every tap a new order, which is why two taps bought two songs: nothing
    downstream could tell them apart. A UUID5 over the fingerprint pushes the decision to
    the one place equipped to make it — the submitter derives the ARQ job id from the order
    id, and ARQ declines an id it is already running. Changing one answer and confirming
    again is a genuinely different draft and therefore a genuinely different order, which is
    the behaviour a customer expects.

    The fingerprint carries ``WizardDraft.session_id``, so "the same draft" means the same
    RUN through the wizard and not the same answers for all time. Without it a customer who
    wanted a second copy of a song — same recipient, same four answers, same lyric — minted
    the id their first order already holds, collided with the ``orders`` primary key, and
    was told "I could not hand this to the studio" with no reason and no way out, forever.
    Determinism is meant to survive a double tap, not to make a purchase unrepeatable.
    """
    return uuid5(_ORDER_NAMESPACE, _order_fingerprint(telegram_user_id, draft))


def _build_order(callback: CallbackQuery, deps: BotDeps, draft: WizardDraft, brief: Brief) -> Order:
    now = deps.clock()
    return Order(
        id=_order_id_for(callback.from_user.id, draft),
        telegram_user_id=callback.from_user.id,
        brief=brief,
        state=OrderState.DRAFT,
        correlation_id=current_correlation_id() or new_correlation_id(),
        created_at=now,
        updated_at=now,
    )


async def _is_authorized(
    deps: BotDeps, order: Order, language: Language, callback: CallbackQuery
) -> bool:
    """The gate. Out of scope means "always passes", not "is not called".

    ``order`` is the one built by ``_build_order`` immediately above, so its
    ``telegram_user_id`` is ``callback.from_user.id`` — the person tapping confirm — rather
    than anything re-derived here.

    The double-tap defence does NOT rest on this call: it rests on the per-chat lock and the
    ``Wizard.submitting`` flip, both described in the module docstring. What DOES rest on it
    is the three double-tap TESTS (tests/test_bot/test_submitting.py), whose
    ``GatedPaymentProvider`` parks the first tap on an ``asyncio.Event`` here and feeds the
    second while it waits. Those tests wire no entitlement store, so ``_entitlement_refusal``
    above returns without awaiting anything and this stays the suspension point they need —
    but any future check that awaits ahead of it for THEM would stop them testing what they
    were written to test without going red. Read that file before inserting one.
    """
    result = await deps.payment.authorize(
        order_id=order.id,
        amount_minor=deps.amount_minor,
        currency=deps.currency,
        telegram_user_id=order.telegram_user_id,
    )
    if isinstance(result, Err):
        _LOG.error("payment authorisation failed", extra=result.error.to_log_dict())
        await say(callback, error_text(result.error, language))
        return False
    if not result.value.is_authorized:
        _LOG.info(
            "payment declined",
            extra={"order_id": str(order.id), "provider": result.value.provider},
        )
        await say(callback, translate("wizard.payment_declined", language))
        return False
    return True


async def _start_progress(
    callback: CallbackQuery, language: Language, *, name: str | None
) -> tuple[int, int] | None:
    """Turn the confirm screen into the first progress frame. ``None`` if we cannot post."""
    text = queued_text(language, name=name)
    message = callback.message
    if isinstance(message, Message):
        try:
            await message.edit_text(text, reply_markup=None)
        except TelegramAPIError as exc:
            _LOG.info("could not reuse the confirm message", extra={"failure": repr(exc)})
        else:
            return message.chat.id, message.message_id
    return await _post_progress(callback, text)


async def _post_progress(callback: CallbackQuery, text: str) -> tuple[int, int] | None:
    bot = callback.bot
    if bot is None:
        _LOG.error("no bot on the callback; cannot post a progress message")
        return None
    try:
        sent = await bot.send_message(chat_id=callback.from_user.id, text=text)
    except TelegramAPIError as exc:
        _LOG.error("could not post a progress message", extra={"failure": repr(exc)})
        return None
    return sent.chat.id, sent.message_id


def build_router() -> Router:
    router = Router(name="confirm")
    router.callback_query.register(
        handle_confirm, Wizard.confirm, NavCB.filter(F.action == NavAction.CONFIRM)
    )
    return router
