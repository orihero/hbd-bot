"""The tolerant parse boundary, fed real malformed model output.

Every case below has been observed in production somewhere. The bar is the same for all
of them: the boundary either recovers the object or returns a typed ``Err``. It never
raises, and it never returns unvalidated data.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from hbd.contracts import Err, Ok
from hbd.errors import ErrorCode
from hbd.providers.llm.parsing import (
    MAX_LOGGED_PAYLOAD_CHARS,
    extract_first_json_object,
    parse_model_json,
    strip_code_fences,
)

PROVIDER = "test-provider"


class Sample(BaseModel):
    """A minimal response model with one required field and one bounded number."""

    name: str = Field(min_length=1)
    lines: tuple[str, ...] = ()
    score: float = 0.0


def parse(raw: str | None, *, finish_reason: str | None = None) -> Ok[Sample] | Err:
    return parse_model_json(raw, Sample, provider=PROVIDER, finish_reason=finish_reason)


# ---------------------------------------------------------------------------
# The happy path and its near neighbours
# ---------------------------------------------------------------------------
def test_returns_validated_model_for_clean_json() -> None:
    # Arrange
    raw = '{"name": "Gʻulomjon", "lines": ["a", "b"], "score": 0.5}'

    # Act
    result = parse(raw)

    # Assert
    assert isinstance(result, Ok)
    assert result.value.name == "Gʻulomjon"
    assert result.value.lines == ("a", "b")


def test_recovers_object_from_a_json_labelled_code_fence() -> None:
    raw = '```json\n{"name": "Alyona"}\n```'

    result = parse(raw)

    assert isinstance(result, Ok)
    assert result.value.name == "Alyona"


def test_recovers_object_from_an_unlabelled_code_fence() -> None:
    raw = '```\n{"name": "Alyona"}\n```'

    result = parse(raw)

    assert isinstance(result, Ok)


def test_recovers_object_from_an_unterminated_code_fence() -> None:
    # A truncated response loses its closing fence before it loses its closing brace.
    raw = '```json\n{"name": "Alyona"}'

    result = parse(raw)

    assert isinstance(result, Ok)


def test_recovers_object_buried_in_chain_of_thought_prose() -> None:
    raw = (
        "Okay, let me think about this. The user wants a name.\n"
        "I will use the Uzbek spelling.\n\n"
        '{"name": "Gʻulomjon", "score": 0.9}\n\n'
        "Let me know if you would like another version!"
    )

    result = parse(raw)

    assert isinstance(result, Ok)
    assert result.value.score == pytest.approx(0.9)


def test_recovers_object_that_was_truncated_at_the_token_cap() -> None:
    # The closing brace never arrived: finishReason would read MAX_TOKENS.
    raw = '{"name": "Alyona", "lines": ["one", "two"]'

    result = parse(raw, finish_reason="MAX_TOKENS")

    assert isinstance(result, Ok)
    assert result.value.lines == ("one", "two")


def test_recovers_object_with_a_delimiter_swapped_from_bracket_to_brace() -> None:
    # A close-only repairer cannot fix this; the library one can.
    raw = '{"name": "Alyona", "lines": ["one", "two"}'

    result = parse(raw)

    assert isinstance(result, Ok)
    assert result.value.name == "Alyona"


def test_ignores_braces_that_live_inside_string_values() -> None:
    raw = 'preamble {"name": "a } b {", "score": 1.0} trailer'

    result = parse(raw)

    assert isinstance(result, Ok)
    assert result.value.name == "a } b {"


def test_recovers_the_first_object_when_the_model_wrapped_it_in_an_array() -> None:
    # Taking the first element is a deliberate recovery, not an accident: a model that
    # answers with a one-element list has produced the object we asked for.
    raw = '[{"name": "Alyona"}]'

    result = parse(raw)

    assert isinstance(result, Ok)
    assert result.value.name == "Alyona"


def test_accepts_a_number_the_model_wrote_as_a_string() -> None:
    raw = '{"name": "Alyona", "score": "0.75"}'

    result = parse(raw)

    assert isinstance(result, Ok)
    assert result.value.score == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Degradation: every one of these must be a typed Err, never an exception
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("label", "raw"),
    [
        ("bare json true", "true"),
        ("bare python True", "True"),
        ("bare null", "null"),
        ("bare number", "42"),
        ("prose only", "I'm sorry, I can't help with that request."),
        ("empty string", ""),
        ("whitespace only", "   \n\t  "),
        ("wrong shape", '{"title": "no name field here"}'),
        ("nested wrong type", '{"name": {"first": "Alyona"}}'),
        ("html error page", "<html><body>502 Bad Gateway</body></html>"),
    ],
)
def test_degrades_to_typed_err_instead_of_raising(label: str, raw: str) -> None:
    # Act
    result = parse(raw)

    # Assert
    assert isinstance(result, Err), label
    assert result.error.error_code is ErrorCode.PARSE_FAILED


def test_degrades_to_typed_err_when_the_model_returned_nothing_at_all() -> None:
    result = parse(None)

    assert isinstance(result, Err)
    assert "no text" in result.error.operator_message or result.error.context["parse_error"]


def test_parse_failure_is_retryable_so_a_reprompt_is_allowed() -> None:
    result = parse("not json at all")

    assert isinstance(result, Err)
    assert result.error.is_retryable is True


def test_parse_failure_logs_the_raw_payload_and_finish_reason_in_context() -> None:
    raw = "I refuse to answer in JSON."

    result = parse(raw, finish_reason="SAFETY")

    assert isinstance(result, Err)
    context = result.error.context
    assert context["raw_payload"] == raw
    assert context["finish_reason"] == "SAFETY"
    assert context["response_model"] == "Sample"
    assert context["provider"] == PROVIDER
    assert context["parse_error"]


def test_parse_failure_truncates_a_very_large_payload_in_the_error_context() -> None:
    raw = "x" * (MAX_LOGGED_PAYLOAD_CHARS * 3)

    result = parse(raw)

    assert isinstance(result, Err)
    assert len(result.error.context["raw_payload"]) == MAX_LOGGED_PAYLOAD_CHARS
    assert result.error.context["raw_payload_chars"] == len(raw)


def test_reports_which_stages_were_attempted() -> None:
    result = parse("```json\nnonsense\n```")

    assert isinstance(result, Err)
    assert result.error.context["parse_stages"]


# ---------------------------------------------------------------------------
# The individual stages
# ---------------------------------------------------------------------------
def test_strip_code_fences_returns_text_unchanged_when_no_fence_is_present() -> None:
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'


def test_strip_code_fences_returns_the_original_when_the_fence_body_is_empty() -> None:
    assert strip_code_fences("```json\n\n```") == "```json\n\n```"


def test_extract_first_json_object_returns_none_when_no_object_starts() -> None:
    assert extract_first_json_object("just prose") is None


def test_extract_first_json_object_returns_none_when_the_object_never_closes() -> None:
    assert extract_first_json_object('{"a": 1') is None


def test_extract_first_json_object_returns_only_the_first_object() -> None:
    assert extract_first_json_object('{"a": 1} {"b": 2}') == '{"a": 1}'


def test_extract_first_json_object_handles_escaped_quotes_inside_strings() -> None:
    raw = '{"a": "she said \\"} hi\\""}'

    assert extract_first_json_object(raw) == raw


def test_a_repairer_that_raises_is_a_failed_stage_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The repair library is a third party, so it is external data too.
    def explode(_text: str) -> str:
        raise RuntimeError("the repairer itself blew up")

    monkeypatch.setattr("hbd.providers.llm.parsing.repair_json", explode)

    result = parse('{"name": "Alyona"')

    assert isinstance(result, Err)


def test_strip_code_fences_leaves_a_fence_with_no_newline_after_it_alone() -> None:
    assert strip_code_fences('```json {"a": 1}') == '```json {"a": 1}'
