"""One answer per album, not one per photo (IMAGE_VIDEO_SPEC §2.2, §2.3.2).

Telegram delivers a ten-photo album as ten separate messages sharing a ``media_group_id``. A
handler that answers each one draws ten replies, and ten updates also approach the inbound
gate's 30-per-minute ceiling (§0.1). :class:`AlbumMemory` is the 60-second seen-set both use:

* the inbound gate counts the FIRST item of an album and lets the follow-ons through as zero
  updates (``bot.gate``);
* the fallback and the song wizard's free-text steps reply to the first item only.

Keyed by ``(account, media_group_id, purpose)`` so the gate having seen an album does not stop
a handler from answering it once. In-process and bounded, like the gate's own counters: the
bot is one process, and a restart that forgets an album costs at most one extra reply.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

__all__ = ["AlbumMemory", "ALBUM_WINDOW"]

#: How long an album is remembered (§2.3.2). Telegram sends an album's items within a second
#: or two of each other; a minute is generous and still short enough that a second album
#: sent later is a new one.
ALBUM_WINDOW: Final[timedelta] = timedelta(seconds=60)

#: A hard ceiling on remembered albums, so a flood of distinct ids cannot grow the map.
_MAX_ENTRIES: Final[int] = 10_000


class AlbumMemory:
    """The seen-set. :meth:`first` is the whole interface."""

    __slots__ = ("_seen", "_window")

    def __init__(self, *, window: timedelta = ALBUM_WINDOW) -> None:
        self._window = window
        self._seen: dict[tuple[int, str, str], datetime] = {}

    def first(
        self, telegram_user_id: int, media_group_id: str | None, *, purpose: str, now: datetime
    ) -> bool:
        """True for a message that is not part of an album, or the first of one seen for
        ``purpose`` inside the window; False for every follow-on."""
        if media_group_id is None:
            return True
        key = (telegram_user_id, media_group_id, purpose)
        seen_at = self._seen.get(key)
        if seen_at is not None and now - seen_at < self._window:
            return False
        if len(self._seen) >= _MAX_ENTRIES:
            self._prune(now)
        self._seen[key] = now
        return True

    def _prune(self, now: datetime) -> None:
        live = {key: at for key, at in self._seen.items() if now - at < self._window}
        if len(live) >= _MAX_ENTRIES:
            live.clear()
        self._seen = live
