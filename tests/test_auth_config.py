from __future__ import annotations

from pathlib import Path

import pytest

from treqs_cli.auth import resolve_api_url
from treqs_cli.config import AuthStore
from treqs_cli.errors import AuthError
from treqs_cli.models import AuthState


def test_auth_store_round_trip(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.json")
    state = AuthState(
        api_url="https://api.treqs.ai",
        access_token="access-token",
        refresh_token="refresh-token",
        provider="github",
    )

    path = store.save(state)
    loaded = store.require()

    assert path.exists()
    assert loaded.access_token == "access-token"
    assert loaded.refresh_token == "refresh-token"


def test_resolve_api_url_rejects_non_local_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TREQS_ALLOW_HTTP", raising=False)

    with pytest.raises(AuthError, match="insecure HTTP"):
        resolve_api_url("http://api.example.com")


def test_resolve_api_url_allows_local_http() -> None:
    assert resolve_api_url("http://127.0.0.1:3002") == "http://127.0.0.1:3002"
