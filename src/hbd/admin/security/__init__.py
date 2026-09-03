"""Everything the admin panel uses to decide *who* and *whether*, and nothing else.

Six modules, one job each: password hashing that never blocks the event loop, client-IP
derivation that never believes a header from an untrusted peer, login rate limiting that
runs before argon2 and fails closed, opaque tokens that are stored only as digests, the RBAC
matrix with its action-scoped step-up, and the record-counted reveal budget that bounds how
much personal data one step-up's grace window can be spent on.

Every function here is pure over primitives — parameters, not settings objects, and no
database or Redis access except through an injected store protocol. That is deliberate:
this is the package where a bug is an authentication bypass, so it must be testable without
a request, a server or a session, and it must be readable end to end in one sitting.
"""

from __future__ import annotations

from hbd.admin.security.budget import (
    DEFAULT_REVEAL_BUDGET,
    MAX_RECORDS_PER_REVEAL,
    RevealBudgetDecision,
    RevealBudgetLimits,
    RevealBudgetOutcome,
    RevealBudgetScope,
    charge_reveal_budget,
    reveal_budget_key,
)
from hbd.admin.security.clientip import (
    IpNetwork,
    is_trusted_peer,
    parse_trusted_proxies,
    resolve_client_ip,
)
from hbd.admin.security.passwords import (
    PasswordVerification,
    build_hasher,
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)
from hbd.admin.security.permissions import (
    RBAC_MATRIX,
    ROLE_PERMISSIONS,
    AccessDecision,
    Grant,
    Permission,
    PermissionGuard,
    StepUpAction,
    StepUpGrant,
    StepUpGuard,
    StepUpRequirement,
    build_step_up_scope,
    check_access,
    check_role,
    check_step_up,
    is_permitted,
    require,
    require_step_up,
    step_up_from_session,
)
from hbd.admin.security.ratelimit import (
    LoginRateLimits,
    RateLimitDecision,
    RateLimitOutcome,
    RateLimitScope,
    RedisWindowCounterStore,
    WindowCounterStore,
    check_login_rate_limit,
)
from hbd.admin.security.tokens import (
    SessionToken,
    generate_csrf_token,
    issue_session_token,
    sha256_hex,
)

__all__ = [
    # passwords
    "PasswordVerification",
    "build_hasher",
    "hash_password",
    "hash_password_async",
    "verify_password",
    "verify_password_async",
    # client ip
    "IpNetwork",
    "is_trusted_peer",
    "parse_trusted_proxies",
    "resolve_client_ip",
    # the reveal budget
    "DEFAULT_REVEAL_BUDGET",
    "MAX_RECORDS_PER_REVEAL",
    "RevealBudgetDecision",
    "RevealBudgetLimits",
    "RevealBudgetOutcome",
    "RevealBudgetScope",
    "charge_reveal_budget",
    "reveal_budget_key",
    # rate limiting
    "LoginRateLimits",
    "RateLimitDecision",
    "RateLimitOutcome",
    "RateLimitScope",
    "RedisWindowCounterStore",
    "WindowCounterStore",
    "check_login_rate_limit",
    # tokens
    "SessionToken",
    "generate_csrf_token",
    "issue_session_token",
    "sha256_hex",
    # permissions
    "AccessDecision",
    "Grant",
    "Permission",
    "PermissionGuard",
    "StepUpAction",
    "StepUpGrant",
    "StepUpGuard",
    "StepUpRequirement",
    "RBAC_MATRIX",
    "ROLE_PERMISSIONS",
    "build_step_up_scope",
    "check_access",
    "check_role",
    "check_step_up",
    "is_permitted",
    "require",
    "require_step_up",
    "step_up_from_session",
]
