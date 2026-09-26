"""
tests/test_promo_peshta_m3_blueprint.py
=======================================
Verification suite for Milestone 3 (Requirement R3):
Higgsfield Execution Blueprint & Execution Manual.
"""

import ast
import re
from pathlib import Path
import pytest

# Anchored to this file, not to a home directory: these tests live inside the
# campaign they verify (marketing/campaigns/peshta/tests/), so both roots are
# derived from __file__ and the checkout can sit anywhere.
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
PROMO_DIR = WORKSPACE_ROOT / "marketing/campaigns/peshta"
BLUEPRINT_PATH = PROMO_DIR / "05_higgsfield_execution_blueprint.md"
MANUAL_PATH = PROMO_DIR / "05_higgsfield_execution_manual.md"
SETUP_PATH = PROMO_DIR / "05_HIGGSFIELD_RECREATION_SETUP.md"
DRIVING_DIR = PROMO_DIR / "driving_clips"
ASSETS_DIR = PROMO_DIR / "character_assets"


def test_blueprint_and_manual_exist():
    assert BLUEPRINT_PATH.exists(), f"Missing {BLUEPRINT_PATH}"
    assert BLUEPRINT_PATH.stat().st_size > 20000, "Blueprint file is suspiciously small"

    assert MANUAL_PATH.exists(), f"Missing {MANUAL_PATH}"
    manual_content = MANUAL_PATH.read_text(encoding="utf-8")
    blueprint_content = BLUEPRINT_PATH.read_text(encoding="utf-8")
    assert len(manual_content) == len(blueprint_content), "Manual and Blueprint content length mismatch"


def test_setup_file_ignored_and_untouched():
    """Ensure 05_HIGGSFIELD_RECREATION_SETUP.md was strictly ignored and not corrupted."""
    assert SETUP_PATH.exists(), "Setup file was deleted or moved"
    # Ensure our blueprint does NOT reference 05_HIGGSFIELD_RECREATION_SETUP.md
    blueprint_content = BLUEPRINT_PATH.read_text(encoding="utf-8")
    assert "05_HIGGSFIELD_RECREATION_SETUP" not in blueprint_content, (
        "Directive violation: 05_HIGGSFIELD_RECREATION_SETUP was referenced in blueprint"
    )


def test_all_11_clips_represented_in_blueprint():
    content = BLUEPRINT_PATH.read_text(encoding="utf-8")

    expected_clips = [
        "clip_01_verse1_setup.mp4",
        "clip_02_hook_duo_roses.mp4",
        "clip_03_chorus_drop_hero.mp4",
        "clip_04_call_response_1.mp4",
        "clip_05_call_response_2.mp4",
        "clip_06_strophe_swagger_strut.mp4",
        "clip_07_duo_charm_finger_wag.mp4",
        "clip_08_canyon_transition_stomp.mp4",
        "clip_09_canyon_double_point.mp4",
        "clip_10_elif_red_steps.mp4",
        "clip_11_polat_hero_outro.mp4",
    ]

    for clip in expected_clips:
        assert clip in content, f"Clip {clip} not documented in blueprint"


def test_character_cards_referenced():
    content = BLUEPRINT_PATH.read_text(encoding="utf-8")
    for card in ["Card P01", "Card P02", "Card P04", "Card E01", "Card E02", "Card E03"]:
        assert card in content, f"Character card {card} not referenced in blueprint"


def test_motion_strength_ranges():
    content = BLUEPRINT_PATH.read_text(encoding="utf-8")
    # Assert values in Section 2 table
    for strength in ["0.72", "0.76", "0.75", "0.74", "0.73", "0.70"]:
        assert strength in content, f"Motion strength {strength} not documented"


def test_beat_drop_calibration_values():
    content = BLUEPRINT_PATH.read_text(encoding="utf-8")
    assert "27.264" in content, "Start calibration t=27.264s missing"
    assert "34.184" in content, "Raw video drop t=34.184s missing"
    assert "6.920" in content, "Audio drop t=6.920s missing"
    assert "208" in content, "Drop frame index 208 missing"
    assert "1290" in content or "1,290" in content, "Frame count 1290 missing"


def test_card_p04_fedora_negative_prompt_exception():
    content = BLUEPRINT_PATH.read_text(encoding="utf-8")
    # For clip 08 and clip 09 (which use Card P04), hat and fedora must be unblocked
    canyon_sections = [
        content[content.find("Shot Profile: Clip 08"):content.find("Shot Profile: Clip 09")],
        content[content.find("Shot Profile: Clip 09"):content.find("Shot Profile: Clip 10")]
    ]
    for sec in canyon_sections:
        neg_section = sec.split("Negative Prompt")[1].split("Anticipated Challenges")[0]
        code_block = neg_section.split("```text")[1].split("```")[0]
        assert "hat" not in code_block, "hat was mistakenly left in Card P04 negative prompt code block!"
        assert "fedora" not in code_block, "fedora was mistakenly left in Card P04 negative prompt code block!"


def test_embedded_python_script_validity_and_dry_run():
    content = BLUEPRINT_PATH.read_text(encoding="utf-8")
    start = content.find("run_higgsfield_pipeline.py")
    code_start = content.find("```python\n", start) + 10
    code_end = content.find("\n```", code_start)
    code = content[code_start:code_end]

    # Verify AST syntax
    tree = ast.parse(code)
    assert tree is not None, "Failed to parse AST of embedded script"

    # Execute dry run in clean namespace
    ns = {}
    exec(code, ns)
    assert "SHOT_MANIFEST" in ns, "SHOT_MANIFEST missing from script namespace"
    assert len(ns["SHOT_MANIFEST"]) == 11, f"Expected 11 items in manifest, got {len(ns['SHOT_MANIFEST'])}"
