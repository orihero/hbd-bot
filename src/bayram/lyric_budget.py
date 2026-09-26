"""How many lyrics one account may have written for it in a day, and where that is counted.

**The hole this closes.** ``handlers.lyrics.MAX_LYRIC_WRITES`` bounds the writes one *draft*
may bill (``src/bayram/bot/handlers/lyrics.py:80``), and ``handlers.common.reset_to_welcome``
throws the draft away and mints a fresh one — so ``/start`` resets the counter, and anyone
who can send ``/start`` can drive unbounded LLM spend one session at a time. The lyric write
is the first vendor spend in the product AND it sits before every other gate: the render
gate, the credit balance and the in-flight cap all guard the *worker*, which a user who
never presses Confirm never reaches. A hard gate behind an uncapped free tier is exposure
the wrong way round.

**Why this is not ``bayram.ratelimit``.** That module's counters are an in-process dict, which
is the right shape for a tap rate and the wrong one for a day-long money budget: a bot
restart — a deploy, a crash, an OOM kill — hands every account a fresh budget, and a budget
a user can reset by making the bot restart is not a budget. This one is a row, so it
survives the process. It also fails open where the *counter* cannot be read, which is
``bayram.ratelimit``'s rule too and for the same reason; see :class:`LyricBudgetStore`.

**Why this is not the credit ledger either.** ``credit_ledger.delta`` is pinned by
``ck_credit_ledger_delta_matches_kind`` to ``grant > 0 / debit < 0 / consume = 0``, so a
lyric write is not expressible as a row there without a new kind — and putting a non-money
event in the money ledger would break the ``balance == SUM(delta)`` invariant every credits
test asserts. A separate table with its own seam also keeps
``bayram.bot.deps.BotDeps.entitlements`` literally read-only for gates: the bot writes a lyric
counter, never a credit.

**This module is a leaf.** It imports ``bayram.contracts``, ``bayram.errors`` and
``bayram.entitlements`` — itself a leaf — and nothing else. It may never import ``bayram.config``
(see :func:`resolve_lyric_budget_policy`, which reads ``Settings`` defensively exactly as
``bayram.entitlements`` and ``bayram.ratelimit`` do) and never ``bayram.db``.

**The day boundary is midnight UTC**, and it is the allowance window's own arithmetic with
``period_days=1`` rather than a second epoch: reusing
:func:`bayram.entitlements.period_index_for` is what stops two different "which window is it?"
functions from disagreeing about the same instant, and it means the daily budget turns over
on the same boundary the rolling allowance does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from bayram.contracts import Result
from bayram.entitlements import period_index_for, period_start
from bayram.errors import ConfigError

__all__ = [
    # Policy
    "LyricBudgetPolicy",
    "DEFAULT_LYRIC_BUDGET_POLICY",
    "resolve_lyric_budget_policy",
    # Time
    "day_index_for",
    "day_resets_at",
    # Values
    "LyricBudgetVerdict",
    # Seam
    "LyricBudgetStore",
]

#: The rolling-window arithmetic, asked for a window one day long. See the module docstring.
_DAY: Final[int] = 1

#: Lyric writes one account may be billed for per UTC day.
#:
#: Twenty, derived rather than picked. The user settled on three song credits per thirty
#: days (D-A), a song needs at least one lyric write, and ``MAX_LYRIC_WRITES`` already lets
#: one draft spend five — so an honest customer who orders their whole month's allowance in
#: a single sitting AND rerolls every one of those songs to the per-draft ceiling spends
#: fifteen. Twenty leaves that customer a third of that again in headroom and still turns
#: "hold ``/start`` down" from unbounded vendor spend into twenty calls a day.
#:
#: The direction of the error matters: too tight and the bot refuses a paying-intent
#: customer at the one step the wizard cannot skip, which costs a sale to save pennies; too
#: loose and an abuser gets a bounded, observable number of calls instead of an unbounded
#: one. The order of magnitude is what this control is for.
_DEFAULT_WRITES_PER_DAY: Final[int] = 20


@dataclass(frozen=True, slots=True)
class LyricBudgetPolicy:
    """The one number the lyric budget runs on. Immutable, injected, never ambient."""

    writes_per_day: int = _DEFAULT_WRITES_PER_DAY

    def __post_init__(self) -> None:
        """Refuse a budget that cannot be enforced, at wiring time rather than mid-wizard.

        A ceiling below one would refuse every customer their first lyric and therefore the
        whole product, which is a configuration mistake and not a policy anyone means.
        Mirrors :meth:`bayram.entitlements.EntitlementPolicy.__post_init__` and
        :meth:`bayram.ratelimit.InboundPolicy.__post_init__` so this codebase has one idiom for
        "a policy validates itself", not three.
        """
        if self.writes_per_day < 1:
            raise ConfigError(
                "a lyric budget must allow at least one write a day",
                context={"writes_per_day": self.writes_per_day},
            )


DEFAULT_LYRIC_BUDGET_POLICY: Final[LyricBudgetPolicy] = LyricBudgetPolicy()


def resolve_lyric_budget_policy(settings: object | None = None) -> LyricBudgetPolicy:
    """Build the policy this deployment runs on, reading ``Settings`` defensively.

    ``object`` rather than ``Settings``, and ``getattr`` rather than attribute access, for the
    reason the module docstring gives: importing ``bayram.config`` would give this leaf the one
    edge it has none of. The third instance of an idiom this repo already runs twice
    (``bayram.entitlements.resolve_entitlement_policy``,
    ``bayram.ratelimit.resolve_inbound_policy``).
    """
    if settings is None:
        return DEFAULT_LYRIC_BUDGET_POLICY
    value = getattr(settings, "lyric_writes_per_day", None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return DEFAULT_LYRIC_BUDGET_POLICY
    return LyricBudgetPolicy(writes_per_day=value)


def day_index_for(now: datetime) -> int:
    """Which UTC day ``now`` falls in, counted from the same epoch the allowance uses.

    A pure function of an INJECTED clock, which is what makes "the budget opens again
    tomorrow" a test that moves a variable rather than one that sleeps for a day. A naive
    datetime is rejected by the function underneath rather than assumed to be UTC — guessing
    the zone would move the boundary by up to a day and hand out a second budget.
    """
    return period_index_for(now, period_days=_DAY)


def day_resets_at(index: int) -> datetime:
    """The instant the day AFTER ``index`` opens — when a spent budget comes back.

    Exists so a refusal can say *when*, which is the difference between a refusal and a dead
    end. Same rule as ``bayram.entitlements.period_start``, one window along.
    """
    return period_start(index + 1, period_days=_DAY)


@dataclass(frozen=True, slots=True)
class LyricBudgetVerdict:
    """The budget's answer for one requested lyric write.

    ``used`` is reported rather than hidden for the reason
    :class:`bayram.ratelimit.ThrottleVerdict` reports its count: it is the only thing that tells
    an operator whether a refusal was one write over the line or a script hammering the
    writer, and those two want different responses. It can exceed ``limit``, because a
    refused write still counts — see :meth:`LyricBudgetStore.claim_lyric_write`.
    """

    is_allowed: bool
    used: int
    limit: int
    #: Aware UTC. The instant the count goes back to zero; a refusal renders its date.
    resets_at: datetime


@runtime_checkable
class LyricBudgetStore(Protocol):
    """The seam between "may this account be written a lyric?" and where that is counted.

    One method, deliberately: a store that could also *read* the count without spending it
    would grow a caller that checks and then writes, which is the read-then-write race the
    single conditional statement underneath exists to remove.

    Returns a ``Result`` and never raises, like every other protocol in this codebase, so
    the gate at the lyric step needs no ``try``. The persistence implementation is
    ``bayram.db.lyric_budget.SqlLyricBudget``.

    ``runtime_checkable`` verifies member PRESENCE only, never signatures — ``mypy --strict``
    over ``tests`` is what actually catches a fake that has drifted.
    """

    async def claim_lyric_write(
        self, telegram_user_id: int, *, now: datetime
    ) -> Result[LyricBudgetVerdict]:
        """Charge one write against today's budget and say whether it may proceed.

        The count is charged BEFORE the answer is known, so a write that is refused still
        counts. That is what makes the ceiling a ceiling rather than a line a caller can sit
        on forever, and it is the same rule :func:`bayram.ratelimit.check_update_rate` states.

        Rolls over on its own: a claim made on a later day than the stored one resets the
        count to this write rather than needing a sweep to come and clear it.
        """
        ...
