"""Operator command-line tools. Run with ``python -m bayram.tools.<name>``.

Not a library. Nothing under ``src/bayram`` imports from here: each module is a process entry
point that an operator with shell and database access runs by hand, and importing one from
the application would give the running product a code path whose only caller is a human.

They exist because the admin panel has authentication and health and nothing else — there
is no write route, no UI and no audit-log requirement satisfied for one — so the choice for
the operations that must be possible today was between a small audited CLI and an operator
typing ``UPDATE`` into ``psql``. The CLI writes through exactly the same idempotent
functions the product uses, which is the whole point: it cannot produce a row shape the
ordinary path could not.
"""

from __future__ import annotations

__all__: list[str] = []
