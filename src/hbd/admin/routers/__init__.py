"""The HTTP surface. One module per §6 section; the app factory mounts them.

Two conventions hold across every router here and every router later slices add:

* **The permission guard is declared on the router, never on a handler.** A per-handler
  guard is a guard somebody forgets on the next route (§12.1 T3), and the route-enumeration
  test reads the guard off the route's dependencies to prove exactly one is present.
* **No handler writes ``try``/``except``.** A failure is one ``ProblemError``; one
  handler renders the envelope (§6.2).
"""

from __future__ import annotations

from hbd.admin.routers.audit import build_audit_router
from hbd.admin.routers.auth import build_auth_router, build_login_router
from hbd.admin.routers.health import build_health_router
from hbd.admin.routers.retention import build_retention_router

__all__ = [
    "build_auth_router",
    "build_login_router",
    "build_health_router",
    "build_audit_router",
    "build_retention_router",
]
