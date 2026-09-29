"""The Telegram calls the media stages make, behind one port (IMAGE_VIDEO_SPEC §3.3).

The stage jobs (:mod:`bayram.runtime.media_jobs`) never touch ``aiogram`` directly: they
download an upload, edit the tray, send or edit the progress message, and deliver an album or
a video. Putting those behind :class:`MediaMessenger` keeps the stage tests about the state machine
— a fake records what would have been sent — and keeps the Telegram rules in one place:

* **size is checked twice** on a download (``avatar.py``'s pattern): Telegram's claimed
  ``file_size`` before a byte moves, the bytes on disk after — a claim that turns out to be
  wrong must not decide how much the host stores. The file goes straight to disk
  (``download_file(destination=…)``), never into memory (§3.6);
* **never log a ``file_path``**: with the bot token prefixed it is a live, unauthenticated URL
  to the customer's photo;
* **an edit that changes nothing is a success.** Telegram answers "message is not modified"
  with a 400; the progress frame re-renders from the row and may legitimately be identical;
* **a video over 50 MB goes as a document** (§3.3 ``media_deliver``): ``sendVideo`` takes
  at most 50 MB from a bot, with ``supports_streaming`` and the geometry and duration ffprobe
  measured, so it plays inline;
* **delivery says whether the customer blocked us** (``bot.delivery.is_blocked_by_customer``),
  because that failure is final and must not be retried or refunded as ours.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramRetryAfter,
)
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InputMediaPhoto, Message

from bayram.bot.delivery import BLOCKED_BY_CUSTOMER_KEY, is_blocked_by_customer
from bayram.contracts import Result, err, ok
from bayram.errors import DeliveryError, ValidationError
from bayram.logging import get_logger

__all__ = ["MediaMessenger", "TelegramMediaMessenger", "TOO_LARGE_KEY", "VIDEO_MAX_BYTES"]

_LOG = get_logger(__name__)

#: ``ValidationError.context`` flag on a download refused for its size: the customer's file,
#: not our outage, so the stage refuses the request instead of answering ``busy``.
TOO_LARGE_KEY: Final[str] = "is_too_large"

_NOT_MODIFIED: Final[str] = "message is not modified"

#: The largest file ``sendVideo`` takes from a bot; above it the clip goes by ``sendDocument``
#: (§3.3 ``media_deliver``). A 5 s 720p render is a few megabytes, so this is the edge case.
VIDEO_MAX_BYTES: Final[int] = 50 * 1024 * 1024


@runtime_checkable
class MediaMessenger(Protocol):
    """What the media stages need from Telegram. Nothing here raises."""

    async def download(self, file_id: str, dest: Path, *, max_bytes: int) -> Result[int]:
        """Stream an upload to ``dest``. The byte count, or ``Err`` (size → ``TOO_LARGE_KEY``)."""
        ...

    async def send(
        self, chat_id: int, text: str, markup: InlineKeyboardMarkup | None = None
    ) -> int | None:
        """A new message; its id, or ``None`` when it did not land."""
        ...

    async def edit(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        """Redraw a message in place. True when the screen now shows ``text``."""
        ...

    async def send_photos(
        self, chat_id: int, photos: Sequence[Path], *, caption: str
    ) -> Result[tuple[str, ...]]:
        """One album (``sendMediaGroup``), caption on the first photo — or, for exactly one
        photo, ``sendPhoto``, since an album takes two to ten. The ``file_id`` of each
        photo, in order. ``Err(DeliveryError)`` carries ``BLOCKED_BY_CUSTOMER_KEY`` when the
        customer blocked the bot, and ``is_retryable`` for a failure worth trying again."""
        ...

    async def send_video(
        self,
        chat_id: int,
        video: Path,
        *,
        caption: str,
        width: int | None,
        height: int | None,
        duration_s: float | None,
    ) -> Result[str]:
        """``sendVideo`` (streamable, with the measured geometry), or ``sendDocument`` above
        :data:`VIDEO_MAX_BYTES`. The ``file_id``; errors as :meth:`send_photos`."""
        ...


class TelegramMediaMessenger:
    """:class:`MediaMessenger` over the worker's send-only ``Bot``."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def download(self, file_id: str, dest: Path, *, max_bytes: int) -> Result[int]:
        try:
            file = await self._bot.get_file(file_id)
            if file.file_size is not None and file.file_size > max_bytes:
                return err(_too_large(file.file_size, max_bytes))
            if file.file_path is None:
                return err(DeliveryError("Telegram gave no path for the upload", is_retryable=True))
            dest.parent.mkdir(parents=True, exist_ok=True)
            await self._bot.download_file(file.file_path, destination=dest)
        except TelegramAPIError as exc:
            return err(
                DeliveryError(
                    "the upload could not be fetched from Telegram",
                    is_retryable=True,
                    context={"failure": type(exc).__name__},
                    cause=exc,
                )
            )
        except OSError as exc:
            return err(
                DeliveryError(
                    "the upload could not be written to the workspace",
                    is_retryable=True,
                    context={"failure": type(exc).__name__},
                    cause=exc,
                )
            )
        size = dest.stat().st_size if dest.exists() else 0
        if size > max_bytes:
            # The second ceiling: Telegram's claim was wrong.
            dest.unlink(missing_ok=True)
            return err(_too_large(size, max_bytes))
        if size == 0:
            return err(DeliveryError("the upload downloaded empty", is_retryable=True))
        return ok(size)

    async def send(
        self, chat_id: int, text: str, markup: InlineKeyboardMarkup | None = None
    ) -> int | None:
        try:
            message = await self._bot.send_message(chat_id, text, reply_markup=markup)
        except TelegramAPIError as exc:
            _LOG.warning(
                "a media message could not be sent",
                extra={"chat_id": chat_id, "failure": type(exc).__name__},
            )
            return None
        return message.message_id

    async def edit(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        try:
            await self._bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup
            )
        except TelegramBadRequest as exc:
            if _NOT_MODIFIED in str(exc.message).lower():
                return True
            _LOG.info(
                "a media message could not be edited",
                extra={"chat_id": chat_id, "failure": type(exc).__name__},
            )
            return False
        except TelegramAPIError as exc:
            _LOG.warning(
                "a media message could not be edited",
                extra={"chat_id": chat_id, "failure": type(exc).__name__},
            )
            return False
        return True

    async def send_photos(
        self, chat_id: int, photos: Sequence[Path], *, caption: str
    ) -> Result[tuple[str, ...]]:
        try:
            if len(photos) == 1:
                # ``sendMediaGroup`` takes 2–10 items and answers 400 to one; a partial
                # delivery (Q3: one variant failed to generate) is a single photo.
                single = await self._bot.send_photo(
                    chat_id, FSInputFile(photos[0]), caption=caption
                )
                return ok((_largest_photo_id(single),))
            media = [
                InputMediaPhoto(media=FSInputFile(path), caption=caption if index == 0 else None)
                for index, path in enumerate(photos)
            ]
            sent = await self._bot.send_media_group(chat_id, media=list(media))
        except TelegramAPIError as exc:
            return err(_delivery_error("the media album could not be delivered", exc))
        return ok(tuple(_largest_photo_id(message) for message in sent))

    async def send_video(
        self,
        chat_id: int,
        video: Path,
        *,
        caption: str,
        width: int | None,
        height: int | None,
        duration_s: float | None,
    ) -> Result[str]:
        try:
            size = video.stat().st_size
        except OSError as exc:
            return err(
                DeliveryError(
                    "the video to deliver could not be read",
                    is_retryable=False,
                    context={"failure": type(exc).__name__},
                    cause=exc,
                )
            )
        try:
            if size > VIDEO_MAX_BYTES:
                document = await self._bot.send_document(
                    chat_id, FSInputFile(video), caption=caption
                )
                return ok(document.document.file_id if document.document else "")
            sent = await self._bot.send_video(
                chat_id,
                FSInputFile(video),
                caption=caption,
                width=width,
                height=height,
                duration=max(1, round(duration_s)) if duration_s else None,
                supports_streaming=True,
            )
        except TelegramAPIError as exc:
            return err(_delivery_error("the video could not be delivered", exc))
        return ok(sent.video.file_id if sent.video else "")


def _delivery_error(message: str, exc: TelegramAPIError) -> DeliveryError:
    blocked = is_blocked_by_customer(exc)
    return DeliveryError(
        message,
        # A 400 is the request, not the moment: sending it again changes nothing. Nor does an
        # upload over the Bot API's limit (aiogram raises it as a network error, not a 400).
        is_retryable=not blocked
        and not isinstance(exc, TelegramBadRequest | TelegramEntityTooLarge),
        context={
            BLOCKED_BY_CUSTOMER_KEY: blocked,
            "failure": type(exc).__name__,
            "retry_after": getattr(exc, "retry_after", None)
            if isinstance(exc, TelegramRetryAfter)
            else None,
        },
        cause=exc,
    )


def _largest_photo_id(message: Message) -> str:
    return message.photo[-1].file_id if message.photo else ""


def _too_large(size: int, limit: int) -> ValidationError:
    return ValidationError(
        "the upload is larger than a media input may be",
        context={TOO_LARGE_KEY: True, "bytes": size, "max_bytes": limit},
    )
