"""The image (and, from M4, video) router (IMAGE_VIDEO_SPEC §2.2–§2.6, §3.1).

Registered after ``navigation`` and before the song's step routers, ``submitting`` and
``fallback`` (``bot.handlers``), and wrapped in ``only_in_private`` like every customer router.

**Both observers stand down for ``Wizard.submitting``**, the ``menu`` router's filter for the
menu router's reason: ``handlers.submitting`` claims every update while a song renders, and its
park is what ``order_in_flight`` reads. v1 media does not start while a song renders (§2.2, Q5)
— a picker or 🔁 pressed then answers ``wizard.queued``.

Two families of registration, told apart by the spec's callback rule (§2 "Callbacks"):

* **pre-freeze** — the tray's ✅ 🗑 ✖️, the aspect buttons, and the messages of a compose — are
  STATE-FILTERED to ``ImageOrder.*``; a stale one falls through to the fallback's
  stale-callback screen like any other expired button. The picker is the exception: it is
  drawn from the menu, which has no state;
* **post-freeze** — every button carrying a job id — have NO state filter and read the row.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter

from bayram.bot.callbacks import MediaAction, MediaCB
from bayram.bot.handlers.media import compose, jobs
from bayram.bot.states import ImageOrder, Wizard

__all__ = ["build_router"]


def build_router() -> Router:
    router = Router(name="media")
    router.message.filter(~StateFilter(Wizard.submitting))
    router.callback_query.filter(~StateFilter(Wizard.submitting))

    # -- the picker (stateless) -----------------------------------------------------------
    router.callback_query.register(
        compose.handle_pick, MediaCB.filter(F.action == MediaAction.PICK)
    )

    # -- compose (ImageOrder.compose) ---------------------------------------------------
    router.message.register(compose.handle_compose_text, ImageOrder.compose, F.text)
    router.message.register(compose.handle_compose_photo, ImageOrder.compose, F.photo)
    router.message.register(compose.handle_compose_document, ImageOrder.compose, F.document)
    router.message.register(compose.handle_compose_other, ImageOrder.compose)
    router.callback_query.register(
        compose.handle_done, ImageOrder.compose, MediaCB.filter(F.action == MediaAction.DONE)
    )
    router.callback_query.register(
        compose.handle_clear, ImageOrder.compose, MediaCB.filter(F.action == MediaAction.CLEAR)
    )
    router.callback_query.register(
        compose.handle_drop,
        StateFilter(ImageOrder.compose, ImageOrder.aspect),
        MediaCB.filter(F.action == MediaAction.DROP),
    )

    # -- the aspect, and the freeze (ImageOrder.aspect) ------------------------------------
    router.callback_query.register(
        compose.handle_aspect, ImageOrder.aspect, MediaCB.filter(F.action == MediaAction.ASPECT)
    )
    # Anything sent once the photos are closed (§2.3.2).
    router.message.register(
        compose.handle_after_done, StateFilter(ImageOrder.aspect, ImageOrder.quote)
    )

    # -- post-freeze: a job id, no state filter ------------------------------------------
    router.callback_query.register(jobs.handle_pay, MediaCB.filter(F.action == MediaAction.PAY))
    router.callback_query.register(
        jobs.handle_credit, MediaCB.filter(F.action == MediaAction.CREDIT)
    )
    router.callback_query.register(jobs.handle_beta, MediaCB.filter(F.action == MediaAction.BETA))
    router.callback_query.register(jobs.handle_edit, MediaCB.filter(F.action == MediaAction.EDIT))
    router.callback_query.register(
        jobs.handle_cancel, MediaCB.filter(F.action == MediaAction.CANCEL)
    )
    router.callback_query.register(jobs.handle_retry, MediaCB.filter(F.action == MediaAction.RETRY))
    router.callback_query.register(jobs.handle_again, MediaCB.filter(F.action == MediaAction.AGAIN))
    router.callback_query.register(jobs.handle_more, MediaCB.filter(F.action == MediaAction.MORE))
    return router
