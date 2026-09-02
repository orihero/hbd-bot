"""Four complete catalogues, and a lookup that cannot take the bot down."""

from __future__ import annotations

import string

import pytest

from hbd.bot.i18n import (
    SUPPORTED_LANGUAGES,
    escape_html,
    genre_label,
    language_label,
    occasion_label,
    parse_language,
    translate,
    vocal_gender_label,
)
from hbd.bot.locales import CATALOGUES, REFERENCE_LANGUAGE
from hbd.contracts import Genre, Language, Occasion, VoiceGender
from hbd.errors import (
    GENERIC_USER_MESSAGE_KEY,
    AudioProcessingError,
    DeliveryError,
    EntitlementError,
    HbdError,
    InsufficientCreditsError,
    ModerationRejectedError,
    PaymentError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    TooManyOrdersInFlightError,
    ValidationError,
)
from hbd.pipeline.events import STAGE_MESSAGE_KEYS


def placeholders(template: str) -> frozenset[str]:
    return frozenset(
        field for _, field, _, _ in string.Formatter().parse(template) if field is not None
    )


def test_every_language_has_a_catalogue() -> None:
    # Arrange / Act / Assert
    assert set(CATALOGUES) == set(Language)
    assert set(SUPPORTED_LANGUAGES) == set(Language)


@pytest.mark.parametrize("language", list(Language))
def test_catalogue_defines_exactly_the_reference_key_set(language: Language) -> None:
    # Arrange
    reference = set(CATALOGUES[REFERENCE_LANGUAGE])

    # Act
    actual = set(CATALOGUES[language])

    # Assert
    assert actual == reference


@pytest.mark.parametrize("language", list(Language))
def test_catalogue_uses_the_same_placeholders_as_the_reference(language: Language) -> None:
    # Arrange
    reference = CATALOGUES[REFERENCE_LANGUAGE]

    # Act / Assert
    for key, template in reference.items():
        assert placeholders(CATALOGUES[language][key]) == placeholders(template), key


@pytest.mark.parametrize(
    "error",
    [
        ValidationError("x"),
        ModerationRejectedError("x"),
        ProviderTimeoutError("x", provider="p"),
        ProviderRateLimitedError("x", provider="p"),
        AudioProcessingError("x"),
        DeliveryError("x"),
        PaymentError("x"),
        # The three entitlement refusals. This hardcoded list is the ONLY thing proving
        # their keys exist: ``test_locale_contract`` exempts the whole ``error.`` prefix
        # from its code scan, and ``translate`` degrades a missing key to the key itself,
        # so a refusal with no catalogue entry would ship reading "error.credits_exhausted"
        # with every test in the suite green.
        EntitlementError("x"),
        InsufficientCreditsError("x"),
        TooManyOrdersInFlightError("x"),
        HbdError("x"),
    ],
)
def test_every_error_user_message_key_exists_in_every_catalogue(error: HbdError) -> None:
    # Arrange / Act / Assert
    for language in Language:
        assert error.user_message_key in CATALOGUES[language]
    assert GENERIC_USER_MESSAGE_KEY in CATALOGUES[REFERENCE_LANGUAGE]


@pytest.mark.parametrize("language", list(Language))
def test_no_error_message_carries_a_placeholder(language: Language) -> None:
    """The worker renders these bare, so a placeholder in one reaches a customer as braces.

    ``runtime.jobs._tell_the_customer_why`` sends ``translate(key, language)`` with no
    parameters at all — it has the failed error, not its context — while the bot's
    ``handlers.common.error_text`` does pass the context through. A key rendered from both
    sides must therefore read correctly with nothing interpolated, which is why the date in
    the out-of-credits refusal is a SEPARATE line (``credits.next_opens``) that only the
    read-only confirm-screen gate sends.
    """
    # Arrange / Act
    offenders = {
        key: sorted(placeholders(template))
        for key, template in CATALOGUES[language].items()
        if key.startswith("error.") and placeholders(template)
    }

    # Assert
    assert offenders == {}


def test_every_pipeline_stage_has_a_progress_message() -> None:
    # Arrange / Act / Assert
    for language in Language:
        for key in STAGE_MESSAGE_KEYS.values():
            assert key in CATALOGUES[language], (language, key)


@pytest.mark.parametrize("language", list(Language))
def test_every_enum_option_has_a_label(language: Language) -> None:
    # Arrange / Act / Assert
    for occasion in Occasion:
        assert occasion_label(occasion, language) != f"occasion.{occasion.value}"
    for genre in Genre:
        assert genre_label(genre, language) != f"genre.{genre.value}"
    for gender in VoiceGender:
        assert vocal_gender_label(gender, language) != f"vocal_gender.{gender.value}"
    for value in Language:
        assert language_label(value, language) != f"language.{value.value}"


def test_missing_key_degrades_to_the_key_instead_of_raising() -> None:
    # Arrange / Act
    text = translate("no.such.key.anywhere", Language.EN)

    # Assert
    assert text == "no.such.key.anywhere"


def test_missing_parameter_degrades_instead_of_raising() -> None:
    # Arrange / Act — the template wants {limit} and gets nothing
    text = translate("wizard.note.too_long", Language.EN)

    # Assert
    assert "{limit}" in text


def test_extra_parameters_are_ignored() -> None:
    # Arrange / Act
    text = translate("wizard.cancelled", Language.EN, unused="value")

    # Assert
    assert text == CATALOGUES[Language.EN]["wizard.cancelled"]


def test_interpolated_values_are_html_escaped() -> None:
    # Arrange
    hostile = "<b>Aziza</b>"

    # Act
    text = translate("wizard.name.confirm", Language.EN, name=hostile)

    # Assert — our own <b> survives, the user's does not
    assert "&lt;b&gt;Aziza&lt;/b&gt;" in text
    assert "<b>Aziza</b>" not in text


def test_escape_html_handles_any_value() -> None:
    # Arrange / Act / Assert
    assert escape_html(5) == "5"
    assert escape_html("a & b") == "a &amp; b"


def test_uzbek_latin_copy_uses_the_correct_modifier_letter() -> None:
    # Arrange
    catalogue = CATALOGUES[Language.UZ_LATN]

    # Act
    offenders = [
        key
        for key, value in catalogue.items()
        if any(mark in value for mark in ("‘", "’", "'", "`"))
    ]

    # Assert — display orthography is the half of the name subsystem customers see
    assert offenders == []


@pytest.mark.parametrize(
    ("code", "expected"),
    [("en", Language.EN), ("uz_cyrl", Language.UZ_CYRL), (None, Language.UZ_LATN)],
)
def test_parse_language_reads_a_code_or_falls_back(code: str | None, expected: Language) -> None:
    # Arrange / Act / Assert
    assert parse_language(code) is expected


def test_parse_language_falls_back_on_nonsense() -> None:
    # Arrange / Act / Assert
    assert parse_language("martian") is Language.UZ_LATN
