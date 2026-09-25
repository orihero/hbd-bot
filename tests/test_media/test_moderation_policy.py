"""L0, the policy, strikes and the legal-hold seal (IMAGE_VIDEO_SPEC §6.3, §6.4, §6.7, M3.1).

Pure units: the normaliser folds the tricks, the lexicons match in all four scripts, the G1/G2
mappings fail closed, the hard rule fires on ``sexual`` + youth, strikes suspend, and a sealed
object opens only with the owner's private key.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from bayram.contracts import is_err, is_ok
from bayram.db.enums import MediaScreenDecision
from bayram.moderation.contracts import CategoryCode
from bayram.moderation.legal_hold import (
    generate_keypair,
    is_sealed,
    open_sealed,
    parse_public_key,
    seal,
)
from bayram.moderation.lexicon import (
    denylist_hits,
    has_youth_signal,
    is_within_caps,
    normalise,
)
from bayram.moderation.policy import (
    G2_POLICIES,
    G1Reading,
    apply_hard_rule,
    decide_g1,
    decide_g2,
    is_csam_class,
    parse_qwen3guard_text,
)
from bayram.moderation.strikes import (
    STRIKE_SUSPENSION,
    MemoryStrikeStore,
    RedisStrikeStore,
    SuspensionReason,
    record_block,
)
from tests.conftest import FIXED_NOW

USER = 7_001


# ---------------------------------------------------------------------------
# L0
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "folded"),
    [
        ("ＮＵＤＥ", "nude"),  # full-width
        ("n\u200bud\u00ade", "nude"),  # zero-width space, soft hyphen
        ("nаked", "naked"),  # Cyrillic а inside a Latin word
        ("Oʻldir", "o'ldir"),  # U+02BB
        ("p0rn", "porn"),  # digit for a letter
        ("ГОЛАЯ", "голая"),
    ],
)
def test_normalise_folds_the_tricks(raw: str, folded: str) -> None:
    assert normalise(raw) == folded


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("yalang‘och ayol", CategoryCode.SEXUAL),
        ("ялангоч", CategoryCode.SEXUAL),
        ("эротическое фото", CategoryCode.SEXUAL),
        ("Shavkat Mirziyoyev on a horse", CategoryCode.POLITICS_OFFICIALS),
        ("Путин", CategoryCode.POLITICS_OFFICIALS),
        ("Mickey Mouse birthday cake", CategoryCode.COPYRIGHT_CHARACTER),
        ("Маша и медведь", CategoryCode.COPYRIGHT_CHARACTER),
        ("a nazi flag", CategoryCode.EXTREMISM),
        ("террористы", CategoryCode.EXTREMISM),
        ("uni oʻldir", CategoryCode.VIOLENCE),
        ("lolicon art", CategoryCode.SEXUAL_MINORS),
    ],
)
def test_the_denylist_matches_in_every_script(text: str, category: CategoryCode) -> None:
    assert category in {hit.category for hit in denylist_hits(text)}


@pytest.mark.parametrize(
    "text",
    [
        "a lantern-lit courtyard in Samarkand at dusk",
        "Karimovlar oilasi uchun tabrik",  # a common surname is not an official
        "tugʻilgan kuning bilan, onajon",
        "бабушка с тортом",
    ],
)
def test_an_ordinary_greeting_is_not_on_the_denylist(text: str) -> None:
    assert denylist_hits(text) == ()


@pytest.mark.parametrize(
    "text",
    [
        "bolalar bayrami",
        "qizcha gullar bilan",
        "oʻquvchi qiz",
        "мактаб формаси",
        "девочка с шариками",
        "школьница",
        "a schoolgirl",
        "two kids",
        "teenage boy",
    ],
)
def test_the_youth_lexicon_covers_four_scripts(text: str) -> None:
    assert has_youth_signal(text)


def test_an_adult_greeting_carries_no_youth_signal() -> None:
    assert not has_youth_signal(["my wife at the seaside", "onam uchun gullar"])


def test_the_caps_bound_characters_and_words() -> None:
    assert is_within_caps("a cat")
    assert not is_within_caps("ab")
    assert not is_within_caps("x" * 801)
    assert not is_within_caps(" ".join("a" for _ in range(161)))


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------
def test_g1_mapping_and_the_unknown_category_rule() -> None:
    assert decide_g1(G1Reading("unsafe", ("Violent",))) == (
        MediaScreenDecision.BLOCK,
        (CategoryCode.VIOLENCE,),
    )
    assert decide_g1(G1Reading("controversial", ("Politically Sensitive Topics",))) == (
        MediaScreenDecision.REVIEW,
        (CategoryCode.POLITICS_OFFICIALS,),
    )
    assert decide_g1(G1Reading("safe", ("None",))) == (MediaScreenDecision.ALLOW, ())
    assert decide_g1(G1Reading(None, ())) == (MediaScreenDecision.UNAVAILABLE, ())
    assert decide_g1(G1Reading("safe", ("Aliens",)))[0] is MediaScreenDecision.BLOCK


def test_the_qwen3guard_text_is_parsed_strictly() -> None:
    assert parse_qwen3guard_text("Safety: Controversial\nCategories: Jailbreak, PII") == G1Reading(
        "controversial", ("Jailbreak", "PII")
    )
    assert parse_qwen3guard_text("Safety: Safe\nCategories: None").safety == "safe"
    assert parse_qwen3guard_text("Safety: Safe\nSafety: Unsafe").safety is None
    assert parse_qwen3guard_text("yes it is allowed").safety is None


def test_g2_fails_closed_on_every_malformed_answer() -> None:
    clean = dict.fromkeys(G2_POLICIES, 0.0)
    malformed: tuple[object, ...] = (
        {},
        None,
        [],
        {**clean, "violence": "high"},
        {**clean, "violence": 1.5},
    )
    for bad in malformed:
        assert decide_g2(bad, sexual_block_p=0.2)[0] is MediaScreenDecision.UNAVAILABLE
    assert decide_g2(clean, sexual_block_p=0.2)[0] is MediaScreenDecision.ALLOW
    decision, codes, _ = decide_g2({**clean, "brand_new": 0.0}, sexual_block_p=0.2)
    assert (decision, codes) == (MediaScreenDecision.BLOCK, (CategoryCode.OTHER_UNSAFE,))


def test_g2_review_band_and_the_configured_nudity_threshold() -> None:
    clean = dict.fromkeys(G2_POLICIES, 0.0)
    assert decide_g2({**clean, "violence": 0.4}, sexual_block_p=0.2)[0] is (
        MediaScreenDecision.REVIEW
    )
    assert decide_g2({**clean, "sexually_explicit": 0.15}, sexual_block_p=0.1)[0] is (
        MediaScreenDecision.BLOCK
    )
    assert decide_g2({**clean, "sexually_explicit": 0.15}, sexual_block_p=0.2)[0] is (
        MediaScreenDecision.ALLOW
    )


def test_the_hard_rule() -> None:
    allow = MediaScreenDecision.ALLOW
    review = MediaScreenDecision.REVIEW
    sexual = (CategoryCode.SEXUAL,)
    assert apply_hard_rule(review, sexual, youth_signal=False) == (review, sexual)
    decision, codes = apply_hard_rule(review, sexual, youth_signal=True)
    assert is_csam_class(decision, codes)
    decision, codes = apply_hard_rule(allow, (CategoryCode.SEXUAL_MINORS,), youth_signal=False)
    assert is_csam_class(decision, codes)
    assert apply_hard_rule(allow, (), youth_signal=True) == (allow, ())


# ---------------------------------------------------------------------------
# Strikes
# ---------------------------------------------------------------------------
async def test_three_strikes_in_a_week_suspend_for_a_week() -> None:
    store = MemoryStrikeStore()
    first = await record_block(
        store, USER, event_id="a:prepay", weight=1, is_csam=False, now=FIXED_NOW
    )
    again = await record_block(
        store, USER, event_id="a:prepay", weight=1, is_csam=False, now=FIXED_NOW
    )
    assert first is None and again is None  # a redelivered stage adds nothing

    suspended = await record_block(
        store, USER, event_id="b:output", weight=2, is_csam=False, now=FIXED_NOW
    )

    assert suspended is not None and suspended.reason is SuspensionReason.STRIKES
    assert await store.suspension(USER, now=FIXED_NOW + timedelta(days=6)) is not None
    assert await store.suspension(USER, now=FIXED_NOW + STRIKE_SUSPENSION) is None


async def test_strikes_older_than_the_window_do_not_count() -> None:
    store = MemoryStrikeStore()
    await record_block(store, USER, event_id="a", weight=2, is_csam=False, now=FIXED_NOW)

    later = FIXED_NOW + timedelta(days=8)
    assert await record_block(store, USER, event_id="b", weight=1, is_csam=False, now=later) is None


async def test_a_csam_suspension_never_expires_or_downgrades() -> None:
    store = MemoryStrikeStore()
    await record_block(store, USER, event_id="a", weight=3, is_csam=True, now=FIXED_NOW)
    await store.suspend(USER, reason=SuspensionReason.STRIKES, now=FIXED_NOW)

    found = await store.suspension(USER, now=FIXED_NOW + timedelta(days=365))
    assert found is not None and found.reason is SuspensionReason.CSAM
    assert await store.clear(USER)
    assert await store.suspension(USER, now=FIXED_NOW) is None


async def test_the_screening_budget_counts_a_job_once() -> None:
    store = MemoryStrikeStore()
    assert await store.count_screen(USER, job_id="j1", now=FIXED_NOW) == 1
    assert await store.count_screen(USER, job_id="j1", now=FIXED_NOW) == 1
    assert await store.count_screen(USER, job_id="j2", now=FIXED_NOW) == 2
    assert await store.screens_today(USER, now=FIXED_NOW + timedelta(days=1)) == 0


@pytest.mark.integration
async def test_the_redis_strike_store_against_a_live_redis() -> None:
    from redis.asyncio import Redis

    redis: Redis[bytes] = Redis.from_url(
        os.environ.get("BAYRAM_TEST_REDIS_URL", "redis://localhost:6379/15")
    )
    prefix = f"test:{uuid4().hex}:"
    store = RedisStrikeStore(redis, prefix=prefix)
    try:
        assert await store.add_strikes(USER, event_id="a", weight=2, now=FIXED_NOW) == 2
        assert await store.add_strikes(USER, event_id="a", weight=2, now=FIXED_NOW) == 2
        await store.suspend(USER, reason=SuspensionReason.CSAM, now=FIXED_NOW)
        await store.suspend(USER, reason=SuspensionReason.STRIKES, now=FIXED_NOW)
        found = await store.suspension(USER, now=FIXED_NOW)
        assert found is not None and found.reason is SuspensionReason.CSAM
        assert await store.count_screen(USER, job_id="j", now=FIXED_NOW) == 1
        assert await store.clear(USER)
        assert await store.suspension(USER, now=FIXED_NOW) is None
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The seal
# ---------------------------------------------------------------------------
def test_a_sealed_object_opens_only_with_the_owners_key() -> None:
    private, public = generate_keypair()
    other_private, _ = generate_keypair()
    recipient = parse_public_key(public)
    assert recipient is not None

    blob = seal(b"held bytes", recipient)

    assert is_sealed(blob) and b"held bytes" not in blob
    opened = open_sealed(blob, private)
    assert is_ok(opened) and opened.value == b"held bytes"
    assert is_err(open_sealed(blob, other_private))
    assert is_err(open_sealed(blob[:-1] + bytes([blob[-1] ^ 1]), private))


def test_a_public_key_must_be_32_base64_bytes() -> None:
    assert parse_public_key("") is None
    assert parse_public_key("not base64!") is None
    assert parse_public_key("c2hvcnQ=") is None
    assert parse_public_key(generate_keypair()[1]) is not None


# ---------------------------------------------------------------------------
# The operator's tools
# ---------------------------------------------------------------------------
def test_the_legal_hold_tool_opens_what_the_host_sealed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from bayram.tools.legal_hold import main

    assert main(["keygen"]) == 0
    lines = capsys.readouterr().out.splitlines()
    private = lines[0].rsplit(" ", 1)[-1]
    public = lines[1].rsplit(" ", 1)[-1]
    recipient = parse_public_key(public)
    assert recipient is not None
    sealed = tmp_path / "held.bin"
    sealed.write_bytes(seal(b"evidence", recipient))
    key_file = tmp_path / "owner.key"
    key_file.write_text(private, encoding="ascii")

    assert main(["open", str(sealed), str(tmp_path / "out.jpg"), "--key-file", str(key_file)]) == 0
    assert (tmp_path / "out.jpg").read_bytes() == b"evidence"
    assert main(["open", str(key_file), str(tmp_path / "x"), "--key-file", str(key_file)]) == 1


def test_unsuspend_takes_a_positive_telegram_id() -> None:
    from bayram.tools.media import RefusedError, plan

    assert plan(["unsuspend", "42"]).telegram_user_id == 42
    for bad in ("0", "abc"):
        with pytest.raises(RefusedError):
            plan(["unsuspend", bad])
