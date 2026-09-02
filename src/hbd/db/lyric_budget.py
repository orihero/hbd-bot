"""Charging one lyric write against a day, in a single conditional statement.

The shape is the split :mod:`hbd.db.credits` makes and for the same reasons:

* :func:`claim_write` takes an ``AsyncSession`` first, takes ``now`` as a parameter, lets
  exceptions propagate and **never commits** — so a future caller can compose it into a
  transaction it already owns;
* :class:`SqlLyricBudget` is the never-throw facade in the ``SqlKitRepository`` idiom: one
  ``run_guarded`` delegation owning exactly one ``async with self._sessions.begin()``.

**Why the increment is one statement and not a read-then-write.** The claim has to answer
three questions at once — is there a row, is it today's, what is the new count — and a
``SELECT`` followed by an ``UPDATE`` answers them with a window in between where a second
update slips through. ``INSERT … ON CONFLICT DO UPDATE`` with a ``CASE`` over the stored
``day_index`` does all three atomically on both engines, opening the account, rolling the
day over and incrementing in whichever combination the row needs. In the ``SET`` clause a
bare column reference means the row that is already there on Postgres and on SQLite alike
(``excluded`` is the proposed one), which is what makes the ``CASE`` a comparison against
yesterday's stored day rather than against the value being inserted.

The count is then read back rather than returned by ``RETURNING``, matching
``hbd.db.credit_sql.account_state``: a second ``SELECT`` inside the same transaction is
portable across both drivers, and the read is of Core columns rather than the ORM row
because the identity map would hand back the copy from before the Core write.

Two concurrent claims can both read the post-increment value and both be refused on the same
write. That is the conservative direction — the total ever ALLOWED can only be at or under
the ceiling, never over — and in the bot it is close to theoretical anyway: aiogram holds a
per-chat FSM isolation lock for the whole update, so one account's writes are serialised
before they reach here.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import Result
from hbd.db.credit_sql import upsert_statement
from hbd.db.guard import run_guarded
from hbd.db.models.lyric_budget import LyricBudgetRow
from hbd.lyric_budget import (
    DEFAULT_LYRIC_BUDGET_POLICY,
    LyricBudgetPolicy,
    LyricBudgetVerdict,
    day_index_for,
    day_resets_at,
)

__all__ = ["SqlLyricBudget", "claim_write"]


async def claim_write(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    now: datetime,
    policy: LyricBudgetPolicy = DEFAULT_LYRIC_BUDGET_POLICY,
) -> LyricBudgetVerdict:
    """Charge one write against ``telegram_user_id``'s day and report the verdict.

    Charges first and decides afterwards, which is deliberate: a limiter that only counted
    the writes it allowed would let a caller sit exactly on the ceiling indefinitely. The
    consequence is that ``used`` can exceed ``limit``, and every caller that renders a number
    has to know that — which is why the refusal copy names the LIMIT and not the count.
    """
    day = day_index_for(now)
    await session.execute(
        upsert_statement(
            session,
            LyricBudgetRow,
            {"telegram_user_id": telegram_user_id, "day_index": day, "writes": 1},
            index_elements=["telegram_user_id"],
            set_={
                "day_index": day,
                # A bare column here is the STORED row on both dialects, so this reads
                # "same day → one more, a later day → start again at this write".
                "writes": sa.case(
                    (LyricBudgetRow.day_index == day, LyricBudgetRow.writes + 1), else_=1
                ),
                # Set by hand because ``onupdate`` is an UPDATE-statement hook and this is an
                # INSERT; without it a row that is bumped every day would keep the timestamp
                # of the day it was created.
                "updated_at": now,
            },
        )
    )
    used = await _writes_today(session, telegram_user_id)
    return LyricBudgetVerdict(
        is_allowed=used <= policy.writes_per_day,
        used=used,
        limit=policy.writes_per_day,
        resets_at=day_resets_at(day),
    )


async def _writes_today(session: AsyncSession, telegram_user_id: int) -> int:
    """The count this transaction just wrote. Columns, never ``session.get`` — see the module
    docstring: the identity map would answer with the row as it was before the Core write.
    """
    count = await session.scalar(
        sa.select(LyricBudgetRow.writes).where(LyricBudgetRow.telegram_user_id == telegram_user_id)
    )
    return int(count or 0)


class SqlLyricBudget:
    """:class:`hbd.lyric_budget.LyricBudgetStore` over the ``lyric_budgets`` table.

    Owns its transaction, never raises, and is the only thing in the bot process that writes
    this counter. Deliberately NOT a method on ``EntitlementStore``: the bot may not move a
    credit (``hbd.bot.deps.BotDeps.entitlements``), and a second write on that protocol is
    exactly where the rule would erode. A separate seam keeps "every entitlement gate reads"
    literally true while still giving the lyric step something durable to count in.
    """

    __slots__ = ("_policy", "_sessions")

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        policy: LyricBudgetPolicy = DEFAULT_LYRIC_BUDGET_POLICY,
    ) -> None:
        self._sessions = sessions
        self._policy = policy

    @property
    def policy(self) -> LyricBudgetPolicy:
        """The numbers this store was built with. Read by the wiring test, nothing else."""
        return self._policy

    async def claim_lyric_write(
        self, telegram_user_id: int, *, now: datetime
    ) -> Result[LyricBudgetVerdict]:
        """Charge one write. A failure comes back as an ``Err``; the caller decides."""
        return await run_guarded(
            "claim_lyric_write",
            lambda: self._claim(telegram_user_id, now),
            telegram_user_id=telegram_user_id,
        )

    async def _claim(self, telegram_user_id: int, now: datetime) -> LyricBudgetVerdict:
        async with self._sessions.begin() as session:
            return await claim_write(
                session, telegram_user_id=telegram_user_id, now=now, policy=self._policy
            )
