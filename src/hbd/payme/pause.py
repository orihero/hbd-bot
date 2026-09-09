"""The operator pause switch: one Redis key that stops NEW checkouts and nothing else.

**What it stops, and — far more importantly — what it must never stop.** The switch is read in
exactly one place, ``hbd.payme.provider.PaymeCheckoutProvider.charge``, which is the bot-side
half of the rail: the code that opens an intent and hands a customer a link. It is
**deliberately never consulted on an inbound ``PerformTransaction``**, and that is not an
oversight to be tidied up later by somebody adding a check to the gateway for symmetry.
Refusing money that is already in flight is how an incident becomes a dispute: the customer's
card has been charged by Payme, the rail is holding funds it believes are ours, and a merchant
who answers ``-31008`` to that has not prevented a bad sale — it has produced a payment with
no receipt, no credit and no automatic way back, since ``CancelTransaction`` on a performed
transaction is ``-31007`` by design (see ``PAYME_INTEGRATION §6``). The correct shape of
"stop taking money" is therefore to stop QUOTING it, and to settle every quote already given.

**A read that fails is not a pause.** :func:`is_paused` logs at WARNING and answers ``False``
when Redis cannot be reached. This is the same judgement ``PaymeCheckoutProvider`` makes about
its own defensive wrapper and it is written down in both places because it looks wrong on
first reading: surely an unknown state should fail closed? No — the population this switch
protects is "sales we would rather not take for the next twenty minutes", and the population
failing closed would destroy is "every sale, for as long as Redis is unwell". An unreachable
Redis silently stopping all revenue is a far worse outage than a paused rail briefly taking a
payment an operator meant to defer. **It follows that this switch is not a security control
and must never be documented, tested or relied upon as one.** It is an operator convenience
with a known open failure mode.

**A WRITE that fails is loud, and the asymmetry is the whole point.** :func:`set_paused` turns
a Redis failure into a :class:`hbd.errors.StorageError` rather than swallowing it, because the
operator typing ``payme pause`` is about to go and do something on the strength of believing
the rail is shut. A pause that silently did not take is the one way this module could cause the
incident it exists to contain. The read may guess; the write may not.

**The eviction risk, stated honestly.** The key is written with NO TTL, so it does not lapse on
its own — but Redis is a cache in this deployment, not a database: a restart with no persistence
configured, a ``FLUSHDB``, or eviction under ``maxmemory`` pressure all silently un-pause the
rail, and nothing anywhere will say so. There is no fix for that inside this module; a column
would need a migration, a schema and a read on the checkout path that currently touches no
database at all. The compensating control is procedural and it is named in
``docs/deployment/08-payme.md``: ``python -m hbd.payme.cli status`` reports the switch, and the
runbook requires re-checking it after any Redis restart. That is a weaker guarantee than a
durable flag and it is recorded as one rather than dressed up.

**No Redis import.** The client is reached through :class:`PauseSwitch`, a three-method
Protocol, for the reason every store in this codebase is (see
``hbd.ratelimit.WindowCounterStore``): it lets the two functions below be tested against a fake
that can be made to fail on demand, which is the only way the two paragraphs above can be
asserted rather than merely believed. It also keeps ``hbd.payme`` free of a runtime dependency
on ``redis`` in every module but the composition root.

See ``DECISIONS.md D11`` for the rail this belongs to and ``PAYME_INTEGRATION §8`` for the
go-live and rollback sequence the switch is the first step of.
"""

from __future__ import annotations

from typing import Any, Final, Protocol, runtime_checkable

from hbd.errors import StorageError
from hbd.logging import get_logger

__all__ = [
    "PAYME_PAUSE_KEY",
    "PAUSED_VALUE",
    "PauseSwitch",
    "is_paused",
    "set_paused",
]

_LOG = get_logger(__name__)

#: The one key. Namespaced ``hbd:`` like everything else this deployment writes into a shared
#: Redis, and spelled once here because the writer (:func:`set_paused`, reached from the
#: operator CLI) and the reader (:func:`is_paused`, reached from the bot's checkout handler)
#: run in two different processes: a second spelling would not fail a build, it would produce a
#: switch that reports itself as flipped and stops nothing.
PAYME_PAUSE_KEY: Final[str] = "hbd:payme:paused"

#: What a paused rail stores. The VALUE is almost immaterial — :func:`set_paused` deletes the
#: key to resume rather than writing a falsy value, so presence is the signal — but a human
#: running ``redis-cli GET hbd:payme:paused`` during an incident should see something that
#: reads as "yes" rather than an empty string.
PAUSED_VALUE: Final[str] = "1"

#: Values that mean "open" if somebody sets the key by hand to something other than
#: :data:`PAUSED_VALUE`. Accepting these is not indulgence of sloppy operators: it is the
#: difference between ``redis-cli SET hbd:payme:paused 0`` quietly pausing the rail — the exact
#: opposite of what the person typing it intended — and it doing nothing.
_OPEN_VALUES: Final[frozenset[str]] = frozenset({"", "0", "false", "no", "off"})


@runtime_checkable
class PauseSwitch(Protocol):
    """The three Redis commands this module uses, and not one more.

    Narrow on purpose, following :class:`hbd.ratelimit.WindowCounterStore`: a parameter typed
    as the whole client would let a later edit reach for ``expire``, ``scan`` or a pipeline
    inside what is meant to stay a single round trip, and it would make the failure-mode tests
    below need a real Redis to express "this read raises".

    ``redis.asyncio.Redis`` satisfies it structurally with no adapter, which is the point:
    ``hbd.payme.container`` passes its ``ArqRedis`` straight in.
    """

    async def get(self, name: str) -> Any:
        """The stored value, or ``None``. Returns ``bytes`` or ``str`` depending on the client."""
        ...

    async def set(self, name: str, value: str) -> Any:
        """Store a value with no expiry. The pause must outlive the shell that set it."""
        ...

    async def delete(self, *names: str) -> Any:
        """Remove keys. Resuming is a delete, not a falsy write — see :data:`PAUSED_VALUE`."""
        ...


async def is_paused(switch: PauseSwitch) -> bool:
    """Is the checkout rail paused? **A read that fails answers ``False``.**

    Never raises, for the reason argued at length in the module docstring: the alternative to
    guessing here is every sale in the product stopping because a cache is unwell. The guess is
    logged at WARNING so the guess is discoverable, and it is deliberately not logged at ERROR
    — an unreachable Redis is already being reported by the code that actually needs it, and a
    second ERROR per checkout would bury that.
    """
    try:
        stored = await switch.get(PAYME_PAUSE_KEY)
    except Exception as exc:
        # Broad on purpose. redis-py raises its own hierarchy, asyncio raises TimeoutError, the
        # socket layer raises OSError, and a misconfigured DSN raises ValueError — and the
        # answer this function owes its caller is the same for every one of them. Narrowing
        # this would turn an unanticipated client error into an exception crossing a seam on
        # the checkout path, which is precisely what the House rule forbids.
        _LOG.warning(
            "the checkout pause switch could not be read; treating the rail as open",
            extra={"key": PAYME_PAUSE_KEY, "detail": repr(exc)},
        )
        return False
    return _means_paused(stored)


async def set_paused(switch: PauseSwitch, *, paused: bool) -> None:
    """Flip the switch. **Raises :class:`hbd.errors.StorageError` when the write does not land.**

    The mirror image of :func:`is_paused`, and the asymmetry is deliberate — see the module
    docstring. An operator who pauses the rail is about to act on the belief that it is shut;
    a silent no-op here is the one way this module could cause an incident rather than contain
    one.

    ``paused=False`` DELETES the key rather than writing a falsy value, so a resumed rail leaves
    no trace to be misread later, and so ``EXISTS`` is a complete answer for anyone debugging
    with ``redis-cli``. No TTL is set in either direction: a pause that expired on its own would
    re-open the rail at an hour nobody chose.
    """
    try:
        if paused:
            await switch.set(PAYME_PAUSE_KEY, PAUSED_VALUE)
        else:
            await switch.delete(PAYME_PAUSE_KEY)
    except Exception as exc:
        raise StorageError(
            "the checkout pause switch could not be written, so the rail is unchanged",
            is_retryable=True,
            context={"key": PAYME_PAUSE_KEY, "paused": paused, "detail": repr(exc)},
            cause=exc,
        ) from exc
    _LOG.info(
        "an operator changed the checkout pause switch",
        extra={"key": PAYME_PAUSE_KEY, "paused": paused},
    )


def _means_paused(stored: object) -> bool:
    """Interpret whatever the client handed back. ``bytes`` and ``str`` both arrive here.

    ``decode_responses`` is a per-client setting this module does not control and must not
    depend on: ``ArqRedis`` and a hand-built ``Redis`` disagree about it, and a comparison
    against the ``str`` constant alone would make the switch work in one process and not the
    other — the sort of defect that is only ever found during the incident it was armed for.
    """
    if stored is None:
        return False
    if isinstance(stored, bytes | bytearray):
        text = stored.decode("utf-8", "replace")
    else:
        text = str(stored)
    return text.strip().lower() not in _OPEN_VALUES
