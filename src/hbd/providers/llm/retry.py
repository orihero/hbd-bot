"""Re-prompt on a parse failure. One narrow job, deliberately.

A stochastic source often succeeds on the second ask, so ``PARSE_FAILED`` — and only
``PARSE_FAILED`` — earns another attempt here, bounded by ``Settings.llm_parse_max_attempts``
and carrying a nudge that tells the model what went wrong.

Transport failures are *not* retried here. Timeouts, 429s and 5xx belong to the pipeline's
provider retry ladder, which owns the backoff and the jitter; duplicating that bound inside
the adapter layer would multiply the two together.
"""

from __future__ import annotations

from pydantic import BaseModel

from hbd.contracts import Err, LlmProvider, LlmRequest, Result
from hbd.errors import ErrorCode
from hbd.logging import get_logger
from hbd.providers.llm.prompt_loader import load_prompt

__all__ = ["generate_with_retry", "RETRY_NUDGE_PROMPT"]

_LOG = get_logger(__name__)

RETRY_NUDGE_PROMPT: str = "retry_nudge"


def _nudged(request: LlmRequest) -> LlmRequest:
    """A NEW request whose system prompt carries the "that was not JSON" reminder."""
    return request.model_copy(
        update={"system_prompt": request.system_prompt + load_prompt(RETRY_NUDGE_PROMPT)}
    )


async def generate_with_retry[M: BaseModel](
    provider: LlmProvider,
    request: LlmRequest,
    response_model: type[M],
    *,
    timeout_s: float,
    max_attempts: int,
) -> Result[M]:
    """Call ``generate_json`` up to ``max_attempts`` times, re-prompting on parse failure.

    Returns the last ``Err`` when every attempt fails. Never raises.
    """
    attempts = max(1, max_attempts)
    outcome = await provider.generate_json(request, response_model, timeout_s=timeout_s)
    for attempt in range(2, attempts + 1):
        if not isinstance(outcome, Err) or outcome.error.error_code is not ErrorCode.PARSE_FAILED:
            return outcome
        _LOG.warning(
            "re-prompting %s for %s after a parse failure (attempt %d of %d)",
            provider.name,
            response_model.__name__,
            attempt,
            attempts,
            extra={"provider": provider.name, "attempt": attempt, "max_attempts": attempts},
        )
        outcome = await provider.generate_json(
            _nudged(request), response_model, timeout_s=timeout_s
        )
    return outcome
