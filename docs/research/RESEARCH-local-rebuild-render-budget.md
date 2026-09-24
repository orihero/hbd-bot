# The honest render budget for the local rebuild

**Date:** 2026-09-19
**Machine-readable version:** `marketing/campaigns/peshta/06_local/render_budget.json`
**Question it answers:** is it worth spending a night of GPU time rebuilding the 43-second
vertical reel on our own hardware, to see whether local models can match the version we paid a
cloud service to make?

---

## The number, and the recommendation

**Do not spend the night yet. Spend two hours first.**

The full rebuild is **38 separate video generations**, not the 14 an earlier note promised, and it
will take **somewhere between 6 and 23 hours of GPU time — call it 12**. The earlier "14 units,
about 5 hours" figure was not merely optimistic. It was costing a different film: it assumed each
of the reel's 11 sections was one unbroken shot, and every one of them turns out to contain hard
cuts inside it.

Before committing 12 hours, render **four** of those 38 pieces — about **two hours** — and look at
them. They are chosen to break the things most likely to break. If they hold up, the night is worth
buying. If they do not, you will have learned it for two hours instead of twelve.

And there is a cheaper gate inside the cheap gate: the first **30 minutes** of those two hours
produces only still images, needs no downloads, and already answers the single biggest question.
Stop and look at that point.

---

## Glossary, once

| Term | What it means here |
| --- | --- |
| **still / keyframe** | A single generated picture. Every video clip has to start from one. |
| **i2v** | "Image to video" — the model takes one still and animates forward from it. This is the expensive step. |
| **sub-shot** | One uninterrupted camera setup. The reel has 38 of them. |
| **N_max** | The most frames the video model can produce in one go before it runs out of memory. Not yet confirmed. |
| **SR** | "Super-resolution" — the optional final step that lifts the picture from 720×1280 to 1080×1920. |
| **interpolation** | Inventing in-between frames to convert the model's 24 frames per second to the master's 30. |
| **identity drift** | The lead's face quietly changing between shots, because each still is generated independently. |

---

## A. How many generations — 38, and the memory limit does not change it

A useful and slightly surprising result: **the unconfirmed memory limit does not matter to the
count.** We tested the four candidate values that the still-running benchmark might return — 121,
97, 81 and 61 frames per generation — and at every one of them the answer is the same:

| Memory limit (N_max) | Generations | Forced by the model | Longest clip needs | Margin |
| --- | --- | --- | --- | --- |
| 121 frames | 38 | 0 | 61 frames | 60 |
| 97 frames | 38 | 0 | 61 frames | 36 |
| 81 frames | 38 | 0 | 61 frames | 20 |
| 61 frames | 38 | 0 | 61 frames | **0** |

The longest single sub-shot in the reel is just under two seconds. Even in the worst case it fits
in one generation. **The edit sets the budget, not the hardware.**

One caveat worth holding: at the worst case of 61, the longest sub-shot needs *exactly* 61 frames.
Zero splits, but zero margin. If the benchmark comes back below 61, exactly one sub-shot splits.

**Why a forced split would matter.** If a sub-shot ever had to be generated in two pieces, the
rebuild would show a hard cut in a place where the master has none. That is not a bookkeeping
detail — it is a visible difference in the finished film, and the whole point of the exercise is to
compare like with like. None are required. Good.

---

## B. Wall clock — 6 to 23 hours, centre about 12

Here is the honest arithmetic, and the honest uncertainty.

**What we actually measured:** a still takes 107 seconds. A 121-frame video clip takes roughly 19
minutes. That is all. Everything else below is a model built on those two numbers.

**What we did not measure, and it is the whole ballgame:** whether a *short* clip is proportionally
cheaper than a long one. Nobody knows. Three defensible answers give three very different bills:

| Assumption about short clips | Video stage alone |
| --- | --- |
| They buy nothing — every clip costs the full 19 minutes | **12.0 h** |
| Fixed 4 minutes of setup per clip, then a flat rate per frame | **5.6 h** |
| Attention cost grows with the *square* of clip length, so short clips are much cheaper | **3.7 h** |

That is a 3.3× spread from one unmeasured quantity, on the stage that is 60–75% of the job.

Adding every other stage:

| | Optimistic | Central | Pessimistic |
| --- | --- | --- | --- |
| Character reference sheets | 21 min | 27 min | 32 min |
| 38 keyframe stills | 68 min | 102 min | 136 min |
| 38 video generations | 3.7 h | 7.0 h | 16.8 h |
| Super-resolution | skipped | 1.9 h *(guess)* | 1.9 h *(guess)* |
| Frame interpolation | 19 min *(guess)* | 57 min *(guess)* | 95 min *(guess)* |
| Assembly and mux | 10 min | 10 min | 10 min |
| **Total** | **5.6 h** | **12.1 h** | **23.3 h** |

Excluding super-resolution entirely: **5.6 h / 10.2 h / 21.4 h**.

Three honesty notes, because the brief asked for them:

- **The super-resolution stage has never been run, let alone timed.** The 3 minutes per clip above
  is a placeholder. It could be 1 minute; it could be 8.
- **The interpolation numbers are also guesses.** That stage has never been timed either.
- The optimistic column assumes the unmeasured scaling law holds *and* that nothing needs
  re-rolling. On a dance video with hands in shot, nothing has ever needed zero re-rolls.

Stills are also not free: the plan needs **one still per sub-shot — 38 of them, not 14**. That is
roughly an extra hour that the earlier estimate simply did not contain.

---

## C. The four files waiting to be downloaded (9.9 GB total)

| File | Size | What it buys | What it costs |
| --- | --- | --- | --- |
| **1080p upsampler** | 192 MB | The only route to a 1080×1920 result. Without it we ship 720×1280 blown up, and the comparison is not resolution-matched. | *Adds* up to 1.9 h of render time. |
| **Frame-interpolation weights** | 104 MB | The 24→30 fps conversion the entire frame plan is built on. Without it, judder — on a dance video. | 19–95 min. Cheapest quality on the list. |
| **Vision encoder** | 817 MB | Makes each clip stick to the still it was given. Attacks the project's biggest quality risk directly. | Essentially nothing. **Best value of the four.** |
| **Smaller text encoder** | 8.7 GB | Nothing to the picture — this one attacks the *clock*. | Its own download time. |

**The fourth one is the only lever on speed, so it deserves a number.** Today a 15.4 GB text
encoder shares the graphics card with a 15.5 GB video model. Our own node survey names that
contention as the direct reason a clip takes 19 minutes: the two models take turns being evicted
and reloaded. The smaller copy is 8.7 GB and frees roughly 6.7 GB, so the eviction stops.

**Estimated saving: 15–35% off per-clip time — 19 minutes falling to roughly 12–16. Across 38 clips
that is about 1 to 2 hours back.** This is an estimate, not a measurement, and it could be zero: if
the real bottleneck turns out to be the model's own maths rather than memory pressure, this
download buys nothing at all. Downloading 8.7 GB costs about 12 minutes on a fast line and 40 on a
slow one, plus a manual file move.

---

## D. The cheapest experiment that actually tells you something

**Render four sub-shots: `10a`, `05b`, `11a`, `11b`. About two hours. Then look at them.**

This is a recommendation, not a hedge. Each of the four is there to break something specific, and
each was chosen after looking at the actual frames of the master rather than at any document.

- **`10a` — the face close-up.** A tight shot of the female lead filling the frame, both hands
  raised beside her jaw, fine pearl chains against a cream collar, deep red behind. Big face plus
  nearby hands is the hardest thing to generate. It is also the exact shot the old planning
  document described as a *wide full-body seated shot* — it is nothing of the kind — so rendering it
  proves the corrected shot list end to end.
- **`05b` — the fast full-body dance move with hands.** The male lead alone on a red stepped
  platform, feet planted on a hard edge, arms swinging through a beat, the hatted ensemble ranked
  behind him, camera reframing. Full-body anatomy, feet, swinging hands and a background crowd at
  once. If local video falls apart anywhere, it falls apart here.
- **`11a` and `11b` — the seam.** Two consecutive shots of the *same man*, same suit, same set:
  wide full-body, then a hard cut to a medium profile. These are generated from two completely
  independent stills and then butted together. If the model cannot hold one face, the drift lands
  on adjacent frames where the eye compares them side by side. **This is the one test the full
  build cannot survive failing.**

**Cost: about 2 hours (1.0 h optimistic, 1.5 h central, 2.3 h pessimistic).** Roughly a seventh of
the full build.

**Run it in two stages and stop in the middle.** Stage one is the two character reference sheets
plus the four stills — **30 minutes, still images only, needs none of the four downloads.** Look at
them. If the four pictures are not recognisably the same two people, stop there: no amount of video
quality rescues a project that cannot hold a face, and you will have spent half an hour learning
it. Only if they hold does stage two — the four clips, interpolation, upscale and assembly — get
launched.

What this does not test: the desert location, the hooded ensemble, the veiled figure, the two
dissolve-style seams, and whether identity holds across *38* stills rather than four.

Downloads needed for a fair stage two: the interpolation weights (104 MB) and the vision encoder
(817 MB). Skip the upsampler and compare at 720×1280. The big text encoder is not worth its own
download time at four clips.

---

## E. Four ways to make it cheaper, and what each one costs the comparison

1. **Drop sub-shot `10c` and cover it from the tail of the shots either side.** Saves 11–27
   minutes. Costs three frames — one tenth of a second, in a place where the master simply returns
   to a framing already on screen. Nobody can see this. **Take it.**

2. **Generate fewer spare frames per clip** (cut the trim allowance from 12 frames to 4). Saves
   about 33 minutes — *and nothing at all* if it turns out cost is per clip rather than per frame.
   Costs the slack we use to throw away a bad first frame or a glitchy tail, so defects that would
   have been trimmed become visible instead. **Hold it in reserve**, use it only once we know the
   scaling law and have seen clean clip heads.

3. **Skip the upscale and compare at 720×1280, with the master shrunk to match.** Saves up to 1.9
   hours and a download. Costs the ability to say anything about finish — and it flatters both
   sides, because shrinking the master hides its own softness too. **Take it for the experiment,
   reject it for the final verdict.** Motion and identity are what is in doubt; resolution is not.

4. **Reuse one still across neighbouring sub-shots of the same setup.** Saves under 15 minutes even
   if every candidate were taken. Six of the eight candidate pairs are a size change — one picture
   physically cannot serve both. On the two that could, both clips would open from an identical
   frame, and the master's cut there is a genuine change of setup; our version would read as a
   stutter where the master reads as an edit. **Reject.** Trivial saving, visible defect, and it
   damages precisely the seam quality the whole comparison is trying to measure.

---

## The single biggest driver

**The 38 video generations — and specifically, the unmeasured question of how generation time
scales with clip length.** That stage is 60–75% of the total in every scenario, and that one
unknown swings it between 3.7 and 12.0 hours.

There is a benchmark already queued that answers it: short runs at 49 and 33 frames, behind the
121-frame run. **They collapse a 3.3× spread into a number, and they cost minutes.** Nothing else on
this page is worth as much. Do not start the full reel before they land.

A related and genuinely counter-intuitive point: because per-clip setup cost does not shrink, 38
short clips are **not** obviously cheaper than 14 long ones, even though they contain the same 43
seconds of film. If the pessimistic model is right, they are 2.6× *more* expensive. If the
optimistic one is right, they are cheaper. That is exactly what the pending benchmark decides.

---

## One risk that is not on the clock

Time is not the only thing 38 sub-shots cost.

On this hardware, the lead's face is held together by nothing but the reference images fed to the
still generator — there is no trained character model, no face-locking adapter, none of the tools
that normally guarantee consistency. **38 independently generated stills are 38 chances for the
face to drift**, and a hard cut every 1.2 seconds parks those drifts next to each other on screen,
where the eye compares them. Fourteen longer units hid drift by cutting less often. Thirty-eight
cannot. **None of the four downloads fixes this, and no amount of GPU time buys it back.** That is
why `11a`/`11b` is in the recommended experiment.

Worth stating plainly when the comparison is finally judged: **the master is itself inconsistent.**
Three visibly different men play the male lead across its 43 seconds — a heavier clean-shaven man
in most of the studio shots, a slimmer younger stubbled man in two sections, and a bearded man
under a hat in the desert. Our rebuild deliberately holds *one* face throughout. If that is not said
out loud, the rebuild will be marked down for being more consistent than the thing it is copying.

---

## Where the numbers live

- Full machine-readable budget, including per-sub-shot frame counts and timings:
  `marketing/campaigns/peshta/06_local/render_budget.json`
- The corrected 38-sub-shot cut list: `marketing/campaigns/peshta/06_local/subshots.json`
- The corrected shot bible: `marketing/campaigns/peshta/06_local/shot_bible_v2.json`
- Verified node schemas and the four pending downloads: `marketing/campaigns/peshta/06_local/node_schemas.json`

**Ground truth rule, restated because it produced every correction above:** the delivered master
reel is the only description of what the film looks like. The prompts we sent the cloud service
record what we *asked for*, not what came back. Where a document and a frame disagree, the frame
wins. Sixteen frames were viewed directly for this budget; nothing in it about the master's content
is inferred from a filename, a timestamp or an older document.
