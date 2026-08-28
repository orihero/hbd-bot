"""The boot-time capability check.

The whole value of this module is that it fails at start rather than on a paying customer's
order, so the tests assert on WHEN it raises and on whether the message tells an operator
what to actually do.

The "ffmpeg built without libopus" case is exercised with a real executable script placed
on a temporary PATH. That is a filesystem stand-in, not a mock of ffmpeg's behaviour: the
code under test still forks, execs and parses genuine output.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from hbd.audio.startup import ensure_ffmpeg_available, missing_encoders
from hbd.errors import ConfigError, ErrorCode
from tests.test_audio.conftest import ABSENT_BINARY, FFMPEG_BINARY, FFPROBE_BINARY

requires_posix = pytest.mark.skipif(
    sys.platform.startswith("win"), reason="uses an executable shell script as a stand-in binary"
)

ENCODER_TABLE_WITH_OPUS = """Encoders:
 A..... aac                  AAC (Advanced Audio Coding)
 A..... libmp3lame           libmp3lame MP3
 A..... libopus              libopus Opus
"""
ENCODER_TABLE_WITHOUT_OPUS = """Encoders:
 A..... aac                  AAC (Advanced Audio Coding)
 A..... libmp3lame           libmp3lame MP3
"""


def install_fake_ffmpeg(
    directory: Path, monkeypatch: pytest.MonkeyPatch, *, stdout: str, exit_code: int = 0
) -> None:
    """Put a real, executable stand-in ``ffmpeg``/``ffprobe`` FIRST on PATH.

    Prepended rather than replacing PATH outright, so the script's own ``cat`` still
    resolves — an empty PATH would make every fake silently print nothing.
    """
    for name in ("ffmpeg", "ffprobe"):
        script = directory / name
        script.write_text(f"#!/bin/sh\ncat <<'TABLE'\n{stdout}TABLE\nexit {exit_code}\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")


# ---------------------------------------------------------------------------
# missing_encoders — pure
# ---------------------------------------------------------------------------
def test_reports_nothing_missing_when_the_table_lists_every_required_encoder() -> None:
    assert missing_encoders(ENCODER_TABLE_WITH_OPUS) == ()


def test_reports_libopus_when_the_table_does_not_list_it() -> None:
    assert missing_encoders(ENCODER_TABLE_WITHOUT_OPUS) == ("libopus",)


def test_reports_every_absent_encoder_from_an_explicit_requirement_list() -> None:
    assert missing_encoders(ENCODER_TABLE_WITH_OPUS, ("libopus", "libvorbis")) == ("libvorbis",)


# ---------------------------------------------------------------------------
# the binaries
# ---------------------------------------------------------------------------
def test_raises_config_error_when_ffmpeg_is_not_on_path() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ConfigError) as caught:
        ensure_ffmpeg_available(ffmpeg_binary=ABSENT_BINARY, ffprobe_binary=ABSENT_BINARY)

    assert caught.value.error_code is ErrorCode.CONFIG_INVALID


def test_the_message_names_the_environment_variable_an_operator_would_set() -> None:
    with pytest.raises(ConfigError) as caught:
        ensure_ffmpeg_available(ffmpeg_binary=ABSENT_BINARY, ffprobe_binary=ABSENT_BINARY)

    assert "HBD_FFMPEG_BINARY" in caught.value.operator_message


def test_a_missing_ffprobe_is_caught_too(tmp_path: Path) -> None:
    # Arrange: ffmpeg present, ffprobe not.
    if FFMPEG_BINARY is None:
        pytest.skip("needs a real ffmpeg on PATH")

    with pytest.raises(ConfigError) as caught:
        ensure_ffmpeg_available(ffmpeg_binary=FFMPEG_BINARY, ffprobe_binary=ABSENT_BINARY)

    assert "HBD_FFPROBE_BINARY" in caught.value.operator_message


def test_a_startup_failure_is_never_retryable() -> None:
    with pytest.raises(ConfigError) as caught:
        ensure_ffmpeg_available(ffmpeg_binary=ABSENT_BINARY, ffprobe_binary=ABSENT_BINARY)

    assert caught.value.is_retryable is False


# ---------------------------------------------------------------------------
# the encoder table
# ---------------------------------------------------------------------------
@requires_posix
def test_raises_when_ffmpeg_was_built_without_libopus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    install_fake_ffmpeg(tmp_path, monkeypatch, stdout=ENCODER_TABLE_WITHOUT_OPUS)

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        ensure_ffmpeg_available(ffmpeg_binary="ffmpeg", ffprobe_binary="ffprobe")

    assert "libopus" in caught.value.operator_message
    assert caught.value.context["missing_encoders"] == ["libopus"]


@requires_posix
def test_the_missing_encoder_message_explains_the_customer_impact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch, stdout=ENCODER_TABLE_WITHOUT_OPUS)

    with pytest.raises(ConfigError) as caught:
        ensure_ffmpeg_available(ffmpeg_binary="ffmpeg", ffprobe_binary="ffprobe")

    assert "sendVoice" in caught.value.operator_message


@requires_posix
def test_raises_when_the_binary_cannot_even_list_its_encoders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: on PATH, executable, and broken.
    install_fake_ffmpeg(tmp_path, monkeypatch, stdout="", exit_code=1)

    with pytest.raises(ConfigError) as caught:
        ensure_ffmpeg_available(ffmpeg_binary="ffmpeg", ffprobe_binary="ffprobe")

    assert "looks broken" in caught.value.operator_message


@requires_posix
def test_returns_quietly_when_the_toolchain_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    install_fake_ffmpeg(tmp_path, monkeypatch, stdout=ENCODER_TABLE_WITH_OPUS)

    # Act / Assert: reaching the end without a ConfigError IS the assertion.
    ensure_ffmpeg_available(ffmpeg_binary="ffmpeg", ffprobe_binary="ffprobe")


@requires_posix
def test_a_slow_binary_is_a_config_error_not_a_hung_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: a binary that never answers.
    script = tmp_path / "ffmpeg"
    script.write_text("#!/bin/sh\nsleep 30\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "ffprobe").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "ffprobe").chmod((tmp_path / "ffprobe").stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        ensure_ffmpeg_available(
            ffmpeg_binary="ffmpeg", ffprobe_binary="ffprobe", probe_timeout_s=0.5
        )

    assert "did not answer" in caught.value.operator_message


def test_the_real_toolchain_on_this_machine_passes_the_check() -> None:
    # Arrange: the check that will run at every boot, against the actual installation.
    if FFMPEG_BINARY is None or FFPROBE_BINARY is None:
        pytest.skip("no ffmpeg installed here; the fake-PATH tests cover the logic")

    ensure_ffmpeg_available(ffmpeg_binary="ffmpeg", ffprobe_binary="ffprobe")
