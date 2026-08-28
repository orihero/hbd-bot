"""The policy gate, run before a single cent is spent on generation.

Two layers, cheapest first:

1. A local denylist over the free-text note. It costs nothing, catches the obvious, and
   works when the LLM is down.
2. The model itself, asked for a strict JSON verdict.

Fail-open is deliberate on *transport* failure and fail-closed on a *verdict*. If the LLM
cannot be reached we do not hold a paying customer hostage to a moderation outage — the
note is short, the local list already ran, and the downstream vendors moderate their own
inputs. If the LLM answers and says no, that is a decision, and it is honoured.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict

from hbd.config import Settings
from hbd.contracts import Brief, Err, LlmProvider, LlmRequest, Result, err, ok
from hbd.errors import ModerationRejectedError
from hbd.logging import get_logger
from hbd.pipeline.prompts import moderation_system_prompt, moderation_user_prompt

__all__ = ["ModerationPayload", "LlmModerator", "AllowAllModerator", "LOCAL_DENY_PATTERNS"]

_LOGGER = get_logger(__name__)

#: Deliberately narrow. This is a tripwire for unmistakable abuse, not a censor — the
#: model does the nuanced judging, and a false positive here costs us a real order.
LOCAL_DENY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(kill|murder|rape|bomb)\b", re.IGNORECASE),
    re.compile(r"\b(nazi|jihad|terrorist)\b", re.IGNORECASE),
    re.compile(r"\b(o['ʻ‘’]ldir|jinoyat)\b", re.IGNORECASE),
    re.compile(r"\b(убить|изнасил|террорист)", re.IGNORECASE),
)

#: How much of a rejected note to keep in the log. Enough to triage, not the whole essay.
REJECTED_NOTE_LOG_CHARS: Final[int] = 200


class ModerationPayload(BaseModel):
    """The model's verdict. Tolerant of extra keys, strict about the two that matter."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    is_allowed: bool = True
    reason: str = ""


def _local_hit(text: str) -> str | None:
    for pattern in LOCAL_DENY_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return match.group(0)
    return None


class AllowAllModerator:
    """No-op gate. For replays and for tests that are not about moderation."""

    async def review(self, brief: Brief) -> Result[None]:
        return ok(None)


class LlmModerator:
    """Local denylist, then a strict-JSON verdict from the LLM."""

    def __init__(self, llm: LlmProvider, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def review(self, brief: Brief) -> Result[None]:
        subject = f"{brief.recipient.display} {brief.note}"
        hit = _local_hit(subject)
        if hit is not None:
            return err(
                ModerationRejectedError(
                    "brief rejected by the local denylist",
                    context={"pattern_hit": hit, "note": brief.note[:REJECTED_NOTE_LOG_CHARS]},
                )
            )

        request = LlmRequest(
            system_prompt=moderation_system_prompt(),
            user_prompt=moderation_user_prompt(brief),
            temperature=0.0,
            max_output_tokens=self._settings.llm_max_output_tokens,
        )
        result = await self._llm.generate_json(
            request, ModerationPayload, timeout_s=self._settings.llm_timeout_s
        )
        if isinstance(result, Err):
            _LOGGER.warning(
                "moderation call failed; allowing the brief on the local verdict alone",
                extra=result.error.to_log_dict(),
            )
            return ok(None)

        verdict = result.value
        if verdict.is_allowed:
            return ok(None)
        return err(
            ModerationRejectedError(
                "brief rejected by the moderation model",
                context={
                    "reason": verdict.reason[:REJECTED_NOTE_LOG_CHARS],
                    "note": brief.note[:REJECTED_NOTE_LOG_CHARS],
                },
            )
        )
