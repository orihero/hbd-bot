"""Confirmation, the payment gate, and handing the order to the queue.

The payment gate is a real call to a real ``PaymentProvider`` that happens to be a no-op in
this build. It is written the way a paid flow is written — authorise, branch on the result,
only then spend money — so switching to a live rail is a wiring change in the composition
root and not a rewrite of this file.

The message the user is looking at when they press Confirm becomes the progress message:
it is edited into the first frame and its id travels with the job, so the worker's events
land in a message that already exists instead of racing to create one.
"""

from __future__ import annotations

from uuid import uuid4

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.draft import WizardDraft
from hbd.bot.handlers.common import error_text, expire, read_draft, say, show_step
from hbd.bot.handlers.lyrics import enter_lyrics_step
from hbd.bot.i18n import translate
from hbd.bot.progress import queued_text
from hbd.bot.states import Wizard, WizardStep
from hbd.contracts import Brief, Err, Language, Order, OrderState
from hbd.logging import current_correlation_id, get_logger, new_correlation_id

__all__ = ["build_router"]

_LOG = get_logger(__name__)



async def handle_confirm(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    brief_result = draft.to_brief()
    if isinstance(brief_result, Err):
        _LOG.info("confirm pressed on an incomplete draft", extra=brief_result.error.to_log_dict())
        await say(callback, error_text(brief_result.error, draft.ui_language))
        await show_step(callback, state, draft, WizardStep.CONFIRM)
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
    """Payment gate, then queue. Either step failing leaves the user on the confirm screen."""
    language = draft.ui_language
    order = _build_order(callback, deps, brief)
    if not await _is_authorized(deps, order, language, callback):
        await show_step(callback, state, draft, WizardStep.CONFIRM)
        return

    await state.set_state(Wizard.submitting)
    target = await _start_progress(callback, language)
    if target is None:
        await say(callback, translate("wizard.enqueue_failed", language))
        await show_step(callback, state, draft, WizardStep.CONFIRM)
        return

    chat_id, message_id = target
    authorized = order.with_state(OrderState.AUTHORIZED, now=deps.clock())
    submitted = await deps.submitter.submit(
        authorized, chat_id=chat_id, progress_message_id=message_id
    )
    if isinstance(submitted, Err):
        _LOG.error("order could not be queued", extra=submitted.error.to_log_dict())
        await say(callback, translate("wizard.enqueue_failed", language))
        await show_step(callback, state, draft, WizardStep.CONFIRM)
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
    await state.clear()


def _build_order(callback: CallbackQuery, deps: BotDeps, brief: Brief) -> Order:
    now = deps.clock()
    return Order(
        id=uuid4(),
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
    """The gate. Out of scope means "always passes", not "is not called"."""
    result = await deps.payment.authorize(
        order_id=order.id, amount_minor=deps.amount_minor, currency=deps.currency
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


async def _start_progress(callback: CallbackQuery, language: Language) -> tuple[int, int] | None:
    """Turn the confirm screen into the first progress frame. ``None`` if we cannot post."""
    text = queued_text(language)
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
