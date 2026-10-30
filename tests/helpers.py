"""Shared test helpers: a throwaway RSA key pair and JWT builders. No Keycloak needed."""

import base64
import hashlib
import hmac
import json
import time
from contextlib import contextmanager

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://keycloak.test/realms/hrd"

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()
OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

PUBLIC_PEM = PUBLIC_KEY.public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)


def make_token(
    sub,
    *,
    issuer: str = ISSUER,
    expires_in: int = 300,
    key=None,
    extra: dict | None = None,
    include_exp: bool = True,
) -> str:
    now = int(time.time())
    claims = {"sub": str(sub), "iss": issuer, "iat": now}
    if include_exp:
        claims["exp"] = now + expires_in
    claims.update(extra or {})
    return jwt.encode(claims, key or PRIVATE_KEY, algorithm="RS256")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_unsigned_token(sub) -> str:
    """A token with `alg: none`, the classic forgery."""
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = _b64(
        json.dumps({"sub": str(sub), "iss": ISSUER, "exp": int(time.time()) + 300}).encode()
    )
    return f"{header}.{payload}."


def make_hs256_token_signed_with_public_key(sub) -> str:
    """Key-confusion forgery: HS256 signed using the (public) RSA key as the secret."""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(
        json.dumps({"sub": str(sub), "iss": ISSUER, "exp": int(time.time()) + 300}).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(PUBLIC_PEM, signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}"


@contextmanager
def expect_raises(exc_type):
    """Tiny stand-in for pytest.raises, so the pure tests also run without pytest."""
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")
