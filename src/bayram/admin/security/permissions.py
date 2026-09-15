"""The RBAC matrix as data, and the two guards that read it.

§12.2 of ADMIN_PANEL_PLAN is a table, so it is stored here as a table: one
:class:`Permission` per row, one :class:`Grant` per cell, and **no wildcard**. A wildcard
is how a permission added next quarter silently lands on a role nobody reviewed; an absent
cell is a denial, stated once. Because the matrix is data, the Slice 1c test can be
parameterised straight over it rather than restating it in assertions that drift.

The four roles come from ``bayram.db.enums.AdminRole``. The plan's draft called the third role
``OPERATOR``; the shipped enum calls it ``ADMIN`` and that is what this module speaks.
Ordering is documentation only — ``StrEnum`` compares as text, and nothing here derives a
permission from "greater than", because the first role that does not fit the ladder turns
every such check into a silent grant.

**Step-up is scoped to an action *and* a subject.** A session-wide "recently
re-authenticated" flag is the design this replaces: it lets a step-up collected to reveal
one order's note authorise blocking an unrelated user, which is precisely the confused
deputy the control exists to stop. So a grant is the exact string ``<action>:<subject-id>``
and it is compared whole. Single-use consumption is the session store's job, not this
module's.

**Freshness is enforced on top of that, and the window is not a constant here.** The
ordinary grace is ``AdminSettings.admin_step_up_grace_seconds``, threaded in by the caller
as ``grace_s``; there is deliberately no module-level default, because a default is what a
future caller silently inherits when an operator has lowered the setting. The two actions
§12.1 T2 marks "grace 0" — purge and config commit/rollback — take
:data:`STEP_UP_FRESH_MAX_AGE_S`, which is **zero**, and the choice is derived from the
matrix rather than restated, so raising the setting cannot loosen them and a future ``FRESH``
cell cannot quietly inherit the grace. Zero is a window rather than a wall: a grant carrying
the deciding request's own instant still passes, which is the shape those two actions must
take — re-authenticate and act under one ``now``, never across a round trip.

Nothing here raises for an authorisation failure: the guards return a
:class:`AccessDecision` and the HTTP layer maps it to the error envelope. A pure decision
is testable without a request, and it keeps the one place that decides "may they?" free of
any opinion about status codes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from bayram.db.enums import AdminRole
from bayram.logging import get_logger

__all__ = [
    "Permission",
    "StepUpAction",
    "StepUpRequirement",
    "Grant",
    "RBAC_MATRIX",
    "ROLE_PERMISSIONS",
    "STEP_UP_ACTIONS",
    "STEP_UP_FRESH_MAX_AGE_S",
    "MAX_STEP_UP_SCOPE_CHARS",
    "AccessDecision",
    "StepUpGrant",
    "PermissionGuard",
    "StepUpGuard",
    "build_step_up_scope",
    "grant_for",
    "is_permitted",
    "check_access",
    "check_role",
    "check_step_up",
    "max_age_for_action",
    "require",
    "require_step_up",
    "step_up_from_session",
]

_LOGGER: Final = get_logger(__name__)

#: The window for a "grace 0" action (§12.1 T2) — purge and config commit/rollback. Zero
#: seconds, not "a small number of seconds": only a grant carrying the deciding request's own
#: instant authorises one, so the action has to re-authenticate and act under a single
#: ``now`` rather than across a round trip. Anything larger is a grace, and the whole point
#: of these two cells is that they have none.
#:
#: There is no companion constant for the ordinary window. That one is
#: ``AdminSettings.admin_step_up_grace_seconds`` and it arrives as ``grace_s``.
STEP_UP_FRESH_MAX_AGE_S: Final[int] = 0
#: ``admin_sessions.step_up_scope`` is ``String(128)``.
MAX_STEP_UP_SCOPE_CHARS: Final[int] = 128

_SCOPE_SEPARATOR: Final[str] = ":"
#: Scopes are built from closed vocabularies and identifiers, never from free text, so the
#: shape is asserted before the value reaches the database or a log line.
_SCOPE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:-]{3,128}$")


class Permission(StrEnum):
    """One row of §12.2. The value is what a route declares and an audit row records."""

    SESSION_SELF = "session.self"
    DASHBOARD_READ = "dashboard.read"
    RECORDS_READ = "records.read"
    CHAT_INDEX_READ = "chat.index.read"
    WIZARD_STATE_READ = "wizard_state.read"
    MODERATION_QUEUE_READ = "moderation.queue.read"
    CONFIG_READ = "config.read"
    RETENTION_READ = "retention.read"
    REVEAL_PERSONAL_DATA_READ = "reveal.personal_data.read"
    REVEAL_PERSONAL_DATA = "reveal.personal_data"
    REVEAL_MEDIA_READ = "reveal.media.read"
    REVEAL_MEDIA = "reveal.media"
    ORDER_RETRY = "order.retry"
    ORDER_FORCE_DELIVER = "order.force_deliver"
    USER_BLOCK = "user.block"
    #: The role half of ``USER_BLOCK``'s ``W+S`` cell — see the matrix note beside it.
    USER_BLOCK_WRITE = "user.block.write"
    CREDIT_GRANT = "credit.grant"
    #: The role half of ``CREDIT_GRANT``'s ``W+S`` cell, for the same reason.
    CREDIT_GRANT_WRITE = "credit.grant.write"
    BROADCAST_READ = "broadcast.read"
    #: The role half of ``BROADCAST_SEND``'s ``W+S`` cell — see the matrix note beside it.
    BROADCAST_WRITE = "broadcast.write"
    BROADCAST_SEND = "broadcast.send"
    MODERATION_REVEAL = "moderation.reveal"
    MODERATION_DECIDE = "moderation.decide"
    RETENTION_SWEEP = "retention.sweep"
    AUDIT_READ = "audit.read"
    REVEAL_VOLUME_READ = "reveal.volume.read"
    EXPORT_AGGREGATE = "export.aggregate"
    USER_PURGE = "user.purge"
    CONFIG_WRITE = "config.write"
    ORDER_EVIDENCE_EXPORT = "order.evidence_export"
    AUDIT_EXPORT = "audit.export"
    ADMIN_READ = "admin.read"
    ADMIN_MANAGE = "admin.manage"
    #: The role half of ``ADMIN_MANAGE``'s ``W+S`` cell — see the matrix note beside it.
    ADMIN_MANAGE_WRITE = "admin.manage.write"
    #: The checkout pause switch. A plain ``W`` on purpose and **never** a member of
    #: :data:`STEP_UP_ACTIONS` — see the matrix note beside it.
    RAIL_CONTROL = "rail.control"
    #: Re-enqueue one settled payment's confirmation. Its own row rather than a reuse of
    #: :attr:`RAIL_CONTROL`, so SUPPORT gets the remedy without the switch.
    PAYMENT_NOTIFY = "payment.notify"
    #: The support queue, read. **M** at every role — see the matrix note beside it.
    SUPPORT_READ = "support.read"
    #: Working a ticket: moving it, claiming it, noting it, answering it. A plain ``W`` with
    #: **no step-up**, which makes it safe as a router guard. See the matrix note.
    SUPPORT_WRITE = "support.write"
    #: Repointing where every future ticket card lands. ADMIN and OWNER, **not** SUPPORT, and
    #: a plain ``W`` with no step-up — see the matrix note, which argues both halves.
    SUPPORT_GROUP_WRITE = "support.group.write"


class StepUpAction(StrEnum):
    """The left half of a step-up scope.

    Coarser than :class:`Permission` in exactly one place: every reveal — a name, a note, a
    chat body, a moderation detail, an audio stream — is the single ``reveal`` action, so
    the one audited reveal path in §12.3 has one scope shape. Everything else maps 1:1,
    because a step-up for "block this user" must not authorise "purge this user".
    """

    REVEAL = "reveal"
    ORDER_FORCE_DELIVER = "order.force_deliver"
    USER_BLOCK = "user.block"
    #: Its own action rather than a reuse of ``USER_BLOCK``: a step-up collected to bar an
    #: abuser must not also authorise minting them spendable credit, which is exactly the
    #: confused deputy the scope exists to close.
    CREDIT_GRANT = "credit.grant"
    #: Its own action for the reason ``CREDIT_GRANT`` is: a step-up collected to comp one
    #: customer must not also authorise a message to every customer. It is the only action
    #: here whose subject is not a person — the scope is a campaign id — and that is what
    #: makes reusing another one wrong twice over.
    BROADCAST_SEND = "broadcast.send"
    MODERATION_DECIDE = "moderation.decide"
    USER_PURGE = "user.purge"
    CONFIG_WRITE = "config.write"
    ORDER_EVIDENCE_EXPORT = "order.evidence_export"
    AUDIT_EXPORT = "audit.export"
    ADMIN_MANAGE = "admin.manage"


class StepUpRequirement(StrEnum):
    """How recently the operator must have re-authenticated for this cell."""

    NONE = "none"
    REQUIRED = "required"
    FRESH = "fresh"


class AccessDecision(StrEnum):
    """The guards' answer. Anything but ``ALLOWED`` is a refusal with a distinct reason.

    The reasons are distinct because the panel reacts differently to each: a missing
    step-up opens the re-authentication prompt, a scope mismatch means the operator
    switched subjects mid-flow, and a role failure must not offer a prompt at all.
    """

    ALLOWED = "allowed"
    FORBIDDEN_ROLE = "forbidden_role"
    STEP_UP_REQUIRED = "step_up_required"
    STEP_UP_SCOPE_MISMATCH = "step_up_scope_mismatch"
    STEP_UP_EXPIRED = "step_up_expired"


@dataclass(frozen=True, slots=True)
class Grant:
    """One cell of the matrix. Absence of a cell is denial; this is never "empty".

    ``is_unmasked`` is what the serializer reads: **M** and **R** are both reads, and the
    difference between them is whether personal data comes back in the clear, which is a
    response-boundary decision rather than a routing one (§12.3).
    """

    is_readable: bool = False
    is_unmasked: bool = False
    is_writable: bool = False
    is_reveal: bool = False
    step_up: StepUpRequirement = StepUpRequirement.NONE


#: The cell vocabulary of §12.2, named as the table names them.
_M: Final[Grant] = Grant(is_readable=True)
_R: Final[Grant] = Grant(is_readable=True, is_unmasked=True)
_W: Final[Grant] = Grant(is_writable=True)
_WS: Final[Grant] = Grant(is_writable=True, step_up=StepUpRequirement.REQUIRED)
_WSF: Final[Grant] = Grant(is_writable=True, step_up=StepUpRequirement.FRESH)
_AS: Final[Grant] = Grant(
    is_readable=True,
    is_unmasked=True,
    is_reveal=True,
    step_up=StepUpRequirement.REQUIRED,
)


def _row(
    *,
    viewer: Grant | None = None,
    support: Grant | None = None,
    admin: Grant | None = None,
    owner: Grant | None = None,
) -> Mapping[AdminRole, Grant]:
    """One matrix row. A role left ``None`` has no cell, which is a denial."""
    cells = {
        AdminRole.VIEWER: viewer,
        AdminRole.SUPPORT: support,
        AdminRole.ADMIN: admin,
        AdminRole.OWNER: owner,
    }
    return MappingProxyType({role: cell for role, cell in cells.items() if cell is not None})


#: §12.2, verbatim but for one ruled-on split. VIEWER · SUPPORT · ADMIN (the plan's
#: OPERATOR) · OWNER. The exception is the pair of ``ADMIN_*`` rows at the bottom, which
#: follow §6.8 line 949 rather than §12.2's collapsed row; the reason is written out there.
RBAC_MATRIX: Final[Mapping[Permission, Mapping[AdminRole, Grant]]] = MappingProxyType(
    {
        Permission.SESSION_SELF: _row(viewer=_W, support=_W, admin=_W, owner=_W),
        Permission.DASHBOARD_READ: _row(viewer=_M, support=_M, admin=_M, owner=_R),
        Permission.RECORDS_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.CHAT_INDEX_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.WIZARD_STATE_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.MODERATION_QUEUE_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.CONFIG_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.RETENTION_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        # ── The THIRD place this table splits a §12.2 row, for the same reason as the two ──
        # ── below it. Read the ADMIN_READ / ADMIN_MANAGE note at the bottom first. ────────
        #
        # §12.2 rows 4, 6, 7 and 9 all reduce to one endpoint — "Every ``A`` cell routes
        # through the same ``POST /reveal`` endpoint" (§12.2 line 1886) — and §6.8 line 928
        # gives that endpoint as ``S +S, audited, budgeted``. One ``A+S`` cell on the router
        # makes it unreachable by everybody, for :func:`check_role`'s reason: the router
        # guard holds no subject and therefore no grant, so it answers STEP_UP_REQUIRED to a
        # SUPPORT operator holding a live, correctly-scoped ``reveal:<order>`` grant, for
        # ever. And unlike the roster there is no §6.8 sibling row to fall back on, because
        # /reveal has exactly one.
        #
        # Guarding the router with RECORDS_READ instead — the shape ``test_budget.py``'s
        # probe route uses — is not available either: RECORDS_READ is ``M`` for all four
        # roles, and §12.2 gives VIEWER no reveal cell at all.
        #
        # So the row is split: REVEAL_PERSONAL_DATA_READ is the ROLE half — who may reach
        # ``POST /reveal`` at all, SUPPORT and above and pointedly not VIEWER — carrying no
        # step-up, so the router guard decides it and lets the request through.
        # REVEAL_PERSONAL_DATA keeps the ``A+S`` cell and is what the HANDLER enforces on
        # the subject in the body, through
        # ``deps.enforce_step_up(StepUpAction.REVEAL, subject_id=…)``. Both halves run on
        # every request; neither is decorative and neither is sufficient alone.
        #
        # ``_M`` and not ``_R``: passing this guard unmasks nothing by itself. The plaintext
        # only crosses after the step-up, the budget charge and the audit row, and that is
        # the ``_AS`` cell on the next line.
        Permission.REVEAL_PERSONAL_DATA_READ: _row(support=_M, admin=_M, owner=_M),
        Permission.REVEAL_PERSONAL_DATA: _row(support=_AS, admin=_AS, owner=_AS),
        # ── The second place this table splits a §12.2 row, for the SAME reason as the ──
        # ── ADMIN_READ / ADMIN_MANAGE pair below. See the long note there first. ────────
        #
        # §12.2 row 10 is ``Stream audio or read lyric text | — | A+S | A+S | A+S``, and
        # §6.8 lines 924-925 give both endpoints as ``S +S, audited``. Read literally as one
        # cell it makes GET /api/assets/{id}/stream unreachable by everybody: the router
        # guard is :func:`check_role`, which holds no subject and therefore no grant, so it
        # answers STEP_UP_REQUIRED to an ``A+S`` cell for ever — an operator who has just
        # completed a correctly-scoped ``reveal:<asset>`` step-up still gets 403, and it
        # looks right, because STEP_UP_REQUIRED is exactly what the matrix predicts.
        #
        # So the row is split the way §12.2 itself split the roster: REVEAL_MEDIA_READ is
        # the ROLE half — who may reach the media routes at all, which is SUPPORT and above
        # and pointedly not VIEWER — and it carries no step-up, so the router guard decides
        # it and lets the request through. REVEAL_MEDIA keeps the ``A+S`` cell and is what
        # the HANDLER enforces on the subject it has read, through
        # ``deps.enforce_step_up(StepUpAction.REVEAL, subject_id=str(asset_id))``. Both
        # halves therefore run on every request: neither is decorative and neither is
        # sufficient alone.
        #
        # ``_M`` and not ``_R``: passing this guard unmasks nothing by itself. The bytes
        # only move after the step-up, and that is the ``_AS`` cell below.
        Permission.REVEAL_MEDIA_READ: _row(support=_M, admin=_M, owner=_M),
        Permission.REVEAL_MEDIA: _row(support=_AS, admin=_AS, owner=_AS),
        Permission.ORDER_RETRY: _row(admin=_W, owner=_W),
        Permission.ORDER_FORCE_DELIVER: _row(admin=_WS, owner=_WS),
        Permission.USER_BLOCK: _row(admin=_WS, owner=_WS),
        # ── The FOURTH place this table splits a §12.2 row, and the first where the row ──
        # ── is a WRITE. Read the REVEAL_MEDIA note above first; the mechanism is the ────
        # ── same one and the failure it avoids is identical. ───────────────────────────
        #
        # §12.2 row 13 is ``Block / unblock a user | — | — | W+S | W+S`` and §6.8 lines
        # 904-905 give both endpoints as ``O +S``. Declared as one cell on the router it
        # makes ``POST /users/{id}/block`` unreachable by everybody: the router guard is
        # :func:`check_role`, which holds no subject and therefore no grant, so it answers
        # ``STEP_UP_REQUIRED`` to a ``W+S`` cell for ever — an ADMIN who has just completed
        # a correctly-scoped ``user.block:<telegram id>`` step-up still gets 403, and it
        # looks right, because ``STEP_UP_REQUIRED`` is what the matrix predicts.
        #
        # So USER_BLOCK_WRITE is the ROLE half — exactly USER_BLOCK's two roles with the
        # step-up removed — and it is what the two routes declare at the router.
        # USER_BLOCK keeps the ``W+S`` cell and is what the HANDLER enforces on the Telegram
        # id it has read, through ``deps.enforce_step_up(StepUpAction.USER_BLOCK, …)``.
        # Both run on every request; neither is decorative and neither is sufficient alone.
        #
        # A general ``records.write`` was the alternative to a new row, and its cells would
        # be identical today (ADMIN, OWNER, ``W``). It was rejected, and NOT added: §12.2
        # has no such row, so a permission invented to be the foil for this argument would
        # be a cell in the matrix that no route declares and no plan section can source.
        # The argument stands without it — identical today is not the same decision: "may
        # edit a record" and "may bar an account from the product" are two questions, and
        # one permission answering both means the day somebody widens the first they have
        # quietly widened blocking too.
        Permission.USER_BLOCK_WRITE: _row(admin=_W, owner=_W),
        # ── §12.2 has NO row for issuing credits, so this pair is a ruling rather than a ──
        # ── transcription. ``AuditAction.CREDIT_GRANT`` has existed since the entitlement ──
        # ── ledger shipped (``db/enums.py:212``) with nothing able to write it. ──────────
        #
        # Leaving it uncelled was not an option: a permission the matrix has no row for
        # denies every role (:func:`grant_for` answers ``None``), so the route would be dead
        # at OWNER and the audit member would stay unreachable.
        #
        # **ADMIN and OWNER, not OWNER alone.** A comp is the routine end of a support
        # ticket — "the render failed twice, give them another go" — and an action only the
        # owner can take is one the owner is woken up to take, which is how a shared login
        # gets made.
        #
        # **What actually bounds a bad ADMIN here, stated exactly.** It is DETECTION, not a
        # ceiling: every grant lands on the append-only ledger with
        # ``actor="admin:<username>"`` and §12.4's audit row names the operator, the reason
        # code and the subject, so "who comped how much this month" is a ``SUM`` over an
        # indexed filter. ``schemas.credits.MAX_GRANT_CREDITS`` caps ONE CALL and nothing
        # else: the grace below is not zero, so one re-authentication authorises every grant
        # to that account until it expires, and there is no per-actor, per-account or
        # per-day cumulative ceiling anywhere on this path — unlike ``POST /reveal``, whose
        # ``charge_reveal_budget`` does hold a rolling total. Sequential calls inside one
        # window therefore mint an unbounded number of credits, visibly. That asymmetry is a
        # deliberate reading of the two actions — a reveal discloses a customer's data and
        # cannot be taken back, while a grant is fully described by rows nobody can delete
        # and is answered by reading them — and it is written here rather than left implied,
        # because a note claiming a bound the code does not enforce is worse than no note.
        # A cumulative ceiling in the reveal budget's shape is the change to make if this
        # deployment decides detection is not enough.
        #
        # **``W+S`` and not a bare ``W``.** This is the only action in the panel that ISSUES
        # VALUE — a credit is one render, which is real vendor spend. T2 (session theft) and
        # T8 (CSRF) both end at "a live cookie can do whatever the cookie can do without
        # re-authenticating", and §12.1 T2 answers that with step-up for "every reveal,
        # purge, force-deliver, block and config commit". Minting spendable credit belongs
        # in that company more than a block does: a block is undone by pressing the other
        # button, and a spent credit is not undone at all.
        #
        # **NOT ``FRESH``.** §12.1 T2's grace-0 pair is purge and config commit, and both
        # are there because they are irreversible across a customer's whole record or across
        # the fleet. A grant is one bounded number on one account, fully described by a row
        # nobody can delete, so holding it to a zero-second window would make the ordinary
        # comp a two-request dance against a threat the audit row already covers.
        Permission.CREDIT_GRANT: _row(admin=_WS, owner=_WS),
        # The role half, for the reason USER_BLOCK_WRITE above states at length.
        Permission.CREDIT_GRANT_WRITE: _row(admin=_W, owner=_W),
        # ── §12.2 has NO row for messaging customers either, so these three are a ruling ──
        # ── in the shape the CREDIT_GRANT pair above is. BROADCAST_SPEC §3.1 is the ──────
        # ── source; read the USER_BLOCK_WRITE note first for the split mechanism. ───────
        #
        # **Why the read is ``M`` at every role, including VIEWER.** A campaign record is a
        # title, a segment document, a state and four counters — operator-facing text and
        # arithmetic, no customer in it. A VIEWER who can see that 40 000 people were
        # messaged on Tuesday but not who sent it is the reader this panel exists for, and
        # the alternative — hiding the campaign list from the role whose whole job is
        # looking — makes "what went out?" a question only the people who sent it can
        # answer. ``_M`` and not ``_R``: the recipient list is masked at the response
        # boundary for everyone (§6.1), so there is nothing here for an ``R`` cell to
        # unmask.
        #
        # **ADMIN and OWNER for the write, not OWNER alone.** Composing and revising a
        # draft is ordinary operational work — a service notice about an outage is written
        # by whoever is awake — and an action only the owner can take is an action the owner
        # gets woken up for, which is how a shared login gets made.
        #
        # **``W+S`` on the send, and it is the pair's whole point.** This is the only action
        # in the panel that reaches EVERY customer at once, and it is the least reversible
        # thing the panel can do: a block is undone by pressing the other button, a credit
        # is described by a row nobody can delete, and a message that has left Telegram
        # cannot be recalled, corrected or unread. §12.1 T2 answers "a live cookie can do
        # whatever the cookie can do" with a step-up for every irreversible write, and this
        # one belongs in that company more than a block does.
        #
        # **NOT ``FRESH``.** The grace-0 pair is purge and config commit, both irreversible
        # across a customer's whole record or across the fleet. A schedule is bounded by the
        # audience the operator has just seen counted, it is auditable before it happens
        # (the INTENT row) and after (the OUTCOME row), and it is pausable mid-flight — so
        # holding it to a zero-second window would make the ordinary service notice a
        # two-request dance against a threat those two rows already cover.
        #
        # The split is the USER_BLOCK_WRITE one exactly: ``check_role`` holds no subject and
        # therefore no grant, so a lone ``W+S`` cell on the router answers STEP_UP_REQUIRED
        # to an ADMIN holding a live ``broadcast.send:<campaign>`` grant for ever.
        # BROADCAST_WRITE is the ROLE half the write routes declare; BROADCAST_SEND keeps
        # the ``W+S`` cell and is what ``POST /broadcasts/{id}/schedule`` and
        # ``/test-send`` enforce in the handler, on the campaign id they have read. Pause,
        # resume and cancel take the role half alone and no step-up: each one only STOPS
        # messages going out, and a control that makes stopping harder than starting is
        # the wrong way round.
        Permission.BROADCAST_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.BROADCAST_WRITE: _row(admin=_W, owner=_W),
        Permission.BROADCAST_SEND: _row(admin=_WS, owner=_WS),
        Permission.MODERATION_REVEAL: _row(admin=_AS, owner=_AS),
        Permission.MODERATION_DECIDE: _row(admin=_WS, owner=_WS),
        Permission.RETENTION_SWEEP: _row(admin=_W, owner=_W),
        Permission.AUDIT_READ: _row(admin=_M, owner=_R),
        Permission.REVEAL_VOLUME_READ: _row(admin=_R, owner=_R),
        Permission.EXPORT_AGGREGATE: _row(admin=_W, owner=_W),
        Permission.USER_PURGE: _row(owner=_WSF),
        Permission.CONFIG_WRITE: _row(owner=_WSF),
        Permission.ORDER_EVIDENCE_EXPORT: _row(owner=_WS),
        Permission.AUDIT_EXPORT: _row(owner=_WS),
        # ── The one place this table deliberately does NOT follow §12.2. ──────────────
        # §6.8 line 949 is the endpoint-level table and it is the authority here:
        #     | GET | /admins | List | W |
        # — owner, write-class, and pointedly with NO ``+S``, while the four writes beneath
        # it (POST /admins, PATCH /admins/{id}, POST /admins/{id}/reset-password,
        # DELETE /admins/{id}/sessions) each carry ``W +S`` explicitly. §12.2 collapsed all
        # five into one row — ``| Admin account CRUD, revoke others' sessions | — | — | — |
        # W+S |`` — and that collapsed row was NOT followed, by a ruling on the
        # contradiction, because the endpoint table is the more specific statement. §12.2 now
        # carries the same split (lines 1883-1884), so the two sections agree again.
        #
        # The split is not cosmetic. :func:`check_role` is the router-level guard and it
        # takes only (permission, role): it holds no grant and reads no session, so a single
        # ``_WS`` cell answers ``STEP_UP_REQUIRED`` to an OWNER unconditionally and forever —
        # a granted, unexpired, correctly-scoped ``admin.manage`` step-up still yields 403.
        # Reading §12.2's collapsed row literally therefore made the roster unreachable by
        # every role, which is not what either section asks for.
        #
        # So: ADMIN_READ is the roster read (owner, ``W``, no step-up) and ADMIN_MANAGE stays
        # the ``W+S`` cell guarding the four account writes when they arrive in Phase 2.
        # Do not merge them back.
        Permission.ADMIN_READ: _row(owner=_W),
        Permission.ADMIN_MANAGE: _row(owner=_WS),
        # The ROLE half of the ``W+S`` cell above, and the FIFTH place this table splits a
        # row. The mechanism is USER_BLOCK_WRITE's exactly: :func:`check_role` is what a
        # router-level guard calls, it holds no subject and therefore no grant, so a router
        # declaring ADMIN_MANAGE itself answers ``STEP_UP_REQUIRED`` to an OWNER holding a
        # live, correctly-scoped ``admin.manage:<username>`` grant — for ever, and it looks
        # right, because ``STEP_UP_REQUIRED`` is what the matrix predicts.
        #
        # So ``POST /admins`` declares ADMIN_MANAGE_WRITE at the router and enforces
        # ADMIN_MANAGE's step-up in the handler, on the username it has read. Both run on
        # every request; neither is decorative and neither is sufficient alone.
        #
        # **Not a reuse of ADMIN_READ, whose cells are identical today.** That is the
        # USER_BLOCK_WRITE argument again and it holds here more sharply: "may see who has
        # access" and "may give somebody access" are two questions, and one permission
        # answering both means the day anybody widens the roster read — to ADMIN, say, so a
        # deputy can see who is on call — they have quietly handed that role the power to
        # mint an account for themselves.
        Permission.ADMIN_MANAGE_WRITE: _row(owner=_W),
        # ── Two more rulings §12.2 has no rows for, in the shape of the CREDIT_GRANT and ──
        # ── BROADCAST pairs above: the Payme rail shipped after the plan's table was ─────
        # ── written. ``BILLING_RAIL_BOARD §3`` is the source. ───────────────────────────
        #
        # **RAIL_CONTROL is a plain ``W`` and must NEVER be added to STEP_UP_ACTIONS.** That
        # is the reverse of the ruling every other operator action here took, so the four
        # reasons are written down rather than left to be re-litigated:
        #
        # (a) The owning module has already disclaimed the switch as a control.
        #     ``bayram.payme.pause``'s docstring says it verbatim — "this switch is not a
        #     security control and must never be documented, tested or relied upon as one.
        #     It is an operator convenience with a known open failure mode" — because
        #     ``is_paused`` answers ``False`` when Redis cannot be reached. Putting the
        #     panel's heaviest gate on a switch whose own reader fails open would be an
        #     inconsistency that module contradicts on sight.
        # (b) The blast radius is not in the step-up class. A hijacked session that presses
        #     pause stops the bot QUOTING new checkouts: no money moves, no personal data is
        #     disclosed, no credit is minted, no message is sent, and the next operator
        #     undoes it in one click. What actually carries a step-up here is REVEAL
        #     (discloses a person), USER_BLOCK (denies service to a person), CREDIT_GRANT
        #     (mints money) and BROADCAST_SEND (messages every customer). Pause belongs with
        #     ORDER_RETRY, which carries none — and with the broadcast PAUSE route, whose
        #     note above already rules that "a control that makes stopping harder than
        #     starting is the wrong way round".
        # (c) The moment it is needed is the moment it cannot be afforded. Pause is an
        #     incident brake, and ``pause.py`` made exactly this availability-over-strictness
        #     trade on its own read path. A password box between an operator and the brake is
        #     ninety more seconds of whatever they are braking.
        # (d) It is one hazard away from shipping a dead route. :func:`check_role` is what a
        #     router-level guard calls, it holds no subject and therefore no grant, so any
        #     permission appearing in :data:`STEP_UP_ACTIONS` answers ``STEP_UP_REQUIRED``
        #     unconditionally — for ever, at OWNER, while LOOKING correct because that is
        #     what the matrix predicts. If a future reviewer decides pause deserves a
        #     step-up after all, the remedy is the split every ``W+S`` row above takes —
        #     ``RAIL_CONTROL_WRITE`` at the router plus ``RAIL_CONTROL`` enforced in the
        #     handler through ``deps.enforce_step_up`` — and NEVER adding this member to the
        #     mapping. ``tests/test_admin/test_rbac_matrix.py`` asserts its absence there.
        #
        # What pause gets instead: a mandatory ``reasonCode`` (``ReasonedRequest``), ADMIN
        # and OWNER only, an ``admin_audit_log`` row per press, and a response that RE-READS
        # the Redis key rather than echoing the request.
        Permission.RAIL_CONTROL: _row(admin=_W, owner=_W),
        # **SUPPORT holds this one and holds nothing else on the rail**, which is the whole
        # reason it is a second row rather than a use of RAIL_CONTROL. Re-enqueuing a
        # settled payment's confirmation sends a message the customer was already owed: it
        # writes no money row, mints no credit and creates no state a customer can spend,
        # and its idempotency is structural rather than promised (``payme_notify_job_id`` is
        # deterministic so ARQ collapses a double press, and ``mark_intent_notified`` stamps
        # only ``WHERE notified_at IS NULL``). SUPPORT is who takes the "I paid and nothing
        # happened" call, so refusing them the single most common answer to it would make
        # the panel useless at the one desk that needs it — while riding on RAIL_CONTROL
        # would hand a support agent the switch that stops the business selling.
        #
        # No ``+S`` for reason (b) above, more sharply: the action's entire effect is a
        # message this system already decided to send and failed to.
        Permission.PAYMENT_NOTIFY: _row(support=_W, admin=_W, owner=_W),
        # ── A third ruling §12.2 has no rows for, in the shape of the CREDIT_GRANT, ──────
        # ── BROADCAST and RAIL pairs above. ``SUPPORT_TICKETS_SPEC §7`` is the source, and ─
        # ── the one thing to carry away from this note is the LAST paragraph: neither of ──
        # ── these two rows carries a step-up, and that is what makes both of them usable ──
        # ── as router-level guards. ──────────────────────────────────────────────────────
        #
        # **The read is ``M`` at every role, VIEWER included**, and it is the same sentence
        # ``BROADCAST_READ`` is given: the queue is what the panel exists to show. A VIEWER
        # who can see that eleven people are waiting on an answer but not read the queue is
        # the reader this panel was built for, told to ask somebody else. ``_M`` and not
        # ``_R``: the customer's Telegram id is published exactly as ``GET /api/users``
        # publishes it and their name is not on a ticket at all, so there is nothing here for
        # an ``R`` cell to unmask — the one plaintext this surface carries is the complaint
        # itself, which is argued at the view
        # (:class:`~bayram.db.admin.views.SupportTicketListItem`) rather than at the cell.
        #
        # **SUPPORT holds the write, and this is the only write row in the table that starts
        # at SUPPORT rather than at ADMIN.** That is the whole point of the role: a support
        # operator's entire job is answering customers, and a matrix in which the role named
        # SUPPORT may read the support queue and not reply to it describes a person who can
        # watch the work and not do it. The comparison that settles it is ``PAYMENT_NOTIFY``
        # directly above — SUPPORT already holds the answer to "I paid and nothing happened",
        # and it would be incoherent to hand them the remedy and withhold the conversation.
        #
        # **Replying is counted HERE rather than split into its own ``support.reply`` row.**
        # A reply does send a message to a customer, which is the property that earned
        # ``BROADCAST_SEND`` its ``W+S``, so the asymmetry is stated rather than assumed: a
        # broadcast reaches EVERY customer at once, cannot be recalled and is composed by
        # somebody who will not be the one who finds out it was wrong, while a ticket reply
        # goes to ONE person who asked us a question and is answered in the same minute they
        # asked it. A step-up on it would re-authenticate an operator forty times a shift,
        # which does not make the fortieth reply safer — it makes the password box furniture.
        # The accountability is carried instead by two records that a broadcast does not have:
        # the ``admin_audit_log`` row (``ticket.reply``, with the ticket as its subject) and
        # ``support_ticket_events``, which is append-only and names the author of every line.
        # ``BROADCAST_WRITE``'s own note makes this trade in the other direction, and both are
        # deliberate.
        #
        # **ADMIN and OWNER are on the write too, and not because of a ladder.** Nothing in
        # this module derives a permission from "greater than" (see the module docstring), so
        # their cells are here because they were decided: an ADMIN triaging out of hours and
        # an OWNER answering the one complaint that reached them personally are both ordinary,
        # and a queue only SUPPORT can touch is a queue that stops at the weekend.
        #
        # **Neither row carries a step-up, so neither needs the ROLE-half split that
        # USER_BLOCK_WRITE, CREDIT_GRANT_WRITE, BROADCAST_WRITE and ADMIN_MANAGE_WRITE were
        # each forced into.** :func:`check_role` holds no subject and therefore no grant, so
        # ANY cell carrying ``StepUpRequirement.REQUIRED`` answers ``STEP_UP_REQUIRED`` for
        # ever when it is declared at a router — to a correctly re-authenticated OWNER
        # included — while looking exactly right, because ``STEP_UP_REQUIRED`` is what the
        # matrix predicts. That hazard has been hit five times in this file and is written out
        # at each of them. These two are plain ``_M``/``_W``, so ``routers/support.py``
        # declares them directly and there is nothing to enforce in a handler. If a future
        # reviewer decides a ticket reply deserves a step-up after all, the remedy is the
        # split the four rows above take — ``SUPPORT_REPLY`` enforced through
        # ``deps.enforce_step_up`` on the ticket id, with ``SUPPORT_WRITE`` left on the router
        # — and NEVER adding a step-up to this row.
        Permission.SUPPORT_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.SUPPORT_WRITE: _row(support=_W, admin=_W, owner=_W),
        # ── A FOURTH ruling §12.2 has no row for, and the second one in this namespace. ──
        # ── ``SUPPORT_TICKETS_SPEC §5.1``'s 2026-09-15 amendment and §3.8 are the source. ─
        #
        # **What this permission is for.** The Telegram group that receives ticket cards used
        # to be ``BAYRAM_SUPPORT_GROUP_CHAT_ID``, an integer in a unit file: changing it meant
        # editing a deployment and restarting a process, so the capability belonged to whoever
        # could deploy and was bounded by that. §3.8 moved it into a ``bot_chats`` row an
        # operator repoints from a screen, and a capability that has stopped being bounded by
        # SSH access has to be bounded by a cell in this table instead. This is that cell.
        #
        # **It is deliberately NOT ``SUPPORT_WRITE``, and the split is the whole point of
        # adding a row rather than reusing the one directly above.** A support operator works
        # the queue: they read a complaint, claim it, answer it and resolve it, dozens of times
        # a shift, and every one of those acts is about ONE customer who is already waiting.
        # Choosing where every FUTURE ticket card is posted is a different act with a different
        # blast radius: the wrong room means a customer's complaint — their words, their
        # Telegram id, the ⚠️ they pressed — is published to people who should not see it, and
        # nothing about that is visible from the board an operator is looking at. SUPPORT is
        # ``—`` here for that reason and loses nothing it is named for; ``SUPPORT_READ`` still
        # answers "where do my tickets go?" for every role, which is the question an operator
        # must be able to ask without being able to change the answer.
        #
        # **ADMIN and OWNER, not OWNER alone**, on ``BROADCAST_WRITE``'s and
        # ``CREDIT_GRANT``'s reasoning taken a third time: re-pointing the inbox after a group
        # is migrated, renamed or accidentally deleted is ordinary operational work done by
        # whoever is awake, and an action only the owner can take is an action the owner gets
        # woken up for — which is how a shared login gets made.
        #
        # **A plain ``W`` with NO step-up, transcribing ``BROADCAST_WRITE``'s written
        # argument.** The accountability is carried by the ``admin_audit_log`` row — the actor,
        # their role, their IP, the chat that was selected AND the chat it was taken away from
        # (``SelectionChange.previous_chat_id`` exists so that second fact can be recorded) —
        # beside a ``bot_chats`` row that keeps ``selected_by_username`` and ``selected_at``
        # standing even after the selection moves on. That is the same trade ``BROADCAST_WRITE``
        # makes for composing a campaign: the append-only record is the control, and the
        # re-authentication box is not.
        #
        # **And because it carries no step-up it is safe as a router-level guard, which is the
        # property that actually matters here.** :func:`check_role` is what a router guard
        # calls; it holds no subject and therefore no grant, so ANY cell carrying
        # ``StepUpRequirement.REQUIRED`` answers ``STEP_UP_REQUIRED`` for ever when declared at
        # a router — to a correctly re-authenticated OWNER included — while looking exactly
        # right, because ``STEP_UP_REQUIRED`` is what the matrix predicts. This file has been
        # bitten by that five times (REVEAL_PERSONAL_DATA, REVEAL_MEDIA, USER_BLOCK,
        # CREDIT_GRANT/BROADCAST_SEND, ADMIN_MANAGE) and each has its note above. This row
        # carries none, so ``routers/support_groups.py`` declares it directly and no handler
        # there enforces authorisation. If a future reviewer decides repointing the inbox
        # deserves a step-up, the remedy is the split those five took — a
        # ``SUPPORT_GROUP_SELECT`` step-up enforced in the handler on the chat id it has read,
        # with this row left on the router — and NEVER adding a step-up here.
        Permission.SUPPORT_GROUP_WRITE: _row(admin=_W, owner=_W),
    }
)

#: The §12.1 T9 shape, DERIVED from the matrix rather than restated beside it — two hand-
#: maintained copies of an authorisation table disagree eventually, and the disagreement is
#: always a grant.
ROLE_PERMISSIONS: Final[Mapping[AdminRole, frozenset[Permission]]] = MappingProxyType(
    {
        role: frozenset(permission for permission, row in RBAC_MATRIX.items() if role in row)
        for role in AdminRole
    }
)

#: Which step-up action guards which permission. Every permission whose grant carries a
#: step-up requirement appears here, asserted by test — a missing entry would be a route
#: that asks for a step-up nobody can grant.
STEP_UP_ACTIONS: Final[Mapping[Permission, StepUpAction]] = MappingProxyType(
    {
        Permission.REVEAL_PERSONAL_DATA: StepUpAction.REVEAL,
        Permission.REVEAL_MEDIA: StepUpAction.REVEAL,
        Permission.MODERATION_REVEAL: StepUpAction.REVEAL,
        Permission.ORDER_FORCE_DELIVER: StepUpAction.ORDER_FORCE_DELIVER,
        Permission.USER_BLOCK: StepUpAction.USER_BLOCK,
        Permission.CREDIT_GRANT: StepUpAction.CREDIT_GRANT,
        Permission.BROADCAST_SEND: StepUpAction.BROADCAST_SEND,
        Permission.MODERATION_DECIDE: StepUpAction.MODERATION_DECIDE,
        Permission.USER_PURGE: StepUpAction.USER_PURGE,
        Permission.CONFIG_WRITE: StepUpAction.CONFIG_WRITE,
        Permission.ORDER_EVIDENCE_EXPORT: StepUpAction.ORDER_EVIDENCE_EXPORT,
        Permission.AUDIT_EXPORT: StepUpAction.AUDIT_EXPORT,
        Permission.ADMIN_MANAGE: StepUpAction.ADMIN_MANAGE,
    }
)

#: Action → how fresh a grant for it must be, DERIVED from the matrix. An action is
#: ``FRESH`` when any permission it guards is, so the strictest cell wins and a second
#: hand-maintained list of "the grace-0 actions" — which would eventually disagree with
#: §12.2, and always in the loosening direction — does not exist.
_ACTION_STEP_UP: Final[Mapping[StepUpAction, StepUpRequirement]] = MappingProxyType(
    {
        action: (
            StepUpRequirement.FRESH
            if any(
                grant.step_up is StepUpRequirement.FRESH
                for permission, guarding in STEP_UP_ACTIONS.items()
                if guarding is action
                for grant in RBAC_MATRIX[permission].values()
            )
            else StepUpRequirement.REQUIRED
        )
        for action in STEP_UP_ACTIONS.values()
    }
)


@dataclass(frozen=True, slots=True)
class StepUpGrant:
    """A step-up as it is stored: the exact scope it was granted for, and when."""

    scope: str
    granted_at: datetime


def step_up_from_session(scope: str | None, granted_at: datetime | None) -> StepUpGrant | None:
    """Lift ``admin_sessions.step_up_scope`` / ``step_up_at`` into a grant, or ``None``.

    Both columns are nullable and are only meaningful together: half a grant is no grant.
    """
    if scope is None or granted_at is None:
        return None
    return StepUpGrant(scope=scope, granted_at=granted_at)


def build_step_up_scope(action: str, subject_id: str) -> str:
    """``"<action>:<subject-id>"``. Raises ``ValueError`` on a shape that cannot be stored.

    Validated rather than trusted because the result is written to a ``String(128)`` column
    and read back into an authorisation comparison: a scope carrying a newline, a space or
    2 KiB of anything is a bug upstream, and silently truncating it would widen a grant.
    """
    if not action or not subject_id:
        raise ValueError("a step-up scope needs both an action and a subject to be storable")
    scope = f"{action}{_SCOPE_SEPARATOR}{subject_id}"
    if len(scope) > MAX_STEP_UP_SCOPE_CHARS or _SCOPE_PATTERN.fullmatch(scope) is None:
        raise ValueError(f"step-up scope is not a storable identifier: {scope!r}")
    return scope


def grant_for(permission: Permission, role: AdminRole) -> Grant | None:
    """The cell for this role, or ``None`` when the matrix has none — which is a denial."""
    return RBAC_MATRIX[permission].get(role)


def is_permitted(permission: Permission, role: AdminRole) -> bool:
    """Role check only. Says nothing about masking or step-up; see :func:`check_access`."""
    return grant_for(permission, role) is not None


def _max_age_s(requirement: StepUpRequirement, grace_s: int) -> int:
    return STEP_UP_FRESH_MAX_AGE_S if requirement is StepUpRequirement.FRESH else grace_s


def max_age_for_action(action: StepUpAction, *, grace_s: int) -> int:
    """How many seconds a grant for ``action`` stays valid, given the configured grace.

    The one place outside :func:`check_access` that needs the answer is the step-up route,
    which reports an ``expiresAt`` to the SPA. It asks here rather than doing the arithmetic
    itself, because an ``expiresAt`` computed from the grace for an action the guard will
    only honour for zero seconds is a promise the next request breaks.
    """
    return _max_age_s(_ACTION_STEP_UP[action], grace_s)


def check_step_up(
    step_up: StepUpGrant | None,
    *,
    required_scope: str,
    now: datetime,
    max_age_s: int,
) -> AccessDecision:
    """Is ``step_up`` a live grant for exactly ``required_scope``?

    Scope equality is exact and whole-string: a grant for ``reveal:<order>`` is not a grant
    for ``user.block:<order>``, for ``reveal:<other-order>``, or for a prefix of either.
    """
    if step_up is None:
        return AccessDecision.STEP_UP_REQUIRED
    if step_up.scope != required_scope:
        return AccessDecision.STEP_UP_SCOPE_MISMATCH
    age_s = (now - step_up.granted_at).total_seconds()
    if age_s < 0 or age_s > max_age_s:
        # A grant timestamped in the future is a clock problem or a forged row; neither is
        # a reason to authorise a purge.
        return AccessDecision.STEP_UP_EXPIRED
    return AccessDecision.ALLOWED


def check_role(permission: Permission, role: AdminRole) -> AccessDecision:
    """As much as can be decided without a subject: the cell, and whether it wants a step-up.

    This is the router-level question. A router guard holds no subject — the subject is a
    path parameter only the handler has read — and therefore no grant either, so a window
    would be inert there. Rather than hand one over to be ignored, the router asks the
    narrower question and gets ``STEP_UP_REQUIRED`` for a cell whose step-up the request has
    not presented, which is the honest answer and the one the SPA turns into a prompt.
    """
    grant = grant_for(permission, role)
    if grant is None:
        return AccessDecision.FORBIDDEN_ROLE
    if grant.step_up is StepUpRequirement.NONE:
        return AccessDecision.ALLOWED
    return AccessDecision.STEP_UP_REQUIRED


def check_access(
    permission: Permission,
    *,
    role: AdminRole,
    now: datetime,
    grace_s: int,
    subject_id: str | None = None,
    step_up: StepUpGrant | None = None,
) -> AccessDecision:
    """The whole check: role first, then step-up when the cell demands one.

    ``subject_id`` identifies what the action is being taken against — an order id, a
    Telegram user id, a config version. It is required exactly when the cell requires a
    step-up, because the scope cannot be built without it.

    ``grace_s`` is ``AdminSettings.admin_step_up_grace_seconds``. It has no default on
    purpose: a caller that forgets it is a compile-time error rather than a route quietly
    honouring fifteen minutes after an operator configured one. It is ignored for the
    ``FRESH`` cells, so raising it cannot loosen a purge or a config commit.
    """
    grant = grant_for(permission, role)
    if grant is None:
        return AccessDecision.FORBIDDEN_ROLE
    if grant.step_up is StepUpRequirement.NONE:
        return AccessDecision.ALLOWED
    action = STEP_UP_ACTIONS[permission]
    if subject_id is None:
        _LOGGER.error(
            "step-up permission checked without a subject id; denying",
            extra={"event": "admin.rbac.missing_subject", "permission": str(permission)},
        )
        return AccessDecision.STEP_UP_REQUIRED
    return check_step_up(
        step_up,
        required_scope=build_step_up_scope(action, subject_id),
        now=now,
        max_age_s=_max_age_s(grant.step_up, grace_s),
    )


@dataclass(frozen=True, slots=True)
class PermissionGuard:
    """What :func:`require` returns: a callable that decides, and names its permission.

    The ``permission`` attribute is not decoration — the Slice 1c route-enumeration test
    reads it off each route's dependencies to assert that every route carries exactly one.
    """

    permission: Permission

    def __call__(
        self,
        *,
        role: AdminRole,
        now: datetime,
        grace_s: int,
        subject_id: str | None = None,
        step_up: StepUpGrant | None = None,
    ) -> AccessDecision:
        return check_access(
            self.permission,
            role=role,
            now=now,
            grace_s=grace_s,
            subject_id=subject_id,
            step_up=step_up,
        )


@dataclass(frozen=True, slots=True)
class StepUpGuard:
    """What :func:`require_step_up` returns: one action bound to one subject."""

    action: str
    subject_id: str

    @property
    def scope(self) -> str:
        return build_step_up_scope(self.action, self.subject_id)

    def __call__(
        self,
        step_up: StepUpGrant | None,
        *,
        now: datetime,
        max_age_s: int,
    ) -> AccessDecision:
        """``max_age_s`` has no default: see :func:`max_age_for_action` for where it comes
        from. A guard for a grace-0 action handed the ordinary grace would honour it, so the
        window is never guessed here."""
        return check_step_up(step_up, required_scope=self.scope, now=now, max_age_s=max_age_s)


def require(permission: Permission) -> PermissionGuard:
    """Declare the permission a router needs. Applied at router level, never per handler."""
    return PermissionGuard(permission=permission)


def require_step_up(action: str, subject_id: str) -> StepUpGuard:
    """Demand a step-up for this action **on this subject**.

    Both halves are load-bearing. ``require_step_up("user.block", user_id)`` rejects a grant
    obtained for ``reveal:<order-id>``, and it also rejects one obtained for
    ``user.block:<a-different-user>``.
    """
    # Built eagerly so an unstorable scope fails where the route is declared, not on the
    # first request that reaches it.
    build_step_up_scope(action, subject_id)
    return StepUpGuard(action=action, subject_id=subject_id)
