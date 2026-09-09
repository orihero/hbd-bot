"""Delivery: the right method for the right asset, and honest failure when it is not."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage, TelegramMethod

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.delivery import (
    BLOCKED_BY_CUSTOMER_KEY,
    MAX_CAPTION_CHARS,
    MAX_MESSAGE_CHARS,
    DeliveryLedger,
    _fit_caption,
    deliver_kit,
    order_reference,
)
from hbd.bot.i18n import escape_html, translate
from hbd.contracts import AssetKind, Err, Kit, Language, LyricSection, Ok
from hbd.errors import ErrorCode
from hbd.pipeline.events import PipelineStage
from hbd.pipeline.outcome import PipelineGap
from hbd.watermark import WATERMARK_HANDLE
from tests.conftest import UZBEK_NAME_CANONICAL, make_asset, make_lyrics
from tests.test_bot.conftest import CHAT_ID, RecordingSession, buttons


async def deliver(bot: Bot, kit: Kit, **overrides: object) -> object:
    return await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, **overrides)  # type: ignore[arg-type]


def watermark(key: str, language: Language = Language.EN) -> str:
    """The rendered watermark line, read the way delivery reads it.

    Asserted against instead of a raw ``"@hbduzbot"`` literal so that rewording
    ``watermark.song`` in a catalogue moves the test with the copy, and so a locale that
    silently lost the key fails here rather than shipping an unmarked song.
    """
    return translate(key, language, handle=WATERMARK_HANDLE)


def fail_once(session: RecordingSession, method: str, error: Exception) -> None:
    """Arm ``method`` to be rejected exactly once, then let the next attempt through.

    ``RecordingSession.failures`` is a standing arrangement: whatever is registered under a
    method name raises on EVERY call to it, which cannot express the one thing the branded
    ``sendAudio`` fallback exists for — the first send refused, the retry accepted. The
    session lives in ``tests/test_bot/conftest.py``, which the whole bot suite shares, so the
    disarm is wrapped around it here rather than built into it. The wrapper delegates to the
    real ``make_request``, so the refused call is still recorded and still raises; only the
    arming is one-shot.
    """
    session.failures[method] = error
    original = session.make_request

    async def once(
        bot: Bot,
        request: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 - the signature is aiogram's, not ours
    ) -> Any:
        try:
            return await original(bot, request, timeout)
        finally:
            session.failures.pop(type(request).__name__, None)

    session.make_request = once  # type: ignore[assignment,method-assign]


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
    body = translate(
        "delivery.lyric_sheet",
        Language.EN,
        title=kit.lyrics.title,
        body=kit.lyrics.as_plain_text(),
    )
    invite = watermark("watermark.invite")
    assert sheet == f"{invite}\n\n{body}\n\n{invite}"


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


# ---------------------------------------------------------------------------
# The watermark — carriers (c) message caption and (d) lyric-sheet text
#
# Forwarding is this product's only distribution channel: there is no link, no store page
# and no share sheet. A song that lands in a third person's chat wearing nothing at all is
# a copy that sells nobody anything, so every message that leaves this module carries the
# handle somewhere a forward preserves.
# ---------------------------------------------------------------------------
async def test_the_song_goes_out_under_the_bot_as_its_performer(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """``performer`` is the carrier that survives the file leaving Telegram."""
    # Arrange / Act
    await deliver(bot, kit)

    # Assert
    assert session.last_named("SendAudio").performer == WATERMARK_HANDLE


async def test_a_kit_with_a_cover_sends_it_as_the_audio_thumbnail(
    bot: Bot, session: RecordingSession, kit_with_cover: Kit
) -> None:
    # Arrange / Act
    result = await deliver(bot, kit_with_cover)

    # Assert
    assert isinstance(result, Ok)
    assert session.last_named("SendAudio").thumbnail is not None


async def test_a_kit_without_a_cover_still_delivers_the_song(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """``Kit.cover`` is optional because the cover is generated best-effort."""
    # Arrange / Act
    result = await deliver(bot, kit)

    # Assert
    assert isinstance(result, Ok)
    assert session.last_named("SendAudio").thumbnail is None


async def test_a_cover_whose_file_vanished_still_delivers_the_song(
    bot: Bot, session: RecordingSession, kit_with_cover: Kit
) -> None:
    """``FSInputFile`` opens lazily inside aiogram, long after delivery decided to use it.

    A workspace swept between assembly and delivery would otherwise raise from the middle of
    the multipart write rather than return an ``Err``, and the song — which exists, and is
    fine — would be lost to a missing picture.
    """
    # Arrange
    cover = kit_with_cover.cover
    assert cover is not None
    cover.path.unlink()

    # Act
    result = await deliver(bot, kit_with_cover)

    # Assert
    assert isinstance(result, Ok)
    assert session.last_named("SendAudio").thumbnail is None


async def test_a_refused_thumbnail_is_retried_once_without_it_rather_than_losing_the_song(
    bot: Bot, session: RecordingSession, kit_with_cover: Kit
) -> None:
    """Telegram decides a thumbnail is unacceptable at SEND time and nowhere earlier.

    Not JPEG, over 200 kB, over 320 px on a side: each comes back as a 400 on a call that
    would have succeeded without the picture. The song is the one message the whole product
    turns on, so it is sent again unbranded before any failure is reported.
    """
    # Arrange — only the FIRST SendAudio is refused
    fail_once(
        session,
        "SendAudio",
        TelegramBadRequest(
            method=SendMessage(chat_id=CHAT_ID, text="x"),
            message="Bad Request: failed to get HTTP URL content",
        ),
    )
    ledger = DeliveryLedger()

    # Act
    result = await deliver(bot, kit_with_cover, ledger=ledger)

    # Assert — a second, stripped attempt, one delivered song, no reported failure
    assert isinstance(result, Ok)
    attempts = session.named("SendAudio")
    assert len(attempts) == 2
    retry = attempts[-1]
    assert retry.performer is None  # type: ignore[attr-defined]
    assert retry.thumbnail is None  # type: ignore[attr-defined]
    assert ledger.sent_for(kit_with_cover.order_id) & {"song"} == {"song"}


async def test_a_song_refused_twice_is_reported_once_and_not_marked_delivered(
    bot: Bot, session: RecordingSession, kit_with_cover: Kit
) -> None:
    """The retry is a fallback, not a redelivery: a request refused stripped too still fails.

    A 400 is the one shape the stripped retry can answer, so it is the one shape that gets a
    second attempt — and when *that* is refused as well the song is reported missing and the
    ledger is left unmarked, so the ARQ retry sends it rather than skipping it as delivered.
    """
    # Arrange — every attempt is refused, branded or not
    ledger = DeliveryLedger()
    session.failures["SendAudio"] = TelegramBadRequest(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="Bad Request: chat not found"
    )

    # Act
    result = await deliver(bot, kit_with_cover, ledger=ledger)

    # Assert
    assert isinstance(result, Err)
    assert len(session.named("SendAudio")) == 2
    assert "song" not in ledger.sent_for(kit_with_cover.order_id)


async def test_a_blocked_bot_costs_exactly_one_sendaudio_rather_than_two(
    bot: Bot, session: RecordingSession, kit_with_cover: Kit
) -> None:
    """A failure the branding did not cause must not buy a second identical call.

    The guard was once ``if failure is not None and branding``, and ``_song_branding`` never
    returns an empty mapping — ``performer`` is unconditional — so it was always true and
    EVERY hard failure cost two ``sendAudio`` calls where the pre-watermark code made one.
    ``TelegramForbiddenError`` (the customer blocked the bot) and ``TelegramRetryAfter`` are
    the two that hurt: stripping a performer cannot unblock a bot, and under a 429 the
    second call only deepens the wait. This pins the attempt count at one for a non-400.
    """
    # Arrange — every attempt refused with the shape a blocked bot returns
    ledger = DeliveryLedger()
    session.failures["SendAudio"] = TelegramForbiddenError(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="bot was blocked by the user"
    )

    # Act
    result = await deliver(bot, kit_with_cover, ledger=ledger)

    # Assert — reported once, attempted once, and still not marked delivered
    assert isinstance(result, Err)
    assert len(session.named("SendAudio")) == 1
    assert "song" not in ledger.sent_for(kit_with_cover.order_id)


async def test_a_blocked_customer_is_reported_as_a_structured_fact(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """The churn source the worker reads, and it must not be a substring of a log line.

    ``_log_failure`` builds ``f"{label}:{type(exc).__name__}"`` for an operator to read; a
    caller that parsed THAT for meaning would stop working the day somebody reformatted it.
    The classification travels under its own key in ``DeliveryError.context`` instead.
    """
    # Arrange
    session.failures["SendAudio"] = TelegramForbiddenError(
        method=SendMessage(chat_id=CHAT_ID, text="x"),
        message="Forbidden: bot was blocked by the user",
    )

    # Act
    result = await deliver(bot, kit)

    # Assert
    assert isinstance(result, Err)
    assert result.error.context[BLOCKED_BY_CUSTOMER_KEY] is True


async def test_an_ordinary_rejection_is_not_read_as_a_block(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """A 400 is the branded-send retry path, and reading it as churn would invent departures."""
    # Arrange
    session.failures["SendAudio"] = TelegramBadRequest(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="Bad Request: THUMBNAIL_INVALID"
    )

    # Act
    result = await deliver(bot, kit)

    # Assert
    assert isinstance(result, Err)
    assert result.error.context[BLOCKED_BY_CUSTOMER_KEY] is False


async def test_a_deleted_account_is_not_read_as_a_block(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """THE CARVE-OUT, and the reason the predicate exists at all.

    ``Forbidden: user is deactivated`` is a DELETED Telegram account. It is undeliverable for
    a different reason, it is not churn anybody can win back, and Telegram sends no
    ``my_chat_member`` update for it — so counting it as a block would put a number on the
    Churn card that no second source could ever corroborate. Recording nothing is the honest
    answer, and widening the predicate to every ``TelegramForbiddenError`` would trade a known
    gap for an unknown lie.
    """
    # Arrange
    session.failures["SendAudio"] = TelegramForbiddenError(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="Forbidden: user is deactivated"
    )

    # Act
    result = await deliver(bot, kit)

    # Assert
    assert isinstance(result, Err)
    assert result.error.context[BLOCKED_BY_CUSTOMER_KEY] is False


async def test_a_block_seen_on_any_asset_is_reported_for_the_whole_delivery(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """Delivery is best-effort per asset, so the flag has to be sticky across all four legs.

    The song can land and a greeting be refused a moment later; one refusal is enough, and
    the assets that were never attempted say nothing to the contrary.
    """
    # Arrange
    session.failures["SendVoice"] = TelegramForbiddenError(
        method=SendMessage(chat_id=CHAT_ID, text="x"),
        message="Forbidden: bot was blocked by the user",
    )

    # Act
    result = await deliver(bot, kit)

    # Assert
    assert isinstance(result, Err)
    assert session.named("SendAudio"), "the song went out before the block was seen"
    assert result.error.context[BLOCKED_BY_CUSTOMER_KEY] is True


async def test_the_handle_rides_on_the_audio_and_every_greeting_caption(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """``sendVoice`` takes no performer and no thumbnail, so its caption is the only carrier."""
    # Arrange / Act
    await deliver(bot, kit)

    # Assert
    assert watermark("watermark.song") in (session.last_named("SendAudio").caption or "")
    voices = session.named("SendVoice")
    assert voices
    for voice in voices:
        assert watermark("watermark.invite") in (voice.caption or "")  # type: ignore[attr-defined]


async def test_every_part_of_a_split_lyric_sheet_carries_the_invitation(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """Parts are separate messages, and a customer forwards messages, not sheets.

    An invitation that only rode on part one is absent from the part that actually gets
    forwarded, which is the whole failure this asserts against.
    """
    # Arrange
    long_section = LyricSection(label="verse", lines=tuple(["a line of lyric"] * 200))
    lyrics = make_lyrics(sections=(long_section, long_section, long_section))
    big = kit.model_copy(update={"lyrics": lyrics})

    # Act
    await deliver(bot, big)

    # Assert — top and bottom of the first part and of the last
    invite = watermark("watermark.invite")
    sheets = [
        call.text
        for call in session.named("SendMessage")
        if isinstance(call, SendMessage) and lyrics.title in (call.text or "")
    ]
    assert len(sheets) >= 3
    for text in (sheets[0], sheets[-1]):
        assert text.startswith(invite)
        assert text.endswith(invite)


async def test_a_split_sheet_still_fits_the_message_ceiling_with_the_invitation_on_it(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """Two forty-character lines spend a rounding error of the half-message heading reserve."""
    # Arrange
    long_section = LyricSection(label="verse", lines=tuple(["a line of lyric"] * 200))
    big = kit.model_copy(update={"lyrics": make_lyrics(sections=(long_section,) * 3)})

    # Act
    await deliver(bot, big)

    # Assert
    for call in session.named("SendMessage"):
        assert len(call.text) <= MAX_MESSAGE_CHARS  # type: ignore[attr-defined]


async def test_the_longest_title_the_contract_allows_still_fits_the_caption_ceiling(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """Telegram's caption ceiling is 1024, a quarter of what the message helpers budget.

    ``LyricDraft.title`` is bounded at 120 characters, which is why a caption could never
    overflow before; appending a localised watermark line is what added a term to that sum
    that this module does not itself bound.

    Ampersands because they are the most expensive character a title can be made of: each
    costs one character in the draft and five (``&amp;``) in the caption Telegram is handed.
    A caption measured on the doubly-escaped form — the mistake this pins — reads 3 000 here,
    clips a caption that fits five times over and drops the watermark with it.
    """
    # Arrange — a title at the contract's ceiling, made of the most expensive character
    lyrics = make_lyrics(title="&" * 120)
    heavy = kit.model_copy(update={"lyrics": lyrics})

    # Act
    await deliver(bot, heavy)

    # Assert — nothing was clipped, and the caption is inside the ceiling
    caption = session.last_named("SendAudio").caption
    assert watermark("watermark.song") in caption
    assert escape_html("&" * 120) in caption
    assert len(caption) <= MAX_CAPTION_CHARS


def test_a_caption_over_the_ceiling_is_clipped_at_a_line_boundary() -> None:
    """Whole lines, so a clip can never orphan a ``<b>`` from its ``</b>``.

    Broken markup is rejected by Telegram exactly as an over-long caption is, so a guard that
    clips mid-tag has bought nothing — it has only changed which 400 arrives.
    """
    # Arrange — a short marked-up heading, then a line far past the ceiling on its own
    heading = "🎵 <b>A Song</b>"
    overflowing = "t" * MAX_CAPTION_CHARS

    # Act
    fitted = _fit_caption(f"{heading}\n{overflowing}")

    # Assert — the heading survived intact, tags and all; the line that did not fit is gone
    assert fitted == heading


def test_a_caption_with_no_line_that_fits_keeps_the_watermark_it_was_composed_for() -> None:
    """The last line is ours, plain and short — and worth more than the part it advertises."""
    # Arrange — not even the first line fits, so there is nothing to keep that is not a fragment
    mark = watermark("watermark.song")

    # Act
    fitted = _fit_caption("🎵 <b>{}</b>\n\n{}".format("t" * MAX_CAPTION_CHARS, mark))

    # Assert
    assert fitted == mark
    assert "<b>" not in fitted


def test_a_caption_inside_the_ceiling_is_handed_back_untouched() -> None:
    """The only path that runs in production: measured, found to fit, returned unchanged."""
    # Arrange
    caption = f"🎵 <b>A Song</b>\nSound on.\n\n{watermark('watermark.song')}"

    # Act / Assert
    assert _fit_caption(caption) == caption


async def test_the_watermark_is_localised_with_the_rest_of_the_delivery(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """A Russian customer must not be advertised to in English."""
    # Arrange / Act
    await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.RU)

    # Assert
    caption = session.last_named("SendAudio").caption
    assert watermark("watermark.song", Language.RU) in caption
    assert watermark("watermark.song", Language.EN) not in caption
