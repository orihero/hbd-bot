"""A song that names nobody: the pipeline with ``Brief.recipient`` set to ``None``.

The bring-your-own-lyrics path in the wizard produces orders that never collected a name —
the customer wrote the words and put whatever name they wanted inside them — and this is
the state the rest of the product had never seen. The name is not decoration here: it is a
hook section, a chunk boundary, an STT call, a candidate ladder, a line on the lyric sheet
and a word in four delivery messages. Every one of those has to become optional without
weakening the guarantee for orders that DO have a name, which is what these tests hold in
place from both sides.

The one invariant deliberately kept as an ERROR is a lyric that has a name and no hook.
That pairing is ``lyric_shape``'s to guarantee, so its absence means the guarantee was
broken upstream, and composing anyway would sing a name with no way to re-render it.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from hbd.audio.lyric_sheet import render_lyric_sheet as render_typeset_sheet
from hbd.config import Settings
from hbd.contracts import Brief, LyricSection, is_ok
from hbd.pipeline.assembly import validate_brief
from hbd.pipeline.assets import render_lyric_sheet
from hbd.pipeline.events import ProgressReporter
from hbd.pipeline.lyric_shape import build_lyric_draft
from hbd.pipeline.name_stage import render_song
from hbd.pipeline.plan_builder import build_composition_plan
from hbd.pipeline.retry import RetryPolicy
from tests.conftest import UZBEK_NAME_CANONICAL, make_brief, make_lyrics
from tests.test_pipeline.conftest import (
    RecordingSink,
    Studio,
    failure_of,
    fake_similarity,
    no_sleep,
    ticking_clock,
    value_of,
)

PASTED = (
    ("verse-1", ("Aunt Zulfiya wrote these words", "for tonight"), False),
    ("verse-2", ("and we have sung them for years",), False),
)


def nameless_brief(**overrides: object) -> Brief:
    return make_brief(recipient=None, **overrides)


def nameless_lyrics() -> object:
    return build_lyric_draft(PASTED, title="For tonight", language=make_lyrics().language)


# ---------------------------------------------------------------------------
# the lyric: no hook, and nothing woven in
# ---------------------------------------------------------------------------
def test_a_nameless_lyric_flags_no_hook_and_names_nobody() -> None:
    """The absence of a hook is the signal every later stage reads."""
    # Act
    lyrics = build_lyric_draft(PASTED, title="For tonight", language=make_lyrics().language)

    # Assert
    assert lyrics.name_display is None
    assert lyrics.name_hook_sections == ()
    assert all(section.is_name_hook is False for section in lyrics.sections)


def test_a_nameless_lyric_is_sung_exactly_as_it_was_typed() -> None:
    """Nothing is prepended. A name we invented would be a word the customer never wrote."""
    # Act
    lyrics = build_lyric_draft(PASTED, title="For tonight", language=make_lyrics().language)

    # Assert
    assert lyrics.sections[0].lines == ("Aunt Zulfiya wrote these words", "for tonight")
    assert UZBEK_NAME_CANONICAL not in lyrics.as_plain_text()


def test_a_named_lyric_still_gets_its_hook_guarantee() -> None:
    """The other half of the pair. Optional must not mean weakened."""
    # Act
    lyrics = build_lyric_draft(
        PASTED,
        title="For tonight",
        language=make_lyrics().language,
        name_display=UZBEK_NAME_CANONICAL,
    )

    # Assert
    assert len(lyrics.name_hook_sections) == 1
    assert UZBEK_NAME_CANONICAL in lyrics.as_plain_text()


# ---------------------------------------------------------------------------
# the composition plan: no name chunk, and the seconds it would have cost
# ---------------------------------------------------------------------------
def test_a_nameless_plan_carries_no_name_chunk(settings: Settings) -> None:
    # Act
    plan = value_of(
        build_composition_plan(
            build_lyric_draft(PASTED, title="For tonight", language=settings.default_ui_language),
            brief=nameless_brief(),
            candidate=None,
            settings=settings,
            seed=7,
        )
    )

    # Assert
    assert plan.name_chunk_index is None
    assert all(chunk.is_name_chunk is False for chunk in plan.chunks)


def test_a_nameless_plan_spends_the_whole_song_budget_on_the_words(
    settings: Settings,
) -> None:
    """Nothing is reserved for a chunk that does not exist.

    Reserving it anyway would hand the customer a song shorter than the one they paid for,
    with the missing seconds spent on nothing and no error to show for it.
    """
    # Act
    plan = value_of(
        build_composition_plan(
            build_lyric_draft(PASTED, title="For tonight", language=settings.default_ui_language),
            brief=nameless_brief(),
            candidate=None,
            settings=settings,
            seed=7,
        )
    )

    # Assert
    assert plan.total_duration_ms == settings.song_length_ms


def test_a_nameless_plan_is_not_stored_for_inpainting(settings: Settings) -> None:
    """Storing it buys a name re-roll that can never be asked for, at the vendor's price."""
    # Act
    plan = value_of(
        build_composition_plan(
            build_lyric_draft(PASTED, title="For tonight", language=settings.default_ui_language),
            brief=nameless_brief(),
            candidate=None,
            settings=settings,
            seed=7,
        )
    )

    # Assert
    assert plan.should_store_for_inpainting is False


def test_a_named_lyric_with_no_hook_is_still_refused(settings: Settings) -> None:
    """The invariant the missing-hook error was written for, kept intact.

    A lyric that HAS a name and no hook is broken — ``lyric_shape`` guarantees the pairing —
    and composing it would sing the name with no chunk boundary and no way to re-render it.
    """
    # Arrange — a named draft whose hook flag has been stripped, as corruption would leave it
    named = make_lyrics(
        sections=tuple(
            LyricSection(label=section.label, lines=section.lines, is_name_hook=False)
            for section in make_lyrics().sections
        )
    )
    brief = make_brief()
    assert brief.recipient is not None

    # Act
    outcome = build_composition_plan(
        named,
        brief=brief,
        candidate=brief.recipient.candidates[0],
        settings=settings,
        seed=7,
    )

    # Assert
    assert "name-hook" in failure_of(outcome).operator_message


# ---------------------------------------------------------------------------
# the name stage: one render, and the STT vendor is never called
# ---------------------------------------------------------------------------
async def test_a_nameless_order_composes_once_and_verifies_nothing(studio: Studio) -> None:
    """The acoustic loop has nothing to compare against, so it does not run.

    Letting it run would spend an STT call scoring a name the brief does not have.
    """
    # Arrange
    brief = nameless_brief()
    order_id = uuid4()
    plan = value_of(
        build_composition_plan(
            build_lyric_draft(
                PASTED, title="For tonight", language=studio.settings.default_ui_language
            ),
            brief=brief,
            candidate=None,
            settings=studio.settings,
            seed=7,
        )
    )

    # Act
    render = value_of(
        await render_song(
            plan,
            order_id=order_id,
            brief=brief,
            music=studio.music,
            stt=studio.stt,
            similarity=fake_similarity,
            settings=studio.settings,
            policy=RetryPolicy(max_attempts=2, backoff_base_s=0.01, jitter=0.0),
            sleeper=no_sleep,
            reporter=ProgressReporter(RecordingSink(), order_id=order_id, correlation_id="corr"),
            clock=ticking_clock(),
            slots=asyncio.Semaphore(2),
        )
    )

    # Assert
    assert render.renders == 1
    assert render.candidate is None
    assert render.was_checked is False
    assert render.is_verified is False
    assert render.verdicts == ()
    assert studio.stt.calls == []
    assert studio.music.inpaint_calls == []


# ---------------------------------------------------------------------------
# the deliverables
# ---------------------------------------------------------------------------
def test_the_plain_lyric_sheet_drops_the_signature_line() -> None:
    """An em dash followed by nothing is a typo on the last line of the deliverable."""
    # Act
    sheet = render_lyric_sheet(
        build_lyric_draft(PASTED, title="For tonight", language=make_lyrics().language)
    )

    # Assert
    assert not sheet.rstrip().endswith("—")
    assert "— None" not in sheet


def test_the_typeset_lyric_sheet_renders_the_words_unchanged() -> None:
    """``enforce_display_name`` builds a regex from the name; an empty one matches everywhere.

    Run against a nameless lyric without the guard, it rewrote the whole sheet into nothing.
    """
    # Act
    sheet = render_typeset_sheet(
        build_lyric_draft(PASTED, title="For tonight", language=make_lyrics().language)
    )

    # Assert
    assert "Aunt Zulfiya wrote these words" in sheet
    assert "for tonight" in sheet


# ---------------------------------------------------------------------------
# the pipeline boundary
# ---------------------------------------------------------------------------
def test_a_brief_with_no_recipient_passes_validation() -> None:
    """A missing name is a valid order here, as opposed to a name present and blank.

    The guard was written to catch a recipient whose display form is empty, which is
    corruption; "no recipient at all" is a product state and has to pass.
    """
    # Act
    outcome = validate_brief(nameless_brief())

    # Assert
    assert is_ok(outcome)
