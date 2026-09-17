"""Wire models for ``/metrics/vendor-*`` — the one screen that is entirely about money.

The dashboard's rule was "a rate with no denominator is ``null``". This surface adds a
second one that is stricter, because the numbers here are dollars rather than percentages:

**A quantity nobody measured is ``null``, and it is null all the way from the column.**
``vendor_usage`` declares no default on any quantity column, ``SUM()`` over a group of NULLs
returns NULL, and nothing between that column and this model coalesces. So ``totalTokens``
comes back ``null`` for a group of speech syntheses — which never had tokens — rather than
``0``, which would say the vendor billed us for a completion that used none. The SPA renders
``null`` as "no data" and ``isCostPriced: false`` as "not priced"; neither renders as a
figure, which is the point.

**``costUsd`` and ``costedCalls`` are one fact in two fields and never travel apart.** The
sum covers the priced rows alone, so a window in which nine of nine hundred calls carried a
rate produces a real dollar total over a tenth of a percent of the traffic. Without the
second number that total is a budget an operator would act on; with it, it is a sample they
can see the size of. That ratio is the shipped case and not a pathological one: the music
leg is priced out of the box from ``music_usd_per_minute``'s placeholder ``0.15`` and
reports ``ESTIMATED``, while speech, transcription and both LLM legs write no cost at all
until a rate is configured — so the very first song makes ``costUsd`` non-null over a
fraction of the calls in the window, and the pairing is what keeps that honest.

**``costSource`` is a string here and an enum everywhere behind it.** ``"mixed"`` is not a
:class:`~bayram.contracts.CostSource` member and must not become one: it is a statement about a
GROUP — that its priced calls did not all arrive at their figure the same way — and inventing
a fourth provenance member would let a single row claim it. The domain model carries
``cost_source`` and ``is_cost_mixed`` separately and this layer is where they collapse.

**Two capability flags, both measured, both deliberately window-blind.**
``isInstrumented`` says a ``vendor_usage`` row exists at all and ``isCostPriced`` says one
carries a cost; ``hasRowsInWindow`` is the only windowed one of the three. That is what lets
the SPA tell three different empties apart — nothing recorded here, recorded but not one
call priced, and nothing in the range you chose — which §11.4 renders as three screens with
three different remedies. A single ``rows: []`` cannot say which. ``isCostPriced: false``
does NOT describe a fresh deployment: music is priced from a placeholder rate, so the flag
is true from the first rendered song and false only where nothing has rendered one yet.

**Nothing here is personal data.** Vendors, operations, model ids, counts, UTC days and
error codes — no name, no note, no transcript, no telegram id — so there is no masking
decision on this surface and no unmasked variant of any response.
"""

from __future__ import annotations

from datetime import date
from typing import Final

from bayram.admin.schemas.common import ApiModel
from bayram.admin.schemas.dashboard import WindowView, to_window_view
from bayram.contracts import CostSource, Vendor, VendorOperation
from bayram.db.admin.sql import TimeWindow
from bayram.db.admin.views import (
    VendorErrorCount,
    VendorUsagePerDay,
    VendorUsageRollup,
    VendorUsageTotals,
)

__all__ = [
    "MIXED_COST_SOURCE",
    "VendorErrorView",
    "VendorUsagePerDayView",
    "VendorUsageResponse",
    "VendorUsageRollupView",
    "VendorUsageTotalsView",
    "to_vendor_error_view",
    "to_vendor_usage_per_day_view",
    "to_vendor_usage_response",
    "to_vendor_usage_rollup_view",
    "to_vendor_usage_totals_view",
    "cost_source_of",
]

#: What a group whose priced calls disagree about provenance reports. A wire value and NOT a
#: ``CostSource`` member: it describes a group, and a member would let one row claim it.
MIXED_COST_SOURCE: Final[str] = "mixed"


class VendorUsageTotalsView(ApiModel):
    """The window collapsed to one row — the hero tile's whole source.

    Every quantity is nullable and none of them is nullable defensively: a deployment that
    only ever calls an LLM has no ``billedCharacters`` to report and one that only renders
    music has no ``totalTokens``. ``null`` is the true answer in both directions.
    """

    calls: int
    successes: int
    failures: int
    #: ``null`` when ``calls`` is 0. An empty window has no success rate, not a bad one.
    success_rate: float | None
    #: Summed over priced rows only — read it with ``costedCalls``, never without.
    cost_usd: float | None
    #: How many of ``calls`` carried a cost at all.
    costed_calls: int
    #: ``"vendor_reported"`` | ``"derived"`` | ``"estimated"`` | ``"mixed"`` | ``null``, on the
    #: hero tile as well as on every row. Without it the one number an operator budgets
    #: against could not say whether it came from an invoice or from arithmetic against the
    #: placeholder ``music_usd_per_minute`` rate.
    cost_source: str | None
    total_tokens: int | None
    billed_characters: int | None
    audio_ms: int | None
    avg_latency_ms: int | None


class VendorUsageRollupView(ApiModel):
    """One ``(vendor, operation, modelId)`` group.

    The group key is the invoice's shape: ElevenLabs bills music by the minute, speech by
    the character and transcription by the minute of audio, so a per-vendor row alone would
    mix three units and reconcile against nothing. ``modelId`` joins the key because a rate
    card is quoted per model.
    """

    vendor: Vendor
    operation: VendorOperation
    #: The vendor's own id, not one of our enums — rendered as raw text, never humanised.
    model_id: str | None
    calls: int
    successes: int
    failures: int
    success_rate: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    billed_characters: int | None
    audio_ms: int | None
    cost_usd: float | None
    #: ``"vendor_reported"`` | ``"derived"`` | ``"estimated"`` | ``"mixed"`` | ``null``. See
    #: the module docstring on why ``"mixed"`` is a string and not an enum member.
    cost_source: str | None
    costed_calls: int
    avg_latency_ms: int | None
    max_latency_ms: int | None


class VendorUsageResponse(ApiModel):
    """``GET /api/metrics/vendor-usage`` — the breakdown, its totals, and three empties.

    ``isInstrumented`` and ``isCostPriced`` ignore the window; ``hasRowsInWindow`` is the
    windowed one. The three together are what let an empty table render as a sentence an
    operator can act on rather than as a grid of dashes.
    """

    #: Echoed so an empty state can name the range it found nothing in. ``null`` for all time.
    window: WindowView | None
    #: Any ``vendor_usage`` row exists at all. Window deliberately ignored.
    is_instrumented: bool
    #: Any row carries a cost. Window deliberately ignored — an unpriced deployment says
    #: "not priced" whatever range is being looked at.
    is_cost_priced: bool
    #: The windowed one of the three. False with ``isInstrumented`` true means "widen it".
    has_rows_in_window: bool
    totals: VendorUsageTotalsView
    #: Busiest first, then vendor, operation and model id. Never ordered by cost — a
    #: nullable sort key orders differently on SQLite and Postgres.
    rows: list[VendorUsageRollupView]


class VendorUsagePerDayView(ApiModel):
    """One vendor's calls and spend on one UTC day.

    A ``(day, vendor)`` pair with no calls is ABSENT from the array rather than present at
    zero: the server does not always know what range the caller wants charted, and a
    zero-filled day is a claim that we spent nothing on a day we may not have existed on.
    """

    day: date
    vendor: Vendor
    calls: int
    cost_usd: float | None
    costed_calls: int


class VendorErrorView(ApiModel):
    """One error code's share of one vendor's failures in the window."""

    vendor: Vendor
    #: ``null`` groups every failure whose writer recorded no code.
    error_code: str | None
    count: int
    #: Of THAT vendor's failures, not of every vendor's.
    share: float


# ---------------------------------------------------------------------------
# projections
# ---------------------------------------------------------------------------
def to_vendor_usage_totals_view(totals: VendorUsageTotals) -> VendorUsageTotalsView:
    """Project the totals. The rate comes off the view model and is never recomputed."""
    return VendorUsageTotalsView(
        calls=totals.calls,
        successes=totals.successes,
        failures=totals.failures,
        success_rate=totals.success_rate,
        cost_usd=totals.cost_usd,
        costed_calls=totals.costed_calls,
        cost_source=cost_source_of(totals.cost_source, is_mixed=totals.is_cost_mixed),
        total_tokens=totals.total_tokens,
        billed_characters=totals.billed_characters,
        audio_ms=totals.audio_ms,
        avg_latency_ms=totals.avg_latency_ms,
    )


def to_vendor_usage_rollup_view(rollup: VendorUsageRollup) -> VendorUsageRollupView:
    """Project one group, collapsing its two provenance facts into the one wire field.

    ``is_cost_mixed`` wins over ``cost_source`` because a group that mixes has no single
    honest source to name: reporting the ``MIN`` of the two would tell the panel every call
    in the group was vendor-reported when half of them were arithmetic over a rate card.
    """
    return VendorUsageRollupView(
        vendor=rollup.vendor,
        operation=rollup.operation,
        model_id=rollup.model_id,
        calls=rollup.calls,
        successes=rollup.successes,
        failures=rollup.failures,
        success_rate=rollup.success_rate,
        prompt_tokens=rollup.prompt_tokens,
        completion_tokens=rollup.completion_tokens,
        total_tokens=rollup.total_tokens,
        billed_characters=rollup.billed_characters,
        audio_ms=rollup.audio_ms,
        cost_usd=rollup.cost_usd,
        cost_source=cost_source_of(rollup.cost_source, is_mixed=rollup.is_cost_mixed),
        costed_calls=rollup.costed_calls,
        avg_latency_ms=rollup.avg_latency_ms,
        max_latency_ms=rollup.max_latency_ms,
    )


def to_vendor_usage_per_day_view(day: VendorUsagePerDay) -> VendorUsagePerDayView:
    return VendorUsagePerDayView(
        day=day.day,
        vendor=day.vendor,
        calls=day.calls,
        cost_usd=day.cost_usd,
        costed_calls=day.costed_calls,
    )


def to_vendor_error_view(error: VendorErrorCount) -> VendorErrorView:
    return VendorErrorView(
        vendor=error.vendor,
        error_code=error.error_code,
        count=error.count,
        share=error.share,
    )


def to_vendor_usage_response(
    *,
    window: TimeWindow | None,
    is_instrumented: bool,
    is_cost_priced: bool,
    totals: VendorUsageTotals,
    rows: tuple[VendorUsageRollup, ...],
) -> VendorUsageResponse:
    """Assemble the one response. Keyword-only: five arguments of five different shapes.

    ``hasRowsInWindow`` is derived from the totals rather than taken as a sixth argument —
    "the window holds calls" and "the window's call count is above zero" are the same fact,
    and passing it separately would let a caller ship a response that disagreed with itself.
    """
    return VendorUsageResponse(
        window=to_window_view(window),
        is_instrumented=is_instrumented,
        is_cost_priced=is_cost_priced,
        has_rows_in_window=totals.calls > 0,
        totals=to_vendor_usage_totals_view(totals),
        rows=[to_vendor_usage_rollup_view(row) for row in rows],
    )


def cost_source_of(source: CostSource | None, *, is_mixed: bool) -> str | None:
    """``"mixed"``, the group's one source, or ``null`` when nothing in it was priced.

    ``is_mixed`` wins over ``source`` because a group that mixes has no single honest source
    to name: reporting the ``MIN`` of the two would tell the panel every call in the group
    was vendor-reported when half of them were arithmetic over a rate card.

    Public rather than private because the dashboard's finance section collapses the same
    two facts into the same one wire field, and a second spelling of this rule is how the
    two surfaces come to disagree about what "mixed" means.
    """
    if is_mixed:
        return MIXED_COST_SOURCE
    return None if source is None else source.value
