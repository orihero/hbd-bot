"""``python -m bayram.tools.credits`` — the only way an operator can move a credit today.

Two things are worth testing about a sixty-line CLI and they are not the argument parsing.

**It writes through the product's own functions.** Every assertion below reads the database
back through the ordinary tables, so a refactor that made the tool issue its own ``UPDATE``
would still have to produce the ledger row, the balance and the actor that
:class:`~bayram.db.credits.SqlCreditLedger` produces. That is the property that keeps
``verify_balances`` clean and keeps a comped credit explainable months later.

**It refuses a typo instead of acting on it.** The id is the only thing in the command that
identifies a person, and the cost of getting it wrong is credits handed to a stranger with
no way to notice. ``argparse``'s ``type=int`` would have accepted ``-1`` (a chat, not a
person) and ``0x10``, so the parsing is done by hand and every refusal is asserted as a
returned exit code — never as an exception a shell would show as a traceback.
"""

from __future__ import annotations

from typing import Final

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import Result, err
from bayram.db.credits import SqlCreditLedger
from bayram.entitlements import CreditBalance, EntitlementPolicy
from bayram.errors import StorageError
from bayram.tools.credits import (
    EXIT_REFUSED,
    Block,
    Grant,
    RefusedError,
    apply,
    main,
    plan,
)
from tests.test_db.conftest import MovableClock

_USER: Final[int] = 8_912_345_678_901
_ACTOR: Final[str] = "admin:dilnoza"


def _ledger(sessions: async_sessionmaker[AsyncSession], clock: MovableClock) -> SqlCreditLedger:
    return SqlCreditLedger(sessions, clock=clock, policy=EntitlementPolicy())


def _grant(*, credits: int = 2, reference: str = "ops-1") -> Grant:
    return Grant(
        telegram_user_id=_USER,
        credits=credits,
        actor=_ACTOR,
        idempotency_key=f"grant:admin:{reference}",
    )


#: Raw SQL, not a mapped row, and that is Rule 15 rather than taste: ``bayram/db/__init__.py``
#: says nothing outside persistence should import a ``*Row``, because a mapped row is an
#: implementation detail with a session attached. Nothing outside ``tests/test_db`` held one
#: before this change and nothing does now — ``tests/test_pipeline/test_render_gate.py``
#: counts its rows the same way for the same reason.
_BALANCE_SQL: Final[str] = "SELECT balance FROM credit_accounts WHERE telegram_user_id = :id"
_ENTRIES_SQL: Final[str] = (
    "SELECT idempotency_key, delta, actor FROM credit_ledger ORDER BY idempotency_key"
)
_IS_BLOCKED_SQL: Final[str] = "SELECT is_blocked FROM users WHERE telegram_user_id = :id"


async def _balance(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(await session.scalar(sa.text(_BALANCE_SQL), {"id": _USER}) or 0)


async def _entries(sessions: async_sessionmaker[AsyncSession]) -> list[tuple[str, int, str | None]]:
    """Every ledger row as ``(idempotency_key, delta, actor)``, oldest key first."""
    async with sessions() as session:
        rows = (await session.execute(sa.text(_ENTRIES_SQL))).all()
        return [(str(row[0]), int(row[1]), row[2]) for row in rows]


async def _is_blocked(sessions: async_sessionmaker[AsyncSession]) -> bool:
    async with sessions() as session:
        return bool(await session.scalar(sa.text(_IS_BLOCKED_SQL), {"id": _USER}))


class _ExplodedStore(SqlCreditLedger):
    """A ledger whose grant comes back as ``Err``. Stands in for a database outage.

    A subclass rather than a hand-written fake so that everything else about it — the
    session factory, the policy, the clock — is the real thing: the point under test is what
    the CLI does with an ``Err``, not what it does with a stub.
    """

    async def grant(
        self, *, telegram_user_id: int, credits: int, idempotency_key: str, actor: str
    ) -> Result[CreditBalance]:
        return err(StorageError("the ledger is unreachable"))


# ---------------------------------------------------------------------------
# grant
# ---------------------------------------------------------------------------
async def test_a_grant_moves_the_balance_and_signs_the_row_with_the_operator(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The whole reason this exists rather than an ``UPDATE``: the row that explains it."""
    # Arrange
    ledger = _ledger(sessions, clock)

    # Act
    printed = await apply(ledger, _grant(credits=2))

    # Assert
    assert await _balance(sessions) == 2
    assert await _entries(sessions) == [("grant:admin:ops-1", 2, _ACTOR)]
    assert "grant:admin:ops-1" in printed, "the reference has to be printed to be reusable"


async def test_the_same_reference_twice_tops_the_account_up_once(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The shape of a real operator's day: a command that may or may not have landed.

    A run that timed out between the statement and the terminal is repeated verbatim, and
    the second run must be a no-op that still prints the same balance — which is how the
    operator tells "already applied" from "did not happen".
    """
    # Arrange
    ledger = _ledger(sessions, clock)
    first = await apply(ledger, _grant(credits=2, reference="ops-7"))

    # Act
    second = await apply(ledger, _grant(credits=2, reference="ops-7"))

    # Assert
    assert await _balance(sessions) == 2
    assert len(await _entries(sessions)) == 1
    assert first == second


async def test_two_different_references_are_two_different_grants(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Idempotency must not become "an operator can only ever comp an account once"."""
    # Arrange
    ledger = _ledger(sessions, clock)
    await apply(ledger, _grant(credits=1, reference="ops-a"))

    # Act
    await apply(ledger, _grant(credits=1, reference="ops-b"))

    # Assert
    assert await _balance(sessions) == 2
    assert len(await _entries(sessions)) == 2


async def test_a_store_that_fails_is_one_refusal_line_and_never_a_traceback(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A traceback out of this command would print the DSN. It raises the refusal instead."""
    # Arrange
    store = _ExplodedStore(sessions, clock=clock, policy=EntitlementPolicy())

    # Act / Assert
    with pytest.raises(RefusedError):
        await apply(store, _grant())


# ---------------------------------------------------------------------------
# block
# ---------------------------------------------------------------------------
async def test_blocking_an_account_the_bot_has_never_written_a_row_for(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The accounts most worth blocking are exactly the ones with no ``users`` row.

    ``repository._ensure_user`` only runs when an order is created, so somebody abusing the
    wizard without ever confirming has never been written down. ``set_blocked`` upserts, and
    this is the test that would fail the day it became a rowcount-checked ``UPDATE``.
    """
    # Arrange
    ledger = _ledger(sessions, clock)

    # Act
    printed = await apply(ledger, Block(telegram_user_id=_USER, actor=_ACTOR, is_blocked=True))

    # Assert
    assert await _is_blocked(sessions) is True
    assert _ACTOR in printed, "the actor has nowhere in the schema to go, so it is reported"


async def test_unblocking_lifts_the_bar_without_touching_anything_else(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)
    await apply(ledger, Block(telegram_user_id=_USER, actor=_ACTOR, is_blocked=True))

    # Act
    await apply(ledger, Block(telegram_user_id=_USER, actor=_ACTOR, is_blocked=False))

    # Assert
    assert await _is_blocked(sessions) is False
    assert await _entries(sessions) == [], "a block is not a credit movement"


# ---------------------------------------------------------------------------
# What a command line asks for
# ---------------------------------------------------------------------------
def test_a_grant_without_a_reference_mints_a_fresh_one_every_time() -> None:
    """The default has to be safe for a FIRST run and unsafe to repeat blindly.

    A stable default key would make every un-referenced grant the same grant — the second
    operator to comp a customer would silently add nothing — so an omitted ``--reference``
    mints a new one, and :func:`_grant` prints it so a deliberate retry is still possible.
    """
    # Arrange
    argv = ["grant", "--telegram-user-id", str(_USER), "--actor", "dilnoza", "--credits", "1"]

    # Act
    first, second = plan(argv), plan(argv)

    # Assert
    assert isinstance(first, Grant) and isinstance(second, Grant)
    assert first.idempotency_key.startswith("grant:admin:")
    assert first.idempotency_key != second.idempotency_key


def test_a_supplied_reference_becomes_the_key_verbatim() -> None:
    """The operator's token is the whole idempotency guarantee; it must not be rewritten."""
    # Arrange / Act
    planned = plan(
        [
            "grant",
            "--telegram-user-id",
            str(_USER),
            "--actor",
            "dilnoza",
            "--credits",
            "3",
            "--reference",
            "incident-2026-08-30",
        ]
    )

    # Assert
    assert planned == Grant(
        telegram_user_id=_USER,
        credits=3,
        actor="admin:dilnoza",
        idempotency_key="grant:admin:incident-2026-08-30",
    )


def test_block_and_unblock_are_the_same_verb_with_the_flag_flipped() -> None:
    """One verb, so an operator cannot learn to block and never find how to undo it."""
    # Arrange
    argv = ["block", "--telegram-user-id", str(_USER), "--actor", "dilnoza"]

    # Act / Assert
    assert plan(argv) == Block(telegram_user_id=_USER, actor=_ACTOR, is_blocked=True)
    assert plan([*argv, "--unblock"]) == Block(
        telegram_user_id=_USER, actor=_ACTOR, is_blocked=False
    )


# ---------------------------------------------------------------------------
# Refusals — none of these ever opens a database connection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "given",
    [
        "abc",
        "-1",  # a negative id is a CHAT, not a person
        "0",
        "12.5",
        "",
        " 12 34",
        "0x10",
        str(2**63),  # one past what the column can hold
    ],
)
def test_a_malformed_telegram_user_id_is_refused_before_anything_is_opened(
    given: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Granting credits to the wrong account is a real cost with no way to notice it."""
    # Arrange / Act
    code = main(["grant", "--telegram-user-id", given, "--actor", "dilnoza", "--credits", "1"])

    # Assert
    assert code == EXIT_REFUSED
    assert "--telegram-user-id" in capsys.readouterr().out


@pytest.mark.parametrize("given", ["0", "-2", "abc", ""])
def test_a_grant_of_nothing_is_refused_with_a_sentence_not_a_constraint_name(
    given: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange / Act
    code = main(
        ["grant", "--telegram-user-id", str(_USER), "--actor", "dilnoza", "--credits", given]
    )

    # Assert
    assert code == EXIT_REFUSED
    assert "--credits" in capsys.readouterr().out


@pytest.mark.parametrize("given", ["", "   ", "d" * 27])
def test_an_actor_that_would_be_stored_cut_in_half_is_refused(
    given: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """An attribution an operator believes is recorded and is not is worse than none."""
    # Arrange / Act
    code = main(["block", "--telegram-user-id", str(_USER), "--actor", given])

    # Assert
    assert code == EXIT_REFUSED
    assert "--actor" in capsys.readouterr().out


@pytest.mark.parametrize("given", ["grant:period:1:2", "with space", "a" * 65, ""])
def test_a_reference_that_could_collide_with_an_allowance_key_is_refused(
    given: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """``grant:period:{id}:{index}`` is the key an allowance has not been minted under yet.

    A reference free to contain a colon could take that key first, and the mint would then
    read its own idempotency guard as "already granted" and silently skip a customer's
    allowance forever.
    """
    # Arrange / Act
    code = main(
        [
            "grant",
            "--telegram-user-id",
            str(_USER),
            "--actor",
            "dilnoza",
            "--credits",
            "1",
            "--reference",
            given,
        ]
    )

    # Assert
    assert code == EXIT_REFUSED
    assert "--reference" in capsys.readouterr().out
