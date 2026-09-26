"""``python -m bayram.payme.cli`` — the rail's recovery surface, and on day one the ONLY one.

**Why this exists at all.** "The customer paid and got nothing" is the commonest real payment
incident there is, and this rail has no outbound Merchant API: there is no method a merchant
may call to ask Payme what happened to a transaction, so every answer has to come from our own
tables plus the operator's reading of the cabinet. Without this file the answer to a lost
callback is SSH and ``psql`` on a production host, typing ``UPDATE payment_intents`` by hand
next to a ``credit_ledger`` whose ``verify_balances`` invariant that ``UPDATE`` would break —
and on this deployment the standing note is that SSH to the box is not reliably available.
The recovery MECHANISM therefore ships in the same increment as the rail. The admin HTTP API
and the payments screens are deferred deliberately (``PAYME_INTEGRATION §8``): the panel's own
redesign has WS3-WS8 outstanding with WS3 as the root blocker, and payments screens built on a
surface that is about to be rebuilt would be thrown away twice.

**The rule this file inherits from :mod:`bayram.tools`, and where it consciously departs.**
``bayram.tools``' own docstring states it: an operator tool WRITES through the same functions the
product does and never its own SQL, so it cannot produce a row shape the ordinary path could
not. Every write here obeys that without exception — ``settle`` is
``PaymeLedger.force_settle``, ``reconcile`` is the sweep's own three arms, ``notify`` is the
same ARQ enqueue the gateway makes after a settlement, and ``pause`` is
:func:`bayram.payme.pause.set_paused`. **The departure is on the READ side and it is deliberate.**
``journal`` has to answer "did Payme ever call us about this, what did we say, and did the
money land" — which spans ``payment_intents``, ``payme_transactions``, ``payme_rpc_log``,
``topup_purchases``, ``plan_purchases`` and ``credit_ledger``, six tables that no port exposes
together and should not: :class:`bayram.payme.ports.PaymeLedger` is the surface an INTERNET-FACING
process holds, and widening it with a cross-table diagnostic join so that a human could read it
would put that join one authentication bug away from a stranger. So the dossier below is
assembled from read-only statements in this module, inside ``run_guarded`` like every other
database call in this codebase, and NOTHING in this file writes SQL of its own.

**This is the SECOND module in ``bayram.payme`` that imports ``bayram.db``**, after
:mod:`bayram.payme.container`, whose docstring calls itself the only one. That sentence needs
amending rather than obeying, and the exception is the same one: a composition root is defined
by importing everything it wires, and this file is a process entry point that joins the two
halves exactly as the gateway's lifespan does. The bar the rest of the package obeys — no
module that implements protocol behaviour may reach into persistence — is untouched: every
other file here would still typecheck with ``bayram.db`` deleted from the tree, and so would the
gateway. Nothing imports this module; it has no callers inside the product at all, which is
``bayram.tools``' own rule for an operator tool and the reason it can afford the wider reach.

**Why the journal is unanswerable from the process logs.** ``RequestLogMiddleware`` records the
route TEMPLATE and not the body, by design and for good privacy reasons, so the application log
can say that ``POST /payme`` was called four hundred times and cannot say which transaction any
of them concerned. ``payme_rpc_log`` exists for exactly that gap and carries no Telegram id, no
request body and no header (see the migration's docstring for the privacy argument). This tool
is what makes that table legible.

**Exit codes are part of the interface**, because ``invariant`` is meant to be reachable from a
monitoring cron and a command that reports a settlement mismatch on standard output while
exiting ``0`` is a command nobody will notice:

* ``0`` — the command did what it said.
* ``1`` — refused. The operator's input was wrong, or the rail's state made the action
  impossible. Nothing was written.
* ``2`` — configuration or database failure. Nothing was written.
* ``3`` — the command ran, and what it found is wrong: a settlement invariant that does not
  balance, or a reconcile arm that failed.

**Every subcommand takes its instant from the container's injected clock**, never from a bare
``utc_now()`` at a call site, so a certification rehearsal driving the twelve-hour window in
seconds sees the same time here as the gateway does. That is the same rule the rest of the
integration follows and it is what lets ``reconcile`` be tested at all.

**It builds the GATEWAY's container and therefore the gateway's settings** — ``PaymeSettings``
from ``BAYRAM_PAYME_ENV_FILE`` — so it must be run on the host that holds ``/etc/bayram/payme.env``.
It does NOT check ``payme_enabled``, and that omission is load-bearing: the first thing an
operator does in a payment incident is switch the rail off, and a recovery tool that refused to
run against a disabled rail would be unusable at precisely the moment it is needed. ``status``
reports the flag instead.

See ``DECISIONS.md D11``, ``PAYME_INTEGRATION §5`` for the replay guarantees ``settle`` relies
on, ``§6`` for why there is no reversal and what an operator does instead, and
``docs/deployment/08-payme.md`` for the runbooks each subcommand belongs to.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import PaymentIntent, PaymentIntentState
from bayram.contracts import Result, is_err
from bayram.db.enums import PaymentIntentState as StoredIntentState
from bayram.db.enums import PaymeState as StoredPaymeState
from bayram.db.guard import run_guarded
from bayram.db.models.credit_ledger import CreditLedgerRow
from bayram.db.models.payme_rpc_log import PaymeRpcLogRow
from bayram.db.models.payme_transaction import PAYME_TRANSACTION_ID_LENGTH, PaymeTransactionRow
from bayram.db.models.payment_intent import PUBLIC_REF_LENGTH, PaymentIntentRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.errors import BayramError
from bayram.logging import configure_logging, get_logger
from bayram.payme.container import PaymeContainer, QueuedNotifier, payme_container
from bayram.payme.pause import PauseSwitch, is_paused, set_paused
from bayram.payme.ports import OPERATOR_SETTLE_PREFIX, PaymeLedger, PaymeStatementRow
from bayram.payme.settings import build_payme_settings

__all__ = [
    "main",
    "plan",
    "apply",
    "console_for",
    "OperatorConsole",
    "Report",
    "RefusedError",
    "Journal",
    "Statement",
    "Settle",
    "Notify",
    "Pause",
    "Status",
    "Invariant",
    "Reconcile",
    "Request",
    "OPERATOR_SETTLE_PREFIX",
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_CONFIG",
    "EXIT_MISMATCH",
]

_LOG = get_logger(__name__)

EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 1
EXIT_CONFIG: Final[int] = 2
EXIT_MISMATCH: Final[int] = 3

# ``OPERATOR_SETTLE_PREFIX`` — what ``payment_intents.settle_note`` starts with when a human
# settled the intent rather than a ``PerformTransaction`` — is IMPORTED from
# ``bayram.payme.ports`` above and re-exported in ``__all__``, not respelled here. This module
# only READS it, to split the settlement counts into the two populations an operator has to tell
# apart. It used to carry its own copy, on the argument that the ledger kept its own private and
# an underscore import would be a promise about another module's internals. Promoting the string
# into ``ports`` — the one module ``bayram.db`` and this package both already import, and which
# neither may skip — answers that objection instead of adding a third copy for the admin read
# layer. ``test_cli.py`` pins both ends: that a real force-settled row starts with it, and that
# this name IS the one in ``ports``.

#: How long a settled intent is left alone before ``reconcile`` re-enqueues its announcement.
#: The same grace ``bayram.runtime.payme_jobs`` uses, and for the same reason: an intent settled
#: two seconds ago probably has a job in flight, and racing it would be two messages about one
#: song. Restated rather than imported because ``bayram.payme`` may not depend on
#: ``bayram.runtime``.
NOTIFY_GRACE_S: Final[int] = 60

#: The ceiling on rows any single arm of ``reconcile`` touches, and on ``journal --since``.
#: A bound rather than "all of them" because this runs on a production host during an incident
#: and an unbounded sweep is how a recovery tool becomes the second outage.
DEFAULT_BATCH: Final[int] = 200

#: ``journal --since`` and ``status`` look back over this by default. Twenty-four hours is the
#: window the settlement invariant is specified against (``PAYME_INTEGRATION §3``), so the two
#: commands agree about what "recently" means without an operator having to pass a flag.
DEFAULT_WINDOW_HOURS: Final[int] = 24
_MAX_WINDOW_HOURS: Final[int] = 24 * 365

#: The alphabet ``public_ref`` is minted from — ``secrets.token_hex(12)``. Validated here so a
#: mistyped reference is one sentence rather than a database round trip that finds nothing, and
#: so a reference pasted with a stray ``;`` or ``=`` (the two characters Payme's own link parser
#: treats structurally) is refused by the tool rather than by the rail.
_HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")

#: How much operator note this tool will carry. The COLUMN is 64 and the ledger truncates to
#: it deliberately; this larger bound exists only to stop a pasted stack trace becoming a
#: settle note, and is generous on purpose — refusing a note for length at the moment somebody
#: is settling a real payment by hand would be the tool getting in the way of its own purpose.
_MAX_NOTE: Final[int] = 200

_ISO_HINT: Final[str] = (
    "give an ISO-8601 instant, for example 2026-09-09T00:00:00Z or 2026-09-09T03:30:00+05:00. "
    "A value with no offset is read as UTC."
)


class RefusedError(Exception):
    """An operator-facing refusal. Its message is printed and nothing else is.

    An exception rather than a ``Result``, the same shape :mod:`bayram.tools.credits` and
    :mod:`bayram.admin.bootstrap` use and for the same reason: :func:`main` is the boundary of the
    process, there is no caller to hand a value back to, and what it owes the operator is one
    sentence and an exit code. A traceback here would put the database DSN — password included
    — on a terminal and into a shell's scrollback.
    """


# ---------------------------------------------------------------------------
# What the command line asks for. One frozen value per subcommand.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Journal:
    """``journal`` — everything this deployment knows about one payment, or a recent list.

    Exactly one of the three selectors is set; :func:`_collect` refuses the other combinations,
    so nothing downstream has to decide what ``--ref`` plus ``--since`` would mean.
    """

    public_ref: str | None
    payme_transaction_id: str | None
    since: datetime | None
    limit: int


@dataclass(frozen=True, slots=True)
class Statement:
    """``statement`` — exactly the rows ``GetStatement`` would return for a period."""

    frm: datetime
    to: datetime


@dataclass(frozen=True, slots=True)
class Settle:
    """``settle`` — the recovery button. The note is mandatory; see :func:`_note`."""

    public_ref: str
    note: str


@dataclass(frozen=True, slots=True)
class Notify:
    """``notify`` — re-enqueue the "your payment went through" announcement."""

    public_ref: str


@dataclass(frozen=True, slots=True)
class Pause:
    """``pause`` and ``resume``. One value, because they are one action with two settings."""

    paused: bool


@dataclass(frozen=True, slots=True)
class Status:
    """``status`` — the rail state, the last inbound call, and the recent funnel."""

    hours: int


@dataclass(frozen=True, slots=True)
class Invariant:
    """``invariant`` — the three-way settlement count over a window. Exits 3 on a mismatch."""

    hours: int


@dataclass(frozen=True, slots=True)
class Reconcile:
    """``reconcile`` — run the sweep's arms once, synchronously, now."""

    limit: int


type Request = Journal | Statement | Settle | Notify | Pause | Status | Invariant | Reconcile


@dataclass(frozen=True, slots=True)
class Report:
    """What a subcommand produced: the lines to print, and the code to exit with.

    A value rather than a bare string because three of these commands can succeed at running
    and still be reporting bad news — an invariant that does not balance, a reconcile arm that
    could not read its backlog — and an operator's cron needs to be able to tell that from
    standard output being non-empty. See the module docstring's exit-code table.
    """

    lines: tuple[str, ...]
    exit_code: int = EXIT_OK

    def text(self) -> str:
        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
# The collaborators a subcommand acts through. Built from the gateway's container.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class OperatorConsole:
    """Everything :func:`apply` is allowed to touch, and nothing else.

    A value object rather than the whole :class:`bayram.payme.container.PaymeContainer` for two
    reasons. The first is testability: a test can hand in a fake pause switch that raises on
    demand and a notifier that records instead of reaching Redis, and drive every subcommand
    against an in-memory database with no queue anywhere. The second is narrowing, the same
    discipline the container itself applies — nothing here can reach ``settings`` and start
    making decisions from configuration that the gateway has already made, and nothing can
    reach the ASGI ``service`` and answer a JSON-RPC call from a terminal.

    ``ledger`` is typed as the PORT. ``sessions`` is the exception argued in the module
    docstring: read-only, diagnostic, and never written through.
    """

    ledger: PaymeLedger
    sessions: async_sessionmaker[AsyncSession]
    switch: PauseSwitch
    notify: Callable[[str], Awaitable[None]]
    clock: Callable[[], datetime]
    merchant_id: str
    account_field: str
    is_sandbox: bool
    is_enabled: bool


def console_for(container: PaymeContainer) -> OperatorConsole:
    """Narrow the gateway's container to the operator surface. The only place they are joined.

    The notifier is the container's OWN :class:`bayram.payme.container.QueuedNotifier`, deliberately
    rather than a fresh enqueue spelled here: it carries the deterministic job id, so an
    operator's ``notify`` and the gateway's post-commit enqueue for the same intent collapse into
    one ARQ job instead of two messages about one song.
    """
    return OperatorConsole(
        ledger=container.ledger,
        sessions=container.session_factory,
        switch=container.redis,
        notify=QueuedNotifier(container.redis),
        clock=container.clock,
        merchant_id=container.settings.payme_merchant_id,
        account_field=container.settings.payme_account_field,
        is_sandbox=container.settings.payme_is_sandbox,
        is_enabled=container.settings.payme_enabled,
    )


# ---------------------------------------------------------------------------
# Parsing and validation. Every refusal about the operator's INPUT happens here.
# ---------------------------------------------------------------------------
def _parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m bayram.payme.cli",
        description=(
            "Inspect and recover Payme payments. Reads the gateway's own settings, so run it "
            "on the host that holds the payme env file."
        ),
        epilog=(
            "Exit codes: 0 done, 1 refused, 2 configuration or database failure, "
            "3 ran but found a mismatch."
        ),
    )
    sub = parser.add_subparsers(dest="verb", required=True)

    journal = sub.add_parser(
        "journal",
        help="everything known about one payment: intent, transactions, receipt, grant, RPC log",
    )
    selector = journal.add_mutually_exclusive_group(required=True)
    selector.add_argument("--ref", default=None, help="our public reference (the ac. value)")
    selector.add_argument("--payme-id", default=None, help="Payme's own 24-character id")
    selector.add_argument(
        "--since", default=None, help=f"list intents opened since this instant. {_ISO_HINT}"
    )
    journal.add_argument(
        "--limit", default=str(DEFAULT_BATCH), help=f"rows for --since (default {DEFAULT_BATCH})"
    )

    statement = sub.add_parser(
        "statement", help="the rows GetStatement would return, to diff against a cabinet export"
    )
    statement.add_argument(
        "--from", dest="frm", required=True, help=f"start, inclusive. {_ISO_HINT}"
    )
    statement.add_argument("--to", required=True, help=f"end, inclusive. {_ISO_HINT}")

    settle = sub.add_parser(
        "settle",
        help=(
            "settle an intent by hand after a lost callback. Writes the sale under the "
            "intent's own idempotency key, so a late genuine PerformTransaction grants nothing "
            "twice."
        ),
    )
    settle.add_argument("--ref", required=True, help="our public reference")
    settle.add_argument(
        "--note",
        required=True,
        help=(
            "why, and on whose evidence. Stored on the intent forever as operator:<note>, "
            "which is what distinguishes a hand-settled sale from a rail-settled one."
        ),
    )

    notify = sub.add_parser("notify", help="re-enqueue the settled-payment announcement")
    notify.add_argument("--ref", required=True, help="our public reference")

    sub.add_parser("pause", help="stop opening NEW checkouts. Never refuses a payment in flight")
    sub.add_parser("resume", help="start opening checkouts again")

    status = sub.add_parser(
        "status", help="the pause switch, the last inbound call, and the recent funnel"
    )
    status.add_argument("--hours", default=str(DEFAULT_WINDOW_HOURS), help="window to count over")

    invariant = sub.add_parser(
        "invariant", help="the three-way settlement count. Exits 3 when it does not balance"
    )
    invariant.add_argument(
        "--hours", default=str(DEFAULT_WINDOW_HOURS), help="window to count over"
    )

    reconcile = sub.add_parser("reconcile", help="run the sweep's arms once, synchronously")
    reconcile.add_argument(
        "--limit", default=str(DEFAULT_BATCH), help=f"rows per arm (default {DEFAULT_BATCH})"
    )
    return parser.parse_args(argv)


def plan(argv: Sequence[str]) -> Request:
    """What this command line asks for, fully validated — or a :class:`RefusedError`.

    Separated from :func:`main` for the reason :func:`bayram.tools.credits.plan` is: every refusal
    below is a judgement about the operator's own input, none of them needs an engine to be
    proved, and a test that had to stand up a database to assert "a mistyped reference is
    refused" would be asserting something else.
    """
    return _collect(_parse(argv))


def _collect(args: argparse.Namespace) -> Request:
    """Turn parsed arguments into a validated request. Nothing below this line reads argv."""
    verb = str(args.verb)
    if verb == "journal":
        return Journal(
            public_ref=_public_ref(args.ref) if args.ref is not None else None,
            payme_transaction_id=(_payme_id(args.payme_id) if args.payme_id is not None else None),
            since=_instant(args.since, "--since") if args.since is not None else None,
            limit=_bounded(args.limit, "--limit", low=1, high=1000),
        )
    if verb == "statement":
        frm = _instant(args.frm, "--from")
        to = _instant(args.to, "--to")
        if to < frm:
            raise RefusedError("Refusing a statement whose --to falls before its --from.")
        return Statement(frm=frm, to=to)
    if verb == "settle":
        return Settle(public_ref=_public_ref(args.ref), note=_note(args.note))
    if verb == "notify":
        return Notify(public_ref=_public_ref(args.ref))
    if verb == "pause":
        return Pause(paused=True)
    if verb == "resume":
        return Pause(paused=False)
    if verb == "status":
        return Status(hours=_bounded(args.hours, "--hours", low=1, high=_MAX_WINDOW_HOURS))
    if verb == "invariant":
        return Invariant(hours=_bounded(args.hours, "--hours", low=1, high=_MAX_WINDOW_HOURS))
    return Reconcile(limit=_bounded(args.limit, "--limit", low=1, high=1000))


def _public_ref(raw: str) -> str:
    """Our own opaque reference, refused rather than looked up when it cannot be one of ours.

    Checked against the mint's alphabet and the column's width rather than against the current
    length of ``secrets.token_hex(12)``: pinning 24 here would make a future widening of the
    reference a silent refusal in the recovery tool, discovered during an incident.
    """
    text = raw.strip()
    if not text or len(text) > PUBLIC_REF_LENGTH:
        raise RefusedError(
            f"Refusing --ref {raw!r}: a reference is 1 to {PUBLIC_REF_LENGTH} characters."
        )
    if not set(text) <= _HEX:
        raise RefusedError(
            f"Refusing --ref {raw!r}: references are lowercase hexadecimal. This one is not "
            "ours, so nothing would be found under it."
        )
    return text


def _payme_id(raw: str) -> str:
    """Payme's own transaction id. Validated loosely, and the looseness is the point.

    Length only, because this is a THIRD PARTY's identifier: the ids we have seen are 24
    lowercase hex characters, but a recovery tool that enforced that and was wrong would refuse
    to look up the one transaction somebody is trying to find. The column's width is the only
    hard bound — anything longer could never have been stored, so it cannot be found.
    """
    text = raw.strip()
    if not text or len(text) > PAYME_TRANSACTION_ID_LENGTH:
        raise RefusedError(
            f"Refusing --payme-id {raw!r}: at most {PAYME_TRANSACTION_ID_LENGTH} characters, "
            "which is the width the rail's id is stored at."
        )
    if any(character.isspace() for character in text):
        raise RefusedError(f"Refusing --payme-id {raw!r}: it contains whitespace.")
    return text


def _note(raw: str) -> str:
    """Why the operator is settling by hand. Mandatory, and non-empty is part of mandatory.

    ``argparse`` makes ``--note`` required; this makes ``--note ""`` required to mean something.
    The note is the ONLY record of why a sale exists that the rail never confirmed, it is read
    months later by whoever is reconciling, and a blank one turns an auditable correction into
    an unexplained credit. It is not length-refused: the ledger truncates to the column's width
    on purpose, because losing the tail of a note typed under pressure is better than losing the
    settlement to a validation error.
    """
    text = raw.strip()
    if not text:
        raise RefusedError(
            "Refusing an empty --note: a hand-settled sale with no reason recorded is an "
            "unexplained credit. Say what happened and on whose evidence."
        )
    if len(text) > _MAX_NOTE:
        raise RefusedError(f"Refusing --note: at most {_MAX_NOTE} characters.")
    return text


def _instant(raw: str, flag: str) -> datetime:
    """An ISO-8601 instant, made timezone-aware. A naive value is read as UTC.

    Naive input is ACCEPTED rather than refused because an operator during an incident types
    ``2026-09-09T14:00`` and a tool that answered with a usage error would be spending their
    attention on its own pedantry. It is then stamped UTC — the timezone every clock in this
    system is stored in — and the assumption is printed back, so a reader of the output can see
    which window was actually queried.
    """
    text = raw.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RefusedError(f"Refusing {flag} {raw!r}: {_ISO_HINT}") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _bounded(raw: str, flag: str, *, low: int, high: int) -> int:
    """A whole number in range, refused rather than coerced.

    Taken as text and validated instead of handed to ``argparse``'s ``type=int``, which accepts
    ``-1`` and ``0x10`` and turns a typo into a traceback rather than a sentence — the same
    judgement :mod:`bayram.tools.credits` makes about a Telegram id.
    """
    text = str(raw).strip()
    if not text.isdigit() or not low <= int(text) <= high:
        raise RefusedError(f"Refusing {flag} {raw!r}: a whole number from {low} to {high}.")
    return int(text)


# ---------------------------------------------------------------------------
# Doing it. One coroutine per subcommand, dispatched from `apply`.
# ---------------------------------------------------------------------------
async def apply(console: OperatorConsole, request: Request) -> Report:
    """Perform the request and hand back what to print and what to exit with.

    Takes the console rather than a session, matching :func:`bayram.tools.credits.apply`: every
    guarantee the ledger port makes — one transaction per call, idempotent on the key, never
    raises — is a guarantee this tool inherits instead of re-implementing.
    """
    if isinstance(request, Journal):
        return await _journal(console, request)
    if isinstance(request, Statement):
        return await _statement(console, request)
    if isinstance(request, Settle):
        return await _settle(console, request)
    if isinstance(request, Notify):
        return await _notify(console, request)
    if isinstance(request, Pause):
        return await _pause(console, request)
    if isinstance(request, Status):
        return await _status(console, request)
    if isinstance(request, Invariant):
        return await _invariant(console, request)
    return await _reconcile(console, request)


async def _journal(console: OperatorConsole, request: Journal) -> Report:
    """The dossier, or the recent list. The "what happened to this payment" answer."""
    if request.since is not None:
        return await _recent(console, since=request.since, limit=request.limit)
    public_ref = request.public_ref
    if public_ref is None:
        # ``_collect`` fills exactly one selector — argparse's mutually exclusive group is
        # ``required=True`` — so this branch has an id by construction.
        rail_id = request.payme_transaction_id or ""
        public_ref = _unwrap(await _ref_behind(console, payme_transaction_id=rail_id))
        if public_ref is None:
            raise RefusedError(
                f"No transaction {rail_id!r} has ever been created here. "
                "Either the id is mistyped, or Payme never reached this endpoint about it — "
                "which is itself the answer, and `status` will show whether it reached us at "
                "all."
            )
    lines = _unwrap(await _dossier(console, public_ref=public_ref))
    if lines is None:
        raise RefusedError(f"No intent exists under reference {public_ref!r}.")
    return Report(tuple(lines))


async def _statement(console: OperatorConsole, request: Statement) -> Report:
    """Exactly what ``GetStatement`` would answer, so a human can diff it against the cabinet."""
    rows = _unwrap(await console.ledger.statement(frm=request.frm, to=request.to))
    lines = [
        f"GetStatement {_moment(request.frm)} .. {_moment(request.to)}  (inclusive, "
        f"sorted by Payme's own clock)",
        f"{len(rows)} transaction(s).",
    ]
    lines.extend(_statement_line(row, account_field=console.account_field) for row in rows)
    return Report(tuple(lines))


async def _settle(console: OperatorConsole, request: Settle) -> Report:
    """**The recovery button.** Prints the intent it is about to settle, then settles it.

    The pre-read is not decoration. This command writes a receipt and a credit for money the
    rail never confirmed, on an operator's judgement, and the output is the only record of what
    that judgement was made against — so the intent's state, amount, product and buyer go on the
    terminal beside the settlement, where they end up in the incident's scrollback.

    An intent that is ALREADY PAID short-circuits without a write and says so, including who
    settled it and when: an operator pressing this twice needs to learn that the first press
    worked, not to have a second note written over the first.
    """
    before = _unwrap(await console.ledger.intent(public_ref=request.public_ref))
    if before is None:
        raise RefusedError(f"No intent exists under reference {request.public_ref!r}.")
    lines = ["About to settle by hand:", *_intent_lines(before)]
    if before.state is PaymentIntentState.PAID:
        lines.append(
            f"Nothing written: this intent is already paid (settled {_moment(before.settled_at)}). "
            "The first settlement stands, with its original note."
        )
        return Report(tuple(lines))

    now = console.clock()
    settled = _unwrap(
        await console.ledger.force_settle(public_ref=request.public_ref, now=now, note=request.note)
    )
    _LOG.info(
        "an operator settled a payment intent by hand",
        extra={"public_ref": request.public_ref, "note": request.note},
    )
    lines.append("")
    lines.append("Settled. The sale was written under the intent's own idempotency key, so a")
    lines.append("late genuine PerformTransaction will collapse onto the same unique indexes")
    lines.append("and grant nothing twice.")
    lines.extend(_intent_lines(settled))
    written = _unwrap(await _dossier(console, public_ref=request.public_ref))
    if written is not None:
        lines.append("")
        lines.extend(written)
    return Report(tuple(lines))


async def _notify(console: OperatorConsole, request: Notify) -> Report:
    """Re-enqueue the announcement. Refuses the three cases where it would do nothing.

    The job is deliberately not run here. This process holds no Telegram token — that is the
    whole reason the gateway is a fourth process — so telling a customer anything is the
    worker's job, and a CLI that sent the message itself would need the one credential this host
    exists to be without.
    """
    intent = _unwrap(await console.ledger.intent(public_ref=request.public_ref))
    if intent is None:
        raise RefusedError(f"No intent exists under reference {request.public_ref!r}.")
    if intent.state is not PaymentIntentState.PAID:
        raise RefusedError(
            f"Refusing to announce {request.public_ref}: it is {intent.state.value}, not paid. "
            "There is nothing to tell the customer yet. Settle it first if the money landed."
        )
    if intent.telegram_user_id is None:
        raise RefusedError(
            f"Refusing to announce {request.public_ref}: the buyer's account has been erased, "
            "so there is nobody left to send it to. The receipt and the credit are untouched."
        )
    if intent.notified_at is not None:
        raise RefusedError(
            f"Refusing to announce {request.public_ref}: it was already announced at "
            f"{_moment(intent.notified_at)}, and the job stops on that stamp — re-enqueuing it "
            "would do nothing. If the customer never saw the message, that is a delivery "
            "problem in the bot, not a queue problem here."
        )
    try:
        await console.notify(request.public_ref)
    except Exception as exc:
        raise RefusedError(
            "The announcement could not be queued, so nothing was sent and nothing was "
            f"changed: {exc!r}. The worker's own sweep re-enqueues unannounced settlements "
            "every few minutes, so this may resolve itself once Redis is reachable."
        ) from exc
    return Report(
        (
            f"Queued the settled-payment announcement for {request.public_ref}.",
            "The worker sends it; this process holds no Telegram token.",
        )
    )


async def _pause(console: OperatorConsole, request: Pause) -> Report:
    """Flip the switch that stops NEW checkouts. It never refuses a payment in flight."""
    await set_paused(console.switch, paused=request.paused)
    if request.paused:
        return Report(
            (
                "The checkout rail is PAUSED. The bot will stop handing out new payment links.",
                "Payments already in flight are unaffected and will still settle: refusing "
                "money a customer's bank has already moved is how an incident becomes a "
                "dispute.",
                "The switch lives in Redis with no expiry. A Redis restart or eviction "
                "silently un-pauses it — re-check with `status` after either.",
            )
        )
    return Report(("The checkout rail is OPEN. New payment links will be handed out again.",))


async def _status(console: OperatorConsole, request: Status) -> Report:
    """The one screen an operator opens first: is it on, did it hear from Payme, what happened.

    The abandoned/expired distinction is computed here as a READ-TIME predicate rather than
    stored: an ``expired`` intent that never held a transaction is a customer who never reached
    the payment form, which is a funnel problem; one that DID hold a transaction is a payment
    that started and did not finish, which is a rail problem. Two very different incidents that
    would otherwise look identical. As a predicate it needs no column, no migration and no
    backfill, and it cannot drift out of step with the rows it describes.
    """
    now = console.clock()
    since = now - timedelta(hours=request.hours)
    paused = await is_paused(console.switch)
    counts = _unwrap(await _funnel(console, since=since))
    lines = [
        f"Rail:        {'PAUSED' if paused else 'open'} for new checkouts"
        + ("" if paused else "  (the pause switch is not set)"),
        f"Configured:  merchant {console.merchant_id or '(unset)'}, "
        f"{'SANDBOX' if console.is_sandbox else 'production'}, "
        f"endpoint {'enabled' if console.is_enabled else 'DISABLED'}",
        f"Now:         {_moment(now)}   window: last {request.hours}h from {_moment(since)}",
        "",
        f"Last inbound call: {counts.last_call}",
        f"Inbound calls in window: {counts.rpc_calls}"
        + (f" ({counts.rpc_faults} answered with an error)" if counts.rpc_calls else ""),
        "",
        "Intents opened in window:",
    ]
    lines.extend(f"  {name:<28} {value}" for name, value in counts.intent_lines())
    lines.append("")
    lines.append("Rail-side transactions in window:")
    lines.extend(f"  {name:<28} {value}" for name, value in counts.transaction_lines())
    if paused:
        lines.append("")
        lines.append("Remember: `resume` is what turns sales back on. Nothing else does.")
    return Report(tuple(lines))


async def _invariant(console: OperatorConsole, request: Invariant) -> Report:
    """The three-way settlement count, and the fourth number without which it lies.

    ``settlement_counts`` counts performed transactions on Payme's clock and receipts under the
    keys of intents settled in the window. Those are the same instant for a rail settlement, so
    the identity ``performed == receipts`` holds exactly — **but a force-settled intent has no
    performed transaction at all**, so an honest report has to count operator settlements
    separately and state the identity as ``performed + operator == receipts``. Reporting the
    three raw numbers alone would make every use of the recovery button look like a defect,
    which is how a monitoring alert gets muted.

    ``grants`` is the single-song SUBSET: a plan sale writes a receipt and no credit at
    purchase, so ``grants <= receipts`` is expected and only ``grants > receipts`` is wrong.
    """
    now = console.clock()
    frm = now - timedelta(hours=request.hours)
    counts = _unwrap(await console.ledger.settlement_counts(frm=frm, to=now))
    by_operator = _unwrap(await _operator_settlements(console, frm=frm, to=now))
    expected = counts.transactions_performed + by_operator
    balanced = expected == counts.receipts_written and counts.grants_written <= expected
    lines = [
        f"Settlement invariant over the last {request.hours}h ({_moment(frm)} .. {_moment(now)}):",
        f"  performed transactions   {counts.transactions_performed}",
        f"  settled by an operator   {by_operator}",
        f"  receipts written         {counts.receipts_written}",
        f"  credit grants written    {counts.grants_written}   "
        "(the single-song subset; a plan sale grants nothing at purchase)",
    ]
    if balanced:
        lines.append("Balanced.")
        return Report(tuple(lines))
    lines.append(
        f"MISMATCH: {counts.transactions_performed} performed + {by_operator} operator "
        f"= {expected}, but {counts.receipts_written} receipt(s) exist."
        if expected != counts.receipts_written
        else f"MISMATCH: {counts.grants_written} grant(s) against {expected} settlement(s)."
    )
    lines.append(
        "This is NOT self-repaired, here or anywhere: `journal --ref` each settlement in the "
        "window and decide by hand. A discrepancy in the shared paid-sale write primitive is "
        "the defect this count exists to catch, and repairing it automatically would hide it."
    )
    _LOG.error(
        "the payme settlement invariant does not balance",
        extra={
            "performed": counts.transactions_performed,
            "operator_settled": by_operator,
            "receipts": counts.receipts_written,
            "grants": counts.grants_written,
            "hours": request.hours,
        },
    )
    return Report(tuple(lines), EXIT_MISMATCH)


async def _reconcile(console: OperatorConsole, request: Reconcile) -> Report:
    """Run the sweep's arms once, now, synchronously. For when the worker is not running.

    The same three arms ``bayram.runtime.payme_jobs.run_payme_sweep`` runs on its cron, in the same
    order, through the same ledger methods — this is not a second implementation, it is the same
    calls made from a terminal. The fourth arm, the invariant, is its own subcommand here
    because an operator wants to read it far more often than they want to move state.

    **Each arm is independent and a failure in one does not stop the others.** Expiring lapsed
    intents and re-enqueuing announcements are unrelated jobs that happen to run together, and
    letting an unreachable Redis stop a state sweep would be the tail wagging the dog. A run
    with any arm in failure exits 3, so this is safe to put in a cron.
    """
    now = console.clock()
    lines = [f"Reconciling at {_moment(now)}, at most {request.limit} rows per arm."]
    faults = 0

    expired, fault = _arm(await console.ledger.expire_lapsed(now=now, limit=request.limit))
    faults += fault
    lines.append(_arm_line("pending intents expired", expired, fault))

    stale, fault = _arm(
        await console.ledger.expire_stale_transactions(now=now, limit=request.limit)
    )
    faults += fault
    lines.append(_arm_line("stale transactions cancelled and released", stale, fault))

    backlog = await console.ledger.pending_notifications(
        older_than=now - timedelta(seconds=NOTIFY_GRACE_S), limit=request.limit
    )
    if is_err(backlog):
        faults += 1
        lines.append(_arm_line("settled payments re-announced", 0, 1))
    else:
        queued = 0
        for intent in backlog.value:
            try:
                await console.notify(intent.public_ref)
            except Exception as exc:
                # One unreachable enqueue must not strand the other hundred and ninety-nine,
                # and this is the arm that exists to compensate for exactly that outage.
                faults += 1
                _LOG.error(
                    "a settled payment could not be re-announced",
                    extra={"public_ref": intent.public_ref, "detail": repr(exc)},
                )
            else:
                queued += 1
        lines.append(_arm_line("settled payments re-announced", queued, 0))
        if len(backlog.value) >= request.limit:
            lines.append(
                "  (the backlog filled the batch; run it again — there may be more waiting)"
            )
    if faults:
        lines.append(f"{faults} arm(s) failed. See the log for the reason; nothing was retried.")
        return Report(tuple(lines), EXIT_MISMATCH)
    return Report(tuple(lines))


def _arm(outcome: Result[int]) -> tuple[int, int]:
    """Unpack one counting arm into ``(rows, faults)``. Never raises.

    Both arms it serves return ``Result[int]`` through ``run_guarded``, so a database failure
    arrives as data rather than as an exception — unpacked in one place so the two arms cannot
    come to disagree about what a failure means.
    """
    if is_err(outcome):
        _LOG.error("a payme reconcile arm failed", extra=dict(outcome.error.to_log_dict()))
        return 0, 1
    return outcome.value, 0


def _arm_line(name: str, rows: int, fault: int) -> str:
    return f"  {name:<44} {'FAILED (see the log)' if fault else rows}"


# ---------------------------------------------------------------------------
# Reads. Diagnostic, cross-table, and the one thing this module does not do
# through a port — see the module docstring for the argument.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Funnel:
    """One window of the rail's activity, already counted. A value so `status` only formats."""

    opened: int
    paid: int
    awaiting: int
    pending: int
    cancelled: int
    abandoned: int
    lapsed_after_a_transaction: int
    created: int
    performed: int
    rail_cancelled: int
    rpc_calls: int
    rpc_faults: int
    last_call: str

    def intent_lines(self) -> tuple[tuple[str, int], ...]:
        return (
            ("opened", self.opened),
            ("paid", self.paid),
            ("awaiting a payment", self.awaiting),
            ("still pending", self.pending),
            ("cancelled", self.cancelled),
            ("expired, never started", self.abandoned),
            ("expired, payment started", self.lapsed_after_a_transaction),
        )

    def transaction_lines(self) -> tuple[tuple[str, int], ...]:
        return (
            ("created", self.created),
            ("performed", self.performed),
            ("cancelled", self.rail_cancelled),
        )


async def _ref_behind(console: OperatorConsole, *, payme_transaction_id: str) -> Result[str | None]:
    """Our reference for one of Payme's ids, or ``Ok(None)``. Two joined reads, one transaction."""

    async def read() -> str | None:
        async with console.sessions() as session:
            intent_id = await session.scalar(
                sa.select(PaymeTransactionRow.intent_id).where(
                    PaymeTransactionRow.payme_transaction_id == payme_transaction_id
                )
            )
            if intent_id is None:
                return None
            found = await session.scalar(
                sa.select(PaymentIntentRow.public_ref).where(PaymentIntentRow.id == intent_id)
            )
            return None if found is None else str(found)

    return await run_guarded(
        "payme.cli.ref_behind", read, payme_transaction_id=payme_transaction_id
    )


async def _dossier(console: OperatorConsole, *, public_ref: str) -> Result[list[str] | None]:
    """Everything this deployment knows about one payment, as printable lines.

    ONE read transaction over six tables, and the reason it is one is that an operator reading
    the output has to be able to trust that the receipt and the transaction they are looking at
    were true at the same instant. Six separate reads during a live settlement would show a
    performed transaction with no receipt and send somebody hunting a defect that does not
    exist.
    """

    async def read() -> list[str] | None:
        async with console.sessions() as session:
            intent = (
                await session.execute(
                    sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == public_ref)
                )
            ).scalar_one_or_none()
            if intent is None:
                return None
            transactions = list(
                (
                    await session.execute(
                        sa.select(PaymeTransactionRow)
                        .where(PaymeTransactionRow.intent_id == intent.id)
                        .order_by(PaymeTransactionRow.payme_time.asc())
                    )
                )
                .scalars()
                .all()
            )
            key = intent.idempotency_key
            topups = list(
                (
                    await session.execute(
                        sa.select(TopupPurchaseRow).where(TopupPurchaseRow.idempotency_key == key)
                    )
                )
                .scalars()
                .all()
            )
            plans = list(
                (
                    await session.execute(
                        sa.select(PlanPurchaseRow).where(PlanPurchaseRow.idempotency_key == key)
                    )
                )
                .scalars()
                .all()
            )
            grants = list(
                (
                    await session.execute(
                        sa.select(CreditLedgerRow)
                        .where(CreditLedgerRow.idempotency_key == key)
                        .order_by(CreditLedgerRow.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            rail_ids = [row.payme_transaction_id for row in transactions]
            calls = list(
                (
                    await session.execute(
                        sa.select(PaymeRpcLogRow)
                        .where(
                            sa.or_(
                                PaymeRpcLogRow.public_ref == public_ref,
                                PaymeRpcLogRow.payme_transaction_id.in_(rail_ids)
                                if rail_ids
                                else sa.false(),
                            )
                        )
                        .order_by(PaymeRpcLogRow.at.asc())
                    )
                )
                .scalars()
                .all()
            )
        return _render_dossier(
            intent=intent,
            transactions=transactions,
            topups=topups,
            plans=plans,
            grants=grants,
            calls=calls,
        )

    return await run_guarded("payme.cli.dossier", read, public_ref=public_ref)


async def _recent(console: OperatorConsole, *, since: datetime, limit: int) -> Report:
    """``journal --since`` — the recent intents, one line each. A list, never a dossier.

    Deliberately not N dossiers: the question this form answers is "which of these is the one
    I am looking for", and six tables per row would bury it.
    """

    async def read() -> list[str]:
        async with console.sessions() as session:
            rows = list(
                (
                    await session.execute(
                        sa.select(PaymentIntentRow)
                        .where(PaymentIntentRow.created_at >= since)
                        .order_by(PaymentIntentRow.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            lines = [f"{len(rows)} intent(s) opened since {_moment(since)}, newest first:"]
            for row in rows:
                lines.append(
                    f"  {row.public_ref}  {_moment(row.created_at)}  "
                    f"{row.state.value:<9}  {row.product.value:<8}  "
                    f"{row.amount_minor} {row.currency}"
                    + (f"  {row.settle_note}" if row.settle_note else "")
                )
            if len(rows) >= limit:
                lines.append("  (the batch is full; narrow --since or raise --limit)")
            return lines

    return Report(tuple(_unwrap(await run_guarded("payme.cli.recent", read, since=since))))


async def _funnel(console: OperatorConsole, *, since: datetime) -> Result[_Funnel]:
    """Count one window. Two grouped counts, one journal probe, one transaction."""

    async def read() -> _Funnel:
        async with console.sessions() as session:
            by_state = {
                str(state): int(total)
                for state, total in (
                    await session.execute(
                        sa.select(PaymentIntentRow.state, sa.func.count())
                        .where(PaymentIntentRow.created_at >= since)
                        .group_by(PaymentIntentRow.state)
                    )
                ).all()
            }
            # The abandoned/expired split, as a predicate. An expired intent with no rail-side
            # transaction is a customer who never reached the payment form.
            held = (
                sa.select(PaymeTransactionRow.intent_id)
                .where(PaymeTransactionRow.intent_id == PaymentIntentRow.id)
                .exists()
            )
            lapsed = await session.scalar(
                sa.select(sa.func.count())
                .select_from(PaymentIntentRow)
                .where(
                    PaymentIntentRow.created_at >= since,
                    PaymentIntentRow.state == StoredIntentState.EXPIRED,
                    held,
                )
            )
            rail = {
                str(state): int(total)
                for state, total in (
                    await session.execute(
                        sa.select(PaymeTransactionRow.state, sa.func.count())
                        .where(PaymeTransactionRow.payme_time >= since)
                        .group_by(PaymeTransactionRow.state)
                    )
                ).all()
            }
            calls = int(
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(PaymeRpcLogRow)
                    .where(PaymeRpcLogRow.at >= since)
                )
                or 0
            )
            faults = int(
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(PaymeRpcLogRow)
                    .where(PaymeRpcLogRow.at >= since, PaymeRpcLogRow.reply_code != 0)
                )
                or 0
            )
            last = (
                await session.execute(
                    sa.select(PaymeRpcLogRow).order_by(PaymeRpcLogRow.at.desc()).limit(1)
                )
            ).scalar_one_or_none()
        expired = by_state.get(StoredIntentState.EXPIRED.value, 0)
        lapsed_count = int(lapsed or 0)
        return _Funnel(
            opened=sum(by_state.values()),
            paid=by_state.get(StoredIntentState.PAID.value, 0),
            awaiting=by_state.get(StoredIntentState.AWAITING.value, 0),
            pending=by_state.get(StoredIntentState.PENDING.value, 0),
            cancelled=by_state.get(StoredIntentState.CANCELLED.value, 0),
            abandoned=expired - lapsed_count,
            lapsed_after_a_transaction=lapsed_count,
            created=rail.get(StoredPaymeState.CREATED.value, 0),
            performed=rail.get(StoredPaymeState.PERFORMED.value, 0),
            rail_cancelled=(
                rail.get(StoredPaymeState.CANCELLED.value, 0)
                + rail.get(StoredPaymeState.CANCELLED_AFTER_PERFORM.value, 0)
            ),
            rpc_calls=calls,
            rpc_faults=faults,
            last_call=(
                "none, ever — Payme has never reached this endpoint"
                if last is None
                else f"{_moment(last.at)}  {last.method}  reply {last.reply_code}  "
                f"from {last.peer_ip or 'an unrecorded address'}"
            ),
        )

    return await run_guarded("payme.cli.funnel", read, since=since)


async def _operator_settlements(
    console: OperatorConsole, *, frm: datetime, to: datetime
) -> Result[int]:
    """How many settlements in the window a HUMAN made. See :func:`_invariant`."""

    async def read() -> int:
        async with console.sessions() as session:
            return int(
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(PaymentIntentRow)
                    .where(
                        PaymentIntentRow.state == StoredIntentState.PAID,
                        PaymentIntentRow.settled_at >= frm,
                        PaymentIntentRow.settled_at <= to,
                        PaymentIntentRow.settle_note.startswith(OPERATOR_SETTLE_PREFIX),
                    )
                )
                or 0
            )

    return await run_guarded("payme.cli.operator_settlements", read, frm=frm, to=to)


# ---------------------------------------------------------------------------
# Rendering. No decisions here — everything below only formats.
# ---------------------------------------------------------------------------
def _moment(value: datetime | None) -> str:
    """One instant, in UTC, to the second. ``None`` reads as a word and never as ``None``."""
    if value is None:
        return "—"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


def _intent_lines(intent: PaymentIntent) -> list[str]:
    """One intent as an operator reads it. The buyer's id is shown: this is a private terminal."""
    return [
        f"  reference   {intent.public_ref}",
        f"  state       {intent.state.value}",
        f"  product     {intent.product.value}"
        + (
            f"  ({intent.plan_songs} songs / {intent.plan_days} days)"
            if intent.plan_songs is not None
            else ""
        ),
        f"  amount      {intent.amount_minor} {intent.currency}  (minor units — tiyin)",
        f"  buyer       {intent.telegram_user_id if intent.telegram_user_id else 'ERASED'}",
        f"  cashbox     {intent.merchant_id}"
        + ("  SANDBOX" if intent.is_sandbox else "  production"),
        f"  language    {intent.language}",
        f"  valid until {_moment(intent.valid_until)}",
        f"  settled     {_moment(intent.settled_at)}",
        f"  announced   {_moment(intent.notified_at)}",
    ]


def _render_dossier(
    *,
    intent: PaymentIntentRow,
    transactions: Sequence[PaymeTransactionRow],
    topups: Sequence[TopupPurchaseRow],
    plans: Sequence[PlanPurchaseRow],
    grants: Sequence[CreditLedgerRow],
    calls: Sequence[PaymeRpcLogRow],
) -> list[str]:
    """The dossier's text. Pure: it reads already-loaded rows and decides nothing."""
    lines = [
        f"Intent {intent.public_ref}",
        f"  state       {intent.state.value}",
        f"  product     {intent.product.value}"
        + (
            f"  ({intent.plan_songs} songs / {intent.plan_days} days)"
            if intent.plan_songs is not None
            else ""
        ),
        f"  amount      {intent.amount_minor} {intent.currency}",
        f"  buyer       {intent.telegram_user_id if intent.telegram_user_id else 'ERASED'}",
        f"  cashbox     {intent.merchant_id}"
        + ("  SANDBOX" if intent.is_sandbox else "  production"),
        f"  opened      {_moment(intent.created_at)}",
        f"  valid until {_moment(intent.valid_until)}",
        f"  settled     {_moment(intent.settled_at)}"
        + (f"  note {intent.settle_note}" if intent.settle_note else ""),
        f"  announced   {_moment(intent.notified_at)}",
        # The key is shown because it is the join between all six tables below, and an operator
        # comparing a receipt against an intent needs to be able to see that they carry the same
        # one. It contains the buyer's Telegram id by construction, which is exactly why it is
        # never sent to Payme and why `public_ref` exists.
        f"  key         {intent.idempotency_key}",
        "",
        f"Rail-side transactions ({len(transactions)}):",
    ]
    if transactions:
        lines.extend(
            f"  {row.payme_transaction_id}  {row.state.value:<23}  "
            f"payme_time {_moment(row.payme_time)}  "
            f"created {_moment(row.create_time)}  performed {_moment(row.perform_time)}  "
            f"cancelled {_moment(row.cancel_time)}"
            + (f"  reason {row.cancel_reason}" if row.cancel_reason is not None else "")
            for row in transactions
        )
    else:
        lines.append("  none — Payme has never opened a transaction against this intent")
    lines.append("")
    lines.append(f"Receipts under this key ({len(topups) + len(plans)}):")
    lines.extend(
        f"  topup   {row.product.value}  {row.credits_granted} credit(s)  "
        f"{row.amount_minor} {row.currency}  via {row.provider}  ref {row.reference}  "
        f"{_moment(row.created_at)}"
        for row in topups
    )
    lines.extend(
        f"  plan    {row.plan.value}  {row.songs_included} song(s)  "
        f"{row.amount_minor} {row.currency}  via {row.provider}  ref {row.reference}  "
        f"ends {_moment(row.plan_ends_at)}"
        for row in plans
    )
    if not topups and not plans:
        lines.append("  none — no sale has been written for this intent")
    lines.append("")
    lines.append(f"Credit ledger rows under this key ({len(grants)}):")
    lines.extend(
        f"  {row.kind.value:<6}  {row.delta:+d}  {row.reason.value}  "
        f"actor {row.actor or '—'}  {_moment(row.created_at)}"
        for row in grants
    )
    if not grants:
        lines.append("  none")
    lines.append("")
    lines.append(f"Inbound RPC calls that mention it ({len(calls)}):")
    lines.extend(
        f"  {_moment(row.at)}  {row.method:<24}  reply {row.reply_code:<7}  "
        f"{row.duration_ms}ms  from {row.peer_ip or 'an unrecorded address'}"
        for row in calls
    )
    if not calls:
        lines.append(
            "  none — Payme has never called this endpoint about it. If the customer says "
            "they paid, the money is in the cabinet and this is a `settle` case."
        )
    return lines


def _statement_line(row: PaymeStatementRow, *, account_field: str) -> str:
    """One statement row, spelled the way the cabinet export spells it.

    ``account_field`` comes from settings rather than from the row because it is the name PAYME
    was told to call our reference by, configured in their cabinet; the row carries only the
    value. Printing them together is what makes this output diffable against an export by eye.
    """
    view = row.transaction
    return (
        f"  {view.payme_transaction_id}  {_moment(view.payme_time)}  "
        f"{view.state.value:<23}  {view.amount_minor}  "
        f"{account_field}={row.account_value}  {row.product.value}  "
        f"ours {view.our_id}"
    )


def _unwrap[T](outcome: Result[T]) -> T:
    """The value, or a refusal carrying the error's operator message and nothing else.

    Every ledger method and every read here returns a ``Result``; this is the single place a
    failure becomes a sentence, so no subcommand grows its own opinion about how to report one
    — and so a ``StorageError``'s context, which carries the DSN, never reaches the terminal.
    """
    if is_err(outcome):
        raise RefusedError(outcome.error.operator_message)
    return outcome.value


# ---------------------------------------------------------------------------
# The process
# ---------------------------------------------------------------------------
async def _run(request: Request) -> Report:
    """Build the gateway's container, do the one thing, and release it on every path.

    ``payme_container`` is the same context manager the ASGI lifespan uses, so this tool holds
    exactly the object graph the running gateway does — the same engine sizing, the same ledger,
    the same clock. A CLI that built its own would be a second composition root and would
    eventually disagree with the first about something that mattered.
    """
    settings = build_payme_settings()
    async with payme_container(settings) as container:
        return await apply(console_for(container), request)


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point. Returns an exit code and never raises.

    Every failure prints one line and nothing else. A traceback here would carry the database
    DSN and, on a configuration error, could carry the merchant key — the two things this
    command must never put on a terminal or into a shell's scrollback.
    """
    configure_logging()
    try:
        request = plan(sys.argv[1:] if argv is None else argv)
    except RefusedError as exc:
        print(str(exc))
        return EXIT_REFUSED
    try:
        report = asyncio.run(_run(request))
    except RefusedError as exc:
        print(str(exc))
        return EXIT_REFUSED
    except BayramError as exc:
        print(exc.operator_message)
        return EXIT_CONFIG
    print(report.text())
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
