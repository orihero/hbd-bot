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

from hbd.admin.routers.admins import build_admins_router
from hbd.admin.routers.assets import build_asset_media_router, build_assets_router
from hbd.admin.routers.audit import build_audit_router
from hbd.admin.routers.auth import build_auth_router, build_login_router
from hbd.admin.routers.config import build_config_router
from hbd.admin.routers.dashboard import build_dashboard_router
from hbd.admin.routers.generations import build_generations_router
from hbd.admin.routers.health import build_health_router
from hbd.admin.routers.orders import build_orders_router
from hbd.admin.routers.retention import build_retention_router
from hbd.admin.routers.reveal import build_reveal_router
from hbd.admin.routers.users import build_users_router, build_wizard_state_router

__all__ = [
    "build_admins_router",
    "build_asset_media_router",
    "build_assets_router",
    "build_audit_router",
    "build_auth_router",
    "build_config_router",
    "build_dashboard_router",
    "build_generations_router",
    "build_health_router",
    "build_login_router",
    "build_orders_router",
    "build_retention_router",
    "build_reveal_router",
    "build_users_router",
    "build_wizard_state_router",
]
