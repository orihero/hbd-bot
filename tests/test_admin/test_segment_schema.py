"""The segment document's WIRE half — the shape, the codec, and the lowering between them.

``tests/test_db/test_admin_segment.py`` already asserts what a segment MEANS, against a real
engine and a hand-written population. Nothing here re-asserts any of that. This file is about
the three things that layer cannot see:

* **What a browser can hand us.** ``?segment=`` is a query string, so every assertion about a
  forged token is an assertion that the boundary returns an ``Err`` rather than raising — the
  same never-throw property ``tests/test_admin/test_pagination.py`` asserts of ``decode_cursor``,
  for the same reason: a 500 on a malformed parameter is a bug an operator cannot work around.
* **That a node is a rule or a group and never both.** ``extra="forbid"`` is what makes a
  hybrid a 422, and it is one word in a base class three imports away — precisely the kind of
  setting that survives a review and dies in a refactor. So the hybrid is tested directly.
* **That the lowering adds no vocabulary.** :func:`~hbd.admin.schemas.segment.to_segment` is
  total by design, and the value of that is only visible in a test that hands it something
  wrong and finds the refusal arriving from the COMPILER's message rather than a second copy
  of it here. An unparseable instant and a naive one are both checked that way.

The blueprint's own example document (§1.2) is written out verbatim as :data:`_BLUEPRINT` and
walked end to end — decode, lower, compile — because the three steps are separately correct in
a way that composes wrongly if any of them invents a default.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from hbd.admin.schemas.segment import (
    MAX_SEGMENT_CHARS,
    SEGMENT_SCHEMA_VERSION,
    GroupModel,
    RuleModel,
    SegmentModel,
    SortModel,
    decode_segment,
    encode_segment,
    to_segment,
)
from hbd.contracts import is_err, is_ok
from hbd.db.admin.segment import (
    DEFAULT_SORT,
    MatchMode,
    SegmentError,
    SegmentGroup,
    SegmentOp,
    SegmentRule,
    compile_segment,
    segment_capabilities,
)

#: One clock for the whole file. The compiler reads no wall clock, so this is the only "today"
#: any assertion below depends on.
_NOW: Final[datetime] = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)

#: This deployment's optional tables, resolved once. Compiling against the real set rather than
#: an empty one is what keeps a capability-gated field from silently becoming untestable.
_CAPABILITIES: Final[frozenset[str]] = segment_capabilities()

#: BLUEPRINT §1.2, transcribed. Changing this dict is changing the published contract.
_BLUEPRINT: Final[dict[str, Any]] = {
    "v": 1,
    "match": "all",
    "rules": [
        {"field": "ui_language", "op": "in", "value": ["ru", "en"]},
        {
            "field": "joined_at",
            "op": "between",
            "value": ["2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"],
        },
        {
            "match": "any",
            "rules": [
                {"field": "plan_status", "op": "in", "value": ["lapsed"]},
                {"field": "delivered_order_count", "op": "gte", "value": 3},
            ],
        },
    ],
    "sort": {"key": "delivered_order_count", "dir": "desc"},
}

#: The two shape refusals this module makes. Named so an assertion says which one it wants.
_NOT_A_DOCUMENT: Final[str] = "segment is not a valid document"
_UNKNOWN_VERSION: Final[str] = "unknown segment schema version"

#: A string no legal document contains, planted in every place a caller controls, so a refusal
#: that echoes ANY of them fails a test instead of a privacy review.
_SENTINEL: Final[str] = "leaked-caller-text"

#: Tokens that did not come from this API. Every one must be a typed ``Err`` naming the
#: parameter — never a raise, and never a document.
_FORGED_TOKENS: Final[tuple[tuple[str, str], ...]] = (
    ("empty", ""),
    ("not-base64", "!!! not base64 at all !!!"),
    ("not-utf-8", base64.urlsafe_b64encode(b"\xff\xfe not utf-8").decode("ascii")),
    ("not-json", base64.urlsafe_b64encode(b"{not json").decode("ascii")),
    ("not-an-object", base64.urlsafe_b64encode(b"[1,2,3]").decode("ascii")),
    ("a-bare-number", base64.urlsafe_b64encode(b"7").decode("ascii")),
    ("json-null", base64.urlsafe_b64encode(b"null").decode("ascii")),
)


def _token(document: object) -> str:
    """What a browser sends: an arbitrary JSON value, base64url'd. Never a model."""
    return base64.urlsafe_b64encode(json.dumps(document).encode("utf-8")).decode("ascii")


def _decoded(document: object) -> SegmentModel:
    """Decode a document that is expected to be legal, and fail loudly if it is not."""
    result = decode_segment(_token(document))
    assert is_ok(result), result
    return result.value


def _refused(document: object) -> SegmentError:
    """Decode a document that is expected to be refused, and hand back the refusal."""
    result = decode_segment(_token(document))
    assert is_err(result), result
    assert isinstance(result.error, SegmentError)
    return result.error


def _refusal(document: object) -> str:
    """The message a refused document produces — all most of the assertions below need."""
    return str(_refused(document))


# ---------------------------------------------------------------------------
# the blueprint's own document, end to end
# ---------------------------------------------------------------------------
def test_the_blueprint_document_decodes_lowers_and_compiles() -> None:
    model = _decoded(_BLUEPRINT)

    assert model.v == SEGMENT_SCHEMA_VERSION
    assert model.match is MatchMode.ALL
    assert [type(node) for node in model.rules] == [RuleModel, RuleModel, GroupModel]

    segment = to_segment(model)
    assert segment.sort.key == "delivered_order_count"
    assert segment.sort.direction == "desc"

    compiled = compile_segment(segment, now=_NOW, capabilities=_CAPABILITIES)
    assert is_ok(compiled), compiled
    assert compiled.value.predicate is not None
    # ``plan_status`` and ``delivered_order_count`` both scan a related table; the two direct
    # columns do not. The router reads this number to refuse ``?withTotal=`` beside them.
    assert compiled.value.aggregate_rule_count == 2


def test_a_token_this_module_minted_reads_back_unchanged() -> None:
    """Round trip, including the two fields ``encode_segment`` drops as uninformative."""
    for document in (
        _BLUEPRINT,
        {"v": 1, "match": "all", "rules": []},
        {"v": 1, "match": "none", "rules": [{"field": "is_blocked", "op": "is_true"}]},
    ):
        model = _decoded(document)
        round_tripped = decode_segment(encode_segment(model))
        assert is_ok(round_tripped), round_tripped
        assert round_tripped.value == model


# ---------------------------------------------------------------------------
# the never-throw boundary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("name", "raw"), _FORGED_TOKENS, ids=[name for name, _ in _FORGED_TOKENS])
def test_a_forged_token_is_a_typed_refusal_and_never_a_raise(name: str, raw: str) -> None:
    result = decode_segment(raw)

    assert is_err(result), name
    assert isinstance(result.error, SegmentError)
    assert result.error.context["parameter"] == "segment"


def test_a_token_over_the_cap_is_refused_before_anything_decodes_it() -> None:
    result = decode_segment("A" * (MAX_SEGMENT_CHARS + 1))

    assert is_err(result)
    assert str(result.error) == "segment is too long"


def test_a_token_at_the_cap_is_not_refused_for_its_length() -> None:
    """The bound is a ceiling, not a fence one character inside it."""
    padded = _token(_BLUEPRINT)
    assert len(padded) <= MAX_SEGMENT_CHARS
    assert is_ok(decode_segment(padded))


def test_a_refusal_never_carries_the_caller_s_text() -> None:
    """Pydantic's own message quotes the input. This boundary must not forward it."""
    error = _refused(
        {
            "v": 1,
            "match": "all",
            "rules": [{"field": _SENTINEL, "op": "eq", "value": _SENTINEL, _SENTINEL: 1}],
            _SENTINEL: _SENTINEL,
        }
    )

    rendered = f"{error} {error.context}"
    assert _SENTINEL not in rendered


# ---------------------------------------------------------------------------
# a node is a rule or a group, never both
# ---------------------------------------------------------------------------
def test_a_hybrid_node_is_neither_a_rule_nor_a_group() -> None:
    error = _refused(
        {
            "v": 1,
            "match": "all",
            "rules": [{"field": "joined_at", "op": "is_null", "match": "any"}],
        }
    )

    assert str(error) == _NOT_A_DOCUMENT


@pytest.mark.parametrize(
    "node",
    [
        pytest.param({"field": "joined_at"}, id="rule-without-an-operator"),
        pytest.param({"op": "is_null"}, id="operator-without-a-field"),
        pytest.param({"match": "any"}, id="group-without-rules"),
        pytest.param({"rules": [{"field": "is_blocked", "op": "is_true"}]}, id="rules-no-match"),
        pytest.param({"field": "is_blocked", "op": "is_true", "negate": True}, id="a-negate-flag"),
        pytest.param({}, id="an-empty-object"),
    ],
)
def test_a_half_written_node_is_refused(node: dict[str, Any]) -> None:
    assert _refusal({"v": 1, "match": "all", "rules": [node]}) == _NOT_A_DOCUMENT


def test_an_empty_nested_group_is_refused() -> None:
    """A silently-true group is how a campaign reaches everybody while looking narrowed."""
    error = _refused({"v": 1, "match": "all", "rules": [{"match": "any", "rules": []}]})

    assert str(error) == _NOT_A_DOCUMENT


def test_an_empty_root_means_everyone() -> None:
    """The asymmetry with the case above is the point: an unfiltered list is VISIBLY unfiltered."""
    segment = to_segment(_decoded({"v": 1, "match": "all", "rules": []}))

    compiled = compile_segment(segment, now=_NOW, capabilities=_CAPABILITIES)
    assert is_ok(compiled), compiled
    assert compiled.value.predicate is None


# ---------------------------------------------------------------------------
# the version
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "version",
    [
        pytest.param(2, id="ahead"),
        pytest.param(0, id="behind"),
        pytest.param(1.5, id="not-a-whole-number"),
        pytest.param("one", id="not-a-number"),
    ],
)
def test_a_version_this_module_does_not_speak_is_refused(version: object) -> None:
    assert _refusal({"v": version, "match": "all", "rules": []}) == _UNKNOWN_VERSION


def test_a_document_with_no_version_is_refused_as_a_version_it_does_not_speak() -> None:
    """No default: "no version" and "version 1" must not be the same document forever."""
    assert _refusal({"match": "all", "rules": []}) == _UNKNOWN_VERSION


# ---------------------------------------------------------------------------
# the wire vocabulary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("op", list(SegmentOp), ids=[op.value for op in SegmentOp])
def test_every_operator_s_wire_spelling_survives_the_decode(op: SegmentOp) -> None:
    """The enum's VALUES are the contract; a member renamed without its value is a broken SPA."""
    model = _decoded({"v": 1, "match": "all", "rules": [{"field": "joined_at", "op": op.value}]})

    rule = model.rules[0]
    assert isinstance(rule, RuleModel)
    assert rule.op is op


@pytest.mark.parametrize("mode", list(MatchMode), ids=[mode.value for mode in MatchMode])
def test_every_match_mode_s_wire_spelling_survives_the_decode(mode: MatchMode) -> None:
    model = _decoded({"v": 1, "match": mode.value, "rules": []})

    assert model.match is mode


@pytest.mark.parametrize(
    "op",
    [pytest.param("contains", id="a-substring-probe"), pytest.param("EQ", id="wrong-case")],
)
def test_an_operator_outside_the_closed_set_is_refused(op: str) -> None:
    document = {"v": 1, "match": "all", "rules": [{"field": "joined_at", "op": op}]}

    assert _refusal(document) == _NOT_A_DOCUMENT


@pytest.mark.parametrize(
    "value",
    [
        pytest.param({"nested": 1}, id="an-object"),
        pytest.param([[1, 2]], id="a-nested-list"),
        pytest.param([{"a": 1}], id="a-list-of-objects"),
        pytest.param("z" * 65, id="a-string-past-the-cap"),
    ],
)
def test_a_value_that_is_not_a_bounded_scalar_or_a_flat_list_is_refused(value: object) -> None:
    """Refused at the schema, so the compiler never has to have an opinion about a dict."""
    document = {
        "v": 1,
        "match": "all",
        "rules": [{"field": "ui_language", "op": "in", "value": value}],
    }

    assert _refusal(document) == _NOT_A_DOCUMENT


def test_a_field_key_past_the_cap_is_refused() -> None:
    """An unknown key is the one caller string the compiler puts in a context. Bound it here."""
    document = {"v": 1, "match": "all", "rules": [{"field": "z" * 65, "op": "eq", "value": 1}]}

    assert _refusal(document) == _NOT_A_DOCUMENT


# ---------------------------------------------------------------------------
# lowering
# ---------------------------------------------------------------------------
def test_an_instant_is_lowered_to_an_aware_datetime() -> None:
    """The compiler refuses a string outright, so the text must become a ``datetime`` here."""
    segment = to_segment(
        _decoded(
            {
                "v": 1,
                "match": "all",
                "rules": [{"field": "joined_at", "op": "gte", "value": "2026-06-01T00:00:00Z"}],
            }
        )
    )

    rule = segment.root.rules[0]
    assert isinstance(rule, SegmentRule)
    assert rule.value == datetime(2026, 6, 1, tzinfo=UTC)


def test_both_bounds_of_a_between_are_lowered() -> None:
    segment = to_segment(
        _decoded(
            {
                "v": 1,
                "match": "all",
                "rules": [
                    {
                        "field": "joined_at",
                        "op": "between",
                        "value": ["2026-06-01T00:00:00Z", "2026-07-01T00:00:00+00:00"],
                    }
                ],
            }
        )
    )

    rule = segment.root.rules[0]
    assert isinstance(rule, SegmentRule)
    assert rule.value == [datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        pytest.param("last tuesday", "this operator needs an instant", id="not-a-date"),
        pytest.param("2026-06-01T00:00:00", "an instant must carry a UTC offset", id="naive"),
    ],
)
def test_an_instant_this_layer_cannot_parse_is_left_for_the_compiler_to_refuse(
    value: str, message: str
) -> None:
    """One refusal, in the module that owns the rule — not a second copy of it at the boundary."""
    segment = to_segment(
        _decoded(
            {"v": 1, "match": "all", "rules": [{"field": "joined_at", "op": "gte", "value": value}]}
        )
    )

    compiled = compile_segment(segment, now=_NOW, capabilities=_CAPABILITIES)
    assert is_err(compiled)
    assert str(compiled.error) == message
    assert compiled.error.context["field"] == "joined_at"


def test_a_value_on_a_field_that_is_not_an_instant_is_carried_through_untouched() -> None:
    segment = to_segment(
        _decoded(
            {
                "v": 1,
                "match": "all",
                "rules": [
                    {"field": "ui_language", "op": "in", "value": ["ru", "en"]},
                    {"field": "order_count", "op": "gte", "value": 3},
                    {"field": "is_blocked", "op": "is_true"},
                ],
            }
        )
    )

    assert [rule.value for rule in segment.root.rules if isinstance(rule, SegmentRule)] == [
        ["ru", "en"],
        3,
        None,
    ]


def test_an_unknown_field_falls_through_to_the_compiler_by_name() -> None:
    """The registry is the allowlist, and this module does not keep a second copy of it."""
    segment = to_segment(
        _decoded(
            {"v": 1, "match": "all", "rules": [{"field": "phone_e164", "op": "eq", "value": "x"}]}
        )
    )

    compiled = compile_segment(segment, now=_NOW, capabilities=_CAPABILITIES)
    assert is_err(compiled)
    assert str(compiled.error) == "unknown field"
    assert compiled.error.context["field"] == "phone_e164"


def test_a_nested_group_is_lowered_with_its_shape_intact() -> None:
    segment = to_segment(_decoded(_BLUEPRINT))

    nested = segment.root.rules[2]
    assert isinstance(nested, SegmentGroup)
    assert nested.match is MatchMode.ANY
    assert len(nested.rules) == 2


# ---------------------------------------------------------------------------
# sorting
# ---------------------------------------------------------------------------
def test_a_document_with_no_sort_takes_the_registry_s_default() -> None:
    """One name per column: the default is ``joined_at``, which IS ``users.created_at``."""
    segment = to_segment(_decoded({"v": 1, "match": "all", "rules": []}))

    assert segment.sort == DEFAULT_SORT


def test_a_sort_with_no_direction_reads_newest_first() -> None:
    model = _decoded({"v": 1, "match": "all", "rules": [], "sort": {"key": "order_count"}})

    assert model.sort == SortModel(key="order_count", dir="desc")
    assert to_segment(model).sort.direction == DEFAULT_SORT.direction


@pytest.mark.parametrize(
    "direction",
    [pytest.param("up", id="invented"), pytest.param("ASC", id="wrong-case")],
)
def test_a_sort_direction_outside_the_two_is_refused(direction: str) -> None:
    document = {"v": 1, "match": "all", "rules": [], "sort": {"key": "joined_at", "dir": direction}}

    assert _refusal(document) == _NOT_A_DOCUMENT


def test_an_unsortable_key_is_the_compiler_s_refusal_not_this_module_s() -> None:
    """``SORT_KEYS`` is derived from the registry; a second list here would drift from it."""
    segment = to_segment(
        _decoded({"v": 1, "match": "all", "rules": [], "sort": {"key": "last_activity_at"}})
    )

    compiled = compile_segment(segment, now=_NOW, capabilities=_CAPABILITIES)
    assert is_err(compiled)
    assert str(compiled.error) == "unknown sort key"
