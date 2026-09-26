#!/usr/bin/env python3
"""G13 mechanical pre-check -- runs BEFORE the human native-speaker review.

Three checks, all free, all offline:

  1. ORTHOGRAPHY  every o'/g' mark in a shipping string must be U+02BB
     MODIFIER LETTER TURNED COMMA. ASCII U+0027, U+2018, U+2019 and U+00B4
     are failures. U+02BC (tutuq belgisi) is allowed only in a hamza word.
  2. SYLLABLES    re-run the repo's own vowel-invariant counter over every
     sung line and report the count against the plan's claimed figure.
  3. PROVENANCE   grep each string against the four research documents and
     classify it corpus-verbatim / adapted / invented.

Exit code is 0 for a clean orthography scan, 1 otherwise. The syllable and
provenance sections are informational -- Variant D is deliberately NOT
13-syllable Barmoq (plan 3.5), so a non-13 count is not by itself a failure.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent

TC = "ʻ"  # MODIFIER LETTER TURNED COMMA -- the correct o'/g' mark
TB = "ʼ"  # MODIFIER LETTER APOSTROPHE -- tutuq belgisi, ma'no / san'at
NBSP = " "

BAD_MARKS = {
    "'": "ASCII APOSTROPHE",
    "‘": "LEFT SINGLE QUOTATION MARK",
    "’": "RIGHT SINGLE QUOTATION MARK",
    "´": "ACUTE ACCENT",
    "`": "GRAVE ACCENT",
}

# --------------------------------------------------------------------------
# the repo's own counter, lifted verbatim from tests/test_peshta_lyrics.py:28
# --------------------------------------------------------------------------


def normalize_uzbek_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ʻ‘`´]", "'", text)
    text = re.sub(r"[ʼ’]", "'", text)
    return text


def count_uzbek_vowels(cluster: str) -> int:
    norm = normalize_uzbek_text(cluster)
    clean = norm.replace("-", "")
    clean = re.sub(r"[oO]'", "Õ", clean)
    clean = re.sub(r"[gG]'", "Ğ", clean)
    return len(re.findall(r"[aeiouõAEIOUÕ]", clean))


# --------------------------------------------------------------------------
# the shipping string set
# --------------------------------------------------------------------------

SUNG = [
    ("L1", "Sovgʻa izlab boshim qotdi...", 8),
    ("L2", "BOTDA! BAYRAM-BOTDA!", 6),
    ("L3", "Isming aytib kuylar bugun, botda Bayram-botda!", 14),
    ("L4", "O mani kuydirding, o mani suydirding!", 12),
    ("L5", "Oʻn besh mingga qoʻshiq tayyor, Bayram-botga kiring!", 14),
]

OTHER = [
    ("title-a", "Bayram Uzbekiston"),
    ("title-b", "Bayram Oʻzbekiston"),
    ("pin-lat-1", "Tugʻilgan kunga eng ajoyib va esda qolarli sovgʻa — uning ismiga atalgan shaxsiy qoʻshiq!"),
    ("pin-lat-2", "1 daqiqada tayyor boʻladi, soʻzlarini oʻqish esa MUTLAQO BEPUL!"),
    ("pin-lat-3", "Hoziroq sinab koʻring: https://t.me/bayram_uzbot?start=ig_peshta"),
    ("pin-lat-4", "(Havola profil bioda ham bor!)"),
]

CORPUS = {"01": "01_character_concepts.md", "02": "02_parody_lyrics.md",
          "03": "03_production_blueprint.md", "CM": "CAMPAIGN_MASTER.md"}


def scan_marks(label: str, s: str) -> list[str]:
    out = []
    for ch, name in BAD_MARKS.items():
        for m in re.finditer(re.escape(ch), s):
            i = m.start()
            ctx = s[max(0, i - 8):i + 9]
            out.append(f"{label}: {name} U+{ord(ch):04X} at index {i} in {ctx!r}")
    return out


_SRC = {k: normalize_uzbek_text(
            (HERE / v).read_text(encoding="utf-8")
        ).lower().replace(NBSP, " ").replace("\u2026", "...")
        for k, v in CORPUS.items()}


def provenance(s: str) -> str:
    """Is this exact string (mark- and ellipsis-insensitive) in the corpus?"""
    needle = normalize_uzbek_text(s).lower().replace(NBSP, " ").replace("\u2026", "...")
    hits = [k for k, text in _SRC.items() if needle and needle in text]
    return "verbatim in " + "+".join(hits) if hits else "NOT FOUND (new for this cut)"


def main() -> int:
    failures: list[str] = []

    print("=" * 72)
    print("1. ORTHOGRAPHY -- U+02BB scan over every shipping string")
    print("=" * 72)

    sp = HERE / "cards" / "strings.txt"
    if not sp.exists():
        print(f"FAIL: {sp} missing -- run make_cards.py first")
        return 1
    raw = sp.read_text(encoding="utf-8")
    card_rows = [r.split("\t") for r in raw.splitlines() if r.strip()]
    for row in card_rows:
        cid, lines = row[0], row[1:]
        for n, ln in enumerate(lines, 1):
            failures.extend(scan_marks(f"cards/strings.txt {cid} L{n}", ln))
    for lid, ln, _ in SUNG:
        failures.extend(scan_marks(f"plan 3.5 {lid}", ln))
    for lid, ln in OTHER:
        failures.extend(scan_marks(f"phase-H {lid}", ln))

    tc = raw.count(TC)
    tb = raw.count(TB)
    nb = raw.count(NBSP)
    print(f"cards/strings.txt: {len(card_rows)} card rows, "
          f"U+02BB x{tc}, U+02BC x{tb}, U+00A0 x{nb}")
    print(f"G14 shape: ascii-apostrophes={raw.count(chr(39))} (must be 0), "
          f"nbsp={nb} (must be >= 1)")
    if nb < 1:
        failures.append(
            "cards/strings.txt: no U+00A0 -- the price separator is a plain "
            "space, so '15 000' can wrap into '15' / '000 so\u02bbm' (7.4 ruling 4)")
    if failures:
        for f in failures:
            print("  FAIL " + f)
    else:
        print("  PASS: no ASCII/curly apostrophe anywhere in the shipping set")

    print()
    print("=" * 72)
    print("2. SYLLABLES -- repo counter (tests/test_peshta_lyrics.py:28)")
    print("=" * 72)
    for lid, ln, claimed in SUNG:
        got = count_uzbek_vowels(ln)
        mark = "ok" if got == claimed else f"MISMATCH (plan says {claimed})"
        bar13 = "  <- not 13" if got != 13 else "  <- 13, Barmoq-conformant"
        print(f"  {lid} = {got:2d}  {mark}{bar13}   {ln}")

    print()
    print("=" * 72)
    print("3. PROVENANCE -- exact-string search over 01 / 02 / 03")
    print("=" * 72)
    for row in card_rows:
        cid = row[0]
        joined = " ".join(row[1:])
        if not joined:
            print(f"  {cid:4s} (no text -- white flash)")
            continue
        print(f"  {cid:4s} whole card : {provenance(joined):30s} {joined!r}")
        if len(row) > 2:
            for n, ln in enumerate(row[1:], 1):
                print(f"       line {n}    : {provenance(ln):30s} {ln!r}")
    for lid, ln, _ in SUNG:
        print(f"  {lid:4s} {provenance(ln):28s} {ln!r}")
    for lid, ln in OTHER:
        print(f"  {lid:9s} {provenance(ln):28s} {ln[:56]!r}")

    print()
    if failures:
        print(f"RESULT: ORTHOGRAPHY FAILED -- {len(failures)} bad mark(s)")
        return 1
    print("RESULT: orthography clean. Syllable + provenance sections are "
          "informational; the human gate G13 is still required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
