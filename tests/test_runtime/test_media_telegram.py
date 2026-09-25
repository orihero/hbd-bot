"""The media messenger's Telegram rules (IMAGE_VIDEO_SPEC §3.3): an album's file ids come back
in order, an unchanged edit is a success, a blocked customer is told apart, and a download is
refused on Telegram's claimed size before a byte moves."""

from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import EditMessageText, SendMediaGroup, SendPhoto
from aiogram.types import Chat, File, Message, PhotoSize

from bayram.bot.delivery import BLOCKED_BY_CUSTOMER_KEY
from bayram.contracts import is_err, is_ok
from bayram.runtime.media_telegram import TOO_LARGE_KEY, TelegramMediaMessenger
from tests.test_bot.conftest import CHAT_ID, FIXED_MOMENT, RecordingSession


def _photo_message(message_id: int, file_id: str) -> Message:
    return Message(
        message_id=message_id,
        date=FIXED_MOMENT,
        chat=Chat(id=CHAT_ID, type="private"),
        photo=[
            PhotoSize(file_id=f"{file_id}-small", file_unique_id="s", width=90, height=160),
            PhotoSize(file_id=file_id, file_unique_id="l", width=768, height=1344),
        ],
    )


async def test_an_album_answers_the_largest_file_id_of_each_photo(
    bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    session.responses["SendMediaGroup"] = [_photo_message(1, "big-a"), _photo_message(2, "big-b")]
    photos = []
    for name in ("a.jpg", "b.jpg"):
        path = tmp_path / name
        path.write_bytes(b"\xff\xd8fake")
        photos.append(path)

    sent = await TelegramMediaMessenger(bot).send_photos(CHAT_ID, photos, caption="made")

    assert is_ok(sent) and sent.value == ("big-a", "big-b")
    call = session.last_named("SendMediaGroup")
    assert isinstance(call, SendMediaGroup)
    assert [item.caption for item in call.media] == ["made", None]


async def test_a_blocked_customer_is_reported_as_final(bot: Bot, session: RecordingSession) -> None:
    session.failures["SendMediaGroup"] = TelegramForbiddenError(
        method=SendMediaGroup(chat_id=CHAT_ID, media=[]),
        message="Forbidden: bot was blocked by the user",
    )

    sent = await TelegramMediaMessenger(bot).send_photos(CHAT_ID, [], caption="x")

    assert is_err(sent)
    assert sent.error.context[BLOCKED_BY_CUSTOMER_KEY] is True
    assert sent.error.is_retryable is False


async def test_an_edit_that_changes_nothing_is_a_success(
    bot: Bot, session: RecordingSession
) -> None:
    session.failures["EditMessageText"] = TelegramBadRequest(
        method=EditMessageText(text="x", chat_id=CHAT_ID, message_id=5),
        message="Bad Request: message is not modified",
    )

    assert await TelegramMediaMessenger(bot).edit(CHAT_ID, 5, "x") is True


async def test_a_download_larger_than_claimed_is_refused_before_it_moves(
    bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    session.responses["GetFile"] = File(
        file_id="f", file_unique_id="u", file_size=30 * 1024 * 1024, file_path="photos/f.jpg"
    )
    session.files["photos/f.jpg"] = b"x"

    downloaded = await TelegramMediaMessenger(bot).download(
        "f", tmp_path / "raw", max_bytes=20 * 1024 * 1024
    )

    assert is_err(downloaded) and downloaded.error.context[TOO_LARGE_KEY] is True
    assert not (tmp_path / "raw").exists()


async def test_a_download_lands_on_disk(
    bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    session.responses["GetFile"] = File(
        file_id="f", file_unique_id="u", file_size=4, file_path="photos/f.jpg"
    )
    session.files["photos/f.jpg"] = b"\xff\xd8ok"

    downloaded = await TelegramMediaMessenger(bot).download("f", tmp_path / "raw", max_bytes=100)

    assert is_ok(downloaded) and downloaded.value == 4
    assert (tmp_path / "raw").read_bytes() == b"\xff\xd8ok"


async def test_a_single_photo_goes_as_send_photo_never_a_one_item_album(
    bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    # Q3: one variant failed to generate. sendMediaGroup takes 2-10 items and 400s on one.
    session.responses["SendPhoto"] = _photo_message(1, "only")
    path = tmp_path / "a.jpg"
    path.write_bytes(b"\xff\xd8fake")

    sent = await TelegramMediaMessenger(bot).send_photos(CHAT_ID, [path], caption="made")

    assert is_ok(sent) and sent.value == ("only",)
    call = session.last_named("SendPhoto")
    assert isinstance(call, SendPhoto) and call.caption == "made"
    assert not [c for c in session.calls if isinstance(c, SendMediaGroup)]


async def test_a_bad_request_is_not_retried(
    bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    session.failures["SendMediaGroup"] = TelegramBadRequest(
        method=SendMediaGroup(chat_id=CHAT_ID, media=[]), message="Bad Request: too few media"
    )
    photos = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
    for path in photos:
        path.write_bytes(b"\xff\xd8fake")

    sent = await TelegramMediaMessenger(bot).send_photos(CHAT_ID, photos, caption="x")

    assert is_err(sent) and sent.error.is_retryable is False
