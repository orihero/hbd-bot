# Reading the A/B metrics: Higgsfield cloud reel vs local-model rebuild

**Status:** harness built and self-verified 2026-09-19. No local render exists yet, so
every number below is a *prediction* of what to look for, not a result.

**Harness:** `marketing/campaigns/peshta/06_local/compare_ab.py`
**Output:** `marketing/campaigns/peshta/06_local/ab/{side_by_side.mp4, contact_sheet_A.png, contact_sheet_B.png, metrics.json}`

This document exists so that whoever opens `metrics.json` after the first local render can
tell, without re-deriving anything, whether the local pipeline is **worse**, **better**, or
merely **different**. That third category is the one that matters: a local render that
scores differently is not automatically a failure, and the most common mistake in a
comparison like this is to read "different grade" as "worse quality".

---

## 0. Read this before the body — a correction added 2026-09-19

This document was written against a reading of the reel that measurement has since
overturned. It is kept as written, because the harness it explains is still the harness and
`compare_ab.py` stamps this exact path into every `metrics.json` it emits. Three corrections,
in the order they will bite.

**The reel is 38 sub-shots, not eleven continuous takes.** The premise under §1, under §2.2's
"Each macro shot is supposed to be one continuous take", under the continuity row in §2.3,
under the contact-sheet argument in §3 and under the self-test result in §5 is that each of
the eleven macro windows is one unbroken shot. It is not.
`marketing/campaigns/peshta/06_local/subshots.json` records `total_subshots: 38` across those eleven
windows, 33 of them measured frame-exact, and `RESEARCH-local-rebuild-render-budget.md`
lines 15–19 states the consequence plainly: the earlier estimate "assumed each of the reel's
11 sections was one unbroken shot, and every one of them turns out to contain hard cuts
inside it." The effect on §2.2 is direct — a scene change detected inside a macro window is
not prima facie an i2v conditioning failure, because A genuinely cuts in there. §2.2's caveat
already says to read the delta rather than the absolute; read that now as the main
instruction rather than the caveat.

**The shot bible has moved.** §1's `marketing/campaigns/peshta/06_local/shot_bible.json` is a dead path.
`06_local/` now holds `shot_bible_v2.json`, and the original survives only under
`06_local/superseded/`, whose README opens "Superseded — audit trail only. DO NOT USE AS
GENERATION INPUT." `compare_ab.py:65` already points `DEFAULT_BIBLE` at the v2 file, but it
does not yet *read* it: `load_shots` (`compare_ab.py:124`) expects a top-level `shots` key,
v2 carries `master_timeline` and a 38-entry `subshots` list instead, and calling the loader
against today's default bible raises `KeyError: 'shots'`. That is a defect in the harness
rather than in this document, and it is recorded here rather than repaired here. Note that
§1's fallback paragraph does not cover it: the fallback fires only when the bible is
*absent*, and this one is present and unreadable.

**The eleven-frame contact sheet samples across cuts.** §3's sheets take one frame at the
midpoint of each macro window. Those windows contain hard cuts, so a midpoint frame is a
frame from whichever sub-shot happens to straddle the middle. The sheet remains the right
tool for identity drift, but "shot 09" on sheet A is one of several looks inside shot 09, not
its representative — so a disagreement between the two sheets may be the sampling rather than
the render. The window boundaries are themselves suspect: `subshots.json` finds the
documented eleven-window frame table drifting from the measured cuts, +1 at the first cut and
+10 by the last, with both tables summing to 1290 so no checksum ever catches it.

No claim in §1–§5 below has been rewritten. The one thing added inside the body is a dated
note beside §5's self-test command, saying where the reel it needs has gone. This folder is
frozen at its date; corrections are added, not folded in.

---

## 1. What is being compared, and why the comparison is asymmetric

A (reference) is the shipped 43s reel: 1080x1920, 30fps CFR, exactly 1290 frames, built on
Higgsfield cloud by **motion transfer** (`hf_mult_motion_control`) over 11 macro shots — a
driving video supplied the motion for every frame.

B is the local rebuild of the same 43 seconds by a **different method**: one still keyframe
per scene, then image-to-video from that still, then the existing master music muxed
underneath.

That method difference drives almost everything below. Motion transfer inherits real human
motion and real temporal coherence from the driving clip. Image-to-video invents motion
from a single frame. So the interesting failures are not "is B blurry" but **does B hold
still, hold identity, and hold the beat** across a shot that runs four to six seconds.

Shot windows come from `marketing/campaigns/peshta/06_local/shot_bible.json`. If that file is missing the
harness parses the eleven windows out of `FINAL_RECREATION_REPORT` section 3 instead and
sets `shot_windows.fallback_used = true` — check that flag before trusting the windows.

---

## 2. The metrics, one at a time

### 2.1 `frame_diff` — mean and stddev of frame-to-frame luma difference

Computed as `tblend=all_mode=difference` followed by `signalstats`, so the number is the
mean absolute luma delta between consecutive frames, on a 0–255 scale. It is doing two jobs
at once, and separating them is the whole skill of reading it.

- **`frame_diff.mean` is motion energy.** How much the picture changes per frame.
- **`frame_diff.stddev` is how *evenly* that motion is distributed** across the shot.

| Reading | What it means |
| --- | --- |
| B mean **much lower** than A (say <60% of A) | **Worse.** The classic i2v failure: the still barely animates. A "living photograph" — some parallax and cloth drift, no dance. On shots 03, 06, 08 and 09, which are the dance beats, this is disqualifying. |
| B mean **much higher** than A (say >150% of A) | **Worse, differently.** Not more dancing — this is almost always per-pixel churn: texture crawl, background boiling, a face reshuffling every frame. Confirm on the side-by-side before believing it is real motion. |
| B mean within roughly ±25% of A | **Fine.** The shot carries comparable motion. |
| B stddev **much higher** than A at a similar mean | **Worse.** Motion is lumpy — the clip sits nearly frozen and then lurches. Very common when an i2v model burns its motion budget in the first second and coasts. Look for this on the long shots: 07 (6.24s) and 09 (5.92s). |
| B stddev **much lower** than A at a similar mean | **Different, possibly better.** Motion is smoother and more uniform. Whether that reads as "smooth" or "sedated" is a human call — go to the side-by-side. |

The reference's own numbers set the scale. Per-shot `frame_diff.mean` in A ranges from
**2.86** (shot 01, a locked-off establishing wide) to **12.16** (shot 10, a 1.6s cut), with
a whole-reel mean of **6.96**. So "a shot at 3" is not sluggish if it is shot 01; compare
each shot against its own counterpart, never against the reel average.

### 2.2 `scene_changes` — scdet count inside each shot window

Each macro shot is supposed to be one continuous take. A scene change detected *inside* a
window means the video discontinuously jumped.

This is the metric most likely to catch a genuine local-pipeline defect, because an i2v
model that loses its conditioning mid-generation produces exactly this: the subject's face,
framing or wardrobe resets between one frame and the next.

| Reading | What it means |
| --- | --- |
| B count **> A count** on a shot | **Worse, and go look immediately.** Note the `times_s` array — it names the second to scrub to. |
| B count ≈ A count | **Fine.** |
| B count **< A count** | **Usually different, not better.** See the caveat below. |

**Caveat, and it is a big one.** A is *not* clean here: it logs **34 detections across the
reel** at the default threshold of 10, including 11 inside shot 09 and 7 inside shot 08.
Those two shots are the canyon dance break — fast whip-pans and hard cuts in the driving
clip. So most of A's count is **real, intended motion being flagged**, not a defect. scdet
cannot distinguish "hard cut" from "very fast motion".

Two consequences:
1. **Read the delta, not the absolute.** `scene_changes_delta` is the signal.
2. A lower count in B on shots 08/09 probably means B **failed to produce the fast motion**,
   which is a defect that looks like an improvement in this column. Cross-check against
   `frame_diff.mean` on the same shot: low scene changes *and* low frame_diff together is
   the signature of a shot that did not move.

Raise `--scdet-threshold` above 10 to suppress the motion-driven detections and isolate true
discontinuities; the threshold used is recorded in the JSON alongside every count.

### 2.3 `luma` and `saturation` — grade drift

Mean `YAVG` and `SATAVG` per shot. These compare the *look* of the two pipelines, and they
are the metric most likely to be **different rather than worse**.

The reel has two distinct looks, and the metrics show it plainly: the crimson studio shots
sit around luma 33–61, while the canyon shots 08 and 09 sit at **90.2** and **104.4**. Any
reading has to respect that split — a luma delta of 30 between A and B means something quite
different on shot 03 than on shot 09.

| Reading | What it means |
| --- | --- |
| `luma_mean_delta` within about ±5 | **Fine.** Grades match. |
| B consistently darker or brighter by a similar amount on *every* shot | **Different, and cheap to fix.** A global offset is one colour pass in the assembly step, not a model problem. Say so rather than re-rendering. |
| B's offset varies in *sign* between shots | **Worse.** The local pipeline is not holding a consistent grade, so the eleven shots will not cut together as one film. This is a continuity defect, and it is the expensive kind. |
| B saturation far **below** A | **Different, leaning worse.** The reel's identity is the crimson studio. A desaturated red set loses the brand look even if every frame is individually sharp. |
| B saturation far **above** A | **Check for clipping**, not richness. Compare `saturation.max` — if it is pinned near the ceiling the chroma is blowing out. |

Because the harness stores `min`/`max`/`stddev` as well as the mean, an intra-shot drift —
the frame getting steadily darker across a 6-second i2v generation, a known failure mode —
shows up as a large `luma.stddev` in B against a small one in A, even when the means agree.
**Check the stddev before concluding the grades match.**

### 2.4 Sharpness: what is reported and what is not

**`laplacian_variance` is `null` on every shot, deliberately.** Laplacian variance needs
numpy plus opencv or Pillow to pull decoded frames into an array, and none of the three are
installed on this machine; the brief forbids installing them. The harness reports the
omission in `metrics.json` under `sharpness.reason` rather than fabricating a number.

**`edge_energy_ffmpeg_laplacian` is reported instead**, and is deliberately named so it can
never be mistaken for the above. It is the mean of a 4-neighbour Laplacian edge map computed
by ffmpeg's `convolution` filter. It moves in the same direction as sharpness — a soft frame
gives a lower number — but it is a **mean, not a variance**, which makes it:

- more sensitive to global contrast than true Laplacian variance, and
- less sensitive to a *small region* going soft while the rest of the frame stays crisp.

That second limitation matters here, because the most likely local-render defect is exactly
a small region going soft: **the face**. A subject whose face melts while the crimson set
stays sharp can score fine on this metric. Treat it as a screening number only.

| Reading | What it means |
| --- | --- |
| B within about ±15% of A | **Inconclusive.** Judge sharpness on the contact sheet, not here. |
| B far **below** A | **Worse.** Genuine softness — i2v blur, or an upscale from a lower native resolution. |
| B far **above** A | **Suspect, not better.** Usually over-sharpening halos or h264 blocking, both of which raise edge energy while looking worse. Confirm on the contact sheet. |

Reference values: whole-reel mean **0.695**, per shot from **0.439** (shot 03) to **1.150**
(shot 09). The canyon shots score high because the rock has hard texture, not because they
are better photographed — another reason to compare shot against matching shot.

If numpy and opencv are ever installed on the machine that runs this, the harness will pick
them up automatically and start populating `laplacian_variance`; nothing needs editing.

---

## 3. The metric that is not in the JSON

Identity. There is no objective number here for "is that the same person in shot 11 as in
shot 03", and no cheap one exists without a face-embedding model.

That is what **`contact_sheet_A.png` and `contact_sheet_B.png`** are for: eleven frames, one
per macro shot, at the midpoint of each window, labelled with shot number and timestamp.
Put the two sheets side by side and identity drift is a two-second judgement.

This is worth stating plainly, because **the reference itself drifts.** On sheet A, the lead
does not read as one continuous person across all eleven shots — wardrobe and face both move
between the studio and canyon halves. So the bar for B is not "perfect identity", it is
**"no worse than A"**. Judging the local render against an imagined perfect reference will
reject a build that is actually competitive.

---

## 4. Order of reading

Thirty seconds, in this order:

1. **`side_by_side.mp4`** with sound on, once through. Most verdicts are already decided
   here. The burned-in timecode names the live shot number, so note the shots that bothered
   you.
2. **The two contact sheets**, side by side. Identity and grade drift.
3. **`metrics.json`**, and only for the shots step 1 flagged. `per_shot.delta_A_minus_B` is
   the array to read; the per-side absolutes are there to give the delta scale.

Do not start at the JSON. Every metric here has a failure mode that looks like a pass, and
the numbers exist to explain and localise what the eye already caught — not to replace it.

---

## 5. Harness self-verification

Before any real comparison, the harness was run against the reference reel **compared with
itself**, which must drive every difference to exactly zero:

```
python3 marketing/campaigns/peshta/06_local/compare_ab.py \
    --b marketing/campaigns/peshta/final_polat_peshta_reel.mp4 --label-b "B  SELF-TEST COPY"
```

*Added 2026-09-19:* that command is still exactly the one that was run, and it is left
unedited because the numbers below are its output — but it is no longer runnable from a fresh
clone. `marketing/campaigns/peshta/final_polat_peshta_reel.mp4` is matched by `.gitignore` line 83
(`marketing/campaigns/peshta/**/*.mp4`), so the reel is present on the machine that produced this document
and absent from the repository. Anyone re-running the self-test elsewhere has to fetch the
reel first; the same applies to `--a`, whose default is the same file.

Result: `self_test_result.max_abs_delta = 0`, `passed = true` — all seven delta fields on all
eleven shots exactly `0.0`. `side_by_side.mp4` rendered at 2160x1920, 1290 frames, 43.000s,
frame-exact against the source, with one audio stream.

The harness sets a non-zero exit code if a self-test fails, so it can be wired into a check.
Re-run the self-test after any edit to `compare_ab.py`: it is the only thing standing between
a metric bug and a wrong verdict on the local pipeline.

### A note on the two environment workarounds

Both are load-bearing and neither is a hack worth removing:

- **This ffmpeg has no `drawtext` and no `subtitles`** — it is built without libfreetype and
  libass. Every burned-in label is therefore rendered to PNG by
  `marketing/campaigns/peshta/06_local/_abtext.py`, a stdlib-only PNG writer with a 5x7 bitmap font, and
  composited with `overlay`. The running timecode is a 1 Hz PNG sequence for the same reason.
- **The side-by-side is an `hstack` at 2160x1920, not a vstack into 1080x1920.** Stacking two
  9:16 frames into a 1080x1920 canvas would force each half to roughly 540x960 — a 4x
  reduction in pixel count — destroying precisely the detail this comparison exists to judge.
  Side by side also puts the two faces at the same vertical position, so comparing is one
  short horizontal glance. `--layout vstack` is available for phone viewing and is explicitly
  the lower-fidelity option.
