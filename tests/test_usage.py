"""The attribution seam every vendor adapter measures itself through.

``bayram.usage`` exists so that a provider can report what a call cost without a signature
that names an order. Everything asserted here is a property that promise rests on: the
scope nests and restores, an unbound read is honestly empty rather than a guess, and the
log line carries both halves of the record — what the vendor did and who it was for — in
one flat object a log query can filter on.

The dataclass defaults get their own test because they are the design. Every optional
quantity is ``None``, never ``0``: a defaulted zero is what made
``generation_attempts.cost_usd`` unreadable, and a regression that "helpfully" defaults one
of these to zero would put a fabricated number in a column the panel sums.

The last section leaves ``bayram.usage`` to pin the other half of the promise on the one
implementation that can fail: :class:`~bayram.db.vendor_usage.DbUsageSink`. ``UsageSink`` is
declared here and its contract — ``record`` returns, always — is a claim about callers of
this module, so the case where even the fallback log line fails is asserted beside the
Protocol that makes the claim rather than only beside the table.
"""

from __future__ import annotations

import logging
from dataclasses import fields
from typing import Any, Final
from uuid import UUID, uuid4

import pytest

from bayram.contracts import CostSource, UsageTask, Vendor, VendorOperation
from bayram.usage import (
    LOGGING_USAGE_SINK,
    USAGE_EVENT,
    LoggingUsageSink,
    UsageContext,
    UsageSink,
    VendorUsage,
    current_usage_context,
    log_usage,
    usage_scope,
)

_ORDER_ID: Final[UUID] = UUID("11111111-2222-3333-4444-555555555555")

#: The fields that must never acquire a non-``None`` default. Named rather than derived so
#: that adding a column and forgetting the rule fails here with a readable message.
_QUANTITY_FIELDS: Final[tuple[str, ...]] = (
    "model_id",
    "http_status",
    "error_code",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "billed_characters",
    "audio_ms",
    "request_bytes",
    "response_bytes",
    "cost_usd",
    "cost_source",
)


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    """The ``extra=`` payload as the formatter sees it: flat on the record's ``__dict__``."""
    return dict(record.__dict__)


def _usage(**overrides: object) -> VendorUsage:
    values: dict[str, object] = {
        "vendor": Vendor.OPENROUTER,
        "operation": VendorOperation.CHAT_COMPLETION,
        "provider": "openai-compat",
        "is_success": True,
    }
    values.update(overrides)
    return VendorUsage(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The scope
# ---------------------------------------------------------------------------
def test_reading_the_context_outside_any_scope_reports_nothing_bound() -> None:
    # Act — a one-shot tool, a unit test and a health probe all call from here.
    context = current_usage_context()

    # Assert — two nulls, not an invented order.
    assert context == UsageContext(order_id=None, task=None)


def test_a_scope_binds_both_halves_of_the_attribution_for_its_block() -> None:
    # Act
    with usage_scope(order_id=_ORDER_ID, task=UsageTask.LYRICS) as bound:
        inside = current_usage_context()

    # Assert
    assert bound == inside
    assert inside.order_id == _ORDER_ID
    assert inside.task is UsageTask.LYRICS


def test_leaving_a_scope_restores_exactly_what_was_bound_before_it() -> None:
    # Arrange
    with usage_scope(order_id=_ORDER_ID, task=UsageTask.LYRICS):
        # Act — the orchestrator's per-stage wrapper is this shape: an inner scope entered
        # and left six times inside one order.
        with usage_scope(task=UsageTask.SONG):
            innermost = current_usage_context()
        after = current_usage_context()

    # Assert
    assert innermost.task is UsageTask.SONG
    assert after.task is UsageTask.LYRICS
    assert current_usage_context().order_id is None


def test_an_inner_scope_naming_only_a_task_keeps_the_order_the_outer_one_bound() -> None:
    # Arrange — this is the whole reason the pipeline can bind an order once and a task per
    # stage. If the inner scope cleared the order, every stage's spend would be unattributed.
    with usage_scope(order_id=_ORDER_ID), usage_scope(task=UsageTask.GREETING_SPEECH):
        # Act
        context = current_usage_context()

    # Assert
    assert context.order_id == _ORDER_ID
    assert context.task is UsageTask.GREETING_SPEECH


def test_the_wizards_preview_scope_carries_a_task_and_deliberately_no_order() -> None:
    # Act — the bot's lyric preview runs before an order row exists; inventing an id would
    # attribute real spend to an order that never happened.
    with usage_scope(task=UsageTask.LYRICS_PREVIEW) as bound:
        pass

    # Assert
    assert bound.task is UsageTask.LYRICS_PREVIEW
    assert bound.order_id is None


def test_a_scope_is_restored_even_when_the_block_raises() -> None:
    # Arrange / Act — a vendor call inside the scope fails often; the ContextVar must not
    # leak into whatever the worker picks up next.
    with pytest.raises(RuntimeError), usage_scope(order_id=uuid4(), task=UsageTask.SONG):
        raise RuntimeError("the vendor timed out")

    # Assert
    assert current_usage_context() == UsageContext(order_id=None, task=None)


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field_name", _QUANTITY_FIELDS)
def test_every_optional_quantity_defaults_to_none_and_never_to_zero(field_name: str) -> None:
    # Act
    default = getattr(_usage(), field_name)

    # Assert — a zero here is a measurement nobody took, and SUM() cannot tell the two apart.
    assert default is None, f"VendorUsage.{field_name} defaults to {default!r}, not None"


def test_the_two_flags_default_to_false_because_absence_of_a_flag_is_a_real_answer() -> None:
    # Act
    usage = _usage()

    # Assert — unlike the quantities, these two are booleans an adapter always knows.
    assert usage.is_fallback is False
    assert usage.is_fake is False


def test_the_record_is_frozen_so_a_measurement_cannot_be_edited_after_the_fact() -> None:
    # Arrange
    usage = _usage()

    # Act / Assert
    with pytest.raises(AttributeError):
        usage.cost_usd = 1.0  # type: ignore[misc]


def test_the_record_declares_no_field_the_row_cannot_store() -> None:
    # Arrange — VendorUsage is the row minus the columns the sink fills in itself. A field
    # added here without a column is a measurement that is logged and silently not persisted.
    from bayram.db.models.vendor_usage import VendorUsageRow

    # Act
    declared = {field.name for field in fields(VendorUsage)}
    stored = {column.name for column in VendorUsageRow.__table__.columns}

    # Assert
    assert declared <= stored, f"VendorUsage fields with no column: {sorted(declared - stored)}"


# ---------------------------------------------------------------------------
# The log line
# ---------------------------------------------------------------------------
def test_the_usage_line_carries_the_measurement_and_the_attribution_together(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    logger = logging.getLogger("tests.usage")
    usage = _usage(
        model_id="google/gemma-4-31b-it:free",
        prompt_tokens=140,
        completion_tokens=60,
        total_tokens=200,
        cost_usd=0.000123,
        cost_source=CostSource.VENDOR_REPORTED,
    )

    # Act
    with caplog.at_level(logging.INFO, logger="tests.usage"):
        log_usage(logger, usage, UsageContext(order_id=_ORDER_ID, task=UsageTask.LYRICS))

    # Assert — one grep-able event with both halves flat on it.
    record = caplog.records[-1]
    extras = _extras(record)
    assert record.message == USAGE_EVENT
    assert extras["vendor"] is Vendor.OPENROUTER
    assert extras["total_tokens"] == 200
    assert extras["cost_source"] is CostSource.VENDOR_REPORTED
    assert extras["order_id"] == str(_ORDER_ID)
    assert extras["task"] == UsageTask.LYRICS.value


def test_an_unattributed_call_logs_two_nulls_rather_than_omitting_the_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    logger = logging.getLogger("tests.usage")

    # Act — a health probe: measured, and for nobody.
    with caplog.at_level(logging.INFO, logger="tests.usage"):
        log_usage(
            logger,
            _usage(operation=VendorOperation.HEALTH),
            UsageContext(order_id=None, task=None),
        )

    # Assert — an absent key and a null key read differently in a log query.
    extras = _extras(caplog.records[-1])
    assert "order_id" in extras and extras["order_id"] is None
    assert "task" in extras and extras["task"] is None


async def test_the_default_sink_logs_the_call_with_whatever_scope_is_current(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange — every adapter's constructor defaults to this, so a caller with no database
    # still gets the measurement rather than nothing.
    sink = LoggingUsageSink()

    # Act
    with (
        caplog.at_level(logging.INFO, logger="bayram.usage"),
        usage_scope(order_id=_ORDER_ID, task=UsageTask.MODERATION),
    ):
        await sink.record(_usage())

    # Assert
    record = caplog.records[-1]
    extras = _extras(record)
    assert record.message == USAGE_EVENT
    assert extras["order_id"] == str(_ORDER_ID)
    assert extras["task"] == UsageTask.MODERATION.value


def test_the_shipped_default_sink_satisfies_the_protocol_every_adapter_declares() -> None:
    # Act / Assert — the adapters type their ctor param as UsageSink; the shared instance
    # they default to has to be one.
    assert isinstance(LOGGING_USAGE_SINK, UsageSink)


# ---------------------------------------------------------------------------
# The "may not raise" contract
# ---------------------------------------------------------------------------
class _LoggerThatFailsOnTheUsageLine:
    """Stands in for ``Logger.makeRecord`` raising on an ``extra`` key collision.

    Realistic in exactly the shape that matters: ``log_usage`` passes one ``extra`` key per
    ``VendorUsage`` field, so it is the call that can collide with a ``LogRecord``
    attribute, while the sink's own WARNING passes two keys that cannot. Hence ``info``
    raises and ``warning`` records.
    """

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        raise KeyError("Attempt to overwrite 'module' in LogRecord")

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        self.warnings.append(message)


class _SessionsNobodyShouldReach:
    """Records whether the insert was attempted. It must not be, once logging has failed."""

    def __init__(self) -> None:
        self.was_opened = False

    def begin(self) -> None:
        self.was_opened = True


async def test_a_sink_whose_logging_fails_still_returns_rather_than_failing_the_vendor_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — the persisting sink's docstring promises the WHOLE body is guarded, and an
    # adapter awaits record() on every return path including its failure paths. A sink that
    # raised would turn "the metrics row did not persist" into "the customer's song failed".
    from bayram.db import vendor_usage as sink_module

    logger = _LoggerThatFailsOnTheUsageLine()
    monkeypatch.setattr(sink_module, "_log", logger)
    sessions = _SessionsNobodyShouldReach()
    sink = sink_module.DbUsageSink(sessions)  # type: ignore[arg-type]

    # Act
    await sink.record(_usage())

    # Assert — nothing escaped, the operator can still see instrumentation is broken, and
    # the failure was caught where it happened rather than one statement later.
    assert logger.warnings == ["vendor usage row not persisted"]
    assert sessions.was_opened is False
