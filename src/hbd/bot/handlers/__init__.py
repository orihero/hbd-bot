"""Router assembly. Order matters, so it is stated once, here.

``commands`` first (``/help``, ``/privacy``, ``/support`` and ``/forget`` have to work from
any state, and the note step accepts any text, so a command reaching it would be sung), then
``start`` (a ``/start`` must work from anywhere, including mid-wizard), then the
navigation buttons, then the step handlers, then ``submitting``, and ``fallback`` last — it
matches everything, so anything registered after it would be dead code.

``submitting`` sits second to last for the same reason ``fallback`` is last: it claims every
message and every button in one state, so a step router placed after it would never see an
update. Ahead of ``fallback`` because that is the whole point of it — while a song is being
made, "nobody claimed this" must not be answered with "your session expired".
"""

from __future__ import annotations

from aiogram import Router

from hbd.bot.handlers import (
    commands,
    confirm,
    fallback,
    lyrics,
    name,
    navigation,
    questions,
    start,
    submitting,
)

__all__ = ["build_router"]


def build_router() -> Router:
    """A fresh, fully wired router tree. Called once by the composition root."""
    router = Router(name="hbd")
    router.include_routers(
        commands.build_router(),
        start.build_router(),
        navigation.build_router(),
        questions.build_router(),
        name.build_router(),
        lyrics.build_router(),
        confirm.build_router(),
        submitting.build_router(),
        fallback.build_router(),
    )
    return router
