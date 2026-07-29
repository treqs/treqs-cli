from __future__ import annotations

import os
import webbrowser
from urllib.parse import urlparse

from .config import DEFAULT_API_URL
from .errors import AuthError
from .models import AuthState

TREQS_API_TOKEN_ENV = "TREQS_API_TOKEN"


def env_api_token() -> str | None:
    """Return the non-empty TREQS_API_TOKEN environment value, if set."""
    token = os.environ.get(TREQS_API_TOKEN_ENV, "").strip()
    return token or None


def token_auth_state(api_url: str, token: str) -> AuthState:
    """Build the auth state for a TReqs API token (no refresh flow, no expiry)."""
    return AuthState(
        api_url=api_url.rstrip("/"),
        access_token=token,
        token_type="Bearer",
        refresh_token=None,
        expires_at=None,
        provider="token",
    )


def resolve_api_url(explicit_url: str | None = None) -> str:
    resolved = (
        (explicit_url or "").strip()
        or os.environ.get("TREQS_API_URL", "").strip()
        or DEFAULT_API_URL
    ).rstrip("/")

    parsed = urlparse(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AuthError(f"Invalid TReqs API URL: {resolved}")
    if parsed.scheme == "http" and not _is_local_http(parsed.hostname):
        allow_http = os.environ.get("TREQS_ALLOW_HTTP", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if not allow_http:
            raise AuthError(
                f"Refusing non-local insecure HTTP TReqs API URL: {resolved}. "
                "Use HTTPS, or set TREQS_ALLOW_HTTP=1 for controlled development."
            )
    return resolved


def open_browser(url: str, *, disabled: bool = False) -> bool:
    env_disabled = os.environ.get("TREQS_DISABLE_BROWSER_OPEN", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if disabled or env_disabled:
        return False
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


def _is_local_http(hostname: str | None) -> bool:
    return hostname in {"localhost", "127.0.0.1", "::1"}
