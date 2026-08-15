"""
Pure unit tests for ticketing/tickets/qr.py - no database required.
"""

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import jwt
import pytest

from ticketing.tickets.qr import (
    InvalidQrPayloadError,
    build_qr_payload,
    verify_qr_payload,
)


def test_qr_payload_round_trips_ticket_and_user_ids():
    ticket_id = uuid.uuid4()
    user_id = uuid.uuid4()
    payload = build_qr_payload(ticket_id=ticket_id, user_id=user_id)

    claims = verify_qr_payload(payload)

    assert claims.ticket_id == ticket_id
    assert claims.user_id == user_id


def test_qr_payload_is_opaque_not_the_raw_ids():
    ticket_id = uuid.uuid4()
    payload = build_qr_payload(ticket_id=ticket_id, user_id=uuid.uuid4())
    assert str(ticket_id) not in payload  # base64url-encoded JWT, not plaintext


def test_qr_payload_rejects_tampered_signature():
    payload = build_qr_payload(ticket_id=uuid.uuid4(), user_id=uuid.uuid4())
    tampered = payload[:-3] + ("aaa" if not payload.endswith("aaa") else "bbb")
    with pytest.raises(InvalidQrPayloadError):
        verify_qr_payload(tampered)


def test_qr_payload_rejects_malformed_string():
    with pytest.raises(InvalidQrPayloadError):
        verify_qr_payload("not-a-jwt-at-all")


def test_qr_payload_rejects_wrong_token_type():
    """A ticket's QR string must never be accepted where a different
    signed-token type is expected, and vice versa - e.g. an access token
    must not double as a QR payload even though both are HS256 JWTs
    signed with the same SECRET_KEY."""
    from datetime import datetime, timezone

    from core.config import settings

    payload = {
        "sub": str(uuid.uuid4()),
        "type": "access",  # an access-token-shaped payload, not "ticket_qr"
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(InvalidQrPayloadError):
        verify_qr_payload(token)


def test_qr_payload_rejects_forged_payload_with_wrong_secret():
    from datetime import datetime, timezone

    payload = {
        "tid": str(uuid.uuid4()),
        "uid": str(uuid.uuid4()),
        "type": "ticket_qr",
        "iat": datetime.now(timezone.utc),
    }
    forged = jwt.encode(payload, "attacker-controlled-secret", algorithm="HS256")
    with pytest.raises(InvalidQrPayloadError):
        verify_qr_payload(forged)


def test_qr_payload_does_not_enforce_its_own_expiry():
    """The QR payload itself has no exp claim to expire - the live Ticket
    row in the database is the sole source of truth for whether a ticket
    is still valid (see ticketing/tickets/qr.py's docstring and
    ticketing/tickets/service.py::validate_ticket)."""
    from datetime import datetime, timedelta, timezone

    from core.config import settings

    long_ago = datetime.now(timezone.utc) - timedelta(days=365)
    payload = {
        "tid": str(uuid.uuid4()),
        "uid": str(uuid.uuid4()),
        "type": "ticket_qr",
        "iat": long_ago,
        "exp": long_ago + timedelta(minutes=1),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    # Does not raise, despite the (irrelevant) exp claim being long past.
    verify_qr_payload(token)


def test_qr_payload_rejects_malformed_ticket_id_claim():
    from datetime import datetime, timezone

    from core.config import settings

    payload = {
        "tid": "not-a-uuid",
        "uid": str(uuid.uuid4()),
        "type": "ticket_qr",
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(InvalidQrPayloadError):
        verify_qr_payload(token)
