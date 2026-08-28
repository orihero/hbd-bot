"""Re-prompting. Parse failures earn another ask; transport failures do not."""

from __future__ import annotations

from pydantic import BaseModel, Field

from hbd.contracts import Err, LlmRequest, Ok, Result, err, ok
from hbd.errors import ProviderRateLimitedError, ProviderRejectedContentError
from hbd.providers.llm.retry import generate_with_retry
from tests.test_providers_llm.conftest import StubLlmProvider

REQUEST = LlmRequest(system_prompt="write json", user_prompt="go")


class Sample(BaseModel):
    name: str = Field(min_length=1)


async def run(
    responses: list[Result[Sample] | str], *, max_attempts: int = 2
) -> tuple[Ok[Sample] | Err, StubLlmProvider]:
    provider = StubLlmProvider(responses)
    result = await generate_with_retry(
        provider, REQUEST, Sample, timeout_s=1.0, max_attempts=max_attempts
    )
    return result, provider


async def test_a_first_attempt_that_parses_is_not_retried() -> None:
    # Arrange / Act
    result, provider = await run(['{"name": "Alyona"}'])

    # Assert
    assert isinstance(result, Ok)
    assert provider.call_count == 1


async def test_a_parse_failure_is_reprompted_and_the_second_answer_is_accepted() -> None:
    result, provider = await run(["thinking out loud, no json", '{"name": "Alyona"}'])

    assert isinstance(result, Ok)
    assert provider.call_count == 2


async def test_the_reprompt_tells_the_model_what_went_wrong() -> None:
    _, provider = await run(["nope", '{"name": "Alyona"}'])

    first, second = provider.requests
    assert second.system_prompt.startswith(first.system_prompt)
    assert "one JSON object" in second.system_prompt
    assert second.user_prompt == first.user_prompt


async def test_the_original_request_is_never_mutated_by_the_reprompt() -> None:
    _, provider = await run(["nope", '{"name": "Alyona"}'])

    assert REQUEST.system_prompt == "write json"
    assert provider.requests[0].system_prompt == "write json"


async def test_attempts_are_bounded_and_the_last_error_is_returned() -> None:
    result, provider = await run(["nope", "still nope", '{"name": "Alyona"}'], max_attempts=2)

    assert isinstance(result, Err)
    assert provider.call_count == 2


async def test_more_attempts_are_used_when_configured() -> None:
    result, provider = await run(["nope", "still nope", '{"name": "Alyona"}'], max_attempts=3)

    assert isinstance(result, Ok)
    assert provider.call_count == 3


async def test_a_transport_failure_is_not_reprompted_here() -> None:
    # Backoff and jitter belong to the pipeline's ladder, not to this bound.
    result, provider = await run([err(ProviderRateLimitedError("429", provider="stub"))])

    assert isinstance(result, Err)
    assert provider.call_count == 1


async def test_a_content_refusal_is_not_reprompted() -> None:
    result, provider = await run([err(ProviderRejectedContentError("no", provider="stub"))])

    assert isinstance(result, Err)
    assert provider.call_count == 1


async def test_a_max_attempts_below_one_still_makes_a_single_call() -> None:
    result, provider = await run([ok(Sample(name="Alyona"))], max_attempts=0)

    assert isinstance(result, Ok)
    assert provider.call_count == 1
