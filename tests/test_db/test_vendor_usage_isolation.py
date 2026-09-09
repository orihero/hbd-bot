"""The structural half of "fake-provider rows are excluded", asserted with ``ast``.

``hbd.db.admin.vendor_usage._narrow`` applies ``is_fake IS false`` unless a caller opts in,
and every reporting aggregate in that module is built through it. That is a property of one
file, and a property of one file is only an invariant of the SYSTEM if no second file can
build a ``vendor_usage`` SELECT behind its back.

So this file asserts the import boundary rather than the filter. A reporting query written
in a new ``db/admin/finance.py`` would be one ``_narrow`` cannot reach, and nobody reviewing
that file would necessarily notice the missing predicate — but they cannot write it without
importing ``VendorUsageRow``, and that import fails here.

The allowlist is six modules and each one is on it for a stated reason:

* the model itself, and the registry that re-exports it;
* ``hbd.db.vendor_usage`` — the WRITER, which by definition sees every row including the
  fake ones, because recording a demo run is the whole reason ``is_fake`` exists;
* ``hbd.db.purge`` — the retention sweep, which DELETES by age and must not skip fake rows;
  filtering them there would leak a demo run past its cutoff for ever;
* ``hbd.db.vendor_balances`` — the balance poller's per-song rate measurement, the one
  non-reporting reader, which spells ``is_fake.is_(False)`` itself and is therefore on this
  list by name rather than by accident;
* ``hbd.db.admin.vendor_usage`` — the only module in ``src/`` that reports on the table.

Adding a seventh is a decision, not an accident, and this test is where it gets made.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

#: Every module in ``src/`` allowed to name ``VendorUsageRow``. See the module docstring for
#: the argument behind each entry; a name added here without one is the failure this guards.
ALLOWED_MODULES: Final[frozenset[str]] = frozenset(
    {
        "hbd.db.models.vendor_usage",
        "hbd.db.models.__init__",
        "hbd.db.vendor_usage",
        "hbd.db.purge",
        "hbd.db.vendor_balances",
        "hbd.db.admin.vendor_usage",
    }
)

_ROW: Final[str] = "VendorUsageRow"
_SOURCE_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "src"


def _module_name(path: Path) -> str:
    """``src/hbd/db/purge.py`` → ``hbd.db.purge``; a package file keeps its ``__init__``."""
    return ".".join(path.relative_to(_SOURCE_ROOT).with_suffix("").parts)


def _imports_the_row(path: Path) -> bool:
    """Whether this module IMPORTS the mapped class, read from the syntax tree.

    ``ast`` rather than a substring search, so a docstring that merely mentions the name in
    prose — ``user_activity_snapshot.py`` does exactly that, arguing why its own row has no
    ``updated_at`` the way ``VendorUsageRow`` does not — is not mistaken for a query.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(alias.name == _ROW for alias in node.names):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name.endswith(f".{_ROW}") for alias in node.names
        ):
            return True
    return False


def test_only_the_named_modules_can_build_a_vendor_usage_query() -> None:
    # Arrange — walk the whole of ``src/``, not a hand-listed subset: the module this test
    # exists to catch is by definition one nobody has thought of yet.
    modules = sorted(_SOURCE_ROOT.rglob("*.py"))
    assert modules, "no source modules found; the walk root is wrong"

    # Act
    importers = {_module_name(path) for path in modules if _imports_the_row(path)}

    # Assert — an unexpected importer is a reporting query ``_narrow`` cannot reach, so the
    # message names what to do rather than only what broke.
    assert importers - ALLOWED_MODULES == set(), (
        "a module outside the allowlist imports VendorUsageRow and can therefore build a "
        "SELECT that skipped _narrow's is_fake filter; either route the query through "
        "hbd.db.admin.vendor_usage, or add the module to ALLOWED_MODULES with the reason"
    )


def test_the_allowlist_names_no_module_that_has_since_been_deleted() -> None:
    # Arrange — the other direction, and it matters: an allowlist entry for a module that no
    # longer exists is a permission nobody revoked, silently waiting for a file of that name
    # to be recreated for an unrelated purpose.
    modules = {_module_name(path) for path in _SOURCE_ROOT.rglob("*.py")}

    # Act / Assert
    assert ALLOWED_MODULES - modules == set(), "the allowlist names a module that is gone"
