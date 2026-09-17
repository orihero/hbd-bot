"""The segment document as it travels — a pydantic shape, and the codec that puts it in a URL.

**This module is the boundary, not the meaning.** :mod:`bayram.db.admin.segment` owns every
question about what a segment *means*: which fields exist, which operator applies to which
kind, what NULL does, how deep a document may nest, how many related-table scans one
document may buy. This module owns the two things that layer must not learn — the wire
SHAPE (camelCase, ``extra="forbid"``, a version number) and the base64url envelope that
lets a whole document ride inside ``?segment=`` — and it decides no audience whatsoever.

**Two refusal points, and deliberately no third.** A bad segment is refused for exactly one
of two reasons, in one of two places:

* **Shape** — not an object, an unknown operator, a value that is not a scalar or a flat
  list, a node that is neither a rule nor a group. Pydantic refuses these, here.
* **Meaning** — an unknown field, an operator that field does not take, a value the field's
  kind cannot use, a limit broken, a sort key that is not sortable.
  :func:`~bayram.db.admin.segment.compile_segment` refuses these, there.

:func:`to_segment` sits between them and is **total**: it cannot fail, has no ``Result``,
and adds no vocabulary of its own. That is the property worth protecting. A lowering step
that could refuse would need its own message for "this is not a date", and there would then
be two spellings of that refusal — one for the query-string path and one for the request
body — which is precisely how ``?from=`` acquired four different messages for one rule
before :mod:`bayram.admin.window` deleted them.

**Instants, and why an unparseable one is passed on rather than rejected.** JSON has no
instant type, so ``joined_at`` arrives as text. :func:`to_segment` asks the registry which
fields are :attr:`~bayram.db.admin.segment.FieldKind.INSTANT` and parses those values into
``datetime`` objects, because the compiler refuses a string outright. What it does **not**
do is judge them: a string that will not parse is handed on as a string, and one that parses
without an offset is handed on naive. Both are refused a few frames later by
``_as_instant`` — "this operator needs an instant" and "an instant must carry a UTC offset"
— which is the module docstring's rule, stated once, applied to the worker and to HTTP
alike. Deciding it twice would let the two copies drift, and only one of them is reachable
from the queue.

**Rule or group, never both.** A node is a :class:`RuleModel` (``field``/``op``/``value``)
or a :class:`GroupModel` (``match``/``rules``). ``extra="forbid"`` on
:class:`~bayram.admin.schemas.common.ApiModel` is what makes a hybrid a 422 rather than a
document whose halves are both half-honoured: ``{"field": "...", "match": "any"}`` fails the
rule branch on the extra ``match`` and the group branch on the extra ``field``, so it
matches neither member of the union and no guess is made about which one was meant.

**Empty root, non-empty group.** The root — :class:`SegmentModel` itself — may carry no
rules, and that means "everyone": an operator who cleared the last row of the filter can see
that the list is unfiltered. A nested :class:`GroupModel` may not, because an empty ``any``
buried two levels down is invisibly ``TRUE`` and drags the whole group's negation with it,
which is how a campaign reaches the entire database while its author believes it was
narrowed. The asymmetry is structural rather than conditional — the root is a different
class from a nested group — so there is no flag anybody can pass to relax it.

**The version is required, not defaulted.** ``v`` is eight bytes and it is the only thing
that lets version 2 be told apart from a client that never heard of versions. A default
would make "no version" and "version 1" the same document forever, and the day the shape
changes the codec would have to guess which of the two a saved campaign holds.

**The two views at the bottom travel the other way, and neither of them widens anything.**
:func:`to_segment_fields_view` publishes the registry itself — key, kind, operators, doc —
so the SPA's rule builder is generated from the server's allowlist rather than from a
hand-kept copy that would eventually offer a field the compiler refuses (or, worse, keep
offering one that was withdrawn). :func:`to_segment_preview_view` publishes counts over an
audience and no rows at all: there is deliberately no sample of matching customers here,
because §6.1 requires every row this feature puts on the wire to be masked and
:class:`~bayram.admin.schemas.users.UserView` carries the raw Telegram id by design — every
``/users/**`` route keys on it. An operator who wants to see the people can ask
``GET /api/users?segment=`` with the same document, the same compiler and the same
permission, so nothing is withheld except a second projection nobody needs.

**The token is opaque and untrusted.** ``?segment=`` is a query string a browser hands us,
so :func:`decode_segment` is a never-throw boundary returning ``Result`` — the same posture
:func:`~bayram.db.admin.page.decode_cursor` takes for the same reason, and its refusals carry
the parameter and never the caller's text. :data:`MAX_SEGMENT_CHARS` is checked *before*
the base64 is touched: it bounds the work every later step does, and it keeps a document
nested far below the interpreter's recursion limit, which is the one failure a decoder
cannot report as a ``Result``.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Annotated, Final

from pydantic import StringConstraints, field_validator
from pydantic import ValidationError as PydanticValidationError

from bayram.admin.schemas.common import ApiModel
from bayram.contracts import Language, Result, err, ok
from bayram.db.admin.segment import (
    DEFAULT_SORT,
    FIELDS,
    SEGMENT_LIMITS,
    SORT_KEYS,
    FieldKind,
    FieldSpec,
    MatchMode,
    Segment,
    SegmentError,
    SegmentGroup,
    SegmentNode,
    SegmentOp,
    SegmentRule,
    SortDirection,
    SortSpec,
)
from bayram.db.admin.views import SegmentBreakdown

__all__ = [
    "MAX_SEGMENT_CHARS",
    "MAX_SEGMENT_KEY_CHARS",
    "SEGMENT_SCHEMA_VERSION",
    "SegmentValue",
    "RuleModel",
    "GroupModel",
    "SegmentNodeModel",
    "SortModel",
    "SegmentModel",
    "encode_segment",
    "decode_segment",
    "to_segment",
    "SegmentFieldView",
    "SegmentLimitsView",
    "SegmentFieldsView",
    "LanguageCount",
    "SegmentPreviewView",
    "to_segment_fields_view",
    "to_segment_preview_view",
]

#: The base64url token's ceiling, checked before anything decodes it. Declared here and
#: repeated as ``Query(max_length=MAX_SEGMENT_CHARS)`` at the router — the duplication ``q``
#: and ``?limit=`` already carry, and for the same reason: the router refuses an oversize
#: parameter with a 422 naming it, and this module refuses it again for every caller that
#: reaches the codec without going through HTTP. Four kilobytes is roughly forty times the
#: largest document :data:`~bayram.db.admin.segment.SEGMENT_LIMITS` permits, and small enough
#: that no legal document can nest deep enough to reach Python's recursion limit.
MAX_SEGMENT_CHARS: Final[int] = 4096

#: The shape below. Bumped only when a field is renamed or removed — adding an optional one
#: is not a new version, because a version 1 document still means what it said.
SEGMENT_SCHEMA_VERSION: Final[int] = 1

#: A registry key is a schema name this API publishes, and the longest one is twenty-four
#: characters. The cap exists because an UNKNOWN key is the one caller-supplied string the
#: compiler does put in an error context (``_compile_rule``: "unknown field"), so without a
#: bound a three-kilobyte key would ride into a log line.
MAX_SEGMENT_KEY_CHARS: Final[int] = 64

#: A string value is an enum member, a wizard step or an RFC3339 instant — the longest of
#: which is about thirty characters. There is no free-text field and cannot be one:
#: :data:`~bayram.db.admin.segment.SEGMENT_REFUSALS` names the columns that would need one.
_MAX_VALUE_CHARS: Final[int] = 64

#: ``v``. Named because :func:`_refusal_for` matches an error location against it.
_VERSION_FIELD: Final[str] = "v"

_TOO_LONG: Final[str] = "segment is too long"
_NOT_DECODABLE: Final[str] = "segment is not decodable"
_NOT_A_DOCUMENT: Final[str] = "segment is not a valid document"
_UNKNOWN_VERSION: Final[str] = "unknown segment schema version"
_EMPTY_GROUP: Final[str] = "a group must carry at least one rule"

#: One member of a rule's value. Bounded scalars and nothing else — a nested object is not a
#: value any operator takes, so it is refused by the schema rather than carried as far as
#: the compiler. ``bool`` leads the union so JSON's ``true`` stays a ``bool``; the compiler
#: refuses it where a number is wanted, which it could not do if it arrived as ``1``.
type RuleValue = bool | int | Annotated[str, StringConstraints(max_length=_MAX_VALUE_CHARS)]

#: What a rule carries. ``None`` is the value of a no-operand operator (``is_true``,
#: ``is_null``); the LIST is flat because ``in``/``not_in``/``between`` are the only
#: operators that take several, and none of them nests.
type SegmentValue = RuleValue | list[RuleValue] | None


class RuleModel(ApiModel):
    """One leaf predicate: a registry key, an operator, and the operator's value.

    ``field`` is checked for length here and for EXISTENCE nowhere in this module — the
    registry is the allowlist and :func:`~bayram.db.admin.segment.compile_segment` is where a
    key is resolved against it. Validating it twice would mean two lists of field names, and
    the second one would be the one somebody forgot to update.
    """

    field: Annotated[str, StringConstraints(max_length=MAX_SEGMENT_KEY_CHARS)]
    op: SegmentOp
    value: SegmentValue = None


class GroupModel(ApiModel):
    """A nested boolean node, which must carry at least one rule.

    Only the NESTED case is this class; the root is :class:`SegmentModel`. See the module
    docstring on why an empty group is refused here while an empty root is not.
    """

    match: MatchMode
    rules: tuple[SegmentNodeModel, ...]

    @field_validator("rules")
    @classmethod
    def _must_carry_a_rule(
        cls, rules: tuple[SegmentNodeModel, ...]
    ) -> tuple[SegmentNodeModel, ...]:
        if not rules:
            raise ValueError(_EMPTY_GROUP)
        return rules


#: A node is one or the other. The union is unordered on purpose: ``extra="forbid"`` makes
#: the two shapes disjoint, so nothing is decided by which branch is tried first.
type SegmentNodeModel = RuleModel | GroupModel

GroupModel.model_rebuild()


class SortModel(ApiModel):
    """What the result is ordered by. ``key`` is a NAME, resolved by the registry, never here.

    The DIRECTION is settled by the type — :data:`~bayram.db.admin.segment.SortDirection` is a
    two-member ``Literal`` — which is what lets ``segment._check_sort`` check the key alone
    and call a runtime guard on the direction dead code.
    """

    key: Annotated[str, StringConstraints(max_length=MAX_SEGMENT_KEY_CHARS)]
    dir: SortDirection = DEFAULT_SORT.direction


class SegmentModel(ApiModel):
    """A whole segment document: a version, the root group inline, and an optional sort.

    The root group is spelled INLINE rather than as a nested ``root`` object because that is
    the document an operator reads and the one the wizard writes; a wrapper level would buy
    nothing but a second pair of braces in every saved campaign.
    """

    #: Required. See the module docstring on why this has no default.
    v: int
    match: MatchMode
    #: Empty means everyone — the unfiltered list, and the only place empty is legal.
    rules: tuple[SegmentNodeModel, ...] = ()
    #: Absent means :data:`~bayram.db.admin.segment.DEFAULT_SORT`.
    sort: SortModel | None = None

    @field_validator("v")
    @classmethod
    def _known_version(cls, version: int) -> int:
        if version != SEGMENT_SCHEMA_VERSION:
            raise ValueError(_UNKNOWN_VERSION)
        return version


def encode_segment(model: SegmentModel) -> str:
    """Serialise a document to the opaque base64url token ``?segment=`` carries.

    ``exclude_none`` keeps a token as short as the document it stands for: a ``is_true`` rule
    has no value and a default sort is not a sort, and both would otherwise be spelled out in
    every "next page" link this parameter rides along with. It is not size for its own sake —
    :data:`MAX_SEGMENT_CHARS` is a hard refusal at the other end, and the fields dropped here
    are exactly the ones that carry no information.
    """
    payload = json.dumps(
        model.model_dump(mode="json", by_alias=True, exclude_none=True),
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_segment(raw: str) -> Result[SegmentModel]:
    """Parse a document out of a query string. Never raises; every failure is a typed ``Err``.

    Four things can be wrong with an inbound token — it is too long, it is not base64 or not
    UTF-8 or not JSON, it is JSON that is not this shape, or it is this shape at a version we
    do not speak — and only the last two are worth telling apart. The rest all mean "this did
    not come from us" to the caller, so they collapse into one refusal rather than a taxonomy
    nobody branches on, exactly as :func:`~bayram.db.admin.page.decode_cursor` collapses its six.

    Pydantic's own message is deliberately NOT forwarded: it quotes the input that failed, and
    the value a caller sent is the one thing a segment refusal must never carry.
    """
    if len(raw) > MAX_SEGMENT_CHARS:
        return err(_bad_segment(_TOO_LONG))
    try:
        # The padding restoration ``page.decode_cursor`` does, for the same reason: a
        # URL-safe encoder elsewhere may have stripped the ``=``.
        decoded = base64.urlsafe_b64decode((raw + "=" * (-len(raw) % 4)).encode("ascii", "ignore"))
        document = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, ValueError) as exc:
        # ``ValueError`` covers UnicodeDecodeError and json.JSONDecodeError, both subclasses.
        return err(_bad_segment(_NOT_DECODABLE, cause=exc))
    try:
        model = SegmentModel.model_validate(document)
    except PydanticValidationError as exc:
        return err(_bad_segment(_refusal_for(exc), cause=exc))
    return ok(model)


def to_segment(model: SegmentModel) -> Segment:
    """Lower a wire document onto the plain dataclasses the compiler takes. Cannot fail.

    Every refusal this step could plausibly make is already made on one side of it or the
    other — see the module docstring — so this is a translation and nothing else. The only
    judgement it exercises is asking the registry which fields are instants, and it does that
    to CONVERT rather than to validate: an unparseable or naive instant travels on unchanged
    and is refused by the compiler, which owns that message.
    """
    root = SegmentGroup(match=model.match, rules=tuple(_lower(node) for node in model.rules))
    if model.sort is None:
        return Segment(root=root)
    return Segment(root=root, sort=SortSpec(key=model.sort.key, direction=model.sort.dir))


class SegmentFieldView(ApiModel):
    """One entry of the registry, as the rule builder reads it.

    ``key``, ``kind`` and ``ops`` are what the editor needs to draw a row: which operators to
    offer, and what kind of input the value is. ``doc`` is the field's own safety argument,
    carried verbatim from :attr:`~bayram.db.admin.segment.FieldSpec.doc` rather than paraphrased
    into a UI label — an operator choosing an audience should be able to read what the field
    actually means, and a second copy of that sentence in TypeScript is a second copy to keep
    true.
    """

    key: str
    kind: FieldKind
    #: Sorted by value, so two reads of an unchanged registry are byte-identical and a
    #: client can cache the document.
    ops: tuple[SegmentOp, ...]
    #: Whether this key may appear in ``sort``. Read from
    #: :data:`~bayram.db.admin.segment.SORT_KEYS` rather than from ``FieldSpec.sortable``, which
    #: is only half the condition — a sortable field also needs an expression to order by.
    sortable: bool
    #: True when the predicate is a correlated subquery. Published because it is what makes a
    #: rule expensive and what makes ``?withTotal=`` refuse to run beside a sort on it, and an
    #: SPA that cannot see it would have to discover both by getting a 422.
    is_aggregate: bool
    #: The table this field needs, or ``null`` when it always works.
    capability: str | None
    #: Whether this deployment has that table. A field whose capability is missing is still
    #: LISTED — the builder shows it disabled rather than pretending it was never designed —
    #: because a rule on it is a refusal naming the field, and "the table is not installed
    #: here" must not look like "nobody matched".
    is_available: bool
    doc: str


class SegmentLimitsView(ApiModel):
    """:data:`~bayram.db.admin.segment.SEGMENT_LIMITS`, so the editor stops before the
    server does."""

    max_rules: int
    max_depth: int
    max_value_members: int
    max_aggregate_rules: int


class SegmentFieldsView(ApiModel):
    """``GET /api/segments/fields`` — the whole vocabulary of a segment document."""

    #: The document version a client must send. Published rather than hard-coded in the SPA
    #: for the reason :data:`SEGMENT_SCHEMA_VERSION` exists at all.
    version: int
    default_sort: SortModel
    limits: SegmentLimitsView
    #: Ordered by key, for the same reason ``ops`` is.
    fields: list[SegmentFieldView]


class LanguageCount(ApiModel):
    """One language and how many of the audience read it. Empty languages are absent."""

    language: Language
    count: int


class SegmentPreviewView(ApiModel):
    """``GET /api/segments/preview`` — how many people, and how many of them are reachable.

    **The three refusal counts overlap and the client must not add them up.** ``blocked`` is
    our own bar and ``skippedBotBlocked`` is the customer's; one account can be both, so
    ``matched`` is not their sum plus ``reachable``. Only ``reachable`` is a complement, and
    it is the number a send would actually attempt.
    """

    #: Exact, never bounded — see :func:`~bayram.db.admin.users.count_segment_exactly` for why a
    #: saturating total is not an answer anybody can authorise a broadcast against.
    matched: int
    reachable: int
    skipped_blocked: int
    skipped_bot_blocked: int
    by_language: list[LanguageCount]


def to_segment_fields_view(*, capabilities: frozenset[str]) -> SegmentFieldsView:
    """The registry as data, for the deployment the caller is actually talking to.

    ``capabilities`` is a parameter rather than a call to
    :func:`~bayram.db.admin.segment.segment_capabilities` here, so the router reads the
    deployment once and the same set decides both what this document says is available and
    what :func:`~bayram.db.admin.segment.compile_segment` will accept a moment later.
    """
    return SegmentFieldsView(
        version=SEGMENT_SCHEMA_VERSION,
        default_sort=SortModel(key=DEFAULT_SORT.key, dir=DEFAULT_SORT.direction),
        limits=SegmentLimitsView(
            max_rules=SEGMENT_LIMITS.max_rules,
            max_depth=SEGMENT_LIMITS.max_depth,
            max_value_members=SEGMENT_LIMITS.max_value_members,
            max_aggregate_rules=SEGMENT_LIMITS.max_aggregate_rules,
        ),
        fields=[_field_view(spec, capabilities=capabilities) for spec in _sorted_specs()],
    )


def to_segment_preview_view(breakdown: SegmentBreakdown) -> SegmentPreviewView:
    """The audience preview. Counts only — no row, masked or otherwise, is on this wire."""
    return SegmentPreviewView(
        matched=breakdown.matched,
        reachable=breakdown.reachable,
        skipped_blocked=breakdown.blocked,
        skipped_bot_blocked=breakdown.bot_blocked,
        by_language=[
            LanguageCount(language=language, count=count)
            for language, count in breakdown.by_language
        ],
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _sorted_specs() -> list[FieldSpec]:
    return [FIELDS[key] for key in sorted(FIELDS)]


def _field_view(spec: FieldSpec, *, capabilities: frozenset[str]) -> SegmentFieldView:
    return SegmentFieldView(
        key=spec.key,
        kind=spec.kind,
        ops=tuple(sorted(spec.ops)),
        sortable=spec.key in SORT_KEYS,
        is_aggregate=spec.is_aggregate,
        capability=spec.capability,
        is_available=spec.capability is None or spec.capability in capabilities,
        doc=spec.doc,
    )


def _bad_segment(message: str, *, cause: Exception | None = None) -> SegmentError:
    # The offending document is deliberately NOT in the context: it is attacker-supplied text
    # that would otherwise be interpolated into a log line and an error body — the refusal
    # ``SegmentError`` and ``page._bad_cursor`` both make.
    return SegmentError(message, context={"parameter": "segment"}, cause=cause)


def _refusal_for(exc: PydanticValidationError) -> str:
    """Which of the two shape refusals a pydantic failure was.

    The error's LOCATION is read and its message is not. A location is a field name this API
    published; a message quotes what the caller sent.

    A document with NO version lands here too — its failure is located at ``v`` — and gets the
    same refusal, which is the true one: a document that does not say which shape it is, is a
    document whose shape we do not know.
    """
    for error in exc.errors():
        if error["loc"][:1] == (_VERSION_FIELD,):
            return _UNKNOWN_VERSION
    return _NOT_A_DOCUMENT


def _lower(node: SegmentNodeModel) -> SegmentNode:
    """One wire node to one compiler node, recursively. Depth is the compiler's limit, not ours."""
    if isinstance(node, GroupModel):
        return SegmentGroup(match=node.match, rules=tuple(_lower(child) for child in node.rules))
    return SegmentRule(field=node.field, op=node.op, value=_lower_value(node.field, node.value))


def _lower_value(field: str, value: SegmentValue) -> object:
    """JSON text to a Python instant, but only where the registry says the field is one.

    An unknown key falls through untouched — the compiler refuses it by name a moment later,
    and a lowering step that raised here would be refusing the same document twice with two
    different messages.
    """
    spec = FIELDS.get(field)
    if spec is None or spec.kind is not FieldKind.INSTANT:
        return value
    if isinstance(value, list):
        return [_as_instant(member) for member in value]
    return _as_instant(value)


def _as_instant(value: RuleValue | None) -> object:
    """``datetime.fromisoformat`` where it applies, and the value unchanged where it does not."""
    if not isinstance(value, str):
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        # Not a date at all. The compiler says so, in the one message it already has for it.
        return value
    return parsed
