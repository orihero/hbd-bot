"""Media moderation (IMAGE_VIDEO_SPEC §6, D24): the contract every guard is held to.

* ``contracts`` — :class:`~bayram.moderation.contracts.MediaModerator`, the verdict schema and
  the closed category codes (M2.4's seam);
* ``lexicon`` — L0: normalisation, the denylist and the youth lexicon;
* ``policy`` — how a guard's output becomes our decision: the G1 label mapping, the G2
  thresholds, the hard rule;
* ``gateway`` — :class:`~bayram.moderation.gateway.GatewayGuardModerator`, the G1–G3 and G8
  clients on the owner's 5090;
* ``strikes`` — strikes, suspension and the per-account screening budget;
* ``legal_hold`` — sealing CSAM-class bytes to the escalation owner (§6.7);
* ``fake`` / ``factory`` — the test double and the settings switch.

Every path fails closed: a guard that does not answer is ``unavailable``, which is
``media.busy`` before payment and never ``allow`` (O10).
"""

from __future__ import annotations

__all__: list[str] = []
