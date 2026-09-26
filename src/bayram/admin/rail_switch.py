"""The panel's half of the checkout pause switch, and the one ``try``/``except`` it needs.

**Why this module exists at all.** :func:`bayram.payme.pause.set_paused` RAISES a
:class:`~bayram.errors.StorageError` when the Redis write does not land, and handlers in this
package never write ``try``/``except`` — a failure is one :class:`~bayram.admin.errors.ProblemError`
rendered by a single exception handler (§6.2), which is also what keeps ruff's ``TRY`` ruleset
green. So the exception has to become a ``Result`` somewhere, and that somewhere is a named
seam rather than a bare ``try`` inside a route: fifty lines here is the price of every billing
handler staying a straight line, and of the conversion being asserted once instead of at each
call site.

**It is deliberately NOT a second pause mechanism.** There is one key,
:data:`~bayram.payme.pause.PAYME_PAUSE_KEY`, imported and never respelled; one writer,
``pause.set_paused``; one reader, ``pause.is_paused``. The CLI (``python -m bayram.payme.cli
pause``) and this module are two callers of those two functions, which is what keeps "is the
rail paused?" a question with one answer. A panel that wrote its own key — or its own
truthiness rule for the stored value — would give the operator a switch that reports itself
flipped and stops nothing, which is the exact defect ``PAYME_PAUSE_KEY``'s own comment
describes.

**The read may guess; the write may not, and the asymmetry is inherited rather than
invented.** ``is_paused`` never raises and answers ``False`` when Redis is unwell, because the
population failing closed would destroy is "every sale, for as long as Redis is unwell". This
module keeps that behaviour untouched and does NOT wrap the read in a ``Result``, so the panel
reports **what the bot's own checkout path would see** rather than an ``UNKNOWN`` the runtime
does not have. A tri-state ``bool | None`` was the rejected alternative and it is worse than it
looks: it would make the panel a second reader that disagrees with the one
``PaymeCheckoutProvider.charge`` consults, which is two answers to one question — and the
operator would act on the panel's.

``set_paused`` is the mirror image and its failure is loud here for the same reason it is loud
there: an operator who pauses the rail is about to go and do something on the strength of
believing it is shut, so a pause that silently did not take is the one way this seam could
cause the incident it exists to contain. :func:`write_pause` therefore returns an ``Err``,
which :func:`bayram.admin.errors.unwrap` renders as a 503 — never a 200 over an unchanged switch.

**The two caveats the panel must keep saying.** They belong to ``pause.py`` and are restated
here because this is the module a reader of the admin package will find first: the key is
written with no TTL but Redis is a cache in this deployment, so a restart with no persistence,
a ``FLUSHDB`` or eviction under ``maxmemory`` pressure all silently un-pause the rail with
nothing anywhere saying so; and a Redis that cannot be reached reads as OPEN. Neither is
fixable inside this module — a durable flag would need a migration and a database read on a
checkout path that currently touches none — so they are rendered permanently beside the switch
in the console instead (``BILLING_RAIL_BOARD §2``).
"""

from __future__ import annotations

from bayram.admin.container import AdminContainer
from bayram.contracts import Result, err, ok
from bayram.errors import StorageError
from bayram.payme.pause import PAYME_PAUSE_KEY, is_paused, set_paused

__all__ = ["PAYME_PAUSE_KEY", "read_pause", "write_pause"]


async def read_pause(container: AdminContainer) -> bool:
    """Is the rail paused, **as the bot would see it**? Never raises, never answers ``None``.

    A straight call to :func:`bayram.payme.pause.is_paused` over the panel's own Redis handle —
    the same function ``PaymeCheckoutProvider.charge`` calls over the bot's. That sameness is
    the point of the indirection being one line: the panel is not entitled to a better answer
    than the code that acts on it, and any interpretation added here (a TTL check, a second
    truthiness rule, an UNKNOWN) would be a divergence nobody could see until an incident.

    ``container.redis`` satisfies ``pause.PauseSwitch`` structurally — three methods, no
    adapter — which is why nothing in this package imports ``redis`` to make this call.
    """
    return await is_paused(container.redis)


async def write_pause(container: AdminContainer, *, paused: bool) -> Result[None]:
    """Flip the switch, or report that it did not flip. **The only ``try`` in this package's
    billing surface.**

    ``set_paused`` raises rather than returning, so the conversion has to happen once; doing
    it here rather than in the handler is what lets the two route bodies read as
    ``unwrap(await write_pause(...))`` and carry no error handling of their own.

    ``Err`` and not a re-raise: the repo's rule is that a failure crosses a seam as a
    ``Result``, and :func:`bayram.admin.errors.unwrap` turns this one into the shared envelope's
    503 at the boundary. The ``StorageError`` is passed through rather than rebuilt, so the key
    name and the requested state it already carries in ``context`` reach the log unchanged and
    the message an operator reads is the one ``pause.py`` wrote for exactly this failure.

    ``paused=False`` DELETES the key rather than writing a falsy value — that is ``set_paused``'s
    decision and is why an operator debugging with ``redis-cli`` can treat ``EXISTS`` as a
    complete answer. Nothing here re-reads: the caller re-reads through :func:`read_pause`, so
    the response reports the switch as STORED and not as requested.
    """
    try:
        await set_paused(container.redis, paused=paused)
    except StorageError as failure:
        return err(failure)
    return ok(None)
