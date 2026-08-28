"""Seams the bot needs from the rest of the system.

The bot depends on these protocols, never on the queue module or the worker. That keeps the
intake wizard unit-testable with no Redis, and it means the day the job runner changes the
handlers do not.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from hbd.contracts import Order, Result

__all__ = ["OrderSubmitter", "Clock", "utc_now"]

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
