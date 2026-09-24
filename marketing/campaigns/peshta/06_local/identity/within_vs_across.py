#!/usr/bin/env python3
"""Within-shot noise floor vs across-cut drift, on the delivered master.

WHY THIS REPLACES THE EARLIER NUMBER
The first pass formed clusters by thresholding cosine >= 0.55 and then reported the
mean cosine WITHIN those clusters. That is circular: any set built by "keep pairs above
0.55" has a within-set mean just above 0.55, almost regardless of the footage. The
reported 0.592 largely measured the threshold, not the film.

The defensible split, which requires no chosen threshold:
  WITHIN-SHOT pairs  -- same person guaranteed, no generative process ran between them.
                        Their spread is the METRIC'S NOISE FLOOR on this footage: how
                        much cosine moves from pose, lighting, motion blur and
                        compression alone, with identity held fixed.
  ACROSS-CUT pairs   -- the actual question, but contaminated by genuinely different
                        people (this is an ensemble piece). So we do NOT take its mean;
                        we seed on one identity and look at the distribution.

Credit: the circularity and this fix were identified by specific-tasks.
"""
import cv2, numpy as np, os, glob, itertools, json, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER = "/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/final_polat_peshta_reel.mp4"
FLOOR, CEILING = 0.17, 0.99
drift = lambda c: (c - FLOOR) / (CEILING - FLOOR)

sys.path.insert(0, HERE)
from score_master import best_face  # reuse the identical two-window detector


def shot_bounds(cuts_path):
    cuts = [float(x) for x in open(cuts_path) if x.strip()]
    return [0.0] + cuts + [43.0]


def sample(t0, t1, fps, outdir, tag):
    os.makedirs(outdir, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
                    "-i", MASTER, "-vf", f"fps={fps}", "-frame_pts", "0",
                    os.path.join(outdir, f"{tag}_%03d.png"), "-y"], check=True)
    return sorted(glob.glob(os.path.join(outdir, f"{tag}_*.png")))


def feats_for(paths, det, rec):
    out = []
    for p in paths:
        img = cv2.imread(p)
        if img is None:
            continue
        box, _ = best_face(img, det)
        if box is None:
            continue
        out.append((os.path.basename(p), rec.feature(rec.alignCrop(img, box))))
    return out


def main():
    det = cv2.FaceDetectorYN.create(os.path.join(HERE, "yunet.onnx"), "", (320, 320), score_threshold=0.5)
    rec = cv2.FaceRecognizerSF.create(os.path.join(HERE, "sface.onnx"), "")

    b = shot_bounds(os.path.join(HERE, "cuts.txt"))
    shots = [(b[i], b[i + 1], b[i + 1] - b[i]) for i in range(len(b) - 1)]
    shots_long = sorted([s for s in shots if s[2] >= 1.0], key=lambda s: -s[2])
    print(f"shots from scdet: {len(shots)}   >=1.0s: {len(shots_long)}")
    print("NOTE: the 27-36s canyon stretch produced many detections 0.03-0.1s apart.")
    print("      Those are almost certainly fast motion, not real cuts. Treated as unusable for")
    print("      the within-shot floor (too short to sample), which biases the floor toward the")
    print("      calmer studio material. Stated, not hidden.\n")

    # ---- WITHIN-SHOT NOISE FLOOR -------------------------------------------------
    within = []
    used = 0
    for k, (t0, t1, d) in enumerate(shots_long[:10]):
        ps = sample(t0 + 0.05, t1 - 0.05, 10, os.path.join(HERE, "within_frames"), f"s{k:02d}")
        fs = feats_for(ps, det, rec)
        if len(fs) < 2:
            continue
        used += 1
        vals = [rec.match(fs[i][1], fs[j][1], cv2.FaceRecognizerSF_FR_COSINE)
                for i, j in itertools.combinations(range(len(fs)), 2)]
        within += vals
        print(f"  shot {k:02d}  {t0:6.2f}-{t1:6.2f} ({d:4.2f}s)  faces={len(fs):2d}  "
              f"pairs={len(vals):3d}  mean={np.mean(vals):.3f} min={np.min(vals):.3f}")

    within = np.array(within)
    print(f"\nWITHIN-SHOT NOISE FLOOR  ({used} shots, {len(within)} pairs)")
    print(f"  mean={within.mean():.3f}  median={np.median(within):.3f}  "
          f"p10={np.percentile(within,10):.3f}  min={within.min():.3f}")
    print(f"  => identity held FIXED, cosine still varies this much from pose/light/blur alone.")

    # ---- ACROSS-CUT, SEEDED ON ONE IDENTITY --------------------------------------
    # Seed = the longest shot, whose frames are the same person by construction.
    t0, t1, d = shots_long[0]
    seed_paths = sample(t0 + 0.05, t1 - 0.05, 10, os.path.join(HERE, "seed_frames"), "seed")
    seed = feats_for(seed_paths, det, rec)
    print(f"\nSEED identity = longest shot {t0:.2f}-{t1:.2f}s ({d:.2f}s), {len(seed)} faces")

    all_paths = sorted(glob.glob(os.path.join(HERE, "master_frames", "*.png")))
    allf = feats_for(all_paths, det, rec)
    rows = []
    for name, f in allf:
        t = float(name[1:7])
        best = max(rec.match(f, sf, cv2.FaceRecognizerSF_FR_COSINE) for _, sf in seed)
        in_seed_shot = t0 <= t <= t1
        rows.append((t, best, in_seed_shot))

    out_shot = [r for r in rows if not r[2]]
    vals = np.array([r[1] for r in out_shot])
    print(f"every sampled face scored against the seed ({len(out_shot)} outside the seed shot):")
    print(f"  mean={vals.mean():.3f}  median={np.median(vals):.3f}  max={vals.max():.3f}  min={vals.min():.3f}")

    floor_p10 = np.percentile(within, 10)
    above = vals[vals >= floor_p10]
    print(f"\n  frames scoring at/above the within-shot p10 floor ({floor_p10:.3f}): "
          f"{len(above)}/{len(out_shot)} ({100*len(above)/len(out_shot):.0f}%)")
    print(f"  => the other {100-100*len(above)/len(out_shot):.0f}% are either a DIFFERENT person")
    print(f"     (corps, second lead, veiled figure) or the same lead drifted below the floor.")
    print(f"     This metric alone cannot tell those apart. That ambiguity is the honest limit here.")

    print("\nper-frame score against seed (t, cosine, drift_score):")
    for t, v, ins in rows:
        mark = "SEED" if ins else ("  ok" if v >= floor_p10 else "  --")
        print(f"  {mark} t={t:6.2f}  cos={v:.3f}  drift={drift(v):+.3f}")

    json.dump({
        "method": "within-shot noise floor vs seeded across-cut; supersedes the circular 0.592",
        "within_shot": {"pairs": int(len(within)), "mean": round(float(within.mean()), 4),
                        "median": round(float(np.median(within)), 4),
                        "p10": round(float(floor_p10), 4), "min": round(float(within.min()), 4)},
        "seed_shot": {"start_s": t0, "end_s": t1, "faces": len(seed)},
        "across_cut_vs_seed": {"n": int(len(out_shot)), "mean": round(float(vals.mean()), 4),
                               "median": round(float(np.median(vals)), 4),
                               "frac_above_floor": round(float(len(above) / len(out_shot)), 4)},
        "caveat": "across-cut population mixes the seed lead with other cast; this metric cannot separate drift from a genuinely different person.",
    }, open(os.path.join(HERE, "within_vs_across.json"), "w"), indent=1)
    print(f"\nwrote within_vs_across.json")


if __name__ == "__main__":
    main()
