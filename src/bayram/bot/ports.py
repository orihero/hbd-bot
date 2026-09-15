"""Seams the bot needs from the rest of the system.

The bot depends on these protocols, never on the queue module or the worker. That keeps the
intake wizard unit-testable with no Redis, and it means the day the job runner changes the
handlers do not.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from bayram.contracts import Order, Result

__all__ = ["OrderSubmitter", "SupportTicketEraser", "Clock", "utc_now"]

#: Supplies "now". Injected so a state transition is assertable against a fixed instant.
type Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """The production clock. Always timezone-aware."""
    return datetime.now(UTC)


@runtime_checkable
class OrderSubmitter(Protocol):
    """Hands a finished order to the job queue.

    The implementation lives in the composition root (ARQ, in production). It receives the
    chat and the id of the progress message the bot has already posted, so the worker's
    progress events can be edited into a message that exists rather than racing to create
    one.

    Returns the job handle on success — logged, never shown to a customer.
    """

    async def submit(
        self, order: Order, *, chat_id: int, progress_message_id: int
    ) -> Result[str]: ...


@runtime_checkable
class SupportTicketEraser(Protocol):
    """Deletes one customer's support tickets. The erasure route ``/forget`` promises.

    **A port of its own rather than a thirteenth method on**
    :class:`bayram.support.SupportTicketStore`, and the split is the same one ``BotDeps``
    already makes twice. ``EntitlementStore`` is read by every gate and written by exactly one
    caller; ``SupportTicketStore`` is the working seam — open, describe, post, move — and it is
    held by handlers that a customer drives. This protocol can express one thing, it is DELETE,
    and a handler that holds it cannot open, move or read a ticket. Folding it into the working
    store would put an irreversible delete within reach of every support handler in the bot,
    which is precisely the reasoning ``purchases`` uses against putting a grant on the meter.

    **Delete, not anonymise, and that is a schema fact rather than a preference.**
    ``support_tickets.telegram_user_id`` is NOT NULL — deliberately unlike
    ``broadcast_recipients`` and ``credit_ledger``, which keep a count with the account number
    taken off it — because there is no count here worth keeping: a ticket without the person
    it belongs to is a complaint nobody can answer and a body nobody may read. The whole row
    goes, and ``support_ticket_events.ticket_id`` is ``ON DELETE CASCADE`` so the timeline goes
    with it in one statement.

    Returns how many tickets were removed, so ``/forget`` can log a number rather than a
    boolean; zero is the ordinary answer for a customer who never had a problem, and is
    success. Idempotent, like the other two erasures the command performs, because ``/forget``
    is documented as safe to send again when one arm of it fails.
    """

    async def forget_tickets(self, telegram_user_id: int) -> Result[int]: ...
