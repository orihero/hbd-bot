"""The media policy: how a guard's output becomes OUR decision (IMAGE_VIDEO_SPEC §6.3, §6.4).

The guards answer; this module decides. Everything in it is pure and versioned by
:data:`~bayram.moderation.contracts.MEDIA_POLICY_VERSION` — a threshold or a table changed here
is a version bump, so no quote screened under the old rules can start a render (§2.3.1).

**G1 (Qwen3Guard-Gen-4B) is a generative classifier**: a ``safety`` label and category names,
no scores. ``unsafe`` → ``block``; ``controversial`` → ``review`` (a refusal before payment);
``safe`` → ``allow``. A missing or unknown label is ``unavailable`` — nothing was judged — and
**an unknown category name is a block** (``other_unsafe``): the guard flagged something our
closed table cannot name, and "we could not read the reason" is not a reason to allow it.

**G2 (ShieldGemma 2) returns a probability per policy**; the decision is per-category
thresholds below. ``scores:{}`` — or a policy we asked for missing from the answer — is
``unavailable``, never ``allow`` (the §6.3 invariant). ``sexual`` is zero-tolerance on every
image at ``media_sexual_image_block_p`` (§6.4): age cannot be judged from pixels.

**The hard rule** (§6.4): ``sexual_minors`` over its low threshold, or ``sexual`` together
with a youth signal, is a CSAM-class block. It is represented as ``block`` with
``sexual_minors`` among the categories — :func:`is_csam_class` is the one test for it — so the
stage chain can hold the bytes (§6.7), strike ×3 and suspend without a second vocabulary.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from bayram.db.enums import MediaScreenDecision
from bayram.moderation.contracts import (
    CategoryCode,
    MediaVerdict,
    VerdictSubject,
    strictest,
)

__all__ = [
    "G1_CATEGORY_TABLE",
    "G2_POLICIES",
    "G2_CUSTOM_MINOR_POLICY",
    "G2Threshold",
    "G1Label",
    "G1Reading",
    "decide_g1",
    "decide_g2",
    "parse_g1_label",
    "parse_qwen3guard_text",
    "apply_hard_rule",
    "is_csam_class",
    "combine",
    "block_verdict",
]

#: Qwen3Guard's category names (lower-cased, spaces collapsed) → our closed codes. ``none``
#: is the guard saying "no category" and maps to nothing.
G1_CATEGORY_TABLE: Final[Mapping[str, CategoryCode | None]] = {
    "none": None,
    "violent": CategoryCode.VIOLENCE,
    "violence": CategoryCode.VIOLENCE,
    "non-violent illegal acts": CategoryCode.OTHER_UNSAFE,
    "sexual content or sexual acts": CategoryCode.SEXUAL,
    "sexual content": CategoryCode.SEXUAL,
    "sexual": CategoryCode.SEXUAL,
    "pii": CategoryCode.PII,
    "personally identifiable information": CategoryCode.PII,
    "suicide & self-harm": CategoryCode.SELF_HARM,
    "suicide and self-harm": CategoryCode.SELF_HARM,
    "self-harm": CategoryCode.SELF_HARM,
    "unethical acts": CategoryCode.OTHER_UNSAFE,
    "politically sensitive topics": CategoryCode.POLITICS_OFFICIALS,
    "politically sensitive": CategoryCode.POLITICS_OFFICIALS,
    "copyright violation": CategoryCode.COPYRIGHT_CHARACTER,
    "copyright": CategoryCode.COPYRIGHT_CHARACTER,
    "jailbreak": CategoryCode.JAILBREAK,
}

#: The custom ShieldGemma policy that stands in for a minor detector (§6.4 item 2).
#: Uncalibrated: a signal, logged, not a detector.
G2_CUSTOM_MINOR_POLICY: Final[str] = "sexualised depiction of a minor"
_G2_CUSTOM_KEY: Final[str] = "custom"


@dataclass(frozen=True, slots=True)
class G2Threshold:
    """``p >= block`` blocks; ``review <= p < block`` holds for a human (after payment) or
    refuses (before it). ``review is None`` has no middle band."""

    category: CategoryCode
    block: float
    review: float | None = None


#: The policies sent with every G2 call, in the §6.5 order, and how each is judged. The
#: ``sexually_explicit`` block threshold is the setting (zero tolerance, §6.4); the others are
#: fixed here and recalibrated in M3.3 against the labelled image set.
G2_POLICIES: Final[Mapping[str, G2Threshold]] = {
    "sexually_explicit": G2Threshold(CategoryCode.SEXUAL, block=0.2),
    "dangerous": G2Threshold(CategoryCode.OTHER_UNSAFE, block=0.6, review=0.35),
    "violence": G2Threshold(CategoryCode.VIOLENCE, block=0.6, review=0.35),
    G2_CUSTOM_MINOR_POLICY: G2Threshold(CategoryCode.SEXUAL_MINORS, block=0.1),
}


# ---------------------------------------------------------------------------
# G1
# ---------------------------------------------------------------------------
class G1Label:
    """The three labels Qwen3Guard emits."""

    SAFE: Final[str] = "safe"
    CONTROVERSIAL: Final[str] = "controversial"
    UNSAFE: Final[str] = "unsafe"


_G1_DECISIONS: Final[Mapping[str, MediaScreenDecision]] = {
    G1Label.SAFE: MediaScreenDecision.ALLOW,
    G1Label.CONTROVERSIAL: MediaScreenDecision.REVIEW,
    G1Label.UNSAFE: MediaScreenDecision.BLOCK,
}


@dataclass(frozen=True, slots=True)
class G1Reading:
    """What G1 said about one item, before our policy: a label (``None`` = missing or not one
    of the three) and the raw category names."""

    safety: str | None
    categories: tuple[str, ...]


def parse_g1_label(raw: object) -> str | None:
    """``"Unsafe"``/``"unsafe "`` → ``"unsafe"``; anything else → ``None``."""
    if not isinstance(raw, str):
        return None
    label = raw.strip().lower()
    return label if label in _G1_DECISIONS else None


def _category_key(raw: str) -> str:
    return " ".join(raw.strip().lower().replace("_", " ").split())


_SAFETY_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*safety\s*:\s*(\w+)\s*$", re.I | re.M)
_CATEGORIES_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*categories\s*:\s*(.*)$", re.I | re.M)


def parse_qwen3guard_text(content: str) -> G1Reading:
    """The interim G1 route (§6.5): Qwen3Guard's own text, ``Safety: …`` / ``Categories: …``.

    Strict: exactly one ``Safety:`` line with one of the three labels, or the label is
    missing (→ ``unavailable``). Categories are comma-separated; absent means none.
    """
    labels = _SAFETY_LINE.findall(content)
    safety = parse_g1_label(labels[0]) if len(labels) == 1 else None
    found = _CATEGORIES_LINE.findall(content)
    names: tuple[str, ...] = ()
    if found:
        names = tuple(part for part in (p.strip() for p in found[0].split(",")) if part)
    return G1Reading(safety=safety, categories=names)


def decide_g1(reading: G1Reading) -> tuple[MediaScreenDecision, tuple[CategoryCode, ...]]:
    """One item's G1 answer under our policy (§6.3)."""
    if reading.safety is None:
        return MediaScreenDecision.UNAVAILABLE, ()
    decision = _G1_DECISIONS[reading.safety]
    codes: list[CategoryCode] = []
    unknown = False
    for name in reading.categories:
        key = _category_key(name)
        if key not in G1_CATEGORY_TABLE:
            unknown = True
            continue
        code = G1_CATEGORY_TABLE[key]
        if code is not None and code not in codes:
            codes.append(code)
    if unknown:
        # §6.3: unknown → parse error → block. Named, so the stored codes say why.
        if CategoryCode.OTHER_UNSAFE not in codes:
            codes.append(CategoryCode.OTHER_UNSAFE)
        return MediaScreenDecision.BLOCK, tuple(codes)
    if decision is MediaScreenDecision.ALLOW:
        # A safe label with category names is the guard hedging; the label is the answer.
        return decision, ()
    return decision, tuple(codes)


# ---------------------------------------------------------------------------
# G2
# ---------------------------------------------------------------------------
def _g2_key(raw: str) -> str | None:
    """The policy a G2 score key names: a stock name, or the custom minor policy under either
    spelling the gateway may echo (``"custom"`` or its text)."""
    key = raw.strip().lower()
    if key in G2_POLICIES:
        return key
    if key in (_G2_CUSTOM_KEY, G2_CUSTOM_MINOR_POLICY):
        return G2_CUSTOM_MINOR_POLICY
    return None


def decide_g2(
    scores: object, *, sexual_block_p: float
) -> tuple[MediaScreenDecision, tuple[CategoryCode, ...], dict[CategoryCode, float]]:
    """One image's G2 answer under our policy (§6.3, §6.4).

    ``scores`` is whatever the gateway sent. Not a mapping, empty, a policy we asked for
    missing, or a value that is not a probability → ``unavailable``. A score under a policy we
    did not ask for → ``block`` (``other_unsafe``): the same rule as G1's unknown category.
    """
    if not isinstance(scores, Mapping) or not scores:
        return MediaScreenDecision.UNAVAILABLE, (), {}
    read: dict[str, float] = {}
    unknown = False
    for raw_key, raw_value in scores.items():
        key = _g2_key(str(raw_key))
        if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
            return MediaScreenDecision.UNAVAILABLE, (), {}
        value = float(raw_value)
        if not 0.0 <= value <= 1.0:
            return MediaScreenDecision.UNAVAILABLE, (), {}
        if key is None:
            unknown = True
            continue
        read[key] = max(value, read.get(key, 0.0))
    if set(read) != set(G2_POLICIES):
        if unknown:
            return MediaScreenDecision.BLOCK, (CategoryCode.OTHER_UNSAFE,), {}
        return MediaScreenDecision.UNAVAILABLE, (), {}
    decisions: list[MediaScreenDecision] = []
    codes: list[CategoryCode] = []
    kept: dict[CategoryCode, float] = {}
    for key, threshold in G2_POLICIES.items():
        p = read[key]
        kept[threshold.category] = max(p, kept.get(threshold.category, 0.0))
        block_at = sexual_block_p if threshold.category is CategoryCode.SEXUAL else threshold.block
        if p >= block_at:
            decisions.append(MediaScreenDecision.BLOCK)
        elif threshold.review is not None and p >= threshold.review:
            decisions.append(MediaScreenDecision.REVIEW)
        else:
            continue
        if threshold.category not in codes:
            codes.append(threshold.category)
    if unknown:
        decisions.append(MediaScreenDecision.BLOCK)
        if CategoryCode.OTHER_UNSAFE not in codes:
            codes.append(CategoryCode.OTHER_UNSAFE)
    return strictest(decisions), tuple(codes), kept


# ---------------------------------------------------------------------------
# The hard rule and combining
# ---------------------------------------------------------------------------
def apply_hard_rule(
    decision: MediaScreenDecision,
    categories: Sequence[CategoryCode],
    *,
    youth_signal: bool,
) -> tuple[MediaScreenDecision, tuple[CategoryCode, ...]]:
    """§6.4: ``sexual_minors`` flagged, or ``sexual`` flagged with a youth signal → a
    CSAM-class block, whatever the decision was. Otherwise unchanged."""
    codes = tuple(dict.fromkeys(categories))
    flagged_minor = CategoryCode.SEXUAL_MINORS in codes
    sexual_with_youth = CategoryCode.SEXUAL in codes and youth_signal
    if not (flagged_minor or sexual_with_youth):
        return decision, codes
    if not flagged_minor:
        codes = (*codes, CategoryCode.SEXUAL_MINORS)
    return MediaScreenDecision.BLOCK, codes


def is_csam_class(decision: MediaScreenDecision, categories: Iterable[CategoryCode]) -> bool:
    """The one test for the hard rule's outcome (§6.7): a block naming ``sexual_minors``."""
    return decision is MediaScreenDecision.BLOCK and CategoryCode.SEXUAL_MINORS in set(categories)


def block_verdict(
    subject: VerdictSubject,
    categories: Sequence[CategoryCode],
    *,
    model_id: str,
    policy: str,
) -> MediaVerdict:
    return MediaVerdict(
        decision=MediaScreenDecision.BLOCK,
        categories=tuple(dict.fromkeys(categories)),
        scores={},
        subject=subject,
        model_id=model_id,
        policy_version=policy,
    )


def combine(
    parts: Sequence[MediaVerdict],
    *,
    fallback_subject: VerdictSubject,
    model_id: str,
    policy: str,
    youth_signal: bool,
) -> MediaVerdict:
    """Several per-item verdicts → one: the strictest decision, its subject, the union of the
    codes and the highest score per code — then the hard rule over the union (§6.4)."""
    decision = strictest(part.decision for part in parts)
    subject = next((part.subject for part in parts if part.decision is decision), fallback_subject)
    codes: list[CategoryCode] = []
    scores: dict[CategoryCode, float] = {}
    for part in parts:
        codes.extend(code for code in part.categories if code not in codes)
        for code, value in part.scores.items():
            scores[code] = max(value, scores.get(code, 0.0))
    decision, final = apply_hard_rule(decision, codes, youth_signal=youth_signal)
    return MediaVerdict(
        decision=decision,
        categories=final,
        scores=scores,
        subject=subject,
        model_id=model_id,
        policy_version=policy,
    )
