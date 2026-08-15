"""
Ticket-specific configuration constants. Not added to `core/config.py`
per this workstream's instructions (ticketing-specific, not
application-wide) - see ticketing/fares/config.py's docstring for the
same reasoning.
"""

from __future__ import annotations

# How long a purchased ticket remains valid from the moment it's issued.
# A hackathon-appropriate fixed window (there's no real schedule/arrival
# data to derive a trip-specific validity window from - routing is
# schedule-agnostic per api/transit/journey_schemas.py). 90 minutes
# comfortably covers a single journey plus a buffer for delays/transfers.
TICKET_VALIDITY_MINUTES = 90

# Alphabet and length for `Ticket.ticket_code` - deliberately excludes
# visually-ambiguous characters (0/O, 1/I/L) since this code is meant to
# be readable off a phone screen or receipt, not just machine-scanned.
TICKET_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
TICKET_CODE_LENGTH = 8
