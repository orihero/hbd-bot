"""The image and video router (IMAGE_VIDEO_SPEC §2.2–§2.6, §3.1).

Registered after ``navigation`` and before the song's step routers, ``submitting`` and
``fallback`` (``bot.handlers``), and wrapped in ``only_in_private`` like every customer router.

**Both observers stand down for ``Wizard.submitting``**, the ``menu`` router's filter for the
menu router's reason: ``handlers.submitting`` claims every update while a song renders, and its
park is what ``order_in_flight`` reads. v1 media does not start while a song renders (§2.2, Q5)
— a picker or 🔁 pressed then answers ``wizard.queued``.

Two families of registration, told apart by the spec's callback rule (§2 "Callbacks"):

* **pre-freeze** — the tray's ✅ 🗑 ✖️, the aspect buttons, a video's tier/voice/⬅️ screens
  after ✅ Done, and the messages of a compose — are STATE-FILTERED to ``ImageOrder.*`` /
  ``VideoOrder.*``; a stale one falls through to the fallback's stale-callback screen like any
  other expired button. The picker is the exception: it is drawn from the menu, which has no
  state;
* **post-freeze** — every button carrying a job id — have NO state filter and read the row.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter

from bayram.bot.callbacks import MediaAction, MediaCB
from bayram.bot.handlers.media import compose, jobs, video
from bayram.bot.states import ImageOrder, VideoOrder, Wizard

__all__ = ["build_router"]

#: The screens of a video after ✅ Done where a message is answered, not taken (§2.4.1):
#: photos get ``media.compose.closed``, anything else ``media.use_buttons``.
_VIDEO_BUTTON_STEPS = (
    VideoOrder.aspect,
    VideoOrder.tier,
    VideoOrder.voice,
    VideoOrder.voice_gender,
    VideoOrder.script_review,
    VideoOrder.quote,
)
#: Every video screen that carries ⬅️ (and so ✖️ with no job on it).
_VIDEO_BACK_STEPS = (
    VideoOrder.aspect,
    VideoOrder.tier,
    VideoOrder.voice,
    VideoOrder.voice_gender,
    VideoOrder.voice_text,
    VideoOrder.script_review,
    VideoOrder.voice_note,
)


def build_router() -> Router:
    router = Router(name="media")
    router.message.filter(~StateFilter(Wizard.submitting))
    router.callback_query.filter(~StateFilter(Wizard.submitting))
    composing = StateFilter(ImageOrder.compose, VideoOrder.compose)

    # -- the picker (stateless) -----------------------------------------------------------
    router.callback_query.register(
        compose.handle_pick, MediaCB.filter(F.action == MediaAction.PICK)
    )

    # -- compose (ImageOrder.compose, VideoOrder.compose: one tray) -----------------------
    router.message.register(compose.handle_compose_text, composing, F.text)
    router.message.register(compose.handle_compose_photo, composing, F.photo)
    router.message.register(compose.handle_compose_document, composing, F.document)
    router.message.register(compose.handle_compose_other, composing)
    router.callback_query.register(
        compose.handle_done, ImageOrder.compose, MediaCB.filter(F.action == MediaAction.DONE)
    )
    router.callback_query.register(
        video.handle_done, VideoOrder.compose, MediaCB.filter(F.action == MediaAction.DONE)
    )
    router.callback_query.register(
        compose.handle_clear, composing, MediaCB.filter(F.action == MediaAction.CLEAR)
    )
    router.callback_query.register(
        compose.handle_drop,
        StateFilter(ImageOrder.compose, ImageOrder.aspect, VideoOrder.compose, *_VIDEO_BACK_STEPS),
        MediaCB.filter(F.action == MediaAction.DROP),
    )

    # -- the aspect, and the image's freeze (ImageOrder.aspect) ---------------------------
    router.callback_query.register(
        compose.handle_aspect, ImageOrder.aspect, MediaCB.filter(F.action == MediaAction.ASPECT)
    )

    # -- a video after ✅ Done (§2.4.1) ------------------------------------------------------
    router.callback_query.register(
        video.handle_aspect, VideoOrder.aspect, MediaCB.filter(F.action == MediaAction.ASPECT)
    )
    router.callback_query.register(
        video.handle_tier, VideoOrder.tier, MediaCB.filter(F.action == MediaAction.TIER)
    )
    router.callback_query.register(
        video.handle_voice, VideoOrder.voice, MediaCB.filter(F.action == MediaAction.VOICE)
    )
    router.callback_query.register(
        video.handle_gender,
        VideoOrder.voice_gender,
        MediaCB.filter(F.action == MediaAction.GENDER),
    )
    router.callback_query.register(
        video.handle_script,
        VideoOrder.script_review,
        MediaCB.filter(F.action == MediaAction.SCRIPT),
    )
    router.callback_query.register(
        video.handle_back,
        StateFilter(*_VIDEO_BACK_STEPS),
        MediaCB.filter(F.action == MediaAction.BACK),
    )
    router.message.register(video.handle_voice_text, VideoOrder.voice_text, F.text)
    router.message.register(video.handle_voice_in_text_step, VideoOrder.voice_text, F.voice)
    router.message.register(video.handle_voice_note, VideoOrder.voice_note, F.voice)
    # A photo is "closed" wherever it arrives after ✅ (§2.3.2); anything else in the note
    # step is not a voice message.
    router.message.register(
        compose.handle_after_done,
        StateFilter(VideoOrder.voice_note, VideoOrder.voice_text),
        F.photo,
    )
    router.message.register(video.handle_note_wrong_type, VideoOrder.voice_note)

    # Anything sent once the photos are closed (§2.3.2).
    router.message.register(
        compose.handle_after_done,
        StateFilter(
            ImageOrder.aspect, ImageOrder.quote, VideoOrder.voice_text, *_VIDEO_BUTTON_STEPS
        ),
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
    router.callback_query.register(
        video.handle_record_again, MediaCB.filter(F.action == MediaAction.RECORD)
    )
    return router
