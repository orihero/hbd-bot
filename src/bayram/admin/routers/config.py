"""``GET /api/config`` — what this admin process is actually running with.

**It is a read and it writes nothing, and there is nothing here it could write to.** The
settings object is built inside the lifespan and frozen (``AdminSettings.model_config``), so
"effective configuration" here means "what the process booted with", full stop. There is no
override table behind this route, no tier on any field and nothing to commit or roll back.

**It is not the runtime-config editor of Phase 7.** That one edits the *bot's* frozen
``bayram.config.Settings`` through an override layer, behind ``CONFIG_WRITE``, a step-up with
no grace (§12.1 T2) and ``admin_config_enabled``. The fields on this response are
``BAYRAM_ADMIN_*`` variables, which are not on the bot's ``Settings`` at all — so they have no
tier, deliberately, because there is no tiered field for an override to shadow. The two
endpoints will coexist: this one answers "what is the panel itself running with", which no
amount of editing the bot's config can answer.

**The guard is ``require_permission`` at the router**, which resolves to ``check_role``.
§12.2 gives CONFIG_READ as **M** to all four roles, and unlike the audit list the **M** cell
has no redacted variant to choose between: the fields that would need redacting are not on
the response in any form. The handler therefore takes no ``Admin`` — the router dependency
has already authenticated the request, and taking the operator in order to ignore them would
imply a cell-dependent projection that does not exist.

**Secrets are absent rather than masked**, which is a property of
:mod:`bayram.admin.schemas.config_view` rather than of this file: that module names every field
it exposes, so a secret added to ``AdminSettings`` tomorrow is omitted by default instead of
being caught by a denylist somebody forgot to extend.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends

from bayram.admin.deps import API_PREFIX, Settings, require_permission
from bayram.admin.schemas.config_view import ConfigView, to_config_view
from bayram.admin.security.permissions import Permission

__all__ = ["CONFIG_PATH", "build_config_router"]

CONFIG_PATH: Final[str] = f"{API_PREFIX}/config"


def build_config_router() -> APIRouter:
    """The configuration surface. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["config"],
        dependencies=[Depends(require_permission(Permission.CONFIG_READ))],
    )

    @router.get(CONFIG_PATH)
    async def read_config(settings: Settings) -> ConfigView:
        """The process's own settings, projected onto the allowlist in ``config_view``.

        ``Settings`` resolves to ``container.settings``, so this reports what the running
        application is bound to rather than what a re-read of the environment would say —
        the two differ exactly when somebody edited ``.env.admin`` without a restart, and
        that gap is the thing an operator is here to find.
        """
        return to_config_view(settings)

    return router
