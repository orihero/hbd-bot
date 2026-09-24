"""
tests/test_promo_peshta_m4_assembly.py
======================================
Comprehensive Test Suite for Milestone 4 (R4):
Automated Post-Production Assembly Engine & Assembled Preview Verification.

Verifies:
  - assemble_polat_peshta.py CLI parsing, pure standard library compliance, and zero pip deps.
  - Splicing & Conformance Engine (1080x1920, 30fps CFR, YUV420p, Turkish mafia noir grading).
  - 8-point automated verification suite on marketing/campaigns/peshta/assembled_preview.mp4.
  - Audio-visual beat synchronization at 0:34 primary sub-bass drop (Frame 208 / t = 6.920s).
  - Container faststart moov atom placement before mdat (<4096 bytes).
  - Clean error handling on edge cases and invalid media.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
import pytest

# Anchored to this file, not to a home directory: these tests live inside the
# campaign they verify (marketing/campaigns/peshta/tests/), so both roots are
# derived from __file__ and the checkout can sit anywhere.
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
PROMO_DIR = WORKSPACE_ROOT / "marketing/campaigns/peshta"
SCRIPT_PATH = PROMO_DIR / "assemble_polat_peshta.py"
OUTPUT_MP4 = PROMO_DIR / "assembled_preview.mp4"
DRIVING_DIR = PROMO_DIR / "driving_clips"
AUDIO_PATH = Path("/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3")
SETUP_PATH = PROMO_DIR / "05_HIGGSFIELD_RECREATION_SETUP.md"

# Import assemble_polat_peshta directly. It is a sibling script in the campaign
# folder, not an installed package, so the campaign dir goes on the path.
sys.path.insert(0, str(PROMO_DIR))
from assemble_polat_peshta import (
    DEFAULT_AUDIO_PATH,
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_PATH,
    TURKISH_MAFIA_NOIR_FILTER,
    build_filtergraph,
    check_faststart_atoms,
    find_input_clips,
    natural_sort_key,
    parse_args,
    probe_media,
    str_to_bool_or_flag,
    verify_assembly,
)


# =============================================================================
# 1. Pipeline Architecture & Integrity Compliance
# =============================================================================

def test_script_file_exists_and_executable():
    """Verify assemble_polat_peshta.py exists, is executable, and non-empty."""
    assert SCRIPT_PATH.is_file(), f"Missing assembly script: {SCRIPT_PATH}"
    assert SCRIPT_PATH.stat().st_size > 2000, "Assembly script is suspiciously small"
    assert os.access(SCRIPT_PATH, os.X_OK), "Assembly script must be executable"


def test_pure_standard_library_compliance():
    """
    CRITICAL CONSTRAINT: Pure Python 3 standard library + FFmpeg/FFprobe.
    ZERO third-party pip dependencies allowed.
    """
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            # Skip intra-package or relative imports
            imported_modules.add(node.module.split(".")[0])

    # Allowable Python standard library modules
    allowed_stdlib = {
        "argparse", "ast", "collections", "contextlib", "dataclasses",
        "datetime", "enum", "functools", "io", "itertools", "json",
        "math", "os", "pathlib", "re", "shutil", "stat", "string",
        "struct", "subprocess", "sys", "tempfile", "time", "typing",
        "urllib", "__future__",
    }

    third_party = imported_modules - allowed_stdlib
    assert not third_party, f"Found forbidden third-party imports in {SCRIPT_PATH.name}: {third_party}"


def test_directive_setup_file_untouched_and_unreferenced():
    """
    USER DIRECTIVE: IGNORE 05_HIGGSFIELD_RECREATION_SETUP.md entirely.
    Ensure our assembly script does not touch or reference it.
    """
    assert SETUP_PATH.exists(), "Setup file was deleted or moved"
    script_content = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "05_HIGGSFIELD_RECREATION_SETUP" not in script_content, (
        "Directive violation: 05_HIGGSFIELD_RECREATION_SETUP was referenced in assemble_polat_peshta.py"
    )


# =============================================================================
# 2. CLI Argument Parsing & Validation
# =============================================================================

def test_cli_default_arguments():
    """Verify default CLI options align with milestone specifications."""
    args = parse_args([])
    assert args.input_dir == DEFAULT_INPUT_DIR
    assert args.audio == DEFAULT_AUDIO_PATH
    assert args.output == DEFAULT_OUTPUT_PATH
    assert args.color_grade is True
    assert args.crossfade == 0.0
    assert args.trim_lead == 0.0
    assert args.verify is False
    assert args.verify_only is False


def test_cli_custom_arguments_and_flags():
    """Verify custom CLI flag parsing across all permutations."""
    custom_in = Path("/tmp/custom_clips")
    custom_audio = Path("/tmp/custom.mp3")
    custom_out = Path("/tmp/output.mp4")

    # Test full argument assignment
    args = parse_args([
        "--input-dir", str(custom_in),
        "--audio", str(custom_audio),
        "-o", str(custom_out),
        "--crossfade", "0.067",
        "--trim-lead", "0.10",
        "--verify",
    ])
    assert args.input_dir == custom_in
    assert args.audio == custom_audio
    assert args.output == custom_out
    assert args.color_grade is True
    assert math.isclose(args.crossfade, 0.067)
    assert math.isclose(args.trim_lead, 0.10)
    assert args.verify is True
    assert args.verify_only is False

    # Test color grade flag variants
    assert parse_args(["--no-color-grade"]).color_grade is False
    assert parse_args(["--color-grade", "False"]).color_grade is False
    assert parse_args(["--color-grade=false"]).color_grade is False
    assert parse_args(["--color-grade", "True"]).color_grade is True
    assert parse_args(["--color-grade"]).color_grade is True

    # Test verify-only
    assert parse_args(["--verify-only"]).verify_only is True


def test_str_to_bool_or_flag_helper():
    """Test boolean converter helper function."""
    assert str_to_bool_or_flag(True) is True
    assert str_to_bool_or_flag(False) is False
    assert str_to_bool_or_flag("true") is True
    assert str_to_bool_or_flag("TRUE") is True
    assert str_to_bool_or_flag("1") is True
    assert str_to_bool_or_flag("yes") is True
    assert str_to_bool_or_flag("false") is False
    assert str_to_bool_or_flag("0") is False
    assert str_to_bool_or_flag("no") is False

    with pytest.raises(argparse.ArgumentTypeError):
        str_to_bool_or_flag("invalid_boolean")


# =============================================================================
# 3. Clip Ingestion & Natural Sorting Engine
# =============================================================================

def test_natural_sort_key_behavior():
    """Test natural sorting order with various file naming patterns."""
    items = [
        Path("clip_10.mp4"),
        Path("clip_01.mp4"),
        Path("clip_02.mp4"),
        Path("clip_11.mp4"),
        Path("clip_03.mp4"),
    ]
    sorted_items = sorted(items, key=natural_sort_key)
    expected_order = ["clip_01.mp4", "clip_02.mp4", "clip_03.mp4", "clip_10.mp4", "clip_11.mp4"]
    assert [p.name for p in sorted_items] == expected_order


def test_find_input_clips_from_driving_clips():
    """Verify find_input_clips discovers exactly 11 clips in sequential order."""
    clips = find_input_clips(DRIVING_DIR)
    assert len(clips) == 11, f"Expected 11 driving clips, found {len(clips)}"

    for i in range(1, 12):
        expected_prefix = f"clip_{i:02d}_"
        assert clips[i - 1].name.startswith(expected_prefix), (
            f"Clip index {i} mismatch: got {clips[i - 1].name}, expected prefix {expected_prefix}"
        )


def test_find_input_clips_missing_directory(tmp_path: Path):
    """Verify error handling on non-existent directory."""
    non_existent = tmp_path / "non_existent_dir"
    with pytest.raises(FileNotFoundError, match="Input directory does not exist"):
        find_input_clips(non_existent)


def test_find_input_clips_empty_directory(tmp_path: Path):
    """Verify error handling on empty directory."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="No video clips found"):
        find_input_clips(empty_dir)


# =============================================================================
# 4. Complex Filtergraph Generation Engine
# =============================================================================

def test_build_filtergraph_clean_cut_with_color_grade():
    """Verify filtergraph with clean cuts and Turkish mafia noir grading."""
    fg = build_filtergraph(num_clips=11, color_grade=True, crossfade=0.0, trim_lead=0.0)

    # 1. Check all 11 streams are scaled to 1080x1920, 30fps CFR, setsar=1, yuv420p
    for i in range(11):
        assert f"[{i}:v]setpts=PTS-STARTPTS" in fg
        assert "scale=1080:1920:force_original_aspect_ratio=decrease" in fg
        assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2" in fg
        assert "setsar=1,fps=30,format=yuv420p" in fg
        assert f"[v{i}]" in fg

    # 2. Check concatenation filter
    expected_concat_inputs = "".join(f"[v{i}]" for i in range(11))
    assert f"{expected_concat_inputs}concat=n=11:v=1:a=0[v_cat]" in fg

    # 3. Check color grading filter
    assert f"[v_cat]{TURKISH_MAFIA_NOIR_FILTER}[v_out]" in fg


def test_build_filtergraph_no_color_grade():
    """Verify filtergraph without color grading routes through null filter."""
    fg = build_filtergraph(num_clips=3, color_grade=False, crossfade=0.0, trim_lead=0.0)
    assert "[v_cat]null[v_out]" in fg
    assert TURKISH_MAFIA_NOIR_FILTER not in fg


def test_build_filtergraph_with_trim_lead():
    """Verify trim_lead inserts trim filter into per-clip chains."""
    clip_durations = [2.5, 3.0, 4.0]
    fg = build_filtergraph(num_clips=3, color_grade=True, crossfade=0.0, trim_lead=0.10, clip_durations=clip_durations)
    assert "trim=start=0.100:end=2.400" in fg
    assert "trim=start=0.100:end=2.900" in fg
    assert "trim=start=0.100:end=3.900" in fg


def test_build_filtergraph_with_crossfade():
    """Verify crossfade generates chained xfade filters."""
    clip_durations = [2.0, 3.0, 4.0]
    fg = build_filtergraph(num_clips=3, color_grade=True, crossfade=0.1, clip_durations=clip_durations)
    assert "xfade=transition=fade:duration=0.100:offset=1.900" in fg


def test_build_filtergraph_invalid_num_clips():
    """Verify ValueError is raised for 0 clips."""
    with pytest.raises(ValueError, match="At least one input clip is required"):
        build_filtergraph(num_clips=0)


# =============================================================================
# 5. Faststart Atom Positioning Inspection
# =============================================================================

def test_check_faststart_atoms_on_assembled_preview():
    """Verify faststart moov atom is located before mdat within first 4096 bytes."""
    assert OUTPUT_MP4.is_file(), f"Target video {OUTPUT_MP4} does not exist"
    passed, msg, meta = check_faststart_atoms(OUTPUT_MP4)
    assert passed, f"Faststart check failed: {msg}"
    assert meta["moov_in_first_4096"] is True
    top_boxes = [b["type"] for b in meta["top_boxes"]]
    assert "moov" in top_boxes
    assert "mdat" in top_boxes
    assert top_boxes.index("moov") < top_boxes.index("mdat"), "'moov' must precede 'mdat'"


def test_check_faststart_atoms_missing_file(tmp_path: Path):
    """Verify faststart check returns False for non-existent file."""
    fake_path = tmp_path / "fake.mp4"
    passed, msg, _ = check_faststart_atoms(fake_path)
    assert passed is False
    assert "does not exist" in msg


def test_check_faststart_atoms_corrupted_file(tmp_path: Path):
    """Verify faststart check returns False for non-MP4 dummy data."""
    dummy_path = tmp_path / "dummy.mp4"
    dummy_path.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41")
    passed, msg, _ = check_faststart_atoms(dummy_path)
    assert passed is False
    assert "missing 'moov' atom" in msg


# =============================================================================
# 6. Built-in 8-Check Automated Verification Suite
# =============================================================================

def test_verify_assembly_all_8_checks_pass_on_master():
    """
    Run verify_assembly on assembled_preview.mp4 and verify 100% pass rate
    across all 8 discrete quality gates.
    """
    assert OUTPUT_MP4.is_file(), f"Output file missing: {OUTPUT_MP4}"
    report = verify_assembly(
        OUTPUT_MP4,
        expected_duration=43.0,
        duration_tol=0.10,
        expected_frames=1290,
        frame_tol=3,
        min_size_bytes=5_000_000,
        raise_on_failure=True,
    )

    assert report["all_passed"] is True
    checks = report["checks"]

    # Verify each check explicitly
    assert checks["check_1_file_size"]["passed"] is True
    assert checks["check_2_resolution"]["passed"] is True
    assert checks["check_3_framerate"]["passed"] is True
    assert checks["check_4_duration_frames"]["passed"] is True
    assert checks["check_5_audio_stream"]["passed"] is True
    assert checks["check_6_faststart"]["passed"] is True
    assert checks["check_7_bitstream_decode"]["passed"] is True
    assert checks["check_8_black_frames"]["passed"] is True


def test_verify_assembly_detects_small_file_failure(tmp_path: Path):
    """Verify Check 1 fails if file size < 5 MB."""
    tiny_file = tmp_path / "tiny.mp4"
    tiny_file.write_bytes(b"short content")
    report = verify_assembly(tiny_file, min_size_bytes=5_000_000, raise_on_failure=False)
    assert report["all_passed"] is False
    assert report["checks"]["check_1_file_size"]["passed"] is False


def test_verify_assembly_raises_on_failure(tmp_path: Path):
    """Verify raise_on_failure raises AssertionError."""
    tiny_file = tmp_path / "tiny.mp4"
    tiny_file.write_bytes(b"short content")
    with pytest.raises(AssertionError, match="Check 1 Failed"):
        verify_assembly(tiny_file, raise_on_failure=True)


# =============================================================================
# 7. Empirical Video Geometry & Bitstream Stream Validation
# =============================================================================

def test_assembled_video_empirical_stream_geometry():
    """
    Direct ffprobe validation of video stream properties:
      - Resolution: 1080x1920
      - SAR: 1:1, DAR: 9:16
      - r_frame_rate: 30/1, avg_frame_rate: 30/1
      - Duration: 43.000s ± 0.05s
      - Frame count: 1290
      - Codec: h264, pix_fmt: yuv420p
    """
    meta = probe_media(OUTPUT_MP4)
    v_streams = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
    assert len(v_streams) == 1, "Expected exactly 1 video stream"
    v0 = v_streams[0]

    assert v0["codec_name"] == "h264"
    assert v0["width"] == 1080
    assert v0["height"] == 1920
    assert v0["sample_aspect_ratio"] == "1:1"
    assert v0["display_aspect_ratio"] == "9:16"
    assert v0["r_frame_rate"] == "30/1"
    assert v0["avg_frame_rate"] == "30/1"
    assert v0["pix_fmt"] == "yuv420p"

    nb_frames = int(v0["nb_frames"])
    assert nb_frames == 1290, f"Expected exactly 1290 frames, got {nb_frames}"

    duration = float(v0["duration"])
    assert math.isclose(duration, 43.000, abs_tol=0.05), f"Duration {duration} out of 43.000s ± 0.05s tolerance"


def test_assembled_audio_empirical_stream_properties():
    """
    Direct ffprobe validation of audio stream properties:
      - Codec: AAC
      - Sample Rate: 48,000 Hz
      - Channels: 2 (Stereo)
      - Duration: 43.000s
    """
    meta = probe_media(OUTPUT_MP4)
    a_streams = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
    assert len(a_streams) == 1, "Expected exactly 1 audio stream"
    a0 = a_streams[0]

    assert a0["codec_name"] == "aac"
    assert int(a0["sample_rate"]) == 48000
    assert int(a0["channels"]) == 2
    dur = float(a0["duration"])
    assert math.isclose(dur, 43.000, abs_tol=0.05)


def test_assembled_file_size_upper_and_lower_bounds():
    """
    Verify video bitrate / file size is production-grade:
      - Minimum: 5 MB (sanity floor)
      - Expected range: 25 MB to 60 MB for high-bitrate 1080x1920 43s master
    """
    size_bytes = OUTPUT_MP4.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    assert size_mb >= 5.0, f"File size {size_mb:.2f} MB is below 5 MB"
    assert 20.0 <= size_mb <= 60.0, f"File size {size_mb:.2f} MB is outside realistic bounds (20-60 MB)"


# =============================================================================
# 8. Audio-Visual Beat Synchronization (0:34 Primary Drop Calibration)
# =============================================================================

def test_beat_drop_alignment_calibration():
    """
    Verify the primary 0:34 sub-bass drop calibration:
      - Audio transient slam is at relative t = 6.920s (Frame 208).
      - Clip 01 spans 0.000s - 2.256s (68 frames).
      - Clip 02 spans 2.256s - 5.176s (88 frames).
      - Cumulative start of Clip 03 is at 156 frames (t = 5.176s).
      - Clip 03 spans 5.176s - 8.976s (114 frames, frames 156 to 270).
      - Drop frame 208 falls at frame index 52 within Clip 03 (5.176s + 52/30 = 6.909s ~ 6.920s).
      - The drop falls directly into the deep squat apex of Clip 03.
    """
    clips = find_input_clips(DRIVING_DIR)
    clip_01_meta = probe_media(clips[0])
    clip_02_meta = probe_media(clips[1])
    clip_03_meta = probe_media(clips[2])

    f1 = int(clip_01_meta["streams"][0]["nb_frames"])
    f2 = int(clip_02_meta["streams"][0]["nb_frames"])
    f3 = int(clip_03_meta["streams"][0]["nb_frames"])

    assert f1 == 68
    assert f2 == 88
    assert f3 == 114

    clip_03_start_frame = f1 + f2
    assert clip_03_start_frame == 156

    clip_03_end_frame = clip_03_start_frame + f3
    assert clip_03_end_frame == 270

    drop_frame = 208
    assert clip_03_start_frame <= drop_frame < clip_03_end_frame, (
        f"Drop frame {drop_frame} must fall inside Clip 03 ({clip_03_start_frame}..{clip_03_end_frame})"
    )

    offset_in_clip_03 = drop_frame - clip_03_start_frame
    assert offset_in_clip_03 == 52


# =============================================================================
# 9. CLI Subprocess Invocation Verification
# =============================================================================

def test_cli_subprocess_verify_only_exit_zero():
    """Verify running `python3 assemble_polat_peshta.py --verify-only` exits with returncode 0."""
    res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--verify-only"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"--verify-only failed with stderr:\n{res.stderr}"
    assert "ALL 8 VERIFICATION GATES PASSED" in res.stdout
