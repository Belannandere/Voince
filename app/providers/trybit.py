"""Trybit payment provider.

Docs:
  https://docs.trybit.com/
  https://docs.trybit.com/api-reference-v2/authorization.md
  https://docs.trybit.com/api-reference-v2/h2h.md

CONFIRMED by public docs:
  - Auth header:     Authorization: Token <API_KEY>
  - Create invoice:  POST {base}/v2/invoice/create
  - Invoice info:    POST {base}/v2/invoice/merchant/info
  - Statuses:        created | paid | partial | overpaid | canceled

Postback verification:
  - Per third-party SDKs (Socket, GitHub, PyPI), Trybit sends the
    postback as a **JWT signed with HS256** using the "Secret Key"
    from the project dashboard. There is NO separate `signature`
    header; the token is embedded in the request.
  - This is NOT confirmed by official Trybit docs. If it turns out
    to be wrong, `verify_webhook_signature` will log enough
    information to adapt (see _debug_log_webhook).
  - Fail-closed: if no valid verification path is available, the
    webhook is rejected with 401.
"""

import base64
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.providers.base import PaymentError, PaymentProvider

logger = logging.getLogger("trybit")


class TrybitProvider(PaymentProvider):
    name = "trybit"

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        shop_id: str,
        webhook_secret: str = "",
        webhook_public_key: str = "",
    ) -> None:
        self._api_url = (api_url or "").strip().rstrip("/")
        # Sanitize: strip whitespace and drop non-ASCII (common copy-paste bug).
        self._api_key = (api_key or "").strip().encode("ascii", "ignore").decode("ascii")
        self._shop_id = (shop_id or "").strip().encode("ascii", "ignore").decode("ascii")
        self._webhook_secret = (webhook_secret or "").strip()
        self._webhook_public_key = webhook_public_key or ""

    # ---------- internals ----------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/json",
        }

    def _ensure_configured(self) -> None:
        if not self._api_key or not self._shop_id:
            raise PaymentError(
                "Trybit is not configured (missing TRYBIT_API_KEY / TRYBIT_SHOP_ID)."
            )

    @staticmethod
    def _unwrap(data: Any) -> dict[str, Any]:
        """Trybit v2 responses may come wrapped in different ways:

          - {"data": {...}}                    (some endpoints)
          - {"status": "...", "result": {...}} (CryptoCloud-style wrapper)
          - flat {...}                         (some endpoints)

        Accept all three shapes.
        """
        if not isinstance(data, dict):
            return {}
        # CryptoCloud-style wrapper: {"status": ..., "result": {...}}
        if isinstance(data.get("result"), dict):
            return data["result"]
        # Wrapper with "data"
        if isinstance(data.get("data"), dict):
            return data["data"]
        # Flat object
        return data

    # ---------- payment creation ----------

    async def create_payment(
        self,
        *,
        amount: float,
        order_id: str,
        email: str | None = None,
        purpose: str = "topup",
    ) -> dict[str, Any]:
        self._ensure_configured()

        url = f"{self._api_url}/v2/invoice/create"
        body: dict[str, Any] = {
            "shop_id": self._shop_id,
            "amount": round(float(amount), 2),
            "currency": "USD",
            "order_id": order_id,
            "add_fields": {"purpose": purpose},
        }
        if email:
            body["email"] = email

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=body, headers=self._headers())
            except httpx.HTTPError as exc:
                logger.error("[trybit] network error: %s", exc.__class__.__name__)
                raise PaymentError("Network error while talking to Trybit") from exc

        if resp.status_code >= 400:
            logger.error("[trybit] HTTP %s from /v2/invoice/create", resp.status_code)
            raise PaymentError(f"Trybit returned HTTP {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise PaymentError("Invalid JSON from Trybit") from exc

        payload = self._unwrap(data)
        uuid_value = payload.get("uuid") or payload.get("invoice_uuid")
        if not uuid_value:
            logger.error("[trybit] response missing uuid: keys=%s", list(payload))
            raise PaymentError("Trybit returned no invoice uuid")

        return {
            "provider_payment_id": str(uuid_value),
            "payment_url": payload.get("link") or payload.get("pay_url"),
            "raw": payload,
        }

    # ---------- status lookup ----------

    async def get_payment_status(self, provider_payment_id: str) -> dict[str, Any]:
        self._ensure_configured()

        url = f"{self._api_url}/v2/invoice/merchant/info"
        body = {"uuids": [provider_payment_id]}

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(url, json=body, headers=self._headers())
            except httpx.HTTPError as exc:
                logger.error("[trybit] network error: %s", exc.__class__.__name__)
                raise PaymentError("Network error while talking to Trybit") from exc

        if resp.status_code >= 400:
            raise PaymentError(f"Trybit returned HTTP {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise PaymentError("Invalid JSON from Trybit") from exc

        
        # Unwrap the same way as create_payment.
        inner = data
        if isinstance(data, dict):
            if isinstance(data.get("result"), list):
                inner = data["result"]
            elif isinstance(data.get("result"), dict):
                inner = data["result"]
            elif isinstance(data.get("data"), list):
                inner = data["data"]
            elif isinstance(data.get("data"), dict):
                inner = data["data"]

        if isinstance(inner, list) and inner:
            return inner[0] if isinstance(inner[0], dict) else {}
        if isinstance(inner, dict):
            return inner
        return {}

    # ---------- webhook verification ----------

    def verify_webhook_signature(
        self,
        raw_body: bytes,
        signature: str,
        headers: dict[str, str] | None = None,
    ) -> bool:
        """Verify a Trybit postback.

        Primary path: JWT-HS256 with the project Secret Key.
        Fallback path: RSA-SHA256 with the configured public key (kept
        for compatibility in case official docs contradict the SDKs).

        Fail-closed: if neither path succeeds, return False.

        Debug logging: safe metadata (header names, body size, JWT
        structure) is logged at WARNING level to aid adaptation if the
        format turns out to be different. Secret values are never logged.
        """
        # ---- Try JWT-HS256 first ----
        if self._webhook_secret:
            token = self._extract_jwt(raw_body, signature, headers)
            if token:
                payload = self._verify_jwt_hs256(token, self._webhook_secret)
                if payload is not None:
                    return True
                logger.warning(
                    "[trybit] webhook JWT found but signature invalid (HS256)"
                )

        # ---- Fallback: RSA-SHA256 over raw body ----
        if self._webhook_public_key and signature:
            if self._verify_rsa_sha256(raw_body, signature, self._webhook_public_key):
                return True

        # ---- Nothing worked ----
        self._debug_log_webhook(raw_body, signature, headers)
        return False

    # ---------- verification helpers ----------

    @staticmethod
    def _looks_like_jwt(value: str) -> bool:
        parts = value.split(".")
        return len(parts) == 3 and all(parts)

    def _extract_jwt(
        self,
        raw_body: bytes,
        signature: str,
        headers: dict[str, str] | None,
    ) -> str | None:
        """Locate a JWT token from common locations."""
        # 1) Explicit signature argument (some deployments pass it there)
        if signature and self._looks_like_jwt(signature):
            return signature.strip()

        # 2) Headers: Authorization: Bearer <jwt>, X-Token, X-JWT, etc.
        if headers:
            for name, value in headers.items():
                lname = name.lower()
                if lname in ("authorization", "x-token", "x-jwt", "x-signature", "signature"):
                    if not value:
                        continue
                    token = value.strip()
                    if token.lower().startswith("bearer "):
                        token = token[7:].strip()
                    if self._looks_like_jwt(token):
                        return token

        # 3) Body is JSON with a `token` / `jwt` / `signature` field
        try:
            parsed = json.loads(raw_body)
        except Exception:
            parsed = None

        if isinstance(parsed, dict):
            for key in ("token", "jwt", "signature", "postback_token"):
                candidate = parsed.get(key)
                if isinstance(candidate, str) and self._looks_like_jwt(candidate):
                    return candidate.strip()
            # Nested: {"data": {"token": "..."}}
            inner = parsed.get("data")
            if isinstance(inner, dict):
                for key in ("token", "jwt", "signature"):
                    candidate = inner.get(key)
                    if isinstance(candidate, str) and self._looks_like_jwt(candidate):
                        return candidate.strip()

        # 4) Raw body itself is a JWT (text/plain)
        try:
            body_text = raw_body.decode("utf-8", errors="ignore").strip()
        except Exception:
            body_text = ""
        if body_text and self._looks_like_jwt(body_text):
            return body_text

        return None

    @staticmethod
    def _b64url_decode(data: str) -> bytes:
        pad = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(data + pad)

    def _verify_jwt_hs256(self, token: str, secret: str) -> dict[str, Any] | None:
        """Verify JWT-HS256 using the given secret. Return payload or None."""
        try:
            header_b64, payload_b64, sig_b64 = token.split(".")
        except ValueError:
            return None

        try:
            expected = hmac.new(
                secret.encode("utf-8"),
                f"{header_b64}.{payload_b64}".encode("ascii"),
                hashlib.sha256,
            ).digest()
            actual = self._b64url_decode(sig_b64)
        except Exception:
            return None

        if not hmac.compare_digest(expected, actual):
            return None

        try:
            payload_json = self._b64url_decode(payload_b64)
            return json.loads(payload_json)
        except Exception:
            return None

    @staticmethod
    def _verify_rsa_sha256(
        raw_body: bytes, signature: str, pem: str
    ) -> bool:
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError:
            logger.error("[trybit] `cryptography` is required for RSA verification")
            return False

        try:
            public_key = serialization.load_pem_public_key(pem.encode("utf-8"))
        except Exception:
            return False

        try:
            sig_bytes = bytes.fromhex(signature.strip())
        except ValueError:
            return False

        try:
            public_key.verify(
                sig_bytes, raw_body, padding.PKCS1v15(), hashes.SHA256()
            )
            return True
        except InvalidSignature:
            return False
        except Exception:
            return False

    @staticmethod
    def _debug_log_webhook(
        raw_body: bytes, signature: str, headers: dict[str, str] | None
    ) -> None:
        """Log safe metadata to help adapt if the format is different.

        NEVER logs secret values or full payload bodies.
        """
        header_names = sorted((headers or {}).keys())
        body_preview = raw_body[:120].decode("utf-8", errors="replace")
        logger.warning(
            "[trybit] webhook unverified: size=%d headers=%s sig_present=%s body_preview=%r",
            len(raw_body),
            header_names,
            bool(signature),
            body_preview,
        )


# Singleton wired from settings at import time.
trybit_provider = TrybitProvider(
    api_url=settings.trybit_api_url,
    api_key=settings.trybit_api_key,
    shop_id=settings.trybit_shop_id,
    webhook_secret=settings.trybit_webhook_secret,
    webhook_public_key=settings.trybit_webhook_public_key,
)