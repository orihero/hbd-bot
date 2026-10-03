"""Which checkout rails a deployment sells on: the env-wired list and the owner's per-rail switch.

Two different questions, answered in two different places, and the split is the design
(``DECISIONS.md D28``):

* **Wired** — :func:`wired_rails` — is a pure function of :class:`bayram.config.Settings`. It
  says which rails this deployment was BUILT with, in routing order, and a change needs a
  restart. ``checkout_provider`` contributes ``stub`` → nothing, ``payme`` → Payme, ``rhmt`` →
  Rahmat and ``both`` → Rahmat then Payme; checkout.uz is appended when
  ``checkoutuz_enabled`` is on AND ``checkoutuz_api_key`` is non-blank. An empty tuple means
  the stub. The order is the order the composite routes in and the order the buttons are
  drawn in, so the generic price button always charges ``wired_rails(...)[0]``.
* **Switched** — :func:`read_rail_enabled` / :func:`write_rail_enabled` — is one Redis key per
  rail that the OWNER flips in the admin panel without a restart. It narrows the wired list
  and can never widen it: a rail switched on that is not wired stays unsold.

**Effective sale state is wired AND switched AND not globally paused**, and it is read only
where a sale STARTS — in a rail's ``charge`` and when the bot draws price buttons. Settlement
never reads the switch: money a customer's bank has already taken is settled whatever the
owner has since decided, by exactly the argument ``bayram.payme.pause`` makes for its own key.

**A switch that cannot be read is ON.** A missing key, a value nobody wrote, and an
unreachable Redis all answer the caller's ``default`` (``True``), for the reason the pause
switch fails open: the population a fail-closed read would hurt is "every sale for as long as
Redis is unwell". The env flag is the hard off; this is a convenience with a known open
failure mode, and must not be relied on as a control.

**A switch is never deleted, only written.** Off is an explicit ``"0"`` and on an explicit
``"1"``. Deleting on off — the shape ``bayram.teachers_day`` uses — would make "off" and "never
set" the same state, and since never-set reads as ON here, switching a rail off would switch
it on. A write that fails is loud (:class:`bayram.errors.StorageError`): the owner is about to
act on believing the rail is shut.

**The wired list is published for the admin process**, which cannot read ``bot.env``: the bot
writes it to :data:`WIRED_RAILS_KEY` at boot (no TTL) and the admin panel reads it back to grey
out rails that are not live. ``None`` from :func:`read_wired_rails` means "the bot has not said",
which the panel must render as unknown rather than as "nothing is wired".

This module imports no rail package and no Redis client; the client is duck-typed (``get`` and
``set``), matching ``bayram.teachers_day`` and the fake in ``tests/test_admin/conftest.py``,
which has no ``mget`` — hence one ``get`` per rail in :func:`read_rail_switches`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from bayram.contracts import Result, err, ok
from bayram.errors import StorageError, ValidationError
from bayram.logging import get_logger

if TYPE_CHECKING:
    from bayram.config import Settings

__all__ = [
    "RAIL_SWITCH_KEY_PREFIX",
    "WIRED_RAILS_KEY",
    "SWITCHABLE_RAILS",
    "rail_switch_key",
    "wired_rails",
    "read_rail_enabled",
    "read_rail_switches",
    "write_rail_enabled",
    "read_wired_rails",
    "publish_wired_rails",
]

_LOG = get_logger(__name__)

#: One key per rail: ``bayram:config:checkout_rail:<name>``. Namespaced beside the other owner
#: switches (``bayram:config:teachers_day``), spelled once because the writer (admin) and the
#: readers (bot, rail providers) are different processes.
RAIL_SWITCH_KEY_PREFIX: Final[str] = "bayram:config:checkout_rail:"
#: Comma-separated rail names in routing order, written by the bot at boot with no TTL.
WIRED_RAILS_KEY: Final[str] = "bayram:checkout:wired_rails"
#: The rails the owner may switch, in the order the panel lists them. The names are the
#: ``CheckoutProvider.name`` of each rail and the ``payment_intents.provider`` they write —
#: spelled as literals because this module may not import the rail packages.
SWITCHABLE_RAILS: Final[tuple[str, ...]] = ("rhmt", "payme", "checkoutuz")

_ON: Final[str] = "1"
_OFF: Final[str] = "0"
_ON_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_OFF_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})

#: What each ``checkout_provider`` value contributes, in routing order. Rahmat leads under
#: ``both`` because that is how the shipped composite has always routed the generic button.
_PROVIDER_RAILS: Final[dict[str, tuple[str, ...]]] = {
    "stub": (),
    "payme": ("payme",),
    "rhmt": ("rhmt",),
    "both": ("rhmt", "payme"),
}


def rail_switch_key(rail: str) -> str:
    """The Redis key holding ``rail``'s switch. No validation: callers pass a known rail."""
    return f"{RAIL_SWITCH_KEY_PREFIX}{rail}"


def wired_rails(settings: Settings) -> tuple[str, ...]:
    """The rails this deployment sells on, in routing order. Pure; reads only ``settings``.

    ``()`` means the stub. checkout.uz counts only when it is enabled AND its key is set: an
    enabled rail with no credential is not wired, it is misconfigured, and drawing a button
    for it would put a press in front of a customer that can only fail.
    """
    rails = list(_PROVIDER_RAILS.get(settings.checkout_provider, ()))
    if settings.checkoutuz_enabled and settings.checkoutuz_api_key.strip():
        rails.append("checkoutuz")
    return tuple(rails)


def _decode(value: Any) -> str:
    return (value.decode() if isinstance(value, bytes) else str(value)).strip().lower()


async def read_rail_enabled(redis: Any | None, rail: str, *, default: bool = True) -> bool:
    """Whether the owner has ``rail`` switched on. **Never raises**; fails towards ``default``.

    A value that is neither an on- nor an off-spelling answers ``default`` too, and is logged:
    nothing in this system writes one, so it is somebody's hand in ``redis-cli``, and guessing
    "off" from it would stop sales on a typo.
    """
    if redis is None:
        return default
    key = rail_switch_key(rail)
    try:
        raw = await redis.get(key)
    except Exception as exc:  # a switch read must never take the press down
        _LOG.warning(
            "a checkout rail switch could not be read; treating it as the default",
            extra={"key": key, "rail": rail, "default": default, "detail": repr(exc)},
        )
        return default
    if raw is None:
        return default
    value = _decode(raw)
    if value in _ON_VALUES:
        return True
    if value in _OFF_VALUES:
        return False
    _LOG.warning(
        "a checkout rail switch holds an unrecognised value; treating it as the default",
        extra={"key": key, "rail": rail, "value": value, "default": default},
    )
    return default


async def read_rail_switches(redis: Any | None) -> dict[str, bool]:
    """Every switchable rail's switch, in :data:`SWITCHABLE_RAILS` order. **Never raises.**"""
    return {rail: await read_rail_enabled(redis, rail) for rail in SWITCHABLE_RAILS}


async def write_rail_enabled(redis: Any, rail: str, enabled: bool) -> Result[None]:
    """Store ``rail``'s switch as an explicit ``"1"`` or ``"0"``. Never deletes the key.

    An unknown rail is a :class:`ValidationError` and touches nothing; a Redis failure is a
    :class:`StorageError`, because a switch the owner believes is off and is not is the one way
    this module could cause an incident.
    """
    if rail not in SWITCHABLE_RAILS:
        return err(
            ValidationError(
                "unknown checkout rail",
                context={"rail": rail, "switchable": list(SWITCHABLE_RAILS)},
            )
        )
    key = rail_switch_key(rail)
    try:
        await redis.set(key, _ON if enabled else _OFF)
    except Exception as exc:  # surfaced to the owner as a StorageError
        return err(
            StorageError(
                "failed to write a checkout rail switch to redis",
                context={"rail": rail, "enabled": enabled, "key": key},
                cause=exc,
            )
        )
    return ok(None)


async def read_wired_rails(redis: Any | None) -> tuple[str, ...] | None:
    """The rail list the bot last published, or ``None`` when unknown. **Never raises.**

    An empty string is a real answer — a stub deployment publishes it — and returns ``()``;
    only a missing key or an unreadable Redis returns ``None``.
    """
    if redis is None:
        return None
    try:
        raw = await redis.get(WIRED_RAILS_KEY)
    except Exception as exc:  # the panel renders "unknown" instead
        _LOG.warning(
            "the published wired checkout rails could not be read",
            extra={"key": WIRED_RAILS_KEY, "detail": repr(exc)},
        )
        return None
    if raw is None:
        return None
    return tuple(part for part in (p.strip() for p in _decode(raw).split(",")) if part)


async def publish_wired_rails(redis: Any | None, rails: tuple[str, ...]) -> None:
    """Write ``rails`` to :data:`WIRED_RAILS_KEY` with no TTL. **Never raises.**

    Best-effort by design: a bot that could not publish still sells correctly, and the only
    cost is an admin panel that shows "unknown" until the next boot.
    """
    if redis is None:
        return
    try:
        await redis.set(WIRED_RAILS_KEY, ",".join(rails))
    except Exception as exc:  # publishing is advisory
        _LOG.warning(
            "the wired checkout rails could not be published for the admin panel",
            extra={"key": WIRED_RAILS_KEY, "rails": list(rails), "detail": repr(exc)},
        )
