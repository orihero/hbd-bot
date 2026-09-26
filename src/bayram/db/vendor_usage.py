"""The persisting :class:`~bayram.usage.UsageSink`: one ``vendor_usage`` row per vendor call.

This is the only place a measured call becomes a row, and it is the only place that knows
both halves of the record: the adapter supplies what the vendor did
(:class:`~bayram.usage.VendorUsage`), and this module reads who it was for from
``usage_scope()`` and which request it belonged to from the correlation id. That split is
what keeps every provider signature free of an order id.

**Nothing here may raise, ever.** ``record`` is awaited on every return path of every
adapter, including their failure paths, so an exception escaping this function would turn
"the metrics row did not persist" into "the customer's song failed". The whole body is
guarded: a failed write logs a WARNING with the vendor and operation — enough to notice
the instrumentation is broken — and returns. The measurement is still on stdout regardless,
because :func:`~bayram.usage.log_usage` runs BEFORE the insert is attempted, so a database
that is down costs the durable copy and not the observable one.

**The write is synchronous on the call path, by choice.** It is one small INSERT issued
after the vendor's response has already been fully read, against a connection pool the
process already holds; the vendor round trip it rides behind is three orders of magnitude
slower. A background queue would trade that millisecond for rows lost on every shutdown,
and the rows nobody can afford to lose are the ones written just before a crash.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.db.models.vendor_usage import VendorUsageRow
from bayram.logging import current_correlation_id, get_logger
from bayram.usage import UsageContext, VendorUsage, current_usage_context, log_usage

__all__ = ["DbUsageSink"]

_log = get_logger(__name__)

#: What ``bayram.logging`` returns when no correlation id has been bound. Stored as ``NULL``
#: rather than verbatim: a sentinel in a column is a value that sorts, groups and joins like
#: a real id, and "-" would eventually be counted as a request.
_UNBOUND_CORRELATION_ID: Final[str] = "-"


class DbUsageSink:
    """Writes each measured call to ``vendor_usage``. Owns its own transaction.

    ``sessions`` is the process's session factory rather than a session, because a sink
    outlives any one request and is shared by every adapter in a
    :class:`~bayram.runtime.providers.ProviderSet`. Each ``record`` opens and commits its own
    short transaction: the alternative — joining whatever transaction the caller happens to
    be in — would make a rolled-back pipeline stage erase the evidence that its vendor call
    was made and paid for, which is precisely backwards.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(self, usage: VendorUsage) -> None:
        """Log the call, then persist it. Never raises — see the module docstring."""
        try:
            # Inside the guard, not merely before it. ``log_usage`` is not the safe half of
            # this method: ``Logger.makeRecord`` raises ``KeyError`` when a key in ``extra``
            # collides with a ``LogRecord`` attribute, and ``log_usage`` passes one key per
            # ``VendorUsage`` field, so a field added upstream is one rename away from
            # failing a paid vendor call. The WARNING below cannot fail the same way: it
            # names two keys, both of them checked against ``LogRecord`` here and now.
            context = current_usage_context()
            log_usage(_log, usage, context)
            async with self._sessions.begin() as session:
                session.add(_to_row(usage, context))
        except Exception:
            # Logged rather than swallowed silently: instrumentation that stops working
            # looks exactly like a deployment with no traffic, and the panel's
            # ``isVendorUsage`` probe would then report "not instrumented" for a system that
            # is calling vendors all day.
            _log.warning(
                "vendor usage row not persisted",
                exc_info=True,
                extra={"vendor": usage.vendor.value, "operation": usage.operation.value},
            )


def _to_row(usage: VendorUsage, context: UsageContext) -> VendorUsageRow:
    """Assemble the row. Every optional quantity is copied as-is, ``None`` included.

    Written out field by field rather than through ``asdict()`` so that adding a column to
    the model without adding a field to :class:`~bayram.usage.VendorUsage` (or the reverse) is
    a type error here rather than a column that silently stays ``NULL`` in production.
    """
    correlation_id = current_correlation_id()
    return VendorUsageRow(
        vendor=usage.vendor,
        operation=usage.operation,
        provider=usage.provider,
        model_id=usage.model_id,
        is_fallback=usage.is_fallback,
        is_fake=usage.is_fake,
        task=context.task,
        order_id=context.order_id,
        correlation_id=None if correlation_id == _UNBOUND_CORRELATION_ID else correlation_id,
        is_success=usage.is_success,
        http_status=usage.http_status,
        error_code=usage.error_code,
        latency_ms=usage.latency_ms,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        billed_characters=usage.billed_characters,
        audio_ms=usage.audio_ms,
        request_bytes=usage.request_bytes,
        response_bytes=usage.response_bytes,
        cost_usd=usage.cost_usd,
        cost_source=usage.cost_source,
    )
