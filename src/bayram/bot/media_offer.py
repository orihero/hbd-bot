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
from bayram.db.enums import MediaKind, MediaSku, MediaTier
from bayram.media.offering import media_offered, sku_price_minor
from bayram.media.overrides import read_paused

__all__ = [
    "BUILT_COMPOSE_KINDS",
    "SKU_FOR_KIND",
    "SKU_FOR_TIER",
    "is_sku_paused",
    "offered_kinds",
    "offered_tiers",
]

#: The compose flows this build has: ``ImageOrder`` (§2.3) and, since M4.1, ``VideoOrder``
#: (§2.4). A kind missing here is offered to nobody whatever its flag says.
BUILT_COMPOSE_KINDS: Final[frozenset[MediaKind]] = frozenset({MediaKind.IMAGE, MediaKind.VIDEO})

#: The SKU each video tier sells (O2, D22).
SKU_FOR_TIER: Final[dict[MediaTier, MediaSku]] = {
    MediaTier.STANDARD: MediaSku.VIDEO_STANDARD,
    MediaTier.FAST: MediaSku.VIDEO_FAST,
}

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


async def offered_tiers(deps: BotDeps, telegram_user_id: int) -> frozenset[MediaTier]:
    """The video tiers this account may buy now (§2.4.1): offered, priced and not paused.

    The tier screen is drawn only when this holds two; with Fast flagged off (until M6) it is
    Standard alone, the screen is skipped and the quote names the tier.
    """
    tiers: set[MediaTier] = set()
    for tier, sku in SKU_FOR_TIER.items():
        if sku_price_minor(deps.settings, sku) is None:
            continue
        if not media_offered(deps.settings, sku, telegram_user_id, is_paused=False):
            continue
        if not await is_sku_paused(deps, sku):
            tiers.add(tier)
    return frozenset(tiers)
