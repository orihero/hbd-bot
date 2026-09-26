"""``bayram.db.admin.credits`` — the account read, the ledger page, and the two absences.

The assertions that carry this file are the ones about **absence**, because every other
behaviour here is shared with the list endpoints and already asserted for them:

* **No account row is ``None``, never a zeroed object.** ``credit_sql.account_state`` answers
  ``(0, None)`` for a missing row, which is byte-identical to a live account that has spent
  everything, and the two mean opposite things to an operator looking at a refused customer.
  :func:`test_an_account_that_was_never_opened_is_none_rather_than_a_zeroed_row` is what stops
  a future simplification onto that primitive.
* **An erased ledger row belongs to nobody.** ``/forget`` nulls ``credit_ledger.telegram_user_id``
  and keeps the row, so those movements must appear on no account's page — including on a page
  fetched for the id that used to own them.

Rows are seeded by hand rather than through ``SqlCreditLedger``, for the reason every other
seed in this package is: the writer reads a clock and decides ``created_at`` itself, and the
ordering assertions here need three rows at three known, distinct instants.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import is_ok
from bayram.db.admin import credits
from bayram.db.admin.page import PageRequest, decode_cursor
from bayram.db.enums import CreditEntryKind, CreditReason
from bayram.db.models.credit_account import CreditAccountRow
from bayram.db.models.credit_ledger import CreditLedgerRow

_TELEGRAM_ID: Final[int] = 88_000_222
_OTHER_ID: Final[int] = 88_000_333
_DAY_ONE: Final[datetime] = datetime(2026, 3, 20, 9, 0, tzinfo=UTC)


async def seed_account(session: AsyncSession, **kw: Any) -> CreditAccountRow:
    row = CreditAccountRow(
        telegram_user_id=kw.pop("telegram_user_id", _TELEGRAM_ID),
        balance=kw.pop("balance", 2),
        lifetime_granted=kw.pop("lifetime_granted", 5),
        allowance_period_index=kw.pop("allowance_period_index", 7),
        created_at=_DAY_ONE,
        updated_at=_DAY_ONE,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_entry(session: AsyncSession, *, created_at: datetime, **kw: Any) -> CreditLedgerRow:
    """One ledger row. ``idempotency_key`` defaults to a unique value, because it is unique."""
    row = CreditLedgerRow(
        id=kw.pop("id", uuid4()),
        telegram_user_id=kw.pop("telegram_user_id", _TELEGRAM_ID),
        kind=kw.pop("kind", CreditEntryKind.GRANT),
        reason=kw.pop("reason", CreditReason.ADMIN_GRANT),
        delta=kw.pop("delta", 1),
        order_id=kw.pop("order_id", None),
        generation=kw.pop("generation", 0),
        idempotency_key=kw.pop("idempotency_key", f"grant:admin:{uuid4()}"),
        actor=kw.pop("actor", "admin:owner"),
        created_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# The account
# ---------------------------------------------------------------------------
async def test_the_account_reports_the_three_columns_it_stores(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        await seed_account(session, balance=3, lifetime_granted=9, allowance_period_index=4)

    # Act
    async with sessions.begin() as session:
        account = await credits.get_credit_account(session, _TELEGRAM_ID)

    # Assert
    assert account is not None
    assert (account.balance, account.lifetime_granted) == (3, 9)
    assert account.allowance_period_index == 4
    assert account.telegram_user_id == _TELEGRAM_ID


async def test_an_account_that_was_never_opened_is_none_rather_than_a_zeroed_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The distinction ``account_state`` cannot make, and the reason this is not a call to it.

    ``(0, None)`` is what that primitive answers for a missing row AND what it answers for a
    live account that has spent its last credit. An operator reading "0 credits" about
    somebody who has never been metered — and who is therefore still owed a whole rolling
    allowance — has been told the opposite of the truth.
    """
    # Arrange — one account exists, so a passing ``None`` cannot come from an empty table.
    async with sessions.begin() as session:
        await seed_account(session, telegram_user_id=_OTHER_ID)

    # Act
    async with sessions.begin() as session:
        missing = await credits.get_credit_account(session, _TELEGRAM_ID)
        spent = await credits.get_credit_account(session, _OTHER_ID)

    # Assert
    assert missing is None
    assert spent is not None


async def test_an_account_that_never_had_an_allowance_reports_a_null_period(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — ``allowance_period_index`` is nullable until the first allowance lands, which
    # is how "opened but never granted" stays distinguishable from "granted in period 0".
    async with sessions.begin() as session:
        await seed_account(session, allowance_period_index=None)

    # Act
    async with sessions.begin() as session:
        account = await credits.get_credit_account(session, _TELEGRAM_ID)

    # Assert
    assert account is not None
    assert account.allowance_period_index is None


# ---------------------------------------------------------------------------
# The ledger page
# ---------------------------------------------------------------------------
async def test_the_ledger_lists_this_accounts_movements_newest_first(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three movements at three instants, plus one belonging to somebody else.
    async with sessions.begin() as session:
        await seed_entry(session, created_at=_DAY_ONE, idempotency_key="first")
        await seed_entry(
            session,
            created_at=_DAY_ONE + timedelta(hours=1),
            kind=CreditEntryKind.DEBIT,
            reason=CreditReason.ORDER_RENDER,
            delta=-1,
            order_id=UUID(int=9),
            generation=1,
            idempotency_key="second",
            actor="pipeline",
        )
        await seed_entry(session, created_at=_DAY_ONE + timedelta(hours=2), idempotency_key="third")
        await seed_entry(
            session, created_at=_DAY_ONE, telegram_user_id=_OTHER_ID, idempotency_key="other"
        )

    # Act
    async with sessions.begin() as session:
        page = await credits.list_credit_entries(
            session, telegram_user_id=_TELEGRAM_ID, request=PageRequest(limit=10)
        )
        total = await credits.count_credit_entries(session, telegram_user_id=_TELEGRAM_ID)

    # Assert — this account's rows, nobody else's, newest first, with every column projected.
    assert [item.idempotency_key for item in page.items] == ["third", "second", "first"]
    assert page.next_cursor is None
    assert (total.total, total.is_exact) == (3, True)
    debit = page.items[1]
    assert (debit.kind, debit.reason, debit.delta) == (
        CreditEntryKind.DEBIT,
        CreditReason.ORDER_RENDER,
        -1,
    )
    assert (debit.order_id, debit.generation, debit.actor) == (UUID(int=9), 1, "pipeline")


async def test_a_full_page_hands_back_a_cursor_that_fetches_the_rest(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The keyset, on the index that exists: ``(telegram_user_id, created_at)`` plus the id.

    The two rows sharing ``_DAY_ONE`` are the case the ``id`` tie-break is for — every write
    in one transaction stamps the same instant, so this is the ordinary shape of a grant and
    the debit that follows it, not a contrived collision.
    """
    # Arrange — four rows, two of them at the same instant.
    async with sessions.begin() as session:
        for index in range(2):
            await seed_entry(session, created_at=_DAY_ONE, idempotency_key=f"same-{index}")
        for index in range(2):
            await seed_entry(
                session,
                created_at=_DAY_ONE + timedelta(hours=index + 1),
                idempotency_key=f"later-{index}",
            )

    # Act — two pages of two.
    async with sessions.begin() as session:
        first = await credits.list_credit_entries(
            session, telegram_user_id=_TELEGRAM_ID, request=PageRequest(limit=2)
        )
        assert first.next_cursor is not None
        cursor = decode_cursor(first.next_cursor)
        assert is_ok(cursor)
        second = await credits.list_credit_entries(
            session,
            telegram_user_id=_TELEGRAM_ID,
            request=PageRequest(limit=2, cursor=cursor.value),
        )

    # Assert — four distinct rows across two pages, in one strictly descending order.
    keys = [item.idempotency_key for item in (*first.items, *second.items)]
    assert len(set(keys)) == 4
    assert keys[:2] == ["later-1", "later-0"]
    assert second.next_cursor is None


async def test_an_erased_movement_belongs_to_nobodys_page(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``/forget`` nulls the id and keeps the row; the row must then appear on no account.

    This is the erasure working rather than a query that forgot a branch, and it is asserted
    from the side that would break: fetching the page for the id that used to own the row.
    """
    # Arrange — one live movement and one erased one.
    async with sessions.begin() as session:
        await seed_entry(session, created_at=_DAY_ONE, idempotency_key="live")
        await seed_entry(
            session,
            created_at=_DAY_ONE + timedelta(hours=1),
            telegram_user_id=None,
            idempotency_key="erased",
        )

    # Act
    async with sessions.begin() as session:
        page = await credits.list_credit_entries(
            session, telegram_user_id=_TELEGRAM_ID, request=PageRequest(limit=10)
        )
        total = await credits.count_credit_entries(session, telegram_user_id=_TELEGRAM_ID)

    # Assert — the count agrees with the page it labels, which is the half a stray predicate
    # on only one of the two statements would break.
    assert [item.idempotency_key for item in page.items] == ["live"]
    assert total.total == 1


async def test_an_account_with_no_movements_is_an_empty_page_rather_than_an_error(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — an account can exist with no ledger row only through a manual insert, but the
    # inverse (rows, no account) is what ``/forget`` leaves behind, so neither may raise.
    async with sessions.begin() as session:
        await seed_account(session)

    # Act
    async with sessions.begin() as session:
        page = await credits.list_credit_entries(
            session, telegram_user_id=_TELEGRAM_ID, request=PageRequest(limit=10)
        )

    # Assert
    assert page.items == ()
    assert page.next_cursor is None
