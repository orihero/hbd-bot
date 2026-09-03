"""Contracts that hold ACROSS the four catalogues and between the catalogues and the code.

``test_i18n.py`` proves each catalogue has the reference key set and the reference
placeholders. These are the two failures that survive that and only show up in front of a
customer:

* a catalogue uses a tag Telegram does not support. Every message goes out with
  ``parse_mode=HTML``, so an unsupported tag is a 400 *at send time* — the message simply
  never arrives, and only for the locale that has the typo;
* the CODE renders a key no catalogue defines. ``translate`` never raises, by design: it
  logs and returns the key itself, so the customer is shown the literal string
  ``support.no_contact`` and every test still passes. That is exactly how
  ``support.no_contact`` shipped referenced-but-undefined.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from hbd.bot.callbacks import NavAction
from hbd.bot.locales import CATALOGUES
from hbd.contracts import Language

#: Every tag Telegram's Bot API documents for ``parse_mode=HTML``. Anything else is a 400.
#: ``span`` is admitted only as ``<span class="tg-spoiler">``, which is checked separately.
SUPPORTED_TAGS: Final[frozenset[str]] = frozenset(
    {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "ins",
        "s",
        "strike",
        "del",
        "code",
        "pre",
        "a",
        "tg-spoiler",
        "blockquote",
        "tg-emoji",
        "span",
    }
)

_TAG = re.compile(r"<\s*/?\s*([a-zA-Z][a-zA-Z0-9-]*)")
_SPAN = re.compile(r"<\s*span\b[^>]*>")

#: The bot package, which is where every catalogue key is rendered from.
_SOURCE_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "hbd"

#: Packages under :data:`_SOURCE_ROOT` that render no catalogue key and are skipped whole.
#:
#: The admin panel is a JSON API for operators: it imports nothing from ``hbd.bot.locales``,
#: calls ``translate`` nowhere, and has no catalogue of its own — its strings are English
#: constants in an error envelope. It is skipped because :func:`_module_level_key_constants`
#: is a *heuristic* ("a dotted string assigned to a name ending in KEY"), and that heuristic
#: reads a column name as an i18n key: ``RevealField.RECIPIENT_LOOKUP_KEY =
#: "briefs.recipient_lookup_key"`` in ``hbd.admin.schemas.reveal`` is the name of a database
#: column that ``POST /reveal`` audits, and it is neither rendered to a customer nor
#: translatable.
#:
#: Narrowing the *heuristic* instead was measured and rejected: restricting it to genuinely
#: module-level assignments — which is what its name says — drops ten real bot keys that are
#: declared inside a mapping or a class body, including every ``error.*`` one. Skipping a
#: package that provably renders none is the change that loses nothing.
_SKIPPED_PACKAGES: Final[frozenset[str]] = frozenset({"admin"})

#: Functions whose FIRST positional argument is an i18n key.
_KEY_FUNCTIONS: Final[frozenset[str]] = frozenset({"translate"})

#: Keys built at run time from an enum value rather than written out, e.g.
#: ``f"language.{value.value}"``. ``test_i18n`` already walks every enum member of each.
_COMPUTED_PREFIXES: Final[tuple[str, ...]] = (
    "language.",
    "occasion.",
    "genre.",
    "vocal_gender.",
    "progress.",
    "error.",
    "gap.",
)


def _tags(text: str) -> set[str]:
    return {name.lower() for name in _TAG.findall(text)}


@pytest.mark.parametrize("language", list(Language))
def test_every_tag_in_the_catalogue_is_one_telegram_supports(language: Language) -> None:
    # Arrange
    catalogue = CATALOGUES[language]

    # Act
    offenders = {
        key: sorted(_tags(text) - SUPPORTED_TAGS)
        for key, text in catalogue.items()
        if _tags(text) - SUPPORTED_TAGS
    }

    # Assert
    assert offenders == {}


@pytest.mark.parametrize("language", list(Language))
def test_a_span_is_only_ever_the_spoiler_span(language: Language) -> None:
    # Arrange / Act — Telegram accepts <span> for exactly one class and rejects the rest
    offenders = [
        key
        for key, text in CATALOGUES[language].items()
        for opening in _SPAN.findall(text)
        if 'class="tg-spoiler"' not in opening
    ]

    # Assert
    assert offenders == []


@pytest.mark.parametrize("language", list(Language))
def test_every_opening_tag_is_closed(language: Language) -> None:
    """An unbalanced tag is the other 400: Telegram parses the whole message or none of it."""
    # Arrange / Act
    offenders = []
    for key, text in CATALOGUES[language].items():
        depth: list[str] = []
        for match in re.finditer(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)[^>]*>", text):
            closing, name = match.group(1), match.group(2).lower()
            if closing:
                if not depth or depth.pop() != name:
                    offenders.append(key)
                    break
            else:
                depth.append(name)
        else:
            if depth:
                offenders.append(key)

    # Assert
    assert offenders == []


def _literal_keys_rendered_by(path: Path) -> set[str]:
    """Every i18n key this module passes to ``translate`` as a plain string literal."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in _KEY_FUNCTIONS or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
    return found


def _module_level_key_constants(path: Path) -> set[str]:
    """Keys assigned to a module constant, e.g. ``_TOO_LATE_KEY = "wizard.cancel_too_late"``.

    They are rendered through a name rather than a literal at the call site, so the AST
    walk above cannot see them — and a constant is exactly how the handlers that matter
    most (the too-late guard, the progress frames) name their keys.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if "." not in value.value or " " in value.value:
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        if any(isinstance(t, ast.Name) and t.id.upper().endswith("KEY") for t in targets):
            found.add(value.value)
    return found


def test_every_key_the_code_renders_is_defined_in_every_catalogue() -> None:
    """The check that ``support.no_contact`` needed and nothing had.

    ``translate`` degrades a missing key to the key itself and logs an ERROR, so a
    referenced-but-undefined key is invisible to every other test in the suite and fully
    visible to the customer.
    """
    # Arrange
    referenced: set[str] = set()
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        if path.parent.name == "locales":
            continue
        if not _SKIPPED_PACKAGES.isdisjoint(path.relative_to(_SOURCE_ROOT).parts):
            continue
        referenced |= _literal_keys_rendered_by(path)
        referenced |= _module_level_key_constants(path)
    referenced = {
        key for key in referenced if not key.startswith(_COMPUTED_PREFIXES) and "{" not in key
    }
    assert referenced, "the key scan found nothing; it has stopped testing anything"

    # Act / Assert
    for language in Language:
        missing = sorted(referenced - set(CATALOGUES[language]))
        assert missing == [], (language, missing)


def test_the_skipped_packages_really_do_render_no_catalogue_key() -> None:
    """Close :data:`_SKIPPED_PACKAGES`, so the exemption cannot grow into a hole.

    An exemption set is worth nothing unless it is checked: the moment a skipped package
    calls ``translate`` or imports a catalogue, the test above would stop covering it and
    say nothing. So both halves are asserted here — no ``translate`` call, and no import of
    the locales module — and the day either becomes false, this fails and the package has to
    come back into the scan rather than quietly leave it.
    """
    # Arrange
    offenders: dict[str, list[str]] = {}

    # Act
    for package in sorted(_SKIPPED_PACKAGES):
        root = _SOURCE_ROOT / package
        assert root.is_dir(), package
        for path in sorted(root.rglob("*.py")):
            reasons = sorted(_literal_keys_rendered_by(path))
            if "hbd.bot.locales" in path.read_text(encoding="utf-8"):
                reasons.append("imports hbd.bot.locales")
            if reasons:
                offenders[str(path.relative_to(_SOURCE_ROOT))] = reasons

    # Assert
    assert offenders == {}


def _actions_named_inside_register_calls(path: Path) -> set[str]:
    """Every ``NavAction`` member named inside a ``…register(…)`` call in this module.

    The AST rather than a text search, because a member mentioned in a docstring or drawn
    by a keyboard is exactly what this must NOT count as handled.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "register"):
            continue
        segment = ast.get_source_segment(source, node) or ""
        found |= set(re.findall(r"NavAction\.([A-Z_]+)", segment))
    return found


def test_every_nav_action_is_registered_to_a_handler() -> None:
    """A button nothing handles falls through to the stale-callback path and reads as broken.

    ``TRY_AGAIN`` shipped exactly like that: ``lyrics_failed_keyboard`` drew it and no
    router claimed it, so the one retry offered to a customer whose lyric had failed
    answered "that screen has moved on". A registration is a line in some ``build_router``
    that nothing forces anyone to add, so this is the thing that forces it.
    """
    # Arrange
    handlers = _SOURCE_ROOT / "bot" / "handlers"
    registered: set[str] = set()
    for path in sorted(handlers.glob("*.py")):
        registered |= _actions_named_inside_register_calls(path)

    # Act / Assert
    assert sorted({member.name for member in NavAction} - registered) == []


#: Codepoints whose Unicode ``Emoji_Presentation`` is **No**: they render as a flat
#: monochrome glyph — or as tofu — unless followed by U+FE0F VARIATION SELECTOR-16.
#:
#: Four of these shipped bare while their neighbours in the same message carried the
#: selector, so ``privacy.text`` listed ``🎙 The name you gave me`` in text style directly
#: above ``✍️``, ``🎵`` and ``🎬`` in colour, and two frames of the twelve-frame progress
#: bar (``🛡`` moderating, ``🎚`` post-processing) came out monochrome while the other ten
#: did not. Python exposes no ``Emoji_Presentation`` property, so this is the curated set:
#: the four in use plus the near neighbours an editor reaching for a "tool" or "document"
#: glyph is most likely to pick next. Add to it rather than working around it.
TEXT_DEFAULT_EMOJI: Final[frozenset[str]] = frozenset("🎙🎚🎛🛡🗑🗒🗓🗂🖼🖊🖋⏱⏲✉✏✒✂❤⚠⚙↩↪⬅➡⬆⬇ℹ⌨☑▶◀")

#: The selector that forces emoji presentation.
EMOJI_SELECTOR: Final[str] = "️"


@pytest.mark.parametrize("language", list(Language))
def test_no_text_default_emoji_is_left_without_its_selector(language: Language) -> None:
    """Mixed monochrome and colour glyphs in one list read as a rendering bug."""
    # Arrange
    catalogue = CATALOGUES[language]

    # Act
    bare = [
        (key, character)
        for key, template in catalogue.items()
        for index, character in enumerate(template)
        if character in TEXT_DEFAULT_EMOJI and template[index + 1 : index + 2] != EMOJI_SELECTOR
    ]

    # Assert
    assert bare == [], (
        f"{language.value} uses a text-presentation emoji without U+FE0F: "
        + ", ".join(f"{key} → {character!r}" for key, character in bare)
    )
