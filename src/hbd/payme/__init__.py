"""The Payme Merchant API rail: the wire protocol, and later the process that terminates it.

**This package may import ``hbd.contracts``, ``hbd.checkout``, ``hbd.errors`` and
``hbd.logging``. Its wire, domain and port modules may NEVER import ``hbd.db``.** The
direction of that dependency is the whole architecture of this integration and it is worth
stating once, here, rather than discovering it as an import cycle at composition-root boot on
a deployment: persistence implements the ports declared in this package from the OTHER
direction, exactly as ``hbd.db.purchases.SqlPurchaseLedger`` implements
``hbd.checkout.PurchaseFulfiller`` and ``hbd.db.credits.SqlCreditLedger`` implements
``EntitlementStore``. A rail that reached into persistence would be a rail that could not be
tested without a database, and the state machine below is exactly the thing that must be
testable without one.

**Exactly three modules here are allowed past that bar, and all three are doors rather than
rooms:** :mod:`hbd.payme.container` (the composition root — a composition root is defined by
importing everything it wires), :mod:`hbd.payme.app` (which reaches for ``hbd.db.engine.ping``
and nothing else, for its readiness probe) and :mod:`hbd.payme.cli` (the operator tool, whose
cross-table diagnostics have no port and must not be given one on a process facing the public
internet). Every OTHER module here names ``hbd.db`` nowhere in its own source — including
:mod:`hbd.payme.harness`, which reaches persistence only through the container door — and
``tests/test_payme/test_protocol.py`` asserts exactly that, over every module in the package,
by parsing the source rather than by trusting this paragraph. A fourth door has to be argued
here, and in that test, rather than arriving as a line at the top of a module nobody re-reads.

The second bar is narrower and easier to break by accident: **``hbd.payme`` must not import
``hbd.admin``.** They are different processes with different blast radii. The admin app holds
operator sessions and an audit HMAC key; this package's process holds the Payme cashbox key,
an INBOUND VERIFICATION secret whose theft mints credits rather than impersonating us or
spending a vendor balance. Three separate secrets, three separate containers, and the import
graph is what keeps the separation from being merely an intention — ``hbd.admin.app`` derives
its forbidden-environment tuple from a list this deployment widens with the merchant key, so
an admin process that could see this package would be one refactor away from being able to
boot holding it.

**What is in this package and what is deliberately not.** The modules here divide on exactly
one line: whether a thing needs I/O.

* :mod:`hbd.payme.protocol` — the wire vocabulary. Method names, error codes, the two state
  enums, the millisecond clock conversion and the JSON-RPC envelope renderers. No I/O, no
  clock read, no credential.
* :mod:`hbd.payme.errors` — the refusals, as ``HbdError`` subclasses carrying an ``rpc_code``.
  They are ``HbdError`` subclasses SPECIFICALLY so ``hbd.db.guard.run_guarded`` already
  catches them and a refusal travels back to the dispatcher as an ``Err`` rather than as an
  exception crossing a seam.
* :mod:`hbd.payme.auth` — one constant-time comparison and one log-safe accessor.
* :mod:`hbd.payme.link` — the checkout URL, which is CONSTRUCTED and never requested.
* :mod:`hbd.payme.rules` — the pure predicates the persistence-side transaction body calls,
  so that "is this transaction past its window?" is answerable in a unit test with two
  datetimes and an integer rather than against a database.

Everything above is free of credentials by construction, which is why the whole of it can be
built, tested and certified against Payme's published documentation before Payme has handed
over a merchant id or a key. The merchant key is only ever compared against itself, so a
placeholder is a fully functional gateway.

**The rest of the package, which does need I/O, a credential or a composition root.** These
arrived with the process that terminates the protocol, and each is listed here so that
"what is in ``hbd.payme``?" is answerable without an ``ls``:

* :mod:`hbd.payme.ports` — the frozen views and the ``PaymeLedger`` protocol persistence
  implements from the other side. Still no I/O; it is the seam itself.
* :mod:`hbd.payme.settings` — ``PaymeSettings`` and its own ``HBD_PAYME_ENV_FILE``. The one
  module that names the merchant key, and it holds it as a ``SecretStr``.
* :mod:`hbd.payme.service` — the dispatcher: one ``Result`` mapped onto one JSON-RPC envelope,
  one journal row and one log line per inbound call.
* :mod:`hbd.payme.app` — the ASGI application and the rule that every reply on ``/payme`` is
  HTTP 200, including a refusal.
* :mod:`hbd.payme.container` — the composition root. See the three-doors paragraph above.
* :mod:`hbd.payme.provider` — the BOT's half: a ``CheckoutProvider`` whose ``charge`` opens an
  intent and builds a URL, and opens no socket at all. It runs in the bot's process, not this
  one, which is why it may not see ``hbd.db`` either.
* :mod:`hbd.payme.pause` — the operator kill switch for NEW checkouts, read by the provider
  and never consulted on an inbound settlement.
* :mod:`hbd.payme.cli` — ``python -m hbd.payme.cli``: journal, statement, settle, notify,
  pause, resume, status, invariant, reconcile. The recovery surface that ships on day one.
* :mod:`hbd.payme.harness` — ``python -m hbd.payme.harness``: Payme's published sandbox
  scripts as a data table, replayed against a RUNNING gateway on certification day.

**Nothing in this package is reachable in a default deployment.** ``HBD_CHECKOUT_PROVIDER``
ships ``stub`` and ``HBD_PAYME_ENABLED`` ships false, so production behaviour is byte-identical
to today until configuration changes. See ``DECISIONS.md D11`` and ``PAYME_INTEGRATION §1``.
"""

from __future__ import annotations
