"""``broadcast_bodies`` — what a campaign actually says, one row per language.

**A child table rather than a JSON blob on ``broadcasts``, and the reason is enforcement.**
A blob cannot carry ``UNIQUE (broadcast_id, language)`` and cannot carry a length or an
emptiness ``CHECK``. Those three constraints are the whole difference between a campaign that
cannot ship with an empty Russian body and one that ships with an empty Russian body to
eleven thousand people, and a blob's alternative is validation in whichever writer happens to
run — which is the validation every writer added later forgets.

**THE BODY NAMES NOBODY, AND THAT IS A PRODUCT RULE, NOT AN OMISSION.** There is no
``{placeholder}`` interpolation at any layer: a body is the same text for everyone who reads
that language. It is what keeps this table free of personal data (see below), it is what makes
one rendered message reviewable before a send instead of forty thousand unreviewable ones, and
it is what stops a mail-merge bug greeting a customer by a recipient's name out of a brief.

**One optional image and one optional URL button. Nothing else.** The attachment is stored as
TWO columns and a reviewer arriving from ``assets`` will recognise both:
:attr:`BroadcastBodyRow.media_storage_key` is where the operator's upload lives in our own
object store, because the admin process is forbidden a Telegram bot token
(``FORBIDDEN_ENV_VARS``) and therefore cannot obtain a ``file_id`` at compose time;
:attr:`BroadcastBodyRow.media_file_id` is what Telegram hands back on the FIRST send, cached
so the remaining thirty-nine thousand nine hundred and ninety-nine reuse it. That is
``assets.tg_file_id``'s cost control (SoW FIL-4) applied to the one message shape that
multiplies it by the size of an audience: uploading the same photograph per recipient is the
difference between a campaign that costs bytes once and one that costs bytes forty thousand
times.

**The caption ceiling is a CHECK, not a convention.** Telegram accepts 4 096 characters in a
message and 1 024 in a photo caption. A body over that ceiling with an image attached is a
``TelegramBadRequest`` for EVERY recipient — a dead campaign, discovered one message at a
time — so the database refuses the pair rather than the send discovering it. The same
argument the HTML validation makes at compose time (§3.3), one layer lower and unbypassable.

**Not personal data, and in NEITHER of ``tests/test_db/test_privacy_constraints.py``'s two
sets**, recorded there rather than left silent. Every column is a UUID, a closed
:class:`~hbd.contracts.Language`, a storage key, a Telegram file id, a URL, or operator-
authored marketing copy addressed to a population — and by the no-interpolation rule above,
that copy cannot contain a customer's name, number or order. It is text FROM us, never text
ABOUT a person, which is the distinction ``vendor_usage``'s exemption turns on.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.contracts import Language
from hbd.db.base import Base, TimestampMixin, enum_type

__all__ = [
    "BroadcastBodyRow",
    "BROADCAST_BODY_LENGTH",
    "BROADCAST_CAPTION_LENGTH",
    "BUTTON_LABEL_LENGTH",
    "BUTTON_URL_LENGTH",
    "MEDIA_STORAGE_KEY_LENGTH",
    "MEDIA_FILE_ID_LENGTH",
]

#: Telegram's own limit on a text message, and the same number ``bot.delivery``'s
#: ``MAX_MESSAGE_CHARS`` holds. Spelled here rather than imported: a model in ``hbd.db`` must
#: not depend on ``hbd.bot``, and the two are pinned to each other by the sender that would
#: fail loudly on any drift.
BROADCAST_BODY_LENGTH: Final[int] = 4_096
#: Telegram's limit on a PHOTO CAPTION — a quarter of the above. Enforced by
#: ``ck_broadcast_bodies_caption_length`` whenever an image is attached; see the module
#: docstring.
BROADCAST_CAPTION_LENGTH: Final[int] = 1_024
#: One inline button, whose label is rendered inside it. Short by construction.
BUTTON_LABEL_LENGTH: Final[int] = 64
#: An ``https://`` URL. Matches ``assets.PATH_LENGTH``, which is the same kind of bound.
BUTTON_URL_LENGTH: Final[int] = 512
#: Object-store key of the operator's upload. ``assets.storage_key``'s width, because it is
#: the same bucket and the same key shape.
MEDIA_STORAGE_KEY_LENGTH: Final[int] = 512
#: Telegram's opaque handle for a file it already holds. ``assets.TG_FILE_ID_LENGTH``.
MEDIA_FILE_ID_LENGTH: Final[int] = 128


class BroadcastBodyRow(TimestampMixin, Base):
    """The message one language group receives.

    ``TimestampMixin`` IS used: a draft is revised, and ``updated_at`` is the answer to "was
    this the text that went out, or did somebody edit it after?" — which the revise endpoint
    refuses after ``draft`` precisely so the answer stays "yes".
    """

    __tablename__ = "broadcast_bodies"
    __table_args__ = (
        # One body per language per campaign. Unnamed so ``NAMING_CONVENTION``'s ``uq``
        # template renders ``uq_broadcast_bodies_broadcast_id_language``, which is what the
        # migration must spell through ``batch_op.f``.
        #
        # It is also the ONLY index this table gets: its leading column is ``broadcast_id``,
        # so the one read anybody performs — "every body for this campaign" — is served by it
        # already, and a second index on ``broadcast_id`` would be the redundant leading-column
        # duplicate ``orders`` records as a mistake this codebase has made before.
        sa.UniqueConstraint("broadcast_id", "language"),
        # An empty body is a message that says nothing to everybody. ``String`` length caps
        # the top; nothing but this caps the bottom.
        sa.CheckConstraint("length(text) > 0", name="text_not_empty"),
        # A label with no URL renders a dead button; a URL with no label renders nothing at
        # all. Neither is a state a composer meant to reach.
        sa.CheckConstraint(
            "(button_label IS NULL) = (button_url IS NULL)",
            name="button_pair",
        ),
        # See the module docstring: with an image attached the body is a CAPTION, and Telegram
        # refuses a caption over 1 024 characters for every recipient alike.
        sa.CheckConstraint(
            f"media_storage_key IS NULL OR length(text) <= {BROADCAST_CAPTION_LENGTH}",
            name="caption_length",
        ),
        # The cached handle is meaningless without the file it was cached FOR: a ``file_id``
        # with no stored original cannot be re-sent after Telegram forgets it, and cannot be
        # re-uploaded either.
        sa.CheckConstraint(
            "media_file_id IS NULL OR media_storage_key IS NOT NULL",
            name="media_pair",
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: ``CASCADE`` because a body is meaningless without its campaign — unlike a recipient
    #: row, which is also cascaded, and unlike the audit trail, which is not reachable from
    #: here at all.
    broadcast_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False
    )
    #: Which language group reads this. The recipient row snapshots the account's language at
    #: expansion and the sender picks the body from it, so a customer who switches languages
    #: after the audience was frozen still receives the message they were counted in.
    language: Mapped[Language] = mapped_column(enum_type(Language), nullable=False)
    #: The message. HTML, because the bot runs ``parse_mode=HTML`` globally — validated
    #: against Telegram's tag set at compose time, since an unclosed tag is a refusal for
    #: every recipient rather than a typo in one.
    text: Mapped[str] = mapped_column(sa.String(BROADCAST_BODY_LENGTH), nullable=False)
    #: The optional image, in OUR object store. NULL for a text-only campaign.
    media_storage_key: Mapped[str | None] = mapped_column(
        sa.String(MEDIA_STORAGE_KEY_LENGTH), nullable=True
    )
    #: Telegram's handle for that image once it has taken it, written by the WORKER after the
    #: first successful send and reused by every send after. NULL until then, and NULL forever
    #: on a text-only campaign.
    media_file_id: Mapped[str | None] = mapped_column(
        sa.String(MEDIA_FILE_ID_LENGTH), nullable=True
    )
    #: The optional inline button. Both columns or neither —
    #: ``ck_broadcast_bodies_button_pair``.
    button_label: Mapped[str | None] = mapped_column(sa.String(BUTTON_LABEL_LENGTH), nullable=True)
    button_url: Mapped[str | None] = mapped_column(sa.String(BUTTON_URL_LENGTH), nullable=True)
