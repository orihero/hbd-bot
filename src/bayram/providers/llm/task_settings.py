"""The slice of ``Settings`` the LLM text tasks need: seven numbers, no keys.

Frozen and narrow on purpose. A unit test builds one in a line, and a lyric writer never
holds an API key it has no use for.
"""

from __future__ import annotations

from dataclasses import dataclass

from bayram.config import Settings

__all__ = ["LlmTaskSettings"]


@dataclass(frozen=True, slots=True)
class LlmTaskSettings:
    llm_temperature: float
    llm_max_output_tokens: int
    llm_timeout_s: float
    llm_parse_max_attempts: int
    name_chunk_duration_ms: int
    greeting_min_duration_s: float
    greeting_max_duration_s: float

    @classmethod
    def from_settings(cls, settings: Settings) -> LlmTaskSettings:
        return cls(
            llm_temperature=settings.llm_temperature,
            llm_max_output_tokens=settings.llm_max_output_tokens,
            llm_timeout_s=settings.llm_timeout_s,
            llm_parse_max_attempts=settings.llm_parse_max_attempts,
            name_chunk_duration_ms=settings.name_chunk_duration_ms,
            greeting_min_duration_s=settings.greeting_min_duration_s,
            greeting_max_duration_s=settings.greeting_max_duration_s,
        )
