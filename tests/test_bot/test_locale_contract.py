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
import unicodedata
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from hbd.bot.callbacks import NavAction
from hbd.bot.keyboards import LANGUAGE_COLUMNS
from hbd.bot.locales import CATALOGUES
from hbd.contracts import Language
from tests.test_bot.test_keyboards import every_keyboard, every_reply_keyboard

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


#: Every label family drawn on a button. All six, not two: a new :class:`Genre` or
#: :class:`Occasion` arrives as a button without anyone editing ``keyboards.py`` — that
#: file's own first rule — so those three families are exactly where an emoji-free label
#: would ship with a green suite. ``language.`` is here for the same reason from the other
#: direction: those four labels are byte-identical in all four catalogues, so a translator
#: correcting one locale would never see them, and until PD-4 they were the only button
#: family in the product with no emoji at all.
BUTTON_LABEL_PREFIXES: Final[tuple[str, ...]] = (
    "button.",
    "menu.",
    "occasion.",
    "genre.",
    "vocal_gender.",
    "language.",
)

#: The only key under a LABEL prefix whose value is a sentence, not a button. It is a
#: message body — the line drawn ABOVE the menu — and ``keyboards.MENU_BUTTON_KEYS``
#: deliberately excludes it, because a customer who types "Что делаем?" must not reach a
#: dispatcher with no button to dispatch to.
#:
#: One entry, and it has to stay one. The wizard's own prompts are spelled
#: ``wizard.occasion.prompt`` / ``wizard.genre.prompt`` / ``wizard.vocal_gender.prompt``,
#: which fall outside the six prefixes entirely: an ``occasion.prompt`` in this set would be
#: an exemption for a key that does not exist, and an exemption nobody can see the effect of
#: is how the rule below stops being enforced.
NOT_A_BUTTON: Final[frozenset[str]] = frozenset({"menu.prompt"})

#: Unicode categories a leading character may NOT have. A label leads with a pictograph, so
#: anything the standard classifies as a letter or a number is a label with no emoji on it.
#: Spelt as the forbidden set rather than as "category is So", because a future label could
#: legitimately lead with a symbol Unicode files under ``Sk``/``Sm``/``Sc`` or with a
#: sequence whose first codepoint is not itself ``So``.
_NOT_AN_EMOJI_CATEGORY: Final[tuple[str, ...]] = ("L", "N", "Z", "C", "P")

#: The two codepoints that GLUE a grapheme cluster together after its base character:
#: U+FE0F, which forces emoji presentation, and U+200D ZERO WIDTH JOINER, which welds two
#: pictographs into one glyph (👨‍👩‍👧 is seven codepoints and one button-sized picture).
_JOINER: Final[str] = "‍"

#: The regional-indicator block. A flag is a PAIR of these and nothing else: 🇺🇿 is
#: U+1F1FA U+1F1FF, and reading only the first half would make 🇺🇿 and 🇺🇦 the same emoji —
#: which is precisely the comparison the duplicate rule below performs.
_REGIONAL_INDICATORS: Final[range] = range(0x1F1E6, 0x1F1FF + 1)

#: Skin-tone modifiers, which attach to the base pictograph the way U+FE0F does.
_SKIN_TONES: Final[range] = range(0x1F3FB, 0x1F3FF + 1)


def _first_grapheme(text: str) -> str:
    """The first user-perceived character of ``text`` — the thing a reader calls "the emoji".

    Written out rather than imported because the standard library segments nothing: there is
    no ``str`` method and no stdlib module that groups codepoints into grapheme clusters, and
    this repository will not take a dependency for one test. It covers the three shapes that
    actually occur on a button here and says so, instead of pretending to implement UAX #29:

    * a base pictograph followed by U+FE0F (``⚙️``, ``✍️``) — half the ``button.*`` family;
    * a flag, which is a PAIR of regional indicators (``🇺🇿``, ``🇷🇺``) — taking one half
      would collapse every flag beginning with 🇺 into one emoji and make the duplicate rule
      below fire on ``language_output`` in a way no reader could explain;
    * a ZWJ sequence or a skin tone, neither of which is on a button today, admitted so that
      the first one somebody adds is measured rather than silently cut in half.

    Anything else returns a single character, which is the correct answer for a label that
    leads with a letter — the case ``test_every_button_label_leads_with_an_emoji`` exists to
    catch.
    """
    if not text:
        return ""
    cluster = [text[0]]
    index = 1
    if ord(text[0]) in _REGIONAL_INDICATORS:
        if index < len(text) and ord(text[index]) in _REGIONAL_INDICATORS:
            cluster.append(text[index])
            index += 1
        return "".join(cluster)
    while index < len(text):
        character = text[index]
        is_glue = (
            character in (EMOJI_SELECTOR, _JOINER)
            or ord(character) in _SKIN_TONES
            or unicodedata.combining(character) != 0
        )
        if not is_glue:
            break
        cluster.append(character)
        index += 1
        if character == _JOINER and index < len(text):
            cluster.append(text[index])
            index += 1
    return "".join(cluster)


@pytest.mark.parametrize("language", list(Language))
def test_every_button_label_leads_with_an_emoji(language: Language) -> None:
    """Every button in this product wears an emoji, and that is a rule, not a habit.

    It reads as one until a family drifts. Three of the six prefixes below are not written
    by hand at all: ``keyboards.py``'s first rule is that a new :class:`Genre` or
    :class:`Occasion` becomes a button the moment its label exists, with no edit to that
    file — so the day somebody adds a tenth genre, the ONE thing standing between a bare
    ``Retro`` on a keyboard full of emoji and a shipped release is this assertion. The other
    three families drift the same way one key at a time: a translator adding
    ``button.to_settings`` to a locale copies the neighbour above it, or does not.

    Measured on the first GRAPHEME rather than the first codepoint, because ``🇺🇿`` is two
    codepoints and ``⚙️`` is two as well; a codepoint test would pass for the wrong reason on
    the first and mis-report the second. The presentation half is checked against
    :data:`TEXT_DEFAULT_EMOJI` rather than re-derived: a leading ``⚙`` with no U+FE0F is a
    monochrome glyph or a tofu box next to a row of coloured ones, which is the defect
    ``test_no_text_default_emoji_is_left_without_its_selector`` was written for, seen on the
    one position where it is most visible.
    """
    # Arrange
    catalogue = CATALOGUES[language]
    labels = {
        key: value
        for key, value in catalogue.items()
        if key.startswith(BUTTON_LABEL_PREFIXES) and key not in NOT_A_BUTTON
    }
    assert labels, "the label scan found nothing; it has stopped testing anything"

    # Act
    bare = {
        key: value
        for key, value in labels.items()
        if unicodedata.category(_first_grapheme(value)[0]).startswith(_NOT_AN_EMOJI_CATEGORY)
    }
    unselected = {
        key: value
        for key, value in labels.items()
        if value[0] in TEXT_DEFAULT_EMOJI and EMOJI_SELECTOR not in _first_grapheme(value)
    }

    # Assert
    assert bare == {}, f"{language.value} draws these buttons with no emoji: {sorted(bare)}"
    assert unselected == {}, (
        f"{language.value} leads these buttons with a text-presentation emoji and no U+FE0F, "
        f"so they render monochrome beside their neighbours: {sorted(unselected)}"
    )


def test_the_only_label_prefixed_key_that_is_not_a_button_is_the_menu_prompt() -> None:
    """Close :data:`NOT_A_BUTTON`, because a skip list is the way the rule above dies.

    The cheapest response to a red ``test_every_button_label_leads_with_an_emoji`` is another
    entry here, and the second entry is the one nobody argues about. So the exemption is
    pinned to its reason: the key must be a MESSAGE BODY, and the only evidence of that which
    does not restate the skip list is that ``keyboards.MENU_BUTTON_KEYS`` — the tuple the menu
    is actually built from and the set its router filters on — does not contain it.

    A key added here that IS on a button therefore fails; a key added to the keyboard that is
    exempted here fails too.
    """
    # Arrange
    from hbd.bot.keyboards import MENU_BUTTON_KEYS

    # Act / Assert — every exemption is a real key, under a label prefix, and on no keyboard
    for key in sorted(NOT_A_BUTTON):
        assert key in CATALOGUES[Language.EN], key
        assert key.startswith(BUTTON_LABEL_PREFIXES), key
        assert key not in MENU_BUTTON_KEYS, key
    assert sorted(NOT_A_BUTTON) == ["menu.prompt"]


def _labels_by_screen(language: Language) -> Iterator[tuple[str, tuple[str, ...]]]:
    """Every keyboard the bot draws, as ``(name, labels)``, across BOTH registers.

    The inline and reply registers are kept apart in ``test_keyboards.py`` because they are
    measured differently; here they are the same population, because a duplicate emoji is a
    fact about what a customer sees on one screen and Telegram does not care which kind of
    markup drew it. Flattening happens here — through the two different attributes — so that
    the test below never has to ask what kind of markup it is holding.
    """
    for name, inline in every_keyboard(language):
        yield name, tuple(button.text for row in inline.inline_keyboard for button in row)
    for name, reply in every_reply_keyboard(language):
        yield name, tuple(button.text for row in reply.keyboard for button in row)


def _is_a_language_picker(name: str) -> bool:
    """The screens where a duplicate leading emoji is deliberate — every language picker.

    COMPUTED from the register's own naming rather than listed, so a fifth language shape
    added to ``every_keyboard`` inherits the carve-out and cannot silently fail the rule
    below; a hand-written set was tried and was wrong in BOTH directions at once, naming an
    entry that does not exist and omitting ``language_onboarding`` — the first screen a
    customer sees, and the one where the two 🇺🇿 actually appear.

    The duplication is a product decision, not an oversight: every button in this product
    carries an emoji, with no exceptions, and both Uzbek options are Uzbek, so both carry
    🇺🇿 and the ENDONYM in its own script (``Oʻzbekcha (lotin)`` versus ``Ўзбекча (кирилл)``)
    is what tells them apart. That is exactly why ``LANGUAGE_COLUMNS`` had to become 1, and
    why the assertion about it lives in this file: measured, the two labels are 20 and 19
    characters, so a two-column row is 39 against a 30-character budget — Telegram would cut
    the endonym mid-word and leave two buttons that really were identical.
    """
    return name.startswith("language_")


@pytest.mark.parametrize("language", list(Language))
def test_no_two_buttons_on_one_screen_lead_with_the_same_emoji(language: Language) -> None:
    """The emoji is the fast half of a label, so two of them on one screen is a mis-tap.

    A customer scanning a keyboard reads the pictographs first and the words second — that is
    what the emoji is FOR — so two buttons wearing the same one are two buttons that look
    identical for the fraction of a second in which a thumb is already moving. On the confirm
    screen the two candidates would be "record it" and "cancel".

    Enforced per screen rather than per catalogue, because the constraint is about what is
    visible at once: ``✅`` on the name step and ``✅`` on the lyrics step is fine and the same
    ``✅`` twice on either is not. Walked in every locale because a keyboard mixes hand-written
    navigation labels with translated enum content, and only a translator can bring the two
    into collision.
    """
    # Arrange / Act
    collisions: dict[str, list[str]] = {}
    for name, labels in _labels_by_screen(language):
        if _is_a_language_picker(name):
            continue
        leading = Counter(_first_grapheme(label) for label in labels)
        for emoji, count in leading.items():
            if count > 1:
                collisions[f"{name}:{emoji}"] = [
                    label for label in labels if _first_grapheme(label) == emoji
                ]

    # Assert
    assert collisions == {}, (
        f"{language.value} draws two buttons with the same leading emoji on one screen: "
        f"{collisions}"
    )


@pytest.mark.parametrize("language", list(Language))
def test_the_carved_out_screens_really_are_the_language_pickers(language: Language) -> None:
    """Close the carve-out from the other side: it must exempt pickers and nothing else.

    ``_is_a_language_picker`` is a string prefix, so the way it goes wrong is a screen named
    ``language_something`` that is not a language picker at all — at which point a duplicate
    emoji anywhere on it stops being measured and nobody finds out. The evidence that a
    screen IS a picker is that every one of its choice buttons carries a ``LanguageCB``.
    """
    # Arrange / Act / Assert
    carved_out = [name for name, _ in every_keyboard(language) if _is_a_language_picker(name)]
    assert carved_out, "the carve-out matches nothing; the rule above is no longer carved"
    for name in carved_out:
        _, markup = next(pair for pair in every_keyboard(language) if pair[0] == name)
        data = [button.callback_data or "" for row in markup.inline_keyboard for button in row]
        assert any(item.startswith("lang:") for item in data), name


def test_the_language_picker_is_one_column() -> None:
    """The carve-out above and the thing that makes it safe, asserted in one place.

    Accepting two 🇺🇿 buttons is only defensible while the endonym beside each is fully
    readable, and at two columns it is not: ``🇺🇿 Oʻzbekcha (lotin)`` is 20 characters and
    ``🇺🇿 Ўзбекча (кирилл)`` is 19, so the row is 39 against ``MAX_ROW_LABEL_CHARS`` of 30 and
    Telegram — which splits a row's width evenly and truncates the overflow — would cut both
    endonyms mid-word. The customer would then be looking at two buttons that are genuinely
    indistinguishable, on the first screen they ever see, with no way to tell which one they
    read.

    So this assertion is not a layout preference. It is the precondition of the exemption,
    and it lives in this file rather than in ``test_keyboards.py`` so that the two cannot
    drift apart: widen the columns and the test that explains WHY the duplicate is allowed
    goes red in the same run.
    """
    # Arrange / Act / Assert
    assert LANGUAGE_COLUMNS == 1
