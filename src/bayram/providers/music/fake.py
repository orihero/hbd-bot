"""A ``MusicProvider`` that renders real, decodable silence. Tests and local dev.

The bytes are a genuine MPEG-1 Layer III stream — 32 kbps, 44.1 kHz, mono — assembled from
valid frame headers followed by zeroed side info and main data, which every decoder renders
as silence. That matters more than it sounds: the audio post stage runs ffmpeg, and a
placeholder like ``b"fake-audio"`` would sail through the provider tests and then blow up
the first time anything real touched it. This file hands the rest of the pipeline something
ffprobe will actually parse.

The fake still runs ``guard_plan``, so a plan that would be rejected by the vendor is
rejected here too, at test speed and for free.

It also **records its usage**, with ``is_fake=True`` and no cost. A demo run that wrote no
rows at all would be indistinguishable from a deployment nobody instrumented, which is the
one confusion the vendor panel exists to prevent; a demo run that wrote priced rows would
be worse still. So the calls are visible, the flag excludes them from spend, and
``vendor=FAKE`` keeps them out of every real vendor's total.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Final

from bayram.contracts import (
    CompositionPlan,
    CostSource,
    Err,
    HealthState,
    ProviderHealth,
    RenderedAudio,
    Result,
    Vendor,
    VendorOperation,
    err,
    ok,
)
from bayram.errors import BayramError, ValidationError
from bayram.providers.music.payload import guard_plan
from bayram.usage import LOGGING_USAGE_SINK, UsageSink, VendorUsage

__all__ = [
    "FakeMusicProvider",
    "FakeCall",
    "silent_mp3",
    "SILENT_MP3_FRAME",
    "MP3_FRAME_DURATION_S",
    "FAKE_PROVIDER_NAME",
]

FAKE_PROVIDER_NAME: Final[str] = "fake_music"

#: MPEG-1 Layer III, no CRC, 32 kbps, 44.1 kHz, mono, no padding.
_MP3_FRAME_HEADER: Final[bytes] = bytes((0xFF, 0xFB, 0x10, 0xC0))
#: 144 * 32000 / 44100, floored — the frame length this header declares.
_MP3_FRAME_BYTES: Final[int] = 104
#: 1152 samples per Layer III frame at 44.1 kHz.
MP3_FRAME_DURATION_S: Final[float] = 1152 / 44_100

SILENT_MP3_FRAME: Final[bytes] = _MP3_FRAME_HEADER + bytes(
    _MP3_FRAME_BYTES - len(_MP3_FRAME_HEADER)
)

#: Long enough to be a real file, short enough that a test suite stays fast.
DEFAULT_FAKE_CLIP_S: Final[float] = 2.0
DEFAULT_FAKE_COST_USD: Final[float] = 0.0

_MS_PER_S: Final[int] = 1_000


def silent_mp3(duration_s: float) -> bytes:
    """A decodable, silent MP3 of roughly ``duration_s``. Always at least one frame."""
    frames = max(1, math.ceil(max(0.0, duration_s) / MP3_FRAME_DURATION_S))
    return SILENT_MP3_FRAME * frames


class FakeCall:
    """One recorded invocation, so a test can assert what the pipeline asked for."""

    __slots__ = ("chunk_index", "idempotency_key", "operation", "plan", "source_song_id")

    def __init__(
        self,
        *,
        operation: str,
        plan: CompositionPlan,
        idempotency_key: str,
        source_song_id: str | None = None,
        chunk_index: int | None = None,
    ) -> None:
        self.operation = operation
        self.plan = plan
        self.idempotency_key = idempotency_key
        self.source_song_id = source_song_id
        self.chunk_index = chunk_index

    def __repr__(self) -> str:
        return (
            f"FakeCall(operation={self.operation!r}, chunks={len(self.plan.chunks)}, "
            f"source_song_id={self.source_song_id!r}, chunk_index={self.chunk_index!r})"
        )


class FakeMusicProvider:
    """Deterministic ``MusicProvider``. No network, no keys, no cost."""

    name: str = FAKE_PROVIDER_NAME

    def __init__(
        self,
        *,
        clip_duration_s: float = DEFAULT_FAKE_CLIP_S,
        failure: BayramError | None = None,
        health_state: HealthState = HealthState.HEALTHY,
        usage: UsageSink = LOGGING_USAGE_SINK,
    ) -> None:
        self._clip_duration_s = clip_duration_s
        self._failure = failure
        self._health_state = health_state
        self._usage = usage
        self._calls: list[FakeCall] = []
        self._render_count = 0

    @property
    def calls(self) -> tuple[FakeCall, ...]:
        """Recorded calls, oldest first. A snapshot — mutating it changes nothing."""
        return tuple(self._calls)

    async def _record(
        self,
        *,
        operation: VendorOperation,
        is_success: bool,
        plan: CompositionPlan,
        audio: RenderedAudio | None = None,
        error: BayramError | None = None,
    ) -> None:
        """Recorded, flagged fake, and never priced. No socket was opened to cost money."""
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.FAKE,
                operation=operation,
                provider=self.name,
                is_success=is_success,
                model_id=None,
                is_fake=True,
                error_code=error.error_code.value if error is not None else None,
                audio_ms=plan.total_duration_ms if audio is not None else None,
                response_bytes=len(audio.data) if audio is not None else None,
            )
        )

    def _render(self, plan: CompositionPlan) -> RenderedAudio:
        self._render_count += 1
        data = silent_mp3(self._clip_duration_s)
        frames = len(data) // len(SILENT_MP3_FRAME)
        return RenderedAudio(
            data=data,
            mime="audio/mpeg",
            duration_s=frames * MP3_FRAME_DURATION_S,
            remote_id=f"fake-song-{self._render_count:04d}",
            cost_usd=DEFAULT_FAKE_COST_USD,
            cost_source=CostSource.ESTIMATED,
        )

    async def compose(
        self, plan: CompositionPlan, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        self._calls.append(
            FakeCall(operation="compose", plan=plan, idempotency_key=idempotency_key)
        )
        guarded = guard_plan(plan)
        if isinstance(guarded, Err):
            # A plan this adapter refused never became a call, so it is not one to record —
            # the same line the live adapter draws around ``guard_plan``.
            return guarded
        if self._failure is not None:
            await self._record(
                operation=VendorOperation.MUSIC_COMPOSE,
                is_success=False,
                plan=plan,
                error=self._failure,
            )
            return err(self._failure)
        audio = self._render(plan)
        await self._record(
            operation=VendorOperation.MUSIC_COMPOSE, is_success=True, plan=plan, audio=audio
        )
        return ok(audio)

    async def inpaint(
        self,
        plan: CompositionPlan,
        *,
        source_song_id: str,
        chunk_index: int,
        idempotency_key: str,
        timeout_s: float,
    ) -> Result[RenderedAudio]:
        self._calls.append(
            FakeCall(
                operation="inpaint",
                plan=plan,
                idempotency_key=idempotency_key,
                source_song_id=source_song_id,
                chunk_index=chunk_index,
            )
        )
        if not 0 <= chunk_index < len(plan.chunks):
            return err(
                ValidationError(
                    f"chunk index {chunk_index} is out of range for a "
                    f"{len(plan.chunks)}-chunk plan",
                    context={"chunk_index": chunk_index, "chunk_count": len(plan.chunks)},
                )
            )
        guarded = guard_plan(plan)
        if isinstance(guarded, Err):
            return guarded
        if self._failure is not None:
            await self._record(
                operation=VendorOperation.MUSIC_INPAINT,
                is_success=False,
                plan=plan,
                error=self._failure,
            )
            return err(self._failure)
        audio = self._render(plan)
        await self._record(
            operation=VendorOperation.MUSIC_INPAINT, is_success=True, plan=plan, audio=audio
        )
        return ok(audio)

    async def health(self) -> Result[ProviderHealth]:
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.FAKE,
                operation=VendorOperation.HEALTH,
                provider=self.name,
                is_success=self._health_state is not HealthState.UNAVAILABLE,
                is_fake=True,
            )
        )
        return ok(
            ProviderHealth(
                name=self.name,
                state=self._health_state,
                as_of=datetime.now(tz=UTC),
                detail="fake provider; no vendor contacted",
            )
        )

    async def aclose(self) -> None:
        """Present so a caller can close either provider without a type check."""
        return
