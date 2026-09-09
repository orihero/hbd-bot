"""Everything the Payme gateway needs, and the one credential no other process may hold.

This is the third settings model in the tree, and the reason there are three rather than one
is the same reason there are four processes: **a settings model is a list of what a host is
allowed to reach.** ``hbd.config.Settings`` holds the five outbound vendor credentials;
``hbd.admin.settings.AdminSettings`` deliberately holds none of them; and this model holds
exactly one secret — the Payme cashbox key — and none of theirs. That key is an INBOUND
VERIFICATION secret: stealing it mints credits against our own database. It cannot be used to
impersonate the bot to a customer, and it cannot spend a single dollar of vendor balance. That
is a third blast radius, distinct from both of the other two, and it is what earns this process
its own container, its own unit file and its own dotenv.

**``HBD_PAYME_ENV_FILE`` is a SECOND variable and not a tier name shared with
``HBD_ENV_FILE``.** The rule is stated once, at :data:`hbd.admin.settings.ADMIN_ENV_FILE_VAR`,
and it applies here with more force rather than less: the whole point of a separate file is
that the gateway reads something the bot does not, and one knob deriving both paths would be
one edit away from pointing them at the same file — at which moment the process with an
inbound internet socket is holding the Telegram token. The boot-time credential scan in
:mod:`hbd.payme.app` follows the same selection, so the file that was LOADED is the file that
gets scanned.

**There are no aliases on any field.** The environment variable name is mechanically
``HBD_`` + the field name upper-cased, with no exceptions, because
``tests/test_payme/test_settings.py`` derives the documented variable set from
``PaymeSettings.model_fields`` and compares it against ``.env.payme.example`` in BOTH
directions. An alias would make one of those two lists a lie, and the lie would be discovered
by an operator setting a variable that does nothing.

Three fields carry an argument worth reading before changing them:

* :attr:`PaymeSettings.payme_merchant_key` is ``SecretStr`` rather than ``str``, following
  ``admin_audit_hmac_key`` — the only precedent in the tree. pydantic then renders it as
  ``**********`` in ``repr()``, ``model_dump()`` and ``model_dump_json()``, which matters here
  because this process logs its settings at boot and a JSON dump of a model is exactly the
  shape ``hbd.logging.redact`` cannot mask: that function needs the field NAME beside the
  value, and a dump gives it neither. The cost is that the repo now carries two patterns —
  four plain-``str`` vendor credentials on ``Settings`` and one ``SecretStr`` here — and
  converting the other four is a separate change, recorded as an open question rather than
  half-done.
* **No length assertion on the key.** The documentation says 36 characters; the length of the
  sandbox ``TEST_KEY`` is unverified, and a wrong length assertion is a boot failure on
  go-live day, at the exact moment nobody can afford one. The key is only ever compared
  against itself (:func:`hbd.payme.auth.verify_basic`), so its length is not a correctness
  property of anything here. :mod:`hbd.payme.app` logs the length — never the value — at INFO
  on boot instead, so a truncated paste is visible in one line of the journal.
* :attr:`PaymeSettings.payme_return_url` refuses any value containing ``;``. That character is
  the parameter separator inside Payme's own base64 payload and a value carrying one is
  SILENTLY TRUNCATED by their parser — verified against the live sandbox echo. A truncated
  deep link fails in the only way that is worse than failing loudly: the customer's browser
  goes somewhere that is almost right, and nothing in this system observes it. So the refusal
  is at settings-build time, which is why :func:`hbd.payme.link.build_checkout_link` is total
  and returns no ``Result``.
"""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import ip_network
from typing import Annotated, Any, Final, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from hbd.config import ENV_PREFIX, LogLevel, resolve_env_file
from hbd.errors import ConfigError
from hbd.payme.protocol import (
    DEFAULT_ACCOUNT_FIELD,
    DEFAULT_AUTH_LOGIN,
    PaymeErrorCode,
)
from hbd.payme.rules import DEFAULT_TRANSACTION_TIMEOUT_MS

__all__ = [
    "PaymeSettings",
    "PaymeEnvironment",
    "PAYME_ENV_FILE",
    "PAYME_ENV_FILE_VAR",
    "PAYME_SECRET_FIELDS",
    "PAYME_LINK_SEPARATOR",
    "DEV_ENVIRONMENT",
    "payme_env_file",
    "build_payme_settings",
]

#: Never ``.env`` and never ``.env.admin``: three processes, three files, three blast radii.
PAYME_ENV_FILE: Final[str] = ".env.payme"

#: Selects a different one — ``HBD_PAYME_ENV_FILE=/etc/hbd/payme.env``, which is what
#: ``deploy/systemd/hbd-payme.service`` sets. Deliberately its OWN variable rather than a tier
#: name shared with ``HBD_ENV_FILE``; see the module docstring and
#: :data:`hbd.admin.settings.ADMIN_ENV_FILE_VAR`, which states the rule first. Read from the
#: process environment only, for the reason on :data:`hbd.config.ENV_FILE_VAR`.
PAYME_ENV_FILE_VAR: Final[str] = f"{ENV_PREFIX}PAYME_ENV_FILE"

#: The fields on this model that hold a secret, by NAME. One entry, and it is the whole reason
#: this process exists separately. Exposed as a tuple rather than left implicit so that a
#: future reader adding a second credential has somewhere to add it, and so a test can assert
#: every name on it is a ``SecretStr`` — the property that keeps it out of ``model_dump()``.
PAYME_SECRET_FIELDS: Final[tuple[str, ...]] = ("payme_merchant_key",)

#: The character that terminates a value inside Payme's base64 payload. Refused in the return
#: URL here rather than escaped there, because their parser does not decode percent-encoding
#: either — there is nothing to escape it WITH.
PAYME_LINK_SEPARATOR: Final[str] = ";"

#: The one environment in which DEBUG may be on. Mirrors ``AdminSettings``' spelling so the
#: three models cannot disagree about what "dev" is called.
DEV_ENVIRONMENT: Final[str] = "dev"

#: Closed rather than ``str``, for the reason ``AdminSettings`` gives: ``prod`` is what turns
#: the foreign-credential check in the lifespan from a warning into a refusal, so a typo like
#: ``production`` would silently downgrade the strongest boot control this process has.
type PaymeEnvironment = Literal["dev", "staging", "prod"]

_DEBUG_LEVEL: Final[str] = "DEBUG"


def payme_env_file() -> str:
    """Which dotenv file the gateway reads. See :data:`PAYME_ENV_FILE_VAR`.

    Reads the module global at call time rather than closing over it, so a test that
    monkeypatches :data:`PAYME_ENV_FILE` redirects every reader of it — including the boot
    scan, which must read the same file this function names or it clears a host whose
    credentials are sitting in the file that was actually loaded.
    """
    return resolve_env_file(PAYME_ENV_FILE_VAR, PAYME_ENV_FILE)


def _split_csv(value: Any) -> Any:
    """Accept ``a,b,c`` from the environment for a tuple-typed setting.

    Mirrors the helper in :mod:`hbd.config` and the one in :mod:`hbd.admin.settings` rather
    than importing either: the first is private, and the second lives in a package this one
    may never import. A cross-package reach for eight lines would be a worse coupling than the
    duplication, and here it would be an architectural violation as well.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip().strip("[]")
    return [item.strip().strip("\"'") for item in stripped.split(",") if item.strip()]


class PaymeSettings(BaseSettings):
    """The gateway's whole configuration surface. Immutable once loaded.

    Build one with :func:`build_payme_settings`, which converts a validation failure into a
    ``ConfigError`` naming the offending ``HBD_*`` variable — the same contract
    ``hbd.config.build_settings`` offers the bot and ``build_admin_settings`` offers the panel.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=PAYME_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # -- runtime, shared meanings with the other two models -----------------
    environment: PaymeEnvironment = Field(default="dev")
    log_level: LogLevel = Field(default="INFO")
    is_debug: bool = Field(default=False)

    # -- infrastructure: the same database and Redis the other three use ----
    #: The gateway connects as the APPLICATION role (``hbd_app`` in docker-compose's two-role
    #: split), never the owner role. Migration 0023's tables inherit that role's default
    #: grants; whether they actually did is a deployment check, written down in the runbook
    #: rather than assumed here.
    database_url: str = Field(min_length=1, description="postgresql+asyncpg://…")
    #: Used for exactly one thing: enqueuing the "your payment went through" job onto the
    #: worker's queue. The gateway holds no Telegram token, so it cannot send that message
    #: itself — which is the whole reason the notification is a job. A Redis outage therefore
    #: costs a customer a delayed message and never a refused payment; see
    #: :class:`hbd.payme.service.PaymeService`.
    redis_url: str = Field(default="redis://localhost:6379/0")

    # -- the gateway process ------------------------------------------------
    #: Off by default, exactly as ``admin_enabled`` is, and the lifespan refuses to start
    #: while it is false. An endpoint that accepts money because a dependency was installed
    #: is not a decision anybody made. It is also the kill switch: taking the rail down is one
    #: variable and a restart, not a release.
    payme_enabled: bool = Field(default=False)
    #: Loopback, with the TLS terminator in front. Binding ``0.0.0.0`` publishes a credit mint
    #: to the internet with one shared secret in front of it. Read by the operator and by the
    #: unit file's ``ExecStart``, never by :func:`hbd.payme.app.create_app` — uvicorn is told
    #: on the command line, and this field is what an operator compares that line against.
    payme_host: str = Field(default="127.0.0.1", min_length=1)
    payme_port: int = Field(default=8091, ge=1, le=65535)
    #: Lets a fleet monitor read ``/readyz``'s detailed body with no session and no cabinet
    #: key. Empty disables that path entirely; there is no default token to forget to change.
    payme_probe_token: str = Field(default="")

    # -- the rail -----------------------------------------------------------
    #: The cashbox this deployment sells through, as it appears in the cabinet. PUBLIC — it is
    #: rendered in a customer's browser address bar inside every checkout link — which is why
    #: it also lives in the bot's ``.env`` and why it is not on :data:`PAYME_SECRET_FIELDS`.
    #: Compared against the intent's OWN stored merchant id at settlement, so a deployment
    #: repointed at another cashbox while an old link is still live in somebody's chat is a
    #: ``-31055`` refusal rather than a customer charged by an account nobody reconciles.
    payme_merchant_id: str = Field(default="")
    #: **The one secret on this host.** Compared, whole, against the ``login:key`` pair
    #: presented in the ``Authorization`` header under ``hmac.compare_digest``. It is never
    #: sent anywhere, never logged, and never written to a database — it is only ever compared
    #: against itself, which is what makes a 36-character placeholder a fully functional
    #: gateway and lets this entire integration be built and certified before Payme has handed
    #: over anything. Required when :attr:`payme_enabled`; see :meth:`_a_live_rail_has_a_key`.
    payme_merchant_key: SecretStr = Field(default=SecretStr(""))
    #: The login half of that pair. Both official merchant templates hard-code the literal
    #: ``Paycom``; the current documentation hedges on whether it is guaranteed, so it is a
    #: setting and the ``-32504`` log line records the login that was actually PRESENTED. The
    #: first sandbox call therefore answers the question, rather than a support ticket.
    payme_basic_login: str = Field(default=DEFAULT_AUTH_LOGIN, min_length=1)
    #: The account subfield name a human typed into the cabinet's «Настройка Аккаунт» form.
    #: It must equal what is configured there or every ``CheckPerformTransaction`` is a
    #: ``-31050`` that looks like our bug — which is why the ``-31050`` log line names both
    #: this value and the field names actually received.
    payme_account_field: str = Field(default=DEFAULT_ACCOUNT_FIELD, min_length=1)
    #: The code for "this order already has another active transaction", and the one place
    #: Payme's own materials contradict each other: the sandbox scenario text demands
    #: ``-31008``, PaycomUZ's PHP template returns ``-31050``, and three third-party packages
    #: pick ``-31054`` or ``-31099``. Shipping it as a value means a certification finding is
    #: an environment variable and a restart rather than a release. Bounded to the negative
    #: range so a typo cannot emit a positive "code" Payme would read as a success.
    payme_duplicate_transaction_code: int = Field(
        default=int(PaymeErrorCode.STATE_REFUSAL), lt=0
    )
    #: The rail's own window, measured from ``params.time`` — Payme's creation instant, not
    #: ours. Twelve hours by default. A SETTING rather than a constant so the expiry branch
    #: can be driven in seconds during certification: an untested branch on the money path is
    #: how "cancel first, refuse second" silently becomes "refuse only".
    payme_transaction_timeout_ms: int = Field(
        default=DEFAULT_TRANSACTION_TIMEOUT_MS, ge=1_000, le=604_800_000
    )
    #: Which cashbox environment this endpoint believes it is terminating. **A label, not a
    #: branch.** Nothing in this process selects a URL from it — the gateway builds no links —
    #: and the flag that governs settlement is the one stored on the INTENT, written when the
    #: link was built. It is here so the boot line and the authenticated ``/readyz`` body can
    #: say which environment an operator configured, and it is documented as a label so that
    #: nobody later adds a branch that can disagree with the intent's own stored value.
    payme_is_sandbox: bool = Field(default=False)
    #: An explicit checkout host, overriding the sandbox/production constants. Blank means
    #: "derive" (:func:`hbd.payme.link.resolve_base_url`). Read here by the operator CLI and
    #: the certification harness, which build links from this model; the BOT builds the links
    #: customers actually tap, from its own copy of the same value.
    payme_checkout_base_url: str = Field(default="")
    #: Where Payme sends the browser after a payment. Blank means "send no ``c`` parameter",
    #: which is the shipped default and costs nothing: settlement is driven by the inbound
    #: ``PerformTransaction``, never by the customer coming back. A ``;`` in it is refused —
    #: see the module docstring and :meth:`_a_return_url_survives_paymes_parser`.
    payme_return_url: str = Field(default="")

    # -- caller identification (see the OUT OF SCOPE note below) ------------
    #: How many proxy hops sit between this process and the internet. **Zero by default, and
    #: that zero is what makes the allowlist below inert.** With no hops the socket's peer IS
    #: the terminator, so every request would appear to come from one address and a filter
    #: matching it would either pass everything or refuse everything —
    #: ``hbd.admin.security.clientip`` learned this already, at the cost of a rate limiter
    #: that counted the whole internet as one client.
    payme_trusted_proxy_hops: int = Field(default=0, ge=0, le=4)
    #: The caller allowlist, enforced **only** when :attr:`payme_trusted_proxy_hops` is above
    #: zero. Empty by default and expected to STAY empty: Payme originates from
    #: ``185.234.113.0/28`` and that range belongs in the TLS terminator's configuration, not
    #: here, because a filter matching the wrong address is worse than no filter at all. The
    #: field exists so a deployment that genuinely knows its hop count can add depth, and the
    #: peer IP is journalled on every request either way, so the real caller set is
    #: discoverable from our own logs rather than assumed.
    payme_allowed_cidrs: Annotated[tuple[str, ...], NoDecode] = Field(default=())

    # -- validators ---------------------------------------------------------
    _normalize_cidrs = field_validator("payme_allowed_cidrs", mode="before")(_split_csv)

    @field_validator("payme_allowed_cidrs")
    @classmethod
    def _cidrs_must_parse(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Parse now so a typo fails the boot rather than the first request it silently drops.

        ``strict=False`` so ``185.234.113.1/28`` — a host address written with a network mask,
        which is what an operator copies out of a support email — is accepted as the network
        it obviously means instead of raising about host bits.
        """
        for entry in value:
            try:
                ip_network(entry, strict=False)
            except ValueError as exc:
                raise ValueError(f"{entry!r} is not a CIDR block: {exc}") from exc
        return value

    @field_validator("payme_return_url")
    @classmethod
    def _a_return_url_survives_paymes_parser(cls, value: str) -> str:
        """Refuse a ``;``. Payme's parser truncates the value at it and says nothing.

        The separator inside the base64 payload is ``;`` and percent-encoding is NOT decoded
        on the way back out, so there is no escape available — the only correct handling is to
        refuse the value where an operator can still read the message. Verified against the
        live sandbox echo, which returns the truncated string as the parsed receipt.
        """
        if PAYME_LINK_SEPARATOR in value:
            raise ValueError(
                f"must not contain {PAYME_LINK_SEPARATOR!r}: it separates parameters inside "
                "Payme's base64 payload and their parser truncates the value at it without "
                "reporting anything, so the customer's browser would be sent to a URL that is "
                "almost right and nothing here would observe it"
            )
        return value

    @model_validator(mode="after")
    def _a_live_rail_has_a_key(self) -> Self:
        """A rail that is switched on and cannot authenticate anybody is not switched on.

        The check is emptiness and **nothing else**. The documentation says the key is 36
        characters; the sandbox ``TEST_KEY``'s length is unverified, and asserting a length we
        have not seen would turn go-live day into a boot failure over a value that is correct.
        The key's only job is to equal itself, so its length is not a property this process
        depends on — :mod:`hbd.payme.app` logs the length at INFO instead, where a truncated
        paste is one line of the journal rather than a certification slot.
        """
        if self.payme_enabled and not self.payme_merchant_key.get_secret_value():
            raise ValueError(
                f"{ENV_PREFIX}PAYME_MERCHANT_KEY must be set when "
                f"{ENV_PREFIX}PAYME_ENABLED is true: the endpoint authenticates every inbound "
                "call by comparing the whole login:key pair against it, so an empty key would "
                "accept nobody and the rail would answer -32504 to every request Payme makes"
            )
        return self

    @model_validator(mode="after")
    def _debug_is_refused_in_prod(self) -> Self:
        """The same refusal ``AdminSettings`` makes, for the same privacy reason.

        DEBUG is the level at which the ORM echoes bound parameters into logs that no
        retention sweep can reach. On this process those parameters are an idempotency key
        carrying a Telegram user id and a rail-side transaction id — the two values that join a
        person to a payment.
        """
        if self.is_production and (self.is_debug or self.log_level == _DEBUG_LEVEL):
            raise ValueError(
                "DEBUG logging is refused in prod: the ORM echoes bound parameters — here, "
                "idempotency keys carrying a Telegram user id — into logs that no retention "
                "sweep can reach"
            )
        return self

    # -- derived ------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def merchant_key(self) -> str:
        """The key as a bare string, for the one comparison that needs it.

        A property rather than a plain field so that every OTHER reader — a log line, a repr,
        a ``model_dump`` — gets ``**********`` and has to reach for this name deliberately.
        ``grep -n "\\.merchant_key" src/`` is therefore the complete list of places the secret
        is in the clear, and it has exactly one entry.
        """
        return self.payme_merchant_key.get_secret_value()

    @property
    def allowed_networks(self) -> tuple[str, ...]:
        """The allowlist, or an empty tuple when the hop count makes it meaningless.

        Derived rather than checked at each call site so "enforced only above zero hops" is
        one expression rather than a condition three readers have to remember. An operator who
        sets the CIDRs and forgets the hop count gets no filter — which is the correct outcome,
        because with zero hops the address the filter would match is the terminator's.
        """
        return self.payme_allowed_cidrs if self.payme_trusted_proxy_hops > 0 else ()


_FAILURE_PREAMBLE: Final[str] = (
    "The Payme gateway's configuration is invalid or incomplete. Fix these environment "
    "variables (see .env.payme.example):"
)


def _describe_failure(exc: PydanticValidationError) -> str:
    """One line per issue, each naming the ``HBD_*`` variable an operator can actually edit.

    A cross-field refusal has no single field to blame — pydantic reports it with an empty
    ``loc`` — so it is printed as the message alone rather than as ``HBD_<ROOT>``, which names
    nothing. Every such message names its own variables in its text.
    """
    lines: list[str] = []
    for issue in exc.errors():
        field = ".".join(str(part) for part in issue["loc"])
        prefix = f"{ENV_PREFIX}{field.upper()}: " if field else ""
        lines.append(f"  {prefix}{issue['msg']}")
    return "\n".join(lines)


def build_payme_settings(overrides: Mapping[str, object] | None = None) -> PaymeSettings:
    """Build from :func:`payme_env_file` and the environment, ``overrides`` layered on top.

    Raises ``ConfigError`` and nothing else — a caller never sees a pydantic exception, and the
    operator message names every offending ``HBD_*`` variable. Never carries a VALUE into the
    message: pydantic's own report for a ``SecretStr`` field prints the masked form, and the
    two cross-field refusals above name variables rather than quoting them.
    """
    values: dict[str, Any] = dict(overrides or {})
    values.setdefault("_env_file", payme_env_file())
    try:
        return PaymeSettings(**values)
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
