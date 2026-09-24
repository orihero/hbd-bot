#!/usr/bin/env python3
"""
marketing/campaigns/peshta/assemble_polat_peshta.py
======================================
Automated Post-Production Assembly & Conformance Engine for Milestone 4 (R4).

Stitches 11 Higgsfield/driving macro clips into a seamless 43.000s 9:16 vertical
Instagram Reel / TikTok master video, synchronized to the master parody audio
(Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3) with Kurtlar Vadisi cinematic color grading
and strict faststart container optimization.

Key Technical Specifications:
  - Resolution: 1080x1920 (9:16 vertical, SAR 1:1, DAR 9:16)
  - Frame Rate: 30.0 fps Constant Frame Rate (CFR), r_frame_rate='30/1'
  - Duration: 43.000s ± 0.10s, exactly 1,290 frames (±3 frames)
  - Video Codec: H.264 (libx264, High Profile, YUV420p)
  - Audio Codec: AAC-LC, 320 kbps, 48000 Hz, stereo
  - Streaming: faststart moov atom positioned before mdat in first 4096 bytes
  - Color Grade: Kurtlar Vadisi Turkish mafia noir aesthetic:
      eq=contrast=1.10:brightness=-0.02:saturation=0.94
      colorbalance=bs=0.06:bm=-0.02:bh=-0.04:rm=0.02

Pure Python 3 standard library + FFmpeg / FFprobe. ZERO third-party pip dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

# Default workspace directory topology
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "driving_clips"
DEFAULT_AUDIO_PATH = Path("/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3")
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "assembled_preview.mp4"

# Color grading filter chain
TURKISH_MAFIA_NOIR_FILTER = (
    "eq=contrast=1.10:brightness=-0.02:saturation=0.94,"
    "colorbalance=bs=0.06:bm=-0.02:bh=-0.04:rm=0.02"
)


def natural_sort_key(p: Path) -> list[int | str]:
    """Generates a natural sort key ensuring numeric sequence order (clip_01..clip_11)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", p.name)]


def find_input_clips(input_dir: Path | str) -> list[Path]:
    """
    Discovers all MP4 video clips within input_dir, sorted in natural numeric order.
    Excludes hidden files and non-MP4 artifacts.
    """
    directory = Path(input_dir).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {directory}")

    clips = [
        f for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() in (".mp4", ".mov", ".mkv") and not f.name.startswith(".")
    ]
    if not clips:
        raise FileNotFoundError(f"No video clips found in directory: {directory}")

    clips.sort(key=natural_sort_key)
    return clips


def probe_media(file_path: Path | str, ffprobe_bin: str = "ffprobe") -> dict[str, Any]:
    """
    Probes video/audio file metadata via ffprobe, returning parsed JSON dictionary.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Target media file not found: {path}")

    cmd = [
        ffprobe_bin,
        "-v", "error",
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
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}:\n{res.stderr.strip()}")

    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse ffprobe JSON output for {path}: {e}") from e


def check_faststart_atoms(file_path: Path | str) -> tuple[bool, str, dict[str, Any]]:
    """
    Inspects the MP4 container structure to verify the faststart 'moov' atom
    is positioned before the 'mdat' atom within the initial 4096 bytes.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        return False, f"File does not exist: {path}", {}

    file_size = path.stat().st_size
    with open(path, "rb") as f:
        first_4k = f.read(4096)
        moov_in_4k = first_4k.find(b"moov")
        mdat_in_4k = first_4k.find(b"mdat")

        # Sequentially parse top-level ISO MP4 boxes
        f.seek(0)
        boxes: list[dict[str, Any]] = []
        pos = 0
        while pos < min(file_size, 10_000_000):  # parse first 10MB of box index
            f.seek(pos)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            box_size = int.from_bytes(hdr[0:4], "big")
            box_type = hdr[4:8].decode("latin1", errors="ignore")

            actual_size = box_size
            if box_size == 1:
                # 64-bit extended size
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

    return True, f"'moov' atom located at offset {moov_offset} (<4096 bytes) preceding 'mdat'", details


def build_filtergraph(
    num_clips: int,
    color_grade: bool = True,
    crossfade: float = 0.0,
    trim_lead: float = 0.0,
    clip_durations: list[float] | None = None,
    clip_targets: list[float] | None = None,
) -> str:
    """
    Constructs the FFmpeg complex filtergraph conforming all input streams to:
      - 1080x1920 portrait (DAR 9:16, SAR 1:1)
      - Constant 30 fps
      - YUV420p pixel format
      - Zero PTS timestamp drift
      - Concatenation (clean cut or xfade)
      - Turkish mafia noir color grade
    """
    if num_clips < 1:
        raise ValueError("At least one input clip is required to build filtergraph")

    filter_chains: list[str] = []

    # Calibrated macro durations for the 11 shots (Milestone 1 / SHOT_TABLE.md)
    # Sum: 43.000s = exactly 1,290 frames @ 30.0 fps CFR.
    DEFAULT_CALIBRATED_DURATIONS = [
        2.256, 2.920, 3.800, 2.840, 2.600, 4.840, 6.240, 4.480, 5.920, 1.600, 5.504
    ]

    # 1. Per-clip conforming filter
    for i in range(num_clips):
        trim_part = ""
        tpad_part = ""
        if clip_targets and i < len(clip_targets):
            t_target = clip_targets[i]
            tpad_part = "tpad=stop_mode=clone:stop_duration=1.0,"
            trim_part = f"trim=start=0:end={t_target:.3f},"
        elif trim_lead > 0.0:
            if clip_durations and i < len(clip_durations) and clip_durations[i] > (2 * trim_lead):
                end_s = clip_durations[i] - trim_lead
                trim_part = f"trim=start={trim_lead:.3f}:end={end_s:.3f},"
            else:
                trim_part = f"trim=start={trim_lead:.3f},"

        conforming = (
            f"[{i}:v]{tpad_part}{trim_part}setpts=PTS-STARTPTS,"
            f"scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,fps=30,format=yuv420p[v{i}]"
        )
        filter_chains.append(conforming)

    # 2. Sequence Concatenation or Crossfade
    if crossfade <= 0.0 or num_clips == 1:
        # Standard clean cuts via concat filter
        concat_inputs = "".join(f"[v{i}]" for i in range(num_clips))
        filter_chains.append(f"{concat_inputs}concat=n={num_clips}:v=1:a=0[v_cat]")
    else:
        # Chain xfade filters across clips
        # Note: offsets depend on cumulative duration
        if not clip_durations or len(clip_durations) != num_clips:
            # Fallback to concat if exact durations are not provided
            concat_inputs = "".join(f"[v{i}]" for i in range(num_clips))
            filter_chains.append(f"{concat_inputs}concat=n={num_clips}:v=1:a=0[v_cat]")
        else:
            curr_stream = "[v0]"
            curr_offset = clip_durations[0] - crossfade
            for i in range(1, num_clips):
                next_stream = f"[v{i}]"
                out_stream = f"[xf{i}]" if i < num_clips - 1 else "[v_cat]"
                filter_chains.append(
                    f"{curr_stream}{next_stream}xfade=transition=fade:duration={crossfade:.3f}:offset={max(0.0, curr_offset):.3f}{out_stream}"
                )
                curr_stream = out_stream
                if i < num_clips - 1:
                    curr_offset += clip_durations[i] - crossfade

    # 3. Color grading stage
    if color_grade:
        filter_chains.append(f"[v_cat]{TURKISH_MAFIA_NOIR_FILTER}[v_out]")
    else:
        filter_chains.append("[v_cat]null[v_out]")

    return ";".join(filter_chains)


def assemble_video(
    input_dir: Path | str,
    audio_path: Path | str,
    output_path: Path | str,
    color_grade: bool = True,
    crossfade: float = 0.0,
    trim_lead: float = 0.0,
    target_duration: float = 43.0,
    clip_targets: list[float] | None = None,
    conform_targets: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> Path:
    """
    Orchestrates the end-to-end post-production assembly pipeline.
    """
    in_dir = Path(input_dir).resolve()
    audio = Path(audio_path).resolve()
    out = Path(output_path).resolve()

    if not audio.is_file():
        raise FileNotFoundError(f"Master audio track not found: {audio}")

    clips = find_input_clips(in_dir)
    print(f"[*] Ingesting {len(clips)} driving clips from: {in_dir}")
    for idx, c in enumerate(clips, 1):
        print(f"    - Clip {idx:02d}: {c.name}")

    # Probe clip durations if needed for trimming or xfade
    clip_durations: list[float] = []
    for c in clips:
        meta = probe_media(c, ffprobe_bin=ffprobe_bin)
        stream_dur = 0.0
        streams = meta.get("streams", [])
        if streams:
            stream_dur = float(streams[0].get("duration") or meta.get("format", {}).get("duration", 0.0))
        clip_durations.append(stream_dur)

    # Resolve macro target durations if conform_targets is requested
    resolved_targets = None
    if conform_targets:
        default_11_targets = [
            2.256, 2.920, 3.800, 2.840, 2.600, 4.840, 6.240, 4.480, 5.920, 1.600, 5.504
        ]
        resolved_targets = clip_targets if clip_targets is not None else default_11_targets

    # Build filtergraph
    filtergraph = build_filtergraph(
        num_clips=len(clips),
        color_grade=color_grade,
        crossfade=crossfade,
        trim_lead=trim_lead,
        clip_durations=clip_durations,
        clip_targets=resolved_targets,
    )

    out.parent.mkdir(parents=True, exist_ok=True)

    # Assemble FFmpeg command
    cmd = [ffmpeg_bin, "-y"]

    # Ingest video clips as inputs 0 .. N-1
    for c in clips:
        cmd.extend(["-i", str(c)])

    # Ingest master audio as input N
    audio_index = len(clips)
    cmd.extend(["-i", str(audio)])

    cmd.extend([
        "-filter_complex", filtergraph,
        "-map", "[v_out]",
        "-map", f"{audio_index}:a:0",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-fps_mode", "cfr",
        "-c:a", "aac",
        "-b:a", "320k",
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
    ])

    if target_duration > 0.0:
        cmd.extend(["-t", f"{target_duration:.3f}"])

    cmd.append(str(out))

    print(f"[*] Executing FFmpeg complex assembly to: {out.name}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("[-] FFmpeg assembly failed!", file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        raise RuntimeError(f"FFmpeg assembly failed with exit code {res.returncode}:\n{res.stderr.strip()}")

    print(f"[✓] Assembled preview successfully created: {out} ({out.stat().st_size} bytes)")
    return out


def verify_assembly(
    video_path: Path | str,
    expected_duration: float = 43.0,
    duration_tol: float = 0.10,
    expected_frames: int = 1290,
    frame_tol: int = 3,
    min_size_bytes: int = 5_000_000,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    raise_on_failure: bool = True,
) -> dict[str, Any]:
    """
    Built-in Automated Verification Suite executing 8 quality gates:
      - Check 1: File existence and non-zero size (>5 MB).
      - Check 2: Resolution strictly 1080x1920 (DAR 9:16, SAR 1:1).
      - Check 3: Frame rate strictly 30.0 fps CFR (r_frame_rate == '30/1').
      - Check 4: Duration equals 43.000s within ±0.10s, frame count equals 1,290 frames (±3 frames).
      - Check 5: Audio stream present, codec AAC, sample rate 48000 Hz, stereo.
      - Check 6: Faststart moov atom located before mdat in first 4096 bytes.
      - Check 7: Bitstream decode integrity test (ffmpeg -v error -i <output> -f null -) exits with 0 errors.
      - Check 8: Black frame detector confirms zero accidental black frames.
    """
    path = Path(video_path).resolve()
    report: dict[str, Any] = {
        "file": str(path),
        "all_passed": True,
        "checks": {},
    }

    # -------------------------------------------------------------------------
    # Check 1: File existence and non-zero size (>5 MB)
    # -------------------------------------------------------------------------
    c1_passed = False
    c1_details = ""
    if not path.is_file():
        c1_details = f"File does not exist: {path}"
    else:
        size = path.stat().st_size
        size_mb = size / (1024 * 1024)
        if size >= min_size_bytes:
            c1_passed = True
            c1_details = f"File exists, size = {size_mb:.2f} MB ({size:,} bytes) >= 5.0 MB"
        else:
            c1_details = f"File size {size_mb:.2f} MB ({size:,} bytes) is below minimum {min_size_bytes:,} bytes"

    report["checks"]["check_1_file_size"] = {"passed": c1_passed, "details": c1_details}
    if not c1_passed:
        report["all_passed"] = False

    # Early exit if file does not exist
    if not c1_passed:
        if raise_on_failure:
            raise AssertionError(f"Check 1 Failed: {c1_details}")
        return report

    # Probe metadata for Checks 2, 3, 4, 5
    probe_data = probe_media(path, ffprobe_bin=ffprobe_bin)
    streams = probe_data.get("streams", [])
    format_info = probe_data.get("format", {})

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    # -------------------------------------------------------------------------
    # Check 2: Resolution strictly 1080x1920 (DAR 9:16, SAR 1:1)
    # -------------------------------------------------------------------------
    c2_passed = False
    c2_details = ""
    if not video_streams:
        c2_details = "No video stream detected in file"
    else:
        v0 = video_streams[0]
        w = int(v0.get("width") or 0)
        h = int(v0.get("height") or 0)
        sar = v0.get("sample_aspect_ratio", "")
        dar = v0.get("display_aspect_ratio", "")

        is_res = (w == 1080 and h == 1920)
        is_sar = sar in ("1:1", "1/1", "")
        is_dar = dar in ("9:16", "9/16", "")

        if is_res and is_sar and is_dar:
            c2_passed = True
            c2_details = f"Resolution = {w}x{h}, SAR = {sar or '1:1'}, DAR = {dar or '9:16'} strictly conform to 9:16"
        else:
            c2_details = f"Geometry mismatch: {w}x{h} (SAR: {sar}, DAR: {dar}); expected 1080x1920 (SAR 1:1, DAR 9:16)"

    report["checks"]["check_2_resolution"] = {"passed": c2_passed, "details": c2_details}
    if not c2_passed:
        report["all_passed"] = False

    # -------------------------------------------------------------------------
    # Check 3: Frame rate strictly 30.0 fps CFR (r_frame_rate == '30/1')
    # -------------------------------------------------------------------------
    c3_passed = False
    c3_details = ""
    if not video_streams:
        c3_details = "No video stream to inspect frame rate"
    else:
        v0 = video_streams[0]
        r_fps = v0.get("r_frame_rate", "")
        avg_fps = v0.get("avg_frame_rate", "")
        if r_fps == "30/1" and avg_fps == "30/1":
            c3_passed = True
            c3_details = f"Constant Frame Rate confirmed: r_frame_rate='{r_fps}', avg_frame_rate='{avg_fps}' (30.0 fps)"
        else:
            c3_details = f"Frame rate mismatch: r_frame_rate='{r_fps}', avg_frame_rate='{avg_fps}'; expected '30/1'"

    report["checks"]["check_3_framerate"] = {"passed": c3_passed, "details": c3_details}
    if not c3_passed:
        report["all_passed"] = False

    # -------------------------------------------------------------------------
    # Check 4: Duration equals 43.000s within ±0.10s, frame count equals 1,290 frames (±3 frames)
    # -------------------------------------------------------------------------
    c4_passed = False
    c4_details = ""
    if not video_streams:
        c4_details = "No video stream for duration/frames measurement"
    else:
        v0 = video_streams[0]
        dur_str = v0.get("duration") or format_info.get("duration") or "0.0"
        nb_frames_str = v0.get("nb_frames")

        duration = float(dur_str)

        # Count packets/frames if nb_frames missing from header
        if not nb_frames_str or nb_frames_str == "N/A":
            p_cmd = [
                ffprobe_bin, "-v", "error", "-select_streams", "v:0",
                "-count_packets", "-show_entries", "stream=nb_read_packets",
                "-of", "json", str(path)
            ]
            p_res = subprocess.run(p_cmd, capture_output=True, text=True)
            if p_res.returncode == 0:
                p_data = json.loads(p_res.stdout)
                nb_frames = int(p_data.get("streams", [{}])[0].get("nb_read_packets", 0))
            else:
                nb_frames = round(duration * 30.0)
        else:
            nb_frames = int(nb_frames_str)

        dur_diff = abs(duration - expected_duration)
        frame_diff = abs(nb_frames - expected_frames)

        is_dur_ok = (dur_diff <= duration_tol)
        is_frames_ok = (frame_diff <= frame_tol)

        if is_dur_ok and is_frames_ok:
            c4_passed = True
            c4_details = (
                f"Duration = {duration:.3f}s (delta = {dur_diff:.3f}s <= ±{duration_tol}s), "
                f"Frames = {nb_frames:,} (delta = {frame_diff} <= ±{frame_tol} frames)"
            )
        else:
            c4_details = (
                f"Duration or frame count out of tolerance: duration = {duration:.3f}s "
                f"(expected {expected_duration}s ±{duration_tol}s), frames = {nb_frames} "
                f"(expected {expected_frames} ±{frame_tol})"
            )

    report["checks"]["check_4_duration_frames"] = {"passed": c4_passed, "details": c4_details}
    if not c4_passed:
        report["all_passed"] = False

    # -------------------------------------------------------------------------
    # Check 5: Audio stream present, codec AAC, sample rate 48000 Hz, stereo
    # -------------------------------------------------------------------------
    c5_passed = False
    c5_details = ""
    if not audio_streams:
        c5_details = "No audio stream found in container"
    else:
        a0 = audio_streams[0]
        codec = a0.get("codec_name", "").lower()
        sr = int(a0.get("sample_rate") or 0)
        channels = int(a0.get("channels") or 0)

        is_aac = (codec == "aac")
        is_sr = (sr == 48000)
        is_stereo = (channels == 2)

        if is_aac and is_sr and is_stereo:
            c5_passed = True
            c5_details = f"Audio stream verified: codec = {codec.upper()}, sample_rate = {sr} Hz, channels = {channels} (Stereo)"
        else:
            c5_details = f"Audio parameter mismatch: codec='{codec}', sample_rate={sr}, channels={channels}; expected AAC, 48000Hz, stereo (2 channels)"

    report["checks"]["check_5_audio_stream"] = {"passed": c5_passed, "details": c5_details}
    if not c5_passed:
        report["all_passed"] = False

    # -------------------------------------------------------------------------
    # Check 6: Faststart moov atom located before mdat in first 4096 bytes
    # -------------------------------------------------------------------------
    c6_passed, c6_details, c6_extra = check_faststart_atoms(path)
    report["checks"]["check_6_faststart"] = {"passed": c6_passed, "details": c6_details, "meta": c6_extra}
    if not c6_passed:
        report["all_passed"] = False

    # -------------------------------------------------------------------------
    # Check 7: Bitstream decode integrity test (ffmpeg -v error -i <output> -f null -)
    # -------------------------------------------------------------------------
    c7_cmd = [ffmpeg_bin, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"]
    c7_res = subprocess.run(c7_cmd, capture_output=True, text=True)
    c7_passed = (c7_res.returncode == 0 and not c7_res.stderr.strip())
    c7_details = "Decode test clean: 0 bitstream/decoding errors" if c7_passed else f"Decode test failed:\n{c7_res.stderr.strip()}"
    report["checks"]["check_7_bitstream_decode"] = {"passed": c7_passed, "details": c7_details}
    if not c7_passed:
        report["all_passed"] = False

    # -------------------------------------------------------------------------
    # Check 8: Black frame detector confirms zero accidental black frames
    # -------------------------------------------------------------------------
    c8_cmd = [
        ffmpeg_bin, "-hide_banner", "-i", str(path),
        "-vf", "blackdetect=d=0.1:pix_th=0.10",
        "-f", "null", "-"
    ]
    c8_res = subprocess.run(c8_cmd, capture_output=True, text=True)
    black_matches = re.findall(r"black_start:\s*([0-9.]+)\s+black_end:\s*([0-9.]+)\s+black_duration:\s*([0-9.]+)", c8_res.stderr)
    if not black_matches:
        c8_passed = True
        c8_details = "Zero accidental black frames detected across full sequence"
    else:
        c8_passed = False
        c8_details = f"Detected {len(black_matches)} black frame sequence(s): {black_matches[:3]}"

    report["checks"]["check_8_black_frames"] = {"passed": c8_passed, "details": c8_details}
    if not c8_passed:
        report["all_passed"] = False

    # Print summary
    print("\n" + "=" * 80)
    print("AUTOMATED 8-POINT MASTER ASSEMBLY VERIFICATION SUITE")
    print("=" * 80)
    for k, v in report["checks"].items():
        status = "PASS" if v["passed"] else "FAIL"
        print(f"[{status:^4}] {k.upper()}: {v['details']}")
    print("=" * 80)

    if report["all_passed"]:
        print("[✓] ALL 8 VERIFICATION GATES PASSED DETERMINISTICALLY.")
    else:
        print("[-] ONE OR MORE VERIFICATION GATES FAILED.")
        if raise_on_failure:
            failed_keys = [k for k, v in report["checks"].items() if not v["passed"]]
            raise AssertionError(f"Verification gates failed: {failed_keys}")

    print("=" * 80 + "\n")
    return report


def str_to_bool_or_flag(v: Any) -> bool:
    """Helper to convert string representations or flags to boolean."""
    if isinstance(v, bool):
        return v
    val = str(v).strip().lower()
    if val in ("true", "1", "yes", "y", "t"):
        return True
    if val in ("false", "0", "no", "n", "f"):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected, got '{v}'")


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Automated Post-Production Assembly Engine for Polat Alemdar & Elif Eylül 'Peshta' Recreation"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Directory containing video clips to assemble (default: marketing/campaigns/peshta/driving_clips/)",
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=DEFAULT_AUDIO_PATH,
        help="Path to master audio file (default: /Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Destination MP4 file path (default: marketing/campaigns/peshta/assembled_preview.mp4)",
    )
    parser.add_argument(
        "--color-grade",
        nargs="?",
        const=True,
        default=True,
        type=str_to_bool_or_flag,
        help="Toggle cinematic Turkish mafia noir color grading (default: True)",
    )
    parser.add_argument(
        "--no-color-grade",
        dest="color_grade",
        action="store_false",
        help="Disable cinematic Turkish mafia noir color grading",
    )
    parser.add_argument(
        "--crossfade",
        type=float,
        default=0.0,
        help="Subtle transition crossfade duration in seconds (default: 0.0 for clean cuts)",
    )
    parser.add_argument(
        "--trim-lead",
        type=float,
        default=0.0,
        help="Seconds to trim from start/end of clips where AI models produce distortion (default: 0.0)",
    )
    parser.add_argument(
        "--conform-targets",
        action="store_true",
        default=False,
        help="Conform input clips to exact calibrated macro shot durations from SHOT_TABLE.md",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=False,
        help="Run automated 8-check verification suite on output MP4 after assembly",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        default=False,
        help="Run verification check on existing output file without re-assembling",
    )

    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    """Main CLI execution entrypoint."""
    args = parse_args(argv)

    if args.verify_only:
        print(f"[*] Running verification only on existing file: {args.output}")
        try:
            res = verify_assembly(args.output, raise_on_failure=False)
            return 0 if res["all_passed"] else 1
        except Exception as e:
            print(f"[-] Verification failed with error: {e}", file=sys.stderr)
            return 1

    try:
        assembled_file = assemble_video(
            input_dir=args.input_dir,
            audio_path=args.audio,
            output_path=args.output,
            color_grade=args.color_grade,
            crossfade=args.crossfade,
            trim_lead=args.trim_lead,
            conform_targets=args.conform_targets,
            target_duration=43.0,
        )

        if args.verify:
            res = verify_assembly(assembled_file, raise_on_failure=True)
            return 0 if res["all_passed"] else 1

        return 0

    except Exception as e:
        print(f"[-] Pipeline execution halted: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
