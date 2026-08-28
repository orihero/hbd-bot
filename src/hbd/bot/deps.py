"""Everything a handler is allowed to reach for, in one frozen container.

Handlers take ``deps: BotDeps`` as a parameter; aiogram injects it from the dispatcher's
workflow data by name. No handler imports a provider, reads the environment, or calls
``get_settings()`` — which is what makes every one of them testable with a fake queue and a
fixed clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from hbd.bot.payment import DEFAULT_CURRENCY, FREE_AMOUNT_MINOR, NoopPaymentProvider
from hbd.bot.ports import Clock, OrderSubmitter, utc_now
from hbd.config import Settings
from hbd.contracts import PaymentProvider
from hbd.pipeline.ports import ContentWriter

__all__ = ["BotDeps", "DEPS_KEY"]

#: Workflow-data key. Also the handler parameter name, because aiogram injects by name.
DEPS_KEY: Final[str] = "deps"


@dataclass(frozen=True, slots=True)
class BotDeps:
    """Immutable handler dependencies.

    ``content`` is required and has no default: the wizard writes the lyric itself now,
    because the customer approves it before anything is queued. The worker is handed a
    decided lyric rather than a brief to write one from, so a bot built without a writer
    could not get a customer past the preview screen and should fail at the composition
    root instead of at the fifth screen of a live session.

    ``payment`` defaults to the no-op provider because payment is out of scope for this
    build; the field exists so the real rail is a wiring change and not a refactor.
    """

    settings: Settings
    submitter: OrderSubmitter
    content: ContentWriter
    payment: PaymentProvider = field(default_factory=NoopPaymentProvider)
    clock: Clock = utc_now
    amount_minor: int = FREE_AMOUNT_MINOR
    currency: str = DEFAULT_CURRENCY
