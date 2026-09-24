#!/usr/bin/env python3
"""Score identity consistency across the delivered Higgsfield master.

This establishes THE BAR TO BEAT. The master was itself generated, so it drifts too;
the local rebuild's target is "no worse than this", not perfection.

Adapted from specific-tasks' calibrated face_consistency.py. Same cv2 5.0.0, same
YuNet + SFace ONNX, so numbers are directly comparable between the two machines.

Calibration measured on the target box:
    different people                     0.139, 0.201
    same character, independent stills   0.652 - 0.864
    same character, near-identical       0.980 - 0.994
    self vs self                         1.000
=> FLOOR 0.17, CEILING 0.99.  drift_score = (measured - 0.17) / (0.99 - 0.17)

SFace's published 0.363 same/different threshold is USELESS on generated faces --
six visibly different generated characters all scored 0.765-0.956 against each other.
Never report raw cosines against 0.363.
"""
import cv2, numpy as np, sys, os, glob, itertools, json

HERE = os.path.dirname(os.path.abspath(__file__))
DET = os.environ.get("YUNET", os.path.join(HERE, "yunet.onnx"))
REC = os.environ.get("SFACE", os.path.join(HERE, "sface.onnx"))

FLOOR, CEILING = 0.17, 0.99


def drift(c):
    return (c - FLOOR) / (CEILING - FLOOR)


def best_face(img, det, min_conf=0.55):
    """specific-tasks' two-window search: full frame, then top 60%.

    On tall 9:16 frames a single full-frame pass misses faces; the upper crop
    recovers a lot of them. Returns the highest-confidence candidate.
    """
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
        return None, None
    conf, tag, g = max(cands, key=lambda c: c[0])
    return g, f"{tag}/{conf:.2f}"


def main(argv):
    frames_dir = argv[0] if argv else os.path.join(HERE, "master_frames")
    crops_dir = os.path.join(HERE, "master_crops")
    os.makedirs(crops_dir, exist_ok=True)

    det = cv2.FaceDetectorYN.create(DET, "", (320, 320), score_threshold=0.5)
    rec = cv2.FaceRecognizerSF.create(REC, "")

    paths = []
    for e in ("*.png", "*.jpg"):
        paths += sorted(glob.glob(os.path.join(frames_dir, e)))
    if not paths:
        sys.exit(f"no frames in {frames_dir}")

    feats, names, no_face = [], [], []
    for p in paths:
        img = cv2.imread(p)
        if img is None:
            continue
        box, how = best_face(img, det)
        base = os.path.splitext(os.path.basename(p))[0]
        if box is None:
            no_face.append(base)
            continue
        aligned = rec.alignCrop(img, box)
        cv2.imwrite(os.path.join(crops_dir, base + ".png"), aligned)
        feats.append(rec.feature(aligned))
        names.append(base)

    n = len(feats)
    print(f"frames scanned : {len(paths)}")
    print(f"faces detected : {n}")
    print(f"no face        : {len(no_face)}  ({100*len(no_face)/max(1,len(paths)):.0f}% -- NOT a drift result, never averaged in as zero)")
    if no_face:
        print("  missed: " + ", ".join(no_face[:24]) + (" ..." if len(no_face) > 24 else ""))
    if n < 2:
        sys.exit("\nneed >= 2 detected faces")

    M = np.eye(n)
    for i, j in itertools.combinations(range(n), 2):
        M[i, j] = M[j, i] = rec.match(feats[i], feats[j], cv2.FaceRecognizerSF_FR_COSINE)

    off = M[np.triu_indices(n, 1)]
    print(f"\nALL PAIRS (mixed cast -- expect low, this is not the headline)")
    print(f"  pairs={len(off)}  mean={off.mean():.3f}  min={off.min():.3f}  max={off.max():.3f}")

    # Agglomerative-ish clustering on cosine, to separate the leads from each other.
    # Threshold chosen well ABOVE the published 0.363, which is useless on generated faces.
    THRESH = 0.55
    unassigned = set(range(n))
    clusters = []
    while unassigned:
        seed = max(unassigned, key=lambda i: sum(1 for j in unassigned if j != i and M[i, j] >= THRESH))
        grp = {seed}
        changed = True
        while changed:
            changed = False
            for j in list(unassigned - grp):
                if np.mean([M[j, k] for k in grp]) >= THRESH:
                    grp.add(j)
                    changed = True
        clusters.append(sorted(grp))
        unassigned -= grp

    clusters.sort(key=len, reverse=True)
    print(f"\nCLUSTERS at cosine >= {THRESH} (candidate distinct identities): {len(clusters)}")
    out = {"floor": FLOOR, "ceiling": CEILING, "threshold": THRESH,
           "frames_scanned": len(paths), "faces_detected": n, "no_face": no_face,
           "clusters": []}
    for ci, grp in enumerate(clusters):
        sub = [M[i, j] for i, j in itertools.combinations(grp, 2)]
        label = f"cluster_{ci}"
        rec_ = {"label": label, "size": len(grp),
                "members": [names[i] for i in grp]}
        print(f"\n  {label}: {len(grp)} faces")
        print(f"    {', '.join(names[i] for i in grp[:14])}{' ...' if len(grp) > 14 else ''}")
        if sub:
            a = np.array(sub)
            rec_.update(mean_cosine=round(float(a.mean()), 4),
                        min_cosine=round(float(a.min()), 4),
                        max_cosine=round(float(a.max()), 4),
                        mean_drift_score=round(float(drift(a.mean())), 4),
                        worst_drift_score=round(float(drift(a.min())), 4))
            print(f"    within-cluster cosine  mean={a.mean():.3f}  min={a.min():.3f}  max={a.max():.3f}")
            print(f"    NORMALISED DRIFT SCORE mean={drift(a.mean()):.3f}  worst={drift(a.min()):.3f}   <-- THE BAR")
        else:
            print("    singleton -- no within-cluster pairs")
        out["clusters"].append(rec_)

    with open(os.path.join(HERE, "master_identity_bar.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nwrote {os.path.join(HERE, 'master_identity_bar.json')}")
    print(f"aligned crops in {crops_dir} -- LOOK at them before trusting any cluster")


if __name__ == "__main__":
    main(sys.argv[1:])
