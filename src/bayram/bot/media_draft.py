"""An image or video request while it is being composed (IMAGE_VIDEO_SPEC §2.3.1, §2.4.1).

The FSM holds one :class:`MediaDraft` under :data:`MEDIA_DRAFT_KEY`: the prompt, the photos'
Telegram ids, the tray message the compose screen is drawn on and the aspect. **Never bytes**
— Redis keeps FSM data for fourteen days and an upload is personal data on a 24-hour clock
(O16); the worker downloads each photo by its ``file_id`` only after the draft is frozen
(§3.3 ``media_screen``).

Validated on the way back in, like :mod:`bayram.bot.draft`: a draft written by an older build
or hand-edited in Redis fails validation and reads as absent, never as a crash.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from bayram.contracts import Language
from bayram.db.enums import MediaAspect, MediaKind, MediaTier, MediaVoiceGender, MediaVoiceMode
from bayram.moderation.lexicon import NARRATION_MAX_CHARS

__all__ = [
    "MEDIA_DRAFT_KEY",
    "MIN_PROMPT_CHARS",
    "MAX_PROMPT_CHARS",
    "MAX_UPLOAD_BYTES",
    "UPLOAD_DOCUMENT_MIMES",
    "MediaRef",
    "MediaVoiceNoteRef",
    "MediaDraft",
    "load_media_draft",
]

MEDIA_DRAFT_KEY: Final[str] = "media_draft"

#: The prompt's bounds (§1.3): required, 3–800 characters.
MIN_PROMPT_CHARS: Final[int] = 3
MAX_PROMPT_CHARS: Final[int] = 800

#: The Bot API's ``getFile`` ceiling (§2.3.2). A bigger document could never be downloaded.
MAX_UPLOAD_BYTES: Final[int] = 20 * 1024 * 1024

#: The document types accepted as a photo (§2.3.2). Anything else is ``media.compose.unsupported``;
#: an animated WebP passes here and is refused by ``media_screen``'s decode (§3.3).
UPLOAD_DOCUMENT_MIMES: Final[frozenset[str]] = frozenset({"image/jpeg", "image/png", "image/webp"})


class MediaRef(BaseModel):
    """One uploaded photo, by reference. ``file_unique_id`` is what de-duplicates (§2.3.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_id: str = Field(min_length=1, max_length=256)
    file_unique_id: str = Field(min_length=1, max_length=64)
    mime: str = Field(default="image/jpeg", max_length=64)
    w: int | None = Field(default=None, ge=0)
    h: int | None = Field(default=None, ge=0)
    size: int | None = Field(default=None, ge=0)


class MediaVoiceNoteRef(BaseModel):
    """An own voice note (§2.4.2): Telegram's ids and its whole-second duration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_id: str = Field(min_length=1, max_length=256)
    file_unique_id: str = Field(min_length=1, max_length=64)
    duration: int = Field(ge=0)


class MediaDraft(BaseModel):
    """The compose state. Frozen; every change is a new draft via :meth:`updated`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: MediaKind
    #: A fresh one per compose, so two identical requests are two drafts.
    session_id: str = Field(min_length=1, max_length=64)
    ui_language: Language
    prompt: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    refs: tuple[MediaRef, ...] = ()
    #: The album the last one-per-album notice (cap reached, unsupported) was given for, so
    #: a ten-photo album draws one notice and not ten (§2.3.2).
    last_media_group_id: str | None = None
    #: The one live tray message of this compose (§2.3.2). A photo or a prompt moves it
    #: under the customer's message; a button press edits it in place.
    tray_message_id: int | None = None
    #: The album the current tray was sent for: the album's first item moves the tray, its
    #: later items edit that tray in place, so an album draws one reply (§2.3.2). Separate
    #: from :attr:`last_media_group_id`, which tracks the one-per-album NOTICES.
    tray_media_group_id: str | None = None
    aspect: MediaAspect | None = None
    #: Video only (§2.4): the choices made after ✅ Done, written onto the ``drafting`` row
    #: by the last voice step.
    tier: MediaTier | None = None
    voice: MediaVoiceMode | None = None
    voice_gender: MediaVoiceGender | None = None
    #: The words an AI voice will say — typed, or an AI-written line the customer took.
    narration_text: str | None = Field(default=None, max_length=NARRATION_MAX_CHARS)
    #: An own voice note, by reference (``F.voice`` only), never its bytes.
    voice_note: MediaVoiceNoteRef | None = None
    #: How many AI-written lines were asked for: the next ``media_script`` is line ``n``, and
    #: 🔄 is offered while ``n`` ≤ ``media_script_max_regens`` (§2.4.2).
    script_requests: int = Field(default=0, ge=0)
    #: The ``media_jobs.id`` this draft was frozen into, as hex; ``None`` while composing.
    #: ✏️ Edit reopens compose from this draft when it names the job being edited.
    frozen_job: str | None = None

    def updated(self, **changes: Any) -> MediaDraft:
        """Return a NEW draft with ``changes`` applied and revalidated. Never mutates."""
        return MediaDraft.model_validate({**self.model_dump(), **changes})

    @property
    def unique_ids(self) -> frozenset[str]:
        return frozenset(ref.file_unique_id for ref in self.refs)

    def to_state_data(self) -> dict[str, Any]:
        return {MEDIA_DRAFT_KEY: self.model_dump(mode="json")}


def load_media_draft(state_data: dict[str, Any]) -> MediaDraft | None:
    """The draft in FSM data, or ``None`` when there is none or it does not validate."""
    raw = state_data.get(MEDIA_DRAFT_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        return MediaDraft.model_validate(raw)
    except PydanticValidationError:
        return None
