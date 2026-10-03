"""Signature verification for Rahmat / MultiCard webhooks.

Multicard/Rahmat supports two signature schemes:
  1. 'webhooks' (recommended): sha1(uuid + invoice_id + amount + secret)
  2. 'success' (legacy):        md5(store_id + invoice_id + amount + secret)

Both amounts are formatted as integer tiyin (e.g. 700000).
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from bayram.rhmt.ports import DEFAULT_CALLBACK_SCHEME, RhmtCallbackScheme

__all__ = ["verify_rhmt_webhook"]


def verify_rhmt_webhook(
    payload: dict[str, Any],
    *,
    secret: str,
    scheme: str | RhmtCallbackScheme = DEFAULT_CALLBACK_SCHEME,
) -> bool:
    """Verify that an inbound callback from Rahmat was signed with ``secret``.

    Returns False immediately if secret is blank, sign is missing, or the signature
    does not match. Case-insensitive comparison via hmac.compare_digest.
    """
    if not secret:
        return False

    sign = str(payload.get("sign") or "").strip()
    if not sign:
        return False

    invoice_id = str(payload.get("invoice_id") or "")
    amount_raw = payload.get("amount")
    try:
        amount_int = int(amount_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False

    scheme_str = scheme.value if isinstance(scheme, RhmtCallbackScheme) else str(scheme).lower()

    if scheme_str == RhmtCallbackScheme.SUCCESS.value:
        store_id = str(payload.get("store_id") or "")
        sign_string = f"{store_id}{invoice_id}{amount_int}{secret}"
        expected = hashlib.md5(sign_string.encode("utf-8")).hexdigest()
    else:
        uuid = str(payload.get("uuid") or "")
        sign_string = f"{uuid}{invoice_id}{amount_int}{secret}"
        expected = hashlib.sha1(sign_string.encode("utf-8")).hexdigest()

    return hmac.compare_digest(expected.lower(), sign.lower())
