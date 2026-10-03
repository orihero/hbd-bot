"""Tests for Rahmat webhook signature verification."""

from __future__ import annotations

import hashlib

from bayram.rhmt.ports import RhmtCallbackScheme
from bayram.rhmt.verify import verify_rhmt_webhook


def test_verify_webhooks_scheme_sha1_valid() -> None:
    uuid = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    invoice_id = "inv_123456"
    amount = 700000
    secret = "rhmt_secret_test_xyz"

    sign_str = f"{uuid}{invoice_id}{amount}{secret}"
    valid_sign = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()

    payload = {
        "uuid": uuid,
        "invoice_id": invoice_id,
        "amount": amount,
        "sign": valid_sign,
        "status": 1,
    }

    assert verify_rhmt_webhook(payload, secret=secret, scheme=RhmtCallbackScheme.WEBHOOKS) is True
    assert verify_rhmt_webhook(payload, secret=secret, scheme="webhooks") is True
    # Case-insensitive
    payload["sign"] = valid_sign.upper()
    assert verify_rhmt_webhook(payload, secret=secret) is True


def test_verify_success_scheme_md5_valid() -> None:
    store_id = 1001
    invoice_id = "inv_9999"
    amount = 4900000
    secret = "rhmt_secret_legacy"

    sign_str = f"{store_id}{invoice_id}{amount}{secret}"
    valid_sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    payload = {
        "store_id": store_id,
        "invoice_id": invoice_id,
        "amount": amount,
        "sign": valid_sign,
    }

    assert verify_rhmt_webhook(payload, secret=secret, scheme=RhmtCallbackScheme.SUCCESS) is True
    assert verify_rhmt_webhook(payload, secret=secret, scheme="success") is True


def test_verify_tampered_amount_fails() -> None:
    uuid = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    invoice_id = "inv_123456"
    amount = 700000
    secret = "rhmt_secret_test_xyz"

    sign_str = f"{uuid}{invoice_id}{amount}{secret}"
    valid_sign = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()

    payload = {
        "uuid": uuid,
        "invoice_id": invoice_id,
        "amount": 700001,  # tampered
        "sign": valid_sign,
    }
    assert verify_rhmt_webhook(payload, secret=secret) is False


def test_verify_tampered_secret_fails() -> None:
    uuid = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    invoice_id = "inv_123456"
    amount = 700000
    secret = "rhmt_secret_test_xyz"

    sign_str = f"{uuid}{invoice_id}{amount}{secret}"
    valid_sign = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()

    payload = {
        "uuid": uuid,
        "invoice_id": invoice_id,
        "amount": amount,
        "sign": valid_sign,
    }
    assert verify_rhmt_webhook(payload, secret="wrong_secret") is False


def test_verify_empty_secret_fails() -> None:
    payload = {
        "uuid": "abc",
        "invoice_id": "123",
        "amount": 1000,
        "sign": "anything",
    }
    assert verify_rhmt_webhook(payload, secret="") is False


def test_verify_missing_or_empty_sign_fails() -> None:
    payload = {
        "uuid": "abc",
        "invoice_id": "123",
        "amount": 1000,
    }
    assert verify_rhmt_webhook(payload, secret="secret") is False

    payload["sign"] = "   "
    assert verify_rhmt_webhook(payload, secret="secret") is False


def test_verify_invalid_amount_fails() -> None:
    payload = {
        "uuid": "abc",
        "invoice_id": "123",
        "amount": "not-a-number",
        "sign": "abc",
    }
    assert verify_rhmt_webhook(payload, secret="secret") is False
