"""What the worker writes to the ledger when a run ends, and what it deliberately does not.

The debit is taken once, at ``AUTHORIZING``, by ``CreditGatedPaymentProvider``. Closing it
is a separate decision made much later and by a different module, because only
``bayram.runtime.jobs`` can see whether the kit actually reached the customer. That decision
has an exploit on either side of it, which is why it gets a module of its own rather than a
couple of extra assertions in ``test_jobs``:

* refund a kit Telegram refused and anyone who blocks the bot right after Confirm renders
  for free, forever — the kit is fully paid for in vendor spend and is still persisted and
  redeliverable when the send gives up;
* refund a cancelled job and every SIGTERM hands out free songs, because arq re-queues a
  cancelled job (``retry_jobs`` defaults to ``True``) and the replay finds an order that is
  no longer paid for and charges nothing back;
* *fail* to refund a terminal failure and the FAILED progress frame's promise — "you have
  not lost anything" — becomes a lie the customer can count.

Every test therefore asserts the exact movement list for the order, not just a balance:
``["debit"]`` and ``["debit", "consume"]`` are different facts that can share a balance.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from arq.worker import Retry

from bayram.bot.i18n import translate
from bayram.contracts import Kit, Ok, Order, Result, err, ok
from bayram.entitlements import SettlementOutcome
from bayram.errors import PipelineError, ProviderTimeoutError, StorageError
from bayram.payments import PIPELINE_ACTOR
from bayram.runtime.jobs import generate_and_deliver
from tests.test_bot.conftest import CHAT_ID, RecordingSession
from tests.test_runtime.conftest import RecordingEntitlementStore

# Imported rather than rebuilt: this module drives the SAME job function through the SAME
# scripted pipeline, and a second copy of the container shape is a second thing to keep in
# step with ``AppContainer``. tests/test_db/test_credit_schema.py imports privates from
# tests/test_db/test_migrations.py for the same reason.
from tests.test_runtime.test_jobs import (
    MESSAGE_ID,
    _Container,
    _ctx,
    _final_attempt,
    _outcome,
)

#: What a run that reached the customer must leave behind: the debit, then the consume that
#: marks it spent. Written out because the interesting failures are one element long.
DELIVERED_MOVEMENTS = ["debit", "consume"]


async def _charged(store: RecordingEntitlementStore, order: Order) -> None:
    """Put the account in the state the render gate leaves it in: one open debit.

    The pipeline is scripted in these tests, so it never reaches the real gate. Charging by
    hand here is the honest stand-in — it produces exactly the net position (-1, unsettled)
    that ``CreditGatedPaymentProvider`` produces at ``AUTHORIZING``, which is the only thing
    settlement reads.
    """
    charged = await store.charge(
        telegram_user_id=order.telegram_user_id, order_id=order.id, actor=PIPELINE_ACTOR
    )
    assert isinstance(charged, Ok), f"arrange failed to open a debit: {charged}"


def _refuse_every_send(session: RecordingSession) -> None:
    """Telegram rejects the kit, the voice notes and the explanation alike."""
    for name in ("SendAudio", "SendVoice", "SendMessage"):
        session.failures[name] = TelegramBadRequest(method=None, message="chat not found")  # type: ignore[arg-type]


async def _in_flight(store: RecordingEntitlementStore, telegram_user_id: int) -> int:
    """How many of this account's orders still hold an unsettled debit."""
    balance = await store.balance_for(telegram_user_id)
    assert isinstance(balance, Ok), f"the balance could not be read: {balance}"
    return balance.value.in_flight


async def test_a_delivered_run_consumes_the_credit_and_frees_the_in_flight_slot(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    # Arrange
    store = RecordingEntitlementStore()
    await _charged(store, order)
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path, credits=store)

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert — spent, not returned, and the abuse cap no longer counts this order
    assert summary["is_delivered"] is True
    assert store.kinds_for(order.id) == DELIVERED_MOVEMENTS
    assert store.credits == 2
    assert await _in_flight(store, order.telegram_user_id) == 0


async def test_a_terminally_failed_run_refunds_the_credit_the_progress_frame_promised(
    order: Order, bot: Bot, tmp_path: Path
) -> None:
    """``progress.failed`` says "you have not lost anything". This is what makes it true.

    ``error.content_not_allowed`` is the moderation rejection specifically, because the
    charge now happens at ``AUTHORIZING`` — one stage BEFORE ``MODERATING`` — so a refused
    note is a charged-then-terminally-failed run and this refund is the only thing standing
    between the customer and paying for a song nobody was allowed to write.
    """
    # Arrange
    store = RecordingEntitlementStore()
    await _charged(store, order)
    failure = PipelineError("moderator refused", user_message_key="error.content_not_allowed")
    container = _Container(order=order, outcome=err(failure), root=tmp_path, credits=store)

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is False
    assert store.kinds_for(order.id) == ["debit", "refund"]
    assert store.credits == 3
    assert await _in_flight(store, order.telegram_user_id) == 0


async def test_a_kit_telegram_refused_is_consumed_and_never_refunded(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    """The NOT_DELIVERED half of the policy, and the one that is an exploit if inverted.

    On the last attempt a refused send stops being retryable and the run ends — but the kit
    is rendered, persisted and redeliverable, so the credit bought something. Refunding here
    would mean: tap Confirm, block the bot, collect a full LLM + ElevenLabs render, watch
    five sends fail, get the credit back, repeat.
    """
    # Arrange
    store = RecordingEntitlementStore()
    await _charged(store, order)
    _refuse_every_send(session)
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path, credits=store)
    ctx = _ctx(container, bot, job_try=_final_attempt(container))

    # Act
    summary = await generate_and_deliver(ctx, str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is False
    assert store.kinds_for(order.id) == DELIVERED_MOVEMENTS
    assert "refund" not in store.kinds_for(order.id)
    assert store.credits == 2
    # The CONSUME half of the policy has to be the whole half: a run that has stopped must
    # not keep holding the cap's only slot, or a customer whose send failed is locked out
    # until the grace expires.
    assert await _in_flight(store, order.telegram_user_id) == 0


async def test_a_cancelled_job_settles_nothing_because_arq_will_run_it_again(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    """One free song per deploy is what a refund on this path costs.

    ``build_kit_worker_settings`` never sets ``retry_jobs``, so arq's default ``True``
    applies and ``Worker.handle_sig`` cancels every running task on SIGTERM. The job comes
    back; if the cancellation had refunded, the replay would find an order that is no longer
    paid for, charge again, and the customer would have rendered twice for one credit — on
    every single deployment.
    """
    # Arrange
    store = RecordingEntitlementStore()
    await _charged(store, order)
    container = _Container(
        order=order, outcome=ok(_outcome(kit)), root=tmp_path, hangs=True, credits=store
    )
    task = asyncio.create_task(
        generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Act
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Assert — the debit is untouched and still counts, which is what makes the replay a
    # no-op charge rather than a second sale.
    assert store.kinds_for(order.id) == ["debit"]
    assert store.credits == 2
    assert await _in_flight(store, order.telegram_user_id) == 1


async def test_a_retryable_failure_on_a_non_final_attempt_settles_nothing(
    order: Order, bot: Bot, tmp_path: Path
) -> None:
    """``Retry`` means the run is not over, so neither is the debit."""
    # Arrange
    store = RecordingEntitlementStore()
    await _charged(store, order)
    container = _Container(
        order=order,
        outcome=err(ProviderTimeoutError("slow", provider="music")),
        root=tmp_path,
        credits=store,
    )

    # Act
    with pytest.raises(Retry):
        await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert store.kinds_for(order.id) == ["debit"]
    assert store.credits == 2


async def test_a_send_that_is_coming_back_around_settles_nothing_either(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    """The second ``Retry`` path: the kit exists and the send will be tried again.

    Consuming here would be harmless to the balance but would free the in-flight slot for a
    run that is still running, which is precisely the stacking the cap exists to refuse.
    """
    # Arrange
    store = RecordingEntitlementStore()
    await _charged(store, order)
    _refuse_every_send(session)
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path, credits=store)

    # Act
    with pytest.raises(Retry):
        await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert store.kinds_for(order.id) == ["debit"]
    assert await _in_flight(store, order.telegram_user_id) == 1


async def test_a_redelivered_job_settles_the_same_order_once_not_twice(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    """arq can hand the same job to a worker again — a settlement must be idempotent.

    The real ledger decides this by net position and a unique ``consume:{order}:{gen}`` key;
    the fake decides it the same way. Either way the second pass must add no row, or an
    operator reading the trail sees one order sold twice.
    """
    # Arrange
    store = RecordingEntitlementStore()
    await _charged(store, order)
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path, credits=store)

    # Act — the same job, twice, exactly as a redelivery runs it
    await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)
    await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert store.kinds_for(order.id) == DELIVERED_MOVEMENTS
    assert store.credits == 2


async def test_an_order_that_was_never_debited_is_never_settled_into_a_free_credit(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path
) -> None:
    """No debit, no settlement. It happens when the store is unwired, when an account was
    erased mid-render, and on a redelivery whose first run already closed the row.

    A settlement that wrote a row here would be a settlement that MINTS. On the delivered
    path a stray CONSUME would only pollute the audit trail, but the same helper refunds on
    the failure path, and a refund for an order nobody paid for is free credits for every
    failed run in the system.
    """
    # Arrange — no charge at all
    store = RecordingEntitlementStore()
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path, credits=store)

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is True
    assert store.movements == []
    assert store.credits == 3


async def test_a_delivered_song_whose_debit_was_already_closed_is_reported_loudly(
    order: Order, kit: Kit, bot: Bot, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The only externally visible trace of a song that went out for free.

    A debit refunded out from under a live job — by the sweep, or by a settlement written on
    an earlier attempt — leaves ``net_position == 0``, so delivery's CONSUME writes nothing
    and returns ``Ok(False)``. That used to share an INFO line with every ordinary no-op,
    which made a free song and a redelivery indistinguishable in the log. It is now a
    WARNING of its own on the DELIVERED path, where a closed debit means the kit was paid
    for by nobody.
    """
    # Arrange — charged and then fully settled before the job's own settlement runs.
    store = RecordingEntitlementStore()
    await _charged(store, order)
    refunded = await store.settle(
        telegram_user_id=order.telegram_user_id,
        order_id=order.id,
        outcome=SettlementOutcome.FAILED,
        actor=PIPELINE_ACTOR,
    )
    assert isinstance(refunded, Ok), refunded
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path, credits=store)

    # Act
    with caplog.at_level(logging.WARNING):
        summary = await generate_and_deliver(
            _ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID
        )

    # Assert — the kit went out, and the log says the credit did not pay for it.
    assert summary["is_delivered"] is True
    assert any("settled nothing" in record.message for record in caplog.records)


async def test_a_ledger_that_refuses_the_settlement_still_lets_the_customer_hear_why(
    order: Order,
    bot: Bot,
    session: RecordingSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An ``Err`` from the store is logged at ERROR and changes nothing else about the run.

    The customer's explanation is the one thing on this path they can act on
    (``error.content_not_allowed`` is fixable by rewording). Losing it because the database
    was briefly unreachable would trade a bookkeeping problem — which WU6's sweep repairs —
    for a customer who never learns what went wrong.
    """
    # Arrange
    store = _RefusingSettlementStore()
    await _charged(store, order)
    failure = PipelineError("moderator refused", user_message_key="error.content_not_allowed")
    container = _Container(order=order, outcome=err(failure), root=tmp_path, credits=store)

    # Act
    with caplog.at_level(logging.ERROR):
        summary = await generate_and_deliver(
            _ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID
        )

    # Assert — the run finished, the reason was said, and the failure was not swallowed
    assert summary["is_delivered"] is False
    assert session.last_named("SendMessage").text == translate(
        "error.content_not_allowed", order.brief.ui_language
    )
    assert [r.message for r in caplog.records if r.levelname == "ERROR"].count(
        "the credit could not be settled; the debit stays open"
    ) == 1


async def test_a_ledger_that_raises_does_not_take_down_a_job_whose_kit_already_landed(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    """``run_guarded`` should make this impossible; the helper does not rely on that.

    By the time settlement runs, the audio is on the customer's phone. An exception escaping
    here would turn a delivered order into a job arq retries — re-rendering a kit that has
    already been sent, and sending it a second time.
    """
    # Arrange
    store = _ExplodingSettlementStore()
    await _charged(store, order)
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path, credits=store)

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is True
    assert session.named("SendAudio")


async def test_a_worker_wired_without_a_ledger_still_delivers_the_kit(
    order: Order, kit: Kit, bot: Bot, session: RecordingSession, tmp_path: Path
) -> None:
    """Only a hand-built container can be here — ``build_container`` always wires the store.

    It is still worth a test: settlement is bookkeeping, and bookkeeping that can refuse to
    deliver a paid-for song is worse than bookkeeping that is missing.
    """
    # Arrange
    container = _Container(order=order, outcome=ok(_outcome(kit)), root=tmp_path)
    object.__setattr__(container, "credits", None)  # AppContainer is frozen

    # Act
    summary = await generate_and_deliver(_ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID)

    # Assert
    assert summary["is_delivered"] is True
    assert session.named("SendAudio")


async def test_a_ledger_that_raises_on_the_failure_path_still_says_why(
    order: Order,
    bot: Bot,
    session: RecordingSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The refund is ordered BEFORE the explanation, so it must not be able to swallow it.

    ``_run_pipeline`` settles first on purpose (jobs.py:280-282) so that "you have not lost
    anything" is already true when the customer reads it rather than eventually true. That
    ordering is only safe because :func:`bayram.runtime.jobs._settle` swallows everything, and
    this is the test that holds it to that. The delivered-path test above cannot: there
    settlement runs *after* the send, so a raise costs the customer nothing they have not
    already received, and the branch that actually matters would stay unproven.
    """
    # Arrange
    store = _ExplodingSettlementStore()
    await _charged(store, order)
    failure = PipelineError("moderator refused", user_message_key="error.content_not_allowed")
    container = _Container(order=order, outcome=err(failure), root=tmp_path, credits=store)

    # Act
    with caplog.at_level(logging.ERROR):
        summary = await generate_and_deliver(
            _ctx(container, bot), str(order.id), CHAT_ID, MESSAGE_ID
        )

    # Assert — the reason arrived, and the swallowed exception was still made loud
    assert summary["is_delivered"] is False
    assert session.last_named("SendMessage").text == translate(
        "error.content_not_allowed", order.brief.ui_language
    )
    assert [r.message for r in caplog.records if r.levelname == "ERROR"].count(
        "settling the credit raised; the debit stays open"
    ) == 1


class _RefusingSettlementStore(RecordingEntitlementStore):
    """Charges normally, then answers every settlement with a retryable storage failure."""

    async def settle(
        self, *, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> Result[bool]:
        return err(StorageError("the ledger is unreachable", context={"order_id": str(order_id)}))


class _ExplodingSettlementStore(RecordingEntitlementStore):
    """The contract-violating store: it raises instead of returning an ``Err``."""

    async def settle(
        self, *, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> Result[bool]:
        raise RuntimeError("the settlement store is broken in a way Result cannot express")
