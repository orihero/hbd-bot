"""The entitlement tables refuse a wrong row in SQL, not in a Python pre-flight check.

Every assertion here is a ``pytest.raises(IntegrityError)`` around a real insert rather than
a ``SELECT`` that decides whether the insert would be safe. That distinction is the whole
point of the constraints: a pre-flight read is a race with every other writer, and the
conditional ``UPDATE … WHERE balance >= :cost`` that WU2 builds on top is only trustworthy
if the row underneath it cannot go negative even when a writer forgets the predicate.

The tables carry **no personal data and no retention clock**, deliberately, which is why
they are absent from ``tables_with_personal_data`` in ``test_privacy_constraints.py``:
every column is a Telegram id, a closed enum, an integer or a machine-built key, so there
is no text *about* a person anywhere. An audit trail that deleted itself on the 30/90-day
schedules in ``hbd.db.retention`` could not answer a billing or fraud question about the
period it had just erased — so the ledger outlives those clocks on purpose, and
:func:`test_neither_credit_table_carries_a_retention_clock` pins that decision down rather
than leaving it to be re-litigated by whoever next reads the purge code.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.db.base import ENUM_LENGTH
from hbd.db.enums import CreditEntryKind, CreditReason
from hbd.db.models import Base, CreditAccountRow, CreditLedgerRow
from tests.test_db.test_enum_lengths import _all_declared_str_enums
from tests.test_db.test_migrations import _config

#: A Telegram id well outside the 32-bit range, so a column that quietly became an
#: ``Integer`` on either engine would fail this file rather than production.
_BIG_TELEGRAM_ID: Final[int] = 8_912_345_678_901
_CREDITS_REVISION: Final[str] = "0006"


def _table(name: str) -> sa.Table:
    """The mapped ``Table`` for ``name``.

    Read off ``Base.metadata`` rather than ``Row.__table__`` because the declarative
    attribute is typed as ``FromClause``, which mypy --strict will not let a test reach
    ``.indexes`` or ``.name`` through.
    """
    return Base.metadata.tables[name]


async def _open_account(
    factory: async_sessionmaker[AsyncSession],
    *,
    telegram_user_id: int = _BIG_TELEGRAM_ID,
    balance: int = 0,
) -> None:
    async with factory.begin() as session:
        session.add(
            CreditAccountRow(
                telegram_user_id=telegram_user_id, balance=balance, lifetime_granted=balance
            )
        )


async def _write_entry(
    factory: async_sessionmaker[AsyncSession],
    *,
    kind: CreditEntryKind,
    reason: CreditReason,
    delta: int,
    idempotency_key: str,
    order_id: UUID | None = None,
    generation: int = 0,
) -> None:
    async with factory.begin() as session:
        session.add(
            CreditLedgerRow(
                telegram_user_id=_BIG_TELEGRAM_ID,
                kind=kind,
                reason=reason,
                delta=delta,
                order_id=order_id,
                generation=generation,
                idempotency_key=idempotency_key,
                actor="pipeline",
            )
        )


# ---------------------------------------------------------------------------
# credit_accounts
# ---------------------------------------------------------------------------
async def test_an_account_round_trips_a_telegram_id_too_large_for_a_32_bit_column(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the primary key is Telegram's own id, and Telegram ids have already passed
    # 2**32. A narrowed column would truncate the identity every gate reads.
    await _open_account(sessions, balance=3)

    # Act
    async with sessions() as session:
        stored = await session.get(CreditAccountRow, _BIG_TELEGRAM_ID)

    # Assert
    assert stored is not None
    assert stored.telegram_user_id == _BIG_TELEGRAM_ID
    assert stored.balance == 3
    # Nothing has been minted for a period yet; "opened" and "granted" are different facts.
    assert stored.allowance_period_index is None


async def test_the_natural_primary_key_is_not_renumbered_by_sqlite(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — SQLAlchemy treats an Integer-family primary key as autoincrementing unless
    # told otherwise, which on SQLite makes the column a ROWID alias. If autoincrement=False
    # were dropped, the supplied id would be replaced by a rowid and every later lookup by
    # Telegram id would miss.
    await _open_account(sessions)

    # Act
    async with sessions() as session:
        ids = (await session.scalars(sa.select(CreditAccountRow.telegram_user_id))).all()

    # Assert
    assert list(ids) == [_BIG_TELEGRAM_ID]


async def test_a_negative_balance_is_refused_by_the_database(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act / Assert — the second layer under the conditional UPDATE. A debit that
    # skipped its `balance >= :cost` predicate would otherwise render a free song and leave
    # a negative row that every later read would silently trust.
    with pytest.raises(IntegrityError):
        await _open_account(sessions, balance=-1)


async def test_an_existing_balance_cannot_be_driven_negative_by_an_update(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the realistic shape of the bug: the row was fine when it was created.
    await _open_account(sessions, balance=1)

    # Act / Assert
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            await session.execute(
                sa.update(CreditAccountRow)
                .where(CreditAccountRow.telegram_user_id == _BIG_TELEGRAM_ID)
                .values(balance=CreditAccountRow.balance - 2)
            )


async def test_two_accounts_cannot_share_a_telegram_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a duplicate would make "the balance" ambiguous, and the conditional UPDATE
    # would move whichever row the planner reached first.
    await _open_account(sessions, balance=1)

    # Act / Assert
    with pytest.raises(IntegrityError):
        await _open_account(sessions, balance=5)


# ---------------------------------------------------------------------------
# credit_ledger
# ---------------------------------------------------------------------------
async def test_a_debit_and_a_refund_for_one_order_coexist_at_different_generations(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the shape the whole idempotency scheme rests on: a refunded order returns to
    # net 0 and is charged again at the next generation, so the two debits are distinct rows
    # with distinct keys rather than a duplicate the unique index would reject.
    order_id = uuid4()

    # Act
    await _write_entry(
        sessions,
        kind=CreditEntryKind.DEBIT,
        reason=CreditReason.ORDER_RENDER,
        delta=-1,
        idempotency_key=f"debit:{order_id}:0",
        order_id=order_id,
    )
    await _write_entry(
        sessions,
        kind=CreditEntryKind.REFUND,
        reason=CreditReason.ORDER_FAILED,
        delta=1,
        idempotency_key=f"refund:{order_id}:0",
        order_id=order_id,
    )
    await _write_entry(
        sessions,
        kind=CreditEntryKind.DEBIT,
        reason=CreditReason.ORDER_RENDER,
        delta=-1,
        idempotency_key=f"debit:{order_id}:1",
        order_id=order_id,
        generation=1,
    )

    # Assert — net position, which is what the ALLOW decision reads.
    async with sessions() as session:
        net = await session.scalar(
            sa.select(sa.func.sum(CreditLedgerRow.delta)).where(
                CreditLedgerRow.order_id == order_id
            )
        )
    assert net == -1


async def test_two_entries_cannot_share_an_idempotency_key(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — this index is the only thing that makes two racing writers of the same
    # movement produce one row instead of two, and it is what the on_conflict_do_nothing
    # insert in WU2 conflicts against.
    order_id = uuid4()
    await _write_entry(
        sessions,
        kind=CreditEntryKind.DEBIT,
        reason=CreditReason.ORDER_RENDER,
        delta=-1,
        idempotency_key=f"debit:{order_id}:0",
        order_id=order_id,
    )

    # Act / Assert
    with pytest.raises(IntegrityError):
        await _write_entry(
            sessions,
            kind=CreditEntryKind.DEBIT,
            reason=CreditReason.ORDER_RENDER,
            delta=-1,
            idempotency_key=f"debit:{order_id}:0",
            order_id=order_id,
        )


async def test_a_debit_with_a_positive_delta_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act / Assert — a debit that added credits would mint them, and it is exactly
    # the sign error a reviewer does not reliably catch in a diff.
    with pytest.raises(IntegrityError):
        await _write_entry(
            sessions,
            kind=CreditEntryKind.DEBIT,
            reason=CreditReason.ORDER_RENDER,
            delta=1,
            idempotency_key="debit:wrong-sign:0",
        )


async def test_a_grant_with_a_negative_delta_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act / Assert — the mirror image: a grant that burned credits.
    with pytest.raises(IntegrityError):
        await _write_entry(
            sessions,
            kind=CreditEntryKind.GRANT,
            reason=CreditReason.PERIOD_ALLOWANCE,
            delta=-3,
            idempotency_key=f"grant:period:{_BIG_TELEGRAM_ID}:0",
        )


async def test_a_zero_delta_debit_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act / Assert — zero is reserved for CONSUME. A zero debit would occupy an
    # in-flight slot and settle nothing while claiming to have charged.
    with pytest.raises(IntegrityError):
        await _write_entry(
            sessions,
            kind=CreditEntryKind.DEBIT,
            reason=CreditReason.ORDER_RENDER,
            delta=0,
            idempotency_key="debit:zero:0",
        )


async def test_a_consume_that_moves_the_balance_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act / Assert — a non-zero CONSUME would desynchronise
    # credit_accounts.balance from SUM(delta) with no other symptom until the WU2 invariant
    # test noticed, which is precisely the drift the two-representation design accepts only
    # because the database refuses this row.
    with pytest.raises(IntegrityError):
        await _write_entry(
            sessions,
            kind=CreditEntryKind.CONSUME,
            reason=CreditReason.ORDER_DELIVERED,
            delta=1,
            idempotency_key="consume:moving:0",
        )


async def test_a_consume_settles_a_debit_without_moving_the_balance(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the positive half: the settlement marker the in-flight count reads.
    order_id = uuid4()
    await _write_entry(
        sessions,
        kind=CreditEntryKind.DEBIT,
        reason=CreditReason.ORDER_RENDER,
        delta=-1,
        idempotency_key=f"debit:{order_id}:0",
        order_id=order_id,
    )

    # Act
    await _write_entry(
        sessions,
        kind=CreditEntryKind.CONSUME,
        reason=CreditReason.ORDER_DELIVERED,
        delta=0,
        idempotency_key=f"consume:{order_id}:0",
        order_id=order_id,
    )

    # Assert — the order stays paid for; the marker adds a row, not a movement.
    async with sessions() as session:
        net = await session.scalar(
            sa.select(sa.func.sum(CreditLedgerRow.delta)).where(
                CreditLedgerRow.order_id == order_id
            )
        )
        kinds = (
            await session.scalars(
                sa.select(CreditLedgerRow.kind).where(CreditLedgerRow.order_id == order_id)
            )
        ).all()
    assert net == -1
    assert set(kinds) == {CreditEntryKind.DEBIT, CreditEntryKind.CONSUME}


async def test_an_allowance_entry_needs_no_order(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act — a period allowance belongs to a person and to a window, not to an
    # order, which is why order_id is nullable and carries no foreign key.
    await _write_entry(
        sessions,
        kind=CreditEntryKind.GRANT,
        reason=CreditReason.PERIOD_ALLOWANCE,
        delta=3,
        idempotency_key=f"grant:period:{_BIG_TELEGRAM_ID}:0",
    )

    # Assert
    async with sessions() as session:
        stored = (await session.scalars(sa.select(CreditLedgerRow))).one()
    assert stored.order_id is None
    assert stored.delta == 3


async def test_a_ledger_entry_may_reference_an_order_that_does_not_exist(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act — deliberately no foreign key: the gate can charge before the orders row
    # is written, and a ledger entry must outlive the order it refers to (the same reasoning
    # docs/ADMIN_PANEL_PLAN.md §5.8 gives for payments.order_id).
    order_id = uuid4()
    await _write_entry(
        sessions,
        kind=CreditEntryKind.DEBIT,
        reason=CreditReason.ORDER_RENDER,
        delta=-1,
        idempotency_key=f"debit:{order_id}:0",
        order_id=order_id,
    )

    # Assert
    async with sessions() as session:
        stored = (await session.scalars(sa.select(CreditLedgerRow))).one()
    assert stored.order_id == order_id


# ---------------------------------------------------------------------------
# Schema-level guarantees the behavioural tests above rely on
# ---------------------------------------------------------------------------
def test_the_named_indexes_exist_exactly_as_the_writers_expect() -> None:
    # Arrange — WU2's on_conflict_do_nothing names the idempotency index, and the operator
    # history read depends on the composite. A renamed index breaks both silently.
    ledger_indexes = {str(index.name): index for index in _table("credit_ledger").indexes}

    # Act
    composite = ledger_indexes["ix_credit_ledger_user_created"]
    unique_key = ledger_indexes["ix_credit_ledger_idempotency_key"]

    # Assert
    assert [column.name for column in composite.columns] == ["telegram_user_id", "created_at"]
    assert unique_key.unique is True


def test_neither_credit_table_carries_a_retention_clock() -> None:
    # Arrange — the counterpart of their absence from tables_with_personal_data in
    # test_privacy_constraints.py. Adding an expires_at here would put the audit trail on a
    # schedule that erases the evidence for exactly the period a dispute is about.
    tables = (_table("credit_accounts"), _table("credit_ledger"))

    # Act
    clocks = [
        f"{table.name}.{column.name}"
        for table in tables
        for column in table.columns
        if column.name.endswith(("expires_at", "purged_at"))
    ]

    # Assert
    assert clocks == []


def test_no_credit_column_holds_free_text_about_a_person() -> None:
    # Arrange — the reason the two tables hold no personal data is structural, not a
    # promise: every string column is a machine-built key or a closed actor label. A new
    # free-text column would make this file the place that says so out loud.
    string_columns = {
        f"{table.name}.{column.name}"
        for table in (_table("credit_accounts"), _table("credit_ledger"))
        for column in table.columns
        if isinstance(column.type, sa.String) and not isinstance(column.type, sa.Enum)
    }

    # Assert
    assert string_columns == {"credit_ledger.idempotency_key", "credit_ledger.actor"}


def test_both_credit_enums_are_picked_up_by_the_enum_width_sweep() -> None:
    # Arrange — test_enum_lengths.py collects StrEnums *declared in* hbd.db.enums, so a
    # member added here is checked against ENUM_LENGTH before Postgres rejects the insert
    # that SQLite would have accepted. This asserts the pickup rather than assuming it.
    covered = {enum_cls.__name__ for enum_cls in _all_declared_str_enums()}

    # Act
    longest = max(
        (member.value for member in (*CreditEntryKind, *CreditReason)),
        key=len,
    )

    # Assert
    assert {"CreditEntryKind", "CreditReason"} <= covered
    assert len(longest) <= ENUM_LENGTH


def test_the_credits_revision_is_reachable_from_head() -> None:
    # Arrange — walk_revisions starts at head, so membership proves the chain resolves and
    # that nobody else has claimed 0006 on this branch.
    script = ScriptDirectory.from_config(_config())

    # Act
    revisions = {revision.revision for revision in script.walk_revisions()}

    # Assert — reachability, not headship. The admin-panel revisions build ON TOP of this
    # one, so pinning the head here would turn every later migration into a failure in the
    # credits suite; ``test_migrations.py`` is where "exactly one head exists" is asserted.
    assert _CREDITS_REVISION in revisions
    assert len(script.get_heads()) == 1


def test_both_tables_are_registered_on_the_shared_metadata() -> None:
    # Arrange / Act — a model missing from db/models/__init__.py is a table create_all never
    # builds and Alembic autogenerate never sees, which would make every test above fail for
    # a reason that has nothing to do with the constraints under test.
    assert {"credit_accounts", "credit_ledger"} <= set(Base.metadata.tables)
