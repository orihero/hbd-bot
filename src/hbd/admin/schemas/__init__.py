"""Request and response models for the admin API. One module per resource.

Everything inherits :class:`hbd.admin.schemas.common.ApiModel`, which fixes the three things
that must not vary per endpoint: camelCase on the wire, ``extra="forbid"`` on the way in, and
frozen instances so a serializer cannot quietly edit a response it was handed.
"""

from __future__ import annotations

from hbd.admin.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    PasswordChangeRequest,
    StepUpRequest,
    StepUpResponse,
)
from hbd.admin.schemas.chats import (
    ChatConversationItem,
    ChatConversationsResponse,
    ChatMessageView,
    ChatTranscriptResponse,
)
from hbd.admin.schemas.common import (
    MAX_PASSWORD_CHARS,
    MIN_PASSWORD_CHARS,
    ApiModel,
    ErrorBody,
    ErrorEnvelope,
)
from hbd.admin.schemas.overview import (
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
from hbd.admin.schemas.vendors import (
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
