"""
Pure unit tests for users/security.py - no database required.
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

from users.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_never_returns_plaintext():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$2b$")


def test_hash_password_is_salted_and_nondeterministic():
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b


def test_verify_password_accepts_correct_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_incorrect_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_verify_password_rejects_malformed_hash_without_raising():
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_access_token_round_trips_user_id():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_access_token_rejects_bad_signature():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_access_token_rejects_expired_token():
    from datetime import datetime, timedelta, timezone

    from core.config import settings
    from users.security import ALGORITHM

    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "iat": now - timedelta(hours=1),
        "exp": now - timedelta(minutes=1),
    }
    expired_token = jwt.encode(expired_payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(expired_token)


def test_access_token_rejects_wrong_token_type():
    from datetime import datetime, timedelta, timezone

    from core.config import settings
    from users.security import ALGORITHM

    now = datetime.now(timezone.utc)
    wrong_type_payload = {
        "sub": str(uuid.uuid4()),
        "type": "ticket_qr",  # not "access"
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(wrong_type_payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_access_token_rejects_malformed_subject():
    from datetime import datetime, timedelta, timezone

    from core.config import settings
    from users.security import ALGORITHM

    now = datetime.now(timezone.utc)
    payload = {
        "sub": "not-a-uuid",
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_access_token_rejects_token_signed_with_different_secret():
    from datetime import datetime, timedelta, timezone

    from users.security import ALGORITHM

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(payload, "a-completely-different-secret", algorithm=ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)
