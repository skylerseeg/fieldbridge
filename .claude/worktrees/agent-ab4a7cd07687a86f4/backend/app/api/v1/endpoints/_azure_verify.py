"""
Azure AD (Entra ID) ID-token verification helper.

Used by POST /auth/azure/callback. Sits alongside endpoints/auth.py instead
of in app/core/ (which is deny-listed for agent edits — see .claude/settings.json
`MULTI-TENANT FOUNDATION` block). Keeping it module-local means a bad edit
here only breaks the Azure SSO path, not every authenticated request.

Verification steps, in order:
  1. Fetch signing keys from the tenant-scoped JWKS URI (cached by PyJWKClient).
  2. Verify RS256 signature with the matching kid.
  3. Verify `iss` matches https://login.microsoftonline.com/{tid}/v2.0.
  4. Verify `aud` matches settings.azure_client_id (the SPA's app registration).
  5. Verify `tid` matches settings.azure_tenant_id (pin to the customer's
     directory — prevents tokens from other Entra tenants being accepted
     even if they happen to have the same aud misconfigured).

Any failure raises HTTPException(401) with a specific reason so the frontend
can log the actual cause during onboarding.
"""
from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient

from app.core.config import settings


class AzureVerificationError(HTTPException):
    """401 with a specific reason. Kept distinct from generic auth 401s
    so the frontend can surface configuration problems separately."""

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"azure_id_token: {detail}",
        )


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    """
    One JWKS client per process, cached. The library itself caches the fetched
    key set with its own TTL (default 60s), so this lru_cache is just to avoid
    re-constructing the HTTP client on every request.
    """
    if not settings.azure_tenant_id:
        # Fail loudly at first call rather than hitting a URL with an empty
        # tenant segment.
        raise AzureVerificationError(
            "AZURE_TENANT_ID not configured on the server",
        )
    jwks_uri = (
        f"https://login.microsoftonline.com/"
        f"{settings.azure_tenant_id}/discovery/v2.0/keys"
    )
    return PyJWKClient(jwks_uri)


def verify_azure_id_token(id_token: str) -> dict:
    """
    Verify an Azure AD v2 ID token and return its claims on success.

    Raises AzureVerificationError(401) on any failure.
    """
    if not settings.azure_client_id:
        raise AzureVerificationError("AZURE_CLIENT_ID not configured on the server")

    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(id_token).key
    except Exception as exc:  # jwt.exceptions.PyJWKClientError + network errors
        raise AzureVerificationError(f"JWKS lookup failed: {exc}") from exc

    expected_issuer = (
        f"https://login.microsoftonline.com/{settings.azure_tenant_id}/v2.0"
    )

    try:
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.azure_client_id,
            issuer=expected_issuer,
            # PyJWT verifies exp, nbf, iat, aud, iss by default when we pass
            # audience+issuer. Leave signature verification on.
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise AzureVerificationError("token expired")
    except jwt.InvalidAudienceError:
        raise AzureVerificationError("audience mismatch")
    except jwt.InvalidIssuerError:
        raise AzureVerificationError("issuer mismatch")
    except jwt.InvalidTokenError as exc:
        raise AzureVerificationError(f"invalid token: {exc}") from exc

    # Defense-in-depth tenant pin. audience+issuer above already pin this
    # indirectly, but checking `tid` explicitly prevents a class of
    # misconfigurations where iss was relaxed during onboarding.
    tid = claims.get("tid")
    if tid != settings.azure_tenant_id:
        raise AzureVerificationError(
            f"tid mismatch: got {tid!r}, expected {settings.azure_tenant_id!r}"
        )

    return claims


def email_from_claims(claims: dict) -> str | None:
    """
    Extract the user's email from an Azure ID token.

    Work / school accounts usually don't return `email`; the UPN
    (`preferred_username`) is the addressable identifier. Fall back in order:
    email → preferred_username → upn.
    """
    return (
        claims.get("email")
        or claims.get("preferred_username")
        or claims.get("upn")
    )
