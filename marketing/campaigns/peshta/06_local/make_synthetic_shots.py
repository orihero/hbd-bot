#!/usr/bin/env python3
"""
marketing/campaigns/peshta/06_local/make_synthetic_shots.py
=============================================
Generate a throwaway set of synthetic per-shot clips so assemble_local.py can be
exercised end to end without waiting on a single local render.

Deliberately nasty: the clips come out at mixed resolutions (portrait, square-ish
and one landscape), mixed frame rates (24 / 25 / 30 / 60), and deliberately wrong
durations relative to their shot_bible window, so every conform branch gets hit.

Writes ONLY into the directory you pass with --out-dir. Point it at a scratchpad,
never at the repository.

    ./make_synthetic_shots.py --out-dir /tmp/local_synth          # all shots LONG
    ./make_synthetic_shots.py --out-dir /tmp/local_synth --short 4,9
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SHOT_BIBLE = SCRIPT_DIR / "shot_bible_v2.json"

# (width, height, source_fps, lavfi source) cycled across the shots
PROFILES = [
    (1080, 1920, 30, "testsrc2"),
    (720, 1280, 24, "smptebars"),
    (1080, 1920, 25, "testsrc2"),
    (1280, 720, 30, "smptebars"),      # landscape: exercises the pad/crop branch
    (864, 1536, 60, "testsrc2"),
    (1080, 1920, 30, "smptebars"),
    (540, 960, 24, "testsrc2"),
    (1080, 1920, 30, "testsrc2"),
    (1088, 1920, 25, "smptebars"),     # off-by-8 width: exercises the scaler
    (1080, 1920, 30, "testsrc2"),
    (768, 1344, 30, "smptebars"),
]

# Seconds added on top of each window, so most shots arrive LONG the way a real
# image2video model does (fixed 5 s / 81-frame outputs, not 2.256 s ones).
SURPLUS = [0.44, 0.08, 1.02, 0.05, 0.50, 0.30, 2.00, 0.20, 0.60, 0.90, 0.40]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--shot-bible", type=Path, default=DEFAULT_SHOT_BIBLE)
    ap.add_argument("--short", default="",
                    help="Comma-separated shot ordinals to render DELIBERATELY SHORT "
                         "(half their window), e.g. '4,9'.")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args(argv)

    bible = json.loads(args.shot_bible.read_text())
    fps = float((bible.get("master_timeline") or {}).get("fps") or 30.0)
    shots = bible["shots"]
    short = {int(x) for x in args.short.split(",") if x.strip()}

    out_dir = args.out_dir.resolve()
    if out_dir.is_relative_to(SCRIPT_DIR.parent.parent):
        print(f"[-] refusing to write synthetic clips inside the repository: {out_dir}",
              file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, s in enumerate(shots, start=1):
        frames = int(s.get("frames") or round(float(s["dur_s"]) * fps))
        window = frames / fps
        w, h, src_fps, src = PROFILES[(i - 1) % len(PROFILES)]
        if i in short:
            dur = round(window * 0.5, 3)
            tag = "SHORT"
        else:
            dur = round(window + SURPLUS[(i - 1) % len(SURPLUS)], 3)
            tag = "long" if dur > window + 1e-6 else "exact"
        path = out_dir / f"shot_{i:02d}.mp4"
        lavfi = f"{src}=size={w}x{h}:rate={src_fps}:duration={dur}"
        cmd = [
            args.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", lavfi,
            "-vf", f"hue=h={(i * 31) % 360}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
            "-pix_fmt", "yuv420p", "-an",
            str(path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[-] failed to build {path.name}:\n{res.stderr.strip()}", file=sys.stderr)
            return 1
        print(f"    {path.name}  {w}x{h}@{src_fps}  {dur:.3f}s  "
              f"(window {window:.3f}s / {frames}f)  [{tag}]")

    print(f"[*] {len(shots)} synthetic clips in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
