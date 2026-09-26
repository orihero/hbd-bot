"""The HTTP surface. One module per §6 section; the app factory mounts them.

Two conventions hold across every router here and every router later slices add:

* **The permission guard is declared on the router, never on a handler.** A per-handler
  guard is a guard somebody forgets on the next route (§12.1 T3). The route-enumeration
  test proves it by calling every builder below and reading the guard off the ``APIRouter``
  it returns — not off the mounted route, whose ``dependencies`` list is the router's and
  the handler's concatenated and so cannot tell the two apart. Exactly one guard, and
  nothing a handler added on top.
* **No handler writes ``try``/``except``.** A failure is one ``ProblemError``; one
  handler renders the envelope (§6.2).
"""

from __future__ import annotations

from bayram.admin.routers.admins import build_admin_accounts_router, build_admins_router
from bayram.admin.routers.assets import build_asset_media_router, build_assets_router
from bayram.admin.routers.audit import build_audit_router
from bayram.admin.routers.auth import build_auth_router, build_login_router
from bayram.admin.routers.billing import (
    build_billing_records_router,
    build_payment_notify_router,
    build_rail_control_router,
    build_rail_router,
)
from bayram.admin.routers.broadcasts import (
    build_broadcast_actions_router,
    build_broadcasts_router,
)
from bayram.admin.routers.chats import build_chats_router
from bayram.admin.routers.config import build_config_router
from bayram.admin.routers.credits import build_credit_grant_router, build_credits_router
from bayram.admin.routers.dashboard import (
    build_audience_lists_router,
    build_dashboard_router,
)
from bayram.admin.routers.generations import build_generations_router
from bayram.admin.routers.health import build_health_router
from bayram.admin.routers.orders import build_orders_router
from bayram.admin.routers.retention import build_retention_router
from bayram.admin.routers.reveal import build_reveal_router
from bayram.admin.routers.segments import (
    build_segment_fields_router,
    build_segments_router,
)
from bayram.admin.routers.support import (
    build_support_actions_router,
    build_support_router,
)
from bayram.admin.routers.support_groups import (
    build_support_group_actions_router,
    build_support_groups_router,
)
from bayram.admin.routers.users import (
    build_user_block_router,
    build_users_router,
    build_wizard_state_router,
)
from bayram.admin.routers.vendors import build_vendors_router

__all__ = [
    "build_admin_accounts_router",
    "build_admins_router",
    "build_asset_media_router",
    "build_assets_router",
    "build_audience_lists_router",
    "build_audit_router",
    "build_auth_router",
    "build_billing_records_router",
    "build_broadcast_actions_router",
    "build_broadcasts_router",
    "build_chats_router",
    "build_config_router",
    "build_credit_grant_router",
    "build_credits_router",
    "build_dashboard_router",
    "build_generations_router",
    "build_health_router",
    "build_login_router",
    "build_orders_router",
    "build_payment_notify_router",
    "build_rail_control_router",
    "build_rail_router",
    "build_retention_router",
    "build_reveal_router",
    "build_segment_fields_router",
    "build_segments_router",
    "build_support_actions_router",
    "build_support_group_actions_router",
    "build_support_groups_router",
    "build_support_router",
    "build_user_block_router",
    "build_users_router",
    "build_vendors_router",
    "build_wizard_state_router",
]
