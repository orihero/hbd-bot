"""``GET /api/metrics/vendor-*`` — what each vendor was asked to do, and what it cost.

Three reads, no writes, and this is the first surface in the panel that puts a dollar figure
on screen at all. ``routers/dashboard.py`` refuses to, and its refusal is still right for the
table it reads: ``generation_attempts.cost_usd`` defaults to ``0.0``, so every row there
carries a cost nobody measured and charting it would be a confident lie about money. Nothing
changed about that judgement — a different table was built. ``vendor_usage`` declares no
default on any quantity column, so an unmeasured group arrives here as ``NULL`` from
``SUM()`` and reaches the SPA as ``null``, which renders as "not priced" and never as a
number.

**The rate card is partial out of the box, and every response here is shaped around that.**
Music ships priced — ``music_usd_per_minute`` defaults to a placeholder ``0.15``, so the
first rendered song produces a real dollar figure reported as ``ESTIMATED`` — while speech,
transcription and both LLM legs stay unpriced until an operator configures a rate, and
Scribe has no rate to configure at all. So a typical window's ``costUsd`` is a true sum over
a MINORITY of the calls it sits beside, which is why ``costedCalls`` travels with every
total and ``costSource`` with every row: without them the tile reads as the deployment's
spend, and it is a sample whose size the operator cannot see.

**The window is asked for, never assumed.** Either end alone is enough
(:func:`~hbd.admin.window.resolve_window`): ``?from=`` is counted up to the instant the
request was served and ``?to=`` leaves the series open below. The response echoes the range
it counted over, so a chart drawn from one bound stays reproducible from the answer. A naive
instant is a 422 naming the parameter, because ``UtcDateTime`` would otherwise raise inside
the driver's bind processor where no handler is waiting.

**``?vendor=`` repeats, and repeating it widens.** OR within the field, AND across fields
(§6.1), typed as :class:`~hbd.contracts.Vendor` so an unknown value is a 422 from FastAPI
rather than a filter that quietly matches nothing. No values at all means no filter — never
``IN ()``, which is the query that returns an empty page and looks like an answer.

**Two of the three flags on ``/vendor-usage`` deliberately ignore the window.**
``isInstrumented`` and ``isCostPriced`` are probes over the whole table; ``hasRowsInWindow``
is the windowed one. That is what lets the SPA tell three empties apart — nothing recorded
in this deployment, recorded but not one call priced, and nothing in the range you chose —
which §11.4 renders as three screens with three different remedies. ``rows: []`` alone
cannot say which, and a zero-filled chart says the wrong one. ``isCostPriced`` false is the
narrow case rather than the shipped one, given the music rate above: it describes a
deployment that has moderated and written lyrics and never rendered a song.

**A day with no calls is absent from ``/vendor-usage-by-day``**, not present at zero. Same
rule as the dashboard's day series and for a sharper reason: a zero bar here is a claim
about money we did not spend on a day this deployment may not have existed on.

**These three routes now EXCLUDE fake-provider rows, and that is a behaviour change.**
``_narrow`` applies ``is_fake IS false`` by default (see
:mod:`hbd.db.admin.vendor_usage`), so a ``HBD_USE_FAKE_PROVIDERS`` demo no longer inflates
the spend, the success rate, the average latency or the error breakdown on this surface.
``?includeFake=true`` is how a demo run stays inspectable, and ``?excludeHealth=true`` drops
the balance poller's hourly quota probes for an operator reading the rollup as an invoice.

**No new ``Permission`` member.** §12.3 already classes costs and latencies as always-visible
non-personal data, and every column this surface reads is a closed enum, an integer, a
machine id or a bounded error code — no name, no note, no transcript, no telegram id. So
DASHBOARD_READ is the cell, there is no masking decision to make, no serializer to route
through and no unmasked variant of any response. A ``VENDOR_READ`` member would have been a
five-file change across two languages buying a distinction nobody can act on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from hbd.admin.deps import API_PREFIX, Db, require_permission
from hbd.admin.schemas.vendors import (
    VendorErrorView,
    VendorUsagePerDayView,
    VendorUsageResponse,
    to_vendor_error_view,
    to_vendor_usage_per_day_view,
    to_vendor_usage_response,
)
from hbd.admin.security.permissions import Permission
from hbd.admin.window import resolve_window
from hbd.contracts import Vendor, VendorOperation
from hbd.db.admin.sql import TimeWindow
from hbd.db.admin.vendor_usage import (
    SPENDABLE_EXCLUSIONS,
    has_priced_vendor_usage,
    has_recorded_vendor_usage,
    vendor_error_breakdown,
    vendor_usage_per_day,
    vendor_usage_rollup,
    vendor_usage_totals,
)
from hbd.db.base import utc_now

__all__ = [
    "VENDOR_ERRORS_PATH",
    "VENDOR_USAGE_BY_DAY_PATH",
    "VENDOR_USAGE_PATH",
    "build_vendors_router",
]

#: Full paths, built from the prefix rather than written as literals. Routers here are
#: included without one, because the forced-rotation gate compares ``scope["route"].path``
#: against absolute paths.
VENDOR_USAGE_PATH: Final[str] = f"{API_PREFIX}/metrics/vendor-usage"
VENDOR_USAGE_BY_DAY_PATH: Final[str] = f"{API_PREFIX}/metrics/vendor-usage-by-day"
VENDOR_ERRORS_PATH: Final[str] = f"{API_PREFIX}/metrics/vendor-errors"


def build_window(
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> TimeWindow | None:
    """``?from=&to=`` as a dependency, or ``None`` for the whole record.

    Declared here rather than imported from ``routers/dashboard.py``, which has an identical
    one. That is not duplication left in by accident: the clock is read from **this
    module's** globals, which is this package's uniform per-router seam for moving time in a
    test (``monkeypatch.setattr(vendors_router, "utc_now", ...)``, the shape
    ``tests/test_admin/test_asset_stream.py`` uses against ``assets``). Importing another
    router's dependency would move that seam onto a module a test patching this one has no
    reason to touch, and would put every windowed route in the panel behind one clock.
    """
    return resolve_window(since, until, now=utc_now())


def build_vendors(
    vendor: Annotated[list[Vendor] | None, Query(alias="vendor")] = None,
) -> tuple[Vendor, ...]:
    """``?vendor=`` repeated, as a tuple. Empty means "no filter", never "match none".

    The asymmetry :func:`~hbd.db.admin.sql.apply_in` documents, made explicit at the edge:
    an absent parameter and an empty list are the same request — show me every vendor —
    and a tuple is what the read layer takes, so the ``None`` is normalised once here rather
    than in each of the three handlers.
    """
    return tuple(vendor or ())


def build_include_fake(
    include_fake: Annotated[bool, Query(alias="includeFake")] = False,
) -> bool:
    """``?includeFake=`` — whether a ``HBD_USE_FAKE_PROVIDERS`` run is counted. Default false.

    **The default on these three routes CHANGED**, and this parameter is what keeps that from
    being a loss. ``_narrow`` now excludes ``is_fake`` rows structurally, so a demo run no
    longer inflates ``costUsd``, ``calls``, ``successRate``, ``avgLatencyMs`` or the error
    breakdown — which is the fix. But ``Vendor.FAKE`` exists so a demo is recorded and
    VISIBLY excluded, and "visibly" means there is a way to look at it. Without the opt-in
    the change would turn a demo from "silently inflating spend" into "silently invisible",
    which is the same defect facing the other way.
    """
    return include_fake


def build_exclude_health(
    exclude_health: Annotated[bool, Query(alias="excludeHealth")] = False,
) -> tuple[VendorOperation, ...]:
    """``?excludeHealth=`` — drop the balance poller's hourly quota probes. Default false.

    False by default here and true inside every SPEND query, and the asymmetry is deliberate.
    A quota probe is a real call to a real vendor, so it belongs in a reachability breakdown
    — an operator asking "is ElevenLabs answering us" wants those rows. It is not spend, so
    ``cost_per_delivered_song`` and ``vendor_spend_split`` name
    :data:`~hbd.db.admin.vendor_usage.SPENDABLE_EXCLUSIONS` in their own bodies rather than
    leaving it to a caller. This flag is for an operator reading the invoice-shaped rollup
    who wants the probes out of the way.
    """
    return SPENDABLE_EXCLUSIONS if exclude_health else ()


#: The four dependency aliases every route on this surface annotates with.
Window = Annotated[TimeWindow | None, Depends(build_window)]
Vendors = Annotated[tuple[Vendor, ...], Depends(build_vendors)]
IncludeFake = Annotated[bool, Depends(build_include_fake)]
ExcludeHealth = Annotated[tuple[VendorOperation, ...], Depends(build_exclude_health)]


def build_vendors_router() -> APIRouter:
    """The vendor spend surface. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["vendors"],
        dependencies=[Depends(require_permission(Permission.DASHBOARD_READ))],
    )

    @router.get(VENDOR_USAGE_PATH)
    async def vendor_usage(
        db: Db,
        window: Window,
        vendors: Vendors,
        include_fake: IncludeFake,
        exclude_health: ExcludeHealth,
    ) -> VendorUsageResponse:
        """The breakdown, its totals, and the three flags that make an empty one readable.

        Four round trips and each answers a question the others cannot. The two probes ignore
        the window on purpose — see the module docstring — and the totals are their own query
        rather than a fold over ``rows``, because summing groups in Python means deciding
        what ``None + None`` is, and every answer but "leave it null" invents a zero on the
        one tile an operator budgets against.
        """
        totals = await vendor_usage_totals(
            db,
            window=window,
            vendors=vendors,
            include_fake=include_fake,
            exclude_operations=exclude_health,
        )
        return to_vendor_usage_response(
            window=window,
            is_instrumented=await has_recorded_vendor_usage(db),
            is_cost_priced=await has_priced_vendor_usage(db),
            totals=totals,
            rows=await vendor_usage_rollup(
                db,
                window=window,
                vendors=vendors,
                include_fake=include_fake,
                exclude_operations=exclude_health,
            ),
        )

    @router.get(VENDOR_USAGE_BY_DAY_PATH)
    async def vendor_usage_by_day(
        db: Db,
        window: Window,
        vendors: Vendors,
        include_fake: IncludeFake,
        exclude_health: ExcludeHealth,
    ) -> list[VendorUsagePerDayView]:
        """Calls and spend per UTC day per vendor, oldest first.

        A ``(day, vendor)`` pair with no calls is absent from the array rather than present
        at zero, and this layer does not fill the gaps: ``from``/``to`` are optional, so it
        frequently does not know what range is being charted. The SPA, which does, is where
        a chart decides what to draw for a day it asked about and got nothing for.
        """
        return [
            to_vendor_usage_per_day_view(day)
            for day in await vendor_usage_per_day(
                db,
                window=window,
                vendors=vendors,
                include_fake=include_fake,
                exclude_operations=exclude_health,
            )
        ]

    @router.get(VENDOR_ERRORS_PATH)
    async def vendor_errors(
        db: Db,
        window: Window,
        vendors: Vendors,
        include_fake: IncludeFake,
        exclude_health: ExcludeHealth,
    ) -> list[VendorErrorView]:
        """Failed calls by ``(vendor, errorCode)``, largest first, with each code's share.

        The share is of THAT vendor's failures. "What is going wrong with ElevenLabs" is the
        question, and a denominator spanning every vendor answers a different one — a vendor
        with one broken call would report a share near zero simply because another vendor was
        busy.
        """
        return [
            to_vendor_error_view(error)
            for error in await vendor_error_breakdown(
                db,
                window=window,
                vendors=vendors,
                include_fake=include_fake,
                exclude_operations=exclude_health,
            )
        ]

    return router
