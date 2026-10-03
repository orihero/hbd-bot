"""Tests for RhmtWebhookService: settlement, idempotency, and audit trails."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Any, Final
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from bayram.checkout import PaymentIntent, Product
from bayram.contracts import is_ok
from bayram.db.base import Base
from bayram.db.engine import create_session_factory
from bayram.db.enums import CreditEntryKind, PaymentIntentState
from bayram.db.models import CreditLedgerRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.db.payme import SqlPaymeLedger
from bayram.rhmt.ports import RHMT_PROVIDER_NAME, RhmtInvoiceStatus
from bayram.rhmt.service import RhmtWebhookService

_SECRET: Final[str] = "test_rhmt_secret_12345"
_USER: Final[int] = 8_912_345_678_901
_PRICE: Final[int] = 700_000
_PLAN_PRICE: Final[int] = 4_900_000


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, public_ref: str) -> None:
        self.calls.append(public_ref)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    built = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with built.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield built
    await built.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def notifier() -> _RecordingNotifier:
    return _RecordingNotifier()


@pytest.fixture
def service(
    sessions: async_sessionmaker[AsyncSession],
    notifier: _RecordingNotifier,
) -> RhmtWebhookService:
    return RhmtWebhookService(
        sessions,
        secret=_SECRET,
        scheme="webhooks",
        notify_enqueue=notifier,
    )


async def _open_intent(
    sessions: async_sessionmaker[AsyncSession],
    *,
    product: Product = Product.SINGLE,
    amount_minor: int = _PRICE,
    plan_songs: int | None = None,
    plan_days: int | None = None,
) -> PaymentIntent:
    ledger = SqlPaymeLedger(sessions, merchant_id="test_rhmt")
    res = await ledger.open_intent(
        telegram_user_id=_USER,
        product=product,
        amount_minor=amount_minor,
        currency="UZS",
        idempotency_key=f"topup:{_USER}:{product.value}:{uuid4().hex[:8]}",
        language="uz_latn",
        merchant_id="test_rhmt",
        is_sandbox=True,
        plan_songs=plan_songs,
        plan_days=plan_days,
        provider=RHMT_PROVIDER_NAME,
    )
    assert is_ok(res), res
    return res.value


def _make_payload(
    *,
    invoice_id: str,
    amount: int,
    uuid: str = "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    status: str | int = RhmtInvoiceStatus.SUCCESS.value,
    secret: str = _SECRET,
    scheme: str = "webhooks",
    store_id: int = 1001,
) -> dict[str, Any]:
    if scheme == "success":
        sign_str = f"{store_id}{invoice_id}{amount}{secret}"
        sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
        # The shape Rahmat really sends to callback_url: no status field (captured
        # from a sandbox payment, 2026-09-30). An invented status here once hid that
        # every real legacy callback was acknowledged without settling.
        return {
            "store_id": store_id,
            "amount": amount,
            "invoice_id": invoice_id,
            "invoice_uuid": uuid,
            "billing_id": None,
            "payment_time": "2026-09-30 14:45:21",
            "ps": "uzcard",
            "uuid": uuid,
            "sign": sign,
        }
    sign_str = f"{uuid}{invoice_id}{amount}{secret}"
    sign = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()
    return {
        "uuid": uuid,
        "invoice_id": invoice_id,
        "amount": amount,
        "status": status,
        "sign": sign,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_signature_verification_failure(service: RhmtWebhookService) -> None:
    payload = {
        "uuid": "fake-uuid",
        "invoice_id": "inv_123",
        "amount": 700000,
        "status": 1,
        "sign": "bad-signature",
    }
    status, body = await service.handle_callback(payload)
    assert status == 400
    assert body["success"] is False
    assert body["error"] == "invalid signature"


@pytest.mark.anyio
async def test_missing_invoice_id(service: RhmtWebhookService) -> None:
    uuid = "uuid-123"
    amount = 700000
    sign = hashlib.sha1(f"{uuid}{amount}{_SECRET}".encode()).hexdigest()
    payload = {
        "uuid": uuid,
        "invoice_id": "",
        "amount": amount,
        "status": 1,
        "sign": sign,
    }
    status, body = await service.handle_callback(payload)
    assert status == 400
    assert body["success"] is False
    assert body["error"] == "missing invoice_id"


@pytest.mark.anyio
async def test_unknown_invoice_id(service: RhmtWebhookService) -> None:
    payload = _make_payload(invoice_id="inv_does_not_exist", amount=700000)
    status, body = await service.handle_callback(payload)
    assert status == 404
    assert body["success"] is False
    assert body["error"] == "intent not found"


@pytest.mark.anyio
async def test_single_song_settlement_success(
    sessions: async_sessionmaker[AsyncSession],
    service: RhmtWebhookService,
    notifier: _RecordingNotifier,
) -> None:
    intent = await _open_intent(sessions, product=Product.SINGLE, amount_minor=_PRICE)
    uuid = "multicard-uuid-001"
    payload = _make_payload(invoice_id=intent.public_ref, amount=_PRICE, uuid=uuid)

    status, body = await service.handle_callback(payload)
    assert status == 200
    assert body == {"success": True}

    # Verify intent row updated
    async with sessions() as session:
        intent_row = (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == intent.public_ref)
            )
        ).scalar_one()
        assert intent_row.state == PaymentIntentState.PAID
        assert intent_row.settled_at is not None
        assert intent_row.settle_note == f"rhmt:{uuid}"

        # Verify receipt row created
        topup_rows = (
            (
                await session.execute(
                    sa.select(TopupPurchaseRow).where(TopupPurchaseRow.reference == uuid)
                )
            )
            .scalars()
            .all()
        )
        assert len(topup_rows) == 1
        assert topup_rows[0].telegram_user_id == _USER
        assert topup_rows[0].credits_granted == 1
        assert topup_rows[0].amount_minor == _PRICE
        assert topup_rows[0].provider == RHMT_PROVIDER_NAME

        # Verify credit ledger grant created
        grants = (
            (
                await session.execute(
                    sa.select(CreditLedgerRow).where(
                        CreditLedgerRow.telegram_user_id == _USER,
                        CreditLedgerRow.kind == CreditEntryKind.GRANT,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(grants) == 1
        assert grants[0].delta == 1

    # Verify notification job enqueued with the invoice_id (public_ref)
    assert notifier.calls == [intent.public_ref]


@pytest.mark.anyio
async def test_plan_settlement_success(
    sessions: async_sessionmaker[AsyncSession],
    service: RhmtWebhookService,
    notifier: _RecordingNotifier,
) -> None:
    intent = await _open_intent(
        sessions,
        product=Product.STARTER,
        amount_minor=_PLAN_PRICE,
        plan_songs=10,
        plan_days=30,
    )
    uuid = "multicard-plan-uuid-002"
    payload = _make_payload(invoice_id=intent.public_ref, amount=_PLAN_PRICE, uuid=uuid)

    status, body = await service.handle_callback(payload)
    assert status == 200
    assert body == {"success": True}

    # Verify intent row updated
    async with sessions() as session:
        intent_row = (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == intent.public_ref)
            )
        ).scalar_one()
        assert intent_row.state == PaymentIntentState.PAID

        # Verify plan purchase receipt row created
        plan_rows = (
            (
                await session.execute(
                    sa.select(PlanPurchaseRow).where(PlanPurchaseRow.reference == uuid)
                )
            )
            .scalars()
            .all()
        )
        assert len(plan_rows) == 1
        assert plan_rows[0].telegram_user_id == _USER
        assert plan_rows[0].songs_included == 10
        assert plan_rows[0].amount_minor == _PLAN_PRICE
        assert plan_rows[0].provider == RHMT_PROVIDER_NAME

    assert notifier.calls == [intent.public_ref]


@pytest.mark.anyio
async def test_idempotent_replay_already_paid(
    sessions: async_sessionmaker[AsyncSession],
    service: RhmtWebhookService,
    notifier: _RecordingNotifier,
) -> None:
    intent = await _open_intent(sessions, product=Product.SINGLE, amount_minor=_PRICE)
    payload = _make_payload(invoice_id=intent.public_ref, amount=_PRICE)

    # First delivery
    status1, body1 = await service.handle_callback(payload)
    assert status1 == 200
    assert body1 == {"success": True}
    assert len(notifier.calls) == 1

    # Second delivery (replay)
    status2, body2 = await service.handle_callback(payload)
    assert status2 == 200
    assert body2["success"] is True
    assert body2.get("message") == "already settled"

    # Notification must NOT be enqueued again
    assert len(notifier.calls) == 1

    # Only one topup row exists
    async with sessions() as session:
        topup_count = await session.scalar(sa.select(sa.func.count()).select_from(TopupPurchaseRow))
        assert topup_count == 1


@pytest.mark.anyio
async def test_amount_mismatch_refused(
    sessions: async_sessionmaker[AsyncSession],
    service: RhmtWebhookService,
    notifier: _RecordingNotifier,
) -> None:
    intent = await _open_intent(sessions, product=Product.SINGLE, amount_minor=_PRICE)
    tampered_price = 100_000  # paying less than asked
    payload = _make_payload(invoice_id=intent.public_ref, amount=tampered_price)

    status, body = await service.handle_callback(payload)
    assert status == 400
    assert body["success"] is False
    assert body["error"] == "amount mismatch"

    # Intent stays PENDING
    async with sessions() as session:
        intent_row = (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == intent.public_ref)
            )
        ).scalar_one()
        assert intent_row.state == PaymentIntentState.PENDING

        topup_count = await session.scalar(sa.select(sa.func.count()).select_from(TopupPurchaseRow))
        assert topup_count == 0

    assert len(notifier.calls) == 0


@pytest.mark.anyio
async def test_status_error_or_revert_cancels_intent(
    sessions: async_sessionmaker[AsyncSession],
    service: RhmtWebhookService,
    notifier: _RecordingNotifier,
) -> None:
    intent = await _open_intent(sessions, product=Product.SINGLE, amount_minor=_PRICE)
    payload = _make_payload(
        invoice_id=intent.public_ref,
        amount=_PRICE,
        status=RhmtInvoiceStatus.ERROR.value,
    )

    status, body = await service.handle_callback(payload)
    assert status == 200
    assert body == {"success": True}

    async with sessions() as session:
        intent_row = (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == intent.public_ref)
            )
        ).scalar_one()
        assert intent_row.state == PaymentIntentState.CANCELLED

    assert len(notifier.calls) == 0


@pytest.mark.anyio
async def test_status_draft_or_progress_noop(
    sessions: async_sessionmaker[AsyncSession],
    service: RhmtWebhookService,
    notifier: _RecordingNotifier,
) -> None:
    intent = await _open_intent(sessions, product=Product.SINGLE, amount_minor=_PRICE)
    payload = _make_payload(
        invoice_id=intent.public_ref,
        amount=_PRICE,
        status=RhmtInvoiceStatus.PROGRESS.value,
    )

    status, body = await service.handle_callback(payload)
    assert status == 200
    assert body == {"success": True}

    async with sessions() as session:
        intent_row = (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == intent.public_ref)
            )
        ).scalar_one()
        assert intent_row.state == PaymentIntentState.PENDING

    assert len(notifier.calls) == 0


@pytest.mark.anyio
async def test_legacy_success_md5_scheme_settlement(
    sessions: async_sessionmaker[AsyncSession],
    notifier: _RecordingNotifier,
) -> None:
    service = RhmtWebhookService(
        sessions,
        secret=_SECRET,
        scheme="success",
        notify_enqueue=notifier,
    )
    intent = await _open_intent(sessions, product=Product.SINGLE, amount_minor=_PRICE)
    payload = _make_payload(
        invoice_id=intent.public_ref,
        amount=_PRICE,
        scheme="success",
        store_id=999,
    )

    status, body = await service.handle_callback(payload)
    assert status == 200
    assert body == {"success": True}

    async with sessions() as session:
        intent_row = (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == intent.public_ref)
            )
        ).scalar_one()
        assert intent_row.state == PaymentIntentState.PAID

    assert notifier.calls == [intent.public_ref]
