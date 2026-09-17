"""Our link, parsed by PAYME's own parser. The only test here that touches the network.

**Why this test is worth its marker.** ``tests/test_payme/test_link.py`` pins the builder
against Payme's one published worked example and against itself: it proves the encoder is
deterministic and that it agrees with the single vector in the documentation. What it cannot
prove is what Payme's parser does with the parameters that vector does not contain — ``l``,
``cr`` and above all ``c``, the return URL — because the documentation describes that parser in
prose and the prose is wrong about at least two things.

``https://test.paycom.uz/<base64>`` decodes a blob and echoes what it parsed, as JSON, in a
``window['formData']`` assignment, **with no authentication of any kind**. That makes Payme's
real parser a free conformance test available before Payme has heard our name, and it is the
single most valuable thing the research behind this integration turned up. It is why the two
parser facts encoded in ``bayram.payme.link`` are facts rather than beliefs.

**The three claims, each of which cost a real defect somewhere.**

1. Everything we send survives the round trip: the merchant id, the account subfield under the
   name the cabinet is configured with, the amount in TIYIN unmultiplied, the language and the
   currency.
2. A ``;`` anywhere inside a value silently TRUNCATES that value. There is no escape
   mechanism, no error and no warning — the truncated half simply never arrives. This is why
   ``BAYRAM_PAYME_RETURN_URL`` refuses a ``;`` at settings-build time and why ``public_ref`` is
   minted from a hex alphabet that cannot contain one.
3. Percent-encoding is NOT decoded. A ``quote()``-ed return URL arrives at the customer's
   browser still escaped and the deep link is dead. The URL is passed RAW, and the instinct to
   encode it is the wrong instinct exactly once, here.

**Marked ``integration`` and therefore OUT of ``make test``** (``pytest -m "not integration"``).
It needs the internet and nothing else — no credential, no cabinet, no merchant account — so
it is run deliberately with ``make test-all`` or
``pytest -m integration tests/test_payme/test_sandbox_link_live.py``.

A transport failure SKIPS rather than fails: the subject of these assertions is Payme's parser,
and a laptop on a train has nothing to say about it. An HTTP status that is not 200, or a page
with no ``formData`` in it, is a real failure — that would mean the echo we built this
conformance check on has changed shape, which is something we want to hear about.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

import httpx
import pytest

from bayram.contracts import Language
from bayram.payme.link import (
    SANDBOX_CHECKOUT_URL,
    UZS_CURRENCY_CODE,
    build_checkout_link,
    encode_payload,
)

pytestmark = pytest.mark.integration

#: Payme's own example merchant id. Public by nature — it is rendered in a browser address bar
#: on every checkout — and using theirs keeps this file from implying we have one yet.
_MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"
_ACCOUNT_FIELD: Final[str] = "order_id"
#: The shape ``secrets.token_hex(12)`` mints: 24 lowercase hex characters, incapable of holding
#: a ``;`` or an ``=`` and carrying no Telegram id.
_PUBLIC_REF: Final[str] = "9f3c1ab24e77d05c8b16aa42"
#: 7 000 so'm in TIYIN. **Not** multiplied by 100 anywhere on this path.
_AMOUNT_MINOR: Final[int] = 700_000
#: A real deep link back into the bot, with a query string and no ``;``.
_RETURN_URL: Final[str] = "https://t.me/bayram_uzbot?start=paid"

_TIMEOUT: Final[float] = 20.0

#: The echo assigns a JSON *string* to ``window['formData']``. The first assignment on the page
#: is the live one; a second copy appears inside a commented-out block of example markup, which
#: is why this is anchored and read non-greedily rather than searched for anywhere.
_FORM_DATA: Final[re.Pattern[str]] = re.compile(r"window\['formData'\]\s*=\s*'(.*?)';")


def _echo(url: str) -> dict[str, Any]:
    """GET the sandbox and return the ``data`` object it says it parsed.

    Follows redirects because the echo is a single-page application's bootstrap and the host
    has moved before — which is also why ``BAYRAM_PAYME_CHECKOUT_BASE_URL`` exists as an override.
    """
    try:
        response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
    except httpx.TransportError as exc:  # pragma: no cover - depends on the runner's network
        pytest.skip(f"no network to {SANDBOX_CHECKOUT_URL}: {exc}")
    assert response.status_code == 200, f"{response.status_code} from the sandbox echo"
    found = _FORM_DATA.search(response.text)
    assert found is not None, (
        "the sandbox page carries no window['formData'] — the free conformance echo this "
        "integration's parser facts were established against has changed shape"
    )
    payload: dict[str, Any] = json.loads(found.group(1))
    parsed: dict[str, Any] = payload["data"]
    return parsed


def test_paymes_own_parser_reads_back_every_parameter_we_encoded() -> None:
    """The whole receipt, round-tripped through the real parser. No credential involved."""
    # Arrange
    url = build_checkout_link(
        base_url=SANDBOX_CHECKOUT_URL,
        merchant_id=_MERCHANT,
        account_field=_ACCOUNT_FIELD,
        public_ref=_PUBLIC_REF,
        amount_minor=_AMOUNT_MINOR,
        language=Language.UZ_LATN,
        return_url=_RETURN_URL,
    )

    # Act
    parsed = _echo(url)

    # Assert
    assert parsed["merchant"] == _MERCHANT
    assert parsed["account"] == {_ACCOUNT_FIELD: _PUBLIC_REF}
    # A STRING on the way back, which is fine and is why nothing compares these two as text:
    # the integer is what our own settlement compares, and it compares it against the intent.
    assert int(parsed["amount"]) == _AMOUNT_MINOR
    assert parsed["lang"] == "uz"
    assert int(parsed["currency"]) == UZS_CURRENCY_CODE
    assert parsed["callback"] == _RETURN_URL


def test_the_return_url_survives_untruncated_and_unescaped() -> None:
    """The claim ``bayram.payme.link`` makes twice and the one a browser silently punishes."""
    # Arrange
    url = build_checkout_link(
        base_url=SANDBOX_CHECKOUT_URL,
        merchant_id=_MERCHANT,
        account_field=_ACCOUNT_FIELD,
        public_ref=_PUBLIC_REF,
        amount_minor=_AMOUNT_MINOR,
        language=Language.RU,
        return_url=_RETURN_URL,
    )

    # Act
    parsed = _echo(url)

    # Assert
    assert parsed["callback"] == _RETURN_URL
    assert "%3A" not in parsed["callback"]
    assert parsed["callback"].endswith("start=paid")


def test_a_semicolon_inside_a_value_is_silently_truncated_by_paymes_parser() -> None:
    """**Parser fact 1, asserted against the parser rather than against a belief.**

    There is no escaping mechanism and no error: the half after the ``;`` simply never arrives.
    This is the whole reason ``BAYRAM_PAYME_RETURN_URL`` refuses a ``;`` at settings-build time —
    a truncated deep link fails in a way nothing observes, on somebody else's phone.

    The blob is hand-built rather than produced by :func:`build_checkout_link`, because the
    builder cannot produce this input: the one value an operator controls is refused before it
    reaches it. What is under test here is Payme, not us.
    """
    # Arrange
    payload = (
        f"m={_MERCHANT};ac.{_ACCOUNT_FIELD}={_PUBLIC_REF};a={_AMOUNT_MINOR};l=uz;"
        f"cr={UZS_CURRENCY_CODE};c=https://t.me/bayram_uzbot?start=a;b=2"
    )
    url = f"{SANDBOX_CHECKOUT_URL}/{encode_payload(payload)}"

    # Act
    parsed = _echo(url)

    # Assert
    assert parsed["callback"] == "https://t.me/bayram_uzbot?start=a"
    assert "b=2" not in parsed["callback"]


def test_percent_encoding_is_not_decoded_by_paymes_parser() -> None:
    """**Parser fact 2.** A ``quote()``-ed URL arrives escaped, and the deep link is dead.

    Hand-built for the same reason as the test above: :func:`bayram.payme.link.build_checkout_link`
    deliberately encodes nothing but the final base64, so it cannot produce this input either.
    The test exists so that a future contributor who "fixes" the missing ``quote()`` has
    something that goes red.
    """
    # Arrange
    escaped = "https%3A%2F%2Ft.me%2Fbayram_bot%3Fstart%3Dpaid"
    payload = (
        f"m={_MERCHANT};ac.{_ACCOUNT_FIELD}={_PUBLIC_REF};a={_AMOUNT_MINOR};l=uz;"
        f"cr={UZS_CURRENCY_CODE};c={escaped}"
    )
    url = f"{SANDBOX_CHECKOUT_URL}/{encode_payload(payload)}"

    # Act
    parsed = _echo(url)

    # Assert
    assert parsed["callback"] == escaped


def test_an_amount_in_tiyin_is_never_multiplied_on_the_way_to_paymes_parser() -> None:
    """The hundred-fold bug, checked at the far end rather than in our own encoder.

    ``single_song_price_minor = 700_000`` IS the number Payme is sent. A customer charged
    7 000 000 so'm for a 7 000 so'm song is the specific outcome this asserts against, and
    asserting it here means the claim is checked against the system that would do the charging.
    """
    # Arrange
    url = build_checkout_link(
        base_url=SANDBOX_CHECKOUT_URL,
        merchant_id=_MERCHANT,
        account_field=_ACCOUNT_FIELD,
        public_ref=_PUBLIC_REF,
        amount_minor=_AMOUNT_MINOR,
        language=Language.EN,
        return_url="",
    )

    # Act
    parsed = _echo(url)

    # Assert
    assert parsed["amount"] == str(_AMOUNT_MINOR)
    assert parsed["amount"] != str(_AMOUNT_MINOR * 100)
    # A blank return URL omits ``c`` entirely rather than sending ``c=``: an empty callback is
    # a value, and it would redirect a paying customer to nothing.
    assert "callback" not in parsed
