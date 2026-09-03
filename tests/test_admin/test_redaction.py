"""Masking, asserted by code point — §12.3, and §14 Slice 1c's ``Gʻulom`` bullet.

Every confusable or invisible character here is written as an escape. ``Gʻulom``,
``G'ulom`` and ``G’ulom`` are three different strings that render almost identically in a
terminal, a diff and a code review, and the whole point of the acceptance bullet is that the
first must never become either of the others. A test written with the visible character would
keep passing after an editor, a copy-paste through a word processor or a "smart quotes"
transform silently rewrote it — so :data:`GULOM` is the source literal
``"G\\u02bbulom"``, the zero-width joiner and the variation selector are escapes too, and
the code points are asserted by :func:`ord` before anything is masked.

Three layers:

* **the function** — :func:`first_grapheme` over the cluster shapes real display names take,
  including the emoji and regional-indicator branches nothing else in the suite reaches;
* **the payload** — the seeded plaintext is searched for as a substring of the raw response
  bytes of every GET route the application serves, at every one of the four roles, because
  §12.3 is a rule about bytes rather than about what the SPA chooses to render;
* **the secrets** — the same sweep, against DSN userinfo, the audit HMAC key, the probe
  token and an argon2 PHC string. That folds §12.4's ``GET /config`` bullet into one
  cross-cutting guarantee: the DSN regex is asserted against the settings first, so a
  pattern that had stopped matching could not pass this file silently.

The wizard draft gets the strictest form of the rule. ``/users/{tg}/wizard-state`` reports
presence and a character count and nothing else, so "no substring of the plaintext" is
asserted token by token — and ``charCount`` is asserted to equal the plaintext's length,
which proves the count was computed from a value that never reached the wire.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from collections.abc import AsyncIterator
from typing import Final
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa

from hbd.admin.container import AdminContainer
from hbd.admin.routers.orders import ORDER_PATH, ORDERS_PATH
from hbd.admin.routers.users import WIZARD_STATE_PATH
from hbd.admin.schemas.users import WIZARD_TEXT_FIELDS
from hbd.admin.serializers.redaction import (
    MASK,
    TELEGRAM_ID_VISIBLE_DIGITS,
    first_grapheme,
    mask_name,
    mask_telegram_user_id,
)
from hbd.admin.settings import AdminSettings
from hbd.db.enums import AdminRole
from hbd.db.models.asset import AssetRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from tests.test_admin.conftest import (
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    make_settings,
    open_container,
    sign_in,
)
from tests.test_admin.test_config_router import (
    AUDIT_DSN,
    AUDIT_HMAC_KEY,
    DATABASE_DSN,
    DSN_WITH_USERINFO,
    PROBE_TOKEN,
    REDIS_DSN,
    SECRETS,
)
from tests.test_admin.test_orders_router import (
    PLAINTEXT_NAME,
    PLAINTEXT_NOTE,
    PLAINTEXT_TRANSCRIPT,
    TELEGRAM_ID,
    seed_named_order,
)
from tests.test_admin.test_routes_enumeration import MOUNTED_ROUTES
from tests.test_admin.test_users_router import seed_wizard_session
from tests.test_admin.test_wizard_state import NOTE as DRAFT_NOTE
from tests.test_admin.test_wizard_state import RECIPIENT_DISPLAY as DRAFT_RECIPIENT

#: ``Gʻulom``, spelled so no editor can rewrite it: U+0047 U+02BB U+0075 U+006C U+006F U+006D.
GULOM: Final[str] = "G\u02bbulom"
#: U+02BB MODIFIER LETTER TURNED COMMA — the character the acceptance bullet is about.
TURNED_COMMA: Final[str] = "\u02bb"
#: The two characters it must never be normalised into: APOSTROPHE and RIGHT SINGLE
#: QUOTATION MARK. Neither is a modifier letter and both change how the name is pronounced.
APOSTROPHE: Final[str] = "\u0027"
RIGHT_SINGLE_QUOTE: Final[str] = "\u2019"
#: U+02BC MODIFIER LETTER APOSTROPHE — the *other* Uzbek modifier letter, in ``sanʼat``.
MODIFIER_APOSTROPHE: Final[str] = "\u02bc"

#: An argon2 PHC prefix. §12.3 puts the credential in the "never returned at any role" row.
ARGON2_PREFIX: Final[str] = "$argon2id$"

#: Every plaintext the seeded world holds, asserted absent from every body below.
PLAINTEXTS: Final[tuple[str, ...]] = (
    PLAINTEXT_NAME,
    PLAINTEXT_NOTE,
    PLAINTEXT_TRANSCRIPT,
    DRAFT_NOTE,
    DRAFT_RECIPIENT,
)

EVERY_ROLE: Final[tuple[AdminRole, ...]] = (
    AdminRole.VIEWER,
    AdminRole.SUPPORT,
    AdminRole.ADMIN,
    AdminRole.OWNER,
)

#: Words long enough that finding one in a response could not be a coincidence. Four
#: characters is the floor: "opa" and "the" appear in ordinary JSON keys, "atab" does not.
_MIN_TOKEN_CHARS: Final[int] = 4


def revealing_tokens(text: str) -> tuple[str, ...]:
    """The whitespace-delimited words of ``text`` that are long enough to be evidence."""
    return tuple(token for token in text.split() if len(token) >= _MIN_TOKEN_CHARS)


# ---------------------------------------------------------------------------
# The function, by code point
# ---------------------------------------------------------------------------
def test_the_fixture_name_is_the_code_points_the_bullet_names() -> None:
    # Arrange / Act — asserted first, so every test below is known to be about U+02BB and
    # not about whatever an editor left behind.

    # Assert
    assert [ord(char) for char in GULOM] == [0x0047, 0x02BB, 0x0075, 0x006C, 0x006F, 0x006D]
    assert GULOM == PLAINTEXT_NAME
    assert unicodedata.category(TURNED_COMMA) == "Lm"


def test_masking_gulom_yields_g_and_the_elision() -> None:
    # Arrange / Act — the acceptance case itself.
    masked = mask_name(GULOM)

    # Assert
    assert masked == "G" + MASK
    assert [ord(char) for char in (masked or "")] == [0x0047, 0x2022, 0x2022, 0x2022]


def test_the_modifier_letter_is_never_split_off_into_the_visible_head() -> None:
    # Arrange — a cut at a byte emits a lone continuation byte; a cut at two clusters leaks
    # ``Gʻ``, which is the first half of the name.
    head = first_grapheme(GULOM)

    # Act / Assert
    assert head == "G"
    assert len(head) == 1
    assert TURNED_COMMA not in (mask_name(GULOM) or "")
    assert head.encode("utf-8") == b"G"


@pytest.mark.parametrize("forbidden", [APOSTROPHE, RIGHT_SINGLE_QUOTE], ids=["u+0027", "u+2019"])
def test_the_modifier_letter_is_never_normalised_into_a_quote(forbidden: str) -> None:
    # Arrange / Act
    masked = mask_name(GULOM) or ""

    # Assert
    assert forbidden not in masked
    assert forbidden not in first_grapheme(GULOM)


def test_nothing_here_normalises_and_the_name_would_survive_it_anyway() -> None:
    # Arrange / Act — the module calls neither NFC nor NFKC. This documents why that is
    # safe rather than lucky: both forms leave U+02BB alone, so the absence of a call is a
    # decision with no cost, and the temptation to "clean the name up first" has no upside.

    # Assert
    assert unicodedata.normalize("NFC", GULOM) == GULOM
    assert unicodedata.normalize("NFKC", GULOM) == GULOM


def test_a_name_that_begins_with_the_modifier_letter_masks_to_the_modifier_letter() -> None:
    # Arrange / Act — U+02BB is a letter, so it is a cluster of its own and the head of a
    # name that starts with it. A module that treated it as a mark would return ``a•••``
    # and quietly rename somebody.

    # Assert
    assert first_grapheme(TURNED_COMMA + "ali") == TURNED_COMMA
    assert mask_name(TURNED_COMMA + "ali") == TURNED_COMMA + MASK


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ""),
        ("e\u0301", "e\u0301"),
        ("\U0001f1fa\U0001f1ff", "\U0001f1fa\U0001f1ff"),
        ("\U0001f1fa\U0001f1ff\U0001f1f7\U0001f1fa", "\U0001f1fa\U0001f1ff"),
        ("\U0001f469\u200d\U0001f4bb", "\U0001f469\u200d\U0001f4bb"),
        ("\U0001f44d\U0001f3fd", "\U0001f44d\U0001f3fd"),
        ("a\ufe0f", "a\ufe0f"),
        ("\u200d", "\u200d"),
        ("Дилноза", "Д"),
        ("san" + MODIFIER_APOSTROPHE + "at", "s"),
    ],
    ids=[
        "empty",
        "combining-acute",
        "one-flag",
        "two-flags-are-not-one-cluster",
        "zwj-sequence",
        "emoji-modifier",
        "variation-selector",
        "trailing-zwj-alone",
        "cyrillic",
        "u+02bc-is-a-letter-too",
    ],
)
def test_the_first_cluster_is_the_first_user_perceived_character(text: str, expected: str) -> None:
    # Arrange / Act — over-keeping shows one extra mark; under-keeping emits mojibake. The
    # approximation is allowed only the first failure, so every case here is exact.
    head = first_grapheme(text)

    # Assert
    assert head == expected
    assert text.startswith(head)


def test_the_head_is_always_a_substring_of_the_input_rather_than_a_re_encoding() -> None:
    # Arrange — "never normalises, never decomposes, never re-encodes" is the docstring's
    # promise, and a name that survives unchanged must be byte-identical to the typed one.
    for text in (GULOM, "san" + MODIFIER_APOSTROPHE + "at", "Дил", "e\u0301"):
        # Act
        head = first_grapheme(text)

        # Assert
        assert text.encode("utf-8").startswith(head.encode("utf-8")), text


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (None, None),
        ("", MASK),
        ("   ", MASK),
        ("  " + GULOM + "  ", "G" + MASK),
        (DRAFT_RECIPIENT, "G" + MASK),
    ],
    ids=["purged", "empty", "whitespace", "padded", "the-draft-fixture-name"],
)
def test_mask_name_edge_cases(name: str | None, expected: str | None) -> None:
    # Arrange / Act — ``None`` stays ``None`` because a purge is not a mask: returning the
    # elision would promise the operator something to reveal that no longer exists.

    # Assert
    assert mask_name(name) == expected


@pytest.mark.parametrize(
    ("telegram_user_id", "expected"),
    [
        (123_456_789, "•" * 5 + "789"),
        (-1_001_234_567_890, "•" * 5 + "890"),
        (1_000, "•" * 5 + "000"),
        (999, "•" * 5),
        (12, "•" * 5),
        (0, "•" * 5),
    ],
    ids=["ordinary", "a-channel-id-loses-its-sign", "leading-zeros-kept", "three", "two", "zero"],
)
def test_a_telegram_id_keeps_its_last_digits_behind_a_fixed_width_mask(
    telegram_user_id: int, expected: str
) -> None:
    # Arrange / Act — the tail is the discriminator an operator matches a ticket against;
    # the prefix is a constant five bullets so the mask's width cannot leak the magnitude.
    masked = mask_telegram_user_id(telegram_user_id)

    # Assert
    assert masked == expected
    assert masked.startswith("•" * 5)
    assert len(masked) - 5 <= TELEGRAM_ID_VISIBLE_DIGITS


def test_the_mask_width_does_not_track_the_id_it_hides() -> None:
    # Arrange / Act — a proportional mask would turn "how many bullets" into a coarse
    # account-age signal, which is the leak the fixed prefix exists to close.
    widths = {len(mask_telegram_user_id(value)) for value in (1_000, 10**9, 10**14)}

    # Assert
    assert widths == {5 + TELEGRAM_ID_VISIBLE_DIGITS}


# ---------------------------------------------------------------------------
# The payload — the same rule, over the wire
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_settings() -> AdminSettings:
    """Settings carrying real credentials, so the secret sweep has something to catch."""
    return make_settings(
        redis_url=REDIS_DSN,
        admin_audit_dsn=AUDIT_DSN,
        admin_audit_hmac_key=AUDIT_HMAC_KEY,
        admin_probe_token=PROBE_TOKEN,
    )


@pytest.fixture
async def container(
    admin_settings: AdminSettings, fake_redis: FakeRedis, rate_limits: MemoryRateLimits
) -> AsyncIterator[AdminContainer]:
    """The standard container with a credentialed ``database_url`` swapped in afterwards.

    The engine must be the in-memory one — this suite has no Postgres — while the settings
    object the ``/config`` view reports has to be the one carrying a password, or the DSN
    assertion would be asserting against nothing.
    """
    async with open_container(admin_settings, fake_redis, rate_limits) as built:
        yield dataclasses.replace(
            built, settings=built.settings.model_copy(update={"database_url": DATABASE_DSN})
        )


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


async def seed_world(container: AdminContainer, fake_redis: FakeRedis) -> dict[str, object]:
    """One order carrying every plaintext, plus a live wizard draft for the same person."""
    order_id = await seed_named_order(container)
    await seed_wizard_session(fake_redis, telegram_user_id=TELEGRAM_ID)
    async with container.session_factory.begin() as db:
        asset_id = (await db.execute(sa.select(AssetRow.id))).scalars().first()
        attempt_id = (await db.execute(sa.select(GenerationAttemptRow.id))).scalars().first()
        await db.execute(
            sa.update(GenerationAttemptRow).values(stt_transcript=PLAINTEXT_TRANSCRIPT)
        )
    assert isinstance(asset_id, UUID)
    assert isinstance(attempt_id, UUID)
    return {
        "order_id": order_id,
        "asset_id": asset_id,
        "attempt_id": attempt_id,
        "telegram_user_id": TELEGRAM_ID,
    }


async def sweep(
    client: httpx.AsyncClient, identifiers: dict[str, object]
) -> dict[str, httpx.Response]:
    """GET every route the application serves, keyed by the path that was requested."""
    bodies: dict[str, httpx.Response] = {}
    for method, template, _ in sorted(MOUNTED_ROUTES):
        if method != "GET":
            continue
        path = template.format(**identifiers)
        bodies[path] = await client.get(path)
    return bodies


@pytest.mark.parametrize("role", EVERY_ROLE, ids=[role.value for role in EVERY_ROLE])
async def test_no_plaintext_reaches_any_body_at_any_role(
    container: AdminContainer,
    client: httpx.AsyncClient,
    fake_redis: FakeRedis,
    role: AdminRole,
) -> None:
    # Arrange — §12.3 has no unmasked variant of any of these at any role, OWNER included:
    # the plaintext is reachable only through ``POST /reveal`` in Phase 2.
    identifiers = await seed_world(container, fake_redis)
    await signed_in(container, client, role=role)

    # Act
    responses = await sweep(client, identifiers)

    # Assert — over the raw text, so a leak nested under an unexpected key fails too.
    for path, response in responses.items():
        for plaintext in PLAINTEXTS:
            assert plaintext not in response.text, (path, role)


async def test_the_masked_name_is_what_the_records_screens_do_carry(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange — the positive half. A body with neither the plaintext nor the mask would
    # pass the sweep above by returning nothing at all.
    identifiers = await seed_world(container, fake_redis)
    await signed_in(container, client, role=AdminRole.VIEWER)
    order_id = identifiers["order_id"]

    # Act
    listing = await client.get(ORDERS_PATH)
    detail = await client.get(ORDER_PATH.format(order_id=order_id))

    # Assert
    assert listing.status_code == 200
    assert detail.status_code == 200
    assert "G" + MASK in listing.text
    assert "G" + MASK in detail.text
    assert mask_telegram_user_id(TELEGRAM_ID) in listing.text


@pytest.mark.parametrize("role", EVERY_ROLE, ids=[role.value for role in EVERY_ROLE])
async def test_the_wizard_draft_leaks_no_word_of_its_plaintext_at_any_role(
    container: AdminContainer,
    client: httpx.AsyncClient,
    fake_redis: FakeRedis,
    role: AdminRole,
) -> None:
    # Arrange — the strongest form of the rule, because this projection returns presence and
    # a count: no whitespace-delimited word of the draft may appear anywhere in the body.
    await seed_world(container, fake_redis)
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(WIZARD_STATE_PATH.format(telegram_user_id=TELEGRAM_ID))

    # Assert
    assert response.status_code == 200
    for plaintext in (DRAFT_NOTE, DRAFT_RECIPIENT):
        for token in revealing_tokens(plaintext):
            assert token not in response.text, (token, role)


async def test_the_character_count_is_the_only_thing_the_draft_reports(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange — a count that equals the plaintext's length proves the length was computed
    # from a value that never reached the wire, rather than from something truncated first.
    await seed_world(container, fake_redis)
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(WIZARD_STATE_PATH.format(telegram_user_id=TELEGRAM_ID))).json()

    # Assert
    counts = {field["key"]: field["charCount"] for field in body["textFields"]}
    assert set(counts) == set(WIZARD_TEXT_FIELDS)
    assert counts["note"] == len(DRAFT_NOTE)
    assert counts["recipient"] == len(DRAFT_RECIPIENT)
    assert body["telegramUserIdMasked"] == mask_telegram_user_id(TELEGRAM_ID)


# ---------------------------------------------------------------------------
# §12.3's "never returned at any role" row, and §12.4's DSN bullet
# ---------------------------------------------------------------------------
def test_the_dsn_pattern_matches_the_credentials_it_is_looking_for() -> None:
    # Arrange / Act — asserted against the fixtures first, so a regex that had stopped
    # matching could not make the sweep below pass by matching nothing.

    # Assert
    assert DSN_WITH_USERINFO.search(DATABASE_DSN) is not None
    assert DSN_WITH_USERINFO.search(REDIS_DSN) is not None
    assert DSN_WITH_USERINFO.search(AUDIT_DSN) is not None


@pytest.mark.parametrize("role", EVERY_ROLE, ids=[role.value for role in EVERY_ROLE])
async def test_no_secret_reaches_any_body_at_any_role(
    container: AdminContainer,
    client: httpx.AsyncClient,
    fake_redis: FakeRedis,
    role: AdminRole,
) -> None:
    # Arrange — the credential row of §12.3 is "never, at any role", so it is swept exactly
    # as hard as the personal data, and across every route rather than only ``/config``.
    identifiers = await seed_world(container, fake_redis)
    await signed_in(container, client, role=role)

    # Act
    responses = await sweep(client, identifiers)

    # Assert
    for path, response in responses.items():
        assert DSN_WITH_USERINFO.search(response.text) is None, (path, role)
        assert ARGON2_PREFIX not in response.text, (path, role)
        for secret in SECRETS:
            assert secret not in response.text, (path, role)
