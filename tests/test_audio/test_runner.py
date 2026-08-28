"""The subprocess seam.

These use the Python interpreter as a stand-in child process rather than ffmpeg. That is
not a mock: it is a real fork/exec whose exit code, stderr and runtime we control exactly,
which is the only way to assert on the hang and non-zero-exit paths deterministically.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hbd.audio.constants import MAX_CAPTURED_STDERR_CHARS
from hbd.audio.runner import run_command, tail
from hbd.contracts import is_err, is_ok
from hbd.errors import ErrorCode
from tests.test_audio.conftest import ABSENT_BINARY

TIMEOUT_S = 30.0


def python_command(script: str) -> tuple[str, ...]:
    return (sys.executable, "-c", script)


# ---------------------------------------------------------------------------
# tail
# ---------------------------------------------------------------------------
def test_tail_keeps_short_text_whole() -> None:
    assert tail("short") == "short"


def test_tail_keeps_the_end_because_ffmpeg_reports_failures_last() -> None:
    text = "x" * 100 + "THE ACTUAL ERROR"

    trimmed = tail(text, limit=20)

    assert trimmed.endswith("THE ACTUAL ERROR")
    assert "truncated" in trimmed


def test_tail_bounds_the_captured_stderr() -> None:
    trimmed = tail("y" * (MAX_CAPTURED_STDERR_CHARS * 3))

    # Assert: bounded, allowing for the truncation marker itself.
    assert len(trimmed) < MAX_CAPTURED_STDERR_CHARS * 2


# ---------------------------------------------------------------------------
# success
# ---------------------------------------------------------------------------
async def test_captures_stdout_and_stderr_of_a_successful_run() -> None:
    # Arrange
    script = "import sys; sys.stdout.write('OUT'); sys.stderr.write('ERR')"

    # Act
    result = await run_command(python_command(script), operation="test.ok", timeout_s=TIMEOUT_S)

    # Assert
    assert is_ok(result)
    assert result.value.stdout == "OUT"
    assert result.value.stderr == "ERR"
    assert result.value.returncode == 0


async def test_undecodable_output_never_explodes() -> None:
    # Arrange: ffmpeg emits whatever a file's metadata contained, valid UTF-8 or not.
    script = "import sys; sys.stdout.buffer.write(b'\\xff\\xfe bad bytes')"

    result = await run_command(python_command(script), operation="test.bytes", timeout_s=TIMEOUT_S)

    assert is_ok(result)
    assert "bad bytes" in result.value.stdout


# ---------------------------------------------------------------------------
# failure
# ---------------------------------------------------------------------------
async def test_a_non_zero_exit_becomes_an_error_carrying_the_stderr() -> None:
    # Arrange
    script = "import sys; sys.stderr.write('Invalid argument: -af'); sys.exit(3)"

    # Act
    result = await run_command(python_command(script), operation="test.fail", timeout_s=TIMEOUT_S)

    # Assert
    assert is_err(result)
    assert result.error.error_code is ErrorCode.AUDIO_FAILED
    assert result.error.context["returncode"] == 3
    assert "Invalid argument" in str(result.error.context["stderr"])


async def test_the_error_names_which_pass_failed() -> None:
    result = await run_command(
        python_command("raise SystemExit(1)"), operation="loudnorm.apply", timeout_s=TIMEOUT_S
    )

    assert is_err(result)
    assert result.error.context["operation"] == "loudnorm.apply"
    assert "loudnorm.apply" in result.error.operator_message


async def test_a_hang_is_killed_and_reported_rather_than_waited_on_forever() -> None:
    # Arrange: a child that would outlive the whole test session.
    script = "import time; time.sleep(600)"

    # Act
    result = await run_command(python_command(script), operation="test.hang", timeout_s=0.5)

    # Assert
    assert is_err(result)
    assert "exceeding 0.5s" in result.error.operator_message


async def test_a_missing_binary_is_terminal_not_retryable() -> None:
    # Arrange: retrying a binary that is not installed can never succeed.
    result = await run_command((ABSENT_BINARY,), operation="test.absent", timeout_s=TIMEOUT_S)

    # Assert
    assert is_err(result)
    assert result.error.is_retryable is False
    assert result.error.is_terminal is True


async def test_a_missing_binary_points_at_the_startup_check() -> None:
    result = await run_command((ABSENT_BINARY,), operation="test.absent", timeout_s=TIMEOUT_S)

    assert is_err(result)
    assert "ensure_ffmpeg_available" in result.error.operator_message


async def test_a_timeout_is_retryable_because_the_next_attempt_may_be_luckier() -> None:
    result = await run_command(
        python_command("import time; time.sleep(600)"), operation="test.hang", timeout_s=0.5
    )

    assert is_err(result)
    assert result.error.is_retryable is True


async def test_a_binary_the_os_refuses_to_start_is_an_error_not_a_crash(tmp_path: Path) -> None:
    # Arrange: a file that exists but carries no execute bit — a real deployment mistake
    # (a binary restored from an archive that dropped its permissions).
    not_executable = tmp_path / "ffmpeg"
    not_executable.write_text("#!/bin/sh\nexit 0\n")

    # Act
    result = await run_command(
        (str(not_executable),), operation="test.permission", timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_err(result)
    assert "refused to start" in result.error.operator_message
