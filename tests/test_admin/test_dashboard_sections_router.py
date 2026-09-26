"""The four dashboard sections and the plan book, over the real ASGI stack and real SQLite.

The assertions that carry this file are the ones about numbers the page refuses to invent,
because every one of them is a number an operator would act on:

* a **rate with no denominator cannot be constructed** — the four wire primitives raise
  rather than serialise, so ``RatioView(value=0.87)`` and ``UsdCost(amount_usd=41.20)`` are
  not shapes this API can produce, and the test asserts the refusal rather than the absence;
* **throughput is windowed on ``delivered_at`` and the cohort on ``created_at``**, and an
  order created on one day and delivered two days later proves the two series disagree on
  purpose — this is the regression test that stops somebody folding them back together;
* a **fake-provider row is excluded structurally** from every spend figure and is reported
  by ``fakeCalls`` so the exclusion is visible rather than silent;
* **money is never zero-filled** while counts are, and only when the caller gave a lower
  bound, which ``isZeroFilled`` states on the wire;
* an **unconfigured FX rate** produces a null net with a REASON, never a converted figure
  and never a zero;
* a **top-up sold before amounts were recorded** is counted and never priced;
* **``bucket=hour`` over a long window is a 422 naming the parameter**, never a silent
  coarsening into a different question;
* **no ``telegramUserId``, receipt reference or idempotency key appears in any of the five
  payloads at any role** — DASHBOARD_READ has no masking branch and must keep having none.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.admin.container import AdminContainer
from bayram.admin.routers.dashboard import (
    AUDIENCE_PATH,
    FINANCE_PATH,
    PERFORMANCE_PATH,
    PLAN_LIABILITY_PATH,
    SERIES_PATH,
    VENDOR_PATH,
)
from bayram.admin.settings import AdminSettings
from bayram.contracts import (
    BotBlockSource,
    BotMembershipEvent,
    CostSource,
    Language,
    OrderState,
    Vendor,
    VendorOperation,
)
from bayram.db.enums import AdminRole, CreditEntryKind, CreditReason, PlanKind, TopupKind
from bayram.db.models.bot_membership_event import BotMembershipEventRow
from bayram.db.models.credit_ledger import CreditLedgerRow
from bayram.db.models.order import OrderRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.db.models.user import UserRow
from bayram.db.models.user_activity_snapshot import UserActivitySnapshotRow
from bayram.db.models.vendor_usage import VendorUsageRow
from tests.test_admin.conftest import (
    FakeRedis,
    MemoryRateLimits,
    make_settings,
    open_client,
    open_container,
)
from tests.test_admin.test_dashboard_router import signed_in

#: Fixed instants. Every number below is derived from timestamps, so a wall clock would race
#: the test run against a bucket boundary.
DAY_ONE: Final[datetime] = datetime(2026, 3, 20, 9, 0, tzinfo=UTC)
DAY_THREE: Final[datetime] = datetime(2026, 3, 22, 9, 0, tzinfo=UTC)
FAR_FUTURE: Final[datetime] = datetime(2027, 1, 1, tzinfo=UTC)

SEVEN_THOUSAND_SOM: Final[int] = 700_000
FX_RATE: Final[float] = 12_800.0

#: The plaintext the privacy sweep looks for. ASCII on purpose: a non-ASCII string comes back
#: from ``JSONResponse`` as ``\\uXXXX`` escapes and a substring check would pass vacuously.
TELEGRAM_ID: Final[int] = 77_000_555
RECEIPT_REFERENCE: Final[str] = "payme-ref-Gulomjon"
IDEMPOTENCY_KEY: Final[str] = "topup-key-Gulomjon"

#: Every DASHBOARD_READ section. ``/dashboard/audience-lists`` is deliberately NOT here: it
#: is the identified route, it stands on RECORDS_READ, and it returns a Telegram id on
#: purpose — putting it in this tuple would make the privacy sweep below fail for the one
#: payload that is meant to carry identity, and would hide that the other six do not.
ALL_PATHS: Final[tuple[str, ...]] = (
    AUDIENCE_PATH,
    FINANCE_PATH,
    PERFORMANCE_PATH,
    SERIES_PATH,
    VENDOR_PATH,
    PLAN_LIABILITY_PATH,
)


def _window(start: datetime, end: datetime) -> dict[str, str]:
    return {"from": start.isoformat(), "to": end.isoformat()}


# ---------------------------------------------------------------------------
# seed helpers — explicit values, no clocks, no policies
# ---------------------------------------------------------------------------
async def seed_user(
    session: AsyncSession,
    *,
    telegram_user_id: int = TELEGRAM_ID,
    created_at: datetime = DAY_ONE,
    last_seen_at: datetime | None = None,
    is_blocked: bool = False,
    blocked_bot_at: datetime | None = None,
    ui_language: Language = Language.UZ_LATN,
) -> UserRow:
    row = UserRow(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        ui_language=ui_language,
        is_blocked=is_blocked,
        blocked_bot_at=blocked_bot_at,
        last_seen_at=last_seen_at or created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_order(
    session: AsyncSession,
    *,
    user: UserRow,
    created_at: datetime = DAY_ONE,
    delivered_at: datetime | None = None,
    state: OrderState = OrderState.DELIVERED,
) -> OrderRow:
    row = OrderRow(
        id=uuid4(),
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        state=state,
        correlation_id="corr-sections",
        is_paid=True,
        delivered_at=delivered_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_usage(
    session: AsyncSession,
    *,
    created_at: datetime = DAY_ONE,
    order: OrderRow | None = None,
    vendor: Vendor = Vendor.ELEVENLABS,
    operation: VendorOperation = VendorOperation.MUSIC_COMPOSE,
    cost_usd: float | None = 0.45,
    is_fake: bool = False,
    latency_ms: int | None = 4_000,
    total_tokens: int | None = None,
    billed_characters: int | None = None,
    audio_ms: int | None = None,
) -> VendorUsageRow:
    row = VendorUsageRow(
        id=uuid4(),
        vendor=vendor,
        operation=operation,
        provider="elevenlabs_music",
        model_id="music-v1",
        is_fallback=False,
        is_fake=is_fake,
        order_id=None if order is None else order.id,
        is_success=True,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        cost_source=None if cost_usd is None else CostSource.ESTIMATED,
        total_tokens=total_tokens,
        billed_characters=billed_characters,
        audio_ms=audio_ms,
        created_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_topup(
    session: AsyncSession,
    *,
    created_at: datetime = DAY_ONE,
    amount_minor: int = SEVEN_THOUSAND_SOM,
    currency: str = "UZS",
    provider: str = "stub",
    key: str = IDEMPOTENCY_KEY,
) -> None:
    session.add(
        TopupPurchaseRow(
            id=uuid4(),
            telegram_user_id=TELEGRAM_ID,
            product=TopupKind.SINGLE,
            credits_granted=1,
            amount_minor=amount_minor,
            currency=currency,
            provider=provider,
            reference=RECEIPT_REFERENCE,
            idempotency_key=key,
            created_at=created_at,
        )
    )
    await session.flush()


async def seed_topup_grant(
    session: AsyncSession, *, created_at: datetime = DAY_ONE, key: str = IDEMPOTENCY_KEY
) -> None:
    """The ledger half of a top-up. Alone, it is the pre-instrumentation shape."""
    session.add(
        CreditLedgerRow(
            id=uuid4(),
            telegram_user_id=TELEGRAM_ID,
            kind=CreditEntryKind.GRANT,
            reason=CreditReason.TOPUP_PURCHASE,
            delta=1,
            generation=0,
            idempotency_key=key,
            actor="checkout",
            created_at=created_at,
        )
    )
    await session.flush()


async def seed_plan(
    session: AsyncSession,
    *,
    created_at: datetime = DAY_ONE,
    ends_at: datetime = FAR_FUTURE,
    songs_included: int = 12,
    songs_used: int = 0,
    telegram_user_id: int | None = TELEGRAM_ID,
    currency: str = "UZS",
    key: str = "plan-key-1",
) -> None:
    session.add(
        PlanPurchaseRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            plan=PlanKind.STARTER,
            songs_included=songs_included,
            songs_used=songs_used,
            amount_minor=5_000_000,
            currency=currency,
            provider="stub",
            reference=RECEIPT_REFERENCE,
            idempotency_key=key,
            plan_ends_at=ends_at,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await session.flush()


async def seed_activity_snapshot(
    session: AsyncSession, *, taken_at: datetime, day: int, week: int, month: int
) -> None:
    """One night's sample, filed the way ``runtime/activity_job.py`` files it.

    ``snapshot_date`` is ``taken_at``'s UTC day and nothing else: the read buckets on
    ``taken_at`` and relies on the two agreeing, so a helper that let them drift would be
    seeding a row the writer cannot produce.
    """
    session.add(
        UserActivitySnapshotRow(
            id=uuid4(),
            snapshot_date=taken_at.date(),
            taken_at=taken_at,
            total_accounts=month,
            blocked_accounts=0,
            active_24h_accounts=day,
            active_7d_accounts=week,
            active_30d_accounts=month,
            created_at=taken_at,
        )
    )
    await session.flush()


async def seed_membership(
    session: AsyncSession, *, event: BotMembershipEvent, at: datetime = DAY_ONE
) -> None:
    session.add(
        BotMembershipEventRow(
            id=uuid4(),
            telegram_user_id=TELEGRAM_ID,
            event=event,
            source=BotBlockSource.MEMBERSHIP_UPDATE,
            at=at,
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# permission
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_every_section_refuses_an_operator_without_dashboard_read(
    container: AdminContainer, client: httpx.AsyncClient, path: str
) -> None:
    # Arrange — no session at all is the strongest form of the refusal.
    # Act
    response = await client.get(path)

    # Assert
    assert response.status_code == 401


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("role", list(AdminRole))
async def test_every_role_holding_dashboard_read_is_served(
    container: AdminContainer, client: httpx.AsyncClient, path: str, role: AdminRole
) -> None:
    # Arrange — §12.2 gives DASHBOARD_READ to all four roles; this is the fold-bundle check
    # that an operator does not need RECORDS_READ for the funnel or RETENTION_READ for a card.
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(path)

    # Assert
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# privacy — the sweep, at every role
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", list(AdminRole))
async def test_no_section_leaks_an_identifier_a_receipt_or_a_key(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — seed every table that holds an identifier, then read every section.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_order(session, user=user, delivered_at=DAY_ONE + timedelta(minutes=1))
        await seed_usage(session, order=order)
        await seed_topup(session)
        await seed_topup_grant(session)
        await seed_plan(session)
        await seed_membership(session, event=BotMembershipEvent.BLOCKED)
    await signed_in(container, client, role=role)

    # Act
    bodies = [(await client.get(path)).text for path in ALL_PATHS]

    # Assert — DASHBOARD_READ has no masking branch, so the guarantee has to be that the
    # value never enters the payload rather than that it is masked on the way out.
    for body in bodies:
        assert str(TELEGRAM_ID) not in body
        assert RECEIPT_REFERENCE not in body
        assert IDEMPOTENCY_KEY not in body
        assert "telegramUserId" not in body
        assert "reference" not in body
        assert "idempotencyKey" not in body


# ---------------------------------------------------------------------------
# audience
# ---------------------------------------------------------------------------
async def test_the_two_kinds_of_block_are_two_numbers_and_never_a_sum(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one account barred by an operator, one that blocked the bot, and one that is
    # BOTH. Summing the columns would count the third twice; the remedies differ anyway.
    async with container.session_factory.begin() as session:
        await seed_user(session, telegram_user_id=1, is_blocked=True)
        await seed_user(session, telegram_user_id=2, blocked_bot_at=DAY_ONE)
        await seed_user(session, telegram_user_id=3, is_blocked=True, blocked_bot_at=DAY_ONE)
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH)).json()

    # Assert
    assert body["totalAccounts"]["current"] == 3
    assert body["blockedAccounts"] == 2
    assert body["botBlockedAccounts"] == 2


async def test_churn_is_null_rather_than_a_pair_of_zeroes_when_nothing_was_ever_recorded(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an empty membership table. "Nobody blocked the bot" and "we have never
    # watched" are two different sentences and only the second is true here.
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH)).json()

    # Assert
    assert body["isChurnInstrumented"] is False
    assert body["churn"] is None


async def test_churn_counts_passages_in_both_directions_once_instrumented(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one customer who left and came back inside one window appears in both
    # numbers, because these are passages and not a gauge.
    async with container.session_factory.begin() as session:
        await seed_membership(session, event=BotMembershipEvent.BLOCKED, at=DAY_ONE)
        await seed_membership(session, event=BotMembershipEvent.UNBLOCKED, at=DAY_THREE)
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH)).json()

    # Assert
    assert body["isChurnInstrumented"] is True
    assert body["churn"]["blocked"]["current"] == 1
    assert body["churn"]["unblocked"]["current"] == 1


async def test_a_window_with_no_lower_bound_yields_a_null_previous_and_no_change(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``?to=`` alone. An open-below range has no length, so it has no predecessor,
    # and a zero there would claim the preceding period was measured and empty.
    async with container.session_factory.begin() as session:
        await seed_user(session)
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH, params={"to": FAR_FUTURE.isoformat()})).json()

    # Assert
    for card in ("totalAccounts", "newAccounts"):
        assert body[card]["previous"] is None
        assert body[card]["change"] is None


async def test_the_delta_splits_the_two_windows_at_the_boundary_without_double_counting(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one sign-up in the previous window, two in the current, and one exactly ON
    # the boundary, which is half-open below and therefore belongs to the CURRENT window.
    start, end = DAY_THREE, DAY_THREE + timedelta(days=1)
    async with container.session_factory.begin() as session:
        await seed_user(session, telegram_user_id=1, created_at=start - timedelta(hours=1))
        await seed_user(session, telegram_user_id=2, created_at=start)
        await seed_user(session, telegram_user_id=3, created_at=start + timedelta(hours=2))
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH, params=_window(start, end))).json()

    # Assert
    assert body["newAccounts"]["current"] == 2
    assert body["newAccounts"]["previous"] == 1
    assert body["newAccounts"]["change"]["denominator"] == 1.0


async def test_the_two_churns_are_two_measurements_and_the_card_gets_both(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one account that blocked the bot, and one plan that ended and was not bought
    # again. The panel draws these in ONE card, which is exactly why the response must keep
    # them apart: a passage count in people and a rate over ended plans.
    async with container.session_factory.begin() as session:
        await seed_user(session)
        await seed_membership(session, event=BotMembershipEvent.BLOCKED)
        await seed_plan(session, ends_at=DAY_ONE + timedelta(days=30))
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH)).json()

    # Assert — the block churn has no denominator at all; the subscription churn has one and
    # publishes it, and neither number is derived from the other.
    assert body["churn"]["blocked"]["current"] == 1
    assert "denominator" not in body["churn"]["blocked"]
    churn = body["subscriptionChurn"]
    assert churn["endedPlans"] == 1
    assert churn["lapsed"] == 1
    assert churn["renewed"] == 0
    assert churn["anonymisedEnded"] == 0
    assert churn["rate"] == {"value": 1.0, "numerator": 1.0, "denominator": 1.0}


async def test_subscription_churn_is_null_rather_than_zeroes_when_nothing_was_ever_sold(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an account, no receipts. Four zeroes would read as "nobody renews".
    async with container.session_factory.begin() as session:
        await seed_user(session)
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH)).json()

    # Assert — dropped by ``capabilities.isPlanRevenue``, the probe that already existed for
    # this question, which is why the response grew no fourth flag beside it.
    assert body["subscriptionChurn"] is None


async def test_a_running_plan_is_not_counted_as_a_lapse(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a plan that has not ended yet. Its holder has not declined to renew; they
    # have not reached the decision, and counting them would file every new customer as
    # churned for thirty days.
    async with container.session_factory.begin() as session:
        await seed_user(session)
        await seed_plan(session, ends_at=FAR_FUTURE)
    await signed_in(container, client)

    # Act
    churn = (await client.get(AUDIENCE_PATH)).json()["subscriptionChurn"]

    # Assert — no denominator, so no rate. Never 0.0, which would read as perfect retention.
    assert churn["endedPlans"] == 0
    assert churn["lapsed"] == 0
    assert churn["rate"]["value"] is None
    assert churn["rate"]["denominator"] == 0.0


async def test_the_language_mix_carries_the_denominator_its_shares_are_taken_over(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``ui_language`` is NOT NULL, so every account lands in exactly one entry.
    async with container.session_factory.begin() as session:
        await seed_user(session, telegram_user_id=1)
        await seed_user(session, telegram_user_id=2)
    await signed_in(container, client)

    # Act
    mix = (await client.get(AUDIENCE_PATH)).json()["languageMix"]

    # Assert — the share is formed against the block's own total, so a filtered or truncated
    # list cannot renormalise itself to 100% of whatever survived.
    assert mix["accounts"] == 2
    assert [entry["language"] for entry in mix["languages"]] == ["uz_latn"]
    assert mix["languages"][0]["accounts"] == 2
    assert mix["languages"][0]["share"] == {"value": 1.0, "numerator": 2.0, "denominator": 2.0}


async def test_a_customer_who_bought_again_is_a_renewal_and_the_rate_is_a_measured_zero(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one plan that has ended, and a second receipt from the same customer bought
    # afterwards. "Renewed" is any later purchase by the same account: there is no renewal
    # event in this schema, so the EXISTS probe is the only thing that can answer it, and a
    # customer who came back four months later is indistinguishable here from one who
    # renewed the same afternoon. That is the read's stated limit, pinned rather than hidden.
    async with container.session_factory.begin() as session:
        await seed_user(session)
        await seed_plan(session, created_at=DAY_ONE, ends_at=DAY_THREE, key="plan-key-first")
        await seed_plan(session, created_at=DAY_THREE, ends_at=FAR_FUTURE, key="plan-key-second")
    await signed_in(container, client)

    # Act
    churn = (await client.get(AUDIENCE_PATH)).json()["subscriptionChurn"]

    # Assert — the running second plan is NOT in the denominator (its outcome is not final),
    # and 0.0 here is a measured rate over one ended plan, not the "nothing was measured"
    # zero the ``rate`` field refuses to invent when ``endedPlans`` is 0.
    assert churn["endedPlans"] == 1
    assert churn["renewed"] == 1
    assert churn["lapsed"] == 0
    assert churn["rate"] == {"value": 0.0, "numerator": 0.0, "denominator": 1.0}


async def test_an_erased_customers_ended_plan_is_its_own_arm_and_never_a_lapse(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a receipt whose ``telegram_user_id`` ``/forget`` nulled. The renewal probe is
    # an equality on that column, so nothing can join to it: the read CANNOT know whether
    # this customer came back, and filing them as a lapse would state that they did not.
    async with container.session_factory.begin() as session:
        await seed_plan(session, telegram_user_id=None, ends_at=DAY_THREE, key="plan-key-erased")
    await signed_in(container, client)

    # Act
    churn = (await client.get(AUDIENCE_PATH)).json()["subscriptionChurn"]

    # Assert — the three arms PARTITION the denominator: an erased ending is counted once,
    # in its own arm. That makes ``rate`` a FLOOR on real churn rather than a ceiling —
    # understated by at most ``anonymisedEnded`` endings — which the query, the view and the
    # wire model all now say in those words. This assertion is what fails if anybody moves
    # the anonymised rows back inside ``lapsed``, which would be a change to the number the
    # panel prints and not a refactor.
    assert churn["endedPlans"] == 1
    assert churn["anonymisedEnded"] == 1
    assert churn["lapsed"] == 0
    assert churn["renewed"] == 0
    assert churn["renewed"] + churn["lapsed"] + churn["anonymisedEnded"] == churn["endedPlans"]


async def test_the_language_mix_ranks_the_languages_and_omits_the_ones_nobody_speaks(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — three accounts over two of the four languages.
    async with container.session_factory.begin() as session:
        await seed_user(session, telegram_user_id=1, ui_language=Language.UZ_LATN)
        await seed_user(session, telegram_user_id=2, ui_language=Language.UZ_LATN)
        await seed_user(session, telegram_user_id=3, ui_language=Language.RU)
    await signed_in(container, client)

    # Act
    mix = (await client.get(AUDIENCE_PATH)).json()["languageMix"]

    # Assert — largest first, so the card can be read top-down; the two unspoken languages
    # are ABSENT rather than zero rows, which is a presentational choice the read argues (a
    # zero here would be a true measurement over a NOT NULL column, unlike a gap in a
    # series); and both entries divide by the block's own total, so a truncated list cannot
    # renormalise itself to 100% of whatever survived the cut.
    assert [entry["language"] for entry in mix["languages"]] == ["uz_latn", "ru"]
    assert [entry["accounts"] for entry in mix["languages"]] == [2, 1]
    assert mix["accounts"] == 3
    assert {entry["share"]["denominator"] for entry in mix["languages"]} == {3.0}


async def test_the_activity_series_is_empty_rather_than_zero_filled_and_echoes_its_grain(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an account exists and the nightly snapshot job has never run.
    async with container.session_factory.begin() as session:
        await seed_user(session)
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH)).json()

    # Assert — a night with no sample is ABSENT; zero-filling would report that nobody used
    # the bot. The live gauge above still answers, which is why the two are separate fields.
    assert body["activityHistory"] == []
    assert body["isActivityHistory"] is False
    assert body["activityBucket"] == "day"
    assert body["activeAccounts"]["day"] >= 0


async def test_a_night_the_snapshot_job_missed_is_absent_from_the_history_and_not_a_zero(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — samples on two nights with an unmeasured night between them. The gap cannot
    # be back-filled either: ``users.last_seen_at`` is a gauge that was overwritten, so the
    # missing night has no true value and a zero would be a fabricated measurement wearing a
    # chart line. The API layer, which knows the range it was asked for, decides how a hole
    # renders; this response's job is to not invent one.
    async with container.session_factory.begin() as session:
        await seed_user(session)
        await seed_activity_snapshot(session, taken_at=DAY_ONE, day=4, week=9, month=20)
        await seed_activity_snapshot(session, taken_at=DAY_THREE, day=6, week=11, month=25)
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH)).json()

    # Assert — oldest first, two points for two samples, and the middle day is simply not
    # there. The three counts stay nested (day ⊆ week ⊆ month) within each point, which is
    # what makes them three lines and never a stacked area.
    history = body["activityHistory"]
    assert body["isActivityHistory"] is True
    assert [point["day"] for point in history] == [4, 6]
    assert [point["week"] for point in history] == [9, 11]
    assert [point["month"] for point in history] == [20, 25]
    assert [point["startedAt"] for point in history] == sorted(
        point["startedAt"] for point in history
    )
    assert all(point["day"] <= point["week"] <= point["month"] for point in history)
    assert (DAY_ONE + timedelta(days=1)).date().isoformat() not in str(history)


async def test_the_audience_route_takes_no_bucket_parameter(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``extra="forbid"`` is on bodies, not query strings, so an unknown parameter
    # is IGNORED here. The assertion is that it changes nothing: the grain is fixed, and a
    # caller who sends ``?bucket=month`` gets daily points and is told so by the echo.
    await signed_in(container, client)

    # Act
    body = (await client.get(AUDIENCE_PATH, params={"bucket": "month"})).json()

    # Assert
    assert body["activityBucket"] == "day"


# ---------------------------------------------------------------------------
# vendor
# ---------------------------------------------------------------------------
async def test_the_per_vendor_cost_is_divided_by_the_whole_cohort_not_its_own_subset(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two delivered songs, one of which carries a vendor call. Dividing by the
    # attributed order alone would report $0.45 a song; dividing by the cohort reports the
    # honest $0.225 and publishes the coverage that explains it.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        first = await seed_order(session, user=user, delivered_at=DAY_ONE + timedelta(minutes=1))
        await seed_order(session, user=user, delivered_at=DAY_ONE + timedelta(minutes=2))
        await seed_usage(session, order=first, cost_usd=0.45)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_PATH)).json()

    # Assert
    assert body["deliveredOrders"] == 2
    row = body["costPerSongByVendor"][0]
    assert row["vendor"] == "elevenlabs"
    assert row["costUsd"] == 0.45
    assert row["attributedOrders"] == 1
    assert row["costPerSong"]["denominator"] == 2.0
    assert row["costPerSong"]["value"] == pytest.approx(0.225)


async def test_an_unpriced_call_is_its_own_provenance_bucket_and_never_a_zero(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a call nobody could price. "This cost nothing" and "nobody could say" are
    # different facts, and collapsing them is how a deployment concludes rendering is free.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_order(session, user=user, delivered_at=DAY_ONE + timedelta(minutes=1))
        await seed_usage(session, order=order, cost_usd=None)
    await signed_in(container, client)

    # Act
    provenance = (await client.get(VENDOR_PATH)).json()["costProvenance"]

    # Assert
    assert provenance == [{"costSource": None, "calls": 1, "costUsd": None}]


async def test_the_unit_rows_and_the_cost_rows_divide_by_one_and_the_same_cohort(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two delivered songs and one instrumented call carrying tokens and nothing
    # else. The denominator is taken ONCE by the handler and threaded into both breakdowns:
    # two reads of the delivered count microseconds apart could straddle a delivery and give
    # cost-per-song and tokens-per-song different populations, and the whole reason the two
    # tables sit in one payload is that a reader compares them.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        first = await seed_order(session, user=user, delivered_at=DAY_ONE + timedelta(minutes=1))
        await seed_order(session, user=user, delivered_at=DAY_ONE + timedelta(minutes=2))
        await seed_usage(session, order=first, cost_usd=0.45, total_tokens=1_000)
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_PATH)).json()

    # Assert — the three unit families never share an axis, so the two nobody measured are
    # ``null`` and not ``0``: a zero would say the vendor charged us for no characters.
    units = body["unitsPerSongByVendor"][0]
    assert units["vendor"] == "elevenlabs"
    assert units["totalTokens"] == 1_000
    assert units["billedCharacters"] is None
    assert units["audioMs"] is None
    assert units["charactersPerSong"] is None
    assert units["tokensPerSong"]["denominator"] == float(body["deliveredOrders"])
    assert (
        units["tokensPerSong"]["denominator"]
        == body["costPerSongByVendor"][0]["costPerSong"]["denominator"]
    )
    assert units["tokensPerSong"]["value"] == pytest.approx(500.0)


async def test_a_health_probe_is_not_a_provenance_bucket_because_it_is_never_priced(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one composed song and one balance probe. The poller writes ~72 HEALTH rows a
    # day and none of them can carry a price, so counting them here would let the quota probe
    # dominate the unpriced bucket within a week and make an instrumented deployment read as
    # uninstrumented. ``cost_provenance`` therefore excludes the unspendable operations by
    # default — the same exclusions ``vendorSpend`` on this response was taken with, so the
    # partition reconciles against the total it sits beside.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_order(session, user=user, delivered_at=DAY_ONE + timedelta(minutes=1))
        await seed_usage(session, order=order, cost_usd=0.45)
        await seed_usage(session, operation=VendorOperation.HEALTH, cost_usd=None)
    await signed_in(container, client)

    # Act
    provenance = (await client.get(VENDOR_PATH)).json()["costProvenance"]

    # Assert
    assert provenance == [{"costSource": "estimated", "calls": 1, "costUsd": 0.45}]


async def test_a_fake_provider_run_is_excluded_from_the_breakdown_as_well_as_the_total(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a demo run beside a real one. The per-vendor rows expose no ``include_fake``
    # knob on purpose: a breakdown that could be narrowed differently from the total printed
    # above it is exactly how the two come to disagree, so the exclusion is structural in
    # both and this test is what keeps it that way.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_order(session, user=user, delivered_at=DAY_ONE + timedelta(minutes=1))
        await seed_usage(session, order=order, cost_usd=0.45)
        await seed_usage(
            session, order=order, vendor=Vendor.OPENROUTER, cost_usd=9.99, is_fake=True
        )
    await signed_in(container, client)

    # Act
    body = (await client.get(VENDOR_PATH)).json()

    # Assert — the fake row is in no row, no total and no provenance bucket, and the guard
    # counts it so the exclusion is visible rather than silent.
    assert [row["vendor"] for row in body["costPerSongByVendor"]] == ["elevenlabs"]
    assert [row["vendor"] for row in body["unitsPerSongByVendor"]] == ["elevenlabs"]
    assert body["vendorSpend"]["amountUsd"] == pytest.approx(0.45)
    assert sum(row["calls"] for row in body["costProvenance"]) == 1


async def test_the_vendor_section_republishes_the_finance_figures_rather_than_recomputing_them(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the same window, the same instant, two sections. ``vendorSpend`` and
    # ``vendorBalances`` appear on both under exactly these names; republishing a figure
    # under a second name, or from a second aggregate with different exclusions, is how two
    # cards on one page come to disagree in front of an operator.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_order(session, user=user, delivered_at=DAY_ONE + timedelta(minutes=1))
        await seed_usage(session, order=order, cost_usd=0.45)
        await seed_usage(session, operation=VendorOperation.HEALTH, cost_usd=None)
    await signed_in(container, client)
    params = _window(DAY_ONE - timedelta(days=1), FAR_FUTURE)

    # Act
    finance = (await client.get(FINANCE_PATH, params=params)).json()
    vendor = (await client.get(VENDOR_PATH, params=params)).json()

    # Assert — the amount is asserted as well as the equality, so the test cannot pass by
    # both sections returning "nothing was measured".
    assert vendor["vendorSpend"]["amountUsd"] == pytest.approx(0.45)
    assert vendor["vendorSpend"] == finance["vendorSpend"]
    assert vendor["vendorBalances"] == finance["vendorBalances"]
    assert vendor["window"] == finance["window"]


# ---------------------------------------------------------------------------
# finance
# ---------------------------------------------------------------------------
async def test_an_unconfigured_fx_rate_produces_a_null_net_with_a_reason_never_a_zero(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the shipped state: no rate published. A default of 1.0 would read 7 000 soʻm
    # as $7 000 against $0.45 of cost, on the one card that says whether the business works.
    async with container.session_factory.begin() as session:
        await seed_topup(session)
        await seed_usage(session)
    await signed_in(container, client)

    # Act
    body = (await client.get(FINANCE_PATH)).json()

    # Assert
    assert body["fx"] == {"uzsPerUsd": None, "asOf": None}
    assert body["netRunRate"]["netMinor"] is None
    assert body["netRunRate"]["unavailableReason"] == "no_fx_rate"
    assert body["netRunRate"]["annualisedMinor"] is None


async def test_a_published_rate_produces_a_net_that_names_the_rate_and_the_window_it_used(
    fake_redis: FakeRedis, rate_limits: MemoryRateLimits
) -> None:
    # Arrange — the run-rate card uses its OWN trailing window, not the request's, so a
    # selector set to Today cannot make "MRR" mean today's net and then annualise it.
    settings: AdminSettings = make_settings(
        admin_uzs_per_usd=FX_RATE,
        admin_uzs_per_usd_as_of="2026-09-01",
        admin_single_song_price_minor=SEVEN_THOUSAND_SOM,
        admin_kit_currency="UZS",
    )
    async with open_container(settings, fake_redis, rate_limits) as container:
        now = datetime.now(UTC)
        async with container.session_factory.begin() as session:
            await seed_topup(session, created_at=now - timedelta(days=1))
            await seed_usage(session, created_at=now - timedelta(days=1), cost_usd=1.0)
        async with open_client(container) as client:
            await signed_in(container, client)

            # Act
            body = (await client.get(FINANCE_PATH)).json()

    # Assert — 700 000 tiyin taken in, one dollar of vendor cost at 12 800 soʻm = 1 280 000
    # tiyin out. The subtraction happens in the unit the operator sells in.
    net = body["netRunRate"]
    assert net["unavailableReason"] is None
    assert net["currency"] == "UZS"
    assert net["netMinor"] == SEVEN_THOUSAND_SOM - round(FX_RATE * 100)
    assert net["fxUsed"] == {"uzsPerUsd": FX_RATE, "asOf": "2026-09-01"}
    assert net["window"]["from"] is not None


async def test_derived_revenue_is_absent_with_a_reason_when_no_price_is_published(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the estimate multiplies a config value read at query time and is a different
    # class of figure from a recorded receipt, so it is a separate field and never summed in.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        await seed_order(session, user=user, delivered_at=DAY_ONE)
    await signed_in(container, client)

    # Act
    body = (await client.get(FINANCE_PATH)).json()

    # Assert
    assert body["derivedRevenue"]["deliveredSongs"] == 1
    assert body["derivedRevenue"]["amountMinor"] is None
    assert body["derivedRevenue"]["unavailableReason"] == "no_price_published"


async def test_revenue_is_never_summed_across_currencies_or_collapsed_across_rails(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one UZS stub sale and one USD sale on a real rail in the same window. A
    # scalar total would be a number in an invented unit AND would read a stub as settled.
    async with container.session_factory.begin() as session:
        await seed_topup(session, key="a")
        await seed_topup(session, key="b", currency="USD", provider="payme", amount_minor=100)
    await signed_in(container, client)

    # Act
    body = (await client.get(FINANCE_PATH)).json()

    # Assert
    assert len(body["revenue"]) == 2
    assert {row["currency"] for row in body["revenue"]} == {"UZS", "USD"}
    assert {row["provider"] for row in body["revenue"]} == {"stub", "payme"}
    assert {row["isStubRail"] for row in body["revenue"]} == {True, False}


async def test_a_topup_sold_before_amounts_were_recorded_is_counted_and_never_priced(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the pre-instrumentation shape is a bare ledger GRANT with no receipt sharing
    # its key. Back-pricing it would reprice history every time the price moves.
    async with container.session_factory.begin() as session:
        await seed_topup_grant(session, key="old-sale")
        await seed_topup_grant(session, key="new-sale")
        await seed_topup(session, key="new-sale")
    await signed_in(container, client)

    # Act
    body = (await client.get(FINANCE_PATH)).json()

    # Assert
    assert body["unpricedTopups"] == {"unpriced": 1, "priced": 1}
    assert sum(row["amountMinor"] for row in body["revenue"]) == SEVEN_THOUSAND_SOM


async def test_a_zero_priced_sale_is_a_recorded_sale_and_not_an_unpriced_one(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``single_song_price_minor`` ships ``ge=0``, so a promo at zero is a real
    # sale. "Sold for zero" is a row with amountMinor 0; "sold before we recorded amounts"
    # is the ABSENCE of a row. The two are told apart structurally, never by a null.
    async with container.session_factory.begin() as session:
        await seed_topup_grant(session, key="free-sale")
        await seed_topup(session, key="free-sale", amount_minor=0)
    await signed_in(container, client)

    # Act
    body = (await client.get(FINANCE_PATH)).json()

    # Assert
    assert body["unpricedTopups"]["unpriced"] == 0
    assert body["revenue"][0]["amountMinor"] == 0


async def test_a_fake_provider_run_is_excluded_from_spend_and_reported_as_excluded(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one real priced call and one fake one. Before ``_narrow`` excluded fakes by
    # default a demo inflated every cost, rate and latency on the page; making it invisible
    # instead would be the same defect facing the other way, which ``fakeCalls`` prevents.
    async with container.session_factory.begin() as session:
        await seed_usage(session, cost_usd=0.45)
        await seed_usage(session, cost_usd=9.99, is_fake=True, vendor=Vendor.FAKE)
    await signed_in(container, client)

    # Act
    body = (await client.get(FINANCE_PATH)).json()

    # Assert
    assert body["vendorSpend"]["calls"] == 1
    assert body["vendorSpend"]["amountUsd"] == pytest.approx(0.45)
    assert body["fakeCalls"] == {"fakeCalls": 1, "totalCalls": 2}


async def test_a_health_probe_is_not_spend_and_does_not_reach_the_cost_per_song(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the balance poller writes ~72 HEALTH rows a day with no order and no task.
    # Counting them as spend would report checking our own balance as money spent on a song.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_order(session, user=user, delivered_at=DAY_ONE)
        await seed_usage(session, order=order, cost_usd=0.45)
        await seed_usage(session, operation=VendorOperation.HEALTH, cost_usd=5.0)
    await signed_in(container, client)

    # Act
    body = (await client.get(FINANCE_PATH)).json()

    # Assert
    assert body["vendorSpend"]["amountUsd"] == pytest.approx(0.45)
    assert body["costPerSong"]["cost"]["amountUsd"] == pytest.approx(0.45)
    assert body["costPerSong"]["perSongUsd"]["value"] == pytest.approx(0.45)
    assert body["costPerSong"]["perSongUsd"]["denominator"] == 1.0


async def test_an_unpriced_window_reports_a_null_cost_with_a_reason_and_no_ratio(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — calls recorded, no rate configured. ``$0.00`` here is the exact lie the
    # nullable columns, the absent COALESCE and the wire validator all exist to prevent.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_order(session, user=user, delivered_at=DAY_ONE)
        await seed_usage(session, order=order, cost_usd=None)
    await signed_in(container, client)

    # Act
    body = (await client.get(FINANCE_PATH)).json()

    # Assert
    assert body["vendorSpend"]["amountUsd"] is None
    assert body["vendorSpend"]["costSource"] is None
    assert body["vendorSpend"]["unavailableReason"] == "not_priced"
    assert body["vendorSpend"]["calls"] == 1
    assert body["costPerSong"]["perSongUsd"] is None


async def test_balances_are_empty_and_flagged_when_the_poller_has_never_run(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the admin process holds no vendor key and makes no call; an empty list plus
    # a false capability is the honest rendering of "nobody has polled", not "$0 left".
    await signed_in(container, client)

    # Act
    body = (await client.get(FINANCE_PATH)).json()

    # Assert
    assert body["vendorBalances"] == []
    assert body["capabilities"]["isVendorBalance"] is False


# ---------------------------------------------------------------------------
# performance — the throughput correction
# ---------------------------------------------------------------------------
async def test_throughput_is_windowed_on_delivered_at_and_disagrees_with_the_cohort(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ONE order created on day one and delivered two days later. This is the
    # regression test for the throughput correction: ``orders_per_day`` is a cohort ("what
    # arrived that day") and ``delivered_per_bucket`` is throughput ("what shipped that
    # day"), the two disagree by exactly the pipeline latency, and neither is a fixed
    # version of the other.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        await seed_order(session, user=user, created_at=DAY_ONE, delivered_at=DAY_THREE)
    await signed_in(container, client)
    arrival = _window(DAY_ONE - timedelta(hours=1), DAY_ONE + timedelta(hours=1))
    shipping = _window(DAY_THREE - timedelta(hours=1), DAY_THREE + timedelta(hours=1))

    # Act
    on_arrival = (await client.get(PERFORMANCE_PATH, params=arrival)).json()
    on_shipping = (await client.get(PERFORMANCE_PATH, params=shipping)).json()

    # Assert — nothing shipped on the day it was ordered; the one delivery lands on day three.
    assert on_arrival["deliveredOrders"]["current"] == 0
    assert on_arrival["deliveryLatency"]["sampleCount"] == 0
    assert on_shipping["deliveredOrders"]["current"] == 1
    assert on_shipping["deliveryLatency"]["sampleCount"] == 1


async def test_the_delivered_count_and_the_latency_sample_are_one_population(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a slow order created inside the window and delivered after it. The created-at
    # cohort would include it in the count and exclude it from the median; both cards here
    # are windowed on ``delivered_at``, so they describe the same orders.
    start, end = DAY_ONE, DAY_ONE + timedelta(hours=2)
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        await seed_order(session, user=user, created_at=start, delivered_at=start)
        await seed_order(session, user=user, created_at=start, delivered_at=FAR_FUTURE)
    await signed_in(container, client)

    # Act
    body = (await client.get(PERFORMANCE_PATH, params=_window(start, end))).json()

    # Assert
    assert body["deliveredOrders"]["current"] == body["deliveryLatency"]["sampleCount"] == 1


async def test_the_funnel_returns_every_state_zero_filled_and_no_abandoned_count(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a funnel with a rung missing is unreadable, and 0 here is a real count of a
    # real state. There is no ``abandoned`` field because drafts are DELETED at the cutoff,
    # so any such number would decay towards zero as the window lengthens.
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        await seed_order(session, user=user, state=OrderState.DRAFT)
    await signed_in(container, client)

    # Act
    body = (await client.get(PERFORMANCE_PATH)).json()

    # Assert
    funnel = body["orderFunnel"]
    assert funnel["created"] == 1
    assert len(funnel["byState"]) == len(list(OrderState))
    assert {row["state"]: row["count"] for row in funnel["byState"]}["draft"] == 1
    assert "abandoned" not in json.dumps(funnel)


async def test_a_component_with_no_writer_reports_not_probed_and_never_ok(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an empty deployment. Reporting silence as health is how a strip of green dots
    # ends up describing a subsystem nobody instrumented.
    await signed_in(container, client)

    # Act
    body = (await client.get(PERFORMANCE_PATH)).json()

    # Assert
    assert {dot["state"] for dot in body["systemStatus"]} == {"not_probed"}
    assert all(dot["evidence"] for dot in body["systemStatus"])


# ---------------------------------------------------------------------------
# series
# ---------------------------------------------------------------------------
async def test_counts_zero_fill_across_the_requested_range_and_money_does_not(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a sign-up on day one and one on day three, with day two empty. A bucket with
    # no sign-ups is honestly zero sign-ups; a bucket with no priced call is ``null`` and
    # never ``$0.00``, which is the distinction the whole schema beneath this exists to keep.
    async with container.session_factory.begin() as session:
        await seed_user(session, telegram_user_id=1, created_at=DAY_ONE)
        await seed_user(session, telegram_user_id=2, created_at=DAY_THREE)
        await seed_topup(session, created_at=DAY_ONE)
    await signed_in(container, client)
    params = _window(DAY_ONE - timedelta(hours=9), DAY_THREE + timedelta(hours=15))

    # Act
    body = (await client.get(SERIES_PATH, params=params)).json()

    # Assert
    assert body["isZeroFilled"] is True
    assert [point["count"] for point in body["signups"]] == [1, 0, 1]
    assert len(body["revenue"]) == 1


async def test_a_series_with_no_lower_bound_is_not_zero_filled(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``?to=`` alone leaves the series open below, and a filled bucket before the
    # first row would claim "0 sign-ups" for days this deployment did not exist.
    async with container.session_factory.begin() as session:
        await seed_user(session, created_at=DAY_ONE)
    await signed_in(container, client)

    # Act
    body = (await client.get(SERIES_PATH, params={"to": FAR_FUTURE.isoformat()})).json()

    # Assert
    assert body["isZeroFilled"] is False
    assert len(body["signups"]) == 1


async def test_a_weekly_series_sums_exactly_to_the_daily_one_it_was_folded_from(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the fold is what guarantees this. Two independent SQL expressions could not,
    # and Postgres and SQLite do not even agree on how to number a week.
    async with container.session_factory.begin() as session:
        for index, day in enumerate((DAY_ONE, DAY_THREE, DAY_THREE + timedelta(days=1))):
            await seed_user(session, telegram_user_id=index + 1, created_at=day)
    await signed_in(container, client)
    params = _window(DAY_ONE, DAY_THREE + timedelta(days=2))

    # Act
    daily = (await client.get(SERIES_PATH, params={**params, "bucket": "day"})).json()
    weekly = (await client.get(SERIES_PATH, params={**params, "bucket": "week"})).json()
    monthly = (await client.get(SERIES_PATH, params={**params, "bucket": "month"})).json()

    # Assert
    total = sum(point["count"] for point in daily["signups"])
    assert total == 3
    assert sum(point["count"] for point in weekly["signups"]) == total
    assert sum(point["count"] for point in monthly["signups"]) == total


async def test_bucket_hour_without_a_lower_bound_is_a_422_naming_the_parameter(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a refusal, never a silent coarsening: answering at a different grain answers
    # a different question and the caller has no way to notice.
    await signed_in(container, client)

    # Act
    response = await client.get(SERIES_PATH, params={"bucket": "hour"})

    # Assert
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "INVALID_INPUT"
    assert body["details"]["parameter"] == "bucket"


async def test_bucket_hour_over_a_long_window_is_a_422_rather_than_a_coarser_answer(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the default ceiling is eight days: a week plus the delta arm's predecessor.
    await signed_in(container, client)
    params = {**_window(DAY_ONE, DAY_ONE + timedelta(days=30)), "bucket": "hour"}

    # Act
    response = await client.get(SERIES_PATH, params=params)

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["details"]["parameter"] == "bucket"


async def test_a_series_that_would_exceed_the_point_ceiling_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — 750 points clears a year of daily buckets and a month of hourly ones; five
    # years of days does not, and a chart nobody can read is not an answer.
    await signed_in(container, client)
    params = {**_window(DAY_ONE, DAY_ONE + timedelta(days=2_000)), "bucket": "day"}

    # Act
    response = await client.get(SERIES_PATH, params=params)

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["details"]["parameter"] == "bucket"


async def test_to_before_from_is_the_same_422_it_has_always_been(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the window's own rule, unchanged, through the same path every other windowed
    # route uses.
    await signed_in(container, client)

    # Act
    response = await client.get(SERIES_PATH, params=_window(DAY_THREE, DAY_ONE))

    # Assert
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# plan liability
# ---------------------------------------------------------------------------
async def test_the_liability_route_takes_no_window_and_echoes_the_instant_it_used(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — liability is a STATE, not a flow: "how much was owed during March" is a
    # question this table cannot answer, so a window over it would be meaningless.
    async with container.session_factory.begin() as session:
        await seed_plan(session)
    await signed_in(container, client)

    # Act — a window parameter is accepted by the URL and ignored by the handler.
    plain = (await client.get(PLAN_LIABILITY_PATH)).json()
    windowed = (await client.get(PLAN_LIABILITY_PATH, params=_window(DAY_ONE, DAY_THREE))).json()

    # Assert
    assert "window" not in plain
    assert plain["asOf"] is not None
    assert plain["livePlans"] == windowed["livePlans"] == 1


async def test_the_holder_count_drops_the_erased_and_the_anonymised_count_says_so(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two live plans, one whose holder sent /forget. ``COUNT(DISTINCT)`` does not
    # count NULLs, so the holder count understates by exactly the number of customers who
    # exercised a right. This is the single most regressible number in the module.
    async with container.session_factory.begin() as session:
        await seed_plan(session, key="a")
        await seed_plan(session, key="b", telegram_user_id=None)
    await signed_in(container, client)

    # Act
    body = (await client.get(PLAN_LIABILITY_PATH)).json()

    # Assert
    assert body["livePlans"] == 2
    assert body["liveHolders"] == 1
    assert body["liveAnonymisedPlans"] == 1


async def test_live_plans_exceeds_live_holders_when_one_customer_renewed_early(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a renewal bought before the previous plan lapsed leaves two rows current.
    # Liability is carried by rows, not by people, even before any erasure.
    async with container.session_factory.begin() as session:
        await seed_plan(session, key="a")
        await seed_plan(session, key="b")
    await signed_in(container, client)

    # Act
    body = (await client.get(PLAN_LIABILITY_PATH)).json()

    # Assert
    assert body["livePlans"] == 2
    assert body["liveHolders"] == 1


async def test_unconsumed_songs_is_null_with_no_live_plan_and_zero_when_nothing_is_owed(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the null-never-zero rule applied to an aggregate. ``null`` means "no plan is
    # in this partition"; ``0`` means "plans are, and they owe nothing". Two screens.
    await signed_in(container, client)

    # Act
    empty = (await client.get(PLAN_LIABILITY_PATH)).json()
    async with container.session_factory.begin() as session:
        await seed_plan(session, songs_included=12, songs_used=12)
    exhausted = (await client.get(PLAN_LIABILITY_PATH)).json()

    # Assert
    assert empty["unconsumedSongs"] is None
    assert exhausted["unconsumedSongs"] == 0


async def test_utilisation_returns_ten_bars_always_and_covers_ended_plans_only(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a live plan at 50% appears in no bar, because a running plan's ratio is not
    # final and breakage is not measurable before the clock stops. A histogram with holes in
    # it is unreadable, so all ten bars come back even on an empty table.
    await signed_in(container, client)
    empty = (await client.get(PLAN_LIABILITY_PATH)).json()
    async with container.session_factory.begin() as session:
        await seed_plan(session, key="live", songs_included=12, songs_used=6)
        await seed_plan(session, key="done", ends_at=DAY_ONE, songs_included=12, songs_used=12)
        await seed_plan(session, key="part", ends_at=DAY_ONE, songs_included=12, songs_used=5)

    # Act
    body = (await client.get(PLAN_LIABILITY_PATH)).json()

    # Assert — a fully used plan lands in the closed top bar, not a spurious eleventh; 5 of
    # 12 floors to bar 4 on both dialects because the expression uses ``//``.
    assert len(empty["utilisation"]) == 10
    assert len(body["utilisation"]) == 10
    assert body["endedPlans"] == 2
    assert body["utilisation"][9]["count"] == 1
    assert body["utilisation"][4]["count"] == 1
    assert sum(bar["count"] for bar in body["utilisation"]) == 2


async def test_live_amounts_carry_their_currency_and_are_never_one_scalar(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — two live plans in two currencies. There is no honest total across them, and
    # today's one-element list on a real deployment is not a licence to collapse the shape.
    async with container.session_factory.begin() as session:
        await seed_plan(session, key="a", currency="UZS")
        await seed_plan(session, key="b", currency="USD")
    await signed_in(container, client)

    # Act
    body = (await client.get(PLAN_LIABILITY_PATH)).json()

    # Assert
    assert {row["currency"] for row in body["liveAmounts"]} == {"UZS", "USD"}
    assert all(isinstance(row["amountMinor"], int) for row in body["liveAmounts"])


# ---------------------------------------------------------------------------
# the primitives refuse the illegal shape
# ---------------------------------------------------------------------------
def test_a_bare_rate_and_an_unsourced_cost_are_not_constructible() -> None:
    # Arrange — this is what makes "a bare rate is unrepresentable" true rather than
    # aspirational: the violation raises at construction, so no reviewer has to notice it.
    from pydantic import ValidationError

    from bayram.admin.schemas.overview import FxRateView, RatioView, TrendView, UsdCost

    illegal: tuple[Any, ...] = (
        lambda: RatioView(value=0.5, numerator=1, denominator=0),
        lambda: RatioView(value=None, numerator=1, denominator=2),
        lambda: UsdCost(
            amount_usd=41.2, costed_calls=1, calls=2, cost_source=None, unavailable_reason=None
        ),
        lambda: UsdCost(
            amount_usd=None,
            costed_calls=1,
            calls=2,
            cost_source="derived",
            unavailable_reason=None,
        ),
        lambda: UsdCost(
            amount_usd=1.0,
            costed_calls=3,
            calls=2,
            cost_source="derived",
            unavailable_reason=None,
        ),
        lambda: TrendView(
            current=5, previous=0, change=RatioView(value=1.0, numerator=1, denominator=1)
        ),
        lambda: FxRateView(uzs_per_usd=FX_RATE, as_of=None),
    )

    # Act / Assert
    for build in illegal:
        with pytest.raises(ValidationError):
            build()
