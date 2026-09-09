"""``user_profiles`` — what one Telegram account told us about itself.

**A table, not columns on ``users``, and that is a decision about erasure rather than
schema taste.** Two facts in the tree today force it. ``docs/product/ADMIN_PANEL_PLAN.md:674``
records "No DDL" on ``users`` as a standing commitment; and ``credits.set_blocked``
(``src/hbd/db/credits.py``) UPSERTs a ``users`` row precisely so an operator can bar an
account that never ordered — which means a ``users`` row must be able to outlive everything
else we know about a person. ``/forget`` therefore must never delete it. But a phone
number, a username, a given name and a photograph of a face are exactly what ``/forget``
exists to delete. Put them on ``users`` and the erasure command quietly stops erasing the
most sensitive thing it was built for, with nothing in the suite positioned to notice —
``tests/test_db/test_privacy_constraints.py`` walks tables, not columns. ``UserRow``'s own
docstring already made this same call once, for the credits balance; this is that argument
applied to identity. (Do **not** justify the split with ``purge_user``: no such function
exists — ``grep -rn purge_user src/`` finds only ``db/enums.py`` and
``bot/handlers/commands.py`` describing it as unbuilt.)

**Revision 0017 broke the "No DDL" commitment for one column** (``users.blocked_bot_at``,
the churn fact) **and this table's argument does not depend on it.** The DDL freeze was
always the weaker half: the load-bearing half is the erasure asymmetry in the paragraph
above — the ``users`` row must SURVIVE ``/forget`` so a block can outlive an erasure, and a
number and a face are precisely what ``/forget`` exists to delete. That half is untouched,
so nothing about the freeze falling licenses moving the phone number or the photograph onto
``users``.

**Keyed on ``users.id``, not on ``telegram_user_id``** — deliberately unlike
``credit_accounts`` and ``lyric_budgets``, which key on Telegram's own id because they are
charged several screens before any ``users`` row exists. The unmask path is what decides it
here: ``RevealRequest.subject_id`` is a ``UUID`` by construction
(``src/hbd/admin/schemas/reveal.py:182``, ``:282``) and the step-up scope is spelled
``reveal:<str(uuid)>``, so ``users.id`` is the identifier the audited reveal machinery
already carries end to end. Keying on the Telegram id instead would mean either a
reveal-model change or a join on every unmask, forever, to answer a question the primary
key can answer for free. The objection that onboarding happens before any order — so there
may be no ``users`` row to point at — is answered by ``hbd.db.users_sql.ensure_user``, which
creates the row at first contact, and not by changing the key. The foreign key also makes
the avatar's object key derivable from the primary key alone.

**There is no ``avatar_storage_key`` column.** The key is ``hbd.user_profiles.avatar_key``
of the ``user_id`` and every site rebuilds it from the row it already holds. That is the
one shape in which the archive-orphan bug ``repository._replace_assets`` documents at
``repository.py:362-380`` — a row recording one spelling of a key while the bytes live
under another, so the sweep deletes the record and the bytes stay forever — is
structurally impossible rather than merely fixed.

**There is no retention clock: no ``profile_expires_at``, no ``profile_purged_at``.** The
product owner chose "kept while the account exists" (PD-2), so there is no date to store
and no sweep to run; ``/forget`` DELETEs the row and the row's *absence* is the erasure
record. That claim is enforced, not merely asserted here:
``tests/test_db/test_privacy_constraints.py`` holds a ``tables_erased_on_request`` set
naming this table beside the ``tables_with_personal_data`` set that demands an
``*_expires_at`` of everything in it, and asserts the two disjoint — so a personal-data
table is either on a clock or named as erased on request, and never silently absent from
both. ``tests/test_db/test_audit_retention.py`` needs no entry for this table: both of its
derivations filter on ``name.endswith("expires_at")``, so a table with no such column is
ignored by construction.

**The foreign key is ``ON DELETE CASCADE`` even though nothing deletes a ``users`` row
today.** It is the cheapest possible guarantee that a profile can never outlive the account
it describes — a lie about who a phone number belongs to being the worst failure this table
can produce — and it costs exactly nothing for as long as "nothing deletes a ``users`` row"
stays true. If that ever changes, the guarantee is already in the schema instead of in a
code path someone has to remember to write.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, TimestampMixin, UtcDateTime

__all__ = [
    "UserProfileRow",
    "PHONE_LENGTH",
    "USERNAME_LENGTH",
    "NAME_LENGTH",
    "FILE_ID_LENGTH",
    "MIME_LENGTH",
]

#: E.164 admits at most fifteen digits, and one leading ``+`` is the only punctuation
#: :func:`hbd.user_profiles.normalise_phone` ever emits. Sixteen is therefore the exact
#: bound rather than a round number, and a value that does not fit is a number that did not
#: come through the normaliser.
PHONE_LENGTH: Final[int] = 16
#: Telegram's own ceiling on a ``@username``, stored without the ``@`` — the sigil is
#: presentation, and keeping it out of the column stops two spellings of one handle from
#: reaching an operator's search.
USERNAME_LENGTH: Final[int] = 32
#: Telegram's own ceiling on ``first_name`` and ``last_name``. Matching the source rather
#: than choosing our own means a name we would have truncated cannot exist upstream.
NAME_LENGTH: Final[int] = 64
#: Telegram's ``file_unique_id`` is far shorter than this today; the headroom is here so a
#: format change upstream surfaces as a longer id we still store, not as a truncation that
#: makes every subsequent photo look changed.
FILE_ID_LENGTH: Final[int] = 64
#: An IANA media type with parameters. Only :data:`hbd.user_profiles.AVATAR_MIME` is ever
#: written today, but the column is sized for a real content type rather than for that one
#: literal, because a column sized to today's single value is how the next value silently
#: becomes a truncation.
MIME_LENGTH: Final[int] = 64


class UserProfileRow(TimestampMixin, Base):
    """The identity facts one account shared, all of them erased together by ``/forget``.

    Every column here is either personal data or the provenance of a piece of personal
    data, which is what makes the whole-row DELETE in ``hbd.db.user_profiles`` a complete
    erasure that needs no column-by-column audit. Nothing operational lives here: the
    language *preference* stays on ``users.ui_language`` (a preference on the row that
    survives ``/forget``), and the timestamps below record when we were told something, not
    when we may stop knowing it.
    """

    __tablename__ = "user_profiles"

    #: The account this describes, and the primary key. ``ON DELETE CASCADE`` so a profile
    #: can never outlive its ``users`` row; see the module docstring for why this and not
    #: ``telegram_user_id``.
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    #: Telegram's own account id, ``UNIQUE`` because it is the lookup key on both live
    #: paths — every bot update carries it and ``/api/users/{telegram_user_id}/**`` is
    #: addressed by it — while the primary key is what the reveal path carries. Without the
    #: uniqueness a retried onboarding could open a second profile for one account and the
    #: two would disagree about the same person's number.
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, unique=True)
    #: The delivery number, in the single canonical spelling
    #: :func:`hbd.user_profiles.normalise_phone` produces. Deliberately **not** indexed and
    #: not filterable: an index would make "who has this number" a cheap question for
    #: anyone with panel access, and the panel never needs to ask it — it reaches a profile
    #: through the account, never through the number.
    phone_e164: Mapped[str | None] = mapped_column(sa.String(PHONE_LENGTH), nullable=True)
    #: The ``@username`` without its ``@``. Nullable because most accounts have none, and
    #: because an account can drop one at any time — a stored handle is what we were told,
    #: not a claim about what is true now.
    telegram_username: Mapped[str | None] = mapped_column(sa.String(USERNAME_LENGTH), nullable=True)
    #: Telegram's ``first_name``. Kept so an operator reading a delivery failure sees a
    #: person rather than an integer; masked on every wire the panel serves.
    first_name: Mapped[str | None] = mapped_column(sa.String(NAME_LENGTH), nullable=True)
    #: Telegram's ``last_name``, absent for most accounts and stored on the same terms as
    #: ``first_name``.
    last_name: Mapped[str | None] = mapped_column(sa.String(NAME_LENGTH), nullable=True)
    #: Telegram's stable per-file id for the profile photo we stored, so a later fetch can
    #: compare ids and skip re-downloading a photo that has not changed. Without it every
    #: refresh pays for the bytes again to learn they are the same bytes.
    avatar_file_unique_id: Mapped[str | None] = mapped_column(
        sa.String(FILE_ID_LENGTH), nullable=True
    )
    #: The content type the stored avatar bytes actually are. ``LocalFileStorage.put``
    #: accepts a content type and persists none, so without this column the admin avatar
    #: route would have to guess one for a blob it is about to serve — and a served image
    #: whose type is guessed is how a stored image becomes stored XSS. The route matches
    #: this value whole against :data:`hbd.user_profiles.AVATAR_MIME` and 415s otherwise.
    avatar_mime: Mapped[str | None] = mapped_column(sa.String(MIME_LENGTH), nullable=True)
    #: When the avatar bytes were written — presence flag *and* provenance in one column.
    #: There is no ``avatar_storage_key`` beside it: the key is
    #: :func:`hbd.user_profiles.avatar_key` of ``user_id``, rebuilt wherever it is needed,
    #: so this row can never name a location the bytes are not in.
    avatar_stored_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: When this account first told us which language to speak. **Write-once.** It answers
    #: "when did this person choose", so a later change in Settings must not move it —
    #: otherwise the only evidence that the first choice was made at all is overwritten by
    #: every subsequent one, and an account that has chosen four times looks new.
    language_chosen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: When the *current* number was shared. A re-share moves this and leaves
    #: :attr:`onboarded_at` alone — it is the freshness of the number we would dial.
    phone_shared_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: When this account first completed onboarding. Distinct from
    #: :attr:`phone_shared_at` on purpose: collapse the two and every returning customer who
    #: updates their number appears in the admin list as newly onboarded, which turns the
    #: only cohort figure the panel has into noise.
    onboarded_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
