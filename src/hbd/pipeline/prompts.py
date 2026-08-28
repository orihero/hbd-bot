"""Prompt construction. Pure string building — no I/O, no model objects.

Kept apart from ``content.py`` so a prompt can be tuned (or A/B'd) without touching the
parse-and-validate boundary, and so every instruction the model receives is readable in
one place.

Two rules appear in every prompt because they are the product:

* the recipient's name is written in the DISPLAY orthography, character for character;
* ALL CAPS is forbidden. In a music model capitals mean LOUDER, not stressed, and Uzbek
  stress already falls on the final syllable without any marking.
"""

from __future__ import annotations

from typing import Final

from hbd.contracts import Brief, Genre, Language, LyricDraft, Occasion, VoiceDescriptor

__all__ = [
    "LANGUAGE_NAMES",
    "GENRE_BRIEFS",
    "OCCASION_BRIEFS",
    "lyrics_system_prompt",
    "lyrics_user_prompt",
    "scripts_system_prompt",
    "scripts_user_prompt",
    "moderation_system_prompt",
    "moderation_user_prompt",
]

LANGUAGE_NAMES: Final[dict[Language, str]] = {
    Language.UZ_LATN: "Uzbek written in the Latin alphabet",
    Language.UZ_CYRL: "Uzbek written in the Cyrillic alphabet",
    Language.RU: "Russian",
    Language.EN: "English",
}

GENRE_BRIEFS: Final[dict[Genre, str]] = {
    Genre.POP: "modern radio pop, bright and hooky",
    Genre.RETRO_ESTRADA: "1980s Soviet-era estrada, warm and nostalgic",
    Genre.HIP_HOP: "friendly hip-hop with a clear rhythmic flow",
    Genre.ROCK: "guitar-driven rock with an anthemic chorus",
    Genre.ACOUSTIC_BALLAD: "intimate acoustic ballad, guitar and voice",
    Genre.DANCE_ELECTRONIC: "upbeat four-on-the-floor dance track",
    Genre.UZBEK_POP: "contemporary Uzbek pop (estrada) with national colour",
    Genre.UZBEK_FOLK: "Uzbek folk idiom with traditional imagery",
    Genre.SHASHMAQOM: "classical shashmaqom phrasing, ornate and ceremonial",
    Genre.JAZZ_LOUNGE: "smooth lounge jazz, swung and relaxed",
}

OCCASION_BRIEFS: Final[dict[Occasion, str]] = {
    Occasion.BIRTHDAY: "a birthday",
    Occasion.ANNIVERSARY: "an anniversary",
    Occasion.CUSTOM: "a personal celebration",
}

_SHARED_RULES: Final[str] = (
    "Rules you must never break:\n"
    "1. Write the recipient's name exactly as given, character for character, including "
    "every apostrophe-like mark. Do not transliterate it, do not respell it, do not "
    "abbreviate it.\n"
    "2. Never use ALL CAPS for emphasis. Capitals are read as loudness, not stress.\n"
    "3. No profanity, no politics, no religion, no romantic or sexual content, no alcohol, "
    "no references to real artists or brands.\n"
    "4. Respond with a single JSON object and nothing else. No prose, no code fences."
)

_LYRIC_SECTION_RULES: Final[str] = (
    "Structure: 4 to 6 sections. Exactly one section must have is_name_hook set to true. "
    "That hook section is short — one or two lines, at most eight seconds when sung — and "
    "the recipient's name must appear in it. It is rendered as its own audio chunk, so it "
    "must make sense on its own."
)


def _name_line(brief: Brief) -> str:
    return f'The recipient is named "{brief.recipient.display}".'


def _note_line(brief: Brief) -> str:
    if not brief.note.strip():
        return "The sender gave no extra detail; keep the imagery warm and universal."
    return f'The sender said this about them: "{brief.note.strip()}"'


def lyrics_system_prompt(language: Language) -> str:
    return (
        "You are a professional songwriter for a celebration-song service in Uzbekistan. "
        f"You write only in {LANGUAGE_NAMES[language]}.\n\n"
        f"{_LYRIC_SECTION_RULES}\n\n{_SHARED_RULES}"
    )


def lyrics_user_prompt(brief: Brief) -> str:
    return (
        f"Write celebration song lyrics for {OCCASION_BRIEFS[brief.occasion]}.\n"
        f"{_name_line(brief)}\n"
        f"{_note_line(brief)}\n"
        f"Musical style: {GENRE_BRIEFS[brief.genre]}.\n"
        f"Language of the lyrics: {LANGUAGE_NAMES[brief.output_language]}.\n\n"
        'Return JSON shaped as {"title": str, "sections": '
        '[{"label": str, "lines": [str], "is_name_hook": bool}]}.'
    )


def scripts_system_prompt(language: Language, count: int) -> str:
    return (
        "You write short spoken greetings performed by distinct characters for a "
        f"celebration service in Uzbekistan. You write only in {LANGUAGE_NAMES[language]}.\n\n"
        f"Write exactly {count} greetings, one per character supplied, each in that "
        "character's own voice and register. Each greeting addresses the recipient "
        "directly, names them at least once, and stands alone.\n\n"
        f"{_SHARED_RULES}"
    )


def _voice_line(voice: VoiceDescriptor) -> str:
    return f'- persona_id "{voice.persona_id}" (voice gender: {voice.gender.value})'


def scripts_user_prompt(
    brief: Brief,
    lyrics: LyricDraft,
    *,
    voices: tuple[VoiceDescriptor, ...],
    target_duration_s: float,
) -> str:
    roster = "\n".join(_voice_line(voice) for voice in voices)
    return (
        f"Write one spoken greeting for {OCCASION_BRIEFS[brief.occasion]}.\n"
        f"{_name_line(brief)}\n"
        f"{_note_line(brief)}\n"
        f'The song written for them is titled "{lyrics.title}".\n'
        f"Each greeting must take about {target_duration_s:.0f} seconds to read aloud.\n"
        f"Characters:\n{roster}\n\n"
        'Return JSON shaped as {"greetings": [{"persona_id": str, "text": str}]}, '
        "using each persona_id above exactly once."
    )


def moderation_system_prompt() -> str:
    return (
        "You are a content safety reviewer for a family celebration-song service in "
        "Uzbekistan. Decide whether the submitted material can be turned into a public "
        "birthday song.\n\n"
        "Reject material that is sexual, hateful, harassing, political, religious, "
        "defamatory, threatening, promotes alcohol or drugs, targets a public figure, or "
        "impersonates a real artist or brand. A personal, affectionate or humorous note "
        "about a friend or relative is allowed.\n\n"
        'Respond with a single JSON object {"is_allowed": bool, "reason": str} and '
        "nothing else."
    )


def moderation_user_prompt(brief: Brief) -> str:
    """The material to judge. The lyric block appears only when there is one to judge.

    A lyric the customer approved in the wizard is user free text that ships as the
    product, so the reviewer must see it. A brief without one is left byte-identical to
    what it was before the preview step existed — the reviewer should not be told about an
    absent lyric, and prompt drift on the common path buys nothing.
    """
    blocks = [
        f'Recipient name: "{brief.recipient.display}"',
        f"Occasion: {brief.occasion.value}",
        f'Sender note: "{brief.note.strip()}"',
    ]
    if brief.approved_lyrics is not None:
        blocks.append(f'Song lyrics: "{brief.approved_lyrics.as_plain_text()}"')
    return "\n".join(blocks)
