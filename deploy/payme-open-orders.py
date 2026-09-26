#!/usr/bin/env python3
"""Open N *pending* payment intents, so Payme can drive their sandbox against real orders.

**Why this exists.** Payme certifies a merchant by calling ``CheckPerformTransaction``,
``CreateTransaction`` and ``PerformTransaction`` against orders that already exist on OUR side,
and their engineer asks for the order ids and the amounts **in tiyin** before the slot starts.
Nothing shipped could produce one. :mod:`payme.harness` opens intents but immediately drives
each to a terminal state — that is the whole point of it — and the bot's own checkout is behind
``CHECKOUT_PROVIDER=stub`` (`09-payme-go-live.md` §6, decided rather than pending). The only
remaining route was ``INSERT INTO payment_intents`` by hand on a production host, next to a
``credit_ledger`` whose ``verify_balances`` invariant a hand-written row is one typo away from
breaking. That is exactly what :mod:`bayram.tools`' standing rule forbids, so this file obeys it
instead: **every write here is ``PaymeLedger.open_intent``**, the same port the bot's provider
calls, so this script cannot produce a row shape the product could not, and a change to the
intent's schema reaches it with no edit. It writes nothing else — no transaction, no receipt, no
grant — because a *pending* order is the entire deliverable.

**Every row carries ``is_sandbox=true``**, whatever the process is configured with, exactly as
the harness does and for the same reason: certification money is not revenue, and excluding it by
construction beats excluding it with a ``WHERE`` clause somebody has to remember to write.

**It works under BOTH package names.** The repository is ``bayram`` and the host is still ``hbd``
(`09-payme-go-live.md` §2, Gate A). This picks whichever is importable rather than hard-coding
one, so the certification slot and the rename cutover need not happen in a particular order —
and so nobody edits a script at the moment they are on a call with Payme.

**THE ORDERS EXPIRE TWELVE HOURS AFTER THIS RUNS.** ``DEFAULT_INTENT_TTL_S`` is ``43_200`` and
the gateway's container deliberately does not thread a setting through to it (opening an intent
is the BOT's port), so there is no knob here to turn. The expiry sweep then flips ``pending`` to
``expired``, and every ``CheckPerformTransaction`` afterwards answers ``-31053`` — a refusal that
reads exactly like a broken merchant to the person testing us. **Open them on the day, and re-run
this if the slot slips.** The printed table states each order's deadline for that reason.

Run it on the host, as the user that can read the gateway's env file:

    sudo -u hbd env HBD_PAYME_ENV_FILE=/etc/hbd/payme.env \\
      /opt/hbd/venv/bin/python payme-open-orders.py --telegram-user-id <your Telegram id>

Exit codes follow :mod:`bayram.payme.cli`: ``0`` did it, ``1`` refused and wrote nothing, ``2``
configuration or database failure and wrote nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import secrets
import sys
from types import ModuleType
from typing import Any, Final

EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 1
EXIT_CONFIG: Final[int] = 2

#: The two names the product has had. Order matters only in the window where both are installed,
#: and there the repository's own name is the right answer.
_PACKAGES: Final[tuple[str, ...]] = ("bayram", "hbd")

#: What the idempotency key of every row this script writes begins with. Deliberately neither the
#: bot's ``topup:{id}:{scope}:{seq}`` nor the harness's ``harness:{run}:{scenario}``: an operator
#: reading the journal months from now must be able to tell an order opened FOR PAYME TO TEST
#: from a customer's real purchase and from a rehearsal, with only the key in front of them.
_KEY_PREFIX: Final[str] = "certify"

#: 7 000 so'm, in tiyin. ``single_song_price_minor``'s shipped value, and the harness's default.
#: Nothing on this path multiplies by 100 — this integer IS what Payme is sent and what the
#: settlement compares their integer against.
_DEFAULT_AMOUNT_MINOR: Final[int] = 700_000

#: What Payme asked for. A count rather than a constant three because the next slot will ask for
#: a different number and editing a script mid-call is how mistakes get made.
_DEFAULT_COUNT: Final[int] = 3

#: A bound, because this writes rows to a production table and a mistyped ``--count`` should be a
#: refusal rather than ten thousand orders nobody will ever reconcile.
_MAX_COUNT: Final[int] = 20

#: The language stamped on the intent. These orders belong to no real customer's chat, so there
#: is no locale to read off an update; ``uz_latn`` is the product's own default and the one the
#: harness stamps.
_LANGUAGE: Final[str] = "uz_latn"


def _resolve_package() -> tuple[str, ModuleType]:
    """Import whichever of the two names is installed, or refuse with a sentence.

    A plain ``ModuleNotFoundError`` traceback here would be the wrong answer twice over: it names
    only the first name tried, and it is a wall of frames at a moment when somebody wants one
    line telling them they are on the wrong host or outside the venv.
    """
    for name in _PACKAGES:
        try:
            return name, importlib.import_module(name)
        except ModuleNotFoundError:
            continue
    raise SystemExit(
        f"none of {', '.join(_PACKAGES)} is importable. Run this with the deployment's own "
        f"interpreter, e.g. /opt/hbd/venv/bin/python"
    )


def _positive_int(raw: str, name: str, *, maximum: int | None = None) -> int:
    """``argparse``'s ``type=int`` accepts ``-1`` and ``0x10``; both are worth refusing here.

    The same guard :mod:`bayram.payme.harness` applies, for the same two reasons: the Telegram id
    is the only argument that identifies a person, and the amount is the only one that is money.
    """
    if not raw.isdigit() or int(raw) <= 0:
        raise SystemExit(f"--{name} must be a positive integer, got {raw!r}")
    value = int(raw)
    if maximum is not None and value > maximum:
        raise SystemExit(f"--{name} must be at most {maximum}, got {value}")
    return value


def _label(raw: str) -> str:
    """A fresh run label, or the operator's own — narrowed to what is readable in a key.

    It lands in ``payment_intents.idempotency_key``, which is the string every replay in this
    system deduplicates on. A ``:`` or a ``;`` would corrupt nothing and would make the key
    unreadable at exactly the moment somebody is reading keys.
    """
    if not raw:
        return secrets.token_hex(4)
    if not raw.isalnum() or len(raw) > 32:
        raise SystemExit(f"--label must be at most 32 letters and digits, got {raw!r}")
    return raw


def _somoni(amount_minor: int) -> str:
    """Tiyin rendered as so'm, thin-space grouped, for the human half of the output only.

    Never fed back into anything. The number that crosses to Payme is the integer.
    """
    return f"{amount_minor // 100:,}".replace(",", " ")


async def _open_orders(
    package: str,
    *,
    count: int,
    telegram_user_id: int,
    amount_minor: int,
    label: str,
) -> tuple[list[Any], Any]:
    """Open ``count`` intents through the ledger port and hand them back with the settings.

    The container is built by the package's own composition root — the same one the gateway boots
    from — so these rows are written by the same ``open_intent``, against the same database, with
    the same clock as the endpoint that will be asked about them.
    """
    checkout = importlib.import_module(f"{package}.checkout")
    contracts = importlib.import_module(f"{package}.contracts")
    container_mod = importlib.import_module(f"{package}.payme.container")
    settings_mod = importlib.import_module(f"{package}.payme.settings")

    settings = settings_mod.build_payme_settings()
    if not settings.payme_merchant_id:
        raise SystemExit(
            f"{package.upper()}_PAYME_MERCHANT_ID is blank in the env file this process read. "
            f"An order opened without a cashbox id is one the settlement refuses with -31055, "
            f"and the checkout link for it carries an empty m= that Payme answers with "
            f"«Поставщик не найден» — a sentence about their system that reads as one about ours."
        )

    opened: list[Any] = []
    async with container_mod.payme_container(settings) as container:
        for index in range(1, count + 1):
            result = await container.ledger.open_intent(
                telegram_user_id=telegram_user_id,
                product=checkout.Product.SINGLE,
                amount_minor=amount_minor,
                currency="UZS",
                idempotency_key=f"{_KEY_PREFIX}:{label}:{index}",
                language=_LANGUAGE,
                merchant_id=settings.payme_merchant_id,
                # Always true, whatever the process is configured with. See the module docstring.
                is_sandbox=True,
            )
            if contracts.is_err(result):
                # Partial success is reported, not swallowed: rows already written are real and
                # the operator needs their references even when the run stopped early.
                _render(package, opened, settings=settings, label=label, partial=True)
                raise SystemExit(f"order {index} of {count} was refused: {result.error!r}")
            opened.append(result.value)
    return opened, settings


def _render(
    package: str,
    intents: list[Any],
    *,
    settings: Any,
    label: str,
    partial: bool = False,
) -> None:
    """The two blocks an operator needs: one to paste to Payme, one to keep.

    Split deliberately. The first is the answer to «айди ва эмаунт тийнда керак болади» and
    nothing else, so it can be forwarded as it stands without an operator editing our internal
    labels out of it under time pressure. The second is what makes the run reconcilable
    afterwards — the idempotency keys, the deadline, and the links.
    """
    if not intents:
        return
    link_mod = importlib.import_module(f"{package}.payme.link")
    contracts = importlib.import_module(f"{package}.contracts")
    base_url = link_mod.resolve_base_url(is_sandbox=True, override=settings.payme_checkout_base_url)
    field = settings.payme_account_field

    print()
    if partial:
        print("PARTIAL RUN — the orders below were written before the refusal.")
        print()
    print(f"--- for Payme ({field} + amount in tiyin) " + "-" * 28)
    print()
    for intent in intents:
        print(f"  {field}={intent.public_ref}   amount={intent.amount_minor}")
    print()
    print(f"  all {len(intents)} are in state `pending`, currency UZS,")
    print(f"  {intents[0].amount_minor} tiyin = {_somoni(intents[0].amount_minor)} so'm each.")
    print()
    print("--- for us " + "-" * 60)
    print()
    print(f"  cashbox      {settings.payme_merchant_id}  (sandbox={settings.payme_is_sandbox})")
    print(f"  label        {label}   keys: {_KEY_PREFIX}:{label}:1..{len(intents)}")
    print(f"  payable until {intents[0].valid_until.isoformat()}  <-- -31053 after this")
    print()
    for intent in intents:
        link = link_mod.build_checkout_link(
            base_url=base_url,
            merchant_id=intent.merchant_id,
            account_field=field,
            public_ref=intent.public_ref,
            amount_minor=intent.amount_minor,
            language=contracts.Language(intent.language),
        )
        print(f"  {intent.public_ref}")
        print(f"    {link}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Open pending payment intents for a Payme certification slot, through the same "
            "ledger port the bot's provider uses. Writes nothing else. Every row is sandbox."
        )
    )
    parser.add_argument(
        "--count",
        default=str(_DEFAULT_COUNT),
        help=f"how many orders to open (default {_DEFAULT_COUNT}, max {_MAX_COUNT})",
    )
    parser.add_argument(
        "--telegram-user-id",
        required=True,
        help=(
            "whose account the credit lands on if Payme actually performs one of these, and who "
            "receives the worker's 'your payment went through' message. Use your own."
        ),
    )
    parser.add_argument(
        "--amount",
        default=str(_DEFAULT_AMOUNT_MINOR),
        help=(
            f"the price in TIYIN (default {_DEFAULT_AMOUNT_MINOR} — "
            f"{_somoni(_DEFAULT_AMOUNT_MINOR)} so'm; nothing here multiplies by 100)"
        ),
    )
    parser.add_argument(
        "--label",
        default="",
        help=(
            f"labels every key this run writes, as {_KEY_PREFIX}:<label>:<n> "
            "(default: a fresh random one). Reuse a label only to re-print a previous run: "
            "open_intent is idempotent on the key and will hand back the SAME orders."
        ),
    )
    args = parser.parse_args(argv)

    count = _positive_int(args.count, "count", maximum=_MAX_COUNT)
    telegram_user_id = _positive_int(args.telegram_user_id, "telegram-user-id")
    amount_minor = _positive_int(args.amount, "amount")
    label = _label(args.label)

    package, _module = _resolve_package()
    errors = importlib.import_module(f"{package}.errors")
    # The base exception was renamed with the package: ``HbdError`` on the host, ``BayramError``
    # in the repository. Resolved by lookup rather than by name so this file needs no edit on
    # either side of the Gate A cutover — the same reason ``_resolve_package`` exists.
    base_error: type[Exception] = getattr(
        errors, "BayramError", getattr(errors, "HbdError", Exception)
    )
    try:
        intents, settings = asyncio.run(
            _open_orders(
                package,
                count=count,
                telegram_user_id=telegram_user_id,
                amount_minor=amount_minor,
                label=label,
            )
        )
    except base_error as exc:
        # One sentence and an exit code. A traceback here would put the database DSN — password
        # included — into a shell's scrollback, which is the reason the operator CLI does the same.
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    _render(package, intents, settings=settings, label=label)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
