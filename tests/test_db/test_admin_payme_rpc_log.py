"""``db.admin.payme_rpc_log`` — the journal that fills before anything else does.

This table is the FIRST evidence this deployment will have that the rail exists: the gateway
daemon already answers on 127.0.0.1:8091 behind the tunnel while ``CHECKOUT_PROVIDER`` is still
unset, so Payme's checks land here before a single ``payment_intents`` row is written. Every
test below is about a shape that has to be right on day one rather than on the day money moves.

Three properties earn their tests:

* **Success and fault are told apart by SIGN.** ``reply_code`` is ``0`` for success and the
  JSON-RPC code otherwise, negative for every protocol fault, and there is deliberately no
  second boolean column that could disagree with it.
* **An empty ``methods`` tuple means NO filter.** ``IN ()`` quietly returning an empty page is
  the failure mode that empties an incident screen at exactly the moment somebody clears the
  filters to see everything.
* **Zero calls for an intent is an ANSWER, not a gap.** It is what a force-settled payment looks
  like, and — for a payment older than ninety days — what the journal's retention looks like.
  This layer returns the empty tuple and refuses to guess which; the caller decides from the
  row's own age.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import is_ok
from bayram.db.admin.page import PageRequest, page_request
from bayram.db.admin.payme_rpc_log import (
    CallFilters,
    call_totals,
    calls_for_intent,
    count_calls,
    fault_clusters,
    has_recorded_inbound_call,
    last_inbound_call,
    list_calls,
)
from bayram.db.admin.sql import TimeWindow
from tests.test_db.rail_helpers import add, make_call

_NOW: Final[datetime] = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


async def test_the_journal_probes_are_empty_before_payme_has_ever_called(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``None`` and ``False``: "Payme has never reached this endpoint", not a failed fetch."""
    # Act
    async with sessions() as session:
        assert await last_inbound_call(session) is None
        assert await has_recorded_inbound_call(session) is False


async def test_the_last_call_is_the_newest_and_ignores_any_window(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Window-blind on purpose: the answer is most useful when it is OLD.

    "Nothing for six hours" is the signal; scoping it to the header's range would replace that
    with "nothing in the last hour", which is a different and much less alarming sentence.
    """
    # Arrange
    await add(
        sessions,
        make_call(at=_NOW - timedelta(days=30), method="CheckTransaction"),
        make_call(at=_NOW - timedelta(hours=6), method="GetStatement", reply_code=-32504),
    )

    # Act
    async with sessions() as session:
        last = await last_inbound_call(session)
        assert await has_recorded_inbound_call(session) is True

    # Assert
    assert last is not None
    assert last.method == "GetStatement"
    assert last.reply_code == -32504
    assert last.at == _NOW - timedelta(hours=6)


async def test_a_failed_auth_call_renders_with_both_identifiers_null(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Both columns nullable is the design: the NULLs say how much we learned from the call."""
    # Arrange
    await add(sessions, make_call(at=_NOW, method="Unknown", reply_code=-32504, peer_ip=None))

    # Act
    async with sessions() as session:
        last = await last_inbound_call(session)

    # Assert
    assert last is not None
    assert (last.public_ref, last.payme_transaction_id, last.peer_ip) == (None, None, None)


async def test_totals_count_faults_by_sign_in_one_statement(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``reply_code != 0``. No second column, and no ``sum(CASE … ELSE 0)``."""
    # Arrange — two successes and three faults, one of which is a positive code.
    await add(
        sessions,
        make_call(at=_NOW, reply_code=0),
        make_call(at=_NOW, reply_code=0),
        make_call(at=_NOW, reply_code=-31003),
        make_call(at=_NOW, reply_code=-31050),
        make_call(at=_NOW, reply_code=7),
    )

    # Act
    async with sessions() as session:
        calls, faults = await call_totals(session)

    # Assert
    assert (calls, faults) == (5, 3)


async def test_totals_are_zero_and_not_null_over_an_empty_window(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``count`` is never NULL, which is why it is used rather than ``sum``."""
    # Arrange
    await add(sessions, make_call(at=_NOW - timedelta(days=10)))

    # Act
    async with sessions() as session:
        totals = await call_totals(
            session, window=TimeWindow(start=_NOW - timedelta(hours=1), end=_NOW)
        )

    # Assert
    assert totals == (0, 0)


async def test_fault_clusters_group_by_method_and_code_and_exclude_success(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Commonest first, with the two instants that turn a count into a diagnosis."""
    # Arrange
    first = _NOW - timedelta(minutes=8)
    await add(
        sessions,
        make_call(at=first, method="CheckTransaction", reply_code=-31003, duration_ms=40),
        make_call(at=_NOW, method="CheckTransaction", reply_code=-31003, duration_ms=4000),
        make_call(at=_NOW, method="CheckTransaction", reply_code=-31003, duration_ms=90),
        make_call(at=_NOW, method="PerformTransaction", reply_code=-31008),
        make_call(at=_NOW, method="CheckTransaction", reply_code=0),
    )

    # Act
    async with sessions() as session:
        clusters = await fault_clusters(session, limit=20)

    # Assert
    assert [(c.method, c.reply_code, c.calls) for c in clusters] == [
        ("CheckTransaction", -31003, 3),
        ("PerformTransaction", -31008, 1),
    ]
    biggest = clusters[0]
    assert (biggest.first_at, biggest.last_at) == (first, _NOW)
    # A MAX and not a mean: a mean over this cluster would hide the four-second call.
    assert biggest.slowest_ms == 4000


async def test_fault_clusters_honour_the_limit(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The route refuses an out-of-range limit with a 422; this layer applies the one it got."""
    # Arrange
    await add(
        sessions,
        make_call(at=_NOW, method="A", reply_code=-1),
        make_call(at=_NOW, method="B", reply_code=-2),
        make_call(at=_NOW, method="C", reply_code=-3),
    )

    # Act
    async with sessions() as session:
        clusters = await fault_clusters(session, limit=2)

    # Assert
    assert len(clusters) == 2


async def test_an_empty_methods_tuple_means_no_filter(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**Never "match none".** An incident is investigated by clearing filters."""
    # Arrange
    await add(
        sessions,
        make_call(at=_NOW, method="CheckTransaction"),
        make_call(at=_NOW, method="PerformTransaction"),
    )

    # Act
    async with sessions() as session:
        page = await list_calls(session, filters=CallFilters(), request=PageRequest())
        narrowed = await list_calls(
            session,
            filters=CallFilters(methods=("PerformTransaction",)),
            request=PageRequest(),
        )

    # Assert
    assert len(page.items) == 2
    assert [item.method for item in narrowed.items] == ["PerformTransaction"]


async def test_faults_only_narrows_by_sign(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The same predicate the totals use, so the list and the count cannot disagree."""
    # Arrange
    await add(
        sessions,
        make_call(at=_NOW, reply_code=0),
        make_call(at=_NOW, reply_code=-31003),
    )

    # Act
    async with sessions() as session:
        page = await list_calls(
            session, filters=CallFilters(faults_only=True), request=PageRequest()
        )
        total = await count_calls(session, filters=CallFilters(faults_only=True))

    # Assert
    assert [item.reply_code for item in page.items] == [-31003]
    assert (total.total, total.is_exact) == (1, True)


async def test_keyset_paging_walks_the_journal_exactly_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The cursor is ``(at, id)`` — this table has no ``created_at`` to page on.

    Every row shares one instant, so the ``id`` tie-break is what the walk depends on.
    """
    # Arrange
    await add(sessions, *[make_call(at=_NOW) for _ in range(5)])

    # Act
    seen: list[str] = []
    cursor: str | None = None
    async with sessions() as session:
        for _ in range(5):
            request = page_request(limit=2, cursor=cursor)
            assert is_ok(request)
            page = await list_calls(session, filters=CallFilters(), request=request.value)
            seen.extend(str(item.id) for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

    # Assert
    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_calls_for_intent_match_on_either_identifier(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A call about an unknown account carries only ``public_ref``; a perform carries both."""
    # Arrange
    ref = "a" * 24
    txn = "b" * 24
    await add(
        sessions,
        make_call(at=_NOW - timedelta(minutes=2), method="CheckPerformTransaction", public_ref=ref),
        make_call(at=_NOW, method="PerformTransaction", public_ref=ref, payme_transaction_id=txn),
        make_call(at=_NOW, method="CheckTransaction", payme_transaction_id=txn),
        make_call(at=_NOW, method="CheckTransaction", public_ref="c" * 24),
    )

    # Act
    async with sessions() as session:
        calls = await calls_for_intent(session, public_ref=ref, payme_transaction_ids=(txn,))

    # Assert — oldest first, and the unrelated reference is not in the set.
    assert len(calls) == 3
    assert calls[0].method == "CheckPerformTransaction"
    assert all(call.public_ref == ref or call.payme_transaction_id == txn for call in calls)


async def test_calls_for_an_intent_payme_never_mentioned_are_empty_not_an_error(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The ``settle`` case.** Zero rows is the answer, and an empty id tuple is no filter.

    A force-settled payment has no inbound call about it at all, so this returns ``()`` — which
    the caller renders as "Payme never called us about this" or, for an old payment, as the
    ninety-day journal having aged out. This layer has no clock and refuses to guess.
    """
    # Arrange
    await add(sessions, make_call(at=_NOW, public_ref="z" * 24))

    # Act
    async with sessions() as session:
        calls = await calls_for_intent(session, public_ref="a" * 24, payme_transaction_ids=())

    # Assert
    assert calls == ()
