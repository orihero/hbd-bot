"""A programmable :class:`MediaModerator` for tests and offline runs (IMAGE_VIDEO_SPEC §6.2, §10).

Allows everything unless told otherwise. A test scripts a decision per subject
(``decisions["output_image"] = BLOCK``), a transport failure for every call (``failure``), and
reads back what was screened (``calls``) — which is how "the collage is screened, not only the
photos" and "the output is screened before delivery" are asserted without a guard model.

Boot refuses ``media_moderator="fake"`` with any SKU offered unless ``use_fake_providers``
(§4.5), so this never screens a real customer's request.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from bayram.contracts import Result, err, ok
from bayram.db.enums import MediaScreenDecision
from bayram.errors import BayramError
from bayram.moderation.contracts import (
    CategoryCode,
    ImageItem,
    MediaVerdict,
    TextItem,
    VerdictSubject,
    VoiceTranscript,
)

__all__ = ["FakeModerator", "FakeScreenCall", "FAKE_MODERATOR_NAME"]

FAKE_MODERATOR_NAME: Final[str] = "fake_moderator"


@dataclass(frozen=True, slots=True)
class FakeScreenCall:
    """One screen call as the fake saw it: the subjects, never the content."""

    kind: str
    subjects: tuple[VerdictSubject, ...]
    item_ids: tuple[str, ...]


@dataclass(slots=True)
class FakeModerator:
    """Deterministic and programmable. Configure the knobs; read ``calls`` afterwards."""

    name: str = FAKE_MODERATOR_NAME
    #: Decision by subject; a subject not listed is allowed.
    decisions: dict[str, MediaScreenDecision] = field(default_factory=dict)
    #: Category codes reported with a non-allow decision, by subject.
    categories: dict[str, tuple[CategoryCode, ...]] = field(default_factory=dict)
    #: Decision by item id (``output-1``), consulted before :attr:`decisions` — how a test
    #: blocks ONE of two images that share a subject.
    item_decisions: dict[str, MediaScreenDecision] = field(default_factory=dict)
    #: Category codes by item id, for :attr:`item_decisions`.
    item_categories: dict[str, tuple[CategoryCode, ...]] = field(default_factory=dict)
    #: When set, every call answers ``Err(failure)`` — a guard that did not answer.
    failure: BayramError | None = None
    #: Failures handed out by the next calls, in order, before :attr:`failure` is consulted.
    failures_once: list[BayramError] = field(default_factory=list)
    transcript: VoiceTranscript = field(
        default_factory=lambda: VoiceTranscript(text="", language="en")
    )
    calls: list[FakeScreenCall] = field(default_factory=list)

    def _verdict(
        self,
        subjects: Sequence[VerdictSubject],
        *,
        policy: str,
        item_ids: Sequence[str] = (),
    ) -> MediaVerdict:
        worst: tuple[MediaScreenDecision, VerdictSubject, tuple[CategoryCode, ...]] | None = None
        order = (
            MediaScreenDecision.BLOCK,
            MediaScreenDecision.REVIEW,
            MediaScreenDecision.UNAVAILABLE,
        )
        ids = list(item_ids) or [""] * len(subjects)
        for subject, item_id in zip(subjects, ids, strict=False):
            if item_id in self.item_decisions:
                decision = self.item_decisions[item_id]
                codes = self.item_categories.get(item_id, ())
            else:
                decision = self.decisions.get(subject, MediaScreenDecision.ALLOW)
                codes = self.categories.get(subject, ())
            if decision is MediaScreenDecision.ALLOW:
                continue
            if worst is None or order.index(decision) < order.index(worst[0]):
                worst = (decision, subject, codes)
        if worst is None:
            subject = subjects[0] if subjects else "prompt"
            return MediaVerdict(
                decision=MediaScreenDecision.ALLOW,
                categories=(),
                scores={},
                subject=subject,
                model_id=self.name,
                policy_version=policy,
            )
        decision, subject, codes = worst
        return MediaVerdict(
            decision=decision,
            categories=codes,
            scores=dict.fromkeys(codes, 0.99),
            subject=subject,
            model_id=self.name,
            policy_version=policy,
        )

    def _failure(self) -> BayramError | None:
        if self.failures_once:
            return self.failures_once.pop(0)
        return self.failure

    async def screen_text(self, items: Sequence[TextItem], *, policy: str) -> Result[MediaVerdict]:
        subjects = tuple(item.subject for item in items)
        self.calls.append(
            FakeScreenCall(
                kind="text", subjects=subjects, item_ids=tuple(item.id for item in items)
            )
        )
        failure = self._failure()
        if failure is not None:
            return err(failure)
        return ok(self._verdict(subjects, policy=policy, item_ids=[item.id for item in items]))

    async def screen_images(
        self, items: Sequence[ImageItem], *, policy: str
    ) -> Result[MediaVerdict]:
        subjects = tuple(item.subject for item in items)
        self.calls.append(
            FakeScreenCall(
                kind="image", subjects=subjects, item_ids=tuple(item.id for item in items)
            )
        )
        failure = self._failure()
        if failure is not None:
            return err(failure)
        return ok(self._verdict(subjects, policy=policy, item_ids=[item.id for item in items]))

    async def transcribe(self, audio: Path, *, language_hint: str) -> Result[VoiceTranscript]:
        self.calls.append(FakeScreenCall(kind="transcribe", subjects=("transcript",), item_ids=()))
        failure = self._failure()
        if failure is not None:
            return err(failure)
        return ok(self.transcript)

    def subjects_screened(self, kind: str) -> tuple[VerdictSubject, ...]:
        """Every subject passed to one kind of call, in order."""
        return tuple(
            subject for call in self.calls if call.kind == kind for subject in call.subjects
        )
