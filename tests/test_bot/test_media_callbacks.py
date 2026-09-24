"""``MediaCB`` (IMAGE_VIDEO_SPEC §2 "Callbacks"): a job id in 22 characters, inside 64 bytes."""

from __future__ import annotations

from uuid import uuid4

import pytest

from bayram.bot.callbacks import MediaAction, MediaCB, pack_job_ref, read_job_ref


def test_a_job_ref_round_trips_in_22_characters() -> None:
    job_id = uuid4()
    ref = pack_job_ref(job_id)
    assert len(ref) == 22
    assert read_job_ref(ref) == job_id


@pytest.mark.parametrize("value", ["", "short", "!" * 22, "a" * 23])
def test_a_malformed_ref_reads_as_absent(value: str) -> None:
    assert read_job_ref(value) is None


@pytest.mark.parametrize("action", list(MediaAction))
def test_every_media_payload_fits_telegrams_64_bytes(action: MediaAction) -> None:
    packed = MediaCB(action=action, job=pack_job_ref(uuid4())).pack()
    assert len(packed.encode()) <= 64
    assert MediaCB.unpack(packed).action is action
