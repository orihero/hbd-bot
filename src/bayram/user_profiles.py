"""Who the customer is — language, number, name, face — and the seam that stores it.

**This module is a leaf and must stay one.** It imports ``bayram.contracts`` (and would import
``bayram.errors`` if it ever named a refusal of its own) and NOTHING else: never ``bayram.db``,
never ``bayram.config``. ``bayram.entitlements`` and ``bayram.lyric_budget`` both state that rule in
their own docstrings and this module is their sibling, so it is repeated here rather than
inferred. What it buys is concrete: the bot layer depends on :class:`UserProfileStore`, a
protocol, and not on SQLAlchemy — ``bayram.db.user_profiles.SqlUserProfiles`` is the only thing
in the tree that knows a ``user_profiles`` row exists, and the ``bayram.db`` package imports
*this* module rather than the reverse, so there is no back-edge for a circular import to come
back through. (``bayram.entitlements`` records what that cycle cost when the same types were
tried in ``bayram.contracts``.)

**Why ``ui_language`` is a READ here and :meth:`UserProfileStore.record_language` is the
WRITE.** The column stays on ``users``: that table is DDL-frozen
(``docs/product/ADMIN_PANEL_PLAN.md:674`` says "No DDL"), and ``credits.set_blocked`` upserts
it so an operator can bar an account that never ordered — which is exactly why a phone number
and a face may not live there, since ``/forget`` must be able to delete those and must never
delete the row an operator blocked. So the personal data goes in its own table keyed on
``users.id`` and ``get`` JOINs the language back in. It is a field on :class:`UserProfile`
rather than a second lookup because four surfaces read it and every one of them silently falls
back to ``UZ_LATN`` without it: ``/start`` for a returning customer, the 🎵 draft seed, the
settings screen's ``{language}`` line, and ``reset_to_welcome`` after a ``state.clear()`` has
thrown the FSM cache away. A customer who chose Russian once and is answered in Uzbek by four
different screens does not conclude that a cache expired; they conclude the bot ignored them.

**Why :meth:`UserProfileStore.record_avatar` takes BYTES and not an object key.** The
implementation owns the ``Storage`` handle, so "write the object, then the row" and "delete
the object only after the row commits" are one layer's problem instead of a protocol whose
two callers must remember to sequence themselves. ``BotDeps`` gains one field, not two, and
there is no window in which a caller holds bytes it has nowhere to put.

**Why :meth:`UserProfileStore.forget` returns ``Result[None]`` and deletes.** PD-3: ``/forget``
DELETEs the profile row outright rather than nulling its columns, so there is no "nulled some
columns but not others" state for a later read to trip over and nothing to stamp. This table
is on NO clock (PD-2 — no ``profile_expires_at``, no sweep, no retention setting): the product
owner chose "kept while the account exists", so the ABSENCE of the row *is* the erasure record,
and an operator seeing nothing cannot tell "purged" from "never onboarded" — which is what PD-3
wants them to see. The ``users`` row survives with its ``ui_language``, invisibly: onboarding
reads the profile row, finds none, and asks both questions again on the next ``/start``.

**There is no backfill (D11).** ``Ok(None)`` from :meth:`UserProfileStore.get` is therefore the
normal answer for every account that existed before revision 0014 and for every account since
``/forget`` — not an error, and not a reason to take a fail-open path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from bayram.contracts import Language, Result

__all__ = [
    # Values
    "UserProfile",
    # Keys and canonical spellings
    "AVATAR_MIME",
    "normalise_phone",
    "avatar_key",
    # Seam
    "UserProfileStore",
]

#: Telegram hands the shared contact's number in whatever shape the SIM was registered in
#: ("+998 90 123 45 67", "998901234567"). Exactly one canonical spelling is persisted, because
#: two spellings would give an operator's search two different answers about one person.
#:
#: The bounds are E.164's own: a leading ``+``, a country code that cannot start with zero,
#: and eight to fifteen digits in total. Deliberately not narrowed to ``+998`` — see
#: :func:`normalise_phone`.
_PHONE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\+[1-9]\d{7,14}$")

#: Characters a human or a carrier may put in a number that carry no information: spaces,
#: dashes, the brackets around a city code, and the dot some locales use as a separator.
#:
#: U+00A0 and U+202F are in the set because Telegram desktop clients and iOS contact cards
#: both emit non-breaking spaces inside formatted numbers, and a number that differs from a
#: stored one by an invisible character is the worst possible spelling collision: it looks
#: identical in every log line and every admin screen, and matches nothing.
_PHONE_NOISE: Final[str] = " -()\u00a0\u202f."

#: The only content type an avatar is ever stored as, and the ONE definition of it in the tree.
#:
#: ``bayram.bot.avatar`` imports this rather than declaring its own, and
#: ``bayram.admin.routers.users`` builds ``AVATAR_MIMES = frozenset({AVATAR_MIME})`` from it —
#: legal, because ``tests/test_admin/test_asset_stream.py:712`` caps only what the admin
#: package imports from ``bayram.storage``. Three literals in three layers would drift silently
#: in BOTH directions at once: ``record_avatar`` answers ``ok(None)`` for a MIME it does not
#: recognise and the admin route answers 415 for one outside its set, so the observable
#: result of a drift is "no avatars anywhere" with a fully green suite.
#: See :meth:`UserProfileStore.record_avatar`.
AVATAR_MIME: Final[str] = "image/jpeg"


@dataclass(frozen=True, slots=True)
class UserProfile:
    """Everything the bot knows about the person it is talking to, as one immutable read.

    Frozen and slotted like every other value in this codebase: a profile is handed to
    screens, to gates and to the admin serialisers, and a mutable one would let a render
    path "fix up" a phone number that the database still spells differently.

    It is ONE object rather than a language lookup plus a contact lookup because the two
    are read together on almost every update — the gate needs to know whether to let the
    wizard start, and the screen that answers needs the language to answer in — and two
    round trips inside the FSM isolation lock is a cost paid on every tap.
    """

    #: ``users.id``. The join key, the avatar's object key (:func:`avatar_key`) and the
    #: ``subject_id`` an audited unmask carries (``RevealRequest.subject_id`` is a ``UUID``),
    #: which is precisely why the table is keyed on it and not on the Telegram id.
    user_id: UUID
    #: The id every inbound update carries, and the only handle the bot itself ever has.
    telegram_user_id: int
    #: Read back from ``users.ui_language``, which is the column this row JOINs to.
    #:
    #: ``Language``, not ``Language | None``: ``users.ui_language`` is ``nullable=False`` and
    #: a profile row cannot exist without its ``users`` row — the primary key IS the foreign
    #: key. Annotating it optional would push a ``None`` branch into every screen that
    #: renders a language, and each of those branches would have to invent a fallback.
    ui_language: Language
    #: E.164, canonicalised by :func:`normalise_phone`. ``None`` until the customer shares it.
    phone_e164: str | None
    #: Without the ``@``. Telegram's own field carries it bare; storing it with the sigil
    #: would make an operator's search for ``gulom`` miss the row that starts with ``@``.
    telegram_username: str | None
    first_name: str | None
    last_name: str | None
    #: Telegram's stable per-bot id for the photo, so a later fetch can skip an unchanged one.
    avatar_file_unique_id: str | None
    #: Recorded because ``LocalFileStorage.put`` accepts a ``content_type`` and persists none
    #: of it (``storage.py:149-173`` returns it on the ``StoredObject`` and discards it).
    #: Without the column the admin route would have to GUESS a content type for a blob, and
    #: a guessed content type on stored bytes is how an uploaded image becomes stored XSS.
    avatar_mime: str | None
    #: Presence flag AND timestamp. There is no ``avatar_storage_key`` column and there never
    #: will be: the key is reconstructible from ``user_id`` alone (:func:`avatar_key`).
    avatar_stored_at: datetime | None
    #: When the customer last chose a language deliberately — not when a fallback was used.
    language_chosen_at: datetime | None
    phone_shared_at: datetime | None
    onboarded_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def is_onboarded(self) -> bool:
        """Whether the wizard may start. Reads ``phone_e164`` and NEVER ``onboarded_at``.

        The two agree today, because ``/forget`` deletes the whole row and there is no way to
        hold one without the other. The distinction is insurance against the change that
        stops deleting and starts nulling in place: an ``onboarded_at``-based answer would
        then claim an onboarding whose evidence had just been erased, and the bot would wave
        the customer into the wizard while holding no number to deliver their song to — and
        would never ask for one again, because it believes it already did.

        The number is the gate because the number is the fallback delivery channel; a
        language alone buys the customer nothing.
        """
        return self.phone_e164 is not None


def normalise_phone(raw: str) -> str | None:
    """The one canonical spelling of a shared number, or ``None`` if it is not one.

    ``None`` is a REFUSAL, not an error: the caller renders ``onboarding.contact.required``
    and asks again. That is why this returns an optional rather than a ``Result`` and why it
    cannot raise — a number the parser dislikes must produce a screen, never a traceback and
    never an ``Err`` travelling up a seam that is supposed to mean "the database broke".

    Normalisation happens HERE and nowhere else, because two spellings of one number are two
    people as far as an operator's search is concerned, and ``user_profiles.phone_e164`` is
    deliberately unindexed and unfilterable — a duplicate would never be noticed by a
    constraint. :meth:`UserProfileStore.record_contact` therefore trusts what it is handed
    rather than re-validating, so that there is one definition of a valid number instead of
    two that drift.

    **The pattern admits every country on purpose.** A Russian or Kazakh number is entirely
    plausible in this market, and a customer whose SIM is not Uzbek must not be told their own
    phone is invalid. It is also why the admin mask may not keep a fixed ``+998`` head in the
    clear (CONTRACTS §6): a mask that assumed the country code would publish two *subscriber*
    digits of ``+79161234567`` while hiding the part that is not secret.
    """
    candidate = raw.strip()
    for noise in _PHONE_NOISE:
        candidate = candidate.replace(noise, "")
    if not candidate:
        return None
    if not candidate.startswith("+"):
        candidate = f"+{candidate}"
    match = _PHONE_PATTERN.match(candidate)
    return match.group(0) if match is not None else None


def avatar_key(user_id: object) -> str:
    """The ONE spelling of a profile photo's object key: ``users/{user_id}/avatar.jpg``.

    Four things this shape decides, each closing a specific failure:

    1. **It lives here and not in ``bayram.storage``.** ``tests/test_admin/test_asset_stream.py``
       (line 712) asserts that everything the admin package imports from ``bayram.storage`` is
       within ``{"LocalFileStorage", "archive_key"}``, and the avatar route must rebuild this
       key server-side rather than trust one off the wire. Putting the builder in
       ``bayram.storage`` would fail that assertion the day the route lands, and the cheap way
       out of a failing import cap is to widen the cap — which is the whole point of it gone.
       ``bayram.storage`` gets no edit at all.
    2. **It is keyed on the ``users.id`` UUID**, mirroring ``archive_key``'s
       ``orders/{order_id}/…``, so a raw Telegram id never becomes a directory name on disk
       and the key is not guessable by anyone who knows a customer's account.
    3. **The filename is FIXED.** A customer who changes their photo is a re-download that
       overwrites the same object; a key that carried ``file_unique_id`` would leave one
       unreachable blob per photo change, with nothing recording that it exists.
    4. **It is reconstructible from the id alone**, which is what lets ``/forget`` delete the
       bytes with no ``avatar_storage_key`` column existing anywhere — and lets that delete
       run unconditionally, so bytes written by a ``record_avatar`` whose row update later
       failed can never outlive the erasure.

    ``object`` rather than ``UUID`` matches ``archive_key``'s own signature: callers pass a
    ``UUID`` today, and the formatting is the contract.
    """
    return f"users/{user_id}/avatar.jpg"


@runtime_checkable
class UserProfileStore(Protocol):
    """The seam between "who is this customer?" and the table that answers.

    Every method returns a ``Result`` and NONE of them raises — the rule ``bayram.contracts``
    states for every protocol in this codebase, honoured on the other side by
    ``bayram.db.guard.run_guarded``, which turns a ``SQLAlchemyError`` into an ``Err``. Onboarding
    runs inside the FSM isolation lock and answers a live customer: a leaked exception there
    is a handler that never replies, and a customer staring at a keyboard that does nothing.

    The implementation is ``bayram.db.user_profiles.SqlUserProfiles``, which holds the
    ``Storage`` handle as well as the session factory (see the module docstring). It is
    deliberately NOT a method set on ``KitRepository``: that protocol is held by the worker,
    and widening it would hand the render worker a customer write it must never make — and
    hand ``BotDeps`` a ``create_order`` it must never call.

    ``runtime_checkable`` verifies member PRESENCE only, never signatures. ``mypy --strict``
    over ``tests`` is what actually catches a fake that has drifted from this protocol.
    """

    async def get(self, telegram_user_id: int) -> Result[UserProfile | None]:
        """The profile, or ``Ok(None)`` when there is no row for this account.

        ``Ok(None)`` is a NORMAL answer and callers must not treat it as an error. There is no
        backfill (D11), so on the deploy after revision 0014 it is the answer for the entire
        installed base, and it is the answer for every account since its ``/forget``. The two
        cases are indistinguishable on purpose (PD-3): "erased" and "never onboarded" describe
        exactly the same knowledge.

        ``Err`` means the database could not be read — a different thing entirely, which the
        caller fails OPEN on (C1-5): a customer must not be locked out of the product by an
        outage in the table that decides whether to ask them a question.

        The ``users`` row is JOINed for :attr:`UserProfile.ui_language`, INNER, because the
        primary key of this table is a foreign key onto it.
        """
        ...

    async def record_language(
        self, telegram_user_id: int, *, ui_language: Language
    ) -> Result[UserProfile]:
        """Persist a DELIBERATE language choice, and answer with the whole profile.

        Idempotent, and called from two places: the first screen a new customer ever sees, and
        the settings picker every time afterwards. It creates the ``users`` row and the
        profile row if they do not exist, which is why it can be the first thing that ever
        happens to an account.

        It is the ONE writer that refreshes ``users.ui_language`` from a choice. Everything
        else that writes that column writes a guess: ``credits.touch`` carries whatever
        language the draft happened to be rendering in, and ``users_sql.ensure_user`` is
        called with ``is_language_authoritative=False`` from order creation precisely so that
        placing an order cannot stamp the brief's language over the one the customer picked in
        settings. Returning the profile rather than ``None`` lets the caller redraw the
        settings screen from the stored truth instead of from what it just tried to write.
        """
        ...

    async def record_contact(
        self,
        telegram_user_id: int,
        *,
        phone_e164: str,
        telegram_username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> Result[UserProfile]:
        """Store the shared contact — the step that makes :attr:`UserProfile.is_onboarded` true.

        **This seam trusts its inputs, deliberately.** The caller has already checked that
        ``message.contact.user_id == message.from_user.id`` — Telegram lets anyone forward a
        third party's contact card, and a stranger's number stored as this customer's is a
        song delivered to the wrong person — and has already run :func:`normalise_phone`, so
        what arrives is E.164. Re-validating here would put two definitions of "a valid
        number" in the tree, and the day they drift the second one wins silently.

        The identity fields come from ``message.from_user`` rather than from the contact card:
        the card carries whatever the sharer typed into their address book, while the account
        fields are what Telegram itself knows. An ``Err`` here must be reported to the
        customer rather than swallowed, because a "thank you" for a number that was not stored
        is a promise the delivery fallback cannot keep.
        """
        ...

    async def record_avatar(
        self, telegram_user_id: int, *, image: bytes, mime: str, file_unique_id: str
    ) -> Result[None]:
        """Store the profile photo. **Best effort — a failure here is not an onboarding failure.**

        ``Ok(None)`` is the answer to "there is no profile row yet", "that MIME is not
        :data:`AVATAR_MIME`" and "the object store refused the write" alike. None of those is
        a reason to stop a customer from ordering a song, and a caller that had to distinguish
        them would grow a branch per case at the one step where the bot must simply move on.
        Each is logged where it happens, so the silence is in the flow and not in the record.

        An unknown MIME is DISCARDED rather than stored: if Telegram ever serves WebP profile
        photos, that surfaces as a logged refusal instead of a blob the admin panel serves
        under a content type it guessed. See :data:`AVATAR_MIME`, which is where that string
        is defined for the whole tree — the bot's fetcher passes exactly it, and the admin
        route's allowlist is built from it.

        ``avatar_mime`` is recorded on the row because ``LocalFileStorage.put`` takes a
        ``content_type`` and persists none of it; ``file_unique_id`` is recorded so a later
        fetch can skip a photo that has not changed. The object key is not stored at all — it
        is :func:`avatar_key` of the ``users.id``.
        """
        ...

    async def forget(self, telegram_user_id: int) -> Result[None]:
        """Honour ``/forget``: delete the row, then the avatar's bytes. PD-3.

        A DELETE and not a blanking, so there is no half-erased row for a later read to
        misinterpret, nothing to stamp, and no clock to reconcile — this table is on none
        (PD-2), so the absence of the row IS the erasure record. The ``users`` row survives,
        because an operator's block must survive a data-subject request; what dies with this
        statement is the number, the username, the name and the face.

        The object is deleted AFTER the row transaction commits and UNCONDITIONALLY — whether
        or not ``avatar_stored_at`` was set — because ``LocalFileStorage.delete`` treats a
        missing object as success, so the cost is one no-op unlink and the benefit is that
        bytes written by a ``record_avatar`` whose row update later failed cannot outlive the
        erasure. ``repository._replace_assets`` argues the identical trade.

        Idempotent and total: an account that never onboarded has nothing to erase, which is a
        successful erasure and not a failure — the shape ``EntitlementStore.forget`` already
        documents. The caller runs this BEFORE the credit erasure, because the number and the
        photograph are the most sensitive things in the request, and reports an ``Err`` rather
        than claiming a deletion that did not happen.
        """
        ...
