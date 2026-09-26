#!/usr/bin/env python3
"""Render the Variant D 30-second bed by calling Eleven Music directly.

Plan: marketing/campaigns/peshta/04_generation_plan.md section 3.7. This bypasses
``pipeline/orchestrator.py`` on purpose (section 3.1): the orchestrator needs a database,
an ``Order`` row, payment authorisation and STT name verification, none of which a promo
has. A hand-built ``CompositionPlan`` goes straight to ``ElevenLabsMusicProvider.compose``.

SPENDING IS OPT-IN. With no arguments this script is a DRY RUN: it builds the exact
request body, prints it, and sends nothing. Only ``--spend-real-money`` opens a socket.

    .venv/bin/python marketing/campaigns/peshta/render_variant_d_bed.py   # free, sends nothing
    .venv/bin/python marketing/campaigns/peshta/render_variant_d_bed.py \
        --spend-real-money=bayram-variant-d-bed-001        # ~$0.075, POSTs for real

The spend flag takes the idempotency key as its VALUE, and the parser runs with
``allow_abbrev=False``. Both locks exist because a single boolean flag was NOT
accident-proof: argparse abbreviates long options by default, so a shorter ``--spend``
silently matched ``--spend-real-money`` and bought a song during a test that was written
to prove the opposite. A flag that needs a value cannot be triggered by an abbreviation,
a stale shell-history line, or a half-typed command.

Run it with cwd = the repository root: ``build_settings()`` resolves ``.env`` relative to
the process working directory, and from anywhere else it raises a ``ConfigError`` naming
BAYRAM_ELEVENLABS_API_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from bayram.config import Settings, build_settings
from bayram.contracts import Chunk, CompositionPlan, ContextAdherence, Err, Genre, Language
from bayram.providers.music import build_compose_body, build_music_provider, guard_plan
from bayram.providers.music.payload import MUSIC_PATH
from bayram.providers.music.styles import positive_styles_for

OUT = Path(__file__).resolve().parent / "audio" / "variant_d_bed_001.mp3"

# Bump this (-001 -> -002) for every DELIBERATE new take. Keep it FIXED when
# retrying a transport failure, or you pay twice for the same song.
# NOT "peshta-...": the adapter sends this as the `idempotency-key` HTTP HEADER
# (elevenlabs.py IDEMPOTENCY_HEADER, applied in _headers), so it is a string a
# vendor can see. See section 3.6.
IDEMPOTENCY_KEY = "bayram-variant-d-bed-001"

POS = (
    *positive_styles_for(Genre.UZBEK_POP),
    "folk trap", "808 sub bass", "trap hi-hats",
    "male lead vocal", "shouted hype ad-libs", "anthemic",
    "uzbek language vocal", "sung in uzbek",
)
NEG = (
    "explicit lyrics", "lo-fi", "muffled vocals", "spoken word",
    "english lyrics", "russian lyrics", "cover version", "karaoke backing",
)

# U+02BB written as an escape so nothing depends on this file's encoding
# round-tripping through an editor.
TC = "ʻ"   # MODIFIER LETTER TURNED COMMA, the one in o- and g-

PLAN = CompositionPlan(
    chunks=(
        Chunk(text="[instrumental] lone doira, thin tense synth, no bass yet",
              duration_ms=6000, positive_styles=POS, negative_styles=NEG,
              context_adherence=ContextAdherence.MEDIUM),
        Chunk(text=f"Sovg{TC}a izlab boshim qotdi...\nBOTDA! BAYRAM-BOTDA!",
              duration_ms=9000, positive_styles=POS, negative_styles=NEG,
              context_adherence=ContextAdherence.HIGH),
        Chunk(text="Isming aytib kuylar bugun, botda Bayram-botda!\n"
                   "O mani kuydirding, o mani suydirding!",
              duration_ms=9000, positive_styles=POS, negative_styles=NEG,
              context_adherence=ContextAdherence.HIGH),
        Chunk(text=f"O{TC}n besh mingga qo{TC}shiq tayyor, Bayram-botga kiring!",
              duration_ms=6000, positive_styles=POS, negative_styles=NEG,
              context_adherence=ContextAdherence.HIGH),
    ),
    language=Language.UZ_LATN,          # our records only; NOT sent to the vendor
    seed=20260918,                      # same seed + same plan = reproducible take
    is_instrumental=False,
    should_store_for_inpainting=True,   # keeps a song-id so ONE chunk can be re-rolled
)

#: Section 3.6 (D4): never name the artist or the track anywhere a vendor can see, and
#: never ask for a copy. `failures.py` only LABELS a rejection after the fact -- it reads
#: the vendor's response body, never our request, and prevents nothing. This is the
#: enforcement, and it runs before anything is sent.
FORBIDDEN_ANYWHERE = ("hamdam sobirov", "peshta")
FORBIDDEN_AS_POSITIVE = ("in the style of", "sounds like", "cover of")


def rights_violations(plan: CompositionPlan, idempotency_key: str) -> list[str]:
    """Every place a banned string reaches the wire. Empty list means clean."""
    found: list[str] = []
    for marker in FORBIDDEN_ANYWHERE:
        if marker in idempotency_key.casefold():
            found.append(f"idempotency-key header contains {marker!r}")
    for index, chunk in enumerate(plan.chunks):
        fields = {
            "text": (chunk.text,),
            "positive_styles": chunk.positive_styles,
            "negative_styles": chunk.negative_styles,
        }
        for field, values in fields.items():
            for value in values:
                folded = value.casefold()
                for marker in FORBIDDEN_ANYWHERE:
                    if marker in folded:
                        found.append(f"chunk[{index}].{field} contains {marker!r}")
                if field == "negative_styles":
                    continue  # an exclusion pushes AWAY from the original; section 3.6
                for marker in FORBIDDEN_AS_POSITIVE:
                    if marker in folded:
                        found.append(f"chunk[{index}].{field} contains {marker!r}")
    return found


def _describe_marks(text: str) -> str:
    """Name every non-ASCII codepoint, so a mangled U+02BB is visible, not guessed."""
    marks = sorted({f"U+{ord(ch):04X} {ch!r}" for ch in text if ord(ch) > 127})
    return ", ".join(marks) if marks else "(ascii only)"


def print_request(settings: Settings, body: dict[str, Any]) -> None:
    """Print exactly what would be POSTed. The API key is never printed."""
    url = f"{settings.elevenlabs_base_url.rstrip('/')}{MUSIC_PATH}"
    print("POST", url)
    print("params:", json.dumps({"output_format": settings.music_output_format}))
    print("headers:", json.dumps({
        "xi-api-key": f"<redacted, {len(settings.elevenlabs_api_key)} chars>",
        "idempotency-key": IDEMPOTENCY_KEY,
        "accept": "audio/*",
        "content-type": "application/json",
    }, indent=2))
    print("body:")
    print(json.dumps(body, indent=2, ensure_ascii=False))
    print()
    print("top-level body keys:", sorted(body))
    print("tempo field present:", any("tempo" in k for k in _all_keys(body)))
    print("music_length_ms present:", "music_length_ms" in body)
    print("language on the wire:", any("lang" in k for k in _all_keys(body)))
    for index, chunk in enumerate(PLAN.chunks):
        print(f"chunk[{index}] {chunk.duration_ms}ms marks: {_describe_marks(chunk.text)}")
    print("plan total:", PLAN.total_duration_ms, "ms")


def _all_keys(node: object) -> list[str]:
    """Every dict key anywhere in the body, so a nested field cannot hide."""
    keys: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(key)
            keys.extend(_all_keys(value))
    elif isinstance(node, list):
        for item in node:
            keys.extend(_all_keys(item))
    return keys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the CLI. The DEFAULT, and the default of every mistake, is a dry run.

    ``allow_abbrev=False`` is load-bearing, not tidiness. With argparse's default
    abbreviation on, ``--spend`` is an unambiguous prefix of ``--spend-real-money`` and
    spends the money -- which is exactly what happened here, in a test written to check
    that it would not. The flag also takes the idempotency key as a required VALUE, so
    the operator has to name the take they are buying.
    """
    parser = argparse.ArgumentParser(
        description="Render the Variant D bed. DRY RUN unless the spend flag is given in full.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--spend-real-money",
        dest="spend_confirmation",
        metavar="IDEMPOTENCY_KEY",
        default=None,
        help=(
            "Actually POST to ElevenLabs and pay for a render. Must be given as "
            f"--spend-real-money={IDEMPOTENCY_KEY} -- the key is typed out so a "
            "half-remembered command cannot spend."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Explicitly ask for the default behaviour: build and print, send nothing.",
    )
    args = parser.parse_args(argv)
    if args.spend_confirmation is not None and args.dry_run:
        parser.error("--dry-run and --spend-real-money contradict each other")
    if args.spend_confirmation is not None and args.spend_confirmation != IDEMPOTENCY_KEY:
        parser.error(
            f"--spend-real-money must be given the current idempotency key "
            f"({IDEMPOTENCY_KEY!r}), got {args.spend_confirmation!r}. Nothing was sent."
        )
    args.spend = args.spend_confirmation == IDEMPOTENCY_KEY
    return args


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = build_settings()

    if settings.use_fake_providers:                      # gate 1
        print("REFUSING: fake providers on; this writes silent MP3 frames.")
        return 2

    guarded = guard_plan(PLAN)                           # gate 2 - a bad plan costs nothing
    if isinstance(guarded, Err):
        print("plan rejected locally:", guarded.error.operator_message)
        return 2

    violations = rights_violations(PLAN, IDEMPOTENCY_KEY)  # gate 3 - section 3.6, D4
    if violations:
        print("REFUSING on rights grounds:")
        for violation in violations:
            print("  -", violation)
        return 2

    provider = build_music_provider(settings)
    try:
        if provider.name != "elevenlabs_music":          # gate 4
            print(f"REFUSING: provider is {provider.name!r}")
            return 2

        body = build_compose_body(PLAN, model_id=settings.music_model_id)
        print_request(settings, body)

        est = PLAN.total_duration_ms / 60000 * settings.music_usd_per_minute
        if not args.spend:
            print()
            print(f"DRY RUN - nothing sent, nothing spent. A real run would cost ~${est:.4f}.")
            print(f"To actually render: --spend-real-money={IDEMPOTENCY_KEY}")
            return 0

        print(f"rendering {PLAN.total_duration_ms}ms via {provider.name} "
              f"({settings.music_model_id}, {settings.music_output_format}) est ${est:.4f}")
        result = await provider.compose(
            PLAN, idempotency_key=IDEMPOTENCY_KEY, timeout_s=settings.music_timeout_s
        )
        if isinstance(result, Err):
            e = result.error
            print(f"FAILED code={e.error_code.value} retryable={e.is_retryable}")
            print(f"       {e.operator_message}")
            print(f"       context={e.context}")
            return 1
        audio = result.value
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(audio.data)
        print(f"wrote {OUT}  {len(audio.data):,} bytes  mime={audio.mime}")
        print(f"  requested_duration_s={audio.duration_s}  (REQUESTED, not measured)")
        print(f"  remote_id={audio.remote_id!r}  (None => this take cannot be inpainted)")
        print(f"  cost_usd={audio.cost_usd} ({audio.cost_source.value})")
        return 0
    finally:
        await provider.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
