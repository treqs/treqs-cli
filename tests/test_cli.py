from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from treqs_cli.application.requests.models import TrainingRequest
from treqs_cli.cli import cli
from treqs_cli.commands.shared import auth_state_for_request
from treqs_cli.config import AuthStore, RepoContextStore
from treqs_cli.context import TreqsContext
from treqs_cli.models import AuthState, RepoContext

REPO_ROOT = Path(__file__).resolve().parents[1]


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

    request_auth = auth_state_for_request(state, stored_auth)

    assert request_auth.api_url == "http://127.0.0.1:3002"
    assert stored_auth.api_url == "https://api.treqs.ai"


def test_requests_commands_use_repo_project_context(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    config_home = tmp_path / "config"
    work_repo = tmp_path / "repo"
    work_repo.mkdir()
    (work_repo / ".git").mkdir()
    AuthStore(config_home / "auth.json").save(
        AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    )
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

    calls: list[tuple[str, str, object]] = []

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
            calls.append(("list", path, (auth_state.api_url, statuses, limit, offset)))
            return [_training_request_payload()]

        def create_training_request(
            self,
            auth_state: AuthState,
            path: str,
            json_payload: dict[str, str],
        ) -> TrainingRequest:
            calls.append(("create", path, json_payload))
            return TrainingRequest.model_validate(
                {**_training_request_payload().model_dump(mode="json"), **json_payload}
            )

        def get_training_request(
            self,
            auth_state: AuthState,
            path: str,
        ) -> TrainingRequest:
            calls.append(("show", path, auth_state.api_url))
            return _training_request_payload()

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    listed = runner.invoke(
        cli,
        ["--json", "requests", "list", "--status", "draft", "--limit", "10"],
        env=env,
        catch_exceptions=False,
    )
    created = runner.invoke(
        cli,
        [
            "--json",
            "requests",
            "create",
            "--title",
            "Train model",
            "--description",
            "Train a small model",
            "--workflow-path",
            ".github/workflows/train.yml",
        ],
        env=env,
        catch_exceptions=False,
    )
    shown = runner.invoke(
        cli,
        ["--json", "requests", "show", "request-1"],
        env=env,
        catch_exceptions=False,
    )

    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["id"] == "request-1"
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["workflowPath"] == ".github/workflows/train.yml"
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["id"] == "request-1"
    assert calls == [
        (
            "list",
            "/api/v1/user/projects/mnist/training-requests",
            ("https://api.treqs.ai", ("draft",), 10, 0),
        ),
        (
            "create",
            "/api/v1/user/projects/mnist/training-requests",
            {
                "title": "Train model",
                "description": "Train a small model",
                "status": "draft",
                "workflowPath": ".github/workflows/train.yml",
            },
        ),
        (
            "show",
            "/api/v1/user/projects/mnist/training-requests/request-1",
            "https://api.treqs.ai",
        ),
    ]


def test_repo_local_commands_fail_clearly_outside_git_repo(tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    commands = [
        ("project", "use", "trevor/mnist"),
        ("project", "status"),
        ("project", "clear"),
        ("requests", "list"),
        ("requests", "create", "--title", "Train model"),
        ("requests", "show", "request-1"),
    ]

    for args in commands:
        result = _run_treqs_module(*args, cwd=tmp_path, config_home=config_home)
        assert result.returncode == 1, result.stderr
        assert "requires a git repository" in result.stderr
        assert "Traceback" not in result.stderr

    assert not (tmp_path / ".treqs").exists()


def _training_request_payload() -> TrainingRequest:
    return TrainingRequest(
        id="request-1",
        title="Train model",
        description="Train a small model",
        status="draft",
        projectSlug="mnist",
        createdAt="2026-01-01T00:00:00.000Z",
        updatedAt="2026-01-01T00:00:00.000Z",
    )


def _run_treqs_module(
    *args: str,
    cwd: Path,
    config_home: Path,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["TREQS_CONFIG_HOME"] = str(config_home)
    current_pythonpath = env.get("PYTHONPATH", "")
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = (
        f"{src_path}{os.pathsep}{current_pythonpath}" if current_pythonpath else src_path
    )
    return subprocess.run(
        [sys.executable, "-m", "treqs_cli", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
