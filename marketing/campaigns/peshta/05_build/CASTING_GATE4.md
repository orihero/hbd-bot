# GATE 4 — keyframe winners, 2026-09-19

12 of 14 passed on attempt 1. Four needed attempt 2:
- **S-A10 a01 FAILED** — face drifted to a different, shaved-headed man. a02 holds the anchor.
- **S-A13 a01 FAILED** — model added sunglasses that were never prompted. a02 is clean and its
  two flanking banks clip both frame edges correctly.
- **S-A12 a01 weak** — her face drifted. a02 is the cleaner two-shot.
- **S-B02 a01** — came back wrapped in a decorative film/polaroid border. Repaired for free with
  `crop=912:1808:120:120` rather than re-rolling; border measured at ~110 px by edge sampling.
- **S-B01** — a02 chosen over a01: it frames him *inside* the red gate, which is the stronger image.
- **S-A07** — a02 chosen: the prayer beads hang loose instead of being bunched in the fist.

Measured first-attempt yield on Element frames: **~71%** (10/14). Budget two attempts per
keyframe; the plan's assumption of 2 attempts was right.
