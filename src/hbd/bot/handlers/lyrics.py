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
and a failure is a normal outcome, not an error page: they are told, and offered the retry
by name on a ``lyrics_failed_keyboard`` rather than being dropped back on the language
picker to work out for themselves that re-pressing the ticked button is how one retries.

The waiting frame carries a Cancel button, which it did not, and that is not decoration.
``llm_timeout_s`` is forty-five seconds; a screen that can sit still that long with nothing
to press is indistinguishable from a hung bot, and the fallback answered anything typed at
it with "use the buttons above" on a screen that had none. Cancel during the write really
does cancel: the result is dropped on return rather than overwriting a session the user has
already left — see :func:`enter_lyrics_step`.

It is also the first vendor spend in the product, and it happens BEFORE the payment gate,
which is new. Three consequences are handled here rather than left to luck: the session is
parked in ``Wizard.submitting`` while the call is in flight, so nothing the user sends
mid-write can race the result; :data:`MAX_LYRIC_WRITES` bounds how many times one session
may bill the writer at all; and a per-account DAILY budget bounds how many times one person
may, however many sessions they start.

**The two caps are not the same control and neither replaces the other.**
:data:`MAX_LYRIC_WRITES` counts writes on the DRAFT, so it bounds one sitting's rerolls —
and ``handlers.common.reset_to_welcome`` throws the draft away, which is the point of a
fresh start and also the hole: ``/start`` gave the counter back, so the spend a single
person could drive was unbounded. :func:`_has_daily_budget` is the ceiling above it, kept in
a database row that no ``/start`` and no process restart resets. Every other gate in the
product — the payment gate, the credit balance, the in-flight cap — guards the WORKER, which
a person who never presses Confirm never reaches, so this step had no per-person ceiling at
all until that budget landed.
"""

from __future__ import annotations

from typing import Final

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.draft import WizardDraft
from hbd.bot.handlers.balance import show_confirm
from hbd.bot.handlers.common import (
    COMMAND_PREFIX,
    Event,
    error_text,
    expire,
    present,
    read_draft,
    say,
    show_step,
    write_draft,
)
from hbd.bot.i18n import translate
from hbd.bot.keyboards import (
    lyrics_failed_keyboard,
    lyrics_writing_keyboard,
    start_over_keyboard,
)
from hbd.bot.lyrics_entry import parse_typed_lyrics
from hbd.bot.screens import Screen
from hbd.bot.states import Wizard, WizardStep, state_for
from hbd.contracts import Err, LyricDraft, Result
from hbd.logging import get_logger
from hbd.lyric_budget import LyricBudgetVerdict

__all__ = ["build_router", "enter_lyrics_step", "handle_try_again", "MAX_LYRIC_WRITES"]

_LOG = get_logger(__name__)

#: How many times one wizard session may ask the writer for a lyric.
#:
#: This step is the first vendor spend in the whole product AND it sits before the payment
#: gate, which is a combination that did not exist before the preview: anyone who can send
#: ``/start`` can reach it. Five is chosen to be invisible to a real customer — one
#: automatic write plus four rerolls is more than anybody rewrites a birthday song — while
#: turning "hold the button down" from unbounded spend into a bounded one.
#:
#: It is a cap on ONE SITTING and it stays that way. ``reset_to_welcome`` resets it by
#: design, because a fresh start is meant to be a fresh start; the per-person ceiling that
#: a restart must NOT reset is :func:`_has_daily_budget`, which is a row rather than a field
#: on the draft. Two controls, two purposes: this one stops a stuck customer rerolling
#: forever, that one stops a script.
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
    call returned. ``handlers.submitting`` owns that state and answers a message or a stale
    button arriving in it with the truth about what is happening, rather than the
    fallback's "use the buttons above". ``show_step`` sets the real state again on every
    exit path.

    The flip happens BEFORE the writing frame goes up, not after. Presenting is itself an
    await against Telegram, and everything typed inside that window used to land on a live
    ``Wizard.output_language`` — the state the user had come from — which is a narrower
    version of exactly the race the park exists to close.

    That frame carries a Cancel button, so the write really can be abandoned, so the result
    can arrive after the session has moved on. It is dropped when it does. Writing it back
    would resurrect a draft the user cancelled and put a preview on a screen that has
    already said goodbye — and the check is the state itself rather than a flag, because
    Cancel, ``/start`` and expiry all leave ``Wizard.submitting`` and any of the three means
    the same thing here.
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

    brief = brief_result.value
    # AFTER the brief is built, so a draft that cannot produce one costs nobody a write, and
    # BEFORE the writing frame and the vendor call, so a refusal spends nothing at all.
    if not await _has_daily_budget(event, state, deps, draft):
        return

    # Counted on the ATTEMPT, not on success: a failed call is billed too, so a writer that
    # keeps failing must not hand out unlimited retries.
    spent = draft.updated(lyric_writes=draft.lyric_writes + 1)
    await state.set_state(Wizard.submitting)
    # The brief is what proves there is a recipient to name, so the name is taken from it
    # rather than re-narrowed off the draft: ``to_brief`` cannot succeed without one.
    name = brief.recipient.display
    await present(
        event,
        Screen(
            translate("wizard.lyrics.writing", language, name=name),
            lyrics_writing_keyboard(language),
        ),
    )
    written = await deps.content.write_lyrics(brief)
    if await state.get_state() != Wizard.submitting.state:
        _LOG.info("the session left the write before it finished; dropping the result")
        return
    await _show_written(event, state, spent, written)


async def _show_written(
    event: Event, state: FSMContext, draft: WizardDraft, written: Result[LyricDraft]
) -> None:
    """Put up whichever screen the vendor's answer earns. Split out for size only.

    The sequencing above it is unchanged and still load-bearing — this runs after the
    "did the session leave while we were writing?" check, never before it, because a preview
    written into a cancelled session is the one outcome that must not be shown.
    """
    if isinstance(written, Err):
        _LOG.error("the lyric writer failed in the wizard", extra=written.error.to_log_dict())
        await _show_write_failure(event, state, draft)
        return
    lyrics = written.value
    _LOG.info(
        "lyric drafted for preview",
        extra={"sections": len(lyrics.sections), "output_language": str(lyrics.language)},
    )
    await show_step(event, state, draft.updated(lyrics=lyrics), WizardStep.LYRICS)


async def _has_daily_budget(
    event: Event, state: FSMContext, deps: BotDeps, draft: WizardDraft
) -> bool:
    """Charge one write against this account's day. ``False`` means it has already refused.

    Enforcing from the day it merges, never behind ``Settings.credits_enforced``: that flag
    exists so the credit BALANCE can ship dark without turning paying-intent customers away,
    and this refuses abuse rather than customers (D-B). Shipping an abuse rail switched off
    is shipping no rail.

    **Fails OPEN on an unreadable counter**, logged at ERROR. Every customer-facing gate in
    this codebase makes the same call for the same reason — ``handlers.confirm``'s meter
    read, ``bot.gate``'s block check, ``hbd.ratelimit``'s throttle — and here the exposure it
    admits is bounded rather than open-ended: :data:`MAX_LYRIC_WRITES` still caps the sitting
    and the inbound throttle still caps the taps, so a database outage costs a bounded number
    of writer calls. Failing closed would stop every customer at the one step the wizard
    cannot skip, for the duration of a blip that has already broken ordering anyway.

    An update with no ``from_user`` is let through unmetered because there is no account to
    charge — the same first line ``bot.gate._decide`` opens with.
    """
    store = deps.lyric_budget
    user = event.from_user
    if store is None or user is None:
        return True
    claimed = await store.claim_lyric_write(user.id, now=deps.clock())
    if isinstance(claimed, Err):
        _LOG.error(
            "the daily lyric budget could not be counted; the write is allowed through",
            extra=claimed.error.to_log_dict(),
        )
        return True
    verdict = claimed.value
    if verdict.is_allowed:
        return True
    _LOG.warning(
        "daily lyric budget spent; the writer is not called",
        extra={
            "telegram_user_id": user.id,
            "writes_today": verdict.used,
            "limit": verdict.limit,
            "resets_at": verdict.resets_at.isoformat(),
        },
    )
    await _refuse_for_today(event, state, draft, verdict)
    return False


async def _refuse_for_today(
    event: Event, state: FSMContext, draft: WizardDraft, verdict: LyricBudgetVerdict
) -> None:
    """Say no in the shape this particular no actually has. Two shapes, and the split matters.

    A refused REROLL is not a dead end at all: the draft still holds a finished lyric, so the
    customer is put back on the preview with its buttons and can approve the words they
    already have and order the song. Nothing is lost.

    A refused FIRST write is different — the wizard cannot go forward today, and re-arming
    the language buttons (which is what ``show_step`` would do, since ``resolve_step``
    downgrades a lyric-less LYRICS to OUTPUT_LANGUAGE) would offer a button that leads
    straight back to this refusal. That is the dead-end-dressed-as-a-working-screen shape
    this codebase designs against, so the session is cleared and replaced by the reason plus
    the one button that still leads somewhere — exactly what ``handlers.confirm._refuse``
    does with the other refusal only the calendar lifts.

    ``resets_at`` is rendered as a plain ``YYYY-MM-DD``: the day turns over at midnight UTC
    and a full ISO timestamp would put a time zone in front of a fact accurate to the day.
    The template names the LIMIT and not the count, because a refused write still counts and
    ``used`` can therefore exceed it — see :meth:`hbd.lyric_budget.LyricBudgetStore`.
    """
    language = draft.ui_language
    text = translate(
        "wizard.lyrics.budget_spent",
        language,
        limit=verdict.limit,
        resets_at=verdict.resets_at.date().isoformat(),
    )
    if draft.lyrics is not None:
        await say(event, text)
        await show_step(event, state, draft, WizardStep.LYRICS)
        return
    await state.clear()
    await present(event, Screen(text=text, markup=start_over_keyboard(language)))


async def _show_write_failure(event: Event, state: FSMContext, draft: WizardDraft) -> None:
    """Say the writer failed, and name the retry. Never raises.

    A failure used to be a sentence dropped above the language picker, which left "press
    the button that is already ticked" as the retry — undocumented anywhere the customer
    could see it, and indistinguishable from having to answer the question again. The
    screen now says what happened and offers Try again beside Cancel.

    The FSM is still moved to ``Wizard.output_language`` even though that screen is not the
    one on display: it is the step this draft has genuinely got back to, so Try again
    matches, Cancel matches, and a language button on an older message the user scrolls up
    to still works. This does what ``show_step`` does, minus the rendering, because the
    whole point is to show a different screen from the one the step would draw.
    """
    await write_draft(state, draft)
    await state.set_state(state_for(WizardStep.OUTPUT_LANGUAGE))
    await present(
        event,
        Screen(
            translate("wizard.lyrics.failed", draft.ui_language),
            lyrics_failed_keyboard(draft.ui_language),
        ),
    )


async def handle_lyrics_ok(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """These are the words. Nothing is generated or charged until this press.

    ``deps`` is here for one reason: ``show_confirm`` reads the meter so the commit screen
    can say what this song will cost. The read is the same one the Confirm gate makes a tap
    later and it writes nothing — see :mod:`hbd.bot.handlers.balance`.
    """
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_confirm(callback, state, deps, draft)


async def handle_regenerate(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """Ask for a different lyric. Every other answer in the draft is untouched."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await enter_lyrics_step(callback, state, deps, draft)


async def handle_try_again(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """The retry offered by ``lyrics_failed_keyboard``. Same call, one press, no re-answering.

    Bound to ``Wizard.output_language`` because that is where a failed write leaves the
    session — the answer was given, only the vendor call fell over — so this is the same
    thing pressing the language button again did, with a name on it. It is not free:
    ``MAX_LYRIC_WRITES`` counts attempts, failures included, so a writer that is down stops
    handing out retries rather than billing forever.
    """
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    _LOG.info("retrying the lyric write after a failure", extra={"writes": draft.lyric_writes})
    await enter_lyrics_step(callback, state, deps, draft)


async def handle_typed_lyrics(message: Message, state: FSMContext) -> None:
    """A pasted lyric replaces ours. Rejections keep the user on the step, as elsewhere.

    The command guard is the same one the note step carries, and it is needed for the same
    reason: this handler matches ANY text in ``Wizard.lyrics``, so an unrecognised command
    — ``/halp``, ``/stop``, a typo — is claimed by no router before it and would otherwise
    be accepted as the lyric and sung. ``parse_typed_lyrics`` has no opinion about a
    leading slash; only the twenty-character minimum rejected any of them, and by accident.
    Re-showing the step puts the preview and its buttons back rather than leaving the chat
    silent after a command that visibly did nothing.
    """
    draft = await read_draft(state)
    if draft is None:
        await expire(message, state)
        return
    text = (message.text or "").strip()
    if text.startswith(COMMAND_PREFIX):
        _LOG.info("command-shaped text at the lyrics step; not stored", extra={"length": len(text)})
        await show_step(message, state, draft, WizardStep.LYRICS)
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
    router.callback_query.register(
        handle_try_again, Wizard.output_language, NavCB.filter(F.action == NavAction.TRY_AGAIN)
    )
    router.message.register(handle_typed_lyrics, Wizard.lyrics, F.text)
    router.message.register(handle_lyrics_not_typed, Wizard.lyrics)
    return router
