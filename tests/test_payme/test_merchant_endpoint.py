"""The money outcomes, through the full ASGI stack. Rows counted, not replies believed.

``tests/test_payme/test_state_machine.py`` proves the ledger's commit boundary against a real
database; ``tests/test_payme/test_http.py`` proves the wire rules against the real router. This
file is the join: it drives the same requests Payme will send, through authentication, through
the dispatcher, into the ledger, and then it counts rows. A reply saying ``state: 2`` is not
evidence that a credit was granted, and a reply saying ``-32400`` is not evidence that nothing
was.

**The four claims.** One perform writes exactly one receipt and exactly one grant. A SECOND
perform — the retry Payme sends whenever our answer was lost — writes neither and returns the
STORED ``perform_time``, byte for byte. A create followed by a cancel writes neither and
releases the intent so the customer can try another card. And a failure injected into the sale
write leaves nothing behind at all: no receipt, no grant, and the transaction still in state 1,
because the flip, the claim, the receipt and the grant are one commit or none.

No network, no Redis, no Postgres, no marker: in-memory SQLite and a made-up 36-character key.
The notifier is a recorder rather than the real ARQ enqueue, so the suite proves the enqueue
happens after the commit without a queue being up.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa

from hbd.checkout import PaymentIntent, Product
from hbd.contracts import is_ok
from hbd.db.base import utc_now
from hbd.db.enums import CreditEntryKind, PaymentIntentState, PaymeState
from hbd.db.models import CreditLedgerRow
from hbd.db.models.payme_rpc_log import PaymeRpcLogRow
from hbd.db.models.payme_transaction import PaymeTransactionRow
from hbd.db.models.payment_intent import PaymentIntentRow
from hbd.db.models.topup_purchase import TopupPurchaseRow
from hbd.errors import StorageError
from hbd.payme.app import PAYME_PATH, create_app
from hbd.payme.container import PaymeContainer, SqlRpcJournal, build_payme_container
from hbd.payme.protocol import CancelReason, PaymeErrorCode, to_ms
from hbd.payme.service import PaymeService
from hbd.payme.settings import PAYME_ENV_FILE_VAR, PaymeSettings, build_payme_settings
from tests.test_payme.test_http import _basic

_MEMORY_URL: Final[str] = "sqlite+aiosqlite:///:memory:"
_KEY: Final[str] = "d4f1a9c07b2e46d8ab53c1e90f7a2b6c5d3e"
_LOGIN: Final[str] = "Paycom"
_MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"
#: Well outside 2**31, matching the rest of the payme suite: an accidental ``Integer`` column
#: on this path would not fail loudly, it would truncate the id of whoever is paying.
_USER: Final[int] = 8_912_345_678_901
#: 7 000 soʻm in tiyin. Already the number Payme is sent — nothing on this path multiplies.
_PRICE: Final[int] = 700_000


class _RecordingNotifier:
    """Stands in for the ARQ enqueue. Records what it was asked to tell the customer about."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, public_ref: str) -> None:
        self.calls.append(public_ref)


@pytest.fixture(autouse=True)
def _no_local_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(PAYME_ENV_FILE_VAR, str(tmp_path / "absent.env"))


@pytest.fixture
def notifier() -> _RecordingNotifier:
    return _RecordingNotifier()


@pytest.fixture
async def container(notifier: _RecordingNotifier) -> AsyncIterator[PaymeContainer]:
    """A real container with the queue handle swapped for a recorder.

    Everything else is the production object graph: the real engine, the real
    ``SqlPaymeLedger``, the real journal. Only the one edge that would need a running Redis is
    replaced, and it is replaced with something that can be asserted about.
    """
    settings: PaymeSettings = build_payme_settings(
        {
            "_env_file": None,
            "database_url": _MEMORY_URL,
            "payme_enabled": True,
            "payme_merchant_id": _MERCHANT,
            "payme_merchant_key": _KEY,
            "payme_basic_login": _LOGIN,
        }
    )
    built = await build_payme_container(settings)
    wired = replace(
        built,
        service=PaymeService(
            built.ledger,
            clock=built.clock,
            journal=SqlRpcJournal(built.session_factory),
            notify=notifier,
            account_field=settings.payme_account_field,
            duplicate_code=settings.payme_duplicate_transaction_code,
        ),
    )
    yield wired
    await built.aclose()


@pytest.fixture
async def client(container: PaymeContainer) -> AsyncIterator[httpx.AsyncClient]:
    application = create_app(container=container)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as opened:
            yield opened


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def call(client: httpx.AsyncClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """One authenticated JSON-RPC call. Asserts the 200 and the envelope shape on the way out."""
    response = await client.post(
        PAYME_PATH,
        json={"method": method, "params": params, "id": 1},
        headers={"Authorization": _basic(_LOGIN, _KEY)},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert ("result" in body) != ("error" in body)
    return body


async def open_intent(container: PaymeContainer, *, key: str | None = None) -> PaymentIntent:
    """Open one intent through the bot's own port — the only way a payable order exists."""
    opened = await container.ledger.open_intent(
        telegram_user_id=_USER,
        product=Product.SINGLE,
        amount_minor=_PRICE,
        currency="UZS",
        idempotency_key=key or f"topup:{_USER}:single:{uuid4().hex[:8]}",
        language="uz_latn",
        merchant_id=_MERCHANT,
        is_sandbox=True,
    )
    assert is_ok(opened), opened
    return opened.value


def payme_id() -> str:
    """A 24-character hex id, the shape of the Mongo ObjectId the rail actually sends."""
    return uuid4().hex[:24]


async def count_of(container: PaymeContainer, table: type[Any]) -> int:
    async with container.session_factory() as session:
        total = await session.scalar(sa.select(sa.func.count()).select_from(table))
        return int(total or 0)


async def grants_in(container: PaymeContainer) -> int:
    async with container.session_factory() as session:
        total = await session.scalar(
            sa.select(sa.func.count())
            .select_from(CreditLedgerRow)
            .where(CreditLedgerRow.kind == CreditEntryKind.GRANT)
        )
        return int(total or 0)


async def transaction_row(container: PaymeContainer, identifier: str) -> PaymeTransactionRow:
    async with container.session_factory() as session:
        return (
            await session.execute(
                sa.select(PaymeTransactionRow).where(
                    PaymeTransactionRow.payme_transaction_id == identifier
                )
            )
        ).scalar_one()


async def intent_row(container: PaymeContainer, public_ref: str) -> PaymentIntentRow:
    async with container.session_factory() as session:
        return (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == public_ref)
            )
        ).scalar_one()


def account(intent: PaymentIntent) -> dict[str, str]:
    return {"order_id": intent.public_ref}


def now_ms() -> int:
    moment: datetime = utc_now()
    return to_ms(moment)


# ---------------------------------------------------------------------------
# The happy path, counted
# ---------------------------------------------------------------------------
async def test_check_perform_allows_a_fresh_intent_and_writes_no_money_rows(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    # Arrange
    intent = await open_intent(container)

    # Act
    body = await call(
        client, "CheckPerformTransaction", {"amount": _PRICE, "account": account(intent)}
    )

    # Assert
    assert body["result"] == {"allow": True}
    assert await count_of(container, TopupPurchaseRow) == 0
    assert await grants_in(container) == 0


async def test_one_perform_writes_exactly_one_receipt_and_exactly_one_grant(
    client: httpx.AsyncClient, container: PaymeContainer, notifier: _RecordingNotifier
) -> None:
    """The whole integration, in four requests and three counts."""
    # Arrange
    intent = await open_intent(container)
    identifier = payme_id()
    await call(client, "CheckPerformTransaction", {"amount": _PRICE, "account": account(intent)})
    created = await call(
        client,
        "CreateTransaction",
        {"id": identifier, "time": now_ms(), "amount": _PRICE, "account": account(intent)},
    )
    assert created["result"]["state"] == 1

    # Act
    performed = await call(client, "PerformTransaction", {"id": identifier})

    # Assert
    assert performed["result"]["state"] == 2
    assert performed["result"]["perform_time"] > 0
    assert await count_of(container, TopupPurchaseRow) == 1
    assert await grants_in(container) == 1
    assert (await intent_row(container, intent.public_ref)).state == PaymentIntentState.PAID
    # The customer is told by the WORKER: this process holds no Telegram token, so the only
    # thing it can do about a settled payment is hand the reference to the queue.
    assert notifier.calls == [intent.public_ref]


async def test_a_replayed_perform_returns_the_same_perform_time_and_grants_nothing_twice(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """Payme resends on a lost response and asserts the second answer matches the first."""
    # Arrange
    intent = await open_intent(container)
    identifier = payme_id()
    await call(
        client,
        "CreateTransaction",
        {"id": identifier, "time": now_ms(), "amount": _PRICE, "account": account(intent)},
    )
    first = await call(client, "PerformTransaction", {"id": identifier})

    # Act
    second = await call(client, "PerformTransaction", {"id": identifier})

    # Assert
    assert second["result"] == first["result"]
    assert await count_of(container, TopupPurchaseRow) == 1
    assert await grants_in(container) == 1


async def test_a_replayed_create_returns_the_stored_create_time(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    # Arrange
    intent = await open_intent(container)
    identifier = payme_id()
    params = {"id": identifier, "time": now_ms(), "amount": _PRICE, "account": account(intent)}
    first = await call(client, "CreateTransaction", params)

    # Act
    second = await call(client, "CreateTransaction", params)

    # Assert
    assert second["result"] == first["result"]
    assert await count_of(container, PaymeTransactionRow) == 1


async def test_create_then_cancel_writes_no_money_and_releases_the_intent(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """A declined card must let the customer try another one within seconds."""
    # Arrange
    intent = await open_intent(container)
    identifier = payme_id()
    await call(
        client,
        "CreateTransaction",
        {"id": identifier, "time": now_ms(), "amount": _PRICE, "account": account(intent)},
    )

    # Act
    cancelled = await call(
        client, "CancelTransaction", {"id": identifier, "reason": int(CancelReason.DEBIT_ERROR)}
    )

    # Assert
    assert cancelled["result"]["state"] == -1
    assert cancelled["result"]["cancel_time"] > 0
    assert await count_of(container, TopupPurchaseRow) == 0
    assert await grants_in(container) == 0
    assert (await intent_row(container, intent.public_ref)).state == PaymentIntentState.PENDING


async def test_a_cancelled_transaction_replays_its_stored_cancel_time_as_a_success(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    # Arrange
    intent = await open_intent(container)
    identifier = payme_id()
    await call(
        client,
        "CreateTransaction",
        {"id": identifier, "time": now_ms(), "amount": _PRICE, "account": account(intent)},
    )
    first = await call(client, "CancelTransaction", {"id": identifier, "reason": 1})

    # Act
    second = await call(client, "CancelTransaction", {"id": identifier, "reason": 1})

    # Assert
    assert second["result"] == first["result"]


async def test_check_transaction_reports_the_three_clocks_with_zero_for_what_has_not_happened(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """Integer ``0`` and never ``null``: the PHP template's null is the known deviation."""
    # Arrange
    intent = await open_intent(container)
    identifier = payme_id()
    await call(
        client,
        "CreateTransaction",
        {"id": identifier, "time": now_ms(), "amount": _PRICE, "account": account(intent)},
    )

    # Act
    body = await call(client, "CheckTransaction", {"id": identifier})

    # Assert
    result = body["result"]
    assert result["create_time"] > 0
    assert result["perform_time"] == 0
    assert result["cancel_time"] == 0
    assert result["reason"] is None
    assert result["state"] == 1


async def test_get_statement_returns_our_id_under_transaction_and_theirs_under_id(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """The one reply where the two identifiers change places, plus the account object."""
    # Arrange
    intent = await open_intent(container)
    identifier = payme_id()
    moment = now_ms()
    created = await call(
        client,
        "CreateTransaction",
        {"id": identifier, "time": moment, "amount": _PRICE, "account": account(intent)},
    )

    # Act
    body = await call(client, "GetStatement", {"from": moment - 1000, "to": moment + 1000})

    # Assert
    rows = body["result"]["transactions"]
    assert len(rows) == 1
    assert rows[0]["id"] == identifier
    assert rows[0]["transaction"] == created["result"]["transaction"]
    assert rows[0]["account"] == {"order_id": intent.public_ref}
    assert rows[0]["amount"] == _PRICE


# ---------------------------------------------------------------------------
# Refusals that must not cost money
# ---------------------------------------------------------------------------
async def test_a_wrong_amount_is_minus_31001_and_never_a_reprice(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """A price change between the tap and the payment must not silently charge a new number."""
    # Arrange
    intent = await open_intent(container)

    # Act
    body = await call(
        client, "CheckPerformTransaction", {"amount": _PRICE + 1, "account": account(intent)}
    )

    # Assert
    assert body["error"]["code"] == PaymeErrorCode.WRONG_AMOUNT


async def test_an_unknown_account_reference_is_minus_31050_with_the_subfield_name_in_data(
    client: httpx.AsyncClient,
) -> None:
    """``data`` is the string a human typed into the cabinet's «Настройка Аккаунт» form."""
    # Act
    body = await call(
        client, "CheckPerformTransaction", {"amount": _PRICE, "account": {"order_id": "deadbeef"}}
    )

    # Assert
    assert body["error"]["code"] == PaymeErrorCode.ACCOUNT_UNKNOWN
    assert body["error"]["data"] == "order_id"
    assert set(body["error"]["message"]) == {"ru", "uz", "en"}


async def test_an_account_object_under_the_wrong_subfield_name_is_minus_31050(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """The single most likely go-live defect: the cabinet and the setting disagree."""
    # Arrange
    intent = await open_intent(container)

    # Act
    body = await call(
        client,
        "CheckPerformTransaction",
        {"amount": _PRICE, "account": {"phone": intent.public_ref}},
    )

    # Assert
    assert body["error"]["code"] == PaymeErrorCode.ACCOUNT_UNKNOWN
    assert body["error"]["data"] == "order_id"


async def test_performing_a_transaction_we_never_created_is_minus_31003_and_writes_nothing(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """PerformTransaction NEVER creates a transaction. An unknown id is -31003, always."""
    # Act
    body = await call(client, "PerformTransaction", {"id": payme_id()})

    # Assert
    assert body["error"]["code"] == PaymeErrorCode.TRANSACTION_NOT_FOUND
    assert await count_of(container, PaymeTransactionRow) == 0
    assert await count_of(container, TopupPurchaseRow) == 0


async def test_cancelling_a_performed_transaction_is_minus_31007_and_reverses_nothing(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """No post-perform reversal is built. See PAYME_INTEGRATION §6 and the manual-refund runbook.

    ``credit_accounts.balance`` is a single fungible scalar with no lot structure, so a debit
    could not know whose credit it was burning — a refund of one purchase can take a credit the
    customer paid for in another. PaycomUZ's own template answers the same way by default.
    """
    # Arrange
    intent = await open_intent(container)
    identifier = payme_id()
    await call(
        client,
        "CreateTransaction",
        {"id": identifier, "time": now_ms(), "amount": _PRICE, "account": account(intent)},
    )
    await call(client, "PerformTransaction", {"id": identifier})

    # Act
    body = await call(
        client, "CancelTransaction", {"id": identifier, "reason": int(CancelReason.REFUND)}
    )

    # Assert
    assert body["error"]["code"] == PaymeErrorCode.ORDER_DELIVERED
    assert await grants_in(container) == 1
    assert (await transaction_row(container, identifier)).state == PaymeState.PERFORMED


async def test_change_password_is_dispatched_and_refused_rather_than_unknown(
    client: httpx.AsyncClient,
) -> None:
    """Not a ``-32601`` surprise, and not implemented: rotation is stop, edit, restart."""
    # Act
    body = await call(client, "ChangePassword", {"password": "hunter2"})

    # Assert
    assert body["error"]["code"] == PaymeErrorCode.INTERNAL
    assert "redeploy" in body["error"]["message"]


# ---------------------------------------------------------------------------
# Atomicity — the claim the whole design rests on
# ---------------------------------------------------------------------------
async def test_a_failure_in_the_sale_write_leaves_no_receipt_and_no_flipped_transaction(
    client: httpx.AsyncClient, container: PaymeContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Either all four rows exist or none do — and it is the DATABASE that guarantees it.

    The flip of the transaction, the claim on the intent, the receipt and the credit grant are
    one ``async with sessions.begin()``. Breaking the last of the four must therefore undo the
    first three, which is the difference between "exactly once" being a property and being a
    promise in a docstring.
    """

    # Arrange
    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise StorageError("the sale write failed")

    intent = await open_intent(container)
    identifier = payme_id()
    await call(
        client,
        "CreateTransaction",
        {"id": identifier, "time": now_ms(), "amount": _PRICE, "account": account(intent)},
    )
    monkeypatch.setattr("hbd.db.payme.write_single_sale", _boom)

    # Act
    body = await call(client, "PerformTransaction", {"id": identifier})

    # Assert
    assert body["error"]["code"] == PaymeErrorCode.INTERNAL
    assert await count_of(container, TopupPurchaseRow) == 0
    assert await grants_in(container) == 0
    assert (await transaction_row(container, identifier)).state == PaymeState.CREATED
    assert (await intent_row(container, intent.public_ref)).state == PaymentIntentState.AWAITING


async def test_a_recovered_perform_after_a_failure_still_settles_exactly_once(
    client: httpx.AsyncClient, container: PaymeContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry after an incident is the case this whole design is shaped around."""

    # Arrange
    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise StorageError("the sale write failed")

    intent = await open_intent(container)
    identifier = payme_id()
    await call(
        client,
        "CreateTransaction",
        {"id": identifier, "time": now_ms(), "amount": _PRICE, "account": account(intent)},
    )
    monkeypatch.setattr("hbd.db.payme.write_single_sale", _boom)
    await call(client, "PerformTransaction", {"id": identifier})
    monkeypatch.undo()

    # Act
    recovered = await call(client, "PerformTransaction", {"id": identifier})

    # Assert
    assert recovered["result"]["state"] == 2
    assert await count_of(container, TopupPurchaseRow) == 1
    assert await grants_in(container) == 1


# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------
async def test_every_inbound_call_is_journalled_including_the_ones_we_refuse(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """"Did Payme ever call us about this, and what did we say?" is unanswerable without it.

    The route-template-only request log the admin panel carries cannot answer it: every call
    here lands on one path with one template, and the difference between them is entirely in a
    body nothing is allowed to record.
    """
    # Arrange
    intent = await open_intent(container)

    # Act
    await call(client, "CheckPerformTransaction", {"amount": _PRICE, "account": account(intent)})
    await client.post(PAYME_PATH, content=b"garbage")

    # Assert
    async with container.session_factory() as session:
        rows = (
            (await session.execute(sa.select(PaymeRpcLogRow).order_by(PaymeRpcLogRow.at)))
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert rows[0].method == "CheckPerformTransaction"
    assert rows[0].reply_code == 0
    assert rows[0].public_ref == intent.public_ref
    # The refused call is recorded too, with no method to record and no body anywhere.
    assert rows[1].reply_code == int(PaymeErrorCode.UNAUTHORISED)
    assert rows[1].public_ref is None


# ---------------------------------------------------------------------------
# The one code Payme's own materials disagree about
# ---------------------------------------------------------------------------
async def _gateway_with(duplicate_code: int) -> tuple[PaymeContainer, PaymeSettings]:
    """A second gateway configured with a different duplicate-transaction code."""
    settings: PaymeSettings = build_payme_settings(
        {
            "_env_file": None,
            "database_url": _MEMORY_URL,
            "payme_enabled": True,
            "payme_merchant_id": _MERCHANT,
            "payme_merchant_key": _KEY,
            "payme_basic_login": _LOGIN,
            "payme_duplicate_transaction_code": duplicate_code,
        }
    )
    return await build_payme_container(settings), settings


@pytest.mark.parametrize(
    ("duplicate_code", "carries_account_shape"),
    [(-31008, False), (-31050, True), (-31054, True)],
    ids=["the-sandbox-text", "the-php-template", "an-unallocated-member"],
)
async def test_a_second_transaction_for_a_held_intent_uses_the_settable_duplicate_code(
    duplicate_code: int, carries_account_shape: bool
) -> None:
    """"This order already has another active transaction" is a real contradiction in their docs.

    The sandbox scenario text demands ``-31008``, PaycomUZ's own PHP template returns
    ``-31050``, and three third-party packages pick ``-31054`` or ``-31099``. The code ships as
    an environment variable so a certification finding is a restart rather than a release —
    and the ENVELOPE has to move with it: everything in ``-31050..-31099`` is rendered to the
    customer by Payme's own interface, which needs ``data`` and a three-key message map.
    """
    # Arrange — the mutex point: a second card is refused BEFORE it is charged.
    container, _ = await _gateway_with(duplicate_code)
    try:
        application = create_app(container=container)
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://g") as client:
                intent = await open_intent(container)
                await call(
                    client,
                    "CreateTransaction",
                    {
                        "id": payme_id(),
                        "time": now_ms(),
                        "amount": _PRICE,
                        "account": account(intent),
                    },
                )

                # Act — a different rail-side id against the same, already-held intent.
                body = await call(
                    client,
                    "CreateTransaction",
                    {
                        "id": payme_id(),
                        "time": now_ms(),
                        "amount": _PRICE,
                        "account": account(intent),
                    },
                )
    finally:
        await container.aclose()

    # Assert
    error = body["error"]
    assert error["code"] == duplicate_code
    if carries_account_shape:
        assert error["data"] == "order_id"
        assert set(error["message"]) == {"ru", "uz", "en"}
        assert all(error["message"].values())
    else:
        assert "data" not in error
        assert isinstance(error["message"], str)


async def test_a_failed_notification_enqueue_never_costs_payme_its_200(
    container: PaymeContainer,
) -> None:
    """Redis being down must be a customer told late, never a payment the rail retries.

    The money is committed before the enqueue is attempted, so swallowing the failure loses
    nothing that the sweep's delivery arm cannot pick up sixty seconds later. Answering
    ``-32400`` instead would make Payme retry a settlement that already happened.
    """

    # Arrange
    async def _unreachable(public_ref: str) -> None:
        raise ConnectionError("no redis here")

    application = create_app(
        container=replace(
            container,
            service=PaymeService(
                container.ledger,
                clock=container.clock,
                journal=SqlRpcJournal(container.session_factory),
                notify=_unreachable,
                account_field="order_id",
                duplicate_code=-31008,
            ),
        )
    )
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://g") as client:
            intent = await open_intent(container)
            identifier = payme_id()
            await call(
                client,
                "CreateTransaction",
                {
                    "id": identifier,
                    "time": now_ms(),
                    "amount": _PRICE,
                    "account": account(intent),
                },
            )

            # Act
            body = await call(client, "PerformTransaction", {"id": identifier})

    # Assert
    assert body["result"]["state"] == 2
    assert await count_of(container, TopupPurchaseRow) == 1
    assert await grants_in(container) == 1
