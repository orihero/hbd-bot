"""The image and video products (IMAGE_VIDEO_SPEC, D20–D26): contracts and policy.

Vendor-free. The adapters that talk to a generation backend live in
``bayram.providers.media``; what lives here is what every backend is held to
(:mod:`bayram.media.contracts`), who may see and buy a media SKU
(:mod:`bayram.media.offering`), the operator's Redis switches (:mod:`bayram.media.overrides`),
the margin rule (:mod:`bayram.media.margin`), the boot refusals (:mod:`bayram.media.boot`)
and the collage that turns several photos into one input (:mod:`bayram.media.composite`).
"""

from __future__ import annotations

__all__: list[str] = []
