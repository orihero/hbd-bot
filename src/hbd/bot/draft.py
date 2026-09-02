"""The wizard's accumulated answers, and how they survive a round-trip through FSM storage.

aiogram's storage holds plain JSON, so the draft is serialised with ``mode="json"`` and
validated on the way back in. Nothing here trusts what came out of Redis: a draft written
by an older build, or hand-edited, fails validation and is reported as an expired session
rather than crashing a handler.

The draft is frozen. Every step returns a NEW draft via :meth:`WizardDraft.updated`.
"""

from __future__ import annotations

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

__all__ = ["WizardDraft", "load_draft", "DRAFT_KEY", "MAX_NOTE_CHARS", "REQUIRED_ANSWERS"]

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
    def missing_answers(self) -> tuple[str, ...]:
        """Names of the answers still required before a :class:`Brief` can be built."""
        return tuple(name for name in REQUIRED_ANSWERS if getattr(self, name) is None)

    @property
    def is_complete(self) -> bool:
        """Ready to confirm: every required answer given AND a lyric approved."""
        return not self.missing_answers and self.lyrics is not None

    def to_state_data(self) -> dict[str, Any]:
        """The dict handed to ``FSMContext.update_data``."""
        return {DRAFT_KEY: self.model_dump(mode="json")}

    def to_brief(self) -> Result[Brief]:
        """Build the finished brief, or explain exactly what is still missing."""
        occasion, genre, vocal_gender = self.occasion, self.genre, self.vocal_gender
        recipient, output_language = self.recipient, self.output_language
        if (
            occasion is None
            or genre is None
            or vocal_gender is None
            or recipient is None
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
