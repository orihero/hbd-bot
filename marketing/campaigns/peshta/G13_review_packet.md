# G13 — native-speaker review packet

**Gate:** `04_generation_plan.md` §8 G13 · **Phase A step 9** · **blocks Phase B and step 10**
**Reviewer:** you. **Everything below is unbought.** No card is final, no song is rendered.
**Prepared:** 2026-09-18 · mechanical pre-check `marketing/campaigns/peshta/g13_check.py` (run, exit 0)

You are being asked to sign off **every Uzbek string a viewer will see or hear**, as one set.
Answer inline — write **OK**, **FIX: <new string>**, or **CUT** under each item. Ordered worst
risk first; items 1–6 are the ones that can still change the film.

**What the machine already checked, so you don't have to:**

| Check | Result |
|---|---|
| ASCII `'` / curly `'` anywhere in the shipping set | **0 occurrences** — every `oʻ`/`gʻ` is U+02BB |
| U+00A0 in the price (stops `15` / `000` wrapping) | **present, 1 occurrence** (`ATIGI 15<NBSP>000 SOʻM`) |
| Syllable counts vs the plan's claimed figures | **all 5 sung lines match** (8 / 6 / 14 / 12 / 14) |
| Barmoq vazni 13-syllable rule | **does not bind Variant D** — see §0 below |

---

## 0. Two things to know before you read the strings

**Barmoq vazni does not apply here.** Variants A/B/C are 13-syllable verse. Variant D is a
soundbite and scores **8 / 6 / 14 / 12 / 14** — the repo's own test asserts exactly those
figures (`tests/test_peshta_lyrics.py:287`) and it passes. I re-ran the repo's counter over the
final strings and got the same numbers. **Do not "fix" any line to 13 syllables.** Judge these
for singability and naturalness, not for meter.

> ⚠ **Read this before you mark any sung line FIX.** `marketing/campaigns/peshta/audio/variant_d_bed_001.mp3`
> already exists on disk — **30.04 s, real music, mastered to −14.8 dB mean / −0.2 dB peak**,
> written 2026-09-18 12:59, i.e. **before this packet**. §11 step 9 says G13 happens *before the
> song is bought*; it appears a bed was already rendered. Practical consequence for you: the five
> sung lines in §2, §6 and §11 may already be **baked into that audio**. Changing one is not free
> — it needs a re-render at ~$0.075 with a bumped idempotency key (`-002`), and a fresh
> listen-and-approve. **Cards are still free to change; sung lines are not.** Say so explicitly if
> a sung fix is worth the re-render.

**Provenance labels** used below, all verified by exact string search this session:

- **verbatim** — the exact string exists in `01`/`02`/`03`/`CAMPAIGN_MASTER`.
- **assembled** — every fragment exists in the corpus; the *sentence* is new to this cut.
- **new** — does not exist in the corpus in any form. **Highest risk.**

**Coverage of the plan's nine flagged items** — every one is answered somewhere below:

| §8 G13 item | Asked here as |
|---|---|
| 1 `SOAT 23:55. SOVGʻA ESA YOʻQ!` | §8 |
| 2 `UNING ISMIGA ATALGAN QOʻSHIQ!` | §3 |
| 3 `SOʻZLARINI OʻQISH BEPUL!` | §5 |
| 4 Register | §4 (widened — it is a three-way clash, not two-way) |
| 5 `O mani kuydirding…` | §2 |
| 6 `Bayram-botga kiring!` | §6 |
| 7 `Oʻn besh mingga` | §6 |
| 8 Audio-title spelling | §7 |
| 9 Speed claim gone | §9 (it is **not** entirely gone — see there) |
| *(not on the plan's list)* | §1 caption/pinned comment, §10 demo name, §11 remainder |

---

## 1. 🔴 The caption and the pinned comment do not exist yet

**Status: BLOCKING, and it is not on the plan's list of nine.** §11 Phase H steps 44–45 say
the caption carries "the tappable handle and the speed claim" and the pinned comment carries
"the how-it-works" — but **no actual copy is written anywhere in the plan**. These ship *with*
the video (§11 Phase H, R17), so they need your sign-off in this same pass or Phase H stalls.

The nearest thing to a draft is `03_production_blueprint.md:418-421`, which is **corpus-verbatim**:

```
🔥 Tugʻilgan kunga eng ajoyib va esda qolarli sovgʻa — uning ismiga atalgan shaxsiy qoʻshiq!
⚡️ 1 daqiqada tayyor boʻladi, soʻzlarini oʻqish esa MUTLAQO BEPUL!
👉 Hoziroq sinab koʻring: https://t.me/bayram_uzbot?start=ig_bayram
(Havola profil bioda ham bor! 👆)
```

*Gloss: "The best and most memorable birthday gift — a personal song dedicated to their name! /
It's ready in 1 minute, and reading the lyrics is COMPLETELY FREE! / Try it right now: <link> /
(The link is in the profile bio too!)"*

**Three problems with using it as written:**

1. **`1 daqiqada tayyor boʻladi` is the exact claim §7.4 ruling 3 struck off the card as an
   overclaim.** The product's own timeout is `music_timeout_s = 420.0` (seven minutes,
   `config.py:425`). Ruling 3 says the claim "moves to the pinned comment"; risk R11 says if it
   goes back anywhere it must be **a ceiling, not a promise** (*bir necha daqiqada*). As written
   it is a promise. **Your call: `bir necha daqiqada`, or no number at all?**
2. ~~**The link contains the word `peshta`.**~~ **SETTLED 2026-09-18: renamed to `ig_bayram`.**
   Decision D4 and risk R10 keep *peshta* — the original hit's title — out of anything that
   ships; §3.5 enforces that in the lyrics and §3.6 in the vendor headers, and the caption link
   was the one surviving place it shipped publicly. The rename cost nothing: the bot has **no
   handler for this payload at all** (`src/bayram/bot/handlers/start.py:186-188` only
   special-cases the paid-return payload; everything else falls through to the generic
   welcome), so no attribution breaks. Nothing for the reviewer to decide here.
3. **Cyrillic variant — ship it or not?** `03 §4.3` mandates a dual-script pinned comment. The
   product itself is **Latin-only** (`uz_latn.py`, no Cyrillic locale). Your call.

> **ANSWER 1a (speed claim):**
> **ANSWER 1b (peshta in the link):**
> **ANSWER 1c (Cyrillic pinned comment):**
> **ANSWER 1d (final caption copy):**
> **ANSWER 1e (final pinned-comment copy):**

---

## 2. 🔴 `O mani kuydirding, o mani suydirding!` — the lip-sync line

| | |
|---|---|
| **Where** | Sung, chunk 3. Audible **8.00 – 10.50 s**, over the phone shot and the real bot recording |
| **On screen** | Not printed — heard only |
| **Provenance** | **verbatim** (`02:625`, `CAMPAIGN_MASTER`) |
| **Syllables** | 12 |
| **Gloss** | "Oh, you set me on fire; oh, you made me fall in love" |

`02:625` calls this *"the emotional peak that viewers love to lip-sync"* — it is the single line
most likely to be re-performed, so an off note here is the one people repeat.

**Two questions (plan G13 #5):**

- **`mani` or `meni`?** `mani` is Tashkent colloquial; `meni` is standard. The apostrophe gate
  cannot catch this — **this line contains no apostrophe at all.**
- **Bare `o`.** Is `o` correct as a standalone interjection, or should it be `Oʻ` (U+02BB), `Oh`,
  or something else? Note the line is lower-cased mid-sentence in the corpus (`o mani…`).

> **ANSWER 2:**

---

## 3. 🔴 `UNING ISMIGA / ATALGAN / QOʻSHIQ!` — card c4, and it is now three lines

| | |
|---|---|
| **Where** | Card **c4**, frames 218–399 |
| **On screen** | **3.64 s** — the longest single narrative card, and the product claim |
| **Provenance** | **assembled.** Every fragment is in `03`; the sentence is new. Adapted from `03:418`'s *"uning ismiga atalgan shaxsiy qoʻshiq"* (`shaxsiy` dropped) |
| **Gloss** | "A song dedicated to **their** name!" |

This card **replaced** Variant D's `ISMINGIZ BILAN MAXSUS QOʻSHIQ!` ("a special song with YOUR
name"), which named the wrong person — the whole premise is gifting a song to someone else, and
the shot underneath is the **recipient's** phone.

**Three questions:**

- **Does `uning` land?** Or does a viewer need `doʻstingiz ismiga` / `yaqiningiz ismiga`
  ("your friend's / your loved one's name") to understand who is being sung about? (plan G13 #2)
- **The line break changed after the plan was written.** §7.4a re-measured on the installed
  Montserrat ExtraBold: `ATALGAN QOʻSHIQ!` is 834 px, over the 800 px bound, so the card is now
  **three lines**: `UNING ISMIGA` / `ATALGAN` / `QOʻSHIQ!`. **Does the phrase still read
  naturally broken there**, with `ATALGAN` alone on its own line?
- **Is dropping `shaxsiy` ("personal") a loss?**

> **ANSWER 3:**

---

## 4. 🟠 Register — and it is a three-way clash, not the two-way one the plan describes

Plan G13 #4 says: sung lines are informal, cards are polite, settle it. **That understates it.**
Measured across the actual final set, **the sung lines are internally mixed and the cards are
internally mixed too:**

| Layer | Informal (2sg) | Polite (2pl) | Third person |
|---|---|---|---|
| **Sung** | `Isming aytib` (your name) | `Bayram-botga **kiring**!` | — |
| **Cards** | c2 `TOʻXTA…` (stop!) | c6 `HOZIROQ **KIRING**:` | c4 `**UNING** ismiga` |
| **Bot UI on screen, 9.00–10.50 s** | — | `**oʻzingiz** yozadigan koʻrinishda yozing` (`uz_latn.py:290`) | — |

So in fifteen seconds the viewer is addressed as *sen*, as *siz*, and talked about in the third
person. That may be fine — ad copy often mixes — but **it is a deliberate choice you have to
make, not an accident to leave in.** The bot itself is consistently polite, so the safest
resolution is probably polite everywhere except the sung hook.

**Settle it in one direction for the sung lines and the cards together.** If you choose polite,
`TOʻXTA…` → `TOʻXTANG…` and the sung `Isming aytib` → `Ismingiz aytib` (which adds a syllable —
14 instead of 13 for that line; harmless, see §0).

> **ANSWER 4 (pick one: all-polite / all-informal / mixed-as-is, and list the strings to change):**

---

## 5. 🟠 `SOʻZLARINI OʻQISH BEPUL!` — card c5

| | |
|---|---|
| **Where** | Card **c5**, frames 400–524 |
| **On screen** | **2.50 s**, over the phone shot and the real bot recording |
| **Provenance** | **assembled.** From `03:419`'s *"soʻzlarini oʻqish esa MUTLAQO BEPUL!"*, with `esa MUTLAQO` dropped to fit |
| **Gloss** | "Reading the lyrics is free!" |
| **Break** | Two lines: `SOʻZLARINI OʻQISH` / `BEPUL!` — the break is **specified**, because a greedy wrap yields `SOʻZLARINI` / `OʻQISH BEPUL!`, which splits the claim across the wrong clause |

This is the claim that **replaced the speed claim**, and it is the only promise in the film that
is verifiable in the product: the free lyric preview really does happen before the payment gate.

**Questions (plan G13 #3):**

- Does it read as **"reading the lyrics is free"** — or could it be read as *"the song's lyrics
  are free (but the song isn't)"*, or worse, as *"the song is free"*?
- Whose lyrics? `soʻzlarini` is 3sg-possessive + accusative with no antecedent on this card.
  Does it need `qoʻshiq soʻzlarini`?
- Is losing `esa MUTLAQO` ("*absolutely* free") a real loss of punch?

> **ANSWER 5:**

---

## 6. 🟠 `Oʻn besh mingga qoʻshiq tayyor, Bayram-botga kiring!` — the sung CTA

| | |
|---|---|
| **Where** | Sung, chunk 4. Audible **11.50 – 13.24 s**, under card c6 |
| **On screen** | Not printed |
| **Provenance** | **new as a line.** `Bayram-botga kiring!` is verbatim (`01:520`); the price half is rewritten from Variant D's *"15 mingga qoʻshiq tayyor: kiring @bayram_uzbot!"* |
| **Syllables** | 14 (plan says 14 — matches) |
| **Gloss** | "For fifteen thousand a song is ready — go into Bayram-bot!" |

Two deliberate changes from Variant D: the numeral is **spelled out** (`Oʻn besh` — a numeral is
not singable) and the `@handle` is **removed from the sung line** (a sung @handle is
unintelligible; it moves to card c7, where it is read).

**Questions:**

- **Is `Oʻn besh mingga` singable and natural**, or does a real speaker say `oʻn besh ming
  soʻmga`? (plan G13 #7)
- **`Bayram-botga kiring!`** — is the dative right, and does **`Bayram-bot`** read as a name
  rather than a typo for *bayram bot*? (plan G13 #6) It is the correct government — *kirmoq*
  takes the dative, so Variant D's bare *"kiring Bayram bot"* was broken — but confirm the
  hyphenated compound looks deliberate.
- **`Bayram-botda` is not the handle.** The audio hook says *Bayram-bot*; the handle is
  `@bayram_uzbot`. Gate G15(b) tests what Telegram search actually returns for "bayram bot".
  **Is the mismatch acceptable, or should a sung line say the real handle?**

> **ANSWER 6:**

---

## 7. 🟠 The audio title — pick one spelling

The corpus writes it two ways:

- `Bayram Uzbekiston - Peshta (Parodiya)` — `02:638`
- `Bayram Oʻzbekiston` — `CAMPAIGN_MASTER §5.2`

**Neither ships as written.** R10 forbids publishing under a title carrying *Peshta*, and
suggests **`@bayram_uzbot — Bayram-botda`** instead.

- `Uzbekiston` or `Oʻzbekiston` (U+02BB)? **Does the country name belong in the title at all?**
- Sign off the final title string. (plan G13 #8)

> **ANSWER 7:**

---

## 8. 🟡 `SOAT 23:55.` / `SOVGʻA ESA YOʻQ!` — card c1, the hook

| | |
|---|---|
| **Where** | Card **c1**, frames 0–126 — **the first thing anyone sees** |
| **On screen** | **2.54 s** (c2 overlaps it from 1.60 s) |
| **Provenance** | **verbatim** (`03:492`) |
| **Gloss** | "It's 23:55. And there's no gift!" |

It **replaced** Variant D's `SOVGʻAGA NIMADIR TOPISH KERAKMI?` (31 characters, wraps to 3 lines,
unreadable in 1.2 s muted). The corpus version carries a 😱 emoji; **the emoji is dropped** —
Montserrat ExtraBold has no emoji glyphs (verified: U+1F525 and U+1F449 both absent).

- **Does it read as contemporary vernacular**, or as a literal clock reading? (plan G13 #1)
- Is `esa` right here, or is it too written/formal for a shouty hook card?
- 50–62% of viewers see this **muted**. **Is the panic legible from these seven words alone?**

> **ANSWER 8:**

---

## 9. 🟡 The speed claim — confirm it is gone, except it is not quite

Plan G13 #9 asks you to confirm **no on-screen string implies a turnaround time**. On the cards,
that holds: `10 SONIYADA TAYYOR BOʻLADI!` was removed and replaced by c5's free-preview claim.

**But the real bot recording at 9.00 – 10.50 s puts a time claim back on screen.** The shipped
string filmed in that shot is:

> `✍️ {name} uchun soʻzlarni yozayapman… bu bir daqiqagacha oladi.` — `uz_latn.py:311`

*"I'm writing the lyrics for {name}… this takes up to about a minute."* It is a **ceiling**
(`-gacha`, "up to"), which is what risk R11 asks for, and it is the product's own shipped copy —
but it is **1.5 seconds of on-screen Uzbek making a time promise**, and §7.4 ruling 3 states the
claim was "removed entirely". Two ways to go: accept it (it is true, and it is the product
speaking), or film the demo so that frame is not held.

> **ANSWER 9 (accept / re-film):**

---

## 10. 🟡 The demo recording — the name you type is on screen for 1.5 s

Phase A step 12 films the real bot with a "neutral recipient name". That name is **visible Uzbek
text in the film** (it appears in `wizard.output_language.prompt` = `{name} uchun qoʻshiq qaysi
tilda boʻlsin?` and in the lyric preview title).

**Pick the name now**, before filming: a common, unambiguous Uzbek given name that is not a real
person you know and does not read as a joke. `03` uses *Saodatxon* in a mock-up.

> **ANSWER 10 (name to type):**

---

## 11. 🟢 The low-risk remainder — read them, but they are all corpus-verbatim

| Card | String | On screen | Provenance | Gloss | Judge |
|---|---|---|---|---|---|
| **c2** | `TOʻXTA…` | **0.94 s**, frames 80–126, pulsing | verbatim (`02 §2.4 r2`), apostrophe corrected to U+02BB, `...` → `…` | "Stop…" | Informal singular — see §4. Is the ellipsis right for a freeze beat? |
| **c3** | `BAYRAM-BOTDA!` | **1.82 s**, frames 127–217, on the 808 slam | verbatim (`02 §2.4 r3`) | "In Bayram-bot!" | Shouted locative with no verb — does it stand alone? Corpus had 🔥; replaced with a drawn vector flame |
| **c6** | `HOZIROQ KIRING:` + `@bayram_uzbot` | **3.50 s**, frames 575–749 | verbatim (`02 §2.4 r6`) | "Go in right now: @bayram_uzbot" | Polite imperative — see §4. Colon + handle instead of the dative; acceptable as a label? Corpus had 👉; replaced with a vector chevron |
| **c7** | `@bayram_uzbot` | **12.10 s**, frames 145–749 (longest exposure in the film) | verbatim (all four docs) | — | Nothing to translate; confirm the handle is exactly right |
| **c8** | `ATIGI 15<NBSP>000 SOʻM` + `Bitta kofe narxi` | **6.60 s**, frames 420–749 | verbatim (`03:589`, `03:373`) | "Only 15,000 soʻm / The price of one coffee" | The space in `15 000` is U+00A0 so it cannot wrap (a wrap would read as 15 soʻm). Is *bitta kofe narxi* the right anchor, or *bitta lavash puli* / *taksi puli* (both also in the corpus)? |
| **c9** | — | 3 × 0.04 s | white flash, no text | — | — |

**Sung lines not already covered above** — all three **verbatim** from `02 §2.4`:

| | Line | Audible | Syll | Gloss |
|---|---|---|---|---|
| **L1** | `Sovgʻa izlab boshim qotdi...` | 0.24 – 1.60 s | 8 | "Hunting for a gift, my head's in a spin…" |
| **L2** | `BOTDA! BAYRAM-BOTDA!` | on the slam, 2.54 s | 6 | "In the bot! In Bayram-bot!" |
| **L3** | `Isming aytib kuylar bugun, botda Bayram-botda!` | 2.54 – 8.00 s | 14 | "Saying your name it sings today, in the bot, in Bayram-bot!" |

L3 carries the **informal `Isming`** — that is the register question in §4.

> **ANSWER 11 (anything in this table you want changed):**

---

## Sign-off

- [ ] I have read every string above and the ones I marked FIX have been changed.
- [ ] I accept the register decision recorded in §4.
- [ ] The caption and pinned-comment copy in §1 are final.

**Signed / date:**

Once this is signed: Phase A step 10 renders the cards, and Phase B may buy the song.
**Gate G13 runs a second time in Phase G step 41**, on the burned-in cards — this pass is the
strings, that pass is how they look on screen.

---

*Mechanical pre-check: `marketing/campaigns/peshta/g13_check.py` (orthography, syllables, provenance). Run it
again after any FIX above — it exits non-zero on an ASCII apostrophe or a lost U+00A0, and it
was verified to do so against a deliberately corrupted copy of `cards/strings.txt`.*
