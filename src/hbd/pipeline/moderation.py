"""The policy gate, run before a single cent is spent on a *vendor* rendering.

Where it sits is worth being honest about. The gate runs inside the pipeline, so it is
still ahead of every music and speech call — but it is no longer ahead of everything. The
wizard now drafts a lyric from the note so the customer can approve it, and the customer
authorises payment before the job is queued. So an abusive note reaches the writing model,
and a rejected brief fails after authorisation rather than before it. That is a deliberate
trade for a preview step the product wanted; it is not an oversight, and moving the gate
into the wizard is the change to make if the trade stops being acceptable.

Two layers, cheapest first:

1. A local denylist over the free text — the note, and the lyric when the customer wrote
   or pasted their own. It costs nothing, catches the obvious, and works when the LLM is
   down.
2. The model itself, asked for a strict JSON verdict.

A pasted lyric is reviewed for the same reason the note is: it is user free text, it goes
verbatim to a music vendor, and it *is* the delivered product. Because a denylist hit can
now come from three places, the error carries ``hit_in`` so an operator triaging a false
positive can tell a name from a note from a whole song without guessing.

Fail-open on *transport* failure is deliberate, and it is now conditional. If the LLM
cannot be reached on a brief whose text is only the note, we do not hold a paying customer
hostage to a moderation outage: the note is short, the local list already ran, the note is
never rendered verbatim, and the downstream vendors moderate their own inputs. None of
those four reasons survives when the customer wrote the lyric — up to three thousand
characters that go to the music vendor unaltered and come back as the product. So a brief
carrying an approved lyric fails CLOSED on a transport failure. The error is retryable, so
the worker's ladder gets another attempt at the model rather than the order dying on one
timeout. If the LLM answers and says no, that is a decision, and it is honoured either way.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict

from hbd.config import Settings
from hbd.contracts import Brief, Err, LlmProvider, LlmRequest, Result, err, ok
from hbd.errors import HbdError, ModerationRejectedError
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


def _hit_source(hit: str, *, name: str, note: str, lyrics: str) -> str:
    """Which of the three free-text fields the denylist actually landed in.

    Triage only. The scan itself runs over the three joined together, so that a future
    pattern spanning a boundary still fires; this just re-locates the matched substring
    afterwards. ``"unknown"`` is unreachable in practice and is here rather than an
    assertion because a moderation error must never be replaced by a crash.
    """
    folded = hit.casefold()
    for label, text in (("name", name), ("note", note), ("lyrics", lyrics)):
        if folded in text.casefold():
            return label
    return "unknown"


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
        approved = brief.approved_lyrics
        lyrics_text = approved.as_plain_text() if approved is not None else ""
        # An order with no recipient — the bring-your-own path — still has a note and a
        # lyric to review, and those are where hostile text actually arrives. The name
        # contributes an empty string rather than the word "None".
        name = "" if brief.recipient is None else brief.recipient.display
        subject = f"{name} {brief.note} {lyrics_text}"
        hit = _local_hit(subject)
        if hit is not None:
            return err(
                ModerationRejectedError(
                    "brief rejected by the local denylist",
                    context={
                        "pattern_hit": hit,
                        "hit_in": _hit_source(
                            hit,
                            name=name,
                            note=brief.note,
                            lyrics=lyrics_text,
                        ),
                        "note": brief.note[:REJECTED_NOTE_LOG_CHARS],
                    },
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
            return self._on_transport_failure(
                result.error, has_approved_lyrics=approved is not None
            )

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

    @staticmethod
    def _on_transport_failure(error: HbdError, *, has_approved_lyrics: bool) -> Result[None]:
        """What an unreachable moderation model means, which depends on who wrote the words.

        A note-only brief is allowed through on the local verdict alone — see the module
        docstring for why that trade is still the right one. A brief carrying a lyric the
        customer supplied is not: those words are sent to the music vendor unaltered and
        handed back as the product, so an outage must not become the route by which they
        skip the gate. Marked retryable, because the failure is the transport and not the
        brief: the worker's ladder tries the model again rather than killing the order on
        one timeout.
        """
        if not has_approved_lyrics:
            _LOGGER.warning(
                "moderation call failed; allowing the note-only brief on the local verdict alone",
                extra=error.to_log_dict(),
            )
            return ok(None)
        _LOGGER.error(
            "moderation call failed on a customer-written lyric; refusing to fail open",
            extra=error.to_log_dict(),
        )
        return err(
            ModerationRejectedError(
                "moderation could not review a customer-written lyric",
                is_retryable=True,
                context={"failure": error.error_code.value},
            )
        )
