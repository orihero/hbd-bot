"""Router assembly. Order matters, so it is stated once, here.

``start`` first (a ``/start`` must work from anywhere, including mid-wizard), then the
navigation buttons, then the step handlers, and ``fallback`` last — it matches everything,
so anything registered after it would be dead code.
"""

from __future__ import annotations

from aiogram import Router

from hbd.bot.handlers import confirm, fallback, name, navigation, questions, start

__all__ = ["build_router"]


def build_router() -> Router:
    """A fresh, fully wired router tree. Called once by the composition root."""
    router = Router(name="hbd")
    router.include_routers(
        start.build_router(),
        navigation.build_router(),
        questions.build_router(),
        name.build_router(),
        confirm.build_router(),
        fallback.build_router(),
    )
    return router
