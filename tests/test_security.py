import uuid

from app.core.security import AuthError, TokenVerifier
from tests.helpers import (
    ISSUER,
    OTHER_PRIVATE_KEY,
    PUBLIC_KEY,
    expect_raises,
    make_hs256_token_signed_with_public_key,
    make_token,
    make_unsigned_token,
)


def verifier(**kwargs) -> TokenVerifier:
    return TokenVerifier(issuer=ISSUER, key_resolver=lambda token: PUBLIC_KEY, **kwargs)


def test_valid_token_returns_claims():
    sub = uuid.uuid4()
    claims = verifier().verify(make_token(sub))
    assert claims["sub"] == str(sub)


def test_trailing_slash_in_configured_issuer_is_ignored():
    v = TokenVerifier(issuer=ISSUER + "/", key_resolver=lambda token: PUBLIC_KEY)
    assert v.verify(make_token(uuid.uuid4()))["iss"] == ISSUER


def test_expired_token_is_rejected():
    with expect_raises(AuthError):
        verifier().verify(make_token(uuid.uuid4(), expires_in=-3600))


def test_wrong_issuer_is_rejected():
    with expect_raises(AuthError):
        verifier().verify(make_token(uuid.uuid4(), issuer="https://evil.test/realms/hrd"))


def test_token_signed_with_another_key_is_rejected():
    with expect_raises(AuthError):
        verifier().verify(make_token(uuid.uuid4(), key=OTHER_PRIVATE_KEY))


def test_token_without_expiry_is_rejected():
    with expect_raises(AuthError):
        verifier().verify(make_token(uuid.uuid4(), include_exp=False))


def test_alg_none_token_is_rejected():
    with expect_raises(AuthError):
        verifier().verify(make_unsigned_token(uuid.uuid4()))


def test_hs256_key_confusion_token_is_rejected():
    with expect_raises(AuthError):
        verifier().verify(make_hs256_token_signed_with_public_key(uuid.uuid4()))


def test_garbage_is_rejected():
    with expect_raises(AuthError):
        verifier().verify("not-a-jwt")
    with expect_raises(AuthError):
        verifier().verify("")


def test_audience_is_checked_only_when_configured():
    token = make_token(uuid.uuid4(), extra={"aud": "account"})
    # Not configured: an `aud` claim in the token is fine.
    assert verifier().verify(token)["aud"] == "account"
    # Configured and matching: accepted.
    assert verifier(audience="account").verify(token)
    # Configured and different: rejected.
    with expect_raises(AuthError):
        verifier(audience="hrd-ai").verify(token)
