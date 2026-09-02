"""Exception hierarchy for HBD Bot.

Two audiences, one object:

* ``user_message_key`` is a locale key. It is the ONLY thing a customer ever sees, it is
  never interpolated with vendor text, and it is safe by construction.
* ``operator_message`` plus ``context`` is what lands in the logs. It may contain
  everything a responder needs (redaction happens in ``hbd.logging``, not here).

``is_retryable`` is part of the contract, not a guess made at the call site: the raising
layer knows whether the same call could succeed again, the retry layer does not.

This module imports nothing from the rest of the package, so anything may import it.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

__all__ = [
    "ErrorCode",
    "HbdError",
    "ConfigError",
    "ValidationError",
    "NotFoundError",
    "ModerationRejectedError",
    "ProviderError",
    "ProviderTimeoutError",
    "ProviderRateLimitedError",
    "ProviderUnavailableError",
    "ProviderQuotaExhaustedError",
    "ProviderRejectedContentError",
    "ProviderInvalidResponseError",
    "LlmParseError",
    "PipelineError",
    "NameVerificationExhaustedError",
    "AudioProcessingError",
    "StorageError",
    "DeliveryError",
    "PaymentError",
    "EntitlementError",
    "InsufficientCreditsError",
    "TooManyOrdersInFlightError",
]

#: Fallback locale key. Every localisation catalogue MUST define it.
GENERIC_USER_MESSAGE_KEY: Final[str] = "error.generic"

_EMPTY_CONTEXT: Final[Mapping[str, Any]] = MappingProxyType({})


class ErrorCode(StrEnum):
    """Our own closed taxonomy. Nothing downstream ever pattern-matches a vendor string."""

    # Configuration and input
    CONFIG_INVALID = "CONFIG_INVALID"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    CONTENT_REJECTED = "CONTENT_REJECTED"

    # Provider transport
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_5XX = "UPSTREAM_5XX"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    ARTIST_NAME_IN_STYLE = "ARTIST_NAME_IN_STYLE"
    UPSTREAM_MALFORMED = "UPSTREAM_MALFORMED"
    PARSE_FAILED = "PARSE_FAILED"

    # Pipeline
    NAME_UNVERIFIABLE = "NAME_UNVERIFIABLE"
    AUDIO_FAILED = "AUDIO_FAILED"
    STORAGE_FAILED = "STORAGE_FAILED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    PAYMENT_FAILED = "PAYMENT_FAILED"

    # Entitlement. Deliberately NOT filed under "# Provider transport" and deliberately
    # not reusing QUOTA_EXHAUSTED: that code belongs to ProviderQuotaExhaustedError, means
    # "OUR balance with a vendor is gone" and renders "error.service_unavailable". Telling
    # a customer who has simply used their allowance that the studio is down would be a
    # lie, and it would poison every vendor-failure dashboard with ordinary business
    # declines. These three are business outcomes: nothing is broken.
    CREDITS_EXHAUSTED = "CREDITS_EXHAUSTED"
    TOO_MANY_IN_FLIGHT = "TOO_MANY_IN_FLIGHT"
    ACCOUNT_BLOCKED = "ACCOUNT_BLOCKED"

    UNKNOWN = "UNKNOWN"


class HbdError(Exception):
    """Base of every error this system raises or carries inside an ``Err``.

    Instances are treated as immutable: every attribute is exposed read-only and
    ``context`` is a read-only mapping.
    """

    #: Subclasses override these two; the constructor may still override per instance.
    code: ErrorCode = ErrorCode.UNKNOWN
    default_user_message_key: str = GENERIC_USER_MESSAGE_KEY
    default_is_retryable: bool = False

    def __init__(
        self,
        operator_message: str,
        *,
        user_message_key: str | None = None,
        code: ErrorCode | None = None,
        is_retryable: bool | None = None,
        context: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(operator_message)
        self._operator_message = operator_message
        self._user_message_key = user_message_key or self.default_user_message_key
        self._code = code or self.code
        self._is_retryable = self.default_is_retryable if is_retryable is None else is_retryable
        self._context: Mapping[str, Any] = (
            MappingProxyType(dict(context)) if context else _EMPTY_CONTEXT
        )
        if cause is not None:
            self.__cause__ = cause

    # -- read-only surface --------------------------------------------------
    @property
    def operator_message(self) -> str:
        """Full-context message for logs. Never shown to a customer."""
        return self._operator_message

    @property
    def user_message_key(self) -> str:
        """Locale key resolved by the bot layer against the user's interface language."""
        return self._user_message_key

    @property
    def error_code(self) -> ErrorCode:
        return self._code

    @property
    def is_retryable(self) -> bool:
        """True when the identical call could plausibly succeed on a later attempt."""
        return self._is_retryable

    @property
    def is_terminal(self) -> bool:
        return not self._is_retryable

    @property
    def context(self) -> Mapping[str, Any]:
        """Read-only operator context. Redaction is applied by the logging layer."""
        return self._context

    def with_context(self, **extra: Any) -> HbdError:
        """Return a NEW error of the same type carrying additional context."""
        merged = {**self._context, **extra}
        clone = type(self)(
            self._operator_message,
            user_message_key=self._user_message_key,
            code=self._code,
            is_retryable=self._is_retryable,
            context=merged,
        )
        clone.__cause__ = self.__cause__
        return clone

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "error_type": type(self).__name__,
            "error_code": str(self._code),
            "operator_message": self._operator_message,
            "user_message_key": self._user_message_key,
            "is_retryable": self._is_retryable,
            "context": dict(self._context),
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self._code!s}, retryable={self._is_retryable}, "
            f"message={self._operator_message!r})"
        )


# ---------------------------------------------------------------------------
# Configuration and validation (always terminal)
# ---------------------------------------------------------------------------
class ConfigError(HbdError):
    """A required setting is missing or unusable. Raised at startup, never in a request."""

    code = ErrorCode.CONFIG_INVALID
    default_user_message_key = "error.service_unavailable"
    default_is_retryable = False


class ValidationError(HbdError):
    """Data crossing a system boundary failed schema or range validation."""

    code = ErrorCode.INVALID_INPUT
    default_user_message_key = "error.invalid_input"
    default_is_retryable = False


class NotFoundError(ValidationError):
    """A row or object the caller named does not exist, or has been purged.

    A ``ValidationError`` subclass so it inherits the terminal, non-retryable posture —
    asking again for something that is not there will not conjure it. It has its own code
    so a caller can tell "you named something that is gone" from "what you handed me was
    malformed" without string-matching a message, and so the idempotency probe that
    expects it can stay quiet instead of logging an incident on every order.
    """

    code = ErrorCode.NOT_FOUND
    default_user_message_key = "error.invalid_input"
    default_is_retryable = False


class ModerationRejectedError(HbdError):
    """Our own policy layer refused the brief."""

    code = ErrorCode.CONTENT_REJECTED
    default_user_message_key = "error.content_not_allowed"
    default_is_retryable = False


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
class ProviderError(HbdError):
    """Base for every failure attributable to a third-party vendor."""

    code = ErrorCode.UNKNOWN
    default_user_message_key = "error.provider_generic"
    default_is_retryable = False

    def __init__(
        self,
        operator_message: str,
        *,
        provider: str | None = None,
        user_message_key: str | None = None,
        code: ErrorCode | None = None,
        is_retryable: bool | None = None,
        context: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(context or {})
        if provider is not None:
            merged["provider"] = provider
        super().__init__(
            operator_message,
            user_message_key=user_message_key,
            code=code,
            is_retryable=is_retryable,
            context=merged,
            cause=cause,
        )

    @property
    def provider(self) -> str | None:
        value = self._context.get("provider")
        return value if isinstance(value, str) else None


class ProviderTimeoutError(ProviderError):
    code = ErrorCode.UPSTREAM_TIMEOUT
    default_user_message_key = "error.provider_slow"
    default_is_retryable = True


class ProviderRateLimitedError(ProviderError):
    code = ErrorCode.RATE_LIMITED
    default_user_message_key = "error.provider_busy"
    default_is_retryable = True


class ProviderUnavailableError(ProviderError):
    """5xx, connection reset, DNS failure — the vendor is down, not our payload."""

    code = ErrorCode.UPSTREAM_5XX
    default_user_message_key = "error.provider_generic"
    default_is_retryable = True


class ProviderQuotaExhaustedError(ProviderError):
    """Balance or plan quota gone. Never retried against the same provider."""

    code = ErrorCode.QUOTA_EXHAUSTED
    default_user_message_key = "error.service_unavailable"
    default_is_retryable = False


class ProviderRejectedContentError(ProviderError):
    """The vendor refused the payload on policy grounds. Never retried as-is."""

    code = ErrorCode.CONTENT_REJECTED
    default_user_message_key = "error.content_not_allowed"
    default_is_retryable = False


class ProviderInvalidResponseError(ProviderError):
    """HTTP 200 with a body that does not match the vendor's own documented shape."""

    code = ErrorCode.UPSTREAM_MALFORMED
    default_user_message_key = "error.provider_generic"
    default_is_retryable = True


class LlmParseError(ProviderError):
    """Model output survived transport but failed strip -> parse -> repair -> validate.

    Raise with the raw payload and the finish reason in ``context``; the logging layer
    truncates it. A re-prompt is usually worth one attempt, hence retryable by default.
    """

    code = ErrorCode.PARSE_FAILED
    default_user_message_key = "error.provider_generic"
    default_is_retryable = True


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class PipelineError(HbdError):
    """A stage of our own orchestration failed."""

    code = ErrorCode.UNKNOWN
    default_user_message_key = "error.generic"
    default_is_retryable = False


class NameVerificationExhaustedError(PipelineError):
    """Every configured candidate orthography failed acoustic verification.

    Terminal by design: the pipeline gives up gracefully and delivers the best attempt
    rather than burning further generations. See ``docs`` in ``hbd.contracts.NameVerdict``.
    """

    code = ErrorCode.NAME_UNVERIFIABLE
    default_user_message_key = "error.name_pronunciation_best_effort"
    default_is_retryable = False


class AudioProcessingError(PipelineError):
    code = ErrorCode.AUDIO_FAILED
    default_user_message_key = "error.generic"
    default_is_retryable = True


class StorageError(PipelineError):
    code = ErrorCode.STORAGE_FAILED
    default_user_message_key = "error.generic"
    default_is_retryable = True


class DeliveryError(PipelineError):
    """Telegram refused a send. The retry ladder reads ``is_retryable``."""

    code = ErrorCode.DELIVERY_FAILED
    default_user_message_key = "error.delivery_failed"
    default_is_retryable = True


class PaymentError(HbdError):
    """Reserved for the real rail. ``NoopPaymentProvider`` never raises it."""

    code = ErrorCode.PAYMENT_FAILED
    default_user_message_key = "error.payment_failed"
    default_is_retryable = False


# ---------------------------------------------------------------------------
# Entitlement — the customer is refused for a BUSINESS reason, not a technical one
# ---------------------------------------------------------------------------
class EntitlementError(HbdError):
    """This account may not have this render. Nothing is broken and nothing is retryable.

    ``default_is_retryable = False`` is the load-bearing attribute, not a default anyone
    should override: ``Err.is_retryable`` drives the ARQ ladder in ``hbd.runtime.jobs``, so
    a retryable refusal would re-run the whole pipeline on a schedule for a customer whose
    answer cannot change until an operator or the calendar changes it.

    Raised **directly** for a barred account, which is why the base carries a user message
    of its own rather than the generic one: a block is the one entitlement refusal with no
    number attached to it, so it has no subclass to carry a count. The two refusals that do
    carry numbers subclass it below, and every caller that only needs "was this a business
    decline?" catches this type.
    """

    code = ErrorCode.ACCOUNT_BLOCKED
    default_user_message_key = "error.blocked"
    default_is_retryable = False


class InsufficientCreditsError(EntitlementError):
    """The allowance is spent. ``context`` must say by how much and when it reopens.

    The gate that renders this has exactly one chance to be useful, so the writer is
    expected to pass ``balance``, ``needed`` and ``next_grant_at`` as scalars — a refusal
    that says only "no" sends the customer to support, and the allowance is rolling, so
    "the next one opens on <date>" is both actionable and true.
    """

    code = ErrorCode.CREDITS_EXHAUSTED
    default_user_message_key = "error.credits_exhausted"
    default_is_retryable = False


class TooManyOrdersInFlightError(EntitlementError):
    """A render this account already paid for has not finished yet.

    Terminal for *this* attempt even though the situation clears on its own: retrying it
    inside the queue would burn the retry budget waiting for an unrelated job, and the
    customer can simply press again when their song arrives.
    """

    code = ErrorCode.TOO_MANY_IN_FLIGHT
    default_user_message_key = "error.too_many_in_flight"
    default_is_retryable = False
