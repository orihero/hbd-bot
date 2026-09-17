"""``/support/groups`` — every chat the bot knows it is in, and which one gets the tickets.

**This namespace exists because Telegram has no "list my groups" API.** A bot cannot enumerate
the chats it belongs to; the only way it ever learns a group exists is a ``my_chat_member``
update, delivered when its OWN membership changes. A group the bot was already sitting in on
the day this shipped produces no such event, appears in no list, and cannot be backfilled from
anything. Every shape below is bent around that fact rather than around REST tidiness, and the
places it shows are worth naming once: the list is unpaged, a pasted chat id is a first-class
route rather than a debugging convenience, and "Telegram says the bot is a member" and "the bot
has been PROVED able to post" are two different fields on every row.

**A module of its own rather than two more routers in ``routers/support.py``.** That file opens
"this is the only namespace in the panel whose subject is a conversation", and a directory of
rooms is not a conversation — there is no customer on any row here, no body, no timeline, and
nothing to mask. The mechanical half is the same decision seen from the other side: the two
POSTs stand on ``SUPPORT_GROUP_WRITE``, which is a third permission, and §12.1 T3's rule is that
the guard is declared on the router — so they were always going to be a third factory. Putting
that factory in ``support.py`` would leave one file declaring three permissions across three
builders, and a reader could no longer tell which guard covers which route without
cross-referencing. ``users.py``, ``credits.py`` and ``billing.py`` split on exactly this line.

**ONE select endpoint, and deliberately no separate "add a manual chat".** An id the table has
never heard of is INSERTED as ``source=manual`` by the same call that selects it. A two-step
"add, then select" flow would invent a state — added, unselected, unverified, unowned — that
means nothing in this feature: a row nobody selected is a row nobody looks at, and the only
reason to type a chat id into this panel at all is to point the tickets at it. What makes that
safe is not a check this process could perform, because it cannot: a pasted id is an unverified
CLAIM (a typo, a room the bot was thrown out of, a channel, a group that has since migrated to a
new id), and **the verification job is what tells the truth about it**. The endpoint records the
claim and says so; ``verified_at`` says whether it works.

**Nothing here talks to Telegram, and nothing here can.** The admin process is denied a bot
token (``ADMIN_PANEL_PLAN D10 / §4.2``), so a selection is a database write plus an ARQ job
through :mod:`bayram.admin.queue` — a Redis write and nothing more. That is also why the
verification job's name is restated as a literal there rather than imported from
``bayram.runtime``: the module that holds the job holds an ``aiogram.Bot``, and
``test_the_seam_can_reach_nothing_that_sends_a_message`` reads ``admin/queue.py``'s imports.

**COMMIT, THEN ENQUEUE, and this is the second namespace to be built that way on purpose.**
``routers/support.py``'s module docstring times the window and names what it destroyed the first
time round; the short version is that :func:`bayram.admin.deps.get_db_session` commits on a
clean exit of the REQUEST, tens of milliseconds after a handler's last statement, while ARQ
polls Redis every half second — so a worker can win that window, open its OWN session under READ
COMMITTED, and act on rows nothing outside this connection can see. For the verification job
that means reading the chat it was handed, finding no such row, and either doing nothing or
writing a verdict about a selection that does not exist yet. So :func:`_select` writes, audits,
reads its answer back, calls :func:`_committed`, and enqueues after that. Do NOT move the
enqueue above the commit to make a dead worker roll the selection back; that is the bug, not the
tidy-up, and the price is stated where it is paid — a refused enqueue is a 503 over a committed
selection, which leaves an inbox that is pointed at the right room and has not been checked.

**Selecting enqueues; clearing does not.** There is nothing for a worker to verify about a chat
nobody is posting to, and a verdict recorded against a chat an operator has just unselected is a
red badge on a row that no longer claims anything. ``AdminQueue``'s "the seam carries work the
worker must do, never news it might like" is the rule; this is its fourth application.

**The GET must not record that it was viewed.**
``tests/test_admin/test_routes_enumeration.py`` snapshots every domain table around every GET
this application serves and asserts nothing changed. Every function in
:mod:`bayram.db.admin.bot_chats` is a ``sa.select``; nothing in the read router writes, and
nothing in it may ever start to — a "last checked by" stamp on a screen the panel polls would
write a row every few seconds.

**What a reader of this file must not do with ``botStatus``.** It is what Telegram last said, at
the instant it said it — evidence, never permission. An administrator can have
``can_post_messages`` taken away with no membership transition sent at all, and a ``manual`` row
has never had a transition in the first place. The only field that answers "can the bot post
here" is ``verifiedAt``, written by the job that actually tried.

``routers/support.py`` is the style this file copies, and it is the file whose
committed-then-enqueued pattern is copied rather than reinvented.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError

from bayram.admin import audit_sink
from bayram.admin.deps import API_PREFIX, Admin, Container, CurrentAdmin, Db, require_permission
from bayram.admin.errors import AdminErrorCode, ProblemError, problem, unwrap
from bayram.admin.schemas.groups import (
    SupportGroupClearResponse,
    SupportGroupSelectionView,
    SupportGroupSelectRequest,
    SupportGroupSelectResponse,
    SupportGroupsResponse,
    to_groups_response,
)
from bayram.admin.security.permissions import Permission
from bayram.bot_chats import SelectionChange
from bayram.db.admin.audit import AuditEntry
from bayram.db.admin.bot_chats import list_bot_chats
from bayram.db.base import utc_now
from bayram.db.bot_chats import clear_support_group, select_support_group
from bayram.db.enums import AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.db.models.bot_chat import SELECTED_SUPPORT_GROUP_INDEX

__all__ = [
    "SUPPORT_GROUPS_PATH",
    "SUPPORT_GROUP_SELECT_PATH",
    "SUPPORT_GROUP_CLEAR_PATH",
    "BOT_CHAT_SUBJECT_TYPE",
    "SUPPORT_GROUP_REASON",
    "build_support_groups_router",
    "build_support_group_actions_router",
]

SUPPORT_GROUPS_PATH: Final[str] = f"{API_PREFIX}/support/groups"

#: ``/select`` and ``/clear`` are literal segments under ``/support/groups`` and there is no
#: parameterised sibling for either to shadow — this whole namespace takes NO path parameter, so
#: registration order is free here in a way it pointedly is not one namespace along, where
#: ``SUPPORT_BOARD_PATH`` must be declared ahead of ``{ticket_id}`` or an operator's board is
#: answered with a 422 about a malformed UUID.
#:
#: The chat id travels in the BODY rather than in the path, and that is a decision rather than
#: an accident of the verb. It is a 64-bit NEGATIVE integer somebody may have typed by hand; in
#: a path it would be validated by a converter that knows only "int", so a pasted user id (a
#: person) or a value wider than ``BIGINT`` would reach the handler and be refused two
#: statements deeper, inside a transaction that had already cleared the previous selection. In
#: the body it is a pydantic field with the real bounds on it and a 422 that names ``chatId``.
SUPPORT_GROUP_SELECT_PATH: Final[str] = f"{SUPPORT_GROUPS_PATH}/select"
SUPPORT_GROUP_CLEAR_PATH: Final[str] = f"{SUPPORT_GROUPS_PATH}/clear"

#: ``admin_audit_log.subject_type`` for every row this module writes, spelled once — the
#: ``TICKET_SUBJECT_TYPE`` and ``BROADCAST_SUBJECT_TYPE`` precedent, because a second literal is
#: a second way for one chat's rows to end up under two subjects. It is a member of the CLOSED
#: :data:`~bayram.db.admin.audit.SUBJECT_TYPES` frozenset; a value outside it raises
#: ``AuditValueRejectedError`` inside ``append``, which ``audit_sink`` SWALLOWS and retries with
#: ``subject_id=None`` — a 200 carrying a row that has lost the chat it was about.
#:
#: The subject id is ``bot_chats.chat_id`` as text: Telegram's own negative integer, which is
#: this table's primary key. Not the group's title (it is renamed by people who do not work
#: here) and not the ``@handle`` (most groups have none).
BOT_CHAT_SUBJECT_TYPE: Final[str] = "bot_chat"

#: The reason every row this module writes carries, stamped by the server rather than asked for
#: — neither request body takes a ``reasonCode``, which ``schemas/groups.py`` argues.
#:
#: ``ROUTINE_OPS`` and **not** ``routers/support.py``'s ``SUPPORT_INVESTIGATION``, which is the
#: one place these two neighbouring namespaces deliberately diverge. That code means "the
#: support desk was working a complaint", and filtering the audit log on it should return
#: exactly that population — four operators answering four customers. Choosing which Telegram
#: room the cards are posted into is not an investigation of anybody: it is configuration of the
#: desk itself, done once and then not again for months, and folding it into the same code would
#: put a deployment-wide setting into the same bucket as the work it configures. The ACTION
#: (``support.group.select`` / ``support.group.clear``) is what an investigator filters on here;
#: the reason code is honest about the category rather than decorative.
SUPPORT_GROUP_REASON: Final[AuditReasonCode] = AuditReasonCode.ROUTINE_OPS

#: What a concurrent double-press is told. Two operators pressing Select in the same instant
#: each read one selected row, each clear the row they read, each set their own — and under
#: READ COMMITTED both transactions are legal right up to the commit, where
#: ``ix_bot_chats_selected_support_group`` refuses the second. That is the index doing the job
#: the transaction ordering cannot, and the loser is told to look again rather than being handed
#: a 500.
_RACED_SELECTION: Final[str] = "another operator changed the support group at the same moment"


def build_support_groups_router() -> APIRouter:
    """The directory an operator reads. ``SUPPORT_READ``, declared once, on the router.

    **The same cell the ticket queue stands on, and every role holds it** — VIEWER included.
    "Where do my tickets go?" is a question an operator must be able to answer without being
    able to change the answer, and the row it is answered from holds no customer at all: a chat
    id, a title, a public ``@handle``, three closed enums and a colleague's login. The write
    cell beside it is a different permission for exactly that reason.
    """
    router = APIRouter(
        tags=["support"],
        dependencies=[Depends(require_permission(Permission.SUPPORT_READ))],
    )

    @router.get(SUPPORT_GROUPS_PATH)
    async def support_groups(db: Db) -> SupportGroupsResponse:
        """Every chat the bot knows it is in, the selected one first. **Unpaged.**

        No ``PageRequest``, no cursor, no ``withTotal``, and that is a judgement about the data
        rather than an omission: Telegram has no "list my groups" API, so this table fills one
        row at a time from ``my_chat_member`` updates and from ids an operator typed, and its
        population is a handful in every deployment this product will have.
        :func:`~bayram.db.admin.bot_chats.list_bot_chats` argues it at length, including the
        failure mode if the assumption ever breaks — a silly screen rather than a silent
        truncation.

        **This route writes nothing and must not start to.** It is the read a "last checked"
        stamp would naturally attach itself to, and ``test_no_get_route_changes_domain_state``
        snapshots every domain table around it.
        """
        return to_groups_response(await list_bot_chats(db))

    return router


def build_support_group_actions_router() -> APIRouter:
    """Select and clear — both on ``SUPPORT_GROUP_WRITE``, both audited, neither stepped up.

    One factory because one permission (§12.1 T3). ``SUPPORT_GROUP_WRITE`` is ADMIN and OWNER
    with **no step-up**, so there is nothing for a handler below to enforce — which is the
    deliberate consequence of the cell being a plain ``W`` rather than an oversight. The
    permission's own note argues why repointing the inbox is not ``SUPPORT_WRITE``, why it is
    not ``W+S``, and what split this file would have to take if a reviewer ever decided it
    should be.
    """
    router = APIRouter(
        tags=["support"],
        dependencies=[Depends(require_permission(Permission.SUPPORT_GROUP_WRITE))],
    )

    @router.post(SUPPORT_GROUP_SELECT_PATH)
    async def select_group(
        body: SupportGroupSelectRequest, db: Db, admin: Admin, container: Container
    ) -> SupportGroupSelectResponse:
        """Point the support inbox at a chat — known or pasted — and go and check it.

        **An id the directory has never heard of is recorded as ``source=manual`` by this same
        call**, which is why there is one endpoint here and not two. A pasted id is an
        unverified claim and the panel says so: the row is born ``bot_status=unknown``, with a
        ``chat_type`` inferred from the id's shape and nothing in ``verified_at``. The
        verification job enqueued at the end of this handler is what turns the claim into a fact
        or into a failure an operator can act on — see the module docstring, and
        :func:`~bayram.db.bot_chats.select_support_group`, which argues why a chat the bot was
        kicked from is still selectable (``delete_webhook(drop_pending_updates=True)`` makes a
        stale ``kicked`` the ordinary state after a deploy).

        **The write clears before it sets, inside this request's transaction.** Setting first
        would trip ``ix_bot_chats_selected_support_group`` against a row this same transaction
        was about to clear — an ``IntegrityError`` on the HAPPY path. The index is still not
        redundant with that ordering: it is what closes the concurrent double-press the ordering
        cannot, and this handler turns the refusal into a 409 rather than a 500.

        **THE ANSWER ALWAYS CARRIES THE CHOSEN ROW AS "checking…", INCLUDING WHEN THAT CHAT WAS
        VERIFIED LAST MONTH.** :func:`~bayram.db.bot_chats.select_support_group` nulls
        ``verified_at`` and ``verification_error`` in the same statement that claims the row, so
        the directory re-read below cannot publish a verdict from before this press. That is not
        cosmetic: the panel does not poll, so whatever this response says about verification is
        what an operator sees until they press something — and a chat verified in August and
        since abandoned would otherwise come back accent-green on both the row and the "Ticket
        cards go to" header, a second before the worker's 403 is written where nothing will read
        it. This route must not "helpfully" restore the old verdict on a re-select; the pair is
        the verdict on the CURRENT selection and there is not one yet.

        **This is also the "Check again" endpoint.** The dialog's button on the already-selected
        row posts this same body, and the reset plus the enqueue below is the entire mechanism
        behind it — so an operator who has just fixed a permission in Telegram watches the red
        sentence clear rather than being shown the identical one and left guessing whether the
        check ran. It is the only way out of the 503 case too: the enqueue follows the commit,
        so a Redis blip leaves the inbox moved and its row honestly reading "checking…" with
        nothing coming, and pressing the button again is what asks for a verdict.

        **``threadId`` travels with the selection.** Omitting it clears the topic, by design —
        "the group itself" has to be expressible — so a client that means to keep a topic must
        send it. ``schemas/groups.py`` says the same thing where a client author would look.

        Read, project, COMMIT, enqueue — the order ``routers/support.py`` explains and this
        module's docstring argues. ``db`` is unusable after :func:`_committed`.
        """
        now = utc_now()
        try:
            change = await select_support_group(
                db,
                body.chat_id,
                thread_id=body.thread_id,
                selected_by_username=admin.username,
                now=now,
            )
        except IntegrityError as exc:
            # The losing side of a genuine race, recognised by WHICH index exists rather than
            # by parsing the driver's prose: psycopg and aiosqlite word this violation
            # differently and both are free to reword it in a patch release, so a substring
            # match on ``SELECTED_SUPPORT_GROUP_INDEX`` would be a 500 the day either did.
            # ``bot_chats`` has exactly one unique index — that one, named and exported by the
            # model for this purpose — so on THIS statement an ``IntegrityError`` has one
            # meaning. The ``admin_users`` bootstrap catches ``ACTIVE_OWNER_INDEX``'s violation
            # the same way, and for the same reason.
            #
            # No audit row: this transaction is already aborted, so a row cannot go in it, and
            # ``record_refusal`` would have to open its own while this one is mid-rollback.
            # Nothing was written, and the operator who WON the race has their row in the log.
            raise _double_press() from exc
        await audit_sink.record(
            db,
            container,
            _entry(
                admin,
                action=AuditAction.SUPPORT_GROUP_SELECT,
                chat_id=change.chat_id,
                field_names=("bot_chats.is_support_group", "bot_chats.thread_id"),
            ),
            now=now,
        )
        answer = SupportGroupSelectResponse(
            groups=to_groups_response(await list_bot_chats(db)).groups,
            selection=_selection_view(change),
        )
        # COMMIT, then enqueue. The worker opens its own session and reads the chat by id; a
        # job that overtook this commit would find no such row and either do nothing or write a
        # verdict about a selection nothing outside this connection can see.
        await _committed(db)
        unwrap(await container.queue.enqueue_support_group_verification(change.chat_id))
        return answer

    @router.post(SUPPORT_GROUP_CLEAR_PATH)
    async def clear_group(db: Db, admin: Admin, container: Container) -> SupportGroupClearResponse:
        """Unselect the support group. **Tickets keep working; only the group post stops.**

        This is a supported state and not a broken one — it is the fallback D18 named, reached
        by a click now rather than by a redeploy — so clearing when nothing is selected is a
        **200 and never a 404**: the caller asked for "no group selected" and that is what they
        have. Answering a second press with an error would report a failure for arriving at
        exactly the requested outcome.

        **Nothing is enqueued.** There is no room to verify and no card to render, and a job
        that told the worker "there is now no support group" would be news rather than work.

        **``selectedAt``, ``selectedByUsername`` and ``threadId`` are left standing on the row**
        — only the boolean moves. "This was once the support group, chosen by this person, on
        that day, in that topic" is the most useful thing to know about a chat an operator is
        looking at while wondering where last month's tickets went, and re-selecting it later
        keeps the topic it always had. :func:`~bayram.db.bot_chats.clear_support_group` owns
        that decision; this route must not tidy it away.

        **A press that cleared nothing writes no audit row**, which is the one asymmetry in this
        module worth stating. The log records what was DONE, and nothing was: there is no chat
        to name as the subject, and a row carrying ``subject_id=None`` is exactly the shape
        ``audit_sink`` produces when it swallows a rejected subject type and retries — so
        writing one deliberately would make that bug indistinguishable from an ordinary entry.
        """
        now = utc_now()
        cleared = await clear_support_group(db, now=now)
        if cleared is not None:
            await audit_sink.record(
                db,
                container,
                _entry(
                    admin,
                    action=AuditAction.SUPPORT_GROUP_CLEAR,
                    chat_id=cleared,
                    field_names=("bot_chats.is_support_group",),
                ),
                now=now,
            )
        return SupportGroupClearResponse(
            groups=to_groups_response(await list_bot_chats(db)).groups,
            cleared_chat_id=cleared,
        )

    return router


# ---------------------------------------------------------------------------
# The shared bodies
# ---------------------------------------------------------------------------
def _double_press() -> ProblemError:
    """409, naming neither chat. Two operators raced; the answer is "read it again".

    The winning chat is deliberately not published. This request lost at the index, so the
    handler does not know what won without a second read — and a second read inside an aborted
    transaction is not available. ``_wrong_status`` one namespace along publishes the status it
    read a moment BEFORE the write for the same reason, rather than pretending to have raced it.
    """
    return problem(
        AdminErrorCode.CONFLICT,
        _RACED_SELECTION,
        index=SELECTED_SUPPORT_GROUP_INDEX,
    )


def _selection_view(change: SelectionChange) -> SupportGroupSelectionView:
    """What the write reported, on the wire. ``moved`` is computed by the value, not here.

    :attr:`~bayram.bot_chats.SelectionChange.moved` is a property of the record rather than an
    expression in this function, so the sentence the panel renders and the fact the audit row
    describes are read off one definition. Re-deriving ``previous is not None and previous !=
    chat`` here would be a second copy of a rule whose whole subtlety is the case where the two
    ids are EQUAL — an operator re-selecting the same group to change its topic, which is an
    ordinary act and is not a move.
    """
    return SupportGroupSelectionView(
        chat_id=change.chat_id,
        previous_chat_id=change.previous_chat_id,
        thread_id=change.thread_id,
        created=change.created,
        moved=change.moved,
    )


async def _committed(db: Db) -> None:
    """End the request's transaction HERE, so the enqueue that follows names committed rows.

    ``routers/support.py``'s :func:`_committed` is the original and carries the full argument,
    including the two rejected alternatives (committing inside ``get_db_session``, and a
    ``BackgroundTask``). It is restated rather than imported for the reason a private helper is
    always restated: importing another router's underscore-prefixed function would couple two
    modules through a name neither exports, and the one-line body is not the part worth sharing
    — the constraint is.

    **Nothing may touch ``db`` after this call.** ``get_db_session`` holds the session inside
    ``async_sessionmaker.begin()``, and SQLAlchemy's ``TransactionalContext`` refuses any further
    statement on a transaction closed inside its own context manager. So the handler above reads
    the directory, builds its answer, calls this, and enqueues last; a read moved below this line
    is a 500 at runtime that no type checker will catch.
    """
    await db.commit()


def _entry(
    admin: CurrentAdmin,
    *,
    action: AuditAction,
    chat_id: int,
    field_names: tuple[str, ...],
) -> AuditEntry:
    """One row for one press. Both handlers in this module build their row here.

    ``subjectType`` is :data:`BOT_CHAT_SUBJECT_TYPE` and ``subjectId`` the chat's own id as
    text. On a CLEAR that is the chat that WAS selected rather than nothing at all: "nothing" is
    not a subject, and an entry that named none would lose the only fact an incident review
    wants from it — which room stopped receiving the cards.

    ``fieldNames`` names columns and never their values, the rule every audit row in this
    package follows, and the literal ``table.column`` spelling ``^[a-z][a-z0-9_.]{0,63}$``
    requires. The chat TITLE is never among them: it is a string other people choose, it changes
    without anybody here doing anything, and the 730-day table is not the place to accumulate
    copies of it.

    ``recordCount`` is absent on both. The column means "how many people did this authorise a
    message to", and the answer is not one — it is every ticket from now until somebody presses
    one of these buttons again, which is not a number this request knows.
    """
    return AuditEntry(
        action=action,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=BOT_CHAT_SUBJECT_TYPE,
        subject_id=str(chat_id),
        field_names=field_names,
        reason_code=SUPPORT_GROUP_REASON,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )
