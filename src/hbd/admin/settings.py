"""Everything the admin process needs, and nothing it must not hold.

**There is no vendor field and no bot-token field on this model — not optional ones, none.**
That absence is the security property, and it is stronger than any check could be: a
``HBD_ELEVENLABS_API_KEY`` sitting in this host's environment is not merely unread, there is
no attribute it could ever be read through. A missing key cannot be an error here and a
present key cannot be a value (ADMIN_PANEL_PLAN §4.2, D10). ``.env.admin`` is a separate
file for the same reason: pointing the panel at the shared ``.env`` would hand it every one
of the four credentials in ``hbd.config.VENDOR_SECRET_FIELDS`` by accident, which is exactly
the mistake the separate process exists to make impossible.

Everything else here is a bound, and every bound fails at build time rather than at the
first request that depends on it:

* ``environment`` is a closed ``Literal``. It is not decoration — ``prod`` is what makes the
  vendor-secret check in the lifespan a refusal rather than a warning, so a typo like
  ``production`` would silently downgrade the strongest boot control in the package.
* ``admin_cookie_secure`` may not be turned off **anywhere**, dev included. The cookies are
  ``__Host-`` prefixed, and that prefix is *defined* to make a browser reject a ``Set-Cookie``
  that lacks ``Secure`` — a dev panel serving one stored neither cookie and could never sign
  anyone in, while outside dev it would be a session token on the wire. ``http://127.0.0.1``
  is a secure context in Chrome and Firefox, so ``Secure`` costs dev nothing.
* ``admin_public_origin`` is required outside ``dev``. It fails closed — a wrong origin 403s
  every mutation — but a deploy that forgets it boots, passes ``/healthz``, serves a login
  page and then rejects every state change with ``ORIGIN_REJECTED``, which is a far harder
  incident to read than a boot refusal naming the variable.
* ``DEBUG`` is refused in ``prod``. It is the level at which the ORM echoes bound parameters
  — recipient names, notes, lyrics — into logs that have no retention clock and that
  ``hbd.db.purge`` cannot reach (§8.7).
* The trusted-proxy CIDRs are parsed here, so a typo in
  ``HBD_ADMIN_TRUSTED_PROXY_CIDRS`` fails the boot rather than silently trusting nothing —
  or, if the entry was meant to widen the list, silently trusting the wrong thing.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from hbd.admin.security.clientip import IpNetwork, parse_trusted_proxies
from hbd.config import ENV_PREFIX, LogLevel
from hbd.errors import ConfigError

__all__ = [
    "AdminSettings",
    "AdminEnvironment",
    "ADMIN_ENV_FILE",
    "DEV_ENVIRONMENT",
    "DEV_PUBLIC_ORIGIN",
    "build_admin_settings",
]

#: Never ``.env``: a shared file is how a vendor key reaches a process that must not hold one.
ADMIN_ENV_FILE: Final[str] = ".env.admin"

#: The one environment in which ``DEBUG`` may be on and the public origin may be left at its
#: loopback default. ``Secure`` is not on that list any more — see the module docstring.
DEV_ENVIRONMENT: Final[str] = "dev"

#: What ``admin_public_origin`` falls back to in dev, and only in dev.
DEV_PUBLIC_ORIGIN: Final[str] = "http://127.0.0.1:8080"

#: Closed rather than ``str`` — see the module docstring.
type AdminEnvironment = Literal["dev", "staging", "prod"]

_ORIGIN_SCHEMES: Final[tuple[str, ...]] = ("http://", "https://")

_DEBUG_LEVEL: Final[str] = "DEBUG"


def _split_csv(value: Any) -> Any:
    """Accept ``a,b,c`` from the environment for a tuple-typed setting.

    Mirrors the helper in :mod:`hbd.config` rather than importing it: that one is private,
    and a cross-module reach into a private name is a worse coupling than eight lines. A
    human types a comma-separated list into ``.env.admin``; pydantic-settings would
    otherwise demand JSON for a complex type.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip().strip("[]")
    return [item.strip().strip("\"'") for item in stripped.split(",") if item.strip()]


class AdminSettings(BaseSettings):
    """The admin process's whole configuration surface. Immutable once loaded.

    Build one with :func:`build_admin_settings`, which converts a validation failure into a
    ``ConfigError`` naming the offending ``HBD_*`` variable — the same contract
    ``hbd.config.build_settings`` offers the bot and the worker.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=ADMIN_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # -- runtime, shared meanings with hbd.config.Settings ------------------
    environment: AdminEnvironment = Field(default="dev")
    log_level: LogLevel = Field(default="INFO")
    is_debug: bool = Field(default=False)

    # -- infrastructure: the same database and Redis the bot and worker use -
    database_url: str = Field(min_length=1, description="postgresql+asyncpg://…")
    redis_url: str = Field(default="redis://localhost:6379/0")

    # -- the panel itself ---------------------------------------------------
    #: Off by default: an admin surface that appears because a dependency was installed is
    #: not a decision anybody made. The lifespan refuses to start while this is false.
    admin_enabled: bool = Field(default=False)
    #: The config editor's own switch, separate from ``admin_enabled`` so the riskiest
    #: surface in the panel can be taken away without taking the panel away. It is read
    #: only from this file, never from the override table, or it would not be a kill
    #: switch — a stolen session could turn it back on (§8.6).
    admin_config_enabled: bool = Field(default=True)
    #: Loopback, with TLS in front. Binding 0.0.0.0 publishes a password login to the
    #: internet and nothing in this package is designed for that.
    admin_host: str = Field(default="127.0.0.1", min_length=1)
    admin_port: int = Field(default=8080, ge=1, le=65535)
    #: The origin the browser actually reaches, scheme included. Compared exactly against
    #: the ``Origin`` header on every state-changing request (§12.1 T8), so a wrong value
    #: fails visibly rather than leaving the CSRF check half-applied. The default is a dev
    #: convenience only: outside dev, leaving it unset is refused at boot.
    admin_public_origin: str = Field(default=DEV_PUBLIC_ORIGIN, min_length=1)
    #: ``None`` means "derive", and it derives to ``True`` everywhere. An explicit ``false``
    #: is refused in every environment: the cookies are ``__Host-`` prefixed.
    admin_cookie_secure: bool | None = Field(default=None)

    # -- sessions: two clocks, both enforced server-side --------------------
    admin_session_ttl_s: int = Field(default=43_200, ge=3_600, le=86_400)
    admin_session_idle_ttl_s: int = Field(default=3_600, ge=300, le=28_800)
    #: How long one step-up authorises further actions in the same scope. Configuration
    #: rather than a constant because the right answer is a policy choice: 0 makes every
    #: action in the scope re-prompt. The two action classes that must never carry a grace
    #: at all — purge and config commit/rollback — do not read this: §12.1 T2 makes them
    #: unconditionally fresh, so lowering this is a tightening and raising it cannot loosen
    #: them.
    admin_step_up_grace_seconds: int = Field(default=300, ge=0, le=900)

    # -- argon2id: the cost of one login, paid on this host -----------------
    admin_argon2_time_cost: int = Field(default=3, ge=2, le=10)
    admin_argon2_memory_kib: int = Field(default=65_536, ge=32_768, le=1_048_576)
    admin_argon2_parallelism: int = Field(default=4, ge=1, le=16)

    # -- client IP derivation (§12.1 T13) -----------------------------------
    admin_trusted_proxy_hops: int = Field(default=0, ge=0, le=4)
    admin_trusted_proxy_cidrs: Annotated[tuple[str, ...], NoDecode] = Field(default=())

    # -- audit chain --------------------------------------------------------
    #: The only secret on this model, and it is not a vendor credential: it protects the
    #: record of what operators did. Required from the first boot rather than from the first
    #: audited action, because a chain that starts unkeyed is a chain with an unsigned prefix
    #: nobody can ever verify.
    #: ``SecretStr``, not ``str``: pydantic then renders it as ``**********`` in
    #: ``repr(settings)``, ``model_dump()`` and ``model_dump_json()``. ``hbd.logging.redact``
    #: masks it only when the field NAME is supplied beside the value, and a settings repr
    #: is exactly a bare value — so before this the only thing keeping §12.4's "never
    #: logged" true was that nobody had written the offending line yet.
    admin_audit_hmac_key: SecretStr = Field(min_length=32)
    #: The owner role's DSN (§4.5). Empty is a supported deployment and means the two-role
    #: setup is not in place: migration 0006 skips its ``REVOKE`` and logs a WARNING, and
    #: ``/audit/verify`` reports ``chainProtection: "hmac-only"``. A control that is not
    #: deployed is reported as not deployed, never implied — which is why this is a value
    #: the panel reads rather than an assumption it makes.
    admin_audit_dsn: str = Field(default="")

    # -- reveal budgets: a ceiling on how much personal data one operator can --
    # -- pull in one shift, independent of the per-action step-up (§12.1) ------
    #: Counted in **records, not requests** (§12.3), which is the correction the plan's
    #: review forced: one reveal returning fifty chat bodies charges fifty. A
    #: request-counted ceiling of 200 would be 200 whole transcripts an hour, all inside
    #: policy — bulk export through the reveal endpoint. Read by
    #: :func:`hbd.admin.deps.reveal_budget_limits`; the window is a fixed clock hour, not a
    #: sliding one, so the number is spendable twice across the boundary by design (the
    #: control is a detection signal as much as a limit).
    admin_reveal_records_per_hour: int = Field(default=200, ge=10, le=2_000)
    #: The second, independent ceiling: transcript pages per **UTC day**. Charged only by a
    #: conversation reveal, on its own key namespace, so exhausting the day's transcripts
    #: never costs an operator the ability to unmask a single name — and spending the hour
    #: on names never costs them a transcript.
    admin_reveal_conversations_per_day: int = Field(default=20, ge=1, le=200)

    # -- the name-verification threshold, MIRRORED and not owned -------------
    #: ``name_match_min_similarity`` as the WORKER is running it, republished here so
    #: ``/generations/names`` can mark it on the similarity histogram and count how many
    #: attempts sit within 0.05 of it.
    #:
    #: It is deliberately ``None`` by default and deliberately not derived from
    #: ``hbd.config.Settings``. This process does not read ``.env`` (see the module
    #: docstring — that separation is what keeps a vendor key out of reach), so it cannot
    #: know what the worker was actually started with; and importing the bot model's field
    #: DEFAULT would publish ``0.85`` on a deployment that runs ``0.9``, drawing a
    #: threshold line nobody configured on the one chart whose entire purpose is arguing
    #: about where that line belongs. Unset therefore means "this deployment has not
    #: published its threshold": the endpoint answers ``threshold: null`` with
    #: ``nearThreshold: null``, and the histogram renders honestly with no marker.
    #:
    #: The cost of the mirror is drift — an operator who moves the worker's threshold and
    #: not this one gets a marker in the wrong place. That is why it is published on
    #: ``GET /api/config`` beside every other value the panel is running under, where the
    #: two can be compared, rather than hidden inside the metrics response alone.
    admin_name_match_min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)

    # -- the read-only data volume ------------------------------------------
    #: The same directory ``hbd.runtime.container.build_container`` is given as its
    #: ``data_root``, mounted here **read-only** (§12.1 T4). The panel reaches exactly one
    #: subdirectory of it — ``<root>/archive``, where the pipeline puts a finished kit's
    #: bytes — and reaches it only through the ``Storage`` protocol, never as a path.
    #:
    #: A setting rather than a constant because the two processes are deployed separately
    #: and a panel pointed at the wrong volume must be a configuration mistake somebody can
    #: fix, not a rebuild. Nothing is created here: the admin process has no write
    #: permission on this tree, and a directory it conjured would be one the worker never
    #: writes into — a silent "no such object" for every asset in the fleet.
    admin_data_root: Path = Field(default=Path("var"))

    # -- probes -------------------------------------------------------------
    #: Lets a fleet monitor read ``/readyz``'s detailed body without an operator session.
    #: Empty disables that path entirely; there is no default token to forget to change.
    admin_probe_token: str = Field(default="")

    # -- validators ---------------------------------------------------------
    _normalize_cidrs = field_validator("admin_trusted_proxy_cidrs", mode="before")(_split_csv)

    @field_validator("admin_name_match_min_similarity", mode="before")
    @classmethod
    def _blank_threshold_means_unpublished(cls, value: Any) -> Any:
        """``HBD_ADMIN_NAME_MATCH_MIN_SIMILARITY=`` is "not published", not a broken float.

        Every other optional value in this file is a ``str`` whose empty form is falsy, so
        an empty variable is simply off. This one is a number, and pydantic would refuse an
        empty string — turning a documented "leave it blank" into a boot failure. The
        example file ships the variable blank, so this is the path an untouched deployment
        actually takes.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("admin_trusted_proxy_cidrs")
    @classmethod
    def _cidrs_must_parse(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Parse now so a typo fails the boot, not the first rate-limit decision.

        ``parse_trusted_proxies`` raises ``ConfigError``; it is re-raised as ``ValueError``
        so pydantic folds it into the report that names the environment variable, instead of
        escaping past :func:`build_admin_settings`'s contract.
        """
        try:
            parse_trusted_proxies(value)
        except ConfigError as exc:
            raise ValueError(exc.operator_message) from exc
        return value

    @field_validator("admin_public_origin")
    @classmethod
    def _origin_must_be_a_bare_origin(cls, value: str) -> str:
        """``scheme://host[:port]`` and nothing else — no path, no trailing slash.

        The ``Origin`` header a browser sends carries exactly this shape, and the check that
        reads it is an exact string comparison. A configured value with a trailing slash
        would never match, turning the control off in a way that looks like it is on.
        """
        if not value.startswith(_ORIGIN_SCHEMES):
            raise ValueError(f"must start with http:// or https://, got {value!r}")
        remainder = value.split("://", 1)[1]
        if not remainder or "/" in remainder:
            raise ValueError(f"must be a bare scheme://host[:port] with no path, got {value!r}")
        return value

    @model_validator(mode="after")
    def _bounds_that_span_fields(self) -> Self:
        """Refuse the four states that are field-by-field valid and jointly wrong."""
        if self.admin_session_idle_ttl_s > self.admin_session_ttl_s:
            raise ValueError(
                f"admin_session_idle_ttl_s ({self.admin_session_idle_ttl_s}) must not exceed "
                f"admin_session_ttl_s ({self.admin_session_ttl_s}); an idle window longer than "
                "the absolute cap is not an idle window"
            )
        if self.admin_cookie_secure is False:
            raise ValueError(
                "admin_cookie_secure must not be false in any environment, including "
                f"{DEV_ENVIRONMENT!r}: the session and CSRF cookies are __Host- prefixed, and "
                "that prefix makes a browser reject a Set-Cookie without Secure outright — "
                "the panel would be unusable rather than merely insecure. http://127.0.0.1 "
                "is a secure context in Chrome and Firefox, so Secure works in dev too"
            )
        if (
            self.environment != DEV_ENVIRONMENT
            and "admin_public_origin" not in self.model_fields_set
        ):
            raise ValueError(
                f"{ENV_PREFIX}ADMIN_PUBLIC_ORIGIN must be set when environment is "
                f"{self.environment!r}: it is compared exactly against the Origin header on "
                "every state-changing request, so the loopback default would boot, pass "
                "/healthz, serve a login page and then reject every mutation with "
                "ORIGIN_REJECTED"
            )
        if self.is_production and (self.is_debug or self.log_level == _DEBUG_LEVEL):
            raise ValueError(
                "DEBUG logging is refused in prod: the ORM echoes bound parameters — names, "
                "notes, lyrics — into logs that no retention sweep can reach"
            )
        return self

    # -- derived ------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def is_cookie_secure(self) -> bool:
        """Always ``True``. ``Secure`` goes on the session and CSRF cookies everywhere.

        Not derived from the environment, because the cookie *names* are not derived from
        the environment either: ``__Host-hbd_session`` and ``__Host-hbd_csrf`` carry a prefix
        whose whole definition is "a browser must reject this cookie unless it is Secure,
        Path=/ and has no Domain". Sending the prefix without the flag stored no cookie at
        all in dev, so the panel could not be signed into with a real browser — the suite
        missed it because ``httpx`` does not enforce cookie prefixes.

        Dropping the prefix in dev instead would trade a real security property for a dev
        convenience. It is not needed: ``http://127.0.0.1`` and ``http://localhost`` are
        secure contexts in Chrome and Firefox, which accept and return ``Secure`` cookies
        over plain HTTP there. The kept field is a refusal, not a switch — the validator
        rejects an explicit ``false`` rather than letting it serve a cookie no browser keeps.
        """
        return True

    @property
    def trusted_proxies(self) -> tuple[IpNetwork, ...]:
        """The parsed CIDR list. Validated at build time, so this cannot raise here."""
        return parse_trusted_proxies(self.admin_trusted_proxy_cidrs)


_FAILURE_PREAMBLE: Final[str] = (
    "The admin panel's configuration is invalid or incomplete. Fix these environment "
    "variables (see .env.admin.example):"
)


def _describe_failure(exc: PydanticValidationError) -> str:
    """One line per issue, each naming the ``HBD_*`` variable an operator can actually edit.

    A cross-field refusal has no single field to blame — pydantic reports it with an empty
    ``loc`` — so it is printed as the message alone rather than as ``HBD_<ROOT>``, which
    names nothing. Every such message names its own variables in its text.
    """
    lines: list[str] = []
    for issue in exc.errors():
        field = ".".join(str(part) for part in issue["loc"])
        prefix = f"{ENV_PREFIX}{field.upper()}: " if field else ""
        lines.append(f"  {prefix}{issue['msg']}")
    return "\n".join(lines)


def build_admin_settings(overrides: Mapping[str, object] | None = None) -> AdminSettings:
    """Build from ``.env.admin`` and the environment, with ``overrides`` layered on top.

    Raises ``ConfigError`` and nothing else — a caller never sees a pydantic exception, and
    the operator message names every offending ``HBD_*`` variable.
    """
    values: dict[str, Any] = dict(overrides or {})
    try:
        return AdminSettings(**values)
    except PydanticValidationError as exc:
        raise ConfigError(
            f"{_FAILURE_PREAMBLE}\n{_describe_failure(exc)}",
            context={"issue_count": len(exc.errors())},
            cause=exc,
        ) from exc
    except SettingsError as exc:
        raise ConfigError(
            f"{_FAILURE_PREAMBLE}\n  {exc}",
            context={"issue_count": 1},
            cause=exc,
        ) from exc
