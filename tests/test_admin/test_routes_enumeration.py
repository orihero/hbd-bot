"""The application's route table, asserted whole — §12.1 T8, §14 Slice 1c.

This file exists because of a specific failure mode: a router that is written, unit-tested
against a locally-mounted copy, and then never included in ``create_app``. Every test in
``tests/test_admin/test_*_router.py`` passes; the endpoint 404s in production. Nothing else
in the suite notices, because a router test that mounts its own router is testing the router,
not the application.

So the assertions here are deliberately about ``create_app()`` and nothing else:

* **The table is frozen.** :data:`MOUNTED_ROUTES` spells out every method, path and
  router-level permission the application serves. A route that appears, disappears, moves or
  changes its guard fails here — including the one that was never mounted at all.
* **Every exported builder is reachable.** :data:`hbd.admin.routers.__all__` is walked and
  each builder's own paths are required to be present in the application. This is the half
  that catches the *next* router: adding it to the package's ``__all__`` without adding the
  ``include_router`` line is a failure, not a silence.
* **Exactly one guard, and it is on the router.** ``APIRoute.dependencies`` answers the
  first half and cannot answer the second: FastAPI builds that attribute by concatenating
  the router's ``dependencies=`` list with the decorator's own
  (``APIRouter.add_api_route``: ``current_dependencies = self.dependencies.copy()``, then
  ``extend(dependencies)``), so a guard moved off the router and onto the handler reads
  back through it identically — which is the exact substitution §12.1 T3 forbids.
  ``route.dependant`` is worse still, since it flattens the whole tree. So the guard is
  attributed instead by rebuilding every router ``hbd.admin.routers.__all__`` exports and
  reading ``APIRouter.dependencies`` — the router's own list, before FastAPI has copied it
  anywhere. Anything a route carries beyond what its router declares is a handler guard,
  and :func:`test_no_route_carries_a_guard_its_router_did_not_declare` requires that
  difference to be empty.
* **Every non-GET carries CSRF, and no GET writes.** Neither is a property of a route
  object: CSRF is enforced inside ``get_current_admin`` and "does not write" is not
  declared anywhere at all. So both are asserted twice — structurally, by freezing the set
  of mutations, and behaviourally, by sending the requests and by snapshotting every domain
  table around every GET the application serves.
* **The SPA mount changes none of it.** ``create_app()`` is only half the story since Slice
  1d: the static mount and the SPA fallback are installed by the *lifespan*, so the frozen
  table above describes an application nobody runs. The last section re-asserts it against
  the one they do, names the two SPA routes as the only exemption (:data:`SPA_ROUTE_NAMES`),
  closes that exemption so a third non-``APIRoute`` cannot slip in unnoticed, and then checks
  behaviourally that the catch-all answers for none of the table's paths.

Paths are built from ``API_PREFIX``/``AUTH_PREFIX`` and the routers' own path constants
rather than written as literals: §6.8's tables in the plan predate ``API_PREFIX = "/api"``
and spell every path without it, so a literal here would encode the doc's stale form.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from functools import cache
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from fastapi import APIRouter, params
from fastapi.routing import APIRoute

from hbd.admin import app as app_module
from hbd.admin import routers as routers_package
from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer
from hbd.admin.deps import API_PREFIX, AUTH_PREFIX, RequirePermission
from hbd.admin.errors import AdminErrorCode
from hbd.admin.middleware.security_headers import IMMUTABLE_PATH_PREFIX
from hbd.admin.routers.admins import ADMINS_PATH
from hbd.admin.routers.assets import (
    ASSET_PATH,
    ASSET_STREAM_PATH,
    ASSET_TEXT_PATH,
    ASSETS_PATH,
)
from hbd.admin.routers.audit import AUDIT_PATH, VERIFY_PATH
from hbd.admin.routers.config import CONFIG_PATH
from hbd.admin.routers.dashboard import (
    CAPABILITIES_PATH,
    FAILURES_PATH,
    LATENCY_PATH,
    NAME_ANALYTICS_PATH,
    NAME_STRATEGIES_PATH,
    ORDERS_BY_DAY_PATH,
    PULSE_PATH,
)
from hbd.admin.routers.generations import ATTEMPT_PATH, GENERATIONS_PATH
from hbd.admin.routers.health import STATUS_OK
from hbd.admin.routers.orders import (
    ORDER_ASSETS_PATH,
    ORDER_ATTEMPTS_PATH,
    ORDER_PATH,
    ORDER_TIMELINE_PATH,
    ORDERS_PATH,
)
from hbd.admin.routers.retention import RETENTION_PATH
from hbd.admin.routers.reveal import REVEAL_PATH
from hbd.admin.routers.users import (
    USER_ORDERS_PATH,
    USER_PATH,
    USERS_PATH,
    WIZARD_STATE_PATH,
)
from hbd.admin.security.permissions import RBAC_MATRIX, Permission, StepUpAction
from hbd.db.base import Base
from hbd.db.enums import AdminRole, AuditReasonCode
from hbd.db.models.asset import AssetRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from tests.test_admin.conftest import (
    ORIGIN,
    PASSWORD,
    USERNAME,
    api_routes,
    create_account,
    csrf_headers,
    sign_in,
)
from tests.test_admin.test_orders_router import TELEGRAM_ID, seed_named_order

#: The three routes reachable without a session: the two probes and the login itself.
#: ``/api/auth/login`` — never the doc's ``/auth/login``; see the module docstring.
EXEMPT_PATHS: Final[frozenset[str]] = frozenset({"/healthz", "/readyz", f"{AUTH_PREFIX}/login"})

#: Every route the application serves, as ``(method, path, permission)``. ``None`` in the
#: third position means the route carries no router-level guard, which only the exempt three
#: are allowed to do.
#:
#: Written out in full rather than derived: derivation from the routers would pass whether or
#: not ``app.py`` includes them, which is the exact bug this file is here to prevent. Adding
#: an endpoint means adding a line here, and that is the point.
MOUNTED_ROUTES: Final[frozenset[tuple[str, str, Permission | None]]] = frozenset(
    {
        # Probes and login — no session, no guard.
        ("GET", "/healthz", None),
        ("GET", "/readyz", None),
        ("POST", f"{AUTH_PREFIX}/login", None),
        # Own session.
        ("GET", f"{AUTH_PREFIX}/me", Permission.SESSION_SELF),
        ("POST", f"{AUTH_PREFIX}/logout", Permission.SESSION_SELF),
        ("POST", f"{AUTH_PREFIX}/password", Permission.SESSION_SELF),
        ("POST", f"{AUTH_PREFIX}/step-up", Permission.SESSION_SELF),
        # Dashboard and metrics.
        ("GET", PULSE_PATH, Permission.DASHBOARD_READ),
        ("GET", CAPABILITIES_PATH, Permission.DASHBOARD_READ),
        ("GET", ORDERS_BY_DAY_PATH, Permission.DASHBOARD_READ),
        ("GET", FAILURES_PATH, Permission.DASHBOARD_READ),
        ("GET", LATENCY_PATH, Permission.DASHBOARD_READ),
        ("GET", NAME_STRATEGIES_PATH, Permission.DASHBOARD_READ),
        # The name bake-off's full shape — same window, same population, same guard as the
        # bare series above. Aggregate counts only: no name, no candidate text, no
        # transcript, so it belongs to DASHBOARD_READ rather than to RECORDS_READ.
        ("GET", NAME_ANALYTICS_PATH, Permission.DASHBOARD_READ),
        # Records.
        ("GET", ORDERS_PATH, Permission.RECORDS_READ),
        ("GET", ORDER_PATH, Permission.RECORDS_READ),
        ("GET", ORDER_ATTEMPTS_PATH, Permission.RECORDS_READ),
        ("GET", ORDER_ASSETS_PATH, Permission.RECORDS_READ),
        ("GET", ORDER_TIMELINE_PATH, Permission.RECORDS_READ),
        ("GET", USERS_PATH, Permission.RECORDS_READ),
        ("GET", USER_PATH, Permission.RECORDS_READ),
        ("GET", USER_ORDERS_PATH, Permission.RECORDS_READ),
        ("GET", GENERATIONS_PATH, Permission.RECORDS_READ),
        ("GET", ATTEMPT_PATH, Permission.RECORDS_READ),
        ("GET", ASSETS_PATH, Permission.RECORDS_READ),
        ("GET", ASSET_PATH, Permission.RECORDS_READ),
        # The two audited media reveals, and the reason they carry a different cell from
        # the two metadata routes directly above. §12.2 row 10 is ``A+S``; a router-level
        # guard resolves to ``check_role``, which holds no subject and therefore no grant,
        # so guarding these with REVEAL_MEDIA would answer STEP_UP_REQUIRED to an operator
        # holding a live, correctly-scoped grant, for ever. The row is split exactly the way
        # §12.2 split the admin roster: REVEAL_MEDIA_READ is the role half and lives here,
        # and REVEAL_MEDIA's ``A+S`` cell is enforced inside the handler on the asset id it
        # has read. Both run on every request; neither is sufficient alone.
        ("GET", ASSET_STREAM_PATH, Permission.REVEAL_MEDIA_READ),
        ("GET", ASSET_TEXT_PATH, Permission.REVEAL_MEDIA_READ),
        # The wizard-state projection is a second router precisely so it can carry a
        # different cell from the records around it (§12.2 row 5).
        ("GET", WIZARD_STATE_PATH, Permission.WIZARD_STATE_READ),
        # Operations.
        ("GET", CONFIG_PATH, Permission.CONFIG_READ),
        ("GET", RETENTION_PATH, Permission.RETENTION_READ),
        ("GET", AUDIT_PATH, Permission.AUDIT_READ),
        ("GET", VERIFY_PATH, Permission.AUDIT_READ),
        # ADMIN_READ, not ADMIN_MANAGE: §6.8 line 949 lists this GET as a bare owner ``W``
        # and gives the four account writes below it an explicit ``W +S``. ``ADMIN_MANAGE``
        # keeps that ``W+S`` cell and guards no route in this slice.
        ("GET", ADMINS_PATH, Permission.ADMIN_READ),
        # The one path by which masked data becomes plaintext (§12.2 line 1886: "every ``A``
        # cell routes through the same ``POST /reveal`` endpoint"). Its row is split like the
        # two media routes above and for the same ``check_role`` reason —
        # REVEAL_PERSONAL_DATA_READ is the role half declared here, and
        # REVEAL_PERSONAL_DATA's ``A+S`` cell is enforced by the handler on the subject in
        # the body. It is the only POST in this table that is not an auth route.
        ("POST", REVEAL_PATH, Permission.REVEAL_PERSONAL_DATA_READ),
    }
)

#: Every mutation the read-only slice ships. A fifth one is a deliberate edit to this set,
#: which is what makes "every non-GET is a POST that goes through the CSRF check inside
#: ``get_current_admin``" a claim a reviewer can check rather than one a route can escape.
MUTATIONS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("POST", f"{AUTH_PREFIX}/login"),
        ("POST", f"{AUTH_PREFIX}/logout"),
        ("POST", f"{AUTH_PREFIX}/password"),
        ("POST", f"{AUTH_PREFIX}/step-up"),
        # ``POST`` and not ``GET`` even though a reveal reads: the body carries a reason
        # code, an optional free-text reason and a field list, and §12.1 T8 requires that no
        # GET change state — a reveal writes an audit row and charges a budget, so it is a
        # mutation by that rule whatever the verb suggests. Being a POST is also what puts
        # it behind the CSRF check inside ``get_current_admin``.
        ("POST", REVEAL_PATH),
    }
)

#: The two routes the SPA mount installs, by ``name`` — and the whole of what is exempt from
#: :data:`MOUNTED_ROUTES`. §11.1, Slice 1d.
#:
#: They are exempt because of what they *are*, not because of what they serve. ``spa-assets``
#: is a Starlette ``Mount`` and ``spa-index`` a plain Starlette ``Route``; neither is an
#: ``APIRoute``, so neither has anywhere for FastAPI to copy a router's ``dependencies=`` list
#: to and there is no guard on either to assert. Nor should there be: they serve the static
#: bundle that draws the login screen, so a permission guard would put the login behind the
#: login. They read no session and touch no database.
#:
#: That exemption is a real hole, and this is where it is closed rather than widened.
#: ``api_routes`` skips every non-``APIRoute`` silently, so an endpoint written as a bare
#: ``Route`` or a ``Mount`` — under ``/api`` or anywhere else — would be invisible to every
#: assertion in this file, guard and all, and "the table is unchanged" would then be true
#: because the route was skipped rather than because it does not exist.
#: :func:`test_the_non_api_routes_are_exactly_the_named_exemptions` pins the set closed, so a
#: third one fails here and has to be argued for.
SPA_ROUTE_NAMES: Final[frozenset[str]] = frozenset({"spa-assets", "spa-index"})

#: FastAPI's own schema document, which is not an ``APIRoute`` either and predates the SPA by
#: a long way. Named for the same reason: an exemption set is worth nothing unless it is closed.
FRAMEWORK_ROUTE_NAMES: Final[frozenset[str]] = frozenset({"openapi"})

_PATH_PARAM: Final[re.Pattern[str]] = re.compile(r"\{(\w+)\}")


def methods_of(route: APIRoute) -> set[str]:
    """The route's own methods, without the ``HEAD`` Starlette pairs with every ``GET``."""
    return {method for method in (route.methods or set()) if method != "HEAD"}


def method_paths(routes: Iterable[APIRoute]) -> set[tuple[str, str]]:
    """``(method, path)`` for every route given."""
    return {(method, route.path) for route in routes for method in methods_of(route)}


#: How a route is identified across the two places it is read from: the application, and the
#: router that built it. Path and methods together, because neither alone is unique — one
#: path can carry two methods and one method is shared by thirty paths.
RouteKey = tuple[str, frozenset[str]]


def route_key(route: APIRoute) -> RouteKey:
    """``(path, methods)`` — the identity a mounted route shares with its declaration."""
    return (route.path, frozenset(methods_of(route)))


def permission_guards(dependencies: Sequence[params.Depends]) -> list[RequirePermission]:
    """The :class:`RequirePermission` guards in a ``dependencies=`` list, in order."""
    return [d.dependency for d in dependencies if isinstance(d.dependency, RequirePermission)]


@cache
def builder_declarations() -> tuple[tuple[RouteKey, tuple[RequirePermission, ...]], ...]:
    """Every route the exported builders declare, paired with its **router's** own guards.

    Each builder is called and its ``APIRouter.dependencies`` read directly — the list the
    router was constructed with, which is the only reading of "the guard is on the router"
    that a handler-level guard cannot imitate. See :func:`guards_of`.

    Rebuilt rather than read off the application, so the attribution survives a FastAPI that
    stores included routers differently: this version keeps the source router on the wrapper
    it appends, an older one copies the routes in flat, and neither shape is asserted here.
    The guards are therefore *different instances* from the ones the running application
    holds, which is why everything below compares ``permission`` and never identity.

    A tuple of pairs rather than a dict so a collision is still visible; see
    :func:`test_no_two_builders_declare_the_same_route`.
    """
    declared: list[tuple[RouteKey, tuple[RequirePermission, ...]]] = []
    for name in routers_package.__all__:
        builder: Callable[[], APIRouter] = getattr(routers_package, name)
        router = builder()
        guards = tuple(permission_guards(router.dependencies))
        declared.extend(
            (route_key(route), guards) for route in router.routes if isinstance(route, APIRoute)
        )
    return tuple(declared)


@cache
def guards_declared_on_routers() -> dict[RouteKey, tuple[RequirePermission, ...]]:
    """:func:`builder_declarations` as a lookup."""
    return dict(builder_declarations())


def guards_of(route: APIRoute) -> list[RequirePermission]:
    """The permission guards the **router** declares for this route.

    Read off the ``APIRouter`` that builds the route, not off the route. ``APIRoute.dependencies``
    cannot tell the two apart: FastAPI builds it by copying the router's ``dependencies=``
    list and then extending it with the decorator's, so a guard moved from
    ``APIRouter(dependencies=[...])`` to ``@router.get(..., dependencies=[...])`` reads back
    through it unchanged — and that move is precisely what §12.1 T3 forbids.
    ``route.dependant`` is looser again, flattening the whole tree.

    An unattributable route — one no exported builder declares — returns ``[]``, i.e. no
    router-level guard, which is the truthful answer for a route registered straight onto the
    application. :func:`test_every_mounted_route_is_declared_by_an_exported_builder` is what
    keeps that fallback from quietly swallowing one.

    :func:`handler_guards_of` is the other half: what the route carries and the router did not
    declare.
    """
    return list(guards_declared_on_routers().get(route_key(route), ()))


def handler_guards_of(route: APIRoute) -> list[RequirePermission]:
    """The guards on the route that its router did not declare — the §12.1 T3 violation.

    A multiset difference, not a set one: a router guard duplicated on the handler is still a
    handler guard, and a set difference would report nothing.
    """
    unclaimed = list(guards_of(route))
    extra: list[RequirePermission] = []
    for guard in permission_guards(route.dependencies):
        match = next((d for d in unclaimed if d.permission is guard.permission), None)
        if match is None:
            extra.append(guard)
        else:
            unclaimed.remove(match)
    return extra


# ---------------------------------------------------------------------------
# The table, whole
# ---------------------------------------------------------------------------
def test_the_application_serves_exactly_the_expected_route_table(
    container: AdminContainer,
) -> None:
    # Arrange — the real factory, with nothing mounted on top of it. A test that mounts a
    # router here would be asserting its own wiring rather than ``app.py``'s.
    application = create_app(container=container)

    # Act
    served: set[tuple[str, str, Permission | None]] = set()
    for route in api_routes(application):
        guards = guards_of(route)
        permission = guards[0].permission if guards else None
        served.update((method, route.path, permission) for method in methods_of(route))

    # Assert — as a set difference in both directions, so the failure names the route rather
    # than reporting that two sets of thirty-one tuples are unequal.
    assert MOUNTED_ROUTES - served == set(), "declared but not mounted"
    assert served - MOUNTED_ROUTES == set(), "mounted but not declared"


def test_every_router_the_package_exports_is_actually_mounted(
    container: AdminContainer,
) -> None:
    # Arrange — the half that catches the *next* router: a builder exported from
    # ``hbd.admin.routers`` whose ``include_router`` line was never added to ``create_app``.
    application = create_app(container=container)
    served = method_paths(api_routes(application))

    # Act / Assert
    for name in routers_package.__all__:
        builder: Callable[[], APIRouter] = getattr(routers_package, name)
        router = builder()
        expected = method_paths(r for r in router.routes if isinstance(r, APIRoute))
        assert expected, f"{name} builds a router with no routes"
        assert served >= expected, f"{name} is exported but never included in create_app"


def test_no_route_is_registered_twice(container: AdminContainer) -> None:
    # Arrange — a duplicate answers from whichever copy was registered first, so a second
    # ``include_router`` of the same router is invisible at runtime and hides a wiring bug.
    application = create_app(container=container)

    # Act
    pairs = [
        (method, route.path) for route in api_routes(application) for method in methods_of(route)
    ]

    # Assert
    assert len(pairs) == len(set(pairs))


# ---------------------------------------------------------------------------
# The guard on each route
# ---------------------------------------------------------------------------
def test_every_route_outside_the_exempt_set_carries_exactly_one_router_guard(
    container: AdminContainer,
) -> None:
    # Arrange
    application = create_app(container=container)

    # Act / Assert
    for route in api_routes(application):
        guards = guards_of(route)
        if route.path in EXEMPT_PATHS:
            assert guards == [], route.path
        else:
            assert len(guards) == 1, route.path


def test_no_route_carries_a_guard_its_router_did_not_declare(
    container: AdminContainer,
) -> None:
    # Arrange — §12.1 T3 itself, and the only assertion in this file that can see the
    # difference. Every other one reads ``guards_of``, which now answers with the *router's*
    # list; a handler guard is invisible to it by construction, and would be invisible full
    # stop if the surplus were not asserted away here.
    application = create_app(container=container)

    # Act / Assert
    for route in api_routes(application):
        assert handler_guards_of(route) == [], route.path


def test_every_mounted_route_is_declared_by_an_exported_builder(
    container: AdminContainer,
) -> None:
    # Arrange — the assertion ``guards_of``'s fallback rests on. It answers ``[]`` for a route
    # no builder declares, which is honest but indistinguishable from "the router declares no
    # guard", so a route registered straight onto the application with a handler guard could
    # read as an unguarded one. Require every served route to have a declaration to be
    # attributed to.
    application = create_app(container=container)
    declared = guards_declared_on_routers()

    # Act / Assert
    for route in api_routes(application):
        assert route_key(route) in declared, route.path


def test_no_two_builders_declare_the_same_route() -> None:
    # Arrange — ``guards_declared_on_routers`` is a dict, so two builders declaring the same
    # ``(path, methods)`` would leave the later one's guards attributed to both routes and
    # the earlier one's read by nobody.

    # Act
    keys = [key for key, _ in builder_declarations()]

    # Assert
    assert len(keys) == len(set(keys))


def test_the_exempt_set_is_present_rather_than_merely_unmatched(
    container: AdminContainer,
) -> None:
    # Arrange — the previous test passes vacuously if a probe is renamed, which would widen
    # the unauthenticated surface silently. Assert the three exempt paths exist.
    application = create_app(container=container)

    # Act
    paths = {route.path for route in api_routes(application)}

    # Assert
    assert paths >= EXEMPT_PATHS


def test_every_guard_names_a_permission_the_matrix_has_a_row_for(
    container: AdminContainer,
) -> None:
    # Arrange — a permission added to the enum but never given a §12.2 row is a cell nobody
    # decided, and it would deny silently rather than fail loudly.
    application = create_app(container=container)

    # Act / Assert
    for route in api_routes(application):
        for guard in guards_of(route):
            assert guard.permission in RBAC_MATRIX, route.path


# ---------------------------------------------------------------------------
# Shape rules — §12.1 T3, T8
# ---------------------------------------------------------------------------
def test_the_only_non_get_routes_are_the_known_mutations(
    container: AdminContainer,
) -> None:
    # Arrange — CSRF is enforced inside ``get_current_admin`` rather than as a per-route
    # object, so there is nothing to enumerate; freezing the mutation set is what makes the
    # next one a decision. The behavioural half lives in ``test_auth_router.py``.
    application = create_app(container=container)

    # Act
    non_get = {
        (method, path) for method, path in method_paths(api_routes(application)) if method != "GET"
    }

    # Assert
    assert non_get == MUTATIONS


def test_no_namespace_mixes_identifier_names(container: AdminContainer) -> None:
    # Arrange — ``/orders/{order_id}`` and ``/orders/{id}`` in the same namespace is how a
    # caller learns to send the wrong identifier to the right-looking URL (§12.1 T3).
    application = create_app(container=container)
    by_namespace: dict[str, set[str]] = {}

    # Act
    for route in api_routes(application):
        parts = route.path.strip("/").split("/")
        if parts[0] != API_PREFIX.strip("/"):
            continue
        by_namespace.setdefault(parts[1], set()).update(_PATH_PARAM.findall(route.path))

    # Assert
    for namespace, names in by_namespace.items():
        assert len(names) <= 1, (namespace, names)


def test_every_path_parameter_is_typed(container: AdminContainer) -> None:
    # Arrange — a ``str`` path parameter is a parser in the handler, and a parser in the
    # handler is a 500 where a 422 belongs.
    application = create_app(container=container)

    # Act / Assert — ``field_info.annotation`` rather than the pydantic-v1 ``ModelField.type_``,
    # which this FastAPI's v2 compat shim does not carry.
    seen = 0
    for route in api_routes(application):
        for param in route.dependant.path_params:
            annotation = param.field_info.annotation
            assert annotation in (UUID, int), (route.path, param.name, annotation)
            seen += 1

    # Assert — and the loop ran, so a change that stops exposing path params fails here too.
    assert seen == sum(len(_PATH_PARAM.findall(path)) for _, path, _ in MOUNTED_ROUTES)


# ---------------------------------------------------------------------------
# CSRF — the behavioural half of "every non-GET carries CSRF"
# ---------------------------------------------------------------------------
#: A well-shaped body for each mutation, so a refusal here is the CSRF layer's and not the
#: request model's. The three guarded routes reach ``get_current_admin`` — and therefore
#: ``deps.enforce_csrf`` — before any of these fields is read; ``/api/auth/login`` never
#: reaches it at all and calls ``auth._enforce_origin`` itself, which is why it appears in
#: the origin test below and not in the token one.
_MUTATION_BODIES: Final[dict[str, dict[str, Any]]] = {
    f"{AUTH_PREFIX}/login": {"username": USERNAME, "password": PASSWORD},
    f"{AUTH_PREFIX}/logout": {},
    f"{AUTH_PREFIX}/password": {
        "currentPassword": PASSWORD,
        "newPassword": "a-replacement-nobody-chose-for-them",
    },
    f"{AUTH_PREFIX}/step-up": {
        "password": PASSWORD,
        "scope": StepUpAction.REVEAL.value,
        "subjectId": "3f2b9c1e-0a5d-4f61-9c2a-7b18d4e6f0a3",
    },
    # Well-shaped rather than answerable: the CSRF and origin checks run inside
    # ``get_current_admin``, long before this body is validated or the order is looked up,
    # so a refusal here is the layer under test and not the request model or a 404.
    REVEAL_PATH: {
        "subjectType": "order",
        "subjectId": "3f2b9c1e-0a5d-4f61-9c2a-7b18d4e6f0a3",
        "fields": ["briefs.recipient_name_display"],
        "reasonCode": AuditReasonCode.SUPPORT_INVESTIGATION.value,
    },
}

#: The mutations that go through the permission guard, and therefore through the CSRF check
#: inside ``get_current_admin``. Derived from :data:`MUTATIONS` rather than listed again, so
#: a fifth mutation is covered the moment it is added to the frozen set.
GUARDED_MUTATIONS: Final[tuple[str, ...]] = tuple(
    sorted(path for _, path in MUTATIONS if path != f"{AUTH_PREFIX}/login")
)


def test_every_mutation_has_a_body_the_csrf_tests_can_send() -> None:
    # Arrange / Act — the two tests below are only as complete as this mapping, and a
    # mutation added to ``MUTATIONS`` without a body here would silently go unprobed.

    # Assert
    assert set(_MUTATION_BODIES) == {path for _, path in MUTATIONS}


@pytest.mark.parametrize("path", GUARDED_MUTATIONS, ids=str)
async def test_a_mutation_without_the_csrf_token_is_refused(
    container: AdminContainer, client: httpx.AsyncClient, path: str
) -> None:
    # Arrange — a signed-in operator, with the cookie jar a browser would carry. The only
    # thing missing is the header, which is exactly what a cross-site form cannot add.
    await create_account(container, role=AdminRole.OWNER)
    assert (await sign_in(client)).status_code == 200

    # Act
    response = await client.post(path, json=_MUTATION_BODIES[path], headers={"Origin": ORIGIN})

    # Assert
    assert response.status_code == 403, path
    assert response.json()["error"]["code"] == AdminErrorCode.CSRF_REJECTED.value, path


@pytest.mark.parametrize("path", sorted({path for _, path in MUTATIONS}), ids=str)
async def test_a_mutation_from_a_foreign_origin_is_refused(
    container: AdminContainer, client: httpx.AsyncClient, path: str
) -> None:
    # Arrange — the login is included here and excluded above: it is exempt from the
    # permission guard, so its origin check is its own, and a regression there would be
    # invisible to every other test in this file.
    await create_account(container, role=AdminRole.OWNER)
    assert (await sign_in(client)).status_code == 200
    headers = csrf_headers(client) | {"Origin": "https://not-the-panel.example"}

    # Act
    response = await client.post(path, json=_MUTATION_BODIES[path], headers=headers)

    # Assert
    assert response.status_code == 403, path
    assert response.json()["error"]["code"] == AdminErrorCode.ORIGIN_REJECTED.value, path


async def test_no_route_answers_a_method_the_table_does_not_declare(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — Starlette answers 405 for a method a path does not carry, and that is the
    # answer wanted: a route that quietly accepted DELETE would be a mutation nobody froze.
    await create_account(container, role=AdminRole.OWNER)
    assert (await sign_in(client)).status_code == 200
    headers = csrf_headers(client)

    # Act / Assert
    for method, path, _ in MOUNTED_ROUTES:
        if "{" in path:
            continue
        forbidden = "POST" if method == "GET" else "DELETE"
        response = await client.request(forbidden, path, headers=headers)
        assert response.status_code == 405, (forbidden, path)


# ---------------------------------------------------------------------------
# §12.1 T8 — no GET route changes state
# ---------------------------------------------------------------------------
#: The two tables a GET is *allowed* to touch, excluded explicitly rather than left to luck.
#:
#: ``admin_sessions``: ``deps.get_current_admin`` → ``sessions.touch_session`` advances
#: ``last_seen_at`` and ``last_ip`` on every authenticated request, GET included. It is
#: throttled to ``sessions.IDLE_TOUCH_INTERVAL_S`` seconds, so a test that signs in and
#: immediately reads would observe no write at all — which is precisely why the exclusion is
#: written down instead of relied upon. The Redis mirror of that row is excluded for the
#: same reason and is not part of the snapshot either.
#:
#: ``admin_audit_log``: a refused request writes its own committed refusal row (§12.6,
#: ``deps.RequirePermission``). The sweep below runs as OWNER and every GET it makes is now
#: allowed — ``GET /api/admins`` included, since the roster moved onto ``ADMIN_READ`` — so
#: nothing here provokes one today. The exclusion stays because the rule it protects is
#: §12.6's, not this sweep's: the day a GET lands whose cell the sweeping role lacks, losing
#: that refusal row would be the wrong way to keep this test green.
#:
#: T8's rule is about domain state, and every other table in the schema is domain state.
GET_WRITABLE_TABLES: Final[frozenset[str]] = frozenset({"admin_sessions", "admin_audit_log"})


async def state_snapshot(container: AdminContainer) -> dict[str, list[str]]:
    """Every row of every domain table, as comparable text.

    Whole rows rather than ``COUNT(*)`` and a few ``updated_at`` columns: an UPDATE that
    rewrites a column in place moves no count and would pass a count-based check, and the
    columns a future writer touches are not knowable from here.
    """
    async with container.session_factory.begin() as db:
        return {
            table.name: sorted(repr(tuple(row)) for row in (await db.execute(sa.select(table))))
            for table in Base.metadata.sorted_tables
            if table.name not in GET_WRITABLE_TABLES
        }


async def test_no_get_route_changes_domain_state(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a populated database, so a GET has real rows to spoil, and real identifiers
    # in every path, so each handler runs its query rather than short-circuiting on a 404.
    order_id = await seed_named_order(container)
    async with container.session_factory.begin() as db:
        asset_id = (await db.execute(sa.select(AssetRow.id))).scalars().first()
        attempt_id = (await db.execute(sa.select(GenerationAttemptRow.id))).scalars().first()
    assert asset_id is not None and attempt_id is not None
    identifiers = {
        "order_id": order_id,
        "telegram_user_id": TELEGRAM_ID,
        "asset_id": asset_id,
        "attempt_id": attempt_id,
    }
    await create_account(container, role=AdminRole.OWNER)
    assert (await sign_in(client)).status_code == 200

    # Act / Assert — snapshotted around each route in turn, so a failure names the offender
    # instead of reporting that the database moved at some point during a sweep of thirty.
    for method, template, _ in sorted(MOUNTED_ROUTES):
        if method != "GET":
            continue
        path = template.format(**identifiers)
        before = await state_snapshot(container)
        response = await client.get(path)
        assert response.status_code != 500, path
        assert await state_snapshot(container) == before, path


# ---------------------------------------------------------------------------
# The SPA mount — the same table, asserted against the application that ships
# ---------------------------------------------------------------------------
#: Path-parameter values for the sweeps below. Well-formed rather than real: every guarded
#: route refuses an unauthenticated caller before its handler runs, so the row need not exist
#: — but the value must still parse, or a 422 would stand in for the 401 being looked for.
_PROBE_IDENTIFIERS: Final[dict[str, object]] = {
    "order_id": UUID(int=1),
    "telegram_user_id": 1,
    "asset_id": UUID(int=2),
    "attempt_id": UUID(int=3),
}


@pytest.fixture
def spa_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A directory shaped like ``vite build``'s output, patched onto ``hbd.admin.app``.

    Patched rather than written into ``src/hbd/admin/static``, because whether that directory
    exists depends on whether anybody has run ``make ui-build``. Without the patch these
    tests would assert one thing on a developer's machine and pass vacuously on CI, where the
    bundle is absent and the fallback 404s before it can shadow anything.

    Returns the shell's marker text, so a caller can assert a response *is* it — and, below,
    that thirty other responses are not.
    """
    shell = "<!doctype html><title>hbd admin</title><div id=root></div>"
    static = tmp_path / "static"
    (static / IMMUTABLE_PATH_PREFIX.strip("/")).mkdir(parents=True)
    (static / "index.html").write_text(shell, encoding="utf-8")
    monkeypatch.setattr(app_module, "STATIC_DIR", static)
    monkeypatch.setattr(app_module, "SPA_INDEX", static / "index.html")
    return shell


async def test_the_route_table_is_unchanged_once_the_spa_mount_is_installed(
    container: AdminContainer,
) -> None:
    # Arrange — every structural assertion above reads ``create_app()``'s output, and that
    # application has NO SPA routes: ``app._mount_spa`` runs from the lifespan, so a catch-all
    # cannot shadow a route registered after the factory. Which means the frozen table has so
    # far been asserted against an application nobody actually runs. Assert it again against
    # the one they do.
    application = create_app(container=container)

    # Act
    async with application.router.lifespan_context(application):
        served: set[tuple[str, str, Permission | None]] = set()
        for route in api_routes(application):
            guards = guards_of(route)
            permission = guards[0].permission if guards else None
            served.update((method, route.path, permission) for method in methods_of(route))

    # Assert — the same two differences as the unmounted case, and the same strictness. The
    # SPA contributed nothing to either side; that is the claim, and it is not weakened to
    # accommodate the mount.
    assert MOUNTED_ROUTES - served == set(), "declared but not mounted"
    assert served - MOUNTED_ROUTES == set(), "mounted but not declared"


async def test_the_non_api_routes_are_exactly_the_named_exemptions(
    container: AdminContainer,
) -> None:
    # Arrange — the assertion that keeps ``api_routes``' ``isinstance`` filter honest, and the
    # reason the test above can be trusted. See :data:`SPA_ROUTE_NAMES`.
    application = create_app(container=container)

    # Act
    async with application.router.lifespan_context(application):
        names: set[str | None] = set()
        for route in application.routes:
            if isinstance(route, APIRoute):
                continue
            # The wrapper ``include_router`` appends. It carries APIRoutes, which
            # ``api_routes`` walks and the frozen table covers, so it is not an exemption.
            if isinstance(getattr(route, "original_router", None), APIRouter):
                continue
            names.add(getattr(route, "name", None))

    # Assert
    assert names == set(SPA_ROUTE_NAMES | FRAMEWORK_ROUTE_NAMES)


async def test_the_catch_all_shadows_no_route_in_the_table(
    container: AdminContainer, spa_bundle: str
) -> None:
    # Arrange — the structural tests prove the catch-all is not an ``APIRoute``. They do not
    # prove it never *answers*: Starlette matches in registration order, so a mount installed
    # one line too early would shadow real routes while leaving the route table untouched.
    # Unauthenticated is the sharpest probe available, and needs no seeding: a guarded route
    # answers 401 with a JSON envelope and the shell is a 200 of HTML, so the two cannot be
    # confused with each other.
    application = create_app(container=container)

    # Act / Assert
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            # First, that the fallback is live at all. Without this every assertion below
            # would pass on an application whose SPA mount was simply broken.
            shell = await http.get("/orders/00000000-0000-0000-0000-000000000001")
            assert shell.status_code == 200
            assert shell.text == spa_bundle

            for method, template, _ in sorted(MOUNTED_ROUTES):
                path = template.format(**_PROBE_IDENTIFIERS)
                response = await http.request(method, path)
                assert response.status_code != 404, (method, path)
                assert response.text != spa_bundle, (method, path)
                content_type = response.headers.get("content-type", "")
                assert "text/html" not in content_type, (method, path, content_type)


async def test_the_probes_answer_exactly_what_they_did_before_the_spa(
    container: AdminContainer, spa_bundle: str
) -> None:
    # Arrange — the two routes an orchestrator polls, and the two likeliest to be quietly
    # replaced by a 200 of HTML: both are unauthenticated GETs on short paths, which is the
    # exact shape the catch-all exists to serve. ``/healthz`` matters most, because it answers
    # 200 with an EMPTY body — so a shadowing catch-all would still read as "up" to anything
    # that only looks at the status code.
    application = create_app(container=container)

    # Act
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            live = await http.get("/healthz")
            ready = await http.get("/readyz")

    # Assert — byte for byte what ``test_health.py`` asserts, restated here because that file
    # would keep passing if the shell were served with the right status code and the wrong body.
    assert live.status_code == 200
    assert live.content == b""
    assert ready.status_code == 200
    assert ready.json() == {"status": STATUS_OK}
