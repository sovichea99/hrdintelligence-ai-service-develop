"""Authentication dependency: who is calling, and are they allowed to use the AI service.

Fails closed: if auth or the database is not configured, requests get 503. There is no switch
that skips authentication.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import AuthError, AuthUnavailableError
from app.repositories.chat_repository import ChatRepository

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


KNOWN_ROLES = frozenset({"admin", "instructor"})  # roles.role_name values in the ERD


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    role: str  # "admin" | "instructor"; retrieval scope (7.2/7.3) depends on it


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    verifier = request.app.state.token_verifier
    session_factory = request.app.state.session_factory
    if verifier is None or session_factory is None:
        raise HTTPException(status_code=503, detail="The service is not configured")

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Verification may fetch Keycloak's keys over the network, so keep it off the event loop.
        claims = await asyncio.to_thread(verifier.verify, credentials.credentials)
    except AuthUnavailableError:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    except AuthError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        keycloak_id = uuid.UUID(str(claims["sub"]))
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with session_factory() as db:
        found = await ChatRepository(db).get_user_with_role(keycloak_id)

    # Fail closed: unknown account, inactive account, or a role we do not know all get the same
    # answer, so the response does not reveal which one it was.
    if found is None:
        raise HTTPException(status_code=403, detail="This account may not use the AI service")
    user, role = found
    if user.is_active is not True or role not in KNOWN_ROLES:
        raise HTTPException(status_code=403, detail="This account may not use the AI service")
    return CurrentUser(user_id=user.user_id, role=role)