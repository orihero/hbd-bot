"""``/segments`` — the filter vocabulary, and how many people one filter selects.

Two routes, two routers, two permissions, and the split is the whole design of this module.

**``/segments/fields`` is the builder's source of truth, and it is BROADCAST_READ.** The
segment registry (``BROADCAST_SPEC §1.4``) is an allowlist: a key that is not in
:data:`~bayram.db.admin.segment.FIELDS` is unaddressable under any spelling, and the four
free-text columns a campaign must never target are named in
:data:`~bayram.db.admin.segment.SEGMENT_REFUSALS` so that adding one back is a diff a reviewer
sees. A rule builder that shipped its own copy of that list would drift from it in the one
direction that matters — it would keep offering a field after the server withdrew it, and an
operator would compose an audience the compiler then refuses — so the SPA generates its
editors from this route instead. That also means a deployment missing an optional table
(``chat_messages`` today) tells the builder so, rather than letting an operator write a rule
that is a 422 waiting to happen.

**``/segments/preview`` is RECORDS_READ, and that is not a widening.** It answers exactly
what ``GET /api/users?segment=`` already answers — the same document, the same compiler, the
same statement builder — with the counts instead of the page. Putting it behind
BROADCAST_WRITE would have made an audience number harder to obtain than the list of accounts
it counts, which is the wrong way round; putting it behind BROADCAST_READ would have kept a
viewer from seeing a total for a filter they may already page through one screen at a time.

**No customer row is on either wire, and the preview's missing ``sample`` is deliberate.**
``BROADCAST_SPEC §3.2`` sketched ten masked ``UserView``s beside the counts. ``UserView``
carries the **raw** Telegram id — every ``/users/**`` route keys on it, so the list could not
build a link or a reveal without it — and §6.1 requires every row this feature puts on the
wire to be masked. Rather than mint a second, differently-masked projection of the same row
whose two copies would drift, the preview returns numbers only: an operator who wants to see
the people opens the Users screen with the same ``?segment=`` token.

**Both handlers refuse the same way the Users list does**, because they share the codec and
the compiler: an oversize token is a 422 naming the parameter, an undecodable one is
"segment is not decodable", an unknown field or an unsortable key is
:func:`~bayram.db.admin.segment.compile_segment`'s refusal, and none of the four ever echoes the
caller's value back. Neither handler takes an ``Admin``: §12.3 has no unmasked variant of a
count or of a schema, so taking the operator in order to ignore them would imply a masking
decision that does not exist.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from bayram.admin.deps import API_PREFIX, Db, require_permission
from bayram.admin.errors import unwrap
from bayram.admin.schemas.segment import (
    MAX_SEGMENT_CHARS,
    SEGMENT_SCHEMA_VERSION,
    SegmentFieldsView,
    SegmentModel,
    SegmentPreviewView,
    decode_segment,
    to_segment,
    to_segment_fields_view,
    to_segment_preview_view,
)
from bayram.admin.security.permissions import Permission
from bayram.db.admin.segment import (
    CompiledSegment,
    MatchMode,
    SortSpec,
    compile_segment,
    segment_capabilities,
)
from bayram.db.admin.users import UserFilters, segment_breakdown
from bayram.db.base import utc_now

__all__ = [
    "SEGMENT_FIELDS_PATH",
    "SEGMENT_PREVIEW_PATH",
    "SegmentToken",
    "compiled_segment",
    "build_segment_fields_router",
    "build_segments_router",
]

#: Both are literal segments — nothing under ``/segments`` takes a ``{param}`` — so neither
#: can shadow the other and registration order is uncontested. That is worth stating because
#: it is the exception: ``ORDER_STATE_COUNTS_PATH`` has to be declared ahead of ``ORDER_PATH``
#: for Starlette to reach it at all.
SEGMENT_FIELDS_PATH: Final[str] = f"{API_PREFIX}/segments/fields"
SEGMENT_PREVIEW_PATH: Final[str] = f"{API_PREFIX}/segments/preview"

#: The document, as a query parameter. ``max_length`` is declared here AND checked again
#: inside :func:`~bayram.admin.schemas.segment.decode_segment` — the duplication ``q`` and
#: ``?limit=`` already carry, and for the same reason: this one refuses an oversize token
#: with a 422 naming the parameter, and the codec refuses it for every caller that reaches it
#: without going through HTTP.
SegmentToken = Annotated[str | None, Query(max_length=MAX_SEGMENT_CHARS)]


#: The document a caller who sent no ``?segment=`` still needs when they sent a ``?sort=``:
#: an empty root group, which the compiler reads as "everyone" and which costs exactly what
#: no segment costs. Spelled once here rather than at each call site, because a second
#: literal is a second place for the version number to be wrong.
_EVERYONE: Final[SegmentModel] = SegmentModel(v=SEGMENT_SCHEMA_VERSION, match=MatchMode.ALL)


def compiled_segment(
    raw: str | None, *, now: datetime, sort: SortSpec | None = None
) -> CompiledSegment | None:
    """Decode, lower and compile one ``?segment=`` token, or ``None`` when there was nothing to.

    The three steps are separate because their refusals are: the codec owns "this did not
    come from us", :func:`~bayram.admin.schemas.segment.to_segment` owns nothing at all (it is
    total), and the compiler owns every question about meaning. :func:`unwrap` renders both
    kinds as a 422, since :class:`~bayram.db.admin.segment.SegmentError` is a
    :class:`~bayram.errors.ValidationError`.

    Public because ``routers/users.py`` runs the identical pipeline for the identical
    parameter, and two spellings of it would be two answers to "what does this token mean".
    ``now`` is a parameter rather than a call to ``utc_now()`` here for the reason every
    router in this package threads its clock: the relative-day operators are functions of it,
    and a module that read the wall clock could not be tested across a boundary.

    **``sort`` REPLACES the document's own ordering rather than sitting beside it**, which is
    what lets ``GET /api/users`` take a ``?sort=`` parameter at all. A compiled segment
    always carries exactly one sort, :class:`~bayram.db.admin.users.UserFilters` refuses a sort
    that contradicts it, and two sources for one ordering is how a saved campaign comes to
    claim an order the preview it was approved from never showed. So the override happens
    *before* compilation, where the registry still gets to refuse an unsortable key.

    Both arguments absent is ``None`` — no predicate and no ordering — which is the same
    thing :attr:`~bayram.db.admin.users.UserFilters.segment` means by ``None`` and is why an
    unfiltered list keeps its cheap cursor.
    """
    if raw is None and sort is None:
        return None
    model = _EVERYONE if raw is None else unwrap(decode_segment(raw))
    document = to_segment(model)
    if sort is not None:
        document = replace(document, sort=sort)
    return unwrap(compile_segment(document, now=now, capabilities=segment_capabilities()))


def build_segment_fields_router() -> APIRouter:
    """The registry route, behind the campaign cell. One permission, declared on the router."""
    router = APIRouter(
        tags=["segments"],
        dependencies=[Depends(require_permission(Permission.BROADCAST_READ))],
    )

    @router.get(SEGMENT_FIELDS_PATH)
    async def list_segment_fields() -> SegmentFieldsView:
        """Every field a segment may name, with its operators and its own safety argument.

        No database and no session: the registry is module data and the capability probe
        reads the ORM metadata (:func:`~bayram.db.admin.segment.segment_capabilities`), so this
        route answers without a round trip. It is still guarded — the vocabulary names every
        dimension the panel can ask about a customer, which is not a public document.
        """
        return to_segment_fields_view(capabilities=segment_capabilities())

    return router


def build_segments_router() -> APIRouter:
    """The audience preview, on the same cell as the list it counts."""
    router = APIRouter(
        tags=["segments"],
        dependencies=[Depends(require_permission(Permission.RECORDS_READ))],
    )

    @router.get(SEGMENT_PREVIEW_PATH)
    async def preview_segment(db: Db, segment: SegmentToken = None) -> SegmentPreviewView:
        """How many accounts this document selects, how many are reachable, and in which languages.

        The count is **exact** and deliberately not ``?withTotal=``'s bounded one: this is the
        number a human authorises a send against, and ``10,000+`` is a refusal to answer
        rather than an approximation (:func:`~bayram.db.admin.users.count_segment_exactly` makes
        the same argument at length). It is one grouped statement over the same
        ``_filtered()`` the Users page walks, so the preview and the screen an operator checks
        it against can never be two populations.

        No ``?limit=`` and no cursor: there is nothing here to page.
        """
        filters = UserFilters(segment=compiled_segment(segment, now=utc_now()))
        return to_segment_preview_view(await segment_breakdown(db, filters=filters))

    return router
