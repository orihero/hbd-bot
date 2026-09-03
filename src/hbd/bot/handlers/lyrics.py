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

**The step has a second entrance, and it spends nothing.** A customer who picked "I will
write the words myself" back at the occasion list arrives here with
``lyrics_source=OWN``, and the step then PROMPTS instead of writing: no vendor call, no
write counted, no daily budget charged. Everything below about caps, budgets, waiting
frames and mid-write races describes the writer's path only, because the other path has
nothing to race and nothing to bound. The two meet again the moment a lyric exists —
approve, confirm and submit are one code path for both, and a pasted lyric has always been
shaped by ``pipeline.lyric_shape.build_lyric_draft`` exactly like a written one, which is
what lets the worker stay unaware of where the words came from.

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
from hbd.bot.states import Wizard, WizardStep, next_step, state_for
from hbd.contracts import Err, LyricDraft, Result
from hbd.logging import get_logger
from hbd.lyric_budget import LyricBudgetVerdict

__all__ = [
    "build_router",
    "enter_lyrics_step",
    "handle_try_again",
    "retagged",
    "MAX_LYRIC_WRITES",
]

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
    if draft.is_own_lyrics:
        # The whole of the bring-your-own path's cost control: there is nothing to control.
        # No vendor call, so no write to count against MAX_LYRIC_WRITES and nothing to
        # charge against the daily budget — the three guards below all exist to bound spend
        # that this branch does not incur. The screen it lands on asks for the words; see
        # ``screens._own_lyrics_prompt_screen`` and, for why a lyric-less LYRICS survives
        # ``resolve_step`` here, ``screens.resolve_step``.
        _LOG.info("the customer is writing this lyric; the writer is not called")
        await show_step(event, state, retagged(draft), WizardStep.LYRICS)
        return

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
    recipient = brief.recipient
    if recipient is None:  # pragma: no cover - the writer's path always has a name
        # Unreachable: this is the writer's branch, and ``to_brief`` requires a recipient
        # unless the draft is on the own-lyrics path, which returned above.
        _LOG.error("the writer was reached with no recipient; refusing to call it")
        await show_step(event, state, draft, WizardStep.OUTPUT_LANGUAGE)
        return
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
    name = recipient.display
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


def retagged(draft: WizardDraft) -> WizardDraft:
    """Carry an already-typed lyric over to a newly chosen output language.

    On the writer's path a language change rewrites the lyric, which is right: a lyric the
    machine wrote in Russian is not the Uzbek one they asked for. For a lyric a PERSON
    typed it would mean deleting their words in order to ask them to type them again, which
    is the one thing this path exists to avoid.

    So the words are kept and only the tag on them moves. That tag is what the composer is
    told to sing in, and it is the only part of a typed lyric the language question was ever
    deciding — the customer already wrote in whatever language they meant to.

    It matters most on the own-lyrics order, where the words are typed at screen two and the
    language is not chosen until screen five: every one of those lyrics is built under a
    provisional tag and needs this on the way to the summary.
    """
    lyrics = draft.lyrics
    language = draft.output_language
    if lyrics is None or language is None or lyrics.language is language:
        return draft
    _LOG.info(
        "carrying the customer's own lyric to a newly chosen output language",
        extra={"from_language": str(lyrics.language), "to_language": str(language)},
    )
    return draft.updated(lyrics=lyrics.model_copy(update={"language": language}))


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
    following = next_step(WizardStep.LYRICS, is_own_lyrics=draft.is_own_lyrics)
    if following is not WizardStep.CONFIRM and following is not None:
        # The own-lyrics order puts the words SECOND, so approving them is not the last act
        # of the wizard there — the genre, the voice and the language are still to come.
        await show_step(callback, state, draft, following)
        return
    await show_confirm(callback, state, deps, draft)


async def handle_regenerate(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """Ask the writer for a lyric. Every other answer in the draft is untouched.

    One action, drawn under two labels and reached from three screens: "write different
    lyrics" above a lyric the bot wrote, and "let the bot write it" both above the
    customer's own words and on the prompt that is waiting for them — see
    ``keyboards.lyrics_keyboard`` for why the label splits and the handler does not.

    It belongs to the WRITER's path and is only ever drawn there. On an own-lyrics draft
    ``enter_lyrics_step`` shows the prompt again rather than calling anybody, which is the
    right answer to a stale button pressed on an old screen: that draft has no recipient, so
    there is nothing to write a lyric about. Changing the source here to force a write is
    what must not happen — it would move the draft onto an order whose NAME step it has
    never seen.
    """
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
    if recipient is None and not draft.is_own_lyrics:
        # The writer's path lost the name under us; the lyric needs it to build a name hook,
        # so we ask for it again rather than sing to nobody. On the own-lyrics path a
        # missing recipient is not a loss — it was never asked for — and the lyric is built
        # without a hook.
        await show_step(message, state, draft, WizardStep.NAME)
        return
    previous = draft.lyrics
    parsed = parse_typed_lyrics(
        message.text or "",
        language=draft.output_language or draft.ui_language,
        name_display=None if recipient is None else recipient.display,
        title=_title_for(draft, previous),
    )
    if isinstance(parsed, Err):
        _LOG.info("pasted lyric rejected", extra=parsed.error.to_log_dict())
        await say(message, error_text(parsed.error, draft.ui_language))
        return
    await say(message, translate("wizard.lyrics.updated", draft.ui_language))
    # ``lyrics_source`` is deliberately NOT touched. It names which wizard ORDER this draft
    # is walking — which steps exist, what Back does, whether a recipient is required — and
    # a customer who pastes over a lyric the bot wrote is still on the writer's path: they
    # answered the note and the name, and their draft has a name hook. Moving them here sent
    # Back to the occasion step and jumped the language question straight to the summary.
    await show_step(message, state, draft.updated(lyrics=parsed.value), WizardStep.LYRICS)


def _title_for(draft: WizardDraft, previous: LyricDraft | None) -> str:
    """What to call this song. The previous title survives a retype; nothing else is invented.

    On the writer's path a first-ever paste is titled with the recipient's display name,
    which is what the generated lyric would have been called. With no recipient there is no
    such default and none is guessed — a title taken from the first line of somebody's poem
    is a guess they never asked for.

    So a nameless lyric gets a localised placeholder instead of ``build_lyric_draft``'s
    ``DEFAULT_TITLE``, which is the Uzbek word "Tabrik" and would otherwise have headlined
    an English customer's summary and captioned their song. They see it on the preview the
    moment they send their words, so it is a visible placeholder rather than a silent one.
    """
    if previous is not None:
        return previous.title
    recipient = draft.recipient
    if recipient is not None:
        return recipient.display
    return translate("wizard.lyrics.untitled", draft.ui_language)


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
