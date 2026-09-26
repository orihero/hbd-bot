"""Request and response models for the admin API. One module per resource.

Everything inherits :class:`bayram.admin.schemas.common.ApiModel`, which fixes the three things
that must not vary per endpoint: camelCase on the wire, ``extra="forbid"`` on the way in, and
frozen instances so a serializer cannot quietly edit a response it was handed.

**THIS FILE RE-EXPORTS ONLY THE MODULES THAT IMPORT NO WEB FRAMEWORK, and the omissions are
the rule rather than an oversight.** ``billing``, ``broadcasts``, ``credits``, ``orders`` and
``users`` are absent because each imports :mod:`bayram.admin.schemas.page`, whose ``Paging``
alias is an ``Annotated[..., Depends(...)]`` and therefore imports FastAPI at module scope.
The WORKER reaches into this package — ``bayram.runtime.broadcast_job`` decodes a stored
segment with :mod:`bayram.admin.schemas.segment`, deliberately, so the campaign that goes out
is parsed by the same models the operator previewed — and importing a submodule executes this
file first. A re-export added here therefore puts Starlette, FastAPI and the whole request
machinery into a process that must never serve HTTP;
``test_the_worker_decodes_a_stored_segment_without_importing_a_web_framework`` fails on it, in
a subprocess, because by then this interpreter has already imported the admin app.

Adding one is not forbidden, it is just not free: import the module directly
(``from bayram.admin.schemas.billing import SettlementView``) as every router already does.
"""

from __future__ import annotations

from bayram.admin.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    PasswordChangeRequest,
    StepUpRequest,
    StepUpResponse,
)
from bayram.admin.schemas.chats import (
    ChatConversationItem,
    ChatConversationsResponse,
    ChatMessageView,
    ChatTranscriptResponse,
)
from bayram.admin.schemas.common import (
    MAX_PASSWORD_CHARS,
    MIN_PASSWORD_CHARS,
    ApiModel,
    ErrorBody,
    ErrorEnvelope,
)
from bayram.admin.schemas.overview import (
    AbsenceReason,
    AudienceResponse,
    ComponentState,
    FinanceResponse,
    MoneyTotal,
    PerformanceResponse,
    PlanLiabilityResponse,
    RatioView,
    SeriesBucket,
    SeriesResponse,
    TrendView,
    UsdCost,
)
from bayram.admin.schemas.vendors import (
    MIXED_COST_SOURCE,
    VendorErrorView,
    VendorUsagePerDayView,
    VendorUsageResponse,
    VendorUsageRollupView,
    VendorUsageTotalsView,
    to_vendor_error_view,
    to_vendor_usage_per_day_view,
    to_vendor_usage_response,
    to_vendor_usage_rollup_view,
    to_vendor_usage_totals_view,
)

__all__ = [
    "ApiModel",
    "ErrorBody",
    "ErrorEnvelope",
    "MIN_PASSWORD_CHARS",
    "MAX_PASSWORD_CHARS",
    "LoginRequest",
    "LoginResponse",
    "MeResponse",
    "PasswordChangeRequest",
    "StepUpRequest",
    "StepUpResponse",
    "AbsenceReason",
    "AudienceResponse",
    "ComponentState",
    "FinanceResponse",
    "MoneyTotal",
    "PerformanceResponse",
    "PlanLiabilityResponse",
    "RatioView",
    "SeriesBucket",
    "SeriesResponse",
    "TrendView",
    "UsdCost",
    "MIXED_COST_SOURCE",
    "VendorErrorView",
    "VendorUsagePerDayView",
    "VendorUsageResponse",
    "VendorUsageRollupView",
    "VendorUsageTotalsView",
    "ChatConversationItem",
    "ChatConversationsResponse",
    "ChatMessageView",
    "ChatTranscriptResponse",
    "to_vendor_error_view",
    "to_vendor_usage_per_day_view",
    "to_vendor_usage_response",
    "to_vendor_usage_rollup_view",
    "to_vendor_usage_totals_view",
]
