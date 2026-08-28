"""HBD Bot — a Telegram celebration-kit bot for the Uzbekistan market.

One brief in; one AI song, three spoken greetings and a lyric sheet out, with the
recipient's name pronounced correctly. That last part is the product.

Public foundation surface:

* ``hbd.contracts`` — frozen models, the ``Result`` type, and every ``Protocol``.
* ``hbd.config``    — all settings, including the name-candidate ORDER.
* ``hbd.errors``    — the exception hierarchy, retryable vs terminal.
* ``hbd.logging``   — structured JSON logs with a per-order correlation id.

Import from the submodules, not from here; this module deliberately re-exports only the
version so that importing ``hbd`` costs nothing.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
