"""✨ Create, and an image request up to the moment it is frozen (IMAGE_VIDEO_SPEC §2.2–§2.3).

::

    ✨ ─► create.pick ─[🖼]─► ImageOrder.compose ─[✅]─► ImageOrder.aspect ─[shape]─► row frozen
                                  │ text → prompt; photo/document → tray            (screening)
                                  └─[🗑] clear photos · [✖️] drop the draft

**One tray message per compose, edited in place** (§2.3.2). Telegram delivers an album as one
message per photo; each accepted photo that changes the count edits the tray, so a four-photo
album ends showing "Photos: 4/4" and draws no reply of its own. No ``sleep``, no debounce task:
the per-chat lock (``bot.app``) already serialises the album's items, and each edit is the
state after that item.

**At the aspect pick the tray becomes ``media.screening`` BEFORE the row is frozen**, because
the freeze enqueues ``media_screen`` and the worker edits that same message into the quote; an
edit made by the bot after the enqueue could land on top of the worker's quote.

**Freezing obeys the one-open-request rule** (§2.3.1, :mod:`bayram.media.desk`): an earlier
quote of the kind is cancelled, and a request whose pay link is out or that is being made stops
the freeze and is shown instead (``media.open_request``) — here and already at the 🖼 press.

The draft lives in FSM data (:mod:`bayram.bot.media_draft`) and holds Telegram ids only.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid4

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, PhotoSize

from bayram.bot.callbacks import AspectPick, CreatePick, MediaCB
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import (
    Event,
    clear_keeping_identity,
    present,
    reset_to_welcome,
    say,
    ui_language,
)
from bayram.bot.i18n import translate
from bayram.bot.keyboards import (
    create_picker_keyboard,
    media_aspect_keyboard,
    media_open_request_keyboard,
    media_tray_keyboard,
)
from bayram.bot.media_draft import (
    MAX_PROMPT_CHARS,
    MAX_UPLOAD_BYTES,
    MIN_PROMPT_CHARS,
    UPLOAD_DOCUMENT_MIMES,
    MediaDraft,
    MediaRef,
    load_media_draft,
)
from bayram.bot.media_offer import offered_kinds
from bayram.bot.middleware import resolve_language
from bayram.bot.screens import Screen
from bayram.bot.states import ImageOrder
from bayram.contracts import Err, Language
from bayram.db.enums import MediaAspect, MediaBackend, MediaJobState, MediaKind, MediaSku
from bayram.logging import get_logger
from bayram.media.desk import FreezeRequest, InputRef, JobView
from bayram.media.offering import effective_backend, sku_price_minor
from bayram.media.overrides import read_overrides

__all__ = [
    "IMAGE_OUTPUTS",
    "ASPECT_FOR_PICK",
    "open_create",
    "start_image",
    "show_open_request",
    "tray_text",
    "read_media_draft",
    "handle_pick",
    "handle_compose_text",
    "handle_compose_photo",
    "handle_compose_document",
    "handle_compose_other",
    "handle_done",
    "handle_clear",
    "handle_drop",
    "handle_aspect",
    "handle_after_done",
]

_LOG = get_logger(__name__)

#: One request yields two images (O5, D25, §1.3).
IMAGE_OUTPUTS: Final[int] = 2

ASPECT_FOR_PICK: Final[dict[AspectPick, MediaAspect]] = {
    AspectPick.PORTRAIT: MediaAspect.PORTRAIT,
    AspectPick.SQUARE: MediaAspect.SQUARE,
    AspectPick.LANDSCAPE: MediaAspect.LANDSCAPE,
}

#: How much of the prompt the tray echoes back. The whole prompt is kept; this is display.
_PROMPT_PREVIEW_CHARS: Final[int] = 120

_PICK_KEY: Final[str] = "create.pick"
_COMPOSE_KEY: Final[str] = "media.image.compose"
_TRAY_KEY: Final[str] = "media.tray"
_NO_PROMPT_KEY: Final[str] = "media.tray.no_prompt"
_CAP_KEY: Final[str] = "media.tray.cap_reached"
_NEED_PROMPT_KEY: Final[str] = "media.need_prompt"
_PROMPT_INVALID_KEY: Final[str] = "media.prompt.invalid"
_UNSUPPORTED_KEY: Final[str] = "media.compose.unsupported"
_CLOSED_KEY: Final[str] = "media.compose.closed"
_USE_BUTTONS_KEY: Final[str] = "media.use_buttons"
_ASPECT_KEY: Final[str] = "media.aspect"
_SCREENING_KEY: Final[str] = "media.screening"
_STALE_KEY: Final[str] = "media.stale"
_CANCELLED_KEY: Final[str] = "media.cancelled"
_BUSY_KEY: Final[str] = "media.busy"
_EXPIRED_KEY: Final[str] = "wizard.expired"
_OPEN_REQUEST_KEY: Final[str] = "media.open_request"
_OPEN_REQUEST_PAID_KEY: Final[str] = "media.open_request.paid"
_KIND_LABEL_KEYS: Final[dict[MediaKind, str]] = {
    MediaKind.IMAGE: "media.kind.image",
    MediaKind.VIDEO: "media.kind.video",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _user_id(event: Event) -> int | None:
    return event.from_user.id if event.from_user is not None else None


async def read_media_draft(state: FSMContext) -> MediaDraft | None:
    return load_media_draft(await state.get_data())


async def _write(state: FSMContext, draft: MediaDraft) -> None:
    await state.update_data(draft.to_state_data())


def _preview(prompt: str) -> str:
    one_line = " ".join(prompt.split())
    if len(one_line) <= _PROMPT_PREVIEW_CHARS:
        return f"«{one_line}»"
    return f"«{one_line[: _PROMPT_PREVIEW_CHARS - 1]}…»"


def _valid_prompt(text: str | None) -> str | None:
    """The prompt, trimmed, when it is one (§1.3: 3–800 characters, and not a command)."""
    if text is None:
        return None
    trimmed = text.strip()
    if trimmed.startswith("/") or not MIN_PROMPT_CHARS <= len(trimmed) <= MAX_PROMPT_CHARS:
        return None
    return trimmed


def tray_text(draft: MediaDraft, max_refs: int) -> str:
    """The compose tray: what to do, then the prompt and the photo count (§2.3.3)."""
    language = draft.ui_language
    head = translate(_COMPOSE_KEY, language, max=max_refs)
    prompt_state = _preview(draft.prompt) if draft.prompt else translate(_NO_PROMPT_KEY, language)
    line = translate(
        _TRAY_KEY, language, prompt_state=prompt_state, n=len(draft.refs), max=max_refs
    )
    return f"{head}\n\n{line}"


def _tray_markup(draft: MediaDraft) -> InlineKeyboardMarkup:
    return media_tray_keyboard(draft.ui_language, has_photos=bool(draft.refs))


async def _edit_tray(message: Message, draft: MediaDraft, deps: BotDeps) -> MediaDraft:
    """Redraw the tray in place; with no tray on record (or one that is gone) send a new one."""
    text = tray_text(draft, deps.settings.media_max_reference_images)
    bot = message.bot
    if draft.tray_message_id is not None and bot is not None:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=message.chat.id,
                message_id=draft.tray_message_id,
                reply_markup=_tray_markup(draft),
            )
        except TelegramAPIError as exc:
            if (
                isinstance(exc, TelegramBadRequest)
                and "not modified" in (exc.message or "").lower()
            ):
                return draft
            _LOG.info(
                "the tray could not be edited; sending it again", extra={"failure": repr(exc)}
            )
        else:
            return draft
    sent = await message.answer(text, reply_markup=_tray_markup(draft))
    return draft.updated(tray_message_id=sent.message_id)


async def _stale(callback: CallbackQuery, language: Language) -> None:
    await callback.answer(translate(_STALE_KEY, language))


def _kind_label(kind: MediaKind, language: Language) -> str:
    return translate(_KIND_LABEL_KEYS[kind], language)


async def show_open_request(event: Event, job: JobView, language: Language) -> None:
    """``media.open_request`` (§2.3.1): a pay link that is out gets 💳 · ✖️ for THAT row; a
    request being made says so and offers nothing."""
    kind = _kind_label(job.kind, language)
    if job.state is MediaJobState.AWAITING_PAYMENT:
        screen = Screen(
            translate(_OPEN_REQUEST_KEY, language, kind=kind),
            media_open_request_keyboard(language, job.id),
        )
    else:
        screen = Screen(translate(_OPEN_REQUEST_PAID_KEY, language, kind=kind), None)
    await present(event, screen)


# ---------------------------------------------------------------------------
# ✨ and the picker
# ---------------------------------------------------------------------------
async def open_create(
    event: Event, state: FSMContext, deps: BotDeps, *, is_new_message: bool = False
) -> None:
    """✨ Create (§2.2): the picker when media is offered to this account, else the song.

    Offering nothing draws nothing: a customer outside the beta presses ✨ and is in the song
    flow with no extra tap, exactly as 🎵 behaved. The picker carries no state, so a song
    draft in progress is untouched until a row is chosen. ``is_new_message`` draws it under a
    button's message rather than over it (✨ under a delivered result).
    """
    kinds = await offered_kinds(deps, _user_id(event))
    if not kinds:
        await reset_to_welcome(event, state, deps)
        return
    language = await ui_language(state, deps)
    screen = Screen(
        translate(_PICK_KEY, language),
        create_picker_keyboard(
            language,
            is_image_offered=MediaKind.IMAGE in kinds,
            is_video_offered=MediaKind.VIDEO in kinds,
        ),
    )
    if is_new_message and isinstance(event, CallbackQuery):
        if isinstance(event.message, Message):
            await event.message.answer(screen.text, reply_markup=screen.markup)
        return
    await present(event, screen)


async def handle_pick(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """A row of the picker. Stateless: the picker is drawn from the menu, which has none."""
    language = await ui_language(state, deps)
    try:
        pick = CreatePick(callback_data.arg)
    except ValueError:
        await _stale(callback, language)
        return
    if pick is CreatePick.SONG:
        await callback.answer()
        await reset_to_welcome(callback, state, deps)
        return
    kind = MediaKind.IMAGE if pick is CreatePick.IMAGE else MediaKind.VIDEO
    # Re-asked at the press (§2.5): the picker may be hours old, the beta list edited since.
    if kind not in await offered_kinds(deps, callback.from_user.id):
        await _stale(callback, language)
        return
    await callback.answer()
    await start_image(callback, state, deps)


async def start_image(
    event: Event,
    state: FSMContext,
    deps: BotDeps,
    *,
    prompt: str | None = None,
    aspect: MediaAspect | None = None,
    refs: tuple[MediaRef, ...] = (),
    note_key: str | None = None,
    is_new_message: bool = False,
) -> None:
    """A fresh image compose: clear the session, draw the tray, park in ``ImageOrder.compose``.

    ``prompt``/``aspect``/``refs`` pre-fill it (🔁 again, ✏️ Edit). From a button the tray is
    drawn over that message unless ``is_new_message``; from a message it is sent.
    """
    desk = deps.media
    telegram_user_id = _user_id(event)
    language = await ui_language(state, deps)
    if desk is not None and telegram_user_id is not None:
        # §2.3.1: "✨ → 🖼 again" with a request that is paid for or has a pay link out shows
        # that request rather than a compose that could never be frozen.
        opened = await desk.open_request(telegram_user_id, MediaKind.IMAGE)
        if not isinstance(opened, Err) and opened.value is not None:
            await show_open_request(event, opened.value, language)
            return
    await clear_keeping_identity(state)
    draft = MediaDraft(
        kind=MediaKind.IMAGE,
        session_id=uuid4().hex,
        ui_language=language,
        prompt=prompt,
        refs=refs[: deps.settings.media_max_reference_images],
        aspect=aspect,
    )
    text = tray_text(draft, deps.settings.media_max_reference_images)
    if note_key is not None:
        text = f"{translate(note_key, language)}\n\n{text}"
    markup = _tray_markup(draft)
    tray_id: int | None = None
    if isinstance(event, CallbackQuery) and isinstance(event.message, Message):
        if is_new_message:
            tray_id = (await event.message.answer(text, reply_markup=markup)).message_id
        else:
            await present(event, Screen(text, markup))
            tray_id = event.message.message_id
    elif isinstance(event, Message):
        tray_id = (await event.answer(text, reply_markup=markup)).message_id
    draft = draft.updated(tray_message_id=tray_id)
    await state.set_state(ImageOrder.compose)
    await _write(state, draft)
    _LOG.info("an image compose opened", extra={"prefilled": prompt is not None})


# ---------------------------------------------------------------------------
# Compose: text, photos, documents, everything else
# ---------------------------------------------------------------------------
async def _draft_or_expire(message: Message, state: FSMContext) -> MediaDraft | None:
    draft = await read_media_draft(state)
    if draft is None:
        # ``ImageOrder.compose`` with no readable draft: a draft from another build, or data
        # that was wiped under the state. Say so, and leave nothing half-set.
        await clear_keeping_identity(state)
        await say(message, translate(_EXPIRED_KEY, await _language(state)))
    return draft


async def _language(state: FSMContext) -> Language:
    return await resolve_language(state)


def _is_first_notice(draft: MediaDraft, message: Message) -> bool:
    """One notice per album (§2.3.2): true for a lone message or the first of an album."""
    group = message.media_group_id
    return group is None or draft.last_media_group_id != group


async def handle_compose_text(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """A line of text is the prompt; a later one replaces it."""
    draft = await _draft_or_expire(message, state)
    if draft is None:
        return
    prompt = _valid_prompt(message.text)
    if prompt is None:
        await say(
            message,
            translate(
                _PROMPT_INVALID_KEY, draft.ui_language, min=MIN_PROMPT_CHARS, max=MAX_PROMPT_CHARS
            ),
        )
        return
    draft = await _edit_tray(message, draft.updated(prompt=prompt), deps)
    await _write(state, draft)


async def _take_photo(message: Message, state: FSMContext, deps: BotDeps, ref: MediaRef) -> None:
    draft = await _draft_or_expire(message, state)
    if draft is None:
        return
    changed = False
    # §2.3.2: a caption on any item sets or replaces the prompt.
    caption = _valid_prompt(message.caption)
    if caption is not None and caption != draft.prompt:
        draft = draft.updated(prompt=caption)
        changed = True
    max_refs = deps.settings.media_max_reference_images
    if ref.file_unique_id in draft.unique_ids:
        pass  # The same photo twice — sent again, or forwarded back. Deduped, silently.
    elif len(draft.refs) >= max_refs:
        if _is_first_notice(draft, message):
            await say(message, translate(_CAP_KEY, draft.ui_language, max=max_refs))
            draft = draft.updated(last_media_group_id=message.media_group_id)
    else:
        draft = draft.updated(refs=(*draft.refs, ref))
        changed = True
    if changed:
        draft = await _edit_tray(message, draft, deps)
    await _write(state, draft)


def _largest(photo: list[PhotoSize]) -> PhotoSize:
    return max(photo, key=lambda size: size.width * size.height)


async def handle_compose_photo(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """A photo: its largest size goes on the tray (§2.3.2)."""
    photo = message.photo or []
    if not photo:
        await handle_compose_other(message, state, deps)
        return
    size = _largest(photo)
    ref = MediaRef(
        file_id=size.file_id,
        file_unique_id=size.file_unique_id,
        mime="image/jpeg",
        w=size.width,
        h=size.height,
        size=size.file_size,
    )
    await _take_photo(message, state, deps, ref)


async def handle_compose_document(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """A photo sent as a file: JPEG, PNG or WebP, within the Bot API's 20 MB (§2.3.2)."""
    document = message.document
    if (
        document is None
        or document.mime_type not in UPLOAD_DOCUMENT_MIMES
        or (document.file_size is not None and document.file_size > MAX_UPLOAD_BYTES)
    ):
        await handle_compose_other(message, state, deps)
        return
    ref = MediaRef(
        file_id=document.file_id,
        file_unique_id=document.file_unique_id,
        mime=document.mime_type or "image/jpeg",
        size=document.file_size,
    )
    await _take_photo(message, state, deps, ref)


async def handle_compose_other(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """A sticker, a video, a voice note, a PDF: not a photo, said once per album."""
    draft = await _draft_or_expire(message, state)
    if draft is None:
        return
    if not _is_first_notice(draft, message):
        return
    await say(message, translate(_UNSUPPORTED_KEY, draft.ui_language))
    if message.media_group_id is not None:
        await _write(state, draft.updated(last_media_group_id=message.media_group_id))


# ---------------------------------------------------------------------------
# The tray's buttons and the aspect screen
# ---------------------------------------------------------------------------
async def _tray_draft(callback: CallbackQuery, state: FSMContext) -> MediaDraft | None:
    """The draft, when the button pressed is on THIS compose's tray. A tray left over from an
    earlier compose shares the state but not the message, and is answered as stale."""
    draft = await read_media_draft(state)
    message = callback.message
    if (
        draft is None
        or not isinstance(message, Message)
        or draft.tray_message_id != message.message_id
    ):
        await _stale(callback, await _language(state))
        return None
    return draft


async def _is_gpu_reserved(deps: BotDeps, sku: MediaSku) -> bool:
    """O11, §4.5: the operator's GPU window is open and ``sku`` renders on the local GPU.

    Read at Done and at the shape pick, so a customer learns the studio is busy before a row
    is frozen — not from the worker's screen a moment later. ``None`` Redis reads "not
    reserved"; the worker's quote-time check (``bayram.media.gate``) is the backstop.
    """
    if deps.media_kv is None:
        return False
    overrides = await read_overrides(deps.media_kv, sku)
    backend = effective_backend(deps.settings, sku, overrides.backend)
    return backend is MediaBackend.LOCAL and overrides.is_gpu_reserved(deps.clock())


async def handle_done(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """✅ Done: the aspect screen, over the tray. No prompt yet, or the GPU reserved by the
    operator → an alert, and nothing moves (the tray stays for a later ✅)."""
    draft = await _tray_draft(callback, state)
    if draft is None:
        return
    if draft.prompt is None:
        await callback.answer(translate(_NEED_PROMPT_KEY, draft.ui_language), show_alert=True)
        return
    if await _is_gpu_reserved(deps, MediaSku.IMAGE):
        await callback.answer(translate(_BUSY_KEY, draft.ui_language), show_alert=True)
        return
    await callback.answer()
    await state.set_state(ImageOrder.aspect)
    language = draft.ui_language
    await present(
        callback, Screen(translate(_ASPECT_KEY, language), media_aspect_keyboard(language))
    )


async def handle_clear(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """🗑 Clear photos: the prompt stays."""
    draft = await _tray_draft(callback, state)
    if draft is None:
        return
    await callback.answer()
    draft = draft.updated(refs=(), last_media_group_id=None)
    await present(
        callback,
        Screen(tray_text(draft, deps.settings.media_max_reference_images), _tray_markup(draft)),
    )
    await _write(state, draft)


async def handle_drop(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """✖️ before anything was frozen: the draft goes, and there is no row to cancel."""
    draft = await _tray_draft(callback, state)
    if draft is None:
        return
    await callback.answer()
    await clear_keeping_identity(state)
    await present(callback, Screen(translate(_CANCELLED_KEY, draft.ui_language), None))


async def handle_aspect(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """The shape, and the freeze (§2.3.1): the draft becomes a ``screening`` row.

    Entitlement is asked again first (§2.5): the compose may be a day old and the account
    off the beta list since. The price is the setting's now, snapshotted on the row.
    """
    draft = await _tray_draft(callback, state)
    if draft is None:
        return
    language = draft.ui_language
    desk = deps.media
    try:
        aspect = ASPECT_FOR_PICK[AspectPick(callback_data.arg)]
    except ValueError:
        await _stale(callback, language)
        return
    price = sku_price_minor(deps.settings, MediaSku.IMAGE)
    message = callback.message
    if (
        desk is None
        or price is None
        or draft.prompt is None
        or not isinstance(message, Message)
        or MediaKind.IMAGE not in await offered_kinds(deps, callback.from_user.id)
    ):
        await _stale(callback, language)
        await clear_keeping_identity(state)
        await present(callback, Screen(translate(_STALE_KEY, language), None))
        return
    if await _is_gpu_reserved(deps, MediaSku.IMAGE):
        # The window opened while the shape screen was up: nothing is frozen (§4.5).
        await callback.answer(translate(_BUSY_KEY, language), show_alert=True)
        return
    await callback.answer()
    # BEFORE the freeze: the worker edits this same message into the quote once the enqueue
    # lands, and a bot edit after that would draw over it (module docstring).
    await present(callback, Screen(translate(_SCREENING_KEY, language), None))
    frozen = await desk.freeze(
        FreezeRequest(
            telegram_user_id=callback.from_user.id,
            chat_id=message.chat.id,
            tray_message_id=message.message_id,
            kind=MediaKind.IMAGE,
            sku=MediaSku.IMAGE,
            aspect=aspect,
            language=language,
            prompt=draft.prompt,
            refs=tuple(InputRef(ref.file_id, ref.file_unique_id) for ref in draft.refs),
            outputs_requested=IMAGE_OUTPUTS,
            price_minor=price,
            currency=deps.settings.kit_currency,
        )
    )
    if isinstance(frozen, Err):
        # Nothing was written; the shape can be picked again.
        await present(
            callback, Screen(translate(_BUSY_KEY, language), media_aspect_keyboard(language))
        )
        return
    if frozen.value.open_request is not None:
        await clear_keeping_identity(state)
        await show_open_request(callback, frozen.value.open_request, language)
        return
    job_id: UUID | None = frozen.value.job_id
    await _write(
        state, draft.updated(aspect=aspect, frozen_job=job_id.hex if job_id is not None else None)
    )
    await state.set_state(ImageOrder.quote)
    _LOG.info(
        "an image request was frozen",
        extra={
            "media_job_id": str(job_id),
            "photos": len(draft.refs),
            "cancelled_earlier": len(frozen.value.cancelled),
        },
    )


async def handle_after_done(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Anything sent after ✅ Done (§2.3.2): photos draw ``media.compose.closed`` once per
    album; anything else is pointed at the buttons."""
    user = message.from_user
    language = await ui_language(state, deps)
    if message.text is None:
        if user is not None and not deps.albums.first(
            user.id, message.media_group_id, purpose="closed", now=deps.clock()
        ):
            return
        await say(message, translate(_CLOSED_KEY, language))
        return
    await say(message, translate(_USE_BUTTONS_KEY, language))
