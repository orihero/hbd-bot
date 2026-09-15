"""Wire models for ``/users``, and the projection that makes ``/wizard-state`` safe to serve.

**The date column is "last order", not "last seen", and the name is the whole point.**
``users`` has THREE writers and none of them is an order alone: ``users_sql.ensure_user``,
called from ``repository._create_order`` when an order is placed and from
``SqlUserProfiles.record_language`` when somebody answers the very first question the bot
asks; ``credits.touch``, which upserts the row with ``last_seen_at=now`` on every inbound
update; and ``credits.set_blocked``, which upserts it so an operator can bar an account that
never ordered. ``accountCreatedAt`` therefore means FIRST CONTACT, not first purchase, and
this list contains people who have bought nothing — which is what onboarding bought the
panel, not a regression. The previous version of this paragraph claimed one writer, one call
site and "somebody who walks the entire wizard without confirming has no row at all"; every
clause of it was already false in the shipped code before onboarding landed, which is why it
is spelled out here rather than left as a name a reader is expected to trust.

``lastSeenAt`` is still absent from this wire, and the reason has changed rather than gone
away. The column has a real writer now, but it is written per *update*, so publishing it
would turn a screen whose stated purpose is records into a minute-by-minute activity feed
about a customer. ``lastOrderAt`` is derived from ``MAX(orders.created_at)`` and says one
bounded, purchase-shaped thing no matter what a later writer does to the column.

**There is no ``telegramUsername``, ``firstName``, ``lastName`` or ``phoneE164`` on this
wire, at any role, OWNER included.** ``RECORDS_READ`` is ``M`` in all four cells of §12.3's
table, and :class:`~bayram.admin.schemas.common.ApiModel` is ``frozen=True, extra="forbid"``,
so a plaintext field cannot be smuggled in later without editing this model — which is the
property that makes the masking claim checkable rather than aspirational. ``telegramUserId``
ships unmasked beside its own mask and that is not an inconsistency: every ``/users/**``
route keys on it, so the panel could not build a link or a reveal without it. Nothing routes
on a name, a handle or a number, so nothing here carries one, and ``POST /reveal`` stays the
only path to the plaintext.

**The credit columns are on this wire unmasked, and that costs nothing this file protects.**
``credit_accounts`` holds a Telegram id, three integers and two clocks — no free text, no
name, nothing about a person that ``orders.telegram_user_id`` does not already say — which is
why it is deliberately absent from ``tables_with_personal_data``. So ``creditBalance``,
``lifetimeCreditsGranted`` and ``allowancePeriod`` need no mask and no reveal, and the only
care they need is the one their field comments spell out: ``null`` means *no account row* and
must never be rendered as ``0``.

**``/wizard-state`` is a reveal surface, and it is built from an allowlist.** The FSM draft
is the copy that holds the recipient's display name, the free-text note and the entire
approved lyric — and for a session somebody abandoned, it is the *only* copy that ever
exists. :func:`to_wizard_state_view` therefore never walks the stored dict. It reads a fixed
list of key names and emits, for each, presence and a character count. A denylist would ship
the next field somebody adds to :class:`~bayram.bot.draft.WizardDraft`; an allowlist omits it
until a human adds it here, which is the failure direction that does not leak.

There is no unmasked variant of the wizard state at any role, including OWNER. §6.6 states
it and §12.3's table repeats it: the plaintext is reachable only through ``POST /reveal``
with ``subjectType="wizard_draft"``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from bayram.admin.schemas.common import ApiModel
from bayram.admin.schemas.page import PageMeta
from bayram.admin.serializers.redaction import (
    mask_name,
    mask_phone,
    mask_telegram_user_id,
    mask_username,
)
from bayram.contracts import Language, OrderState
from bayram.db.admin.views import SegmentBreakdown, UserDetail, UserListItem

__all__ = [
    "UserView",
    "UsersPage",
    "UserStatsView",
    "OrderStateCount",
    "UserDetailView",
    "DraftFieldView",
    "WizardStateView",
    "WIZARD_TEXT_FIELDS",
    "WIZARD_CHOICE_FIELDS",
    "to_user_view",
    "to_user_stats_view",
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
    #: When the ``users`` row was inserted — i.e. this account's FIRST CONTACT, whichever of
    #: the three writers named in the module docstring got there first. It is not the first
    #: order, and reading it as one understates how long an account has existed by everything
    #: between the language question and the first purchase.
    account_created_at: datetime
    first_order_at: datetime | None
    last_order_at: datetime | None
    order_count: int
    paid_order_count: int
    #: Whether a ``user_profiles`` row exists. False is "never onboarded" and "erased by
    #: /forget" at once, deliberately: PD-3 deletes the row, so absence is the erasure record
    #: and there is no purge stamp to display beside it.
    is_profile_present: bool
    #: ``@G•••``. The handle itself is reachable only through ``POST /reveal`` with
    #: ``user_profiles.telegram_username``.
    telegram_username_masked: str | None
    first_name_masked: str | None
    last_name_masked: str | None
    #: ``•••••42``. No country prefix, by design — see ``serializers.redaction.mask_phone``.
    phone_masked: str | None
    phone_shared_at: datetime | None
    #: From ``avatar_stored_at``. Named for what it is on this side of the wire: when we last
    #: FETCHED a picture, never when the customer changed one.
    avatar_fetched_at: datetime | None
    #: Whether a row claims stored bytes. Nothing stat-ed a file to answer this, so the SPA
    #: must still handle the ``<img>`` 404-ing, and it is what lets the list avoid issuing
    #: fifty requests for accounts that have no photo.
    has_avatar: bool
    #: ``/api/users/{telegramUserId}/avatar``, or ``None`` when there is nothing to fetch.
    #: Formatted by the ROUTER and handed in, so the SPA never builds a path and a prefix
    #: change cannot be missed in TypeScript. The literal ``/avatar`` appears exactly once in
    #: this codebase, in ``routers/users.py`` beside ``USER_PATH``.
    avatar_url: str | None
    #: ``credit_accounts.balance``, or ``null`` when this account has no row there.
    #:
    #: **``null`` is a third value and the panel must render it as one — never as "0".** The
    #: column is ``NOT NULL`` in the schema, so a null here has exactly one cause: no row.
    #: That happens for a customer nobody has ever charged or granted (the row is opened by
    #: the first movement, so everybody who has talked to the bot and not confirmed an order
    #: is in this state — and they are still owed a full rolling allowance the moment they
    #: do) and for a customer whose ``/forget`` deleted it. "0 credits" says the opposite of
    #: both: it says this account has spent everything it had.
    #:
    #: There is no ``isCreditAccountPresent`` beside these three, and the asymmetry with
    #: ``isProfilePresent`` is deliberate rather than an oversight. Every profile column is
    #: independently nullable, so none of them can carry presence and a flag is the only way
    #: to say it; here the balance can carry it alone, and a redundant boolean would be a
    #: second thing to keep in step with the first.
    credit_balance: int | None
    #: Every credit ever added, allowances included — the number that answers "has this
    #: account already been comped?" without reading the ledger. ``null`` for the same one
    #: reason ``creditBalance`` is.
    lifetime_credits_granted: int | None
    #: The last rolling-allowance window this account was minted for. ``null`` for TWO
    #: reasons — no account row, or an account that has never had an allowance — and
    #: ``creditBalance`` is what tells them apart.
    allowance_period: int | None


class UsersPage(ApiModel):
    items: list[UserView]
    meta: PageMeta


class UserStatsView(ApiModel):
    """``GET /api/users/stats`` — what the population the operator has filtered to is made of.

    **These are the same four numbers ``GET /api/segments/preview`` publishes, and that is a
    property of the query rather than a resemblance between two.** Both routes hand a
    :class:`~bayram.db.admin.users.UserFilters` to
    :func:`~bayram.db.admin.users.segment_breakdown`, which is one grouped statement over the
    same ``_filtered()`` the Users list pages, so neither can drift from the screen it labels.
    The only difference is what the filters carry: the preview is narrowed by a ``?segment=``
    document **alone**, because that is the audience a human authorises a send against, while
    this route is narrowed by everything the list is currently showing — the six chips of
    §6.6, the ``from``/``to`` window, and the segment token when one is on the URL. So the
    strip above the table and the rows beneath it are one population by construction, which is
    the only way a stat strip can be trusted while an operator is still changing the filters.

    **The three refusal counts overlap and the client must not add them up.** :attr:`blocked`
    is our own bar and :attr:`bot_blocked` is the customer's — opposite facts about opposite
    subjects — and an account where both are true is counted in both, so :attr:`matched` is
    not :attr:`reachable` plus the two. Only :attr:`reachable` is defined as a complement:
    neither barred by us nor blocking us. :class:`~bayram.db.admin.views.SegmentBreakdown`
    argues the same arithmetic beside the fields it is read from, and the two must not drift.

    **This breakdown must never be added into any other total.** Every figure here is a
    statement about ONE narrowing that ONE operator chose a moment ago, so two calls with two
    filter sets count overlapping people and their sums mean nothing: adding this
    :attr:`matched` to the dashboard's audience counts, to another screen's strip, or into any
    running or lifetime figure produces a number with no population behind it. It is a caption
    for the table it sits above and nothing else.

    **Counts and nothing else, which is what keeps this an aggregate surface.** No Telegram
    id, no handle, no name, no note — not even the ``byLanguage`` split
    :class:`~bayram.admin.schemas.segment.SegmentPreviewView` carries, which is on that wire
    because language is the one personalisation a broadcast body has (§6.1) and answers no
    question this strip is asked. The breakdown is computed with it and this projection drops
    it; adding it here later would be a widening of an aggregate surface, not a formatting
    choice.
    """

    #: Everything the filter set selects. Exact rather than
    #: :data:`~bayram.db.admin.page.TOTAL_COUNT_CAP`-bounded, so it deliberately disagrees with
    #: the list's ``meta.total`` above ten thousand rows — the same split
    #: :class:`~bayram.admin.schemas.orders.OrderStateCountsView` makes, and for its reason: a
    #: strip drawn from a capped sample is wrong with nothing on the screen to reveal it,
    #: whereas "10,000+" is honest about being a ceiling.
    matched: int
    #: ``users.is_blocked IS false AND users.blocked_bot_at IS NULL`` — the only figure here
    #: that is a complement, and the one a send would actually attempt.
    reachable: int
    #: Barred by us. Counted whether or not the customer also blocked the bot.
    #:
    #: Spelled ``blocked`` and ``botBlocked`` rather than the preview's ``skippedBlocked`` /
    #: ``skippedBotBlocked``: "skipped" names what a broadcast does with these accounts, and
    #: nothing is being sent here. The wire word has to match the question the screen asks, or
    #: an operator reads a records strip as a delivery report.
    blocked: int
    #: They blocked the bot. Counted whether or not we also barred them.
    bot_blocked: int


class OrderStateCount(ApiModel):
    """One state with at least one order. States with none are absent, never zero-filled."""

    state: OrderState
    count: int


class UserDetailView(ApiModel):
    user: UserView
    orders_by_state: list[OrderStateCount]
    delivered_order_count: int
    failed_order_count: int
    #: What the BOT would tell this customer they have right now — the stored balance plus a
    #: rolling allowance that is due and not yet minted — computed by the same
    #: :func:`bayram.db.credit_sql.read_balance` function the bot's own gate calls.
    #:
    #: **The same function is not the same answer, and that distinction is load-bearing.**
    #: This line used to claim the call itself was the bot's; it is not, because
    #: ``read_balance`` takes a policy and the two processes build theirs separately — the bot
    #: through :func:`bayram.entitlements.resolve_entitlement_policy` over ``bayram.config``, this
    #: one through :func:`bayram.admin.routers.users._entitlement_policy` over mirrored
    #: ``AdminSettings`` values that the panel cannot verify. The mirrors are what make the
    #: two agree, and when one drifted the field said 4 to an operator while the customer read
    #: 1. So: same arithmetic, same due-allowance rule, and a number that is only as true as
    #: ``admin_free_allowance_credits`` and ``admin_settlement_grace_s`` are current.
    #:
    #: It is on the wire **beside** ``user.creditBalance`` rather than instead of it, because
    #: the two settle different arguments: the stored column is what the ledger can prove,
    #: and this is what the customer was shown on the Confirm screen. An operator handed only
    #: one of them cannot answer "they say they have three songs and your panel says zero",
    #: which is the support ticket this pair exists for. An ``int`` and not ``int | None``:
    #: it is computed for every account, row or no row, and "no row" is exactly what a
    #: brand-new customer with their whole allowance ahead of them looks like.
    credits_projected: int
    #: Debits this account has not settled yet, inside the settlement grace window. A render
    #: whose worker died holds a credit that neither the balance nor the ledger's totals show
    #: as spent, and this is the only number on the screen that explains why the customer is
    #: being refused.
    in_flight_render_count: int


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


def to_user_view(item: UserListItem, *, avatar_url: str | None) -> UserView:
    """Project one list row, masking every profile value on the way out.

    ``avatar_url`` is KEYWORD-ONLY, and that is not a style preference. A bare second
    positional ``str | None`` sitting beside a :class:`UserListItem` is the argument somebody
    eventually passes the wrong thing to — a masked phone, a display name — and the mistake
    type-checks, renders as a broken ``<img>`` and puts the value in the DOM's ``src``.

    The URL arrives from the router rather than being built here for the reason its field
    comment gives: the ``/avatar`` literal has exactly one home, and it is not a schema
    module. This function is the only place ``UserListItem``'s plaintext profile columns are
    read, which is what makes "no unmasked field on this wire" a property of one function
    instead of a habit spread over every handler.
    """
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
        is_profile_present=item.is_profile_present,
        telegram_username_masked=mask_username(item.telegram_username),
        first_name_masked=mask_name(item.first_name),
        last_name_masked=mask_name(item.last_name),
        phone_masked=mask_phone(item.phone_e164),
        phone_shared_at=item.phone_shared_at,
        avatar_fetched_at=item.avatar_stored_at,
        has_avatar=item.has_avatar,
        avatar_url=avatar_url,
        credit_balance=item.credit_balance,
        lifetime_credits_granted=item.lifetime_credits_granted,
        allowance_period=item.allowance_period_index,
    )


def to_user_stats_view(breakdown: SegmentBreakdown) -> UserStatsView:
    """Project the breakdown for the stat strip. Four counts out of five fields, on purpose.

    ``by_language`` is read off the same rows and dropped here rather than never computed:
    :func:`~bayram.db.admin.users.segment_breakdown` groups on the language column because that
    is what makes the whole thing one pass, and a second function that grouped on two columns
    instead of three would be a copy of a query this file has no reason to own. The projection
    is where the narrowing happens, which is also where it can be seen — see
    :class:`UserStatsView` on why a language split is a widening of this surface rather than a
    field somebody forgot.
    """
    return UserStatsView(
        matched=breakdown.matched,
        reachable=breakdown.reachable,
        blocked=breakdown.blocked,
        bot_blocked=breakdown.bot_blocked,
    )


def to_user_detail_view(detail: UserDetail, *, avatar_url: str | None) -> UserDetailView:
    """The detail envelope. Forwards ``avatar_url`` to :func:`to_user_view` unexamined.

    Keyword-only for the same reason, and forwarded rather than re-derived because a detail
    screen showing a different avatar from the list row it was opened from is a bug nobody
    would look for in a schema module.
    """
    return UserDetailView(
        user=to_user_view(detail.user, avatar_url=avatar_url),
        orders_by_state=[
            OrderStateCount(state=state, count=count) for state, count in detail.orders_by_state
        ],
        delivered_order_count=detail.delivered_order_count,
        failed_order_count=detail.failed_order_count,
        credits_projected=detail.credits_projected,
        in_flight_render_count=detail.in_flight_render_count,
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
