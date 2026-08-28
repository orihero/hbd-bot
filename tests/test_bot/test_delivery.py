"""Delivery: the right method for the right asset, and honest failure when it is not."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from hbd.bot.delivery import MAX_MESSAGE_CHARS, deliver_kit
from hbd.bot.i18n import translate
from hbd.contracts import AssetKind, Err, Kit, Language, LyricSection, Ok
from hbd.errors import ErrorCode
from hbd.pipeline.events import PipelineStage
from hbd.pipeline.outcome import PipelineGap
from tests.conftest import UZBEK_NAME_CANONICAL, make_asset, make_lyrics
from tests.test_bot.conftest import CHAT_ID, RecordingSession


async def deliver(bot: Bot, kit: Kit, **overrides: object) -> object:
    return await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, **overrides)  # type: ignore[arg-type]


async def test_song_goes_out_as_audio(bot: Bot, session: RecordingSession, kit: Kit) -> None:
    # Arrange / Act
    result = await deliver(bot, kit)

    # Assert
    assert isinstance(result, Ok)
    audio = session.last_named("SendAudio")
    assert audio.title == kit.lyrics.title
    assert UZBEK_NAME_CANONICAL in (audio.caption or "")


async def test_greetings_go_out_as_voice_notes(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange / Act
    await deliver(bot, kit)

    # Assert — sendVoice, never sendAudio and never sendDocument
    assert len(session.named("SendVoice")) == len(kit.greetings)
    assert not session.named("SendDocument")


async def test_greeting_in_the_wrong_container_is_refused_rather_than_shipped(
    bot: Bot, session: RecordingSession, kit: Kit, tmp_path: Path
) -> None:
    # Arrange — an MP3 greeting would render as a grey file attachment
    mp3 = make_asset(
        tmp_path,
        path=tmp_path / "greeting-mp3.mp3",
        kind=AssetKind.GREETING,
        mime="audio/mpeg",
        duration_s=30.0,
        persona_id="ovozli-bobo",
    )
    broken = kit.model_copy(update={"greetings": (mp3,)})

    # Act
    result = await deliver(bot, broken)

    # Assert
    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.DELIVERY_FAILED
    assert not session.named("SendVoice")


async def test_lyric_sheet_goes_out_as_text_with_the_display_spelling(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange / Act
    await deliver(bot, kit)

    # Assert
    texts = [call.text for call in session.named("SendMessage")]  # type: ignore[attr-defined]
    assert any(UZBEK_NAME_CANONICAL in text for text in texts)
    assert any(kit.lyrics.title in text for text in texts)


async def test_a_long_lyric_is_split_across_messages(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange
    long_section = LyricSection(label="verse", lines=tuple(["a line of lyric"] * 200))
    lyrics = make_lyrics(sections=(long_section, long_section, long_section))
    big = kit.model_copy(update={"lyrics": lyrics})

    # Act
    await deliver(bot, big)

    # Assert
    sheet_messages = [call for call in session.named("SendMessage") if isinstance(call, SendMessage)]
    assert len(sheet_messages) >= 3
    for message in sheet_messages:
        assert len(message.text) <= MAX_MESSAGE_CHARS


async def test_closing_message_apologises_for_every_gap(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange
    gap = PipelineGap(
        stage=PipelineStage.VERIFYING_NAME,
        error_code=ErrorCode.NAME_UNVERIFIABLE,
        detail="ran out of candidates",
        user_message_key="error.name_pronunciation_best_effort",
    )

    # Act
    await deliver(bot, kit, gaps=(gap,))

    # Assert
    closing = session.named("SendMessage")[-1].text  # type: ignore[attr-defined]
    assert translate("error.name_pronunciation_best_effort", Language.EN) in closing


async def test_missing_file_is_reported_and_does_not_raise(
    bot: Bot, session: RecordingSession, kit: Kit, tmp_path: Path
) -> None:
    # Arrange
    kit.song.path.unlink()

    # Act
    result = await deliver(bot, kit)

    # Assert
    assert isinstance(result, Err)
    assert "missing-file" in str(result.error.context["failures"])
    assert not session.named("SendAudio")


async def test_a_failed_song_still_delivers_the_greetings(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange
    session.failures["SendAudio"] = TelegramForbiddenError(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="bot was blocked"
    )

    # Act
    result = await deliver(bot, kit)

    # Assert — best effort per asset: one failure does not cost the rest
    assert isinstance(result, Err)
    assert session.named("SendVoice")


@pytest.mark.parametrize("language", list(Language))
async def test_captions_are_localised(
    bot: Bot, session: RecordingSession, kit: Kit, language: Language
) -> None:
    # Arrange / Act
    await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=language)

    # Assert
    caption = session.last_named("SendVoice").caption
    assert caption
    assert "delivery.greeting_caption" not in caption


async def test_an_ampersand_heavy_lyric_sheet_stays_inside_the_message_ceiling(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """The sheet is escaped on the way out, so the split has to budget escaped characters.

    A pasted lyric can be almost all ampersands. Each one costs one character in the draft
    and five (``&amp;``) in the message Telegram counts, so a sheet budgeted on the raw text
    sails past 4096, Telegram rejects it, delivery reports a failure and the customer never
    receives the one artefact that shows the words they approved.
    """
    # Arrange — 1280 raw characters, comfortably inside every raw bound we apply
    hostile = LyricSection(label="verse", lines=tuple(["&" * 160] * 8))
    lyrics = make_lyrics(sections=(hostile, *make_lyrics().sections))
    heavy = kit.model_copy(update={"lyrics": lyrics})

    # Act
    await deliver(bot, heavy)

    # Assert
    sheet_messages = [call for call in session.named("SendMessage") if isinstance(call, SendMessage)]
    assert sheet_messages
    for message in sheet_messages:
        assert len(message.text) <= MAX_MESSAGE_CHARS


async def test_an_oversized_block_is_carried_across_parts_rather_than_truncated(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """One verse longer than a message is split, not clipped: a lyric sheet loses nothing."""
    # Arrange — a single block with no blank line in it, well over one message
    marker = "zzmarkerzz"
    single_block = LyricSection(label="verse", lines=(*["a line of lyric"] * 400, marker))
    lyrics = make_lyrics(sections=(single_block,), name_display=UZBEK_NAME_CANONICAL)
    big = kit.model_copy(update={"lyrics": lyrics})

    # Act
    await deliver(bot, big)

    # Assert — the last line of the verse survived somewhere in the sheet
    texts = [call.text for call in session.named("SendMessage") if isinstance(call, SendMessage)]
    assert any(marker in text for text in texts)
