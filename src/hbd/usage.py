"""One measured record per vendor call, and the seam every adapter writes it through.

This module is the reason a provider adapter can report what a call cost without knowing
that a database, an order, or a pipeline exists. It imports ``hbd.contracts``,
``hbd.logging`` and the standard library and **nothing else** — deliberately not
``hbd.db`` and not ``hbd.pipeline`` — so every layer in the system is free to depend on
it and no layer is dragged into another's import graph by measuring itself.

Three decisions carry the design:

**Every optional quantity is ``None``, never ``0``.** ``VendorUsage`` mirrors the
``vendor_usage`` columns exactly, and every column there is nullable with no default. A
zero token count and an unmeasured token count are different facts, and ``0`` is the
answer that makes them the same: ``SUM()`` over a column of defaulted zeroes reads as "we
spent nothing" when the truth is "nobody counted". That is the trap
``generation_attempts.cost_usd`` fell into — it defaults to ``0.0``, so the dashboard has
no cost figure it can honestly draw from a table full of rows. Absent stays absent here so
SQL returns ``NULL`` for a group nobody measured, and the null-never-zero rule costs no
application code at all.

**Cost carries its provenance or it does not exist.** ``cost_usd`` and ``cost_source``
move together — both set or both ``None`` — and the database refuses any other
combination (``ck_vendor_usage_cost_carries_its_source``). A dollar figure with no
provenance cannot be read: an operator has no way to tell a number the vendor billed us
from arithmetic we did over our own rate card, and the two deserve different trust.

**Attribution arrives through a context, not through a signature.** ``usage_scope()``
binds ``order_id`` and ``task`` to a ``ContextVar``, exactly the way
``hbd.logging.correlation_scope`` binds a correlation id, so not one provider method grows
an order-id parameter it has no business knowing about. The scope is entered where the
work is understood — the orchestrator's stage wrapper, the runtime job, the wizard's
lyric-preview call — and read where the call is made.

**A sink may not raise.** :class:`UsageSink` is a Protocol whose contract is that
``record`` returns, always. Telemetry that can fail a vendor call is worse than telemetry
that is missing: the customer's song must not be lost because a metrics row did not
persist. Implementations swallow, log and return; see ``hbd.db.vendor_usage.DbUsageSink``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, Final, Protocol, runtime_checkable
from uuid import UUID

from hbd.contracts import CostSource, UsageTask, Vendor, VendorOperation
from hbd.logging import get_logger

__all__ = [
    "VendorUsage",
    "UsageContext",
    "UsageSink",
    "usage_scope",
    "current_usage_context",
    "USAGE_EVENT",
    "log_usage",
    "LoggingUsageSink",
    "LOGGING_USAGE_SINK",
]

#: Grep-able event name. One line per vendor call, success or failure, whatever the sink.
#:
#: Distinct from ``hbd.providers.music.usage.USAGE_EVENT`` (``"music.usage"``) on purpose:
#: that line carries the music adapter's own richer render facts — chunk count, output
#: format, name chunk index — and it stays exactly as it is. This one is the uniform line
#: every vendor emits, and a log query that wants "all spend" wants this one.
USAGE_EVENT: Final[str] = "vendor.usage"

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class VendorUsage:
    """What one vendor call cost and consumed. The row, before it is a row.

    Field-for-field the shape of ``vendor_usage`` minus the columns the sink fills in
    itself (``id``, ``order_id``, ``task``, ``correlation_id``, ``created_at``): an adapter
    knows what it asked the vendor for and what came back, and knows nothing about which
    order it was for. Keeping those two halves apart is what lets the whole attribution
    story live in ``usage_scope()``.

    The four required fields are the four an adapter always knows by the time it returns —
    even from a transport error, where ``http_status`` and every quantity are ``None`` and
    ``is_success`` is ``False``. Everything else defaults to ``None``: see the module
    docstring on why never to default a quantity to zero.
    """

    vendor: Vendor
    operation: VendorOperation
    #: The ADAPTER's name (``elevenlabs_music``, ``openai-compat``, ``fake_llm``), not the
    #: billing entity — that is ``vendor``. Two adapters can bill to one invoice.
    provider: str
    is_success: bool
    #: The vendor's own model identifier as sent or returned, never one of our enums:
    #: ``music_v2``, ``eleven_v3``, ``google/gemma-4-31b-it:free``.
    model_id: str | None = None
    #: True for the SECOND OpenRouter account. Both LLM adapters report ``name`` =
    #: ``"openai-compat"`` today, so without this flag primary and fallback spend are one
    #: undifferentiated number and "how much is the fallback costing us" is unanswerable.
    is_fallback: bool = False
    #: True under ``HBD_USE_FAKE_PROVIDERS``. Recorded rather than skipped, so a demo run is
    #: visibly excluded instead of silently absent.
    is_fake: bool = False
    http_status: int | None = None
    #: A member of the closed ``hbd.errors`` taxonomy. NEVER a response-body excerpt: a
    #: vendor error body can quote the prompt back, and the prompt names a real person.
    error_code: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    billed_characters: int | None = None
    audio_ms: int | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    #: ``None`` means "not priced here" and never "free". Set only together with
    #: ``cost_source``; the database enforces the pairing.
    cost_usd: float | None = None
    cost_source: CostSource | None = None


@dataclass(frozen=True, slots=True)
class UsageContext:
    """Who a vendor call was for. Bound by :func:`usage_scope`, read at the call site.

    Both fields are optional and their combinations are all meaningful: the wizard's lyric
    preview has a task and genuinely no order (the order does not exist yet, and inventing
    one would be worse than a null), and a health probe fired by the runtime has neither.
    """

    order_id: UUID | None
    task: UsageTask | None


#: The unbound context. A module-level singleton rather than a fresh instance per read, so
#: "nobody bound anything" is one object every reader can compare against cheaply.
_UNBOUND: Final[UsageContext] = UsageContext(order_id=None, task=None)

_USAGE_CONTEXT: ContextVar[UsageContext] = ContextVar("hbd_usage_context", default=_UNBOUND)


@runtime_checkable
class UsageSink(Protocol):
    """Where a measured call goes. **Contractually forbidden from raising.**

    Every adapter awaits ``record`` on every return path, including its failure paths, so
    an implementation that raised would convert a lost metrics row into a lost song. An
    implementation that cannot write swallows, logs a WARNING and returns.
    """

    async def record(self, usage: VendorUsage) -> None: ...


@contextmanager
def usage_scope(
    *, order_id: UUID | None = None, task: UsageTask | None = None
) -> Iterator[UsageContext]:
    """Bind attribution for the duration of a block, then restore what was there before.

    Mirrors ``hbd.logging.correlation_scope``'s set/reset-token shape, and nests the same
    way: an inner scope that names only a ``task`` inherits the ``order_id`` the outer
    scope bound, which is exactly the layering the pipeline needs — the orchestrator binds
    the order once and its per-stage wrapper binds the task six times inside it.

    A field passed as ``None`` INHERITS rather than clears. Clearing would mean an inner
    scope naming a task could silently detach the call from its order, and there is no
    caller that wants that; the wizard's preview, which really has no order, is simply
    never inside an order scope to begin with.
    """
    inherited = _USAGE_CONTEXT.get()
    resolved = UsageContext(
        order_id=order_id if order_id is not None else inherited.order_id,
        task=task if task is not None else inherited.task,
    )
    token = _USAGE_CONTEXT.set(resolved)
    try:
        yield resolved
    finally:
        _USAGE_CONTEXT.reset(token)


def current_usage_context() -> UsageContext:
    """The bound attribution, or the unbound ``(None, None)`` outside any scope."""
    return _USAGE_CONTEXT.get()


def log_usage(logger: logging.Logger, usage: VendorUsage, context: UsageContext) -> None:
    """Emit one usage line. The JSON formatter folds ``extra`` into ``context``.

    The attribution is merged in rather than nested so a log query can filter on
    ``context.order_id`` without knowing which of the two dataclasses a field came from.
    ``order_id`` is stringified here because the formatter's ``default=str`` would do it
    anyway and a ``UUID`` that reaches ``extra`` intact reads differently between handlers.
    """
    payload: dict[str, Any] = asdict(usage) | {
        "order_id": str(context.order_id) if context.order_id is not None else None,
        "task": context.task.value if context.task is not None else None,
    }
    logger.info(USAGE_EVENT, extra=payload)


class LoggingUsageSink:
    """The default sink: one structured log line, no persistence.

    Every adapter constructor defaults to :data:`LOGGING_USAGE_SINK`, so a caller with no
    database — a unit test, a one-shot operator tool, the ``hbd.demo`` runner — still gets
    the measurement on stdout and nothing has to be wired for the code to be correct.
    ``hbd.runtime.providers`` replaces it with the persisting sink in the real processes.
    """

    async def record(self, usage: VendorUsage) -> None:
        log_usage(_log, usage, current_usage_context())


#: The adapter default. A single shared instance: it is stateless, so one is enough.
LOGGING_USAGE_SINK: Final[UsageSink] = LoggingUsageSink()
