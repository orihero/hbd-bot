"""Wire models for the two IDENTIFIED dashboard lists — the only ones on this surface.

Every other model under ``schemas/`` that touches a customer is masked, and
:mod:`bayram.admin.schemas.overview`'s docstring states as a standing invariant that no
``telegramUserId``, no handle and no name reaches the dashboard wire at any role. **This
module is the single, deliberate exception**, and it is a separate module rather than a
block inside that one precisely so the exception cannot be read as a relaxation of the rule:
nothing here is imported by the four section responses, and nothing there has to grow an
``is_unmasked`` branch for this to exist.

**What the owner decided, and what they did not.** The sole operator of this panel decided
that an ACCOUNT HOLDER's Telegram identity may be shown to them directly — id, ``@handle``,
first name — with an AUDIT ENTRY in place of a reveal gate. So these two lists are served on
``RECORDS_READ`` from their own route, that route writes an audit row on every call, and the
payload is unmasked. What was **not** decided, and what this module must never be widened to
carry:

* **The recipient's name.** ``briefs.recipient_name_display`` and ``name_records.grapheme``
  are a third party who consented to nothing and whom no operator answers to. They stay
  behind ``POST /reveal`` with the step-up, the budget and the per-view audit row.
* **Free text, media and phone numbers.** The reveal / step-up machinery is untouched by
  this decision and is still the only path to any of them (§12.2).
* **A search box.** These are two fixed lists — the top generators of a window and the last
  N plan sales. There is no filter here that could confirm a guess about one named person,
  which is the property that makes an unmasked list cheaper than an unmasked lookup.

**A masked variant of these shapes does not exist, and adding one would be a bug.** The
route is audited *because* it is unmasked; a caller that could ask for the masked form would
be paying for a control it opted out of, and the audit row would then record a disclosure
that did not happen.

**The window belongs to ONE of the two lists, and the shape says so.** ``topGenerators``
ranks deliveries inside ``?from=``/``?to=``; ``recentSubscribers`` is a RECENCY list that
takes no window at all (:func:`bayram.db.admin.audience_lists.recent_subscribers` argues why).
A response with one ``window`` field at the top would state that both were counted over it,
so the window is carried INSIDE the top-generators block and there is no field on the
subscriber block for it to be mistaken for.
"""

from __future__ import annotations

from datetime import datetime

from bayram.admin.schemas.common import ApiModel
from bayram.admin.schemas.dashboard import WindowView, to_window_view
from bayram.contracts import Language
from bayram.db.admin.sql import TimeWindow
from bayram.db.admin.views import RecentSubscriber, TopGenerator
from bayram.db.enums import PlanKind

__all__ = [
    "TopGeneratorView",
    "TopGeneratorsView",
    "RecentSubscriberView",
    "RecentSubscribersView",
    "AudienceListsResponse",
    "to_audience_lists_response",
]


class TopGeneratorView(ApiModel):
    """One customer on the top-generators list, ranked by songs DELIVERED. Unmasked.

    ``deliveredSongs`` and ``ordersCreated`` are two numbers because the GAP between them is
    the whole story of a heavy user: forty orders and three deliveries is not a top
    generator, it is a support case, and one number cannot say which of the two the row is.

    **The pair is not a conversion rate**, and no consumer may form one from it. Both are
    counted over the same window but on different columns — an order created on Monday and
    delivered on Tuesday is in both, one created before the window and delivered inside it is
    in ``deliveredSongs`` only — so ``ordersCreated`` can legitimately be smaller than the
    count beside it, and even ``0``. :func:`bayram.db.admin.audience_lists.top_generators` says
    the same thing at the query.
    """

    #: Always present, never ``null``: ``orders.telegram_user_id`` is ``NOT NULL`` and the
    #: ranking is keyed to it, so there is no anonymous row to render here the way there is
    #: on the subscriber list below.
    #:
    #: **An erased customer still appears on this list.** ``/forget`` anonymises the receipts
    #: and DELETES the ``user_profiles`` row, but it keeps the ``users`` row (an operator's
    #: block must outlast a data-subject request) and does not touch ``orders`` at all —
    #: there is no per-user order erasure, only the time-based sweep. So such a row comes
    #: back with this id and with ``telegramUsername`` and ``firstName`` ``null``, until the
    #: orders age out. It is the same id ``GET /api/users`` already publishes for that
    #: account; render it as an account with no known name, not as a bug.
    telegram_user_id: int
    #: Telegram's ``@handle`` WITHOUT the ``@``. ``null`` when the account has none — Telegram
    #: does not require one — or when no ``user_profiles`` row was ever written for it. Not a
    #: masked value: ``null`` here means absent, never withheld.
    telegram_username: str | None
    first_name: str | None
    #: The ranking key: orders whose ``delivered_at`` fell in the window.
    delivered_songs: int
    #: Orders CREATED in the same window. See the class docstring: not a denominator.
    orders_created: int
    #: The language the BOT speaks to them in, never the language a song was sung in — the
    #: two are chosen independently and ``briefs.output_language`` is the other one.
    ui_language: Language
    #: ``users.created_at`` — FIRST CONTACT, not the first order.
    first_seen_at: datetime
    #: ``MAX(orders.delivered_at)`` over the same windowed rows. Nullable in the shape and
    #: never ``null`` from this route: presence on the list requires a delivery.
    last_delivered_at: datetime | None


class TopGeneratorsView(ApiModel):
    """The ranked list, with the window it was ranked over and the depth it was cut at."""

    #: The range ``deliveredSongs`` and ``ordersCreated`` were counted over, echoed so the
    #: card's caption comes from the server's own resolved window rather than from the
    #: request. ``null`` means the whole record.
    window: WindowView | None
    #: How deep the cut was made. On the wire because "the top ten" and "everybody, and there
    #: were nine" render differently and the list alone cannot tell them apart.
    limit: int
    #: Most deliveries first, ties broken on the Telegram id so the order is stable across
    #: reads. Empty means nothing was delivered in the window.
    items: list[TopGeneratorView]


class RecentSubscriberView(ApiModel):
    """One recent plan sale, with the buyer's identity and what the plan has left. Unmasked.

    **``isStubRail`` travels with the money and is never collapsed.**
    ``StubCheckoutProvider`` stamps a purchase paid having contacted nobody, so a demo sale
    is indistinguishable from a real one on every field but this one. ``currency`` is on the
    row for the same reason: these amounts are per-sale and are never summed here, and a
    total across two currencies would be a figure in an invented unit.

    **The remainder means opposite things on the two sides of ``isPlanEnded``.**
    ``songsRemaining`` on an ENDED plan is BREAKAGE — money taken for songs that will never
    be delivered; on a RUNNING plan it is an obligation this deployment still owes. Same
    subtraction, opposite facts, which is why the flag is computed here against one echoed
    instant rather than left to the browser's clock.
    """

    #: ``null`` after ``/forget``: the receipt survives the erasure and the identity does not,
    #: so "was this customer charged for songs they never got?" stays answerable. A ``null``
    #: is a lawful erasure, never a missing write and never masking — and the row is rendered
    #: rather than dropped, because a purge is a state and not an error.
    telegram_user_id: int | None
    #: ``null`` for an erased account, whose profile row is deleted outright, and for an
    #: account that simply has no handle.
    telegram_username: str | None
    first_name: str | None
    plan: PlanKind
    #: Minor units in ``currency``. Never converted, never summed across the list.
    amount_minor: int
    currency: str
    #: The rail that answered the charge, raw, as ``plan_purchases.provider`` stored it.
    provider: str
    #: ``provider == "stub"``. Derived at the read; see the class docstring.
    is_stub_rail: bool
    purchased_at: datetime
    #: The BUSINESS clock — when the twelve songs stop being claimable. No sweep reads it and
    #: no purge acts on it, which is why it is not named ``expiresAt``.
    plan_ends_at: datetime
    songs_included: int
    songs_used: int
    #: ``songsIncluded - songsUsed``, over the two integers printed beside it. Read it with
    #: ``isPlanEnded``: the same number is breakage on one side of that flag and an
    #: outstanding obligation on the other.
    songs_remaining: int
    #: ``planEndsAt <= asOf``, against the single instant the block echoes.
    is_plan_ended: bool


class RecentSubscribersView(ApiModel):
    """The last N plan sales, newest first. **No window** — this is a recency list.

    Deliberately carries no ``window`` field. Everything else on this screen is windowed and
    a reader will assume this is too; it is not, and an empty field would be a worse way to
    say so than an absent one. "Who just bought" answers the same whether the last sale was
    an hour ago or in March, and the flow version of this question already exists as the
    revenue series on ``/dashboard/series``.
    """

    #: The one instant every row's ``isPlanEnded`` was decided against, so two rows either
    #: side of a boundary cannot have been judged by two different clocks.
    as_of: datetime
    limit: int
    #: Newest purchase first. Empty means either nothing sold recently or nothing sold ever —
    #: ``isPlanRevenue`` is what tells those apart.
    items: list[RecentSubscriberView]
    #: False means no plan has EVER been sold on this deployment, so an empty list is
    #: "nothing to show" rather than "the read is broken". Measured by
    #: :func:`~bayram.db.admin.metrics.read_capabilities`, never declared.
    is_plan_revenue: bool


class AudienceListsResponse(ApiModel):
    """``GET /api/metrics/dashboard/audience-lists`` — both identified lists, one round trip.

    Two blocks rather than two flat lists with a shared window at the top, because only one
    of them is windowed. See the module docstring.
    """

    top_generators: TopGeneratorsView
    recent_subscribers: RecentSubscribersView


def to_audience_lists_response(
    *,
    window: TimeWindow | None,
    generators: tuple[TopGenerator, ...],
    generators_limit: int,
    subscribers: tuple[RecentSubscriber, ...],
    subscribers_limit: int,
    is_plan_revenue: bool,
    now: datetime,
) -> AudienceListsResponse:
    """Assemble both identified lists. Keyword-only, like every builder on this surface.

    ``now`` is threaded in rather than read here, so every ``isPlanEnded`` on the response —
    and the ``asOf`` that explains them — comes from the one instant the handler read.
    Nothing is masked on the way out and there is no parameter that would mask it: the route
    that calls this is the audited one, and the audit row it writes is the record that this
    payload was disclosed.
    """
    return AudienceListsResponse(
        top_generators=TopGeneratorsView(
            window=to_window_view(window),
            limit=generators_limit,
            items=[_to_top_generator(item) for item in generators],
        ),
        recent_subscribers=RecentSubscribersView(
            as_of=now,
            limit=subscribers_limit,
            items=[_to_recent_subscriber(item, now=now) for item in subscribers],
            is_plan_revenue=is_plan_revenue,
        ),
    )


def _to_top_generator(item: TopGenerator) -> TopGeneratorView:
    """One ranked row, field for field. No projection, no redaction, by decision."""
    return TopGeneratorView(
        telegram_user_id=item.telegram_user_id,
        telegram_username=item.telegram_username,
        first_name=item.first_name,
        delivered_songs=item.delivered_songs,
        orders_created=item.orders_created,
        ui_language=item.ui_language,
        first_seen_at=item.first_seen_at,
        last_delivered_at=item.last_delivered_at,
    )


def _to_recent_subscriber(item: RecentSubscriber, *, now: datetime) -> RecentSubscriberView:
    """One sale, with the two derivations this layer is allowed to make.

    ``songsRemaining`` is a subtraction over two integers that travel beside it, and
    ``isPlanEnded`` is a comparison against the handler's single instant — ``<=``, matching
    :func:`~bayram.db.admin.plan_purchases.plan_liability`, so a plan ending exactly now is
    ended on every surface at once rather than on some of them.
    """
    return RecentSubscriberView(
        telegram_user_id=item.telegram_user_id,
        telegram_username=item.telegram_username,
        first_name=item.first_name,
        plan=item.plan,
        amount_minor=item.amount_minor,
        currency=item.currency,
        provider=item.provider,
        is_stub_rail=item.is_stub_rail,
        purchased_at=item.purchased_at,
        plan_ends_at=item.plan_ends_at,
        songs_included=item.songs_included,
        songs_used=item.songs_used,
        songs_remaining=item.songs_included - item.songs_used,
        is_plan_ended=item.plan_ends_at <= now,
    )
