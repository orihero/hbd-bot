"""The checkout link: one published golden vector, and the four ways to get it wrong.

This file is unusual in that ONE of its assertions is checked against an external authority
and the rest are checked against reasoning. Payme publishes exactly one worked example of the
link transform, and :func:`test_the_published_golden_vector_encodes_byte_for_byte` pins it.
Everything else here pins a decision — the unmultiplied amount, the four-onto-three language
collapse, the omitted ``c``, the stable parameter order — and each of those decisions is one a
reasonable person makes the other way.

**The hundred-fold test is the one to read first.** ``a`` is in tiyin and
``single_song_price_minor`` is ALREADY in tiyin, so the correct implementation multiplies by
nothing. Every payment tutorial in the world converts major units to minor at exactly this
point, the conversion is one character, and the result is a customer presented with a bill for
7 000 000 so'm instead of 7 000. It would pass code review, it would pass a link that renders,
and it would be caught by a human reading a payment page. That is why it has a test with the
bug in its name.

Nothing here touches the network. The sandbox echo at ``https://test.paycom.uz/<base64>`` will
decode one of these blobs and print what it parsed, which is how the parser facts in
``bayram.payme.link``'s docstring were established, but a unit suite that reached for it would be
a unit suite that fails when a third party has an outage.
"""

from __future__ import annotations

import base64
from typing import Final

import pytest

from bayram.contracts import Language
from bayram.payme.link import (
    LANGUAGE_PARAM,
    PARAMETER_SEPARATOR,
    PROD_CHECKOUT_URL,
    SANDBOX_CHECKOUT_URL,
    UZS_CURRENCY_CODE,
    build_checkout_link,
    encode_payload,
    resolve_base_url,
)

#: Payme's own published example, verbatim. Both halves are quoted from the documentation and
#: neither was computed by this repository — that is the entire value of the pair.
_GOLDEN_PAYLOAD: Final[str] = "m=587f72c72cac0d162c722ae2;ac.order_id=197;a=500"
_GOLDEN_BLOB: Final[str] = "bT01ODdmNzJjNzJjYWMwZDE2MmM3MjJhZTI7YWMub3JkZXJfaWQ9MTk3O2E9NTAw"

#: A plausible cashbox id and one of our own opaque references. 24 lowercase hex characters
#: each, which is what ``secrets.token_hex(12)`` mints and what Payme's ObjectIds look like.
_MERCHANT_ID: Final[str] = "587f72c72cac0d162c722ae2"
_PUBLIC_REF: Final[str] = "9f2c4d6a8b0e1f3c5d7a9b0c"

#: The shipped price of one song, in tiyin, as ``Settings.single_song_price_minor`` carries it.
_SINGLE_SONG_TIYIN: Final[int] = 700_000


def _decode(link: str, *, base_url: str = PROD_CHECKOUT_URL) -> str:
    """The parameter payload back out of a built link, as Payme's parser would see it.

    The blob is recovered by stripping the KNOWN base URL rather than by ``rsplit('/')``.
    Standard base64 — which the published golden vector confirms is the right alphabet — emits
    ``/`` and ``+``, so the last path segment of a link is not reliably the whole blob. That is
    not a defect in the format: everything after the host IS the blob, and a slash inside it is
    simply another character of it.
    """
    blob = link.removeprefix(f"{base_url.rstrip('/')}/")
    return base64.b64decode(blob).decode("utf-8")


def _split_pairs(payload: str) -> list[tuple[str, str]]:
    """A ``;``-joined payload as ordered pairs, split ONCE on ``=`` the way Payme splits it.

    A list, not a dict — the ORDER is part of the format and one test asserts it, so the
    conversion to a mapping happens per assertion rather than in the helper.
    """
    pairs: list[tuple[str, str]] = []
    for item in payload.split(PARAMETER_SEPARATOR):
        key, _, value = item.partition("=")
        pairs.append((key, value))
    return pairs


def _parameters(link: str) -> list[tuple[str, str]]:
    """The decoded payload of a built link, as ordered pairs."""
    return _split_pairs(_decode(link))


def _link(
    *,
    base_url: str = PROD_CHECKOUT_URL,
    merchant_id: str = _MERCHANT_ID,
    account_field: str = "order_id",
    public_ref: str = _PUBLIC_REF,
    amount_minor: int = _SINGLE_SONG_TIYIN,
    language: Language = Language.UZ_LATN,
    return_url: str = "",
) -> str:
    """One production link for a single song, with keyword overrides for the one field varied."""
    return build_checkout_link(
        base_url=base_url,
        merchant_id=merchant_id,
        account_field=account_field,
        public_ref=public_ref,
        amount_minor=amount_minor,
        language=language,
        return_url=return_url,
    )


def test_the_published_golden_vector_encodes_byte_for_byte() -> None:
    # Arrange — Payme's documented example. Nothing below was computed by this repository.

    # Act
    encoded = encode_payload(_GOLDEN_PAYLOAD)

    # Assert — the transform itself, then the whole URL the customer is sent to. Both halves
    # are quoted from the vendor's documentation, so this is the one assertion in the file
    # that is checked against an external authority rather than against our own reasoning.
    assert encoded == _GOLDEN_BLOB
    assert f"{PROD_CHECKOUT_URL}/{encoded}" == f"{PROD_CHECKOUT_URL}/{_GOLDEN_BLOB}"


def test_the_builder_reproduces_the_golden_vectors_leading_parameters() -> None:
    # Arrange — the golden vector's own inputs, put through the real builder. The published
    # example carries no ``l`` and no ``cr`` because it predates them; ours always does, so the
    # comparison is on the PREFIX. That is the honest form of this assertion: it proves the
    # builder agrees with Payme about the first three pairs and their order, and it does not
    # pretend the vendor published an example of parameters they never wrote down.

    # Act
    payload = _decode(
        _link(amount_minor=500, public_ref="197", account_field="order_id"),
    )

    # Assert
    assert payload.startswith(_GOLDEN_PAYLOAD)


def test_the_amount_is_passed_as_tiyin_unmultiplied() -> None:
    # Arrange — ``single_song_price_minor`` is ALREADY tiyin. See the module docstring: the
    # hundred-fold bug is one character, it renders a perfectly valid payment page, and it
    # bills a customer 7 000 000 so'm for a 7 000 so'm song.

    # Act
    parameters = dict(_parameters(_link(amount_minor=_SINGLE_SONG_TIYIN)))

    # Assert
    assert parameters["a"] == "700000"
    assert parameters["a"] != "70000000"


def test_all_four_bot_languages_collapse_onto_paymes_three() -> None:
    # Arrange — the bot offers Uzbek in two scripts because a Cyrillic-Uzbek reader is not a
    # Russian speaker; Payme's ``l`` has no slot for the distinction.

    # Act
    emitted = {language: dict(_parameters(_link(language=language)))["l"] for language in Language}

    # Assert — every language is answered for, three values are used, and the one genuinely
    # wrong answer (Cyrillic Uzbek handed a Russian page on the strength of its alphabet) is
    # asserted against by name.
    assert set(emitted) == set(Language), "a new interface language must be mapped explicitly"
    assert set(emitted.values()) == {"uz", "ru", "en"}
    assert emitted[Language.UZ_CYRL] == "uz"
    assert emitted[Language.UZ_LATN] == "uz"
    assert LANGUAGE_PARAM[Language.UZ_CYRL] != "ru"


def test_a_blank_return_url_omits_the_c_parameter_entirely() -> None:
    # Arrange / Act — the default, which is what ships: no return URL configured.
    without = dict(_parameters(_link()))
    with_url = dict(_parameters(_link(return_url="https://t.me/bayram_uzbot?start=paid")))

    # Assert — absent, not empty. ``c=`` is a value: Payme would carry an empty callback and
    # redirect the customer to nothing at the end of a successful payment, whereas no ``c`` at
    # all is a fully working payment that simply does not bounce them back.
    assert "c" not in without
    assert with_url["c"] == "https://t.me/bayram_uzbot?start=paid"


def test_the_return_url_is_passed_raw_and_never_percent_encoded() -> None:
    # Arrange — Payme's parser does NOT decode percent-encoding, so a ``quote()``-ed callback
    # arrives at the browser still escaped and the deep link is dead. This is the one place in
    # the codebase where the instinct to encode a URL parameter is wrong.
    deep_link = "https://t.me/bayram_uzbot?start=paid&ref=abc"

    # Act
    parameters = dict(_parameters(_link(return_url=deep_link)))

    # Assert
    assert parameters["c"] == deep_link
    assert "%3F" not in parameters["c"]
    assert "%26" not in parameters["c"]


def test_a_semicolon_in_a_value_would_truncate_it_which_is_why_settings_refuse_one() -> None:
    # Arrange — the hazard this test documents is Payme's, not ours: there is no escaping
    # mechanism, so a ``;`` inside a value silently ends that value. The builder is pure and
    # total and cannot refuse anything; the refusal lives on ``BAYRAM_PAYME_RETURN_URL`` at
    # settings-build time. This test exists so the reason that validator exists is written
    # down HERE, next to the code whose behaviour makes it necessary.
    hostile = "https://example.test/?a=1;b=2"

    # Act
    parsed = dict(_split_pairs(_decode(_link(return_url=hostile))))

    # Assert — reparsed the way Payme reparses it, the callback has lost everything after the
    # semicolon and a stray ``b`` parameter has appeared. Nothing raised, nothing logged: this
    # is precisely the silent failure the settings validator is there to make impossible.
    assert parsed["c"] == "https://example.test/?a=1"
    assert parsed["b"] == "2"


def test_the_encoded_blob_decodes_back_to_a_stable_parameter_order() -> None:
    # Arrange — a replayed ``open_intent`` returns the same ``public_ref``, so it must produce
    # the byte-identical link. Two different-looking URLs for one purchase in one chat leave
    # the customer to guess which one their money went into.

    # Act
    first = _link(return_url="https://t.me/bayram_uzbot?start=paid")
    second = _link(return_url="https://t.me/bayram_uzbot?start=paid")

    # Assert
    assert first == second
    assert [key for key, _ in _parameters(first)] == ["m", "ac.order_id", "a", "l", "cr", "c"]


def test_the_account_field_name_is_configurable_because_a_human_types_it_into_a_web_form() -> None:
    # Arrange — the cabinet's «Настройка Аккаунт» field name is entered by hand on Payme's side
    # and must equal ``BAYRAM_PAYME_ACCOUNT_FIELD``. A mismatch is the likeliest go-live defect.

    # Act
    parameters = dict(_parameters(_link(account_field="bayram_ref")))

    # Assert
    assert parameters["ac.bayram_ref"] == _PUBLIC_REF
    assert "ac.order_id" not in parameters


def test_the_currency_is_the_iso_numeric_code_and_ct_is_never_emitted() -> None:
    # Arrange / Act
    parameters = dict(_parameters(_link()))

    # Assert — ``cr`` is 860, the ISO-4217 NUMERIC for the so'm, because that is the form this
    # parameter takes; and ``ct`` is absent by decision, because its documented default's unit
    # is not credible and a lifetime wrong by a factor of a thousand either kills every link
    # before it is opened or contradicts the twelve-hour window the transaction runs on.
    assert parameters["cr"] == str(UZS_CURRENCY_CODE) == "860"
    assert "ct" not in parameters


@pytest.mark.parametrize(
    ("is_sandbox", "override", "expected"),
    [
        (False, "", PROD_CHECKOUT_URL),
        (True, "", SANDBOX_CHECKOUT_URL),
        (False, "https://checkout.example.test", "https://checkout.example.test"),
        (True, "https://checkout.example.test", "https://checkout.example.test"),
    ],
)
def test_the_base_url_falls_back_to_the_constants_and_an_override_always_wins(
    *, is_sandbox: bool, override: str, expected: str
) -> None:
    # Arrange / Act
    resolved = resolve_base_url(is_sandbox=is_sandbox, override=override)

    # Assert — blank means "use the constants", so the shipped configuration names no hostname
    # and the two constants stay the single place the real ones are written down. The override
    # exists because Payme has moved this host before and a rail repointable only by a release
    # is a rail that is down for as long as a release takes.
    assert resolved == expected


def test_a_trailing_slash_on_the_base_url_never_produces_a_double_slash() -> None:
    # Arrange — an operator pasting a hostname out of the documentation brings the slash with
    # them. ``https://checkout.paycom.uz//<blob>`` is a different path and Payme 404s it.

    # Act
    link = _link(base_url=f"{PROD_CHECKOUT_URL}/")

    # Assert — the built link is identical to the one built from the un-slashed host. The
    # second assertion is written against the HOST and not against the whole string on purpose:
    # a base64 blob may legitimately contain ``//``, so a blanket "no double slash" check would
    # be a test that fails on one input in sixty-four for a reason unrelated to its subject.
    assert link == _link()
    assert f"{PROD_CHECKOUT_URL}//" not in link
