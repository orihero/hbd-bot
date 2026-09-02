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
from hbd.entitlements import EntitlementStore
from hbd.lyric_budget import LyricBudgetStore
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
    #: The entitlement meter. Every GATE that reads it is read-only — ``balance_for`` is the
    #: only method ``handlers.confirm`` and ``handlers.balance`` call, because a gate that
    #: could write could double-charge. The two exceptions are not gates and neither can
    #: spend anything: ``gate.TouchDrain`` upserts a last-seen row off the hot path, and
    #: ``/forget`` calls ``forget`` to honour a data-subject request.
    #:
    #: TRAILING and DEFAULTED because the whole bot suite builds ``BotDeps`` by keyword with
    #: the fields above and must keep running with the meter unwired
    #: (tests/test_bot/conftest.py:290).
    #:
    #: ``None`` means "no meter at all", which is not the same as
    #: ``Settings.credits_enforced=False``: unwired skips the read entirely, dark performs
    #: the read and enforces the block gate and the in-flight cap from it — both of which
    #: read rows the worker's charge writes whatever that flag says — while ignoring the
    #: balance. Both let a customer with no credits through to the queue; only the second is
    #: the shipped production configuration.
    #:
    #: ``hbd.main`` passes ``container.credits`` here and ``container.payment`` — the plain
    #: no-op provider, NOT the credit-gated one — to ``payment`` above. That asymmetry is
    #: the design: the bot reads and refuses, the worker writes. See
    #: ``handlers.confirm._entitlement_refusal`` and ``runtime.container._render_gate``.
    entitlements: EntitlementStore | None = None
    #: The daily lyric-write ceiling. The one meter in this container the bot genuinely
    #: WRITES to, and a separate seam from ``entitlements`` for exactly that reason: a lyric
    #: write is not a credit, cannot become a free song, and putting it on the store above
    #: would be the moment "every gate that reads the meter is read-only" stopped being
    #: literally true.
    #:
    #: Charged in ``handlers.lyrics.enter_lyrics_step``, which is the first vendor spend in
    #: the product and sits BEFORE the payment and credit gates — those guard the worker,
    #: which a customer who never presses Confirm never reaches. It is durable (a row, not
    #: process memory) because ``MAX_LYRIC_WRITES`` counts per DRAFT and ``reset_to_welcome``
    #: throws the draft away, so a per-session counter is one ``/start`` from being reset.
    #:
    #: TRAILING and DEFAULTED for the same reason as ``entitlements``: the whole bot suite
    #: builds ``BotDeps`` by keyword without it. ``None`` means "no budget wired at all" and
    #: the lyric step then behaves exactly as it did before this field existed.
    lyric_budget: LyricBudgetStore | None = None
