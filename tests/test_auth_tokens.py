from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from click.testing import CliRunner

from treqs_cli.application.requests.models import TrainingRequest
from treqs_cli.cli import cli
from treqs_cli.config import AuthStore, RepoContextStore
from treqs_cli.errors import ApiError, AuthError
from treqs_cli.models import AccessContext, AuthState, RepoContext


class _FakeClient:
    seen_tokens: ClassVar[list[str]] = []
    seen_api_urls: ClassVar[list[str]] = []
    access_context_error: ClassVar[ApiError | None] = None

    def __init__(self, api_url: str) -> None:
        self.api_url = api_url

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get_access_context(self, auth_state: AuthState) -> AccessContext:
        type(self).seen_tokens.append(auth_state.access_token)
        type(self).seen_api_urls.append(auth_state.api_url)
        if self.access_context_error is not None:
            raise self.access_context_error
        return AccessContext.model_validate(_access_context_payload())

    def logout(self, auth_state: AuthState) -> None:
        return None


def _install_fake_client(monkeypatch: Any) -> type[_FakeClient]:
    _FakeClient.seen_tokens = []
    _FakeClient.seen_api_urls = []
    _FakeClient.access_context_error = None
    monkeypatch.setattr("treqs_cli.commands.auth.TreqsApiClient", _FakeClient)
    monkeypatch.setattr("treqs_cli.commands.shared.TreqsApiClient", _FakeClient)
    return _FakeClient


def _env(config_home: Path) -> dict[str, str | None]:
    return {
        "TREQS_CONFIG_HOME": str(config_home),
        "TREQS_API_TOKEN": None,
        "TREQS_API_URL": None,
    }


def test_login_token_validates_and_saves_token_auth_state(monkeypatch: Any, tmp_path: Path) -> None:
    fake = _install_fake_client(monkeypatch)
    config_home = tmp_path / "config"
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["login", "--token", "treqs_pat_abc"],
        env=_env(config_home),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert "Logged in as trevor." in result.output
    assert fake.seen_tokens == ["treqs_pat_abc"]
    payload = json.loads((config_home / "auth.json").read_text(encoding="utf-8"))
    assert payload["access_token"] == "treqs_pat_abc"
    assert payload["token_type"] == "Bearer"
    assert payload["provider"] == "token"
    assert "expires_at" not in payload
    assert "refresh_token" not in payload
    assert payload["user"]["username"] == "trevor"


def test_login_token_rejects_invalid_token_without_saving(monkeypatch: Any, tmp_path: Path) -> None:
    fake = _install_fake_client(monkeypatch)
    fake.access_context_error = ApiError("Unauthorized", status_code=401)
    config_home = tmp_path / "config"
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["login", "--token", "treqs_pat_bad"], env=_env(config_home))

    assert result.exit_code == 1
    assert isinstance(result.exception, AuthError)
    assert "Invalid or revoked API token." in str(result.exception)
    assert not (config_home / "auth.json").exists()


def test_login_token_dash_reads_token_from_stdin(monkeypatch: Any, tmp_path: Path) -> None:
    fake = _install_fake_client(monkeypatch)
    config_home = tmp_path / "config"
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["login", "--token", "-"],
        input="treqs_pat_stdin\n",
        env=_env(config_home),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert fake.seen_tokens == ["treqs_pat_stdin"]
    payload = json.loads((config_home / "auth.json").read_text(encoding="utf-8"))
    assert payload["access_token"] == "treqs_pat_stdin"


def test_login_token_empty_value_is_a_usage_error(monkeypatch: Any, tmp_path: Path) -> None:
    _install_fake_client(monkeypatch)
    config_home = tmp_path / "config"
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["login", "--token", "   "], env=_env(config_home))

    assert result.exit_code == 2
    assert "API token is empty" in result.output
    assert not (config_home / "auth.json").exists()


def test_login_token_keeps_existing_session_when_prompt_declined(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _install_fake_client(monkeypatch)
    config_home = tmp_path / "config"
    AuthStore(config_home / "auth.json").save(
        AuthState(api_url="https://api.treqs.ai", access_token="stored-token")
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["login", "--token", "treqs_pat_new"],
        input="n\n",
        env=_env(config_home),
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "Already logged in" in result.output
    assert "existing session preserved" in result.output
    payload = json.loads((config_home / "auth.json").read_text(encoding="utf-8"))
    assert payload["access_token"] == "stored-token"


def test_login_token_replaces_existing_session_with_confirm_or_force(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _install_fake_client(monkeypatch)
    config_home = tmp_path / "config"
    AuthStore(config_home / "auth.json").save(
        AuthState(api_url="https://api.treqs.ai", access_token="stored-token")
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    confirmed = runner.invoke(
        cli,
        ["login", "--token", "treqs_pat_confirmed"],
        input="y\n",
        env=_env(config_home),
        catch_exceptions=False,
    )
    assert confirmed.exit_code == 0, confirmed.output
    payload = json.loads((config_home / "auth.json").read_text(encoding="utf-8"))
    assert payload["access_token"] == "treqs_pat_confirmed"

    forced = runner.invoke(
        cli,
        ["login", "--force", "--token", "treqs_pat_forced"],
        env=_env(config_home),
        catch_exceptions=False,
    )
    assert forced.exit_code == 0, forced.output
    assert "Already logged in" not in forced.output
    payload = json.loads((config_home / "auth.json").read_text(encoding="utf-8"))
    assert payload["access_token"] == "treqs_pat_forced"


def test_whoami_uses_env_api_token_without_stored_login(monkeypatch: Any, tmp_path: Path) -> None:
    fake = _install_fake_client(monkeypatch)
    config_home = tmp_path / "config"
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    env = _env(config_home)
    env["TREQS_API_TOKEN"] = "treqs_pat_env"

    result = runner.invoke(cli, ["whoami"], env=env, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "trevor <trevor@example.com>" in result.output
    assert "API: https://api.treqs.ai" in result.output
    assert fake.seen_tokens == ["treqs_pat_env"]
    # The ephemeral env-token auth state is never persisted.
    assert not (config_home / "auth.json").exists()


def test_env_api_token_takes_precedence_over_stored_auth(monkeypatch: Any, tmp_path: Path) -> None:
    fake = _install_fake_client(monkeypatch)
    config_home = tmp_path / "config"
    AuthStore(config_home / "auth.json").save(
        AuthState(api_url="https://stored.treqs.ai", access_token="stored-token")
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    env = _env(config_home)
    env["TREQS_API_TOKEN"] = "treqs_pat_env"

    result = runner.invoke(cli, ["whoami"], env=env, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert fake.seen_tokens == ["treqs_pat_env"]
    # Without --api-url/TREQS_API_URL, the stored login still provides the API URL.
    assert fake.seen_api_urls == ["https://stored.treqs.ai"]
    payload = json.loads((config_home / "auth.json").read_text(encoding="utf-8"))
    assert payload["access_token"] == "stored-token"


def test_repo_commands_use_env_api_token_without_stored_login(
    monkeypatch: Any, tmp_path: Path
) -> None:
    config_home = tmp_path / "config"
    work_repo = tmp_path / "repo"
    work_repo.mkdir()
    (work_repo / ".git").mkdir()
    RepoContextStore(work_repo / ".treqs" / "config.toml").save(
        RepoContext(
            api_url="https://api.treqs.ai",
            owner_id="owner-1",
            owner_type="user",
            owner_username="trevor",
            owner_display_name="Trevor",
            project_id="project-1",
            project_slug="mnist",
            project_name="MNIST",
            current_username="trevor",
        )
    )

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def list_training_requests(
            self,
            auth_state: AuthState,
            path: str,
            *,
            statuses: tuple[str, ...],
            limit: int,
            offset: int,
        ) -> list[TrainingRequest]:
            calls.append((auth_state.access_token, path))
            return []

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = _env(config_home)
    env["TREQS_API_TOKEN"] = "treqs_pat_env"

    result = runner.invoke(cli, ["--json", "tr", "list"], env=env, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert calls == [("treqs_pat_env", "/api/v1/user/projects/mnist/training-requests")]
    assert not (config_home / "auth.json").exists()


def test_logout_notes_env_api_token_remains_active(monkeypatch: Any, tmp_path: Path) -> None:
    _install_fake_client(monkeypatch)
    config_home = tmp_path / "config"
    AuthStore(config_home / "auth.json").save(
        AuthState(api_url="https://api.treqs.ai", access_token="stored-token")
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    env = _env(config_home)
    env["TREQS_API_TOKEN"] = "treqs_pat_env"

    result = runner.invoke(cli, ["--json", "logout"], env=env, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"removed": True}
    assert "TREQS_API_TOKEN is set in the environment" in result.stderr
    assert not (config_home / "auth.json").exists()


def _access_context_payload() -> dict[str, Any]:
    return {
        "user": {
            "id": "user-1",
            "sub": "sub-1",
            "username": "trevor",
            "email": "trevor@example.com",
        },
        "owners": [
            {
                "id": "user-1",
                "type": "user",
                "username": "trevor",
                "display_name": "Trevor",
                "role": "owner",
            }
        ],
        "projects_by_owner": {
            "user-1": [
                {
                    "id": "project-1",
                    "slug": "mnist",
                    "name": "MNIST",
                    "visibility": "private",
                    "can_write": True,
                }
            ]
        },
    }
