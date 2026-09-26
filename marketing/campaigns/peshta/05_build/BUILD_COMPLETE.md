# Build complete — 2026-09-19

**Deliverable:** `build/reel_peshta_1080x1920.mp4`

| Check | Target | Measured | |
|---|---|---|---|
| Resolution | 1080×1920 | 1080×1920 | ✅ |
| Frames | 1290 | 1290 | ✅ |
| Duration | 43.000 s | 43.000000 s | ✅ |
| Frame rate | 30 fps CFR | 30/1 | ✅ |
| Video | H.264 High, yuv420p | h264 High, yuv420p | ✅ |
| Audio | AAC-LC 48 kHz stereo | aac 48000 2ch | ✅ |
| Integrated loudness | −14 LUFS | **−14.1 LUFS** | ✅ |
| True peak | ≤ −1.0 dBTP | **−1.2 dBFS** | ✅ |
| Bitrate | ~9 Mbps | 9.09 Mbps | ✅ |

Also produced: `build/reel_peshta_1080x1920_silent.mp4` (picture master) and
`build/cover_frame0.jpg`.

## Gates

| Gate | Result |
|---|---|
| GATE 0 — audio slices | PASS, 11.000/7.000/5.000/5.000 s exact |
| GATE 0b — IP gate | PASS |
| GATE 1 — casting | PASS. 1 of 4 per character had the anchor on the correct side |
| GATE 4 — keyframes | PASS 14/14; 10 on attempt 1, 4 rescued by attempt 2 |
| GATE 6 — lip-sync pilot | PASS, measured +0.999 envelope corr at 0 ms lag |
| GATE 7 — the four beds | PASS, +0.999 / +0.999 / +0.999 / +0.998, all at 0 ms |
| GATE 8 — cutaway takes | PASS 6/6 |
| GATE 10 — conform | PASS, 32/32 shots frame-exact, 0 mismatches |
| Master | PASS, all spec rows above |

## Spend

**180.0 credits** against a 548.5 budget — 67 % under. Two things drove that down: Reference
Elements deleted Steps 2 and 3 entirely (32 cr + 120 unpriced reserved), and no take needed a
retry.

Wallet: 1568.10 → 804.10 over the session. This build took 180; the remaining ~584 went to the
parallel agent's Motion-Control runs, which are not part of this work.

## Deviations from `05_HIGGSFIELD_RECREATION_SETUP.md`

1. **Steps 2 and 3 deleted.** The `soul_2` reference-image path (Step 3b) cannot place a
   character in a scene — it clones the reference's whole frame. Reference Elements replace both
   the sheets and Soul training. See `FINDINGS.md` §2–3.
2. **Every character keyframe moved from `soul_2` to `nano_banana_pro` + Elements.** Only the two
   crowd-only frames (S-A08, S-B02) stayed on `soul_2` text-only.
3. **`kling3_0` std does not return 1080×1920.** Measured: K1 720×1280, K2/K4/K5/K6 716×1284,
   K3 680×1352, all at **24 fps**. `bin/cut.sh`'s
   `scale=…:force_original_aspect_ratio=increase,crop` plus `fps=30` carried all six takes —
   the plan's "nothing is ever cropped/scaled" claim is wrong. Accepted a ~1.5× upscale on the
   23.8 s of cutaway rather than paying `mode:"pro"`; the lip-sync beds, which hold the face and
   are 45 % of runtime, are native 1076×1928.
4. **S-B02 repaired by crop, not re-roll** — it returned inside a decorative film border,
   removed with `crop=912:1808:120:120` for 0 credits.

## Three environment traps worth keeping

- **Step 0's slicing loop is bash-only.** `set -- $spec` does not word-split in zsh, which is the
  default shell here; the loop silently produced no slices. Run it with `bash`.
- **ffmpeg eats stdin**, which consumed the conform loop's `while read` input and shifted every
  other row. Call the scripts with `</dev/null`.
- **The concat demuxer resolves paths relative to the list file's own directory.** `cuts/shot_01.mp4`
  in `build/concat.txt` became `build/cuts/…`. Write absolute paths.
