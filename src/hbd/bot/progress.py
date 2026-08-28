"""The live progress message: one message, edited in place, driven by real pipeline events.

There is no timer here and no invented percentage. Every frame is a ``ProgressEvent`` the
orchestrator actually emitted, so what the customer sees is what the run is doing. A stage
that takes ninety seconds shows the same frame for ninety seconds, which is honest; a fake
crawling bar is not.

Two failure rules:

* An edit that Telegram rejects is logged and dropped. A broken progress bar must never
  take down a run that has already cost real money.
* Telegram rejects an edit whose text is unchanged, so an identical frame is never sent.
"""

from __future__ import annotations

from typing import Final

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from hbd.bot.i18n import translate
from hbd.contracts import Language
from hbd.logging import get_logger
from hbd.pipeline.events import PipelineStage, ProgressEvent, ProgressStatus

__all__ = [
    "TelegramProgressSink",
    "render_progress",
    "queued_text",
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
_RETRY_SUFFIX_KEY: Final[str] = "progress.retrying_suffix"
_DEGRADED_SUFFIX_KEY: Final[str] = "progress.degraded_suffix"


def _bar(ratio: float) -> str:
    filled = round(max(0.0, min(1.0, ratio)) * PROGRESS_BAR_WIDTH)
    return FILLED_BLOCK * filled + EMPTY_BLOCK * (PROGRESS_BAR_WIDTH - filled)


def queued_text(language: Language) -> str:
    """The first frame, posted the moment the order is accepted."""
    return f"{_bar(0.0)}\n{translate(_QUEUED_KEY, language)}"


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


def render_progress(event: ProgressEvent, language: Language) -> str:
    """A pure frame renderer: event in, message text out. No I/O, no state."""
    percent = round(event.progress_ratio * _PERCENT)
    headline = _headline(event, language) + _suffix(event, language)
    return f"{_bar(event.progress_ratio)} {percent}%\n{headline}"


class TelegramProgressSink:
    """Edits one Telegram message per order. Satisfies ``hbd.pipeline.events.ProgressSink``.

    Holds exactly one piece of mutable state — the last text it rendered — because the only
    alternative to remembering it is asking Telegram, and Telegram answers "message is not
    modified" with a 400.
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

    @property
    def last_text(self) -> str | None:
        """What is currently on the user's screen, as far as we know."""
        return self._last_text

    async def emit(self, event: ProgressEvent) -> None:
        """Render and push one frame. Never raises."""
        text = render_progress(event, self._language)
        if text == self._last_text:
            return
        try:
            await self._bot.edit_message_text(
                text=text, chat_id=self._chat_id, message_id=self._message_id
            )
        except TelegramAPIError as exc:
            _LOG.warning(
                "progress edit rejected by Telegram",
                extra={
                    "order_id": str(event.order_id),
                    "correlation_id": event.correlation_id,
                    "chat_id": self._chat_id,
                    "message_id": self._message_id,
                    "stage": event.stage.value,
                    "status": event.status.value,
                    "failure": repr(exc),
                },
            )
            return
        self._last_text = text
