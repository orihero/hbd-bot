"""The name subsystem — the load-bearing module of this product.

No music model on earth accepts IPA, SSML ``<phoneme>``, a lexicon or a stress mark.
Pronunciation control is not a vendor feature we can buy, so we assemble one out of five
parts, each of which lives in its own file here:

1. ``marks``      — every apostrophe a keyboard emits, canonicalised to the right modifier
                    letter (U+02BB in ``oʻ``/``gʻ``, U+02BC for the tutuq belgisi).
2. ``script`` / ``translit`` / ``syllables`` / ``phonetic``
                  — the derivations: Latin <-> Cyrillic both ways, syllable splitting with
                    Uzbek's final-syllable stress, and an English-orthography respelling.
3. ``candidates`` — N ranked spellings per name, **ordered by configuration, not by code**.
4. ``matching``   — the acoustic loop: score an STT transcript of the rendered name chunk
                    against the intended name and re-roll with the next candidate on a miss.
5. ``forms``      — ``DisplayForm`` and ``SubmitForm``: two types, so the perfect spelling a
                    customer reads can never be confused with the distorted spelling we post
                    to a vendor.

Zero network calls, zero provider imports, zero mutation. Pure functions over text.

Typical use::

    resolved = resolve_name(
        typed_text,
        candidate_order=settings.name_candidate_order,
        ui_language=settings.default_ui_language,
    )
    if is_ok(resolved):
        name = resolved.value
        message = f"Kim uchun? {name.display}"          # DISPLAY: perfect ʻ
        first_try = name.candidate_at(0)                 # SUBMIT: whatever the model reads best
"""

from __future__ import annotations

from hbd.names.candidates import build_candidates, derive_submit_form
from hbd.names.forms import DisplayForm, SubmitForm
from hbd.names.marks import (
    APOSTROPHE_VARIANTS,
    MODIFIER_APOSTROPHE,
    TURNED_COMMA,
    canonicalize_marks,
    has_mark,
    normalize_input,
    strip_marks,
    to_ascii_marks,
)
from hbd.names.matching import (
    NameMatch,
    compare_names,
    judge_transcript,
    name_similarity,
    sound_key,
    sound_keys,
)
from hbd.names.phonetic import respell_phonetically
from hbd.names.resolve import MAX_NAME_WORDS, display_form, resolve_name
from hbd.names.script import (
    ScriptProfile,
    detect_script,
    infer_name_language,
    is_russian_cyrillic,
    is_uzbek_cyrillic,
)
from hbd.names.syllables import hyphenate, stress_index, syllabify
from hbd.names.translit import cyrillic_to_latin, latin_to_cyrillic, transliterate

__all__ = [
    # the front door
    "resolve_name",
    "display_form",
    "MAX_NAME_WORDS",
    # display vs submit
    "DisplayForm",
    "SubmitForm",
    # candidates
    "build_candidates",
    "derive_submit_form",
    # verification
    "NameMatch",
    "sound_key",
    "sound_keys",
    "name_similarity",
    "compare_names",
    "judge_transcript",
    # unicode marks
    "TURNED_COMMA",
    "MODIFIER_APOSTROPHE",
    "APOSTROPHE_VARIANTS",
    "canonicalize_marks",
    "strip_marks",
    "to_ascii_marks",
    "normalize_input",
    "has_mark",
    # script and transliteration
    "ScriptProfile",
    "detect_script",
    "is_uzbek_cyrillic",
    "is_russian_cyrillic",
    "infer_name_language",
    "latin_to_cyrillic",
    "cyrillic_to_latin",
    "transliterate",
    # syllables and respelling
    "syllabify",
    "hyphenate",
    "stress_index",
    "respell_phonetically",
]
