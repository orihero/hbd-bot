"""The segment compiler, against a real (in-memory) database rather than against SQL strings.

**Every field assertion here runs the query.** A test that compared rendered SQL would pass
for a predicate the engine then interprets differently — which is exactly the failure the
correlated subqueries in this registry are most likely to have, since an ``EXISTS`` that
lost its correlation renders perfectly and matches every account in the table. So one
population is seeded once, by hand, and each field says which of its six accounts it selects.

The population is written out rather than generated because the whole value of a field test
is that a reader can check the expected set against the fixture by eye. Six accounts is the
smallest number that gives every field at least one member and at least one non-member:

======  ===============================================================================
QUIET   contact only — no profile, no orders, no money, silent for two hundred days
REGULAR the whole story — profile, five orders, credits, top-ups, a LAPSED plan
SUBSCR  a live plan with songs left, a partial profile, one delivered song
SPENT   a plan that is running and has no songs left (EXHAUSTED, never LAPSED)
BARRED  barred by us AND blocked us back, with one top-up before that happened
BROWSER an abandoned checkout, one draft order, blocked us once and came back
======  ===============================================================================

Rows are inserted directly rather than through a repository, for the reason every seed in
this package gives: the expectations below are computed by hand from these timestamps, and a
store that read its own clock would make them assert whatever it chose.

The refusal tests are not decoration. ``SEGMENT_REFUSALS`` is the one thing in this module
that a future contributor can undo by accident — by adding a field, not by changing a line
of logic — so the four identity columns and the message body are asserted absent from the
registry, absent as an operand, and absent as an error message's contents.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import PaymentIntentState
from bayram.contracts import BotBlockSource, BotMembershipEvent, Language, OrderState, is_err, is_ok
from bayram.db.admin import segment as seg
from bayram.db.admin.segment import (
    FIELDS,
    SEGMENT_LIMITS,
    SEGMENT_REFUSALS,
    SORT_KEYS,
    MatchMode,
    Segment,
    SegmentError,
    SegmentGroup,
    SegmentOp,
    SegmentRule,
    SortSpec,
    compile_segment,
    sort_expression,
)
from bayram.db.enums import ChatDirection, ChatMessageKind, IntentProduct, PlanKind, TopupKind
from bayram.db.models.bot_membership_event import BotMembershipEventRow
from bayram.db.models.chat_message import ChatMessageRow
from bayram.db.models.credit_account import CreditAccountRow
from bayram.db.models.order import OrderRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.db.models.user import UserRow
from bayram.db.models.user_profile import UserProfileRow

#: The instant every relative operator below is measured from. Threaded in, never read from a
#: clock — the compiler takes ``now`` for exactly this reason.
NOW: Final[datetime] = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

QUIET: Final[int] = 1001
REGULAR: Final[int] = 1002
SUBSCRIBER: Final[int] = 1003
SPENT: Final[int] = 1004
BARRED: Final[int] = 1005
BROWSER: Final[int] = 1006

EVERYONE: Final[frozenset[int]] = frozenset({QUIET, REGULAR, SUBSCRIBER, SPENT, BARRED, BROWSER})

#: Every capability this deployment's schema has. The chat fields are gated on it, and the
#: "not available here" refusal below deliberately compiles against an EMPTY set instead.
ALL_CAPABILITIES: Final[frozenset[str]] = frozenset({"chat_messages"})

_JUNE: Final[datetime] = datetime(2026, 6, 1, tzinfo=UTC)
_JULY: Final[datetime] = datetime(2026, 7, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Seed helpers — explicit values, no clocks, no policies
# ---------------------------------------------------------------------------
async def _user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    created_at: datetime,
    language: Language,
    last_seen_at: datetime,
    is_blocked: bool = False,
    blocked_bot_at: datetime | None = None,
) -> UserRow:
    row = UserRow(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        ui_language=language,
        is_blocked=is_blocked,
        last_seen_at=last_seen_at,
        blocked_bot_at=blocked_bot_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def _profile(session: AsyncSession, *, user: UserRow, **kw: Any) -> None:
    session.add(
        UserProfileRow(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            phone_e164=kw.pop("phone_e164", None),
            telegram_username=kw.pop("telegram_username", None),
            first_name=kw.pop("first_name", None),
            last_name=kw.pop("last_name", None),
            avatar_stored_at=kw.pop("avatar_stored_at", None),
            language_chosen_at=kw.pop("language_chosen_at", None),
            phone_shared_at=kw.pop("phone_shared_at", None),
            onboarded_at=kw.pop("onboarded_at", None),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()


async def _order(
    session: AsyncSession,
    *,
    user: UserRow,
    state: OrderState,
    created_at: datetime,
    delivered_at: datetime | None = None,
) -> None:
    session.add(
        OrderRow(
            id=uuid4(),
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            state=state,
            correlation_id=uuid4().hex,
            is_paid=state in (OrderState.AUTHORIZED, OrderState.GENERATING, OrderState.DELIVERED),
            delivered_at=delivered_at,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await session.flush()


async def _account(
    session: AsyncSession, *, telegram_user_id: int, balance: int, granted: int, opened: datetime
) -> None:
    session.add(
        CreditAccountRow(
            telegram_user_id=telegram_user_id,
            balance=balance,
            lifetime_granted=granted,
            created_at=opened,
            updated_at=opened,
        )
    )
    await session.flush()


async def _plan(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    ends_at: datetime,
    songs_used: int,
    songs_included: int = 12,
) -> None:
    session.add(
        PlanPurchaseRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            plan=PlanKind.STARTER,
            songs_included=songs_included,
            songs_used=songs_used,
            amount_minor=4_900_000,
            currency="UZS",
            provider="stub",
            reference="stub-raw",
            idempotency_key=uuid4().hex,
            plan_ends_at=ends_at,
            created_at=NOW - timedelta(days=60),
            updated_at=NOW - timedelta(days=60),
        )
    )
    await session.flush()


async def _topup(
    session: AsyncSession, *, telegram_user_id: int, amount_minor: int, created_at: datetime
) -> None:
    session.add(
        TopupPurchaseRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            product=TopupKind.SINGLE,
            credits_granted=1,
            amount_minor=amount_minor,
            currency="UZS",
            provider="stub",
            reference="stub-raw",
            idempotency_key=uuid4().hex,
            created_at=created_at,
        )
    )
    await session.flush()


async def _intent(
    session: AsyncSession, *, telegram_user_id: int, state: PaymentIntentState
) -> None:
    session.add(
        PaymentIntentRow(
            id=uuid4(),
            public_ref=uuid4().hex[:24],
            idempotency_key=uuid4().hex,
            telegram_user_id=telegram_user_id,
            product=IntentProduct.SINGLE,
            amount_minor=700_000,
            currency="UZS",
            provider="stub",
            merchant_id="587f72c72cac0d162c722ae2",
            is_sandbox=True,
            language="uz_latn",
            state=state,
            valid_until=NOW + timedelta(hours=12),
            created_at=NOW - timedelta(days=3),
            updated_at=NOW - timedelta(days=3),
        )
    )
    await session.flush()


async def _membership(
    session: AsyncSession, *, telegram_user_id: int, event: BotMembershipEvent
) -> None:
    session.add(
        BotMembershipEventRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            event=event,
            source=BotBlockSource.MEMBERSHIP_UPDATE,
            at=NOW - timedelta(days=12),
        )
    )
    await session.flush()


async def _message(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    direction: ChatDirection,
    created_at: datetime,
    wizard_step: str | None = None,
) -> None:
    session.add(
        ChatMessageRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            chat_id=telegram_user_id,
            direction=direction,
            kind=ChatMessageKind.TEXT,
            wizard_step=wizard_step,
            is_truncated=False,
            is_from_worker=False,
            text_expires_at=created_at + timedelta(days=30),
            expires_at=created_at + timedelta(days=90),
            created_at=created_at,
        )
    )
    await session.flush()


@pytest.fixture
async def population(sessions: async_sessionmaker[AsyncSession]) -> None:
    """The six accounts the module docstring tabulates, written by hand."""
    async with sessions.begin() as session:
        quiet = await _user(
            session,
            telegram_user_id=QUIET,
            created_at=datetime(2026, 6, 15, tzinfo=UTC),
            language=Language.UZ_LATN,
            last_seen_at=NOW - timedelta(days=200),
        )
        regular = await _user(
            session,
            telegram_user_id=REGULAR,
            created_at=datetime(2026, 6, 20, tzinfo=UTC),
            language=Language.RU,
            last_seen_at=NOW - timedelta(days=1),
        )
        subscriber = await _user(
            session,
            telegram_user_id=SUBSCRIBER,
            created_at=datetime(2026, 7, 2, tzinfo=UTC),
            language=Language.EN,
            last_seen_at=NOW - timedelta(days=2),
        )
        await _user(
            session,
            telegram_user_id=SPENT,
            created_at=datetime(2026, 7, 5, tzinfo=UTC),
            language=Language.UZ_CYRL,
            last_seen_at=NOW - timedelta(days=3),
        )
        await _user(
            session,
            telegram_user_id=BARRED,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
            language=Language.RU,
            last_seen_at=NOW - timedelta(days=4),
            is_blocked=True,
            blocked_bot_at=NOW - timedelta(days=10),
        )
        browser = await _user(
            session,
            telegram_user_id=BROWSER,
            created_at=datetime(2026, 8, 10, tzinfo=UTC),
            language=Language.UZ_LATN,
            last_seen_at=NOW - timedelta(days=5),
        )
        del quiet  # contact only: no profile, no orders, no money, no messages

        # REGULAR: the complete profile. SUBSCRIBER: half of one, so every presence field
        # has a member that is not simply "has a row".
        await _profile(
            session,
            user=regular,
            phone_e164="+998901234542",
            telegram_username="gulomjon",
            first_name="Gʻulomjon",
            avatar_stored_at=datetime(2026, 6, 21, tzinfo=UTC),
            language_chosen_at=datetime(2026, 6, 20, 11, tzinfo=UTC),
            phone_shared_at=datetime(2026, 6, 20, 12, tzinfo=UTC),
            onboarded_at=datetime(2026, 6, 21, tzinfo=UTC),
        )
        await _profile(
            session,
            user=subscriber,
            telegram_username="dilnoza",
            language_chosen_at=datetime(2026, 7, 2, tzinfo=UTC),
        )

        for at in (
            datetime(2026, 6, 25, tzinfo=UTC),
            datetime(2026, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 10, tzinfo=UTC),
        ):
            await _order(
                session, user=regular, state=OrderState.DELIVERED, created_at=at, delivered_at=at
            )
        await _order(
            session,
            user=regular,
            state=OrderState.FAILED,
            created_at=datetime(2026, 7, 12, tzinfo=UTC),
        )
        await _order(
            session,
            user=regular,
            state=OrderState.DRAFT,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        await _order(
            session,
            user=subscriber,
            state=OrderState.DELIVERED,
            created_at=datetime(2026, 7, 20, tzinfo=UTC),
            delivered_at=datetime(2026, 7, 20, tzinfo=UTC),
        )
        await _order(
            session,
            user=browser,
            state=OrderState.DRAFT,
            created_at=datetime(2026, 8, 11, tzinfo=UTC),
        )

        await _account(
            session,
            telegram_user_id=REGULAR,
            balance=5,
            granted=12,
            opened=datetime(2026, 6, 21, tzinfo=UTC),
        )
        await _account(
            session,
            telegram_user_id=SUBSCRIBER,
            balance=0,
            granted=3,
            opened=datetime(2026, 7, 3, tzinfo=UTC),
        )

        # The three live plan cases, one account each, so PlanStatus is exercised as the
        # mutually-exclusive partition it claims to be.
        await _plan(
            session, telegram_user_id=REGULAR, ends_at=NOW - timedelta(days=5), songs_used=4
        )
        await _plan(
            session, telegram_user_id=SUBSCRIBER, ends_at=NOW + timedelta(days=20), songs_used=2
        )
        await _plan(
            session, telegram_user_id=SPENT, ends_at=NOW + timedelta(days=10), songs_used=12
        )

        await _topup(
            session,
            telegram_user_id=REGULAR,
            amount_minor=30_000,
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        await _topup(
            session,
            telegram_user_id=REGULAR,
            amount_minor=20_000,
            created_at=datetime(2026, 8, 2, tzinfo=UTC),
        )
        await _topup(
            session,
            telegram_user_id=BARRED,
            amount_minor=10_000,
            created_at=datetime(2026, 8, 5, tzinfo=UTC),
        )

        await _intent(session, telegram_user_id=REGULAR, state=PaymentIntentState.PAID)
        await _intent(session, telegram_user_id=REGULAR, state=PaymentIntentState.EXPIRED)
        await _intent(session, telegram_user_id=BROWSER, state=PaymentIntentState.PENDING)

        await _membership(session, telegram_user_id=BARRED, event=BotMembershipEvent.BLOCKED)
        await _membership(session, telegram_user_id=BROWSER, event=BotMembershipEvent.BLOCKED)
        await _membership(session, telegram_user_id=BROWSER, event=BotMembershipEvent.UNBLOCKED)

        await _message(
            session,
            telegram_user_id=REGULAR,
            direction=ChatDirection.INBOUND,
            created_at=NOW - timedelta(days=2),
            wizard_step="occasion",
        )
        await _message(
            session,
            telegram_user_id=REGULAR,
            direction=ChatDirection.INBOUND,
            created_at=NOW - timedelta(days=1),
        )
        await _message(
            session,
            telegram_user_id=REGULAR,
            direction=ChatDirection.OUTBOUND,
            created_at=NOW - timedelta(days=1),
        )
        await _message(
            session,
            telegram_user_id=BROWSER,
            direction=ChatDirection.INBOUND,
            created_at=NOW - timedelta(days=40),
            wizard_step="recipient",
        )


# ---------------------------------------------------------------------------
# Helpers the assertions are written in terms of
# ---------------------------------------------------------------------------
def _one(field: str, op: SegmentOp, value: object = None) -> Segment:
    """A root ``all`` group carrying a single rule — the shape most tests want."""
    return Segment(root=SegmentGroup(match=MatchMode.ALL, rules=(SegmentRule(field, op, value),)))


async def _matched(
    sessions: async_sessionmaker[AsyncSession],
    document: Segment,
    *,
    capabilities: frozenset[str] = ALL_CAPABILITIES,
) -> frozenset[int]:
    """Compile, run, and return the Telegram ids the segment selects."""
    compiled = compile_segment(document, now=NOW, capabilities=capabilities)
    assert is_ok(compiled), compiled
    statement = sa.select(UserRow.telegram_user_id)
    if compiled.value.predicate is not None:
        statement = statement.where(compiled.value.predicate)
    async with sessions() as session:
        rows: Sequence[int] = (await session.execute(statement)).scalars().all()
    return frozenset(rows)


# ---------------------------------------------------------------------------
# One case per field. Every entry in FIELDS appears exactly once.
# ---------------------------------------------------------------------------
_FIELD_CASES: Final[tuple[tuple[str, SegmentOp, object, frozenset[int]], ...]] = (
    # users, direct columns
    ("telegram_user_id", SegmentOp.EQ, REGULAR, frozenset({REGULAR})),
    ("ui_language", SegmentOp.IN, ["ru"], frozenset({REGULAR, BARRED})),
    ("is_blocked", SegmentOp.IS_TRUE, None, frozenset({BARRED})),
    ("bot_blocked", SegmentOp.IS_TRUE, None, frozenset({BARRED})),
    ("bot_blocked_at", SegmentOp.IS_NOT_NULL, None, frozenset({BARRED})),
    ("joined_at", SegmentOp.BETWEEN, [_JUNE, _JULY], frozenset({QUIET, REGULAR})),
    ("last_activity_at", SegmentOp.NOT_WITHIN_LAST_DAYS, 90, frozenset({QUIET})),
    ("is_reachable", SegmentOp.IS_TRUE, None, EVERYONE - {BARRED}),
    # user_profiles — presence only
    ("has_profile", SegmentOp.IS_TRUE, None, frozenset({REGULAR, SUBSCRIBER})),
    ("has_phone", SegmentOp.IS_TRUE, None, frozenset({REGULAR})),
    ("has_username", SegmentOp.IS_TRUE, None, frozenset({REGULAR, SUBSCRIBER})),
    ("has_avatar", SegmentOp.IS_TRUE, None, frozenset({REGULAR})),
    ("onboarded_at", SegmentOp.IS_NOT_NULL, None, frozenset({REGULAR})),
    ("phone_shared_at", SegmentOp.IS_NOT_NULL, None, frozenset({REGULAR})),
    ("language_chosen_at", SegmentOp.IS_NOT_NULL, None, frozenset({REGULAR, SUBSCRIBER})),
    # credit_accounts
    ("has_credit_account", SegmentOp.IS_TRUE, None, frozenset({REGULAR, SUBSCRIBER})),
    ("credit_balance", SegmentOp.GT, 0, frozenset({REGULAR})),
    ("lifetime_credits_granted", SegmentOp.GTE, 3, frozenset({REGULAR, SUBSCRIBER})),
    ("first_metered_at", SegmentOp.IS_NOT_NULL, None, frozenset({REGULAR, SUBSCRIBER})),
    # orders
    ("order_count", SegmentOp.GTE, 1, frozenset({REGULAR, SUBSCRIBER, BROWSER})),
    ("paid_order_count", SegmentOp.GTE, 1, frozenset({REGULAR, SUBSCRIBER})),
    ("delivered_order_count", SegmentOp.GTE, 3, frozenset({REGULAR})),
    ("failed_order_count", SegmentOp.GTE, 1, frozenset({REGULAR})),
    ("first_order_at", SegmentOp.IS_NULL, None, frozenset({QUIET, SPENT, BARRED})),
    (
        "last_order_at",
        SegmentOp.WITHIN_LAST_DAYS,
        30,
        frozenset({BROWSER}),
    ),
    ("last_delivered_at", SegmentOp.IS_NOT_NULL, None, frozenset({REGULAR, SUBSCRIBER})),
    ("order_state", SegmentOp.IN, ["failed"], frozenset({REGULAR})),
    # plan_purchases
    ("plan_status", SegmentOp.IN, ["lapsed"], frozenset({REGULAR})),
    ("plan_ends_at", SegmentOp.WITHIN_NEXT_DAYS, 15, frozenset({SPENT})),
    ("plan_purchase_count", SegmentOp.GTE, 1, frozenset({REGULAR, SUBSCRIBER, SPENT})),
    # topup_purchases, payment_intents, bot_membership_events
    ("topup_count", SegmentOp.GTE, 2, frozenset({REGULAR})),
    ("topup_spend_minor", SegmentOp.GTE, 50_000, frozenset({REGULAR})),
    ("last_topup_at", SegmentOp.IS_NOT_NULL, None, frozenset({REGULAR, BARRED})),
    ("has_paid_ever", SegmentOp.IS_TRUE, None, frozenset({REGULAR, SUBSCRIBER, SPENT, BARRED})),
    ("has_abandoned_checkout", SegmentOp.IS_TRUE, None, frozenset({BROWSER})),
    ("bot_block_event_count", SegmentOp.GTE, 1, frozenset({BARRED, BROWSER})),
    ("has_returned_after_block", SegmentOp.IS_TRUE, None, frozenset({BROWSER})),
    # chat_messages — capability-gated
    ("inbound_message_count", SegmentOp.GTE, 2, frozenset({REGULAR})),
    ("last_inbound_message_at", SegmentOp.WITHIN_LAST_DAYS, 7, frozenset({REGULAR})),
    ("wizard_step", SegmentOp.IN, ["occasion"], frozenset({REGULAR})),
)


@pytest.mark.parametrize(("field", "op", "value", "expected"), _FIELD_CASES, ids=lambda case: case)
async def test_each_field_selects_the_accounts_it_names(
    sessions: async_sessionmaker[AsyncSession],
    population: None,
    field: str,
    op: SegmentOp,
    value: object,
    expected: frozenset[int],
) -> None:
    # Arrange / Act
    matched = await _matched(sessions, _one(field, op, value))

    # Assert
    assert matched == expected


def test_every_registered_field_has_a_case_and_a_safety_argument() -> None:
    """The table above is the coverage guarantee, so it must not drift from the registry.

    Two assertions and not one: a field with no case is untested, and a field with no ``doc``
    is one nobody had to argue for — which is how an allowlist stops being one.
    """
    # Arrange / Act
    covered = {field for field, _, _, _ in _FIELD_CASES}

    # Assert
    assert covered == set(FIELDS)
    assert all(len(spec.doc) > 80 for spec in FIELDS.values())


# ---------------------------------------------------------------------------
# One case per operator. Every SegmentOp member appears exactly once.
# ---------------------------------------------------------------------------
_OPERATOR_CASES: Final[tuple[tuple[SegmentOp, str, object, frozenset[int]], ...]] = (
    (SegmentOp.EQ, "telegram_user_id", QUIET, frozenset({QUIET})),
    (SegmentOp.NEQ, "order_count", 0, frozenset({REGULAR, SUBSCRIBER, BROWSER})),
    (SegmentOp.IN, "ui_language", ["en", "uz_cyrl"], frozenset({SUBSCRIBER, SPENT})),
    (SegmentOp.NOT_IN, "ui_language", ["ru"], EVERYONE - {REGULAR, BARRED}),
    (SegmentOp.GT, "credit_balance", 0, frozenset({REGULAR})),
    (SegmentOp.GTE, "order_count", 5, frozenset({REGULAR})),
    (SegmentOp.LT, "order_count", 1, frozenset({QUIET, SPENT, BARRED})),
    (SegmentOp.LTE, "order_count", 1, frozenset({QUIET, SUBSCRIBER, SPENT, BARRED, BROWSER})),
    (SegmentOp.BETWEEN, "joined_at", [_JUNE, _JULY], frozenset({QUIET, REGULAR})),
    (SegmentOp.IS_TRUE, "has_profile", None, frozenset({REGULAR, SUBSCRIBER})),
    (SegmentOp.IS_FALSE, "has_profile", None, EVERYONE - {REGULAR, SUBSCRIBER}),
    (SegmentOp.IS_NULL, "bot_blocked_at", None, EVERYONE - {BARRED}),
    (SegmentOp.IS_NOT_NULL, "bot_blocked_at", None, frozenset({BARRED})),
    (SegmentOp.WITHIN_LAST_DAYS, "last_activity_at", 30, EVERYONE - {QUIET}),
    (SegmentOp.NOT_WITHIN_LAST_DAYS, "last_activity_at", 30, frozenset({QUIET})),
    (SegmentOp.WITHIN_NEXT_DAYS, "plan_ends_at", 30, frozenset({SUBSCRIBER, SPENT})),
)


@pytest.mark.parametrize(("op", "field", "value", "expected"), _OPERATOR_CASES)
async def test_each_operator_means_what_the_table_says(
    sessions: async_sessionmaker[AsyncSession],
    population: None,
    op: SegmentOp,
    field: str,
    value: object,
    expected: frozenset[int],
) -> None:
    # Arrange / Act
    matched = await _matched(sessions, _one(field, op, value))

    # Assert
    assert matched == expected


def test_every_operator_has_a_case() -> None:
    # Arrange / Act / Assert — a new member with no case is an untested operator.
    assert {op for op, _, _, _ in _OPERATOR_CASES} == set(SegmentOp)


async def test_between_is_half_open_so_adjacent_windows_tile(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """The convention ``apply_window`` uses, so a June segment and a June tile agree.

    SUBSCRIBER joined on 2 July. A closed upper bound would put them in June as well as in
    July and every monthly cohort would double-count its boundary.
    """
    # Arrange / Act
    june = await _matched(sessions, _one("joined_at", SegmentOp.BETWEEN, [_JUNE, _JULY]))
    july = await _matched(
        sessions,
        _one("joined_at", SegmentOp.BETWEEN, [_JULY, datetime(2026, 8, 1, tzinfo=UTC)]),
    )

    # Assert
    assert june == {QUIET, REGULAR}
    assert july == {SUBSCRIBER, SPENT}
    assert not june & july


# ---------------------------------------------------------------------------
# The NULL rule: "has not done this" must contain "has never done this"
# ---------------------------------------------------------------------------
async def test_not_within_last_days_includes_accounts_that_never_did_it(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """§1.3's NULL rule, on the field it matters most for.

    Three accounts have never ordered at all, so ``last_order_at`` is NULL for them. A
    "quiet for 30 days" audience that excluded them would reach everyone except the people
    it was built to win back — and the mistake is invisible, because the segment still
    returns rows.
    """
    # Arrange
    never_ordered = {QUIET, SPENT, BARRED}

    # Act
    stale = await _matched(sessions, _one("last_order_at", SegmentOp.NOT_WITHIN_LAST_DAYS, 30))
    recent = await _matched(sessions, _one("last_order_at", SegmentOp.WITHIN_LAST_DAYS, 30))

    # Assert — the two are exact complements, which is what makes the chip flippable.
    assert never_ordered <= stale
    assert stale == EVERYONE - {BROWSER}
    assert recent == {BROWSER}
    assert not stale & recent


async def test_lt_on_a_nullable_instant_includes_nulls_and_gt_does_not(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """The same rule for the absolute comparisons, stated on the same field."""
    # Arrange — between SUBSCRIBER's last order (20 July) and REGULAR's (1 August).
    cutoff = datetime(2026, 7, 25, tzinfo=UTC)

    # Act
    before = await _matched(sessions, _one("last_order_at", SegmentOp.LT, cutoff))
    after = await _matched(sessions, _one("last_order_at", SegmentOp.GT, cutoff))

    # Assert — "never ordered" is stale, never recent.
    assert before == {QUIET, SPENT, BARRED, SUBSCRIBER}
    assert after == {REGULAR, BROWSER}


async def test_a_field_whose_column_cannot_be_null_takes_no_null_branch(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """``users.last_seen_at`` is NOT NULL, so its spec says a NULL is not stale.

    Asserted because the flag is per-field data rather than a rule the compiler derives, and
    a wrong one here is an ``OR … IS NULL`` the planner evaluates for every row forever.
    """
    # Arrange / Act / Assert
    assert FIELDS["last_activity_at"].null_is_stale is False
    assert FIELDS["last_order_at"].null_is_stale is True
    quiet = await _matched(sessions, _one("last_activity_at", SegmentOp.LT, NOW))
    assert quiet == EVERYONE


# ---------------------------------------------------------------------------
# The four named examples, compiled and run
# ---------------------------------------------------------------------------
async def test_the_plan_expired_and_not_repurchased_audience(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """ "Did not renew" — and ``lapsed`` is the only truthful spelling of it.

    There is no renewal in this product, so the audience is "bought a plan, none is running".
    SPENT is the account this test exists for: their plan is spent but still running, so they
    are ``exhausted`` and must NOT be told their subscription lapsed.
    """
    # Arrange / Act
    lapsed = await _matched(sessions, _one("plan_status", SegmentOp.IN, ["lapsed"]))

    # Assert
    assert lapsed == {REGULAR}
    assert await _matched(sessions, _one("plan_status", SegmentOp.IN, ["exhausted"])) == {SPENT}
    assert await _matched(sessions, _one("plan_status", SegmentOp.IN, ["active"])) == {SUBSCRIBER}


async def test_the_four_plan_cases_partition_every_account(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """Mutually exclusive and exhaustive, which is what makes ``not_in`` honest."""
    # Arrange
    # Spelled as the wire values a document actually carries, not as enum members.
    cases = ("none", "active", "exhausted", "lapsed")

    # Act
    matched = [
        await _matched(sessions, _one("plan_status", SegmentOp.IN, [case])) for case in cases
    ]

    # Assert
    assert frozenset().union(*matched) == EVERYONE
    assert sum(len(group) for group in matched) == len(EVERYONE)
    assert (
        await _matched(sessions, _one("plan_status", SegmentOp.NOT_IN, list(cases))) == frozenset()
    )


async def test_joined_in_june_is_a_half_open_range_on_first_contact(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    # Arrange / Act
    matched = await _matched(sessions, _one("joined_at", SegmentOp.BETWEEN, [_JUNE, _JULY]))

    # Assert
    assert matched == {QUIET, REGULAR}


async def test_generated_the_most_is_a_threshold_plus_a_sort(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """A sort alone narrows nothing, so the audience is the threshold and the sort orders it."""
    # Arrange
    document = Segment(
        root=SegmentGroup(
            match=MatchMode.ALL,
            rules=(SegmentRule("delivered_order_count", SegmentOp.GTE, 1),),
        ),
        sort=SortSpec(key="delivered_order_count", direction="desc"),
    )

    # Act
    compiled = compile_segment(document, now=NOW, capabilities=ALL_CAPABILITIES)
    assert is_ok(compiled)
    predicate = compiled.value.predicate
    assert predicate is not None
    ordered = (
        sa.select(UserRow.telegram_user_id)
        .where(predicate)
        .order_by(sort_expression(compiled.value.sort.key).desc(), UserRow.id.desc())
    )
    async with sessions() as session:
        rows = list((await session.execute(ordered)).scalars().all())

    # Assert — three delivered before one, and the sort is carried on the compiled result.
    assert rows == [REGULAR, SUBSCRIBER]
    assert compiled.value.sort.key == "delivered_order_count"
    assert compiled.value.aggregate_rule_count == 1


async def test_inactive_for_months_reaches_the_account_that_stopped(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    # Arrange / Act
    matched = await _matched(sessions, _one("last_activity_at", SegmentOp.NOT_WITHIN_LAST_DAYS, 90))

    # Assert
    assert matched == {QUIET}


async def test_a_composite_segment_nests_groups_and_ands_the_root(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """The blueprint's composite: lapsed heavy users who still have credit and can be reached."""
    # Arrange
    document = Segment(
        root=SegmentGroup(
            match=MatchMode.ALL,
            rules=(
                SegmentRule("plan_status", SegmentOp.IN, ["lapsed"]),
                SegmentRule("delivered_order_count", SegmentOp.GTE, 2),
                SegmentRule("credit_balance", SegmentOp.GT, 0),
                SegmentRule("is_reachable", SegmentOp.IS_TRUE),
                SegmentGroup(
                    match=MatchMode.ANY,
                    rules=(
                        SegmentRule("ui_language", SegmentOp.IN, ["uz_latn", "uz_cyrl"]),
                        SegmentRule("topup_count", SegmentOp.GTE, 1),
                    ),
                ),
            ),
        ),
        sort=SortSpec(key="last_order_at", direction="desc"),
    )

    # Act
    matched = await _matched(sessions, document)

    # Assert — REGULAR is Russian-speaking and qualifies through the top-up arm of the OR.
    assert matched == {REGULAR}


async def test_match_none_is_the_negation_of_the_or(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """One negation mechanism, so there is one place to reason about NULL semantics."""
    # Arrange
    document = Segment(
        root=SegmentGroup(
            match=MatchMode.NONE,
            rules=(
                SegmentRule("is_blocked", SegmentOp.IS_TRUE),
                SegmentRule("has_paid_ever", SegmentOp.IS_TRUE),
            ),
        )
    )

    # Act
    matched = await _matched(sessions, document)

    # Assert
    assert matched == {QUIET, BROWSER}


async def test_an_empty_root_group_means_everyone(
    sessions: async_sessionmaker[AsyncSession], population: None
) -> None:
    """The unfiltered list, and the only place an empty group is legal."""
    # Arrange
    document = Segment(root=SegmentGroup(match=MatchMode.ALL, rules=()))

    # Act
    compiled = compile_segment(document, now=NOW, capabilities=ALL_CAPABILITIES)

    # Assert — ``None`` rather than a tautology, so ``_filtered`` adds no clause at all.
    assert is_ok(compiled)
    assert compiled.value.predicate is None
    assert await _matched(sessions, document) == EVERYONE


def test_an_empty_nested_group_is_refused() -> None:
    """A silently-true group is how a campaign goes to the whole database looking narrowed."""
    # Arrange
    document = Segment(
        root=SegmentGroup(
            match=MatchMode.ALL,
            rules=(
                SegmentRule("is_blocked", SegmentOp.IS_TRUE),
                SegmentGroup(match=MatchMode.ANY, rules=()),
            ),
        )
    )

    # Act
    compiled = compile_segment(document, now=NOW, capabilities=ALL_CAPABILITIES)

    # Assert
    assert is_err(compiled)
    assert "at least one rule" in str(compiled.error)


# ---------------------------------------------------------------------------
# THE REFUSALS
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("column", sorted(SEGMENT_REFUSALS))
def test_no_refused_column_is_a_field_key(column: str) -> None:
    """The four identity columns and the message body are not addressable, under any name."""
    # Arrange / Act / Assert
    assert column not in FIELDS
    assert not any(column in key for key in FIELDS)


@pytest.mark.parametrize("column", sorted(SEGMENT_REFUSALS))
def test_a_rule_naming_a_refused_column_is_an_unknown_field(column: str) -> None:
    # Arrange / Act
    compiled = compile_segment(
        _one(column, SegmentOp.EQ, "+998901234542"), now=NOW, capabilities=ALL_CAPABILITIES
    )

    # Assert
    assert is_err(compiled)
    assert "unknown field" in str(compiled.error)


def test_the_only_fields_that_touch_a_refused_column_are_presence_ticks() -> None:
    """The boundary the refusal actually draws: ``IS NOT NULL`` yes, ``=`` never.

    ``has_phone`` and ``has_username`` do read two of the refused columns, and that is
    allowed — "we hold one" is a fact about our records. What is refused is a caller-supplied
    value reaching them, and a field that takes only ``is_true``/``is_false`` carries no value
    to reach anything with.
    """
    # Arrange
    presence = ("has_phone", "has_username", "has_avatar")

    # Act / Assert
    for key in presence:
        assert FIELDS[key].ops == frozenset({SegmentOp.IS_TRUE, SegmentOp.IS_FALSE})
    assert not any(
        spec.kind is seg.FieldKind.TOKEN and spec.key != "wizard_step" for spec in FIELDS.values()
    )


def test_last_activity_at_is_filterable_and_never_sortable() -> None:
    """The one asymmetry in the registry, and the reason it exists.

    A predicate discloses the bucket the operator already chose. A sort publishes a total
    order over identified accounts, which is the minute-by-minute surveillance the withheld
    ``last_seen_at`` projection exists to prevent. Asserted rather than commented, because
    ``sortable=True`` is a one-character regression.
    """
    # Arrange / Act / Assert
    assert "last_activity_at" in FIELDS
    assert FIELDS["last_activity_at"].sortable is False
    assert "last_activity_at" not in SORT_KEYS
    with pytest.raises(SegmentError):
        sort_expression("last_activity_at")


def test_an_unknown_field_is_refused_by_name_and_the_value_never_is() -> None:
    """The field is a schema name this API publishes; the value is customer data."""
    # Arrange
    secret = "+998901234542"

    # Act
    compiled = compile_segment(
        _one("phone_prefix", SegmentOp.EQ, secret), now=NOW, capabilities=ALL_CAPABILITIES
    )

    # Assert
    assert is_err(compiled)
    assert compiled.error.context["field"] == "phone_prefix"
    assert secret not in str(compiled.error.context)
    assert secret not in str(compiled.error)


def test_a_bad_value_is_refused_with_the_field_named_and_the_value_withheld() -> None:
    """Twenty-five rules means the caller has to be told which one — and only which one."""
    # Arrange
    secret = "+998901234542"

    # Act
    compiled = compile_segment(
        _one("order_count", SegmentOp.GTE, secret), now=NOW, capabilities=ALL_CAPABILITIES
    )

    # Assert
    assert is_err(compiled)
    assert compiled.error.context["field"] == "order_count"
    assert secret not in str(compiled.error.context)


def test_a_capability_the_deployment_lacks_is_named_rather_than_dropped() -> None:
    """ "The table is not installed" and "nobody matched" must not look the same."""
    # Arrange / Act
    compiled = compile_segment(
        _one("inbound_message_count", SegmentOp.GTE, 1), now=NOW, capabilities=frozenset()
    )

    # Assert
    assert is_err(compiled)
    assert compiled.error.context["field"] == "inbound_message_count"
    assert "not available here" in str(compiled.error)


def test_an_operator_a_field_does_not_offer_is_refused() -> None:
    """``telegram_user_id`` takes ``eq`` and ``in`` — a range over account ids is a scan."""
    # Arrange / Act
    compiled = compile_segment(
        _one("telegram_user_id", SegmentOp.GT, 1000), now=NOW, capabilities=ALL_CAPABILITIES
    )

    # Assert
    assert is_err(compiled)
    assert "does not apply" in str(compiled.error)


def test_an_unknown_enum_member_is_refused_before_any_sql_exists() -> None:
    # Arrange / Act
    compiled = compile_segment(
        _one("ui_language", SegmentOp.IN, ["klingon"]), now=NOW, capabilities=ALL_CAPABILITIES
    )

    # Assert
    assert is_err(compiled)
    assert "unknown value" in str(compiled.error)


def test_a_naive_instant_is_refused_rather_than_assumed_to_be_utc() -> None:
    # Arrange
    naive = datetime(2026, 6, 1, 0, 0)

    # Act
    compiled = compile_segment(
        _one("joined_at", SegmentOp.GTE, naive), now=NOW, capabilities=ALL_CAPABILITIES
    )

    # Assert
    assert is_err(compiled)
    assert "UTC offset" in str(compiled.error)


def test_a_boolean_is_not_accepted_where_a_whole_number_is_asked_for() -> None:
    """``bool`` is an ``int`` subclass, so ``true`` would otherwise compile to ``>= 1``."""
    # Arrange / Act
    compiled = compile_segment(
        _one("order_count", SegmentOp.GTE, True), now=NOW, capabilities=ALL_CAPABILITIES
    )

    # Assert
    assert is_err(compiled)


def test_an_empty_value_list_is_refused_rather_than_becoming_in_nothing() -> None:
    """A cleared multi-select is a mistake, not an audience of nobody."""
    # Arrange / Act
    compiled = compile_segment(
        _one("ui_language", SegmentOp.IN, []), now=NOW, capabilities=ALL_CAPABILITIES
    )

    # Assert
    assert is_err(compiled)
    assert "at least one value" in str(compiled.error)


@pytest.mark.parametrize("days", [0, -1, seg.MAX_RELATIVE_DAYS + 1])
def test_a_relative_day_count_is_bounded_at_both_ends(days: int) -> None:
    # Arrange / Act
    compiled = compile_segment(
        _one("last_activity_at", SegmentOp.WITHIN_LAST_DAYS, days),
        now=NOW,
        capabilities=ALL_CAPABILITIES,
    )

    # Assert
    assert is_err(compiled)


def test_a_between_whose_bounds_are_reversed_is_refused() -> None:
    # Arrange / Act
    compiled = compile_segment(
        _one("joined_at", SegmentOp.BETWEEN, [_JULY, _JUNE]),
        now=NOW,
        capabilities=ALL_CAPABILITIES,
    )

    # Assert
    assert is_err(compiled)
    assert "ends before it starts" in str(compiled.error)


# ---------------------------------------------------------------------------
# THE LIMITS — every breach is a refusal, never a truncation
# ---------------------------------------------------------------------------
def test_more_rules_than_the_cap_is_refused() -> None:
    """Truncating would narrow or widen the audience without saying so."""
    # Arrange
    rules = tuple(
        SegmentRule("order_count", SegmentOp.GTE, index)
        for index in range(SEGMENT_LIMITS.max_rules + 1)
    )

    # Act
    compiled = compile_segment(
        Segment(root=SegmentGroup(match=MatchMode.ALL, rules=rules)),
        now=NOW,
        capabilities=ALL_CAPABILITIES,
    )

    # Assert
    assert is_err(compiled)
    assert str(SEGMENT_LIMITS.max_rules) in str(compiled.error)


def test_the_rule_cap_counts_leaves_across_every_group() -> None:
    """A nested group is not a way to smuggle a twenty-sixth rule past the cap."""
    # Arrange — one rule at the root and the rest buried one level down.
    nested = SegmentGroup(
        match=MatchMode.ANY,
        rules=tuple(
            SegmentRule("order_count", SegmentOp.GTE, index)
            for index in range(SEGMENT_LIMITS.max_rules)
        ),
    )
    document = Segment(
        root=SegmentGroup(
            match=MatchMode.ALL, rules=(SegmentRule("is_blocked", SegmentOp.IS_TRUE), nested)
        )
    )

    # Act / Assert
    assert is_err(compile_segment(document, now=NOW, capabilities=ALL_CAPABILITIES))


def test_nesting_deeper_than_the_cap_is_refused() -> None:
    """Root plus two levels. Deeper is a boolean nobody reviewing the campaign can read."""
    # Arrange — four levels of group.
    node = SegmentGroup(match=MatchMode.ANY, rules=(SegmentRule("is_blocked", SegmentOp.IS_TRUE),))
    for _ in range(SEGMENT_LIMITS.max_depth):
        node = SegmentGroup(match=MatchMode.ALL, rules=(node,))

    # Act
    compiled = compile_segment(Segment(root=node), now=NOW, capabilities=ALL_CAPABILITIES)

    # Assert
    assert is_err(compiled)
    assert str(SEGMENT_LIMITS.max_depth) in str(compiled.error)


def test_nesting_exactly_at_the_cap_is_accepted() -> None:
    """The limit is inclusive, asserted so a fencepost change fails here rather than in the UI."""
    # Arrange — root + two nested levels.
    innermost = SegmentGroup(
        match=MatchMode.ANY, rules=(SegmentRule("is_blocked", SegmentOp.IS_TRUE),)
    )
    document = Segment(
        root=SegmentGroup(
            match=MatchMode.ALL,
            rules=(SegmentGroup(match=MatchMode.ALL, rules=(innermost,)),),
        )
    )

    # Act / Assert
    assert is_ok(compile_segment(document, now=NOW, capabilities=ALL_CAPABILITIES))


def test_more_value_members_than_the_cap_is_refused() -> None:
    # Arrange
    members = [str(index) for index in range(SEGMENT_LIMITS.max_value_members + 1)]

    # Act
    compiled = compile_segment(
        _one("wizard_step", SegmentOp.IN, members), now=NOW, capabilities=ALL_CAPABILITIES
    )

    # Assert
    assert is_err(compiled)
    assert str(SEGMENT_LIMITS.max_value_members) in str(compiled.error)


def test_more_aggregate_rules_than_the_cap_is_refused() -> None:
    """Each one is a correlated scan the planner pays for over the whole filtered set."""
    # Arrange — every rule here compiles to a subquery.
    rules = tuple(
        SegmentRule("order_count", SegmentOp.GTE, index)
        for index in range(SEGMENT_LIMITS.max_aggregate_rules + 1)
    )

    # Act
    compiled = compile_segment(
        Segment(root=SegmentGroup(match=MatchMode.ALL, rules=rules)),
        now=NOW,
        capabilities=ALL_CAPABILITIES,
    )

    # Assert
    assert is_err(compiled)
    assert str(SEGMENT_LIMITS.max_aggregate_rules) in str(compiled.error)


def test_direct_column_rules_do_not_count_against_the_aggregate_cap() -> None:
    """Otherwise the cheapest predicates in the registry would ration the expensive ones."""
    # Arrange
    rules = tuple(
        SegmentRule("ui_language", SegmentOp.IN, ["ru"])
        for _ in range(SEGMENT_LIMITS.max_aggregate_rules + 1)
    )

    # Act
    compiled = compile_segment(
        Segment(root=SegmentGroup(match=MatchMode.ALL, rules=rules)),
        now=NOW,
        capabilities=ALL_CAPABILITIES,
    )

    # Assert
    assert is_ok(compiled)
    assert compiled.value.aggregate_rule_count == 0


# ---------------------------------------------------------------------------
# SORTING — the registry is the only vocabulary
# ---------------------------------------------------------------------------
def test_an_unknown_sort_key_is_refused_by_name() -> None:
    # Arrange
    document = Segment(
        root=SegmentGroup(match=MatchMode.ALL, rules=()),
        sort=SortSpec(key="phone_e164", direction="asc"),
    )

    # Act
    compiled = compile_segment(document, now=NOW, capabilities=ALL_CAPABILITIES)

    # Assert
    assert is_err(compiled)
    assert compiled.error.context["parameter"] == "sort"


def test_the_sort_vocabulary_is_derived_from_the_registry() -> None:
    """A second list is how a refused field becomes sortable by accident."""
    # Arrange / Act / Assert
    assert set(SORT_KEYS) == {key for key, spec in FIELDS.items() if spec.sortable}
    assert seg.DEFAULT_SORT.key in SORT_KEYS


@pytest.mark.parametrize("key", sorted(SORT_KEYS))
async def test_every_sortable_expression_is_total_and_never_null(
    sessions: async_sessionmaker[AsyncSession], population: None, key: str
) -> None:
    """No NULLs means no ``NULLS FIRST/LAST`` divergence and a cursor value that always exists.

    Asserted against the database rather than by reading the ``COALESCE``: the accounts with
    no orders, no credits and no top-ups are exactly the rows a missing wrapper would leave
    NULL, and the population has three of them.
    """
    # Arrange
    expression = sort_expression(key)

    # Act
    async with sessions() as session:
        values = (await session.execute(sa.select(UserRow.telegram_user_id, expression))).all()

    # Assert
    assert len(values) == len(EVERYONE)
    assert all(value is not None for _, value in values)


# ---------------------------------------------------------------------------
# Source hygiene — the "cannot be injected into" claim, kept honest
# ---------------------------------------------------------------------------
def test_the_compiler_builds_no_sql_from_text() -> None:
    """No ``text``, no ``column``, no ``literal_column`` — asserted on the syntax tree.

    This is the one property of the module a reader cannot verify by running it: an
    interpolated identifier compiles and runs perfectly until somebody sends the wrong
    string. So the file is parsed and the three constructors that could build SQL out of a
    string are refused outright, the way ``users._SEARCHABLE_COLUMNS`` makes its refusal
    greppable.

    The AST rather than a substring scan, deliberately: this module argues about ``text()``
    in its own prose, and a grep that a docstring can fail is a grep somebody eventually
    silences by editing the docstring.
    """
    # Arrange
    tree = ast.parse(Path(seg.__file__).read_text(encoding="utf-8"))

    # Act — every function actually CALLED in the module, by its final name.
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute | ast.Name)
    }

    # Assert
    assert not called & {"text", "column", "literal_column", "execute", "exec_driver_sql"}
