"""Optional API-key gate for the /api endpoints.

POC-grade: a single shared secret compared in constant time, sent as the
`X-API-Key` header. When `API_KEY` is unset (the default for local dev and the
demo), the dependency is a no-op so nothing needs a key — set `API_KEY` in the
deployed environment to require it. This is intentionally not per-user auth;
it's the smallest thing that stops an unauthenticated caller from POSTing
signals or reading incidents on a shared/deployed instance.
"""

import secrets

from fastapi import Header, HTTPException, status

from app.config import settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = settings.api_key
    if not expected:
        return  # auth disabled — local dev / demo
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
