"""The Rail Board's twelve routes, over HTTP, against the state this deployment is actually in.

**Most of this file asserts the EMPTY rail**, and that is the point rather than a gap.
``merchant_id`` is literally ``placeholder`` on the host, ``is_sandbox`` boots true and
``CHECKOUT_PROVIDER`` is unset, so every count these routes return is ``0`` today and will be
for weeks. A section whose zero state reads as "broken" is a section nobody opens twice, so the
empty answers are asserted as hard as the populated ones — the probes beside every count, the
``never_settled`` verdict that must not be ``balanced``, and the 200 (never a 404, never a 500)
that a rail with three empty tables has to produce.

**The refusals are asserted by CODE and by the parameter they name**, not by "not 200". A 422
that names ``from`` and a 409 that names ``already_notified`` are two different screens with two
different remedies, and a test that only checked the status would pass on either.

The three writes are exercised through the real CSRF and permission machinery: the switch flips
a key in the fake Redis that ``bayram.payme.pause`` itself wrote, the notify records the enqueue
it did not make on ``NullAdminQueue``, and both write an ``admin_audit_log`` row inside the
request's own transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Final
from uuid import uuid4

import httpx
import pytest

from bayram.admin.container import AdminContainer
from bayram.admin.errors import AdminErrorCode
from bayram.admin.queue import NullAdminQueue, job_id_for_payment_notification
from bayram.admin.routers.billing import (
    ATTENTION_PATH,
    CALLS_PATH,
    FAULTS_PATH,
    FUNNEL_PATH,
    INTENT_NOTIFY_PATH,
    INTENT_PATH,
    INTENTS_PATH,
    LOOKUP_PATH,
    RAIL_PATH,
    RAIL_PAUSE_PATH,
    RAIL_RESUME_PATH,
    SETTLEMENT_PATH,
)
from bayram.admin.settings import AdminSettings
from bayram.contracts import Result, ok
from bayram.db.enums import (
    AdminRole,
    AuditAction,
    AuditReasonCode,
    IntentProduct,
    PaymentIntentState,
    PaymeState,
)
from bayram.db.models.admin_audit import AdminAuditRow
from bayram.errors import ErrorCode
from bayram.payme.pause import PAUSED_VALUE, PAYME_PAUSE_KEY
from tests.test_admin.conftest import (
    NOW,
    ORIGIN,
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    csrf_headers,
    open_client,
    open_container,
    sign_in,
)
from tests.test_db.rail_helpers import (
    MERCHANT,
    USER,
    add,
    make_call,
    make_grant,
    make_intent,
    make_topup_receipt,
    make_transaction,
    settle,
)

#: An id no row uses. Every route that takes one must answer without touching a table.
UNKNOWN_INTENT: Final[str] = "3f2b9c1e-0a5d-4f61-9c2a-7b18d4e6f0a3"
#: A well-formed 24-hex reference that matches nothing — the "no payment under that reference"
#: screen, which is a 200 and NOT a 404.
UNMATCHED_REF: Final[str] = "9f13c0a72b4e8d5610fa37cc"
WINDOW: Final[str] = "?from=2026-01-01T00:00:00Z&to=2027-01-01T00:00:00Z"


class ReplayingQueue(NullAdminQueue):
    """A queue that answers the way ARQ does when it already holds the deterministic job id.

    ``NullAdminQueue`` deliberately keeps a LIST of calls rather than a job registry, so it
    cannot detect a duplicate and does not pretend to — inventing a duplicate rule there would
    be asserted by tests and true of nothing. The replay branch still has to be exercised, so
    the fake that models it is declared here, next to the one test that needs it, and still
    records the call so the assertion can be about the arguments.
    """

    async def enqueue_payment_notification(self, public_ref: str) -> Result[str | None]:
        await super().enqueue_payment_notification(public_ref)
        return ok(None)


@pytest.fixture
async def replaying_panel(
    admin_settings: AdminSettings, fake_redis: FakeRedis, rate_limits: MemoryRateLimits
) -> AsyncIterator[tuple[AdminContainer, httpx.AsyncClient]]:
    """A second application whose queue reports every enqueue as already-queued."""
    async with (
        open_container(admin_settings, fake_redis, rate_limits, ReplayingQueue()) as built,
        open_client(built) as http,
    ):
        yield built, http


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole = AdminRole.OWNER
) -> None:
    """One operator at ``role``, signed in with the cookie jar a browser would carry."""
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    assert (await sign_in(client, username=username, password=PASSWORD)).status_code == 200


def body(response: httpx.Response) -> Any:
    return response.json()


def error_of(response: httpx.Response) -> dict[str, Any]:
    payload: dict[str, Any] = response.json()["error"]
    return payload


async def audit_rows(container: AdminContainer, action: AuditAction) -> list[AdminAuditRow]:
    import sqlalchemy as sa

    async with container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.action == action)
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


# ---------------------------------------------------------------------------
# The header: what a rail nobody has switched on looks like
# ---------------------------------------------------------------------------
async def test_the_rail_header_is_legible_on_a_deployment_that_has_never_sold_anything(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """Three empty tables and an unset Redis key must produce a 200 that SAYS so.

    This is the state of the host right now, so it is the first assertion in the file. Every
    ``has*`` probe is window-blind, which is what lets the console render "none has ever been
    opened here" rather than a bare zero the operator has to interpret.
    """
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(RAIL_PATH)

    # Assert
    assert response.status_code == 200
    payload = body(response)
    assert payload["checkoutSeen"] is None
    assert payload["lastInboundCall"] is None
    assert payload["isPaused"] is False
    assert payload["pauseKey"] == PAYME_PAUSE_KEY
    assert payload["hasOpenedAnyIntent"] is False
    assert payload["hasRecordedTransaction"] is False
    assert payload["hasRecordedInboundCall"] is False
    assert payload["hasSettledAnyIntent"] is False


async def test_the_header_measures_the_provider_off_the_newest_intent(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """The panel cannot read ``CHECKOUT_PROVIDER`` or ``PAYME_ENABLED`` from anywhere, so the
    three configuration facts are taken from the row the BOT actually wrote."""
    # Arrange
    await add(container.session_factory, make_intent(now=NOW))
    await signed_in(container, client)

    # Act
    payload = body(await client.get(RAIL_PATH))

    # Assert
    assert payload["checkoutSeen"] == {
        "provider": "payme",
        "merchantId": MERCHANT,
        "isSandbox": True,
        "seenAt": payload["checkoutSeen"]["seenAt"],
    }
    assert payload["hasOpenedAnyIntent"] is True
    # The rail has been quoted from and has still never settled anything: two different facts,
    # and the second is what keeps the settlement card honest.
    assert payload["hasSettledAnyIntent"] is False


async def test_the_header_reports_a_paused_rail_as_the_bot_would_see_it(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange — the key as ``pause.set_paused`` writes it, set behind the panel's back.
    fake_redis.values[PAYME_PAUSE_KEY] = PAUSED_VALUE
    await signed_in(container, client)

    # Act / Assert
    assert body(await client.get(RAIL_PATH))["isPaused"] is True


# ---------------------------------------------------------------------------
# The settlement identity
# ---------------------------------------------------------------------------
async def test_the_settlement_identity_refuses_an_unbounded_window(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """ "All time" is a different question, and on two unindexed clock columns it is also a
    full scan on a route the board polls. So it is refused rather than widened."""
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(SETTLEMENT_PATH)

    # Assert
    assert response.status_code == 422
    failure = error_of(response)
    assert failure["code"] == ErrorCode.INVALID_INPUT.value
    assert failure["details"]["parameter"] == "from"


async def test_an_upper_bound_alone_is_still_an_unbounded_window(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``?to=`` alone leaves ``start`` None, which is exactly the scan being refused.
    await signed_in(container, client)

    # Act
    response = await client.get(f"{SETTLEMENT_PATH}?to=2027-01-01T00:00:00Z")

    # Assert
    assert response.status_code == 422
    assert error_of(response)["details"]["parameter"] == "from"


async def test_an_untouched_rail_reports_never_settled_and_not_a_green_tick(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """THE assertion of this file. Four zeros on a rail that has never settled anything must
    not render as balanced: it is indistinguishable from a healthy quiet week."""
    # Arrange
    await signed_in(container, client)

    # Act
    payload = body(await client.get(f"{SETTLEMENT_PATH}{WINDOW}"))

    # Assert
    assert payload["verdict"] == "never_settled"
    assert payload["verdict"] != "balanced"
    assert payload["hasRecordedSettlement"] is False
    assert payload["window"]["since"] is not None
    assert payload["window"]["until"] is not None


async def test_a_settled_rail_reports_the_identity_rather_than_the_virgin_state(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one rail settlement, end to end: performed transaction, receipt, grant.
    # The intent is committed FIRST because ``PaymentIntentRow.id`` is a Python-side
    # ``default=uuid4`` applied at flush: batched with its own transaction row, ``intent.id``
    # is still ``None`` when ``make_transaction`` reads it, and the insert fails on the NOT
    # NULL rather than on anything this test is about.
    intent = settle(make_intent(now=NOW), at=NOW)
    await add(container.session_factory, intent)
    await add(
        container.session_factory,
        make_transaction(intent_id=intent.id, payme_time=NOW, state=PaymeState.PERFORMED),
        make_topup_receipt(intent, at=NOW),
        make_grant(intent, at=NOW),
    )
    await signed_in(container, client)

    # Act
    payload = body(await client.get(f"{SETTLEMENT_PATH}{WINDOW}"))

    # Assert
    assert payload["hasRecordedSettlement"] is True
    assert payload["transactionsPerformed"] == 1
    assert payload["receiptsWritten"] == 1
    assert payload["grantsWritten"] == 1
    assert payload["operatorSettlements"] == 0
    assert payload["verdict"] == "balanced"


# ---------------------------------------------------------------------------
# The funnel, the attention counts and the fault clusters
# ---------------------------------------------------------------------------
async def test_the_funnel_omits_states_with_no_rows_and_carries_its_probes(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one pending intent and nothing else.
    await add(container.session_factory, make_intent(now=NOW))
    await signed_in(container, client)

    # Act
    payload = body(await client.get(FUNNEL_PATH))

    # Assert — one bar, not five. A zero bar is a claim about payments nobody attempted.
    #
    # The bar carries MONEY as well as a count, and the money is what the strip leads with: a
    # payments screen is read to answer "how much did we take", which `count` answers
    # identically for one 7 000 so'm song and for a hundred. `amountMinor` is tiyin, so 700_000
    # is the one 7 000 so'm intent `make_intent` writes, and `currency` is the intent's own —
    # the server groups by it so a second currency arrives as a second bar rather than being
    # summed into this one.
    assert payload["intents"] == [
        {
            "state": PaymentIntentState.PENDING.value,
            "count": 1,
            "amountMinor": 700_000,
            "currency": "UZS",
        }
    ]
    assert payload["transactions"] == []
    assert (payload["rpcCalls"], payload["rpcFaults"]) == (0, 0)
    assert payload["hasRecordedTransaction"] is False
    assert payload["hasRecordedInboundCall"] is False


@pytest.mark.parametrize("hours", ["0", "169"])
async def test_a_staleness_window_outside_the_bounds_is_refused_by_name(
    container: AdminContainer, client: httpx.AsyncClient, hours: str
) -> None:
    """Refused, never clamped: a clamped value answers a different question with no way for the
    caller to notice."""
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(f"{ATTENTION_PATH}?staleAfterHours={hours}")

    # Assert
    assert response.status_code == 422
    failure = error_of(response)
    assert failure["code"] == ErrorCode.INVALID_INPUT.value
    assert any("staleAfterHours" in field for field in failure["details"]["fields"])


async def test_the_attention_counts_default_to_the_rails_own_timeout(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    payload = body(await client.get(ATTENTION_PATH))

    # Assert — twelve hours, derived from ``DEFAULT_TRANSACTION_TIMEOUT_MS`` rather than picked.
    assert payload["staleAfterHours"] == 12
    assert payload["awaitingHeldPastTimeout"] == 0
    assert payload["paidNeverAnnounced"] == 0
    assert payload["paidWithNoReceipt"] == 0


async def test_an_oversized_fault_cluster_limit_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(f"{FAULTS_PATH}?limit=51")

    # Assert
    assert response.status_code == 422
    assert any("limit" in field for field in error_of(response)["details"]["fields"])


async def test_the_fault_table_groups_by_method_and_reply_code(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two identical faults and one success. Success is not a cluster.
    await add(
        container.session_factory,
        make_call(at=NOW, method="CheckTransaction", reply_code=-31003),
        make_call(at=NOW + timedelta(minutes=1), method="CheckTransaction", reply_code=-31003),
        make_call(at=NOW, method="CheckPerformTransaction", reply_code=0),
    )
    await signed_in(container, client)

    # Act
    payload = body(await client.get(FAULTS_PATH))

    # Assert
    assert payload["hasRecordedInboundCall"] is True
    assert [(row["method"], row["replyCode"], row["calls"]) for row in payload["clusters"]] == [
        ("CheckTransaction", -31003, 2)
    ]


async def test_the_journal_pages_and_says_the_peer_is_the_rail(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await add(container.session_factory, make_call(at=NOW, public_ref="abc123"))
    await signed_in(container, client)

    # Act
    payload = body(await client.get(f"{CALLS_PATH}?withTotal=true"))

    # Assert
    assert payload["meta"]["total"] == 1
    [row] = payload["items"]
    assert row["publicRef"] == "abc123"
    assert row["replyCode"] == 0
    assert row["peerIp"] == "185.8.212.10"


# ---------------------------------------------------------------------------
# The payments list and the lookup
# ---------------------------------------------------------------------------
async def test_the_intents_page_carries_its_probes_inside_the_envelope(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """One request, not two: an empty page must be legible from the response that was empty,
    because the console may not make a follow-up and an operator certainly will not."""
    # Arrange
    await signed_in(container, client)

    # Act
    payload = body(await client.get(INTENTS_PATH))

    # Assert
    assert payload["items"] == []
    assert payload["capabilities"] == {
        "hasOpenedAnyIntent": False,
        "hasRecordedTransaction": False,
        "hasSettledAnyIntent": False,
    }


async def test_a_payment_row_masks_its_buyer_and_never_publishes_the_key(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    intent = make_intent(now=NOW)
    await add(container.session_factory, intent)
    await signed_in(container, client)

    # Act
    response = await client.get(INTENTS_PATH)
    [row] = body(response)["items"]

    # Assert — the mask, the explicit flag, and neither the plaintext id nor the join key.
    assert row["isBuyerErased"] is False
    assert row["telegramUserIdMasked"] is not None
    assert str(USER) not in response.text
    assert "topup:" not in response.text
    assert "idempotencyKey" not in response.text


async def test_an_erased_buyer_is_a_state_with_the_money_intact(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``/forget`` nulls ``telegram_user_id`` and leaves every money column standing. The row
    must render as "buyer erased" — never blank, never an error, never a fraud badge."""
    # Arrange
    await add(container.session_factory, make_intent(now=NOW, telegram_user_id=None))
    await signed_in(container, client)

    # Act
    [row] = body(await client.get(INTENTS_PATH))["items"]

    # Assert
    assert row["isBuyerErased"] is True
    assert row["telegramUserIdMasked"] is None
    assert row["amountMinor"] > 0
    assert row["currency"] == "UZS"


async def test_a_hand_settled_payment_is_told_from_a_rail_settled_one(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """ "Did the rail move this money or did one of us?" is the first question of every
    reconciliation, and ``operatorSettlements`` is a named term precisely so the answer is not
    mistaken for a defect."""
    # Arrange
    await add(
        container.session_factory,
        settle(make_intent(now=NOW), at=NOW, note="operator:INC-441"),
    )
    await signed_in(container, client)

    # Act
    [row] = body(await client.get(INTENTS_PATH))["items"]

    # Assert
    assert row["settleSource"] == "operator"
    assert row["settleNote"] == "operator:INC-441"


@pytest.mark.parametrize(
    "query",
    [
        "",
        f"?ref={UNMATCHED_REF}&transactionId=65f0a1b2c3d4e5f601234567",
    ],
    ids=["neither", "both"],
)
async def test_the_lookup_takes_exactly_one_reference(
    container: AdminContainer, client: httpx.AsyncClient, query: str
) -> None:
    # Arrange — both absent is a caller that forgot the box; both present would silently get
    # whichever branch the query layer tries first.
    await signed_in(container, client)

    # Act
    response = await client.get(f"{LOOKUP_PATH}{query}")

    # Assert
    assert response.status_code == 422
    assert error_of(response)["code"] == ErrorCode.INVALID_INPUT.value


async def test_a_malformed_reference_is_a_different_screen_from_a_missing_one(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(f"{LOOKUP_PATH}?ref=not-a-reference")

    # Assert
    assert response.status_code == 422


async def test_a_reference_that_matches_nothing_is_an_answer_and_not_an_error(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """200 with two nulls, never a 404: the question was answered and the answer is no. A 404
    would render an error page for a successful search."""
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(f"{LOOKUP_PATH}?ref={UNMATCHED_REF}")

    # Assert
    assert response.status_code == 200
    assert body(response) == {"intentId": None, "matchedOn": None}


async def test_the_lookup_finds_an_intent_by_its_public_reference(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    intent = make_intent(now=NOW)
    await add(container.session_factory, intent)
    await signed_in(container, client)

    # Act
    payload = body(await client.get(f"{LOOKUP_PATH}?ref={intent.public_ref}"))

    # Assert
    assert payload == {"intentId": str(intent.id), "matchedOn": "public_ref"}


# ---------------------------------------------------------------------------
# The dossier
# ---------------------------------------------------------------------------
async def test_an_unknown_payment_is_a_404_and_a_malformed_id_is_a_422(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    missing = await client.get(INTENT_PATH.format(intent_id=UNKNOWN_INTENT))
    malformed = await client.get(INTENTS_PATH + "/not-a-uuid")

    # Assert — the 422 comes from FastAPI's path converter, which is the whole reason the path
    # parameter is typed ``UUID`` rather than parsed in the handler.
    assert missing.status_code == 404
    assert error_of(missing)["code"] == ErrorCode.NOT_FOUND.value
    assert malformed.status_code == 422


async def test_the_dossier_answers_the_whole_chain_in_one_response(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a settled single-song sale with everything behind it. The intent is committed
    # on its own first: its ``id`` is a flush-time default, so a row batched with it would read
    # ``None`` (see the settlement test above).
    intent = settle(make_intent(now=NOW), at=NOW)
    intent.notified_at = NOW
    await add(container.session_factory, intent)
    await add(
        container.session_factory,
        make_transaction(intent_id=intent.id, payme_time=NOW, state=PaymeState.PERFORMED),
        make_topup_receipt(intent, at=NOW),
        make_grant(intent, at=NOW),
        make_call(at=NOW, method="PerformTransaction", public_ref=intent.public_ref),
    )
    await signed_in(container, client)

    # Act
    response = await client.get(INTENT_PATH.format(intent_id=intent.id))
    payload = body(response)

    # Assert
    assert response.status_code == 200
    assert len(payload["transactions"]) == 1
    assert payload["receipt"]["source"] == "topup_purchases"
    assert len(payload["ledger"]) == 1
    assert len(payload["calls"]) == 1
    assert [step["status"] for step in payload["lifeline"]["steps"]] == ["done"] * 6
    assert payload["chainStop"]["kind"] == "single_song"
    assert payload["notify"] == {
        "canNotify": False,
        "refusalCode": "already_notified",
        "notifiedAt": payload["notify"]["notifiedAt"],
    }
    assert payload["settleCommand"].endswith(
        f"--ref {intent.public_ref} --note '{intent.public_ref}'"
    )
    # The join key is read by the handler and stops there.
    assert "topup:" not in response.text
    assert str(USER) not in response.text


async def test_a_plan_dossier_reads_its_consumption_off_the_receipt(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """For a single song the chain stops at the grant — ``credit_accounts.balance`` is a
    fungible scalar with no lot structure. For a plan it continues, and this is the one route
    that can say so."""
    # Arrange
    from tests.test_db.rail_helpers import make_plan_receipt

    intent = settle(make_intent(now=NOW, product=IntentProduct.STARTER), at=NOW)
    receipt = make_plan_receipt(intent, at=NOW)
    receipt.songs_used = 3
    await add(container.session_factory, intent, receipt)
    await signed_in(container, client)

    # Act
    payload = body(await client.get(INTENT_PATH.format(intent_id=intent.id)))

    # Assert
    assert payload["chainStop"]["kind"] == "plan"
    assert payload["chainStop"]["songsUsed"] == 3
    # The credit step is not-applicable and NOT missing: a plan grants nothing at purchase.
    steps = {step["key"]: step for step in payload["lifeline"]["steps"]}
    assert steps["credit_granted"]["status"] == "not_applicable"
    assert steps["credit_granted"]["noteCode"] == "plan_grants_nothing"


async def test_the_dossier_of_an_erased_buyer_is_a_state_and_not_a_discrepancy(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """The row this whole section is most likely to render as fraud, and must not.

    ``/forget`` ran between the payment starting and the rail settling it, so
    ``db/payme.py::_settle`` claimed the intent and wrote NO sale — the money moved and there
    was nobody left to grant to. Every downstream lookup therefore returns nothing: no receipt,
    no ledger row, no ``notified_at`` that will ever be stamped. This is the shape that makes a
    naive dossier either 500 on a ``None`` or paint three red MISSING steps over a lawful
    erasure, and it is the population ``paidWithNoReceipt`` is DOMINATED by, so it is also the
    one an operator will click into first.
    """
    # Arrange — paid, by the rail, with the buyer gone and nothing written behind it.
    intent = settle(make_intent(now=NOW, telegram_user_id=None), at=NOW)
    await add(container.session_factory, intent)
    await add(
        container.session_factory,
        make_transaction(intent_id=intent.id, payme_time=NOW, state=PaymeState.PERFORMED),
    )
    await signed_in(container, client)

    # Act
    response = await client.get(INTENT_PATH.format(intent_id=intent.id))
    payload = body(response)

    # Assert — a 200 with the money intact and the buyer named as erased, not as absent.
    assert response.status_code == 200
    assert payload["intent"]["isBuyerErased"] is True
    assert payload["intent"]["telegramUserIdMasked"] is None
    assert payload["intent"]["amountMinor"] > 0
    assert payload["receipt"] is None
    assert payload["ledger"] == []

    # The three dead ends are NOT_APPLICABLE with their own reason, never MISSING. A MISSING
    # here is what sends somebody to reconcile a payment that is already correct.
    steps = {step["key"]: step for step in payload["lifeline"]["steps"]}
    assert steps["performed"]["status"] == "done"
    for key in ("receipt", "credit_granted", "customer_told"):
        assert steps[key]["status"] == "not_applicable", key
        assert steps[key]["noteCode"] == "buyer_erased", key

    # And the remedy is refused for the honest reason rather than offered and then failing.
    assert payload["notify"] == {
        "canNotify": False,
        "refusalCode": "buyer_erased",
        "notifiedAt": None,
    }
    # The join key still embeds the Telegram id after erasure — ``anonymise_intents`` keeps it
    # deliberately, as the replay marker — so the absence assertion matters MORE here, not less.
    assert "topup:" not in response.text


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------
async def test_pausing_writes_the_key_the_bot_reads_and_reports_it_back(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    """The response re-reads the key rather than echoing the request, so an operator sees the
    switch as STORED and not as asked for."""
    # Arrange
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    response = await client.post(
        RAIL_PAUSE_PATH,
        json={"reasonCode": AuditReasonCode.INCIDENT.value},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 200
    assert body(response) == {
        "isPaused": True,
        "pauseKey": PAYME_PAUSE_KEY,
        "changedAt": body(response)["changedAt"],
    }
    assert fake_redis.values[PAYME_PAUSE_KEY] == PAUSED_VALUE


async def test_resuming_deletes_the_key_rather_than_writing_a_falsy_value(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange — paused, by the same writer the CLI uses.
    fake_redis.values[PAYME_PAUSE_KEY] = PAUSED_VALUE
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    response = await client.post(
        RAIL_RESUME_PATH,
        json={"reasonCode": AuditReasonCode.INCIDENT.value},
        headers=csrf_headers(client),
    )

    # Assert — a resumed rail leaves no trace to be misread later, so ``EXISTS`` is a complete
    # answer for anybody debugging with ``redis-cli``.
    assert response.status_code == 200
    assert body(response)["isPaused"] is False
    assert PAYME_PAUSE_KEY not in fake_redis.values


async def test_the_switch_needs_a_reason_and_takes_no_step_up(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """A body with no ``reasonCode`` is a 422; a body WITH one succeeds outright. The second
    half is the assertion that matters: if ``RAIL_CONTROL`` ever reaches ``STEP_UP_ACTIONS``
    this becomes a permanent 403 that looks exactly correct."""
    # Arrange
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    unreasoned = await client.post(RAIL_PAUSE_PATH, json={}, headers=csrf_headers(client))
    reasoned = await client.post(
        RAIL_PAUSE_PATH,
        json={"reasonCode": AuditReasonCode.INCIDENT.value},
        headers=csrf_headers(client),
    )

    # Assert
    assert unreasoned.status_code == 422
    assert reasoned.status_code == 200


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (AdminRole.VIEWER, 403),
        (AdminRole.SUPPORT, 403),
        (AdminRole.ADMIN, 200),
        (AdminRole.OWNER, 200),
    ],
    ids=lambda value: str(value),
)
async def test_only_admin_and_owner_may_touch_the_switch(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole, expected: int
) -> None:
    # Arrange — SUPPORT is refused here and allowed on the notify below, which is the whole
    # reason the two are separate cells.
    await signed_in(container, client, role=role)

    # Act
    response = await client.post(
        RAIL_PAUSE_PATH,
        json={"reasonCode": AuditReasonCode.INCIDENT.value},
        headers=csrf_headers(client),
    )

    # Assert — and a refusal is FORBIDDEN, never STEP_UP_REQUIRED: no grant would ever help.
    assert response.status_code == expected
    if expected == 403:
        assert error_of(response)["code"] == AdminErrorCode.FORBIDDEN.value


async def test_a_press_of_the_switch_writes_one_audit_row_about_the_config(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    await client.post(
        RAIL_PAUSE_PATH,
        json={"reasonCode": AuditReasonCode.INCIDENT.value, "reasonRef": "INC-441"},
        headers=csrf_headers(client),
    )

    # Assert
    [row] = await audit_rows(container, AuditAction.RAIL_PAUSED)
    assert row.subject_type == "config"
    assert row.subject_id == "payme_rail"
    assert row.reason_ref == "INC-441"


# ---------------------------------------------------------------------------
# The nudge
# ---------------------------------------------------------------------------
async def paid_unannounced_intent(container: AdminContainer) -> Any:
    """One settled payment the customer was never told about — the population being served."""
    intent = settle(make_intent(now=NOW), at=NOW)
    await add(container.session_factory, intent, make_topup_receipt(intent, at=NOW))
    return intent


async def test_support_may_re_send_a_confirmation(
    container: AdminContainer, client: httpx.AsyncClient, queue: NullAdminQueue
) -> None:
    """SUPPORT holds this cell and holds nothing else on the rail. They are who takes the "I
    paid and nothing happened" call, and this is the most common answer to it."""
    # Arrange
    intent = await paid_unannounced_intent(container)
    await signed_in(container, client, role=AdminRole.SUPPORT)

    # Act
    response = await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=intent.id),
        json={"reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 200
    payload = body(response)
    assert payload["isReplay"] is False
    assert payload["jobId"] == job_id_for_payment_notification(intent.public_ref)
    assert payload["publicRef"] == intent.public_ref
    # The seam carried a job name and a public reference and nothing else.
    [call] = queue.calls
    assert call.public_ref == intent.public_ref
    assert call.arguments == (intent.public_ref,)


async def test_a_viewer_may_not_re_send_a_confirmation(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    intent = await paid_unannounced_intent(container)
    await signed_in(container, client, role=AdminRole.VIEWER)

    # Act
    response = await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=intent.id),
        json={"reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 403
    assert error_of(response)["code"] == AdminErrorCode.FORBIDDEN.value


async def test_a_notify_writes_one_audit_row_naming_the_payment(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``subject_id`` is a dashed UUID rather than the 24-hex ``public_ref`` on purpose: the
    audit boundary refuses credential-shaped values and rewrites the row with
    ``subject_id=None``, so this asserts the value that was actually stored."""
    # Arrange
    intent = await paid_unannounced_intent(container)
    await signed_in(container, client, role=AdminRole.SUPPORT)

    # Act
    await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=intent.id),
        json={"reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value},
        headers=csrf_headers(client),
    )

    # Assert
    [row] = await audit_rows(container, AuditAction.PAYMENT_NOTIFY)
    assert row.subject_type == "payment"
    assert row.subject_id == str(intent.id)
    assert row.record_count == 1


async def test_a_notify_for_an_unknown_payment_is_a_404(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client, role=AdminRole.SUPPORT)

    # Act
    response = await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=UNKNOWN_INTENT),
        json={"reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 404


async def test_an_unpaid_payment_cannot_be_announced(
    container: AdminContainer, client: httpx.AsyncClient, queue: NullAdminQueue
) -> None:
    # Arrange
    intent = make_intent(now=NOW)
    await add(container.session_factory, intent)
    await signed_in(container, client, role=AdminRole.SUPPORT)

    # Act
    response = await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=intent.id),
        json={"reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value},
        headers=csrf_headers(client),
    )

    # Assert — 409 and not 422: the request is well formed and the STATE refuses it.
    assert response.status_code == 409
    failure = error_of(response)
    assert failure["code"] == AdminErrorCode.CONFLICT.value
    assert failure["details"]["refusalCode"] == "not_paid"
    assert queue.calls == []


async def test_an_erased_buyer_cannot_be_announced_to(
    container: AdminContainer, client: httpx.AsyncClient, queue: NullAdminQueue
) -> None:
    """The receipt and the credit are untouched; there is simply nobody left to send to."""
    # Arrange
    intent = settle(make_intent(now=NOW, telegram_user_id=None), at=NOW)
    await add(container.session_factory, intent)
    await signed_in(container, client, role=AdminRole.SUPPORT)

    # Act
    response = await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=intent.id),
        json={"reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 409
    assert error_of(response)["details"]["refusalCode"] == "buyer_erased"
    assert queue.calls == []


async def test_an_already_announced_payment_is_refused_rather_than_re_queued(
    container: AdminContainer, client: httpx.AsyncClient, queue: NullAdminQueue
) -> None:
    """The job stops on ``notified_at``, so re-enqueuing would do nothing and reporting success
    would be a lie an operator acts on."""
    # Arrange
    intent = settle(make_intent(now=NOW), at=NOW)
    intent.notified_at = NOW
    await add(container.session_factory, intent)
    await signed_in(container, client, role=AdminRole.SUPPORT)

    # Act
    response = await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=intent.id),
        json={"reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 409
    assert error_of(response)["details"]["refusalCode"] == "already_notified"
    assert queue.calls == []


async def test_an_enqueue_onto_a_job_already_queued_reports_a_replay(
    replaying_panel: tuple[AdminContainer, httpx.AsyncClient],
) -> None:
    """ARQ answers ``None`` when it already holds the deterministic id. That is a SUCCESS — the
    announcement is already in flight — and saying so is what stops a third press."""
    # Arrange
    container, client = replaying_panel
    intent = await paid_unannounced_intent(container)
    await signed_in(container, client, role=AdminRole.SUPPORT)

    # Act
    response = await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=intent.id),
        json={"reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 200
    payload = body(response)
    assert payload["isReplay"] is True
    # The job id is deterministic, so it is the same string either way and can still be handed
    # to whoever is reading the worker's logs.
    assert payload["jobId"] == job_id_for_payment_notification(intent.public_ref)


async def test_a_request_id_on_the_body_is_accepted_and_changes_nothing(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``ApiModel`` sets ``extra="forbid"``, and the console sends one action-body shape for
    every operator action — so the field has to exist. It is deliberately not read: the job id
    is deterministic on ``public_ref`` and ``mark_intent_notified`` stamps only where
    ``notified_at IS NULL``."""
    # Arrange
    intent = await paid_unannounced_intent(container)
    await signed_in(container, client, role=AdminRole.SUPPORT)

    # Act
    response = await client.post(
        INTENT_NOTIFY_PATH.format(intent_id=intent.id),
        json={
            "reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value,
            "requestId": str(uuid4()),
        },
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 200
    assert body(response)["jobId"] == job_id_for_payment_notification(intent.public_ref)


async def test_an_unauthenticated_caller_reaches_none_of_it(client: httpx.AsyncClient) -> None:
    # Arrange — no sign-in. Every route on this surface is guarded, including the six reads.
    paths = (RAIL_PATH, SETTLEMENT_PATH, FUNNEL_PATH, ATTENTION_PATH, INTENTS_PATH, CALLS_PATH)

    # Act / Assert
    for path in paths:
        response = await client.get(path, headers={"Origin": ORIGIN})
        assert response.status_code == 401, path
