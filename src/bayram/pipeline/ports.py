"""Seams the pipeline needs that are not vendor adapters.

Everything here is a *port*: the orchestrator depends on the protocol, never on a concrete
module. Two of them (``ContentWriter``, ``Moderator``) ship with a working LLM-backed
implementation in this package; ``NameSimilarity`` deliberately does not, because
normalising two Uzbek strings and scoring them is the name subsystem's job and duplicating
it here would guarantee the two drift apart.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

from bayram.contracts import Brief, LyricDraft, Result, SpokenScript, VoiceDescriptor

__all__ = [
    "Clock",
    "Sleeper",
    "NameSimilarity",
    "ContentWriter",
    "Moderator",
]

#: Supplies "now". Injected so timings and state transitions are testable.
type Clock = Callable[[], datetime]

#: Backoff sleep. Injected so a retry test does not actually wait five seconds.
type Sleeper = Callable[[float], Awaitable[None]]


@runtime_checkable
class NameSimilarity(Protocol):
    """Scores an STT fragment against the intended name, 0.0 to 1.0.

    Implemented by the name subsystem: it owns apostrophe canonicalisation, script
    unification and case folding, so both arguments arrive here as raw text and the
    comparison is entirely that module's business.
    """

    def __call__(self, heard: str, expected: str) -> float: ...


@runtime_checkable
class ContentWriter(Protocol):
    """Turns a brief into the words: one lyric, N in-character spoken greetings."""

    async def write_lyrics(self, brief: Brief) -> Result[LyricDraft]: ...

    async def write_scripts(
        self,
        brief: Brief,
        lyrics: LyricDraft,
        *,
        voices: tuple[VoiceDescriptor, ...],
        name_submitted: str,
        target_duration_s: float,
    ) -> Result[tuple[SpokenScript, ...]]: ...


@runtime_checkable
class Moderator(Protocol):
    """Policy gate over the free-text the user typed. ``Ok(None)`` means allowed."""

    async def review(self, brief: Brief) -> Result[None]: ...
