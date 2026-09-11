"""The admin API, the real one, on a real socket, with a seeded database — for Playwright.

``python -m tests.e2e.serve_admin_e2e`` is the ``webServer`` behind ``admin-ui/e2e``. It
exists because §14 Slice 1d's last acceptance bullet — *"Playwright smoke passes with the
production CSP applied"* — is the only gate in the plan that puts the console in front of a
browser that ENFORCES the policy. jsdom parses no CSP at all, so the Vitest suite is
structurally blind to the class of defect this catches: a stylesheet the browser refuses,
an inline style with no nonce, a scroll lock that silently does nothing.

**What is real here, and it is nearly everything.** The ASGI application is
:func:`bayram.admin.app.create_app` with its lifespan entered, which means the real
``SecurityHeadersMiddleware`` mints the real per-response nonce and stamps the real
``CSP_TEMPLATE``; the real ``_serve_spa_index`` renders the real built bundle out of
``src/bayram/admin/static``; the real routers answer with the real §12.3 masking; the login is
a real argon2 verify against a real ``admin_users`` row written by the real
``accounts.insert_first_owner`` — the statement ``bayram.admin.bootstrap`` uses. Nothing about
the policy, the shell or the wire format is re-stated on this side, so the gate cannot
drift from the middleware: the browser reads the header the middleware wrote, and the
manifest publishes :data:`~bayram.admin.middleware.security_headers.CSP_TEMPLATE` itself for
the assertion that the header is the whole policy rather than a lookalike.

**What is faked is exactly what the unit suite fakes**, and for the same reason: the
database is the in-memory SQLite every ``tests/test_admin`` test runs on, Redis is a
dictionary, and the rate limiter counts in a dict. So this gate needs no Postgres, no
Redis, no network, no vendor key and no ffmpeg — it is a unit-test-shaped process that
happens to listen on a port.

**http://127.0.0.1 is not a shortcut.** The session and CSRF cookies are ``__Host-``
prefixed and therefore ``Secure``; Chrome treats ``127.0.0.1`` as a potentially trustworthy
origin and stores them over plain http, which is the same allowance
``AdminSettings.is_cookie_secure``'s docstring already relies on. ``BAYRAM_ADMIN_PUBLIC_ORIGIN``
is set to the same origin, so the ``ORIGIN_REJECTED`` check is live for every write the
browser makes — the login POST included.

The seed is small and hand-counted: :data:`EXPECTED` states what Live Ops must show, row by
row, so a wrong aggregate in the API fails the browser assertion instead of being confirmed
by it. Nothing in this file asks the API what the numbers are.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import uvicorn

from bayram.admin.app import SPA_INDEX, create_app
from bayram.admin.container import AdminContainer
from bayram.admin.middleware.security_headers import CSP_TEMPLATE
from bayram.admin.schemas.common import MIN_PASSWORD_CHARS
from bayram.admin.security.passwords import hash_password
from bayram.config import ENV_PREFIX
from bayram.contracts import OrderState
from bayram.db.admin import accounts
from bayram.db.base import utc_now
from bayram.errors import ErrorCode
from tests.test_admin.conftest import (
    NOW,
    FakeRedis,
    MemoryRateLimits,
    make_settings,
    open_container,
)
from tests.test_admin.test_orders_router import (
    MASKED_TELEGRAM_ID,
    PURGED_AT,
    TELEGRAM_ID,
    seed_attempt,
    seed_brief,
    seed_order,
    seed_purged_brief,
    seed_user,
)

__all__ = ["EXPECTED", "MANIFEST_PATH", "build_manifest", "main", "seed"]

HOST: Final[str] = "127.0.0.1"
PORT: Final[int] = int(os.environ.get("BAYRAM_E2E_PORT", "8099"))
ORIGIN: Final[str] = f"http://{HOST}:{PORT}"

#: The console's repo-relative home. ``parents[2]`` is the repository root.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Where the Playwright side reads everything it must not hard-code. Gitignored.
MANIFEST_PATH: Final[Path] = Path(
    os.environ.get("BAYRAM_E2E_MANIFEST", str(_REPO_ROOT / "admin-ui" / "e2e" / ".manifest.json"))
)

#: The bootstrapped OWNER. ``insert_first_owner`` always sets ``must_change_password``, so
#: the browser flow includes the forced rotation — that is the real shape of a first sign-in
#: and skipping it would test a state no bootstrapped panel is ever in.
USERNAME: Final[str] = "e2e-owner"
BOOTSTRAP_PASSWORD: Final[str] = "bootstrap-password-e2e"
ROTATED_PASSWORD: Final[str] = "rotated-password-e2e"

#: The two names the product exists to spell. U+02BB MODIFIER LETTER TURNED COMMA in both.
NAME_GULOM: Final[str] = "Gʻulom"
NAME_OKTAM: Final[str] = "Oʻktam"
#: What §12.3 allows out of a read endpoint: first grapheme cluster + ``•••``.
MASKED_GULOM: Final[str] = "G•••"
MASKED_OKTAM: Final[str] = "O•••"

#: The other two strings §14 Slice 1d's font-coverage bullet names. They are not seeded into
#: any order — they are there to be DRAWN, by ``admin-ui/e2e/font-coverage.spec.ts``, which
#: rasterises every character and refuses a ``.notdef`` box. ``Дилноза`` is Cyrillic and
#: ``sanʼat`` carries U+02BC MODIFIER LETTER APOSTROPHE, a different codepoint from the
#: U+02BB in the two names above; a font can easily cover one and not the other.
NAME_DILNOZA: Final[str] = "Дилноза"
WORD_SANAT: Final[str] = "sanʼat"

#: Telegram ids. The purged order belongs to a second customer so the identity sweep's
#: effect is not entangled with the named orders' user row.
PURGED_TELEGRAM_ID: Final[int] = TELEGRAM_ID + 1

#: The one recorded failure, on both the order (triage text) and its generation attempt
#: (which is what the pulse's failure mix actually groups by).
FAILURE_CODE: Final[str] = ErrorCode.UPSTREAM_TIMEOUT.value

_LATENCY_DELIVERED_S: Final[int] = 180
_LATENCY_PURGED_S: Final[int] = 300

#: What Live Ops must show, counted by hand off :func:`seed` and never read back from the
#: API. Each number names the rows that produce it.
#:
#: * ``inFlight`` — the pulse takes NO window, so it is every non-terminal order ever:
#:   the ``generating`` one and the ``authorized`` one.
#: * the 24 h figures come from ``/metrics/orders-by-day`` over a rolling 24 h, so the
#:   hundred-day-old purged order is outside them and the four live ones are inside.
#: * ``successRate`` is ``delivered / (delivered + failed)`` — 1/2 — which `formatRate`
#:   renders at one decimal place.
EXPECTED: Final[dict[str, object]] = {
    "inFlight": 2,
    "orders24h": 4,
    "delivered24h": 1,
    "failed24h": 1,
    "paid24h": 3,
    "terminal24h": 2,
    "successRatePercent": 50.0,
    #: Every order the unfiltered `/orders` page must carry: the four live ones plus the
    #: purged one.
    "ordersTotal": 5,
    #: `LIVE_ORDER_STATES` — authorized, generating, failed.
    "attentionRows": 3,
    #: The pulse's failure mix: one failed generation attempt, so one row at 100%.
    "failureCode": FAILURE_CODE,
    "failureRows": 1,
}


async def _bootstrap_owner(container: AdminContainer) -> UUID:
    """Create the first OWNER through the statement ``bayram.admin.bootstrap`` uses.

    ``accounts.insert_first_owner`` rather than a bare ``create``: it is the §12.6
    conditional insert, it is what the CLI calls, and it is what decides that the account
    arrives with ``must_change_password`` set. The CLI's own ``_run`` is not reachable from
    here — it builds its own container from the environment, which for an in-memory SQLite
    URL is a different database in the same process.
    """
    async with container.session_factory.begin() as db:
        row = await accounts.insert_first_owner(
            db,
            username=USERNAME,
            password_hash=hash_password(BOOTSTRAP_PASSWORD, hasher=container.hasher),
            now=utc_now(),
        )
    if row is None:
        raise RuntimeError("the seeded database already had an admin account")
    return row.id


async def seed(container: AdminContainer) -> dict[str, Any]:
    """Five orders, two customers, one lawful purge. Returns what the browser must find.

    The four live orders are placed on the wall clock, minutes and hours back, because the
    24 h window the SPA asks for is built from the BROWSER's ``Date.now()`` — a fixture
    pinned to a constant instant would fall out of that window and the hero tile would go
    blank for a reason that has nothing to do with the console.

    The purged order is placed on the suite's fixed ``NOW`` instead: it is a hundred days
    old by construction, its identity was swept ninety-odd days after it was created, and
    both facts have to stay stable so the rendered date can be asserted exactly.
    """
    now = datetime.now(UTC)
    async with container.session_factory.begin() as db:
        user = await seed_user(db, telegram_user_id=TELEGRAM_ID)

        delivered_at = now - timedelta(hours=4) + timedelta(seconds=_LATENCY_DELIVERED_S)
        delivered = await seed_order(
            db,
            user=user,
            state=OrderState.DELIVERED,
            created_at=now - timedelta(hours=4),
            updated_at=delivered_at,
            delivered_at=delivered_at,
            is_paid=True,
            correlation_id="e2e-delivered",
        )
        await seed_brief(
            db, order=delivered, recipient_name_display=NAME_GULOM, recipient_name_raw=NAME_GULOM
        )

        failed = await seed_order(
            db,
            user=user,
            state=OrderState.FAILED,
            created_at=now - timedelta(hours=3),
            updated_at=now - timedelta(hours=3) + timedelta(minutes=2),
            is_paid=False,
            failed_reason=FAILURE_CODE,
            correlation_id="e2e-failed",
        )
        await seed_brief(
            db, order=failed, recipient_name_display=NAME_OKTAM, recipient_name_raw=NAME_OKTAM
        )
        # The pulse's failure mix is grouped from `generation_attempts.error_code`, not from
        # `orders.failed_reason` (`bayram.db.admin.metrics.failure_breakdown`), so a failed
        # ORDER alone leaves that panel on its empty state. One failed attempt is what makes
        # the panel render a real `ErrorCodeBadge` for the smoke to read.
        await seed_attempt(
            db,
            order=failed,
            is_success=False,
            error_code=FAILURE_CODE,
            error_message="the provider did not answer in time",
        )

        generating = await seed_order(
            db,
            user=user,
            state=OrderState.GENERATING,
            created_at=now - timedelta(minutes=30),
            updated_at=now - timedelta(minutes=25),
            is_paid=True,
            correlation_id="e2e-generating",
        )
        await seed_brief(
            db, order=generating, recipient_name_display=NAME_GULOM, recipient_name_raw=NAME_GULOM
        )

        authorized = await seed_order(
            db,
            user=user,
            state=OrderState.AUTHORIZED,
            created_at=now - timedelta(minutes=20),
            updated_at=now - timedelta(minutes=20),
            is_paid=True,
            correlation_id="e2e-authorized",
        )
        await seed_brief(
            db, order=authorized, recipient_name_display=NAME_OKTAM, recipient_name_raw=NAME_OKTAM
        )

        # The lawful purge. `seed_purged_brief` clears every identity column and records
        # `PURGED_AT`, which is exactly what the 90-day sweep leaves behind — the row
        # `db.mapping.to_order` refuses to map and `/orders` must still page over.
        purged_user = await seed_user(db, telegram_user_id=PURGED_TELEGRAM_ID)
        purged_delivered_at = NOW - timedelta(days=100) + timedelta(seconds=_LATENCY_PURGED_S)
        purged = await seed_order(
            db,
            user=purged_user,
            state=OrderState.DELIVERED,
            created_at=NOW - timedelta(days=100),
            updated_at=purged_delivered_at,
            delivered_at=purged_delivered_at,
            is_paid=True,
            correlation_id="e2e-purged",
        )
        await seed_purged_brief(db, order=purged)

    return {
        "deliveredOrderId": str(delivered.id),
        "failedOrderId": str(failed.id),
        "purgedOrderId": str(purged.id),
        # `formatDate` renders UTC by default and the Playwright project pins the browser's
        # zone to UTC, so this is the string the cell must contain, character for character.
        "purgedDate": PURGED_AT.astimezone(UTC).strftime("%Y-%m-%d"),
        "telegramUserId": TELEGRAM_ID,
        "telegramUserIdMasked": MASKED_TELEGRAM_ID,
    }


def build_manifest(seeded: dict[str, Any]) -> dict[str, Any]:
    """Everything the Playwright side must not spell for itself.

    ``cspTemplate`` is the middleware's own constant, carried across the language boundary
    rather than transcribed: the browser test formats it with the nonce it read off the
    live response and asserts the whole header equals the result, so a policy edited in
    ``security_headers.py`` either travels here or turns the gate red.
    """
    return {
        "baseUrl": ORIGIN,
        "cspTemplate": CSP_TEMPLATE,
        "username": USERNAME,
        "bootstrapPassword": BOOTSTRAP_PASSWORD,
        "rotatedPassword": ROTATED_PASSWORD,
        "names": {
            "gulom": NAME_GULOM,
            "oktam": NAME_OKTAM,
            "dilnoza": NAME_DILNOZA,
            "sanat": WORD_SANAT,
            "maskedGulom": MASKED_GULOM,
            "maskedOktam": MASKED_OKTAM,
        },
        "expected": EXPECTED,
        "seeded": seeded,
    }


def _strip_bayram_environment() -> None:
    """No ``BAYRAM_`` variable from the developer's shell reaches this process.

    The same isolation ``tests/test_admin/conftest.py`` applies per test. Settings are
    passed explicitly below, but pydantic-settings still reads the environment for any
    field a caller left out, and a stray ``BAYRAM_ADMIN_PUBLIC_ORIGIN`` would 403 every write
    the browser makes with no hint as to why.
    """
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            del os.environ[name]


async def _serve() -> int:
    if len(ROTATED_PASSWORD) < MIN_PASSWORD_CHARS:
        raise RuntimeError("the rotated password is shorter than the server will accept")
    if not SPA_INDEX.is_file():
        sys.stderr.write(
            f"No SPA bundle at {SPA_INDEX}. Run `make ui-build` first — this gate serves the\n"
            "built console, not the dev server.\n"
        )
        return 2

    _strip_bayram_environment()
    settings = make_settings(admin_public_origin=ORIGIN)
    async with open_container(settings, FakeRedis(), MemoryRateLimits()) as container:
        await _bootstrap_owner(container)
        seeded = await seed(container)
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(
            json.dumps(build_manifest(seeded), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(container=container),
                host=HOST,
                port=PORT,
                log_level="warning",
                access_log=False,
            )
        )
        await server.serve()
    return 0


def main() -> int:
    # Written before the socket opens and removed on the way in, so a Playwright run can
    # never read a manifest left behind by a boot that then failed.
    MANIFEST_PATH.unlink(missing_ok=True)
    return asyncio.run(_serve())


if __name__ == "__main__":
    raise SystemExit(main())
