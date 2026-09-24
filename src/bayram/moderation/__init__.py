"""Media moderation (IMAGE_VIDEO_SPEC §6, D24): the contract every guard is held to.

M2.4 ships the seam — :class:`~bayram.moderation.contracts.MediaModerator`, the verdict schema
and a :class:`~bayram.moderation.fake.FakeModerator` for tests — so the stage chain can call it
from day one. The real guard client (``GatewayGuardModerator``, G1–G3 and G8 on the owner's
5090), the L0 lexicons, the policy table and strikes are M3.1. Until then the ``gateway``
setting builds a moderator that answers ``unavailable`` to everything: **fail closed**, so a
deployment that forgot M3 quotes nothing (``media.busy``) rather than screening nothing.
"""

from __future__ import annotations

__all__: list[str] = []
