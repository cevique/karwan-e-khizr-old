"""
Payment provider abstraction.

The project may eventually support a real payment method (e.g. TCash),
but no real credentials/API integration exist yet, and implementing one
without them would mean pretending a real transaction occurred - which
this module explicitly must not do (see the top-level instructions'
"TCASH" section).

Instead, `PaymentProvider` is a small interface a real provider can
implement later without any rewrite of `ticketing.tickets.service`, which
depends only on this interface. `DevPaymentProvider` is the only
implementation for now: it always "succeeds" and is clearly labeled as
such in its own result, so nothing downstream can mistake it for a real
charge.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PaymentResult:
    """Result of a `PaymentProvider.charge` call."""

    success: bool
    provider_name: str
    reference: str
    is_simulated: bool


class PaymentProvider(Protocol):
    """Interface a payment provider (development or real) must satisfy."""

    name: str

    async def charge(self, *, user_id: uuid.UUID, amount: str, currency: str) -> PaymentResult:
        """Attempt to charge `amount` `currency` for `user_id`. Must never
        raise for an ordinary decline - return a `PaymentResult` with
        `success=False` instead; raise only for a genuine provider/
        infrastructure error."""
        ...


class DevPaymentProvider:
    """Development-only `PaymentProvider`: always succeeds immediately,
    with no real money movement and no external call of any kind.

    Every `PaymentResult` it returns has `is_simulated=True` so a caller
    (or a future audit) can never mistake this for a real charge. This is
    the only `PaymentProvider` wired up in this workstream - see
    `ticketing.tickets.service.create_ticket`'s docstring for how it's
    used and how a real provider would be substituted later.
    """

    name = "dev"

    async def charge(self, *, user_id: uuid.UUID, amount: str, currency: str) -> PaymentResult:
        return PaymentResult(
            success=True,
            provider_name=self.name,
            reference=f"dev-{uuid.uuid4()}",
            is_simulated=True,
        )
