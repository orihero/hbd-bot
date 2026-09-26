# Bed audition — `variant_d_bed_001.mp3`

**File:** `marketing/campaigns/peshta/audio/variant_d_bed_001.mp3` · 30.040813 s · MP3 128 kb/s CBR · 44.1 kHz stereo · md5 `f44e2134a9acd1de0a9d72e5f9c461af`
**Provenance:** unauthorised Phase B render, ~$0.075, `remote_id=LIZxbNHtSqirtfbLeSrA` (so it *can* be inpainted).
**The decision:** keep this take, re-roll one chunk of it, or bin it and render fresh. Nothing below spends money and the bed was never touched.

---

## Bottom line

Technically the bed is clean and the grid it lays down is better than the one the plan assumed — **but I cannot tell you whether anyone is singing on it, let alone in Uzbek, and that is the only thing that decides this.**

What measurement settles: the file is a real, continuous 30 s render with no clipping, no DC offset, no dead channel and no vendor splice; it is 2.3 LU too loud, which one static −1.6 dB gain fixes; its rhythmic atom is **0.20000 s exactly**, so every cut point lands on an integer frame at 25/30/50/60 fps with no time-stretch; its arrangement repeats on a **strictly periodic 6.400 s phrase** (three intervals measured at 6.400, 6.400, 6.400); and the plan's locked 95.8 BPM is dead, which is exactly what §2.3's Step 0.5 rider was written to catch. Because the arrangement is that periodic, **exactly two 15 s windows exist** that put the slam on a real drop *and* leave the §2.4 vacuum naturally bass-free: starting at **9.015 s** or at **2.615 s**. Their energy shapes are identical — the periodicity guarantees it. So choosing between them is not an energy decision, it is a **lyric decision**, and only your ears can make it.

What measurement cannot settle, and I will not guess at: there is a strong, continuously articulated pitched lead from 2.02 s (fundamental ~207 Hz, lifting to ~276–310 Hz after ~8.7 s) that is hard-centred and re-articulates at a plausible syllable rate — everything a male lead vocal looks like on a spectrogram. Three separate discriminators failed to separate a sung voice from a lead synth in a mix this dense. Whether it is a voice, whether it is Uzbek, whether the words are ours, and whether it is good are the §3.9 human gate, unchanged.

**One thing to fix regardless of the outcome:** §7.5(a) is broken and I reproduced it. It puts `-ss` *after* `-i`, so the filter graph sees input timestamps and the fade-out fires inside the output. Run verbatim at a non-zero cue it yields a correct-duration file that is **silent from ~5.9 s to the end** and exits 0 — the never-goes-red gate §12 condemns. Measured on a scratchpad copy at `CUE=9.130`: `max_volume −91.0 dB` at 6.2 s, 8.0 s and 12.0 s with `-ss` after `-i`; `−1.6 dB`, `−1.6 dB`, `−0.6 dB` at the same points with `-ss` before `-i`. Move it. This is invisible at `CUE=0`, which is why nothing caught it.

---

## Before you press play

- **It is hot.** Integrated **−12.3 LUFS**, true peak **−0.0 dBFS** against the plan's −14 / −1.0 target. Both errors point the same way, so the correction is one static **−1.6 dB**, no limiting. Use two-pass *linear* `loudnorm` or plain `volume=-1.6dB`. **Do not single-pass `loudnorm`** — in dynamic mode it crushes LRA 7.50 → 4.10, which is audible pumping.
- **It opens on a fade.** −48.6 dB at t=0, reaching full level at **2.00 s**. Nothing before 2.00 s is usable. It closes the same way: material ends ~**28.15 s**, then a fade to −63 dB by 29.9 s. Usable body ≈ **2.00–28.15 s**.

---

## The listening guide

Play the whole file once, straight through, with this open. Ordered by playback time.

| Time | Listen for | If it is not there |
|---|---|---|
| **0.00 – 2.00** | A slow fade up from near-silence. Nothing should be worth keeping here. | Nothing to do — this is expected. It simply means no cut can start before 2.00 s. |
| **2.00 – 2.05** | The track proper starting. **Is that a voice entering, or a synth lead?** Measured fundamental 206.8 Hz (G♯3), male-lead range, hard-centred. | This is the single question three discriminators failed on. If it is a synth, chunk 1 landed as ordered (`[instrumental]`). If it is singing, the vendor sang over the instrumental chunk — not fatal, but it means chunk timings were not honoured. |
| **2.00 – 5.21** | 3.2 s of groove with **no bass at all** (sub band −40 to −44 dB). Thin, tense — chunk 1's brief. | If it sounds full and bassy here, my band measurements are being fooled and the whole despair section loses its free musical support. |
| **5.215** | **THE DROP.** First 808 in the track, after 5.2 s with no bass whatsoever. Sub peak −6.5 dB. | This is candidate window **B**'s slam. If it does not land as an impact by ear, window B is out. |
| **5.82 / 6.42** | Two more 808s, 0.6 s apart — a 3+3+2 tresillo. | — |
| **6.94 – 7.82** | A **0.90 s sub-bass hole**, then the 808 at 7.815 that ends it. Does it read as a deliberate, authored gap or just a bar without bass? | §2.4 budgets post-production for a 0.94 s vacuum. This one is already in the render, 42 dB deep, 40 ms short of spec. If it reads as intentional you get it free — but note the **mids keep playing through it**, so §7.5(b) still has to duck the vocal. |
| **7.9 – 11.5** | **THE GAP — the most important 3.6 s in the file. Is anyone singing here?** Measurably the least pitched, least centred and quietest stretch in the body: no stable fundamental, sub −50 to −55 dB, full band −25 to −32 dB. | §3.5 puts `BOTDA! BAYRAM-BOTDA!` and the high vocal run in chunk 2 (6–15 s). If this is empty, one chunk under-delivered — and this is also the **cold open of the recommended window**, where a silent bed is a feature, not a fault. Answer both ways round. |
| **11.615** | The phrase-2 drop. Loudest sub peak in the file (−5.5 dB); two analysts call the region around it the track's hardest transient. | This is candidate window **A**'s slam, at master frame 130. Everything in the recommended cut rests on this hit reading as a slam. |
| **12.25 – 13.60** | A pitch lift to 276–363 Hz with audible glides — structurally the track's emotional peak, and its loudest passage. Is this `O mani kuydirding…`? Intelligible? | If the CTA-adjacent emotional line is anywhere, it is here. If it is unintelligible, chunk 3 is the re-roll candidate. |
| **13.34 – 14.02** | A 0.72 s bass hole, then a hard hit at **14.015**. | One analyst rates this the single strongest transient in the file (+22.8 dB over 50 ms). It is 2.4 s past the phrase start, so it is a *fill*, not a downbeat — usable as an internal accent, not as the slam. |
| **15.00** | Any section change — new line, new arrangement. | This is the **only one of the three requested chunk boundaries that is visible in the audio** (82nd–97th percentile of spectral change, by two independent methods). Both analysts who checked say the 808s stopping at ~14.2 s fully explains it. Confirm by ear it is a musical event and **not a splice** — a click, a breath cut or a key change here would be a vendor seam inside the cut. |
| **18.015 / 18.62 / 19.22** | The phrase-3 drop group — same shape as 11.615, 6.400 s later. | If this sounds identical to 11.615 rather than developed, the track is more loop than song. That matters for a re-render decision, not for the cut. |
| **19.78 – 20.615** | The second 0.88 s vacuum, 45 dB deep, and the fastest sub attack in the file at the end of it. | The backup vacuum if the 7.8 s one sits under a lyric you need. |
| **24.00** | A section change at the nominal chunk 3/4 boundary. | **Both analysts who tested it found nothing here** (35th and 58th percentile — not a boundary). If you also hear nothing, the chunk-to-seconds arithmetic that `build_inpaint_body` relies on is unreliable on this take, and a per-chunk re-roll would reference the wrong audio. |
| **24.00 – 28.15** | **Where exactly does `Oʻn besh mingga qoʻshiq tayyor, Bayram-botga kiring!` start and end? Write the timecode down.** | The highest-value ten seconds you can spend. §3.5 puts the entire CTA in chunk 4 (24–30 s) and `BAYRAM-BOTDA` in chunk 2 (6–15 s) — so the brand shout and the call to action are 9–18 s apart and **no 15 s window can contain both**. If the CTA is here, row 10 needs a splice or the CTA becomes a card, not a vocal. If it is not here at all, chunk 4 under-delivered. |
| **26.18 – 28.15** | The outro: no sub, thinning. Is the CTA finished before this? | If the CTA's last words fall past 28.15 they are inside the fade and unusable at any window. |
| **28.15 – 30.04** | Confirm this is a fade to nothing, not material you want. | If you want something here, the usable body is longer than I measured. |
| **whole file** | The §3.9 checklist, verbatim: Uzbek not English/Russian-accented · `oʻ` and `gʻ` not mangled · `BAYRAM-BOTDA` lands as a hard staccato shout · `Oʻn besh mingga` intelligible · `Bayram-botga kiring` intelligible · no profanity or nonsense syllables. | Any failure here outranks every measurement in this document. |

---

## The human-only questions

Nothing on this machine can answer these — no speech recogniser, no language ID, no source separation, and §3.9 states there is no acoustic check on this code path. One line each is enough.

1. **Is the vocal in Uzbek?** (If there is no vocal at all, say that instead.)
2. **Are the words the ones we wrote** — the four chunk texts in §3.5, or something else?
3. **Is the pronunciation acceptable to a Tashkent viewer** — `oʻ` and `gʻ` intact, no foreign accent?
4. **Is it good enough to carry the brand?**
5. **At 2.02 s, is that a human voice or a lead synth?** (Measurement failed here; it decides whether chunk 1 came back as ordered.)
6. **Is anyone singing between 7.9 and 11.5 s?** (Decides which of the two candidate windows is usable.)
7. **Where exactly does the CTA line begin and end?** (Decides whether row 10 can exist on this take.)

---

## What the measurements settled

### Structure

Material runs **2.00 s → 28.15 s**; fades either side. The arrangement is an 808 phrase that repeats **exactly every 6.400 s**, starting at **5.215 / 11.615 / 18.015 / 24.415 s** (intervals measured 6.400, 6.400, 6.400). Within each phrase the sub hits at +0.0, +0.6, +1.2 and +2.4–2.6 s, then **3.4 s with no bass at all**. Between phrases the sub band sits at −40 to −55 dB. The 3.6 s at 7.9–11.5 s is the quietest, least pitched passage in the body.

Nothing in the waveform marks the 6 s or 24 s chunk boundaries; only 15 s shows up, and an arrangement event explains it. **You cannot read chunk delivery off this file.**

### Tempo — the plan's 95.8 BPM is dead

The rhythmic atom is **0.20000 s**, fitted by least squares over 15 measured 808 attacks spanning 20.4 s, residuals below my 5 ms resolution. Phase-coherence sweep over the same onsets: R = 0.986 at 0.2000 s, against R = 0.324 at the plan's 0.6263 s and R = 0.259 at 0.600 s. The 808s fall on atoms **0, 3, 6, 13** of each 32-atom phrase — a 3+3+2 tresillo, which is exactly what makes `bpm_detect.py` report **100.00 BPM at MEDIUM**: 0.600 s is three atoms, the commonest gap in a tresillo, so a single-lag picker lands on it. The tool found a real periodicity; it named the wrong one. Its own failing sub-check says so — *inter-onset disagreement 0.331 beat against a 0.08 tolerance*, which is one atom's worth of disagreement with a 0.6 s grid.

**100 BPM is ruled out structurally, not by preference:** a 100 BPM bar is 12 atoms, and the phrase is 32 atoms, three times in a row. 32/12 = 2.67 bars, which cannot be. At 16 atoms to the bar the phrase is exactly 2 bars.

| | Value |
|---|---|
| Atom (16th) | **0.20000 s** = 10 frames @50 fps, 5 @25, 6 @30, 12 @60 |
| Grid phase | ≈ **+0.015 s** *(±25 ms — see the disagreement below)* |
| Beat | 0.800 s = 40 frames @50 |
| Bar (16 atoms) | 3.200 s = 160 frames @50 |
| **Phrase (32 atoms)** | **6.400 s = 320 frames @50** — the bed's real macro-unit |
| Tempo | **75.00 BPM 4/4** (150.00 double-time — same grid, naming only) |

**Keep 50 fps.** §2.2's fps agonising and its "15.031 s trap" both evaporate: the atom is one fifth of a second, so the grid is frame-exact at every rate divisible by 5, and the audio cut is a round 15.000 s, not 15.0313.

### The two windows, and why there are only two

Constraints: the §2.4 vacuum at rel 1.60–2.54 must sit in a bass-free stretch, and the authored slam must not flam against a real 808. Bass-free runs from phrase+3.0 to phrase+6.4, which pins the window start to `phrase + 3.8` — i.e. **the slam lands on the next phrase downbeat, at rel 2.600 (frame 130)**, which §3.8 step 4 already blesses as the rate-agnostic slam time. That yields exactly three starts, of which two leave 15 s of bed:

| | **A — w = 9.015 s** | **B — w = 2.615 s** |
|---|---|---|
| Slam lands on | 11.615 s (loudest sub peak in the file) | 5.215 s (the first drop, largest bass contrast) |
| Cold open, rel 0–1.6 | **−28.7 dB** — the breakdown; clear air for a VO | −21.7 dB — the lead is playing over it |
| Vacuum, rel 1.6–2.54 (sub) | **−54.1 dB** — free | −43.3 dB — free |
| Dance, rel 2.6–8.0 (sub) | −18.6 dB | −21.8 dB |
| Loop seam (0.4 s, full / sub) | 4.0 / 6.5 dB | **0.0 / 3.7 dB** |
| Ends at | 24.015 s | 17.615 s |
| Risk | depends on 7.9–11.5 s being vocal-free | despair section plays under a hype lead |

**A is the recommendation, conditional on question 6.** It has the only genuine breakdown in the file as its cold open. If someone is singing at 9.0–10.6 s, take B instead and accept the weaker despair bed.

A 12.800 s cut (two whole phrases) from either start is the only length that loops truly seamlessly — but it drops ~2.2 s of funnel exposure, and G16's handle requirement gets tight. Not recommended.

### Re-derived §2.4 table — window A, 750 frames @ 50 fps

Every boundary a multiple of 10 frames (one atom), so every cut is on the musical grid and integer at 30/50/60 fps.

| # | Frames | rel t | abs t (bed) | Bed event | Row |
|---|---|---|---|---|---|
| 1 | 0–9 (10f) | 0.000–0.200 | 9.015 | breakdown, no sub | cold open, snap-zoom |
| 2 | 10–79 (70f) | 0.200–1.600 | 9.215 | breakdown continues | SH-01 despair |
| 3 | 80–129 (50f) | 1.600–2.600 | 10.615 | sub −54 dB — **vacuum is free** | snap-zoom 1.00→1.20 |
| — | **frame 130** | **2.600** | **11.615** | **phrase-2 808, sub peak −5.5 dB** | **SLAM · hard cut · cover frame** |
| 4 | 130–219 (90f) | 2.600–4.400 | 11.615 | 808s at rel 2.6/3.2/3.8 | SH-02a |
| 5 | 220–309 (90f) | 4.400–6.200 | 13.415 | 808 at rel 5.0, then bass-free | SH-02b punch-in |
| 6 | 310–399 (90f) | 6.200–8.000 | 15.215 | bass-free — **the dance's quietest 1.8 s** | SH-02c punch-in |
| 7 | 400–449 (50f) | 8.000–9.000 | 17.015 | still bass-free | SH-03 phone |
| 8 | 450–529 (80f) | 9.000–10.600 | 18.015 | **phrase-3 808 lands on this cut** | REAL SCREEN RECORDING |
| 9 | 530–579 (50f) | 10.600–11.600 | 19.615 | 808 at rel 11.2, then vacuum | SH-02d reaction |
| 10 | 580–669 (90f) | 11.600–13.400 | 20.615 | 808 at rel 11.6, then bass-free | SH-04a CTA (bed ducks 6 dB) |
| 11 | 670–749 (80f) | 13.400–15.000 | 22.415 | bass-free turnaround | SH-04b, 60 ms fade, loop |

`10+70+50+90+90+90+50+80+50+90+80 = 750 frames = 15.000000 s`

Three of the film's hardest cuts (frames 130, 450, 580) now land on real 808s. **Credits are unchanged at 49** — every shot's new screen time still fits inside the generation length §6.4 already priced: SH-01 needs 1.4 s of 2 s, SH-02 needs 6.4 s of a 6 s clip (0.40 s reuse, marginally better than the plan's documented 0.46 s), SH-03 1.0 s of 2 s, SH-04 3.4 s of 4 s. G16 re-checked: handle in at frame 150 → 600 continuous frames (needs ≥500) and CTA 170 frames as newest/largest (needs ≥125). **Both pass.** Post-5.0 s cut lengths: 1.8, 1.0, 1.6, 1.0, 1.8, 1.6 s — all under the 2.0 s ceiling. Cover frame moves 127 → **130**.

**The one structural cost, and it is unavoidable.** The phrase period is 6.400 s and the slam is at rel 2.600, so a second drop necessarily lands at rel 9.000 — inside the product demonstration. No start time fixes a period. Row 8 above turns it into the demo's cut point, which is the best available answer. Note that §2.4 never actually asks for a quiet product beat; "rows 7–9 must be calm" is one analyst's inference, not a plan requirement. Judge it at 18.015 s by ear: if a viewer can still read the bot UI over that drop, it is a caveat; if the drop steals the demo, it is a reason to re-render.

---

## Where the analysts disagreed

Three analysts measured this bed independently. Averaging them would hide the useful part.

- **Tempo naming.** Two said ~75 BPM (0.2 s sixteenth, 3.2 s bar); one said 100.00 BPM, agreeing with `bpm_detect.py`. My own fit sides with 75, and the deciding argument is structural rather than statistical: the 32-atom phrase repeats three times and 32 is not a whole number of 100 BPM bars. **75 vs 150 is a naming choice I cannot settle by measurement and it changes no cut point.** 100 is ruled out.
- **Atom length, and whether to time-stretch.** One analyst measured 0.20036 s and proposed a 0.18% `atempo` stretch to make the atom exactly 10 frames. Two others and my own least-squares fit put it at **0.20000 / 0.199976 / 0.20005 s** — already exact. **Do not stretch a paid vocal on a 0.18% reading that three other measurements contradict.**
- **Grid phase.** Reported as +0.015 s (mine), +0.038 s and +0.065 s, because each analyst walks back from the 808 peak by a different amount. The true perceptual attack is somewhere in that 50 ms band — under one frame at 50 fps, but at the edge of the plan's own 20 ms binding window. If the slam feels late in the first render, nudge by one frame.
- **The strongest transient.** Named as 14.060 s, 11.670 s and 7.802 s by the three. They are measuring different things (broadband rise vs sub-band level vs onset strength). All three are real hits; **11.615 s has the highest sub peak** and is the one the recommended cut is built on.
- **The head of the file.** One analyst called 0.00–2.00 s unusable fade and ruled out any cut starting there; another ranked a `w=0` window second precisely because it is the quietest cold open in the file. Both facts are true. My measured seam for a `w=0` window is 31 dB full-band / 52 dB sub — **it cannot loop**, which §2.6 makes a gate. That settles it against `w=0`.
- **The verdict.** One analyst concluded the structure is fatal ("no 15 s window carries the film's shape"), the other two concluded it is a keep. The pessimistic reading assumes the slam must be taken from the bed; **§2.4 and §3.4 both specify an authored 45 Hz sine in ffmpeg post**, so the bed only has to supply a downbeat and a bass-free bar under it, which it does. The half of that verdict that survives is the drop at rel 9.000 under the demo, which I confirmed independently and have carried into row 8.

---

## What a re-render would and would not change

**The inpaint handle exists.** `remote_id=LIZxbNHtSqirtfbLeSrA` came back, so `should_store_for_inpainting=True` was honoured and `provider.inpaint(..., source_song_id=..., chunk_index=k)` will run.

**But it is not cheaper in this repo's accounting.** `inpaint()` and `compose()` both go through `_post_music`, which records `audio_ms=plan.total_duration_ms` (30 000) and `_estimated_cost(plan)`; `estimate_cost_usd(30000, usd_per_minute=0.15)` = **$0.075** — exactly what the accidental take cost. The docstring's "costs a chunk instead of a whole track" is a claim about *vendor* billing that nothing in this repo verifies; `cost_source` is always `ESTIMATED` because `POST /v1/music` returns audio and no price.

**What a chunk re-roll can fix:** one wrong or unintelligible sung line. §3.5 puts `BOTDA! BAYRAM-BOTDA!` in chunk 2 and the **entire CTA alone in chunk 4** — so if only the CTA is wrong, chunk 4 is the cheapest possible target.

**What it cannot fix, at any price, without a new composition plan:**
- **The tempo.** `build_compose_body` sends no tempo field of any kind (§2.3). You cannot ask for 95.8 BPM.
- **The 6.400 s drop period** and therefore the drop under the demo.
- **The 2 s fade-in and 1.9 s fade-out**, and the fact that only 26.15 s of the 30 s is usable.
- **The lyric spread.** Four chunks across 30 s puts the brand shout and the CTA 9–18 s apart. No 15 s window holds both. That is a property of §3.5's chunk layout, not of this take.

**Two traps before you re-roll anything:**
- **The idempotency key.** `IDEMPOTENCY_KEY = "bayram-variant-d-bed-001"` is sent as the `idempotency-key` **HTTP header** (`elevenlabs.py` `IDEMPOTENCY_HEADER`, applied in `_headers()`). Re-running with `-001` risks the vendor replaying the cached take and charging for it. **A deliberate new take must bump to `-002`** — the script's own comment says exactly this, and it is the one line most likely to be skipped in a hurry.
- **The inpaint reference ranges are arithmetic, not measured.** `build_inpaint_body` derives the kept slices from `_chunk_offsets(plan)`, assuming chunk *k* occupies its planned span. Two of the three requested boundaries (6 s and 24 s) are **not present in the delivered audio**. So a chunk re-roll may well reference the wrong slices. Confirm boundary question 7 by ear before trusting it.

---

## The three outcomes

**1 · Keep as-is — $0.00, no schedule slip.**
Adopt the re-derived grid above, apply `volume=-1.6dB`, fix the `-ss` placement in §7.5(a), cut at **9.015 s for 15.000 s**, and go straight to Step 1. The 49-credit shot budget is unchanged and three of the film's hardest cuts land on real 808s. **Choose this if questions 1–4 all pass.** Accept: a drop under the product demo, and a CTA that is a card rather than a sung line unless question 7 places it conveniently.

**2 · Re-roll one chunk — $0.075, half a day.**
Only worth it if exactly one line is wrong and the rest is good; chunk 4 (the whole CTA) is the natural target. Costs the same as a full render in this repo's accounting, returns a **whole new 30 s track**, and therefore **invalidates every timecode in this document** — you re-do Step 0.5 either way. Verify the boundary assumption first. **Choose this only if the vocal is right but one line is mangled.**

**3 · Re-render fresh — $0.075, half a day, and it is the honest choice if the vocal is wrong.**
Bump the key to `-002`. Same price as outcome 2 and it fixes the global problems a chunk re-roll cannot touch — but only if the composition plan changes with it. If you re-render, change §3.5 first: put the CTA and the brand shout within 15 s of each other, or the next take has the same structural problem for the same money. **Choose this if question 1, 2 or 4 fails.** Budget 2–3 takes at $0.075 each, as §3.6 already does.

**Whichever you choose, no video credit moves until the §2.4 table is re-derived on paper — §2.3 requires it, and the table above is that re-derivation for outcome 1 only.**

---

## Integrity

The bed was never opened for writing. Every experiment ran on a scratchpad copy.

```
md5 marketing/campaigns/peshta/audio/variant_d_bed_001.mp3
  before:  f44e2134a9acd1de0a9d72e5f9c461af
  after:   f44e2134a9acd1de0a9d72e5f9c461af   ← unchanged
  480698 bytes · 30.040813 s · mp3 44100 Hz stereo 128 kb/s
```

**Nothing was spent.** No `mcp__higgsfield__*` call of any kind, `get_cost` included. `render_variant_d_bed.py` was not run. No socket to any vendor. Every number above comes from `ffmpeg`, `ffprobe`, the repo's own `.venv` Python and `marketing/campaigns/peshta/bpm_detect.py`.
