"""``users`` — one row per Telegram account that has spoken to the bot."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.contracts import Language
from hbd.db.base import Base, TimestampMixin, UtcDateTime, enum_type, utc_now

__all__ = ["UserRow"]


class UserRow(TimestampMixin, Base):
    """A Telegram user.

    Deliberately thin, and it stays that way now that free-tier counters exist: the
    entitlement balance lives in ``credit_accounts``, keyed on ``telegram_user_id``, not in
    a column here. Two commitments make that the only workable place. ``docs/
    ADMIN_PANEL_PLAN.md`` §5.11 rules out DDL on this table, and a balance column here
    would be a mutable money counter on the row the erasure design treats as
    content-erasable-but-identity-surviving; a separate account row costs nothing and keeps
    both promises. Referral graph and revenue totals remain out of scope.

    **The DDL freeze was broken once, deliberately, and the reconciliation belongs here so
    this file does not argue against its own column.** Revision 0017 adds
    :attr:`blocked_bot_at`, and revision 0021 indexes :attr:`last_seen_at`. The Churn card
    cannot be built without the first — a customer blocking the bot was recorded nowhere at
    all — and the second adds no column and changes no row's meaning. Neither weakens the
    argument above, because the load-bearing half of it was never the plan's DDL rule: it
    was the erasure asymmetry. This row must SURVIVE ``/forget`` so a block can outlive an
    erasure, which is what makes it the wrong home for a mutable money counter and the wrong
    home for a phone number and a face (:mod:`hbd.db.models.user_profile`) — and that half
    is untouched.

    **``/forget`` does NOT clear :attr:`blocked_bot_at`**, on the same footing as
    :attr:`is_blocked` and :attr:`last_seen_at`. A forgotten customer who still has the bot
    blocked is still unreachable, and clearing the column would make the churn gauge count
    them as reachable. The HISTORY of how they got there is anonymised instead, on
    ``bot_membership_events``.

    **Rows are born at first contact, not at first order**, and there are three writers.
    ``hbd.db.users_sql.ensure_user`` is called from ``repository._create_order`` when an
    order is confirmed and from ``hbd.db.user_profiles.SqlUserProfiles.record_language``
    when a customer picks a language on the very first screen; ``credits.touch`` and
    ``credits.set_blocked`` UPSERT the row from the inbound path so an operator can bar an
    account that never ordered. A fourth writer arrived with revision 0017:
    ``hbd.db.churn.mark_bot_blocked`` / ``mark_bot_unblocked``, which UPSERTs the row for the
    same reason ``set_blocked`` does — the account that has not spoken since a deploy is
    precisely the one whose block we need to record — and then writes
    :attr:`blocked_bot_at` and nothing else. Earlier text here claimed
    ``repository._ensure_user`` from ``_create_order`` was the only writer and that a person
    who walks the wizard without confirming has no row at all; onboarding made both halves
    false, and the second one is what the block gate depended on being false.

    ``ui_language`` is refreshed only by a writer that actually knows the answer — a
    language the customer chose (``record_language``) or a ``touch`` carrying a real
    ``Language`` — never by creating an order, which is evidence that the account is alive
    and no evidence at all about which language the person reads in. That distinction is
    the ``is_language_authoritative`` flag on ``ensure_user``; without it every confirmed
    brief would stamp its own output language over a settings choice.

    **The identity facts the bot now collects are NOT here.** The phone number, the
    ``@username``, the name and the profile photo live in ``user_profiles``, keyed on this
    row's ``id`` — see :mod:`hbd.db.models.user_profile` for the full argument. In one
    sentence: this table is DDL-frozen and must *survive* ``/forget`` so a block can
    outlive an erasure, while a number and a face are precisely what ``/forget`` exists to
    delete, so they cannot share a row.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, unique=True)
    #: Interface language. Chosen independently of an order's output language.
    ui_language: Mapped[Language] = mapped_column(
        enum_type(Language), nullable=False, default=Language.UZ_LATN
    )
    #: **The OPERATOR's bar.** Written by ``credits.set_blocked`` from the admin panel. Never
    #: OR-ed with :attr:`blocked_bot_at`, which is the opposite fact.
    is_blocked: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    #: Indexed for ONE aggregate — the active-accounts count, whose predicate is
    #: ``last_seen_at >= now - 30d`` with the 7d and 1d cutoffs taken as conditional counts
    #: inside it. The index is earned by that WHERE clause and by nothing else: three bare
    #: cutoffs over the whole table have no predicate and scan ``users`` however it is
    #: indexed. The write cost is real — ``credits.touch`` UPSERTs this column from the
    #: inbound path, and on Postgres an UPDATE that moves an indexed column loses
    #: HOT-update eligibility — and it is bounded by something that already exists:
    #: ``bot/gate.py``'s ``TouchDrain`` coalesces to ONE upsert per account per MINUTE. If
    #: that coalescer is ever removed or shortened, this index must be re-argued.
    last_seen_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
    #: **The CUSTOMER's block.** When this customer blocked the bot. ``NULL`` means the bot
    #: is not currently blocked by them — NOT that they never have; see
    #: ``bot_membership_events`` for the history, which is why that table exists as well as
    #: this column. Nullable with NO default because a ``FALSE``, an epoch or a ``now()``
    #: would assert something about every row that existed before revision 0017 ran, and
    #: what it would assert is "this account has not blocked us" when the truth is that
    #: nobody had ever looked — ``generation_attempts.cost_usd``'s 0.0 in timestamp form.
    #: Written ONLY by ``hbd.db.churn.mark_bot_blocked`` / ``mark_bot_unblocked``, and it
    #: must appear in NO values dict and NO ``ON CONFLICT`` set clause of ``credits.touch``,
    #: ``credits.set_blocked`` or ``users_sql.ensure_user``: a leak into ``touch``'s set
    #: clause would clear a customer's block on their next inbound message, which is the
    #: identical defect ``touch``'s own docstring records for ``is_blocked``.
    blocked_bot_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
