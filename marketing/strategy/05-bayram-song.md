# 05 — The Bayram song: original lyrics on a measured grid

**Frozen at 2026-09-18.** Produced by a nine-agent workflow: two grounding agents (Uzbek prosody,
growth/legal), four lyricists working different angles, one character designer, two adversarial judges
(native singability; growth and brand risk).

**What this is.** A brand-owned song — new melody, new Uzbek words, our own recording — written to sit
on the tempo and line-shape measured in [`02-instagram-trend-research.md`](02-instagram-trend-research.md)
so it feels native to the moment people are in right now.

**What this is not.** It is not a rewrite of Xamdam Sobirov's *Peshta*. No line here derives from his
text, no hook word of ours is a homophone of his, and nothing below was produced by substituting words
into his lines. What was taken from the reference is a measurement — 95.8 BPM, a 2-bar line, an 8-bar
section, and the placement of a bass dropout before a kick return. Tempo is not a work; a grid is not a
work; the particular words are, and ours are ours. See §9.

---

## §1 The grid we write to

From `02` (FFT analysis of the reference audio, 2026-09-16), restated here as constants:

| Constant | Value |
| --- | --- |
| Tempo | 95.8 BPM |
| Beat | 0.626 s |
| Bar | 2.505 s |
| One line | 2 bars = 8 beats = 5.01 s = 16 eighth-note slots |
| Section | 8 bars = 20.04 s = 4 lines |
| Payoff | sub-bass out for ~0.9 s, kick returns on **beat 5** of the hook line |

Everything below is written to that. The posted cut is **20.0 s — exactly one section**, so the loop
seam is inaudible; the reply-ladder unit is **10.0 s — half a chorus**. Never cut to round seconds.

## §2 The syllable budget

The eighth note is the syllable grain at this tempo (a sung Uzbek syllable averages ~0.30 s), so 16
syllables is the *physical* ceiling of a line and nothing should ever be written there.

| Line type | Syllables | Why |
| --- | --- | --- |
| Verse line | **10–13**, sweet spot 11 | leaves a rest at the line turn and room for one sustained final vowel |
| Chorus content line | 10–12 | |
| Chorus **hook** line | **6–10** | the silence *is* the hook; filling beats 6–8 throws away the drop |

Three things eat the theoretical 16: Uzbek final stress (the last syllable of the line-final word must
land on a strong beat, costing a slot to place it); the unstressed clitics `-da -ni -lar -im`, which
must fall off the beat (`BOT-da`, never `bot-DA`); and breath, which costs 1–2 slots at every line turn
in this chest-forward legato register.

**Rule of thumb: count 11 for a verse line, 9 for a hook line. At 14 you have written a bar and a half
of text into one bar.**

## §3 Your chorus, scanned

The draft as submitted, and what the prosodist found:

**Line 1** — 15 syllables. It technically fits, with one eighth of air in five seconds. Two real
failures: the **slam is buried** (you are still mid-sentence at beat 5, so the kick return lands on a
passing syllable and the drop does nothing), and `telegram` + `botda` stacks a final-stressed syllable
against an initial-stressed one across an /m/+/b/ lip re-close at 0.313 s — the one junction a singer
physically cannot take clean here. `botda telegram botda` also says *in the bot, telegram, in the bot*;
the first `botda` is an orphan.

**Line 2** — correct, and the best-built line in the draft. But it will be mis-performed: four o's on
the page tells every singer to **hold**, and a 2-beat sustain plus 10 syllables does not fit 8 beats.
`oooo` is a **two-eighth pickup, not a sustain**, and the lyric sheet has to say so. Read as its two
equal halves, your draft is already a 4-line chorus in the measured shape — **the architecture was
right, only the density was wrong.**

**Line 3** — 19 syllables into 16 slots. A hard overrun; it cannot be fitted, only split or cut. Inside
it, `izhorlari` is 4 syllables of which 3 are suffix, and its /z/+/h/ seam evaporates at speed (it will
be heard as *izzorlari*); `tugʻilgan kun tabriklari` is 8 straight syllables of dictionary noun phrase
with no stress relief. And `izhorLARI` / `tabrikLARI` is **grammatical rhyme** — the same suffix twice,
which a native ear hears as a grammar drill, not craft.

**`shotda` is `shu botda`** — "in this very bot". That reading fixes the meaning *and* keeps your
`-otda` rhyme. **It is sung elided and spelled in full, always.** Never print `shotda` in a caption,
cover card, first comment or storyboard: a non-word in the caption reads as a typo to exactly the
Uzbek-literate audience we sell name-accuracy to.

### The minimal-change baseline

Your words, your order, fitted to the grid. This is the frozen "chorus unchanged":

```
Tabriklarim, mani jonim — botda              [10]
oooo Bayram uz botda, oooo Bayram uz botda   [10]   (o-o = pickup)
Sevgi izhori, tugʻilgan kun tabriklari       [13]
oooo — hammasi shu botda                     [ 6]
```

Line 1 loses `telegram botda` — five syllables, the only non-Uzbek word in the chorus, the one
unsingable junction, and it pays back no rhyme. Cutting it is what frees beats 6–8, which is what lets
**`botda` land alone on the slam at beat 5**. The comma after `Tabriklarim` is not decoration: in
Tashkent speech `mani` carries both *mening* and *meni*, so without it the sung line can parse as "my
congratulations [are] me". It is also where the singer breathes.

---

## §4 The four versions

### A — «Mehmon» (chorus unchanged) · the answer-video

Three lines of what other people brought, then the turn. It never says "bot" — it saves that for the
chorus, so your chorus arrives as the punchline.

```
Birov karta toʻldirdi, birov uzuk,               [11]  Someone topped up a card, someone a ring,
Mashina surat uchun — bir kunlik xayol,          [12]  The car is for the photo — a dream that lasts a day,
Manda bitta qoʻshiq bor, ichida isming,          [12]  I have one song, and your name is inside it,
Hech kimda yoʻq bunday — pul solma, qoʻshiq sol. [12]  Nobody has one like it — don't put in money, put in a song.
```

### B — «Onam chaqirgandek» (chorus unchanged) · the quiet proof

The small domestic humiliation everyone has lived, then the product truth. Complains about the world
and praises nobody, which clears the *koʻz tegmasin* rule by construction.

```
Hujjatda bir harfim oʻzgarib ketgan   [11]  In the document one letter of mine has been changed
Mashina ovozi buzdi ismimni           [11]  A machine's voice broke my name
Begona yarmini yutdi, soʻramay        [11]  A stranger swallowed half of it, without asking
Onam chaqirgandek aytsin otimni       [11]  Let it say my name the way my mother calls me
```

### C — «Chant» (chorus changed) · pure loop engineering

Chorus line 1 built as a template with exactly one swappable slot, so every reply video is the same two
bars with a different name in it. Emotion deliberately thin, repetition deliberately thick.

```
[HOOK], Dilnoza — botda                      [ 7]
[HOOK], [HOOK] — isming yodda                [ 8]
Tugʻilgan kun, sevgi soʻzi — shu botda       [11]
[HOOK], [HOOK] — Bayram uz botda… [HOOK]!    [11]

Pasportda bir xil — uyda boshqa aytadi       [12]  In the passport one thing — at home they say it another way
Isming buzilsa — koʻngil sinib qaytadi       [12]  If your name gets broken — the heart comes back broken
Uyda qanday chaqirsa — shuni oʻylaymiz       [12]  However they call you at home — that's what we think about
Har soʻzni koʻrasan, keyin kuylaymiz         [11]  You see every word first — then we sing
```

### D — «Tabrikchi» (chorus changed, descended from yours) · the character's song

Sung by a man who has one job in this world — congratulating people — and performs it with the gravity
of a civil servant issuing a permit. The joke is entirely his seriousness. He never comments on the
recipient and never praises them, so a bureaucrat satisfies *koʻz tegmasin* for free: **a clerk files,
he does not flatter.** Keeps your `botda` spine, your line 2 verbatim, and your closing landing.

```
[HOOK], Dilnoza, tabrik — botda                [ 9]
oooo Bayram uz botda, oooo Bayram uz botda     [10]   ← your line, untouched
Ismingiz — onangiz aytgandek — yodda           [11]
oooo — [HOOK]! Hammasi shu botda               [ 8]

Bu dunyoda bitta ishim bor, jonim              [11]  In this world I have one job, my dear.
Tabriklayman — tinim yoʻq, sultonim            [10]  I congratulate — there is no rest, my sultan.
Kecha — toʻy. Bugun — bayram. Erta — toʻy.     [10]  Yesterday a wedding. Today a holiday. Tomorrow a wedding.
Endi bu ish botda boʻladi, xonim               [11]  From now on this work happens in the bot, madam.
```

`jonim / sultonim / xonim` is the character's tic on three different stems, not a suffix drill; line 3
is left off the rhyme so the deadpan list reads as an interruption.

---

## §5 The two verdicts

| Version | Native singability | Growth / brand risk |
| --- | --- | --- |
| **D — Tabrikchi** | **8** | **7.5** |
| A — Mehmon | 7 | 4.5 — *would not ship* |
| C — Chant | 5 | 7 |
| B — Onam chaqirgandek | 5 | 6 |

They disagree about everything except D. The native judge ranks on whether a Tashkent singer would sing
the line without editing it; the growth judge ranks on whether the first two seconds are earned and
whether the ladder can be cut from it. **A is the one both agree costs more than it returns** — no hook
word, no name slot, and the only two lines on the slate that actively lose goodwill.

## §6 The composite to ship

Neither judge's winner is a whole song. This is the union of both:

```
CHORUS
  Tabriklarim, mani jonim — botda                [10]   ← yours, comma added
  oooo Bayram uz botda, oooo Bayram uz botda     [10]   ← yours, verbatim (o-o = pickup)
  Onangiz chaqirgandek yozing — yodda            [11]
  oooo — hammasi shu botda                       [ 6]   ← yours, verbatim

VERSE  (the Tabrikchi's)
  Bu dunyoda bitta ishim bor, jonim              [11]
  Tabriklayman — tinim yoʻq, sultonim            [10]
  Kecha — toʻy. Bugun — bayram. Ertaga — toʻy.   [11]
  Endi bu ish botda boʻladi, xonim               [11]
```

Three of your four chorus lines survive untouched. The verse is the one in the packet the native judge
called "written in Uzbek rather than translated into it".

**Chorus line 3 is the highest-severity line on the slate and this is the safe form of it.** Every
other candidate for that slot — *Ismingiz — onangiz aytgandek — yodda*, and B's whole payoff — states
audible pronunciation as a **fact**, three times per loop, inside the hook. The production pack
(`04` §8.1, §8.6) bans that claim and makes a publicly refuted pronunciation claim a stop-the-ladder
trigger, precisely because there is a two-grader gate that can fail. `yozing … yodda` — *write it the
way your mother says it; it is noted* — is an instruction to the buyer and a promise about the record,
not about the render. Ship that one.

### Required line fixes if you shoot any other version

| Version | Replace | With | Why |
| --- | --- | --- | --- |
| A v1 | `Birov karta toʻldirdi` | `Birov kartaga pul soldi` | *toʻldirmoq* belongs to a balance, not a gift; and `soldi` now pre-echoes `pul solma, qoʻshiq sol` |
| A v2 | `bir kunlik xayol` | `bu ham bir xayol` | "lasting one day" sneers at the gift half the audience brought to this table |
| A v4 | `Hech kimda yoʻq bunday` | `Faqat senga atab` | unverifiable market claim → literally true |
| B v2 | `Mashina ovozi` | `Navbatchi ovozi` | *mashina* is a **car** in colloquial Uzbek — and we *are* the machine voice; don't sing the case against ourselves |
| B v4 | `otimni` | `ismimni` | *ot* for "name" is archaic; the live meaning is **horse** |
| C v3 | `shuni oʻylaymiz` | `shunday kuylaymiz` | a committee sentence about our internal thoughts |
| C v3/v4 | `Tugʻilgan kun` adjacent to `Bayram uz botda` | reorder to `Sevgi soʻzi, tugʻilgan kun — shu botda` | implies *bayram* = birthday, in the hook, twice per loop |
| D v3 | `Erta` | `Ertaga` | *erta* alone is "early/morning" |

## §7 The hook word — both coinages were rejected

Two invented slot words were generated and **both judges killed both**, for the same reason neither
writer caught: **Uzbek reads a final `-am`/`-im` as the 1sg possessive.** Any such coinage arrives as
"my ⟨something⟩", pulls to final stress, and spends the best half-second of the hook sending the
listener to hunt for a stem that does not exist. That is the opposite of a chant. One of them also
comes back from the next room as an existing word, and splits on the page into two real words; the
other is a live inflected Russian form, so the hashtag does not start clean in the half of the market
that types Cyrillic — and printed in ASCII its `o` is ambiguous with `oʻ`, giving a different real word.

**The shape rule for the next attempt:** two syllables, CV-CV or CVC-CV; stress on the **first**
syllable so the attack lands on the downbeat; onset a plosive or affricate (`b d g t k q ch j`) — never
a vowel, never a sibilant, which smears under sub-bass on a phone speaker; stressed vowel **open**
(`a` or `o`), which survives shouting and 128 kbps; ending an **open vowel or `-l`/`-r`** so it can be
held through the dropout and released on the slam — and never `-m`/`-n`/`-im`/`-am`.

**Two clearance gates before anyone books a vocalist:** a native meaning check across Uzbek, Russian,
Kazakh, Kyrgyz and Tajik, and an empty-search check on the hashtag in both scripts.

**Until a word clears both gates, the slot runs on your own line** — `Tabriklarim, ⟨NAME⟩ — botda` —
which is chantable, grammatical, and already the line the audience hears everywhere else.

## §8 The new character

Two originals were designed. Both are built to the existing red-and-cream art direction, both are
faceless-or-flat enough to read at 400px on a muted phone, and neither resembles any existing performer,
mascot or character.

### ISMCHI — recommended

*ism* + the occupational `-chi`: **"the name-person".** A self-appointed registrar of names who has
decided, on nobody's authority but his own, that somebody has to keep a proper record of how people's
names are actually written. He works through the day's names with total ceremony: ledger, red stamp,
one unhesitating line. What he wants is for the paper to finally agree with the mother. What he is bad
at is hurry, small talk, and any sentence containing *tez*. What he is unreasonably good at is the
letters — handed `Gʻulomjon`, `Oʻgʻiloy` or `Muhammadalisher` cold, he writes them with the modifier
letters in the right places and does not look up.

- **Look:** plain cream jacket, no pattern. The entire colour budget is one deep red — stamp handle,
  ink pad, pencil behind the ear, cord on the ledger. Silhouette: a cream block behind a white
  rectangle with one red dot lifted above it, legible as "about to stamp" with no text and no sound.
- **Catchphrase:** «Toʻgʻri yozildi.» — *It is written correctly.* Said flat, on the stamp-down.
- **Why it carries fifty videos:** the reply unit *is* the character. The name arrives in the comments,
  he writes it into the ledger, the stamp lands. Four bars, 10.0 s — the name sits in beats 1–4 where
  the sub-bass is out and the voice is naked, and the **stamp thud lands on beat 5**, so the payoff
  frame is a practical sound effect rather than an edit trick. A visible counter on the page («37-ism»)
  gives fifty episodes an arc with no new material.
- **Production:** cheap, one person, tomorrow, on a phone. Bazaar-and-kanstovar shopping list; the
  stamp is cut same-day at any kiosk. No AI in the base unit, so **no C2PA/AI-label question at all**.
- **The risk that kills it:** he reads as a state clerk. The moment the jacket, table or stamp acquires
  anything resembling an official seal, the video stops being a joke about paperwork and becomes a
  brand satirising a government body — and lands the joke on people who actually work there. Mitigation
  is a **prop rule, not an edit**: wordmark stamp only, rectangular, no crest, no circle, no uniform,
  no epaulettes, no institution named or shown, ever.

### QAYNAR — the alternative

The faceless cream-and-red teapot at the centre of the dasturxon, which has sat through every toy and
every ordinary Tuesday and heard every name in that house the first time it was said — in the register
a mother uses, not the register a form uses. It cannot stand, hurry, or point. Its one dramatic move is
**refusal**: when the passport spelling arrives, the steam stops and the silence does the work.
Catchphrase: «Men eshitganman.» — *I have heard it.* No face means no continuity problem, no lip-sync,
no AI generation; twenty units shot against one wall in an afternoon.

**Why it is the alternative and not the recommendation:** a faceless object cannot be *militant* about
anything. The brand's claim is that somebody insists on getting the name right, and Qaynar can only
witness accuracy, never assert it — so run alone it drifts into atmosphere, gets forwarded as "nice
video", and converts nobody. That is the exact failure mode `03` already recorded against the spectacle
concepts. It works beside a human line, not instead of one.

## §9 Kill list

Nothing on this list ships, in any version:

- `otimni` meaning "my name" — and the whole official-name-vs-home-name *semantic* claim built on it.
  That distinction is **register, not semantics**, in Uzbek. A brand whose single strongest claim is
  name accuracy cannot be caught inventing a fact about names.
- `Mashina ovozi` for a machine voice — *mashina* is a car.
- Either invented hook word as currently spelled, in any typeset copy, before §7's two gates return.
- `shotda` anywhere a reader sees it — caption, cover, storyboard, lyric sheet, DM. Sung only.
- `Hech kimda yoʻq bunday` — an unverifiable competitor claim; the same banned move with the numbers
  filed off.
- `bir kunlik xayol` — devalues the gift half the audience is holding.
- Any line stating audible pronunciation as a fact (§6).
- Any adjacency implying *bayram* = birthday.
- `oooo` on a singer's sheet. Write `o-o (pickup)`. Handed four o's, every singer holds them and breaks
  the bar.

## §10 Where the song stops and the funnel starts

**None of these four songs tells anyone to type `/start`.** All of them end on `botda` — *in the bot* —
which is an address with no door, and the sung "Bayram uz" is **not** the handle `@bayram_uzbot`.

- Every landing on `botda` carries `@bayram_uzbot · 15 000 soʻm` burned into the same frame,
  persistently from the first slam to the last, and the handle sits inside the caption's first 125
  characters. `03` already recorded this exact failure once.
- Ship each variant with its own start payload — `t.me/bayram_uzbot?start=ig_<variant>`. Instagram's
  in-app browser will not hand off to Telegram, but Telegram itself serves a Start Bot button carrying
  the payload, so it survives one extra tap. Without distinct payloads the `04` §8.5 day-14 gate
  (≥1 `/start` per published reply video) cannot be run, and the ladder cannot be measured at all.

**Budget the conversion into burned-in text and a payloaded link. Stop expecting the lyric to carry it.**

## §11 Why an original song at all

The decision to record our own rather than ride the licensed track is settled by three things, in
descending order of size:

1. **Paid distribution becomes possible.** In-app availability is not a commercial sync licence; a
   boosted Reel carrying a label track needs separate clearance or the audio is stripped and the ad
   rejected. A master whose composition *and* recording we own has nothing to clear.
2. **The ladder compounds.** Instagram models "will the viewer visit the audio page" as a ranking
   prediction (`02`). On our own audio, fifty reply videos accumulate on **one page with our handle at
   the top**; on somebody else's, they are buried among tens of thousands and the tap lands on him.
   That is the difference between fifty posts and one asset.
3. **The business-account music restriction stops being a risk.** Original audio has no picker — the
   song ships inside the upload. The dependency disappears, and with it the temptation to act on the
   "switch the category to Entrepreneur" folklore, which changes the interface and not the licence.

**The honest cost:** an unknown original audio gets **none** of the trending sound's distribution. We
are trading borrowed reach for an owned asset, and the first videos will feel slower for it.

**Where the safety comes from, and where it ends.** Tempo is a measurement, not a work — 95.8 BPM is
unprotectable, and so are a 2-bar line grid, a 4-line section, a genre and a key. Pulling the sub-bass
out for a bar and slamming the kick back is a production idiom across the genre — scenes-à-faire, not
protected expression. "A short chantable word in the hook" is an idea, and ideas are not protected —
which is exactly why **our particular word has to be genuinely ours** (§7). New melody, new harmony,
new Uzbek lyrics, new recording means we own both copyrights that matter, in perpetuity.

It stops being safe the moment any of that is walked back: lifting a melodic contour, translating or
substituting into his lines, or choosing a hook word that is a near-homophone of his. **Keep this dated
write-up — it is evidence of method.** One music-rights-literate reviewer, ideally with Uzbek practice,
should hear the master once before first publication. Nothing here is legal advice.

## §12 Open — decide before booking a studio

1. **Cast the Tabrikchi, or don't.** This is the real decision, not which lyric is best. A recurring
   face is the single thing that turns fifty reply videos into a series instead of fifty ads — and it
   is also the thing that can quietly become a wish, because the ladder's throughput maths assumes
   swapping audio and a name card in a template, not getting a man back into a jacket on demand.
   **Decide it on a clock, not on taste.**
2. **The hook word.** Re-derive to §7's shape rule and run both gates. The composite in §6 ships
   without one.
3. **Who sings it.** The Tabrikchi's verse is a deadpan male delivery; the chorus is not. That may be
   two voices, which changes the session.
4. **The master.** Produce once at ~60 s — 4-beat pickup, 8-bar verse, 8-bar chorus, 4–8 bar clean
   instrumental tail for other accounts to talk over. Deliver three files: full vocal, instrumental
   only, and the stems/project kept with its creation dates.
