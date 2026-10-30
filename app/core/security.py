"""Keycloak JWT verification.

Only the signature, issuer and expiry are checked here. Who the user is and whether they may use
the service is decided afterwards from the database (see app/api/deps.py).

Design rules:
- Only RS256 is accepted. This blocks "alg: none" and HS256 key-confusion tokens.
- `exp`, `iss` and `sub` are required.
- The audience is checked only when configured (Keycloak access tokens often carry `aud=account`).
"""

from collections.abc import Callable
from typing import Any

import jwt
from jwt import PyJWKClient


class AuthError(Exception):
    """The token is missing, malformed, expired or not trusted."""


class AuthUnavailableError(Exception):
    """The token could not be checked because the key server (Keycloak) is unreachable."""


KeyResolver = Callable[[str], Any]


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str | None = None,
        audience: str | None = None,
        key_resolver: KeyResolver | None = None,
        leeway_seconds: int = 10,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience or None
        self._leeway = leeway_seconds

        if key_resolver is None:
            client = PyJWKClient(
                jwks_url or f"{self._issuer}/protocol/openid-connect/certs",
                cache_keys=True,
                lifespan=300,
            )

            def key_resolver(token: str) -> Any:
                return client.get_signing_key_from_jwt(token).key

        self._key_resolver = key_resolver

    def verify(self, token: str) -> dict[str, Any]:
        """Return the verified claims. Blocking (may fetch keys): call it from a thread."""
        try:
            key = self._key_resolver(token)
            return jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={
                    "require": ["exp", "iss", "sub"],
                    "verify_aud": self._audience is not None,
                },
            )
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthUnavailableError("key server unreachable") from exc
        except jwt.PyJWTError as exc:
            # Do not echo the library message: it can reveal details about the token.
            raise AuthError("invalid token") from exc