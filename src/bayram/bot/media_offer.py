"""Which media kinds THIS account is offered right now (IMAGE_VIDEO_SPEC §2.2, §2.5).

``media_offered`` is a pure function of ``Settings`` plus the SKU's pause switch; this module
reads the switch from Redis and adds the two things only the bot knows: whether a media desk
is wired at all, and which compose flows exist in this build. Asked at the ✨ press, at the
picker press, and by the menu re-push for its "new" line — and never trusted afterwards: the
🎁/🎟/💳 handlers and ``media_start`` re-check at press and run time.
"""

from __future__ import annotations

from typing import Final

from bayram.bot.deps import BotDeps
from bayram.db.enums import MediaKind, MediaSku
from bayram.media.offering import media_offered
from bayram.media.overrides import read_paused

__all__ = ["BUILT_COMPOSE_KINDS", "SKU_FOR_KIND", "is_sku_paused", "offered_kinds"]

#: The compose flows this build has. Video's (``VideoOrder``, §2.4) is M4.1: until it lands a
#: 🎬 button would lead nowhere, so video is offered to nobody whatever its flag says.
BUILT_COMPOSE_KINDS: Final[frozenset[MediaKind]] = frozenset({MediaKind.IMAGE})

#: The SKU the picker's row for a kind sells. Video's tier is chosen after compose (§2.4.1),
#: so the picker asks about Standard, the tier that exists (O2).
SKU_FOR_KIND: Final[dict[MediaKind, MediaSku]] = {
    MediaKind.IMAGE: MediaSku.IMAGE,
    MediaKind.VIDEO: MediaSku.VIDEO_STANDARD,
}


async def is_sku_paused(deps: BotDeps, sku: MediaSku) -> bool:
    """The kill switch (§4.5). No Redis wired reads as not paused; an unreadable one as paused."""
    if deps.media_kv is None:
        return False
    return await read_paused(deps.media_kv, sku)


async def offered_kinds(deps: BotDeps, telegram_user_id: int | None) -> frozenset[MediaKind]:
    """The kinds the ✨ picker draws for this account. Empty means ✨ is the song, as 🎵 was."""
    if deps.media is None or telegram_user_id is None:
        return frozenset()
    offered: set[MediaKind] = set()
    for kind in sorted(BUILT_COMPOSE_KINDS):
        sku = SKU_FOR_KIND[kind]
        # The switch is read only for an account the rest of the rule admits, so a customer
        # outside the beta costs no Redis round trip on every ✨.
        if not media_offered(deps.settings, sku, telegram_user_id, is_paused=False):
            continue
        if not await is_sku_paused(deps, sku):
            offered.add(kind)
    return frozenset(offered)
