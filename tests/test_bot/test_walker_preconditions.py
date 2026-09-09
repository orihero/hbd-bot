"""The one precondition the three wizard walkers have, enforced statically.

``walk_to_name`` / ``walk_to_lyrics`` / ``walk_to_confirm`` now drive the REAL onboarding
screens (C1-4 / C2-1, decided one way). That only works against a dispatcher whose ``BotDeps``
carries a profile store: with ``profiles=None`` the fail-open rule treats the caller as already
onboarded, so ``/start`` renders the menu, the walker's ``LanguageCB(slot=UI)`` press matches no
handler at all, and the module fails with "that session expired" — a message that points at the
fallback router and not at the missing store. Every assertion in the file then fails at once,
about the wrong thing, in a file about credits or payments or degradations.

Fourteen modules import a walker and eleven of them build their own ``BotDeps``, so the shared
fixture in ``conftest.py`` is not the whole answer and the rule cannot live in a docstring: a
new test that builds a dispatcher locally is exactly the kind of edit that would reintroduce
the failure, and the only symptom would be a message about session expiry. It is checked here
instead: **a module that imports a walker must pass ``profiles=`` to every ``BotDeps`` it
constructs.**

Modules that import no walker are outside the rule on purpose. ``test_middleware.py`` builds
three ``BotDeps`` and never walks — it drives the middleware chain directly, past every router
— and forcing a store on it would be cargo cult: the rule is about a precondition of the
walkers, not about a house style for constructing dependencies.

Statically, by parsing, rather than dynamically by importing: importing every test module to
inspect it would run every module-level fixture registration and collection side effect in the
suite from inside one test, and a syntax-level rule is answerable at the syntax level. The
scan is the same shape as ``test_locale_contract.py``'s key scan and asserts the same second
half — that it found something — because a scan that silently matches nothing is a test that
has stopped testing anything while staying green for ever.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

#: This directory. Every bot-side test module lives here, flat.
_BOT_TESTS: Final[Path] = Path(__file__).resolve().parent

#: The helpers whose import puts a module under the rule.
#:
#: The three walkers, plus ``complete_onboarding``: a module that drives onboarding directly
#: without going on into the wizard has exactly the same precondition, and ``test_commands.py``
#: composes its own ``walk_to_note`` out of it. Named rather than derived from
#: ``test_wizard_flow`` by ``dir()``, because the rule is about what a module IMPORTS and the
#: import is written by name — a derived list would grow a helper that has no such precondition
#: and start failing modules for a reason that is not this one.
_WALKERS: Final[frozenset[str]] = frozenset(
    {"walk_to_name", "walk_to_lyrics", "walk_to_confirm", "complete_onboarding"}
)

#: The dependency container whose construction the rule is about.
_CONTAINER: Final[str] = "BotDeps"

#: The keyword that must be present on every such construction in a walker-importing module.
_REQUIRED_KEYWORD: Final[str] = "profiles"


def _bot_test_modules() -> list[Path]:
    """Every ``test_*.py`` beside this one.

    Non-recursive and unsorted-then-sorted rather than globbed recursively, matching how
    ``test_app.py`` enumerates the handler package: ``tests/test_bot`` is flat by construction
    and a nested directory appearing here would be a structural change worth noticing rather
    than silently absorbing.
    """
    return sorted(_BOT_TESTS.glob("test_*.py"))


def _imports_a_walker(tree: ast.Module) -> bool:
    """Whether this module imports one of :data:`_WALKERS` by name.

    ``ast.ImportFrom`` only, and that is deliberate: ``import tests.test_bot.test_wizard_flow``
    followed by an attribute access would evade this, and nothing in the suite does it — every
    walker call site is a ``from ... import`` because the walkers are called bare. A module that
    started reaching them through the module object would fall out of the rule silently, which
    is why the failure message below names the rule rather than only the offending line.
    """
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name in _WALKERS for alias in node.names)
        for node in ast.walk(tree)
    )


def _unstored_container_calls(tree: ast.Module) -> list[int]:
    """The line of every ``BotDeps(...)`` in this module built without ``profiles=``.

    A ``**kwargs`` splat counts as satisfying the rule — ``ast.keyword.arg`` is ``None`` for one
    — because the scan cannot see inside a dict and a false accusation is worse than a missed
    one here: the rule exists to catch the omission a person makes while adding a test, not to
    be a type system. No site in the suite constructs the container that way today.
    """
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == _CONTAINER):
            continue
        keywords = {keyword.arg for keyword in node.keywords}
        if _REQUIRED_KEYWORD not in keywords and None not in keywords:
            offenders.append(node.lineno)
    return offenders


def test_every_walker_module_gives_every_dispatcher_a_profile_store() -> None:
    """A dispatcher a walker drives must be able to record who the customer is.

    The failure this prevents, concretely: somebody adds a test to ``test_payment_gate.py``,
    copies the ``BotDeps(...)`` two functions above, drops ``profiles=`` because the test is
    about payments, and the new test fails with ``wizard.expired`` on a screen nobody asked
    for. The next person reads that as a routing regression and goes looking in
    ``handlers/fallback.py``. This test fails instead, with the file and the line.
    """
    # Arrange
    offenders: list[str] = []
    walker_modules = 0
    container_calls = 0

    # Act
    for path in _bot_test_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        is_walker_module = _imports_a_walker(tree)
        walker_modules += int(is_walker_module)
        unstored = _unstored_container_calls(tree)
        container_calls += sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == _CONTAINER
            for node in ast.walk(tree)
        )
        if is_walker_module:
            offenders.extend(f"{path.name}:{lineno}" for lineno in unstored)

    # Assert — the rule itself
    assert not offenders, (
        f"these {_CONTAINER}(...) sites are in modules that import a walker and pass no "
        f"{_REQUIRED_KEYWORD}=: {', '.join(offenders)}. A walker drives the real onboarding "
        "screens, so without a store the dispatcher fails open and every assertion in the "
        "module dies on 'that session expired'."
    )

    # Assert — and that the scan is still looking at something. Both halves, because a rename
    # of either the walkers or the container would otherwise leave this test passing for ever
    # while checking nothing at all — the rot ``test_locale_contract.py`` guards against with
    # exactly this shape of assertion.
    assert walker_modules, "no module imports a walker; the walker names have moved"
    assert container_calls, f"no {_CONTAINER}(...) call was found; the container has been renamed"
