"""Everything the admin process needs, and nothing it must not hold.

**There is no vendor field and no bot-token field on this model — not optional ones, none.**
That absence is the security property, and it is stronger than any check could be: a
``HBD_ELEVENLABS_API_KEY`` sitting in this host's environment is not merely unread, there is
no attribute it could ever be read through. A missing key cannot be an error here and a
present key cannot be a value (ADMIN_PANEL_PLAN §4.2, D10). ``.env.admin`` is a separate
file for the same reason: pointing the panel at the shared ``.env`` would hand it every one
of the five credentials in ``hbd.config.VENDOR_SECRET_FIELDS`` by accident, which is exactly
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
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from hbd.admin.csrf import ANY_ORIGIN
from hbd.admin.security.clientip import IpNetwork, parse_trusted_proxies
from hbd.config import ENV_PREFIX, LogLevel, resolve_env_file
from hbd.errors import ConfigError

__all__ = [
    "AdminSettings",
    "AdminEnvironment",
    "ANY_ORIGIN",
    "ADMIN_ENV_FILE",
    "ADMIN_ENV_FILE_VAR",
    "admin_env_file",
    "DEV_ENVIRONMENT",
    "DEV_PUBLIC_ORIGIN",
    "LOOPBACK_HOSTS",
    "loopback_aliases",
    "build_admin_settings",
]

#: Never ``.env``: a shared file is how a vendor key reaches a process that must not hold one.
ADMIN_ENV_FILE: Final[str] = ".env.admin"

#: Selects a different one — ``HBD_ADMIN_ENV_FILE=.env.admin.prod``. Deliberately a SECOND
#: variable rather than a tier name shared with ``HBD_ENV_FILE``: the whole point of this
#: module is that the admin process reads a different file from the bot and the worker, and
#: one knob deriving both paths would be one edit away from pointing them at the same file.
#: Read from the process environment only, for the reason on :data:`hbd.config.ENV_FILE_VAR`.
ADMIN_ENV_FILE_VAR: Final[str] = f"{ENV_PREFIX}ADMIN_ENV_FILE"


def admin_env_file() -> str:
    """Which dotenv file the admin process reads. See :data:`ADMIN_ENV_FILE_VAR`.

    Reads the module global at call time rather than closing over it, so that a test which
    monkeypatches ``ADMIN_ENV_FILE`` still redirects every reader of it.
    """
    return resolve_env_file(ADMIN_ENV_FILE_VAR, ADMIN_ENV_FILE)


#: The one environment in which ``DEBUG`` may be on and the public origin may be left at its
#: loopback default. ``Secure`` is not on that list any more — see the module docstring.
DEV_ENVIRONMENT: Final[str] = "dev"

#: What ``admin_public_origin`` falls back to in dev, and only in dev.
DEV_PUBLIC_ORIGIN: Final[str] = "http://127.0.0.1:8080"

#: Closed rather than ``str`` — see the module docstring.
type AdminEnvironment = Literal["dev", "staging", "prod"]

_ORIGIN_SCHEMES: Final[tuple[str, ...]] = ("http://", "https://")

#: The three spellings of "this machine". A browser treats them as three DIFFERENT origins
#: — an exact-match check configured for one 403s the other two — but they are one server,
#: and which one reaches the URL bar is decided by what the operator typed, by a bookmark,
#: or by whichever one the dev server printed. In dev that distinction protects nothing:
#: anything that can open http://localhost:8080 can open http://127.0.0.1:8080 just as
#: easily, so refusing the alias costs an operator an afternoon and costs an attacker
#: nothing. Outside dev the exact match stands, because there the origin is a real name
#: with a real certificate and a neighbour on the same host is not automatically us.
LOOPBACK_HOSTS: Final[tuple[str, ...]] = ("localhost", "127.0.0.1", "[::1]")


def _split_authority(authority: str) -> tuple[str, str]:
    """``host[:port]`` → ``(host, ":port" or "")``, with IPv6 literals kept bracketed."""
    if authority.startswith("["):
        closing = authority.find("]")
        if closing == -1:  # unbracketed garbage; the field validator already refused it
            return authority, ""
        return authority[: closing + 1], authority[closing + 1 :]
    host, separator, port = authority.partition(":")
    return host, f"{separator}{port}" if separator else ""


def loopback_aliases(origin: str) -> frozenset[str]:
    """Every spelling of ``origin`` a dev browser may present, scheme and port preserved.

    Returns just ``{origin}`` unless its host is one of :data:`LOOPBACK_HOSTS` — a real
    hostname has no aliases to widen to, so a misconfigured staging origin cannot pick any
    up by accident. The port is never varied: ``:5173`` and ``:8080`` are two different
    servers, and only one of them is the panel.
    """
    scheme, separator, authority = origin.partition("://")
    if not separator or not authority:
        return frozenset({origin})
    host, port = _split_authority(authority)
    if host.lower() not in LOOPBACK_HOSTS:
        return frozenset({origin})
    return frozenset(f"{scheme}://{alias}{port}" for alias in LOOPBACK_HOSTS)


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

    # -- the settlement grace, MIRRORED and not owned -----------------------
    #: ``EntitlementPolicy.settlement_grace_s`` as the WORKER is running it, republished here
    #: so ``GET /users/{id}`` can compute ``inFlightRenderCount`` with the same cutoff the
    #: bot's gate used.
    #:
    #: The number matters because it is the one on the screen that explains a refusal. The
    #: gate counts unsettled debits newer than ``now - settlement_grace_s``
    #: (``credit_sql.count_in_flight``), and that grace is either an operator's
    #: ``HBD_SETTLEMENT_GRACE_S`` or DERIVED from the queue ladder
    #: (``entitlements.resolve_entitlement_policy``) — so a deployment that lowered it to
    #: 300s had this panel counting a 30-minute-old debit the customer's own gate had already
    #: forgotten, and one that raised ``HBD_QUEUE_JOB_TIMEOUT_S`` had the panel showing 0
    #: while the gate refused. Under shipped defaults the two agree, which is why nothing
    #: went red.
    #:
    #: Unset means "this deployment has not published its grace", and the panel then uses
    #: ``DEFAULT_ENTITLEMENT_POLICY`` — the shipped default, which is the only honest guess
    #: available to a process that does not read ``.env``. The mirror's cost is drift, which
    #: is why the value is published on ``GET /api/config`` beside the rest, exactly as
    #: ``admin_name_match_min_similarity`` above is: an operator comparing the two columns
    #: can see which clock produced the number.
    admin_settlement_grace_s: int | None = Field(default=None, ge=1, le=86_400)

    # -- the free allowance, MIRRORED and not owned -------------------------
    #: ``EntitlementPolicy.allowance_credits`` as the WORKER is running it, republished here
    #: so ``GET /users/{id}``'s ``creditsProjected`` is the number the customer was actually
    #: shown on their Confirm screen.
    #:
    #: **This mirror exists because a shipped defect proved the allowance moves.** The panel
    #: used to build its policy as ``EntitlementPolicy(settlement_grace_s=...)`` and let the
    #: allowance fall through to the dataclass default of 3, on the argument that the
    #: allowance was a constant on both sides. It stopped being one when the paywall shipped
    #: and ``Settings.free_allowance_credits`` went to 0: ``read_balance`` adds
    #: ``policy.allowance_credits`` whenever an allowance is due, and an allowance of 0 makes
    #: ``credits._mint_due_allowance`` return before it ever stamps
    #: ``allowance_period_index``, so "due" is permanently true for every account. The panel
    #: therefore added 3 songs to every customer in the fleet, forever — a customer holding
    #: one paid top-up read 1 on their own screen and 4 on the operator's, which is precisely
    #: the ticket ``creditsProjected`` was added to settle.
    #:
    #: An ``int`` and not ``int | None``, unlike the two mirrors above, because there is no
    #: honest way to render "unpublished" here: the projection is arithmetic and the
    #: allowance is one of its terms, so this process must commit to a number. The default is
    #: therefore what the bot itself now ships (``Settings.free_allowance_credits``, 0), so
    #: an operator who configures nothing gets agreement with the shipped deployment rather
    #: than a silent three-song overstatement. A deployment that re-opens a free allowance
    #: must set this to the same number, exactly as it must for the grace above; the cost of
    #: any mirror is drift, and drift here shows up as a balance the customer disputes.
    #:
    #: Not yet on ``GET /api/config``: :mod:`hbd.admin.schemas.config_view` publishes the two
    #: mirrors it was written for, and this one has to join them so an operator holding a
    #: disputed balance can see which allowance produced it. Until then the only way to spot
    #: drift is to compare the two deployments' environments by hand.
    admin_free_allowance_credits: int = Field(default=0, ge=0, le=100)

    # -- the FX rate, OWNED here and nowhere else ----------------------------
    #: Soʻm per US dollar, as an operator entered it. Revenue is UZS tiyin and vendor cost is
    #: USD, and no FX rate exists in any table or setting today — which is the single gap
    #: blocking the dashboard's Net card and its revenue-versus-cost chart.
    #:
    #: **It is on AdminSettings and NOT on ``hbd.config.Settings``**, unlike the three mirrors
    #: above, because it is not a mirror: it is a REPORTING parameter with no other owner.
    #: Every vendor rate card and every NFR ceiling in this system is already quoted in USD,
    #: so nothing the bot or the worker does depends on it, and putting it on the frozen
    #: ``Settings`` would create a fourth mirror whose only property is drift, for a value the
    #: worker would never read. It is therefore absent from ``.env.example`` and present only
    #: in ``.env.admin.example``.
    #:
    #: **Unset means NO RATE**, and the panel renders an em-dash rather than a figure. The
    #: three alternatives are all worse. A default of ``1.0`` silently implies parity and
    #: makes 7 000 UZS read as $7 000 against $3.47 of cost — a 200 000% margin on the one
    #: card whose entire purpose is telling an operator whether the business works. A default
    #: of ``0`` is not a usable multiplier in either direction, since the UZS→USD leg divides
    #: by it. And a "plausible" 12 800 is the worst of the three: a number nobody chose,
    #: drifting silently with the som, presented with exactly the confidence of one an
    #: operator entered — the same argument :attr:`admin_name_match_min_similarity` makes
    #: about an invented threshold and :attr:`hbd.config.Settings.support_contact` makes about
    #: a destination nobody reads.
    #:
    #: **The server never converts.** Every payload carries ``amountMinor`` in its own
    #: currency, ``costUsd`` in USD, and this rate beside them; the arithmetic is the client's
    #: and is gated on a non-null rate. A converted figure on the wire has lost its provenance
    #: and would be silently revalued the day the rate is edited — the same
    #: retroactive-repricing defect ``plan_purchases.songs_included`` and
    #: ``vendor_usage.cost_usd`` were each shaped to avoid.
    #:
    #: ``gt=0`` rather than the ``ge=0`` a rate card uses: a zero there means "not priced" and
    #: its result is discarded, whereas a zero here is arithmetic that cannot be performed.
    #: ``le=1_000_000`` sits two orders of magnitude clear of the som's ~12 000–13 000, so a
    #: fat-finger is caught and a real devaluation is not refused.
    admin_uzs_per_usd: float | None = Field(default=None, gt=0, le=1_000_000)
    #: The date the rate above was taken. **Mandatory whenever a rate is set**, enforced by
    #: :meth:`_the_fx_rate_carries_its_date`, so a stale figure is visibly stale. There is no
    #: feed behind this value and there never will be one in this process; the as-of date is
    #: the only staleness signal there is, and it only works if the panel renders it beside
    #: the rate.
    admin_uzs_per_usd_as_of: date | None = Field(default=None)

    # -- the shipped price, MIRRORED and not owned ---------------------------
    #: ``Settings.single_song_price_minor`` as the WORKER is running it, republished here
    #: because every Finance card on the dashboard multiplies by it.
    #:
    #: Nullable and defaulting to ``None`` on :attr:`admin_name_match_min_similarity`'s
    #: precedent: this process does not read ``.env``, so importing the bot model's default
    #: (700 000) would publish a price a deployment may not be charging. Unset means the
    #: derived-revenue figure is ``null`` and the cost-per-song chart draws no price line —
    #: which is honest, where a wrong price is a wrong number on every card at once.
    #:
    #: Note what this is NOT for: it prices a HYPOTHETICAL ("delivered × the shipped price"),
    #: never a historical sale. Recorded revenue comes from ``topup_purchases`` and
    #: ``plan_purchases``, and nothing may back-price a past sale at a value read now.
    admin_single_song_price_minor: int | None = Field(default=None, ge=0)
    #: ISO-4217 code the mirrored price is denominated in. Travels with the price for the
    #: reason ``cost_source`` travels with ``cost_usd``: an amount with no currency cannot be
    #: read, and this one is compared against ``plan_purchases.currency`` before any total is
    #: formed. Bound both-or-neither to the price by
    #: :meth:`_the_mirrored_price_carries_its_currency` — the AdminSettings counterpart of
    #: ``ck_vendor_usage_cost_carries_its_source``.
    admin_kit_currency: str | None = Field(default=None, min_length=3, max_length=3)

    # -- dashboard query bounds ----------------------------------------------
    #: The trailing window the net run-rate ("MRR") card is computed over, INDEPENDENT of the
    #: request's ``?from``/``?to``. Computing it over the caller's window would make "MRR"
    #: mean "today's net" whenever the selector says Today, and then multiply it by twelve for
    #: the ARR beside it. Bounded above at a year because a monthly run rate annualised by
    #: twelve is only meaningful over a window shorter than the year it annualises to.
    admin_dashboard_run_rate_days: int = Field(default=30, ge=1, le=365)
    #: The longest window ``?bucket=hour`` will serve. Beyond it the request is a 422 naming
    #: the parameter, never a silent coarsening — a chart that quietly changed its bucket
    #: width would be a different measurement wearing the same axis. Eight days rather than
    #: seven so a week-long window plus its equal-length PRIOR window (the delta arm's
    #: spanning scan) still fits.
    admin_dashboard_max_hourly_window_days: int = Field(default=8, ge=1, le=31)
    #: Ceiling on points per series in one dashboard series response; exceeding it is a 422.
    #: 750 clears a year of daily buckets (366) and a month of hourly ones (744), and refuses
    #: a year of hourly ones (8 760), which is not a chart anybody draws.
    admin_dashboard_max_series_buckets: int = Field(default=750, ge=24, le=5_000)

    # -- broadcasts ---------------------------------------------------------
    #: The ONLY Telegram accounts ``POST /api/broadcasts/{id}/test-send`` may reach. Empty by
    #: default, which turns the route off: without an allowlist that endpoint is
    #: "send arbitrary operator-authored text to any customer id you can type", with a step-up
    #: in front of it and an audit row behind it but no bound on WHO. The list is
    #: configuration rather than a request field for the same reason the CIDR list is —
    #: whoever may edit ``.env.admin`` is a different, smaller population than whoever holds
    #: an ADMIN session, and a control the caller supplies is not a control.
    #:
    #: Comma-separated in the environment (``HBD_ADMIN_BROADCAST_TEST_RECIPIENTS=123,456``),
    #: exactly like the proxy CIDRs above.
    admin_broadcast_test_recipients: Annotated[tuple[int, ...], NoDecode] = Field(default=())
    #: How far the real audience may have moved from the number the wizard rendered before a
    #: create is refused with 409 ``CONFLICT``. A fraction, not a count: the same twelve
    #: accounts are noise against forty thousand and a different campaign against forty.
    #:
    #: It is not zero because it cannot be. The audience is counted at creation and people
    #: sign up between the preview render and the button press, so an exact-match rule would
    #: refuse a correct request on a live database roughly always — and the first thing an
    #: operator would learn is to stop sending the expected size at all, which is the control
    #: switching itself off.
    admin_broadcast_audience_drift_tolerance: float = Field(default=0.05, ge=0.0, le=1.0)

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
    _normalize_test_recipients = field_validator("admin_broadcast_test_recipients", mode="before")(
        _split_csv
    )

    @field_validator(
        "admin_name_match_min_similarity",
        "admin_settlement_grace_s",
        "admin_uzs_per_usd",
        "admin_uzs_per_usd_as_of",
        "admin_single_song_price_minor",
        "admin_kit_currency",
        mode="before",
    )
    @classmethod
    def _blank_mirror_means_unpublished(cls, value: Any) -> Any:
        """``HBD_ADMIN_NAME_MATCH_MIN_SIMILARITY=`` is "not published", not a broken float.

        Every other optional value in this file is a ``str`` whose empty form is falsy, so
        an empty variable is simply off. These are numbers, and pydantic would refuse an
        empty string — turning a documented "leave it blank" into a boot failure. The
        example file ships the variables blank, so this is the path an untouched deployment
        actually takes.

        Every *optional* published value shares it, mirrors and the FX pair alike: they are
        the values this process can honestly decline to answer, and a second copy of four
        lines is how one of them keeps the "blank means unset" contract and the other starts
        refusing boots. ``admin_uzs_per_usd_as_of`` is on the list for the sharpest version of
        that: an empty variable would otherwise be a pydantic date-parsing failure at boot,
        for a value the example file ships blank. ``admin_kit_currency`` is on it because
        ``min_length=3`` would refuse an empty string rather than read it as unset. The third
        mirror,
        :attr:`admin_free_allowance_credits`, is not on this list because ``None`` is not a
        value it can hold — see :meth:`_blank_allowance_means_the_shipped_default`.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("admin_free_allowance_credits", mode="before")
    @classmethod
    def _blank_allowance_means_the_shipped_default(cls, value: Any) -> Any:
        """``HBD_ADMIN_FREE_ALLOWANCE_CREDITS=`` is the shipped 0, not a boot failure.

        Four lines rather than one more name on the validator above, because the two answer
        differently: that one turns blank into ``None`` — "this deployment has not published
        it" — and this field has no ``None`` to turn into, since the projection it feeds is
        arithmetic that must produce a number either way. Blank therefore means "whatever the
        bot ships", which is the field default and is 0.

        It exists at all because the file beside it documents "leave the mirrors blank" twice,
        so an operator who applies that habit to a third mirror must not be met with a
        pydantic ``int_parsing`` error naming a variable the example file told them to empty.
        """
        if isinstance(value, str) and not value.strip():
            return 0
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

        :data:`~hbd.admin.csrf.ANY_ORIGIN` is the one value that is not an origin. It turns
        the check off ON PURPOSE, which is a different failure from turning it off by typo
        — so it is spelled as its own token here and refused outside ``dev`` below, rather
        than being reachable by any origin-shaped string.
        """
        if value == ANY_ORIGIN:
            return value
        if not value.startswith(_ORIGIN_SCHEMES):
            raise ValueError(f"must start with http:// or https://, got {value!r}")
        remainder = value.split("://", 1)[1]
        if not remainder or "/" in remainder:
            raise ValueError(f"must be a bare scheme://host[:port] with no path, got {value!r}")
        return value

    @model_validator(mode="after")
    def _the_fx_rate_carries_its_date(self) -> Self:
        """A rate and its as-of date are set together or not at all.

        The settings-level counterpart of ``ck_vendor_usage_cost_carries_its_source``: a
        dollar figure whose provenance is unknown is unreadable, and an undated FX rate is
        exactly that. A som rate goes stale within weeks, there is no feed behind this value,
        and the only staleness signal the panel can render is the date beside it — so a rate
        with no date would be a converted Net card that looks current forever.

        The cost is deliberate and stated: an operator who wants a rate must also type a
        date. ``build_admin_settings`` reports either half missing as a ``ConfigError``
        naming both variables.
        """
        has_rate = self.admin_uzs_per_usd is not None
        has_date = self.admin_uzs_per_usd_as_of is not None
        if has_rate != has_date:
            raise ValueError(
                f"{ENV_PREFIX}ADMIN_UZS_PER_USD and {ENV_PREFIX}ADMIN_UZS_PER_USD_AS_OF must be "
                "set together or left blank together: an FX rate with no as-of date cannot be "
                "read as stale, and the panel would convert every figure on the Net card at a "
                "rate of unknown age"
            )
        return self

    @model_validator(mode="after")
    def _the_mirrored_price_carries_its_currency(self) -> Self:
        """A price and its currency are set together or not at all.

        Same discipline as the FX pair above, for the same reason ``cost_source`` travels
        with ``cost_usd``: an amount with no currency cannot be read, and this one is
        compared against ``plan_purchases.currency`` before any total is formed. A currency
        with no price is the mirror image — a unit for a number nobody published.
        """
        has_price = self.admin_single_song_price_minor is not None
        has_currency = self.admin_kit_currency is not None
        if has_price != has_currency:
            raise ValueError(
                f"{ENV_PREFIX}ADMIN_SINGLE_SONG_PRICE_MINOR and {ENV_PREFIX}ADMIN_KIT_CURRENCY "
                "must be set together or left blank together: an amount with no currency "
                "cannot be summed or compared, and a currency with no amount publishes nothing"
            )
        return self

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
        if self.environment != DEV_ENVIRONMENT and self.admin_public_origin == ANY_ORIGIN:
            raise ValueError(
                f"{ENV_PREFIX}ADMIN_PUBLIC_ORIGIN={ANY_ORIGIN!r} is refused when environment "
                f"is {self.environment!r}: the origin check is the only CSRF layer a login "
                "has — before a session exists there is no token to compare — so accepting "
                "every origin lets any page on the internet POST to this panel using the "
                "operator's cookie. It is a dev-only convenience for running the SPA on an "
                "arbitrary port"
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
    def accepted_origins(self) -> frozenset[str]:
        """The origins the CSRF check accepts — exactly one outside ``dev``.

        In ``dev`` a loopback origin widens to its aliases (see :func:`loopback_aliases`) so
        that typing ``localhost`` where the config says ``127.0.0.1`` is not a 403. This is
        the ONLY consumer that widens: the value reported by the config view, and the one
        logged at boot, stay the single configured origin, because that is what an operator
        set and what staging and prod enforce verbatim.

        ``*`` (:data:`~hbd.admin.csrf.ANY_ORIGIN`) passes through as itself, which
        :func:`~hbd.admin.csrf.verify_origin` reads as "accept anything". The model
        validator has already refused it outside ``dev``, so the branch below cannot emit it
        there; the guard is repeated anyway because this property is what the check reads,
        and a future caller building settings by hand should not be able to route around it.
        Outside ``dev`` that second guard returns the EMPTY set — refuse every origin —
        rather than a plausible default: a wildcard that reached prod is a broken
        configuration, and it should stop the panel, not quietly widen it.
        """
        if self.admin_public_origin == ANY_ORIGIN:
            return frozenset({ANY_ORIGIN}) if self.environment == DEV_ENVIRONMENT else frozenset()
        if self.environment != DEV_ENVIRONMENT:
            return frozenset({self.admin_public_origin})
        return loopback_aliases(self.admin_public_origin)

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
    """Build from :func:`admin_env_file` and the environment, ``overrides`` layered on top.

    Raises ``ConfigError`` and nothing else — a caller never sees a pydantic exception, and
    the operator message names every offending ``HBD_*`` variable.
    """
    values: dict[str, Any] = dict(overrides or {})
    values.setdefault("_env_file", admin_env_file())
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
