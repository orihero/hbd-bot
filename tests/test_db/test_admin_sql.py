"""The shared query fragments in ``bayram.db.admin.sql``, on their own.

Separate from ``test_admin_queries.py`` on purpose. That file asserts numbers computed by hand
from a seeded fixture and reads as documentation of the *metrics*; these are the pieces every
one of those queries is built out of, and a search predicate that escapes a ``%`` wrongly is a
bug in twenty endpoints at once rather than in the one whose test happens to notice.

Two of the four groups below run against a real (in-memory) SQLite database rather than
against compiled SQL strings, because the thing under test *is* the database's answer:
``ESCAPE`` handling and ``lower()`` folding are dialect behaviour, and a test that asserted on
the rendered SQL would pass with a pattern the engine then interprets differently.

The escaping is asserted at the Python level as well as through the engine. Both halves are
needed: the string assertion pins the one order the replacements may happen in (a backslash
escaped second re-escapes what the first pass wrote), and the engine assertions pin that the
resulting pattern means what it says on the dialect the suite actually runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bayram.contracts import OrderState, is_err, is_ok
from bayram.db.admin.sql import (
    LIKE_ESCAPE_CHAR,
    MAX_SEARCH_CHARS,
    TimeWindow,
    apply_search,
    apply_window,
    escape_like,
    search_clause,
    time_window,
)
from bayram.db.models.order import OrderRow
from bayram.db.models.user import UserRow

NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)
EARLIER: Final[datetime] = NOW - timedelta(days=30)


# ---------------------------------------------------------------------------
# TimeWindow: the lower bound is optional, the upper one is not
# ---------------------------------------------------------------------------
def test_a_window_with_no_lower_bound_is_valid() -> None:
    # Arrange / Act — "everything ever recorded up to Y", which has no instant to name.
    result = time_window(None, NOW)

    # Assert
    assert is_ok(result)
    assert result.value.start is None
    assert result.value.end == NOW


def test_a_window_still_refuses_a_naive_bound_on_either_end() -> None:
    # Arrange — ``UtcDateTime`` would raise inside the driver's bind processor otherwise.
    naive = datetime(2026, 3, 21, 9, 0)

    # Act / Assert
    assert is_err(time_window(naive, NOW))
    assert is_err(time_window(None, naive))


def test_time_window_remains_the_only_owner_of_the_ordering_check() -> None:
    # Arrange / Act
    result = time_window(NOW, EARLIER)

    # Assert — the message the routers' 422 renders, from one place.
    assert is_err(result)
    assert "ends before it starts" in str(result.error)


def test_an_open_lower_bound_skips_the_ordering_check_rather_than_waiving_it() -> None:
    # Arrange — there is nothing to compare ``end`` against, so no comparison is made.
    result = time_window(None, EARLIER)

    # Assert
    assert is_ok(result)


def test_apply_window_emits_no_lower_predicate_when_the_window_is_open_below() -> None:
    # Arrange — an epoch sentinel would be a clause the planner still evaluates and a bound
    # nobody typed. Its absence is asserted on the SQL, because it is invisible in the rows.
    statement = sa.select(UserRow.telegram_user_id)

    # Act
    open_below = str(apply_window(statement, UserRow.created_at, TimeWindow(None, NOW)))
    closed = str(apply_window(statement, UserRow.created_at, TimeWindow(EARLIER, NOW)))

    # Assert
    assert open_below.count("users.created_at") == 1
    assert closed.count("users.created_at") == 2


def test_apply_window_returns_the_statement_untouched_when_there_is_no_window() -> None:
    # Arrange
    statement = sa.select(UserRow.telegram_user_id)

    # Act / Assert
    assert apply_window(statement, UserRow.created_at, None) is statement


# ---------------------------------------------------------------------------
# escape_like: the order of the replacements is the whole test
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100%", "100\\%"),
        ("a_b", "a\\_b"),
        ("c:\\tmp", "c:\\\\tmp"),
        # The backslash must be escaped FIRST. Escaping ``%`` first would produce
        # ``50\\%`` here — a literal backslash followed by anything — instead of ``50\%``.
        ("50\\%", "50\\\\\\%"),
        ("Gʻulom", "Gʻulom"),
    ],
    ids=["percent", "underscore", "backslash", "backslash-then-percent", "nothing-to-escape"],
)
def test_escape_like_neutralises_every_metacharacter_and_nothing_else(
    raw: str, expected: str
) -> None:
    # Arrange / Act / Assert
    assert escape_like(raw) == expected


# ---------------------------------------------------------------------------
# search_clause: "no query" is no filter, never an empty page
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [None, "", "   "], ids=["absent", "empty", "whitespace"])
def test_a_blank_query_is_no_filter_rather_than_a_filter_matching_nothing(
    text: str | None,
) -> None:
    # Arrange — a search box that has not been typed into must not empty the table, the same
    # asymmetry ``apply_in`` documents.
    assert search_clause(text, [OrderRow.correlation_id]) is None


def test_no_columns_is_no_filter() -> None:
    # Arrange — a caller that has nothing to search is asking for everything, not nothing.
    assert search_clause("anything", []) is None


def test_apply_search_returns_the_statement_untouched_when_there_is_no_query() -> None:
    # Arrange
    statement = sa.select(UserRow.telegram_user_id)

    # Act / Assert
    assert apply_search(statement, None, [OrderRow.correlation_id]) is statement


def test_the_pattern_is_capped_so_a_pathological_query_cannot_grow_without_bound() -> None:
    # Arrange — every substring search is a scan; the only cost left to bound is the per-row
    # one, which grows with the pattern. The router's ``max_length`` makes this unreachable
    # over HTTP, so this is the backstop for a caller that never went through it.
    clause = search_clause("x" * (MAX_SEARCH_CHARS * 10), [OrderRow.correlation_id])

    # Assert — ``%`` on each side of at most the cap.
    assert clause is not None
    pattern = next(iter(clause.compile().params.values()))
    assert pattern == "%" + "x" * MAX_SEARCH_CHARS + "%"


def test_the_escape_character_is_stated_rather_than_left_to_the_dialect() -> None:
    # Arrange — SQLite defaults to *no* escape character, so an unstated one would make a
    # literal ``%`` match everything there and only itself on Postgres.
    clause = search_clause("100%", [OrderRow.correlation_id])

    # Assert
    assert clause is not None
    assert f"ESCAPE '{LIKE_ESCAPE_CHAR}'" in str(clause)


# ---------------------------------------------------------------------------
# search_clause, against the engine: what the database actually matches
# ---------------------------------------------------------------------------
@pytest.fixture
async def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The shared in-memory database from ``conftest``, as a session factory."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def seed(session: AsyncSession, *correlations: str) -> None:
    """One order per string, in ``orders.correlation_id``.

    A real free-text column on a real table rather than a scratch one, and specifically the
    column §11.2's ⌘K palette resolves by shape — so what is asserted here is the predicate a
    later agent will point at ``correlation_id`` for real, not a synthetic stand-in.
    """
    user = UserRow(telegram_user_id=1_000, last_seen_at=NOW, created_at=NOW, updated_at=NOW)
    session.add(user)
    await session.flush()
    for text in correlations:
        session.add(
            OrderRow(
                id=uuid4(),
                user_id=user.id,
                telegram_user_id=user.telegram_user_id,
                state=OrderState.DELIVERED,
                correlation_id=text,
                is_paid=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    await session.flush()


async def matches(session: AsyncSession, query: str) -> set[str]:
    """Every ``correlation_id`` the predicate selects. A ``set`` — order is not under test."""
    statement = apply_search(sa.select(OrderRow.correlation_id), query, [OrderRow.correlation_id])
    rows = await session.execute(statement)
    return {str(value) for value in rows.scalars().all()}


async def test_a_percent_in_the_query_matches_a_literal_percent_and_not_everything(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the bug this escaping exists to prevent: without it ``100%`` means "starts
    # with 100" and the operator is shown rows that do not contain what they typed.
    async with sessions.begin() as session:
        await seed(session, "100% done", "1000 done")

        # Act
        found = await matches(session, "100%")

    # Assert
    assert found == {"100% done"}


async def test_an_underscore_in_the_query_is_a_character_and_not_a_wildcard(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as session:
        await seed(session, "a_b", "axb")

        # Act
        found = await matches(session, "a_b")

    # Assert
    assert found == {"a_b"}


async def test_a_backslash_in_the_query_matches_a_literal_backslash(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the escape character itself, which must survive being escaped with itself.
    async with sessions.begin() as session:
        await seed(session, "c:\\tmp", "c:tmp")

        # Act
        found = await matches(session, "\\tmp")

    # Assert
    assert found == {"c:\\tmp"}


async def test_the_match_is_a_substring_and_is_case_insensitive(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — ASCII on purpose: SQLite's ``lower()`` is ASCII-only, so a non-ASCII case
    # assertion here would be testing the test dialect rather than the predicate.
    async with sessions.begin() as session:
        await seed(session, "REQ-9f201-suffix", "unrelated")

        # Act
        found = await matches(session, "9F201")

    # Assert
    assert found == {"REQ-9f201-suffix"}


async def test_several_columns_are_ored_so_a_hit_in_any_one_of_them_counts(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the shape every ``?q=`` will use: one needle, several columns.
    async with sessions.begin() as session:
        await seed(session, "needle-here", "somewhere else")

        # Act — the second column cannot match a text query, so this also asserts that a
        # non-text column in the list does not break the predicate.
        statement = apply_search(
            sa.select(OrderRow.correlation_id),
            "needle",
            [OrderRow.correlation_id, OrderRow.telegram_user_id],
        )
        found = {str(value) for value in (await session.execute(statement)).scalars().all()}

    # Assert
    assert found == {"needle-here"}
