# Production pack — the document you shoot from

**Written 2026-09-17, morning, Tashkent.** This is the pack the shoot runs on. **It supersedes
[`01-instagram-launch-playbook.md`](01-instagram-launch-playbook.md) wherever the two disagree**,
because the playbook was written on 2026-09-16 — before a single one of its own flagged claims had
been checked. Six of them were checked this morning, against the repository, against the live
production host (read-only), and against primary sources. Four came back verified, one premise was
refuted outright, and one came back mixed — with the claim the whole reply-ladder rests on still
unknown, in the direction that costs money.

Read it in this order: the gate, then what changed, then the facts, then your pack. A producer who
reads only §1 and their own pack has everything they need for the day.

**Convention used throughout:** a line marked **⚠️ PLAYBOOK CONTRADICTED — line NNN** means the
playbook says something this document has proved false. The playbook file has **not** been edited —
nobody has touched it — so anyone shooting from the older document will shoot the wrong thing. That
is itself a blocker (§1, #10).

**Hard rule that applies to everyone in this pack:** the production host is READ ONLY today. No
writes, no migrations, no restarts, no service changes. Everything below that needs a write says so
and names who must do it.

---

## 1. GO / NO-GO

**VERDICT: GO WITH CUTS.** Nothing found this morning kills the shoot. The price is right, the
payment rail is real, and the two cards the playbook thought were legally risky are now the two that
can be filmed most honestly. But three cards lose frames, one loses a genre that does not exist, and
**the house block still cannot shoot unless tonight's render gate produces graded names** — and as of
this morning nobody has booked the people who do the grading.

**The single thing blocking the shoot: two native-speaker graders are not booked for 21:30 tonight.**
Everything in the 13:00–17:30 house block depends on names that have passed a human ear, the bot's own
"verified" verdict is structurally worthless for this claim (§3, FACT 4), and no phone call in this
pack is later than that one.

### The blockers only a human can clear, ranked

| # | Blocker | What it takes | By when |
| --- | --- | --- | --- |
| **1** | **Two unrelated native speakers booked to grade every on-camera name at 21:30.** They must not be on the production team and must not see the bot's verdict. Without them the gate cannot be graded and the house block does not shoot. | Two phone calls. **15 minutes.** | **Now.** Ahead of everything else in this pack. |
| **2** | **Seven names in the render list are blank** — the qaynona, the bobo, the brother, the backup grandmother, two spare street subjects, the second prank subject. The render session cannot start without them, and their risk tier cannot be computed until they exist. | Ring the family, get each person to spell their own name. **20–30 minutes.** | **18:30 tonight.** |
| **3** | **The Gʻayrat decision.** He is one of card 2's four real faces. The pipeline submits the mark-stripped spelling `Gayrat` to the vendor by default — which is the exact slur reading the slate's own hard rules ban by name. Decide: render and grade him, restrict him to the document cutaway, or replace him. Card 4's driver must simply be cast without a `gʻ`. | One decision, written down. **5 minutes.** | **19:00 tonight.** |
| **4** | **Credits for the two render accounts.** Granting needs an ADMIN role plus a step-up password re-auth, and nobody has confirmed that anyone on this team holds it. If nobody does, tonight's 22 renders cost **330 000 soʻm** of real Payme purchases instead of a grant. | Confirm the login exists, or approve the cash. **10 minutes.** | **18:30 tonight.** |
| **5** | **The minors decision.** The slate breaks its own "Do not publish minors" rule in three places (card 5's six-year-old, card 5's «6 YOSHLI AMIRXONGA» card, card 9's child). Default in this pack is **cut**; an override needs written parental consent naming commercial and boosted use, and a named adult signing off. | Confirm the default, or start the consent paperwork. **5 minutes to confirm, an evening to override.** | **Before the house block is called.** |
| **6** | **The three product substitutions.** Card 5's **drill does not exist** (nearest is `🎧 Xip-xop`); "jazz" is labelled `🎷 Jaz-launj`; card 8's «kasb bayrami / ustoz» **is not a button** (tap `🎉 Bayram` or `✨ Boshqa sabab` + free text). The render, the picker screen-record and the caption all have to say the same word. | Three decisions. **10 minutes.** | **Before 19:00** — the renders encode them. |
| **7** | **Write down whether «notoʻgʻri chiqsa — qayta yozamiz» will be honoured by hand via /support.** There is no re-roll button in the bot and the admin panel is read-only in this build. If the answer is no, that line comes out of six captions and two reply templates today. Separately: «pul olmaymiz» (card 3) is a refund promise with **no mechanism** and is cut regardless. | One written commitment. **5 minutes.** | **Before the first caption is written.** |
| **8** | **The release form has four blanks and no contact.** The operator's name, a phone a person actually answers, a second answering phone, and the Instagram handle. `BAYRAM_SUPPORT_CONTACT` ships blank, so the bot's `/support` **may not** be offered as the contact route on a release. Nothing gets printed until a real number exists, and the 24-hour takedown SLA needs one named owner watching an inbox. | Supply four values, name the owner, print 20 copies double-sided. **30 minutes.** | **Tonight.** Card 2 needs them at 09:00. |
| **9** | **Confirm whose money the 14 settled payments are.** Seven-plus distinct Telegram user ids have paid 15 000 soʻm against a production cashbox since 2026-09-14. Nobody outside the team can tell a customer from the team's own card. **No card, caption or reply may say or imply "people are already buying" until someone who knows confirms it** — this is the claim most likely to end up burned into a forwarded video. | One person who knows, answering one question. **10 minutes.** | Before any caption claims traction. |
| **10** | **Somebody must edit the source documents.** The playbook still carries the stub premise (lines 339, 730, 761, 781, 782), the drill and jazz genres, the ustoz occasion, the gʻ-audibility guarantee and the digit-free price fallback. `docs/deployment/09-payme-go-live.md:3-4` and `README.md:429` still say the rail has never moved a som. **And `deploy/payme-open-orders.py:67-70` still declares 700 000 tiyin to be the shipped price** — run that on a Payme certification day and it opens real orders at half price. That one is an operational trap, not a documentation nit. | Edit the files. **30–60 minutes.** Nothing in this pack edits them. | Before anyone opens the playbook to shoot from it. |
| **11** | **Check lex.uz whether the image-consent law (new Civil Code art. 100-1, passed the Legislative Chamber 121–0 on 7 Oct 2025) has been signed and commenced.** The entire card 2 street block rests on the exact wording of its narrow public-place exception. This pack assumes it is in force. | One search. **15 minutes.** | Before the street block. |
| **12** | **Three onboarded Telegram accounts on three real SIMs by 19:00** (two render accounts, one zero-credit account for the paywall screen). A fresh account is asked for its phone number before it sees any picker, and the 20-lyric-writes-per-day cap makes 22 orders impossible on one account. | Onboard them. **20 minutes.** | **19:00 tonight.** |
| **13** | **The real cake photo must exist before the Higgsfield session starts.** It is the reference the cake-world still chases and therefore the 0:05.5 match cut. Nothing in the call sheet currently assigns it, and it is the single most likely way tonight's session collapses. | Shoot the real cake and candle on the phone, put the JPG on the laptop. **15 minutes.** | **Before 19:00.** |

**What is NOT a blocker any more, and should not be re-litigated tonight:** the price (verified,
15 000 soʻm), the checkout provider (verified, production Payme), whether a payment may be filmed
(yes), and whether Shashmaqom, rok, jaz-launj and the hazil occasion ship (they do). The playbook's
21:30 instruction to "confirm on the live host what `single_song_price_minor` actually is, and confirm
the checkout provider" is **done**. ⚠️ **PLAYBOOK CONTRADICTED — line 730.**

---

## 2. WHAT CHANGED SINCE YESTERDAY

Card by card. If a card is unshootable as written, it says so here rather than leaving a producer to
find out on location.

### Card 1 — Gʻ TESTI
**Shootable. One caption line is dead.**
- **KILLED:** «Bayram esa ismni qanday yozsangiz, shunday kuylaydi — ʻ ham, gʻ ham joyida.» The
  second half is false about the audio: the vendor is sent `Gulomjon`, not `Gʻulomjon`, and the bot's
  verifier scores that a perfect 1.000. Replaced in Pack 2 §3 — the mark claim moves onto the
  **screen**, where it is 100% true and a commenter can reproduce it in ten seconds.
- **KILLED:** the playbook's price fallback («if it cannot be confirmed, the card reads «bitta taksi
  puli» with no digits»). The digits are confirmed. ⚠️ **PLAYBOOK CONTRADICTED — line 781.**
- **CONFIRMED:** «15 000 soʻm — bitta taksi puli» is true and under-claims. 15 000 soʻm is a real
  ~4.2 km Yandex Go Start ride.
- **CONDITIONAL:** both names must pass a human ear. Xurshidabegim is 13 characters, which means the
  machine's own gate allows it **one whole wrong syllable** and still passes.
- **STANDING:** never sing `Gʻayrat` on this card.

### Card 2 — «Gulya emas»
**Shootable. Its central claim is now explicitly conditional, and one subject is dropped.**
- **ALTERED:** «Birinchi marta toʻgʻri aytishdi» ships **only** on takes two unrelated native speakers
  passed. If a name fails, replace the person — do not soften the line over a take that is still wrong.
- **RAISED:** the «Gʻayrat — hujjatda «Gayrat»» and «Oʻgʻiloy — «Ogiloy»» cards stage on screen the
  exact spelling the bot submits to the vendor. The grievance is real and it is the film's point — but
  if the audio sings `Gayrat`, this card is the video convicting itself.
- **CUT:** the teenager. Minors are out by default.
- **HARDENED:** signed Uzbek releases before any camera rolls, for all eight subjects filmed.

### Card 3 — BUVIM ISMINI QOʻSHIQDA ESHITDI
**Shootable, with a label change and a promise removed.**
- **ALTERED:** the ORIGINAL AUDIO name becomes `Bayram — shashmaqom uslubida (Oʻgʻiloy)`, and every
  spoken or burned reference says **shashmaqom uslubida**, never bare *Shashmaqom*. The picker
  screen-record may still show the bot's own `🎻 Shashmaqom` button — the product may name the genre,
  the film may not claim the repertoire.
- **CUT:** «pul olmaymiz». A refund promise with no mechanism anywhere in the product.
- **KILLED:** «ismni biz toʻgʻriladik» as a claim about the audio. We corrected the spelling on screen.
- **HARDENED:** the 0:20–0:22 consent beat stays in the cut **as warmth only**. The signed release is
  taken before the tea is poured. Consent filmed after the reaction is the exact shape the new statute
  is written against.
- **BLOCKER:** one person who actually listens to shashmaqom must audition the rendered track. If it
  is generic Central-Asian-flavoured pop with a doira on it, the word shashmaqom does not appear in
  the film at all — the risk is the mislabel, not the AI.

### Card 4 — TAKSICHINING ISMI
**Substantially changed, and in the right direction.**
- **DELETED:** the risk note "Do not film a Payme press: the checkout provider on the deployment is a
  stub and a stub grants a free song." The rail is production Payme. A press may be filmed.
  ⚠️ **PLAYBOOK CONTRADICTED — line 339.**
- **ALTERED:** the default fare card is now the **surge** variant — «Yoʻl — 19 000. Qoʻshiq — 15 000.
  Arzonroq chiqdi.» At 4 600 + 2 500/km an exact 15 000 fare means a ~4.2 km ride, so most real
  end-of-ride screens read higher, and "cheaper than the ride you just paid for" is both truer and a
  better line than a coincidence you would be tempted to stage.
- **DELETED:** "take a vague filming yes at pickup" as a method. Signed release before the ride.
- **ALTERED:** cast a driver with **no `gʻ`** in his name.
- **NEW OPTION:** tap-to-song ran about 50–60 seconds on the live rail, and you see the driver's name
  in the app 3–8 minutes before pickup. **Order the real driver's song at booking** — it lands before
  he arrives. The three pre-renders become insurance rather than the plan. No latency number on screen.

### Card 5 — ENG KUTILMAGAN JANR #1
**Partly unshootable as written. Two of its three genres do not exist as labelled.**
- **KILLED:** `BOBOMGA — DRILL`. **There is no drill anywhere in the product.** Nearest shipping
  option is `🎧 Xip-xop`. The render, the picker screen-record and the caption at playbook line 388
  all have to change together. ⚠️ **PLAYBOOK CONTRADICTED — lines 345–407, 388.**
- **ALTERED:** `JAZZ` → `JAZ-LAUNJ`. The button is `🎷 Jaz-launj`, and the same video screen-records it.
- **CUT:** the six-year-old, and the named-minor card. Replace with an adult from the same room.
- **REORDERED:** `BOBOMGA — XIP-XOP` opens; the qaynona beat sits second, with her visibly in on the
  joke and the card saying she chose the genre. A real identifiable elder woman as the object of a
  joke published by her kelin's side on a commercial account is the riskiest non-illegal frame on the
  slate, and "eng kutilmagan" does not fix who is being laughed at.
- **CONFIRMED:** rok ships as `🤘 Rok`.

### Card 6 — «STUDIYAGA BORDIM» DEB ALDADIM
**Shootable, and one frame got better.**
- **UNLOCKED:** the 0:24–0:27 checkout frame. The bot's real screens may appear on camera. A
  fabricated Payme receipt still may not.
- **CONFIRMED:** «Qoʻshiq haqiqiy — faqat rasm soxta edi.» stays on screen and must survive any
  tightening pass. It is the card's whole defence.
- **UNCHANGED:** the Higgsfield studio still generates **no face** at any angle.

### Card 7 — GURUHGA TASHLADIM
**Shootable. One shot-list instruction described two screens that cannot both exist.**
- **RESOLVED:** an account **with** a credit sees the confirm summary and `🎬 Yozib olinsin` and never
  sees a price. An account **without** a credit sees the paywall and never sees `🎬`. Since the card
  burns `15 000 soʻm` at 0:13, **shoot the paywall face on the zero-credit account.**
- **CONFIRMED:** `😂 Hazil` is the literal button, the writer brief is "an affectionate, funny roast",
  and the shared prompt rules forbid profanity, politics, religion, romance, alcohol and real-artist
  references. The playbook's own note is correct. Never write "diss".
- **STRENGTHENED:** "Do not fabricate a Payme receipt — film the bot's own price/confirm screen" now
  stands for a better reason: the real screens beat any mock.

### Card 8 — USTOZGA ATALGAN QOʻSHIQ
**Shootable, but its 0:18–0:23 frame describes a menu item that does not exist.**
- **KILLED:** occasion «kasb bayrami / ustoz». **Not a button.** The operator taps `🎉 Bayram`, or
  `✨ Boshqa sabab` and types it. No on-screen text or caption may name a teachers' occasion as a
  picker option. The teacher-ness comes from the free-text note step, which is a real capability — it
  is just not a labelled occasion. ⚠️ **PLAYBOOK CONTRADICTED — line 552.**
- **HARDENED:** ask her which form of her name she wants sung — first name, full name, or with the
  patronymic — and sing that one. Tick it on the release.
- **VARIABLE:** the countdown is computed from 2026-09-17. Recompute on the actual posting day.

### Card 9 — TORT SAHNAGA AYLANDI
**Shootable. One frame cut, one number stack unverified.**
- **CUT:** the child blowing out the candle. **An adult hand blows it out.** The match cut on the
  smoke works identically and the generated side is unaffected.
- **CONDITIONAL:** «Ismni toʻgʻri aytdi» and «Gulnoza, hech qanday buzilishsiz» ship on a human-listen
  pass or are cut. Do not soften them into a hedge over a take that is still wrong.
- **UNVERIFIED:** `Tort 200 000 · Gullar 40 000` are the playbook's placeholder numbers. Only the
  15 000 is verified. Check them against the day's real receipts — a fabricated comparison on a video
  engineered to be forwarded is not worth two round numbers.

### Card 10 — PUL SOLMA, QOʻSHIQ SOL
**Shootable, essentially unchanged. Three things to verify on the day.**
- **UNCHANGED, NEW REASON:** the 500 000 soʻm transfer mock stays **neutral, never Payme's UI** — not
  because "our processor is fake" (it is real now) but because that shot is not our product.
  ⚠️ **PLAYBOOK CONTRADICTED — line 676**, in reasoning only; the instruction survives.
- **VERIFY:** `90 soniya` against a real delivered file before burning it.
- **VERIFY:** that the bot actually names the delivered file `Gulnoza — tugʻilgan kun` as the chat
  frame shows.
- **OPEN:** the Reels music picker test on the real account decides this card's variant — not the
  account type. Meta's own Music Guidelines say music "may not be available in all countries."

### Shared rules, account setup and the ladder
- **REWRITTEN:** the banned-phrase list. It is shorter than the playbook's and built on different
  reasons. ⚠️ **PLAYBOOK CONTRADICTED — line 761.** The one genuinely false phrase —
  «Telegramdan chiqmasdan» / "pay inside Telegram" / any implication of one tap — stays banned, but
  for a completely new reason: there are no Telegram native payments, the customer leaves for
  `checkout.paycom.uz`, and `prepare_link` is still unbuilt so it is **two taps with a screen between
  them**. The old reason ("our checkout is a stub") is stale, which is exactly how a ban gets relaxed
  by someone who checks the reason and finds it no longer holds.
- **RESOLVED AND STRUCK:** open question 2 (line 782). Do not re-litigate it at 21:30.
- **FIXED:** the account Name field and both bio lines. Two of the three were ungrammatical in sense
  and they are the most-read strings on the account.
- **CONFIRMED:** exactly 5 hashtags, ASCII only, caption and first comment counted together.
- **CORRECTED:** the playbook's claim that "Instagram has stamped @ibadovmusic AI-generated profile"
  is not supported — that label is **opted into** by the account owner, not imposed.
  ⚠️ **PLAYBOOK CONTRADICTED — line 59.**
- **UNRESOLVED:** the "AI mispronounces difficult names" genre still cannot be shown to exist at 1M+
  scale in English, Russian, Hindi or Turkish after a second, harder pass. Card 1 and the whole
  reply-ladder are a bet on a format with no demonstrated ceiling. That is a product decision, not a
  research gap.

---

## 3. THE FACTS

Six questions were flagged UNVERIFIED yesterday. Here is what each one turned out to be.

### FACT 1 — THE PRICE · **VERIFIED**

**A real customer pays 15 000 soʻm (1 500 000 tiyin, UZS) today.** The 7 000 soʻm figure is dead: it
was the live value only until 2026-09-14 16:45, and on the live host every payment intent opened since
16:57 that day has been for exactly 1 500 000 tiyin — 29 of them, without exception, through
2026-09-15 18:28. The deploy script's `_DEFAULT_AMOUNT_MINOR = 700_000` never touched a customer: it
is the `--amount` default of an operator CLI that opens Payme **certification** orders, every row
stamped `is_sandbox=true`, and the bot never imports it. There is exactly one runtime source of truth
— `Settings.single_song_price_minor` — and both the checkout screen and the render gate read that same
field, so a customer cannot be quoted one number and charged another.

On the taxi line: **15 000 soʻm is honest and under-claims.** Yandex Go's official Tashkent Start
tariff is ≤4 600 minimum + 2 500 soʻm/km, so 15 000 soʻm is a real ~4.2 km city ride; crowdsourced
Tashkent figures are higher still (10 000 start + 4 156/km). Under-claiming is the safe direction.
A Tashkent cappuccino averages 28 000–30 400 soʻm, so the song is **about half a coffee** — available
as a stronger line for any card that wants it. For scale if ever needed: 15 000 soʻm ≈ $1.27 at
~11 766 UZS/USD, or ~8.8 bus tickets.

**Consequence.** Every «15 000 soʻm» already burned into cards 1, 2, 3, 4, 5, 8 and 9 is correct and
stands as written. The playbook's digit-free fallback is deleted. Card 4 defaults to the surge
variant. One product, one price: the starter plan (49 000 soʻm, 12 songs) is priced but **not offered**
— `is_starter_plan_offered` ships False, withdrawn by the owner on 2026-09-14 — so no plan number
appears in any frame or caption, and any card showing two price buttons is drawing a screen that no
longer exists.

**The one gap left:** `/etc/bayram/bayram.env` is `root:hbd 0640` and could not be read from outside,
so the value the currently running process loaded is inferred from the deployed code default plus the
intent history. **One operator opens @bayram_uzbot on a phone and screenshots the paywall reading
«💳 Bitta qoʻshiq — 15 000 soʻm».** Thirty seconds, and the shoot needs the screenshot anyway.

### FACT 2 — THE PAYMENT RAIL · **PREMISE REFUTED**

**The deployment is NOT on the stub.** The live host runs `BAYRAM_CHECKOUT_PROVIDER=payme` against the
**production** Payme cashbox (`is_sandbox: false`, merchant `6aa24fd9ee30563de3a1ac22`), at 15 000 soʻm,
with credits enforcement ON, and it has settled **14 real payments** since 2026-09-14 — every one of
which auto-started and delivered a song. The pause switch is not set. The repo's own docs were never
updated and still say the opposite.

The headline splits three ways:

- **A real payment MAY be filmed.** Yes. The rail is live, production, and not paused.
- **The bot's own «✅ Toʻlovingiz oʻtdi.» MAY be filmed.** Yes — it is a real screen the worker sends
  on settlement. **A fabricated Payme receipt still may not be shown.** That prohibition is unchanged.
- **"Pay inside Telegram" — NO, and this is now the only hard no.** There are no Telegram native
  payments, no Stars, no invoices. The bot hands out a link button that opens `checkout.paycom.uz` in
  a browser. The customer leaves the chat. And it is **not one tap**: `prepare_link` appears nowhere in
  the deployed wheel or the repo source, so the flow is
  `💳 15 000 soʻm — 1 qoʻshiq` → `🔗 Sal qoldi` → `🔗 Toʻlash` → Payme.

**One genuine gift for the edit:** settlement-to-delivered measured **38.45 s, 30.18 s and 65.98 s** on
the three real purchases traced, and tap-to-song ran about 50 seconds end to end — an order of
magnitude better than the 7-minute render budget the dossier feared. If any card ever wants a burned-in
timer, roughly one minute is defensible from the host's own journal. **Do not print anything tighter
than ~60 s without re-measuring on the day, and preferably print nothing.**

**Consequence.** Card 4's stub risk note is deleted. Cards 1 and 5's "no payment screen" constraints
can be lifted if a payment helps the cut. Card 7's instruction stays and gets stronger. The shared
rules are rewritten. And nobody has exercised the live rail in ~37 hours — **put one real 15 000 soʻm
purchase through it on the shoot morning before a camera is pointed at anything.**

**Two things a human owns.** (a) The host is taking real production money while `environment` is `dev`
on both the bot and the gateway, which downgrades two of the money refusals to warnings. Fixing it is a
write and a restart; nothing about the shoot depends on it. (b) Treat **"Payme is wired and armed"** as
verified and **"a stranger's card will settle"** as unverified — the boot line says `is_sandbox: false`
against a merchant id the host inventory recorded as a *sandbox* cashbox on 2026-09-11, and that fact
lives in the Payme cabinet, not on this host. No payment was attempted.

### FACT 3 — WHAT THE PICKER ACTUALLY CONTAINS · **VERIFIED**

**Four of the six flagged options ship; two do not.**

| Option | Ships? | The literal label |
| --- | --- | --- |
| Shashmaqom | **yes** | `🎻 Shashmaqom` (genre) |
| rok | **yes** | `🤘 Rok` (genre) |
| jazz lounge | **yes, spelled differently** | `🎷 Jaz-launj` (genre) — not "jazz lounge" |
| the roast occasion | **yes** | `😂 Hazil` (occasion, enum PRANK) |
| drill | **NO** | nothing close. Nearest shipping option is `🎧 Xip-xop` |
| «kasb bayrami / ustoz» | **NO** | nearest are `🎉 Bayram` (holiday) or `✨ Boshqa sabab` (custom) |

The deployed wheel was diffed against the repo: the Genre enum, the Occasion enum, the wizard order and
every Uzbek label are **byte-identical**, so the strings in Pack 1 and Pack 2 are what a phone will
actually record.

**Three more hard facts the slate did not account for.**
1. **Greetings / spoken TTS do not ship and are invisible to users.** `greetings_per_kit` defaults to 0,
   both greeting stages are filtered out of the progress plan, and 30 days of production logs show zero
   greeting synthesis — the only TTS traffic on the host is speech-to-**text**, used to re-listen to the
   sung name. No card may show or promise a spoken greeting. None currently does; keep it that way.
2. **A first-time account is asked for its PHONE NUMBER before it ever reaches a picker.** A
   screen-recording made on a fresh account captures «📱 Endi telefon raqamingizni qoldiring…» and it
   cannot be edited out without the cut being visible. **Shoot on an already-onboarded account.**
3. **An account with no credits never sees the confirm summary.** The paywall replaces it and carries
   no `🎬 Yozib olinsin` button. To film the summary screen, someone with admin access must put a credit
   on the filming account first — that is a production write and a human must do it.

**Consequence.** Card 5 drops drill and relabels jazz. Card 8 changes its occasion beat. Card 7 picks
one screen and shoots that one. Any frame quoting a price reads 15 000 soʻm with a non-breaking space,
one product, no 49 000 plan.

### FACT 4 — WHAT THE PRONUNCIATION MACHINERY ACTUALLY DOES · **VERIFIED, AND IT IS NOT WHAT THE SLATE SELLS**

The mechanism is real and better than most marketing claims — but **it does not verify the one thing
the slate sells.** Two facts decide the shoot.

**(1) What the bot guarantees is the SPELLING on screen and a listen-back-and-redo loop — not that
gʻ/oʻ/x/q are sung correctly.** The acoustic verifier reduces both the intended name and the
speech-to-text transcript to a "sound key" that deliberately folds `gʻ→g`, `oʻ→o`, `x→h`, `q→k` and
squeezes doubled letters. Measured on the real code:

```
name_similarity("Gʻulomjon", "Gulomjon") = 1.000
name_similarity("Gʻayrat",   "Gayrat")   = 1.000
name_similarity("Oʻgʻiloy",  "Ogiloy")   = 1.000
name_similarity("Toʻlqin",   "Tolkin")   = 1.000
name_similarity("Qodirjon",  "Kodirjon") = 1.000
```

The loop is **structurally incapable** of hearing the difference the whole slate is about.

**(2) The first spelling the bot sends the music vendor is the mark-STRIPPED one, by default and in
production.** The candidate order ships as `stripped, canonical, hyphenated, ascii, phonetic`. So for
Gʻayrat the vendor is asked to sing **"Gayrat"**, and for Oʻgʻiloy **"Ogiloy"** — character for
character the wrong forms card 2 puts on screen as the grievance. Since the verifier scores that a
perfect 1.000, it passes on attempt 1 and the correct spelling is never tried. Production logs confirm:
all 24 verification events shipped `"strategy": "stripped"`, 22 of them at one render.

**The counterintuitive part, and the most useful fact for casting:** the 0.85 gate is computed on the
folded key, so tolerance scales with length. **Key ≤6 characters allows ZERO errors; 7–13 allows one;
14+ allows two.** A long name is therefore more likely to be shipped *wrong* — `Xurshidabegim` sung as
"Kurshidabegim" scores 0.923 and **passes** — while a short name gets re-rolled even when it was fine.
Card 1's two names sit on opposite sides of this, which is precisely why Xurshidabegim needs the human
listen most.

**The honest claim is the bot's own wizard copy, which is already true and already on screen:**
«Qoʻshiq yozilgach, shu soʻzni tinglab koʻraman va notoʻgʻri chiqqan boʻlsa, qaytadan yozaman.»
Film that sentence instead of asserting the gʻ.

**Three consequences, all in copy, none in the shot lists.**
1. Card 1's gʻ guarantee is deleted (Pack 2 §3).
2. Card 2's «Ogiloy» / «Gayrat» beat is a self-own unless a human clears the audio. The card's own risk
   note already demanded two unrelated native speakers; that is no longer optional, it is **the only
   evidence that exists**, and it must be done on the exact takes that appear in the cut.
3. **No number, ever.** 21 passes out of 24 over six days is not a success rate and must not appear on
   screen, in a caption, in a deck, or in a reply to a sceptic — **nor internally, as if it were
   evidence.** Nothing in this repository measures sung pronunciation success. Not one test, benchmark
   or fixture. The bake-off designed to measure it was never run.

**Four things that are true and would otherwise be discovered by a technical commenter.** (a) A re-roll
re-renders the **whole track** and returns a **different song** — inpainting does not fire on this
account and fails silently — so «faqat ismni qayta yozamiz» is false. (b) There is **no re-roll button**
in the bot, so «qayta yozamiz» is a human promise or nothing. (c) The speech-to-text is handed the whole
song, not the isolated name chunk, so a body verse containing the name can satisfy the check while the
hook is wrong. (d) `best_score` is logged as 0.0 on every successful verification — a logging defect, not
a shoot blocker, but any dashboard reading that field will report zero confidence on every pass.

### FACT 5 — THE PLATFORM CLAIMS · **VERIFIED, MIXED**

Six web claims settled.

| Claim | Status | What to do |
| --- | --- | --- |
| **5 hashtags per post** | **VERIFIED** | Exactly 5, ASCII, and captions **and first comments count together** — splitting buys no extra slots. Over-tagging blocks publishing or drops the excess. Report dated 18 Dec 2025; say "mid-December 2025" if a date is ever spoken. |
| **Anti-aggregator rule extended to photos and carousels, 30 Apr 2026** | **VERIFIED, exact date** | It is **account-level recommendability**, not a per-post penalty, and recovery is documented once most of the last 30 days is original. This is why one clean master is uploaded natively per platform and never downloaded-and-reposted. |
| **AI labelling** | **VERIFIED, with a correction** | Correctly labelled AI is **not** demoted; the reach penalty attaches only to accounts featuring a synthetic **person** that skip the label. Ordinary AI tool use is explicitly out of scope. **But the playbook's line that "Instagram has stamped @ibadovmusic AI-generated profile" is almost certainly wrong — that label is opted into, not imposed.** ⚠️ **PLAYBOOK CONTRADICTED — line 59.** The real risk is the *other* label: the per-post "AI info" tag fires **automatically** off C2PA/IPTC metadata written by generators and editors, so check what our pipeline and CapCut write on export and self-disclose deliberately. |
| **"A send is worth 3–5x a like"** and every hook-retention number | **REFUTED as Meta-sourced** | Delete the 3–5x multiplier, "1 send = 15 likes", the send-rate bands, the 1.3-second fixation stat, "72% of viral Reels use jump cuts in 3s", "58% unfollowed for misleading hooks", "50% drop before second 4" — from every card, caption, deck and client document. The 1.3-second study appears to be **invented**. Keep only the qualitative direction: sends-per-reach is the signal that moves non-follower reach. No multiplier attached. |
| **The t.me link** | **VERIFIED, and solved better than feared** | Instagram's in-app browser will not hand off to Telegram — but **Telegram already serves the escape hatch**, and it was checked on our own bot: `t.me/bayram_uzbot?start=ig_bio` returns a Start Bot button whose href carries `&start=ig_bio`. The payload survives. **Do not commission a redirect page** — this already is one. The only cost is one extra tap, and the only copy change is to stop implying the link jumps straight into the bot. |
| **The "AI mispronounces names" genre** | **STILL UNKNOWN, in the direction that hurts** | Two research passes in four languages found no 1M+ example. What *is* proven at scale is the **human** version — one creator's "croissant = Prashant" reel at 15M views, 5K→30K followers in a week, a brand renaming its account and shipping packaging off it. Shoot card 1 so the failing voice is unmistakably a generic machine and the joke survives even if the AI genre never materialises, and read three-second skip rate on the first three posts before funding 20–50 reply videos. |

**Also, and the slate never named it:** Meta's Music Guidelines say music "may not be available in all
countries." The Business-vs-Creator music split is real in practice but **Meta documents none of it**,
and account type may not even be the binding variable. So **opening the picker on the real account is
now mandatory and its result decides card 10** — not the account-type choice. **Do not put "switch the
category to Entrepreneur" in any brief**: it is blog folklore, it changes the interface and not the
licence, and every source that endorses it also says it works inconsistently and varies by region.

### FACT 6 — THE CULTURAL AND LEGAL LANDMINES · **VERIFIED**

Both landmines are real; they are not the same size. And a third one turned up that nobody asked about.

**SHASHMAQOM: usable, with conditions.** No case exists anywhere — searched in Uzbek Latin, Uzbek
Cyrillic, Russian, Azerbaijani and English — of anyone being publicly criticised for AI-generating
maqom, mugham or any UNESCO-listed tradition. The settled Uzbek expert position is narrower and more
useful than "don't": **AI as a helper and an archive is accepted; AI as a replacement for the
ustoz–shogird master tradition is not.** A 90-second gift song in shashmaqom style, given by a family to
its own grandmother, sits on the accepted side. What crosses the line is **register and labelling, not
AI**: calling a generated track *Shashmaqom* when it is generic Central-Asian-flavoured pop; putting
maqom under a "wrong genre" label; `#shashmaqom` on anything comedic. Maqom is state-patronised, which
means a mockery frame escalates past a comment thread — and equally that a respectful frame is aligned
and safe. UNESCO's own ethical principles support adaptation and name the real threats as
"decontextualization, commodification and misrepresentation".

**THE DEAD ARTIST: the cut stands, and a labelled generic retro performer does NOT clear the bar.**
There is no generic 1970s Uzbek estrada face for a model to reach for — the era is one man wide (Botir
Zokirov, 1936–1985, founder of Uzbek estrada), and every other plausible output is either recently dead
and still mourned (Sherali Joʻrayev, d. 4 Sep 2023) or alive and litigable (Farrux Zokirov, b. 1946,
Yalla's director since 1976). A chyron does not cure a likeness — and Uzbek audiences have spent 2026
learning that a famous face in an ad is a casino scam. If retro is ever wanted, **shoot it practically
with a real person in a real jacket**: cheaper than the generation credits, and it carries none of the
risk.

**The legal ground moved while the dossier was being written.**
- **Law ЗРУ-1115 of 21 January 2026 is IN FORCE NOW.** Unlawful processing of a person's personal data
  **using AI**, plus distribution online, is an administrative offence: **50–100 BRV ≈ 20.6–41.2 million
  soʻm, plus confiscation of the equipment used.** That describes what this slate does — a real
  person's name, face and generated singing voice, published commercially. Clean consent is the whole
  defence.
- **A separate image-consent law** (new Civil Code art. 100-1) passed the Legislative Chamber **121–0 on
  7 October 2025** and puts a dead person's image in the hands of their **heirs**, an under-16's in the
  hands of their **parents**, and permits public-place filming only "to reflect the general process".
  Whether it has been signed is unconfirmed — **this pack assumes it is live.**
- AI **content marking** does not land until 1 March 2027, and then on large platforms rather than
  authors. So Uzbek law does not require us to label AI today. Instagram's rules do, and we label anyway.

**THE THIRD THING, and it is the one nobody asked about.** On **10 September 2026 — one week ago — the
Senate approved the law replacing `gʻ→ğ`, `oʻ→ö`, `sh→ş`, `ch→ç`.** The slate's opening post is called
«Gʻ TESTI» and every card's on-screen text is built on U+02BB. **Keep the current spelling** — the law
is unsigned and has no transition dates — **never editorialise about the reform in a caption or a
reply**, and have one neutral canned answer ready for «bu harf oʻzgaryapti-ku» comments (Pack 2 §14,
Pack 5 §4 template G).

**Religion, checked and cleared.** Birthday celebration is genuinely contested in Uzbek religious Q&A
traffic, but it is not a blocker: the mainstream position is permissive, the product already widens past
birthdays, and the brand pack has already thought about the religious reading of the word *bayram*.
Rule for the account: **never argue theology in a reply**; the canned line points at the bot.

---
## 4. PACK ONE — THE RENDER GATE

**Wednesday 17 Sept, 18:30–22:00 (Tashkent, UTC+5). One person owns this session.** It runs before
anything else, because nothing tomorrow can be shot from a song that was not rendered and graded
tonight.

Four facts from this morning override the playbook. Read them once:

1. **The price is 15 000 soʻm and the Payme rail is LIVE production.** Real payments settle. You may
   film a real payment and the bot's own `✅ Toʻlovingiz oʻtdi.` screen. You may never fabricate a Payme
   receipt, and you may never say «Telegramdan chiqmasdan» / "pay inside Telegram" — the customer leaves
   for `checkout.paycom.uz` in a browser, and it is TWO taps, not one.
2. **There is no drill genre and no «kasb bayrami / ustoz» occasion.** Card 5's bobo gets
   **🎧 Xip-xop**. Card 8's occasion is **✨ Boshqa sabab** (typed) or **🎉 Bayram**. "jazz lounge" is
   spelled **🎷 Jaz-launj**.
3. **The bot's own "verified" verdict is deaf to the thing we are selling.** Its checker folds gʻ→g,
   oʻ→o, x→h, q→k and squeezes doubled letters. It scores "Gulomjon" against "Gʻulomjon" at **1.000**.
   The first spelling it sends the vendor is the **mark-stripped** one. Only a human ear decides tonight.
4. **The playbook's 22:00 fallback is wrong.** It says cards 1 and 7 "need no verified render" — but
   card 1 plays a real Bayram song at 0:07–0:13 and card 7 plays a real hazil song from frame one. Both
   need passing names. The real fallback is in §4.4 below. ⚠️ **PLAYBOOK CONTRADICTED — line 730.**

---

### 4.1 THE RENDER LIST — 22 orders

**How to read the risk column.** Strip the name to its sound key by hand: gʻ→g, oʻ→o, x→h, q→k, y→i,
double letters→single. Count the letters. **≤6 letters = the machine allows ZERO errors** (it will
re-roll a good take). **7–13 = one error. 14+ = two errors** — which is why a long name is the one most
likely to be shipped *wrong*. "Sung as" is the spelling the vendor is actually asked to pronounce on
attempt 1.

| # | Name — type it EXACTLY | Sung as (rank 0) | Key / errors allowed | Occasion | Genre | Voice | Lang | Card | E/B |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Gʻulomjon | Gulomjon | gulomjon 8 / 1 | 🎂 Tugʻilgan kun | 🎤 Pop | 👨 Erkak ovozi | 🇺🇿 lotin | 1 | **E** |
| 2 | Xurshidabegim | Xurshidabegim | hurshidabegim 13 / **1** | 🎂 Tugʻilgan kun | 🎤 Pop | 👩 Ayol ovozi | 🇺🇿 lotin | 1 | **E** |
| 3 | Gulchehra | Gulchehra | gulchehra 9 / 1 | 🎶 Sababsiz | 🌟 Oʻzbek estradasi | 👩 Ayol ovozi | 🇺🇿 lotin | 2 hero | **E** |
| 4 | Gʻayrat | **Gayrat** | gairat 6 / **0** | 🎶 Sababsiz | 🎤 Pop | 👨 Erkak ovozi | 🇺🇿 lotin | 2 | **E**⚠ |
| 5 | Oʻgʻiloy **-25** (card 2 woman) | **Ogiloy** | ogiloi 6 / **0** | 🎶 Sababsiz | 🎤 Pop | 👩 Ayol ovozi | 🇺🇿 lotin | 2 | **E** |
| 6 | Abdulaziz | Abdulaziz | abdulaziz 9 / 1 | 🎶 Sababsiz | 📻 Retro estrada | 👨 Erkak ovozi | 🇺🇿 lotin | 2 | **E** |
| 7 | Oʻgʻiloy **-79** (grandmother — DIFFERENT PERSON, separate order) | **Ogiloy** | ogiloi 6 / **0** | 🎶 Sababsiz | 🎻 Shashmaqom | 👩 Ayol ovozi | 🇺🇿 lotin | 3 | **E** |
| 8 | ______ qaynona's real name | fill in | fill in | 🎂 Tugʻilgan kun | 🤘 Rok | 👩 Ayol ovozi | 🇺🇿 lotin | 5 | **E** |
| 9 | ______ bobo's real name | fill in | fill in | 🎂 Tugʻilgan kun | **🎧 Xip-xop** (NOT drill) | 👨 Erkak ovozi | 🇺🇿 lotin | 5 | **E** |
| 10 | ______ brother's real name | fill in | fill in | 🎂 Tugʻilgan kun | 🎸 Akustik ballada | 👨 Erkak ovozi | 🇺🇿 lotin | 6 | **E** |
| 11 | Doniyor | Doniyor | donior 6 / **0** | 😂 Hazil | 🎧 Xip-xop | 👨 Erkak ovozi | 🇺🇿 lotin | 7 | **E** |
| 12 | Nodira Karimovna | Nodira Karimovna | nodirakarimovna 15 / **2** | ✨ Boshqa sabab → type «ustozimga» | 🌟 Oʻzbek estradasi | 👩 Ayol ovozi | 🇺🇿 lotin | 8 | **E** |
| 13 | Nodira (first-name fallback) | Nodira | nodira 6 / **0** | ✨ Boshqa sabab | 🌟 Oʻzbek estradasi | 👩 Ayol ovozi | 🇺🇿 lotin | 8 | **E** |
| 14 | Gulnoza | Gulnoza | gulnoza 7 / 1 | 🎂 Tugʻilgan kun | 🌟 Oʻzbek estradasi | 👩 Ayol ovozi | 🇺🇿 lotin | 9 | **E** |
| 15 | Qodirjon | Qodirjon | kodirjon 8 / 1 | 🎶 Sababsiz | 🎤 Pop | 👨 Erkak ovozi | 🇺🇿 lotin | 4 driver | **E** |
| 16 | Xayrullo | Xayrullo | hairulo 7 / 1 | 🎶 Sababsiz | 🎤 Pop | 👨 Erkak ovozi | 🇺🇿 lotin | 4 driver | **E** |
| 17 | Toʻlqin | **Tolqin** | tolkin 6 / **0** | 🎶 Sababsiz | 🎤 Pop | 👨 Erkak ovozi | 🇺🇿 lotin | 4 driver | B |
| 18 | ______ backup grandmother | fill in | fill in | 🎶 Sababsiz | 🎻 Shashmaqom | 👩 Ayol ovozi | 🇺🇿 lotin | 3 | B |
| 19 | ______ spare street subject A | fill in | fill in | 🎶 Sababsiz | 🎤 Pop | either | 🇺🇿 lotin | 2 | B |
| 20 | ______ spare street subject B | fill in | fill in | 🎶 Sababsiz | 🎤 Pop | either | 🇺🇿 lotin | 2 | B |
| 21 | ______ second prank subject | fill in | fill in | 🎂 Tugʻilgan kun | 🎸 Akustik ballada | 👨 Erkak ovozi | 🇺🇿 lotin | 6 | B |
| 22 | Gulnoza — take 2 for the 95.8 BPM bed | Gulnoza | gulnoza 7 / 1 | 🎂 Tugʻilgan kun | 🕺 Raqs / elektron | 👩 Ayol ovozi | 🇺🇿 lotin | 10 | B |
| — | **Amirxon (6 y.o.)** | Amirxon | amirhon 7 / 1 | — | 🎷 Jaz-launj | — | — | 5 | **BLOCKED — do not order until the minors decision is signed** |

**Honest count: 16 essential + 6 backup = 22 orders.** Each order may internally re-render up to 3 times
chasing the name — that costs no extra credit and no extra typing, so the vendor may render up to 66
tracks tonight.

**Cost.** 22 orders × 90 s = 33 minutes of music. At the repo's rate `BAYRAM_MUSIC_USD_PER_MINUTE=0.15`
that is **≈ $4.95 ESTIMATED**, and **≈ $14.85** if every order burns all three internal attempts. That
0.15 is a *placeholder list price* the repo itself labels ESTIMATED — it is not a vendor invoice.
Lyric-writing cost ships unpriced (0.0). In customer money, 22 credits = **330 000 soʻm** if bought
rather than granted.

⚠ **Row 4, Gʻayrat.** He is one of the four real faces in card 2 and hears his own name at 0:30. The
**absolute ban is on the mangled "GAY-rat" reading** — it must never be sung, burned, spoken or
captioned, in card 1 or anywhere. One reading of the name findings restricts him to the document
cutaway only. **Decide this before 19:00 and write the decision down.** If in doubt, order the render
anyway and decide at 22:00 with the audio in hand.

---

### 4.2 ORDER OF OPERATIONS

#### 18:30 — pre-flight (nothing renders until all six are ticked)

- [ ] **Three Telegram accounts, three real SIMs, all onboarded BEFORE 19:00.** A fresh account is asked
  for its language and then its **phone number** («📱 Endi telefon raqamingizni qoldiring…» + a
  reply-keyboard button «📱 Raqamni yuborish») before it ever sees a picker. Doing that at 19:05 costs
  you the session.
  - **A** and **B** = the render accounts.
  - **C** = the paywall/screen-record account. **Never grant it credits** — a zero-credit account is the
    only way to film the price screen.
- [ ] **Credits on A and B.** 11 songs each + headroom → grant **15 each**. Admin panel → the user →
  grant credits; it needs an **ADMIN** role plus a **step-up password re-auth**, and one call caps at
  **100 credits**. No ADMIN login available → fall back to buying at 15 000 soʻm a credit on the live rail.
- [ ] **Check today's lyric budget on A and B.** Each account gets **20 lyric writes per UTC day**, and
  the UTC day rolled over at **05:00 this morning Tashkent time** — anything typed today already counts.
  If either account has been used today, use a fresh one.
- [ ] Both render phones: DND on, screen-record permission granted, battery >80%, storage >4 GB.
- [ ] The names for rows 8, 9, 10, 18–21 are filled in, **spelled by the person themselves**, not guessed.
- [ ] Every subject's signed Uzbek likeness release is in hand or is confirmed for tomorrow **before**
  the camera rolls.

#### The three limits that will actually bite, and the numbers

| Limit | Value | What it means tonight |
|---|---|---|
| Orders in flight, per account | **1** | You cannot order song 2 until song 1 has been delivered. Two accounts = the whole bandwidth. |
| Simultaneous music renders, whole deployment | **2** | The worker self-throttles; a third order just waits. You cannot go faster by adding phones. |
| Lyric writes per account per UTC day | **20** | 11 songs + rerolls is close to it. Stay ≤18 per account. |
| Lyric rewrites per draft | **5** | Pressing «🔄 Boshqa matn yozilsin» spends one. |
| Inbound taps per account | **30 / 60 s** | One wizard walk is ~10. Don't run two orders inside one minute on one phone. |

**So: two operators, two accounts, ordering alternately. A third ordering phone buys nothing.**

#### 19:00 — queue in this order (first = most irreplaceable)

1. **Row 7, Oʻgʻiloy-79, Shashmaqom** — card 3's take is unrepeatable and Shashmaqom is the one genre
   nobody has heard the product do. If this fails, everything downstream changes.
2. Rows 1, 2 (card 1 — the opening post).
3. Row 3 (Gulchehra — card 2's hook and its ORIGINAL AUDIO).
4. Rows 11, 14 (card 7, card 9).
5. Rows 12, 13 (card 8 — highest-risk render on the slate; order both the patronymic and the fallback).
6. Rows 4, 5, 6 (rest of card 2).
7. Rows 8, 9, 10 (house block).
8. Rows 15, 16 (drivers).
9. Backups 17–22, only if the clock allows.

**Per order, about 4 minutes:** ~2 min of typing through the nine steps, up to 1 min on «✍️ … soʻzlarni
yozayapman… bu bir daqiqagacha oladi.», then 30–70 s of render. 11 orders per account ≈ 50–60 minutes.

**NEVER press «✍️ Oʻz matnim».** That path switches the whole name subsystem off — no name step, no
listen-back, no verification. A take from it cannot be used in any card that makes a pronunciation claim.

#### When one fails — read the message, then act

| What the bot says | What it is | Do this |
|---|---|---|
| «Oldingi qoʻshigʻingiz hali tayyorlanmoqda…» | The 1-in-flight cap | Wait. Do **not** press /start — it throws the draft away. |
| «Bir vaqtda juda koʻp boʻldi — …» | Tap throttle | Stop for 60 seconds. |
| «Bu qoʻshiq uchun allaqachon 5 ta matn yozdim.» | Per-draft lyric cap | Accept the lyric or send your own text. Don't /start to farm more — it spends the daily budget. |
| «Bu hisob uchun bir kunda ruxsat etilgan qadar matn yozib boʻldim (20). Keyingisini … kuni yozsam boʻladi.» | Daily budget spent | That account is **finished until 05:00**. Move to the other one. |
| «Hozircha limitingizdagi barcha qoʻshiqlardan foydalandingiz.» | Out of credits | Grant more, or buy. |
| «Talaffuzni mukammal qila olmadim, shuning uchun eng yaqin variantni yubordim.» | **The bot itself gave up after three internal renders** | **Automatic FAIL.** No audition needed. Re-order once; if it says it again, replace the person. |
| Nothing arrives after 10 minutes | Queue retry ladder (up to 900 s × 5 tries) | Wait to 15 minutes. Then re-order once — it costs a credit and a lyric write. |

**Do NOT change `BAYRAM_NAME_CANDIDATE_ORDER` on the host tonight.** It would change what the vendor is
asked to sing for every name and invalidate every take already graded. That is a production write and it
is not this session's decision. The alternative — accept that no on-camera claim says the gʻ/oʻ is
**sung** — needs no host change and is what every line of copy in Pack 2 already assumes.

---

### 4.3 THE AUDITION PROTOCOL — 21:30

**Two native speakers who are not on the production team.** They do not see the bot's verdict, do not
see this table's risk column, are not told which name is "supposed" to be hard, and do not grade in each
other's hearing.

**They are asked one question per take:** «Bu ism toʻgʻri aytildimi?» Pass or fail. No scale, no comments
needed.

**A take FAILS if any of these is true:**
- the ʻ in gʻ or oʻ is not audible — it is sung as a plain g or o (**this is the most likely failure and
  it is the one the machine cannot hear**)
- q is sung as "k" or "kw" (Qodirjon → "Kodirjon")
- x is sung as "k" or a hard "kh" instead of the soft h
- a doubled consonant is dropped (Muhammad → "Muhamad")
- a whole syllable is wrong, or the stress lands so it becomes another word
- it is not the form that person actually uses for themselves
- the delivery carried «Talaffuzni mukammal qila olmadim…» — fail on sight
- **the two graders disagree.** Only a unanimous pass is a pass.

**The rules, in order of how badly they are broken under time pressure:**
1. **Replace the NAME, never soften the claim.** A failed take means a different person is in that shot.
   It never means «birinchi marta toʻgʻri aytishdi» becomes a weaker sentence over a take that is still
   wrong.
2. **The take that passed is the take that goes in the cut.** A re-render is a new lottery ticket — the
   whole track regenerates, because the "re-record only the name" mechanism does not fire on this
   account. Never re-render after grading.
3. **Two re-orders per name, maximum.** Then drop the subject and move to a backup.
4. **No number, ever.** No pass rate, no count, no "X out of Y" — not on screen, not in a caption, not in
   a comment reply, not in a deck, not internally as if it were evidence.

**The log — fill this in on paper or in a note, one row per take:**

| # | File | Name as written | Order time | Take | Grader 1 (P/F) | Grader 2 (P/F) | VERDICT | Bot said (ignore) | Action |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20260917_c01_Gulomjon_… | Gʻulomjon | | t1 | | | | | |
| 2 | 20260917_c01_Xurshidabegim_… | Xurshidabegim | | t1 | | | | | |
| 3 | 20260917_c02_Gulchehra_… | Gulchehra | | t1 | | | | | |
| 4 | 20260917_c02_Gayrat_… | Gʻayrat | | t1 | | | | | |
| 5 | 20260917_c02_Ogiloy-25_… | Oʻgʻiloy | | t1 | | | | | |
| 6 | 20260917_c02_Abdulaziz_… | Abdulaziz | | t1 | | | | | |
| 7 | 20260917_c03_Ogiloy-79_… | Oʻgʻiloy | | t1 | | | | | |
| … | *(one row per order, 22 rows)* | | | | | | | | |

Graders sign the bottom of the sheet with their names and the time. **That sheet is the only evidence
that exists for the claim this whole account is built on.**

---

### 4.4 THE GO/NO-GO GATE

| Time | Must be true | ✓ |
|---|---|---|
| 18:30 | Three accounts onboarded, credits on A and B, lyric budget clean, names filled in | ☐ |
| 19:00 | Row 7 (Shashmaqom grandmother) ordered — first, before anything | ☐ |
| 19:30 | Phone tests started in parallel (§4.5) — they do not wait for renders | ☐ |
| 20:30 | **Checkpoint 1:** all 16 essential renders delivered and downloaded | ☐ |
| 21:00 | **Last order that can still be graded tonight.** After 21:00 nothing new is ordered | ☐ |
| 21:30 | Both graders in the room, headphones on, sheet printed | ☐ |
| 22:00 | **THE GATE** | ☐ |

**At 22:00, block by block:**

| Block | Shoots only if | Otherwise |
|---|---|---|
| **Card 1** (08:00–09:00) | **Gʻulomjon AND Xurshidabegim** pass | Both fail → card 1 does not shoot. One passes → shoot it as a one-name cut. *(Also requires ≥2 legible competitor failures from the 20:00 bench.)* |
| **Card 2 street block** (09:00–12:00) | **Gulchehra passes** (mandatory — hook and original audio) **AND ≥2 of** Gʻayrat / Oʻgʻiloy-25 / Abdulaziz | Gulchehra fails → the reaction half does not shoot; the confession half still does (see below). |
| **HOUSE BLOCK** (13:00–17:30) | **Card 3:** Oʻgʻiloy-79 passes. **Card 5:** qaynona AND bobo pass. **Card 6:** brother passes. **Card 9:** Gulnoza passes. Each card is independent | Any one fails → that card drops out; the block still shoots for the cards that passed. All four fail → no house block. |
| **Card 7** (18:00–19:00) | **Doniyor passes** | Fails → swap to the second friend and re-order tomorrow morning (one order, ~4 min, needs a free credit). |
| **Card 4** (19:00–22:00) | ≥1 driver name passes **OR** the live-order plan is approved (below) | Neither → the rides still happen as A-roll only. |
| **Card 8** (Day 2) | Nodira Karimovna passes, **or** the Nodira fallback passes | Both fail → card 8 moves to 8 March with a different recipient. |

**Card 4's better option:** tap-to-song ran about **50–60 seconds** on the live rail. You see the
driver's name in the ride-hailing app at booking, which is 3–8 minutes before pickup. **Order the real
driver's song at booking** — it lands before he arrives. The three pre-renders are insurance, not the
plan. (Needs one spare credit per ride on the phone in the car, and no on-camera latency claim ever.)

**THE HARD RULE — if nothing passes by 22:00, the house block does not shoot.** Tomorrow is still a
shooting day, and this is exactly what it is:

1. **08:00–09:00 — Card 1's A-half only.** Cut the competitor failures captured at 20:00 tonight into a
   6-second asset and bank it. Do not publish half a card.
2. **09:00–12:00 — Card 2's CONFESSION half, fully.** Four people saying «Gulya emas. Gulchehra.» —
   0:00 to 0:20 of the card, no song, no earbud, no reaction beat. This is the half that needs eight
   subjects and a city block, and it is the hardest thing on the slate to re-stage. The reaction half is
   a one-person pickup at the same location next week.
3. **13:00–17:00 — the B-roll bank, in the house you already booked:** the real cake and a real orange
   candle, the kitchen, the dasturxon and the light, the red bedsheet / cream hat / candle set for card
   10, the neutral (non-Payme) transfer mock. All of it is needed later and none of it needs a song.
4. **19:00–22:00 — the taxi A-roll:** hands, dashboard, fare screen, three rides, no song playing. Card 4
   is publishable from that footage alone.
5. **All day — signed releases** from every subject, covering organic posting, paid boosting, re-cuts and
   the AI processing of their name and voice. Get them now while the people are in front of you.
6. **Tonight+1, 19:00 — re-run this gate** with replacement names.

**What you do NOT do:** shoot a reaction to a failed take, cut an ungraded song into anything, or shoot
the house block "and fix it in the edit". The grandmother hears her name for the first time exactly once.

---

### 4.5 THE PHONE TESTS — 19:30, in parallel with the renders

#### TEST 1 — CapCut renders U+02BB
On the **exact shoot phone**, in the **exact title font and the exact karaoke/auto-caption style**, type
each of these at title size:

```
Oʻgʻiloy
Gʻulomjon
Gʻayrat
Xurshidabegim
qoʻshiq
toʻgʻri
Oʻzbekcha
15 000 soʻm
```

- **Pass** = every ʻ renders as a raised turned comma of the same height and weight, not `'` `` ` `` `´`
  `’` and not a tofu box — **in the EXPORTED file**, not only in the editor preview, and **with the
  animation/karaoke timing applied**.
- Also check **15 000** does not wrap between the 15 and the 000. The space in it is a no-break space
  (U+00A0) — copy the string, do not retype it with the spacebar.
- **Fail →** install a Latin-Extended font tonight, or pre-render every text card as a 1080×1920 PNG. Do
  not "fix it tomorrow".

#### TEST 2 — the t.me link, iOS **and** Android
Put `t.me/bayram_uzbot?start=ig_bio` in the bio (or a story link) and **tap it from inside Instagram** —
not from Safari or Chrome.

- **Expected and normal:** Instagram's in-app browser opens Telegram's own page, "If you have Telegram,
  you can launch Bayram — Tabriklar, Qoʻshiqlar right away", with a **Start Bot** button. That is **two
  taps**, and the `?start=ig_bio` payload survives it. **Do not commission a redirect page** — this
  already is one.
- Record: iOS taps to reach the bot ____ · Android taps ____ · did the bot open the chat ☐ · did it greet
  in the expected language ☐
- Repeat once with `?start=ig_gtest`.
- **Copy rule that falls out of this test:** no caption, card or voiceover may imply the link jumps
  straight into the bot, or that anything here is one tap.

#### TEST 3 — the music picker, on the real account, in Uzbekistan
New Reel → Audio → search. **Screenshot it.** Write down: is any current Uzbek chart track visible? Is
Peshta there? ☐ yes ☐ no

This decides card 10's variant. **Do not switch the account type or set the profile category to
"Entrepreneur" to get music** — that is folklore, it changes the interface and not the licence, and
Meta's own Music Guidelines say music "may not be available in all countries" regardless.

#### TEST 4 — screen-record every bot flow the cards need
Capture on an **already-onboarded** account (a fresh one shows the phone-number request, which must never
appear in a video engineered to be forwarded). DND on, no banners.

- **Card 1 (0:07–0:13):** type `G'ulomjon` with an ordinary phone apostrophe, then capture the bot handing
  it back with the real ʻ. **The best frame in the whole product is step 6:** «Men uni shunday
  kuylayman:» with the name in a bold blockquote — it is the only screen that renders the mark intact.
  Then the audio file arriving.
- **Card 3 (0:17–0:20):** occasion screen → genre list scrolled to **«🎻 Shashmaqom»** → the name
  «Oʻgʻiloy» in the field. Frame so **«✍️ Oʻz matnim» is out of shot or clearly unpressed**.
- **Card 4 (0:10–0:14):** name typed, occasion + genre tapped, file arriving. 2× speed.
- **Card 5 (0:03–0:06):** genre picker scrolled fast, stopping on **«🤘 Rok»**. It is one column of ten
  plus a nav row, so it scrolls — frame for the scroll.
- **Card 6 (0:24–0:27):** name typed, genre + voice tapped, file arriving.
- **Card 7 — pick ONE of these two; they cannot both exist on one account:**
  - (i) **paid face** (needs a credit): «<b>{name} uchun qoʻshiq</b>» summary + **[🎬 Yozib olinsin]** —
    shows no price.
  - (ii) **paywall face** (needs the zero-credit account C): «🔒 **Soʻzlar sizniki. Pul yozib olishga
    toʻlanadi.**» / «💳 Bitta qoʻshiq — **15 000 soʻm**» / **[💳 15 000 soʻm — 1 qoʻshiq]**, then the link
    screen «🔗 Sal qoldi.» + **[🔗 Toʻlash]**. **Recommended** — it carries the price.
- **Card 8 (0:18–0:23):** full name in Uzbek Latin. **«kasb bayrami / ustoz» is not a button.** Decide now
  and record only that: **✨ Boshqa sabab** + typed text, or **🎉 Bayram**. Then 🌟 Oʻzbek estradasi,
  👩 Ayol ovozi.
- **Optional, and now filmable for real:** the settlement beat — «✅ Toʻlovingiz oʻtdi.» and «Qoʻshigʻingizni
  hozir yozishni boshlayapman». Film only screens the bot draws. **Never a fabricated Payme receipt.**

#### TEST 5 — one real 15 000 soʻm purchase, tonight, on account C
Nobody has exercised the live rail in about 37 hours. Do it now, not in front of a subject.
- [ ] The paywall reads **«💳 Bitta qoʻshiq — 15 000 soʻm»** — **screenshot it.** This is the one price
  fact that could not be closed from outside the host, and the shoot needs the screenshot anyway.
- [ ] The payment completes, `✅ Toʻlovingiz oʻtdi.` arrives, the song auto-starts and lands.
- [ ] Time it for your own planning only. **No latency number goes on screen or in a caption. Ever.**

---

### 4.6 AFTER THE RENDERS

#### Filenames — ASCII only
`ʻ` breaks CapCut, Android's media scanner and exFAT. Keep it out of filenames and keep it in the sheet.

```
YYYYMMDD_c<NN>_<Name-ASCII>-<disambiguator>_<SUBJ>_<genre>_<voice>_t<take>_<PASS|FAIL|PENDING>.mp3

20260917_c03_Ogiloy-79_MRH_shashmaqom_ayol_t1_PASS.mp3
20260917_c02_Ogiloy-25_DLB_pop_ayol_t1_FAIL.mp3
20260917_c01_Gulomjon_ANV_pop_erkak_t2_PASS.mp3
```

- `<Name-ASCII>` = marks stripped — which is, usefully, the exact spelling the vendor was asked to sing.
- `<disambiguator>` is **mandatory whenever two different people share a name**. Tonight that is real:
  **Oʻgʻiloy appears twice** — the ~25-year-old in card 2 and the 79-year-old in card 3. `Ogiloy-25` and
  `Ogiloy-79`, never one file. Check the driver names against the card-2 subjects for the same collision.
- `<SUBJ>` = three letters for the person, matching their release form, so anyone can answer "whose song
  is this?" without opening it.
- Keep `renders.txt` beside the folder with the **true U+02BB spelling** for every file.

#### Where they live
- **Master:** `renders/2026-09-17/` on the shoot laptop, copied to one external drive or cloud folder
  **before anyone sleeps**.
- **Working copies:** the shoot phone's Files app, same names.
- **Failures:** `renders/2026-09-17/fail/` — moved there at the audition and never opened again.
- **Telegram is not the archive.** The chat is where they arrived, not where they live. Download every
  file tonight.
- **Do not go to the production host for them.** It is read-only for this shoot and its archive hands out
  `file://` URLs that are no use to you.
- The clean export is the master for the Reel's ORIGINAL AUDIO. The in-room speaker capture is a
  performance, never the master.

#### The reuse rule — hard
1. **A person's song appears only in that person's video, under that person's signed release.** Not for a
   different person with the same name. Not "nobody will notice". Not as a bed, not muted, not under
   other audio.
2. **Different person = different render, different file, different release.** Tonight's live trap is the
   two Oʻgʻiloys.
3. **Same person across two cards is fine only if their release names both** (Gulnoza in cards 9 and 10).
   The grandmother is single-use by house rule — do not shoot two concepts with the same grandmother, and
   do not shoot two concepts in a taxi.
4. **A FAILED take is used nowhere.** Not as texture, not as a bed, not in a behind-the-scenes cut.
5. Keep the failures as the honest internal record — but **no number derived from them is ever spoken,
   written, put on a slide or typed into a comment reply.** The answer to «necha foiz toʻgʻri chiqadi?» is
   the mechanism, never a percentage.

---
## 5. PACK TWO — EVERY WORD ON SCREEN OR IN A CAPTION, PROOFED

**Proofed 2026-09-17 against the live locale catalogue (`src/bayram/bot/locales/uz_latn.py`), against
this morning's verified facts, and against two independent copy critiques.** Where a fact kills a line,
the fact wins and the line is rewritten below. Nothing here is optional polish — every change is either
an orthography error, a register error, or a claim that is not true.

### 5.0 How the two critiques were reconciled

Two readers went over the Uzbek. **Where they disagreed, the native reader won and the free-model
cross-check lost** — the second reader's own report records that three of its four delegated models
never answered, that the one that did contradicted itself three ways on the central orthography
question, emitted byte-identical "wrong" and "correct" variants, and hallucinated source text that does
not exist. Its independent judgements are kept where they are right and uncontested; its verdicts are
not treated as a second opinion.

The seven places they disagreed, and what shipped:

| String | Native reader | Cross-check | Shipped |
| --- | --- | --- | --- |
| Account Name field | `Ismingiz bilan qoʻshiq` | `Ismingiz aytiladigan qoʻshiq` | **native** — shorter, and the search field pays for length |
| Bio line 2 | `ustoz uchun` | `ustozga atalgan qoʻshiq` / all-dative | **native** |
| Card 3, «Bizning oilada… qoʻshiq qilmagan edi» | `Oilamizda… yozdirmagan edi` | `Bizning oilada… bagʻishlamagan edi` | **native** |
| Card 3's cousin CTA | `qarindoshingizga` | `amakivachcha yoki xolavachchangizga` | **native** |
| Card 5 caption | `Yangi turkum … yozing. Qoʻshigʻini men yozdiraman.` | `…yozasiz. Qoʻshigʻini men yozaman.` | **native** (`seriya` is the Russian word; `turkum` is the Uzbek one) |
| Card 4, the driver's fee | active — `suratga olganimiz uchun unga haq toʻladik` | passive — `videoga olish uchun unga haq toʻlandi` | **native.** It also corrects this pack's own earlier reasoning: `suratga olmoq` is the ordinary Uzbek verb for filming, not photography only |
| Card 6, the reported speech | restore the quotes, or rewrite to `…oʻtirganimni aytdim` | add a comma before `dedim` | **native**, taking the quote-free rewrite so global rule G4 still holds |

**One critique finding was rejected, and the string stays as it is.** The native reader marked the
paywall line «🔒 Soʻzlar sizniki. Pul yozib olishga toʻlanadi.» as agentless and proposed «Toʻlov faqat
yozib olish uchun». **That string is not ours to edit** — it is the bot's own live locale string, quoted
verbatim (verified against `uz_latn.py:126-128`), and it is what the camera records at card 7's 0:23.
Changing it in the pack would only guarantee the burned type and the screen disagree. If the wording is
genuinely wrong it is a product ticket, not a caption fix.

Two open judgement calls the native reader raised and did **not** resolve, because they are the owner's:
**(a)** `havola` over `link` is right for product consistency but is the bookish choice — on Instagram,
Uzbek speakers say *link*, and the CTA is where a stiff word costs taps. **(b)** «QOʻSHIQ SOL» only
works as a pun on «pul solma»; `qoʻshiq solmoq` is not an existing collocation, so some viewers will read
it as an error by the brand that sells correct Uzbek. Both are in still-unknown (§9).

---

### 5.1 ORTHOGRAPHY KIT — read this before you type one character

#### The two characters to copy

Copy this line into a phone note and pin it. Do not retype it, ever.

```
ʻ  Oʻ  oʻ  Gʻ  gʻ  ʼ
```

| Char | Codepoint | Name | Used in |
| --- | --- | --- | --- |
| **ʻ** | U+02BB | MODIFIER LETTER TURNED COMMA | `oʻ` and `gʻ` only — soʻm, qoʻshiq, toʻgʻri, Oʻgʻiloy, Gʻulomjon |
| **ʼ** | U+02BC | MODIFIER LETTER APOSTROPHE | the *tutuq belgisi* — maʼno, sanʼat, aʼlo. **A different character.** No string on this slate needs it, but never substitute ʻ for it if a name or word turns up that does. |

The bot's own intake code (`src/bayram/names/marks.py`) makes exactly this distinction: U+02BB after
`o`/`g`, U+02BC everywhere else. Our copy must match our own product.

#### The four that must never appear

⚠️ **The example column below is only trustworthy if your renderer distinguishes these four glyphs — and
several do not.** The previous version of this table showed the U+0027 and U+2019 rows as the same
character, so the table that teaches the distinction could not demonstrate it. **Verify by codepoint,
not by eye**, with the command underneath.

| Codepoint | Name | Looks like | Why it gets in |
| --- | --- | --- | --- |
| **U+0027** | APOSTROPHE (ASCII, straight) | a vertical tick, no curve, same height either side | the plain phone keyboard |
| **U+2019** | RIGHT SINGLE QUOTATION MARK | a comma raised to cap height, tail curling **down-left** | iOS/macOS smart quotes silently rewriting U+0027 |
| **U+0060** | GRAVE ACCENT | a stroke slanting **down to the right**, sitting high | Android long-press, some keyboards |
| **U+00B4** | ACUTE ACCENT | a stroke slanting **down to the left** | the same |

Also banned: the ordinary comma `,` used as a raised mark.

**The only test that means anything** — run it on the final caption file before export, and expect
**zero hits inside any Uzbek word**:

```
grep -nP "[\x{0027}\x{2019}\x{2018}\x{0060}\x{00B4}]" captions.txt
```

and to confirm the good character is present and is the right one:

```
grep -cP "\x{02BB}" captions.txt
```

#### How to type it

- **There is no reliable long-press.** iOS long-press on `'` does **not** offer U+02BB. Do not hunt for
  it on the keyboard.
- **The only safe method: copy-paste from the pinned note above.** Same for the editor, the caption
  writer and whoever types into the bot on camera.
- **Android Gboard:** install the *Uzbek (Latin)* layout — it puts ʻ on its own key. Verify it is U+02BB
  with the grep above, not by looking at it.
- **Turn off smart punctuation** on every device that will touch caption text: iOS → Settings → General →
  Keyboard → **Smart Punctuation OFF**. It rewrites U+0027 to U+2019 and will corrupt a caption after
  you paste it.
- **The Instagram caption field does not auto-correct pasted text**, but the iOS keyboard does if you
  type. Always paste.

#### The CapCut test — do this tonight, before anything is cut

Type or paste these four strings at title size, in the exact font, on the exact shoot phone:

```
Oʻgʻiloy
Gʻulomjon
qoʻshiq
toʻgʻri
```

Look for a **raised turned comma** — not a straight tick, not a backtick, not a tofu box (□) — **in the
exported file**, not only in the preview. If any of the four fails, install a Latin-Extended font or
pre-render every card as a PNG. This is the single failure mode that makes a slate whose thesis is "your
name, spelled right" render `Gʻayrat` as `G'ayrat`.

#### Two more typographic rules that apply to every string below

1. **`15 000 soʻm` takes a NON-BREAKING SPACE** (U+00A0) between `15` and `000`, so the number can never
   wrap mid-price on a phone. The bot does this; our cards must too. Same for `200 000`, `40 000`,
   `500 000`, `19 000`. **Every number inside a copy-paste block in this document already carries
   U+00A0 — copy the string, never retype it with the spacebar.**
2. **Uzbek case affixes attach to the closing guillemet with NO space:** `«Xurshidabegim»ni`,
   `«Oʻgʻiloy»dagi`, `«Gʻayrat»dagi`. The playbook has a space in all three places. Fixed below.

#### Hashtags and keywords — ASCII only, no exceptions

Never `#qoʻshiq`, `#sovgʻa`, `#tugʻilgankun`. Always `#qoshiq`, `#sovga`, `#tugilgankun`. Never `QOʻSHIQ`
as a comment keyword. The one keyword across the whole slate is **`BAYRAM`**, plain ASCII, matched
case-insensitively with the variants `bayram / БАЙРАМ / bayrom`.

---

### 5.2 GLOBAL FIXES — applied to every card below

| # | Problem | Fix | Why |
| --- | --- | --- | --- |
| G1 | `«Xurshidabegim» ni`, `«Oʻgʻiloy» dagi`, `«Gʻayrat» dagi` | delete the space: `«Xurshidabegim»ni` | Uzbek affixes never stand alone. A space here reads as a typo in exactly the domain we sell. **Applies to a bare letter too:** `ʻ ni` → `ʻ harfini`. |
| G2 | `qoʻshiq qildim` vs `qoʻshiq yozdirdim` | **`yozdirdim`** everywhere — **including in the captions**, which is where the previous pass declared this rule and then failed to apply it | `qoʻshiq qilmoq` is a calque of «делать песню»; `yozdirmoq` ("had it written") is what actually happened and matches the bot's own verb (`yozib olaman`). One account, one verb. |
| G3 | `linkni` vs `havolani` | **`havolani`** everywhere | the bot's own copy says «Havola 12 soat amal qiladi». Match the product. *(Owner decision open — see §5.0.)* |
| G4 | nested `«...»` inside `«...»`, and ASCII `"..."` inside Uzbek | outer `« »`, inner **plain, no quotes** — and if removing the quotes breaks the sentence, **rewrite the sentence**, do not leave it bare | mixed quote systems on a burned card read as sloppy at 140pt; a bare reported clause reads as a first-person claim |
| G5 | `gul bir haftada soʻliydi` (card 8) vs `gul uch kunda soʻliydi` (card 9) | **`bir haftada`** in both | same account, same week, two different flower lifespans is a comment-thread gotcha for no gain |
| G6 | every claim of the form "ismni toʻgʻri aytdi" | see the FACT flags per card | the acoustic verifier is structurally deaf to gʻ/oʻ/x/q. These lines are only shippable on takes two native speakers have passed. |
| **G7** | `Notoʻgʻri chiqsa — yozing, qayta yozamiz.` | **`Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.`** | the old line used `yozmoq` twice in five words for two different things — "write to us" and "re-record". At caption speed it reads as "write, we'll rewrite what you wrote". Applies across cards 1, 2, 3, 4, 8, 9, 10 and both reply templates. |
| **G8** | agentless passives in first-person stories — `haqi toʻlandi`, `Yozib olindi` | active voice | the voice of an accounting note inside a story told by a person |

---

### 5.3 THE FACT BOARD — what changed under the copy this morning

| Fact | Effect on copy |
| --- | --- |
| **Price is 15 000 soʻm, verified live.** 7 000 is dead. | Every `15 000 soʻm` on the slate **stands as written**. The playbook's fallback ("if unconfirmed, the card reads «bitta taksi puli» with no digits") is **deleted**. |
| **The checkout rail is production Payme, not the stub.** | A payment **may** be filmed. The bot's real screens (`💳 15 000 soʻm — 1 qoʻshiq`, `🔗 Sal qoldi`, `✅ Toʻlovingiz oʻtdi.`) may appear on camera. A **fabricated Payme receipt still may not.** |
| **It is not "inside Telegram" and it is not one tap.** | `«Telegramdan chiqmasdan»` / "pay inside Telegram" / "one tap" remain **banned** — for a new reason. The customer leaves for `checkout.paycom.uz`. No card currently uses the phrase; keep it that way. |
| **drill does not ship.** Nearest is `🎧 Xip-xop`. | Card 5's `BOBOMGA — DRILL` and its caption line are **selling a button that does not exist**. Rewritten below. |
| **"jazz lounge" is labelled `🎷 Jaz-launj`.** | Card 5's `JAZZ` must match the button the same video screen-records. Rewritten below. |
| **There is no `kasb bayrami / ustoz` occasion.** | Card 8's shot list names a menu item that does not exist. No caption change needed — but the operator taps `🎉 Bayram` or `✨ Boshqa sabab`, and no on-screen text may name a teachers' occasion as a picker option. |
| **`😂 Hazil` is the literal button.** | Card 7's `hazil` copy is **correct as written**. |
| **`🎻 Shashmaqom` is the literal button, but the track is style, not repertoire.** | Card 3's ORIGINAL AUDIO name changes to `Bayram — shashmaqom uslubida (Oʻgʻiloy)`. The picker screen-record may still show the bot's own `🎻 Shashmaqom` button. |
| **The name submitted to the vendor is the mark-STRIPPED spelling** (`Gayrat`, `Ogiloy`), and the verifier scores that 1.000. | Every claim that the `ʻ`/`gʻ` is **audible** is false. The mark claim moves onto the **screen**, where it is 100% true. Cards 1, 3, 4 rewritten. |
| **There is no re-roll button and no refund mechanism.** | `«qaytadan yozib beramiz»` is shippable **only** if someone commits in writing to honouring it by hand via /support. `«pul olmaymiz»` (card 3) has no mechanism at all and is **cut**. |
| **Inpainting does not fire; a re-roll returns a different song.** | Never write `«faqat ismni qayta yozamiz»`. Not currently on the slate — keep it off. |
| **The wizard is 9 steps and asks a fresh account for its phone number.** | No card may say `«4 ta savol»`. Card 7's `«savollarga javob berasiz»` is correct and vague — keep it. |
| **Output languages are four**, including Uzbek Cyrillic. | Card 7's `«Oʻzbekcha, ruscha, inglizcha»` is incomplete. Fixed below. |

---

### 5.4 CARD 1 — Gʻ TESTI

| Original | Verdict | Use this |
| --- | --- | --- |
| `«Xurshidabegim» ni umuman tanimadi.` | **ORTHOGRAPHY** — affix spacing (G1) | `«Xurshidabegim»ni umuman tanimadi.` |
| `Bayram esa ismni qanday yozsangiz, shunday kuylaydi — ʻ ham, gʻ ham joyida.` | **FACT — FALSE.** The vendor was sent `Gulomjon`. The mark is stripped at rank 0 and the verifier cannot hear it. | `Bayram esa ismingizni qanday yozsangiz, ekranda xuddi shunday koʻrsatadi — ʻ ham joyida. Qoʻshiq yozilgandan keyin ismni oʻzi tinglab chiqadi va notoʻgʻri chiqqan boʻlsa, qaytadan yozadi.` |
| `Bugun ikkita ismni bitta mashhur AI xizmatiga berdik.` | **REGISTER** — `bitta` counts items, it is not the indefinite article; and handing a name "to a service" reads like filing paperwork | `Bugun ikkita ismni mashhur bir AI xizmatida sinab koʻrdik.` |
| `Nomini aytmaymiz, ekranda oʻzingiz eshitasiz.` | **REGISTER** — you do not hear things *on a screen*, and `nomini` has no antecedent on a slate where every sentence is about names | `Qaysi xizmat ekanini aytmaymiz — videoda oʻzingiz eshitasiz.` |
| `Notoʻgʻri chiqsa — yozing, qayta yozamiz.` | **G7 + FACT — CONDITIONAL.** True as a promise, but there is no re-roll button. | `Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.` Keep **only** on a written commitment to honour it by hand via /support. Otherwise cut the line. |
| `Ismingiz qanday buziladi?` (CTA) | **REGISTER** — agentless passive makes names sound like they spoil on their own, and it blunts the grievance the CTA is fishing for | `Ismingizni qanday buzib aytishadi?` |
| `Bizniki-chi?` | **OK** — this is how a person actually writes | unchanged |
| `15 000 soʻm — bitta taksi puli` | **VERIFIED TRUE.** ≈ a 4.2 km Yandex Go Start ride. Under-claims. | unchanged (U+00A0 in `15 000`) |
| `Izohga BAYRAM deb yozing` / `bot havolani oʻzi yuboradi` | OK — ASCII keyword, and `havola` is the product's word (G3) | unchanged |

**BLOCKER on this card:** `Gʻulomjon` and `Xurshidabegim` must both be graded pass by two native speakers
on the exact take in the cut. `Xurshidabegim` is 13 characters — the machine's gate allows it **one whole
wrong syllable** and still passes, so the bot's own "verified" verdict is worth nothing here. Grade it by
ear.

**STANDING BAN on this card:** never sing `Gʻayrat`. The stripped submission is literally `Gayrat`, which
is the slur reading. `Gʻulomjon` carries the same gʻ and none of the exposure.

```
=== ON SCREEN, in edit order ===

goo-LOM-john
Gʻulomjon
Boshqa AI ❌

kher-shi-da-BE-jim
Xurshidabegim
Boshqa AI ❌

Bizniki-chi?

Gʻulomjon ✅
Xurshidabegim ✅

15 000 soʻm — bitta taksi puli
@bayram_uzbot
Izohga BAYRAM deb yozing

=== ON SCREEN — RU cut ===

goo-LOM-john
Gʻulomjon
Другой ИИ ❌

kher-shi-da-BE-jim
Xurshidabegim
Другой ИИ ❌

А наш?

Gʻulomjon ✅
Xurshidabegim ✅

15 000 сум — одна поездка на такси
@bayram_uzbot
Напишите BAYRAM в комментариях

=== CAPTION UZ ===

Bugun ikkita ismni mashhur bir AI xizmatida sinab koʻrdik. «Gʻulomjon» — «goo-LOM-john» boʻldi. «Xurshidabegim»ni umuman tanimadi.

Qaysi xizmat ekanini aytmaymiz — videoda oʻzingiz eshitasiz. Bayram esa ismingizni qanday yozsangiz, ekranda xuddi shunday koʻrsatadi — ʻ ham joyida. Qoʻshiq yozilgandan keyin ismni oʻzi tinglab chiqadi va notoʻgʻri chiqqan boʻlsa, qaytadan yozadi.

Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.

15 000 soʻm · @bayram_uzbot

#bayram #ism #sovga #uzbekistan #tugilgankun

=== CAPTION RU ===

Сегодня прогнали два имени через один известный AI-сервис. «Gʻulomjon» превратился в «goo-LOM-john». «Xurshidabegim» он не узнал вообще.

Название не называем — сами услышите на экране. А Bayram показывает имя ровно так, как вы его написали, вместе с ʻ. И когда песня записана, бот сам её прослушивает и перезаписывает, если имя прозвучало не так.

Вышло не так — напишите, переделаем.

15 000 сум · @bayram_uzbot

#bayram #ism #sovga #uzbekistan #tugilgankun

=== CTA (spoken + end card) ===

UZ: Ismingizni qanday buzib aytishadi? Izohga BAYRAM deb yozing — bot havolani oʻzi yuboradi.
RU: Как коверкают ваше имя? Напишите BAYRAM в комментариях — бот сам пришлёт ссылку.

=== AUTO-DM BODY (one message, link must be inside it) ===

UZ: Salom! Mana havola — ismingiz bilan qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_gtest
RU: Привет! Вот ссылка — песня с вашим именем создаётся здесь: t.me/bayram_uzbot?start=ig_gtest

=== ORIGINAL AUDIO NAME ===

Bayram — Gʻulomjon
```

---

### 5.5 CARD 2 — «Gulya emas»

| Original | Verdict | Use this |
| --- | --- | --- |
| `«Ishda 22 yil — hamma "Gulya" deydi...»` | **TYPOGRAPHY (G4)** — ASCII quotes nested inside guillemets | `Ishda 22 yil — hamma Gulya deydi.` (no inner quotes; it is spoken sync sound) |
| `Tuzatishdan charchadim.` | **REGISTER** — literal «Устала поправлять». Uzbek carries "tired of doing X over and over" on the verb aspect, not on a verbal noun | `Tuzataverib charchadim.` |
| `Ismingiz toʻliq.` | **GRAMMAR — says nothing.** It is the Russian nominal sentence with the dash kept. Uzbek needs a predicate, and this is the payoff card. | `Ismingiz toʻliq aytiladi.` (two-word alternative if the card must be short: `Toʻliq ismingiz.`) |
| `Toʻrt odam, toʻrt ism, toʻrtta qisqartma.` | **GRAMMAR** — `toʻrt / toʻrt / toʻrtta` is inconsistent inside one breath, and people are counted with `kishi` | `Toʻrt kishi. Toʻrt ism. Toʻrt qisqartma.` |
| `Har biriga ismi toʻliq kuylanadigan qoʻshiq qildik.` | **G2** + the claim is about the audio | `Har biriga ismi toʻliq aytiladigan qoʻshiq yozdirdik.` |
| `Kameradagi yuzlar aktyor emas.` | **REGISTER — word-for-word from «Лица в кадре».** Uzbek does not use `yuz` as a metonym for a person on film, and this is the line the whole slate leans on for credibility. | `Videodagi odamlar aktyor emas.` (burned card: `Bular aktyor emas.`) |
| `ertaga shulardan javob qilamiz` | **REGISTER — potentially offensive.** `javob qilmoq`'s live idiom is to dismiss someone (`ishdan javob qilmoq`). In a reply promise it reads as seeing people off. | `ertaga bir nechtasiga javob beramiz` |
| `Birinchi marta toʻgʻri aytishdi.` | **FACT — CONDITIONAL AND LOAD-BEARING.** The single most dangerous line on the slate. | Ships **only** on a take two unrelated native speakers passed. If either fails: **replace the person, do not soften the line.** `Gʻayrat` and `Oʻgʻiloy` are 6-character keys — zero error tolerance at the gate, so a pass there means little acoustically. |
| `Gʻayrat — hujjatda «Gayrat»` / `Oʻgʻiloy — «Ogiloy»` | **FACT — SELF-OWN RISK.** These cards stage on screen the exact spelling the bot submits to the vendor. | Keep the cards — the grievance is real and it is the film's point — but they are only safe **after** the human listen passes. |
| `Necha yildan beri?` | OK | unchanged |

```
=== ON SCREEN, in edit order ===

«Gulya» → Gulchehra

Gulya emas. Gulchehra.
Ishda 22 yil — hamma Gulya deydi. Tuzataverib charchadim.

Gʻayrat. Maktab jurnalida Gayrat deb yozilgan. Hujjatda ham shunday qolib ketgan.
Gʻayrat — hujjatda «Gayrat»

Oʻgʻiloy. Instagramda Ogiloy boʻlib qoldi, tuzata olmadim.
Oʻgʻiloy — «Ogiloy»

Abdulaziz. Ishda Abdu.
Abdulaziz — «Abdu»

Necha yildan beri?

Birinchi marta toʻgʻri aytishdi.

Ismingiz toʻliq aytiladi.
@bayram_uzbot
Izohga BAYRAM deb yozing

=== ON SCREEN — RU cut ===

«Гуля» → Гульчехра

Не Гуля. Гульчехра.
22 года на работе — все говорят Гуля. Устала поправлять.

Гайрат. В школьном журнале записали Gayrat. Так и осталось в документах.
Гайрат — в документе «Gayrat»

Огилой. В инстаграме стала Ogiloy, так и не исправила.
Огилой — «Ogiloy»

Абдулазиз. На работе — Абду.
Абдулазиз — «Абду»

Сколько лет уже?

Впервые произнесли правильно.

Ваше имя — полностью.
@bayram_uzbot
Напишите BAYRAM в комментариях

=== CAPTION UZ ===

«Gulya emas. Gulchehra.» — 22 yil ishda uni notoʻgʻri chaqirishgan.

Toʻrt kishi. Toʻrt ism. Toʻrt qisqartma. Hech biri buni soʻramagan — shunchaki kimgadir toʻliq ism «qiyin» boʻlgan. Har biriga ismi toʻliq aytiladigan qoʻshiq yozdirdik. Videodagi odamlar aktyor emas.

Sizning ismingizni ham qisqartirishadimi? Izohga toʻliq yozing — ertaga bir nechtasiga javob beramiz.

Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.

@bayram_uzbot

#bayram #ism #sovga #uzbekistan #toshkent

=== CAPTION RU ===

«Не Гуля. Гульчехра.» — 22 года на работе её звали неправильно.

Четыре человека. Четыре имени. Четыре сокращения. Никто из них об этом не просил — просто кому-то полное имя оказалось «сложным». Каждому записали песню, где имя звучит целиком. Лица в кадре — не актёры.

Ваше имя тоже сокращают? Напишите его полностью в комментариях — завтра ответим на несколько.

Вышло не так — напишите, переделаем.

@bayram_uzbot

#bayram #ism #sovga #uzbekistan #toshkent

=== CTA + PINNED COMMENT ===

CTA UZ: Sizning ismingizni ham qisqartirishadimi? Toʻliq yozing.
CTA RU: Ваше имя тоже сокращают? Напишите его полностью.

PIN UZ: Ismingizni qanday buzib aytishadi?
PIN RU: Как коверкают ваше имя?

=== AUTO-DM BODY ===

UZ: Salom! Mana havola — ismingiz bilan qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_gulya
RU: Привет! Вот ссылка — песня с вашим именем создаётся здесь: t.me/bayram_uzbot?start=ig_gulya

=== ORIGINAL AUDIO NAME ===

Bayram — Gulchehra
```

---

### 5.6 CARD 3 — BUVIM ISMINI QOʻSHIQDA ESHITDI

| Original | Verdict | Use this |
| --- | --- | --- |
| `Eng qiyini — ism: «Oʻgʻiloy» dagi ʻ.` | **G1 + FACT.** Affix spacing, a bare letter carrying an affix (`ʻ ni` → `ʻ harfini`), **and** the sentence sets up a claim the audio cannot honour: the vendor is sent `Ogiloy`. | **Cut the sentence.** The next one carries the point without promising the mark is audible. |
| `Qoʻshiqni AI yozdi, ismni biz toʻgʻriladik — ʻ ni notoʻgʻri aytsa, qayta yozamiz, pul olmaymiz.` | **FACT — TWO FALSE HALVES.** (a) we corrected the **spelling on screen**, not the sung name; (b) `pul olmaymiz` is a refund promise with **no mechanism** anywhere in the product. | `Qoʻshiqni AI yozdi. Qoʻshiq yozilgandan keyin Bayram ismni oʻzi tinglab chiqadi va notoʻgʻri chiqqan boʻlsa, qaytadan yozadi. Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.` |
| *(word order)* `Ismni Bayram yozilgandan keyin oʻzi tinglab chiqadi` | **GRAMMAR — strands the subject inside the temporal clause.** A reader parses «Bayram yozilgandan keyin» as one unit — "after Bayram is written" — because the passive's real subject (`qoʻshiq`) is absent. The brand name becomes the object of the wrong verb. | the ordering above: `Qoʻshiq yozilgandan keyin Bayram ismni oʻzi tinglab chiqadi…` |
| `Qoʻshiqni AI yozdi — ismni biz toʻgʻriladik.` (on-screen card) | same FACT problem, unhedged at 60pt | `Qoʻshiqni AI yozdi. Ismni biz tekshirib chiqdik.` |
| `Bizning oilada unga hech kim qoʻshiq qilmagan edi.` | **TWO ERRORS.** `qoʻshiq qilmoq` (G2), and `Bizning oilada` is a calque — Uzbek marks possession on the noun. | `Oilamizda unga hech kim qoʻshiq yozdirmagan edi.` |
| `Shashmaqom tanladik, chunki u shuni eshitib oʻsgan.` | **CULTURAL + REGISTER.** Repertoire claim; and a 79-year-old referred to as bare `u` is the one cold line on the card. | `Shashmaqom uslubini tanladik — buvim shu kuylarni eshitib katta boʻlgan.` |
| `siz ikkalangiz bir buvining nabirasisiz` / `amakivachchangizga` | **GRAMMAR + REACH.** Plural subject, singular predicate; and `amakivachcha` is specifically a father's-brother's child, so the forward misses every maternal cousin — exactly the people who share a grandmother on the mother's side. | `Bu videoni qarindoshingizga yuboring — buvingiz Instagramda yoʻq, lekin nabiralari shu yerda.` |
| ORIGINAL AUDIO `Bayram — Shashmaqom (Oʻgʻiloy)` | **CULTURAL — REPERTOIRE CLAIM.** Calling a generated track "Shashmaqom" is the thing that crosses the line, not the AI. | `Bayram — shashmaqom uslubida (Oʻgʻiloy)`. The picker screen-record may still show the bot's own `🎻 Shashmaqom` button. |
| `Bu kim aytyapti?` | **OK and idiomatic** — `qoʻshiq aytmoq` is the Uzbek verb for singing, and this is exactly how a 79-year-old would say it. **Do not "correct" it to `kuylayapti`.** | unchanged |
| `Buvi videoni koʻrdi va joylashga rozi boʻldi.` | OK — and it is the card's defence | unchanged. **Signed release BEFORE the camera rolls**; the on-camera nod is warmth, not consent. |
| caption praise of her | **CULTURAL** — expect «koʻz tegmasin» on a 79-year-old's face and full name | keep the caption's restraint; do not add praise |

**BLOCKER:** one person who actually listens to shashmaqom must audition the rendered `Oʻgʻiloy` track.
If it is generic Central-Asian-flavoured pop with a doira on it, **do not use the word shashmaqom in the
film at all.**

```
=== ON SCREEN, in edit order ===

OʻGʻILOY
Buvimning ismi — Oʻgʻiloy.

Bu kim aytyapti?

@bayram_uzbot · 15 000 soʻm

Qoʻshiqni AI yozdi. Ismni biz tekshirib chiqdik.

Buvingizning ismi nima?
@bayram_uzbot

=== ON SCREEN — RU cut ===

OʻGʻILOY
Мою бабушку зовут Огилой.

Кто это поёт?

@bayram_uzbot · 15 000 сум

Песню написал ИИ. Имя мы проверили.

Как зовут вашу бабушку?
@bayram_uzbot

=== CAPTION UZ ===

Buvimning ismi — Oʻgʻiloy. Oilamizda unga hech kim qoʻshiq yozdirmagan edi.

Shashmaqom uslubini tanladik — buvim shu kuylarni eshitib katta boʻlgan. Qoʻshiqni AI yozdi. Qoʻshiq yozilgandan keyin Bayram ismni oʻzi tinglab chiqadi va notoʻgʻri chiqqan boʻlsa, qaytadan yozadi. Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.

Buvi videoni koʻrdi va joylashga rozi boʻldi.

Bu videoni qarindoshingizga yuboring — buvingiz Instagramda yoʻq, lekin nabiralari shu yerda.

15 000 soʻm · @bayram_uzbot

#bayram #buvim #sovga #uzbekistan #toshkent

=== CAPTION RU ===

Мою бабушку зовут Огилой. В нашей семье ей никто никогда не делал песню.

Выбрали шашмаком как стиль — она под него выросла. Песню написал ИИ. А имя Bayram после записи сам прослушивает и перезаписывает, если оно прозвучало не так. Вышло не так — напишите, переделаем.

Бабушка видела видео и разрешила его выложить.

Отправьте это своему двоюродному брату или сестре — вашей бабушки нет в инстаграме, но внуки у неё одни.

15 000 сум · @bayram_uzbot

#bayram #buvim #sovga #uzbekistan #toshkent

=== CTA ===

UZ: Buvingizning ismini botga yozing.
RU: Напишите имя вашей бабушки боту.

=== AUTO-DM BODY ===

UZ: Salom! Mana havola — ismi bilan qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_buvim
RU: Привет! Вот ссылка — песня с её именем создаётся здесь: t.me/bayram_uzbot?start=ig_buvim

=== ORIGINAL AUDIO NAME ===

Bayram — shashmaqom uslubida (Oʻgʻiloy)
```

---

### 5.7 CARD 4 — TAKSICHINING ISMI

| Original | Verdict | Use this |
| --- | --- | --- |
| `Eng qiyini — «Gʻayrat» dagi gʻ.` | **G1 + FACT + STANDING BAN.** Affix spacing; the submitted spelling is `Gayrat`; and the slate's own hard rule forbids putting `Gʻayrat` under any difficulty frame. | **Cast a driver whose name has no gʻ.** If the driver really is Gʻayrat, the line becomes `Ismini qanday yozgan boʻlsam, ekranda ham xuddi shunday chiqdi.` and the gʻ is never named as the hard part. |
| `Bayram ismni siz yozgandek kuylaydi.` | **FACT — FALSE about the audio** | `Bayram ismingizni siz yozgandek koʻrsatadi, keyin esa yozilgan qoʻshiqni oʻzi tinglab chiqadi.` |
| `Ismini qanday yozsam, ekranda shundoq qaytdi.` | **REGISTER** — «так оно и вернулось» rendered literally. A name does not *return* on a screen in Uzbek; it appears. The correlative pair is `qanday … xuddi shunday`. | `Ismini qanday yozgan boʻlsam, ekranda ham xuddi shunday chiqdi.` |
| `«...Gʻayrat aka...»` (karaoke lyric, frame one) | **FACT + HIGHEST RISK FRAME ON THE SLATE.** The rank-0 submission is literally `Gayrat` — the exact slur reading the playbook bans by name. | Do not shoot this name. If the driver is Gʻayrat and the song is already rendered, the take does **not** ship unless two native speakers confirm the gʻ is audible. Default: pick a different ride. |
| `Yoʻl — 15 000. Qoʻshiq ham 15 000.` | **FACT — DEFAULT TO THE OTHER VARIANT.** At 4 600 min + 2 500/km, an exact 15 000 fare means a ~4.2 km ride; most real screens read higher, and an exact match invites staging. | **Default card:** `Yoʻl — 19 000. Qoʻshiq — 15 000. Arzonroq chiqdi.` Use the parity card only if the real fare screen genuinely reads 15 000. |
| `Gʻayrat akaga suratga olish uchun toʻlandi.` / `haqi toʻlandi` | **G8 — agentless passive in a first-person story.** *(The earlier objection that `suratga olmoq` means photography only is wrong — it is the ordinary Uzbek verb for filming.)* | on-screen, name-free so it survives a driver swap: `Haydovchiga suratga olganimiz uchun haq toʻladik.` In the caption: `…suratga olganimiz uchun unga haq toʻladik.` |
| `Yoʻl puli ham, qoʻshiq ham — bitta narx.` | **FACT — only true on the parity variant** | on the surge variant: `Yoʻl pulidan arzon chiqdi.` |
| `Ovozni oʻzi balandlatdi.` / `Haydovchining ismini ilovada koʻrdim.` / `Qoʻshiq unda qoldi.` | OK — natural | unchanged |
| shot-list note: *"Do not film a Payme press: the checkout provider is a stub"* | **REFUTED.** The rail is production Payme. | **Delete that instruction.** A Payme press may be filmed. Replace it with the consent and plate-blurring conditions only. |

**BLOCKER:** signed Uzbek release **before the ride**, naming organic posting, paid boosting, re-cuts,
and the AI processing of his name and voice. "A vague filming yes at pickup" is deleted as a method —
ЗРУ-1115 has been in force since 21 Jan 2026 and the public-place exception covers only filming "to
reflect the general process".

```
=== ON SCREEN, in edit order ===

«...[HAYDOVCHINING ISMI]...»            <- karaoke lyric, magenta, frame one

Haydovchining ismini ilovada koʻrdim.

Ovozni oʻzi balandlatdi.

Yoʻl — 19 000. Qoʻshiq — 15 000. Arzonroq chiqdi.
   [PARITY VARIANT, only if the real fare screen reads 15 000:]
   Yoʻl — 15 000. Qoʻshiq ham 15 000.

Haydovchiga suratga olganimiz uchun haq toʻladik.
@bayram_uzbot

=== ON SCREEN — RU cut ===

«...[ИМЯ ВОДИТЕЛЯ]...»

Увидел имя водителя в приложении.

Сам прибавил громкость.

Поездка — 19 000. Песня — 15 000. Вышло дешевле.
   [ВАРИАНТ ПАРИТЕТА:]
   Поездка — 15 000. Песня — тоже 15 000.

Водителю заплачено за съёмку.
@bayram_uzbot

=== CAPTION UZ ===

Taksi chaqirdim, ilovada haydovchining ismini koʻrdim va yoʻlda unga oʻsha ism bilan qoʻshiq yozdirdim.

Ismini qanday yozgan boʻlsam, ekranda ham xuddi shunday chiqdi. Bayram qoʻshiq yozilgandan keyin ismni oʻzi tinglab chiqadi. Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.

Haydovchi videoni koʻrdi, joylashga rozi boʻldi, suratga olganimiz uchun unga haq toʻladik. Qoʻshiq unda qoldi.

Yoʻl pulidan arzon chiqdi.

@bayram_uzbot

#bayram #taksi #toshkent #sovga #uzbekistan

=== CAPTION RU ===

Вызвал такси, увидел в приложении имя водителя и прямо в дороге заказал ему песню с этим именем.

Как написал имя — так оно и вернулось на экране. А после записи Bayram сам его прослушивает. Вышло не так — напишите, переделаем.

Водитель посмотрел видео, разрешил выложить, за съёмку ему заплачено. Песня осталась у него.

Вышло дешевле поездки.

@bayram_uzbot

#bayram #taksi #toshkent #sovga #uzbekistan

=== CTA ===

UZ: Ertaga kimning tugʻilgan kuni? Ismini botga yozing.
RU: У кого завтра день рождения? Напишите имя боту.

=== AUTO-DM BODY ===

UZ: Salom! Mana havola — ismi bilan qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_taksi
RU: Привет! Вот ссылка — песня с его именем создаётся здесь: t.me/bayram_uzbot?start=ig_taksi
```

---
### 5.8 CARD 5 — ENG KUTILMAGAN JANR #1

| Original | Verdict | Use this |
| --- | --- | --- |
| `BOBOMGA — DRILL` | **FACT — THE GENRE DOES NOT EXIST.** Nearest shipping option is `🎧 Xip-xop`. | `BOBOMGA — XIP-XOP` |
| `6 YOSHLI AMIRXONGA — JAZZ` | **FACT + LEGAL.** The button is `🎷 Jaz-launj`; and a named, identifiable six-year-old contradicts the slate's own "Do not publish minors" rule and needs parental consent under the pending image law. | **Default: cut the child.** Replace with an adult from the same room, e.g. `AMAKIMGA — JAZ-LAUNJ`. If the child stays: written parental consent naming commercial and boosted use, and record that the no-minors rule was overridden deliberately. |
| `QAYNONAMGA — ROK` (frame 0:00) | **CULTURAL — riskiest non-illegal frame on the slate.** A real identifiable elder woman as the object of a joke published by her kelin's side on a commercial account. | Keep the card text — but **reorder the anthology so `BOBOMGA — XIP-XOP` opens**, put the qaynona beat second, with her visibly in on the joke and the card saying she chose the genre: `QAYNONAM OʻZI TANLADI — ROK` |
| `Yangi seriya.` | **REGISTER** — `seriya` is the Russian TV word; an Uzbek content series is `turkum` | `Yangi turkum.` |
| `eng kutilmagan yaradigan janrni yozasiz. Men yasayman.` | **GRAMMAR + REGISTER.** `yaradigan` is word salad; you make furniture, you write a song (G2); and `yozasiz … Men yozaman` uses one verb for two unrelated acts one clause apart, so the punchline lands as "you write, I write". | `eng kutilmagan janrni yozing. Qoʻshigʻini men yozdiraman.` |
| `Faqat oʻzingiz yoki roziligi bor odam.` | **GRAMMAR + REGISTER.** Incomplete; doubled possessive; and `roziligi bor odam` is contract Uzbek. This is the safety rule, so it must sound like a person said it. | `Faqat oʻz ismingizni yoki rozi boʻlgan odamning ismini yozing.` |
| `Hammasining ismini toʻgʻri aytdi.` | **FACT — CONDITIONAL.** Only shippable if every name in the cut passed the human listen. | Ships on a pass. If any name fails, drop that person from the cut — do not soften the line. |
| `#1: qaynonamga rok, bobomga drill, 6 yoshli Amirxonga jazz` | **FACT** — two dead genres and a named minor | `#1: bobomga xip-xop, qaynonamga rok (janrni oʻzi tanladi), amakimga jaz-launj` |
| `Ertaga yana uchta misol koʻrsataman.` | **REGISTER** — `misol` is a worked example; these are songs | `Ertaga yana uchtasini koʻrsataman.` |
| `Qoida: izohga ism + oʻsha odamga ENG KUTILMAGAN janrni yozing.` | **OK** — and `KUTILMAGAN` (unexpected) rather than `NOTOʻGʻRI` (a verdict) is the correct, deliberate choice | unchanged |
| `Har biri 15 000 soʻm — bitta taksi puli` | **VERIFIED TRUE** | unchanged |
| `Boshqa odam ustidan kulish uchun emas.` | OK — keep it, it is the card's defence | unchanged |
| Shashmaqom in this card | **BANNED** — never under a "wrong genre" label, never in these hashtags | absent; keep it absent |

```
=== ON SCREEN, in edit order (reordered: bobo opens) ===

BOBOMGA — XIP-XOP

QAYNONAM OʻZI TANLADI — ROK

AMAKIMGA — JAZ-LAUNJ

Hammasining ismini toʻgʻri aytdi.

Qoida: ism + ENG KUTILMAGAN janr
Faqat oʻz ismingizni yoki rozi boʻlgan odamning ismini yozing.
Har biri 15 000 soʻm — bitta taksi puli
@bayram_uzbot

=== ON SCREEN — RU cut ===

ДЕДУШКЕ — ХИП-ХОП

СВЕКРОВЬ ВЫБРАЛА САМА — РОК

ДЯДЕ — ДЖАЗ-ЛАУНЖ

Имена всех произнёс правильно.

Правило: имя + САМЫЙ НЕОЖИДАННЫЙ жанр
Только своё имя или имя того, кто согласен.
Каждая — 15 000 сум, одна поездка на такси
@bayram_uzbot

=== CAPTION UZ ===

Yangi turkum. Qoida bitta: izohga ism + oʻsha odamga eng kutilmagan janrni yozing. Qoʻshigʻini men yozdiraman.

#1: bobomga xip-xop, qaynonamga rok (janrni oʻzi tanladi), amakimga jaz-launj. Uchalasining ham ismini toʻgʻri aytdi — asosiy gap shunda.

Muhim: faqat oʻz ismingizni yoki rozi boʻlgan odamning ismini yozing. Boshqa odam ustidan kulish uchun emas.

Ertaga yana uchtasini koʻrsataman.

Har biri 15 000 soʻm · @bayram_uzbot

#bayram #sovga #toshkent #uzbekistan #qoshiq

=== CAPTION RU ===

Новая серия. Правило одно: пишете в комментариях имя + самый неожиданный для этого человека жанр. Я записываю.

#1: дедушке — хип-хоп, свекрови — рок (жанр выбрала сама), дяде — джаз-лаунж. Имена всех троих произнёс правильно — в этом вся суть.

Важно: пишите только своё имя или имя того, кто согласен. Не для того, чтобы смеяться над другим человеком.

Завтра покажу ещё три.

Каждая — 15 000 сум · @bayram_uzbot

#bayram #sovga #toshkent #uzbekistan #qoshiq

=== CTA ===

UZ (creative ask): Izohga: ism + eng kutilmagan janr
UZ (cap the promise): Ertaga uchtasini koʻrsataman.
RU (creative ask): В комментарии: имя + самый неожиданный жанр
RU (cap the promise): Завтра покажу три.

=== AUTO-DM BODY ===

UZ: Salom! Mana havola — ismi bilan qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_janr
RU: Привет! Вот ссылка — песня с этим именем создаётся здесь: t.me/bayram_uzbot?start=ig_janr

=== KEYWORD TRIGGERS (ASCII, case-insensitive) ===

BAYRAM, bayram, bayrom, БАЙРАМ, rok, xip-xop, xip xop, jaz, pop
   (NOT "drill" — the genre does not exist; a drill submission gets the canned reply)
```

---

### 5.9 CARD 6 — «STUDIYAGA BORDIM» DEB ALDADIM

| Original | Verdict | Use this |
| --- | --- | --- |
| `Ukamga qoʻshiq qildim.` | **G2** | `Ukamga qoʻshiq yozdirdim.` |
| `«...va men unga «studiyada ikki kecha oʻtirdim» dedim.»` | **G4 + GRAMMAR.** Guillemets inside guillemets; but stripping them and leaving the clause bare turns the card into a first-person claim that he *really did* sit two nights in a studio — the exact opposite of the video's point. | **Rewrite rather than strip:** `...va unga studiyada ikki kecha oʻtirganimni aytdim.` |
| `@bayram_uzbot ga ismini yozdim` | **ORTHOGRAPHY** — a Latin handle cannot take a bare spaced affix, and attaching one needs an apostrophe we have banned | `@bayram_uzbot botiga ismini yozdim` |
| `Qoʻshiq haqiqiy — faqat rasm yolgʻon edi.` | **REGISTER.** `yolgʻon` is a spoken lie; a fabricated photograph is `soxta`. Bad on the card that is this video's legal defence. | `Qoʻshiq haqiqiy — faqat rasm soxta edi.` **Keep it on screen; do not let a tightening pass trim it.** |
| `Bu rasm ham AI edi.` / `Studiya rasmi AI edi.` | **GRAMMAR** — equates the photo with the tool. Uzbek needs the agent-verb, and this is a required disclosure, so it must be unambiguous. | `Bu rasmni ham AI chizgan.` / `Studiya rasmini AI chizgan.` |
| `Ismini toʻgʻri aytdi — shuning uchun ishondi.` | **FACT — CONDITIONAL** | ships on a pass |
| `40 soniya ishondi.` | OK — a duration inside the video, not a product latency claim | unchanged |
| `Zoʻr-ku... ovozing ham chiqibdi.` / `Bir hafta ovora boʻldim.` / `Oxirida oʻzi onamizga ham buyurtma qildi.` | OK — exactly how a person speaks | unchanged |
| the checkout frame at 0:24–0:27 | **NOW FILMABLE.** The rail is production Payme. | the bot's real screens may appear. Still: **never fabricate a Payme receipt.** |

```
=== ON SCREEN, in edit order ===

Ukamga qoʻshiq yozdirdim.

...va unga studiyada ikki kecha oʻtirganimni aytdim.

40 soniya ishondi.

Qoʻshiq haqiqiy — faqat rasm soxta edi.

@bayram_uzbot

Bu rasmni ham AI chizgan.
Izohga BAYRAM deb yozing

=== ON SCREEN — RU cut ===

Сделал брату песню.

...и сказал ему, что две ночи просидел в студии.

40 секунд верил.

Песня настоящая — фальшивым было только фото.

@bayram_uzbot

Это фото тоже ИИ.
Напишите BAYRAM в комментариях

=== CAPTION UZ ===

Ukamga «bir hafta ovora boʻldim, studiyaga bordim» dedim. 40 soniya ishondi. Studiya rasmini AI chizgan.

Qoʻshiq esa haqiqiy: @bayram_uzbot botiga ismini yozdim, savollarga javob berdim, qoʻshiq keldi. Ismini toʻgʻri aytdi — shuning uchun ishondi.

Oxirida oʻzi onamizga ham buyurtma qildi.

Kimning tugʻilgan kuni yaqin? Ismini yozing.

@bayram_uzbot

#bayram #sovga #prank #tugilgankun #uzbekistan

=== CAPTION RU ===

Сказал брату: «неделю мучился, даже в студию ездил». 40 секунд он верил. Фото студии было сделано ИИ.

А песня настоящая: написал его имя боту @bayram_uzbot, ответил на вопросы, песня пришла. Имя произнёс правильно — поэтому он и поверил.

В конце он сам заказал песню нашей маме.

У кого скоро день рождения? Напишите имя.

@bayram_uzbot

#bayram #sovga #prank #tugilgankun #uzbekistan

=== CTA ===

UZ: Izohga BAYRAM deb yozing — bot havolani oʻzi yuboradi.
RU: Напишите BAYRAM в комментариях — бот сам пришлёт ссылку.

UZ (caption question): Kimning tugʻilgan kuni yaqin?
RU (caption question): У кого скоро день рождения?

=== AUTO-DM BODY ===

UZ: Salom! Mana havola — ismi bilan qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_prank
RU: Привет! Вот ссылка — песня с его именем создаётся здесь: t.me/bayram_uzbot?start=ig_prank
```

---

### 5.10 CARD 7 — GURUHGA TASHLADIM

| Original | Verdict | Use this |
| --- | --- | --- |
| `Oʻzbekcha, ruscha, inglizcha.` | **FACT — INCOMPLETE.** Four output languages ship, including Uzbek Cyrillic. | `Oʻzbekcha (lotin ham, kirill ham), ruscha, inglizcha.` |
| `@bayram_uzbot ichida:` | **REGISTER** — «Внутри @bayram_uzbot» translated straight; it makes something sound physically inside the handle | `@bayram_uzbot botida shunday:` |
| `bot linkni oʻzi yuboradi` | **G3** | `bot havolani oʻzi yuboradi` |
| `hazil` throughout | **VERIFIED CORRECT.** `😂 Hazil` is the literal button; the writer brief is "an affectionate, funny roast"; the prompt rules forbid profanity, politics, religion, romance, alcohol and real-artist references. | unchanged. **Never write `diss`.** |
| `Ismini toʻgʻri aytdi — mana shunisi qoʻrqinchli.` | **FACT — CONDITIONAL**, and the best-worded version of the claim on the whole slate: it is a reaction, not a guarantee | ships on a pass |
| `15 000 soʻm — bitta taksi puli.` | **VERIFIED TRUE** | unchanged |
| shot list 0:23–0:26 *"the bot's own price/confirm screen"* | **FACT — TWO SCREENS THAT CANNOT BOTH EXIST.** With a credit: the confirm summary and `🎬 Yozib olinsin`, no price. Without: the paywall, no `🎬`. | **Pick one and shoot that one.** The card burns `15 000 soʻm` at 0:13 → shoot the **paywall** face on the zero-credit account. |
| `Doniyoooor, taksida puling yoʻq...` | OK — it is a lyric from the real hazil track and must match the audio word for word | verify against the delivered file before burning |
| `Doniyor ruxsat berdi (hali ham oʻzini bosolmayapti).` | OK — natural, funny, and it is the consent line | unchanged |

```
=== ON SCREEN, in edit order ===

«...Doniyoooor, taksida puling yoʻq...»     <- karaoke, word-by-word, frame one

Doʻstimga hazil qoʻshiq yozdirdim.

Ismini toʻgʻri aytdi — mana shunisi qoʻrqinchli.

15 000 soʻm — bitta taksi puli.

@bayram_uzbot
Izohga BAYRAM deb yozing.

=== ON SCREEN — RU cut ===

«...Дониёёёр, в такси денег нет...»

Заказал другу шуточную песню.

Имя произнёс правильно — вот это и страшно.

15 000 сум — одна поездка на такси.

@bayram_uzbot
Напишите BAYRAM в комментариях.

=== CAPTION UZ ===

Doʻstimga hazil qoʻshiq yozdirdim va toʻgʻridan-toʻgʻri unga yubordim. Ismini toʻgʻri aytdi.

@bayram_uzbot botida shunday: ismni yozasiz, savollarga javob berasiz, qoʻshiq chatga keladi. Hazil ham bor, tugʻilgan kun ham, toʻy ham. Oʻzbekcha (lotin ham, kirill ham), ruscha, inglizcha.

Doniyor ruxsat berdi (hali ham oʻzini bosolmayapti).

Ertaga kimning tugʻilgan kuni?

15 000 soʻm · @bayram_uzbot

#bayram #sovga #toshkent #prank #uzbekistan

=== CAPTION RU ===

Заказал другу шуточную песню и сразу отправил ему. Имя произнёс правильно.

Внутри @bayram_uzbot: пишете имя, отвечаете на вопросы, песня приходит в чат. Есть шуточные, есть на день рождения, есть на свадьбу. По-узбекски (и латиница, и кириллица), по-русски, по-английски.

Дониёр разрешил (до сих пор не может успокоиться).

У кого завтра день рождения?

15 000 сум · @bayram_uzbot

#bayram #sovga #toshkent #prank #uzbekistan

=== CTA ===

UZ: Izohga BAYRAM deb yozing — bot havolani oʻzi yuboradi.
RU: Напишите BAYRAM в комментариях — бот сам пришлёт ссылку.

=== AUTO-DM BODY ===

UZ: Salom! Mana havola — ismi bilan qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_roast
RU: Привет! Вот ссылка — песня с его именем создаётся здесь: t.me/bayram_uzbot?start=ig_roast

=== THE BOT SCREEN TO FILM AT 0:23 (paywall face — shoot on a zero-credit account) ===
=== VERBATIM PRODUCT STRING. DO NOT EDIT IT TO MATCH THE BURNED TYPE — match the type to it. ===

🔒 Soʻzlar sizniki. Pul yozib olishga toʻlanadi.

💳 Bitta qoʻshiq — 15 000 soʻm

Siz tanlamaguningizcha hech narsa yozilmaydi.

[button] 💳 15 000 soʻm — 1 qoʻshiq
```

---

### 5.11 CARD 8 — USTOZGA ATALGAN QOʻSHIQ

| Original | Verdict | Use this |
| --- | --- | --- |
| shot list: *occasion «kasb bayrami / ustoz»* | **FACT — NOT A BUTTON.** | The operator taps `🎉 Bayram`, or `✨ Boshqa sabab` and types it. **No on-screen text or caption may name a teachers' occasion as a menu item.** The teacher-ness comes from the free-text note step — a real capability, just not a labelled occasion. |
| `Toʻliq ismi bilan. Otasining ismi ham.` | **GRAMMAR** — the second fragment drops the instrumental | `Toʻliq ismi bilan. Otasining ismi bilan ham.` |
| `Toʻliq ismi bilan, otasining ismi bilan qoʻshiq qildim.` | **G2** — the rule was declared and then not applied to this caption | `Toʻliq ismi bilan, otasining ismi bilan qoʻshiq yozdirdim.` |
| `Gul bir haftada soʻliydi. Qoʻshiq qoladi.` | **OK and the strongest line on the card.** (G5: card 9 matches this, not the other way round.) | unchanged |
| `1-oktabr — 14 kun qoldi.` | **VARIABLE — recompute on posting day.** Correct only if posted 2026-09-17. | see the countdown table |
| `«...Nodira Karimovna...»` | **HIGHEST-RISK RENDER ON THE SLATE** phonetically, and a Russified honorific published by a brand whose pitch is "your name the way it is actually said", in the week of an alphabet-Latinisation vote. | **Ask her which form she wants sung, and sing that.** The patronymic is ordinary school register and not disrespectful — but it is her call, and a first-name-only fallback lyric is already budgeted. |
| `Notoʻgʻri chiqsa — yozing, qayta yozamiz.` | **G7 + FACT — CONDITIONAL** (no mechanism) | `Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.` — keep only on a written commitment |
| *never state the patronymic as a guarantee* | **CORRECT RULE, KEEP IT.** The caption says a thing we did, never a capability we promise. | unchanged |
| `Shu videoni sinfdoshingizga yuboring.` | OK — the highest-intent forward on the slate | unchanged |

**Countdown table — burn the right number:**

| Post date | Uzbek card | Russian card |
| --- | --- | --- |
| 17 Sep | `1-oktabr — 14 kun qoldi.` | `1 октября — осталось 14 дней.` |
| 18 Sep | `...13 kun qoldi.` | `...13 дней.` |
| 20 Sep | `...11 kun qoldi.` | `...11 дней.` |
| 22 Sep | `...9 kun qoldi.` | `...9 дней.` |
| 25 Sep | `...6 kun qoldi.` | `...6 дней.` |
| 28 Sep (last shippable day) | `...3 kun qoldi.` | `...3 дня.` |

Russian noun agreement: `дней` for 5–20, `дня` for 2–4, `день` for 1.

```
=== ON SCREEN, in edit order ===

«...Nodira Karimovna...»            <- karaoke hit, frame one

Ustozimga 20 yildan keyin.

Toʻliq ismi bilan. Otasining ismi bilan ham.

@bayram_uzbot

Gul bir haftada soʻliydi. Qoʻshiq qoladi.

1-oktabr — 14 kun qoldi.          <- RECOMPUTE ON POSTING DAY
15 000 soʻm — bitta taksi puli
@bayram_uzbot
Izohga BAYRAM deb yozing.

=== ON SCREEN — RU cut ===

«...Nodira Karimovna...»

Моей учительнице — через 20 лет.

Полное имя. И отчество.

@bayram_uzbot

Цветы завянут за неделю. Песня останется.

1 октября — осталось 14 дней.     <- ПЕРЕСЧИТАТЬ В ДЕНЬ ПУБЛИКАЦИИ
15 000 сум — одна поездка на такси
@bayram_uzbot
Напишите BAYRAM в комментариях.

=== CAPTION UZ ===

Ustozimni 20 yildan keyin koʻrdim. Toʻliq ismi bilan, otasining ismi bilan qoʻshiq yozdirdim.

1-oktabrgacha 14 kun qoldi. Gul bir haftada soʻliydi — qoʻshiq qoladi. Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.

Shu videoni sinfdoshingizga yuboring. Ustozingizning toʻliq ismini faqat ikkalangiz bilasiz.

15 000 soʻm · @bayram_uzbot

#bayram #ustozlarkuni #sovga #toshkent #uzbekistan

=== CAPTION RU ===

Увидел свою учительницу через 20 лет. Записал ей песню с полным именем и отчеством.

До 1 октября осталось 14 дней. Цветы завянут за неделю — песня останется. Вышло не так — напишите, переделаем.

Отправьте это видео своему однокласснику. Полное имя вашей учительницы знаете только вы двое.

15 000 сум · @bayram_uzbot

#bayram #ustozlarkuni #sovga #toshkent #uzbekistan

=== CTA (burned at ~0:21) ===

UZ: Shu videoni sinfdoshingizga yuboring.
RU: Отправьте это видео однокласснику.

=== AUTO-DM BODY ===

UZ: Salom! Mana havola — ustozingiz uchun qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_ustoz
RU: Привет! Вот ссылка — песня для вашей учительницы создаётся здесь: t.me/bayram_uzbot?start=ig_ustoz

=== ORIGINAL AUDIO NAME ===

Bayram — Ustozga
```

---

### 5.12 CARD 9 — TORT SAHNAGA AYLANDI

| Original | Verdict | Use this |
| --- | --- | --- |
| `gul uch kunda soʻliydi` | **G5** — card 8 says one week | `gul bir haftada soʻliydi` |
| `Sahnani AI chizdi. Qoʻshiqni AI yozdi. Ismni toʻgʻri aytdi.` | **FACT — the third sentence is conditional.** The first two are exactly right and are the card's honesty payload. | ships on a human-listen pass for `Gulnoza`. If it fails: `Sahnani AI chizdi. Qoʻshiqni AI yozdi. Ismni biz tekshirdik.` |
| `«Gulnoza», hech qanday buzilishsiz` | **REGISTER + FACT.** Nominalised «без единого искажения» — nobody says `buzilishsiz` about a name being pronounced, and this is the slate's strongest claim, so the worst place to sound like a spec sheet. | `ismini esa buzmasdan, toʻppa-toʻgʻri aytdi: «Gulnoza»` — and it ships on a pass, or it is cut. Do not soften it into a hedge over a take that is still wrong. |
| `Stol ustidagi eng arzon narsa` | **REGISTER** — «на этом столе» carried over. An Uzbek birthday table is a *dasturxon*; `stol ustidagi narsa` is furniture-talk and throws away the one culturally warm word on the card. | `Dasturxondagi eng arzon narsa` |
| `Tort 200 000 · Gullar 40 000 · Qoʻshiq 15 000` | **`Qoʻshiq 15 000` is VERIFIED.** The other two are the playbook's placeholders. | verify against the day's real cake and flower receipts; do not invent round numbers |
| `Tort ertaga tugaydi. Qoʻshiq qoladi.` | OK — the best-constructed line on the card | unchanged |
| CTA `Birga oʻylashayotgan…` vs caption `Birga tashkil qilayotgan odamingizga yuboring` | **CONSISTENCY + REGISTER.** Two verbs for one ask in one post; and `tashkil qilayotgan odamingiz` is the language of organising a conference, not a friend's birthday. | `Kim bilan birga tayyorlanayotgan boʻlsangiz, oʻshanga yuboring.` in both |
| the child blowing out the candle (0:05.5–0:06) | **LEGAL** — an identifiable minor, against the slate's own rule | **Default: an adult hand blows out the candle.** Otherwise written parental consent naming commercial and boosted use. |
| `Sahna — AI. Qoʻshiq — haqiqiy` (rejected alternative) | **CORRECTLY REJECTED** — it reads as "a human wrote this one", pointing at the decoy | stays rejected |

```
=== ON SCREEN, in edit order ===

«...Gulnoza...»                 <- karaoke lyric, magenta, 0:00.3
Ismi qoʻshiqda aytilgan.

Sahnani AI chizdi. Qoʻshiqni AI yozdi. Ismni toʻgʻri aytdi.

Tort 200 000 · Gullar 40 000 · Qoʻshiq 15 000
   [VERIFY the first two against the day's real receipts]

Tort ertaga tugaydi. Qoʻshiq qoladi.

@bayram_uzbot · 15 000 soʻm
Izohga BAYRAM deb yozing

=== ON SCREEN — RU cut ===

«...Gulnoza...»
Её имя звучит в песне.

Сцену нарисовал ИИ. Песню написал ИИ. Имя произнёс правильно.

Торт 200 000 · Цветы 40 000 · Песня 15 000

Торт закончится завтра. Песня останется.

@bayram_uzbot · 15 000 сум
Напишите BAYRAM в комментариях

=== CAPTION UZ ===

Tort ertaga tugaydi, gul bir haftada soʻliydi — qoʻshiq qoladi.

Dasturxondagi eng arzon narsa: 15 000 soʻm, ismi bilan. Sahnani AI chizdi, qoʻshiqni ham AI yozdi — ismini esa buzmasdan, toʻppa-toʻgʻri aytdi: «Gulnoza». Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.

Shu hafta kimningdir tugʻilgan kuni bormi? Kim bilan birga tayyorlanayotgan boʻlsangiz, oʻshanga yuboring.

@bayram_uzbot

#bayram #tugilgankun #sovga #toshkent #tort

=== CAPTION RU ===

Торт закончится завтра, цветы завянут за неделю — песня останется.

Самое дешёвое на этом столе: 15 000 сум, с её именем. Сцену нарисовал ИИ, песню тоже написал ИИ — а имя произнёс правильно, «Gulnoza», без единого искажения. Вышло не так — напишите, переделаем.

У кого-то на этой неделе день рождения? Отправьте тому, с кем вы это организуете.

@bayram_uzbot

#bayram #tugilgankun #sovga #toshkent #tort

=== CTA ===

UZ: Shu hafta tugʻilgan kun bormi? Kim bilan birga tayyorlanayotgan boʻlsangiz, oʻshanga yuboring.
RU: На этой неделе есть день рождения? Отправьте тому, с кем вы это организуете.

=== AUTO-DM BODY ===

UZ: Salom! Mana havola — ismi bilan qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_tort
RU: Привет! Вот ссылка — песня с её именем создаётся здесь: t.me/bayram_uzbot?start=ig_tort

=== KEYWORD ===

BAYRAM only. NEVER «QOʻSHIQ» — nobody types U+02BB and every miss is a permanently lost lead.
```

---

### 5.13 CARD 10 — PUL SOLMA, QOʻSHIQ SOL

| Original | Verdict | Use this |
| --- | --- | --- |
| `Gul ham ol. Ustiga ismini qoʻsh.` | **GRAMMAR** — literally instructs writing her name on top of the flowers. What you add is the **song**. | `Gul ham ol. Ustiga ismi bilan qoʻshiq qoʻsh.` (caption, siz-form: `Gulni ham oling — ustiga ismi bilan qoʻshiq qoʻshing.`) |
| ti-form card vs siz-form caption | **DELIBERATE, KEEP BOTH.** The card is ti-form to match `PUL SOLMA` / `QOʻSHIQ SOL`; the caption is siz-form. A register choice, not an error — noted so a proofreader does not "fix" it. | unchanged, documented |
| `90 soniya` | **CHECK BEFORE BURNING.** A song *length*, not a latency claim, so it does not violate the no-latency rule — but it must match a real delivered file. | measure an actual delivered MP3. If it is not ~90 s, change the number or drop it. |
| `Mersedes yoʻq. Ismi bor.` | **OK — the most repeatable sentence anyone wrote for this product.** | unchanged |
| `PUL SOLMA.` / `QOʻSHIQ SOL.` | OK — `pul solmoq` (to top up a card) is exactly the idiom the trend's own lyric uses. `QOʻSHIQ` here is **on-screen text**, which is fine; it is banned only as a hashtag or keyword. **But see §5.0(b): `qoʻshiq solmoq` is not an existing collocation and works only as a pun — an owner decision.** | unchanged pending that decision |
| `500 000 soʻm → Gulnoza` (transfer mock) | **KEEP THE MOCK NEUTRAL, never Payme's UI.** The reason has changed: not "our processor is fake" (it is real now) but "that shot is not our product". | unchanged, new reason |
| `Gulnoza — tugʻilgan kun` (the file caption in the chat) | must match what the bot actually names the file | **verify on the screen-record** |
| the "add-on, not substitute" reframe | **KEEP IT.** Without `Gul ham ol`, the video tells a man the woman is worth a taxi fare, and that read travels to her too. | unchanged |

```
=== ON SCREEN, in edit order ===

PUL SOLMA.
«...Gulnoza...»                 <- karaoke lyric, magenta, frame one

Bir daqiqa oldin
500 000 soʻm → Gulnoza          <- NEUTRAL transfer mock, never Payme's UI

QOʻSHIQ SOL.
Gulnoza — tugʻilgan kun

Mersedes yoʻq. Ismi bor.
Gul ham ol. Ustiga ismi bilan qoʻshiq qoʻsh.

15 000 soʻm · @bayram_uzbot
Izohga BAYRAM deb yozing

=== ON SCREEN — RU cut ===

НЕ КИДАЙ НА КАРТУ.
«...Gulnoza...»

Минуту назад
500 000 сум → Гулноза

КИНЬ ПЕСНЮ.
Гулноза — день рождения

Мерседеса нет. Есть её имя.
Цветы всё равно купи. Добавь сверху её имя.

15 000 сум · @bayram_uzbot
Напишите BAYRAM в комментариях

=== CAPTION UZ ===

Pul solma — qoʻshiq sol.

15 000 soʻm, 90 soniya, ismi toʻgʻri aytilgan qoʻshiq. Mersedes ololmasak ham, ismini kuylatib beramiz.

Gulni ham oling — ustiga ismi bilan qoʻshiq qoʻshing. Notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.

Kimga birinchi yuborasiz?

@bayram_uzbot

#bayram #sovga #tugilgankun #toshkent #qoshiq

=== CAPTION RU ===

Не кидай на карту — кинь песню.

15 000 сум, 90 секунд, песня, в которой её имя звучит правильно. Мерседес не потянем — а имя пропеть можем.

Цветы всё равно купите — добавьте сверху её имя. Вышло не так: напишите, переделаем.

Кому отправите первой?

@bayram_uzbot

#bayram #sovga #tugilgankun #toshkent #qoshiq

=== CTA ===

UZ: Izohga BAYRAM deb yozing.
RU: Напишите BAYRAM в комментариях.

=== AUTO-DM BODY ===

UZ: Salom! Mana havola — ismi bilan qoʻshiq shu yerda yoziladi: t.me/bayram_uzbot?start=ig_pulsolma
RU: Привет! Вот ссылка — песня с её именем создаётся здесь: t.me/bayram_uzbot?start=ig_pulsolma
```

---

### 5.14 ACCOUNT-LEVEL STRINGS — proofed, and two of them were broken

These are not on any card. They ship before post one, they are the most-read and least-edited strings on
the account, and the previous versions of the Name field and both bio lines were wrong in sense.

| Field | Ship this | Note |
| --- | --- | --- |
| **Name field** (search-weighted) | `Bayram \| Ismingiz bilan qoʻshiq · Tugʻilgan kun sovgʻasi` | **WAS:** `Ismli qoʻshiq` — which parses as "a song that has a title", i.e. every song ever recorded. Exactly the wrong reading for a brand selling personalised names. Both ʻ are U+02BB; the Name field is not a hashtag, so ʻ is safe and correct here. |
| **Bio line 1 (UZ)** | `Ismingiz toʻgʻri aytiladigan qoʻshiq. 90 soniya, 15 000 soʻm.` | **WAS:** `Ismni toʻgʻri kuylaydigan qoʻshiq` — a song cannot *sing*; a person or the bot sings, the song is what is sung. Also bare `ismni` (nobody's name) instead of `ismingiz`. Verify `90 soniya` against a real file first. |
| **Bio line 2 (UZ)** | `Tugʻilgan kun, toʻy, hazil, ustoz uchun — Telegramda yoziladi.` | **WAS:** `…hazil, ustozga —`, which breaks the list's case agreement at the last item. Occasions match real buttons (`🎂 Tugʻilgan kun`, `💒 Toʻy`, `😂 Hazil`); "ustoz uchun" is a use case, not a claimed menu item — correct, and it must stay that way, because there is no ustoz occasion. |
| **Bio link** | `t.me/bayram_uzbot?start=ig_bio` | **VERIFIED:** the t.me interstitial preserves the `?start=` payload. **Expect and allow for a second tap.** Do not imply it jumps straight into the bot, and do not build a custom redirect. |
| **Bio phone** | `+998 ...` | required for trust in this market; a bot-only bio reads as less trustworthy |
| **Keyword triggers** | `bayram`, `BAYRAM`, `bayrom`, `БАЙРАМ` | ASCII + Cyrillic variants, case-insensitive. **Never a keyword containing ʻ.** |

---

### 5.15 CANNED REPLIES — write these once, paste them all week

| Comment | UZ reply | RU reply |
| --- | --- | --- |
| «necha foiz toʻgʻri chiqadi?» | `Foizini aytmaymiz — bu shunday ishlaydi: qoʻshiq yozilgandan keyin bot ismni oʻzi tinglab chiqadi va notoʻgʻri chiqqan boʻlsa qaytadan yozadi. Sizniki notoʻgʻri chiqsa — bizga xabar bering, qaytadan yozib beramiz.` | `Проценты не называем. Механика такая: после записи бот сам прослушивает имя и перезаписывает, если оно прозвучало не так. У вас вышло не так — напишите, переделаем.` |
| «bu harf oʻzgaryapti-ku» (alphabet reform) | `Hozircha amaldagi imloda yozyapmiz.` — **nothing more. Never editorialise about the reform.** | `Пока пишем по действующим правилам.` |
| «tugʻilgan kun nishonlash joizmi?» | `Bu — har kimning oʻz ishi. Bizda tugʻilgan kundan boshqa sabablar ham bor: @bayram_uzbot` — **never argue theology.** | `Это личное дело каждого. У нас есть поводы и помимо дня рождения: @bayram_uzbot` |
| «staged-ku» | `Videodagi odamlar aktyor emas. Ertaga yana bittasi keladi.` | `Лица в кадре — не актёры. Завтра будет ещё одно.` |
| a name submitted for the ladder | `Yozib oldim. Bugun 10 tasiga qoʻshiq yozdiramiz.` (cap the promise publicly) | `Записал. Сегодня сделаем 10.` |
| a **drill** submission (the genre does not exist) | `Drill hozircha yoʻq — eng yaqini xip-xop. Shuni qilaymi?` | `Дрилла пока нет — ближайшее это хип-хоп. Сделать так?` |
| «Telegramdan chiqmasdan toʻlash mumkinmi?» | `Toʻlov Payme sahifasida boʻladi — tugmani bossangiz oʻsha yerga olib boradi, toʻlagach qoʻshiq oʻzi kela boshlaydi.` | `Оплата проходит на странице Payme — кнопка ведёт туда, после оплаты песня начинает записываться сама.` |

*(`Yozib olindi` was replaced because it is the product's own phrase for recording a song — the literal
button is `🎬 Yozib olinsin` — so replying it to a name submission reads as "your song has been
recorded", which is a delivery claim nobody made.)*

---

### 5.16 THE BANNED-PHRASE LIST — final, and shorter than the playbook's

**Replaces the playbook's shared prompt rules at line 761**, which were written around the stub premise
and are now wrong in both directions. ⚠️ **PLAYBOOK CONTRADICTED — line 761.**

**Never, in any language, on screen, in a caption, or in a reply:**

1. `«Telegramdan chiqmasdan»` / "pay inside Telegram" / "without leaving Telegram" — **still banned, new
   reason.** There are no Telegram native payments. The customer leaves for `checkout.paycom.uz`. The
   truthful line is `«Payme orqali 15 000 soʻm»` and the truthful mechanic on screen is
   `💳 → 🔗 Toʻlash → Payme sahifasi → qoʻshiq oʻzi kela boshlaydi`.
2. Any implication of **one tap** to payment. It is two taps with a screen between them (`prepare_link`
   is still unbuilt). Walk all ten storyboards and confirm no frame shows a single tap going straight to
   Payme.
3. `«ʻ ham, gʻ ham joyida»` or any claim that the modifier letter is **audible in the song**. The mark
   claim lives on the screen, where it is 100% true.
4. `«faqat ismni qayta yozamiz»` — inpainting does not fire on this account; a re-roll returns a whole
   different song.
5. `«pul olmaymiz»` / any refund promise — no mechanism exists.
6. `«kafolat»` / `«гарантия»` as a bare noun.
7. Any **percentage or count** of pronunciation success. Internally too. Nothing in the repo measures it.
8. `«hech bir AI...»` / "no AI can" / «единственный, кто...». Claim only `«bugun, shu ismlarda»`.
9. `«birinchi marta toʻgʻri aytildi»` about a specific take two native speakers have not passed.
10. `«4 ta savol»` — the wizard is nine steps. Say `«bir necha savol»` or say nothing.
11. Any **latency** number — no `«3 daqiqa»`, no `«19 soniya»`. (Settlement-to-delivered measured 30–66 s
    on three real purchases, so roughly one minute is defensible if a burned timer is ever wanted — but
    do not print anything tighter than ~60 s without re-measuring on the day.)
12. A **fabricated Payme receipt.** The real screens are now better than any mock — film those.
13. Bare `«Shashmaqom»` for a generated track. Always `«shashmaqom uslubida»`.
14. `«drill»` as a bot genre, `«jazz»` as a bot genre (it is `Jaz-launj`), `«kasb bayrami / ustoz»` as an
    occasion.
15. Any **plan or second price** — `49 000`, `12 ta qoʻshiq`, `30 kun`. One product, one price.
16. Any **platform-size number** (Telegram users, Instagram users) and any **engagement multiplier**
    (`3–5x a like`, `1 send = 15 likes`, the send-rate bands, the `1.3-second` fixation stat). None
    survive sourcing.
17. ʻ (U+02BB) in a **hashtag or a comment keyword**.
18. `«AI uchun qiyin»` is the only permitted difficulty label, and only on the machine — never a
    `difficulty` / `wrong` / `boss fight` frame on a person's name, a woman's name, an elder's name, or a
    name carrying a religious honorific.
19. The `GAY-rat` reading, in any form, including as a rendered take.
20. `«biz hammasini oʻchiramiz»` / "we delete everything on request" — support tickets are stored and
    `/forget` cannot erase them. If a card or reply goes near the privacy promise, this claim has a live
    hole in it.
21. **"People are already buying" / «allaqachon sotib olishyapti»**, or any traction claim, until somebody
    confirms whose money the 14 settled payments are (§1, #9).

---

### 5.17 PRE-FLIGHT CHECKLIST — tick before anything is exported

**Tonight, before the render gate**

- [ ] Pinned note created with `ʻ Oʻ oʻ Gʻ gʻ ʼ`, shared to the editor, the caption writer and the
  on-camera operator
- [ ] Smart Punctuation OFF on every device that will touch caption text
- [ ] CapCut font test passed on the shoot phone: `Oʻgʻiloy` `Gʻulomjon` `qoʻshiq` `toʻgʻri` all render as
  a turned comma **in the exported file**
- [ ] Every `15 000` in every card uses U+00A0 between `15` and `000`
- [ ] Grep the final caption file for U+0027, U+2019, U+2018, U+0060, U+00B4 — **zero hits inside any
  Uzbek word** (command in §5.1)
- [ ] Card 5: drill replaced with `XIP-XOP` in the render, the picker screen-record **and** the caption —
  all three say the same word
- [ ] Card 5: `JAZZ` replaced with `JAZ-LAUNJ` in all three
- [ ] Card 5 + card 9: minors decision made and recorded (default: cut)
- [ ] Card 8: occasion decision made — `🎉 Bayram` or `✨ Boshqa sabab` + free text
- [ ] Card 3: ORIGINAL AUDIO renamed `Bayram — shashmaqom uslubida (Oʻgʻiloy)`
- [ ] Card 4: driver cast with no `gʻ` in his name, or the Gʻayrat take cleared by two native speakers
- [ ] Card 4: default fare card set to the surge variant
- [ ] Written commitment obtained (or the line cut) on `«qaytadan yozib beramiz»`; `«pul olmaymiz»` deleted
  from card 3 regardless
- [ ] Account Name field and both bio lines replaced with the §5.14 versions **before** post one

**On the shoot morning**

- [ ] One operator opens @bayram_uzbot on a phone and screenshots the paywall reading
  `💳 Bitta qoʻshiq — 15 000 soʻm`. Thirty seconds, and it closes the last gap in the price fact.
- [ ] One real 15 000 soʻm purchase put through the live rail as a rehearsal before a camera is pointed at
  anything — nobody has exercised it in ~37 hours
- [ ] The filming account has a credit on it **if** you intend to film the confirm summary with
  `🎬 Yozib olinsin` (that is an admin write; a human must do it)
- [ ] Every name in every cut graded pass by two native speakers who are not on the production team, on
  the **exact take that appears in the cut**
- [ ] Card 8 countdown recomputed for the actual posting date
- [ ] Card 9 price stack checked against the day's real cake and flower receipts
- [ ] Card 10's `90 soniya` measured against a real delivered file
- [ ] Signed Uzbek likeness releases, **before any camera rolls**, for every identifiable person in cards
  2, 3, 4, 5, 6, 7, 8, 9, 10

---
## 6. PACK THREE — THE HIGGSFIELD SESSION

**Tonight, 17 Sept, 19:00–20:30. One person, one laptop, judged on a phone.**
**Only two cards touch Higgsfield: card 9 (cake world) and card 6 (prank studio still). Everything else
on the slate is ZERO generations and stays that way.**

### 6.0 THE HARD RULE — read before you open the console

> **NO UZBEK TEXT INSIDE A GENERATED FRAME. EVER. Not a name, not a caption, not a word on a cake, not a
> sign on a wall. Every ʻ goes on in CapCut afterwards.**
>
> Why, once: the model garbles Latin-Extended glyphs and nobody has ever tested it on Uzbek Latin — a
> broken ʻ inside the one video that argues "we say your name right" is the product's entire claim
> failing on screen, in the frame, unfixable after posting.

Every prompt in this pack already ends with the exclusion line. **Do not shorten it.**

### 6.1 BEFORE YOU GENERATE ANYTHING — 3 checkboxes

- [ ] **The real cake photo exists.** Shoot the actual cream cake + orange candle on the phone FIRST and
  have the JPG on the laptop. It goes into Soul as the reference so the render chases the real object.
  Without it, do not start — the match cut at 0:05.5 is the whole shot and it fails if the two cakes do
  not look related. **Nothing in the call sheet currently assigns this. It is the single most likely way
  tonight's session collapses.**
- [ ] **Read the live credit prices off the logged-in console** and write them here: Soul still ___ cr ·
  video 5s 720p ___ cr · video 5s 1080p ___ cr. Published pricing disagrees across every source; the
  budget below assumes ~7 cr per 5s 720p video clip and cheap stills. If the console says otherwise, the
  burn-down in §6.7 is wrong and you re-plan before spending.
- [ ] **Confirm your plan's preset list** actually contains SUPER DOLLY IN and DOLLY IN. Fallbacks in §6.3.

### 6.2 THE PROMPTS — paste exactly

Four prompts. Two for card 9, one for card 6, one optional. Nothing else gets generated tonight.

#### 9A — CAKE WORLD, the hero still (Soul 2.0)

Attach the real cake photo as a reference before generating.

```
photoreal macro miniature scene, a cream-frosted birthday cake photographed as if it were a landscape, a full concert stage standing on the frosting, a tall stage light rig at centre burning with a warm orange flame at its tip and magenta stage lights below it, long banquet tables of tiny seated guests running back to the cake's horizon, faces not visible and nobody recognisable, a mountain-sized silver fork and porcelain cup at the cake's edge for scale, dark warm room, dusty volumetric light, 35mm, shallow depth of field, still air, physically stable frosting — no text, no signage, no lettering, no writing on the cake, no logos, no brand marks, no watermark
```

#### 9B — CAKE WORLD, clip 1 (image-to-video from the approved 9A still)

One camera move only. Stacking moves produces warping.

```
slow SUPER DOLLY IN toward the stage on the cake, one camera move only, subtle dust motes in the light, stable physics, frosting does not move, flame burns steadily, no people walking, no crowd movement, no hands entering frame — no text, no signage, no lettering, no music, no dialogue
```

**Reverse this clip in CapCut** so it plays as the pull-back. Never ask the model to invent the reveal.

#### 9C — CAKE WORLD, clip 2 (image-to-video from the SAME still, passed as `@image_1`)

```
slow DOLLY IN on the stage light rig and the silver fork, one camera move only, flame burning steadily with warm orange fire at the tip, magenta rim light only on the stage below, no people in frame, no hands — no text, no signage, no lettering, no music, no dialogue
```

Generate 4s, trim to 2s in CapCut. **Clip 2 is the first thing abandoned if the session runs long.**

#### 6A — PRANK STUDIO STILL (Soul 2.0, still only — no video stage)

```
photoreal portrait, back view of a young man seated at a large condenser microphone in a small dark recording studio, big over-ear headphones, both hands resting flat on a pop filter, face turned away from the camera and not visible at any angle, one warm practical light from the left, shallow depth of field, 35mm, subtle film grain, vertical 9:16 — no screens, no mixing desk, no plaques, no posters, no framed art, no text, no signage, no lettering, no logos, no visible face, no reflection of a face
```

**Do NOT generate his face.** A single-selfie likeness will not survive a sibling who has known that face
for twenty years. Identity here is carried by the haircut and the jacket — and the real person wears that
same jacket on camera, which is what sells it.

#### OPTIONAL — long sectioned variant for 9A only

If the short prompt keeps returning a flat or literal cake after 6 attempts, and only then, rewrite 9A in
the sectioned form the long-prompt models want: `GLOBAL STYLE / SCENE / LOCATION / FIRST FRAME AND
BLOCKING / OPTICS / PHYSICS / LIGHTING / AUDIO (none)`. Keep every exclusion. Do not do this for the
video clips — those want short and one move.

### 6.3 MODE, PRESET, FALLBACK

| # | Mode | Settings | If unavailable on our plan |
|---|---|---|---|
| **9A** | Soul 2.0, still | 9:16, 1080p, quality **High** | Soul Cinema. If 1080p is locked → 720p is acceptable; it is behind motion for 3.5s. Never drop 9:16. |
| **9B** | Image-to-video, preset **SUPER DOLLY IN** | 5s, 9:16. **720p for all test attempts, 1080p for the winner only** | Plain **Dolly In** → then **Zoom In**. Never Crash Zoom. If image-to-video is capped at 8s/720p on this tier, take it — the clip is 3.5s on screen. |
| **9C** | Image-to-video, preset **DOLLY IN** or **STATIC** | 4s, 9:16, 720p | **Static.** If credits are tight, skip generation entirely: hold the 9A still and add a 2% Ken Burns push in CapCut. Zero credits, indistinguishable at 2 seconds. |
| **6A** | Soul 2.0, still | 9:16, 1080p, High | 720p fine. This still is filmed off a phone screen, handheld, at an angle, with glare, never more than ~60% of frame, 2.5s max — the degradation is free cover. |

**BANNED PRESETS, all cards, no exceptions:** Crash Zoom · Bullet Time · Earth Zoom · Action Figure. They
are the 2025 slop signature and read as "made with an AI preset" inside 1.5 seconds. *(This ban is
carried forward from the playbook and is an inference, not sourced data — no source ranks presets by
audience fatigue. It is cheap to obey and expensive to test.)*

**BANNED COMBINATION:** never combine a lipsync generation with a camera-move preset. They are different
surfaces; the combined shot does not exist. (Nothing tonight uses lipsync anyway.)

**NEVER let it generate audio.** Higgsfield has no music generator and we already have the song. Every
video prompt carries `no music, no dialogue`. Do not use Veo-with-audio.

### 6.4 NEGATIVE PROMPTING — the scroll-past tells

Already baked into the prompts above. Do not edit them out. If a model on this plan has a separate
negative field, paste:

```
text, lettering, signage, writing, logos, watermark, subtitles, captions, recognisable faces, extra fingers, malformed hands, plastic skin, waxy sheen, HDR glow, oversaturated, looping fire, plasma flame, melting geometry, warped edges, duplicated objects, camera shake, multiple camera moves, motion blur smear, crowd movement, music, dialogue, voice
```

The five tells that specifically kill these two shots:

1. **Garbled lettering** — the model invents words on cake, mic, wall. The #1 giveaway.
2. **Fire that loops or looks like plasma** — fire is the hardest physical thing these models do, and the
   flame IS the match cut. A flame that pulses on a loop is an instant reject.
3. **Hands** — 6A has two hands on a pop filter. Count the fingers every single time.
4. **Plastic/waxy skin and HDR glow** — reads as "ad" not "photo".
5. **Warping or drift from a stacked camera move** — one move per clip, always.

### 6.5 GENERATE-AND-REJECT PROTOCOL

**Judge every frame on the shoot phone, held at arm's length. Never on the laptop.** A laptop flatters a
generation by about one full quality grade and nobody will ever watch this on one.

**Attempt budget — hold these numbers:**

| Shot | Attempts | Keep | Hard stop |
|---|---|---|---|
| 9A cake still | 8–15 | 1 | **At 15 with nothing usable: abandon the card-9 spectacle.** Ship the phone half as a 14-second reaction-plus-price-stack cut. The price stack is the asset; the cake world is the wrapper. |
| 9B clip 1 | 2–4 (720p), then 1× 1080p of the winner | 1 | 4 |
| 9C clip 2 | 1–2 | 1 | 2 (or skip — CapCut push) |
| 6A studio still | 6–8 | 1 | 8 |

**REJECT IMMEDIATELY — do not "fix it in the edit":**

- [ ] Any legible or semi-legible character anywhere in frame
- [ ] Any face in focus (9A tiny guests must be mush/backlit; 6A must show NO face at any angle, including
  a reflection in the mic body or a window)
- [ ] Flame that is magenta, white, blue or plasma-looking — **the generated flame must be ORANGE.**
  Magenta lives only in the stage rig below and in CapCut typography. If the flame is not orange the match
  cut forces a grade on the real table, and a visibly graded frame in a video arguing "this table is real"
  is a self-own.
- [ ] Flame that pulses, loops or has no heat shimmer
- [ ] Frosting that moves, melts, ripples or behaves like liquid during the camera move
- [ ] Hands with wrong finger count, fused fingers, or a hand entering frame that shouldn't (9B/9C)
- [ ] Headphone band merging into the skull; mic stand geometry that doesn't resolve (6A)
- [ ] A mixing desk, monitor screen, plaque or poster appearing in 6A — it means the exclusions were dropped
- [ ] Two camera moves in one clip, or any drift/warp at the edges
- [ ] The fork or cup changing size or position mid-clip
- [ ] Anything that reads "stock" or "graded ad" on the phone at arm's length

**The 1.5-second test:** look at it for 1.5 seconds on the phone and look away. If your first thought was
about the image rather than about the cake, reject it.

### 6.6 ORDER OF OPERATIONS

**9A blocks everything on card 9** — clips 1 and 2 cannot start until a still is approved.

1. **19:00 — 9A cake still.** Start here. Queue in batches of 4, judge on the phone between batches.
2. **19:00, parallel — 6A studio still.** Terminal shot, no video stage, runs beside 9A on a second
   concurrent slot. Six to eight, pick one, done by ~19:25.
3. **~19:40 — 9B clip 1 at 720p**, 2–4 attempts, pick the move.
4. **~20:00 — 9B winner re-rendered once at 1080p.** 1080p is roughly 2.5× the generation time of 720p;
   this is why it is one render, not four.
5. **~20:15 — 9C clip 2.** Last, cheapest, most disposable.
6. **Tomorrow 12:00–13:00 (lunch, at a desk):** reverse 9B in CapCut and pick the final cake wide.

**IF THE SESSION RUNS LONG, abandon in this order:**

1. **9C clip 2** → replace with a CapCut Ken Burns push on the 9A still.
2. **9B 1080p re-render** → ship the 720p. It is 3.5s behind a dolly move.
3. **The whole card-9 generated half** → ship the phone half as the 14s cut. This is the playbook's own
   kill rule and it is not a failure.
4. **6A is the last thing you give up** — cheapest generation on the board, pivot of a 30-second video,
   and there is no practical substitute for it.

**Never extend past 20:30.** 21:30 is the render-gate grading and that decides whether the house block
shoots at all.

### 6.7 CREDIT & TIME BUDGET

**Envelope: 60–100 credits, 60–90 minutes. Nothing else on the slate touches Higgsfield.**

| Item | Qty | Est. credits |
|---|---|---|
| 9A cake stills | 8–15 | fill in from console |
| 6A studio stills | 6–8 | fill in from console |
| 9B clip 1, 720p tests | 2–4 × ~7 cr | 14–28 |
| 9B clip 1, 1080p winner | 1 × ~14–25 cr | 14–25 |
| 9C clip 2, 720p | 1–2 × ~7 cr | 7–14 |
| **Total** | | **hold at ≤100** |

**Checkpoint at 50 credits:** stop, count what you actually have in hand, and decide. If you are past 50
with no approved 9A still, you are already in the kill case — spend the rest on 6A and go to bed.

**Cost discipline, non-negotiable:** every video test at 720p on the cheapest engine available; 1080p is
one render of one winner. Do not test at 1080p.

### 6.8 FACES — the absolute prohibitions

**A. No recognisable real or historical person is generated. Ever. Faced, faceless, silhouetted, or
chyron-labelled "AI".** This is not a style note, it is the law and it is live:

- **ЗРУ-1115, in force since 21 January 2026.** Unlawful processing of a person's personal data using AI,
  plus distribution online, is an administrative offence: **50–100 BRV ≈ 20.6–41.2 million soʻm, with
  confiscation of the equipment used.**
- A dead person's image rights sit with their **heirs**. There is no "it's a generic face" defence and no
  public-domain-after-N-years clause for likeness.

**Specifically and by name: no retro Uzbek estrada performer is generated tonight or ever without
sign-off.** There is no generic 1970s Uzbek estrada face for a model to reach for — the era is one man
wide (Botir Zokirov, d. 1985), and every other plausible output is either recently dead and still mourned
(Sherali Joʻrayev, d. 4 Sep 2023) or alive and litigable (Farrux Zokirov, b. 1946). **Card 5's
red-curtain stage plate is NOT queued this session.** If anyone reopens it: shoot it practically with a
real person in a real jacket — cheaper than the credits, and it carries none of this. If a retro plate is
ever genuinely wanted, the gate is: **three Uzbeks over 50 see the still and say yes, BEFORE anything is
generated. Default answer is no.**

**B. No Soul ID training on anyone in this shoot.** It needs 20+ photos of a consenting person and a
signed release naming AI generation of their likeness and voice — and reviewers still report identity
drift across separate generations. We need none of it tonight.

**C. Consistency, when a shot needs the same thing twice.** Card 9 needs the same *world* twice, not the
same person: generate **one** approved 9A still, then pass that identical still into both clips — clip 2
references it inline as `@image_1`. Never regenerate a second still and hope the two match; they will not.

**D. Card 6's identity is carried practically, not by the model.** Back of head, headphones, haircut,
jacket — and the real brother wears that same jacket in the real footage.

**E. The tiny guests in the cake world are crowd texture, not people.** Small, backlit, out of focus. If a
face resolves clearly enough to read as a person, reject the frame.

### 6.9 WHAT THIS PACK DOES NOT AUTHORISE

Zero generations on cards **1, 2, 3, 4, 5, 7, 8, 10**. Every one of those had an AI insert and every one
was deliberately deleted — in nine separate producibility reviews the generated frame was the thing that
broke the video. Do not add a generated divider, flame, candle, night-street bridge, end plate or stage
plate to any of them. A viewer who clocks one synthetic frame doubts every real face in the cut.

**Card 9 note carried over from the cultural review:** the phone-side match-cut target is a **real orange
candle blown out by an adult hand**, not by the child. Cut on the smoke either way, never on the frosting
edge.

---

## 7. PACK FOUR — CONSENT, RELEASES AND THE DIGNITY RULES

**For the phone, on location. Read the box you need. If a box is unticked, that person does not appear in
the cut.**

Fill the four blanks marked `⟦FILL⟧` **before printing.** They are the same four on every page: the
operator's full name, the operator's phone, the Instagram handle, and the backup phone of a second person
who answers. **`/support` may not be used as the contact route** — `BAYRAM_SUPPORT_CONTACT` ships blank,
so the bot's support command has no configured destination. Print 20 copies of §7.1 double-sided (Uzbek
one side, Russian the other).

**Three things overriding the playbook, decided this morning:**
- Card 4's method «take a vague filming yes at pickup» is **deleted**. A signed release before the ride,
  or the ride is not filmed. ⚠️ **PLAYBOOK CONTRADICTED — line 339.**
- Card 3's 0:20–0:22 consent beat stays in the cut **as warmth only**. It is not the consent.
- Card 5's child (0:09–0:12) and card 9's child (0:05.5–0:06) are **cut by default**, and card 2's
  teenager is dropped. See §7.5.

### 7.1 THE RELEASE FORM

Hand it over, then **read it aloud anyway** — every time, to everyone, including people who can obviously
read. An unread signed form protects nobody, and reading it aloud takes 50 seconds.

#### 7.1a Uzbek Latin — print side A

> **BAYRAM — VIDEOGA OLISH VA JOYLASHTIRISHGA ROZILIK**
>
> Sana: ______________  Joy: ______________
>
> **1. Kim olyapti.** Men, **⟦FILL: ism-familiya⟧**, «Bayram» (@bayram_uzbot) uchun video olyapman.
> Telefonim: **⟦FILL: telefon⟧**.
>
> **2. Nima uchun.** Bu — reklama. Biz bu video orqali qoʻshiq sotamiz va undan pul topamiz.
>
> **3. Qayerda chiqadi.** Instagram, TikTok, Telegram, YouTube va boshqa tarmoqlarda. Pullik reklama
> sifatida ham koʻrsatilishi mumkin. Qisqartirilgan yoki boshqacha montaj qilingan koʻrinishda ham.
>
> **4. Nechta odam koʻradi.** Bilmaymiz. Yuzta odam ham koʻrishi mumkin, million odam ham. Odamlar
> videoni yuklab olishi, boshqalarga yuborishi va oʻz sahifasiga qayta joylashi mumkin — **bunday
> nusxalarni biz oʻchira olmaymiz.** Internetga chiqqan video butunlay yoʻqolmaydi.
>
> **5. Nima ishlatiladi.** Yuzingiz, ovozingiz va ismingiz. Ismingiz sunʼiy intellekt (AI) yordamida
> qoʻshiqda kuylanadi.
> Ismim aynan shu koʻrinishda yozilsin: ______________________
> Qoʻshiqda: ☐ faqat ismim  ☐ toʻliq ismim  ☐ otamning ismi bilan
>
> **6. Avval koʻrasiz, keyin hal qilasiz.** Video joylanishidan oldin sizga toʻliq koʻrsatamiz. «Yoʻq»
> desangiz — joylanmaydi. Sabab aytishingiz shart emas.
>
> **7. Keyin ham fikringizni qaytarib olsangiz boʻladi.** Joylangandan keyin ham «olib tashlang» deng: oʻz
> sahifalarimizdan **24 soat ichida** oʻchiramiz, pullik reklamani **1 soat ichida** toʻxtatamiz. Sabab
> soʻramaymiz, koʻndirmaymiz.
>
> **8. Pul.** ☐ Toʻlandi: __________ soʻm  ☐ Toʻlanmadi.
> Toʻlangan boʻlsa: video joylansa ham, joylanmasa ham bu pul sizniki.
>
> **9. Koʻrsatmaydigan narsalarimiz.** Hujjatlaringiz, telefon raqamingiz, manzilingiz, mashinangiz raqami
> va bank kartangiz — hech biri kadrda boʻlmaydi.
>
> Bularning hammasini oʻqidim (yoki menga oʻqib berishdi) va tushundim. **Roziman.**
>
> Ism-familiya: ______________________
> Telefon: ______________________
> Imzo: ______________  Sana: ______________
>
> **Bizga yozish uchun:** ⟦FILL: telefon⟧ · ⟦FILL: ikkinchi telefon⟧ · Instagram: ⟦FILL: @handle⟧

#### 7.1b Russian — print side B

> **BAYRAM — СОГЛАСИЕ НА СЪЁМКУ И ПУБЛИКАЦИЮ**
>
> Дата: ______________  Место: ______________
>
> **1. Кто снимает.** Я, **⟦FILL: ФИО⟧**, снимаю видео для «Bayram» (@bayram_uzbot). Мой телефон:
> **⟦FILL: телефон⟧**.
>
> **2. Зачем.** Это реклама. Мы продаём через это видео песни и зарабатываем на нём.
>
> **3. Где появится.** Instagram, TikTok, Telegram, YouTube и другие соцсети. Может показываться как
> платная реклама. Может быть сокращено или перемонтировано.
>
> **4. Сколько людей увидит.** Мы не знаем. Может сто человек, может миллион. Люди могут скачать видео,
> переслать его и выложить у себя — **эти копии мы удалить не сможем.** Попавшее в интернет видео не
> исчезает полностью.
>
> **5. Что будет использовано.** Ваше лицо, ваш голос и ваше имя. Ваше имя будет спето в песне с помощью
> искусственного интеллекта (ИИ).
> Писать моё имя именно так: ______________________
> В песне: ☐ только имя  ☐ полное имя  ☐ с отчеством
>
> **6. Сначала посмотрите, потом решите.** Перед публикацией мы покажем вам готовое видео целиком.
> Скажете «нет» — не опубликуем. Причину объяснять не нужно.
>
> **7. Передумать можно и потом.** Уже после публикации скажите «уберите» — удалим со своих страниц **в
> течение 24 часов**, платное продвижение остановим **в течение 1 часа**. Причин не спрашиваем и
> отговаривать не будем.
>
> **8. Деньги.** ☐ Выплачено: __________ сум  ☐ Не выплачено.
> Если выплачено: деньги ваши независимо от того, выйдет видео или нет.
>
> **9. Чего в кадре не будет.** Ваши документы, номер телефона, адрес, номер машины и банковская карта.
>
> Я всё это прочитал(а) — или мне прочитали вслух — и понял(а). **Согласен / согласна.**
>
> ФИО: ______________________
> Телефон: ______________________
> Подпись: ______________  Дата: ______________
>
> **Как с нами связаться:** ⟦FILL: телефон⟧ · ⟦FILL: второй телефон⟧ · Instagram: ⟦FILL: @handle⟧

#### 7.1c The 20-second verbal version — say it into the camera

Only for a subject who genuinely cannot sign now: a street subject in the rain, a driver at the kerb with
the engine running. **Everybody in the house block signs paper.**

**Uzbek — say exactly this:**

> «Assalomu alaykum. Men Bayram degan botga reklama video olyapman — bu tijorat videosi, biz undan pul
> topamiz. Video Instagram va TikTokda chiqadi. Uni juda koʻp odam koʻrishi mumkin — million kishigacha —
> va odamlar bir-biriga yuboradi, oʻchira olmaymiz. Joylashdan oldin sizga koʻrsataman. Keyin ham «olib
> tashlang» desangiz, 24 soat ichida oʻchiraman. Telefonim: ⟦FILL⟧. Endi ismingizni ayting va rozimisiz
> yoki yoʻqmi — ovoz chiqarib ayting.»

**Russian — say exactly this:**

> «Здравствуйте. Я снимаю рекламное видео для бота Bayram — это коммерческое видео, мы на нём
> зарабатываем. Видео выйдет в Instagram и TikTok. Его может увидеть очень много людей — вплоть до
> миллиона — и люди пересылают такое друг другу, эти копии мы удалить не сможем. Перед публикацией я вам
> его покажу. И потом, если скажете «уберите», удалю в течение 24 часов. Мой телефон: ⟦FILL⟧. Теперь
> назовите своё имя и скажите вслух, согласны вы или нет.»

**They must answer out loud, in their own voice:** «Men ______, roziman.» / «Я ______, согласен(на).»
**Then you say the date out loud, in the same shot:** «Bugun 17-sentabr, 2026-yil.»

#### 7.1d What makes a verbal consent actually usable

- [ ] **One unbroken take.** Their face visible, audio clean, your words and their answer in the same
  shot. No cut anywhere in it.
- [ ] **They say their own name and the word roziman / согласен out loud.** A nod is not consent. A laugh
  is not consent. Silence is not consent. «Mayli» said over the shoulder while walking away is not consent.
- [ ] **You say the date and the platforms out loud** in the same take, so the clip dates itself.
- [ ] **Within one hour**, send them a Telegram or SMS message repeating points 1–7 of the form, and ask
  them to reply. Their one-word reply is the durable record. **Screenshot it.**
- [ ] **Save both** — the clip as `consent_<ism>_<sana>.mp4` and the screenshot — in the shoot folder.
  Neither is deleted while the video is live.
- [ ] The consent clip is **not** put into the posted video unless they separately agreed to that.
- [ ] **No clip and no message reply = it did not happen.** That person is reframed out or the episode is
  dropped to the A-roll.

### 7.2 WHAT UZBEK LAW REQUIRES

Written from what was verified on 2026-09-17. Where it is not settled, it says so and gives the
conservative practice. **This is a production rule sheet, not legal advice.**

#### 7.2a In force today — high confidence

**Law ЗРУ-1115 of 21 January 2026**, in force from publication. Unlawful processing of a person's personal
data **using AI**, and distributing it through media or the internet, is an administrative offence (CAO
art. 46-2): **50–100 BRV, roughly 20.6–41.2 million soʻm, plus confiscation of the equipment used.**

Read that against what this slate actually does: it takes a real person's **name**, **face** and generated
**singing voice** and publishes them commercially. That is the described conduct. Clean consent is the
whole defence. The parliamentary record behind the law cited voice-and-image falsification cases rising
from 1,129 in 2023 to 3,553 in 2024 — an enforcement priority, not a dormant clause.

**Civil Code art. 99.** The right to one's own image is a personal non-property right, inalienable. For a
person who has died, it is exercised by others, including the **heirs**.

**AI ethics rules**, MoJ registration No. 3787 of 14 March 2026 — eight principles including openness and
transparency. Binding today.

**AI content marking** — the obligation lands **1 March 2027**, and is reported as an obligation on large
platforms to provide the capability, not on authors to use it. **So Uzbek law does not require us to label
AI today.** Instagram's rules do, and we label anyway.

#### 7.2b Not settled — treat as in force

**New Civil Code art. 100-1 (image consent).** Passed the Legislative Chamber **121–0 on 7 October 2025**,
sent to the Senate; in force three months after official publication. **Nobody has confirmed whether it
has been signed** — somebody must check lex.uz. Until then, **assume it is live.** What it says:

- Filming a person and using the footage requires **their consent**.
- A person who has died and gave no consent in life: **their heirs** consent.
- **Under 16: the parents** consent.
- **Public-place exception is narrow** — it covers filming "to reflect the general process" at gatherings
  and public places. A tight, identifying, commercially used portrait of one named person is the opposite.
- A publicly shared image may be reused **excluding commercial purposes**. Everything on this slate is a
  commercial purpose.

#### 7.2c Street vs private car vs flat

**A public street is not a free pass.** Card 2 films eight people on one block to keep four.
- A **wide street frame** where nobody is the subject — traffic, a crowd, backs of heads — is the "general
  process" the exception covers. Shoot as much of it as you like.
- The moment the camera **holds on one recognisable face**, or their name appears on screen or in the
  caption, you are outside the exception. **Signed release, before that shot, every time.** No exceptions
  for "he clearly didn't mind".
- Never film someone, then approach them afterwards. Filmed first, asked afterwards is not consent, and
  opt-out blurring is not consent.

**A private car is the driver's workplace and a private space.** Card 4.
- Consent from a working man mid-fare, while his rating depends on his passenger, is **not free consent**.
  Fix the power imbalance before you fix the paperwork.
- **Hire the ride outright for a stated fee, paid before you roll, paid whether or not it posts.** Write
  the amount on the release.
- **Signed release before the ride starts.** Not at the kerb, not at the lights, not after.
- **Second explicit on-camera yes at the kerb**, after the fare is settled and the rating submitted, so he
  answers a passenger who can no longer hurt him.
- **Blur the plate and the trip ID.** Do not show the app screen with his surname or phone. Do not show
  the aggregator's driver profile.
- Say on screen that he was paid — the card already does.
- Shoot the **hands / dashboard / fare-screen A-roll on every ride**, mandatory, not a fallback, so the
  episode survives a withdrawal.
- **Not verified:** whether the ride-hailing platform's own terms restrict filming a driver. Conservative
  practice: do not show the platform's branding and do not imply it endorses us.

**A flat is somebody's home.** Cards 3, 5, 6, 9, 10.
- The **householder** agrees to filming in the home, **and** every identifiable person in shot signs
  separately. One household yes does not cover a cousin who walked through the kitchen.
- Anyone in the background who has not signed is **reframed out or the take is re-shot**. Not blurred
  afterwards.
- Nothing identifying in frame: house number, street sign through the window, documents on the dasturxon,
  the address on a delivery box.
- Everyone in the room is told **both phones are rolling**, before they start.

**A school or staff room is an institution.** Card 8.
- The teacher's own consent **does not cover the school**. Film in a flat. That is already the card's
  instruction — keep it.
- **No classroom, no children, no uniforms, no money collection** shown or mentioned.
- Ask her **which form of her name she wants sung** and sing that one. Tick it on the form (§7.1a point 5).

#### 7.2d Where the releases live

Not established in this phase, so: conservative practice. One folder per shoot, one subfolder per subject,
holding the photographed form or the consent clip, the message screenshot, and the takedown log line. Not
a public cloud link. Kept for as long as the video is live plus one year. Not posted, not shared outside
the team.

**Never say "we delete everything about you."** The bot's `/forget` erases customer data but **cannot
erase support tickets** — that hole is live today. Our promise is about the **video and the raw footage of
that person**, and nothing else.

### 7.3 THE ELDER RULE — card 3, Oʻgʻiloy, 79

The single unrepeatable take on the slate. It is also one comment thread away from «buvisini kontent
qildi».

**Before the camera exists**
- [ ] Asked **at least an hour before**, in her own language, in the room, with **no camera running**.
- [ ] **Asked by her own grandchild or child** — never by the operator, never by "the brand". The relative
  who asks is the same person who appears on camera as the giver and is named in the caption.
- [ ] She is told, in plain words: this goes on the internet · strangers will watch it · possibly a very
  large number of them · people will send it to each other and we cannot take those copies back · **we are
  selling something with it**.
- [ ] **Signed release before the tea is poured.**
- [ ] She is told both phones will be rolling, and where they are.

**Who must be in the room, the whole time**
- [ ] The relative who is the giver, on camera.
- [ ] One more adult from the household.
- [ ] **Never her alone with the crew.** If the room empties, stop rolling until somebody comes back.

**After**
- [ ] She is shown **the actual clip**, on a phone, full screen, sound up, at least once, before anything
  is posted.
- [ ] **Her no kills it. Absolutely, without a reason, forever.** Nobody in the room argues, re-asks, or
  "shows her how good it looks". If she kills it, we shoot **a different grandmother** — we do not direct
  this one.
- [ ] Her no stands for a month afterwards too.
- [ ] The caption does **not** praise her. Expect «koʻz tegmasin» in the comments on a 79-year-old woman's
  face and full name; restraint is the answer, not more warmth.
- [ ] Her street, her mahalla and her full passport name stay out unless she explicitly said yes to each.

**Stop filming the moment any of these happens**
1. She covers her face, or turns away from the camera rather than toward the person.
2. She says stop, even once, even lightly — «boʻldi», «olma», «qoʻy», «yetar».
3. She cries in a way that is not joy: silent, head down, hand to the chest.
4. She asks **twice** who will see this.
5. She starts fixing her scarf or her hair **for the camera**. She has stopped being a person and started
   performing.
6. She looks to a relative for permission before answering a question.
7. She asks whether she has done something wrong.
8. She becomes confused about what the song is or who made it, or repeats the same question.
9. The song or the moment turns to somebody who has died, and the room goes to grief.
10. Anything about her breathing, her colour, or her needing to sit down. She is 79 and no frame is worth it.

**What "stop" means:** stop rolling, **say out loud that you have stopped**, put the phone face-down on the
table, and do not pick it up for ten minutes. If it happens a second time, **the shoot is over** — and what
is already filmed is not posted without a fresh yes, given on a different day.

**Never re-take an emotion.** If the first take fails, the answer is a different grandmother, not a second
performance.

### 7.4 THE PRANK RULE — cards 6 and 7

Cards 6 and 7 are a lie and a roast. Both are shippable. Neither survives one careless frame.

#### 7.4a Where the line is

| Affectionate — it ships | Humiliating — it does not |
| --- | --- |
| The joke is on **your** effort and **your** lie | The joke is on his body, money, intelligence, marriage or family |
| He is the hero of the reveal | His shame, panic, tears or anger **is** the product |
| He would run the same prank back on you | It depends on a fact he would never volunteer: debt, a breakup, weight, a failed exam, a family fight, health, religion |
| Nothing in the cut is something he hasn't already told people himself | He is the last person in the room who knows |
| He is visibly **in on it** on camera after the reveal | A third party who never consented is named in the lyric |
| He says yes to the cut, first time, unprompted | He says «oʻchir» and then agrees after you push. **Pressure means no.** |

#### 7.4b Card 6 — the «studiyaga bordim» lie

- [ ] **The only false thing is the effort and the photo.** The song is genuinely his from frame one, and
  one card says so out loud: «Qoʻshiq haqiqiy — faqat rasm soxta edi.»
- [ ] **The product is never the instrument of the lie.** Never a fake payment, never a fake receipt, never
  «pulini toʻladim» about money nobody moved.
- [ ] Brother, male cousin or friend — not a sister.
- [ ] The final card «Bu rasmni ham AI chizgan.» stays. Own the AI.
- [ ] Not the account's first or second post.

#### 7.4c Card 7 — the hazil roast

- [ ] **1:1 chat only.** The person roasted is the person sitting on the sofa. No group chat, no other
  names, no other avatars.
- [ ] **No third party named in the lyric.** Not his boss, not his girlfriend, not his landlord.
- [ ] The word is **hazil**, never «diss».
- [ ] Phone on Do Not Disturb so unrelated notification banners never intrude.
- [ ] The product's own prompt rules already forbid profanity, politics, religion, romance, alcohol and
  real artists. **So if a line still stings, it is a personal line you added, not a product output — cut it.**

#### 7.4d Consent to the format, the day before

The surprise is the format. That is fine — you get consent to **the format**, not to the words. The day
before, on the record (a Telegram message, screenshotted), say exactly this and get a yes:

> «Ertaga sen haqingda hazil qoʻshiq yozdiraman, reaksiyangni suratga olaman va Instagramga joylayman.
> Qoʻshiqda nima deyilishini oldindan bilmaysan. Joylashdan oldin tayyor videoni senga koʻrsataman —
> yoqmasa, joylamayman. Rozimisan?»

He does not know the lyric. He knows everything else. That is informed, and the format survives.

#### 7.4e THE MANDATORY BEAT — he approves the cut before it posts

This is not optional and it is not a formality.

- [ ] He watches **the final export** — with the captions, the on-screen text and the end card, sound on,
  on a phone, the way a stranger will see it. Not the rushes.
- [ ] **Not on the day it was shot.** Show it the next morning, when he is not still laughing.
- [ ] He says yes **in writing**: «Koʻrdim, joylasa boʻladi.» Screenshot it.
- [ ] **Silence for 24 hours is a no**, not a yes.
- [ ] If he asks for one beat to come out, it comes out. No negotiation. If what is left does not work, the
  video does not exist.
- [ ] Tell him in advance: **if the comments turn on him, we delete the post.** Then actually do it.

### 7.5 CHILDREN

**The default is: no child appears.** The slate contradicts its own «Do not publish minors» rule in three
places, and this morning's decision resolves it:

- **Card 5, 0:09–0:12** — the six-year-old dancing: **cut.** Lead on bobo instead.
- **Card 5's on-screen card «6 YOSHLI AMIRXONGA — JAZZ»** — a named minor on a commercial account:
  **banned as written**, even if the frame goes.
- **Card 9, 0:05.5–0:06** — the child blowing out the candle: **cut.** An adult hand blows it out.
- **Card 2** — the teenager: **dropped entirely.**
- **Card 8** — no classroom, no children, no uniforms. Already so; keep it.

#### If somebody with authority overrides that default

Then **all nine** of these, together, or the frame does not exist:

1. [ ] **Written consent from the parent or legal guardian**, signed before the camera rolls, naming:
   commercial use · paid boosting · re-cuts · indefinite duration · **AI processing of the child's name and
   voice**.
2. [ ] **The child's own yes**, asked separately, by the parent, in front of the operator. **The child's no
   beats the parent's yes.**
3. [ ] **No name.** Not on screen, not in the caption, not sung in the audio used on camera.
4. [ ] **No face as the subject of the frame.** Hands, back of the head, a wide family frame.
5. [ ] **No school, no uniform, no classroom, no address, no mahalla, no street sign, no house number.**
6. [ ] **Never boosted with money. Never in a paid ad. Never in a thumbnail.**
7. [ ] A parent is **physically present for every second** of filming and holds a veto throughout,
   including after seeing the cut.
8. [ ] **Comments limited or turned off** on any post containing a child.
9. [ ] A **named adult signs off** that points 1–8 all pass. Write the name here: ______________

**Stop rule:** a child who stops playing and starts performing for the camera is finished. Stop, and do not
restart.

**When in doubt, the answer is no.** A six-year-old cannot consent to being forwarded a million times, and
cannot withdraw in fifteen years when it matters to him.

### 7.6 ON-SET CHECKLIST — one per subject, ticked before they appear

> **Subject:** ______________________  **Card #:** ____  **Date / time:** ______________
> **Operator:** ______________________  **Phone in their hand:** ______________

- [ ] **1. TOLD, BEFORE ANY CAMERA** — in their language: who we are · that this is a **commercial ad** ·
  that it goes on Instagram, TikTok, Telegram and YouTube · that it **may be boosted with money** · that it
  could be seen by **millions** · and that **forwarded copies cannot be recalled**.
- [ ] **2. CONSENT CAPTURED** — ☐ paper release signed and **photographed** (signature and date legible) ·
  ☐ 20-second verbal consent recorded **and** the follow-up message sent **and** replied to. Saved to the
  shoot folder: ☐
- [ ] **3. NAME SPELLING CONFIRMED BY THE PERSON** — they wrote it themselves. Copy it here exactly, do not
  correct it:
  `______________________________`
  Sung as: ☐ first name only ☐ full name ☐ with patronymic
  (ʻ, gʻ, oʻ, x, q exactly as **they** wrote them. Keep the current spelling — do not restyle it, and do not
  discuss the alphabet reform on camera or in a reply.)
- [ ] **4. APPROVAL-AFTER-VIEWING AGREED** — they know they will see the finished cut before it is posted,
  that **no** at that point is final, and that it needs no reason.
- [ ] **5. CONTACT GIVEN** — a real person's name and a phone that is answered, written on their copy of the
  release **and** said out loud. Number given: ______________
- [ ] **6. PAID** (stranger and taxi cards) — ______ soʻm, paid **before** rolling, and paid whether or not
  it posts.
- [ ] **7. A-ROLL INSURANCE SHOT** — hands / dashboard / fare screen / wide, in the can.
- [ ] **8. NOTHING IDENTIFYING IN FRAME THEY DID NOT AGREE TO** — plate, trip ID, house number, street sign,
  school, uniform, documents, card digits, phone screen, other people.
- [ ] **9. EVERYONE ELSE VISIBLE** has signed, or has been reframed out. (Reframed, not blurred later.)
- [ ] **10. CHILDREN** — ☐ none in frame · ☐ §7.5 complete and signed off by ______________
- [ ] **11. OVER 70** — ☐ n/a · ☐ §7.3 elder protocol running, relative present: ______________
- [ ] **12. PRANK/ROAST CARD** — ☐ n/a · ☐ format consent taken yesterday, screenshotted, and the approval
  beat (§7.4e) is scheduled for **tomorrow morning**.

> **Operator signature:** ______________
> **Anyone on set may stop the shoot. Today the person who decides it stays stopped is:** ______________

**If any box above is unticked, that person does not appear in the cut.** The A-roll exists for exactly this.

### 7.7 THE TAKEDOWN PROMISE

#### 7.7a For the bio — paste-ready

**Uzbek:**
> Videoda oʻzingizni koʻrdingizmi, joylanishini xohlamaysizmi? Yozing — 24 soat ichida oʻchiramiz.

**Russian:**
> Увидели себя в видео и не хотите этого? Напишите — удалим в течение 24 часов.

#### 7.7b The full commitment — for a story highlight, the pinned comment, and the back of the release

1. **Who can ask.** Anyone visible or audible in the video, anyone named in it, a parent or guardian, or an
   heir if the person has died. No documents, no proof.
2. **How.** A DM to the account, or the phone number on the release. One sentence is enough. **No reason
   required.** We do not argue, and we never offer money or a discount to keep it up.
3. **How fast.** Down within **24 hours of the message being sent** — the clock starts when they send it. If
   the post is being **boosted with money, the boost stops within 1 hour.**
4. **What comes down.** The post, on **every** platform we put it on — Instagram, TikTok, Telegram, YouTube
   — plus the original-audio page if their name is in it, plus **any re-cut using the same footage.**
5. **What we honestly cannot do.** We cannot delete copies other people downloaded, forwarded, re-uploaded
   or screen-recorded. **We say this before they sign, not after they ask.**
6. **The smaller option.** If they want it changed rather than gone — a blur, their name out, a different
   caption — we do that inside the same 24 hours. Offer it second; never lead with it.
7. **Their raw footage.** If they ask, we delete every take of them, not just the posted cut, and confirm
   when it is done. We keep only the signed release and the takedown request itself — **and we tell them
   that is what we are keeping.**
8. **We never bring it back.** Not with a new caption, not a month later, not in a compilation.
9. **We log it.** One line in the shoot folder: date asked · date down · what came down · who confirmed.
10. **None of this depends on what they were paid.** Keeping the fee and asking for the video to come down
    is allowed, and is not a thing we mention.

**Do not widen this promise.** It covers the video and our own raw footage of that person. It does **not**
say "we erase everything about you" — messages sent to the bot's support route cannot currently be erased
by `/forget`, so that sentence would be false the moment somebody tested it.

---
## 8. PACK FIVE — THE NAME REPLY-LADDER: OPERATIONS

**Read on the phone. Do not improvise. Every literal string below is paste-ready.**

Facts this pack is built on (verified 2026-09-17, they override the playbook): price is **15 000 soʻm**
(U+00A0 inside the number), the rail is **live production Payme**, the bot's picker has **no drill and no
"ustoz" occasion**, and the pronunciation machinery **cannot hear gʻ/oʻ/x/q** — it folds them away. That
last one is why §8.2 and §8.4 look the way they do.

### 8.0 BEFORE THE FIRST REPLY GOES OUT — one-time setup

- [ ] Operator filming account is **already onboarded** (language screen + phone-number screen done). A
  fresh account shows «📱 Raqamni yuborish» before any picker and it cannot be edited out.
- [ ] Operator account **holds credits**. An account with 0 credits never reaches the confirm screen — the
  paywall replaces it and there is **no 🎬 Yozib olinsin button**. Credits come from an admin grant, which
  needs an ADMIN role plus a step-up re-auth. **A human must do this. It is a production write.**
- [ ] Ladder log spreadsheet exists with exactly these columns: `date · post permalink · commenter handle ·
  name as submitted · lang · decision (RENDER/DECLINE/HOLD) · ear-check pass/fail · reply video URL ·
  notified y/n`. Nothing else. See §8.3.
- [ ] ElevenLabs plan and **month-to-date generation minutes** written at the top of the log. Without this
  number §8.5 cannot be enforced.
- [ ] The pinned comment is live on every ladder parent post, in both languages:

> UZ: `Qoida: faqat OʻZ ismingizni yoki rozi boʻlgan odamning ismini yozing. Boshqa odam haqida qoʻshiq yozmaymiz. Kuniga 10 ta.`
> RU: `Правило: пишите СВОЁ имя или имя человека, который согласен. О посторонних мы не поём. 10 в день.`

- [ ] Owner has confirmed **in writing** whether «notoʻgʻri chiqsa — qaytadan yozib beramiz» will be
  honoured by hand via /support. There is **no re-roll button in the bot**. If the answer is no, that line
  comes out of every caption and template today.

### 8.1 THE LOOP — one reply video, start to finish

| # | Step | Who/where | Time |
|---|---|---|---|
| 1 | **Triage** the comment against §8.2 | phone, comment tab | 1 min |
| 2 | **Log the row** — decision first, work second | spreadsheet | 30 s |
| 3 | **Render** in @bayram_uzbot: named wizard only | operator phone | 2 min typing |
| 4 | **Lyric** appears free → ✅ Shu matn qolsin → 🎬 Yozib olinsin | same | 1 min |
| 5 | **Wait.** Observed 30–66 s. Budget is 420 s. Batch 3 renders, do not sit and watch | — | overlapped |
| 6 | **EAR CHECK** — two native speakers, pass/fail, one question | two people | 1 min |
| 7 | **Cut** in the CapCut ladder template: swap audio, swap name card | laptop/phone | 6 min |
| 8 | **Post** — cover, caption, exactly 5 ASCII hashtags | Instagram | 3 min |
| 9 | **Notify** the commenter with an acceptance reply carrying the link | comment tab | 1 min |

**Hands-on per unit: ~14 min** once the template is muscle memory. Day one is ~20 min.
**Realistic throughput: 4 per hour solo, 5–6 per hour with two people** (one renders + ear-checks, one cuts
+ posts). **10 a day ≈ 2.5 hours of one person.** That is the public cap and the honest ceiling for one
operator.

**Step 3, the non-negotiables:**
- The **named wizard only**. Never «✍️ Oʻz matnim» — that path sets recipient = None, skips the name chunk,
  skips the listen-back, and its "verified" status is structurally absent. A take from that path may never
  appear in a ladder video.
- The picker screen recorded in the cut must land on a real occasion. **«✍️ Oʻz matnim» sits on the same
  screen** — frame it out or keep it visibly unpressed.
- Genre words that exist: `🎤 Pop · 📻 Retro estrada · 🎧 Xip-xop · 🤘 Rok · 🎸 Akustik ballada · 🕺 Raqs /
  elektron · 🌟 Oʻzbek estradasi · 🪕 Oʻzbek xalq qoʻshigʻi · 🎻 Shashmaqom · 🎷 Jaz-launj`. **There is no
  drill.** Write "xip-xop", not "drill", in the caption and on screen.
- The **note step stays empty or generic.** Never type the identifying detail the commenter volunteered
  (workplace, school, "my qaynona", city). See §8.3.

**Step 6, the ear check — this is the gate the whole ladder lives or dies on:**
- Two native speakers, neither of them the person who cut the video.
- One question, nothing else: **«Bu ism toʻgʻri aytildimi?»**
- **Do not show them the bot's own verdict.** Its verifier folds gʻ→g, oʻ→o, x→h, q→k and squeezes doubled
  letters. `name_similarity("Gʻayrat","Gayrat") = 1.000`. It is deaf to exactly the thing we are selling.
- **Unanimous pass = publish. Anything else = do not publish.** Re-render once; a re-render is a
  **completely different song**, so it is a new lottery ticket, not a patch. Fail twice → the commenter
  gets the **holding** reply in §8.4, never a public video with their name sung wrong.
- Publishing a mispronounced name under a brand whose entire pitch is correct pronunciation is the single
  worst thing this ladder can do. It is worse than not replying.

**Step 7, what the reply video may and may not claim:**
- ✅ May show the name **spelled** correctly on the bot's own confirm screen. That claim is 100% true and a
  commenter can reproduce it in ten seconds.
- ✅ May quote the bot's own copy: «Qoʻshiq yozilgach, shu soʻzni tinglab koʻraman va notoʻgʻri chiqqan
  boʻlsa, qaytadan yozaman.»
- ❌ **Never** «ʻ ham, gʻ ham joyida» or any claim the modifier letter is audible.
- ❌ **Never** a percentage, a count, or a success rate. Not on screen, not in a caption, not in a reply.
- ❌ Never «faqat ismni qayta yozamiz», never «kafolat» / «гарантия», never «hech bir AI…».
- ❌ Never a latency number. Never «4 ta savol» — the wizard is 9 steps; say «bir necha savol».
- ❌ Never a name under a "qiyin / notoʻgʻri / boss fight" label. If a difficulty frame is used at all:
  **«AI uchun qiyin»** — the machine's problem, never the person's.
- ❌ Never the «GAY-rat» reading. Gʻulomjon carries the same gʻ and none of the exposure.

### 8.2 THE REFUSAL LIST

A name in a public comment is a request to sing about a real person who did not ask. **Default is no. A yes
is earned by the submitter naming themselves.**

**NEVER RENDERED — no discussion, no exceptions:**

- [ ] Any slur, or a name deliberately spelled to produce one when sung.
- [ ] **Public figures** — politicians, officials, clerics, bloggers, singers, athletes, anyone with a
  Wikipedia page or a blue tick. Law **ЗРУ-1115 (in force since 21 Jan 2026)**: unlawful AI processing of a
  person's personal data plus online distribution = 50–100 BRV (20.6–41.2 m soʻm) **plus confiscation of
  the equipment**.
- [ ] **Dead people.** No exceptions, including "my late grandfather". A deceased person's likeness sits
  with their heirs.
- [ ] Obscene, sexual, or degrading submissions.
- [ ] A name **attached to an insult, a verdict or a grievance** — «qaynonam X, qanday jirkanch»,
  «direktorimiz X ahmoq». The insult contaminates the name; the whole comment is declined.
- [ ] Anything that reads as **bullying a named private person**: a name plus a physical description, a
  name plus a failing, a name submitted by a group all piling on.
- [ ] **Minors named by someone who is not their parent.** Even with a parent: no minor's name is published
  on screen.
- [ ] A name plus **identifying detail**: surname + workplace, school + class, mahalla, house, phone, plate,
  employer, «5-maktab 9-B». See the handling rule below.
- [ ] A submission in a thread that has already turned hostile (§8.6).

**RENDERED ONLY IF:**
- [ ] The commenter is naming **themselves** («mening ismim…»), or
- [ ] The commenter says the person has agreed **and** the name is a bare given name with no detail
  attached, and the video shows the given name only.

**HOW TO DECLINE WITHOUT A FIGHT — three rules:**
1. **One reply, then stop.** Never a second reply in the same thread. Never argue, never explain the law,
   never quote a policy.
2. **Never name what was wrong.** Do not write "this is bullying" or "that's a slur". Decline warmly and
   generically (§8.4). Naming the offence starts the fight.
3. **Do not delete the comment unless it contains a slur, a phone number, an address or an obvious minor's
   details.** Hiding a comment is visible and reads as censorship; a warm generic decline reads as a queue.
   - If it must go: **hide** it (Instagram's hide, not delete) and do not announce it.
   - Repeat offender: restrict the account. No public mention.

**A SUBMISSION THAT IS SOMEONE ELSE'S FULL NAME + IDENTIFYING DETAIL:**
1. Do **not** reply in the thread with the name in it, and do **not** quote any part of it.
2. **Hide the comment** immediately — identifying detail about a third party on our post is our exposure.
3. Log it as `DECLINE — third-party PII`, log the permalink, **do not copy the detail into the log**.
4. Reply once, generically, with template D in §8.4. Do not address the detail.
5. If it repeats from the same account: restrict, do not block (a block is a notification, a restrict is not).
6. If the detail is an address, a phone number, a workplace, or anything about a child: **hide + restrict +
   tell the owner the same day.** That is the §8.6 escalation shape.

### 8.3 PRIVACY — names volunteered in comments

A comment is **not** an order. The 90-day identity purge covers the order **we** create in the bot. It
covers nothing on Instagram.

**WHAT WE KEEP**

| Kept | Where | How long |
|---|---|---|
| Comment permalink | ladder log | campaign + 90 days, then deleted |
| Given name as submitted | ladder log | campaign + 90 days |
| Commenter handle | ladder log **only** | campaign + 90 days |
| Decision + ear-check result | ladder log | campaign + 90 days |
| The rendered song file | operator's phone + archive | purged on the bot's own 90-day clock |

**WHAT WE NEVER WRITE DOWN, ANYWHERE**
- Surnames, patronymics, workplaces, schools, mahallas, cities, phone numbers, ages.
- Anything about a third party the commenter volunteered.
- Screenshots of the comment section saved "for later".

**WHAT IS NEVER REPUBLISHED ON SCREEN OR IN A CAPTION**
- ❌ The commenter's **@handle**, avatar or profile photo — unless they said yes, in writing, in that thread.
- ❌ A screenshot of the comment with the handle or avatar visible. If a comment is shown at all: **crop to
  the text, no handle, no photo, no like count.**
- ❌ Any **surname or patronymic**. On screen, first name only. Always.
- ❌ Any DM content. Ever. A DM is not a comment.
- ❌ The number of submissions received, as a boast.

**HARD PROHIBITIONS**
- **No list building.** A commenter is not a lead. Do not export handles, do not add anyone to a broadcast,
  do not DM anyone who did not trigger the keyword automation.
- **The auto-DM fires once, carries the raw `t.me/bayram_uzbot?start=ig_*` link, and that is the whole
  relationship.** An Instagram comment does not open a 24-hour window; a "tap below" follow-up never arrives.
- **Do not type the commenter's volunteered detail into the bot's note field.** It becomes order data under
  a real retention clock for a person who never contracted with us.

**DELETION ON REQUEST — what we actually promise**
- «Videoni oʻchirib bering» → **take the reply video down within 24 hours**, no questions, no counter-offer.
  Then delete the log row.
- Their own comment is theirs to delete; we can hide it on request.
- ⚠️ **Never say "we delete everything about you."** Support tickets are stored and `/forget` does not erase
  them. The honest line is: «videoni oʻchiramiz va ismingizni roʻyxatdan olib tashlaymiz.»

### 8.4 REPLY TEMPLATES

Reply in the language the comment was written in. **The space inside `15 000` is U+00A0** — copy the string,
do not retype it.

**A · ACCEPTANCE** (name accepted, going into today's batch)
> UZ: `Qabul qilindi ✅ Ismingiz roʻyxatda. Bugungi 10 talikka kiradi — video shu izohga javob boʻlib keladi.`
> RU: `Принято ✅ Ваше имя в списке. Войдёт в сегодняшнюю десятку — видео придёт ответом сюда же.`

**B · HOLDING** (accepted, not today — also the reply after a failed ear check)
> UZ: `Roʻyxatdasiz, navbat hali kelmadi. Kuniga 10 ta ulguramiz, ertaga davom etamiz — yoʻqotib qoʻymadik.`
> RU: `Вы в списке, очередь ещё не дошла. В день успеваем 10, завтра продолжаем — мы вас не потеряли.`

**C · DECLINE** (generic, warm, never names the reason)
> UZ: `Bu safar ulgurmadik, kechirasiz 🙏 Har kuni faqat 10 tasini qilamiz. Xohlasangiz oʻzingiz qilib koʻring: @bayram_uzbot`
> RU: `В этот раз не успели, извините 🙏 Каждый день делаем только 10. Хотите — сделайте сами: @bayram_uzbot`

**D · «WE DON'T SING ABOUT PEOPLE WHO DIDN'T ASK»** (third-party name, mocking submission, name+insult)
> UZ: `Biz faqat oʻzi soʻragan odam haqida qoʻshiq yozamiz. Oʻz ismingizni yozing — bajonidil qilamiz 🙂`
> RU: `Мы поём только о тех, кто попросил сам. Напишите своё имя — с удовольствием сделаем 🙂`

One reply. Then stop. Do not respond again in that thread.

**E · CONVERSION** (a warm commenter, not a bot voice)
> UZ: `Buni botning oʻzi qiladi: ismni yozasiz, bir necha savolga javob berasiz, soʻzlarini bepul koʻrasiz. Yozib olish — 15 000 soʻm. @bayram_uzbot`
> RU: `Это бот делает сам: пишете имя, отвечаете на несколько вопросов, слова видите бесплатно. Запись — 15 000 сум. @bayram_uzbot`

True as written: the lyric is genuinely free and on screen; the recording is what is sold.

**F · «NECHA FOIZ TOʻGʻRI CHIQADI?»** (the sceptic — mechanism, never a number)
> UZ: `Foizini aytmaymiz — oʻlchagan odam yoʻq. Bu shunday ishlaydi: qoʻshiq yozilgach bot ismni oʻzi tinglab koʻradi va notoʻgʻri chiqqan boʻlsa qaytadan yozadi.`
> RU: `Проценты не называем — их никто не измерял. Механика такая: после записи бот сам прослушивает имя и перезаписывает, если прозвучало не так.`

**G · «BU HARF OʻZGARYAPTI-KU»** (alphabet reform, 10 Sep 2026 — neutral, never editorialise)
> UZ: `Hozircha amaldagi imlodan foydalanamiz. Qoida oʻzgarsa — biz ham oʻzgaramiz.`
> RU: `Пока используем действующее написание. Изменится правило — изменимся и мы.`

**H · «NOTOʻGʻRI CHIQDI» (a real customer complains)** — ⚠️ **DO NOT USE until the owner has committed in
writing to honouring this by hand.** There is no re-roll button in the bot.
> UZ: `Kechirasiz. /support orqali yozing — qaytadan yozib beramiz.`
> RU: `Извините. Напишите через /support — перезапишем.`

**NEVER IN ANY REPLY:** a percentage · «kafolat»/«гарантия» · «faqat ismni qayta yozamiz» ·
«Telegramdan chiqmasdan» / «pay inside Telegram» / "one tap" (the real flow is 💳 → 🔗 Toʻlash → Payme
sahifasi — the customer leaves Telegram) · theology · a platform statistic · the competitor's name · any
claim that people are already buying.

### 8.5 THROUGHPUT AND COST

**Per reply video:**

| Line | Value |
|---|---|
| Music render, 90 s | $0.30 |
| Average music attempts per name | **1.17** (22 of 24 passed on attempt 1; 2 needed 3) |
| LLM (intake + lyric + respelling) | $0.0072 |
| Name-verification speech-to-text | $0.0006 |
| **Vendor cost per published reply** | **≈ $0.36** — budget **$0.40** |
| Retail value given away per reply | 15 000 soʻm ≈ $1.27 |

**A 50-reply ladder:**
- Vendor cash: **≈ $18** (floor $15.40 if every name passes first time; ceiling ~$45 if every name burns
  all three renders).
- Retail value given away: **750 000 soʻm ≈ $64**.
- **Generation-cap consumption: ~58 generations.** ← **this is the real constraint, not the money.**

**The binding wall is the ElevenLabs monthly generation cap, and it is tighter than anyone has assumed:**

| Plan | $/mo | 90 s generations/mo | Does a 50-ladder fit? | Does 10/day for 30 days (≈351 gens) fit? |
|---|---|---|---|---|
| Starter | $6 | 11 | **No** | No |
| Creator | $22 | 41 | **No — a 50-ladder does not fit at all** | No |
| Pro | $99 | 202 | Yes, 29% of the month | **No** |
| Scale | $299 | 733 | Yes, 8% | Yes, 48% |

Also on the record: Free/Starter/Creator/Pro are **"For Individual Use Only"** — the honest floor for an
incorporated operator is **Scale, $299/mo** — and **Reseller Rights are "Prohibited" on every self-serve
tier.** That is a live legal question, not a throughput one, and it is the owner's.

**THE DAILY CAP — where marketing stops and a giveaway starts:**

1. **Public promise: «bugun 10 ta».** Never promise more; an uncapped promise is an unbounded backlog.
2. **Hard operational cap: 10 free ladder renders/day, for a bounded 14-day burst** (≈140 renders, ≈164
   generations, ≈$50). Then it is reassessed against the numbers below, not renewed by habit.
3. **Hard monthly rule: ladder renders may never exceed 30% of the plan's monthly generation allowance.**
   Paying customers get the rest. Check month-to-date generations before the first render of every day; **if
   MTD is past 60% of the plan cap, the ladder stops for the month.**
4. **Once paid orders exist, tie it to them:** `daily ladder renders ≤ paid orders that day + 5`.
5. **The giveaway test, run on day 14:** the ladder must have produced **≥1 `/start` per published reply
   video** and **≥1 paid order per 10 published reply videos**. Below either line it is a free-song giveaway
   with a camera on it — cut to **3/day** and re-examine the format, not the volume.

⚠️ There is **no technical limit stopping any of this.** The per-user daily order cap and the free-tier caps
were removed because nothing read them. The cap is human discipline and a number written in the log.

### 8.6 THE ESCALATION RULE — what stops the ladder

**STOP means: publish nothing further, reply to nobody, tell the owner. Only the owner restarts it, in
writing.**

| Trigger | Threshold | Action | Who |
|---|---|---|---|
| **A name we should not have sung is live** | one instance | **Take the video down inside 60 minutes.** One line, no argument (below). Keep the master and the log row. Do not delete the evidence. **STOP the ladder for the day.** | Operator, then owner |
| **A legal or likeness complaint** (ЗРУ-1115, image consent, an heir, a lawyer) | one instance | Video down. Preserve everything. **Do not reply at all.** Owner only. **STOP.** | Owner |
| **Third-party PII published** (address, phone, workplace, a minor) | one instance | Video and comment down. **STOP.** | Operator + owner |
| **Comment section turns hostile** | the highest-liked comment on a ladder post is hostile, **or** >10% of the last 50 comments are hostile | **STOP the ladder that day.** Do not reply to hostility. Do not delete it. Read it, and read the three-second skip rate before posting again. | Operator |
| **Any moderation action** — comment restriction, post removal, reach warning, account label, "we limited your account" | one instance | **STOP everything, all formats.** Do not post to "recover". Screenshot it. | Owner |
| **Engagement-bait signal** — anyone reads the ladder as a contest, or the pinned rule is being ignored at scale | recurring | Repin the rule, restate the 10/day cap, stop replying to submissions for 24 h | Operator |
| **Vendor bill / cap** | MTD generations past 60% of plan cap, **or** any billing, plan-limit or suspension email from the vendor | **STOP renders immediately.** A declined renewal drops the account to Free, where music concurrency is 0 and **the customer-facing product stops too** | Owner |
| **Ear check fails twice on the same name** | per name | No video. Send holding reply B. Log it. Never publish the take | Operator |
| **A pronunciation claim is publicly refuted** in a thread | one instance | Do not defend. Do not reply twice. Use template F, once. Tell the owner | Operator |

**The takedown line, if a video has to come down publicly:**
> UZ: `Videoni oʻchirdik. Kechirasiz.`
> RU: `Видео удалили. Извините.`

Nothing more. No explanation, no defence, no second post about it.

**The one rule that overrides everything in this pack:** if the choice is between publishing today and
publishing a real person's name sung wrong, or sung without their asking — do not publish. The ladder is
repeatable. A forwarded video is not retractable.

---

## 9. WARNINGS AND STILL-UNKNOWN

Unglossed. Everything here is a thing this pack could not close, a number that is softer than it looks, or
a commitment nobody has yet agreed to.

### 9.1 What was verified, and what that verification could not reach

- **The price fact has one hole.** `/etc/bayram/bayram.env` is `root:hbd 0640` and the deploy account has no
  passwordless sudo to read it, so the value the *currently running* process loaded is inferred from the
  deployed code default plus the intent history. The last env-file modification was 2026-09-15 19:44 and no
  intent has been opened since 18:28 that day. **One screenshot of the live paywall closes it.**
- **`BAYRAM_CREDITS_ENFORCED=true` and `BAYRAM_GREETINGS_PER_KIT=0` are both deductions, not reads.** The
  first from a boot refusal that would have fired otherwise, plus a warning line absent from every boot; the
  second from the code default plus 30 days of logs with no greeting stage. Both are strong. Neither is the
  file. Someone with root should run one read-only grep for each.
- **Direct Postgres reads were refused by this session's own production-read policy**, so customer orders
  could not be separated from internal test orders, and nothing older than the journal window (2026-09-11)
  could be reached.
- **"Payme is wired and armed" is verified. "A stranger's card will settle" is not.** The boot line says
  `is_sandbox: false` against a merchant id the host inventory recorded as a *sandbox* cashbox on
  2026-09-11. That fact lives in the Payme cabinet. No payment was attempted.
- **Nothing was written, restarted or changed on the host, and no secret, token or key was read or printed.**

### 9.2 The claims this pack asks you not to make, and why

- **Nothing in the repository measures sung pronunciation success.** Not one test, benchmark or fixture. The
  77-name golden set is a pure-text regression fence. The pipeline's own loop tests run on a fake similarity
  function and a fake music provider that writes the submitted name into the audio bytes so the fake
  speech-to-text can read it back. The bake-off designed to measure this was never run. **The only
  real-world number in existence is 24 journal events over six days, and it may be internal tests.**
- Every line of the form «ismini toʻgʻri aytdi» across cards 2, 5, 6, 7 and 9 is marked conditional in this
  pack, and **this pack cannot tell you whether it will be true.** It ships on a two-native-speaker pass on
  the exact take in the cut, or it does not ship.
- **The "AI mispronounces difficult names" format is still unproven at scale.** Two research passes in four
  languages found no 1M+ example. This pack tells you how to run the ladder safely; it does not tell you the
  ladder will work. Funding 20–50 reply videos on it is a product decision that is still open.

### 9.3 Numbers in this document that are softer than they look

- **`BAYRAM_MUSIC_USD_PER_MINUTE=0.15`** is a placeholder list price the repository itself labels ESTIMATED.
  Treat tonight's $4.95–$14.85 as an order of magnitude, not a bill. Lyric cost ships unpriced (0.0), so it
  is not in the total at all.
- **The $0.36 per-reply figure** rests on two unmeasured things: the vendor's music rounding rule is
  contradicted on its own two live pricing pages (a 24% cost-of-goods swing, unresolved), and the 1.17
  attempts-per-name average comes from those same 24 events of unknown provenance.
- **The ElevenLabs plan this production key sits on, and the month-to-date generation minutes, are UNKNOWN.**
  Every absolute cap in §8.5 is unenforceable until someone writes those two numbers at the top of the ladder
  log. The directional finding stands and matters: a 50-reply ladder does **not** fit inside a Creator plan.
- **Higgsfield credit prices are estimates.** Published pricing contradicts itself across every source and
  the official pricing page returns no readable table. Soul **still**-generation cost was not researched at
  all, and stills are the largest count in tonight's session — the largest unpriced line in the budget.
- **Higgsfield generation times** are the vendor's published medians for other models and may not hold for
  whatever engine the image-to-video step routes to tonight. The 19:00–20:30 schedule has no slack if they
  are wrong.
- **The 10/day cap, the 14-day burst and the day-14 conversion test** are recommendations derived from the
  vendor caps and the playbook's own cadence, not measured optima.
- **The ЗРУ-1115 penalty range in soʻm** depends on the current BRV value, which was not independently
  re-checked.
- **`90 soniya`** (card 10 and bio line 1) is taken from the product's description as a ~90-second song. No
  delivered file was measured.
- **Card 9's `200 000` cake and `40 000` flowers** are the playbook's placeholders. Only the 15 000 is
  verified.
- **Card 8's countdown** is computed from 2026-09-17. If the post slips, the number on screen is wrong and
  the card's urgency argument inverts.

### 9.4 Language, unreviewed

- **The Uzbek in this pack has had two proofreading passes and no native-speaker sign-off on the final
  strings.** The character-level work is solid — every `oʻ`/`gʻ` is U+02BB and there are no stray ASCII
  apostrophes, smart quotes, backticks or acutes in any Uzbek word — but register judgements are a
  proofreader's, not a native's. **A native speaker should read the final copy-paste blocks aloud once
  before export.** It is a ten-minute job for a brand whose entire thesis is that it gets Uzbek right.
- **Every Russian caption, CTA, auto-DM body, canned reply, release form and reply template is newly
  written and has had no native review.** The playbook supplied Russian only for on-screen overlays. The RU
  cuts of cards 2 and 10 in particular use colloquial register that a native should confirm reads as
  intended rather than as flippant.
- **The release form and the takedown promise (§7) are mine and unproofed in both languages.** Have someone
  read both versions aloud before printing, and print in a font that renders U+02BB.
- **No device or app rendering was verified.** The CapCut U+02BB test is unrun and remains a blocker. So is
  the check that Instagram's comment box and CapCut both preserve the U+00A0 inside `15 000` through a
  copy-paste.
- **The card 7 paywall block is the literal locale string as read in the repo.** The deployed wheel was
  reported byte-identical on enum labels, but the paywall string itself was not personally diffed against
  the running process. Screenshot the live screen before matching type to it.

### 9.5 Two owner decisions this pack deliberately did not make

1. **`havola` vs `link`.** `havola` matches the product's own copy and is used throughout. It is also the
   bookish choice — on Instagram, Uzbek speakers say *link*, and the CTA is where a stiff word costs taps.
2. **«QOʻSHIQ SOL» (card 10).** It works only as a pun on «pul solma»; `qoʻshiq solmoq` is not an existing
   collocation, so a share of viewers will read it as an error by the brand that sells correct Uzbek. The
   line is strong enough to keep and weak enough to question.

### 9.6 Still unknown, in the order that they will hurt

1. **Whose money the 14 settled payments are.** Until somebody who knows says so, no card, caption or reply
   may imply traction.
2. **Whether a stranger's card actually settles** on this cashbox. Wired and armed is verified; settlement
   by a real outside customer is not.
3. **Whether the image-consent law has been signed and commenced.** The whole street block and the taxi
   series rest on the exact wording of its narrow public-place exception.
4. **Whether this account can see any current Uzbek chart track in the Reels music picker, in Uzbekistan.**
   Meta documents no account-type split and does document that music may be region-limited. Card 10's
   variant depends on the answer, and only opening the picker gives it.
5. **What the Uzbek audience actually does with AI-generated shashmaqom.** No such artefact has been publicly
   discussed anywhere, so there is no measurement to read. The comment section will answer within an hour.
6. **Whether the "AI mispronounces names" genre exists at scale.** Unresolved after two passes.
7. **Whether anyone on this team holds the ADMIN role and step-up credential needed to grant credits.** If
   not, every ladder render and every gate render is real money.
8. **Whether `@ibadovmusic` carries the AI-generated-profile label at all.** Instagram profiles need a login;
   nobody has looked first-hand. Until someone does, that anecdote does not go in a brief as evidence of a
   penalty — and the documented mechanism says the label is opted into, not imposed.
9. **What metadata our render pipeline and CapCut write into exports.** Instagram's per-post "AI info" label
   fires automatically off C2PA/IPTC credentials and can attach to a post nobody meant to label.
10. **Whether the ride-hailing platform's terms restrict filming a driver at work.** Not checked; the
    conservative practice is in §7.2c.
11. **Whether the flame can be generated as a stable, non-pulsing orange** inside tonight's attempt budget.
    If not, the card-9 kill rule fires — grading the real table to match a wrong-coloured flame is forbidden.
12. **Whether Uzbekistan's personal-data rules impose retention or localisation requirements on the signed
    releases and consent clips themselves.** §7.2d gives conservative practice, not a legal minimum.

### 9.7 Commitments nobody has agreed to yet

These appear in copy in this document and become lies the first time they are tested, unless a named person
accepts them today:

- **The «qaytadan yozib beramiz» promise** — there is no re-roll handler in the bot and the admin panel is
  read-only in this build. Template H is marked DO-NOT-USE for exactly this reason.
- **The 24-hour takedown SLA and the 1-hour boost-stop** — they need one named owner and a monitored inbox,
  checked at least daily. Assign the owner before the bio copy goes live, not after.
- **Approval-before-posting for every identifiable subject** is a schedule cost nobody has budgeted: eight
  street subjects each need the finished cut sent to them and a reply before posting, and the prank cards
  deliberately wait until the next morning. **The producer must accept roughly a day of slip between shoot
  and first post, or cut the number of subjects.**
- **The support-privacy hole.** Support tickets are stored and `/forget` cannot erase them; the test that was
  supposed to protect that promise names a route that does not run. Nobody may widen any privacy promise on
  camera or in a reply.

---

*Produced 2026-09-17. Everything in this document was read on 2026-09-16 or 2026-09-17 and is stamped where
it matters. It rots like everything else in `marketing/strategy/` — a number here older than about three weeks
should be treated as a lie until somebody re-reads it. Correct it by adding a dated line, not by editing an
old one.*
