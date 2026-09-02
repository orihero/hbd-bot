"""The live progress message: one message, edited in place, driven by real pipeline events.

There is no timer here and no invented percentage. Every frame is a ``ProgressEvent`` the
orchestrator actually emitted, so what the customer sees is what the run is doing. A stage
that takes ninety seconds shows the same frame for ninety seconds, which is honest; a fake
crawling bar is not.

The one number that is *not* taken verbatim from the event is the ratio: the sink keeps a
high-water mark and never renders less than it has already shown. That is a guard, not a
timer — it invents no progress, it only refuses to un-say progress the customer has
already seen. It exists because ``VERIFYING_NAME`` is announced from inside the composing
stage, so the honest per-event fraction genuinely goes 55 % → 78 % → 67 %, and a bar
running backwards reads as a crash.

Two failure rules:

* An edit that Telegram rejects is logged and dropped. A broken progress bar must never
  take down a run that has already cost real money.
* Telegram rejects an edit whose text is unchanged, so an identical frame is never sent.
"""

from __future__ import annotations

from typing import Final

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from hbd.bot.i18n import translate
from hbd.contracts import Language
from hbd.logging import get_logger
from hbd.pipeline.events import PipelineStage, ProgressEvent, ProgressStatus

__all__ = [
    "TelegramProgressSink",
    "render_progress",
    "queued_text",
    "timed_out_text",
    "PROGRESS_BAR_WIDTH",
    "FILLED_BLOCK",
    "EMPTY_BLOCK",
]

_LOG = get_logger(__name__)

PROGRESS_BAR_WIDTH: Final[int] = 10
FILLED_BLOCK: Final[str] = "▰"
EMPTY_BLOCK: Final[str] = "▱"
_PERCENT: Final[int] = 100

_QUEUED_KEY: Final[str] = "progress.queued"
_DONE_KEY: Final[str] = "progress.done"
_FAILED_KEY: Final[str] = "progress.failed"
_TIMED_OUT_KEY: Final[str] = "progress.timed_out"
_RETRY_SUFFIX_KEY: Final[str] = "progress.retrying_suffix"
_DEGRADED_SUFFIX_KEY: Final[str] = "progress.degraded_suffix"


def _bar(ratio: float) -> str:
    filled = round(max(0.0, min(1.0, ratio)) * PROGRESS_BAR_WIDTH)
    return FILLED_BLOCK * filled + EMPTY_BLOCK * (PROGRESS_BAR_WIDTH - filled)


def _frame(ratio: float, headline: str) -> str:
    """Bar, percentage, headline. The shape of every frame after the first."""
    return f"{_bar(ratio)} {round(max(0.0, min(1.0, ratio)) * _PERCENT)}%\n{headline}"


def queued_text(language: Language, *, name: str) -> str:
    """The first frame, posted the moment the order is accepted.

    It names the recipient because this message is the only thing on screen for minutes,
    and a customer who queued a song for someone should be able to see whose it is.
    """
    return f"{_bar(0.0)}\n{translate(_QUEUED_KEY, language, name=name)}"


def timed_out_text(language: Language, *, ratio: float = 0.0) -> str:
    """The terminal frame for a run the queue killed at its timeout.

    Cancellation produces no ``ProgressEvent`` — there is nothing left to observe — so this
    is the one frame the bot writes without one. The bar stays where the run died rather
    than being pushed to full: nothing finished.
    """
    return _frame(ratio, translate(_TIMED_OUT_KEY, language))


def _headline(event: ProgressEvent, language: Language) -> str:
    if event.status is ProgressStatus.FAILED:
        return translate(_FAILED_KEY, language)
    if event.stage is PipelineStage.DELIVERING and event.status is ProgressStatus.SUCCEEDED:
        return translate(_DONE_KEY, language)
    return translate(event.detail_key, language)


def _suffix(event: ProgressEvent, language: Language) -> str:
    if event.status is ProgressStatus.RETRYING:
        return " " + translate(_RETRY_SUFFIX_KEY, language, attempt=event.attempt + 1)
    if event.status is ProgressStatus.DEGRADED:
        return " " + translate(_DEGRADED_SUFFIX_KEY, language)
    return ""


def render_progress(event: ProgressEvent, language: Language, *, ratio: float | None = None) -> str:
    """A pure frame renderer: event in, message text out. No I/O, no state.

    ``ratio`` overrides the event's own fraction and exists for exactly one caller — the
    sink's monotonic guard. Nobody should pass a ratio they did not derive from events.
    """
    shown = event.progress_ratio if ratio is None else ratio
    headline = _headline(event, language) + _suffix(event, language)
    return _frame(shown, headline)


class TelegramProgressSink:
    """Edits one Telegram message per order. Satisfies ``hbd.pipeline.events.ProgressSink``.

    Holds two pieces of mutable state, both forced on it:

    * the last text it rendered, because the only alternative to remembering it is asking
      Telegram, and Telegram answers "message is not modified" with a 400;
    * the highest ratio it has already shown, because the bar must never run backwards.
    """

    def __init__(
        self,
        bot: Bot,
        *,
        chat_id: int,
        message_id: int,
        language: Language,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._message_id = message_id
        self._language = language
        self._last_text: str | None = None
        self._high_water: float = 0.0

    @property
    def last_text(self) -> str | None:
        """What is currently on the user's screen, as far as we know."""
        return self._last_text

    @property
    def high_water(self) -> float:
        """The furthest the bar has been drawn. Never decreases."""
        return self._high_water

    async def emit(self, event: ProgressEvent) -> None:
        """Render and push one frame. Never raises."""
        self._high_water = max(self._high_water, event.progress_ratio)
        text = render_progress(event, self._language, ratio=self._high_water)
        await self._push(text, event=event)

    async def emit_timed_out(self, *, markup: InlineKeyboardMarkup | None = None) -> None:
        """Draw the terminal frame for a run the queue cancelled. Never raises.

        Called from the job's cancellation handler, where there is no event to render and
        very little time to render it in, so it does exactly one edit and gives up. This
        is the last thing the customer will see, so it takes a keyboard: a progress
        message that stops moving with nothing to press is where people leave.
        """
        await self._push(
            timed_out_text(self._language, ratio=self._high_water), event=None, markup=markup
        )

    async def _push(
        self,
        text: str,
        *,
        event: ProgressEvent | None,
        markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        if text == self._last_text:
            return
        try:
            await self._bot.edit_message_text(
                text=text,
                chat_id=self._chat_id,
                message_id=self._message_id,
                reply_markup=markup,
            )
        except TelegramAPIError as exc:
            _LOG.warning(
                "progress edit rejected by Telegram",
                extra={
                    "order_id": str(event.order_id) if event is not None else None,
                    "correlation_id": event.correlation_id if event is not None else None,
                    "chat_id": self._chat_id,
                    "message_id": self._message_id,
                    "stage": event.stage.value if event is not None else "timed_out",
                    "status": event.status.value if event is not None else "cancelled",
                    "failure": repr(exc),
                },
            )
            return
        self._last_text = text
