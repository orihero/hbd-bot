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

Nothing fails open any more (IMAGE_VIDEO_SPEC §6.8). This gate used to let a note-only
brief through when the model could not be reached, on the argument that the note is short
and the vendors moderate their own inputs. Two things undid that argument. The verdict
schema defaulted ``is_allowed`` to true and ignored unknown keys, so a model that answered
``{"allowed": false}`` — a refusal in the wrong key — parsed as an approval; and a parse
failure travelled the same ``Err`` road as a timeout, so "the model said something we
could not read" was also waved through. A gate whose silence means yes is not a gate.

So the verdict is now strict (no default, unknown keys forbidden, a real boolean or
nothing), and any failure to get one is retried twice here, then refused. Songs are sold
before this stage runs, so "closed" does not mean silence: the refusal is terminal, the
worker settles the order FAILED, which refunds the credit, and the failure is a
``ModerationUnavailableError`` (``MODERATION_UNAVAILABLE``, not ``CONTENT_REJECTED``) that
carries ``needs_review`` into ``orders.failed_reason``, so an operator can tell an outage
refusal from a real one. The customer is told the service was unavailable, not that their
words were unacceptable — nobody judged them. If the LLM answers and says no, that is a
decision, and it is honoured either way; so is the reviewer vendor's own safety filter
blocking the prompt, which is a judgement too and is neither retried nor marked for review.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict

from bayram.config import Settings
from bayram.contracts import Brief, Err, LlmProvider, LlmRequest, Result, err, ok
from bayram.errors import (
    BayramError,
    ModerationRejectedError,
    ModerationUnavailableError,
    ProviderRejectedContentError,
)
from bayram.logging import get_logger
from bayram.pipeline.prompts import moderation_system_prompt, moderation_user_prompt

__all__ = [
    "ModerationPayload",
    "LlmModerator",
    "AllowAllModerator",
    "LOCAL_DENY_PATTERNS",
    "MODERATION_ATTEMPTS",
    "UNREVIEWED_USER_MESSAGE_KEY",
]

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


#: Attempts at the model before the brief is refused unreviewed: the first call plus the
#: two retries IMAGE_VIDEO_SPEC §6.8 asks for. Back-to-back, deliberately: the transport
#: already retries its own 429s and 5xx with backoff, so these three are about a flaky
#: answer (an unparseable verdict, one timeout), not about waiting out an outage.
MODERATION_ATTEMPTS: Final[int] = 3

#: The customer-facing key for an unreviewed refusal. Not ``error.content_not_allowed``:
#: nothing judged the words, and telling someone to reword a harmless note because our
#: model was down would send them off to fix a problem they do not have.
UNREVIEWED_USER_MESSAGE_KEY: Final[str] = "error.service_unavailable"


#: Strict: anything but an explicit ``is_allowed`` is no verdict. No default on
#: ``is_allowed`` and ``extra="forbid"`` (IMAGE_VIDEO_SPEC §6.8): with a ``True`` default and
#: ignored extras, ``{"allowed": false}`` parsed as an approval. ``strict=True`` for the same
#: reason one step further — lax mode would read the string ``"yes"`` or the integer ``1``
#: as true. An answer this model rejects fails to parse, and a parse failure is refused like
#: any other missing verdict.
#:
#: The rationale lives here and not in the class docstring because the docstring is not
#: private: the schema converters copy it into the response schema's ``description``, so it
#: is sent to the reviewer model on every call. It stays one neutral, model-facing sentence.
class ModerationPayload(BaseModel):
    """The reviewer's verdict: whether the brief is allowed, and a short reason."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    is_allowed: bool
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
        verdict = await self._verdict(request)
        if isinstance(verdict, ProviderRejectedContentError):
            return self._refuse_vendor_blocked(verdict, note=brief.note)
        if isinstance(verdict, BayramError):
            return self._refuse_unreviewed(verdict, has_approved_lyrics=approved is not None)
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

    async def _verdict(self, request: LlmRequest) -> ModerationPayload | BayramError:
        """A parsed verdict, or the last failure after :data:`MODERATION_ATTEMPTS` tries.

        A vendor's own safety block comes back at once, unretried. It is a judgement, not
        an outage: at temperature 0 the same prompt is blocked the same way every time, so
        retrying it only pays for two more identical refusals.
        """
        attempt = 1
        result = await self._ask(request)
        while isinstance(result, Err):
            if isinstance(result.error, ProviderRejectedContentError):
                return result.error
            _LOGGER.warning(
                "moderation call failed; attempt %d of %d",
                attempt,
                MODERATION_ATTEMPTS,
                extra=result.error.to_log_dict(),
            )
            if attempt >= MODERATION_ATTEMPTS:
                return result.error
            attempt += 1
            result = await self._ask(request)
        return result.value

    async def _ask(self, request: LlmRequest) -> Result[ModerationPayload]:
        return await self._llm.generate_json(
            request, ModerationPayload, timeout_s=self._settings.llm_timeout_s
        )

    @staticmethod
    def _refuse_vendor_blocked(error: ProviderRejectedContentError, *, note: str) -> Result[None]:
        """The reviewer model's vendor blocked the brief itself: an ordinary content refusal.

        Somebody's filter did judge these words, so this is a decision like a ``false``
        verdict — the default ``error.content_not_allowed`` key and no ``needs_review`` —
        not the unreviewed refusal an outage earns.
        """
        return err(
            ModerationRejectedError(
                "brief blocked by the moderation vendor's own safety filter",
                context={
                    "reason": "vendor_safety_block",
                    "failure": error.error_code.value,
                    "note": note[:REJECTED_NOTE_LOG_CHARS],
                },
                cause=error,
            )
        )

    @staticmethod
    def _refuse_unreviewed(error: BayramError, *, has_approved_lyrics: bool) -> Result[None]:
        """No verdict after every attempt: refuse, terminally, and flag it for a human.

        Terminal rather than retryable because the retries already happened here; handing
        the worker a retryable error would re-queue a paid order for minutes of backoff
        while the customer watches a progress bar. The worker settles a terminal failure
        as FAILED, which is the existing refund path (IMAGE_VIDEO_SPEC §6.8: songs are
        post-payment, so fail-closed means refund, not silence). ``needs_review`` and
        ``failure`` are allowlisted into ``orders.failed_reason``; the note is not.
        """
        _LOGGER.error(
            "moderation returned no verdict after %d attempts; refusing the brief unreviewed",
            MODERATION_ATTEMPTS,
            extra={**error.to_log_dict(), "has_approved_lyrics": has_approved_lyrics},
        )
        return err(
            ModerationUnavailableError(
                "moderation returned no verdict; the brief was refused unreviewed",
                user_message_key=UNREVIEWED_USER_MESSAGE_KEY,
                context={
                    "failure": error.error_code.value,
                    "attempts": MODERATION_ATTEMPTS,
                    "needs_review": True,
                    "has_approved_lyrics": has_approved_lyrics,
                },
                cause=error,
            )
        )
