"""Deterministic idempotency keys.

A retried ARQ job must not buy the same song twice. Every provider call therefore derives
its key from *what is being asked for*, never from a clock or a UUID4: the same order, the
same stage and the same discriminator produce the same key on attempt one and on attempt
nine, so a vendor that honours idempotency de-duplicates and a vendor that does not at
least gives us a stable handle in its dashboard.

The key deliberately covers the name candidate rank for the song, because re-rolling the
name IS a different request and must not be de-duplicated against the take we rejected.
"""

from __future__ import annotations

import hashlib
from typing import Final
from uuid import UUID

from bayram.pipeline.events import PipelineStage

__all__ = ["idempotency_key", "KEY_PREFIX", "KEY_DIGEST_CHARS"]

KEY_PREFIX: Final[str] = "bayram"
#: 128 bits of a sha256 is plenty to keep keys collision-free and headers short.
KEY_DIGEST_CHARS: Final[int] = 32


def idempotency_key(order_id: UUID, stage: PipelineStage, *discriminators: object) -> str:
    """Stable key for one logical provider call within one order.

    ``discriminators`` distinguish calls that share a stage — greeting index, name
    candidate rank — and are rendered with ``str`` so callers pass domain values directly.
    """
    parts = (KEY_PREFIX, str(order_id), stage.value, *(str(item) for item in discriminators))
    joined = "|".join(parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:KEY_DIGEST_CHARS]
    return f"{KEY_PREFIX}-{stage.value}-{digest}"
