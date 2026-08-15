"""
Default fare constants, used only when no `FareRule` row exists in the
database yet (e.g. a fresh dev environment before the seed data
migration/insert has been run - see the ticketing Alembic migration).

These are intentionally NOT added to `core/config.py` - they're
ticketing-specific, not application-wide configuration, and per this
workstream's instructions the shared config module is not to be modified.
A real deployment should instead maintain its fare(s) as `FareRule` rows
(data, editable without a code change or redeploy) - see
`ticketing.fares.service`.
"""

from __future__ import annotations

import decimal

DEFAULT_FARE_RULE_NAME = "default"
DEFAULT_BASE_FARE = decimal.Decimal("50.00")
DEFAULT_PER_LEG_FARE = decimal.Decimal("20.00")
DEFAULT_CURRENCY = "PKR"
