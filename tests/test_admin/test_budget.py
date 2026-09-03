"""The reveal budget, and the first route in this codebase that actually enforces a step-up.

Two halves, and each exists because the obvious implementation of it is wrong.

**The budget is counted in records** (§12.3). Phase 1 shipped
``admin_reveal_records_per_hour`` and ``admin_reveal_conversations_per_day`` as settings
nothing read. A budget that charges one unit per *request* compiles, passes every test that
only counts refusals, and silently reverts the control to the design the plan's review
rejected: at 200 requests an hour, 200 whole transcripts an hour, ~4,800 a day, all inside
policy and all logged as 200 rows. So the unit tests here charge fifty units in one call and
then require the counter to read fifty, not one.

**Two concurrent reveals must not both pass.** ``charge_reveal_budget`` performs exactly one
store operation per counter — ``INCRBY`` returns the post-charge total — so the check and
the charge are the same operation. :func:`test_two_concurrent_reveals_cannot_both_pass_the_
ceiling` interleaves two charges at the only await point there is and requires exactly one
allowed; a check-then-increment implementation passes both, which is why the counterfactual
is stated in that test rather than left implied.

**And the step-up has to work through a real route.** ``require_step_up`` and
``check_step_up`` were unit-tested in Phase 1 with **zero handler callers** anywhere in
``src/hbd``: ``POST /api/auth/step-up`` wrote ``admin_sessions.step_up_scope`` and no route
ever read the column back. The tests in the last section drive the real step-up route to get
a real grant and then call a real handler, because that is the only shape that catches the
two failures a hand-built ``StepUpGrant`` cannot: an action spelled as a ``Permission``
value rather than a :class:`StepUpAction` (``reveal.personal_data`` builds a perfectly
storable scope that the issued ``reveal:<id>`` grant never matches), and a subject id
stringified differently on the two sides of a whole-string comparison.

The probe router here is deliberately **not** guarded at the router by an ``A+S`` permission.
``deps.RequirePermission`` calls ``check_role``, which answers ``STEP_UP_REQUIRED`` for any
cell carrying a step-up without ever consulting the session's grant — so a reveal route
guarded at the router by ``REVEAL_PERSONAL_DATA`` would refuse a correctly stepped-up
operator forever. The two guards are layered instead: the router decides the **role** with a
no-step-up cell, and the handler decides the **scope**. That is the pattern this module
pins.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
import pytest
import sqlalchemy as sa
from fastapi import APIRouter, Depends

from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer
from hbd.admin.deps import (
    Admin,
    Container,
    enforce_reveal_budget,
    enforce_step_up,
    require_permission,
    reveal_budget_limits,
)
from hbd.admin.errors import AdminErrorCode
from hbd.admin.security.budget import (
    DEFAULT_MAX_CONVERSATIONS_PER_DAY,
    DEFAULT_MAX_RECORDS_PER_HOUR,
    MAX_RECORDS_PER_REVEAL,
    REVEAL_CONVERSATIONS_WINDOW_S,
    REVEAL_RECORDS_WINDOW_S,
    RevealBudgetLimits,
    RevealBudgetOutcome,
    RevealBudgetScope,
    charge_reveal_budget,
    reveal_budget_key,
)
from hbd.admin.security.permissions import Permission, StepUpAction
from hbd.db.base import utc_now
from hbd.errors import ErrorCode
from tests.test_admin.conftest import (
    ORIGIN,
    PASSWORD,
    USERNAME,
    FakeRedis,
    create_account,
    csrf_headers,
    make_settings,
    open_container,
    sign_in,
)

#: A fixed instant, so a test that asserts on a window index is not a race. Chosen mid-hour
#: and mid-day so ``retry_after_s`` is neither the whole window nor almost nothing.
NOW: Final[datetime] = datetime(2026, 3, 21, 9, 30, 0, tzinfo=UTC)
#: The scheme a ``__Host-`` (and therefore ``Secure``) cookie is replayed to; the ``Origin``
#: header the client sends stays :data:`ORIGIN`, which is what the server compares.
COOKIE_ORIGIN: Final[str] = ORIGIN.replace("http://", "https://", 1)

_ACTOR: Final[str] = "reveal-operator"
_SUBJECT_A: Final[str] = "0f9a3b1c-1111-4222-8333-444455556666"
_SUBJECT_B: Final[str] = "0f9a3b1c-9999-4222-8333-444455556666"
_PROBE_PATH: Final[str] = "/api/test-probe/reveal/{subject_id}"
_BUDGET_LOGGER: Final[str] = "hbd.admin.security.budget"
_TIGHT: Final[RevealBudgetLimits] = RevealBudgetLimits(
    max_records_per_hour=10, max_conversations_per_day=2
)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
class _MemoryStore:
    """A :class:`WindowCounterStore` that records every operation it was asked to perform.

    ``operations`` is the atomicity assertion: an implementation that read the counter and
    then wrote it would leave two entries per charge, and the whole design rests on there
    being one.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.operations: list[tuple[str, int]] = []

    async def increment(self, key: str, *, ttl_s: int) -> int:
        return await self.increment_by(key, 1, ttl_s=ttl_s)

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        self.operations.append((key, amount))
        self.counts[key] = self.counts.get(key, 0) + amount
        self.ttls[key] = ttl_s
        return self.counts[key]

    async def refund(self, key: str, *, ttl_s: int) -> None:
        await self.increment_by(key, -1, ttl_s=ttl_s)


class _InterleavingStore(_MemoryStore):
    """Atomic per call, but yields to the event loop *before* every charge.

    That is what makes the race reproducible without threads: two coroutines both enter
    ``increment_by``, both suspend, and then apply their charge one after the other. A
    check-then-increment budget reads the counter before its own charge lands and lets both
    through; a charge-then-compare one cannot, because the value it compares is the value its
    own charge produced.
    """

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        await asyncio.sleep(0)
        return await super().increment_by(key, amount, ttl_s=ttl_s)


class _BrokenStore:
    """Redis is down. Every call raises, which is what the fail-closed path must survive."""

    async def increment(self, key: str, *, ttl_s: int) -> int:
        raise ConnectionError("the budget store is unavailable")

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        raise ConnectionError("the budget store is unavailable")

    async def refund(self, key: str, *, ttl_s: int) -> None:
        raise ConnectionError("the budget store is unavailable")


class _SwitchableStore(_MemoryStore):
    """Works until ``is_down`` is set. The only way to reach the budget's outage path from
    a signed-in session: signing in and stepping up both need a working counter store."""

    def __init__(self) -> None:
        super().__init__()
        self.is_down = False

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        if self.is_down:
            raise ConnectionError("the budget store is unavailable")
        return await super().increment_by(key, amount, ttl_s=ttl_s)


class _ReleaseBrokenStore(_MemoryStore):
    """Charges fine, cannot give anything back. The half-outage the release has to survive."""

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        if amount < 0:
            raise ConnectionError("the budget store is unavailable")
        return await super().increment_by(key, amount, ttl_s=ttl_s)


# ---------------------------------------------------------------------------
# The unit: records, not requests
# ---------------------------------------------------------------------------
async def test_one_reveal_of_fifty_bodies_charges_fifty_units_not_one() -> None:
    """The correction §12.3 says the review forced, asserted as arithmetic."""
    # Arrange
    store = _MemoryStore()

    # Act
    decision = await charge_reveal_budget(
        store, username=_ACTOR, record_count=50, conversation_count=1, now=NOW
    )

    # Assert
    key = reveal_budget_key(RevealBudgetScope.RECORDS, username=_ACTOR, now=NOW)
    assert decision.is_allowed is True
    assert decision.records_charged == 50
    assert store.counts[key] == 50
    assert decision.records_remaining == DEFAULT_MAX_RECORDS_PER_HOUR - 50


async def test_four_fifty_record_reveals_exhaust_a_two_hundred_record_hour() -> None:
    """Four requests, not two hundred: the ceiling counts what was exposed."""
    # Arrange
    store = _MemoryStore()

    # Act
    outcomes = [
        (
            await charge_reveal_budget(
                store, username=_ACTOR, record_count=MAX_RECORDS_PER_REVEAL, now=NOW
            )
        ).is_allowed
        for _ in range(5)
    ]

    # Assert
    assert outcomes == [True, True, True, True, False]


async def test_a_charge_of_zero_records_is_refused_rather_than_silently_free() -> None:
    """``record_count=0`` is how a budget quietly stops working while the suite stays green."""
    with pytest.raises(ValueError, match="at least one record"):
        await charge_reveal_budget(_MemoryStore(), username=_ACTOR, record_count=0, now=NOW)


async def test_a_single_charge_larger_than_one_page_is_refused() -> None:
    """§12.3 caps a conversation reveal at fifty bodies; more is a page that was never paged."""
    with pytest.raises(ValueError, match="at most 50 records"):
        await charge_reveal_budget(
            _MemoryStore(), username=_ACTOR, record_count=MAX_RECORDS_PER_REVEAL + 1, now=NOW
        )


async def test_a_negative_conversation_charge_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        await charge_reveal_budget(
            _MemoryStore(), username=_ACTOR, record_count=1, conversation_count=-1, now=NOW
        )


# ---------------------------------------------------------------------------
# Two budgets, exhaustible separately
# ---------------------------------------------------------------------------
async def test_the_daily_conversation_ceiling_trips_while_the_hourly_records_budget_is_fine() -> (
    None
):
    """Twenty one-body transcripts spend the day's transcripts and 20/200 of the hour."""
    # Arrange
    store = _MemoryStore()

    async def transcript() -> bool:
        decision = await charge_reveal_budget(
            store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW
        )
        return decision.is_allowed

    for _ in range(DEFAULT_MAX_CONVERSATIONS_PER_DAY):
        assert await transcript() is True

    # Act
    refused = await charge_reveal_budget(
        store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW
    )
    name_reveal = await charge_reveal_budget(store, username=_ACTOR, record_count=1, now=NOW)

    # Assert - the transcript budget is spent, the record budget is not
    assert refused.is_allowed is False
    assert refused.scope is RevealBudgetScope.CONVERSATIONS
    assert name_reveal.is_allowed is True
    records_key = reveal_budget_key(RevealBudgetScope.RECORDS, username=_ACTOR, now=NOW)
    assert store.counts[records_key] == DEFAULT_MAX_CONVERSATIONS_PER_DAY + 1


async def test_the_hourly_record_ceiling_trips_while_the_daily_conversation_budget_is_fine() -> (
    None
):
    """Four fifty-body pages spend the hour; the day has sixteen transcripts left."""
    # Arrange
    store = _MemoryStore()
    for _ in range(4):
        allowed = await charge_reveal_budget(
            store, username=_ACTOR, record_count=50, conversation_count=1, now=NOW
        )
        assert allowed.is_allowed is True

    # Act
    refused = await charge_reveal_budget(
        store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW
    )

    # Assert
    assert refused.is_allowed is False
    assert refused.scope is RevealBudgetScope.RECORDS
    assert refused.conversations_remaining == DEFAULT_MAX_CONVERSATIONS_PER_DAY - 4


async def test_the_two_budgets_never_share_a_key() -> None:
    """Separately exhaustible means separately keyed; one namespace is one budget."""
    # Arrange
    store = _MemoryStore()

    # Act
    await charge_reveal_budget(
        store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW
    )

    # Assert
    assert sorted(store.counts) == sorted(
        {
            reveal_budget_key(scope, username=_ACTOR, now=NOW)
            for scope in (RevealBudgetScope.RECORDS, RevealBudgetScope.CONVERSATIONS)
        }
    )


async def test_two_operators_do_not_share_a_budget() -> None:
    # Arrange
    store = _MemoryStore()

    # Act
    for _ in range(DEFAULT_MAX_RECORDS_PER_HOUR // MAX_RECORDS_PER_REVEAL):
        await charge_reveal_budget(store, username=_ACTOR, record_count=50, now=NOW)
    other = await charge_reveal_budget(store, username="another-operator", record_count=50, now=NOW)

    # Assert
    assert other.is_allowed is True


def test_the_key_carries_a_digest_of_the_actor_rather_than_the_name() -> None:
    """Redis keys end up in ``KEYS`` dumps and support tickets; a username is personal-ish."""
    key = reveal_budget_key(RevealBudgetScope.RECORDS, username=_ACTOR, now=NOW)

    assert _ACTOR not in key
    assert key.startswith("hbd:admin:budget:records:")
    assert key.split(":")[-2] == str(int(NOW.timestamp()) // REVEAL_RECORDS_WINDOW_S)


def test_the_case_of_a_username_cannot_open_a_second_budget() -> None:
    """Otherwise the ceiling is bypassed by a name the account lookup treats as one account."""
    assert reveal_budget_key(
        RevealBudgetScope.RECORDS, username=_ACTOR, now=NOW
    ) == reveal_budget_key(RevealBudgetScope.RECORDS, username=_ACTOR.upper(), now=NOW)


def test_the_two_windows_are_an_hour_and_a_day() -> None:
    limits = RevealBudgetLimits()

    assert (limits.records_window_s, limits.conversations_window_s) == (3_600, 86_400)
    assert (REVEAL_RECORDS_WINDOW_S, REVEAL_CONVERSATIONS_WINDOW_S) == (3_600, 86_400)
    assert (limits.max_records_per_hour, limits.max_conversations_per_day) == (200, 20)


async def test_a_new_hour_is_a_new_record_budget_but_the_same_day_of_transcripts() -> None:
    """The windows are epoch-aligned and independent; only one of them rolls at 10:00."""
    # Arrange
    store = _MemoryStore()
    for _ in range(4):
        await charge_reveal_budget(
            store, username=_ACTOR, record_count=50, conversation_count=1, now=NOW
        )
    later = NOW + timedelta(hours=1)

    # Act
    decision = await charge_reveal_budget(
        store, username=_ACTOR, record_count=50, conversation_count=1, now=later
    )

    # Assert - fresh hour, same day
    assert decision.is_allowed is True
    assert decision.records_remaining == DEFAULT_MAX_RECORDS_PER_HOUR - 50
    assert decision.conversations_remaining == DEFAULT_MAX_CONVERSATIONS_PER_DAY - 5


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------
async def test_a_charge_is_one_store_operation_per_counter() -> None:
    """The value compared against the ceiling is the value the charge itself produced.

    A check-then-charge implementation needs a read as well, and that read is the race.
    """
    # Arrange
    store = _MemoryStore()

    # Act
    await charge_reveal_budget(
        store, username=_ACTOR, record_count=7, conversation_count=1, now=NOW
    )

    # Assert
    assert [amount for _, amount in store.operations] == [1, 7]


async def test_two_concurrent_reveals_cannot_both_pass_the_ceiling() -> None:
    """Six plus six against a ceiling of ten: exactly one is served, and the loser is refunded.

    Both coroutines are suspended inside the store before either charge lands, which is the
    interleaving a check-then-increment budget loses to — it would read 0, twice, and allow
    both.
    """
    # Arrange
    store = _InterleavingStore()

    # Act
    first, second = await asyncio.gather(
        charge_reveal_budget(store, username=_ACTOR, record_count=6, now=NOW, limits=_TIGHT),
        charge_reveal_budget(store, username=_ACTOR, record_count=6, now=NOW, limits=_TIGHT),
    )

    # Assert
    assert sorted([first.is_allowed, second.is_allowed]) == [False, True]
    key = reveal_budget_key(RevealBudgetScope.RECORDS, username=_ACTOR, now=NOW, limits=_TIGHT)
    assert store.counts[key] == 6


async def test_a_refused_reveal_gives_its_charge_back() -> None:
    """A refused reveal disclosed nothing, so it may not spend the rest of the window.

    This is the one place the budget deliberately parts company with ``ratelimit.py``, where
    a refused attempt keeps its charge.
    """
    # Arrange
    store = _MemoryStore()
    await charge_reveal_budget(store, username=_ACTOR, record_count=9, now=NOW, limits=_TIGHT)
    key = reveal_budget_key(RevealBudgetScope.RECORDS, username=_ACTOR, now=NOW, limits=_TIGHT)

    # Act - a five-record reveal does not fit in the one unit that is left
    refused = await charge_reveal_budget(
        store, username=_ACTOR, record_count=5, now=NOW, limits=_TIGHT
    )
    still_fits = await charge_reveal_budget(
        store, username=_ACTOR, record_count=1, now=NOW, limits=_TIGHT
    )

    # Assert
    assert refused.is_allowed is False
    assert refused.records_charged == 0
    assert refused.records_remaining == 1
    assert still_fits.is_allowed is True
    assert store.counts[key] == 10


async def test_a_refused_conversation_page_does_not_spend_the_record_budget() -> None:
    """The daily ceiling refuses first, so the hourly counter is never touched."""
    # Arrange
    store = _MemoryStore()
    for _ in range(_TIGHT.max_conversations_per_day):
        await charge_reveal_budget(
            store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW, limits=_TIGHT
        )
    records_key = reveal_budget_key(
        RevealBudgetScope.RECORDS, username=_ACTOR, now=NOW, limits=_TIGHT
    )
    before = store.counts[records_key]

    # Act
    refused = await charge_reveal_budget(
        store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW, limits=_TIGHT
    )

    # Assert
    assert refused.is_allowed is False
    assert refused.scope is RevealBudgetScope.CONVERSATIONS
    assert store.counts[records_key] == before


async def test_a_release_that_cannot_be_written_is_logged_rather_than_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A charge that could not be given back is a real cost to the operator; not invisible."""
    # Arrange
    store = _ReleaseBrokenStore()

    # Act
    with caplog.at_level(logging.ERROR, logger=_BUDGET_LOGGER):
        refused = await charge_reveal_budget(
            store, username=_ACTOR, record_count=11, now=NOW, limits=_TIGHT
        )

    # Assert
    assert refused.is_allowed is False
    events = [getattr(record, "event", None) for record in caplog.records]
    assert "admin.reveal.budget_release_failed" in events


# ---------------------------------------------------------------------------
# The refusal: the WARNING and what it names
# ---------------------------------------------------------------------------
async def test_an_exhausted_budget_logs_a_warning_naming_the_actor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """§12.3: the ceiling is a detection control, and detection needs a name to act on."""
    # Arrange
    store = _MemoryStore()
    await charge_reveal_budget(store, username=_ACTOR, record_count=10, now=NOW, limits=_TIGHT)

    # Act
    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        refused = await charge_reveal_budget(
            store, username=_ACTOR, record_count=1, now=NOW, limits=_TIGHT
        )

    # Assert
    assert refused.is_allowed is False
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert getattr(warnings[0], "admin_username", None) == _ACTOR
    assert getattr(warnings[0], "event", None) == "admin.reveal.budget_exhausted"
    assert getattr(warnings[0], "reveal_budget_scope", None) == RevealBudgetScope.RECORDS.value


async def test_the_conversation_ceiling_names_its_own_budget_in_the_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An alert that could not say *which* ceiling tripped is an alert nobody can triage."""
    # Arrange
    store = _MemoryStore()
    for _ in range(_TIGHT.max_conversations_per_day):
        await charge_reveal_budget(
            store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW, limits=_TIGHT
        )

    # Act
    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        await charge_reveal_budget(
            store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW, limits=_TIGHT
        )

    # Assert
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert [getattr(record, "reveal_budget_scope", None) for record in warnings] == [
        RevealBudgetScope.CONVERSATIONS.value
    ]


async def test_retry_after_counts_down_to_the_reset_rather_than_reporting_the_whole_window() -> (
    None
):
    """A daily budget that answered 86400 half an hour before its reset is unactionable."""
    # Arrange
    store = _MemoryStore()
    for _ in range(_TIGHT.max_conversations_per_day):
        await charge_reveal_budget(
            store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW, limits=_TIGHT
        )

    # Act
    refused = await charge_reveal_budget(
        store, username=_ACTOR, record_count=1, conversation_count=1, now=NOW, limits=_TIGHT
    )

    # Assert - NOW is 09:30 UTC, so the UTC day rolls in 14h30m
    assert refused.retry_after_s == int(timedelta(hours=14, minutes=30).total_seconds())


# ---------------------------------------------------------------------------
# Fail closed
# ---------------------------------------------------------------------------
async def test_a_dead_store_refuses_the_reveal_and_says_it_is_an_outage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unbudgeted reveal path is an unbounded one; and an outage is not an exhausted budget."""
    # Act
    with caplog.at_level(logging.ERROR, logger=_BUDGET_LOGGER):
        decision = await charge_reveal_budget(
            _BrokenStore(), username=_ACTOR, record_count=1, now=NOW
        )

    # Assert
    assert decision.is_allowed is False
    assert decision.outcome is RevealBudgetOutcome.BACKEND_UNAVAILABLE
    assert decision.records_remaining is None
    assert [record.levelno for record in caplog.records] == [logging.ERROR]


async def test_a_store_that_dies_on_the_conversation_counter_also_fails_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The daily ceiling is charged first, so it is the first thing an outage can break."""
    # Act
    with caplog.at_level(logging.ERROR, logger=_BUDGET_LOGGER):
        decision = await charge_reveal_budget(
            _BrokenStore(), username=_ACTOR, record_count=1, conversation_count=1, now=NOW
        )

    # Assert
    assert decision.is_allowed is False
    assert decision.outcome is RevealBudgetOutcome.BACKEND_UNAVAILABLE
    assert decision.scope is RevealBudgetScope.CONVERSATIONS
    assert decision.conversations_remaining is None


# ---------------------------------------------------------------------------
# The panel: a probe route that enforces both guards for real
# ---------------------------------------------------------------------------
class _Clock:
    """The handler's ``now``, settable, so a grant can be aged without sleeping."""

    def __init__(self) -> None:
        self.offset_s: int = 0

    def __call__(self) -> datetime:
        return utc_now() + timedelta(seconds=self.offset_s)


def build_probe_router(clock: _Clock) -> APIRouter:
    """One route shaped exactly like a reveal handler, and nothing else.

    The router guard carries ``RECORDS_READ`` — a cell with **no** step-up — precisely
    because ``deps.RequirePermission`` answers ``STEP_UP_REQUIRED`` for any cell that has
    one, holding no subject and therefore no grant. Role at the router, scope in the handler.
    """
    router = APIRouter(dependencies=[Depends(require_permission(Permission.RECORDS_READ))])

    @router.post(_PROBE_PATH)
    async def probe(
        subject_id: str,
        admin: Admin,
        container: Container,
        records: int = 1,
        conversations: int = 0,
    ) -> dict[str, Any]:
        now = clock()
        scope = await enforce_step_up(
            admin, container, action=StepUpAction.REVEAL, subject_id=subject_id, now=now
        )
        decision = await enforce_reveal_budget(
            admin,
            container,
            record_count=records,
            conversation_count=conversations,
            now=now,
        )
        return {"scope": scope, "recordsCharged": decision.records_charged}

    return router


@dataclass(frozen=True, slots=True)
class Panel:
    """One running admin API, its container, the counter store, and the handler's clock."""

    container: AdminContainer
    http: httpx.AsyncClient
    limits: _SwitchableStore
    clock: _Clock


@asynccontextmanager
async def open_panel(**overrides: Any) -> AsyncIterator[Panel]:
    store = _SwitchableStore()
    clock = _Clock()
    async with open_container(make_settings(**overrides), FakeRedis(), store) as container:
        application = create_app(container=container)
        application.include_router(build_probe_router(clock))
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url=COOKIE_ORIGIN) as http:
                yield Panel(container=container, http=http, limits=store, clock=clock)


@pytest.fixture
async def panel() -> AsyncIterator[Panel]:
    async with open_panel(admin_reveal_records_per_hour=10) as running:
        yield running


async def signed_in(panel: Panel) -> None:
    await create_account(panel.container)
    assert (await sign_in(panel.http)).status_code == 200


async def step_up(
    panel: Panel, *, subject: str, scope: str = "reveal", password: str = PASSWORD
) -> httpx.Response:
    """POST /api/auth/step-up the way the SPA does. The only writer of ``step_up_scope``."""
    return await panel.http.post(
        "/api/auth/step-up",
        json={"password": password, "scope": scope, "subjectId": subject},
        headers=csrf_headers(panel.http),
    )


async def reveal(
    panel: Panel, *, subject: str, records: int = 1, conversations: int = 0
) -> httpx.Response:
    return await panel.http.post(
        f"/api/test-probe/reveal/{subject}",
        params={"records": records, "conversations": conversations},
        headers=csrf_headers(panel.http),
    )


# ---------------------------------------------------------------------------
# The step-up, enforced by a real handler against a real grant
# ---------------------------------------------------------------------------
async def test_a_reveal_without_any_step_up_is_refused(panel: Panel) -> None:
    """Phase 1 wrote ``step_up_scope`` and no route read it back. This is the read."""
    # Arrange
    await signed_in(panel)

    # Act
    response = await reveal(panel, subject=_SUBJECT_A)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value


async def test_a_scoped_step_up_admits_the_subject_it_was_taken_for(panel: Panel) -> None:
    # Arrange
    await signed_in(panel)
    assert (await step_up(panel, subject=_SUBJECT_A)).status_code == 200

    # Act
    response = await reveal(panel, subject=_SUBJECT_A)

    # Assert
    assert response.status_code == 200
    assert response.json() == {"scope": f"reveal:{_SUBJECT_A}", "recordsCharged": 1}


async def test_a_step_up_for_one_order_does_not_admit_another(panel: Panel) -> None:
    """The confused deputy the scope exists to stop, asserted through the route."""
    # Arrange
    await signed_in(panel)
    assert (await step_up(panel, subject=_SUBJECT_A)).status_code == 200

    # Act
    response = await reveal(panel, subject=_SUBJECT_B)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value


async def test_a_step_up_for_a_different_action_does_not_admit_a_reveal(panel: Panel) -> None:
    """A grant collected to block a user is not a grant to read their transcript."""
    # Arrange
    await signed_in(panel)
    granted = await step_up(panel, subject=_SUBJECT_A, scope="user.block")

    # Act
    response = await reveal(panel, subject=_SUBJECT_A)

    # Assert
    assert granted.status_code == 200
    assert granted.json()["scope"] == f"user.block:{_SUBJECT_A}"
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value


async def test_a_grant_older_than_the_grace_is_refused(panel: Panel) -> None:
    """The window the ``/auth/step-up`` response promised is the one the handler honours."""
    # Arrange
    await signed_in(panel)
    granted = await step_up(panel, subject=_SUBJECT_A)
    grace_s = panel.container.settings.admin_step_up_grace_seconds

    # Act - move the handler's clock one second past the promised expiry
    panel.clock.offset_s = grace_s + 1
    response = await reveal(panel, subject=_SUBJECT_A)

    # Assert
    assert granted.status_code == 200
    expiry = datetime.fromisoformat(granted.json()["expiresAt"])
    granted_at = datetime.fromisoformat(granted.json()["grantedAt"])
    assert (expiry - granted_at).total_seconds() == grace_s
    assert response.status_code == 403


async def test_a_grant_inside_the_grace_still_admits_a_second_reveal(panel: Panel) -> None:
    """Grants are not single-use, which is exactly why the budget is the volume bound."""
    # Arrange
    await signed_in(panel)
    assert (await step_up(panel, subject=_SUBJECT_A)).status_code == 200

    # Act
    panel.clock.offset_s = panel.container.settings.admin_step_up_grace_seconds - 1
    first = await reveal(panel, subject=_SUBJECT_A)
    second = await reveal(panel, subject=_SUBJECT_A)

    # Assert
    assert [first.status_code, second.status_code] == [200, 200]


async def test_a_subject_that_could_never_be_a_scope_is_a_422_not_a_403(panel: Panel) -> None:
    """A malformed request must not send the SPA into a re-auth loop it cannot win."""
    # Arrange
    await signed_in(panel)

    # Act - a space is outside the scope pattern, so no grant could ever match it
    response = await panel.http.post(
        "/api/test-probe/reveal/not a scope",
        headers=csrf_headers(panel.http),
    )

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.INVALID_INPUT.value


async def test_a_refused_step_up_is_audited_in_its_own_committed_transaction(
    panel: Panel,
) -> None:
    """§12.6: the refusal row is the one a "successes only" log would not have."""
    # Arrange
    await signed_in(panel)

    # Act
    assert (await reveal(panel, subject=_SUBJECT_A)).status_code == 403

    # Assert
    async with panel.container.session_factory.begin() as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT action, subject_id, error_code FROM admin_audit_log"
                    " WHERE action = 'permission.denied'"
                )
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("permission.denied", _SUBJECT_A, AdminErrorCode.STEP_UP_REQUIRED.value)
    ]


# ---------------------------------------------------------------------------
# The 429 envelope
# ---------------------------------------------------------------------------
async def test_an_exhausted_budget_answers_429_with_the_reveal_code_and_a_retry_after(
    panel: Panel, caplog: pytest.LogCaptureFixture
) -> None:
    """The envelope §12.3 names, end to end: code, ``Retry-After``, the arithmetic — and the
    WARNING naming the operator whose session this was, which is the detection half."""
    # Arrange - the panel fixture configures a ten-record hour
    await signed_in(panel)
    assert (await step_up(panel, subject=_SUBJECT_A)).status_code == 200
    assert (await reveal(panel, subject=_SUBJECT_A, records=10)).status_code == 200

    # Act
    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        response = await reveal(panel, subject=_SUBJECT_A, records=1)

    # Assert
    assert response.status_code == 429
    body = response.json()["error"]
    assert body["code"] == AdminErrorCode.REVEAL_BUDGET_EXHAUSTED.value
    assert body["details"]["budget"] == RevealBudgetScope.RECORDS.value
    assert body["details"]["recordsRequested"] == 1
    assert body["correlationId"]
    assert 0 < int(response.headers["retry-after"]) <= REVEAL_RECORDS_WINDOW_S
    tripped = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "admin.reveal.budget_exhausted"
    ]
    assert [getattr(record, "admin_username", None) for record in tripped] == [USERNAME]


async def test_the_budget_is_charged_in_records_through_the_route(panel: Panel) -> None:
    """One request of ten records exhausts a ten-record hour; ten requests would not."""
    # Arrange
    await signed_in(panel)
    assert (await step_up(panel, subject=_SUBJECT_A)).status_code == 200

    # Act
    spent = await reveal(panel, subject=_SUBJECT_A, records=10)
    refused = await reveal(panel, subject=_SUBJECT_A, records=1)

    # Assert
    assert spent.json()["recordsCharged"] == 10
    assert refused.status_code == 429


async def test_a_reveal_that_would_charge_nothing_is_a_422_rather_than_a_free_reveal(
    panel: Panel,
) -> None:
    """A zero charge is the back door to a budget that silently does not work."""
    # Arrange
    await signed_in(panel)
    assert (await step_up(panel, subject=_SUBJECT_A)).status_code == 200

    # Act
    response = await reveal(panel, subject=_SUBJECT_A, records=0)

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.INVALID_INPUT.value


async def test_the_configured_ceilings_are_the_ones_the_route_enforces(panel: Panel) -> None:
    """``AdminSettings`` is the authority; the module defaults are only a unit-test shape."""
    limits = reveal_budget_limits(panel.container.settings)

    assert limits.max_records_per_hour == 10
    assert limits.max_conversations_per_day == DEFAULT_MAX_CONVERSATIONS_PER_DAY


async def test_a_budget_store_outage_is_a_503_rather_than_a_429() -> None:
    """ "Your budget is spent" for an hour of a Redis outage sends the wrong incident."""
    # Arrange - sign in and step up while the store works, then take it down
    async with open_panel() as running:
        await signed_in(running)
        assert (await step_up(running, subject=_SUBJECT_A)).status_code == 200
        running.limits.is_down = True

        # Act
        response = await reveal(running, subject=_SUBJECT_A)

        # Assert
        assert response.status_code == 503
        assert response.json()["error"]["code"] == AdminErrorCode.SERVICE_UNAVAILABLE.value
