# 06 — The Instagram account as an object: profile, grid, highlights, links

**Dated 2026-09-18.** Everything before this file plans *what to post* (`01` the slate, `04` the
production pack, `05` the song). This one plans *what the account is* — the profile a stranger lands
on after the video that stopped them, and the link architecture behind it. It is the surface `01`
covered in eight bullets under "account setup" and nothing has been built against it yet.

**Its evidence is `07`,** which researched the platform rules a professional account actually runs
under. Where this file reverses an earlier decision — the account type, the pacing of the ladder, the
way each reply is published — `07` carries the finding and the confidence stamp behind it.

Two assets arrived on 2026-09-18 that were not available to `01`–`05`:

- **`bayrambot.uz`** — the domain, already live on Cloudflare.
- **an Instagram handle matching it** — assumed `@bayrambot.uz` below; if the spelling differs,
  every occurrence of the handle in this file changes and nothing else does.

They are worth more than they look, because they close the exact hole `05` §10 named: *"the sung
'Bayram uz' is an address with no door."* It has a door now, and the door and the Instagram handle
are the same eleven characters.

---

## §1 What was checked today, and what it costs

| Checked | Result |
| --- | --- |
| `dig bayrambot.uz` | Cloudflare (`104.21.0.246`, `172.67.151.126`). Live. |
| `curl https://bayrambot.uz/` | **302 → `https://t.me/bayram_uzbot`.** An edge redirect rule, no application behind it. |
| `curl 'https://bayrambot.uz/?start=ig_bio'` | **302 → `https://t.me/bayram_uzbot`** — the query string is **dropped**. |
| `curl https://bayrambot.uz/ig` | Same. A catch-all: **every path and every query collapses to one payload-free link.** |
| `grep -rn bayrambot.uz` in the repo | `pay.bayrambot.uz` and `admin.bayrambot.uz` are **live production subdomains** behind the tunnel. The apex is the only free surface. |
| `cmp marketing/brand/Logo-Bot.png src/bayram/audio/assets/cover.png` | Byte-identical, as `tests/test_audio/test_cover.py` requires. |

**The cost, stated plainly:** the apex as configured today *destroys attribution*. `04` §5.14 and `05`
§10 both build the ladder's only measurable gate — ≥1 `/start` per published reply video — on distinct
`?start=ig_<asset>` payloads. Point a single video at `bayrambot.uz` and that video becomes
unattributable, silently, with no error anywhere. **Nothing may point at the apex until §7 is done.**

---

## §2 The three decisions the new assets force

### D-A · The burned-in lockup becomes `bayrambot.uz`, and the caption keeps `@bayram_uzbot`

`01` and `05` burn `@bayram_uzbot · 15 000 soʻm` into every frame. A Telegram handle is the wrong
string to burn into an *Instagram* video: it cannot be tapped, it cannot be searched on the platform
it is displayed on, and — `05` §10 — nobody says it out loud correctly.

`bayrambot.uz` is sayable, it is one word in both languages, it is the same string as the account the
viewer is already looking at, and it is typable from memory two hours later. So:

- **Burned into frame:** `bayrambot.uz · 15 000 soʻm`, persistent, from the first slam.
- **Spoken on camera, where a line calls for it:** "bayrambot nuqta uz".
- **First 125 characters of the caption:** `@bayram_uzbot` stays, because Telegram search indexes it
  and because a Telegram-native reader converts on a handle faster than on a URL.
- **Bio link:** the domain (after §7).

This is a change to the production pack's shared rules. It is cheap — it is one text layer — but it is
only correct **after** §7, and wrong before it.

### D-B · The avatar is the logo, cut for a 40 px circle

`marketing/brand/Logo-Bot.png` is the logo and it is already a product surface: `marketing/brand/README.md` and
`tests/test_audio/test_cover.py` both hold it as the source of truth for
`src/bayram/audio/assets/cover.png`, which is encoded as the cover art of **every** song shipped. The
account and the delivered song therefore already match, which is the thing that usually has to be
engineered and here is free.

What still has to be decided is the **cut**, because an Instagram avatar is a circle rendered at 110 px
on the profile and about 40 px in feed, and the file is a 1254 px square whose bottom third is a text
band — `@bayram_uzbot` in outlined lettering over «ПОЗДРАВИТЕЛЬНЫЕ ТРЕКИ И ВИДЕО».

- **Ship a centre crop that keeps the robot, the gift and the phone, and loses the text band.** At
  40 px that band is a grey smear, and everything it says is already said twice over by the handle
  sitting next to the avatar and by the Name field beneath it.
- The blue ring makes a clean circle edge, so the crop needs no new artwork — it is one square
  selection out of the existing file.
- **Do not re-cut the cover art to match.** The full picture is correct in a music player at 320 px,
  where the text band is legible and useful; only the avatar is size-constrained.

The same file, alpha-flattened, is now `marketing/brand/Logo-Bot.jpg` — that is what
`python -m bayram.tools.identity change --photo` needs for the Telegram bot picture, so the bot, the
cover art and the Instagram avatar all come off one source.

### D-C · One palette decision is still open: the logo is blue and gold, the slate shoots cream and red

This is worth naming before the first frame is shot rather than after fifty. `01` and `05` specify a
cream-and-red art direction — the ledger, the stamp, ISMCHI's jacket — and the burned-in lockup and
lyric burns are specified in magenta. The logo the viewer taps through to is deep blue with gold
confetti. Three colour stories on one funnel is two too many.

Two ways to close it, and either is fine so long as it is chosen:

1. **Follow the logo.** Burn-ins and highlight covers go blue-and-gold; the set stays cream, which sits
   under blue perfectly well; the stamp stays red as the one accent. Cheapest — nothing is redrawn.
2. **Follow the set.** Keep cream-and-red across every frame and treat the logo as an endpoint mark
   that appears only at the avatar and in the player. Costs nothing to shoot, but the grid and the
   profile picture will not look like the same account at a glance.

**Recommendation: (1).** The logo is the surface that is already shipping to paying recipients, and it
is the expensive one to change — `marketing/brand/README.md` now lists the four steps a logo edit forces. The
burn-in text layer is the cheap one. Move the cheap thing.

---

## §3 The profile object, paste-ready

Ship all of this **before post one**. `04` §2047 already carries it as a checklist item; this is the
same list with the new domain folded in.

| Field | Ship exactly this | Source |
| --- | --- | --- |
| Handle | `@bayrambot.uz` | matches the domain; never change it after post one |
| Account type | **Business** — reversing `01` | `07` F3: `01` chose Creator for the full music catalogue, and we ship original audio only, so that advantage is never spent. Business keeps Graph API, scheduling and analytics past 90 days. Switching either way is instant, free and reversible, so this is a cheap decision, not a permanent one. |
| Facebook Page | connected | `07` F4 — **native comment-to-DM does not exist without it.** Not in any earlier document. |
| Name field (search-weighted) | `Bayram \| Ismingiz bilan qoʻshiq · Tugʻilgan kun sovgʻasi` | `04` §5.14, proofed |
| Bio line 1 | `Ismingiz toʻgʻri aytiladigan qoʻshiq. 90 soniya, 15 000 soʻm.` | `04` §5.14 — verify `90 soniya` against a real file first |
| Bio line 2 | `Tugʻilgan kun, toʻy, hazil, ustoz uchun — Telegramda yoziladi.` | `04` §5.14 |
| Bio line 3 | `+998 ...` | `01` — a bot-only bio reads as untrustworthy in this market |
| Link | `bayrambot.uz/ig` **(only after §6)** — one, not five | `07` F5: Instagram allows five native bio links and **reports clicks on none of them**. One link through our own redirect is the only countable option. |
| Category | not "Entrepreneur"-as-a-trick | `04` §730 — do not set a category to unlock a track |
| Contact buttons | phone that a person answers, second phone as backup | `04` §49 — the release form needs the same two numbers |

Rules that stay from `01`, now with evidence behind them (`07` §2): exactly **one** link, no Linktree;
no growth automation or mass-following for 60 days; vary captions; no `AI-generated profile` label,
because the rule covers synthetic *personas* and this account is human-run (`07` F8).

One rule of `01`'s is **withdrawn**: the worry that "an aggressively pushed off-platform link from day
one" gets new commerce accounts limited. `07` §2 could find no support for it — Instagram does not
allow links in captions at all, and no official statement about suppressing external links exists.
Treat it as folklore and stop designing around it.

Warm-up, which no earlier document specified: **2–3 posts a day maximum while the account is new**,
actions spaced rather than bursted, and **no DM volume at all** in week one.

---

## §4 The grid is a ledger — and that is the whole design

The ladder (`01`) publishes 20–50 near-identical cheap reply videos. On any ordinary account that
produces a grid that looks like a content farm by week two, and the grid is the second thing a stranger
judges after the avatar. **Turn the weakness into the identity:** `05` §8's recommended character,
ISMCHI, keeps a ledger of names, and a grid of fifty tiles *is* a ledger.

- **Every reply Reel gets a hand-set cover image, never the auto-thumbnail.** The cover is one ledger
  row: cream ground, the name written large in the ledger hand, the red stamp landed beside it, a small
  magenta flame in one corner as the only brand mark, and the row number — `37-ism`.
- Scrolled, the profile reads as a register of real Uzbek names — `Gʻulomjon`, `Oʻgʻiloy`,
  `Muhammadalisher` — each spelled correctly with its modifier letters. That is the product claim,
  stated fifty times, without one word of copy.
- It gives fifty cheap episodes a visible arc (`05` §8) and it makes the *next* name-drop obvious to a
  viewer who has never read a caption.
- **Prop rule, carried over from `05` §8 unchanged and non-negotiable:** wordmark stamp only,
  rectangular, no crest, no circle, no uniform, no institution named or shown. The moment the stamp
  looks official the joke lands on people who work in government offices.

**Cover specification** (`07` §3): design at 1080 × 1920, but the grid crops to **3:4** — so the name,
the stamp and the row number all sit inside the **centre 1080 × 1350**, checked on the profile grid tab
before publishing. Export JPG. Bold and high-contrast: thin type is gone at thumbnail size.

### How each reply is published — use the native mechanic, strip the sticker

`07` F1: Instagram has a first-class **reply-to-a-comment-with-a-Reel**. The reply publishes to the
profile as ordinary content *and* stays linked underneath the comment it answers, on a post still being
watched — so reply 37 keeps feeding traffic back into post one. That is free distribution the ladder
was planning to do without.

It collides with `04` §7's privacy rule, because the native comment sticker publishes the commenter's
handle and avatar. **The sticker can be dragged to the bin while editing.** So: use the mechanic, strip
the sticker, keep the rule.

⚠️ **Untested and it decides the publishing route:** does the back-link under the original comment
survive the sticker's deletion? If yes, this is free. If no, the rule wins and replies publish as
standalone Reels. `07` §4 carries the five-minute test; run it before the ladder starts.

### The pacing rule the ladder did not have

`07` F2: near-duplicate content draws **24 hours to 30 days** of reduced reach **to non-followers** —
the only reach a new account has — and **10+ reposts in a rolling 30 days drops an account out of
Explore, Reels and suggestions entirely**. Fifty tiles that differ only by a name is exactly the shape
a classifier is looking for.

The ledger survives this, on three conditions:

- **The sameness lives in the cover, not the footage.** Identical covers are recommended practice for a
  cohesive grid and are not what duplicate detection reads. The video underneath must genuinely differ —
  different framing, different hands, a different reaction, a different room.
- **4–7 Reels a week**, not fifty in a fortnight. `01` always described the ladder as volume across
  4–8 weeks; this just removes the temptation to front-load it.
- **Never re-post a cut that underperformed.** That is the behaviour with the 30-day Explore exclusion
  attached.

**The pinned three** — the permanent top row, the only part of the grid a stranger is guaranteed to
see, and the only three tiles that are *not* ledger rows:

1. **The proof** — card 1 from `01`: foreign AI mangles `Gʻulomjon`, ours does not.
2. **The feeling** — the grandmother card: the name lands inside the emotional beat, brand named in
   dialogue, not flashed.
3. **The mechanics** — what it costs, how long it takes, where it happens. This is the tile that
   converts the person who already believes the first two.

---

## §5 Highlights — five, Uzbek-named, drawn not photographed

Covers are flat: magenta ground, one white geometric element built from the identity's bar-and-flame
construction, no photography, no text in the cover art itself (the title carries the word). They must
read at 56 px.

| Cover | Title | Holds |
| --- | --- | --- |
| candle | `Qanday?` | the mechanics: name → approve every word → recorded → delivered |
| price tag | `Narx` | `15 000 soʻm`, and what the money is for — the writing, per `bot-decoration.json` |
| waveform | `Namunalar` | three finished songs across three genres, including a shashmaqom for a grandfather |
| stamp | `Ishonch` | the consent and takedown commitment — `04` §7.7b was written for exactly this slot |
| flame | `Bayram` | the brand's own song (`05`), and what the name means |

`04` §7.7b already exists as paste-ready text for a highlight, the pinned comment and the back of the
release form. Use it in all three places verbatim; a commitment that is worded three different ways
reads as three different commitments.

---

## §6 The link architecture — fix the apex before anything points at it

The apex must stop being a catch-all and start being a **payload-preserving router**. This is a
Cloudflare edge rule; it touches neither `pay.` nor `admin.`, which stay exactly as they are.

| Short link | Redirects to | Used by |
| --- | --- | --- |
| `bayrambot.uz/ig` | `t.me/bayram_uzbot?start=ig_bio` | the bio link |
| `bayrambot.uz/g` | `…?start=ig_gtest` | card 1 |
| `bayrambot.uz/buvim` | `…?start=ig_buvim` | the grandmother card |
| `bayrambot.uz/taksi` | `…?start=ig_taksi` | the taxi card |
| …one per asset | `…?start=ig_<asset>` | the eleven payloads already named in `01` |
| `bayrambot.uz/` (bare) | `…?start=ig_direct` | anyone who typed the domain from memory — **this is the number that proves burned-in text works**, and today it is invisible |

Three rules:

- **Preserve the payload or do not ship the link.** A redirect that drops `?start=` is worse than no
  short link, because it converts a measurable visit into an anonymous one and nobody notices.
- **Expect the extra tap and stop apologising for it.** `04` §378 verified it: Telegram's own
  interstitial serves a Start Bot button carrying `&start=`, so the payload survives. Do not commission
  a redirect page — the domain now *is* the redirect page, one hop earlier.
- **Never retro-fit printed material.** The release forms in `04` §7 carry `t.me/…` links; those are
  printed, correct, and stay.

Worth reserving, not building now: `bayrambot.uz/<name>` as a shareable song page. It is the natural
second act — a ledger row anyone can link to — and it is the reason not to spend the apex on anything
else.

---

## §7 Blockers, in the order they bite

| # | Blocker | Why it blocks | Fix |
| --- | --- | --- | --- |
| 1 | **The apex drops `?start=`** | every ladder metric in `04` §8.5 | one Cloudflare rule. **Before post one.** |
| 2 | **There is no wordmark.** The old vector identity — level-meter mark, wordmark, lockups, magenta avatar — was removed on 2026-09-18 because nothing referenced it and the wordmark still drew the pre-rename letters `h b d` | the stamp prop in §4 was specified as a "wordmark stamp", and there is no wordmark to cut it from | decide the stamp's face before the kiosk cuts it: the word `BAYRAM` in the ledger hand, or `bayrambot.uz`. **Before the stamp prop is cut.** Recovering the old wordmark from git is not the answer — it draws the wrong letters. |
| 3 | **The logo carries `@bayram_uzbot` in its own pixels** | D-A moves the on-screen address to `bayrambot.uz`, so the avatar and the burn-in will name two different addresses | tolerable — the handle is correct, just not the one being advertised. If the domain ever becomes the primary address, the logo is a four-step change, listed in `marketing/brand/README.md`. Not a launch blocker. |
| 4 | **Peshta expires ≈2026-10-07** | card 10 only | unchanged from `01`; the account design does not depend on it |
| 5 | **Four platform facts are untested on our own account** (`07` §4) | the comment-reply back-link, keyword match semantics, Cyrillic triggers, and the bio link's in-app behaviour. The first decides how every ladder video is published | twenty minutes with a second phone. **Before post one.** |
| 6 | **Two answering phone numbers do not exist yet** | bio, contact buttons and the release form all need them | `04` §49. One person, thirty minutes. |

---

## §8 Sequence

**Day 0 — one sitting, roughly three hours, no shooting.**
Set the apex redirect rules (§6) and test three of them with `curl -I`. Create the account as Business,
connect it to a Facebook Page, and paste the §3 fields. Cut and upload the avatar from
`marketing/brand/Logo-Bot.png` per D-B. Then, **at a desktop**, set up Meta Business Suite's Custom Keywords and
Comment to Message — five keyword slots, exact and case-sensitive, so they are
`bayram`, `Bayram`, `BAYRAM`, `bayrom`, `БАЙРАМ`, and the fifth slot is now spent (`07` F4). Finally run
the four tests in `07` §4, including tapping the bio link from inside the Instagram app on a real iOS
and a real Android device (`01` line 750 — still untested).

Nothing in that hour is a phone task except the tests: keyword automation is desktop-only.

**Day 1 — the three pinned tiles.** Nothing else gets posted until they exist; they are the only part
of the grid a first-time visitor is guaranteed to see.

**Day 2 — the ledger kit.** One cover template, the stamp cut at a kiosk (prop rule §4), the ledger
hand chosen. The kit is what makes reply number 37 cost four minutes instead of forty.

**Week 1 onward — the ladder**, exactly as `01`/`04` specify. The account design's whole job from here
is that each reply costs almost nothing and the grid still reads as one thing.

**At 1,000 followers — switch on Trial Reels.** `07` F6: they publish to non-followers only for 72
hours and auto-share if they clear a niche baseline, which is the right way to test which name-video
shape travels. They require 1,000 followers, so they do not exist for us at launch. Put the milestone
in the plan now so nobody rediscovers the tool at 5,000.

**Highlights fill as the ladder runs.** They are not a launch-day task; an empty highlight is worse than
a missing one.

---

## §9 What this file could not close

- **The handle spelling is assumed**, not verified against the live account. Every `@bayrambot.uz` here
  is a placeholder for whatever was actually registered.
- **Whether this is a fresh account or `@orihero.ai` renamed.** `01` line 45 planned against a 0/0
  professional account. If the new handle carries any history, posts or followers, the pinned three and
  the grid plan need a pass they have not had.
- **Nothing here has been tested on a real phone.** Avatar legibility at 40 px, cover legibility at
  110 px and the bio link's in-app behaviour are all assertions until somebody looks.
- **The redirect rules are specified, not written.** They live in the Cloudflare dashboard, not in this
  repository, which means they have no review, no history and no test. That is a real gap and it should
  be closed the first time one of them breaks, not before.
