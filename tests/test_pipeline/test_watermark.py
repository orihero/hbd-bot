"""THE LEAK GUARD: the watermark reaches the rendered artefacts and never the lyric.

This is the point of the whole watermark package, and it is the one property a review
cannot hold on its own. The watermark and the lyric live two lines apart in
``pipeline.assets`` — the draft is right there when the sheet is typeset, and composing the
invitation into it is a one-character change that goes green everywhere. The consequence is
not a cosmetic defect: the composition plan is built from ``LyricDraft.sections``, so a
watermark inside the draft is posted to the music vendor, set to music, and sung. A customer
hears a voice singing "generate yours at at hbduzbot" in the middle of a birthday song, and
there is no way to un-send it.

So this module builds a real ``Kit`` through :func:`~hbd.pipeline.assembly.assemble_kit`
with a fake post-processor and asserts both halves at once: the four carriers carry it, and
the draft, the plan and the vendor payload do not.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from hbd.config import Settings
from hbd.contracts import AssetKind, CostSource, Kit, LyricDraft, RenderedAudio, err
from hbd.errors import StorageError
from hbd.pipeline import assets
from hbd.pipeline.assembly import assemble_kit
from hbd.pipeline.greetings import GreetingBatch
from hbd.pipeline.name_stage import SongRender
from hbd.pipeline.outcome import RunLedger
from hbd.pipeline.plan_builder import build_composition_plan
from hbd.watermark import (
    SHEET_RULE,
    WATERMARK_HANDLE,
    audio_tags,
    contains_watermark,
)
from tests.conftest import make_brief, make_lyrics, make_plan
from tests.test_pipeline.conftest import FakeAudioPostProcessor, value_of

SONG = RenderedAudio(
    data=b"song-bytes",
    mime="audio/mpeg",
    duration_s=118.0,
    cost_usd=0.3,
    cost_source=CostSource.DERIVED,
)


async def build_kit(
    *, workspace: Path, settings: Settings, post: FakeAudioPostProcessor, lyrics: LyricDraft
) -> Kit:
    """One kit, assembled exactly as the orchestrator assembles one. No greetings needed.

    ``greetings_per_kit=0`` is a shipped product setting, so an empty batch is a complete
    kit rather than a shortcut taken for the test's convenience.
    """
    return value_of(
        await assemble_kit(
            order_id=uuid4(),
            lyrics=lyrics,
            song=SongRender(audio=SONG, plan=make_plan()),
            greetings=GreetingBatch(),
            workspace_root=workspace,
            post=post,
            settings=settings,
            ledger=RunLedger(),
        )
    )


# ---------------------------------------------------------------------------
# the half that must NOT carry it
# ---------------------------------------------------------------------------
async def test_the_lyric_draft_comes_out_of_assembly_exactly_as_it_went_in(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    lyrics = make_lyrics()

    # Act
    kit = await build_kit(
        workspace=tmp_path, settings=settings, post=FakeAudioPostProcessor(), lyrics=lyrics
    )

    # Assert
    assert kit.lyrics == lyrics


async def test_no_section_line_of_the_shipped_lyric_carries_the_watermark(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    lyrics = make_lyrics()

    # Act
    kit = await build_kit(
        workspace=tmp_path, settings=settings, post=FakeAudioPostProcessor(), lyrics=lyrics
    )

    # Assert
    assert not contains_watermark(kit.lyrics.as_plain_text())
    assert not contains_watermark(kit.lyrics.title)
    for section in kit.lyrics.sections:
        for line in section.lines:
            assert not contains_watermark(line)


def test_the_composition_plan_the_vendor_is_sent_carries_no_watermark(
    settings: Settings,
) -> None:
    # Arrange: the plan's chunk texts ARE the payload posted to the music provider, so this
    # is the exact string that would be sung.
    lyrics = make_lyrics()

    # Act
    plan = value_of(
        build_composition_plan(
            lyrics, brief=make_brief(), candidate=None, settings=settings, seed=42
        )
    )

    # Assert
    for chunk in plan.chunks:
        assert not contains_watermark(chunk.text)
    assert WATERMARK_HANDLE not in "".join(chunk.text for chunk in plan.chunks)


# ---------------------------------------------------------------------------
# the half that MUST carry it
# ---------------------------------------------------------------------------
async def test_the_archived_lyric_sheet_carries_the_rule_top_and_bottom(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    lyrics = make_lyrics()

    # Act
    kit = await build_kit(
        workspace=tmp_path, settings=settings, post=FakeAudioPostProcessor(), lyrics=lyrics
    )
    sheet = kit.lyric_sheet.path.read_text(encoding="utf-8")

    # Assert
    assert sheet.startswith(SHEET_RULE)
    assert sheet.endswith(SHEET_RULE)


async def test_the_song_is_handed_the_four_tags_with_our_handle_as_the_artist(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()
    lyrics = make_lyrics()

    # Act
    await build_kit(workspace=tmp_path, settings=settings, post=post, lyrics=lyrics)
    _destination, _cover, tags = post.branded[0]

    # Assert
    assert [key for key, _ in tags] == ["title", "artist", "album", "comment"]
    assert dict(tags)["artist"] == WATERMARK_HANDLE
    assert contains_watermark(dict(tags)["comment"])
    assert tags == audio_tags(title=lyrics.title)


async def test_the_kit_carries_a_cover_and_the_song_was_branded_with_it(
    tmp_path: Path, settings: Settings
) -> None:
    # Arrange
    post = FakeAudioPostProcessor()

    # Act
    kit = await build_kit(workspace=tmp_path, settings=settings, post=post, lyrics=make_lyrics())

    # Assert
    assert kit.cover is not None
    assert kit.cover.kind is AssetKind.COVER
    assert post.branded[0][1] == kit.cover.path
    assert kit.cover in kit.all_assets


async def test_a_kit_whose_cover_could_not_be_drawn_still_carries_the_tags(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: substitute the drawing step, because a real failure needs an unwritable
    # workspace and that would take the song down with it — which is precisely the coupling
    # this test denies. A missing picture must not be a missing watermark: three of the
    # four tags are the watermark and they are written either way.
    post = FakeAudioPostProcessor()
    monkeypatch.setattr(
        assets, "render_cover", lambda destination, **_: err(StorageError("no cover today"))
    )

    # Act
    kit = await build_kit(workspace=tmp_path, settings=settings, post=post, lyrics=make_lyrics())
    _destination, cover, tags = post.branded[0]

    # Assert
    assert kit.cover is None
    assert cover is None
    assert dict(tags)["artist"] == WATERMARK_HANDLE
    assert kit.lyric_sheet.path.read_text(encoding="utf-8").startswith(SHEET_RULE)
