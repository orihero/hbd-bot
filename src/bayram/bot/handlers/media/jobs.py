"""The post-freeze buttons: they carry a job id and trust nothing else (IMAGE_VIDEO_SPEC §2).

💳 / 🎟 / 🎁 / ✏️ / ✖️ on the quote, 🔁 on a busy tray, 🔁 again and ✨ under a delivery or a
failure. Each is registered **without a state filter** — the FSM may be cleared, expired or
parked in a song by the time it is pressed — and each reads the ``media_jobs`` row through
:class:`~bayram.media.desk.MediaDesk`: the presser must own it and it must be in a state the
press fits, or the answer is the ``media.stale`` toast (§2 "Callbacks"). Entitlement is re-read
at the press (§2.5): a drawn 🎁 is never proof of anything.

What each does to the row lives in the desk; what the customer sees lives here.
"""

from __future__ import annotations

from typing import Final

from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bayram.bot.callbacks import MediaCB, read_job_ref
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import (
    clear_keeping_identity,
    error_text,
    present,
    ui_language,
)
from bayram.bot.handlers.media.compose import open_create, read_media_draft, start_image
from bayram.bot.i18n import translate
from bayram.bot.media_draft import MediaRef
from bayram.bot.media_offer import is_sku_paused, offered_kinds
from bayram.bot.screens import Screen
from bayram.bot.states import ImageOrder
from bayram.contracts import Err, Language, Result, err
from bayram.db.enums import MEDIA_TERMINAL_STATES, MediaJobState, MediaKind
from bayram.errors import CheckoutError
from bayram.logging import get_logger
from bayram.media.desk import CancelOutcome, CreditStart, JobView
from bayram.media.offering import MEDIA_STUB_CHARGE_KEY, guarded_media_charge
from bayram.media.service import BetaStart

__all__ = [
    "handle_pay",
    "handle_credit",
    "handle_beta",
    "handle_edit",
    "handle_cancel",
    "handle_retry",
    "handle_again",
    "handle_more",
]

_LOG = get_logger(__name__)

_STALE_KEY: Final[str] = "media.stale"
_CANCELLED_KEY: Final[str] = "media.cancelled"
_TOO_LATE_KEY: Final[str] = "media.cancel_too_late"
_SCREENING_KEY: Final[str] = "media.screening"
_PHOTOS_NOT_KEPT_KEY: Final[str] = "media.compose.photos_not_kept"

#: The states a quote's 💳 applies to: the quote itself, and a pay link being re-sent (§2.3.3).
_PAYABLE_STATES: Final[frozenset[MediaJobState]] = frozenset(
    {MediaJobState.QUOTED, MediaJobState.AWAITING_PAYMENT}
)


async def _stale(callback: CallbackQuery, language: Language) -> None:
    await callback.answer(translate(_STALE_KEY, language))


async def _owned_job(
    callback: CallbackQuery, callback_data: MediaCB, deps: BotDeps, language: Language
) -> JobView | None:
    """The row the button names, when the presser owns it. Answers the stale toast otherwise."""
    job_id = read_job_ref(callback_data.job)
    desk = deps.media
    if job_id is None or desk is None:
        await _stale(callback, language)
        return None
    loaded = await desk.load(job_id)
    if isinstance(loaded, Err):
        await callback.answer(error_text(loaded.error, language), show_alert=True)
        return None
    job = loaded.value
    if job is None or job.telegram_user_id != callback.from_user.id:
        await _stale(callback, language)
        return None
    return job


async def _retire_buttons(callback: CallbackQuery) -> None:
    """Take the quote's buttons off once it has been acted on, so it cannot be pressed twice."""
    message = callback.message
    if not isinstance(message, Message):
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        _LOG.info("could not retire the quote's buttons", extra={"failure": repr(exc)})


async def _leave_compose(state: FSMContext) -> None:
    """Drop the image draft once its request is settled — and ONLY an image draft: the press
    is stateless, and a song wizard running in this chat is not this button's to clear."""
    current = await state.get_state()
    if current is not None and current in {s.state for s in ImageOrder.__all_states__}:
        await clear_keeping_identity(state)


# ---------------------------------------------------------------------------
# 💳 🎟 🎁 — starting the request
# ---------------------------------------------------------------------------
async def _pay_path_not_built() -> Result[None]:
    """The live-paid half of 💳 — ``CheckoutProvider.charge`` with ``resume_media_job_id`` —
    arrives with the payment arms (IMAGE_VIDEO_SPEC §7.3, M5.1). Until then a press on a
    live-paid rail is refused like the stub's, and nothing is written."""
    return err(
        CheckoutError(
            "the media pay path is not built yet (M5.1)", user_message_key=MEDIA_STUB_CHARGE_KEY
        )
    )


async def handle_pay(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """💳 — refused on every rail that is not live-paid, whatever the button said (§7.2)."""
    language = await ui_language(state, deps)
    job = await _owned_job(callback, callback_data, deps, language)
    if job is None:
        return
    if job.state not in _PAYABLE_STATES:
        await _stale(callback, language)
        return
    charged = await guarded_media_charge(deps.settings, job.sku, _pay_path_not_built)
    if isinstance(charged, Err):
        _LOG.info(
            "a media pay press was refused",
            extra={"media_job_id": str(job.id), "rail": deps.settings.checkout_provider},
        )
        await callback.answer(error_text(charged.error, language), show_alert=True)
        return
    await callback.answer()


async def handle_credit(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """🎟 — one credit of this SKU pays for the quote, then the stage chain starts (§7.2)."""
    language = await ui_language(state, deps)
    job = await _owned_job(callback, callback_data, deps, language)
    if job is None or deps.media is None:
        return
    spent = await deps.media.spend_credit(
        job.id,
        telegram_user_id=callback.from_user.id,
        is_paused=await is_sku_paused(deps, job.sku),
    )
    if isinstance(spent, Err):
        await callback.answer(error_text(spent.error, language), show_alert=True)
        return
    if spent.value is not CreditStart.STARTED:
        _LOG.info(
            "a credit press did not start the job",
            extra={"media_job_id": str(job.id), "outcome": spent.value.value},
        )
        await _stale(callback, language)
        return
    await callback.answer()
    await _retire_buttons(callback)
    await _leave_compose(state)


async def handle_beta(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """🎁 — free, for the allowlist, off a live-paid rail; all three re-read now (§2.5)."""
    language = await ui_language(state, deps)
    job = await _owned_job(callback, callback_data, deps, language)
    if job is None or deps.media is None:
        return
    started = await deps.media.start_beta(
        job.id,
        telegram_user_id=callback.from_user.id,
        is_paused=await is_sku_paused(deps, job.sku),
    )
    if isinstance(started, Err):
        await callback.answer(error_text(started.error, language), show_alert=True)
        return
    if started.value is not BetaStart.STARTED:
        await _stale(callback, language)
        return
    await callback.answer()
    await _retire_buttons(callback)
    await _leave_compose(state)


# ---------------------------------------------------------------------------
# ✏️ ✖️ 🔁 — changing the request
# ---------------------------------------------------------------------------
async def handle_edit(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """✏️ (§2.3.1): the old row is cancelled and compose reopens from the draft.

    The FSM draft is used when it is the one this row was frozen from (it has the photos'
    sizes); otherwise the compose is rebuilt from the row. Either way the next ✅ Done freezes
    a NEW row, screened before any quote — a row is never edited in place.
    """
    language = await ui_language(state, deps)
    job = await _owned_job(callback, callback_data, deps, language)
    if job is None or deps.media is None:
        return
    reopened = await deps.media.reopen(job.id, telegram_user_id=callback.from_user.id)
    if isinstance(reopened, Err):
        await callback.answer(error_text(reopened.error, language), show_alert=True)
        return
    if reopened.value is None:
        await _stale(callback, language)
        return
    await callback.answer()
    draft = await read_media_draft(state)
    if draft is not None and draft.frozen_job == job.id.hex:
        prompt, refs = draft.prompt, draft.refs
    else:
        prompt = reopened.value.job.prompt
        refs = tuple(
            MediaRef(file_id=ref.file_id, file_unique_id=ref.file_unique_id or ref.file_id)
            for ref in reopened.value.refs
        )
    await start_image(callback, state, deps, prompt=prompt, aspect=job.aspect, refs=refs)


async def handle_cancel(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """✖️ on a quote, a refusal, a busy tray or an open request (§2.6)."""
    language = await ui_language(state, deps)
    job = await _owned_job(callback, callback_data, deps, language)
    if job is None or deps.media is None:
        return
    outcome = await deps.media.cancel(job.id, telegram_user_id=callback.from_user.id)
    if isinstance(outcome, Err):
        await callback.answer(error_text(outcome.error, language), show_alert=True)
        return
    match outcome.value:
        case CancelOutcome.CANCELLED:
            await callback.answer()
            await _leave_compose(state)
            await present(callback, Screen(translate(_CANCELLED_KEY, language), None))
        case CancelOutcome.TOO_LATE:
            await callback.answer(translate(_TOO_LATE_KEY, language), show_alert=True)
        case CancelOutcome.STALE:
            # A refusal's ✖️: the row is already terminal (``rejected``), so there is nothing
            # to cancel and the honest answer is to retire the screen, not to say "stale".
            if job.state in MEDIA_TERMINAL_STATES:
                await callback.answer()
                await _leave_compose(state)
                await present(callback, Screen(translate(_CANCELLED_KEY, language), None))
                return
            await _stale(callback, language)


async def handle_retry(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """🔁 on ``media.busy``: the SAME frozen row goes back through screening (§2.3.3)."""
    language = await ui_language(state, deps)
    job = await _owned_job(callback, callback_data, deps, language)
    if job is None or deps.media is None:
        return
    if job.state is not MediaJobState.SCREENING:
        await _stale(callback, language)
        return
    # The tray reads "checking" BEFORE the enqueue, for ``compose.handle_aspect``'s reason.
    await callback.answer()
    await present(callback, Screen(translate(_SCREENING_KEY, language), None))
    retried = await deps.media.retry_screen(job.id, telegram_user_id=callback.from_user.id)
    if isinstance(retried, Err) or not retried.value:
        _LOG.info("a busy tray's retry did not re-screen", extra={"media_job_id": str(job.id)})


async def handle_again(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """🔁 under a delivery or a failure: a new compose with the prompt and the shape — never
    the photos, which were deleted after delivery (O16) — as a new message, so the result it
    was pressed under stays in the chat. A re-roll is a new request (O13)."""
    language = await ui_language(state, deps)
    job = await _owned_job(callback, callback_data, deps, language)
    if job is None:
        return
    if job.state not in MEDIA_TERMINAL_STATES or job.kind is not MediaKind.IMAGE:
        await _stale(callback, language)
        return
    if MediaKind.IMAGE not in await offered_kinds(deps, callback.from_user.id):
        await _stale(callback, language)
        return
    await callback.answer()
    await start_image(
        callback,
        state,
        deps,
        prompt=job.prompt,
        aspect=job.aspect,
        note_key=_PHOTOS_NOT_KEPT_KEY,
        is_new_message=True,
    )


async def handle_more(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """✨ under a delivery: the picker, as a new message under the result."""
    await callback.answer()
    await open_create(callback, state, deps, is_new_message=True)
