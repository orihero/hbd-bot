"""``bayram.checkout_rails``: the env-wired rail list and the owner's per-rail switch.

Written against ``tests/test_admin/conftest.FakeRedis`` on purpose — the fake the admin panel's
tests use, which has ``get``/``set``/``delete`` and no ``mget`` — so a switch module that
reached for a command the admin fake lacks would fail here first (``DECISIONS.md D28``).
"""

from __future__ import annotations

import itertools

import pytest

from bayram.checkout_rails import (
    RAIL_SWITCH_KEY_PREFIX,
    SWITCHABLE_RAILS,
    WIRED_RAILS_KEY,
    publish_wired_rails,
    rail_switch_key,
    read_rail_enabled,
    read_rail_switches,
    read_wired_rails,
    wired_rails,
    write_rail_enabled,
)
from bayram.checkoutuz.ports import CHECKOUTUZ_PROVIDER_NAME
from bayram.config import Settings
from bayram.contracts import Err, is_ok
from bayram.errors import StorageError, ValidationError
from tests.test_admin.conftest import FakeRedis


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rail", SWITCHABLE_RAILS)
async def test_a_switch_round_trips_both_ways(rail: str) -> None:
    redis = FakeRedis()

    assert is_ok(await write_rail_enabled(redis, rail, False))
    assert await read_rail_enabled(redis, rail) is False
    assert is_ok(await write_rail_enabled(redis, rail, True))
    assert await read_rail_enabled(redis, rail) is True


async def test_switching_off_writes_zero_and_never_deletes_the_key() -> None:
    # A delete would make "off" read as "never set", and never-set reads as ON.
    redis = FakeRedis()

    await write_rail_enabled(redis, "payme", False)

    assert redis.values[f"{RAIL_SWITCH_KEY_PREFIX}payme"] == "0"
    await write_rail_enabled(redis, "payme", True)
    assert redis.values[f"{RAIL_SWITCH_KEY_PREFIX}payme"] == "1"


async def test_a_missing_key_reads_as_the_default() -> None:
    redis = FakeRedis()

    assert await read_rail_enabled(redis, "rhmt") is True
    assert await read_rail_enabled(redis, "rhmt", default=False) is False
    assert await read_rail_enabled(None, "rhmt") is True


async def test_an_unreachable_redis_reads_as_the_default_and_does_not_raise() -> None:
    redis = FakeRedis()
    await write_rail_enabled(redis, "checkoutuz", False)
    redis.is_down = True

    assert await read_rail_enabled(redis, "checkoutuz") is True
    assert await read_rail_switches(redis) == dict.fromkeys(SWITCHABLE_RAILS, True)


async def test_an_unrecognised_value_reads_as_the_default() -> None:
    redis = FakeRedis()
    redis.values[rail_switch_key("payme")] = "maybe"

    assert await read_rail_enabled(redis, "payme") is True


async def test_an_unknown_rail_is_a_validation_error_and_writes_nothing() -> None:
    redis = FakeRedis()

    result = await write_rail_enabled(redis, "stub", False)

    assert isinstance(result, Err)
    assert isinstance(result.error, ValidationError)
    assert redis.values == {}


async def test_a_failed_write_is_a_storage_error() -> None:
    redis = FakeRedis()
    redis.is_down = True

    result = await write_rail_enabled(redis, "payme", False)

    assert isinstance(result, Err)
    assert isinstance(result.error, StorageError)


async def test_read_rail_switches_reports_every_rail_in_order() -> None:
    redis = FakeRedis()
    await write_rail_enabled(redis, "payme", False)

    switches = await read_rail_switches(redis)

    assert tuple(switches) == SWITCHABLE_RAILS
    assert switches == {"rhmt": True, "payme": False, "checkoutuz": True}


def test_the_switchable_checkoutuz_name_matches_the_rail_constant() -> None:
    # ``bayram.checkout_rails`` may not import a rail package, so the literal is pinned here.
    assert CHECKOUTUZ_PROVIDER_NAME in SWITCHABLE_RAILS


# ---------------------------------------------------------------------------
# The published wired list
# ---------------------------------------------------------------------------
async def test_wired_rails_round_trip_through_redis() -> None:
    redis = FakeRedis()

    assert await read_wired_rails(redis) is None
    await publish_wired_rails(redis, ("rhmt", "payme", "checkoutuz"))
    assert redis.values[WIRED_RAILS_KEY] == "rhmt,payme,checkoutuz"
    assert WIRED_RAILS_KEY not in redis.ttls
    assert await read_wired_rails(redis) == ("rhmt", "payme", "checkoutuz")


async def test_an_empty_published_list_is_known_and_empty() -> None:
    redis = FakeRedis()

    await publish_wired_rails(redis, ())

    assert await read_wired_rails(redis) == ()


async def test_publish_and_read_never_raise_when_redis_is_down() -> None:
    redis = FakeRedis()
    redis.is_down = True

    await publish_wired_rails(redis, ("payme",))
    assert await read_wired_rails(redis) is None
    assert await read_wired_rails(None) is None


# ---------------------------------------------------------------------------
# wired_rails(settings)
# ---------------------------------------------------------------------------
_BASE: dict[str, tuple[str, ...]] = {
    "stub": (),
    "payme": ("payme",),
    "rhmt": ("rhmt",),
    "both": ("rhmt", "payme"),
}


@pytest.mark.parametrize(
    ("provider", "enabled", "key"),
    list(itertools.product(_BASE, (False, True), ("", "   ", "live-key"))),
)
def test_wired_rails_follows_the_decided_order(
    settings: Settings, provider: str, enabled: bool, key: str
) -> None:
    configured = settings.model_copy(
        update={
            "checkout_provider": provider,
            "checkoutuz_enabled": enabled,
            "checkoutuz_api_key": key,
        }
    )
    expected = _BASE[provider] + (("checkoutuz",) if enabled and key.strip() else ())

    assert wired_rails(configured) == expected


def test_the_settings_defaults_wire_nothing(settings: Settings) -> None:
    assert settings.checkoutuz_enabled is False
    assert settings.checkoutuz_api_key == ""
    assert wired_rails(settings) == ()
