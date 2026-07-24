from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from treqs_cli.application.projects.models import Project
from treqs_cli.cli import cli
from treqs_cli.commands.shared import resolve_owner_scope
from treqs_cli.config import AuthStore, RepoContextStore
from treqs_cli.context import TreqsContext
from treqs_cli.errors import ConfigError
from treqs_cli.models import AccessContext, AuthState, RepoContext


def _state(tmp_path: Path, *, is_git_repo: bool) -> TreqsContext:
    return TreqsContext(
        api_url_override=None,
        json_output=False,
        auth_store=AuthStore(tmp_path / "auth.json"),
        repo_context_store=RepoContextStore(tmp_path / ".treqs" / "config.toml"),
        cwd=tmp_path,
        repo_root=tmp_path,
        is_interactive=False,
        is_git_repo=is_git_repo,
    )


def _save_repo_context(tmp_path: Path, owner_username: str) -> None:
    RepoContextStore(tmp_path / ".treqs" / "config.toml").save(
        RepoContext(
            api_url="https://api.treqs.ai",
            owner_id="org-1",
            owner_type="organization",
            owner_username=owner_username,
            owner_display_name="Acme Inc",
            project_id="project-2",
            project_slug="mnist",
            project_name="MNIST Org",
            current_username="trevor",
        )
    )


def test_owner_flag_beats_repo_binding(tmp_path: Path) -> None:
    _save_repo_context(tmp_path, "acme")
    state = _state(tmp_path, is_git_repo=True)

    scope = resolve_owner_scope(state, _access_context(), "beta")

    assert scope.owner_username == "beta"
    assert scope.current_username == "trevor"


def test_repo_binding_beats_personal_owner(tmp_path: Path) -> None:
    _save_repo_context(tmp_path, "acme")
    state = _state(tmp_path, is_git_repo=True)

    scope = resolve_owner_scope(state, _access_context(), None)

    assert scope.owner_username == "acme"
    assert scope.current_username == "trevor"


def test_personal_owner_is_the_final_fallback(tmp_path: Path) -> None:
    state = _state(tmp_path, is_git_repo=False)

    scope = resolve_owner_scope(state, _access_context(), None)

    assert scope.owner_username == "trevor"
    assert scope.current_username == "trevor"


def test_unbound_git_repo_falls_back_to_personal_owner(tmp_path: Path) -> None:
    state = _state(tmp_path, is_git_repo=True)

    scope = resolve_owner_scope(state, _access_context(), None)

    assert scope.owner_username == "trevor"


def test_unknown_owner_selection_fails_clearly(tmp_path: Path) -> None:
    state = _state(tmp_path, is_git_repo=False)

    with pytest.raises(ConfigError, match="Owner not found"):
        resolve_owner_scope(state, _access_context(), "nope")


def test_projects_create_uses_repo_bound_org_owner(monkeypatch: Any, tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    work_repo = tmp_path / "repo"
    work_repo.mkdir()
    (work_repo / ".git").mkdir()
    AuthStore(config_home / "auth.json").save(
        AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    )
    _save_repo_context(work_repo, "acme")

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get_access_context(self, _auth_state: AuthState) -> AccessContext:
            return _access_context()

        def create_project(
            self,
            _auth_state: AuthState,
            path: str,
            json_payload: dict[str, object],
        ) -> Project:
            calls.append((path, str(json_payload.get("slug"))))
            return Project(id="project-9", slug="fresh", name="Fresh")

    monkeypatch.setattr("treqs_cli.commands.projects.TreqsApiClient", FakeClient)
    monkeypatch.setattr("treqs_cli.commands.shared.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["--json", "projects", "create", "Fresh"],
        env={"TREQS_CONFIG_HOME": str(config_home)},
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["id"] == "project-9"
    assert calls == [("/api/v1/user/orgs/acme/projects", "fresh")]


def _access_context() -> AccessContext:
    return AccessContext.model_validate(
        {
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
                },
                {
                    "id": "org-1",
                    "type": "organization",
                    "username": "acme",
                    "display_name": "Acme Inc",
                    "role": "admin",
                },
                {
                    "id": "org-2",
                    "type": "organization",
                    "username": "beta",
                    "display_name": None,
                    "role": "member",
                },
            ],
            "projects_by_owner": {"user-1": [], "org-1": [], "org-2": []},
        }
    )
