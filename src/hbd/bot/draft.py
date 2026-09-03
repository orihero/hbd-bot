"""The wizard's accumulated answers, and how they survive a round-trip through FSM storage.

aiogram's storage holds plain JSON, so the draft is serialised with ``mode="json"`` and
validated on the way back in. Nothing here trusts what came out of Redis: a draft written
by an older build, or hand-edited, fails validation and is reported as an expired session
rather than crashing a handler.

The draft is frozen. Every step returns a NEW draft via :meth:`WizardDraft.updated`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from hbd.bot.i18n import FALLBACK_LANGUAGE
from hbd.contracts import (
    Brief,
    Genre,
    Language,
    LyricDraft,
    Occasion,
    RecipientName,
    Result,
    VoiceGender,
    err,
    ok,
)
from hbd.errors import ValidationError

__all__ = [
    "WizardDraft",
    "LyricSource",
    "load_draft",
    "DRAFT_KEY",
    "MAX_NOTE_CHARS",
    "REQUIRED_ANSWERS",
    "OWN_LYRICS_REQUIRED_ANSWERS",
]

#: Single FSM-data key holding the whole draft, so no other key can collide with it.
DRAFT_KEY: Final[str] = "draft"

#: Mirrors ``Brief.note``'s bound. ``test_draft.py`` asserts the two stay in step.
MAX_NOTE_CHARS: Final[int] = 600

#: Answers without which no :class:`Brief` can exist. ``note`` is deliberately absent, and
#: so is ``lyrics``: the wizard has to hand the lyric writer a finished :class:`Brief` in
#: order to GET a lyric, so ``to_brief()`` must keep succeeding while the lyric is still
#: being written. Completeness for the purposes of *submitting* is :attr:`is_complete`,
#: which requires the lyric on top of these.
REQUIRED_ANSWERS: Final[tuple[str, ...]] = (
    "occasion",
    "genre",
    "vocal_gender",
    "recipient",
    "output_language",
)

#: The same list for the bring-your-own-lyrics path, minus the recipient.
#:
#: That path never asks who the song is for — the customer wrote the words and put whatever
#: name they wanted in them — so ``Brief.recipient`` is ``None`` for these orders and the
#: whole name subsystem is skipped downstream: no hook section, no name chunk, no acoustic
#: verification. Requiring a recipient here would make every one of those drafts permanently
#: incomplete, and ``resolve_step`` would bounce the customer back to a NAME step their path
#: does not contain.
OWN_LYRICS_REQUIRED_ANSWERS: Final[tuple[str, ...]] = (
    "occasion",
    "genre",
    "vocal_gender",
    "output_language",
)


class LyricSource(StrEnum):
    """Who writes the words. Chosen at the occasion step, before any vendor is billed.

    This is the whole of the bring-your-own feature's state, and it lives on the draft
    rather than in the FSM state name because it has to survive Back: a customer who steps
    back to change the genre must not silently be handed the machine's lyric on the way
    forward again.

    ``WRITER`` is the default and must stay the default — a draft written by a build that
    predates this field deserialises into the behaviour it was created under, which is the
    same rule ``session_id`` follows below.
    """

    #: The bot writes the lyric and shows it for approval. One live LLM call per attempt.
    WRITER = "writer"
    #: The customer sends their own words. Costs nothing and calls nobody: the lyric step
    #: prompts instead of writing, so neither ``MAX_LYRIC_WRITES`` nor the per-account daily
    #: budget is touched. Somebody who arrived with a poem already written should not have
    #: to buy a machine's attempt at one in order to reach the screen that accepts theirs.
    OWN = "own"


class WizardDraft(BaseModel):
    """Partial intake. Every field except the interface language may still be unanswered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Which run through the wizard this draft belongs to. Minted once per clean slate by
    #: ``handlers.common.reset_to_welcome`` and carried unchanged through every step, so it
    #: is constant for a double tap on one Confirm screen and different for the next run.
    #:
    #: It exists because the order id is a UUID5 over the draft (see
    #: ``handlers.confirm._order_id_for``): without it, two runs that answer identically —
    #: same recipient, same four answers, same pasted lyric — mint the same order id
    #: forever, the second one dies on the ``orders`` primary key, and a customer who
    #: genuinely wants a second copy of the same song is told "I could not hand this to the
    #: studio" with no reason and no way out.
    #:
    #: Defaults to empty rather than to a fresh value: a draft written by a build that
    #: predates this field must keep hashing to the id its order was already queued under.
    session_id: str = ""
    ui_language: Language = FALLBACK_LANGUAGE
    occasion: Occasion | None = None
    genre: Genre | None = None
    vocal_gender: VoiceGender | None = None
    note: str = Field(default="", max_length=MAX_NOTE_CHARS)
    recipient: RecipientName | None = None
    output_language: Language | None = None
    #: The lyric the user previewed and approved. ``None`` while it is being written, or
    #: after a regenerate has thrown the previous one away.
    lyrics: LyricDraft | None = None
    #: Who is writing the words. Set at the occasion step and honoured by the lyric step;
    #: see :class:`LyricSource` for why it lives here rather than in the FSM state.
    lyrics_source: LyricSource = LyricSource.WRITER
    #: How many times this session has asked the writer for a lyric. The preview step is
    #: the first place a vendor is billed and it sits BEFORE the payment gate, so without
    #: a number here a stranger who never pays can hold the regenerate button down and
    #: spend the operator's LLM budget. Counted here rather than in the handler because the
    #: draft is the only per-session state that survives a restart.
    lyric_writes: int = Field(default=0, ge=0)

    def updated(self, **changes: Any) -> WizardDraft:
        """Return a NEW draft with ``changes`` applied and revalidated. Never mutates."""
        return WizardDraft.model_validate({**self.model_dump(), **changes})

    @property
    def required_answers(self) -> tuple[str, ...]:
        """Which answers this draft's path actually needs. See the two constants above."""
        return OWN_LYRICS_REQUIRED_ANSWERS if self.is_own_lyrics else REQUIRED_ANSWERS

    @property
    def missing_answers(self) -> tuple[str, ...]:
        """Names of the answers still required before a :class:`Brief` can be built."""
        return tuple(name for name in self.required_answers if getattr(self, name) is None)

    @property
    def is_own_lyrics(self) -> bool:
        """True when the customer is supplying the words themselves.

        Read by ``screens.resolve_step`` — which must NOT downgrade a lyric-less preview to
        the language question on this path, because the preview is where the words are
        asked for — and by ``handlers.lyrics``, which uses it to skip the writer entirely.
        """
        return self.lyrics_source is LyricSource.OWN

    @property
    def is_complete(self) -> bool:
        """Ready to confirm: every required answer given AND a lyric approved."""
        return not self.missing_answers and self.lyrics is not None

    def to_state_data(self) -> dict[str, Any]:
        """The dict handed to ``FSMContext.update_data``."""
        return {DRAFT_KEY: self.model_dump(mode="json")}

    def to_brief(self) -> Result[Brief]:
        """Build the finished brief, or explain exactly what is still missing.

        The recipient is required on the writer's path and optional on the customer's, which
        is the one asymmetry here — ``missing_answers`` owns that rule, and this method only
        has to agree with it. A ``None`` recipient reaching ``Brief`` is not a hole: it is
        how the pipeline is told this song names nobody.
        """
        occasion, genre, vocal_gender = self.occasion, self.genre, self.vocal_gender
        recipient, output_language = self.recipient, self.output_language
        if (
            occasion is None
            or genre is None
            or vocal_gender is None
            or (recipient is None and not self.is_own_lyrics)
            or output_language is None
        ):
            return err(
                ValidationError(
                    "wizard draft is incomplete",
                    context={"missing_answers": list(self.missing_answers)},
                )
            )
        return ok(
            Brief(
                recipient=recipient,
                occasion=occasion,
                genre=genre,
                vocal_gender=vocal_gender,
                note=self.note,
                ui_language=self.ui_language,
                output_language=output_language,
                approved_lyrics=self.lyrics,
            )
        )


def load_draft(state_data: dict[str, Any]) -> Result[WizardDraft]:
    """Read a draft out of raw FSM data. Never raises; never trusts the payload."""
    raw = state_data.get(DRAFT_KEY)
    if raw is None:
        return err(ValidationError("no wizard draft in FSM data", context={"key": DRAFT_KEY}))
    if not isinstance(raw, dict):
        return err(
            ValidationError(
                "wizard draft in FSM data is not an object",
                context={"key": DRAFT_KEY, "actual_type": type(raw).__name__},
            )
        )
    try:
        return ok(WizardDraft.model_validate(raw))
    except PydanticValidationError as exc:
        return err(
            ValidationError(
                "wizard draft in FSM data failed validation",
                context={"key": DRAFT_KEY, "issue_count": len(exc.errors())},
                cause=exc,
            )
        )
