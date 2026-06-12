from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, Optional

import jwt
from cryptography.hazmat.primitives import serialization
from fastapi import Header, HTTPException, Request
from loguru import logger

from app.shared.config import get_settings


@dataclass(frozen=True)
class AuthContext:
    """Verified identity from a LibreChat code-API JWT."""

    enabled: bool  # False when auth is unconfigured (open mode)
    sub: Optional[str] = None  # LibreChat user id (trustworthy identity)
    tenant_id: Optional[str] = None
    role: Optional[str] = None
    claims: Dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=4)
def _load_public_key(pem: str):
    """Parse a PEM public key; cached on the PEM string so settings swaps in tests just work."""
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})


async def verify_jwt(request: Request, authorization: Optional[str] = Header(None)) -> AuthContext:
    """Verify the LibreChat-minted Bearer JWT on the request.

    Auth is disabled when no public key is configured. Settings are read at
    request time so the key can be toggled in tests. The verified claims are
    attached to ``request.state.auth`` for route handlers.
    """
    settings = get_settings()
    pem = settings.JWT_PUBLIC_KEY_PEM
    if pem is None:
        context = AuthContext(enabled=False)
        request.state.auth = context
        return context

    if authorization is None:
        raise _unauthorized()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    token = token.strip()

    try:
        key = _load_public_key(pem)
    except ValueError:
        logger.error("CODEAPI_JWT_PUBLIC_KEY is not a valid PEM public key")
        raise HTTPException(status_code=500, detail="Server authentication misconfigured")

    try:
        kid = jwt.get_unverified_header(token).get("kid")
        logger.debug(f"Verifying code-API token with kid={kid}")
    except jwt.InvalidTokenError:
        raise _unauthorized()

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=settings.CODEAPI_JWT_ALGORITHMS,
            audience=settings.CODEAPI_JWT_AUDIENCE,
            issuer=settings.CODEAPI_JWT_ISSUER,
            leeway=settings.CODEAPI_JWT_LEEWAY,
            options={"require": ["exp", "iat", "sub"]},
        )
    except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
        # PyJWT raises TypeError/ValueError (not InvalidTokenError) when the
        # token's alg does not match the configured key type
        logger.warning(f"Rejected code-API token: {exc}")
        raise _unauthorized()

    context = AuthContext(
        enabled=True,
        sub=payload["sub"],
        tenant_id=payload.get("tenant_id"),
        role=payload.get("role"),
        claims=payload,
    )
    request.state.auth = context
    return context
