"""Parsing ffmpeg's loudnorm measurement pass.

Pass one of a two-pass loudnorm prints a small JSON object to stderr, buried in a normal
ffmpeg log. That object is external data we did not construct, so it is extracted, parsed
and SHAPE-validated before a single value is used — never index-and-cast.

The measurement can legitimately be unusable: a fully silent or near-silent input measures
``-inf`` LUFS, and feeding ``measured_I=-inf`` back to ffmpeg fails the second pass. That
case is detected here (:attr:`LoudnormMeasurement.is_usable`) and the caller falls back to
single-pass dynamic normalisation instead of erroring.
"""

from __future__ import annotations

import json
import math
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from bayram.audio.runner import tail
from bayram.contracts import Result, err, ok
from bayram.errors import AudioProcessingError
from bayram.logging import get_logger

__all__ = ["LoudnormMeasurement", "parse_loudnorm_report", "extract_last_json_object"]

_LOG = get_logger(__name__)

#: loudnorm prints a FLAT object whose values are all quoted strings, so locating it by
#: its outermost braces is sufficient — there is no nesting to confuse the scan.
_OPEN: Final[str] = "{"
_CLOSE: Final[str] = "}"


class LoudnormMeasurement(BaseModel):
    """The five fields pass two needs. ffmpeg emits more; extra keys are ignored on
    purpose so a new ffmpeg release cannot break a render."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    input_i: float
    input_tp: float
    input_lra: float
    input_thresh: float
    target_offset: float

    @property
    def is_usable(self) -> bool:
        """False when any measurement is ``inf``/``nan`` — i.e. the input was silence."""
        return all(
            math.isfinite(value)
            for value in (
                self.input_i,
                self.input_tp,
                self.input_lra,
                self.input_thresh,
                self.target_offset,
            )
        )


def extract_last_json_object(text: str) -> str | None:
    """Return the last ``{...}`` span in ``text``, or ``None`` if there is not one."""
    close = text.rfind(_CLOSE)
    if close == -1:
        return None
    open_ = text.rfind(_OPEN, 0, close)
    if open_ == -1:
        return None
    return text[open_ : close + 1]


def _load_object(payload: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(payload)
    except (ValueError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def parse_loudnorm_report(stderr: str) -> Result[LoudnormMeasurement]:
    """Pull the measurement out of a loudnorm pass-one stderr stream.

    Never raises; a malformed or absent report becomes an ``Err`` carrying the stderr
    tail so the failure is diagnosable from the log alone.
    """
    payload = extract_last_json_object(stderr)
    if payload is None:
        return err(_failure("loudnorm pass 1 printed no JSON object", stderr))

    loaded = _load_object(payload)
    if loaded is None:
        return err(_failure("loudnorm pass 1 printed a JSON object that would not parse", stderr))

    try:
        measurement = LoudnormMeasurement.model_validate(loaded)
    except ValidationError as exc:
        detail = f"loudnorm report failed shape validation: {exc.error_count()} issue(s)"
        return err(_failure(detail, stderr, cause=exc))

    if not measurement.is_usable:
        _LOG.warning(
            "audio.loudnorm.measurement_not_finite",
            extra={"input_i": measurement.input_i, "input_tp": measurement.input_tp},
        )
    return ok(measurement)


def _failure(message: str, stderr: str, *, cause: Exception | None = None) -> AudioProcessingError:
    return AudioProcessingError(
        message,
        context={"stderr": tail(stderr)},
        cause=cause,
    )
