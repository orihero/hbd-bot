"""The lyric preview. The step that moved the words from after the payment to before it.

The wizard used to end at a summary: the customer confirmed four answers and a note, paid,
and only then did a worker decide what the song actually said. The one thing they cared
about was the one thing they never saw. Now the wizard writes the lyric itself, shows it,
and only queues the order once the customer has said yes to those exact words — which is
also why ``BotDeps`` carries a ``ContentWriter``.

Three answers are offered to a preview, and all three are equal:

* **approve** — the draft carries the lyric to CONFIRM, and the worker sings it verbatim;
* **regenerate** — throw this one away and ask for another. The brief handed to the writer
  has ``approved_lyrics=None``, or the pipeline would simply hand back what we already had;
* **paste your own** — the step expects text, so a lyric arriving as a plain message
  replaces the draft rather than being treated as a stray reply.

Writing is a live vendor call on the customer's screen, so it gets its own "writing…" frame
and a failure is a normal outcome, not an error page: they are told, and put back on the
previous step where pressing the language button again tries once more.

It is also the first vendor spend in the product, and it happens BEFORE the payment gate,
which is new. Two consequences are handled here rather than left to luck: the session is
parked in ``Wizard.submitting`` while the call is in flight, so nothing the user sends
mid-write can race the result; and :data:`MAX_LYRIC_WRITES` bounds how many times one
session may bill the writer at all.
"""

from __future__ import annotations

from typing import Final

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.draft import WizardDraft
from hbd.bot.handlers.common import (
    Event,
    error_text,
    expire,
    present,
    read_draft,
    say,
    show_step,
)
from hbd.bot.i18n import translate
from hbd.bot.lyrics_entry import parse_typed_lyrics
from hbd.bot.screens import Screen
from hbd.bot.states import Wizard, WizardStep
from hbd.contracts import Err
from hbd.logging import get_logger

__all__ = ["build_router", "enter_lyrics_step", "MAX_LYRIC_WRITES"]

_LOG = get_logger(__name__)

#: How many times one wizard session may ask the writer for a lyric.
#:
#: This step is the first vendor spend in the whole product AND it sits before the payment
#: gate, which is a combination that did not exist before the preview: anyone who can send
#: ``/start`` can reach it, and nothing in this build rate-limits an update. Five is chosen
#: to be invisible to a real customer — one automatic write plus four rerolls is more than
#: anybody rewrites a birthday song — while turning "hold the button down" from unbounded
#: spend into a bounded one. It is a cap, not a rate limit: a real limiter belongs in
#: middleware with configuration behind it, and this is the guard that fits in the draft.
MAX_LYRIC_WRITES: Final[int] = 5


async def enter_lyrics_step(
    event: Event, state: FSMContext, deps: BotDeps, draft: WizardDraft
) -> None:
    """Write a lyric for ``draft`` and put its preview up. Never raises.

    The brief handed to the writer is built from ``draft.updated(lyrics=None)`` on purpose:
    on a regenerate the draft still holds the lyric being replaced, and a brief carrying it
    would make the pipeline's approved-lyric short circuit hand the same words straight
    back.

    The session is parked in ``Wizard.submitting`` for the duration of the vendor call, and
    that is load-bearing rather than tidy. Writing takes seconds, aiogram runs updates as
    concurrent tasks, and the screen this replaces invites the user to send their own words
    as a message — so leaving ``Wizard.lyrics`` live would let a lyric pasted mid-write be
    accepted, confirmed to the customer, and then overwritten by the machine's when the
    call returned. ``Wizard.submitting`` has no wizard handler on it, so a message or a
    second button press during the write is answered by the fallback instead of racing.
    ``show_step`` sets the real state again on every exit path.
    """
    language = draft.ui_language
    if draft.lyric_writes >= MAX_LYRIC_WRITES:
        _LOG.warning(
            "lyric write cap reached; refusing to call the writer again",
            extra={"writes": draft.lyric_writes, "limit": MAX_LYRIC_WRITES},
        )
        await say(event, translate("wizard.lyrics.too_many", language, limit=MAX_LYRIC_WRITES))
        await show_step(event, state, draft, WizardStep.LYRICS)
        return

    brief_result = draft.updated(lyrics=None).to_brief()
    if isinstance(brief_result, Err):
        _LOG.info("cannot write lyrics yet", extra=brief_result.error.to_log_dict())
        await say(event, error_text(brief_result.error, language))
        await show_step(event, state, draft, WizardStep.OUTPUT_LANGUAGE)
        return

    # Counted on the ATTEMPT, not on success: a failed call is billed too, so a writer that
    # keeps failing must not hand out unlimited retries.
    spent = draft.updated(lyric_writes=draft.lyric_writes + 1)
    await present(event, Screen(translate("wizard.lyrics.writing", language)))
    await state.set_state(Wizard.submitting)
    written = await deps.content.write_lyrics(brief_result.value)
    if isinstance(written, Err):
        _LOG.error("the lyric writer failed in the wizard", extra=written.error.to_log_dict())
        await say(event, translate("wizard.lyrics.failed", language))
        await show_step(event, state, spent, WizardStep.OUTPUT_LANGUAGE)
        return

    lyrics = written.value
    _LOG.info(
        "lyric drafted for preview",
        extra={"sections": len(lyrics.sections), "output_language": str(lyrics.language)},
    )
    await show_step(event, state, spent.updated(lyrics=lyrics), WizardStep.LYRICS)


async def handle_lyrics_ok(callback: CallbackQuery, state: FSMContext) -> None:
    """These are the words. Nothing is generated or charged until this press."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(callback, state, draft, WizardStep.CONFIRM)


async def handle_regenerate(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """Ask for a different lyric. Every other answer in the draft is untouched."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await enter_lyrics_step(callback, state, deps, draft)


async def handle_typed_lyrics(message: Message, state: FSMContext) -> None:
    """A pasted lyric replaces ours. Rejections keep the user on the step, as elsewhere."""
    draft = await read_draft(state)
    if draft is None:
        await expire(message, state)
        return
    recipient = draft.recipient
    if recipient is None:
        # Only reachable if storage lost the name under us; the lyric needs it to build a
        # name hook, so we ask for the name again rather than sing to nobody.
        await show_step(message, state, draft, WizardStep.NAME)
        return
    previous = draft.lyrics
    parsed = parse_typed_lyrics(
        message.text or "",
        language=draft.output_language or draft.ui_language,
        name_display=recipient.display,
        title=previous.title if previous is not None else recipient.display,
    )
    if isinstance(parsed, Err):
        _LOG.info("pasted lyric rejected", extra=parsed.error.to_log_dict())
        await say(message, error_text(parsed.error, draft.ui_language))
        return
    await say(message, translate("wizard.lyrics.updated", draft.ui_language))
    await show_step(message, state, draft.updated(lyrics=parsed.value), WizardStep.LYRICS)


async def handle_lyrics_not_typed(message: Message, state: FSMContext) -> None:
    """A voice note or a photo. Lyrics are words, so we ask for words."""
    draft = await read_draft(state)
    if draft is None:
        await expire(message, state)
        return
    _LOG.info("non-text message at the lyrics step", extra={"content_type": message.content_type})
    await say(message, translate("wizard.lyrics.type_only", draft.ui_language))


def build_router() -> Router:
    router = Router(name="lyrics")
    router.callback_query.register(
        handle_lyrics_ok, Wizard.lyrics, NavCB.filter(F.action == NavAction.LYRICS_OK)
    )
    router.callback_query.register(
        handle_regenerate, Wizard.lyrics, NavCB.filter(F.action == NavAction.REGENERATE)
    )
    router.message.register(handle_typed_lyrics, Wizard.lyrics, F.text)
    router.message.register(handle_lyrics_not_typed, Wizard.lyrics)
    return router
