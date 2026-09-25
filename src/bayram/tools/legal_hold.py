"""``python -m bayram.tools.legal_hold`` — the escalation owner's half of §6.7.

Run on the ESCALATION OWNER'S machine, never on the host::

    keygen                          print a new key pair: the private half stays with you;
                                    the public half goes in BAYRAM_MEDIA_LEGAL_HOLD_RECIPIENT
    open <sealed> <out> --key-file F    decrypt one held object copied off the host

The host holds only the public key, so it can seal held bytes and can never read them back
(``bayram.moderation.legal_hold``). Copying a held object off the host and opening it is the
out-of-band access §6.7 describes; the reporting decision it serves is due within 72 hours
(``legal_hold_expires_at``), after which the purge deletes the bytes and keeps the hash.

Exit codes: ``0`` done, ``1`` refused (bad input, wrong key, not a sealed object).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from bayram.contracts import is_err
from bayram.moderation.legal_hold import generate_keypair, open_sealed

__all__ = ["main"]

EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bayram.tools.legal_hold", description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("keygen", help="print a new X25519 key pair")
    opened = sub.add_parser("open", help="decrypt one sealed object")
    opened.add_argument("sealed", type=Path)
    opened.add_argument("out", type=Path)
    opened.add_argument("--key-file", type=Path, required=True, help="the private key, base64")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit:
        return EXIT_REFUSED
    if args.verb == "keygen":
        private, public = generate_keypair()
        print(f"private (keep offline, never on the host): {private}")
        print(f"public  (BAYRAM_MEDIA_LEGAL_HOLD_RECIPIENT): {public}")
        return EXIT_OK
    try:
        blob = Path(args.sealed).read_bytes()
        key = Path(args.key_file).read_text(encoding="ascii")
    except OSError as exc:
        print(f"could not read an input: {exc}")
        return EXIT_REFUSED
    opened = open_sealed(blob, key)
    if is_err(opened):
        print(opened.error.operator_message)
        return EXIT_REFUSED
    Path(args.out).write_bytes(opened.value)
    print(f"wrote {len(opened.value)} bytes to {args.out}")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
