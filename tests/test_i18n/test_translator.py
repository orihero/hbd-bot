"""``t()`` behaviour: strict in tests, loud-but-alive in production."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import pytest

from hbd.contracts import Language
from hbd.errors import (
    GENERIC_USER_MESSAGE_KEY,
    DeliveryError,
    HbdError,
    NameVerificationExhaustedError,
    PaymentError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ValidationError,
)
from hbd.i18n.catalog import Catalog, load_catalogs
from hbd.i18n.translator import (
    STRICT_ENV_VAR,
    Translator,
    get_translator,
    is_strict_by_default,
    t,
    translate_error,
)


def _catalogs() -> Mapping[Language, Catalog]:
    return load_catalogs()


def _lenient() -> Translator:
    return Translator(catalogs=_catalogs(), is_strict=False)


def _strict() -> Translator:
    return Translator(catalogs=_catalogs(), is_strict=True)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language", list(Language))
def test_resolves_a_plain_key_in_every_locale(language: Language) -> None:
    # Act
    rendered = t("name.prompt", language)

    # Assert
    assert rendered
    assert rendered != "name.prompt"


def test_interpolates_named_parameters() -> None:
    # Act
    rendered = t("start.language_set", Language.EN, language="English")

    # Assert
    assert rendered == "Interface language: English."


def test_uzbek_latin_output_carries_the_turned_comma() -> None:
    # Act
    rendered = t("common.no", Language.UZ_LATN)

    # Assert
    assert rendered == "Yoʻq"
    assert "ʻ" in rendered


def test_ignores_extra_parameters_the_template_does_not_use() -> None:
    assert t("common.yes", Language.EN, unused="x") == "Yes"


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, "1 kit so far."), (2, "2 kits so far."), (0, "0 kits so far.")],
)
def test_english_plural_selects_the_right_form(count: int, expected: str) -> None:
    assert t("status.orders_found", Language.EN, count=count) == expected


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "1 набор."),
        (2, "2 набора."),
        (5, "5 наборов."),
        (11, "11 наборов."),
        (21, "21 набор."),
        (22, "22 набора."),
    ],
)
def test_russian_plural_selects_one_few_many(count: int, expected: str) -> None:
    assert t("status.orders_found", Language.RU, count=count) == expected


def test_count_is_available_to_the_template_without_being_passed_twice() -> None:
    assert "3" in t("delivery.greetings_count", Language.UZ_LATN, count=3)


def test_has_reports_key_presence() -> None:
    # Arrange
    translator = _lenient()

    # Act / Assert
    assert translator.has("common.yes", Language.RU) is True
    assert translator.has("common.nope", Language.RU) is False


# ---------------------------------------------------------------------------
# Strict mode — a copy bug must not survive review
# ---------------------------------------------------------------------------
def test_missing_key_raises_in_strict_mode() -> None:
    with pytest.raises(ValidationError, match="missing_key"):
        _strict().translate("no.such.key", Language.EN)


def test_t_is_strict_under_pytest() -> None:
    # Arrange / Act / Assert — the module-level helper uses the process translator.
    assert get_translator().is_strict is True
    with pytest.raises(ValidationError):
        t("no.such.key", Language.EN)


def test_pluralised_key_without_a_count_raises_in_strict_mode() -> None:
    with pytest.raises(ValidationError, match="missing_count"):
        _strict().translate("status.orders_found", Language.EN)


def test_boolean_count_is_rejected_rather_than_treated_as_one() -> None:
    with pytest.raises(ValidationError, match="missing_count"):
        _strict().translate("status.orders_found", Language.EN, count=True)


def test_missing_format_parameter_raises_in_strict_mode() -> None:
    with pytest.raises(ValidationError, match="missing_params"):
        _strict().translate("start.language_set", Language.EN)


def test_strict_failure_carries_diagnostic_context() -> None:
    # Act
    with pytest.raises(ValidationError) as caught:
        _strict().translate("no.such.key", Language.RU)

    # Assert
    assert caught.value.context["key"] == "no.such.key"
    assert caught.value.context["language"] == "ru"
    assert caught.value.context["i18n_reason"] == "missing_key"


# ---------------------------------------------------------------------------
# Production mode — degrade, log, never crash a delivery
# ---------------------------------------------------------------------------
def test_missing_key_falls_back_to_the_key_name_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    translator = _lenient()

    # Act
    with caplog.at_level(logging.ERROR, logger="hbd.i18n.translator"):
        rendered = translator.translate("no.such.key", Language.EN)

    # Assert
    assert rendered == "no.such.key"
    assert any("missing_key" in record.getMessage() for record in caplog.records)


def test_missing_parameter_returns_the_raw_template_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    translator = _lenient()

    # Act
    with caplog.at_level(logging.ERROR, logger="hbd.i18n.translator"):
        rendered = translator.translate("start.language_set", Language.EN)

    # Assert — a sentence with a visible placeholder beats no message at all.
    assert "{language}" in rendered
    assert any("missing_params" in record.getMessage() for record in caplog.records)


def test_missing_count_returns_the_key_name_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    translator = _lenient()

    # Act
    with caplog.at_level(logging.ERROR, logger="hbd.i18n.translator"):
        rendered = translator.translate("status.orders_found", Language.EN)

    # Assert
    assert rendered == "status.orders_found"
    assert any("missing_count" in record.getMessage() for record in caplog.records)


def test_unknown_language_degrades_to_the_key_name(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange — a translator built over a partial catalogue set.
    translator = Translator(catalogs={Language.EN: _catalogs()[Language.EN]}, is_strict=False)

    # Act
    with caplog.at_level(logging.ERROR, logger="hbd.i18n.translator"):
        rendered = translator.translate("common.yes", Language.RU)

    # Assert
    assert rendered == "common.yes"
    assert any("unknown_language" in record.getMessage() for record in caplog.records)


def test_missing_plural_form_degrades_to_the_key_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange — a hand-built catalogue that skipped the Russian 'many' form.
    partial = Catalog(language=Language.RU, entries={"x": {"one": "{count} набор"}})
    translator = Translator(catalogs={Language.RU: partial}, is_strict=False)

    # Act
    with caplog.at_level(logging.ERROR, logger="hbd.i18n.translator"):
        rendered = translator.translate("x", Language.RU, count=5)

    # Assert
    assert rendered == "x"
    assert any("missing_plural_form" in record.getMessage() for record in caplog.records)


def test_broken_template_returns_the_template_rather_than_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange — an unmatched brace is a format error at render time, not load time.
    broken = Catalog(language=Language.EN, entries={"x": "hello {0!z}"})
    translator = Translator(catalogs={Language.EN: broken}, is_strict=False)

    # Act
    with caplog.at_level(logging.ERROR, logger="hbd.i18n.translator"):
        rendered = translator.translate("x", Language.EN, name="a")

    # Assert
    assert rendered == "hello {0!z}"
    assert any("format_failed" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# Errors -> friendly copy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "error",
    [
        ValidationError("bad input"),
        ProviderTimeoutError("slow", provider="elevenlabs"),
        ProviderRateLimitedError("429", provider="elevenlabs"),
        NameVerificationExhaustedError("gave up after 3"),
        DeliveryError("telegram rejected"),
        PaymentError("declined"),
    ],
)
@pytest.mark.parametrize("language", list(Language))
def test_every_error_renders_a_friendly_sentence(error: HbdError, language: Language) -> None:
    # Act
    message = translate_error(error, language)

    # Assert
    assert message
    assert message != error.user_message_key
    assert error.operator_message not in message


def test_error_with_an_unknown_key_falls_back_to_the_generic_message() -> None:
    # Arrange
    error = ValidationError("boom", user_message_key="error.not_in_any_catalogue")
    translator = _lenient()

    # Act
    message = translator.error_message(error, Language.EN)

    # Assert
    assert message == translator.translate(GENERIC_USER_MESSAGE_KEY, Language.EN)


def test_unknown_error_key_is_loud_in_strict_mode() -> None:
    # Arrange
    error = ValidationError("boom", user_message_key="error.not_in_any_catalogue")

    # Act / Assert
    with pytest.raises(ValidationError, match="unknown_error_key"):
        _strict().error_message(error, Language.EN)


# ---------------------------------------------------------------------------
# Strictness selection
# ---------------------------------------------------------------------------
def test_strict_env_var_overrides_the_pytest_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange / Act / Assert
    monkeypatch.setenv(STRICT_ENV_VAR, "0")
    assert is_strict_by_default() is False

    monkeypatch.setenv(STRICT_ENV_VAR, "TRUE")
    assert is_strict_by_default() is True


def test_defaults_to_lenient_outside_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv(STRICT_ENV_VAR, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Act / Assert
    assert is_strict_by_default() is False


def test_get_translator_is_a_process_singleton() -> None:
    assert get_translator() is get_translator()
