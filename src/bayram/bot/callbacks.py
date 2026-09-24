"""Typed callback payloads.

Telegram gives 64 bytes of callback data; these factories keep every payload well inside
it and, more importantly, make an unparseable payload simply not match a handler instead
of raising inside one. That is the boundary validation for everything a button can send.
"""

from __future__ import annotations

import base64
import binascii
from enum import StrEnum
from typing import Final
from uuid import UUID

from aiogram.filters.callback_data import CallbackData

from bayram.contracts import Genre, Language, Occasion, VoiceGender

__all__ = [
    "NavAction",
    "SupportAction",
    "LanguageSlot",
    "LanguageCB",
    "OccasionCB",
    "GenreCB",
    "VocalGenderCB",
    "NavCB",
    "SupportCB",
    "TermsAction",
    "TermsCB",
    "MediaAction",
    "MediaCB",
    "CreatePick",
    "AspectPick",
    "pack_job_ref",
    "read_job_ref",
    "NO_REFERENCE",
    "pack_reference",
    "read_reference",
]


class NavAction(StrEnum):
    """Navigation and confirmation buttons shared across steps."""

    BACK = "back"
    SKIP = "skip"
    CANCEL = "cancel"
    CONFIRM = "confirm"
    NAME_OK = "name_ok"
    RETYPE = "retype"
    LYRICS_OK = "lyrics_ok"
    #: "I will write the words myself", offered in the occasion list. It is a NAV button
    #: sitting among the occasion buttons rather than a fourth :class:`Occasion`, because it
    #: is not an answer to "what are we celebrating?" — it answers who writes the lyric, and
    #: an enum member would have had to be given a label, a prompt and a place in every
    #: brief the pipeline reasons about in order to say something the occasion is not about.
    OWN_LYRICS = "own_lyrics"
    #: Ask for a different lyric. Abbreviated because the value is packed into the 64-byte
    #: callback payload; its BUTTON LABEL lives under ``button.regenerate``, so
    #: ``lyrics_keyboard`` draws this one explicitly instead of via the ``button.{value}``
    #: convention every other nav button follows.
    REGENERATE = "regen"
    #: The four buttons that exist so no message is a dead end. A screen that ends a flow —
    #: cancelled, expired, delivered, or a lyric the writer could not produce — leaves the
    #: user with nothing to do, and "send /start" is not an answer. These are what it
    #: carries instead. They spell their action out because every one of them is well
    #: inside the payload budget: ``nav:report_problem`` is 18 of the 64 bytes.
    START_OVER = "start_over"
    MAKE_ANOTHER = "make_another"
    REPORT_PROBLEM = "report_problem"
    TRY_AGAIN = "try_again"
    #: The settings submenu, and the two ways back up out of it. They spell their action out
    #: for the reason the four above do: ``nav:set_language`` is 16 of the 64 bytes, so the
    #: payload budget buys nothing by abbreviating and an abbreviation costs a reader a
    #: lookup. All five follow the ``button.{action.value}`` convention, so none of them
    #: belongs in ``keyboards.py``'s documented exception block — which is where a reader
    #: goes to find out whether a button's label key was hand-picked, and finding nothing
    #: there is the answer.
    #:
    #: ``TO_MENU`` is drawn in three places and it is the same button in all three: the last
    #: row of the settings submenu, and one row of its own on ``start_over_keyboard`` and
    #: ``post_delivery_keyboard``. Those last two were the product's remaining dead ends —
    #: the only route home from a cancelled, expired or delivered flow was a tap on a
    #: persistent reply keyboard the customer may have collapsed.
    SET_LANGUAGE = "set_language"
    SHOW_PRIVACY = "show_privacy"
    SHOW_SUPPORT = "show_support"
    TO_MENU = "to_menu"
    TO_SETTINGS = "to_settings"
    #: The two buttons the Confirm screen wears when the account cannot afford a render:
    #: buy one song, or take the plan. They pack as ``nav:pay`` and ``nav:subscribe`` — 7
    #: and 13 of the 64 bytes — so there is nothing to abbreviate and both follow the
    #: ``button.{action.value}`` convention, which is why neither appears in
    #: ``keyboards.py``'s hand-picked-label exception block.
    #:
    #: They are NAV actions rather than a step of their own for the reason
    #: :class:`~bayram.bot.pricing.CheckoutOffer` sets out: the checkout is the Confirm screen
    #: wearing a second face, not a new place in the wizard, so nothing about
    #: ``WIZARD_ORDER``, ``previous_step`` or ``resolve_step``'s fixpoint moves for them.
    #:
    #: Their labels are also the FIRST in this product to interpolate a value — the price —
    #: which is why ``_nav_button`` grew ``label_params``. A price baked into four
    #: catalogues would silently disagree with ``BAYRAM_SINGLE_SONG_PRICE_MINOR`` the day an
    #: operator changed it; a price interpolated from ``Settings`` cannot.
    PAY = "pay"
    SUBSCRIBE = "subscribe"


class LanguageSlot(StrEnum):
    """Interface language and output language are chosen INDEPENDENTLY, by the same widget."""

    UI = "ui"
    OUTPUT = "out"
    #: The settings language picker. The settings screen carries NO FSM state — see
    #: ``keyboards.settings_keyboard`` — so the FSM can no longer tell the settings picker
    #: from the wizard's OUTPUT picker, and the payload has to. ``"set"`` rather than
    #: ``"settings"`` for the same reason ``NavAction.REGENERATE`` is ``"regen"``.
    SETTINGS = "set"


class LanguageCB(CallbackData, prefix="lang"):
    slot: LanguageSlot
    code: Language


class OccasionCB(CallbackData, prefix="occ"):
    value: Occasion


class GenreCB(CallbackData, prefix="gen"):
    value: Genre


class VocalGenderCB(CallbackData, prefix="voc"):
    value: VoiceGender


class NavCB(CallbackData, prefix="nav"):
    action: NavAction


class SupportAction(StrEnum):
    """The three support buttons: one the customer presses, two the staff group presses.

    A separate enum from :class:`NavAction` rather than three more members on it, and the
    separation is a wire-format decision rather than a taxonomy one. ``NavCB`` carries an
    action and nothing else, and every nav button in this product is drawn on a screen that
    already knows which order it is about — the closing message, the confirm screen, the
    settings submenu. These three are not: ⚠️ is drawn by the WORKER onto a message the
    customer may tap a month later from several screens into a different wizard, and ``✋``
    and ``✅`` are pressed by a staffer in a group chat that has no FSM of ours at all. All
    three therefore have to carry an id, and giving ``NavCB`` an id field would change the
    packed wire format of every existing nav button — including the ones already sitting in
    customers' chats, which would stop matching their handler the moment the field was added.
    """

    #: The customer's ⚠️ Something is wrong. Carries the ORDER id when the tap came from a
    #: delivered song's closing message, and :data:`NO_REFERENCE` when it did not.
    OPEN = "open"
    #: A staffer taking the ticket in the support group: assign to them, move to
    #: ``in_progress``, re-render the card. Carries the TICKET id.
    CLAIM = "claim"
    #: A staffer closing it. Carries the TICKET id.
    RESOLVE = "resolve"


#: What :attr:`SupportCB.ref` holds when there is no id to carry.
#:
#: A single character rather than the empty string, because aiogram packs callback data by
#: joining the fields with ``:`` and an empty trailing field makes ``sup:open:`` — a payload
#: whose round trip through ``unpack`` is fine but which reads, in a log line and in a
#: ``getUpdates`` dump, as a truncated one. ``-`` is not a hex digit, so it can never collide
#: with a real id.
NO_REFERENCE: Final[str] = "-"


class SupportCB(CallbackData, prefix="sup"):
    """One id, and the action decides which table it names. 45 of the 64 bytes at worst.

    **``ref`` is deliberately ONE field carrying two different ids**, and that is the only
    shape the payload budget admits. ``OPEN`` needs the order the complaint is about;
    ``CLAIM`` and ``RESOLVE`` need the ticket. Carrying both would be
    ``sup:resolve:<32 hex>:<32 hex>`` — 78 bytes against Telegram's 64 — so the choice is one
    field or two callback classes, and two classes would put the three support buttons of one
    feature behind two prefixes that have to be registered, filtered and read separately.

    The overload is safe because the action is not data the caller supplies from somewhere
    else: it is packed into the same 64 bytes by the builder that also packed the id, and the
    two are read by handlers registered on ``SupportCB.filter(F.action == …)``. There is no
    path on which a handler expecting a ticket id is handed an order id — a mismatch is a
    payload that matches no filter, which is the boundary property the module docstring above
    states.

    ``ref`` is the id's ``.hex`` (32 characters, no dashes) rather than ``str(uuid)`` (36),
    because four dashes bought nothing and the budget is the whole reason this class exists
    instead of a field on ``NavCB``. Use :func:`pack_reference` / :func:`read_reference` at
    both ends so the two spellings cannot drift.
    """

    action: SupportAction
    ref: str


class TermsAction(StrEnum):
    """The two buttons under the Terms screen (IMAGE_VIDEO_SPEC §2.1)."""

    #: ✅ I accept. Records the acceptance of the version pair in force, and ONLY when it is
    #: the pair the button was drawn for (``TermsCB.v``): a ✅ drawn before a version bump is
    #: answered with the current screen instead, so nobody is recorded as accepting a text
    #: they were never shown.
    ACCEPT = "ok"
    #: 📄 Read in full. Draws the whole Terms of Use over the summary.
    READ_FULL = "full"


class TermsCB(CallbackData, prefix="trm"):
    """Its own prefix so the terms screen depends on no other router (IMAGE_VIDEO_SPEC §2.1).

    Both handlers are registered with NO state filter inside the onboarding router, above its
    ``NotOnboarded`` catch-all — a not-yet-onboarded customer's ✅ would otherwise be claimed by
    the catch-all and answered with the screen they were already looking at — and every
    ``trm:*`` callback passes ``TermsGateMiddleware``.
    """

    action: TermsAction
    #: The version pair the screen was drawn for, as ``TermsVersions.stamp``. Checked on
    #: ACCEPT only; empty on 📄, which records nothing.
    v: str = ""


class MediaAction(StrEnum):
    """The media buttons (IMAGE_VIDEO_SPEC §2, §2.2, §2.3.3). Short: packed into 64 bytes.

    Two families share one prefix and are told apart by whether :attr:`MediaCB.job` is set.

    **Post-freeze** (``PAY`` … ``MORE``) are drawn by the WORKER (the quote, refusal, busy and
    failure screens are edits it makes to the tray, §3.3) or by the bot's open-request screen.
    Every one carries the ``media_jobs.id`` and is registered WITHOUT a state filter: the FSM
    may be cleared or days old, so the handler reads the row — owner and state — and answers
    ``media.stale`` when the press no longer fits it.

    **Pre-freeze** (``PICK`` … ``ASPECT``) belong to the compose screens, carry no job and are
    registered WITH a state filter (``PICK`` excepted: the picker is drawn from the menu,
    which has no state).
    """

    #: 💳 Pay — only on a live-paid rail (§2.5).
    PAY = "pay"
    #: 🎟 Use a refund credit of this SKU.
    CREDIT = "cred"
    #: 🎁 Free beta — only off a live-paid rail, only for the allowlist, re-checked at press.
    BETA = "beta"
    #: ✏️ Edit: the row is cancelled and compose reopens from the draft (§2.3.1).
    EDIT = "edit"
    #: ✖️ Cancel the request.
    CANCEL = "cancel"
    #: 🔁 Try again on a busy tray: re-runs screening/capability on the SAME frozen row.
    RETRY = "retry"
    #: 🔁 Again after delivery or a failure: a fresh compose pre-filled with the prompt and
    #: aspect (never the photos, O16).
    AGAIN = "again"
    #: ✨ Create something else, under a delivery: the ✨ picker again.
    MORE = "more"
    #: A choice on the ✨ picker; :attr:`MediaCB.arg` is a :class:`CreatePick` value.
    PICK = "pick"
    #: ✅ Done on the compose tray.
    DONE = "done"
    #: 🗑 Clear photos on the compose tray.
    CLEAR = "clear"
    #: ✖️ on a screen before anything was frozen: the draft is dropped, no row exists.
    DROP = "drop"
    #: An aspect on the aspect screen; :attr:`MediaCB.arg` is a :class:`AspectPick` value.
    ASPECT = "asp"


class CreatePick(StrEnum):
    """The three rows of the ✨ picker (§2.2)."""

    SONG = "song"
    IMAGE = "image"
    VIDEO = "video"


class AspectPick(StrEnum):
    """The aspect buttons, by name — the ratio itself contains the ``:`` the payload is split
    on. ``bayram.db.enums.MediaAspect`` holds the ratio."""

    PORTRAIT = "portrait"
    SQUARE = "square"
    LANDSCAPE = "landscape"


class MediaCB(CallbackData, prefix="med"):
    """``med:<action>:<22-char job ref>:<arg>`` — at most 46 of the 64 bytes (§2 "Callbacks").

    ``job`` is empty on a pre-freeze button and ``arg`` on every button but ``PICK`` and
    ``ASPECT``.
    """

    action: MediaAction
    #: :func:`pack_job_ref` of the ``media_jobs.id``; empty before anything is frozen.
    job: str = ""
    arg: str = ""


def pack_job_ref(job_id: UUID) -> str:
    """A ``media_jobs.id`` as 22 characters of unpadded base64url (§2 "Callbacks")."""
    return base64.urlsafe_b64encode(job_id.bytes).rstrip(b"=").decode("ascii")


def read_job_ref(value: str) -> UUID | None:
    """The id back out of :attr:`MediaCB.job`; ``None`` for anything that is not one. Never
    raises, for :func:`read_reference`'s reason."""
    if len(value) != 22:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "==")
    except (binascii.Error, ValueError):
        return None
    return UUID(bytes=raw) if len(raw) == 16 else None


def pack_reference(value: UUID | None) -> str:
    """The wire spelling of an id in :attr:`SupportCB.ref`. ``None`` becomes ``-``."""
    return NO_REFERENCE if value is None else value.hex


def read_reference(value: str) -> UUID | None:
    """The id back out of :attr:`SupportCB.ref`, or ``None`` for ``-`` and for nonsense.

    Total, and never raises. A malformed ``ref`` is a button from a build that packed
    something else, or a payload somebody typed by hand; either way the right answer is the
    same one the module docstring gives for an unparseable payload — treat it as absent, so
    the handler falls back to the order-less door instead of raising inside a callback whose
    only visible symptom would be a spinner that never stops.
    """
    if value == NO_REFERENCE:
        return None
    try:
        return UUID(hex=value)
    except ValueError:
        return None
