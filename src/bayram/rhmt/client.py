"""The outbound HTTP client for the Rahmat / MultiCard REST API.

Handles:
  - Token authentication: POST /auth {application_id, secret}
  - Bearer token caching with early refresh (-60s)
  - 401 recovery (token invalidation and single retry)
  - Invoice creation: POST /payment/invoice
  - Payment status lookup: GET /payment/{uuid}

Amounts are always in UZS tiyin (minor units, 1 UZS = 100 tiyin) end-to-end.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from time import time
from typing import Any, Final

import httpx

from bayram.contracts import Err, Result, err, ok
from bayram.errors import PaymentError
from bayram.logging import get_logger
from bayram.rhmt.ports import RHMT_PROD_BASE_URL, RHMT_SANDBOX_BASE_URL

__all__ = ["RhmtClient", "RhmtInvoice", "DEFAULT_TIMEOUT_S"]

_LOG = get_logger(__name__)

DEFAULT_TIMEOUT_S: Final[float] = 10.0
_REFRESH_LEAD_TIME_S: Final[int] = 60


@dataclass(frozen=True, slots=True)
class RhmtInvoice:
    """An invoice created at Rahmat, holding the checkout URL to redirect the customer to."""

    uuid: str
    invoice_id: str
    amount_minor: int
    checkout_url: str
    status: str
    raw: dict[str, Any]


class RhmtClient:
    """Async client communicating with the Rahmat / MultiCard REST API.

    Cached bearer token is refreshed automatically. A 401 response forces a fresh token
    and retries the request exactly once.
    """

    def __init__(
        self,
        *,
        application_id: str,
        secret: str,
        base_url: str = RHMT_PROD_BASE_URL,
        is_sandbox: bool = False,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._application_id = application_id.strip()
        self._secret = secret.strip()
        default_url = RHMT_SANDBOX_BASE_URL if is_sandbox else RHMT_PROD_BASE_URL
        self._base_url = (base_url or default_url).rstrip("/")
        self._timeout_s = timeout_s
        self._http = http_client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_http = http_client is None

        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return self._base_url

    async def authenticate(self, *, force_refresh: bool = False) -> Result[str]:
        """Obtain or return a valid cached bearer token."""
        async with self._lock:
            now = time()
            lead_time = self._token_expires_at - _REFRESH_LEAD_TIME_S
            if not force_refresh and self._token and now < lead_time:
                return ok(self._token)

            url = f"{self._base_url}/auth"
            payload = {
                "application_id": self._application_id,
                "secret": self._secret,
            }
            try:
                response = await self._http.post(url, json=payload)
            except Exception as exc:
                _LOG.error(
                    "failed to connect to rahmat auth endpoint",
                    extra={"error": str(exc), "url": url},
                )
                return err(PaymentError(f"Rahmat auth network error: {exc}", context={"url": url}))

            if response.status_code != 200:
                _LOG.error(
                    "rahmat auth returned non-200 status",
                    extra={"status_code": response.status_code, "body": response.text[:200]},
                )
                return err(
                    PaymentError(
                        f"Rahmat auth failed with status {response.status_code}",
                        context={"status_code": response.status_code},
                    )
                )

            try:
                body = response.json()
            except Exception as exc:
                return err(PaymentError(f"Rahmat auth response is not JSON: {exc}"))

            token = body.get("token")
            if not token:
                return err(
                    PaymentError(
                        "Rahmat auth response contained no token",
                        context={"body": body},
                    )
                )

            self._token = str(token)
            # Multicard expiry format: "YYYY-MM-DD HH:MM:SS" in GMT+5
            expiry_str = body.get("expiry")
            self._token_expires_at = self._parse_expiry(expiry_str, fallback_seconds=3600)

            _LOG.info(
                "rahmat authenticated successfully",
                extra={"expires_at": self._token_expires_at},
            )
            return ok(self._token)

    async def create_invoice(
        self,
        *,
        store_id: int,
        amount_minor: int,
        invoice_id: str,
        callback_url: str,
        return_url: str,
        language: str = "uz",
        ofd: list[dict[str, Any]] | None = None,
        ttl_s: int | None = None,
    ) -> Result[RhmtInvoice]:
        """Create a payment invoice at Rahmat and receive the checkout URL.

        Amount must be in tiyins (integer).
        """
        payload: dict[str, Any] = {
            "store_id": int(store_id),
            "amount": int(amount_minor),
            "invoice_id": str(invoice_id),
            "callback_url": callback_url,
            "lang": _checkout_lang(language),
        }
        if ttl_s is not None:
            payload["ttl"] = int(ttl_s)
        # Omitted when blank (the boot could not learn the bot's username) rather than sent empty.
        if return_url.strip():
            payload["return_url"] = return_url
        if ofd is not None:
            payload["ofd"] = ofd

        resp = await self._request("POST", "/payment/invoice", json_payload=payload)
        if isinstance(resp, Err):
            return resp

        body = resp.value
        raw_data = body.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else body

        uuid = data.get("uuid")
        checkout_url = data.get("checkout_url")
        if not uuid or not checkout_url:
            return err(
                PaymentError(
                    "Rahmat invoice creation returned missing uuid or checkout_url",
                    context={"response": body},
                )
            )

        invoice = RhmtInvoice(
            uuid=str(uuid),
            invoice_id=str(data.get("invoice_id") or invoice_id),
            amount_minor=int(data.get("amount") or amount_minor),
            checkout_url=str(checkout_url),
            status=str(data.get("status") or "draft"),
            raw=body,
        )
        return ok(invoice)

    async def get_payment(self, uuid: str) -> Result[dict[str, Any]]:
        """Query payment status by payment uuid."""
        return await self._request("GET", f"/payment/{uuid}")

    async def aclose(self) -> None:
        """Close underlying HTTP client if owned."""
        if self._owns_http:
            await self._http.aclose()

    # --- Internals ---

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> Result[dict[str, Any]]:
        """Call an authenticated Rahmat endpoint with 401 token refresh retry."""
        token_res = await self.authenticate()
        if isinstance(token_res, Err):
            return token_res
        token = token_res.value

        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Access-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = await self._http.request(method, url, json=json_payload, headers=headers)
        except Exception as exc:
            _LOG.error(
                "rahmat request network failure",
                extra={"method": method, "url": url, "error": str(exc)},
            )
            return err(PaymentError(f"Rahmat API network error: {exc}", context={"url": url}))

        if response.status_code == 401:
            # Drop token and retry once
            _LOG.warning(
                "rahmat returned 401, refreshing token and retrying once",
                extra={"url": url},
            )
            token_res = await self.authenticate(force_refresh=True)
            if isinstance(token_res, Err):
                return token_res
            token = token_res.value
            headers["Authorization"] = f"Bearer {token}"
            headers["X-Access-Token"] = token
            try:
                response = await self._http.request(method, url, json=json_payload, headers=headers)
            except Exception as exc:
                return err(
                    PaymentError(
                        f"Rahmat API retry network error: {exc}",
                        context={"url": url},
                    )
                )

        try:
            body = response.json()
        except Exception as exc:
            return err(
                PaymentError(
                    f"Rahmat returned non-JSON response ({response.status_code}): {exc}",
                    context={"status_code": response.status_code, "text": response.text[:200]},
                )
            )

        if not response.is_success or (isinstance(body, dict) and body.get("success") is False):
            error_msg = "Rahmat request failed"
            if isinstance(body, dict) and "error" in body:
                err_data = body["error"]
                if isinstance(err_data, dict):
                    error_msg = err_data.get("details") or err_data.get("code") or error_msg
                else:
                    error_msg = str(err_data)
            return err(
                PaymentError(
                    error_msg,
                    context={"status_code": response.status_code, "body": body},
                )
            )

        return ok(body)

    @staticmethod
    def _parse_expiry(expiry_str: str | None, *, fallback_seconds: int = 3600) -> float:
        """Parse Multicard's 'YYYY-MM-DD HH:MM:SS' into unix timestamp."""
        now = time()
        if not expiry_str:
            return now + fallback_seconds
        try:
            dt = datetime.strptime(str(expiry_str).strip(), "%Y-%m-%d %H:%M:%S")
            # Assume Tashkent time (UTC+5)
            tz_offset = UTC
            # Convert to timestamp
            ts = dt.replace(tzinfo=tz_offset).timestamp() - (5 * 3600)
            return ts if ts > now else now + fallback_seconds
        except Exception:
            return now + fallback_seconds


def _checkout_lang(language: str) -> str:
    """Multicard's checkout page speaks ru, uz and en; Uzbek in either script is ``uz``."""
    if language.startswith("ru"):
        return "ru"
    if language.startswith("en"):
        return "en"
    return "uz"
