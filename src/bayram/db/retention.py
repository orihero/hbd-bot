"""The FIL-7 retention schedule, as configuration rather than as literals in a job.

This is a legal requirement (SoW FIL-7 / LR-52), so it is expressed once, here, and every
write site stamps its own ``expires_at`` from it. The purge job then only ever asks
"is ``expires_at`` in the past?" — a single indexed predicate per table, with no join and
no clock arithmetic scattered across six queries.

Storing a derived value is a deliberate trade. The alternative — recomputing the horizon
at purge time from a policy plus an anchor column — reads cleaner but makes a legal hold
(SoW DAT-6) impossible to express, because a hold *is* "push this one row's expiry out".
A stamped column can be held; a computed predicate cannot. The single source of truth for
how the value is derived is :meth:`RetentionPolicy.expires_at`, and nothing else computes
one.

Changing a period changes what NEW rows are stamped with; rows already written keep the
horizon they were stamped with. That is the intended behaviour — a shortened policy must
not retroactively destroy data a user was promised, and a lengthened one must not quietly
resurrect a deletion schedule the privacy notice already stated.

**One table holding personal data is deliberately not represented here: ``user_profiles``.**
The customer's phone number, username, name and profile photo are kept while the account
exists and are erased by ``/forget`` alone — there is no dormancy period, so there is no
field for one here and nothing stamps an ``expires_at`` on that table. That is a product
decision, not an oversight; the argument is in :mod:`bayram.db.models.user_profile`'s
docstring, and it is held honest by ``tests/test_db/test_privacy_constraints.py``, which
lists the table in ``tables_erased_on_request`` and asserts it carries no clock column.
Do not add a period for it here without first moving that table out of that set: a field
in this policy that no write site stamps is a promise the purge job never keeps, and it
would read to the next auditor as a retention schedule that silently does nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

__all__ = [
    "RetentionClass",
    "RetentionPolicy",
    "DEFAULT_RETENTION_POLICY",
    "resolve_retention_policy",
]

_DAYS_PER_YEAR: Final[int] = 365


class RetentionClass(StrEnum):
    """Which row of the FIL-7 table an asset belongs to.

    The class is decided when the asset is written, because only the writer knows whether
    the order was paid; the purge job must not have to re-derive it.
    """

    PAID_AUDIO = "paid_audio"
    FREE_OUTPUT = "free_output"
    EPHEMERAL = "ephemeral"


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Per-class retention periods in days. Frozen: a policy is never edited in place."""

    #: Delivered audio on a paid order — 12 months from delivery.
    paid_audio_days: int = _DAYS_PER_YEAR
    #: Free-tier and sample-adjacent output.
    free_output_days: int = 30
    #: User voice input and intermediate renders.
    ephemeral_days: int = 7
    #: Draft orders the user never completed.
    abandoned_draft_days: int = 14
    #: The recipient's free-text facts, from delivery. Purged regardless of asset class.
    brief_text_days: int = 30
    #: Recipient name, script and candidate orthographies, absent reminder consent.
    recipient_identity_days: int = 90

    def __post_init__(self) -> None:
        for field_name in (
            "paid_audio_days",
            "free_output_days",
            "ephemeral_days",
            "abandoned_draft_days",
            "brief_text_days",
            "recipient_identity_days",
        ):
            value = getattr(self, field_name)
            # ``bool`` is an ``int`` in Python, and ``True`` would silently mean "one day".
            # A retention period is a legal commitment; it does not get to be a typo.
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer, got {value!r}")

    def days_for(self, retention_class: RetentionClass) -> int:
        """Days an asset of ``retention_class`` is kept."""
        match retention_class:
            case RetentionClass.PAID_AUDIO:
                return self.paid_audio_days
            case RetentionClass.FREE_OUTPUT:
                return self.free_output_days
            case RetentionClass.EPHEMERAL:
                return self.ephemeral_days

    def expires_at(self, anchor: datetime, retention_class: RetentionClass) -> datetime:
        """The single place an asset expiry is derived. ``anchor`` is delivery or creation."""
        return anchor + timedelta(days=self.days_for(retention_class))

    def brief_text_expires_at(self, anchor: datetime) -> datetime:
        return anchor + timedelta(days=self.brief_text_days)

    def identity_expires_at(self, anchor: datetime) -> datetime:
        return anchor + timedelta(days=self.recipient_identity_days)

    def abandoned_draft_cutoff(self, now: datetime) -> datetime:
        """Drafts created before this instant are abandoned."""
        return now - timedelta(days=self.abandoned_draft_days)


DEFAULT_RETENTION_POLICY: Final[RetentionPolicy] = RetentionPolicy()

#: ``Settings`` attribute name -> ``RetentionPolicy`` field name.
_SETTINGS_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("retention_paid_audio_days", "paid_audio_days"),
    ("retention_free_output_days", "free_output_days"),
    ("retention_ephemeral_days", "ephemeral_days"),
    ("retention_abandoned_draft_days", "abandoned_draft_days"),
    ("retention_brief_text_days", "brief_text_days"),
    ("retention_recipient_identity_days", "recipient_identity_days"),
)


def resolve_retention_policy(settings: object | None = None) -> RetentionPolicy:
    """Build a policy from ``Settings``, falling back to the FIL-7 defaults.

    ``Settings`` does not carry these fields yet (``bayram.config`` is frozen and owned by
    another module). Reading them defensively means the integrator adds six env-backed
    ints and this function starts honouring them with no change here — and until then the
    legally required defaults apply rather than a crash.
    """
    if settings is None:
        return DEFAULT_RETENTION_POLICY
    overrides = {
        policy_field: value
        for settings_field, policy_field in _SETTINGS_FIELDS
        if isinstance(value := getattr(settings, settings_field, None), int)
        and not isinstance(value, bool)
    }
    if not overrides:
        return DEFAULT_RETENTION_POLICY
    return RetentionPolicy(**overrides)
