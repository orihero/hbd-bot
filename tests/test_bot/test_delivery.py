"""Delivery: the right method for the right asset, and honest failure when it is not."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.delivery import (
    MAX_MESSAGE_CHARS,
    DeliveryLedger,
    deliver_kit,
    order_reference,
)
from hbd.bot.i18n import translate
from hbd.contracts import AssetKind, Err, Kit, Language, LyricSection, Ok
from hbd.errors import ErrorCode
from hbd.pipeline.events import PipelineStage
from hbd.pipeline.outcome import PipelineGap
from tests.conftest import UZBEK_NAME_CANONICAL, make_asset, make_lyrics
from tests.test_bot.conftest import CHAT_ID, RecordingSession, buttons


async def deliver(bot: Bot, kit: Kit, **overrides: object) -> object:
    return await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, **overrides)  # type: ignore[arg-type]


def closing_of(session: RecordingSession) -> Any:
    """The last thing the customer read. Always a ``SendMessage``, always last."""
    return session.named("SendMessage")[-1]


def name_gap(stage: PipelineStage = PipelineStage.VERIFYING_NAME) -> PipelineGap:
    return PipelineGap(
        stage=stage,
        error_code=ErrorCode.NAME_UNVERIFIABLE,
        detail="ran out of candidates",
        user_message_key="error.name_pronunciation_best_effort",
    )


def greeting_gap(index: int) -> PipelineGap:
    return PipelineGap(
        stage=PipelineStage.RENDERING_GREETINGS,
        error_code=ErrorCode.AUDIO_FAILED,
        detail=f"greeting {index} was not rendered",
        user_message_key="error.provider_generic",
    )


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
    sheet_messages = [
        call for call in session.named("SendMessage") if isinstance(call, SendMessage)
    ]
    assert len(sheet_messages) >= 3
    for message in sheet_messages:
        assert len(message.text) <= MAX_MESSAGE_CHARS


async def test_a_split_lyric_sheet_numbers_its_parts(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """Three identical ``📄 <b>Title</b>`` headings read as the same message sent thrice."""
    # Arrange
    long_section = LyricSection(label="verse", lines=tuple(["a line of lyric"] * 200))
    lyrics = make_lyrics(sections=(long_section, long_section, long_section))
    big = kit.model_copy(update={"lyrics": lyrics})

    # Act
    await deliver(bot, big)

    # Assert — every part says which one it is, out of how many
    sheets = [
        call.text
        for call in session.named("SendMessage")
        if isinstance(call, SendMessage) and lyrics.title in (call.text or "")
    ]
    total = len(sheets)
    assert total >= 3
    for part, text in enumerate(sheets, start=1):
        assert f"{part}/{total}" in text


async def test_a_lyric_sheet_that_fits_one_message_is_not_numbered(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """ "1/1" on a message with nothing to compare it to is noise."""
    # Arrange / Act
    await deliver(bot, kit)

    # Assert
    sheet = next(
        call.text
        for call in session.named("SendMessage")
        if isinstance(call, SendMessage) and kit.lyrics.title in (call.text or "")
    )
    assert "1/1" not in sheet
    assert sheet == translate(
        "delivery.lyric_sheet",
        Language.EN,
        title=kit.lyrics.title,
        body=kit.lyrics.as_plain_text(),
    )


async def test_closing_message_apologises_for_every_gap(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange / Act
    await deliver(bot, kit, gaps=(name_gap(), greeting_gap(2)))

    # Assert
    closing = closing_of(session).text
    assert translate("gap.name_best_effort", Language.EN) in closing
    assert translate("gap.greeting_missing", Language.EN) in closing


async def test_a_gap_notice_never_asks_the_customer_to_try_a_delivered_song_again(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """``gap.user_message_key`` points at failure-screen copy. This message is a SUCCESS.

    ``error.name_pronunciation_best_effort`` and its neighbours all end in some variant of
    "please try again", which under a delivered song is both a lie and an invitation to
    burn a second generation for nothing.
    """
    # Arrange / Act
    await deliver(bot, kit, gaps=(name_gap(),))

    # Assert
    closing = closing_of(session).text
    assert translate("error.name_pronunciation_best_effort", Language.EN) not in closing
    assert "try again" not in closing.lower()


async def test_a_clean_run_closes_on_the_undegraded_message(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange / Act
    await deliver(bot, kit)

    # Assert — the whole message, with nothing appended: there was nothing to apologise for
    assert closing_of(session).text == translate(
        "delivery.done",
        Language.EN,
        name=kit.lyrics.name_display,
        order_ref=order_reference(kit.order_id),
    )


async def test_a_run_with_gaps_leads_with_the_apology_not_the_celebration(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """The run did not do what it promised, so the message says so before anything else."""
    # Arrange / Act
    await deliver(bot, kit, gaps=(name_gap(),))

    # Assert — the degraded lead is the FIRST paragraph, the gap sentence comes after it
    closing = closing_of(session).text
    lead, _, rest = closing.partition("\n\n")
    assert "⚠️" in lead
    assert translate("gap.name_best_effort", Language.EN) in rest


async def test_the_same_gap_twice_is_disclosed_once(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """Three greetings lost to three different vendor reasons is one hole to the customer."""
    # Arrange / Act
    await deliver(bot, kit, gaps=(greeting_gap(1), greeting_gap(2), greeting_gap(3)))

    # Assert
    closing = closing_of(session).text
    assert closing.count(translate("gap.greeting_missing", Language.EN)) == 1


async def test_the_closing_message_carries_a_way_onward(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """The emotional peak of the product must not end on a typed command."""
    # Arrange / Act
    await deliver(bot, kit)

    # Assert
    payloads = {data for _text, data in buttons(closing_of(session).reply_markup)}
    assert NavCB(action=NavAction.MAKE_ANOTHER).pack() in payloads
    assert NavCB(action=NavAction.REPORT_PROBLEM).pack() in payloads


async def test_the_closing_message_quotes_a_reference_support_can_reproduce(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange / Act
    await deliver(bot, kit, gaps=(name_gap(),))

    # Assert — the leading characters of the order id, exactly as every log line prints it
    reference = order_reference(kit.order_id)
    assert reference in closing_of(session).text
    assert str(kit.order_id).startswith(reference)


async def test_the_audio_is_never_buried_under_the_text(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """Forwarding the audio message is this product's only distribution; there is no link."""
    # Arrange / Act
    await deliver(bot, kit)

    # Assert
    assert session.call_names.index("SendAudio") < session.call_names.index("SendMessage")


# ---------------------------------------------------------------------------
# Redelivery — the ARQ retry that must not send the kit twice
# ---------------------------------------------------------------------------
async def test_a_retry_sends_only_what_did_not_land_the_first_time(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """One rate-limited text must not cost the customer a second copy of everything.

    ``deliver_kit`` returning ``Err`` becomes an ARQ retry, and the orchestrator's replay
    hands that retry the same kit rather than making a new one.
    """
    # Arrange — every text send fails, so the song and greetings land and nothing else does
    ledger = DeliveryLedger()
    session.failures["SendMessage"] = TelegramBadRequest(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="Too Many Requests"
    )
    first = await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, ledger=ledger)
    assert isinstance(first, Err)

    # Act — the retry, with the outage over
    session.failures.clear()
    session.clear()
    second = await deliver_kit(
        bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, gaps=(name_gap(),), ledger=ledger
    )

    # Assert
    assert isinstance(second, Ok)
    assert not session.named("SendAudio")
    assert not session.named("SendVoice")
    assert session.named("SendMessage")


async def test_a_redelivered_closing_message_still_carries_the_disclosure(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """The bug this pins: the second closing message used to drop the gap notice entirely."""
    # Arrange
    ledger = DeliveryLedger()
    session.failures["SendMessage"] = TelegramBadRequest(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="Too Many Requests"
    )
    await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, ledger=ledger)
    session.failures.clear()
    session.clear()

    # Act
    await deliver_kit(
        bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, gaps=(name_gap(),), ledger=ledger
    )

    # Assert
    assert translate("gap.name_best_effort", Language.EN) in closing_of(session).text


async def test_a_retry_of_a_delivery_that_fully_landed_sends_nothing(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange
    ledger = DeliveryLedger()
    await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, ledger=ledger)
    session.clear()

    # Act
    result = await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, ledger=ledger)

    # Assert
    assert isinstance(result, Ok)
    assert session.calls == []


async def test_two_orders_do_not_share_delivery_state(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """The ledger is keyed by order. A second customer's song is not somebody else's."""
    # Arrange
    ledger = DeliveryLedger()
    await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, ledger=ledger)
    session.clear()
    other = kit.model_copy(update={"order_id": uuid4()})

    # Act
    await deliver_kit(bot, chat_id=CHAT_ID, kit=other, language=Language.EN, ledger=ledger)

    # Assert
    assert session.named("SendAudio")
    assert len(session.named("SendVoice")) == len(other.greetings)


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
    sheet_messages = [
        call for call in session.named("SendMessage") if isinstance(call, SendMessage)
    ]
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
