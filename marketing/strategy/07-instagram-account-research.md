# 07 — Professional-account research: the rules the account itself runs under

**Dated 2026-09-18.** `02` researched *content* — ranking, hooks, captions, the Uzbek scene. This one
researches the *account*: what a professional account is allowed to do, what a brand-new one is allowed
to do, and which of the eight bullets `01` wrote under "account setup" survive contact with the 2026
rules. Read `06` for the design that comes out of it.

**Every number here was read on 2026-09-18 and rots on the schedule this folder's README describes.**
Confidence is stamped per finding. Anything marked ⚠️ is a claim from secondary sources that we have
not tested on our own account, and several of them are five-minute tests.

---

## §1 The eight findings that change something

### F1 · The ladder has a native mechanic, and we were planning to rebuild it by hand — ✅ high

Instagram has a first-class **"reply to a comment with a Reel"**: from the comment, a blue Reels button
opens the camera, and the published reply carries a **comment sticker** that names the commenter and
links their profile. The reply publishes to your profile as ordinary content *and* is linked
underneath the original comment on the original Reel.

That last clause is the whole reason it matters. `01`'s ladder — one proof video, then 20–50 replies to
names left in the comments — currently plans to post those replies as standalone Reels. Posted as
native comment-replies instead, each one is **also** a permanent link sitting under the comment it
answers, on a post that is still being watched. The 37th reply keeps feeding traffic back into post one.

**But it collides head-on with our own privacy rule.** `04` §7 forbids publishing a commenter's handle
or avatar without written consent in that thread, and forbids screenshots that show a handle. The
native sticker *is* the commenter's handle and avatar, published.

The resolution, and it is the single highest-value thing in this file: **the comment sticker can be
deleted while editing** — drag it to the bin — and the reply still publishes. ⚠️ **What we have not
verified is whether the back-link under the original comment survives the sticker's deletion.** If it
does, we get the distribution and keep the privacy rule. If it does not, the choice is explicit:
distribution *or* the rule, and the rule wins.

> **Test before the ladder starts, 5 minutes:** post a throwaway Reel from the account, comment on it
> from a second phone, reply with a Reel, delete the sticker, publish, then look at the original
> comment and see whether the reply is still linked beneath it. Write the answer into `06`.

### F2 · The ladder's shape is a near-duplicate penalty waiting to happen — ✅ high, and this is the real risk

2026 enforcement is explicit about repetitive content: accounts posting near-duplicates face reach
penalties lasting **24 hours to 30 days**, which cut reach *to non-followers* while leaving followers
unaffected — and accounts posting **10 or more reposts in a rolling 30-day window are excluded from
Explore, Reels and suggested posts** altogether.

Non-follower reach is the only reach a 0-follower account has. And `06` §4's grid design — one ledger
template, name swapped, stamp lands — is, viewed from a classifier, fifty near-duplicates.

This does not kill the ledger. It disciplines it:

- **The template lives in the cover, not the video.** Identical covers are a *recommended* practice for
  grid cohesion and are not what a duplicate classifier is looking at. The footage underneath has to
  actually differ: different framing, different hands, a different reaction, a different room.
- **Pace it.** The realistic ceiling is **4–7 Reels per week**, not fifty in a fortnight. `01`'s
  "20–50 cheap replies" is a *volume over 4–8 weeks*, and it was already written that way — this
  finding just removes the temptation to front-load it.
- **Never repost the same cut** to catch a miss. That is the behaviour with the 30-day Explore exclusion
  attached to it.

### F3 · Creator-vs-Business was decided for a reason that does not apply to us — ✅ high

`01` says Creator, "decided before the first edit", because Business accounts are capped to the Meta
Sound Collection (~14,000 cleared tracks) while Creator sees the full licensed catalogue. Both halves
are confirmed. Two things around it are not what `01` assumed:

1. **Switching is instant, free, reversible, and costs no followers, posts or data.** The urgency in
   "decide before the first edit" is misplaced. There is no cooldown.
2. **We ship original audio anyway.** `01` §10 and `05` §11 both settle that every cut runs on our own
   Bayram-generated bed, not a label master. An account that never opens the licensed catalogue gains
   nothing from Creator's access to it.

And the licensing point is sharper than "unverified workaround" territory: **in-app availability is not
a commercial licence**, and this has been litigated — Sony sued OFRA Cosmetics for a reported ~$50M
over commercially-shared influencer content. A brand can be liable for music in content it merely
amplifies. `01`'s instruction never to boost a Reel carrying a label track is correct and is a legal
position, not a reach tactic.

**So choose the account type on the remaining merits, which now favour Business:** full Graph API
access, third-party scheduling, a shared inbox, and analytics that reach past Instagram's 90-day
window. Creator's advantages — the music catalogue and creator-specific inbox tools — are ones this
account will not use. ⚠️ Reported engagement dips after switching are anecdotal and unconfirmed.

### F4 · Native comment-to-DM is free, and its limits are tighter than `04` assumed — ✅ high

Meta Business Suite gives seven automation tools free: Instant Reply, Away Message, **Custom Keywords**,
**Comment to Message**, FAQs (max 4), Saved Replies, and a staged AI auto-reply. The limits that bite:

| Limit | Value | What it does to us |
|---|---|---|
| Keywords | **5 maximum** | `04` §5.14 lists four: `bayram`, `BAYRAM`, `bayrom`, `БАЙРАМ` |
| Matching | **exact, and case-sensitive** | `Bayram` — the way a phone's autocapitalise will actually send it — is **not** covered by `bayram` or `BAYRAM`. Adding it fills the fifth and last slot. |
| Delay | **15 minutes**, unless you reply personally first | the CTA must not imply the bot answers instantly |
| Window | **24 hours** to respond, API-level | unchanged from `04` §378 |
| Volume | **≤200 automated DMs/hour**, ≤750 comment-reply API calls/hour | far above anything this ladder produces |
| Setup | **desktop only**, in Meta Business Suite | not a phone task |
| Prerequisite | the Instagram account must be **connected to a Facebook Page** | **this is a setup step in no existing document** |

Both Creator and Business accounts can use these; a personal account cannot.

⚠️ Whether "exact match" means the comment must *equal* the keyword or merely *contain* it is reported
both ways. This decides whether `Bayram deb yozdim` triggers anything at all, and it is a five-minute
test with a second phone.

### F5 · The bio holds five links, and none of them can be measured — ✅ high

Instagram has allowed up to five native bio links since April 2023; the first shows, the rest collapse
behind "and N others". **Native links report nothing** — no click count, no per-link breakdown.

This makes `01`'s "exactly ONE link" rule right for a better reason than it gave. One link, pointed at
`bayrambot.uz`, is also the only way to *count* anything, because the measurement happens at our own
redirect (`06` §6) rather than at Instagram, which will not tell us. Adding four more native links
would divide attention and still measure nothing.

### F6 · Trial Reels are the right tool and we cannot use them yet — ✅ high

A Trial Reel publishes to **non-followers only** for 72 hours, measures it against a niche baseline,
and auto-shares to followers if it clears the bar. For hook-testing a ladder, it is close to purpose-built.

**It requires a public professional account with at least 1,000 followers.** At 0 followers it does not
exist for us. ⚠️ Soft ceiling reported around five trial reels per day, ~20 via API.

**Put it in the plan at the 1k milestone**, not at launch: at that point the ledger's fifty covers have
made the account a template factory, and trial reels are how you stop guessing which name-video shape
travels.

### F7 · The Name field is the most valuable string on the account, and Google reads it too — ✅ high

Instagram's search weighs three fields: **username, Name field, and bio**. The Name field is the most
heavily weighted *searchable* field, and unlike the handle it can be rewritten at any time without
breaking a link. Public Instagram profiles are also now indexed by Google.

`04` §5.14's proofed Name field — `Bayram | Ismingiz bilan qoʻshiq · Tugʻilgan kun sovgʻasi` — is
therefore correct and load-bearing, and the handle `bayrambot.uz` carrying no keyword costs nothing,
because the keywords live next door. Bio copy should read as natural language stating who it is for,
not as a keyword list; `04` §5.14's two lines already do.

### F8 · The AI label applies to personas, not tools — ✅ high, and `04` was right

Since 31 August 2026 an account whose profile features an **AI-generated person** must carry the
`AI-generated profile` label. Photo editing, illustration and ordinary creative AI use are explicitly
out of scope. Undisclosed AI personas lose recommendation to non-followers in Reels and Explore;
**correctly labelled ones lose nothing.**

This confirms `04` §376 against `01` line 59, and it confirms `05` §8's production note: ISMCHI is shot
practically, on a phone, by one person — no synthetic human, therefore no label question. The live risk
remains the *other* one `04` named: the per-post "AI info" tag that fires automatically off C2PA/IPTC
metadata written by generators and editors, so check what our own pipeline and the editor write on
export.

---

## §2 The do-not list for a brand-new professional account

Not opinions — these are the behaviours with documented enforcement attached, and every one of them is
a thing a growth agency will offer to do for this account.

| Do not | Because |
|---|---|
| Buy followers or engagement | direct suspension risk; the fastest way to lose a 0/0 account before it has anything |
| Follow/unfollow, mass-DM | named as the most commonly penalised behaviours as of August 2026 |
| Send 50 DMs on day one | a new account doing this is "almost guaranteed to get flagged"; treat 50/day as a ceiling to grow toward, never a target |
| Burst all actions at once | new accounts run ~100–500 total actions/day across likes, comments, follows; space them |
| Post more than 2–3 times a day while new | warm up over two to three weeks before normal cadence |
| Repost or near-duplicate | F2 — up to 30 days of reduced non-follower reach, and 10+ in 30 days drops you out of Explore entirely |
| Pre-mix a label master, or switch account type to unlock a track | `01`, and F3's lawsuit record |
| Boost anything carrying a label track | commercial use requires a commercial licence regardless of account type |
| Use a synthetic human host without the label | F8 — loses non-follower recommendation |

`01`'s own rule — no growth automation or mass-following for the first 60 days — survives this
research unchanged. The one claim of `01`'s that this sweep could **not** support is that "an
aggressively pushed off-platform link from day one" is a thing that gets accounts limited: Instagram
does not permit links in captions at all, external links are a structural non-factor rather than a
penalised one, and no official statement about suppressing them exists. ⚠️ Treat the link-penalty
worry as **folklore**, and keep the bio link where it belongs.

---

## §3 Specifications worth copying exactly

- **Reel cover:** design at **1080 × 1920**, but the profile grid crops to **3:4** — so everything that
  must survive (the name, the stamp) sits inside the **centre 1080 × 1350**. Check it on the profile
  grid tab before publishing; the crop is adjustable there. Export JPG.
- **Cover design:** bold, high-contrast, three-to-five words. Thin or decorative type disappears at
  thumbnail size. Keep background, layout and type identical across covers and change only the text —
  this is the recommended way to build a cohesive grid, and it is what `06` §4's ledger already does.
- **Pinned slots:** **six** — three feed posts and three highlights — and they are the most-visible
  real estate on the profile. The 2026 formula is trust → authority → path to purchase, which is
  exactly the origin / proof / mechanics split `06` §4 specifies.
- **Cadence:** 4–7 Reels per week is the working band for an account of this size.

---

## §4 What this file could not close

- **F1's back-link question** — does a comment-reply Reel stay linked under the comment after the
  sticker is deleted? Everything about how the ladder is published depends on it. Untested.
- **F4's matching semantics** — exact-equals or contains? Decides whether keyword automation works at
  all in a language where the trigger word will arrive inside a sentence. Untested.
- **Whether `бayram`-style Cyrillic triggers behave** under a case-sensitive exact matcher. Untested.
- **Every source here is secondary.** Instagram's own Help Centre pages did not render for automated
  fetching; the findings are drawn from trade press and platform-guide publishers, cross-checked where
  they agreed. The four tests above convert the important ones into first-hand facts for about twenty
  minutes of work, and they should be run before post one.

## Sources

Account type and music licensing: [creatorflow.so](https://creatorflow.so/blog/instagram-creator-vs-business-account/),
[socialrails.com](https://socialrails.com/blog/instagram-creator-vs-business-account),
[usethirdchair.com](https://usethirdchair.com/blog/instagram-sound-library-rules-for-creators-and-brands),
[sriplaw.com](https://sriplaw.com/blog/instagram-business-accounts-and-copyright/),
[napoleoncat.com](https://napoleoncat.com/blog/instagram-creator-vs-business-account/) ·
New-account limits and enforcement: [socialchamp.com](https://www.socialchamp.com/blog/instagram-limits/),
[zorcha.com](https://zorcha.com/blogs/13-best-practices-to-avoid-getting-suspended-on-instagram-in-2026),
[usewave.co](https://www.usewave.co/blog/instagram-dm-limits),
[metricool.com](https://metricool.com/instagram-limits/),
[crossglobemarketing.com](https://crossglobemarketing.com/blogs/instagram-original-content-algorithm-2026/),
[sociallyin.com](https://sociallyin.com/blog/instagram-algorithm-update-repost/) ·
Comment-reply Reels: [minter.io](https://minter.io/blog/how-to-reply-to-a-comment-with-an-instagram-reel/),
[wersm.com](https://wersm.com/instagram-adds-option-to-reply-to-comments-with-reels/) ·
Native automation: [creatorflow.so](https://creatorflow.so/blog/instagram-built-in-automation/),
[sendpulse.com](https://sendpulse.com/blog/instagram-comment-automation),
[creatorflow.so](https://creatorflow.so/blog/instagram-dm-compliance-meta-rules/) ·
Bio links: [searchengineland.com](https://searchengineland.com/instagram-now-allows-up-to-5-links-in-bio-395742),
[soci.ai](https://www.soci.ai/knowledge-articles/instagram-link-in-bio/) ·
Trial Reels: [creators.instagram.com](https://creators.instagram.com/blog/instagram-trial-reels),
[storrito.com](https://storrito.com/resources/how-instagram-trial-reels-work-72-hours/),
[postfa.st](https://postfa.st/blog/instagram-trial-reels) ·
Profile SEO: [seosherpa.com](https://seosherpa.com/instagram-search-results/),
[toptal.com](https://www.toptal.com/creator/post/instagram-seo) ·
AI labelling: [workos.com](https://workos.com/blog/instagram-ai-generated-profile-label),
[mlq.ai](https://mlq.ai/news/instagram-will-limit-reach-for-undisclosed-ai-generated-profiles/) ·
Covers, pins, cadence: [buffer.com](https://buffer.com/resources/instagram-image-size/),
[planoly.com](https://www.planoly.com/blog/designing-reel-covers),
[instantdm.com](https://instantdm.com/blog/the-perfect-pinned-post-formula-how-to-turn-your-instagram-profile-into-a-client),
[socialrails.com](https://socialrails.com/blog/instagram-posting-frequency-guide) ·
External links: [socialmediatoday.com](https://www.socialmediatoday.com/news/heres-each-big-social-platform-stand-external-links/733946/)
