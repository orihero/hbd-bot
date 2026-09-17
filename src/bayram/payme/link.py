"""The checkout link. **It is CONSTRUCTED, not requested — this module opens no socket.**

That is the single most surprising true claim in this integration, so it goes first: Payme has
no create-payment-link API for the standard checkout. There is nothing to POST to and nothing
to await. A redirect rail, on this rail, is a semicolon-joined string of ``key=value`` pairs,
base64-encoded and hung off a hostname. Every other vendor adapter in this repository owns a
pooled ``httpx.AsyncClient``; this one has no counterpart, and ``bayram.payme.provider`` carries a
test that scans its own attributes to make sure nobody quietly adds one.

**Three properties of Payme's parser are verified facts, and each is enforced here.** They
were established against the unauthenticated echo at ``https://test.paycom.uz/<base64>``,
which decodes a blob and prints what it parsed — a free conformance test against the real
parser, available before Payme has heard our name.

1. **A ``;`` anywhere inside a VALUE silently truncates that value.** There is no escaping
   mechanism. Two consequences, and they are handled in two different places because they have
   two different owners: the account value is ``public_ref``, minted as 24 lowercase hex
   characters by ``secrets.token_hex(12)``, so it is incapable of containing one; and the
   return URL is operator-supplied, so it is refused at settings-build time
   (``BAYRAM_PAYME_RETURN_URL``, WS-G) rather than here. This function is total and cannot fail,
   which means the guard has to be somewhere a failure can be reported — and a configuration
   error reported at boot is worth a hundred reported at 2 a.m. per payment.
2. **Percent-encoding is NOT decoded.** Payme's parser hands the value through verbatim, so a
   ``quote()``-ed return URL arrives at the browser still escaped and the deep link is dead.
   The URL is therefore passed RAW and nothing in this module encodes anything but the final
   base64. Resist the instinct; it is the wrong instinct exactly once, here.
3. **``ct`` is deliberately never emitted.** It is documented as a link lifetime with a default
   whose unit is not credible in the published material, and a lifetime we get wrong by a
   factor of a thousand either expires every link before the customer opens it or contradicts
   the twelve-hour window the transaction actually runs on. Our own ``valid_until`` is the
   clock that matters and it is enforced on our side, where we can read it.

**Everything here is pure and total.** No clock, no I/O, no ``Result``, no configuration read.
Given the same arguments it returns the same string forever, which is what lets a replayed
``open_intent`` — same key, same ``public_ref`` — produce the byte-identical URL a customer may
already have open in a browser tab.

See ``PAYME_INTEGRATION §1`` for why ``charge`` opens no socket.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from bayram.contracts import Language

__all__ = [
    "PROD_CHECKOUT_URL",
    "SANDBOX_CHECKOUT_URL",
    "UZS_CURRENCY_CODE",
    "LANGUAGE_PARAM",
    "PARAMETER_SEPARATOR",
    "ACCOUNT_PREFIX",
    "encode_payload",
    "build_checkout_link",
    "resolve_base_url",
]

#: Where a real customer's card is charged.
PROD_CHECKOUT_URL: Final[str] = "https://checkout.paycom.uz"

#: The test environment. Also the unauthenticated echo endpoint that made this module
#: certifiable before any credential existed: it decodes a blob and prints what it parsed.
SANDBOX_CHECKOUT_URL: Final[str] = "https://test.paycom.uz"

#: ISO-4217 numeric for the Uzbek so'm, sent as ``cr``. Numeric rather than the alphabetic
#: ``UZS`` because that is the form Payme's parameter takes; the intent stores the alphabetic
#: code, because that is the form ``bayram.checkout.Purchase.currency`` and every receipt column
#: in this system already use, and neither should be converted into the other anywhere but
#: here.
UZS_CURRENCY_CODE: Final[int] = 860

#: The pair separator. Not configurable and not escapable — see parser fact 1 above.
PARAMETER_SEPARATOR: Final[str] = ";"

#: Every account subfield is sent under this prefix: ``ac.order_id=...``. The part after the
#: dot is what a human typed into the cabinet's «Настройка Аккаунт» form, which is why it is a
#: parameter of :func:`build_checkout_link` and not a constant.
ACCOUNT_PREFIX: Final[str] = "ac."

#: The bot's FOUR interface languages collapsed onto Payme's THREE.
#:
#: Uzbek is offered here in both scripts because a customer who reads Cyrillic Uzbek is not a
#: Russian speaker and being handed Russian is the exact failure this product exists to avoid.
#: Payme's ``l`` parameter has no slot for that distinction — it accepts ``ru``, ``uz`` and
#: ``en`` and nothing else — so both Uzbek scripts map to ``uz`` and the customer sees Payme's
#: own Latin Uzbek. Mapping ``UZ_CYRL`` to ``ru`` would be the tempting alternative and it is
#: the one genuinely wrong answer: it would hand a Cyrillic-Uzbek reader a Russian payment page
#: on the strength of their alphabet.
#:
#: A ``Mapping`` over a total, explicit dict rather than a ``.get()`` with a fallback: a
#: language added to ``bayram.contracts.Language`` must be answered for here, and a ``KeyError``
#: in a test is how it gets answered for. A silent default would ship an English payment page
#: to whoever the fifth language was added for.
LANGUAGE_PARAM: Final[Mapping[Language, str]] = MappingProxyType(
    {
        Language.UZ_LATN: "uz",
        Language.UZ_CYRL: "uz",
        Language.RU: "ru",
        Language.EN: "en",
    }
)


def encode_payload(payload: str) -> str:
    """Base64 of ``payload``, with standard padding and the standard alphabet.

    Split out from :func:`build_checkout_link` for one reason, and it is a testing reason worth
    the extra name: Payme publishes exactly ONE worked example of this transform —
    ``m=587f72c72cac0d162c722ae2;ac.order_id=197;a=500`` becomes
    ``bT01ODdmNzJjNzJjYWMwZDE2MmM3MjJhZTI7YWMub3JkZXJfaWQ9MTk3O2E9NTAw`` — and that example
    carries neither ``l`` nor ``cr``, which we always send. Pinning the golden vector against
    the full builder would therefore mean pinning a payload of our own invention against a
    number we computed ourselves, which proves the encoder agrees with itself. Pinning it here
    proves the encoder agrees with PAYME.

    Standard padding, not URL-safe base64 and not stripped padding: the documented vector ends
    in a padded quartet and the path segment is not further encoded. The standard alphabet
    emits ``/`` and ``+``, so a link's blob is NOT reliably its last path segment — everything
    after the host is the blob, and a slash inside it is just another character of it. That is
    worth knowing before writing any code that tries to take a link apart again.
    """
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def _payload(pairs: Sequence[tuple[str, str]]) -> str:
    """``key=value`` pairs joined with ``;``, in the order given. Order is part of the format."""
    return PARAMETER_SEPARATOR.join(f"{key}={value}" for key, value in pairs)


def build_checkout_link(
    *,
    base_url: str,
    merchant_id: str,
    account_field: str,
    public_ref: str,
    amount_minor: int,
    language: Language,
    return_url: str = "",
) -> str:
    """The URL to send a customer to. Pure, total, and the same string every time.

    Parameter order is FIXED — ``m``, ``ac.<field>``, ``a``, ``l``, ``cr``, then ``c`` — and it
    is fixed on purpose rather than because the parser demands it. A stable order means the
    encoded blob is a deterministic function of its inputs, which in turn means a replayed
    ``open_intent`` (same idempotency key, same ``public_ref``) produces the byte-identical
    link a customer may already have open in a browser tab. An order that varied would put two
    different-looking URLs for one purchase in one chat and leave the customer to guess.

    ``amount_minor`` is written out **verbatim, in tiyin**. Nothing on this path multiplies by
    100: ``single_song_price_minor = 700_000`` IS the number Payme is sent, and the settlement
    compares Payme's integer against the stored integer with no arithmetic in between. The one
    hundred-fold bug this comment exists to prevent is a customer charged 7 000 000 so'm for a
    7 000 so'm song, and it has a test named after it.

    ``c`` — the return URL — is omitted ENTIRELY when ``return_url`` is empty, rather than sent
    as ``c=``. An empty value is a value: Payme's parser would carry an empty callback and the
    customer would be redirected to nothing at the end of a successful payment. Settlement never
    depends on the customer coming back, so an absent ``c`` is a fully working payment; a blank
    one is a broken landing.
    """
    pairs: list[tuple[str, str]] = [
        ("m", merchant_id),
        (f"{ACCOUNT_PREFIX}{account_field}", public_ref),
        ("a", str(amount_minor)),
        ("l", LANGUAGE_PARAM[language]),
        ("cr", str(UZS_CURRENCY_CODE)),
    ]
    if return_url:
        # Raw, never quoted — see parser fact 2. A ``;`` here would truncate the callback
        # silently, which is why ``BAYRAM_PAYME_RETURN_URL`` refuses one at settings-build time.
        pairs.append(("c", return_url))
    return f"{base_url.rstrip('/')}/{encode_payload(_payload(pairs))}"


def resolve_base_url(*, is_sandbox: bool, override: str) -> str:
    """Which checkout host to build against: an explicit override, else sandbox or production.

    The override exists for one situation and it is not developer convenience: Payme has moved
    this hostname before, and a rail that can only be repointed by a release is a rail that is
    down for as long as a release takes. Blank means "use the constants", so the shipped
    configuration names no hostname at all and the two constants above stay the single place
    the real ones are written down.

    ``is_sandbox`` is read from the INTENT at settlement time and from settings at link-build
    time, and those are deliberately two different reads of the same idea: the intent records
    which environment its link was built for, so an old sandbox link cannot be settled against
    a production cashbox after somebody flips a setting.
    """
    if override:
        return override
    return SANDBOX_CHECKOUT_URL if is_sandbox else PROD_CHECKOUT_URL
