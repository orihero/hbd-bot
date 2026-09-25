"""L0: normalisation, the denylist and the youth lexicon (IMAGE_VIDEO_SPEC §6.4).

Everything here is local, deterministic and free, and it runs before any guard is asked:

* :func:`normalise` folds the tricks that get a word past a list — NFKC (full-width letters,
  ligatures), invisible characters (zero-width joiners, soft hyphens, bidi marks), every
  apostrophe variant to ``'`` (so ``oʻldir`` and ``o'ldir`` are one word), Latin/Cyrillic
  **homoglyphs inside one word** (``nаked`` with a Cyrillic ``а``), and digits standing in for
  letters inside a word (``p0rn``). Case is folded last.
* :func:`denylist_hits` is the tripwire: an unmistakable term blocks with **no guard call**.
  It extends the song gate's patterns (``pipeline/moderation.py`` ``LOCAL_DENY_PATTERNS``) with
  uz-Latn, uz-Cyrl and ru terms, officials and public figures, and brands and characters —
  Disney's among them, because a character in a customer's picture is somebody else's
  property. Each entry carries the closed :class:`CategoryCode` it stands for.
* :func:`has_youth_signal` is where the **youth signal** comes from (§6.4): none of the
  guards has a minor category, so our code decides that a request talks about a child. It is
  a signal, not a verdict — "a birthday card for my son" is ordinary — and it only matters
  together with ``sexual``, where it triggers the hard rule (§6.4, §6.7).

The lists are part of the policy: changing them is a :data:`MEDIA_POLICY_VERSION` bump, so
every unpaid quote is screened again under the new words (§2.3.1).

A false positive here costs a pre-payment refusal, not a paid order, which is why the lists
may be broader than the song gate's. They are still narrow: a word that is ordinary in a
family greeting (a common surname, "bola" alone) is a youth signal or nothing, never a block.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from bayram.moderation.contracts import CategoryCode

__all__ = [
    "LexiconHit",
    "PROMPT_MIN_CHARS",
    "PROMPT_MAX_CHARS",
    "PROMPT_MAX_WORDS",
    "NARRATION_MAX_CHARS",
    "normalise",
    "denylist_hits",
    "has_youth_signal",
    "is_within_caps",
]

#: §1.3: a prompt is 3–800 characters. The word cap stops an 800-character run of one-letter
#: words, which is a probe, not a description.
PROMPT_MIN_CHARS: Final[int] = 3
PROMPT_MAX_CHARS: Final[int] = 800
PROMPT_MAX_WORDS: Final[int] = 160
#: ``media_jobs.narration_text`` is varchar(160) (§3.2.2).
NARRATION_MAX_CHARS: Final[int] = 160

#: Every apostrophe a customer's keyboard produces, folded to one.
_APOSTROPHES: Final[str] = "ʻʼ‘’`´′ʹʽ"

#: Cyrillic letters that look like Latin ones, and back. Used only inside a word that mixes
#: the two scripts: the minority script is folded into the majority one.
_CYR_TO_LAT: Final[dict[str, str]] = {
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
}  # fmt: skip
_LAT_TO_CYR: Final[dict[str, str]] = {
    "a": "а", "b": "в", "e": "е", "k": "к", "m": "м", "h": "н", "o": "о", "p": "р",
    "c": "с", "t": "т", "y": "у", "x": "х", "i": "і",
}  # fmt: skip
#: Digits and symbols standing in for letters, inside a word that has letters.
_LEET: Final[dict[str, str]] = {
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s",
}  # fmt: skip
_WORD: Final[re.Pattern[str]] = re.compile(r"[\w'@$]+")


def _is_invisible(character: str) -> bool:
    """Format characters (zero-width, bidi, soft hyphen) and variation selectors."""
    return unicodedata.category(character) == "Cf" or 0xFE00 <= ord(character) <= 0xFE0F


def _script(character: str) -> str | None:
    if "a" <= character <= "z":
        return "latn"
    if "Ѐ" <= character <= "ӿ":
        return "cyrl"
    return None


def _fold_word(word: str) -> str:
    letters = [s for s in (_script(c) for c in word) if s is not None]
    if any(c.isalpha() for c in word):
        word = "".join(_LEET.get(c, c) for c in word)
    if "latn" in letters and "cyrl" in letters:
        latin = letters.count("latn") >= letters.count("cyrl")
        table = _CYR_TO_LAT if latin else _LAT_TO_CYR
        word = "".join(table.get(c, c) for c in word)
    return word


def normalise(text: str) -> str:
    """The form every list is matched against. Idempotent."""
    folded = unicodedata.normalize("NFKC", text)
    folded = "".join(c for c in folded if not _is_invisible(c))
    folded = folded.translate({ord(a): "'" for a in _APOSTROPHES})
    folded = folded.casefold().replace("ё", "е")
    folded = _WORD.sub(lambda match: _fold_word(match.group(0)), folded)
    return " ".join(folded.split())


def _stem(*stems: str) -> str:
    """Any word starting with one of ``stems`` (inflection is suffixal in all four)."""
    return r"(?<![\w'])(?:" + "|".join(re.escape(s) for s in stems) + r")[\w']*"


def _word(*words: str) -> str:
    """Exactly one of ``words`` (a phrase may contain spaces)."""
    return r"(?<![\w'])(?:" + "|".join(re.escape(w) for w in words) + r")(?![\w'])"


def _forms(*patterns: str) -> str:
    """A whole word matching one of ``patterns`` — raw regexes spelling a stem and its closed
    set of endings, for a stem that also opens ordinary words (``trump`` → *trumpet*,
    ``трамп`` → *трамплин*, ``qatl`` → *qatlama*, the layered bread). Written by hand, so
    they are never escaped."""
    return r"(?<![\w'])(?:" + "|".join(patterns) + r")(?![\w'])"


def _compile(parts: Iterable[str]) -> re.Pattern[str]:
    return re.compile("|".join(parts))


#: The denylist, by category. Written in :func:`normalise`'s output form: lower case,
#: ``'`` for every apostrophe, ``е`` for ``ё``.
_DENYLIST: Final[tuple[tuple[CategoryCode, re.Pattern[str]], ...]] = (
    (
        CategoryCode.SEXUAL_MINORS,
        _compile(
            (
                _stem("pedophil", "paedophil", "pedofil", "педофил", "lolicon", "shotacon"),
                _word("child porn", "kiddie porn", "детское порно", "bolalar pornosi", "cp porn"),
            )
        ),
    ),
    (
        CategoryCode.SEXUAL,
        _compile(
            (
                _stem("porn", "порн", "hentai", "хентай", "erotic", "эротич", "эротик"),
                _stem("обнаж", "голая", "голые", "голый", "yalang'och", "ялангоч"),
                _stem("shahvoniy", "шаҳвоний", "nsfw"),
                _word("nude", "nudes", "naked", "sex", "sexy", "xxx", "секс", "seks", "секси"),
                _word("topless", "without clothes", "без одежды", "kiyimsiz", "кийимсиз"),
            )
        ),
    ),
    (
        CategoryCode.VIOLENCE,
        _compile(
            (
                _word("kill", "killing", "murder", "rape", "bomb", "behead", "massacre"),
                _stem("o'ldir", "ўлдир", "убий", "убить", "изнасил", "расстрел", "обезглав"),
                # Not stems: ``zo'rlar`` is "the best ones", ``qatlama`` a layered bread and
                # ``qatlamli tort`` a layer cake.
                _forms(r"zo'rla(?:sh|b|gan|moq|ngan|nish|di|ydi)[\w']*"),
                _forms(r"qatl(?:i|ga|ni|da|dan|ning)?", r"қатл(?:и|га|ни|да|дан|нинг)?"),
            )
        ),
    ),
    (
        CategoryCode.EXTREMISM,
        _compile(
            (
                _word("nazi", "nazis", "jihad", "isis", "hitler", "swastika", "игил", "джихад"),
                _stem("terrorist", "террорист", "terrorchi", "террорчи", "свастик", "нацист"),
                _stem("jihod", "жиҳод", "гитлер"),
            )
        ),
    ),
    (
        CategoryCode.POLITICS_OFFICIALS,
        _compile(
            (
                _stem("mirziyoyev", "mirziyoev", "мирзиёев", "путин", "putin", "zelensk"),
                _stem("зеленск", "erdog'an", "erdogan", "эрдоган"),
                # Not stems: *trumpet*, *трамплин*.
                _forms(r"trump(?:'s)?", r"трамп(?:а|у|ом|е)?", r"donald trump(?:'s)?"),
                _word("biden", "байден", "xi jinping", "си цзиньпин"),
                _word("islom karimov", "islam karimov", "ислом каримов", "ислам каримов"),
            )
        ),
    ),
    (
        CategoryCode.COPYRIGHT_CHARACTER,
        _compile(
            (
                _stem("disney", "дисней", "pixar", "пиксар", "марвел", "pokemon"),
                # Not a stem, and not the bare word: *marvelous*, and "guests marvel at the
                # cake". The brand is caught with its possessive or its nouns; G1's copyright
                # class is the net for the rest.
                _forms(
                    r"marvel's",
                    r"marvel (?:comics|studios|universe|heroes|hero|superheroes"
                    r"|superhero|characters|character|movie|movies|style)",
                ),
                _stem("покемон", "pikachu", "пикачу", "spider-man", "spiderman", "человек-паук"),
                _word("mickey mouse", "микки маус", "minnie mouse", "batman", "бэтмен"),
                _word("superman", "супермен", "harry potter", "гарри поттер", "barbie", "барби"),
                _word("hello kitty", "masha and the bear", "маша и медведь", "masha va ayiq"),
                _word("coca-cola", "coca cola", "кока-кола", "nike", "adidas", "gucci"),
                _word("louis vuitton", "mcdonald's", "mcdonalds"),
            )
        ),
    ),
)

#: The youth lexicon (§6.4 item 1), uz-Latn, uz-Cyrl, ru and en.
_YOUTH: Final[re.Pattern[str]] = _compile(
    (
        # uz-Latn
        _stem("bola", "qizcha", "o'g'ilcha", "o'quvchi", "maktab", "o'smir", "go'dak"),
        _stem("chaqaloq", "voyaga yetmagan", "balog'atga yetmagan"),
        _word("o'g'il bola", "qiz bola", "kichkina qiz", "kichkina bola"),
        # uz-Cyrl
        _stem("бола", "қизча", "ўғилча", "ўқувчи", "мактаб", "ўсмир", "гўдак", "чақалоқ"),
        _word("ўғил бола", "қиз бола", "вояга етмаган"),
        # ru
        _stem("ребен", "ребят", "девочк", "мальчик", "школьн", "подрост", "малолет"),
        _stem("несовершеннолет", "малыш", "младен", "детск", "дошкол"),
        _word("дети", "детей", "детям", "детьми", "детях", "дитя"),
        # en
        _stem("child", "teen", "preteen", "schoolgirl", "schoolboy", "toddler", "infant"),
        _stem("underage", "loli", "shota", "kindergart", "juvenile"),
        _word("kid", "kids", "kiddo", "little girl", "little boy", "young girl", "young boy"),
        _word("minor", "minors", "pupil", "pupils", "baby girl", "baby boy"),
    )
)


@dataclass(frozen=True, slots=True)
class LexiconHit:
    """One denylist match: the category, and the matched text (for the operator's log only —
    never stored, never shown)."""

    category: CategoryCode
    term: str


def denylist_hits(text: str) -> tuple[LexiconHit, ...]:
    """Every category the denylist finds in ``text``, at most one hit each."""
    folded = normalise(text)
    hits: list[LexiconHit] = []
    for category, pattern in _DENYLIST:
        match = pattern.search(folded)
        if match is not None:
            hits.append(LexiconHit(category=category, term=match.group(0)))
    return tuple(hits)


def has_youth_signal(texts: Sequence[str] | str) -> bool:
    """Whether any of ``texts`` talks about a child (§6.4 item 1)."""
    items = (texts,) if isinstance(texts, str) else texts
    return any(_YOUTH.search(normalise(text)) is not None for text in items)


def is_within_caps(prompt: str) -> bool:
    """§1.3 and L0: 3–800 characters, at most :data:`PROMPT_MAX_WORDS` words."""
    stripped = prompt.strip()
    return (
        PROMPT_MIN_CHARS <= len(stripped) <= PROMPT_MAX_CHARS
        and len(stripped.split()) <= PROMPT_MAX_WORDS
    )
