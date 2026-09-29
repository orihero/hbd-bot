"""Whole requests on the LIVE Payme rail, from the quote to the delivered file (IMAGE_VIDEO_SPEC §2.3,
§2.4, §3.3, §7.2; the FINAL review).

Each milestone's suite drives its own half: ``test_media_stages`` runs the beta path to two
delivered photos, ``test_media_settlement`` runs 💳 → Perform → the settlement job up to the
start, ``test_media_video_chain`` runs a video from 🎁 to ``sendVideo``. What none of them did
is walk ONE request across all three, which is where a seam between them would show: the
settlement starting a job the chain then cannot finish, a paid video whose voice never ran, or
uploads left behind after a paid delivery.

Here, over one SQLite database shared by the Payme ledger, the settlement job and the stage
chain, with every vendor faked:

* an image: screened → quoted with 💳 (and no 🎁) → a pay link → Perform → the settlement job
  → rendered twice → screened → one album of two photos → the receipt is Payme's and the
  uploads are gone;
* a video for EACH of the four voice kinds (O3): none, AI voice on the customer's words, AI
  voice on the LLM's words (§5.5, as the approved line sits on the row), and the customer's own
  note — the same rail, and each reaches ``sendVideo`` with the voice made the right way
  (narrated in parallel with the render, prepared from the screened note, or no audio at all)
  and its uploads deleted.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from aiogram import Bot

from bayram.checkout import Product
from bayram.config import Settings
from bayram.contracts import Language, Result, is_ok, ok
from bayram.db.enums import (
    MediaAspect,
    MediaInputRole,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaPurchaseProvider,
    MediaSku,
    MediaTier,
    MediaVoiceGender,
    MediaVoiceMode,
)
from bayram.db.media import add_input, create_job, load_job
from bayram.db.models import UserRow
from bayram.db.models.media_input import MediaInputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.models.media_purchase import MediaPurchaseRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.payme import SqlPaymeLedger
from bayram.media.desk import JobView
from bayram.media.payment import SqlMediaCharge
from bayram.media.stages import (
    MEDIA_MUX_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_START_JOB,
    MEDIA_TTS_JOB,
    MEDIA_VOICE_PREPARE_JOB,
    screen_job_id,
)
from bayram.media.voice_probe import VoiceMeasure
from bayram.moderation.contracts import VoiceTranscript
from bayram.payme.provider import PaymeCheckoutProvider
from bayram.runtime.container import AppContainer, build_container
from bayram.runtime.payme_jobs import notify_payment_settled
from tests.conftest import FIXED_NOW
from tests.test_bot.conftest import RecordingSession
from tests.test_runtime.media_fakes import (
    PROMPT,
    TRAY_ID,
    USER,
    Harness,
    build_harness,
    freeze_job,
    jpeg_bytes,
    media_settings,
)

_MERCHANT: Final[str] = "5e730e8e0b852a417aa49ceb"
_NOTE_FILE: Final[str] = "voice-file-e2e"
_OGG: Final[bytes] = b"OggS" + b"\x00" * 64
_LINE: Final[str] = "Happy birthday, dear friend"


@dataclasses.dataclass
class _Probe:
    """ffprobe's measure of a voice note: inside the 5 s clip (O14)."""

    async def measure(self, path: Path) -> Result[VoiceMeasure]:
        return ok(VoiceMeasure(duration_s=4.0, voiced_s=3.5))


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[AppContainer]:
    built = await build_container(
        Settings(
            _env_file=None,
            telegram_bot_token="t",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'media_e2e.db'}",
            elevenlabs_api_key="k",
            llm_api_key="k",
        ),
        data_root=tmp_path / "var",
        with_providers=False,
    )
    yield built
    await built.aclose()


@pytest.fixture
def harness(container: AppContainer, tmp_path: Path) -> Harness:
    """The stage chain on a live-paid rail (O9: Payme, enforced, not the sandbox), over the
    database the Payme ledger and the settlement job write."""
    live = media_settings(
        container.settings,
        checkout_provider="payme",
        credits_enforced=True,
        payme_is_sandbox=False,
        payme_merchant_id=_MERCHANT,
        media_beta_enabled=False,
        media_beta_allowlist=(),
        is_video_standard_offered=True,
        video_standard_backend="fake",
    )
    built = build_harness(live, container.require_session_factory(), tmp_path, FIXED_NOW)
    built.rt = dataclasses.replace(built.rt, voice_probe=_Probe())
    built.moderator.transcript = VoiceTranscript(
        text="happy birthday my dear friend",
        language="en",
        avg_logprob=-0.2,
        no_speech_prob=0.01,
        max_compression_ratio=1.1,
    )
    return built


@pytest.fixture
def rail(container: AppContainer) -> SqlPaymeLedger:
    return SqlPaymeLedger(
        container.require_session_factory(), merchant_id=_MERCHANT, clock=lambda: FIXED_NOW
    )


async def _never_paused() -> bool:
    return False


async def _job(harness: Harness, job_id: UUID) -> MediaJobRow:
    async with harness.sessions() as session:
        job = await load_job(session, job_id)
    assert job is not None
    return job


async def _video_row(harness: Harness, voice: MediaVoiceMode, *, photos: int = 1) -> UUID:
    """What ``VideoOrder``'s last voice step leaves (§2.4.1): a ``screening`` row with every
    choice written on it — the approved LLM line for 🤖, the note's file id for 🎙."""
    now = harness.clock()
    async with harness.sessions.begin() as session:
        user_id = uuid4()
        session.add(UserRow(id=user_id, telegram_user_id=USER))
        await session.flush()
        job_id = await create_job(
            session,
            user_id=user_id,
            telegram_user_id=USER,
            kind=MediaKind.VIDEO,
            sku=MediaSku.VIDEO_STANDARD,
            state=MediaJobState.SCREENING,
            chat_id=USER,
            outputs_requested=1,
            aspect=MediaAspect.PORTRAIT,
            language=Language.EN,
            prompt=PROMPT,
            price_minor=2_500_000,
            currency="UZS",
            now=now,
            quote_ttl=timedelta(seconds=harness.rt.settings.media_quote_ttl_s),
            tier=MediaTier.STANDARD,
            voice_mode=voice,
            voice_gender=MediaVoiceGender.FEMALE
            if voice in (MediaVoiceMode.AI_USER, MediaVoiceMode.AI_LLM)
            else None,
            narration_text=_LINE
            if voice in (MediaVoiceMode.AI_USER, MediaVoiceMode.AI_LLM)
            else None,
            tray_message_id=TRAY_ID,
        )
        ordinal = 0
        for ordinal in range(photos):
            harness.messenger.files[f"photo-{ordinal}"] = jpeg_bytes()
            await add_input(
                session,
                job_id=job_id,
                ordinal=ordinal,
                role=MediaInputRole.PHOTO,
                now=now,
                tg_file_id=f"photo-{ordinal}",
                tg_file_unique_id=f"photo-u-{ordinal}",
            )
        if voice is MediaVoiceMode.OWN:
            harness.messenger.files[_NOTE_FILE] = _OGG
            await add_input(
                session,
                job_id=job_id,
                ordinal=photos,
                role=MediaInputRole.VOICE_NOTE,
                now=now,
                tg_file_id=_NOTE_FILE,
                tg_file_unique_id="note-u",
            )
    return job_id


async def _screen(harness: Harness, job_id: UUID) -> None:
    """``media_screen`` → the quote. On this rail it carries 💳 and never 🎁 (§2.5)."""
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.QUOTED, (job.state, job.error_code)
    markup = harness.messenger.edits[-1][3]
    assert markup is not None
    callbacks = [button.callback_data or "" for row in markup.inline_keyboard for button in row]
    assert any(data.startswith("med:pay:") for data in callbacks), callbacks
    assert not any(data.startswith("med:beta:") for data in callbacks), callbacks


async def _pay(
    harness: Harness,
    rail: SqlPaymeLedger,
    container: AppContainer,
    bot: Bot,
    job_id: UUID,
    *,
    kind: MediaKind,
    sku: MediaSku,
) -> None:
    """💳 through the real Payme provider, Perform on the ledger, then the settlement job."""
    provider = PaymeCheckoutProvider(
        rail,
        merchant_id=_MERCHANT,
        base_url="https://checkout.test",
        account_field="order_id",
        return_url="https://t.me/bayram_uzbot",
        is_sandbox=False,
        plan_songs=12,
        plan_days=30,
        language_of=lambda: Language.EN,
        paused=_never_paused,
    )
    charge = SqlMediaCharge(
        harness.sessions, checkout=provider, settings=harness.rt.settings, clock=lambda: FIXED_NOW
    )
    view = JobView(
        id=job_id,
        telegram_user_id=USER,
        kind=kind,
        sku=sku,
        state=MediaJobState.QUOTED,
        chat_id=USER,
        tray_message_id=None,
        prompt=None,
        aspect=MediaAspect.PORTRAIT,
        language=Language.EN,
        paid_via=None,
    )
    linked = await charge(view)
    assert is_ok(linked), linked
    assert (await _job(harness, job_id)).state is MediaJobState.AWAITING_PAYMENT
    async with harness.sessions() as session:
        intent = await session.scalar(
            sa.select(PaymentIntentRow).where(PaymentIntentRow.resume_media_job_id == job_id)
        )
    assert intent is not None
    assert intent.product.value == Product(sku.value).value
    created = await rail.create(
        payme_transaction_id=f"tx-{job_id.hex[:8]}",
        payme_time=FIXED_NOW,
        amount_minor=intent.amount_minor,
        public_ref=intent.public_ref,
        now=FIXED_NOW,
    )
    assert is_ok(created), created
    performed = await rail.perform(payme_transaction_id=f"tx-{job_id.hex[:8]}", now=FIXED_NOW)
    assert is_ok(performed), performed
    assert (await _job(harness, job_id)).state is MediaJobState.PAID
    ctx: dict[str, Any] = {"container": container, "bot": bot, "redis": harness.queue}
    await notify_payment_settled(ctx, intent.public_ref)


async def _inputs_left(harness: Harness, job_id: UUID) -> int:
    async with harness.sessions() as session:
        return int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(MediaInputRow)
                .where(MediaInputRow.job_id == job_id)
            )
            or 0
        )


async def _receipt(harness: Harness, job_id: UUID) -> MediaPurchaseRow:
    async with harness.sessions() as session:
        (receipt,) = (
            await session.scalars(
                sa.select(MediaPurchaseRow).where(MediaPurchaseRow.job_id == job_id)
            )
        ).all()
    return receipt


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------
async def test_a_paid_image_request_goes_from_the_quote_to_two_delivered_photos(
    container: AppContainer,
    harness: Harness,
    rail: SqlPaymeLedger,
    bot: Bot,
    session: RecordingSession,
) -> None:
    job_id = await freeze_job(harness, photos=(jpeg_bytes(), jpeg_bytes((40, 200, 40))))
    await _screen(harness, job_id)

    await _pay(harness, rail, container, bot, job_id, kind=MediaKind.IMAGE, sku=MediaSku.IMAGE)
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert job.paid_via is MediaPaidVia.PAYME
    assert len(harness.queue.ran_named(MEDIA_START_JOB)) == 1
    # One request, two images (O5), in one album.
    assert len(harness.provider.submits) == 2
    (album,) = harness.messenger.albums
    assert len(album.photos) == 2
    receipt = await _receipt(harness, job_id)
    assert receipt.provider is MediaPurchaseProvider.PAYME
    assert receipt.amount_minor == harness.rt.settings.image_price_minor
    # Uploads deleted straight after delivery (O16): rows, archive objects and workspace.
    assert await _inputs_left(harness, job_id) == 0
    assert not list((harness.storage.root / "media" / str(job_id) / "in").glob("*"))
    assert not (harness.workspace / "media" / str(job_id)).exists()
    assert await harness.gpu.members() == () and await harness.gpu.holder() is None
    assert harness.queue.unhandled == []


# ---------------------------------------------------------------------------
# Video, each voice kind (O3)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("voice", list(MediaVoiceMode), ids=lambda mode: mode.value)
async def test_a_paid_video_goes_from_the_quote_to_a_delivered_clip_for_each_voice(
    container: AppContainer,
    harness: Harness,
    rail: SqlPaymeLedger,
    bot: Bot,
    session: RecordingSession,
    voice: MediaVoiceMode,
) -> None:
    job_id = await _video_row(harness, voice)
    await _screen(harness, job_id)
    if voice is MediaVoiceMode.OWN:
        # The screened copy is what is muxed; Telegram is never asked for the note again.
        harness.messenger.files.pop(_NOTE_FILE)

    await _pay(
        harness,
        rail,
        container,
        bot,
        job_id,
        kind=MediaKind.VIDEO,
        sku=MediaSku.VIDEO_STANDARD,
    )
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert job.paid_via is MediaPaidVia.PAYME
    assert len(harness.messenger.videos) == 1 and harness.messenger.albums == []
    assert (await _receipt(harness, job_id)).provider is MediaPurchaseProvider.PAYME
    narrated = [call.request.text for call in harness.narration.calls]
    prepared = harness.queue.ran_named(MEDIA_VOICE_PREPARE_JOB)
    if voice is MediaVoiceMode.NONE:
        # No audio at all: the clip is re-wrapped, never muxed (§5.6).
        assert narrated == [] and prepared == []
        assert len(harness.video.rewraps) == 1 and harness.video.muxes == []
    elif voice is MediaVoiceMode.OWN:
        # The customer's own note, muxed as-is: never sent to a TTS vendor, never sped up.
        assert narrated == [] and len(prepared) == 1
        ((_, _, may_speed_up),) = harness.video.muxes
        assert may_speed_up is False
    else:
        # The line on the row is spoken once, in parallel with the render, then muxed once.
        assert narrated == [_LINE]
        assert len(harness.queue.ran_named(MEDIA_TTS_JOB)) == 1
        assert len(harness.queue.ran_named(MEDIA_MUX_JOB)) == 1
        ((_, _, may_speed_up),) = harness.video.muxes
        assert may_speed_up is True
    assert job.render_ready_at is not None
    # Every upload — the photo and any note — is gone after delivery (O16).
    assert await _inputs_left(harness, job_id) == 0
    assert not list((harness.storage.root / "media" / str(job_id) / "in").glob("*"))
    assert not (harness.workspace / "media" / str(job_id)).exists()
    assert harness.queue.unhandled == []
