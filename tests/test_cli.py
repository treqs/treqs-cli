from __future__ import annotations

from pathlib import Path

from treqs_cli.cli import _auth_state_for_request
from treqs_cli.config import AuthStore, RepoContextStore
from treqs_cli.context import TreqsContext
from treqs_cli.models import AuthState


def test_api_url_override_beats_saved_auth_url(tmp_path: Path) -> None:
    state = TreqsContext(
        api_url_override="http://127.0.0.1:3002",
        json_output=False,
        auth_store=AuthStore(tmp_path / "auth.json"),
        repo_context_store=RepoContextStore(tmp_path / ".treqs" / "config.toml"),
        cwd=tmp_path,
        repo_root=tmp_path,
        is_interactive=False,
    )
    stored_auth = AuthState(api_url="https://api.treqs.ai", access_token="access-token")

    request_auth = _auth_state_for_request(state, stored_auth)

    assert request_auth.api_url == "http://127.0.0.1:3002"
    assert stored_auth.api_url == "https://api.treqs.ai"
