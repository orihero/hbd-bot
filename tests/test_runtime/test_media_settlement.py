"""Media SKUs on the Payme rail, end to end over SQLite and fakes (IMAGE_VIDEO_SPEC §7, M5.1).

The §10 M5.1 acceptance list, each a test below:

* Perform for each SKU commits the receipt and the conditional ``awaiting_payment → paid`` in
  one transaction;
* Perform on a cancelled job → the receipt, the row untouched, and exactly one
  ``late_settlement`` credit however often the settlement job runs;
* an unknown SKU — a media intent that names no job — fails closed;
* a double settle starts the job once;
* a burned claim plus a failed enqueue → ``media_sweep`` starts the job exactly once;
* a settled media intent never shows the song keyboard;
* a beta failure grants no credit — down the real 🎁 → failed-render path, in
  ``test_media_stages.test_a_beta_failure_mints_no_credit`` (this rail sells no beta).

Plus the §7.2 step-3 refusals (Check/Create on a cancelled or abandoned job), the ✖️ on a
pay link (intent cancelled while pending, "too late" once a transaction holds it) and the
💳 path itself (``SqlMediaCharge`` through the real ``PaymeCheckoutProvider``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from aiogram import Bot
from aiogram.methods import SendMessage

from bayram.admin.routers import billing as billing_router
from bayram.admin.schemas import billing as billing_schemas
from bayram.admin.schemas.billing import LifelineNote
from bayram.bot.handlers import checkout as song_checkout
from bayram.bot.i18n import translate
from bayram.bot.pricing import Pricing
from bayram.checkout import MEDIA_PRODUCTS, Product, PurchaseRequest, StubCheckoutProvider
from bayram.config import Settings
from bayram.contracts import Err, Language, err, is_err, is_ok
from bayram.db import payme as payme_ledger
from bayram.db.enums import (
    IntentProduct,
    MediaAspect,
    MediaCreditReason,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaPurchaseProvider,
    MediaSku,
    PaymentIntentState,
)
from bayram.db.media import MEDIA_REVIEW_SLA, grant_refund, load_job, media_balance, transition
from bayram.db.models.media_credit import MediaCreditLedgerRow
from bayram.db.models.media_input import MediaInputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.models.media_purchase import MediaPurchaseRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.payme import SqlPaymeLedger
from bayram.errors import CheckoutError
from bayram.media.desk import CancelOutcome, JobView, SqlMediaDesk
from bayram.media.overrides import set_gpu_reserved_until, set_paused
from bayram.media.payment import (
    MEDIA_BUSY_KEY,
    MEDIA_DAILY_CAP_KEY,
    MEDIA_STALE_KEY,
    SqlMediaCharge,
    media_idempotency_key,
)
from bayram.media.stages import MEDIA_START_JOB, screen_job_id
from bayram.payme.errors import PaymeFault
from bayram.payme.protocol import PaymeErrorCode
from bayram.payme.provider import PaymeCheckoutProvider
from bayram.runtime import payme_jobs
from bayram.runtime.container import AppContainer, build_container
from bayram.runtime.media_sweep import sweep_media
from bayram.runtime.payme_jobs import (
    PAID_MEDIA_KEY,
    PAID_MEDIA_LATE_KEY,
    notify_payment_settled,
)
from tests.conftest import FIXED_NOW
from tests.test_bot.conftest import RecordingSession
from tests.test_runtime.media_fakes import (
    USER,
    Harness,
    build_harness,
    freeze_job,
    jpeg_bytes,
    media_settings,
)

_MERCHANT: Final[str] = "5e730e8e0b852a417aa49ceb"
_PRICE: Final[int] = 500_000


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'media_settlement.db'}",
        elevenlabs_api_key="k",
        llm_api_key="k",
    )


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[AppContainer]:
    built = await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    yield built
    await built.aclose()


@pytest.fixture
def harness(container: AppContainer, tmp_path: Path) -> Harness:
    """The media stage chain over the SAME database the rail and the settlement job use."""
    live = media_settings(
        container.settings,
        checkout_provider="payme",
        credits_enforced=True,
        payme_is_sandbox=False,
        payme_merchant_id=_MERCHANT,
        is_video_standard_offered=True,
        is_video_fast_offered=True,
        video_fast_price_minor=4_000_000,
    )
    return build_harness(live, container.require_session_factory(), tmp_path, FIXED_NOW)


@pytest.fixture
def rail(container: AppContainer) -> SqlPaymeLedger:
    return SqlPaymeLedger(
        container.require_session_factory(),
        merchant_id=_MERCHANT,
        clock=lambda: FIXED_NOW,
    )


async def _never_paused() -> bool:
    return False


def _charge(harness: Harness, rail: SqlPaymeLedger) -> SqlMediaCharge:
    """The bot's 💳 path, through the real Payme provider over the real ledger."""
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
    return SqlMediaCharge(
        harness.sessions, checkout=provider, settings=harness.rt.settings, clock=lambda: FIXED_NOW
    )


def _ctx(container: AppContainer, bot: Bot, harness: Harness) -> dict[str, Any]:
    return {"container": container, "bot": bot, "redis": harness.queue}


async def _job(harness: Harness, job_id: UUID) -> Any:
    async with harness.sessions() as session:
        return await load_job(session, job_id)


async def _quoted_image(harness: Harness, *, photos: tuple[bytes, ...] = ()) -> UUID:
    """A screened, quoted image — the only row 💳 applies to."""
    job_id = await freeze_job(harness, photos=photos)
    await harness.queue.enqueue_job("media_screen", str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.QUOTED, job.state
    return job_id


async def _quoted_row(harness: Harness, sku: MediaSku) -> UUID:
    """A quoted row of any SKU, moved by hand: the Perform arm reads nothing screening wrote."""
    job_id = await freeze_job(harness)
    async with harness.sessions.begin() as session:
        await session.execute(
            sa.update(MediaJobRow).where(MediaJobRow.id == job_id).values(sku=sku)
        )
        assert await transition(
            session,
            job_id,
            expected=(MediaJobState.SCREENING,),
            to=MediaJobState.QUOTED,
            now=FIXED_NOW,
        )
    return job_id


def _view(job_id: UUID) -> JobView:
    """What the pay handler hands the charge: only the id and the presser are read."""
    return JobView(
        id=job_id,
        telegram_user_id=USER,
        kind=MediaKind.IMAGE,
        sku=MediaSku.IMAGE,
        state=MediaJobState.QUOTED,
        chat_id=USER,
        tray_message_id=None,
        prompt=None,
        aspect=MediaAspect.PORTRAIT,
        language=Language.EN,
        paid_via=None,
    )


@dataclass(frozen=True)
class _Opened:
    public_ref: str
    intent_id: UUID


async def _pay_link(harness: Harness, rail: SqlPaymeLedger, job_id: UUID) -> _Opened:
    linked = await _charge(harness, rail)(_view(job_id))
    assert is_ok(linked), linked
    async with harness.sessions() as session:
        intent = await session.scalar(
            sa.select(PaymentIntentRow).where(PaymentIntentRow.resume_media_job_id == job_id)
        )
    assert intent is not None
    return _Opened(public_ref=intent.public_ref, intent_id=intent.id)


async def _perform(rail: SqlPaymeLedger, opened: _Opened, *, amount: int, tid: str) -> None:
    created = await rail.create(
        payme_transaction_id=tid,
        payme_time=FIXED_NOW,
        amount_minor=amount,
        public_ref=opened.public_ref,
        now=FIXED_NOW,
    )
    assert is_ok(created), created
    performed = await rail.perform(payme_transaction_id=tid, now=FIXED_NOW)
    assert is_ok(performed), performed


async def _receipts(harness: Harness, job_id: UUID) -> list[MediaPurchaseRow]:
    async with harness.sessions() as session:
        return list(
            (
                await session.scalars(
                    sa.select(MediaPurchaseRow).where(MediaPurchaseRow.job_id == job_id)
                )
            ).all()
        )


async def _ledger(harness: Harness, job_id: UUID) -> list[MediaCreditLedgerRow]:
    async with harness.sessions() as session:
        return list(
            (
                await session.scalars(
                    sa.select(MediaCreditLedgerRow).where(MediaCreditLedgerRow.job_id == job_id)
                )
            ).all()
        )


def _sent(session: RecordingSession) -> list[SendMessage]:
    return [call for call in session.calls if isinstance(call, SendMessage)]


def _code(result: Any) -> int:
    assert isinstance(result, Err)
    assert isinstance(result.error, PaymeFault)
    return int(result.error.rpc_code)


# ---------------------------------------------------------------------------
# 💳 and Perform
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sku", list(MediaSku))
async def test_perform_for_each_sku_writes_the_receipt_and_moves_the_job_in_one_commit(
    harness: Harness, rail: SqlPaymeLedger, sku: MediaSku
) -> None:
    job_id = await _quoted_row(harness, sku)
    opened = await _pay_link(harness, rail, job_id)
    job = await _job(harness, job_id)
    assert (job.state, job.payment_intent_id) == (MediaJobState.AWAITING_PAYMENT, opened.intent_id)

    await _perform(rail, opened, amount=_PRICE, tid=f"tx-{sku.value}")

    job = await _job(harness, job_id)
    assert (job.state, job.paid_via, job.paid_at) == (
        MediaJobState.PAID,
        MediaPaidVia.PAYME,
        FIXED_NOW,
    )
    (receipt,) = await _receipts(harness, job_id)
    assert (receipt.provider, receipt.sku, receipt.amount_minor, receipt.reference) == (
        MediaPurchaseProvider.PAYME,
        sku,
        _PRICE,
        f"tx-{sku.value}",
    )
    assert receipt.idempotency_key == media_idempotency_key(sku, USER, job_id)
    # The three-way invariant counts the media receipt: performed == receipts.
    counts = await rail.settlement_counts(
        frm=FIXED_NOW - timedelta(hours=1), to=FIXED_NOW + timedelta(hours=1)
    )
    assert is_ok(counts)
    assert counts.value.transactions_performed == counts.value.receipts_written == 1
    assert counts.value.grants_written == 0


async def test_a_second_pay_press_re_opens_the_same_intent(
    harness: Harness, rail: SqlPaymeLedger
) -> None:
    job_id = await _quoted_image(harness)
    charge = _charge(harness, rail)

    first = await charge(_view(job_id))
    second = await charge(_view(job_id))

    assert is_ok(first) and is_ok(second)
    assert first.value.url == second.value.url
    assert first.value.amount_minor == _PRICE


async def test_an_inline_paid_answer_is_refused_and_starts_nothing(harness: Harness) -> None:
    # The stub reports every charge paid with no money moved (§7.2 step 2).
    job_id = await _quoted_image(harness)
    charge = SqlMediaCharge(
        harness.sessions, checkout=StubCheckoutProvider(), settings=harness.rt.settings
    )

    result = await charge(_view(job_id))

    assert is_err(result)
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED
    assert await _receipts(harness, job_id) == []
    assert MEDIA_START_JOB not in [stage.name for stage in harness.queue.pending]


# ---------------------------------------------------------------------------
# Check / Create refusals and ✖️ on a pay link
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ended", [MediaJobState.CANCELLED, MediaJobState.ABANDONED])
async def test_check_and_create_refuse_a_job_no_longer_awaiting_payment(
    harness: Harness, rail: SqlPaymeLedger, ended: MediaJobState
) -> None:
    job_id = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, job_id)
    assert is_ok(await rail.quote(public_ref=opened.public_ref, amount_minor=_PRICE, now=FIXED_NOW))
    async with harness.sessions.begin() as session:
        assert await transition(
            session,
            job_id,
            expected=(MediaJobState.AWAITING_PAYMENT,),
            to=ended,
            now=FIXED_NOW,
        )

    quoted = await rail.quote(public_ref=opened.public_ref, amount_minor=_PRICE, now=FIXED_NOW)
    created = await rail.create(
        payme_transaction_id="tx-late",
        payme_time=FIXED_NOW,
        amount_minor=_PRICE,
        public_ref=opened.public_ref,
        now=FIXED_NOW,
    )

    assert _code(quoted) == _code(created) == PaymeErrorCode.ACCOUNT_CANCELLED
    assert -31099 <= PaymeErrorCode.ACCOUNT_CANCELLED <= -31050


async def test_cancel_on_a_pay_link_cancels_the_pending_intent_too(
    harness: Harness, rail: SqlPaymeLedger
) -> None:
    job_id = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, job_id)
    desk = SqlMediaDesk(
        harness.sessions, queue=harness.queue, settings=harness.rt.settings, clock=lambda: FIXED_NOW
    )

    outcome = await desk.cancel(job_id, telegram_user_id=USER)

    assert is_ok(outcome) and outcome.value is CancelOutcome.CANCELLED
    assert (await _job(harness, job_id)).state is MediaJobState.CANCELLED
    found = await rail.intent(public_ref=opened.public_ref)
    assert is_ok(found) and found.value is not None
    assert found.value.state.value == PaymentIntentState.CANCELLED.value
    quoted = await rail.quote(public_ref=opened.public_ref, amount_minor=_PRICE, now=FIXED_NOW)
    assert _code(quoted) == PaymeErrorCode.ACCOUNT_CANCELLED


async def test_cancel_is_too_late_once_a_payme_transaction_holds_the_intent(
    harness: Harness, rail: SqlPaymeLedger
) -> None:
    job_id = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, job_id)
    assert is_ok(
        await rail.create(
            payme_transaction_id="tx-held",
            payme_time=FIXED_NOW,
            amount_minor=_PRICE,
            public_ref=opened.public_ref,
            now=FIXED_NOW,
        )
    )
    desk = SqlMediaDesk(
        harness.sessions, queue=harness.queue, settings=harness.rt.settings, clock=lambda: FIXED_NOW
    )

    outcome = await desk.cancel(job_id, telegram_user_id=USER)
    slash = await desk.cancel_open(USER)

    assert is_ok(outcome) and outcome.value is CancelOutcome.TOO_LATE
    assert is_ok(slash) and slash.value is CancelOutcome.TOO_LATE
    assert (await _job(harness, job_id)).state is MediaJobState.AWAITING_PAYMENT


# ---------------------------------------------------------------------------
# Late settlement
# ---------------------------------------------------------------------------
async def test_perform_on_a_cancelled_job_keeps_the_receipt_and_grants_one_late_credit(
    container: AppContainer,
    harness: Harness,
    rail: SqlPaymeLedger,
    bot: Bot,
    session: RecordingSession,
) -> None:
    job_id = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, job_id)
    assert is_ok(
        await rail.create(
            payme_transaction_id="tx-race",
            payme_time=FIXED_NOW,
            amount_minor=_PRICE,
            public_ref=opened.public_ref,
            now=FIXED_NOW,
        )
    )
    # A race past the Check/Create refusals: the row is cancelled while the card is charged.
    async with harness.sessions.begin() as db:
        assert await transition(
            db,
            job_id,
            expected=(MediaJobState.AWAITING_PAYMENT,),
            to=MediaJobState.CANCELLED,
            now=FIXED_NOW,
        )

    assert is_ok(await rail.perform(payme_transaction_id="tx-race", now=FIXED_NOW))
    job = await _job(harness, job_id)
    assert (job.state, job.paid_via) == (MediaJobState.CANCELLED, None)
    assert len(await _receipts(harness, job_id)) == 1

    await notify_payment_settled(_ctx(container, bot, harness), opened.public_ref)
    # A redelivery, and a hand-run second pass over the grant, change nothing.
    await notify_payment_settled(_ctx(container, bot, harness), opened.public_ref)
    async with harness.sessions.begin() as db:
        assert not await grant_refund(
            db, job_id, reason=MediaCreditReason.LATE_SETTLEMENT, now=FIXED_NOW
        )

    ledger = await _ledger(harness, job_id)
    assert [(row.reason, row.delta) for row in ledger] == [(MediaCreditReason.LATE_SETTLEMENT, 1)]
    async with harness.sessions() as db:
        assert await media_balance(db, telegram_user_id=USER, sku=MediaSku.IMAGE) == 1
    (message,) = _sent(session)
    assert message.text == translate(
        PAID_MEDIA_LATE_KEY, Language.EN, kind=translate("media.kind.image", Language.EN)
    )
    assert MEDIA_START_JOB not in [stage.name for stage in harness.queue.pending]


# ---------------------------------------------------------------------------
# Starting the job
# ---------------------------------------------------------------------------
async def test_a_double_settle_starts_the_job_once_and_never_shows_the_song_keyboard(
    container: AppContainer,
    harness: Harness,
    rail: SqlPaymeLedger,
    bot: Bot,
    session: RecordingSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_song_resume(*_: Any, **__: Any) -> Any:
        raise AssertionError("plan_resume ran for a media intent")

    monkeypatch.setattr(payme_jobs, "plan_resume", no_song_resume)
    job_id = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, job_id)
    await _perform(rail, opened, amount=_PRICE, tid="tx-double")

    await notify_payment_settled(_ctx(container, bot, harness), opened.public_ref)
    await notify_payment_settled(_ctx(container, bot, harness), opened.public_ref)
    # And the start itself delivered twice, as a redelivered ARQ job would be.
    await harness.run(MEDIA_START_JOB, str(job_id), 0)
    await harness.drain()

    (message,) = _sent(session)
    assert message.reply_markup is None
    assert message.text == translate(
        PAID_MEDIA_KEY, Language.EN, kind=translate("media.kind.image", Language.EN)
    )
    starts = harness.queue.ran_named(MEDIA_START_JOB)
    assert len(starts) == 1
    assert len(harness.provider.submits) == 2  # one POST per variant, once
    job = await _job(harness, job_id)
    assert job.state is not MediaJobState.PAID


async def test_a_burned_claim_and_a_failed_enqueue_leave_the_sweep_to_start_it_once(
    container: AppContainer,
    harness: Harness,
    rail: SqlPaymeLedger,
    bot: Bot,
    session: RecordingSession,
) -> None:
    job_id = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, job_id)
    await _perform(rail, opened, amount=_PRICE, tid="tx-lost")
    harness.queue.failure = ConnectionError("redis blinked")

    await notify_payment_settled(_ctx(container, bot, harness), opened.public_ref)

    harness.queue.failure = None
    async with harness.sessions() as db:
        resumed = await db.scalar(
            sa.select(PaymentIntentRow.resumed_at).where(PaymentIntentRow.id == opened.intent_id)
        )
    assert resumed is not None  # the audit claim is burned
    assert (await _job(harness, job_id)).state is MediaJobState.PAID
    assert harness.queue.pending == type(harness.queue.pending)()

    later = FIXED_NOW + timedelta(minutes=5)
    await sweep_media(harness.rt, now=later)
    await harness.drain()
    await sweep_media(harness.rt, now=later + timedelta(minutes=5))
    await harness.drain()

    assert len(harness.queue.ran_named(MEDIA_START_JOB)) == 1
    assert len(harness.provider.submits) == 2
    assert (await _job(harness, job_id)).state is not MediaJobState.PAID


# ---------------------------------------------------------------------------
# Fail closed
# ---------------------------------------------------------------------------
async def test_a_media_intent_that_names_no_job_fails_closed(
    harness: Harness, rail: SqlPaymeLedger
) -> None:
    opened = await rail.open_intent(
        telegram_user_id=USER,
        product=Product.IMAGE,
        amount_minor=_PRICE,
        currency="UZS",
        idempotency_key=f"image:{USER}:{uuid4()}",
        language="en",
        merchant_id=_MERCHANT,
        is_sandbox=False,
    )
    assert is_ok(opened)
    ref = opened.value.public_ref

    quoted = await rail.quote(public_ref=ref, amount_minor=_PRICE, now=FIXED_NOW)
    forced = await rail.force_settle(public_ref=ref, now=FIXED_NOW, note="INC-1")

    assert _code(quoted) == PaymeErrorCode.ACCOUNT_UNKNOWN
    assert is_err(forced)  # the whole settlement unwound: no receipt, intent still pending
    found = await rail.intent(public_ref=ref)
    assert is_ok(found) and found.value is not None
    assert found.value.state.value == PaymentIntentState.PENDING.value
    async with harness.sessions() as db:
        assert (await db.scalar(sa.select(sa.func.count()).select_from(MediaPurchaseRow))) == 0


async def test_the_payme_provider_refuses_a_media_purchase_that_names_no_job(
    harness: Harness, rail: SqlPaymeLedger
) -> None:
    provider = _charge(harness, rail)._checkout

    result = await provider.charge(
        PurchaseRequest(
            telegram_user_id=USER,
            product=Product.VIDEO_STANDARD,
            amount_minor=_PRICE,
            currency="UZS",
            idempotency_key="video_standard:1:x",
        )
    )

    assert is_err(result)
    async with harness.sessions() as db:
        assert (await db.scalar(sa.select(sa.func.count()).select_from(PaymentIntentRow))) == 0


@pytest.mark.parametrize("product", sorted(MEDIA_PRODUCTS))
def test_the_song_checkout_sells_no_media_sku(product: Product, settings: Settings) -> None:
    pricing = Pricing.from_settings(settings)
    assert song_checkout._song_amount_minor(pricing, product) is None
    with pytest.raises(ValueError):
        song_checkout._idempotency_key(1, "scope", product=product, seq=0)


def test_every_product_has_an_intent_product_and_the_media_ones_a_sku() -> None:
    assert {p.value for p in Product} == {p.value for p in IntentProduct}
    assert {p.value for p in MEDIA_PRODUCTS} == {sku.value for sku in MediaSku}


# ---------------------------------------------------------------------------
# 💳 re-reads the offer, the switches and the cap at press time (§2.5, §4.5, §7.6, O11)
# ---------------------------------------------------------------------------
async def _intents(harness: Harness) -> int:
    async with harness.sessions() as db:
        return int(await db.scalar(sa.select(sa.func.count()).select_from(PaymentIntentRow)) or 0)


def _switched_charge(harness: Harness, rail: SqlPaymeLedger, settings: Settings) -> SqlMediaCharge:
    """``_charge`` with the operator's Redis switches wired, as ``main`` wires them."""
    return SqlMediaCharge(
        harness.sessions,
        checkout=_charge(harness, rail)._checkout,
        settings=settings,
        switches=harness.rt.switches,
        clock=lambda: FIXED_NOW,
    )


@pytest.mark.parametrize("block", ["paused", "not_offered", "gpu_reserved"])
async def test_a_pay_press_on_a_sku_no_longer_sold_opens_no_intent(
    harness: Harness, rail: SqlPaymeLedger, block: str
) -> None:
    # Arrange — the quote was drawn while the SKU was on sale; then the operator acted.
    job_id = await _quoted_image(harness)
    settings = harness.rt.settings
    if block == "paused":
        await set_paused(harness.rt.switches, MediaSku.IMAGE, paused=True)
    elif block == "not_offered":
        settings = settings.model_copy(update={"is_image_offered": False})
    else:
        # O11 applies to the LOCAL tier only, so the charge sees a real local backend.
        settings = settings.model_copy(
            update={"use_fake_providers": False, "image_backend": "local"}
        )
        await set_gpu_reserved_until(harness.rt.switches, FIXED_NOW + timedelta(hours=1))

    # Act
    result = await _switched_charge(harness, rail, settings)(_view(job_id))

    # Assert — refused before the charge: no intent, the row is still the quote.
    assert isinstance(result, Err)
    expected = MEDIA_STALE_KEY if block == "not_offered" else MEDIA_BUSY_KEY
    assert result.error.user_message_key == expected
    assert await _intents(harness) == 0
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED


async def test_a_pay_press_past_the_daily_cap_opens_no_intent(
    harness: Harness, rail: SqlPaymeLedger
) -> None:
    # Arrange — one image already paid today, and a cap of one (§7.6).
    earlier = await _quoted_image(harness)
    async with harness.sessions.begin() as db:
        await db.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == earlier)
            .values(state=MediaJobState.DELIVERED, paid_via=MediaPaidVia.PAYME, paid_at=FIXED_NOW)
        )
    job_id = await _quoted_row(harness, MediaSku.IMAGE)
    capped = harness.rt.settings.model_copy(update={"media_daily_cap_image": 1})

    # Act
    result = await _switched_charge(harness, rail, capped)(_view(job_id))

    # Assert
    assert isinstance(result, Err)
    assert result.error.user_message_key == MEDIA_DAILY_CAP_KEY
    assert await _intents(harness) == 0
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED


# ---------------------------------------------------------------------------
# A dead intent is withdrawn, never "too late" (§2.6)
# ---------------------------------------------------------------------------
async def _end_intent(harness: Harness, intent_id: UUID, state: PaymentIntentState) -> None:
    async with harness.sessions.begin() as db:
        await db.execute(
            sa.update(PaymentIntentRow).where(PaymentIntentRow.id == intent_id).values(state=state)
        )


@pytest.mark.parametrize("ended", [PaymentIntentState.EXPIRED, PaymentIntentState.CANCELLED])
async def test_cancel_on_a_pay_link_whose_intent_ended_cancels_the_job(
    harness: Harness, rail: SqlPaymeLedger, ended: PaymentIntentState
) -> None:
    job_id = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, job_id)
    await _end_intent(harness, opened.intent_id, ended)
    desk = SqlMediaDesk(
        harness.sessions, queue=harness.queue, settings=harness.rt.settings, clock=lambda: FIXED_NOW
    )

    outcome = await desk.cancel(job_id, telegram_user_id=USER)

    assert is_ok(outcome) and outcome.value is CancelOutcome.CANCELLED
    assert (await _job(harness, job_id)).state is MediaJobState.CANCELLED


async def test_a_pay_press_on_an_expired_intent_hands_out_no_dead_link(
    harness: Harness, rail: SqlPaymeLedger
) -> None:
    job_id = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, job_id)
    await _end_intent(harness, opened.intent_id, PaymentIntentState.EXPIRED)

    again = await _charge(harness, rail)(_view(job_id))

    assert isinstance(again, Err)
    assert again.error.user_message_key == MEDIA_STALE_KEY


async def test_slash_cancel_withdraws_every_pay_link_not_only_the_newest_row(
    harness: Harness, rail: SqlPaymeLedger
) -> None:
    # Arrange — an image pay link out, and a NEWER video of the same account in progress:
    # the one-open-request rule is per kind, so both are open at once.
    image = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, image)
    async with harness.sessions.begin() as db:
        video = MediaJobRow(
            **{
                column.key: getattr(await db.get(MediaJobRow, image), column.key)
                for column in sa.inspect(MediaJobRow).mapper.column_attrs
                if column.key not in ("id", "payment_intent_id")
            }
        )
        video.id = uuid4()
        video.kind = MediaKind.VIDEO
        video.sku = MediaSku.VIDEO_STANDARD
        video.state = MediaJobState.GENERATING
        video.created_at = FIXED_NOW + timedelta(minutes=1)
        db.add(video)
    desk = SqlMediaDesk(
        harness.sessions, queue=harness.queue, settings=harness.rt.settings, clock=lambda: FIXED_NOW
    )

    # Act
    slash = await desk.cancel_open(USER)

    # Assert — the image's intent and row are withdrawn; the paid video is untouched.
    assert is_ok(slash) and slash.value is CancelOutcome.CANCELLED
    assert (await _job(harness, image)).state is MediaJobState.CANCELLED
    found = await rail.intent(public_ref=opened.public_ref)
    assert is_ok(found) and found.value is not None
    assert found.value.state.value == PaymentIntentState.CANCELLED.value
    assert (await _job(harness, video.id)).state is MediaJobState.GENERATING


# ---------------------------------------------------------------------------
# The uploads' clock follows the CONFIGURED deadline (§3.2.2, §3.5)
# ---------------------------------------------------------------------------
async def test_media_start_re_stamps_the_uploads_clock_from_the_configured_deadline(
    container: AppContainer, tmp_path: Path, rail: SqlPaymeLedger
) -> None:
    # Arrange — an operator raised the image deadline; the gateway only knows the default.
    raised = timedelta(hours=6)
    live = media_settings(
        container.settings,
        checkout_provider="payme",
        payme_is_sandbox=False,
        payme_merchant_id=_MERCHANT,
        media_image_deadline_s=int(raised.total_seconds()),
    )
    harness = build_harness(live, container.require_session_factory(), tmp_path, FIXED_NOW)
    job_id = await _quoted_image(harness, photos=(jpeg_bytes(),))
    opened = await _pay_link(harness, rail, job_id)
    await _perform(rail, opened, amount=_PRICE, tid="tx-clock")

    # Act
    await harness.run(MEDIA_START_JOB, str(job_id), 0)

    # Assert
    async with harness.sessions() as db:
        clocks = set(
            (
                await db.scalars(
                    sa.select(MediaInputRow.expires_at).where(MediaInputRow.job_id == job_id)
                )
            ).all()
        )
    assert clocks == {FIXED_NOW + raised + MEDIA_REVIEW_SLA}


# ---------------------------------------------------------------------------
# §7.3: every member has an arm at every match site, at runtime and not only under mypy
# ---------------------------------------------------------------------------
_MEDIA_MEMBERS: Final[frozenset[str]] = frozenset(sku.value for sku in MediaSku)


class _Opener:
    """A ``PaymentIntentOpener`` that records the snapshot a product's arm chose."""

    def __init__(self) -> None:
        self.opened: list[dict[str, Any]] = []

    async def open_intent(self, **fields: Any) -> Any:
        self.opened.append(fields)
        return err(CheckoutError("recorded, not opened"))


@pytest.mark.parametrize("product", list(Product), ids=lambda p: p.value)
async def test_every_product_has_a_defined_outcome_at_every_match_site(
    product: Product, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    is_media = product.value in _MEDIA_MEMBERS
    intent_product = IntentProduct(product.value)

    # The song checkout: a price and a key for a song, a refusal for a media SKU.
    amount = song_checkout._song_amount_minor(Pricing.from_settings(settings), product)
    assert (amount is None) is is_media
    if is_media:
        with pytest.raises(ValueError):
            song_checkout._idempotency_key(1, "scope", product=product, seq=0)
    else:
        assert song_checkout._idempotency_key(1, "scope", product=product, seq=0)

    # PaymeCheckoutProvider.charge: each arm snapshots exactly its own marker.
    opener = _Opener()
    provider = PaymeCheckoutProvider(
        opener,
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
    job_id = uuid4()
    await provider.charge(
        PurchaseRequest(
            telegram_user_id=USER,
            product=product,
            amount_minor=_PRICE,
            currency="UZS",
            idempotency_key=f"k:{product.value}",
            resume_media_job_id=job_id if is_media else None,
        )
    )
    (opened,) = opener.opened
    assert opened["resume_media_job_id"] == (job_id if is_media else None)
    assert (opened["plan_songs"] is not None) is (product is Product.STARTER)

    # The settlement announcement: a song sentence, or the fail-closed ``None`` for media.
    async def sentence(*_: Any, **__: Any) -> str:
        return "song"

    monkeypatch.setattr(payme_jobs, "_single_song_sentence", sentence)
    monkeypatch.setattr(payme_jobs, "_plan_sentence", sentence)
    announced = await payme_jobs._announcement(
        cast(Any, None),
        cast(Any, SimpleNamespace(product=product, public_ref="ref")),
        telegram_user_id=USER,
        language=Language.EN,
    )
    assert announced == (None if is_media else "song")

    # Check/Create's media rung: a song passes, a media intent naming no job is refused.
    ledger = SqlPaymeLedger(cast(Any, None), merchant_id=_MERCHANT)
    row = cast(
        Any,
        SimpleNamespace(product=intent_product, resume_media_job_id=None, public_ref="ref"),
    )
    if is_media:
        with pytest.raises(PaymeFault):
            await ledger._media_job_payable_or_refuse(cast(Any, None), row)
    else:
        await ledger._media_job_payable_or_refuse(cast(Any, None), row)

    # _write_sale routes to exactly one book.
    books: list[str] = []

    async def write(book: str) -> Any:
        async def recorder(*_: Any, **__: Any) -> None:
            books.append(book)

        return recorder

    monkeypatch.setattr(payme_ledger, "write_single_sale", await write("topup"))
    monkeypatch.setattr(payme_ledger, "write_plan_sale", await write("plan"))
    monkeypatch.setattr(ledger, "_write_media_sale", await write("media"), raising=False)
    await ledger._write_sale(
        cast(Any, None),
        intent=cast(
            Any,
            SimpleNamespace(
                product=intent_product,
                amount_minor=_PRICE,
                currency="UZS",
                idempotency_key="k",
                public_ref="ref",
                plan_songs=12,
                plan_days=30,
            ),
        ),
        telegram_user_id=USER,
        reference="tx",
        now=FIXED_NOW,
    )
    expected_book = {Product.SINGLE: "topup", Product.STARTER: "plan"}.get(product, "media")
    assert books == [expected_book]

    # The admin lifeline note and receipt router.
    note = billing_schemas._grants_nothing(product.value)
    assert (note is LifelineNote.MEDIA_GRANTS_NOTHING) is is_media
    for name, book in (
        ("topup_receipt_for_key", "topup"),
        ("plan_receipt_for_key", "plan"),
        ("media_receipt_for_key", "media"),
    ):

        async def receipt(*_: Any, _book: str = book, **__: Any) -> Any:
            return _book

        monkeypatch.setattr(billing_router, name, receipt)
    found = await billing_router._receipt_for(
        cast(Any, None), cast(Any, SimpleNamespace(product=product.value)), idempotency_key="k"
    )
    assert cast(Any, found) == expected_book


def test_the_admin_sites_fail_closed_on_a_product_this_build_does_not_know() -> None:
    assert billing_schemas._grants_nothing("sticker") is None


async def test_a_settlement_of_an_intent_with_an_unknown_product_unwinds_with_no_receipt(
    harness: Harness, rail: SqlPaymeLedger
) -> None:
    # Arrange — a real media intent, whose stored product is then one this build lacks.
    job_id = await _quoted_image(harness)
    opened = await _pay_link(harness, rail, job_id)
    async with harness.sessions.begin() as db:
        await db.execute(
            sa.text("UPDATE payment_intents SET product = 'sticker' WHERE id = :id"),
            {"id": opened.intent_id.hex},
        )

    # Act
    try:
        forced = await rail.force_settle(public_ref=opened.public_ref, now=FIXED_NOW, note="INC")
    except Exception:  # an unmapped product may surface as a raise; either way nothing commits
        forced = None

    # Assert — nothing settled: no receipt, the intent still pending, the job still waiting.
    assert forced is None or is_err(forced)
    async with harness.sessions() as db:
        assert (await db.scalar(sa.select(sa.func.count()).select_from(MediaPurchaseRow))) == 0
        state = await db.scalar(
            sa.text("SELECT state FROM payment_intents WHERE id = :id"),
            {"id": opened.intent_id.hex},
        )
    assert state == PaymentIntentState.PENDING.value
    assert (await _job(harness, job_id)).state is MediaJobState.AWAITING_PAYMENT
