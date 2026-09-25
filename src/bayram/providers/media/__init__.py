"""Image and video generation backends behind ``bayram.media.contracts.MediaGenProvider``.

``local_gateway`` is the owner's 5090 (IMAGE_VIDEO_SPEC §4.2), ``fake`` renders real files
offline, ``higgsfield`` is the paid Fast tier (§4.3, M6.1), ``factory`` turns a backend name
into one of them. fal lands later in M6.
"""

from __future__ import annotations

__all__: list[str] = []
