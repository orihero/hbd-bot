"""The read-only view of the admin process's own effective settings.

**Secrets are absent, not masked, and the difference is the whole point of this module.**
``database_url`` and ``redis_url`` are credentials-bearing DSNs; a starred-out password is
still a published username, a published host, a published port and a published database
name, and it teaches an operator that the panel is willing to print a DSN at all. So no form
of either string reaches the wire — instead :func:`endpoint_of` parses out a host and a port
and those two named values are what the panel renders. ``admin_audit_hmac_key`` and
``admin_probe_token`` have no derived form worth anything and appear nowhere, in any shape.
``admin_audit_dsn`` is reported as the boolean ``isAuditDsnConfigured``, because whether the
owner-role DSN of §4.5 is deployed is an operational fact and the DSN itself is another
credential.

**The view is built by naming every exposed field, one at a time, and never by dumping the
model and removing keys.** A denylist ships the next secret somebody adds to
:class:`~hbd.admin.settings.AdminSettings`: the field lands in ``model_dump()`` the moment
it is declared, the removal list does not grow with it, and the leak is a diff nobody
reviewed. An allowlist omits a new field until a human puts it here, which is the failure
direction that does not leak.

**Every field name is an ``AdminSettings`` attribute name**, camelCased by
:class:`~hbd.admin.schemas.common.ApiModel`, so a number on the panel maps to the
``HBD_ADMIN_*`` variable an operator would edit without a translation table. The four
exceptions are derived and say so below: ``databaseHost`` / ``databasePort``,
``redisHost`` / ``redisPort``, ``isAuditDsnConfigured`` and ``isProbeTokenConfigured``.

**This is not the runtime-config editor of Phase 7.** It describes *this process's* own
configuration, which arrives from ``.env.admin`` and the environment and is frozen at boot.
There is no override layer behind it, nothing here is writable, and none of these fields
carries a tier — the ``HBD_ADMIN_*`` settings are not on the bot's frozen
``hbd.config.Settings`` at all, so there is no tiered field for an override to shadow. The
editor, when it lands, edits the bot's settings through ``CONFIG_WRITE``; this endpoint will
still be the answer to "what is the panel itself running with".
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from hbd.admin.schemas.common import ApiModel
from hbd.admin.settings import AdminEnvironment, AdminSettings
from hbd.config import LogLevel

__all__ = [
    "ConfigView",
    "Endpoint",
    "endpoint_of",
    "to_config_view",
]


@dataclass(frozen=True, slots=True)
class Endpoint:
    """The non-secret half of a DSN: where it points, never what it authenticates with."""

    host: str | None
    port: int | None


def _port_of(netloc: str) -> int | None:
    """The port digits of a netloc, or ``None``.

    Not ``urlsplit(...).port``, which raises ``ValueError`` on a non-numeric port — and this
    runs inside a request handler, where the one rule is that a failure is a raised
    ``ProblemError`` rather than an exception nobody planned for. A port that is not digits
    is simply not reported.

    ``rpartition`` twice: after ``@`` to drop any userinfo (a password may contain a colon),
    then at the last ``:`` so an IPv6 literal's own colons stay inside its brackets.
    """
    _, _, authority = netloc.rpartition("@")
    _, separator, port = authority.rpartition(":")
    if not separator or not port.isdigit():
        return None
    return int(port)


def endpoint_of(dsn: str) -> Endpoint:
    """Host and port from a DSN, with the userinfo discarded rather than redacted.

    ``urlsplit`` handles the ``postgresql+asyncpg`` scheme and ``.hostname`` lowercases and
    unwraps an IPv6 literal. A DSN this process could not parse is not a case to handle here:
    the engine was built from this exact string at boot (``build_admin_container``), so an
    unparseable one never reaches a request. A URL with no authority at all — the suite's
    ``sqlite+aiosqlite:///:memory:`` — yields ``None`` twice, which is the honest answer.
    """
    parts = urlsplit(dsn)
    return Endpoint(host=parts.hostname or None, port=_port_of(parts.netloc))


class ConfigView(ApiModel):
    """``GET /api/config`` — every non-secret setting this process is running under."""

    # -- runtime ------------------------------------------------------------
    environment: AdminEnvironment
    log_level: LogLevel
    is_debug: bool
    is_production: bool

    # -- the panel ----------------------------------------------------------
    admin_enabled: bool
    #: The config editor's own kill switch, read only from ``.env.admin`` (§8.6). Visible
    #: here so an operator can tell "the editor refused me" from "the editor is switched
    #: off" without reading a deploy's environment.
    admin_config_enabled: bool
    admin_host: str
    admin_port: int
    admin_public_origin: str
    #: Always ``true``; the cookies are ``__Host-`` prefixed. Reported rather than assumed,
    #: because "the panel claims Secure is on" is the sentence an incident review needs.
    is_cookie_secure: bool

    # -- sessions and step-up ----------------------------------------------
    admin_session_ttl_s: int
    admin_session_idle_ttl_s: int
    admin_step_up_grace_seconds: int

    # -- argon2id -----------------------------------------------------------
    admin_argon2_time_cost: int
    admin_argon2_memory_kib: int
    admin_argon2_parallelism: int

    # -- client IP derivation (§12.1 T13) ----------------------------------
    admin_trusted_proxy_hops: int
    #: Network topology, not a credential. Wrong values here silently change which address
    #: every rate limit is keyed on, so they are exactly what an operator needs to see.
    admin_trusted_proxy_cidrs: tuple[str, ...]

    # -- reveal budgets -----------------------------------------------------
    admin_reveal_records_per_hour: int
    admin_reveal_conversations_per_day: int

    #: The WORKER's ``name_match_min_similarity``, mirrored into this process so
    #: ``/generations/names`` can mark it. ``null`` means this deployment has not published
    #: it — §11.2 links the histogram straight here, and an operator following that link
    #: needs to see either the number the marker was drawn from or the fact that there
    #: isn't one. Not a secret and not derived: it is a setting like the rest.
    admin_name_match_min_similarity: float | None

    # -- derived: where the DSNs point, never what they authenticate with ---
    database_host: str | None
    database_port: int | None
    redis_host: str | None
    redis_port: int | None
    #: Whether §4.5's owner-role DSN is deployed. The DSN is a credential; whether the
    #: control exists is not, and ``/audit/verify`` already reports the same fact as
    #: ``chainProtection``.
    is_audit_dsn_configured: bool
    #: Whether ``/readyz`` will accept a token instead of an operator session. Empty means
    #: that path is off entirely; the token itself is a credential and is not derived from.
    is_probe_token_configured: bool


def to_config_view(settings: AdminSettings) -> ConfigView:
    """Name every exposed field. Adding one here is a decision; inheriting one is not."""
    database = endpoint_of(settings.database_url)
    redis = endpoint_of(settings.redis_url)
    return ConfigView(
        environment=settings.environment,
        log_level=settings.log_level,
        is_debug=settings.is_debug,
        is_production=settings.is_production,
        admin_enabled=settings.admin_enabled,
        admin_config_enabled=settings.admin_config_enabled,
        admin_host=settings.admin_host,
        admin_port=settings.admin_port,
        admin_public_origin=settings.admin_public_origin,
        is_cookie_secure=settings.is_cookie_secure,
        admin_session_ttl_s=settings.admin_session_ttl_s,
        admin_session_idle_ttl_s=settings.admin_session_idle_ttl_s,
        admin_step_up_grace_seconds=settings.admin_step_up_grace_seconds,
        admin_argon2_time_cost=settings.admin_argon2_time_cost,
        admin_argon2_memory_kib=settings.admin_argon2_memory_kib,
        admin_argon2_parallelism=settings.admin_argon2_parallelism,
        admin_trusted_proxy_hops=settings.admin_trusted_proxy_hops,
        admin_trusted_proxy_cidrs=settings.admin_trusted_proxy_cidrs,
        admin_reveal_records_per_hour=settings.admin_reveal_records_per_hour,
        admin_reveal_conversations_per_day=settings.admin_reveal_conversations_per_day,
        admin_name_match_min_similarity=settings.admin_name_match_min_similarity,
        database_host=database.host,
        database_port=database.port,
        redis_host=redis.host,
        redis_port=redis.port,
        is_audit_dsn_configured=bool(settings.admin_audit_dsn),
        is_probe_token_configured=bool(settings.admin_probe_token),
    )
