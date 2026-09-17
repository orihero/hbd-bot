"""``?from=`` and ``?to=``, parsed once for every list and metric route.

This module exists because the same twelve lines were written **six** times —
``routers/orders.py``, ``routers/generations.py``, ``routers/assets.py``, ``routers/users.py``
and ``routers/dashboard.py`` each carried a private ``_aware``/``_window`` pair, and
``routers/audit.py`` a sixth ``_aware`` on its own — and the copies had already drifted into
four different refusal messages for one rule. Six spellings of a validator is how a rule gets
relaxed in five places and left strict in the sixth, which is exactly the bug this module is
the fix for (ADMIN_PANEL_AUDIT_AND_REDESIGN_PLAN §2.2, "Strict Interval Validation Bug", and
§5.1's fourth item).

``routers/audit.py`` is the one caller that takes :func:`require_aware` **without**
:func:`resolve_window`, and that is not an oversight: ``GET /api/audit`` hands ``from`` and
``to`` to :class:`~bayram.db.admin.audit.AuditQuery` as two independent bounds rather than as a
half-open interval, so it needs the awareness refusal and nothing else this module decides.
Exporting the check separately is what let the sixth copy be deleted rather than left behind
with a promise to keep it in step; the alternative — folding audit's two bounds into a
``TimeWindow`` it does not use — would have changed a query shape to share a validator.

**Half a window is now a window, and which half decides what the other end is.** The old rule
refused ``?from=`` without ``?to=`` on the argument that the missing bound would be invented.
That argument was right about *inventing* and wrong about *what an operator means*:

* ``?from=X`` alone means "since X, and still going". Its missing end is ``now`` — not a
  fabricated instant but the moment the request was served, which is the only end an
  open-ended range can have. It is resolved **once per request** and travels in the parsed
  window, so a keyset walk down the result re-sends the ``from`` it was given and the server
  re-derives the same shape of query; the cursor, not this function, is what pins the page.
* ``?to=Y`` alone means "everything up to Y". Its missing end is not invented at all — it is
  *absent*, and :class:`~bayram.db.admin.sql.TimeWindow` now models that as ``start is None`` so
  no epoch sentinel ever reaches a ``WHERE`` clause. That is the difference between the two
  cases and the reason they are not symmetrical.

**The ordering check is not repeated here.** ``to`` before ``from`` comes back from
:func:`~bayram.db.admin.sql.time_window`, which owns that rule for every caller including the
ones that never touch HTTP. This function's only judgements are "is it aware" (§6.1: a naive
instant is a 422 here, because ``UtcDateTime`` would otherwise raise inside the driver's bind
processor where no handler is waiting) and "which bound is missing".

**The clock is a parameter, never a call.** Routers read ``utc_now()`` from their own module
globals — see ``routers/assets.py``'s ``list_asset_metadata``, and the seam
``monkeypatch.setattr(assets_router, "utc_now", ...)`` in
``tests/test_admin/test_asset_stream.py:205``, which is currently the ONLY test that moves a
router's clock — so a helper that read the clock itself would quietly move the window out
from under the one mechanism this package uses to shift time in a test. Each router
therefore keeps a three-line adapter that supplies its own ``now``; that is not the
duplication this module deletes, it is a uniform per-module injection point, exercised in
``assets`` today and reachable the same way in the other four the day one of them needs it.
Anchors here are function names rather than line numbers on purpose: the extraction that
created this module deleted sixteen lines from ``assets.py``, which silently moved every
citation that had been written against it.

**Not in** :mod:`bayram.admin.schemas.window`: there is no wire model here, and ``schemas/`` is
where camelCase pydantic lives. **Not in** :mod:`bayram.admin.deps`: that module is the
authentication chain, and a pure parser importing it would drag the session store, the CSRF
check and the RBAC matrix into anything that wants to read two timestamps. **Not in**
:mod:`bayram.db.admin.sql`: that layer owns the SQL type and its ordering rule, and it must not
learn what an ``ErrorCode`` or an HTTP problem envelope is.
"""

from __future__ import annotations

from datetime import datetime

from bayram.admin.errors import AdminProblem, ProblemError, unwrap
from bayram.db.admin.sql import TimeWindow, time_window
from bayram.errors import ErrorCode

__all__ = ["require_aware", "resolve_window"]


def _invalid(message: str) -> ProblemError:
    """422 in the pipeline taxonomy — the code the six routers already used for this."""
    return ProblemError(AdminProblem(code=ErrorCode.INVALID_INPUT, message=message))


def require_aware(name: str, value: datetime | None) -> datetime | None:
    """Refuse a naive instant (§6.1). The message is byte-for-byte the six routers' own.

    Public rather than private because ``routers/audit.py`` needs exactly this and needs no
    window at all; the module docstring says why that caller is shaped differently.

    Kept identical rather than improved: ``tests/test_admin/test_orders_router.py`` asserts on
    the substring ``UTC offset``, and a validator extraction that also reworded its refusal
    would make a behavioural regression look like a copy edit.
    """
    if value is not None and value.tzinfo is None:
        raise _invalid(f"{name} must carry a UTC offset, e.g. 2026-08-30T12:00:00Z")
    return value


def resolve_window(
    since: datetime | None, until: datetime | None, *, now: datetime
) -> TimeWindow | None:
    """``from``/``to`` as a half-open ``[start, end)``, or ``None`` for the whole record.

    ``now`` is the instant the calling route already read for the rest of its work; passing it
    in rather than reading a clock here is what keeps the request's several time-dependent
    answers on the same side of every boundary (see ``routers/assets.py``'s
    ``list_asset_metadata``, which hands one ``now`` to both its page and its count).

    A ``from`` in the future is **not** special-cased into an empty window: it becomes
    ``[from, now)``, which ``time_window`` refuses as "ends before it starts". An operator who
    typed next Tuesday gets told so, rather than getting a page of nothing to interpret.
    """
    start, end = require_aware("from", since), require_aware("to", until)
    if start is None and end is None:
        return None
    return unwrap(time_window(start, end if end is not None else now))
