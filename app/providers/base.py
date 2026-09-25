"""Provider-agnostic payment interface.

The rest of Voince must not know which provider is behind it.
See app/providers/trybit.py for the current implementation.
"""

from abc import ABC, abstractmethod
from typing import Any


class PaymentError(Exception):
    """Raised when a payment provider returns an error or is misconfigured."""


class PaymentProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    async def create_payment(
        self,
        *,
        amount: float,
        order_id: str,
        email: str | None = None,
        purpose: str = "topup",
    ) -> dict[str, Any]:
        """Create a payment.

        Must return a dict with at least:
          - provider_payment_id: str
          - payment_url: str | None
        """

    @abstractmethod
    async def get_payment_status(self, provider_payment_id: str) -> dict[str, Any]:
        """Return provider-side status for the given payment id."""

    @abstractmethod
    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        """Return True if the webhook signature is valid."""