#!/usr/bin/env python3
"""
marketing/campaigns/peshta/06_local/assemble_local.py
=======================================
LOCAL conform + assembly harness for the "Peshta" 43s vertical reel rebuild.

This is the *local-models* counterpart to the Higgsfield-era assembler
(``marketing/campaigns/peshta/assemble_polat_peshta.py``). The conform / CFR / faststart /
verification logic below is lifted from that proven script rather than
reinvented; the differences are:

  * the local pipeline renders ONE clip PER SHOT (still keyframe -> image2video),
    so this harness is shot-addressed (``shot_01.mp4`` .. ``shot_NN.mp4``) instead
    of "whatever mp4s are in the folder, natural-sorted";
  * each shot is conformed to its EXACT frame window read from
    ``06_local/shot_bible_v2.json`` (SHOT_BIBLE master_timeline + shots[]), not to a
    hard-coded duration list;
  * a short render is NOT silently padded. ``--short-policy`` must say so.

Authority for the window table is ``06_local/shot_bible_v2.json``. Note that the
per-shot ``dur_s`` values there are NOT integer multiples of 1/30 s (e.g. shot 01
is 2.256 s = 67.68 frames), while the per-shot ``frames`` values sum to exactly
1290. This harness therefore treats ``frames`` as authoritative and derives the
window duration as ``frames / fps``; the two agree to well under one frame per
shot and to exactly 43.000 s in total.

Deliverable spec (same as the Higgsfield master, so the A/B is like-for-like):
  1080x1920, SAR 1:1, 30 fps CFR, yuv420p, H.264 High, no rotation metadata,
  exactly 1290 frames / 43.000 s, AAC-LC 48 kHz stereo, faststart.

Pure Python 3 stdlib + ffmpeg/ffprobe. No pip dependencies. Runs on macOS and
Linux identically.

Typical use
-----------
    # what would happen, without rendering anything
    ./assemble_local.py --input-dir /renders/local_v1 --dry-run

    # real build; refuse to proceed if any shot came back short
    ./assemble_local.py --input-dir /renders/local_v1 -o local_v1_master.mp4

    # accept short renders by freezing their last frame, and say so in the ledger
    ./assemble_local.py --input-dir /renders/local_v1 -o out.mp4 --short-policy hold
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent          # .../promo_peshta/06_local
PROMO_DIR = SCRIPT_DIR.parent                          # .../promo_peshta
REPO_ROOT = PROMO_DIR.parent                           # repo root

DEFAULT_SHOT_BIBLE = SCRIPT_DIR / "shot_bible_v2.json"
DEFAULT_AUDIO = PROMO_DIR / "audio" / "Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3"
DEFAULT_OUTPUT = SCRIPT_DIR / "local_master.mp4"
DEFAULT_PATTERN = "shot_{n02}.mp4"

# Identical grade to the Higgsfield master (assemble_polat_peshta.py
# TURKISH_MAFIA_NOIR_FILTER). OFF by default here: local models are being judged
# on what they produce, and a grade on top muddies the A/B. Turn it on only to
# compare graded-against-graded.
TURKISH_MAFIA_NOIR_FILTER = (
    "eq=contrast=1.10:brightness=-0.02:saturation=0.94,"
    "colorbalance=bs=0.06:bm=-0.02:bh=-0.04:rm=0.02"
)

# Extra clone frames appended in the trim path purely to absorb decoder/resample
# rounding at the tail. It can never mask a short render: a shot only reaches the
# trim path after it has been proven to hold >= its target frame count, and
# `-frames:v N` truncates back to exactly N.
ROUNDING_GUARD_S = 0.5

VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")


# =============================================================================
# ffprobe / container helpers
#
# probe_media() and check_faststart_atoms() are carried over verbatim in
# behaviour from marketing/campaigns/peshta/assemble_polat_peshta.py so that both assemblers
# measure the deliverable the same way. Vendored rather than imported so this
# file can be scp'd to the render box on its own.
# =============================================================================

def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe_media(file_path: Path | str, ffprobe_bin: str = "ffprobe") -> dict[str, Any]:
    """Probe video/audio metadata via ffprobe, returning the parsed JSON."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Target media file not found: {path}")

    cmd = [
        ffprobe_bin, "-v", "error",
        "-show_entries",
        (
            "stream=index,codec_type,codec_name,profile,width,height,"
            "sample_aspect_ratio,display_aspect_ratio,r_frame_rate,avg_frame_rate,"
            "time_base,pix_fmt,nb_frames,duration,sample_rate,channels,channel_layout"
        ),
        "-show_entries", "format=duration,size,bit_rate,format_name",
        "-of", "json",
        str(path),
    ]
    res = run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}:\n{res.stderr.strip()}")
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse ffprobe JSON for {path}: {e}") from e


def probe_rotation(file_path: Path | str, ffprobe_bin: str = "ffprobe") -> float | None:
    """Return the Display Matrix rotation in degrees, or None when absent."""
    cmd = [
        ffprobe_bin, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream_side_data=rotation",
        "-of", "json", str(Path(file_path).resolve()),
    ]
    res = run(cmd)
    if res.returncode != 0:
        return None
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return None
    for stream in data.get("streams", []):
        for sd in stream.get("side_data_list", []):
            if "rotation" in sd:
                return float(sd["rotation"])
    return None


def count_frames(file_path: Path | str, ffprobe_bin: str = "ffprobe") -> int:
    """Exact decoded frame count of stream v:0."""
    cmd = [
        ffprobe_bin, "-v", "error", "-select_streams", "v:0",
        "-count_frames", "-show_entries", "stream=nb_read_frames",
        "-of", "json", str(Path(file_path).resolve()),
    ]
    res = run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe frame count failed for {file_path}:\n{res.stderr.strip()}")
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError(f"No video stream in {file_path}")
    return int(streams[0].get("nb_read_frames") or 0)


def check_faststart_atoms(file_path: Path | str) -> tuple[bool, str, dict[str, Any]]:
    """
    Verify the 'moov' atom sits before 'mdat' and inside the first 4096 bytes.
    Carried over from assemble_polat_peshta.check_faststart_atoms().
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        return False, f"File does not exist: {path}", {}

    file_size = path.stat().st_size
    with open(path, "rb") as f:
        first_4k = f.read(4096)
        moov_in_4k = first_4k.find(b"moov")
        mdat_in_4k = first_4k.find(b"mdat")

        f.seek(0)
        boxes: list[dict[str, Any]] = []
        pos = 0
        while pos < file_size:
            f.seek(pos)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            box_size = int.from_bytes(hdr[0:4], "big")
            box_type = hdr[4:8].decode("latin1", errors="ignore")

            actual_size = box_size
            if box_size == 1:
                ext_hdr = f.read(8)
                if len(ext_hdr) == 8:
                    actual_size = int.from_bytes(ext_hdr, "big")
            elif box_size == 0:
                actual_size = file_size - pos

            boxes.append({"type": box_type, "offset": pos, "size": actual_size})
            if box_size == 0 or actual_size <= 0:
                break
            pos += actual_size

    box_types = [b["type"] for b in boxes]
    moov_idx = box_types.index("moov") if "moov" in box_types else -1
    mdat_idx = box_types.index("mdat") if "mdat" in box_types else -1

    details = {
        "moov_in_first_4096": moov_in_4k != -1,
        "moov_byte_offset_raw": moov_in_4k,
        "mdat_byte_offset_raw": mdat_in_4k,
        "top_boxes": boxes[:6],
    }

    if moov_idx == -1:
        return False, "Container missing 'moov' atom entirely", details

    moov_offset = boxes[moov_idx]["offset"]
    if moov_offset >= 4096 and moov_in_4k == -1:
        return False, f"'moov' atom located at byte {moov_offset} (expected < 4096)", details
    if mdat_idx != -1 and moov_idx > mdat_idx:
        mdat_offset = boxes[mdat_idx]["offset"]
        return False, f"'moov' (offset {moov_offset}) appears AFTER 'mdat' (offset {mdat_offset})", details

    return True, f"'moov' atom at offset {moov_offset} (<4096) preceding 'mdat'", details


# =============================================================================
# Shot bible
# =============================================================================

class Window:
    """One shot's slot on the master timeline."""

    def __init__(self, shot_id: str, index: int, start_s: float, frames: int,
                 fps: float, declared_dur_s: float | None):
        self.id = shot_id
        self.index = index            # 1-based ordinal
        self.start_s = start_s
        self.frames = frames
        self.fps = fps
        self.declared_dur_s = declared_dur_s

    @property
    def dur_s(self) -> float:
        return self.frames / self.fps

    @property
    def end_s(self) -> float:
        return self.start_s + self.dur_s


def load_windows(bible_path: Path) -> tuple[list[Window], dict[str, Any]]:
    if not bible_path.is_file():
        raise FileNotFoundError(f"shot bible not found: {bible_path}")
    bible = json.loads(bible_path.read_text())

    mt = bible.get("master_timeline") or {}
    fps = float(mt.get("fps") or 30.0)
    shots = bible.get("shots") or []
    if not shots:
        raise ValueError(f"{bible_path} has no shots[]")

    windows: list[Window] = []
    cursor = 0
    for i, s in enumerate(shots, start=1):
        frames = s.get("frames")
        if frames is None:
            dur = s.get("dur_s")
            if dur is None:
                raise ValueError(f"shot {s.get('id', i)} has neither 'frames' nor 'dur_s'")
            frames = int(round(float(dur) * fps))
        frames = int(frames)
        if frames <= 0:
            raise ValueError(f"shot {s.get('id', i)} has a non-positive frame count: {frames}")
        windows.append(Window(
            shot_id=str(s.get("id") or f"{i:02d}"),
            index=i,
            start_s=cursor / fps,
            frames=frames,
            fps=fps,
            declared_dur_s=(float(s["dur_s"]) if s.get("dur_s") is not None else None),
        ))
        cursor += frames

    total_frames = cursor
    meta = {
        "fps": fps,
        "total_frames": total_frames,
        "total_duration_s": total_frames / fps,
        "declared_frame_count": mt.get("frame_count"),
        "declared_duration_s": mt.get("duration_s"),
        "resolution": mt.get("resolution") or "1080x1920",
    }
    if mt.get("frame_count") is not None and int(mt["frame_count"]) != total_frames:
        raise ValueError(
            f"shot bible is internally inconsistent: master_timeline.frame_count="
            f"{mt['frame_count']} but shots[].frames sum to {total_frames}"
        )
    return windows, meta


# =============================================================================
# Input discovery
# =============================================================================

def natural_key(name: str) -> list[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def resolve_sources(input_dir: Path, pattern: str, count: int) -> tuple[list[Path | None], list[str]]:
    """
    Map each shot ordinal 1..count to a source file.

    `pattern` is either a format template containing '{n}' / '{n02}'
    (e.g. 'shot_{n02}.mp4' -> shot_01.mp4) or a plain glob (e.g. 'shot_*.mp4'),
    in which case matches are natural-sorted and assigned positionally.

    Returns (sources, missing_descriptions). A slot with no file is None.
    """
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    sources: list[Path | None] = []
    missing: list[str] = []

    if "{" in pattern:
        for n in range(1, count + 1):
            name = pattern.format(n=n, n02=f"{n:02d}", n03=f"{n:03d}")
            cand = input_dir / name
            if cand.is_file():
                sources.append(cand)
            else:
                sources.append(None)
                missing.append(f"shot {n:02d}: expected {cand}")
    else:
        found = sorted(
            (p for p in input_dir.glob(pattern)
             if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES and not p.name.startswith(".")),
            key=lambda p: natural_key(p.name),
        )
        for n in range(1, count + 1):
            if n - 1 < len(found):
                sources.append(found[n - 1])
            else:
                sources.append(None)
                missing.append(f"shot {n:02d}: glob '{pattern}' in {input_dir} yielded only {len(found)} clip(s)")
        if len(found) > count:
            missing.append(
                f"glob '{pattern}' matched {len(found)} clips but the shot bible declares {count} "
                f"windows; extras ignored: {[p.name for p in found[count:]]}"
            )

    return sources, missing


# =============================================================================
# Conform planning
# =============================================================================

class Plan:
    """The decision made for one shot, before any rendering happens."""

    def __init__(self, window: Window):
        self.w = window
        self.source: Path | None = None
        self.src_dur_s = 0.0
        self.src_w = 0
        self.src_h = 0
        self.src_fps = 0.0
        self.src_frames_native: int | None = None
        self.avail_frames_30 = 0
        self.classification = "MISSING"   # SHORT | EXACT | LONG | MISSING
        self.policy = "-"                 # trim-centre | trim-head | trim-tail | hold | stretch | FAIL
        self.trim_start_s = 0.0
        self.trim_end_s = 0.0
        self.stretch_factor = 1.0
        self.pad_s = 0.0
        self.delta_frames = 0
        self.result_frames: int | None = None
        self.conformed: Path | None = None
        self.error: str | None = None


def measure(plan: Plan, ffprobe_bin: str) -> None:
    meta = probe_media(plan.source, ffprobe_bin=ffprobe_bin)
    vstreams = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
    if not vstreams:
        raise RuntimeError(f"{plan.source} has no video stream")
    v = vstreams[0]
    plan.src_w = int(v.get("width") or 0)
    plan.src_h = int(v.get("height") or 0)

    r = str(v.get("r_frame_rate") or "0/1")
    try:
        num, den = r.split("/")
        plan.src_fps = float(num) / float(den) if float(den) else 0.0
    except Exception:
        plan.src_fps = 0.0

    dur = v.get("duration") or meta.get("format", {}).get("duration")
    plan.src_dur_s = float(dur) if dur not in (None, "N/A") else 0.0

    nbf = v.get("nb_frames")
    if nbf not in (None, "N/A"):
        plan.src_frames_native = int(nbf)

    if plan.src_dur_s <= 0.0 and plan.src_frames_native and plan.src_fps > 0:
        plan.src_dur_s = plan.src_frames_native / plan.src_fps
    if plan.src_dur_s <= 0.0:
        raise RuntimeError(f"Could not determine a duration for {plan.source}")

    # How many 30 fps frames this source can actually supply.
    plan.avail_frames_30 = int(math.floor(plan.src_dur_s * plan.w.fps + 1e-6))


def plan_shot(plan: Plan, short_policy: str, trim_anchor: str) -> None:
    target = plan.w.frames
    target_dur = plan.w.dur_s
    avail = plan.avail_frames_30
    plan.delta_frames = avail - target

    if avail >= target:
        plan.classification = "EXACT" if avail == target else "LONG"
        excess = max(0.0, plan.src_dur_s - target_dur)
        if trim_anchor == "head":
            start = 0.0
        elif trim_anchor == "tail":
            start = excess
        else:
            start = excess / 2.0
        # never start so late that the tail runs out
        start = max(0.0, min(start, plan.src_dur_s - target_dur))
        plan.trim_start_s = start
        plan.trim_end_s = start + target_dur
        plan.policy = f"trim-{trim_anchor}"
        plan.pad_s = ROUNDING_GUARD_S       # rounding absorber only; -frames:v truncates
        return

    # Short render.
    plan.classification = "SHORT"
    deficit_frames = target - avail
    if short_policy == "fail":
        plan.policy = "FAIL"
        plan.error = (
            f"render is {deficit_frames} frame(s) short of its {target}-frame window "
            f"({plan.src_dur_s:.3f}s supplied vs {target_dur:.3f}s needed)"
        )
        return
    if short_policy == "hold":
        plan.policy = "hold"
        plan.trim_start_s = 0.0
        plan.trim_end_s = plan.src_dur_s
        plan.pad_s = (deficit_frames / plan.w.fps) + ROUNDING_GUARD_S
        return
    if short_policy == "stretch":
        plan.policy = "stretch"
        plan.trim_start_s = 0.0
        plan.trim_end_s = plan.src_dur_s
        plan.stretch_factor = target_dur / plan.src_dur_s
        plan.pad_s = ROUNDING_GUARD_S
        return
    raise ValueError(f"unknown --short-policy: {short_policy}")


# =============================================================================
# Rendering
# =============================================================================

def build_shot_filter(plan: Plan, fit: str, color_grade: bool, width: int, height: int) -> str:
    parts: list[str] = []
    if plan.trim_start_s > 1e-6:
        parts.append(f"trim=start={plan.trim_start_s:.6f}")
    parts.append("setpts=PTS-STARTPTS")
    if abs(plan.stretch_factor - 1.0) > 1e-9:
        parts.append(f"setpts=PTS*{plan.stretch_factor:.9f}")
    if fit == "crop":
        parts.append(f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos")
        parts.append(f"crop={width}:{height}")
    else:
        parts.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos")
        parts.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    parts.append("setsar=1")
    parts.append(f"fps={plan.w.fps:g}")
    if plan.pad_s > 1e-6:
        parts.append(f"tpad=stop_mode=clone:stop_duration={plan.pad_s:.4f}")
    if color_grade:
        parts.append(TURKISH_MAFIA_NOIR_FILTER)
    parts.append("format=yuv420p")
    return ",".join(parts)


def render_shot(plan: Plan, work_dir: Path, fit: str, color_grade: bool,
                width: int, height: int, crf: int, preset: str,
                ffmpeg_bin: str, ffprobe_bin: str, verbose: bool) -> None:
    out = work_dir / f"conformed_{plan.w.index:02d}.mp4"
    vf = build_shot_filter(plan, fit, color_grade, width, height)
    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(plan.source),
        "-vf", vf,
        "-frames:v", str(plan.w.frames),
        "-an", "-sn", "-dn",
        "-map_metadata", "-1",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-r", f"{plan.w.fps:g}", "-fps_mode", "cfr",
        "-video_track_timescale", str(int(round(plan.w.fps * 1000))),
        # Without negative_cts_offsets the mp4 muxer writes a track duration one
        # B-frame reorder short (2.266000s instead of 2.266667s for a 68-frame
        # shot). The packets are right, but the declared durations then accumulate
        # across the concat and the master lands at 42.9987s instead of 43.000s.
        "-movflags", "+negative_cts_offsets",
        str(out),
    ]
    if verbose:
        print("    $ " + " ".join(cmd))
    res = run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"conform of shot {plan.w.id} failed:\n{res.stderr.strip()}")

    got = count_frames(out, ffprobe_bin=ffprobe_bin)
    plan.result_frames = got
    plan.conformed = out
    if got != plan.w.frames:
        raise RuntimeError(
            f"shot {plan.w.id} conformed to {got} frames, expected {plan.w.frames}. "
            f"Source={plan.source} policy={plan.policy}. This is a harness bug or a "
            f"source the decoder cannot seek; do not ship it."
        )


def concat_shots(plans: list[Plan], work_dir: Path, ffmpeg_bin: str) -> Path:
    listing = work_dir / "concat.txt"
    listing.write_text("".join(f"file '{p.conformed}'\n" for p in plans))
    out = work_dir / "concat.mp4"
    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", "-map_metadata", "-1",
        "-movflags", "+negative_cts_offsets",
        str(out),
    ]
    res = run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"concat failed:\n{res.stderr.strip()}")
    return out


def mux_audio(video: Path, audio: Path, output: Path, video_dur_s: float,
              audio_bitrate: str, ffmpeg_bin: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    # -t on the AUDIO INPUT, never -shortest: the video stream is authoritative
    # for the length of the deliverable. A longer music bed is cut to the picture;
    # a shorter one simply runs out and the picture continues.
    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video),
        "-t", f"{video_dur_s:.6f}", "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-profile:a", "aac_low",
        "-b:a", audio_bitrate, "-ar", "48000", "-ac", "2",
        "-map_metadata", "-1",
        "-movflags", "+faststart+negative_cts_offsets",
        str(output),
    ]
    res = run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"audio mux failed:\n{res.stderr.strip()}")


# =============================================================================
# Ledger
# =============================================================================

LEDGER_COLUMNS = [
    "shot_id", "ordinal", "source", "source_exists",
    "src_w", "src_h", "src_fps", "src_duration_s", "src_frames_native",
    "window_start_s", "window_end_s", "window_frames", "window_duration_s",
    "avail_frames_at_30", "delta_frames", "classification", "policy_applied",
    "trim_anchor", "in_s", "out_s", "stretch_factor", "pad_s",
    "result_frames", "result_duration_s", "conformed_file", "note",
]


def write_ledger(path: Path, plans: list[Plan], trim_anchor: str, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["\t".join(LEDGER_COLUMNS)]
    for p in plans:
        rows.append("\t".join(str(x) for x in [
            p.w.id, p.w.index,
            p.source if p.source else "MISSING",
            "yes" if p.source else "no",
            p.src_w, p.src_h, f"{p.src_fps:.3f}", f"{p.src_dur_s:.3f}",
            p.src_frames_native if p.src_frames_native is not None else "",
            f"{p.w.start_s:.3f}", f"{p.w.end_s:.3f}", p.w.frames, f"{p.w.dur_s:.4f}",
            p.avail_frames_30, f"{p.delta_frames:+d}", p.classification, p.policy,
            trim_anchor if p.policy.startswith("trim") else "-",
            f"{p.trim_start_s:.3f}", f"{p.trim_end_s:.3f}",
            f"{p.stretch_factor:.6f}", f"{p.pad_s:.3f}",
            p.result_frames if p.result_frames is not None else "",
            f"{p.result_frames / p.w.fps:.4f}" if p.result_frames is not None else "",
            p.conformed.name if p.conformed else "",
            p.error or "",
        ]))
    total_res = sum(p.result_frames for p in plans if p.result_frames is not None)
    rows.append("\t".join(str(x) for x in [
        "TOTAL", len(plans), "", "", "", "", "", "", "",
        "0.000", f"{meta['total_duration_s']:.3f}", meta["total_frames"],
        f"{meta['total_duration_s']:.4f}", "", "", "", "", "", "", "", "", "",
        total_res, f"{total_res / meta['fps']:.4f}", "", "",
    ]))
    path.write_text("\n".join(rows) + "\n")


def print_table(plans: list[Plan], meta: dict[str, Any], trim_anchor: str) -> None:
    hdr = (f"{'SHOT':<5}{'WINDOW (s)':<18}{'FR':>5}  {'SOURCE':<22}"
           f"{'SRC dur':>9}{'AVAIL':>7}{'Δ':>6}  {'CLASS':<7}{'POLICY':<13}{'IN→OUT (s)':<17}")
    print(hdr)
    print("-" * len(hdr))
    for p in plans:
        src = p.source.name if p.source else "*** MISSING ***"
        if len(src) > 21:
            src = src[:18] + "..."
        inout = (f"{p.trim_start_s:.3f}→{p.trim_end_s:.3f}" if p.source else "-")
        extra = ""
        if p.policy == "stretch":
            extra = f" x{p.stretch_factor:.3f}"
        elif p.policy == "hold":
            extra = f" +{p.pad_s - ROUNDING_GUARD_S:.3f}s"
        print(f"{p.w.id:<5}{p.w.start_s:>7.3f}→{p.w.end_s:<10.3f}{p.w.frames:>5}  {src:<22}"
              f"{p.src_dur_s:>9.3f}{p.avail_frames_30:>7}{p.delta_frames:>+6}  "
              f"{p.classification:<7}{p.policy:<13}{inout}{extra}")
    print("-" * len(hdr))
    span = f"{0.0:>7.3f}→{meta['total_duration_s']:<10.3f}"
    print(f"{'TOTAL':<5}{span}{meta['total_frames']:>5}   trim-anchor={trim_anchor}")


# =============================================================================
# Verification
# =============================================================================

def verify(output: Path, expected_frames: int, expected_duration: float,
           width: int, height: int, fps: float,
           expect_audio: bool, ffmpeg_bin: str, ffprobe_bin: str,
           min_size_bytes: int) -> dict[str, Any]:
    report: dict[str, Any] = {"file": str(output), "all_passed": True, "checks": {}}

    def record(key: str, passed: bool, details: str) -> None:
        report["checks"][key] = {"passed": passed, "details": details}
        if not passed:
            report["all_passed"] = False

    # 1 - file exists, plausible size
    if not output.is_file():
        record("1_file", False, f"File does not exist: {output}")
        return report
    size = output.stat().st_size
    record("1_file", size >= min_size_bytes,
           f"{output.name}: {size:,} bytes ({size / 1048576:.2f} MB), floor {min_size_bytes:,}")

    data = probe_media(output, ffprobe_bin=ffprobe_bin)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    vs = [s for s in streams if s.get("codec_type") == "video"]
    aus = [s for s in streams if s.get("codec_type") == "audio"]

    # 2 - geometry
    if not vs:
        record("2_resolution", False, "No video stream")
    else:
        v = vs[0]
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        sar = v.get("sample_aspect_ratio", "") or "1:1"
        dar = v.get("display_aspect_ratio", "") or "-"
        ok = (w == width and h == height and sar in ("1:1", "1/1"))
        record("2_resolution", ok, f"{w}x{h}, SAR {sar}, DAR {dar} (want {width}x{height}, SAR 1:1)")

    # 3 - CFR
    if not vs:
        record("3_framerate", False, "No video stream")
    else:
        v = vs[0]
        want = f"{int(fps)}/1" if float(fps).is_integer() else None
        r, a = v.get("r_frame_rate", ""), v.get("avg_frame_rate", "")
        ok = (r == want and a == want) if want else (r == a)
        record("3_framerate", ok, f"r_frame_rate={r}, avg_frame_rate={a} (want {want}) -> CFR")

    # 4 - exact frames + exact duration
    if not vs:
        record("4_frames_duration", False, "No video stream")
    else:
        v = vs[0]
        decoded = count_frames(output, ffprobe_bin=ffprobe_bin)
        header = v.get("nb_frames")
        vdur = float(v.get("duration") or 0.0)
        cdur = float(fmt.get("duration") or 0.0)
        frames_ok = (decoded == expected_frames)
        vdur_ok = abs(vdur - expected_duration) <= 0.001
        cdur_ok = abs(cdur - expected_duration) <= 0.050
        record("4_frames_duration", frames_ok and vdur_ok and cdur_ok,
               f"decoded={decoded} (want exactly {expected_frames}), header nb_frames={header}, "
               f"video stream duration={vdur:.6f}s (want {expected_duration:.3f}s ±0.001), "
               f"container duration={cdur:.6f}s (±0.050)")

    # 5 - audio
    if not expect_audio:
        record("5_audio", True, "audio not requested (--no-audio)")
    elif not aus:
        record("5_audio", False, "No audio stream in container")
    else:
        a = aus[0]
        codec = (a.get("codec_name") or "").lower()
        profile = (a.get("profile") or "")
        sr = int(a.get("sample_rate") or 0)
        ch = int(a.get("channels") or 0)
        adur = float(a.get("duration") or 0.0)
        ok = (codec == "aac" and sr == 48000 and ch == 2)
        record("5_audio", ok,
               f"{codec.upper()} {profile}, {sr} Hz, {ch} ch, duration={adur:.3f}s "
               f"(want AAC-LC / 48000 / 2)")

    # 6 - no rotation metadata
    rot = probe_rotation(output, ffprobe_bin=ffprobe_bin)
    record("6_no_rotation", rot in (None, 0, 0.0),
           "no Display Matrix side data" if rot in (None, 0, 0.0) else f"rotation={rot} present")

    # 7 - faststart
    ok6, det6, meta6 = check_faststart_atoms(output)
    report["checks"]["7_faststart"] = {"passed": ok6, "details": det6, "meta": meta6}
    if not ok6:
        report["all_passed"] = False

    # 8 - decode integrity
    res = run([ffmpeg_bin, "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"])
    ok8 = (res.returncode == 0 and not res.stderr.strip())
    record("8_decode", ok8, "clean decode, 0 bitstream errors" if ok8 else res.stderr.strip()[:500])

    # 9 - black frames
    res = run([ffmpeg_bin, "-hide_banner", "-i", str(output),
               "-vf", "blackdetect=d=0.1:pix_th=0.10", "-f", "null", "-"])
    hits = re.findall(r"black_start:\s*([0-9.]+)\s+black_end:\s*([0-9.]+)\s+black_duration:\s*([0-9.]+)",
                      res.stderr)
    record("9_black_frames", not hits,
           "0 black sequences across the full reel" if not hits
           else f"{len(hits)} black sequence(s): {hits[:5]}")

    width_line = 92
    print()
    print("=" * width_line)
    print(f"LOCAL ASSEMBLY VERIFICATION - {output}")
    print("=" * width_line)
    for k, v in report["checks"].items():
        print(f"[{'PASS' if v['passed'] else 'FAIL':^4}] {k.upper():<20} {v['details']}")
    print("=" * width_line)
    print("[OK] ALL VERIFICATION GATES PASSED." if report["all_passed"]
          else "[!!] ONE OR MORE VERIFICATION GATES FAILED.")
    print("=" * width_line)
    return report


# =============================================================================
# CLI
# =============================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="assemble_local.py",
        description="Conform locally-rendered per-shot clips to the Peshta shot bible "
                    "windows, concatenate, mux the master music, and verify.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input-dir", type=Path, required=True,
                   help="Directory holding the locally-rendered per-shot clips.")
    p.add_argument("--pattern", default=DEFAULT_PATTERN,
                   help="Filename template or glob for the per-shot clips. A template may use "
                        "{n}, {n02}, {n03} (default: %(default)s). A value with no '{' is treated "
                        "as a glob and matches are natural-sorted and assigned in order.")
    p.add_argument("--shot-bible", type=Path, default=DEFAULT_SHOT_BIBLE,
                   help="shot_bible.json holding the authoritative window table (default: %(default)s).")
    p.add_argument("--audio", type=Path, default=DEFAULT_AUDIO,
                   help="Master music track to mux underneath (default: %(default)s).")
    p.add_argument("--no-audio", action="store_true",
                   help="Produce a silent picture-only master (skips the mux and the audio gate).")
    p.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT,
                   help="Destination mp4 (default: %(default)s).")
    p.add_argument("--short-policy", choices=("fail", "hold", "stretch"), default="fail",
                   help="What to do when a render is SHORTER than its window. "
                        "fail (default) refuses to build; hold freezes the last frame; "
                        "stretch time-stretches the clip to fit. Silent padding is how a reel "
                        "ends up with a frozen frame nobody notices, so 'fail' is the default.")
    p.add_argument("--trim-anchor", choices=("centre", "center", "head", "tail"), default="centre",
                   help="Where to take the window from when a render is LONGER (default: centre).")
    p.add_argument("--fit", choices=("pad", "crop"), default="pad",
                   help="Off-aspect sources: letterbox/pillarbox them (pad, default, matches the "
                        "Higgsfield-era assembler) or fill and centre-crop (crop).")
    p.add_argument("--color-grade", action="store_true",
                   help="Apply the same Kurtlar Vadisi noir grade the Higgsfield master carries. "
                        "Off by default so the A/B judges the raw model output.")
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--preset", default="medium")
    p.add_argument("--audio-bitrate", default="320k")
    p.add_argument("--min-size-mb", type=float, default=1.0,
                   help="Size floor for the output sanity gate (default: %(default)s MB).")
    p.add_argument("--ledger", type=Path, default=None,
                   help="Where to write LEDGER.tsv (default: alongside the output).")
    p.add_argument("--work-dir", type=Path, default=None,
                   help="Directory for the per-shot conformed intermediates "
                        "(default: a temp dir, removed on success).")
    p.add_argument("--keep-work", action="store_true", help="Keep the intermediates.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the planned conform table and the ledger, render nothing.")
    p.add_argument("--verbose", action="store_true", help="Echo every ffmpeg command.")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--ffprobe", default="ffprobe")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    trim_anchor = "centre" if args.trim_anchor in ("centre", "center") else args.trim_anchor

    for binary in (args.ffmpeg, args.ffprobe):
        if shutil.which(binary) is None:
            print(f"[-] required binary not on PATH: {binary}", file=sys.stderr)
            return 2

    try:
        windows, meta = load_windows(args.shot_bible.resolve())
    except Exception as e:
        print(f"[-] shot bible: {e}", file=sys.stderr)
        return 2

    fps = meta["fps"]
    total_frames = meta["total_frames"]
    total_dur = meta["total_duration_s"]

    print(f"[*] shot bible : {args.shot_bible}")
    print(f"[*] timeline   : {len(windows)} windows, {total_frames} frames @ {fps:g} fps = {total_dur:.3f}s")
    print(f"[*] inputs     : {args.input_dir}  (pattern '{args.pattern}')")

    # ---- resolve sources; a missing shot is a hard error -------------------
    try:
        sources, missing = resolve_sources(args.input_dir.resolve(), args.pattern, len(windows))
    except Exception as e:
        print(f"[-] {e}", file=sys.stderr)
        return 2

    plans = [Plan(w) for w in windows]
    for pl, src in zip(plans, sources):
        pl.source = src

    absent = [pl for pl in plans if pl.source is None]
    if absent:
        print(f"\n[-] MISSING INPUTS: {len(absent)} of {len(plans)} shot clips are not present.",
              file=sys.stderr)
        for line in missing:
            print(f"      {line}", file=sys.stderr)
        print("    Nothing was rendered. Supply the missing renders, or point --input-dir/--pattern "
              "at the right place.", file=sys.stderr)
        return 3

    # ---- measure + plan ----------------------------------------------------
    try:
        for pl in plans:
            measure(pl, args.ffprobe)
            plan_shot(pl, args.short_policy, trim_anchor)
    except Exception as e:
        print(f"[-] probing/planning failed: {e}", file=sys.stderr)
        return 2

    print()
    print_table(plans, meta, trim_anchor)

    ledger_path = args.ledger or (args.output.resolve().parent / "LEDGER.tsv")
    write_ledger(ledger_path, plans, trim_anchor, meta)
    print(f"\n[*] ledger     : {ledger_path}")

    failures = [pl for pl in plans if pl.policy == "FAIL"]
    if failures:
        print(f"\n[-] {len(failures)} shot(s) came back SHORT of their window and --short-policy=fail:",
              file=sys.stderr)
        for pl in failures:
            print(f"      shot {pl.w.id}: {pl.error}  [{pl.source}]", file=sys.stderr)
        print("    Re-render them at the right length, or choose --short-policy hold|stretch "
              "and accept what the ledger will then record.", file=sys.stderr)
        return 4

    if args.dry_run:
        print("\n[*] --dry-run: nothing rendered.")
        return 0

    if not args.no_audio and not args.audio.is_file():
        print(f"[-] master audio not found: {args.audio}", file=sys.stderr)
        return 2

    # ---- render ------------------------------------------------------------
    tmp_created = False
    if args.work_dir:
        work_dir = args.work_dir.resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="assemble_local_"))
        tmp_created = True

    assembly_ok = False
    try:
        print(f"[*] work dir   : {work_dir}")
        for pl in plans:
            print(f"    conform shot {pl.w.id}: {pl.policy:<13} -> {pl.w.frames} frames")
            render_shot(pl, work_dir, args.fit, args.color_grade,
                        args.width, args.height, args.crf, args.preset,
                        args.ffmpeg, args.ffprobe, args.verbose)

        print("[*] concatenating...")
        cat = concat_shots(plans, work_dir, args.ffmpeg)
        cat_frames = count_frames(cat, ffprobe_bin=args.ffprobe)
        if cat_frames != total_frames:
            raise RuntimeError(
                f"concatenated picture is {cat_frames} frames, expected {total_frames}. "
                f"Refusing to mux."
            )

        if args.no_audio:
            print("[*] --no-audio: remuxing picture only with faststart...")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            res = run([args.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                       "-i", str(cat), "-c", "copy", "-map_metadata", "-1",
                       "-movflags", "+faststart+negative_cts_offsets", str(args.output.resolve())])
            if res.returncode != 0:
                raise RuntimeError(f"remux failed:\n{res.stderr.strip()}")
        else:
            print(f"[*] muxing audio: {args.audio}")
            mux_audio(cat, args.audio.resolve(), args.output.resolve(),
                      total_dur, args.audio_bitrate, args.ffmpeg)

        # ledger again, now with the real per-shot results
        write_ledger(ledger_path, plans, trim_anchor, meta)
        assembly_ok = True

    except Exception as e:
        print(f"\n[-] assembly failed: {e}", file=sys.stderr)
        print(f"    intermediates left in {work_dir}", file=sys.stderr)
        return 5
    finally:
        # Keep the intermediates whenever the build did NOT complete: they are the
        # only evidence of which shot went wrong.
        if tmp_created and not args.keep_work and assembly_ok:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ---- verify ------------------------------------------------------------
    try:
        report = verify(
            args.output.resolve(), total_frames, total_dur,
            args.width, args.height, fps,
            expect_audio=not args.no_audio,
            ffmpeg_bin=args.ffmpeg, ffprobe_bin=args.ffprobe,
            min_size_bytes=int(args.min_size_mb * 1024 * 1024),
        )
    except Exception as e:
        print(f"[-] verification could not run: {e}", file=sys.stderr)
        return 6

    print(f"\n[*] output     : {args.output.resolve()}")
    print(f"[*] ledger     : {ledger_path}")
    return 0 if report["all_passed"] else 7


if __name__ == "__main__":
    sys.exit(main())
