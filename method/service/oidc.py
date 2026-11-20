from __future__ import annotations

import asyncio
import time

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier


class OidcTokenVerifier(TokenVerifier):
    def __init__(self, issuer: str, jwks_url: str, audience: str):
        self.issuer = issuer
        self.audience = audience
        self.jwks = jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            return await asyncio.to_thread(self._verify, token)
        except jwt.PyJWTError:
            return None

    def _verify(self, token: str) -> AccessToken:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise jwt.InvalidAlgorithmError("unsupported token algorithm")
        signing_key = self.jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=self.issuer,
            audience=self.audience,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            leeway=30,
        )
        expires_at = int(claims["exp"])
        if expires_at <= int(time.time()):
            raise jwt.ExpiredSignatureError("token has expired")
        raw_scopes = claims.get("scope", "")
        scopes = raw_scopes.split() if isinstance(raw_scopes, str) else list(raw_scopes)
        email = claims.get("email") if claims.get("email_verified") is True else None
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or "oidc-client"),
            scopes=scopes,
            expires_at=expires_at,
            subject=claims["sub"],
            claims={"email": email, "email_verified": claims.get("email_verified")},
        )


class CompositeTokenVerifier(TokenVerifier):
    """Per-user `evk_` tokens resolve through the store; everything else is OIDC. Tokens never carry admin."""

    def __init__(self, oidc: TokenVerifier | None, store):
        self.oidc = oidc
        self.store = store

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith("evk_"):
            return None if self.oidc is None else await self.oidc.verify_token(token)
        row = await asyncio.to_thread(self.store.resolve_token, token)
        if row is None:
            return None
        return AccessToken(
            token=token,
            client_id="evidence-user-token",
            scopes=["evidence:access"],
            expires_at=None,
            subject=row["subject"],
            claims={"email": None, "email_verified": False},
        )
