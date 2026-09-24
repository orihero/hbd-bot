"""The image and video products (IMAGE_VIDEO_SPEC, D20–D26): contracts and policy.

Vendor-free. The adapters that talk to a generation backend live in
``bayram.providers.media``; what lives here is what every backend is held to
(:mod:`bayram.media.contracts`), who may see and buy a media SKU
(:mod:`bayram.media.offering`), the operator's Redis switches (:mod:`bayram.media.overrides`),
the margin rule (:mod:`bayram.media.margin`), the boot refusals (:mod:`bayram.media.boot`),
the collage that turns several photos into one input (:mod:`bayram.media.composite`), the
stage-job names and ids both processes enqueue by (:mod:`bayram.media.stages`) and the row
moves the bot makes on a frozen request (:mod:`bayram.media.service`). The stage jobs
themselves run in the worker: ``bayram.runtime.media_jobs``.
"""

from __future__ import annotations

__all__: list[str] = []
