"""``python -m hbd.tools.credits grant|block`` — the only operator write surface there is.

Somebody's song failed in a way the refund path could not see, or somebody is farming the
free allowance from a script. Until a Phase 5 admin route exists, the alternative to this
file is an operator typing ``UPDATE credit_accounts SET balance = balance + 1`` into
``psql``, which is worse in three specific ways: it moves the balance without writing the
ledger row that explains it (``verify_balances`` would then report the account as drifted
forever), it is not idempotent under a retry, and it records nobody as having done it.

So the rule this module is built on: **it writes through the same functions the product
does, and never its own SQL.** ``grant`` goes through
:meth:`hbd.entitlements.EntitlementStore.grant`, ``block`` through ``set_blocked``. Both
are the exact calls the render gate and the inbound gate make, so the CLI cannot produce a
row shape the ordinary path could not, and a change to the entitlement policy reaches this
tool with no edit at all.

**Idempotency belongs to the operator.** A grant is keyed on ``grant:admin:{reference}``
and the reference is printed on success, so a run that timed out somewhere between the
statement and the terminal can be repeated verbatim with ``--reference`` and top the
account up exactly once. Without one, a fresh ``uuid4`` is minted — safe for a first run,
and deliberately NOT safe to repeat blindly, which is why the reference is printed rather
than kept quiet.

**Who did it is recorded where the schema can hold it.** ``--actor`` becomes
``admin:{name}`` in ``credit_ledger.actor``, which is a real column on a real row an
auditor can read months later. A BLOCK has nowhere equivalent to go — ``users`` carries no
actor column and ``docs/product/ADMIN_PANEL_PLAN.md`` §5.11 forbids DDL on it — so for that verb
the actor is written to the process log and nothing pretends otherwise. That is stated in
``--help`` too, because an operator should not have to read this docstring to find out
which of their two actions is attributable.

**A malformed id is refused, not coerced.** ``--telegram-user-id`` is taken as text and
validated, because ``argparse``'s ``type=int`` accepts ``-1`` and ``0x10`` and turns a typo
into a traceback rather than a sentence. Granting credits to the wrong account is a real
cost and the id is the only thing in the command that identifies anybody.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import uuid4

from hbd.config import build_settings
from hbd.contracts import Err
from hbd.db import ACTOR_LENGTH, SqlCreditLedger, create_engine, create_session_factory
from hbd.entitlements import EntitlementStore, resolve_entitlement_policy
from hbd.errors import HbdError
from hbd.logging import configure_logging, get_logger

__all__ = [
    "main",
    "plan",
    "apply",
    "Grant",
    "Block",
    "Request",
    "RefusedError",
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_CONFIG",
]

_LOG = get_logger(__name__)

EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 1
EXIT_CONFIG: Final[int] = 2

#: ``admin:`` plus the operator's name, capped by ``credit_ledger.actor``. Imported rather
#: than restated so a widened column cannot leave this refusal rejecting names it would now
#: hold — and so a NARROWED one cannot let this tool write a silently truncated attribution.
_ACTOR_PREFIX: Final[str] = "admin:"
_MAX_ACTOR_NAME: Final[int] = ACTOR_LENGTH - len(_ACTOR_PREFIX)

#: Telegram ids are positive and fit in a signed 64-bit column. Both halves matter: a
#: negative id is a CHAT id (a group), not a person, and granting a group's "account"
#: credits would open a row no gate will ever read.
_MAX_TELEGRAM_USER_ID: Final[int] = 2**63 - 1

#: What may appear in ``--reference``. Deliberately narrow: the value is concatenated into
#: an idempotency key that is also a diagnostic string, and a reference containing a colon
#: could be made to collide with ``grant:period:{id}:{index}`` — i.e. to consume the key a
#: rolling allowance has not been minted under yet, and silently cancel it.
_REFERENCE_CHARS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)
_MAX_REFERENCE_CHARS: Final[int] = 64


class RefusedError(Exception):
    """An operator-facing refusal. Its message is printed; nothing else is.

    An exception rather than a ``Result`` — the one place in this codebase where that is
    the right shape, and the same one :mod:`hbd.admin.bootstrap` uses. There is no caller to
    hand a value back to: :func:`main` is the boundary, and what it owes the operator is one
    sentence and an exit code, never a traceback carrying the DSN.
    """


@dataclass(frozen=True, slots=True)
class Grant:
    """A validated ``grant``. Carries the finished key, so ``apply`` decides nothing."""

    telegram_user_id: int
    credits: int
    actor: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class Block:
    """A validated ``block``. ``is_blocked`` is False for ``--unblock``."""

    telegram_user_id: int
    actor: str
    is_blocked: bool


type Request = Grant | Block


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m hbd.tools.credits",
        description="Grant credits to a Telegram account, or bar it from ordering.",
    )
    sub = parser.add_subparsers(dest="verb", required=True)

    grant = sub.add_parser("grant", help="add credits to one account, idempotently")
    _add_common(grant)
    grant.add_argument("--credits", required=True, help="how many credits to add (at least 1)")
    grant.add_argument(
        "--reference",
        default=None,
        help=(
            "idempotency token; reuse it to retry a run that may already have landed. "
            "A fresh one is minted and printed when this is omitted."
        ),
    )

    block = sub.add_parser("block", help="bar an account from ordering, or lift the bar")
    _add_common(block)
    block.add_argument("--unblock", action="store_true", help="lift the bar instead of setting it")
    return parser.parse_args(argv)


def _add_common(parser: argparse.ArgumentParser) -> None:
    """The two arguments both verbs need, defined once so they cannot describe differently."""
    parser.add_argument("--telegram-user-id", required=True, help="the account to act on")
    parser.add_argument(
        "--actor",
        required=True,
        help=(
            "who is doing this. Recorded in credit_ledger.actor for a grant; for a block "
            "it goes to the process log only, because `users` carries no actor column."
        ),
    )


def _telegram_user_id(raw: str) -> int:
    """A Telegram account id, or a refusal that names what is wrong with the one given."""
    text = raw.strip()
    if not text.isdigit():
        raise RefusedError(
            f"Refusing --telegram-user-id {raw!r}: a Telegram account id is a positive "
            "whole number. A negative id is a chat, not a person."
        )
    value = int(text)
    if value < 1 or value > _MAX_TELEGRAM_USER_ID:
        raise RefusedError(f"Refusing --telegram-user-id {raw!r}: out of range for an account id.")
    return value


def _actor(raw: str) -> str:
    """``admin:{name}``, refused rather than truncated when the name will not fit."""
    name = raw.strip()
    if not name:
        raise RefusedError("--actor must name a person; an empty one records nobody.")
    if len(name) > _MAX_ACTOR_NAME:
        raise RefusedError(
            f"Refusing --actor {raw!r}: at most {_MAX_ACTOR_NAME} characters, or the "
            "attribution would be stored cut in half."
        )
    return f"{_ACTOR_PREFIX}{name}"


def _credits(raw: str) -> int:
    """How many to add. Refused here so the operator reads a sentence, not a constraint name."""
    text = raw.strip()
    if not text.isdigit() or int(text) < 1:
        raise RefusedError(f"Refusing --credits {raw!r}: a grant must add at least 1 credit.")
    return int(text)


def _idempotency_key(reference: str | None) -> str:
    """``grant:admin:{reference}``, minting a reference when the operator gave none."""
    if reference is None:
        return f"grant:admin:{uuid4()}"
    token = reference.strip()
    if not token or len(token) > _MAX_REFERENCE_CHARS:
        raise RefusedError(
            f"Refusing --reference: give 1 to {_MAX_REFERENCE_CHARS} characters, or omit it."
        )
    if not set(token) <= _REFERENCE_CHARS:
        raise RefusedError(
            "Refusing --reference: letters, digits, dash, underscore and dot only. A colon "
            "would let the key collide with an allowance that has not been minted yet."
        )
    return f"grant:admin:{token}"


def plan(argv: Sequence[str]) -> Request:
    """What this command line asks for, fully validated — or a :class:`RefusedError`.

    Separated from :func:`main` so that the deciding half of this tool can be exercised
    without a database and without a process: every refusal below is a judgement about the
    operator's input alone, and none of them should need an engine to be proved.
    """
    return _collect(_parse(argv))


def _collect(args: argparse.Namespace) -> Request:
    """Turn parsed arguments into a validated request. Every refusal happens here."""
    telegram_user_id = _telegram_user_id(str(args.telegram_user_id))
    actor = _actor(str(args.actor))
    if args.verb == "grant":
        return Grant(
            telegram_user_id=telegram_user_id,
            credits=_credits(str(args.credits)),
            actor=actor,
            idempotency_key=_idempotency_key(args.reference),
        )
    return Block(telegram_user_id=telegram_user_id, actor=actor, is_blocked=not bool(args.unblock))


async def apply(store: EntitlementStore, request: Request) -> str:
    """Perform the request against the store and hand back what to print.

    Takes the seam rather than a session so this is the same object the bot and the worker
    hold: every guarantee the store makes — one transaction per call, idempotent on the
    key, never raises — is a guarantee this tool inherits instead of re-implementing.
    """
    if isinstance(request, Grant):
        return await _grant(store, request)
    return await _block(store, request)


async def _grant(store: EntitlementStore, request: Grant) -> str:
    granted = await store.grant(
        telegram_user_id=request.telegram_user_id,
        credits=request.credits,
        idempotency_key=request.idempotency_key,
        actor=request.actor,
    )
    if isinstance(granted, Err):
        raise RefusedError(granted.error.operator_message)
    balance = granted.value
    # The reference is printed on EVERY run, including the one that added nothing because
    # the key had already been used. That is the shape an operator needs: the second run of
    # the same command prints the same balance and the same reference, which is how they
    # can tell a retry that was already applied from a grant that did not happen.
    return (
        f"Account {balance.telegram_user_id}: balance is now {balance.credits}. "
        f"Reference: {request.idempotency_key}"
    )


async def _block(store: EntitlementStore, request: Block) -> str:
    blocked = await store.set_blocked(request.telegram_user_id, is_blocked=request.is_blocked)
    if isinstance(blocked, Err):
        raise RefusedError(blocked.error.operator_message)
    # The only place this actor is recorded. Said plainly in `--help` as well, because an
    # attribution an operator believes is in the database and is not would be worse than
    # none at all.
    _LOG.info(
        "an operator changed an account's block",
        extra={
            "telegram_user_id": request.telegram_user_id,
            "is_blocked": request.is_blocked,
            "actor": request.actor,
        },
    )
    verb = "blocked" if request.is_blocked else "unblocked"
    return (
        f"Account {request.telegram_user_id} is now {verb}. Recorded in the log as {request.actor}."
    )


async def _run(request: Request) -> str:
    """Open the database, do the one write, and release the engine on every path.

    ``require_vendor_secrets=False``: comping a customer must not require the ElevenLabs
    and Gemini keys to be present on the box the operator happens to be on. The engine is
    disposed in a ``finally`` because a refusal is the likeliest outcome of a mistyped
    command and a leaked pool would keep the process from exiting.
    """
    settings = build_settings(require_vendor_secrets=False)
    engine = create_engine(settings.database_url)
    try:
        store = SqlCreditLedger(
            create_session_factory(engine), policy=resolve_entitlement_policy(settings)
        )
        return await apply(store, request)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point. Returns an exit code and never raises.

    Every failure prints one line and nothing else. A traceback here would carry the DSN,
    which is the one thing this command must never put on a terminal or in a scrollback.
    """
    configure_logging()
    try:
        request = plan(sys.argv[1:] if argv is None else argv)
    except RefusedError as exc:
        print(str(exc))
        return EXIT_REFUSED
    try:
        print(asyncio.run(_run(request)))
    except RefusedError as exc:
        print(str(exc))
        return EXIT_REFUSED
    except HbdError as exc:
        print(exc.operator_message)
        return EXIT_CONFIG
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
