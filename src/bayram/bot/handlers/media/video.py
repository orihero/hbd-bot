"""A video request from ✅ Done to the moment it is screened (IMAGE_VIDEO_SPEC §2.4).

::

    VideoOrder.compose ─✅─► row frozen (drafting) ─► media_prescreen ─► VideoOrder.aspect
        ─► VideoOrder.tier (only with two tiers) ─► VideoOrder.voice
             ├─🔇 ─────────────────────────────────────────────────────────┐
             ├─🗣 ─► voice_gender ─► voice_text (typed, within the budget) ─┤
             ├─🤖 ─► voice_gender ─► script_review (media_script) ──────────┤
             └─🎙 ─► voice_note (F.voice, ≤ the clip) ──────────────────────┤
                                                                           ▼
                                        drafting → screening, media_screen ─► quote

The compose tray is the image's (:mod:`.compose`); what is new is that **✅ Done freezes a
``drafting`` row** at once (§2.4.1), so the prompt is screened (``media_prescreen``) while the
customer chooses, and the script writer only ever reads a prompt that passed L0/L1 through
the row's id — never an ARQ argument. The worker draws the shape screen on the tray; every
later screen is the bot's, drawn over that same tray, and **every one carries ⬅️ and ✖️**:
⬅️ walks the §2.4.1 back map (back to compose cancels the draft; a later ✅ freezes a new
one), ✖️ cancels the draft (``compose.handle_drop``).

The choices live in the FSM draft until the LAST voice step, which writes them onto the row
in the same statement that moves it to ``screening`` (``MediaDesk.finalize_video``) — so a
row's words are never edited after it was screened, and ``media_screen`` screens the final
narration as it will be spoken (§2.4.1).

**Length is enforced before payment** (O14, §5.3): typed words against the per-language
budget here; a voice note longer than the clip by Telegram's whole-second ``duration`` here,
and by ffprobe (+0.25 s) in ``media_screen``, which sends the draft back for 🎙 record again.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bayram.bot.callbacks import AspectPick, MediaCB, ScriptPick, read_job_ref
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import (
    Event,
    clear_keeping_identity,
    error_text,
    present,
    say,
    ui_language,
)
from bayram.bot.handlers.media.compose import (
    ASPECT_FOR_PICK,
    is_gpu_reserved,
    is_suspended,
    read_media_draft,
    refuse_suspended,
    show_open_request,
    start_compose,
    tray_draft,
    tray_markup,
    tray_text,
    write_draft,
)
from bayram.bot.i18n import translate
from bayram.bot.keyboards import (
    media_tier_keyboard,
    media_video_aspect_keyboard,
    media_voice_gender_keyboard,
    media_voice_pick_keyboard,
    media_voice_step_keyboard,
)
from bayram.bot.media_draft import MediaDraft, MediaRef, MediaVoiceNoteRef
from bayram.bot.media_offer import SKU_FOR_TIER, is_terms_unconfirmed, offered_tiers
from bayram.bot.pricing import format_amount
from bayram.bot.screens import Screen
from bayram.bot.states import VideoOrder
from bayram.contracts import Err, Language
from bayram.db.enums import (
    MediaAspect,
    MediaJobState,
    MediaKind,
    MediaTier,
    MediaVoiceGender,
    MediaVoiceMode,
)
from bayram.logging import get_logger
from bayram.media.desk import (
    FinalizeOutcome,
    FreezeRequest,
    InputRef,
    VideoChoices,
    VoiceNoteRef,
)
from bayram.media.narration import fits_budget, narration_budget, normalise_narration
from bayram.media.offering import sku_price_minor

__all__ = [
    "BUILT_VOICE_MODES",
    "VIDEO_OUTPUTS",
    "start_video",
    "handle_done",
    "handle_aspect",
    "handle_tier",
    "handle_voice",
    "handle_gender",
    "handle_voice_text",
    "handle_voice_in_text_step",
    "handle_voice_note",
    "handle_note_wrong_type",
    "handle_script",
    "handle_back",
    "handle_record_again",
]

_LOG = get_logger(__name__)

#: One clip per request (§1.3).
VIDEO_OUTPUTS: Final[int] = 1

#: The voice modes this build can finish — all four since the script writer
#: (``media_script``, §5.5) is registered in the worker (M4.3). A mode left out of this set is
#: not drawn and a hand-made press of it is stale, so a mode can be switched off here alone.
BUILT_VOICE_MODES: Final[frozenset[MediaVoiceMode]] = frozenset(MediaVoiceMode)

#: A typical wait per tier for the tier screen (§1.3: Standard ~17.5 min on the GPU, Fast
#: ~1–3 min). The quote gives the real ETA; this only tells the two tiers apart.
_TIER_TYPICAL_MINUTES: Final[dict[MediaTier, int]] = {MediaTier.STANDARD: 20, MediaTier.FAST: 3}

_ASPECT_KEY: Final[str] = "media.aspect"
_TIER_KEY: Final[str] = "media.video.tier"
_VOICE_PICK_KEY: Final[str] = "media.voice.pick"
_GENDER_KEY: Final[str] = "media.voice.gender"
_ENTER_TEXT_KEY: Final[str] = "media.voice.enter_text"
_TOO_LONG_KEY: Final[str] = "media.voice.too_long"
_SCRIPT_WAIT_KEY: Final[str] = "media.voice.script_wait"
_SEND_NOTE_KEY: Final[str] = "media.voice.send_note"
_NOTE_TOO_LONG_KEY: Final[str] = "media.voice_note.too_long"
_NOTE_WRONG_TYPE_KEY: Final[str] = "media.voice_note.wrong_type"
_SCREENING_KEY: Final[str] = "media.screening"
_STALE_KEY: Final[str] = "media.stale"
_BUSY_KEY: Final[str] = "media.busy"
_NEED_PROMPT_KEY: Final[str] = "media.need_prompt"
_ETA_MINUTES_KEY: Final[str] = "media.eta.minutes"
_EXPIRED_KEY: Final[str] = "wizard.expired"

#: Where ⬅️ leads from each screen after ✅ Done (§2.4.1). ``voice`` goes to ``tier`` only
#: when the tier screen was shown, which :func:`handle_back` decides.
_BACK_TO_VOICE: Final[frozenset[str | None]] = frozenset(
    {
        VideoOrder.voice_gender.state,
        VideoOrder.voice_text.state,
        VideoOrder.voice_note.state,
        VideoOrder.script_review.state,
    }
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
async def _stale(callback: CallbackQuery, language: Language) -> None:
    await callback.answer(translate(_STALE_KEY, language))


def _frozen_id(draft: MediaDraft) -> UUID | None:
    return UUID(draft.frozen_job) if draft.frozen_job is not None else None


def _aspect_screen(language: Language) -> Screen:
    return Screen(translate(_ASPECT_KEY, language), media_video_aspect_keyboard(language))


def _tier_screen(deps: BotDeps, language: Language, tiers: frozenset[MediaTier]) -> Screen:
    def price(tier: MediaTier) -> str:
        return format_amount(sku_price_minor(deps.settings, SKU_FOR_TIER[tier]) or 0)

    def eta(tier: MediaTier) -> str:
        return translate(_ETA_MINUTES_KEY, language, minutes=_TIER_TYPICAL_MINUTES[tier])

    text = translate(
        _TIER_KEY,
        language,
        eta_std=eta(MediaTier.STANDARD),
        price_std=price(MediaTier.STANDARD),
        eta_fast=eta(MediaTier.FAST),
        price_fast=price(MediaTier.FAST),
    )
    return Screen(text, media_tier_keyboard(language, tiers))


def _voice_screen(deps: BotDeps, language: Language) -> Screen:
    budget = narration_budget(deps.settings, language)
    return Screen(
        translate(_VOICE_PICK_KEY, language, seconds=budget.seconds, words=budget.words),
        media_voice_pick_keyboard(language, BUILT_VOICE_MODES),
    )


def _enter_text_screen(deps: BotDeps, language: Language) -> Screen:
    budget = narration_budget(deps.settings, language)
    return Screen(
        translate(_ENTER_TEXT_KEY, language, words=budget.words),
        media_voice_step_keyboard(language),
    )


def _send_note_screen(deps: BotDeps, language: Language) -> Screen:
    return Screen(
        translate(_SEND_NOTE_KEY, language, seconds=deps.settings.narration_max_seconds),
        media_voice_step_keyboard(language),
    )


def _script_wait_screen(language: Language) -> Screen:
    return Screen(translate(_SCRIPT_WAIT_KEY, language), media_voice_step_keyboard(language))


async def _step_draft(callback: CallbackQuery, state: FSMContext) -> MediaDraft | None:
    """The draft, when the button is on THIS video request's tray and a row was frozen."""
    draft = await tray_draft(callback, state)
    if draft is None:
        return None
    if draft.kind is not MediaKind.VIDEO or draft.frozen_job is None:
        await _stale(callback, draft.ui_language)
        return None
    return draft


async def _message_draft(message: Message, state: FSMContext, deps: BotDeps) -> MediaDraft | None:
    """The draft a message in a voice step belongs to; an unreadable one expires the flow."""
    draft = await read_media_draft(state)
    if draft is None or draft.kind is not MediaKind.VIDEO or draft.frozen_job is None:
        language = await ui_language(state, deps)
        await clear_keeping_identity(state)
        await say(message, translate(_EXPIRED_KEY, language))
        return None
    return draft


async def _show_voice(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps, draft: MediaDraft
) -> None:
    await state.set_state(VideoOrder.voice)
    await write_draft(state, draft)
    await present(callback, _voice_screen(deps, draft.ui_language))


# ---------------------------------------------------------------------------
# Opening a compose, and ✅ Done
# ---------------------------------------------------------------------------
async def start_video(
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
    """A fresh video compose (§2.2): the image's tray, parked in ``VideoOrder.compose``."""
    await start_compose(
        event,
        state,
        deps,
        kind=MediaKind.VIDEO,
        prompt=prompt,
        aspect=aspect,
        refs=refs,
        note_key=note_key,
        is_new_message=is_new_message,
    )


async def handle_done(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """✅ Done on a video tray: freeze a ``drafting`` row and prescreen it (§2.4.1).

    Nothing is frozen for a suspended account, a missing prompt, or while the operator holds
    the GPU (§4.5: ``media.busy``, no row created). The tray reads "checking" BEFORE the
    freeze, because the prescreen edits this same message into the shape screen.
    """
    draft = await tray_draft(callback, state)
    if draft is None:
        return
    language = draft.ui_language
    if await is_suspended(deps, callback.from_user.id):
        await refuse_suspended(callback, state, language)
        return
    if draft.prompt is None:
        await callback.answer(translate(_NEED_PROMPT_KEY, language), show_alert=True)
        return
    if await is_terms_unconfirmed(deps, callback.from_user.id):
        # Fail closed (§2.1, D26): no row, no prescreen; the tray stays for a later ✅.
        await callback.answer(translate(_BUSY_KEY, language), show_alert=True)
        return
    offered = await offered_tiers(deps, callback.from_user.id)
    tiers = await _open_tiers(deps, offered)
    if offered and not tiers:
        # Every tier this account may buy renders on the reserved GPU (§4.5, O11).
        await callback.answer(translate(_BUSY_KEY, language), show_alert=True)
        return
    # The row's SKU is a placeholder until the last voice step (§2.4.1): the first tier
    # still open, so a prescreen never meets a GPU window Fast does not render on.
    placeholder = min(tiers, key=list(MediaTier).index, default=MediaTier.STANDARD)
    desk = deps.media
    price = sku_price_minor(deps.settings, SKU_FOR_TIER[placeholder])
    message = callback.message
    if desk is None or price is None or not isinstance(message, Message) or not offered:
        await _stale(callback, language)
        await clear_keeping_identity(state)
        await present(callback, Screen(translate(_STALE_KEY, language), None))
        return
    await callback.answer()
    await present(callback, Screen(translate(_SCREENING_KEY, language), None))
    frozen = await desk.freeze(
        FreezeRequest(
            telegram_user_id=callback.from_user.id,
            chat_id=message.chat.id,
            tray_message_id=message.message_id,
            kind=MediaKind.VIDEO,
            sku=SKU_FOR_TIER[placeholder],
            # A placeholder until the shape is picked: the last voice step writes the real
            # one (and the tier's SKU and price) onto the row.
            aspect=MediaAspect.PORTRAIT,
            language=language,
            prompt=draft.prompt,
            refs=tuple(InputRef(ref.file_id, ref.file_unique_id) for ref in draft.refs),
            outputs_requested=VIDEO_OUTPUTS,
            price_minor=price,
            currency=deps.settings.kit_currency,
            state=MediaJobState.DRAFTING,
            tier=placeholder,
        )
    )
    if isinstance(frozen, Err):
        # Nothing was written: the tray comes back for another ✅.
        tray = tray_text(draft, deps.settings.media_max_reference_images)
        text = f"{translate(_BUSY_KEY, language)}\n\n{tray}"
        await present(callback, Screen(text, tray_markup(draft)))
        return
    if frozen.value.open_request is not None:
        await clear_keeping_identity(state)
        await show_open_request(callback, frozen.value.open_request, language)
        return
    job_id = frozen.value.job_id
    await write_draft(state, draft.updated(frozen_job=job_id.hex if job_id is not None else None))
    await state.set_state(VideoOrder.aspect)
    _LOG.info(
        "a video draft was frozen",
        extra={"media_job_id": str(job_id), "photos": len(draft.refs)},
    )


# ---------------------------------------------------------------------------
# Shape, tier, voice
# ---------------------------------------------------------------------------
async def handle_aspect(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """The shape. Then the tier screen with two tiers offered, else straight to the voice."""
    draft = await _step_draft(callback, state)
    if draft is None:
        return
    try:
        aspect = ASPECT_FOR_PICK[AspectPick(callback_data.arg)]
    except ValueError:
        await _stale(callback, draft.ui_language)
        return
    await callback.answer()
    draft = draft.updated(aspect=aspect)
    tiers = await _open_tiers(deps, await offered_tiers(deps, callback.from_user.id))
    if len(tiers) >= 2:
        await state.set_state(VideoOrder.tier)
        await write_draft(state, draft)
        await present(callback, _tier_screen(deps, draft.ui_language, tiers))
        return
    # One tier: no screen (§2.4.1). The quote names it — and a reserved GPU there answers
    # ``media.busy`` at the quote, as it always has (§4.5).
    only = next(iter(tiers), MediaTier.STANDARD)
    await _show_voice(callback, state, deps, draft.updated(tier=only))


async def _open_tiers(deps: BotDeps, offered: frozenset[MediaTier]) -> frozenset[MediaTier]:
    """The offered tiers not inside the operator's GPU window (§4.5, O11): with Fast on
    Higgsfield, a reserved GPU closes Standard alone and Fast is still sold (M6.2)."""
    return frozenset(
        [tier for tier in offered if not await is_gpu_reserved(deps, SKU_FOR_TIER[tier])]
    )


async def handle_tier(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    draft = await _step_draft(callback, state)
    if draft is None:
        return
    try:
        tier = MediaTier(callback_data.arg)
    except ValueError:
        await _stale(callback, draft.ui_language)
        return
    if tier not in await offered_tiers(deps, callback.from_user.id):
        await _stale(callback, draft.ui_language)
        return
    await callback.answer()
    await _show_voice(callback, state, deps, draft.updated(tier=tier))


async def handle_voice(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """🔇 finishes; 🗣 and 🤖 ask which voice; 🎙 asks for the note (§2.4.2)."""
    draft = await _step_draft(callback, state)
    if draft is None:
        return
    language = draft.ui_language
    try:
        mode = MediaVoiceMode(callback_data.arg)
    except ValueError:
        await _stale(callback, language)
        return
    if mode not in BUILT_VOICE_MODES:
        await _stale(callback, language)
        return
    await callback.answer()
    draft = draft.updated(voice=mode, narration_text=None, voice_note=None)
    match mode:
        case MediaVoiceMode.NONE:
            await _finalize(callback, state, deps, draft.updated(voice_gender=None))
        case MediaVoiceMode.AI_USER | MediaVoiceMode.AI_LLM:
            await state.set_state(VideoOrder.voice_gender)
            await write_draft(state, draft)
            await present(
                callback,
                Screen(translate(_GENDER_KEY, language), media_voice_gender_keyboard(language)),
            )
        case MediaVoiceMode.OWN:
            await state.set_state(VideoOrder.voice_note)
            await write_draft(state, draft.updated(voice_gender=None))
            await present(callback, _send_note_screen(deps, language))


async def handle_gender(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """The house voice. Then the words: typed (🗣), or written by the worker (🤖)."""
    draft = await _step_draft(callback, state)
    if draft is None:
        return
    language = draft.ui_language
    try:
        gender = MediaVoiceGender(callback_data.arg)
    except ValueError:
        await _stale(callback, language)
        return
    draft = draft.updated(voice_gender=gender)
    if draft.voice is MediaVoiceMode.AI_LLM:
        await _ask_for_script(callback, state, deps, draft)
        return
    await callback.answer()
    await state.set_state(VideoOrder.voice_text)
    await write_draft(state, draft.updated(voice=MediaVoiceMode.AI_USER))
    await present(callback, _enter_text_screen(deps, language))


async def _ask_for_script(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps, draft: MediaDraft
) -> None:
    """``media_script`` for line ``n`` of this draft (§2.4.2, §5.5); the worker edits the tray
    into the line and its buttons. ≤ ``media_script_max_regens`` regenerations per draft."""
    language = draft.ui_language
    job_id = _frozen_id(draft)
    n = draft.script_requests
    if (
        deps.media is None
        or job_id is None
        or draft.voice_gender is None
        or MediaVoiceMode.AI_LLM not in BUILT_VOICE_MODES
        or n > deps.settings.media_script_max_regens
    ):
        await _stale(callback, language)
        return
    asked = await deps.media.request_script(
        job_id, telegram_user_id=callback.from_user.id, voice_gender=draft.voice_gender, n=n
    )
    if isinstance(asked, Err):
        await callback.answer(error_text(asked.error, language), show_alert=True)
        return
    if not asked.value:
        await _stale(callback, language)
        return
    await callback.answer()
    await state.set_state(VideoOrder.script_review)
    await write_draft(state, draft.updated(voice=MediaVoiceMode.AI_LLM, script_requests=n + 1))
    await present(callback, _script_wait_screen(language))


async def handle_script(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """Under an AI-written line: ✅ use it · ✏️ type it yourself (the voice is kept) · 🔄."""
    draft = await _step_draft(callback, state)
    if draft is None:
        return
    language = draft.ui_language
    try:
        pick = ScriptPick(callback_data.arg)
    except ValueError:
        await _stale(callback, language)
        return
    match pick:
        case ScriptPick.ANOTHER:
            await _ask_for_script(callback, state, deps, draft)
        case ScriptPick.EDIT:
            await callback.answer()
            await state.set_state(VideoOrder.voice_text)
            await write_draft(state, draft)
            await present(callback, _enter_text_screen(deps, language))
        case ScriptPick.USE:
            job_id = _frozen_id(draft)
            if deps.media is None or job_id is None:
                await _stale(callback, language)
                return
            loaded = await deps.media.load(job_id)
            if isinstance(loaded, Err):
                await callback.answer(error_text(loaded.error, language), show_alert=True)
                return
            job = loaded.value
            if (
                job is None
                or job.state is not MediaJobState.DRAFTING
                or job.voice_mode is not MediaVoiceMode.AI_LLM
                or not job.narration_text
            ):
                # No line written yet (or no longer this draft's): the wait goes on.
                await callback.answer(translate(_SCRIPT_WAIT_KEY, language))
                return
            await callback.answer()
            await _finalize(callback, state, deps, draft.updated(narration_text=job.narration_text))


# ---------------------------------------------------------------------------
# Messages in the voice steps
# ---------------------------------------------------------------------------
async def handle_voice_text(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """The words an AI voice says: within the language's budget, or ``too_long`` (O14)."""
    draft = await _message_draft(message, state, deps)
    if draft is None:
        return
    language = draft.ui_language
    budget = narration_budget(deps.settings, language)
    text = message.text or ""
    if text.lstrip().startswith("/"):
        # A command the command router did not claim is not words to be spoken.
        await say(message, translate(_ENTER_TEXT_KEY, language, words=budget.words))
        return
    if not fits_budget(text, budget):
        await say(
            message, translate(_TOO_LONG_KEY, language, seconds=budget.seconds, words=budget.words)
        )
        return
    line = normalise_narration(text)
    # Typed words are the customer's, even after ✏️ under a 🤖 line: ``ai_llm`` on the row means
    # the unedited, L3-screened line WE wrote, which a TTS refusal does not strike (§5.5).
    await _finalize(
        message, state, deps, draft.updated(voice=MediaVoiceMode.AI_USER, narration_text=line)
    )


async def handle_voice_in_text_step(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """A voice note where words were asked for: ask again (§2.4.1)."""
    language = await ui_language(state, deps)
    budget = narration_budget(deps.settings, language)
    await say(message, translate(_ENTER_TEXT_KEY, language, words=budget.words))


async def handle_voice_note(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """An own voice note (``F.voice`` only). Longer than the clip by Telegram's own whole
    seconds → refused before anything is written (O14); ffprobe re-checks it (§5.4)."""
    draft = await _message_draft(message, state, deps)
    voice = message.voice
    if draft is None or voice is None:
        return
    language = draft.ui_language
    seconds = deps.settings.narration_max_seconds
    if voice.duration > seconds:
        await say(
            message,
            translate(_NOTE_TOO_LONG_KEY, language, dur=f"{voice.duration:.1f}", seconds=seconds),
        )
        return
    note = MediaVoiceNoteRef(
        file_id=voice.file_id, file_unique_id=voice.file_unique_id, duration=voice.duration
    )
    await _finalize(
        message,
        state,
        deps,
        draft.updated(voice=MediaVoiceMode.OWN, voice_gender=None, voice_note=note),
    )


async def handle_note_wrong_type(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Text, an audio file, a round video — anything but a voice message (§2.4.1)."""
    await say(message, translate(_NOTE_WRONG_TYPE_KEY, await ui_language(state, deps)))


# ---------------------------------------------------------------------------
# The last step: the row goes to screening
# ---------------------------------------------------------------------------
async def _finalize(event: Event, state: FSMContext, deps: BotDeps, draft: MediaDraft) -> None:
    """Write every choice onto the draft row and move it to ``screening`` (§2.4.1).

    Entitlement, tier and price are read again now (§2.5). From a button the tray becomes
    "checking"; from a message (typed words, a voice note) a NEW message does, and becomes
    the row's tray — the one the worker turns into the quote, next to what was just sent.
    """
    language = draft.ui_language
    job_id = _frozen_id(draft)
    user = event.from_user
    tier = draft.tier or MediaTier.STANDARD
    sku = SKU_FOR_TIER[tier]
    price = sku_price_minor(deps.settings, sku)
    if (
        deps.media is None
        or job_id is None
        or user is None
        or price is None
        or draft.aspect is None
        or draft.voice is None
        or tier not in await offered_tiers(deps, user.id)
    ):
        await _stale_screen(event, state, language)
        return
    if await is_terms_unconfirmed(deps, user.id):
        # A voice note joins the row here (§2.1, D26): fail closed, and the step stays open.
        if isinstance(event, CallbackQuery):
            await event.answer(translate(_BUSY_KEY, language), show_alert=True)
        else:
            await say(event, translate(_BUSY_KEY, language))
        return
    screening = Screen(translate(_SCREENING_KEY, language), None)
    tray_id: int | None = None
    if isinstance(event, Message):
        tray_id = (await event.answer(screening.text)).message_id
    else:
        await present(event, screening)
    note = draft.voice_note
    finalized = await deps.media.finalize_video(
        job_id,
        telegram_user_id=user.id,
        choices=VideoChoices(
            aspect=draft.aspect,
            tier=tier,
            sku=sku,
            price_minor=price,
            voice_mode=draft.voice,
            voice_gender=draft.voice_gender,
            narration_text=draft.narration_text,
            voice_note=None
            if note is None
            else VoiceNoteRef(file_id=note.file_id, file_unique_id=note.file_unique_id),
            tray_message_id=tray_id,
        ),
    )
    if isinstance(finalized, Err) or finalized.value is FinalizeOutcome.STALE:
        _LOG.info(
            "a video draft could not be finalised",
            extra={"media_job_id": str(job_id), "error": isinstance(finalized, Err)},
        )
        await _stale_screen(event, state, language)
        return
    voice = draft.voice
    if tray_id is not None:
        draft = draft.updated(tray_message_id=tray_id)
    await write_draft(state, draft)
    await state.set_state(VideoOrder.quote)
    _LOG.info(
        "a video request went to screening",
        extra={"media_job_id": str(job_id), "voice": voice.value, "tier": tier.value},
    )


async def _stale_screen(event: Event, state: FSMContext, language: Language) -> None:
    await clear_keeping_identity(state)
    await present(event, Screen(translate(_STALE_KEY, language), None))


# ---------------------------------------------------------------------------
# ⬅️ and 🎙 record again
# ---------------------------------------------------------------------------
async def handle_back(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """⬅️ along the §2.4.1 back map. Back to compose cancels the draft row: the next ✅
    freezes a new one, screened again."""
    draft = await _step_draft(callback, state)
    if draft is None:
        return
    language = draft.ui_language
    current = await state.get_state()
    await callback.answer()
    if current == VideoOrder.aspect.state:
        job_id = _frozen_id(draft)
        if deps.media is not None and job_id is not None:
            cancelled = await deps.media.cancel(job_id, telegram_user_id=callback.from_user.id)
            if isinstance(cancelled, Err):
                _LOG.warning(
                    "a video draft could not be cancelled", extra={"media_job_id": str(job_id)}
                )
        draft = draft.updated(frozen_job=None, aspect=None, tier=None, voice=None)
        await state.set_state(VideoOrder.compose)
        await write_draft(state, draft)
        await present(
            callback,
            Screen(tray_text(draft, deps.settings.media_max_reference_images), tray_markup(draft)),
        )
        return
    if current == VideoOrder.tier.state:
        await state.set_state(VideoOrder.aspect)
        await present(callback, _aspect_screen(language))
        return
    if current == VideoOrder.voice.state:
        tiers = await _open_tiers(deps, await offered_tiers(deps, callback.from_user.id))
        if len(tiers) >= 2:
            await state.set_state(VideoOrder.tier)
            await present(callback, _tier_screen(deps, language, tiers))
        else:
            await state.set_state(VideoOrder.aspect)
            await present(callback, _aspect_screen(language))
        return
    if current in _BACK_TO_VOICE:
        job_id = _frozen_id(draft)
        if draft.voice is MediaVoiceMode.AI_LLM and deps.media is not None and job_id is not None:
            # Leaving the 🤖 branch: a line still being written must not land on the row or
            # redraw the tray over the voice screen (§2.4.2). Best effort — a line that lands
            # anyway is overwritten or ignored by the next choice.
            left = await deps.media.leave_script(job_id, telegram_user_id=callback.from_user.id)
            if isinstance(left, Err):
                _LOG.warning(
                    "a video draft could not leave the script", extra={"media_job_id": str(job_id)}
                )
        await _show_voice(
            callback, state, deps, draft.updated(narration_text=None, voice_note=None)
        )


async def handle_record_again(
    callback: CallbackQuery, callback_data: MediaCB, state: FSMContext, deps: BotDeps
) -> None:
    """🎙 under ``media.voice_note.too_long`` (§5.4): the SAME draft, back at ``voice_note``.

    Post-freeze and stateless, like every button carrying a job id: the row must be this
    account's video draft (``media_screen`` sent it back to ``drafting``). The FSM draft is
    used when it is this row's; otherwise it is rebuilt from the row.
    """
    language = await ui_language(state, deps)
    job_id = read_job_ref(callback_data.job)
    desk = deps.media
    message = callback.message
    if job_id is None or desk is None or not isinstance(message, Message):
        await _stale(callback, language)
        return
    loaded = await desk.load(job_id)
    if isinstance(loaded, Err):
        await callback.answer(error_text(loaded.error, language), show_alert=True)
        return
    job = loaded.value
    if (
        job is None
        or job.telegram_user_id != callback.from_user.id
        or job.kind is not MediaKind.VIDEO
        or job.state is not MediaJobState.DRAFTING
    ):
        await _stale(callback, language)
        return
    await callback.answer()
    draft = await read_media_draft(state)
    if draft is None or draft.frozen_job != job.id.hex:
        draft = MediaDraft(
            kind=MediaKind.VIDEO,
            session_id=job.id.hex,
            ui_language=job.language,
            prompt=job.prompt,
            aspect=job.aspect,
            tier=job.tier or MediaTier.STANDARD,
            frozen_job=job.id.hex,
        )
    draft = draft.updated(
        voice=MediaVoiceMode.OWN, voice_note=None, tray_message_id=message.message_id
    )
    await state.set_state(VideoOrder.voice_note)
    await write_draft(state, draft)
    await present(callback, _send_note_screen(deps, draft.ui_language))
