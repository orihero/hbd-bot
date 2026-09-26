"""What the bot says while it is actually making the song.

``Wizard.submitting`` used to be a state nothing was parked in for long: the confirm
handler cleared the FSM the moment the order was queued, and for the whole generation
window — ``music_timeout_s`` is 420 seconds across up to four attempts — the session had no
state at all. Anything the customer typed while they waited therefore fell through to
``fallback.handle_stray_message``, which reads "no state" as "no session" and told them,
mid-run, that their session had expired and to send ``/start``. A customer who obeys that
starts a second song. This module is what stands in that gap: the FSM stays parked here
with the order id in its data, and a message or a stale button arriving during the run is
answered with the truth.

The state is deliberately shared with the lyric write — ``handlers.lyrics`` parks here for
the seconds a vendor call is in flight, so that a lyric pasted mid-write cannot race the
machine's. The two are told apart by :data:`ORDER_ID_KEY`: it is written only once an order
has actually been queued, so "an order is in flight" is a fact about the FSM data and not a
guess from the state name. Everything that has to refuse an action while a song is being
made asks :func:`order_in_flight`, never the state alone.

Registered AFTER every step router and BEFORE ``fallback`` — see that module's docstring.
Its handlers match everything, so anything after it is dead code; these two match
everything *in one state*, which is why they have to come first.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bayram.bot.handlers.common import Event, expire, read_draft, say
from bayram.bot.i18n import translate
from bayram.bot.middleware import resolve_language
from bayram.bot.states import Wizard
from bayram.logging import get_logger

__all__ = [
    "build_router",
    "ORDER_ID_KEY",
    "PROGRESS_MESSAGE_ID_KEY",
    "STILL_IN_STUDIO_KEY",
    "remember_submission",
    "order_in_flight",
    "say_still_working",
]

_LOG = get_logger(__name__)

#: FSM-data key holding the id of the order this session is waiting on. Its PRESENCE is the
#: signal that a song is being made.
#:
#: **The whole of the FSM data dict, named, because this comment used to claim there were two
#: keys in it and there are five.** They are: this one; :data:`PROGRESS_MESSAGE_ID_KEY`
#: below, which ``handlers.commands.handle_forget`` writes back when it re-parks an order;
#: ``bayram.bot.draft.DRAFT_KEY``, the wizard session itself; and ``draft.UI_LANGUAGE_KEY`` and
#: ``draft.ONBOARDED_KEY``, added by onboarding. Five distinct string constants, each
#: declared exactly once and imported everywhere else, which is what makes "they cannot
#: collide" a property of the code rather than of somebody having counted correctly.
#:
#: **The last two are not session state and do not die with a session.**
#: ``handlers.common.clear_keeping_identity`` reads them, clears, and writes them back — so
#: a cancellation, an expiry, a credit refusal or a finished flow leaves the customer's
#: language and the fact that they have already given us a number intact. They are identity;
#: everything above them is one run through the wizard. The single exception is
#: ``commands.handle_forget``, whose bare ``state.clear()`` takes the identity too, because
#: returning the account to first-contact state is precisely what that command promises.
ORDER_ID_KEY: Final[str] = "order_id"

#: FSM-data key holding the message the worker is editing its progress frames into. Kept
#: because a session that outlives its own progress message is a session nobody can find
#: their way back to, and an operator reading a log wants both ids together.
PROGRESS_MESSAGE_ID_KEY: Final[str] = "progress_message_id"

#: Said while the studio has the order. Takes the recipient's name.
QUEUED_KEY: Final[str] = "wizard.queued"

#: Said while the lyric writer has the brief. Also takes the recipient's name, and is the
#: honest answer in that window: nothing is in the studio yet.
WRITING_KEY: Final[str] = "wizard.lyrics.writing"

#: The same fact as :data:`QUEUED_KEY` with no ``{name}`` in it, for the windows where an
#: order is genuinely in flight and there is no draft left to name it with — after
#: ``/forget``, or with a draft that no longer parses.
#:
#: It exists because the alternative every caller used to reach for was ``expire``, which
#: CLEARS the session. Expiring a session that is waiting on a running order is how the bot
#: came to answer the next Cancel with "nothing was made, and nothing was kept" about a song
#: that was minutes from arriving. Saying less is fine; un-parking a live order is not.
STILL_IN_STUDIO_KEY: Final[str] = "wizard.still_in_studio"


async def remember_submission(
    state: FSMContext, *, order_id: UUID, progress_message_id: int
) -> None:
    """Park the session on the order it is waiting for. Leaves the draft untouched."""
    await state.update_data(
        {ORDER_ID_KEY: str(order_id), PROGRESS_MESSAGE_ID_KEY: progress_message_id}
    )


async def order_in_flight(state: FSMContext) -> str | None:
    """The id of the order being made right now, or ``None`` when nothing is.

    Both halves are required. The state name alone is true during a lyric write, when
    nothing has been ordered and Cancel still means what it says; the data key alone would
    survive a reset that cleared the state but not the dict, which storage never does but
    which no caller should have to reason about.
    """
    if await state.get_state() != Wizard.submitting.state:
        return None
    order_id = (await state.get_data()).get(ORDER_ID_KEY)
    return order_id if isinstance(order_id, str) else None


async def say_still_working(event: Event, state: FSMContext, key: str) -> bool:
    """Say ``key`` with the recipient's name in it.

    ``False`` when the draft is gone and there is no name to say it with — every key that
    belongs on this path takes ``{name}``, and rendering the placeholder itself at a
    customer is worse than admitting the session is unreadable. The caller decides what to
    do instead; it is never nothing.
    """
    draft = await read_draft(state)
    recipient = draft.recipient if draft is not None else None
    if draft is None or recipient is None:
        return False
    await say(event, translate(key, draft.ui_language, name=recipient.display))
    return True


async def _answer_or_expire(event: Event, state: FSMContext) -> None:
    """Tell them where their song is, with the name if there is one and without it if not.

    Expiry is reachable only when NO order is in flight. With one in flight the session is
    not expired, whatever the draft looks like — it is waiting on a job that is going to
    deliver into this chat — and clearing it here would leave the next Cancel free to claim
    nothing was made.
    """
    order_id = await order_in_flight(state)
    if await say_still_working(event, state, QUEUED_KEY if order_id else WRITING_KEY):
        return
    if order_id is not None:
        _LOG.info(
            "no draft left to name the wait with; answering without the name",
            extra={"order_id": order_id},
        )
        await say(event, translate(STILL_IN_STUDIO_KEY, await resolve_language(state)))
        return
    _LOG.info("nothing arrived to name the wait with; treating the session as expired")
    await expire(event, state)


async def handle_message_while_working(message: Message, state: FSMContext) -> None:
    """Typed text during a run. The one thing it must never say is "expired"."""
    _LOG.info(
        "message received while the session is working",
        extra={"content_type": message.content_type},
    )
    await _answer_or_expire(message, state)


async def handle_button_while_working(callback: CallbackQuery, state: FSMContext) -> None:
    """A button from an older screen, pressed during a run.

    The nav buttons never reach here — ``handlers.navigation`` is registered earlier and
    refuses them with a message of its own. This is for the rest: an occasion, a genre, a
    language from a screen the wizard has long moved past. The screen it came from is left
    exactly as it is, because editing it would replace a frame the worker may be about to
    write a progress update into.
    """
    await callback.answer()
    _LOG.info("button pressed while the session is working", extra={"data": callback.data})
    await _answer_or_expire(callback, state)


def build_router() -> Router:
    router = Router(name="submitting")
    router.message.register(handle_message_while_working, Wizard.submitting)
    router.callback_query.register(handle_button_while_working, Wizard.submitting)
    return router
