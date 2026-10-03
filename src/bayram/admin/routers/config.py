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

from bayram.admin import audit_sink
from bayram.admin.deps import API_PREFIX, Admin, Container, Db, Settings, require_permission
from bayram.admin.errors import unwrap
from bayram.admin.schemas.config_view import (
    CheckoutRailsConfigView,
    ConfigView,
    MusicProviderConfigView,
    SetCheckoutRailRequest,
    SetMusicProviderRequest,
    SetTeachersDayRequest,
    TeachersDayConfigView,
    to_checkout_rails_config_view,
    to_config_view,
    to_music_provider_config_view,
    to_teachers_day_config_view,
)
from bayram.admin.security.permissions import Permission
from bayram.checkout_rails import read_rail_switches, read_wired_rails, write_rail_enabled
from bayram.db.admin.audit import AuditEntry
from bayram.db.base import utc_now
from bayram.db.enums import AuditAction
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH
from bayram.providers.music.switch import (
    PROVIDER_ELEVENLABS,
    read_music_provider,
    write_music_provider,
)
from bayram.teachers_day import (
    TEACHERS_DAY_DISCOUNT_PERCENT,
    read_teachers_day_enabled,
    write_teachers_day_enabled,
)

__all__ = [
    "CONFIG_CHECKOUT_RAILS_PATH",
    "CONFIG_MUSIC_PROVIDER_PATH",
    "CONFIG_PATH",
    "CONFIG_TEACHERS_DAY_PATH",
    "build_config_manage_router",
    "build_config_router",
]

CONFIG_PATH: Final[str] = f"{API_PREFIX}/config"
CONFIG_MUSIC_PROVIDER_PATH: Final[str] = f"{CONFIG_PATH}/music-provider"
CONFIG_TEACHERS_DAY_PATH: Final[str] = f"{CONFIG_PATH}/teachers-day"
#: The owner's per-rail sale switch (``DECISIONS.md D28``). Read by every role, written by
#: the owner alone, exactly like the two switches above.
CONFIG_CHECKOUT_RAILS_PATH: Final[str] = f"{CONFIG_PATH}/checkout-rails"


async def _checkout_rails_view(redis: object | None) -> CheckoutRailsConfigView:
    """The switches and the bot's published wired list, both read fail-open, never raising.

    Both reads swallow a Redis outage by design (``bayram.checkout_rails``): the switches
    answer "on" and the wired list answers "unknown", which is what the bot itself would
    conclude from the same Redis, so the panel never shows a state the bot is not acting on.
    """
    switches = await read_rail_switches(redis)
    wired = await read_wired_rails(redis)
    return to_checkout_rails_config_view(switches=switches, wired=wired)


def build_config_router() -> APIRouter:
    """The configuration surface. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["config"],
        dependencies=[Depends(require_permission(Permission.CONFIG_READ))],
    )

    @router.get(CONFIG_PATH)
    async def read_config(settings: Settings) -> ConfigView:
        """The process's own settings, projected onto the allowlist in ``config_view``."""
        return to_config_view(settings)

    @router.get(CONFIG_MUSIC_PROVIDER_PATH)
    async def get_music_provider_config(container: Container) -> MusicProviderConfigView:
        """The active music provider from Redis, falling back to default."""
        active = await read_music_provider(container.redis, default=PROVIDER_ELEVENLABS)
        return to_music_provider_config_view(active_provider=active)

    @router.get(CONFIG_TEACHERS_DAY_PATH)
    async def get_teachers_day_config(container: Container) -> TeachersDayConfigView:
        """The Teachers' Day feature switch state from Redis."""
        enabled = await read_teachers_day_enabled(container.redis)
        return to_teachers_day_config_view(
            enabled=enabled, discount_percent=TEACHERS_DAY_DISCOUNT_PERCENT
        )

    @router.get(CONFIG_CHECKOUT_RAILS_PATH)
    async def get_checkout_rails_config(container: Container) -> CheckoutRailsConfigView:
        """Each rail's owner switch and whether the bot booted with it wired."""
        return await _checkout_rails_view(container.redis)

    return router


def build_config_manage_router() -> APIRouter:
    """The configuration mutation surface. Owner only."""
    router = APIRouter(
        tags=["config"],
        dependencies=[Depends(require_permission(Permission.CONFIG_MANAGE))],
    )

    @router.post(CONFIG_MUSIC_PROVIDER_PATH)
    async def set_music_provider(
        body: SetMusicProviderRequest,
        db: Db,
        admin: Admin,
        container: Container,
    ) -> MusicProviderConfigView:
        """Switch the active music generation provider. Owner only. Audited."""
        now = utc_now()
        unwrap(await write_music_provider(container.redis, body.provider))
        active = await read_music_provider(container.redis, default=PROVIDER_ELEVENLABS)
        await audit_sink.record(
            db,
            container,
            AuditEntry(
                action=AuditAction.CONFIG_COMMIT,
                actor_id=admin.admin_user_id,
                actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
                actor_role=admin.role,
                subject_type="config",
                subject_id="music_provider",
                reason_code=body.reason_code,
                reason_ref=body.reason_ref,
                reason_text=body.reason_text,
            ),
            now=now,
        )
        return to_music_provider_config_view(active_provider=active)

    @router.post(CONFIG_TEACHERS_DAY_PATH)
    async def set_teachers_day(
        body: SetTeachersDayRequest,
        db: Db,
        admin: Admin,
        container: Container,
    ) -> TeachersDayConfigView:
        """Switch the Teachers' Day feature flag. Owner only. Audited."""
        now = utc_now()
        unwrap(await write_teachers_day_enabled(container.redis, body.enabled))
        enabled = await read_teachers_day_enabled(container.redis)
        await audit_sink.record(
            db,
            container,
            AuditEntry(
                action=AuditAction.CONFIG_COMMIT,
                actor_id=admin.admin_user_id,
                actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
                actor_role=admin.role,
                subject_type="config",
                subject_id="teachers_day",
                reason_code=body.reason_code,
                reason_ref=body.reason_ref,
                reason_text=body.reason_text,
            ),
            now=now,
        )
        return to_teachers_day_config_view(
            enabled=enabled, discount_percent=TEACHERS_DAY_DISCOUNT_PERCENT
        )

    @router.post(CONFIG_CHECKOUT_RAILS_PATH)
    async def set_checkout_rail(
        body: SetCheckoutRailRequest,
        db: Db,
        admin: Admin,
        container: Container,
    ) -> CheckoutRailsConfigView:
        """Switch one checkout rail's sales on or off. Owner only. Audited.

        The write is an explicit ``"1"``/``"0"`` and a failed one is a 503 with NO audit row:
        the owner must not be told, by the panel or by the audit log, that a rail is shut when
        it is not. Settlement never reads this switch, so turning a rail off stops new
        payments only — money already in flight still settles (``DECISIONS.md D28``).
        """
        now = utc_now()
        unwrap(await write_rail_enabled(container.redis, body.rail, body.enabled))
        view = await _checkout_rails_view(container.redis)
        await audit_sink.record(
            db,
            container,
            AuditEntry(
                action=AuditAction.CONFIG_COMMIT,
                actor_id=admin.admin_user_id,
                actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
                actor_role=admin.role,
                subject_type="config",
                # The DIRECTION is in the subject: CONFIG_COMMIT alone cannot say whether a row
                # closed a rail or reopened it, and the switch's value lives only in Redis,
                # overwritten by the next write — this row is its only history. Inside
                # ``_SUBJECT_ID_PATTERN``; the global pause says the same with
                # RAIL_PAUSED / RAIL_RESUMED.
                subject_id=f"checkout_rail:{body.rail}:{'on' if body.enabled else 'off'}",
                reason_code=body.reason_code,
                reason_ref=body.reason_ref,
                reason_text=body.reason_text,
                ip=admin.client_ip,
            ),
            now=now,
        )
        return view

    return router
