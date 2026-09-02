"""The lyric budget's numbers and its day arithmetic — the half with no database in it.

Kept beside ``test_window.py`` because these two modules are the same kind of control read
twice: an update rate held in process memory, and a vendor-spend budget held in a row. The
policy objects, the defensive ``Settings`` resolver and the self-validating ``__post_init__``
are one idiom across ``hbd.ratelimit``, ``hbd.entitlements`` and ``hbd.lyric_budget``, and
this file pins the third instance of it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hbd.config import Settings
from hbd.errors import ConfigError, ValidationError
from hbd.lyric_budget import (
    DEFAULT_LYRIC_BUDGET_POLICY,
    LyricBudgetPolicy,
    day_index_for,
    day_resets_at,
    resolve_lyric_budget_policy,
)

#: 12:00 on a Sunday. Mid-day so a day boundary is never reached by accident.
MOMENT = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def test_the_shipped_ceiling_clears_a_whole_allowance_spent_in_one_sitting() -> None:
    """Three songs a month at the five writes one draft may spend is fifteen; twenty clears it.

    The number is not a taste setting: too tight refuses a paying-intent customer at the one
    step the wizard cannot skip. If ``MAX_LYRIC_WRITES`` or the allowance ever grows, this
    assertion is where the ceiling is re-argued rather than quietly outgrown.
    """
    # Arrange
    from hbd.bot.handlers.lyrics import MAX_LYRIC_WRITES
    from hbd.entitlements import DEFAULT_ENTITLEMENT_POLICY

    # Act
    honest_worst_case = MAX_LYRIC_WRITES * DEFAULT_ENTITLEMENT_POLICY.allowance_credits

    # Assert
    assert DEFAULT_LYRIC_BUDGET_POLICY.writes_per_day > honest_worst_case


def test_a_budget_that_allows_no_writes_is_refused_at_construction() -> None:
    # Arrange / Act / Assert — a ceiling under one refuses every customer their first lyric,
    # which is a configuration mistake and not a policy anyone means.
    with pytest.raises(ConfigError):
        LyricBudgetPolicy(writes_per_day=0)


def test_no_settings_at_all_gives_the_shipped_policy() -> None:
    # Arrange / Act
    policy = resolve_lyric_budget_policy(None)

    # Assert
    assert policy == DEFAULT_LYRIC_BUDGET_POLICY


def test_the_environment_variable_moves_the_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("HBD_LYRIC_WRITES_PER_DAY", "7")
    settings = Settings(
        _env_file=None,
        telegram_bot_token="123456:test-token-value-for-unit-tests-only",
        database_url="postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test",
        elevenlabs_api_key="k",
        llm_api_key="k",
    )

    # Act
    policy = resolve_lyric_budget_policy(settings)

    # Assert
    assert policy.writes_per_day == 7


def test_settings_with_every_hbd_variable_removed_still_constructs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new bounded field must not become a variable an operator is forced to set."""
    # Arrange
    for name in ("HBD_LYRIC_WRITES_PER_DAY",):
        monkeypatch.delenv(name, raising=False)

    # Act
    settings = Settings(
        _env_file=None,
        telegram_bot_token="123456:test-token-value-for-unit-tests-only",
        database_url="postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test",
        elevenlabs_api_key="k",
        llm_api_key="k",
    )

    # Assert
    assert settings.lyric_writes_per_day == DEFAULT_LYRIC_BUDGET_POLICY.writes_per_day


@pytest.mark.parametrize("value", [None, "twenty", True, 0, -1])
def test_an_object_that_is_not_a_usable_ceiling_falls_back_to_the_default(value: object) -> None:
    """``getattr`` over ``object``: this module is a leaf and may not import ``hbd.config``.

    ``True`` is in the list on purpose — a ``bool`` is an ``int`` in Python, and a policy of
    "one write a day" arrived at by type confusion would look like a deliberate lockout.
    """

    # Arrange
    class Stub:
        lyric_writes_per_day = value

    # Act
    policy = resolve_lyric_budget_policy(Stub())

    # Assert
    assert policy == DEFAULT_LYRIC_BUDGET_POLICY


def test_the_day_is_the_allowance_window_asked_for_one_day() -> None:
    # Arrange / Act
    today = day_index_for(MOMENT)
    later_the_same_day = day_index_for(MOMENT.replace(hour=23, minute=59))

    # Assert — one index for the whole UTC day, so the budget cannot roll over at lunchtime.
    assert today == later_the_same_day


def test_the_budget_comes_back_at_the_next_midnight_utc() -> None:
    # Arrange / Act
    resets_at = day_resets_at(day_index_for(MOMENT))

    # Assert — the instant the refusal renders as a date; a customer refused on the 30th is
    # told the 31st, not "in 24 hours" from whenever they happened to be refused.
    assert resets_at == datetime(2026, 8, 31, tzinfo=UTC)


def test_a_naive_clock_is_refused_rather_than_guessed_at() -> None:
    # Arrange / Act / Assert — guessing the zone would move the boundary by up to a day and
    # hand the same account a second budget.
    with pytest.raises(ValidationError):
        day_index_for(datetime(2026, 8, 30, 12, 0))
