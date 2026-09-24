# `marketing/strategy/`

How the product is taken to market: the trend research behind a campaign, the creative that comes out
of it, and the honest record of what worked.

These documents are **frozen at their date and they rot faster than anything else in the repository.** A
ranking signal, a chart position, a platform rule and a view count all have a half-life of weeks. Every
number here is stamped with the day it was read; a number older than about three weeks should be
treated as a lie until somebody re-reads it. Correct by adding a dated line, not by editing the old one
— the playbook's reasoning has to stay legible after its facts have expired.

| File | Holds |
| --- | --- |
| [`01-instagram-launch-playbook.md`](01-instagram-launch-playbook.md) | The slate: ten production-ready video cards for the Instagram launch, the verdict on the Peshta trend, the shoot-day plan, posting cadence, account setup, and the metrics bar. **Read `04` first** — it was written before its own facts were checked, and `04` supersedes it on *content*. The account-setup half has a second superseder that this index did not name until 2026-09-19: `06` and `07` reversed those bullets on 2026-09-18, and line 747 here still reads «Account type: CREATOR, not Business, and decide it before the first edit», which is no longer the decision. Take account setup from `06`. |
| [`02-instagram-trend-research.md`](02-instagram-trend-research.md) | The evidence: seven parallel research sweeps — the Peshta trend, Reels ranking mechanics in 2026, the Uzbek scene, Higgsfield's real limits, AI-product virality, a competitor teardown, and the craft layer. Each finding carries its confidence. |
| [`03-concept-dossier.md`](03-concept-dossier.md) | The working papers: all twenty concepts, the three adversarial verdicts against each, and the objections. Kept because the objections outlive the concepts. |
| [`04-production-pack.md`](04-production-pack.md) | The pack you shoot from, dated 2026-09-17: the go/no-go gate, the six claims that were flagged UNVERIFIED and are now settled, and the five packs the day runs on — render gate, proofed Uzbek and Russian copy, the Higgsfield session, consent and releases, ladder operations. **It supersedes `01` wherever they disagree.** |
| [`05-bayram-song.md`](05-bayram-song.md) | The brand's own song, dated 2026-09-18: the syllable budget at 95.8 BPM, the submitted chorus scanned and fitted, four candidate lyric versions with two adversarial verdicts, the composite to ship, the hook-word shape rule and its two clearance gates, two original characters, and the case for original audio over a licensed ride. **Original composition — nothing in it derives from the reference track.** |
| [`06-instagram-account-design.md`](06-instagram-account-design.md) | The account as an object, dated 2026-09-18: what the profile ships as the day the `bayrambot.uz` domain and matching handle arrived — the proofed profile fields, the avatar cut and the open blue-and-gold vs cream-and-red palette decision, the grid-as-ledger system that keeps fifty cheap reply videos looking like one account, five highlights, and the apex redirect table. **Written against a live check: the domain today drops the `?start=` payload, so pointing a video at it silently destroys attribution.** **It also reverses `01` on account type:** §3 ships **Business**, not Creator — line 115 today — `07` F3 grants both halves of `01`'s music argument and then removes the reason to care, because an account that never opens the licensed catalogue gains nothing from being able to see it. |
| [`07-instagram-account-research.md`](07-instagram-account-research.md) | The evidence behind `06`, dated 2026-09-18: eight findings on what a professional account may do and what a brand-new one may not — the native comment-reply-with-Reel mechanic and its collision with our privacy rule, the near-duplicate penalty the ladder walks into, why the Creator-vs-Business decision was made for a reason that does not apply to us, the native automation caps, and the do-not list with enforcement attached. **Four platform facts in it are untested on our own account and each is a five-minute test.** |

The first three were produced on 2026-09-16 by a 77-agent research workflow, described at the end of
`01`. `04` was produced on 2026-09-17 by a verification pass against the repository, the live
production host (read-only) and primary sources; what it could not close is listed at the end of it,
unglossed.

## What has expired since — noted 2026-09-19

This folder corrects by adding, so nothing below has been edited out of the document it describes. Read
the originals for the reasoning; read this for what the reasoning no longer buys.

**The Peshta ride is off.** `01` settles "the Peshta question" in a section of its own and `03`
argues about ducking or pre-mixing the master through half a dozen verdicts; all of that is now
history. The audio underneath it is unrecoverable — the Peshta-derived Add-Vocal remix can never be
downloaded lawfully, because Suno grants commercial rights at the moment of download and will not
grant them on a track whose lineage starts with somebody else's upload of a commercial master. That
is a rights-lineage block and not a credit quota, so it does not expire and waiting does not fix it.
The replacement is a native rebuild — a text-only generation with no upload anywhere in its history,
frozen as a Persona so the winning take becomes the product's house voice — and the working,
including why licensing the real record is theoretically possible and practically dead, is in
[`../../docs/research/RESEARCH-uzbek-pop-native-generation.md`](../../docs/research/RESEARCH-uzbek-pop-native-generation.md),
dated 2026-09-19. What survives is the half `01` already got right for a different reason: card 10
was always specified to ship on a Bayram-generated 95.8 BPM bed attached as original audio. The
picker hedge at `01` L38 — open the music picker on the real account and, if the track is
legitimately there, ship a second variant attached to it — was never carried out, and it is now a
closed branch rather than an open one: the rights ruling removes everything that second variant
would have been worth, the song is five weeks past release against the 2–4 week window `01`
measured, and card 10 ships on our own bed either way. Whether the picker would have offered the
official recording at all is undecided and now academic; `06` §9 records that nothing in this folder
has been checked against a live account.

**The account is a cold 0/0 professional account, and its restricted audio library is the design
constraint, not a problem to route around.** `01` line 45 names it exactly — `@orihero.ai`, 0 posts,
0 followers, a *professional* account — and draws its conclusion from it: `01` treats professional
accounts as the ones limited to the commercial audio library, `07` F3 puts that cap on Business
specifically, and card 10 ships on our own bed under either reading. What changed since is the
account *type* and nothing else: `06` §3 ships **Business**, reversing `01` line 747, on `07` F3's
reasoning that both halves of `01`'s music argument are true and neither matters to an account that
never opens the licensed catalogue. So assume no chart track is in the picker, and never switch
account type, change the profile category or pre-mix a master to get at one. The cold start is
unchanged — no followers, no ignition, distribution decided entirely by a small unconnected test
pool reading three-second skip rate. Two facts about the live account remain unverified, and `06` §9
lists them: whether the handle is a fresh registration or `@orihero.ai` renamed, and whether it
carries any history that the grid plan has not been written against.
