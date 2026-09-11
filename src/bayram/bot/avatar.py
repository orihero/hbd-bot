"""Fetching the customer's Telegram profile photo, once, and never at their expense.

The face is a convenience for an operator reading the admin panel — a row with a picture on
it is recognised in a glance where a row with a masked phone number has to be read. It is
worth exactly that much and no more, which is the single premise every decision in this
module follows from: **nothing here may fail onboarding, delay it noticeably, or grow into a
second thing that has to succeed before a customer can buy a song.**

Three things follow, and each is enforced rather than intended:

* the whole fetch sits under one :data:`AVATAR_TIMEOUT_S` deadline, because it is three
  sequential Telegram round trips on the update that just told the customer their number was
  saved;
* it is awaited inline rather than spawned, so an exception inside it is handled here instead
  of surfacing as asyncio's "Task exception was never retrieved" in an operator log at some
  later moment with no update to attribute it to;
* every failure — no photo, hidden photos, an oversized file, a refused store write — returns
  quietly. The caller does not branch on the outcome because there is no outcome it could
  usefully act on.

The bytes never touch the wizard's own storage seam: :meth:`UserProfileStore.record_avatar`
takes them and owns both halves of "write the object, then the row", so this module holds a
``bytes`` object for exactly as long as it takes to hand it over.

**``avatar_file_unique_id`` is written and never read, on purpose.** It is Telegram's stable
per-bot id for a photo, and it is stored so that a FUTURE re-fetch can compare it and skip a
photo that has not changed. There is no re-fetch in this build — the fetch runs exactly once,
at the end of onboarding, so there is nothing to skip and nothing here compares it. That is
written down so the next reader stops looking for the comparison instead of concluding it was
lost in a refactor.
"""

from __future__ import annotations

import asyncio
from typing import Final

from aiogram import Bot
from aiogram.types import PhotoSize

from bayram.contracts import Err
from bayram.logging import get_logger
from bayram.user_profiles import AVATAR_MIME, UserProfileStore

__all__ = [
    "fetch_and_store_avatar",
    "AVATAR_TIMEOUT_S",
    "AVATAR_MAX_BYTES",
    "AVATAR_MIN_EDGE_PX",
]

_LOG = get_logger(__name__)

#: The whole budget for the fetch, in seconds.
#:
#: THREE sequential Telegram round trips sit inside it — ``getUserProfilePhotos``,
#: ``getFile`` and the file download — and they run on the update that has just told the
#: customer their number was saved, inside aiogram's per-chat isolation lock, so nothing else
#: from this chat is processed while they are in flight. Five seconds is about the point at
#: which a person decides a bot has stopped talking to them. The photo is worth less than
#: that, so this deadline is the design and not a safety net: it is expected to fire on a bad
#: connection and the ordinary consequence is an account with no face in the admin list.
AVATAR_TIMEOUT_S: Final[float] = 5.0

#: Refuse anything larger, and check it TWICE — once against the size Telegram CLAIMS in the
#: ``PhotoSize`` and once against the bytes actually read.
#:
#: The claim is not a promise: ``file_size`` is optional in the API and is Telegram's own
#: report about a file this process has not seen. The download runs on the bot's event loop
#: with the whole object in memory, so an unbounded read here is how one customer's wallpaper
#: becomes every customer's latency — and, on a small container, how it becomes the OOM kill
#: that takes the whole bot down mid-order.
AVATAR_MAX_BYTES: Final[int] = 512_000

#: The smallest edge worth storing, in pixels.
#:
#: The admin console draws a 3rem thumbnail in the user list and a portrait on the detail
#: screen, so 320px covers both at a 2x device pixel ratio with nothing to spare and nothing
#: wasted. Picking the LARGEST rung of the ladder instead would drag a multi-megabyte
#: original through this process, through :data:`AVATAR_MAX_BYTES`, and onto disk, for a face
#: nobody will ever see above about 200 CSS pixels.
AVATAR_MIN_EDGE_PX: Final[int] = 320


async def fetch_and_store_avatar(
    bot: Bot, *, telegram_user_id: int, profiles: UserProfileStore | None
) -> None:
    """Best effort, bounded, and incapable of failing onboarding.

    Called ONCE, inline, from the contact step, AFTER the customer already has their menu on
    screen. Inline rather than as a background task on purpose: a task spawned from a handler
    outlives the update, runs outside the FSM isolation lock and outside
    ``middleware.ErrorGuardMiddleware``, and an exception in one surfaces as asyncio's "Task
    exception was never retrieved" in the operator log — attributed to nothing, with no
    correlation id and no customer — instead of as a handled warning inside the update that
    caused it. :func:`asyncio.wait_for` is what makes an inline await affordable: five
    seconds, once, on a path a person walks exactly once in the life of their account.

    **NO PHOTO AND HIDDEN-BY-PRIVACY ARE THE SAME EVENT HERE, and both are ordinary.**
    Telegram answers ``getUserProfilePhotos`` for an account whose photos are restricted with
    an EMPTY ``UserProfilePhotos`` — ``total_count == 0`` — and not with an error, so this
    function cannot tell the two apart and must not try. Neither is a failure, neither is
    logged above INFO, and neither leaves the customer waiting for anything.

    Nothing in here is allowed to propagate. The phone number is the thing onboarding exists
    for; the face is a convenience for an operator, and a convenience may never be the reason
    a customer cannot buy a song. The ``profiles is None`` guard says the same thing about an
    unwired deployment: with no store there is nowhere to put the bytes, so the three round
    trips are not made at all.
    """
    if profiles is None:
        return
    try:
        await asyncio.wait_for(
            _fetch_and_store(bot, telegram_user_id=telegram_user_id, profiles=profiles),
            timeout=AVATAR_TIMEOUT_S,
        )
    except TimeoutError:
        # Listed BEFORE the broad arm and not merged into it: ``TimeoutError`` is an
        # ``OSError`` on 3.11+, so a shared ``except Exception`` would swallow the deadline
        # firing and report it as "could not be fetched" with a stack trace — turning the one
        # outcome this module EXPECTS on a slow connection into noise that looks like a bug.
        _LOG.info("the avatar fetch ran out of time", extra={"telegram_user_id": telegram_user_id})
    except Exception:
        # Deliberately broad. Everything inside is a network call or a parse of what came
        # back, and the caller has already sent the customer their menu: there is no failure
        # here worth turning into a message, and no failure here worth re-raising into
        # ``ErrorGuardMiddleware``, which would apologise for something the customer did not
        # ask for and cannot see.
        _LOG.warning(
            "the avatar could not be fetched",
            extra={"telegram_user_id": telegram_user_id},
            exc_info=True,
        )


async def _fetch_and_store(bot: Bot, *, telegram_user_id: int, profiles: UserProfileStore) -> None:
    """The three round trips and the store write, with no error handling of its own.

    Every early return here is a NORMAL outcome, not an error path: no photo, a photo bigger
    than the ceiling, a file Telegram will not give a path for, an empty download. They are
    separated only so the log line says which one happened; the caller treats them all alike.

    It is a separate function from :func:`fetch_and_store_avatar` because
    :func:`asyncio.wait_for` needs a coroutine to cancel, and because keeping the deadline and
    the exception handling in one small wrapper makes it impossible to add a fourth round trip
    here that quietly escapes either of them.
    """
    photos = await bot.get_user_profile_photos(telegram_user_id, limit=1)
    if photos.total_count == 0 or not photos.photos:
        # An account with no photo and an account whose photos are hidden from this bot are
        # indistinguishable at this line — see the public docstring. Neither is worth more
        # than one INFO, and this is the common case for a real installed base.
        _LOG.info("no profile photo is visible to us", extra={"telegram_user_id": telegram_user_id})
        return
    # ``UserProfilePhotos.photos`` is ``list[list[PhotoSize]]``: the OUTER list is one entry
    # per PHOTO and the INNER one is that photo's size ladder. With ``limit=1`` there is
    # exactly one photo, so the ladder is ``photos[0]`` — iterating the outer list would
    # iterate photos and then treat each ladder as a single size, which is the ``[0]`` bug
    # this comment exists to prevent.
    chosen = _smallest_at_least(photos.photos[0], AVATAR_MIN_EDGE_PX)
    if chosen is None:
        _LOG.info("the photo ladder was empty", extra={"telegram_user_id": telegram_user_id})
        return
    if chosen.file_size is not None and chosen.file_size > AVATAR_MAX_BYTES:
        # The first of the two ceilings. Cheap, and it is the one that avoids the download
        # entirely rather than aborting it after the bytes are already in memory.
        _LOG.info(
            "the profile photo is larger than we are willing to store",
            extra={"telegram_user_id": telegram_user_id, "claimed_bytes": chosen.file_size},
        )
        return
    file = await bot.get_file(chosen.file_id)
    if file.file_path is None:
        _LOG.info(
            "Telegram gave no path for the photo", extra={"telegram_user_id": telegram_user_id}
        )
        return
    buffer = await bot.download_file(file.file_path)
    if buffer is None:
        _LOG.info(
            "the photo download returned nothing", extra={"telegram_user_id": telegram_user_id}
        )
        return
    data = buffer.read()
    if len(data) > AVATAR_MAX_BYTES:
        # The second ceiling, and the reason there are two: ``file_size`` above is Telegram's
        # CLAIM about a file, and a claim that turns out to be wrong must not be the thing
        # that decides how much memory this process spends. WARNING rather than INFO because
        # an under-report is worth noticing, unlike a photo that was simply too big.
        _LOG.warning(
            "the downloaded photo was larger than Telegram claimed; discarding it",
            extra={"telegram_user_id": telegram_user_id, "bytes": len(data)},
        )
        return
    if not data:
        _LOG.info("the photo download was empty", extra={"telegram_user_id": telegram_user_id})
        return
    stored = await profiles.record_avatar(
        telegram_user_id,
        image=data,
        mime=AVATAR_MIME,
        file_unique_id=chosen.file_unique_id,
    )
    if isinstance(stored, Err):
        _LOG.warning("the avatar could not be stored", extra=stored.error.to_log_dict())
        return
    # Never the bytes, never a ``file_path`` and never a ``file_id``: a ``file_path`` is a
    # live, unauthenticated download URL for this customer's face once the bot token is
    # prefixed to it, and an operator log is not the place to publish one.
    _LOG.info("avatar stored", extra={"telegram_user_id": telegram_user_id, "bytes": len(data)})


def _smallest_at_least(ladder: list[PhotoSize], min_edge_px: int) -> PhotoSize | None:
    """The cheapest rung big enough to draw, or the biggest one there is. ``None`` if empty.

    Telegram returns the ladder in ascending size order, but this does not depend on that
    ordering — it sorts — because "documented as ascending" and "ascending on every account"
    are different claims, and being wrong about it would pick a thumbnail so small the admin
    console draws a blurred square, or an original so large
    :data:`AVATAR_MAX_BYTES` throws it away and the customer ends up with no face at all.

    The fallback when nothing reaches ``min_edge_px`` is the LARGEST rung rather than nothing:
    a small photo beats no photo, and an account whose only avatar is 160px is a real account
    that an operator would still rather recognise than not.

    ``min(width, height)`` and not the area: the console crops to a square, so the SHORT edge
    is what decides whether the result looks sharp.
    """
    if not ladder:
        return None
    by_edge = sorted(ladder, key=lambda size: min(size.width, size.height))
    for size in by_edge:
        if min(size.width, size.height) >= min_edge_px:
            return size
    return by_edge[-1]
