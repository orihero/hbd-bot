"""The admin panel: a third process that holds no vendor credential and no bot token.

The bot and the worker load :class:`hbd.config.Settings`, which requires
``HBD_TELEGRAM_BOT_TOKEN``, ``HBD_ELEVENLABS_API_KEY`` and ``HBD_LLM_API_KEY``. This package
loads :class:`hbd.admin.settings.AdminSettings` instead, and that model has **no field** any
of the three could bind to. The distinction is the whole blast-radius argument for running
the panel separately (ADMIN_PANEL_PLAN D10, §4.2, §12.1 T12): a compromised admin host
yields a database session and a session store, not the ability to message every customer as
the bot for as long as the token lives, and not the ability to spend the vendor balance.

Nothing is imported here. ``python -m hbd.admin.bootstrap`` must reach the database without
constructing a FastAPI application, and importing the app eagerly would also make every
``hbd.admin.*`` import pay for Starlette. The entry points are
:func:`hbd.admin.app.create_app` and :mod:`hbd.admin.bootstrap`.
"""

from __future__ import annotations

__all__: list[str] = []
