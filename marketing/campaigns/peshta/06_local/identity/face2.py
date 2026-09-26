#!/usr/bin/env python3
"""v2 face detection: LARGEST face, not most-confident, plus a face count.

The v1 bug: best_face returned the highest-confidence face. In a multi-person frame
that is not a stable subject -- the detector picks the lead on one frame and a corps
dancer on the next, so a "within-shot pair" becomes two different people and the score
collapses. That is what produced a 0.472 "noise floor" spanning -0.205 to 0.99.

Fix (from specific-tasks):
  1. Rank by BOX AREA. The lead is nearly always framed largest, and area is far more
     stable frame-to-frame than confidence. Confidence ranking is exactly what flips.
  2. Deduplicate the full-frame and top-crop search windows by IoU > 0.4, so one face
     found twice is not counted as two.
  3. Return the face COUNT, and make multi-face frames impossible to miss.

FALSIFIABLE PREDICTION this script exists to test:
  the shots that scored LOW in v1 should now report high multi-face rates, and the
  shots that scored HIGH should be mostly single-face. If that holds, the low scores
  were subject-switching and not identity drift -- confirmed mechanically rather than
  inferred from bimodality.
"""
import cv2, numpy as np, os, glob, itertools, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER = "/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/final_polat_peshta_reel.mp4"


def best_face(img, det, min_conf=0.55):
    H, W = img.shape[:2]
    cands = []
    for tag, sub, (ox, oy) in (("full", img, (0, 0)), ("top", img[: int(H * 0.60)], (0, 0))):
        h, w = sub.shape[:2]
        s = min(max(1.0, 640.0 / max(1, min(h, w))), 3.0)
        r = cv2.resize(sub, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC) if s > 1.0 else sub
        rh, rw = r.shape[:2]
        det.setInputSize((rw, rh))
        n, faces = det.detect(r)
        if faces is None:
            continue
        for f in faces:
            if f[-1] < min_conf:
                continue
            g = f.copy()
            g[:14] = g[:14] / s
            g[0] += ox
            g[1] += oy
            for k in range(4, 14, 2):
                g[k] += ox
                g[k + 1] += oy
            cands.append((float(f[-1]), tag, g))
    if not cands:
        return None, None, 0
    kept = []
    for conf, tag, g in sorted(cands, key=lambda c: -c[0]):
        x, y, w_, h_ = g[0], g[1], g[2], g[3]
        dup = False
        for _, _, k in kept:
            kx, ky, kw, kh = k[0], k[1], k[2], k[3]
            ix = max(0, min(x + w_, kx + kw) - max(x, kx))
            iy = max(0, min(y + h_, ky + kh) - max(y, ky))
            inter = ix * iy
            union = w_ * h_ + kw * kh - inter
            if union > 0 and inter / union > 0.4:
                dup = True
                break
        if not dup:
            kept.append((conf, tag, g))
    conf, tag, g = max(kept, key=lambda c: c[2][2] * c[2][3])   # LARGEST, not most confident
    return g, f"{tag}/{conf:.2f}", len(kept)


def main():
    det = cv2.FaceDetectorYN.create(os.path.join(HERE, "yunet.onnx"), "", (320, 320), score_threshold=0.5)
    rec = cv2.FaceRecognizerSF.create(os.path.join(HERE, "sface.onnx"), "")

    cuts = [float(x) for x in open(os.path.join(HERE, "cuts.txt")) if x.strip()]
    b = [0.0] + cuts + [43.0]
    shots = sorted([(b[i], b[i + 1], b[i + 1] - b[i]) for i in range(len(b) - 1)
                    if b[i + 1] - b[i] >= 1.0], key=lambda s: -s[2])[:10]

    v1 = {  # v1 within-shot means, keyed by rounded start time, for the comparison
        5.27: 0.346, 2.30: 0.296, 17.27: 0.382, 37.83: 0.783, 33.43: 0.566,
        41.30: 0.768, 28.57: 0.472, 0.00: 0.579, 10.47: 0.883, 15.80: 0.681,
    }

    print(f"{'shot window':>16} {'dur':>5} {'faces':>6} {'multi%':>7} {'v1 mean':>8} {'v2 mean':>8} {'delta':>7}")
    print("-" * 68)
    rows = []
    for (t0, t1, d) in shots:
        outdir = os.path.join(HERE, "v2_frames")
        os.makedirs(outdir, exist_ok=True)
        tag = f"s{t0:07.2f}".replace(".", "_")
        for old in glob.glob(os.path.join(outdir, f"{tag}_*.png")):
            os.remove(old)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t0+0.05:.3f}", "-to", f"{t1-0.05:.3f}",
                        "-i", MASTER, "-vf", "fps=10", os.path.join(outdir, f"{tag}_%03d.png"), "-y"],
                       check=True)
        ps = sorted(glob.glob(os.path.join(outdir, f"{tag}_*.png")))
        feats, nmulti = [], 0
        for p in ps:
            img = cv2.imread(p)
            if img is None:
                continue
            box, how, nf = best_face(img, det)
            if box is None:
                continue
            feats.append(rec.feature(rec.alignCrop(img, box)))
            if nf > 1:
                nmulti += 1
        if len(feats) < 2:
            continue
        vals = [rec.match(feats[i], feats[j], cv2.FaceRecognizerSF_FR_COSINE)
                for i, j in itertools.combinations(range(len(feats)), 2)]
        m = float(np.mean(vals))
        key = round(t0, 2)
        old = v1.get(key, v1.get(round(t0, 1), None))
        multi_pct = 100.0 * nmulti / len(feats)
        rows.append({"start_s": round(t0, 2), "end_s": round(t1, 2), "faces": len(feats),
                     "multi_face_pct": round(multi_pct, 1), "v1_mean": old,
                     "v2_mean": round(m, 4),
                     "delta": (round(m - old, 4) if old is not None else None)})
        ds = f"{m-old:+.3f}" if old is not None else "   n/a"
        os_ = f"{old:.3f}" if old is not None else "  n/a"
        print(f"{t0:7.2f}-{t1:6.2f} {d:5.2f} {len(feats):6d} {multi_pct:6.0f}% {os_:>8} {m:8.3f} {ds:>7}")

    print("\nTHE TEST: do the shots that scored LOW in v1 show HIGH multi-face rates?")
    lo = [r for r in rows if r["v1_mean"] is not None and r["v1_mean"] < 0.50]
    hi = [r for r in rows if r["v1_mean"] is not None and r["v1_mean"] >= 0.70]
    if lo:
        print(f"  v1-LOW  shots (mean<0.50), n={len(lo)}:  mean multi-face = {np.mean([r['multi_face_pct'] for r in lo]):.0f}%")
    if hi:
        print(f"  v1-HIGH shots (mean>=0.70), n={len(hi)}: mean multi-face = {np.mean([r['multi_face_pct'] for r in hi]):.0f}%")
    if lo and hi:
        gap = np.mean([r['multi_face_pct'] for r in lo]) - np.mean([r['multi_face_pct'] for r in hi])
        print(f"  gap = {gap:+.0f} percentage points")
        print("  => DIAGNOSIS CONFIRMED" if gap > 20 else
              "  => NOT CONFIRMED -- low scores are not explained by multi-face frames;\n"
              "     something else is driving them and the metric needs more work.")

    single = [r for r in rows if r["multi_face_pct"] < 20]
    if single:
        vals = [r["v2_mean"] for r in single]
        print(f"\nSINGLE-SUBJECT NOISE FLOOR ({len(single)} shots with <20% multi-face frames)")
        print(f"  v2 means: {', '.join(f'{v:.3f}' for v in sorted(vals))}")
        print(f"  mean {np.mean(vals):.3f}   min {min(vals):.3f}")
        print("  => identity fixed by construction; only pose/light/blur/compression vary.")
        print("     THIS is the threshold for our experiment: keyframes scoring below it show")
        print("     variation larger than pose and lighting alone can explain.")
        print("     It is a NOISE FLOOR, not Higgsfield's score -- the master's within-shot")
        print("     frames are real continuous footage where identity is fixed by physics.")

    json.dump({"shots": rows,
               "single_subject_floor": {
                   "shots": len(single),
                   "means": [r["v2_mean"] for r in single],
                   "mean": round(float(np.mean([r["v2_mean"] for r in single])), 4) if single else None,
                   "min": round(float(min(r["v2_mean"] for r in single)), 4) if single else None,
               }},
              open(os.path.join(HERE, "face2_result.json"), "w"), indent=1)
    print(f"\nwrote face2_result.json")


if __name__ == "__main__":
    main()
