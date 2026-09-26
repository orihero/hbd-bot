#!/usr/bin/env python3
"""IP gate. Non-zero exit if a forbidden token reaches a GENERATION INPUT.

Why this replaces the shell version
-----------------------------------
The old gate had two holes and the obvious fix opened a third.

  SCOPE  (fixed)  It grepped only 05_build/prompts/, so it was structurally blind
                  to 06_local/, where every generation input for the local rebuild
                  now lives. Its "pass" said nothing about the new work.
  REGEX  (fixed)  'polat' and 'necati' were missing outright.
  PATHS  (this)   Widening the scope made it fire on ~80 filesystem paths, because
                  the delivered master is *named* final_polat_peshta_reel.mp4.
                  A gate that cannot tell a prompt from a path is noise, and a
                  noisy gate gets switched off.

So the rule is about REACHABILITY, not string presence:

  FAIL  a forbidden token in a string that can reach a model -- prompt text,
        character or wardrobe description, negative prompts, captions.
  PASS  the same token inside a filesystem path, a URL, a ComfyUI node name, or
        a field whose whole job is to record provenance or to name the ban.

A file cannot be audited for a rule it is forbidden from stating.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROMO = os.path.abspath(os.path.join(HERE, "..", ".."))

ROOTS = ["05_build/prompts", "06_local"]
SKIP_DIRS = {"superseded", "__pycache__", "venv", "a_frames", "a_keyframes",
             "identity", "source_motion_stills", "ab", ".git"}

BANNED = re.compile(
    r"alemdar|kurtlar|vadisi|sasmaz|şaşmaz|necati|özgü|\bozgu\b|namal|pana ?film|"
    r"sobirov|xamdam|hamdam|peshta|valley of the wolves|deepfake|face ?swap|"
    r"lookalike|looks exactly like|celebrity|shot-for-shot|\bpolat\b|elif eyl",
    re.I)

# Keys whose values are provenance, paths or the ban itself -- allowed to contain tokens.
EXEMPT_KEY = re.compile(
    r"path|file|dir|source|src|url|repo|dest|_meta|provenance|forbidden|banned|"
    r"token|gate|audit|note|why|justification|do_not_reuse|superseded|legacy|"
    r"method|generated_by|harness|label|name$|ground_truth|citation|sha",
    re.I)

# Values that are plainly a path / filename / identifier, not prose a model reads.
LOOKS_LIKE_PATH = re.compile(r"[/\\]|\.(mp4|mp3|png|jpg|json|py|md|sh|safetensors|onnx|txt)\b", re.I)

# Fields that unambiguously DO reach a model.
PROMPT_KEY = re.compile(
    r"prompt|verbatim|description|appearance|wardrobe|motion|keyframe_moment|"
    r"action|caption|negative|clause|identity_block|anchor",
    re.I)


def walk(obj, path, hits):
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk(v, f"{path}.{k}", hits)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk(v, f"{path}[{i}]", hits)
    elif isinstance(obj, str):
        m = BANNED.search(obj)
        if not m:
            return
        leaf = path.rsplit(".", 1)[-1].split("[")[0]
        reaches_model = bool(PROMPT_KEY.search(path))
        exempt = bool(EXEMPT_KEY.search(leaf)) or bool(LOOKS_LIKE_PATH.search(obj))
        if reaches_model and not exempt:
            hits.append(("FAIL", path, m.group(0), obj[:140]))
        elif not exempt:
            hits.append(("WARN", path, m.group(0), obj[:140]))


def main():
    os.chdir(PROMO)
    fails, warns = [], []
    scanned = 0
    for root in ROOTS:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if not fn.endswith((".json", ".md", ".txt")):
                    continue
                fp = os.path.join(dirpath, fn)
                scanned += 1
                hits = []
                if fn.endswith(".json"):
                    try:
                        walk(json.load(open(fp)), fp, hits)
                    except Exception:
                        continue
                else:
                    for i, line in enumerate(open(fp, errors="replace"), 1):
                        m = BANNED.search(line)
                        if m and not LOOKS_LIKE_PATH.search(line):
                            hits.append(("WARN", f"{fp}:{i}", m.group(0), line.strip()[:140]))
                for sev, p, tok, txt in hits:
                    (fails if sev == "FAIL" else warns).append((p, tok, txt))

    print(f"IP GATE: scanned {scanned} data files under {', '.join(ROOTS)}")
    print(f"         (superseded/ excluded -- it is audit trail and is SUPPOSED to contain these)")
    if warns:
        print(f"\n  {len(warns)} advisory hit(s) outside prompt-bearing fields:")
        for p, tok, txt in warns[:15]:
            print(f"    ~ {tok:<12} {p}")
            print(f"      {txt}")
        if len(warns) > 15:
            print(f"    ... and {len(warns)-15} more")
    if fails:
        print(f"\n  {len(fails)} FORBIDDEN TOKEN(S) IN A FIELD THAT REACHES A MODEL:")
        for p, tok, txt in fails:
            print(f"    ! {tok:<12} {p}")
            print(f"      {txt}")
        print("\nIP GATE: FAIL — do not generate.")
        return 1
    print("\nIP GATE: pass — no forbidden token in any prompt-bearing field.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
