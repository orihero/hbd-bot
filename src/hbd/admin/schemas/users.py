"""Wire models for ``/users``, and the projection that makes ``/wizard-state`` safe to serve.

**The date column is "last order", not "last seen", and the name is the whole point.**
``users`` is written by ``repository._ensure_user``, which is called only from
``_create_order``, so the row's clock advances when an order is *created* and at no other
moment — and somebody who walks the entire wizard without confirming has no row at all.
``users.last_seen_at`` therefore does not mean what its name says, and a panel column headed
"last seen" would be a claim about presence derived from a column that measures purchases.
Phase 3's inbound middleware gives it a real writer; until then this layer reports
``lastOrderAt``, derived from ``MAX(orders.created_at)`` so it stays true even after that
writer lands and changes what the column means.

**``/wizard-state`` is a reveal surface, and it is built from an allowlist.** The FSM draft
is the copy that holds the recipient's display name, the free-text note and the entire
approved lyric — and for a session somebody abandoned, it is the *only* copy that ever
exists. :func:`to_wizard_state_view` therefore never walks the stored dict. It reads a fixed
list of key names and emits, for each, presence and a character count. A denylist would ship
the next field somebody adds to :class:`~hbd.bot.draft.WizardDraft`; an allowlist omits it
until a human adds it here, which is the failure direction that does not leak.

There is no unmasked variant of the wizard state at any role, including OWNER. §6.6 states
it and §12.3's table repeats it: the plaintext is reachable only through ``POST /reveal``
with ``subjectType="wizard_draft"``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from hbd.admin.schemas.common import ApiModel
from hbd.admin.schemas.page import PageMeta
from hbd.admin.serializers.redaction import mask_telegram_user_id
from hbd.contracts import Language, OrderState
from hbd.db.admin.views import UserDetail, UserListItem

__all__ = [
    "UserView",
    "UsersPage",
    "OrderStateCount",
    "UserDetailView",
    "DraftFieldView",
    "WizardStateView",
    "WIZARD_TEXT_FIELDS",
    "WIZARD_CHOICE_FIELDS",
    "to_user_view",
    "to_user_detail_view",
    "to_wizard_state_view",
]

#: Draft keys whose value is free text or a name — reported as presence plus a length, never
#: as a value. ``recipient`` and ``lyrics`` are nested objects; their character counts are
#: computed from the sub-keys named in :data:`_TEXT_SUBKEYS` rather than by stringifying the
#: object, because ``str(dict)`` would put the plaintext into the count's own input and one
#: careless ``repr`` later into the response.
WIZARD_TEXT_FIELDS: Final[tuple[str, ...]] = ("note", "recipient", "lyrics")

#: Draft keys whose value is a closed-vocabulary choice, safe to return verbatim. §12.3 puts
#: enums, states and timestamps in the "always visible" row: an occasion is not personal data
#: and hiding it would make the screen useless for the triage it exists for.
WIZARD_CHOICE_FIELDS: Final[tuple[str, ...]] = (
    "ui_language",
    "occasion",
    "genre",
    "vocal_gender",
    "output_language",
)

#: Where the characters live inside the two nested draft values. Only these sub-keys are read.
_TEXT_SUBKEYS: Final[dict[str, tuple[str, ...]]] = {
    "recipient": ("display",),
    "lyrics": ("title", "name_display"),
}


class UserView(ApiModel):
    """One row of ``/users``. There is deliberately no ``lastSeenAt`` — see the module docs."""

    id: UUID
    telegram_user_id: int
    telegram_user_id_masked: str
    ui_language: Language
    is_blocked: bool
    #: When the ``users`` row was inserted — i.e. when this person's FIRST order was created.
    account_created_at: datetime
    first_order_at: datetime | None
    last_order_at: datetime | None
    order_count: int
    paid_order_count: int


class UsersPage(ApiModel):
    items: list[UserView]
    meta: PageMeta


class OrderStateCount(ApiModel):
    """One state with at least one order. States with none are absent, never zero-filled."""

    state: OrderState
    count: int


class UserDetailView(ApiModel):
    user: UserView
    orders_by_state: list[OrderStateCount]
    delivered_order_count: int
    failed_order_count: int


class DraftFieldView(ApiModel):
    """One allowlisted draft key: whether it is there, and how much of it there is.

    ``charCount`` is ``null`` for a key that is absent and ``0`` for one present and empty —
    a distinction that matters when the question is "did they type a note and delete it?".
    """

    key: str
    is_present: bool
    char_count: int | None = None


class WizardStateView(ApiModel):
    """The projected FSM draft. No plaintext, at any role.

    ``isStatePresent`` is false for a user with no live wizard session at all, which is the
    normal state of everyone who is not mid-flow right now. It is distinct from a session
    that exists and is empty, and from one whose TTL is about to take it: the draft expires
    on the abandoned-draft clock (``build_storage``'s ``data_ttl``), so an absent state may
    simply mean the sweep already happened.
    """

    telegram_user_id: int
    telegram_user_id_masked: str
    is_state_present: bool
    #: aiogram's raw state string, e.g. ``Wizard:note``. A closed vocabulary the bot defines.
    state: str | None = None
    #: Which run through the wizard this draft belongs to — the id the order id hashes over.
    session_id: str | None = None
    #: Closed-vocabulary answers, returned verbatim per §12.3's "always visible" row.
    choices: dict[str, str] = {}
    #: One entry per key in :data:`WIZARD_TEXT_FIELDS`, always all of them.
    text_fields: list[DraftFieldView] = []
    #: How many times this session has asked the lyric writer — the spend an operator is
    #: usually looking at this screen to explain.
    lyric_writes: int | None = None


def to_user_view(item: UserListItem) -> UserView:
    return UserView(
        id=item.id,
        telegram_user_id=item.telegram_user_id,
        telegram_user_id_masked=mask_telegram_user_id(item.telegram_user_id),
        ui_language=item.ui_language,
        is_blocked=item.is_blocked,
        account_created_at=item.account_created_at,
        first_order_at=item.first_order_at,
        last_order_at=item.last_order_at,
        order_count=item.order_count,
        paid_order_count=item.paid_order_count,
    )


def to_user_detail_view(detail: UserDetail) -> UserDetailView:
    return UserDetailView(
        user=to_user_view(detail.user),
        orders_by_state=[
            OrderStateCount(state=state, count=count) for state, count in detail.orders_by_state
        ],
        delivered_order_count=detail.delivered_order_count,
        failed_order_count=detail.failed_order_count,
    )


# ---------------------------------------------------------------------------
# the wizard-state projection
# ---------------------------------------------------------------------------
def _char_count(key: str, value: object) -> int | None:
    """Length of the text under ``key``, without the text ever leaving this function.

    A plain string counts itself. A nested object counts only the sub-keys named in
    :data:`_TEXT_SUBKEYS` — never every string it happens to contain, because "sum the
    lengths of everything in there" is the shape that starts reading a field somebody adds
    later. Anything of an unexpected type counts as ``None``: a draft written by another
    build is data this layer does not understand, and guessing its length would be a claim
    about a value it could not parse.
    """
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        parts = [value.get(subkey) for subkey in _TEXT_SUBKEYS.get(key, ())]
        lengths = [len(part) for part in parts if isinstance(part, str)]
        return sum(lengths) if lengths else None
    return None


def _choice(value: object) -> str | None:
    """A closed-vocabulary answer as text, or ``None`` for anything that is not one.

    ``str`` and nothing else. The draft is JSON from Redis, so a value here is whatever a
    previous build wrote; coercing a dict or a list into a label with ``str()`` would put
    an arbitrary payload into a field the panel renders as an enum.
    """
    return value if isinstance(value, str) else None


def to_wizard_state_view(
    telegram_user_id: int, *, state: str | None, draft: dict[str, Any] | None
) -> WizardStateView:
    """Project the FSM draft. Reads an allowlist; never iterates the stored dict."""
    if draft is None:
        return WizardStateView(
            telegram_user_id=telegram_user_id,
            telegram_user_id_masked=mask_telegram_user_id(telegram_user_id),
            is_state_present=state is not None,
            state=state,
            text_fields=[DraftFieldView(key=key, is_present=False) for key in WIZARD_TEXT_FIELDS],
        )
    choices = {
        key: label for key in WIZARD_CHOICE_FIELDS if (label := _choice(draft.get(key))) is not None
    }
    text_fields = [
        DraftFieldView(
            key=key,
            is_present=draft.get(key) is not None,
            char_count=_char_count(key, draft.get(key)),
        )
        for key in WIZARD_TEXT_FIELDS
    ]
    writes = draft.get("lyric_writes")
    return WizardStateView(
        telegram_user_id=telegram_user_id,
        telegram_user_id_masked=mask_telegram_user_id(telegram_user_id),
        is_state_present=True,
        state=state,
        session_id=_choice(draft.get("session_id")),
        choices=choices,
        text_fields=text_fields,
        lyric_writes=writes if isinstance(writes, int) and not isinstance(writes, bool) else None,
    )
