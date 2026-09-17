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

from bayram.contracts import Brief, Genre, Language, LyricDraft, Occasion, VoiceDescriptor
from bayram.providers.llm.prompt_loader import language_guide

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

#: One noun phrase per occasion, read straight into "Write ... lyrics for {phrase}." and
#: into the greeting prompt beside it, so each one has to survive both sentences.
#:
#: Every member of the enum appears here and a ``KeyError`` is the only outcome for one
#: that does not — deliberately, rather than a ``.get`` with a bland default: the whole
#: point of widening ``Occasion`` was that "a personal celebration" was being sung over a
#: roast and a get-well song alike.
OCCASION_BRIEFS: Final[dict[Occasion, str]] = {
    Occasion.BIRTHDAY: "a birthday",
    Occasion.LOVE: "a heartfelt declaration of love or gratitude",
    Occasion.SUPPORT: "encouraging someone who is going through a hard time",
    Occasion.PRANK: "an affectionate, funny roast of the recipient",
    Occasion.HOLIDAY: "a holiday celebration",
    Occasion.WEDDING: "a wedding",
    Occasion.ANNIVERSARY: "an anniversary",
    Occasion.KIDS: "a child, so keep the words simple, playful and easy to sing along to",
    Occasion.NO_OCCASION: "no particular occasion at all, just to make someone smile today",
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

_LYRIC_CRAFT_RULES: Final[str] = (
    "How to write it — these are the difference between a song and filler:\n"
    "1. Rhyme the lines within each section, in pairs or alternating. Verse that does not "
    "rhyme is prose with a backing track.\n"
    "2. Keep lines close to the same length inside a section so they sit on a repeating "
    "melody. A line much longer than its neighbours gets rushed or clipped when sung.\n"
    "3. 2 to 6 lines per section, apart from the hook.\n"
    "4. If a chorus appears more than once, repeat its words. A song in which every "
    "section is new text has no chorus.\n"
    "5. Use at least two concrete details from the sender's note — what this person does, "
    "what they are known for, what the people around them would recognise. Those details "
    "are the entire reason this song is not a generic one. If the note is empty, write "
    "warmly and universally rather than inventing facts about a real person.\n"
    "6. Avoid the stock phrases every birthday song already carries: candles and cake, "
    "another year older, may all your wishes come true, a bright road ahead. Reach for "
    "the specific instead of the ceremonial.\n"
    "7. Address the recipient in one consistent register from first line to last. Do not "
    "drift between formal and familiar mid-song.\n"
    "8. Mention no age, no birth year and no date.\n"
    "9. Section labels are English and name the part: intro, verse-1, pre-chorus, chorus, "
    "verse-2, bridge, outro, hook. Every sung line is in the output language.\n"
    "10. No stage directions, no bracketed cues, no emoji, no markup of any kind. Every "
    "line is sung exactly as it is written."
)


def _name_line(brief: Brief) -> str:
    # Only reached when the writer is being asked for a lyric, which never happens for a
    # brief with no recipient: those carry the customer's own approved lyric and the
    # orchestrator short-circuits before any prompt is built.
    recipient = brief.recipient
    if recipient is None:
        return "The song is not addressed to anyone by name."
    return f'The recipient is named "{recipient.display}".'


def _note_line(brief: Brief) -> str:
    if not brief.note.strip():
        return "The sender gave no extra detail; keep the imagery warm and universal."
    return f'The sender said this about them: "{brief.note.strip()}"'


def lyrics_system_prompt(language: Language) -> str:
    """The live lyric prompt. ``language_guide`` carries the orthography and stress rules.

    That guide already existed — correctly written, with U+02BB and U+02BC spelled out as
    non-negotiable — and was reachable only from a writer with no production callers. So
    the rules the product depends on were maintained in a file nothing sent. Injecting it
    here is what puts them in front of the model that actually writes the song; the code
    still canonicalises the result afterwards, because a rule is a request, not a promise.

    ``_LYRIC_CRAFT_RULES`` arrived the same way and for the same reason. Everything this
    prompt said about *writing* was a prohibition — no caps, no profanity, no brands — and
    a model told only what to avoid returns unobjectionable filler, which is what customers
    were getting. The craft rules are folded down from ``prompts/kit_system.txt``, the
    staff-songwriter brief attached to ``providers.llm.writer.write_kit``: fully written,
    fully tested, and called by nothing on the order path. Rather than reroute the pipeline
    to reach it, its lyric half is restated here, where the live call already looks.

    Only the lyric rules cross over. The greeting, respelling and JSON-shape sections of
    that file describe ``KitPlanPayload``, which this path does not parse — ``LyricsPayload``
    reads ``title`` and ``sections`` and nothing else, so the shape sentence in
    ``lyrics_user_prompt`` stays byte-identical.
    """
    return (
        "You are a professional songwriter for a celebration-song service in Uzbekistan. "
        f"You write only in {LANGUAGE_NAMES[language]}.\n\n"
        f"{language_guide(language)}\n\n"
        f"{_LYRIC_SECTION_RULES}\n\n{_LYRIC_CRAFT_RULES}\n\n{_SHARED_RULES}"
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
    """The reviewer's brief. The substance clause targets GLORIFICATION, not mention.

    It used to read "promotes alcohol or drugs", and that wording cost us a real order.
    Order ``1251314e-2138-4d4e-a263-2874a0c08601`` failed at MODERATING five seconds in,
    showing a paying customer 9% and a generic failure, on this note about a friend:
    "Pivo ichishni yqotiradi, logistica kompaniyasida ishlaydi! Uylangan yaqinda farzandli
    bo'lafi". The model answered ``{"is_allowed": false, "reason": "Sender note references
    alcohol consumption ... which promotes alcohol and is not allowed."}`` — it read a bare
    *mention* as promotion, and that reading beat the very next sentence, which allows an
    affectionate note about a friend. A list item outranks a general permission, so the
    permission has to be made specific enough to win.

    Two changes, both aimed at the same failure: the reject item now names the behaviour we
    actually refuse to celebrate (drug use, drunkenness) rather than the noun, and the
    carve-out enumerates the ordinary things an Uzbek birthday note ribs a friend about.
    Ribbing a friend about beer in a birthday message is routine here; refusing it is not a
    safety win, it is lost revenue and a customer who saw a broken product.

    The JSON-verdict sentence is left byte-identical: ``ModerationPayload`` parses what it
    produces, and prompt tuning has no business drifting the contract.
    """
    return (
        "You are a content safety reviewer for a family celebration-song service in "
        "Uzbekistan. Decide whether the submitted material can be turned into a public "
        "birthday song.\n\n"
        "Reject material that is sexual, hateful, harassing, political, religious, "
        "defamatory, threatening, glorifies drug use or drunkenness, targets a public "
        "figure, or impersonates a real artist or brand. A personal, affectionate or "
        "humorous note about a friend or relative is allowed, including light-hearted "
        "references to drinking, food or habits.\n\n"
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
        f'Recipient name: "{"" if brief.recipient is None else brief.recipient.display}"',
        f"Occasion: {brief.occasion.value}",
        f'Sender note: "{brief.note.strip()}"',
    ]
    if brief.approved_lyrics is not None:
        blocks.append(f'Song lyrics: "{brief.approved_lyrics.as_plain_text()}"')
    return "\n".join(blocks)
