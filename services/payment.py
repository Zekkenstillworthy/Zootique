from __future__ import annotations

from dataclasses import dataclass
import os
import secrets


@dataclass(frozen=True)
class PaymentResult:
    status: str
    provider: str
    provider_reference: str


class PaymentProviderError(ValueError):
    pass


class PaymentProvider:
    name = "base"

    def authorize(self, *, amount: float, method: str, idempotency_key: str) -> PaymentResult:
        raise NotImplementedError


class MockPaymentProvider(PaymentProvider):
    name = "simulated"

    def authorize(self, *, amount: float, method: str, idempotency_key: str) -> PaymentResult:
        if amount < 0:
            raise PaymentProviderError("Payment amount cannot be negative.")
        return PaymentResult("paid", self.name, f"MOCK-{secrets.token_hex(8).upper()}")


def get_payment_provider() -> PaymentProvider:
    provider_name = (os.environ.get("PAYMENT_PROVIDER") or "mock").strip().lower()
    if provider_name in {"mock", "simulated_gateway"}:
        return MockPaymentProvider()
    raise PaymentProviderError(f"Unsupported payment provider: {provider_name}.")
