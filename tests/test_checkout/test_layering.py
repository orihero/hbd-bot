"""``bayram.checkout`` is a LEAF, and this file is what keeps that true against a helpful edit.

The module's own docstring makes a claim — "it may never import ``bayram.db``" — and the claim
is load-bearing rather than aesthetic. ``bayram.db`` imports ``bayram.checkout`` for ``Purchase``,
``PlanState`` and now :class:`bayram.checkout.PaymentIntent`; a single import in the other
direction is an import cycle that shows up as an ``ImportError`` at composition-root boot
time, on a deployment, with a traceback that names neither module as the culprit. The same
argument that keeps ``bayram.contracts`` free of the entitlement types applies here verbatim.

The rail package is barred for a different and stronger reason. ``bayram.checkout`` is the
VENDOR-NEUTRAL vocabulary two packages share: persistence, which stores an intent, and a rail
adapter, which builds a URL from one. The moment this module can see a rail package, the
shortest path for any future field — an error code, a wire state, a hostname — is into here,
and the shared vocabulary quietly becomes one rail's protocol with a neutral filename. A
second rail would then arrive to find the "neutral" layer already committed to the first.

**The assertion is made statically, over the source, and not by inspecting ``sys.modules``.**
A runtime check passes whenever the forbidden module merely has not been imported YET, so it
is green on a test run that happens to import ``bayram.checkout`` first and red on one that does
not — a test whose verdict depends on collection order is worse than no test. Parsing the file
also catches an import written inside ``if TYPE_CHECKING:``, which is invisible at runtime and
is precisely where somebody reaching for a rail type would put it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import bayram.checkout

#: What this module is allowed to see. Everything ``bayram.checkout``'s docstring names, and
#: nothing else — kept as a closed set rather than a blocklist so that a NEW first-party
#: dependency has to be argued for here, in a file about layering, instead of arriving as a
#: line at the top of a module nobody re-reads.
_PERMITTED_FIRST_PARTY: Final[frozenset[str]] = frozenset(
    {"bayram.contracts", "bayram.entitlements", "bayram.logging"}
)

#: The two that must never appear, spelled out so a failure names the rule it broke.
_FORBIDDEN_PREFIXES: Final[tuple[str, ...]] = ("bayram.db", "bayram.payme")


def _imported_modules() -> set[str]:
    """Every module ``bayram/checkout.py`` imports, including under ``if TYPE_CHECKING``.

    ``ast.walk`` rather than a scan of the module body, so an import nested inside a function
    or a conditional is collected too. A relative import would carry ``node.module is None``;
    this package uses none, and one appearing here would show up as a missing name rather than
    passing silently, because the set below is compared for membership and not for emptiness.
    """
    source = Path(bayram.checkout.__file__).read_text(encoding="utf-8")
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _matching(imported: set[str], prefix: str) -> list[str]:
    """Imports of ``prefix`` itself or of anything under it, sorted so a failure is readable."""
    return sorted(name for name in imported if name == prefix or name.startswith(f"{prefix}."))


def test_the_buying_seam_never_imports_the_persistence_package() -> None:
    # Arrange / Act
    offenders = _matching(_imported_modules(), "bayram.db")

    # Assert — persistence implements this module's protocols from the other direction, the
    # way ``bayram.db.credits.SqlCreditLedger`` implements ``EntitlementStore``. An import here
    # is a cycle, and a cycle in a composition root fails at boot, not in a test.
    assert offenders == [], f"bayram.checkout must never import bayram.db; found {offenders}"


def test_the_buying_seam_never_imports_a_rail_package() -> None:
    # Arrange / Act
    offenders = _matching(_imported_modules(), "bayram.payme")

    # Assert — see the module docstring: this is what stops the neutral vocabulary becoming
    # one rail's protocol under a neutral filename.
    assert offenders == [], f"bayram.checkout must never import a rail package; found {offenders}"


def test_the_buying_seam_imports_only_the_leaves_its_docstring_names() -> None:
    # Arrange / Act
    first_party = {name for name in _imported_modules() if name.split(".")[0] == "bayram"}

    # Assert — the closed set, which subsumes both tests above and is the reason a NEW
    # first-party import cannot arrive quietly. Not forbidden; required to be argued for here,
    # in the file about layering, rather than in an import block nobody re-reads. The two
    # named tests stay because a failure of this one would otherwise report a set difference
    # where the real finding is "the cycle is back".
    assert first_party <= _PERMITTED_FIRST_PARTY, (
        "bayram.checkout grew a first-party dependency its docstring does not name: "
        f"{sorted(first_party - _PERMITTED_FIRST_PARTY)}"
    )
    assert not first_party & set(_FORBIDDEN_PREFIXES)


def test_the_forbidden_packages_still_exist_under_the_names_this_file_checks() -> None:
    # Arrange / Act — a guard on the guard. A prefix check against a package that has been
    # renamed passes forever and proves nothing, which is the standard way a layering test
    # dies without going red. ``bayram.db`` is on disk today; ``bayram.payme`` is not yet, so it is
    # asserted CONDITIONALLY — the check must be in place before the package it bars lands,
    # and must start biting the moment it does.
    packages = Path(bayram.checkout.__file__).parent

    # Assert
    assert (packages / "db").is_dir(), "bayram.db has moved; the prefix above now matches nothing"
    for prefix in _FORBIDDEN_PREFIXES:
        assert prefix.startswith("bayram."), prefix
