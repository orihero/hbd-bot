"""The pagination envelope every list endpoint shares, and the two query parameters it reads.

``bayram.admin.schemas.audit`` deliberately does **not** use this: the audit log pages on ``seq``,
a database-assigned monotonic key the hash chain already depends on, while every other list
here pages on ``(created_at, id)`` per §6.1. One envelope covering both would need a cursor
field that means different things per resource, which is worse than two envelopes that each
mean one thing.

``total`` and ``isTotalExact`` travel together and are both ``null`` unless the caller asked
for ``?withTotal=true``. That pairing is the point: ``bounded_total`` stops counting at
:data:`~bayram.db.admin.page.TOTAL_COUNT_CAP`, so a bare ``total`` of 10 000 would be read as a
measurement when it is a ceiling. The panel renders "10,000+" from the pair and a number from
neither half alone.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query

from bayram.admin.errors import unwrap
from bayram.admin.schemas.common import ApiModel
from bayram.db.admin.page import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MIN_PAGE_LIMIT,
    BoundedTotal,
    Page,
    PageRequest,
    page_request,
)

__all__ = ["PageMeta", "page_meta", "PageParams", "Paging"]


class PageMeta(ApiModel):
    """``meta`` on every list response. ``nextCursor`` is ``null`` at the end, never ``""``."""

    next_cursor: str | None = None
    #: Present only for ``?withTotal=true``. See the module docstring on why it is a pair.
    total: int | None = None
    is_total_exact: bool | None = None


def page_meta(page: Page[object], total: BoundedTotal | None = None) -> PageMeta:
    """Build the envelope from a page and, when it was asked for, a bounded count."""
    if total is None:
        return PageMeta(next_cursor=page.next_cursor)
    return PageMeta(next_cursor=page.next_cursor, total=total.total, is_total_exact=total.is_exact)


def page_params(
    limit: Annotated[int, Query(ge=MIN_PAGE_LIMIT, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> PageRequest:
    """``?limit=&cursor=`` as a dependency, validated once for every list endpoint.

    The bounds are declared twice on purpose and the duplication is not a smell: FastAPI's
    ``ge``/``le`` refuse an out-of-range limit at the boundary with a 422 naming the
    parameter, and :func:`~bayram.db.admin.page.page_request` refuses it again for every caller
    that reaches the DB layer without going through HTTP. A cursor can only be checked in
    the second place, because only that layer knows what it encoded.
    """
    return unwrap(page_request(limit=limit, cursor=cursor))


#: The dependency alias handlers annotate with. ``PageParams`` is the type, ``Paging`` the
#: wiring — same split as ``Db`` and ``Container`` in :mod:`bayram.admin.deps`.
PageParams = PageRequest
Paging = Annotated[PageRequest, Depends(page_params)]
