"""Sending the finished kit. The last hundred metres, where a container mistake shows.

Three rules, each of which is a product bug if broken:

* the song goes out with ``sendAudio`` so it gets a player, a title and a duration;
* every greeting goes out with ``sendVoice``, which **requires OGG/Opus** — hand it an MP3
  and Telegram renders a grey file attachment instead of a voice note, so a greeting whose
  mime is wrong is refused the voice path and logged loudly rather than shipped ugly;
* the lyric sheet goes out as TEXT, typeset by us, carrying the DISPLAY spelling with its
  ``ʻ`` intact — it is the one artefact where the orthography is visible.

Delivery is best-effort per asset: a greeting that fails does not cost the customer the
song. Every failure is collected and returned as one ``Err`` after everything sendable has
been sent.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from hbd.bot.i18n import translate
from hbd.contracts import GeneratedAsset, Kit, Language, Result, err, ok
from hbd.errors import DeliveryError
from hbd.logging import get_logger
from hbd.pipeline.outcome import PipelineGap

__all__ = ["deliver_kit", "VOICE_NOTE_MIMES", "MAX_MESSAGE_CHARS"]

_LOG = get_logger(__name__)

#: ``sendVoice`` accepts exactly these. Anything else becomes a file attachment.
VOICE_NOTE_MIMES: Final[frozenset[str]] = frozenset(
    {"audio/ogg", "audio/opus", "audio/ogg; codecs=opus"}
)

#: Telegram's per-message limit. The lyric sheet is split on blank lines below it.
MAX_MESSAGE_CHARS: Final[int] = 4_096


async def deliver_kit(
    bot: Bot,
    *,
    chat_id: int,
    kit: Kit,
    language: Language,
    gaps: Sequence[PipelineGap] = (),
) -> Result[None]:
    """Send song, greetings, lyric sheet and the closing message. Never raises."""
    failures: list[str] = []

    failures.extend(await _send_song(bot, chat_id=chat_id, kit=kit, language=language))
    failures.extend(await _send_greetings(bot, chat_id=chat_id, kit=kit, language=language))
    failures.extend(await _send_lyric_sheet(bot, chat_id=chat_id, kit=kit, language=language))
    failures.extend(
        await _send_closing(bot, chat_id=chat_id, kit=kit, language=language, gaps=gaps)
    )

    if failures:
        return err(
            DeliveryError(
                "one or more kit assets could not be delivered",
                context={
                    "order_id": str(kit.order_id),
                    "chat_id": chat_id,
                    "failures": failures,
                },
            )
        )
    return ok(None)


async def _send_song(bot: Bot, *, chat_id: int, kit: Kit, language: Language) -> tuple[str, ...]:
    caption = translate(
        "delivery.song_caption", language, title=kit.lyrics.title, name=kit.lyrics.name_display
    )
    missing = _missing_file(kit.song)
    if missing is not None:
        return (missing,)
    try:
        await bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(kit.song.path),
            caption=caption,
            title=kit.lyrics.title,
            duration=int(kit.song.duration_s),
        )
    except TelegramAPIError as exc:
        return (_log_failure("song", kit, exc),)
    return ()


async def _send_greetings(
    bot: Bot, *, chat_id: int, kit: Kit, language: Language
) -> tuple[str, ...]:
    failures: list[str] = []
    total = len(kit.greetings)
    for index, greeting in enumerate(kit.greetings, start=1):
        caption = translate("delivery.greeting_caption", language, index=index, total=total)
        failure = await _send_one_greeting(
            bot, chat_id=chat_id, kit=kit, greeting=greeting, caption=caption
        )
        if failure is not None:
            failures.append(failure)
    return tuple(failures)


async def _send_one_greeting(
    bot: Bot, *, chat_id: int, kit: Kit, greeting: GeneratedAsset, caption: str
) -> str | None:
    missing = _missing_file(greeting)
    if missing is not None:
        return missing
    if greeting.mime not in VOICE_NOTE_MIMES:
        _LOG.error(
            "greeting is not OGG/Opus; sendVoice would render it as a file attachment",
            extra={
                "order_id": str(kit.order_id),
                "persona_id": greeting.persona_id,
                "mime": greeting.mime,
                "path": str(greeting.path),
                "accepted": sorted(VOICE_NOTE_MIMES),
            },
        )
        return f"greeting:{greeting.persona_id}:wrong-container:{greeting.mime}"
    try:
        await bot.send_voice(
            chat_id=chat_id,
            voice=FSInputFile(greeting.path),
            caption=caption,
            duration=int(greeting.duration_s),
        )
    except TelegramAPIError as exc:
        return _log_failure(f"greeting:{greeting.persona_id}", kit, exc)
    return None


async def _send_lyric_sheet(
    bot: Bot, *, chat_id: int, kit: Kit, language: Language
) -> tuple[str, ...]:
    """The lyric sheet is text, not a file: it must be readable in the chat itself."""
    body = kit.lyrics.as_plain_text()
    failures: list[str] = []
    for part, chunk in enumerate(_split_for_telegram(body), start=1):
        text = translate("delivery.lyric_sheet", language, title=kit.lyrics.title, body=chunk)
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except TelegramAPIError as exc:
            failures.append(_log_failure(f"lyric_sheet:part-{part}", kit, exc))
    return tuple(failures)


async def _send_closing(
    bot: Bot,
    *,
    chat_id: int,
    kit: Kit,
    language: Language,
    gaps: Sequence[PipelineGap],
) -> tuple[str, ...]:
    lines = [translate("delivery.done", language, name=kit.lyrics.name_display)]
    lines.extend(translate(gap.user_message_key, language) for gap in gaps)
    try:
        await bot.send_message(chat_id=chat_id, text="\n\n".join(lines))
    except TelegramAPIError as exc:
        return (_log_failure("closing", kit, exc),)
    return ()


def _missing_file(asset: GeneratedAsset) -> str | None:
    path: Path = asset.path
    if path.exists():
        return None
    _LOG.error(
        "asset file is missing at delivery time",
        extra={"kind": asset.kind.value, "path": str(path), "persona_id": asset.persona_id},
    )
    return f"{asset.kind.value}:missing-file"


def _log_failure(label: str, kit: Kit, exc: TelegramAPIError) -> str:
    _LOG.error(
        "Telegram rejected an asset",
        extra={"order_id": str(kit.order_id), "asset": label, "failure": repr(exc)},
    )
    return f"{label}:{type(exc).__name__}"


def _split_for_telegram(body: str) -> tuple[str, ...]:
    """Split on blank lines so a verse is never cut in half. Never returns empty."""
    budget = MAX_MESSAGE_CHARS // 2
    blocks = body.split("\n\n") if body else [""]
    parts: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= budget or not current:
            current = candidate[:budget]
            continue
        parts.append(current)
        current = block[:budget]
    parts.append(current)
    return tuple(parts)
