#!/usr/bin/env python3
"""
validate_deliverables.py — Programmatic verification harness for marketing/campaigns/viral-ideas/

Strictly verifies:
1. Deliverable file existence and non-empty size across all 6 core deliverables.
2. Zero-tolerance placeholder scanner across all markdown (.md) and Python (.py) files.
3. Structural header hierarchy (H1, H2, H3, H4) in each markdown deliverable.
4. Quantitative quotas:
   - File 01: >= 5 platforms evaluated + comparison matrix table.
   - File 02: >= 6 case studies with complete hook, retention, cultural trigger, audio,
              and velocity breakdowns.
   - File 03: >= 10 (assert >= 10, target 12) complete concept cards with verbatim
              bilingual hooks (Uzbek Latin & Russian).
   - File 04: All 4 weekly monitoring SOP steps present and detailed.
   - README: Master index table, project summary, and cross-links to all deliverables.

Exit Code Invariant:
- Code 0: 100% compliance across all gates.
- Code 1: Any assertion or verification failure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DELIVERABLE_DIR = Path(__file__).resolve().parent

# ANSI Color escapes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Required deliverable files in marketing/campaigns/viral-ideas/
REQUIRED_FILES = [
    "01_PLATFORM_INTELLIGENCE_AUDIT.md",
    "02_UZBEK_VIRAL_CASE_STUDIES.md",
    "03_BAYRAM_BOT_VIRAL_CONCEPTS.md",
    "04_WEEKLY_MONITORING_SOP.md",
    "README.md",
    "validate_deliverables.py",
]

# Patterns constructed via token concatenation to prevent false-positive self-matching
FORBIDDEN_PATTERN_SPECS = [
    (r"\b" + "TO" + "DO" + r"\b", "Unfinished to-do task marker"),
    (r"\b" + "TB" + "D" + r"\b", "Unfinished to-be-determined marker"),
    (r"\b" + "FIX" + "ME" + r"\b", "Unfinished fix-me marker"),
    (r"\[in" + r"sert\b.*?\]", "Bracketed insert tag"),
    (r"\[place" + r"holder\b.*?\]", "Bracketed placeholder tag"),
    (r"\[your" + r"_.*?\]", "Bracketed your_* tag"),
    (r"\bLorem" + r" ipsum\b", "Dummy Latin filler text"),
    (r"\bX" + r"X,XXX\b", "Uncalculated numeric mask (5-digit)"),
    (r"\bY" + r"Y,YYY\b", "Uncalculated numeric mask (alternate)"),
    (r"\bexam" + r"ple\.com\b", "Generic example domain"),
]


class ValidationReporter:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.passes: list[str] = []

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        print(f"  {RED}[FAIL]{RESET} {message}")

    def add_pass(self, message: str) -> None:
        self.passes.append(message)
        print(f"  {GREEN}[PASS]{RESET} {message}")

    def is_successful(self) -> bool:
        return len(self.errors) == 0


def check_file_existence(reporter: ValidationReporter) -> None:
    """Verifies that all 6 required deliverable files exist and have non-zero size."""
    for filename in REQUIRED_FILES:
        filepath = DELIVERABLE_DIR / filename
        if not filepath.is_file():
            reporter.add_error(f"Missing required file: {filename}")
        elif filepath.stat().st_size == 0:
            reporter.add_error(f"Required file is empty (0 bytes): {filename}")
        else:
            reporter.add_pass(f"File present ({filepath.stat().st_size:,} bytes): {filename}")


def check_placeholders(reporter: ValidationReporter) -> None:
    """Scans all .md and .py files in marketing/campaigns/viral-ideas/ for forbidden placeholder patterns."""
    compiled_patterns = [
        (re.compile(pattern, re.IGNORECASE), label)
        for pattern, label in FORBIDDEN_PATTERN_SPECS
    ]

    target_files = sorted(
        list(DELIVERABLE_DIR.glob("*.md")) + list(DELIVERABLE_DIR.glob("*.py"))
    )
    found_placeholders = 0

    for file_path in target_files:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            reporter.add_error(f"Could not read {file_path.name} as UTF-8: {exc}")
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            # In validate_deliverables.py itself, skip pattern definition lines
            if file_path.name == "validate_deliverables.py" and (
                "FORBIDDEN" in line
                or "pattern" in line.lower()
                or "token concatenation" in line
            ):
                continue

            for regex, label in compiled_patterns:
                match = regex.search(line)
                if match:
                    found_placeholders += 1
                    reporter.add_error(
                        f"Forbidden placeholder ({label}) in "
                        f"{file_path.name}:{line_no} -> '{line.strip()}'"
                    )

    if found_placeholders == 0:
        reporter.add_pass(
            f"Zero forbidden placeholders detected across {len(target_files)} "
            "inspected files (.md & .py)"
        )


def check_doc_01_platform_audit(reporter: ValidationReporter) -> None:
    """Validates 01_PLATFORM_INTELLIGENCE_AUDIT.md structure and platform quota."""
    filepath = DELIVERABLE_DIR / "01_PLATFORM_INTELLIGENCE_AUDIT.md"
    if not filepath.exists():
        reporter.add_error("01_PLATFORM_INTELLIGENCE_AUDIT.md does not exist for inspection")
        return

    text = filepath.read_text(encoding="utf-8")

    # Header checks
    required_sections = [
        ("Executive Summary", r"(?i)##\s+1\.\s+Executive\s+Summary"),
        ("Social Landscape", r"(?i)##\s+2\.\s+The\s+Uzbek\s+Social\s+Landscape"),
        (
            "Comparison Matrix",
            r"(?i)##\s+3\.\s+Comprehensive\s+Platform\s+Benchmarking\s+Matrix",
        ),
        ("Platform Audits", r"(?i)##\s+4\.\s+In-Depth\s+Platform\s+Audits"),
        ("Mathematical Formulations", r"(?i)##\s+5\.\s+Mathematical\s+Formulations"),
        ("Monitoring Stack", r"(?i)##\s+6\.\s+Recommended\s+3-Tier\s+Hybrid\s+Monitoring"),
    ]
    for section_name, pattern in required_sections:
        if not re.search(pattern, text):
            reporter.add_error(
                f"01_PLATFORM_INTELLIGENCE_AUDIT.md: missing required header '{section_name}'"
            )
        else:
            reporter.add_pass(
                f"01_PLATFORM_INTELLIGENCE_AUDIT.md: verified section '{section_name}'"
            )

    # Platforms evaluated quota (>= 5 platforms)
    platforms = re.findall(
        r"(?i)###\s+(?:4\.\d+\s+|Platform\s+\d+:?\s*)"
        r"(?:LiveDune|Popsters|HypeAuditor|TGStat|YouTube|VidIQ|[A-Z][a-zA-Z0-9\s/]+)",
        text,
    )
    if len(platforms) < 5:
        reporter.add_error(
            "01_PLATFORM_INTELLIGENCE_AUDIT.md: found "
            f"{len(platforms)} platform evaluations (expected >= 5)"
        )
    else:
        reporter.add_pass(
            "01_PLATFORM_INTELLIGENCE_AUDIT.md: platform quota met "
            f"({len(platforms)} platforms evaluated >= 5)"
        )

    # Comparison matrix table check
    if "|" not in text or "---" not in text:
        reporter.add_error(
            "01_PLATFORM_INTELLIGENCE_AUDIT.md: missing benchmarking matrix markdown table"
        )
    else:
        reporter.add_pass(
            "01_PLATFORM_INTELLIGENCE_AUDIT.md: benchmarking matrix markdown table present"
        )


def check_doc_02_case_studies(reporter: ValidationReporter) -> None:
    """Validates 02_UZBEK_VIRAL_CASE_STUDIES.md structure, quotas, and case elements."""
    filepath = DELIVERABLE_DIR / "02_UZBEK_VIRAL_CASE_STUDIES.md"
    if not filepath.exists():
        reporter.add_error("02_UZBEK_VIRAL_CASE_STUDIES.md does not exist for inspection")
        return

    text = filepath.read_text(encoding="utf-8")

    # Header checks
    if not re.search(r"(?i)##\s+1\.\s+Executive\s+Summary", text):
        reporter.add_error("02_UZBEK_VIRAL_CASE_STUDIES.md: missing Executive Summary header")
    else:
        reporter.add_pass("02_UZBEK_VIRAL_CASE_STUDIES.md: verified Executive Summary header")

    # Quota check: at least 6 distinct case studies
    case_headers = re.findall(r"(?i)###\s+Case\s+Study\s+\d+", text)
    if len(case_headers) < 6:
        reporter.add_error(
            f"02_UZBEK_VIRAL_CASE_STUDIES.md: found {len(case_headers)} "
            "case studies (expected >= 6)"
        )
    else:
        reporter.add_pass(
            "02_UZBEK_VIRAL_CASE_STUDIES.md: case studies quota met "
            f"({len(case_headers)} case studies analyzed >= 6)"
        )

    # Verify structural requirements across case studies
    sub_requirements = [
        ("3-Second Hook Architecture", r"(?i)####\s+(?:\d+\.\s+)?3-Second\s+Hook"),
        ("Narrative Pacing & Retention", r"(?i)####\s+(?:\d+\.\s+)?Narrative\s+Pacing"),
        ("Uzbek Cultural & Linguistic Triggers", r"(?i)####\s+(?:\d+\.\s+)?Uzbek\s+Cultural"),
        ("Audio Source Classification", r"(?i)####\s+(?:\d+\.\s+)?Audio\s+Source"),
        ("Velocity & Engagement Metrics", r"(?i)####\s+(?:\d+\.\s+)?Velocity\s+&\s+Engagement"),
    ]

    for req_name, req_pattern in sub_requirements:
        matches = re.findall(req_pattern, text)
        if len(matches) < 6:
            reporter.add_error(
                f"02_UZBEK_VIRAL_CASE_STUDIES.md: found {len(matches)} sections "
                f"for '{req_name}' (expected >= 6)"
            )
        else:
            reporter.add_pass(
                f"02_UZBEK_VIRAL_CASE_STUDIES.md: verified {len(matches)} "
                f"'{req_name}' sections across cases"
            )


def check_doc_03_viral_concepts(reporter: ValidationReporter) -> None:
    """Validates 03_BAYRAM_BOT_VIRAL_CONCEPTS.md concepts quota and bilingual scripts."""
    filepath = DELIVERABLE_DIR / "03_BAYRAM_BOT_VIRAL_CONCEPTS.md"
    if not filepath.exists():
        reporter.add_error("03_BAYRAM_BOT_VIRAL_CONCEPTS.md does not exist for inspection")
        return

    text = filepath.read_text(encoding="utf-8")

    # Structural sections
    sections = [
        ("Product Proposition", r"(?i)##\s+1\.\s+Bayram\s+Bot\s+Product\s+Proposition"),
        ("Audio Compliance", r"(?i)##\s+2\.\s+Audio\s+Compliance"),
        ("Viral Concept Template", r"(?i)##\s+3\.\s+Viral\s+Concept\s+Architecture\s+Template"),
        (
            "Concept Cards Section",
            r"(?i)##\s+(?:4|5)\.\s+.*?(?:Concept\s+Cards|Concept\s+Blueprints)",
        ),
    ]
    for sec_name, sec_regex in sections:
        if not re.search(sec_regex, text):
            reporter.add_error(f"03_BAYRAM_BOT_VIRAL_CONCEPTS.md: missing section '{sec_name}'")
        else:
            reporter.add_pass(f"03_BAYRAM_BOT_VIRAL_CONCEPTS.md: verified section '{sec_name}'")

    # Concept cards count (assert >= 10, target is 12)
    concept_headers = re.findall(r"(?i)###\s+Concept\s+\d+[:\s]", text)
    if len(concept_headers) < 10:
        reporter.add_error(
            f"03_BAYRAM_BOT_VIRAL_CONCEPTS.md: found {len(concept_headers)} "
            "concepts (expected >= 10, target 12)"
        )
    else:
        reporter.add_pass(
            "03_BAYRAM_BOT_VIRAL_CONCEPTS.md: concept quota met "
            f"({len(concept_headers)} complete concept cards >= 10)"
        )

    # Bilingual verbatim hook verification (aggregate quota check)
    uz_hooks = re.findall(
        r"(?i)(?:Uzbek\s+Latin|Spoken.*?Uzbek).*?[:\-]\s*[\"“].+?[\"”]", text
    )
    ru_hooks = re.findall(
        r"(?i)(?:Russian|Spoken.*?Russian).*?[:\-]\s*[\"“].+?[\"”]", text
    )

    if len(uz_hooks) < 10:
        reporter.add_error(
            f"03_BAYRAM_BOT_VIRAL_CONCEPTS.md: found {len(uz_hooks)} "
            "verbatim Uzbek hooks (expected >= 10)"
        )
    else:
        reporter.add_pass(
            f"03_BAYRAM_BOT_VIRAL_CONCEPTS.md: verified {len(uz_hooks)} "
            "verbatim Uzbek Latin spoken hooks"
        )

    if len(ru_hooks) < 10:
        reporter.add_error(
            f"03_BAYRAM_BOT_VIRAL_CONCEPTS.md: found {len(ru_hooks)} "
            "verbatim Russian hooks (expected >= 10)"
        )
    else:
        reporter.add_pass(
            f"03_BAYRAM_BOT_VIRAL_CONCEPTS.md: verified {len(ru_hooks)} "
            "verbatim Russian spoken hooks"
        )

    # Bilingual verbatim hook verification (enforced per concept card)
    concept_blocks = re.split(r"(?i)###\s+Concept\s+\d+[:\s]", text)[1:]
    missing_uz = []
    missing_ru = []
    for idx, card in enumerate(concept_blocks, 1):
        if not re.search(
            r"-\s+\*\*Spoken Audio Script \(Uzbek Latin\)\*\*:\s*[\"“].+?[\"”]",
            card,
        ):
            missing_uz.append(idx)
        if not re.search(
            r"-\s+\*\*Spoken Audio Script \(Russian\)\*\*:\s*[\"“].+?[\"”]",
            card,
        ):
            missing_ru.append(idx)

    if missing_uz:
        reporter.add_error(
            "03_BAYRAM_BOT_VIRAL_CONCEPTS.md: missing verbatim Uzbek Latin spoken hook "
            f"in concepts: {missing_uz}"
        )
    else:
        reporter.add_pass(
            "03_BAYRAM_BOT_VIRAL_CONCEPTS.md: verified verbatim Uzbek Latin spoken hooks "
            f"across all {len(concept_blocks)} concepts"
        )

    if missing_ru:
        reporter.add_error(
            "03_BAYRAM_BOT_VIRAL_CONCEPTS.md: missing verbatim Russian spoken hook "
            f"in concepts: {missing_ru}"
        )
    else:
        reporter.add_pass(
            "03_BAYRAM_BOT_VIRAL_CONCEPTS.md: verified verbatim Russian spoken hooks "
            f"across all {len(concept_blocks)} concepts"
        )

    # Sub-sections per concept card check
    concept_subsections = [
        ("Hook (0–3s)", r"(?i)####\s+1\.\s+Hook"),
        ("Body Narrative (3–30s)", r"(?i)####\s+2\.\s+Body\s+Narrative"),
        ("Call-to-Action", r"(?i)####\s+3\.\s+Call-to-Action"),
        ("Audio & Sound Strategy", r"(?i)####\s+4\.\s+Audio\s+&\s+Sound\s+Strategy"),
    ]
    for sub_name, sub_regex in concept_subsections:
        matches = re.findall(sub_regex, text)
        if len(matches) < 10:
            reporter.add_error(
                f"03_BAYRAM_BOT_VIRAL_CONCEPTS.md: found {len(matches)} "
                f"sections for '{sub_name}' (expected >= 10)"
            )
        else:
            reporter.add_pass(
                f"03_BAYRAM_BOT_VIRAL_CONCEPTS.md: verified {len(matches)} "
                f"'{sub_name}' sub-sections"
            )

    # Check for brand handle and price reference
    if "@bayram_uzbot" not in text:
        reporter.add_error(
            "03_BAYRAM_BOT_VIRAL_CONCEPTS.md: missing product handle '@bayram_uzbot'"
        )
    else:
        reporter.add_pass(
            "03_BAYRAM_BOT_VIRAL_CONCEPTS.md: verified '@bayram_uzbot' handle presence"
        )

    if not re.search(r"15[\s,]000", text):
        reporter.add_error(
            "03_BAYRAM_BOT_VIRAL_CONCEPTS.md: missing fixed pricing reference '15 000' or '15,000'"
        )
    else:
        reporter.add_pass(
            "03_BAYRAM_BOT_VIRAL_CONCEPTS.md: verified fixed 15,000 UZS pricing presence"
        )


def check_doc_04_monitoring_sop(reporter: ValidationReporter) -> None:
    """Validates 04_WEEKLY_MONITORING_SOP.md steps and operational details."""
    filepath = DELIVERABLE_DIR / "04_WEEKLY_MONITORING_SOP.md"
    if not filepath.exists():
        reporter.add_error("04_WEEKLY_MONITORING_SOP.md does not exist for inspection")
        return

    text = filepath.read_text(encoding="utf-8")

    # Verify all 4 SOP steps are present
    sop_steps = [
        ("Step 1: Systematic Discovery", r"(?i)##\s+2\.\s+Step\s+1:\s+Systematic\s+Discovery"),
        (
            "Step 2: Velocity Tracking & Filtering",
            r"(?i)##\s+3\.\s+Step\s+2:\s+Velocity\s+Tracking",
        ),
        (
            "Step 3: Sound & Cultural Deconstruction",
            r"(?i)##\s+4\.\s+Step\s+3:\s+Sound\s+&\s+Cultural",
        ),
        (
            "Step 4: Rapid Content Production Sprint",
            r"(?i)##\s+5\.\s+Step\s+4:\s+Rapid\s+Content\s+Production",
        ),
    ]

    for step_title, step_regex in sop_steps:
        if not re.search(step_regex, text):
            reporter.add_error(
                f"04_WEEKLY_MONITORING_SOP.md: missing required header '{step_title}'"
            )
        else:
            reporter.add_pass(
                f"04_WEEKLY_MONITORING_SOP.md: verified SOP step '{step_title}'"
            )

    # Verify quantitative velocity formulas exist
    formulas = ["Views Per Hour", "Velocity Delta", "Share-to-Like", "Comment-to-View"]
    for formula in formulas:
        if formula.lower() not in text.lower():
            reporter.add_error(
                f"04_WEEKLY_MONITORING_SOP.md: missing velocity metric/formula '{formula}'"
            )
        else:
            reporter.add_pass(
                f"04_WEEKLY_MONITORING_SOP.md: verified velocity formula '{formula}'"
            )


def check_doc_readme(reporter: ValidationReporter) -> None:
    """Validates README.md master index, summary, and cross-linking."""
    filepath = DELIVERABLE_DIR / "README.md"
    if not filepath.exists():
        reporter.add_error("README.md does not exist for inspection")
        return

    text = filepath.read_text(encoding="utf-8")

    # Check cross-links to deliverables
    expected_links = [
        "01_PLATFORM_INTELLIGENCE_AUDIT.md",
        "02_UZBEK_VIRAL_CASE_STUDIES.md",
        "03_BAYRAM_BOT_VIRAL_CONCEPTS.md",
        "04_WEEKLY_MONITORING_SOP.md",
        "validate_deliverables.py",
    ]

    for link in expected_links:
        if link not in text:
            reporter.add_error(f"README.md: missing cross-reference or link to '{link}'")
        else:
            reporter.add_pass(f"README.md: verified cross-reference to '{link}'")

    # Check for index table
    if "|" not in text or "---" not in text:
        reporter.add_error("README.md: missing markdown deliverables table")
    else:
        reporter.add_pass("README.md: verified deliverables markdown index table")

    # Check for core product concepts
    if "@bayram_uzbot" not in text:
        reporter.add_error("README.md: missing product handle '@bayram_uzbot'")
    else:
        reporter.add_pass("README.md: verified product handle '@bayram_uzbot'")

    if not re.search(r"15[\s,]000", text):
        reporter.add_error("README.md: missing pricing reference '15 000' or '15,000'")
    else:
        reporter.add_pass("README.md: verified fixed 15,000 UZS pricing reference")


def main() -> int:
    print(f"\n{BOLD}{CYAN}{'=' * 76}{RESET}")
    print(
        f"{BOLD}{CYAN}BAYRAM BOT VIRAL DELIVERABLES PROGRAMMATIC VERIFICATION HARNESS{RESET}"
    )
    print(f"Target Directory: {DELIVERABLE_DIR}")
    print(f"{BOLD}{CYAN}{'=' * 76}{RESET}\n")

    reporter = ValidationReporter()

    print(f"{BOLD}[Gate 1/5] Checking Deliverable File Existence & Size...{RESET}")
    check_file_existence(reporter)

    print(
        f"\n{BOLD}[Gate 2/5] Running Zero-Tolerance Placeholder Scanner (.md & .py)...{RESET}"
    )
    check_placeholders(reporter)

    print(f"\n{BOLD}[Gate 3/5] Validating 01_PLATFORM_INTELLIGENCE_AUDIT.md...{RESET}")
    check_doc_01_platform_audit(reporter)

    print(
        f"\n{BOLD}[Gate 4/5] Validating 02_UZBEK_VIRAL_CASE_STUDIES.md & 03_CONCEPTS.md...{RESET}"
    )
    check_doc_02_case_studies(reporter)
    check_doc_03_viral_concepts(reporter)

    print(f"\n{BOLD}[Gate 5/5] Validating 04_WEEKLY_MONITORING_SOP.md & README.md...{RESET}")
    check_doc_04_monitoring_sop(reporter)
    check_doc_readme(reporter)

    print(f"\n{BOLD}{CYAN}{'=' * 76}{RESET}")
    print(
        f"{BOLD}VERIFICATION SUMMARY: {GREEN}{len(reporter.passes)} PASSED{RESET}, "
        f"{RED if reporter.errors else GREEN}{len(reporter.errors)} FAILED{RESET}"
    )
    print(f"{BOLD}{CYAN}{'=' * 76}{RESET}\n")

    if reporter.errors:
        print(f"{BOLD}{RED}FAILURE DETAILS:{RESET}")
        for idx, error in enumerate(reporter.errors, start=1):
            print(f"  [{idx:02d}] {RED}FAIL:{RESET} {error}")
        print(f"\n{BOLD}{RED}{'!' * 76}{RESET}")
        print(f"{BOLD}{RED}VERIFICATION FAILED: Exiting with returncode 1.{RESET}")
        print(f"{BOLD}{RED}{'!' * 76}{RESET}\n")
        return 1

    print(f"{BOLD}{GREEN}ALL QUALITY GATES PASSED (100% COMPLIANCE).{RESET}")
    print("Exiting with returncode 0.")
    print(f"{BOLD}{CYAN}{'=' * 76}{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
