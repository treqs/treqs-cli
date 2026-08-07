from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from treqs_cli.application.compute.models import ComputeTarget
from treqs_cli.application.jobs.models import ProjectJobs, TrainingJob
from treqs_cli.application.requests.models import (
    TrainingRequest,
    TrainingRequestEvent,
    TrainingRequestQueueResult,
)
from treqs_cli.cli import cli
from treqs_cli.commands.shared import auth_state_for_request
from treqs_cli.config import AuthStore, RepoContextStore
from treqs_cli.context import TreqsContext
from treqs_cli.errors import ConfigError
from treqs_cli.models import AccessContext, AuthState, RepoContext

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

    calls: list[tuple[object, ...]] = []

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
            json_payload: dict[str, object],
        ) -> TrainingRequest:
            calls.append(("create", path, json_payload))
            return TrainingRequest.model_validate(
                {**_training_request_payload().model_dump(mode="json"), **json_payload}
            )

        def update_training_request(
            self,
            auth_state: AuthState,
            path: str,
            json_payload: dict[str, object],
        ) -> TrainingRequest:
            calls.append(("update", path, json_payload))
            return TrainingRequest.model_validate(
                {
                    **_training_request_payload().model_dump(mode="json"),
                    **json_payload,
                    "id": "request-1",
                }
            )

        def get_training_request(
            self,
            auth_state: AuthState,
            path: str,
        ) -> TrainingRequest:
            calls.append(("show", path, auth_state.api_url))
            return _training_request_payload()

        def open_training_request(
            self,
            auth_state: AuthState,
            path: str,
            json_payload: dict[str, object],
        ) -> TrainingRequest:
            calls.append(("open", path, json_payload))
            return TrainingRequest.model_validate(
                {
                    **_training_request_payload().model_dump(mode="json"),
                    **json_payload,
                    "status": "open",
                }
            )

        def queue_training_request(
            self,
            auth_state: AuthState,
            path: str,
        ) -> TrainingRequestQueueResult:
            calls.append(("queue", path, auth_state.api_url))
            return TrainingRequestQueueResult(
                trainingRequest=TrainingRequest(
                    id="request-1",
                    title="Train model",
                    status="queued",
                    projectSlug="mnist",
                ),
                jobId="job-1",
            )

        def list_compute_targets(
            self,
            auth_state: AuthState,
            path: str,
            *,
            include_agent: bool = False,
        ) -> list[ComputeTarget]:
            calls.append(("compute-targets", path, auth_state.api_url, include_agent))
            return [ComputeTarget(id="ct-1", name="GPU", type="dedicated", kind="dedicated")]

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    listed = runner.invoke(
        cli,
        ["--json", "tr", "list", "--status", "draft", "--limit", "10"],
        env=env,
        catch_exceptions=False,
    )
    created = runner.invoke(
        cli,
        [
            "--json",
            "tr",
            "create",
            "--title",
            "Train model",
            "--description",
            "Train a small model",
            "--workflow-path",
            ".github/workflows/train.yml",
            "--workflow-snapshot-id",
            "snapshot-1",
        ],
        env=env,
        catch_exceptions=False,
    )
    shown = runner.invoke(
        cli,
        ["--json", "tr", "show", "request-1"],
        env=env,
        catch_exceptions=False,
    )
    updated = runner.invoke(
        cli,
        [
            "--json",
            "tr",
            "update",
            "request-1",
            "--title",
            "Updated model",
            "--clear-description",
            "--clear-workflow-path",
            "--clear-compute-target",
            "--clear-workflow-snapshot",
        ],
        env=env,
        catch_exceptions=False,
    )
    opened = runner.invoke(
        cli,
        [
            "--json",
            "tr",
            "open",
            "request-1",
            "--workflow-path",
            ".github/workflows/train.yml",
            "--compute-target",
            "GPU",
        ],
        env=env,
        catch_exceptions=False,
    )
    queued = runner.invoke(
        cli,
        ["--json", "tr", "queue", "request-1"],
        env=env,
        catch_exceptions=False,
    )

    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["id"] == "request-1"
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["workflowPath"] == ".github/workflows/train.yml"
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["id"] == "request-1"
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.output)["title"] == "Updated model"
    assert opened.exit_code == 0, opened.output
    assert json.loads(opened.output)["status"] == "open"
    assert queued.exit_code == 0, queued.output
    assert json.loads(queued.output)["jobId"] == "job-1"
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
                "workflowSnapshotId": "snapshot-1",
            },
        ),
        (
            "show",
            "/api/v1/user/projects/mnist/training-requests/request-1",
            "https://api.treqs.ai",
        ),
        (
            "update",
            "/api/v1/user/projects/mnist/training-requests/request-1",
            {
                "title": "Updated model",
                "description": None,
                "workflowPath": None,
                "computeSelection": {"targetId": None},
                "workflowSnapshotId": None,
            },
        ),
        ("compute-targets", "/api/v1/user/compute-targets", "https://api.treqs.ai", False),
        (
            "show",
            "/api/v1/user/projects/mnist/training-requests/request-1",
            "https://api.treqs.ai",
        ),
        (
            "open",
            "/api/v1/user/projects/mnist/training-requests/request-1/open",
            {
                "workflowPath": ".github/workflows/train.yml",
                "computeSelection": {"targetId": "ct-1"},
                "assigneeIds": [],
            },
        ),
        (
            "queue",
            "/api/v1/user/projects/mnist/training-requests/request-1/queue",
            "https://api.treqs.ai",
        ),
    ]


def test_tr_create_defaults_source_branch_from_git(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    config_home = tmp_path / "config"
    work_repo = tmp_path / "repo"
    work_repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "feature/xyz"], cwd=work_repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=work_repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=work_repo, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=work_repo, check=True
    )
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

    calls: list[tuple[object, ...]] = []

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def create_training_request(
            self,
            auth_state: AuthState,
            path: str,
            json_payload: dict[str, object],
        ) -> TrainingRequest:
            calls.append(("create", path, json_payload))
            return TrainingRequest.model_validate(
                {**_training_request_payload().model_dump(mode="json"), **json_payload}
            )

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    defaulted = runner.invoke(
        cli,
        ["--json", "tr", "create", "--title", "Train model"],
        env=env,
        catch_exceptions=False,
    )
    overridden = runner.invoke(
        cli,
        [
            "--json",
            "tr",
            "create",
            "--title",
            "Train model",
            "--source-branch",
            "explicit-branch",
        ],
        env=env,
        catch_exceptions=False,
    )

    assert defaulted.exit_code == 0, defaulted.output
    assert overridden.exit_code == 0, overridden.output
    assert calls == [
        (
            "create",
            "/api/v1/user/projects/mnist/training-requests",
            {
                "title": "Train model",
                "status": "draft",
                "codeConfig": {"sourceBranch": "feature/xyz"},
            },
        ),
        (
            "create",
            "/api/v1/user/projects/mnist/training-requests",
            {
                "title": "Train model",
                "status": "draft",
                "codeConfig": {"sourceBranch": "explicit-branch"},
            },
        ),
    ]


def test_tr_public_lineage_mode_requires_yes_non_interactively(
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

    calls: list[tuple[object, ...]] = []

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def create_training_request(
            self,
            auth_state: AuthState,
            path: str,
            json_payload: dict[str, object],
        ) -> TrainingRequest:
            calls.append(("create", path, json_payload))
            return TrainingRequest.model_validate(
                {**_training_request_payload().model_dump(mode="json"), **json_payload}
            )

        def update_training_request(
            self,
            auth_state: AuthState,
            path: str,
            json_payload: dict[str, object],
        ) -> TrainingRequest:
            calls.append(("update", path, json_payload))
            return TrainingRequest.model_validate(
                {**_training_request_payload().model_dump(mode="json"), **json_payload}
            )

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    # No --yes, and CliRunner is never a tty: must fail rather than hang on a prompt.
    blocked_create = runner.invoke(
        cli,
        [
            "tr",
            "create",
            "--title",
            "Train model",
            "--workflow-path",
            ".treqs/workflows/train.yaml",
            "--lineage-mode",
            "public",
        ],
        env=env,
    )
    blocked_update = runner.invoke(
        cli,
        ["tr", "update", "request-1", "--lineage-mode", "public_anonymous"],
        env=env,
    )

    assert blocked_create.exit_code != 0
    assert isinstance(blocked_create.exception, ConfigError)
    assert "--yes" in str(blocked_create.exception)
    assert blocked_update.exit_code != 0
    assert isinstance(blocked_update.exception, ConfigError)
    assert "--yes" in str(blocked_update.exception)
    assert calls == []

    # --yes bypasses the prompt and the request proceeds normally.
    allowed_create = runner.invoke(
        cli,
        [
            "--json",
            "tr",
            "create",
            "--title",
            "Train model",
            "--workflow-path",
            ".treqs/workflows/train.yaml",
            "--lineage-mode",
            "public",
            "--yes",
        ],
        env=env,
        catch_exceptions=False,
    )
    allowed_update = runner.invoke(
        cli,
        [
            "--json",
            "tr",
            "update",
            "request-1",
            "--lineage-mode",
            "public_anonymous",
            "--yes",
        ],
        env=env,
        catch_exceptions=False,
    )

    assert allowed_create.exit_code == 0, allowed_create.output
    assert allowed_update.exit_code == 0, allowed_update.output
    assert calls == [
        (
            "create",
            "/api/v1/user/projects/mnist/training-requests",
            {
                "title": "Train model",
                "status": "draft",
                "workflowPath": ".treqs/workflows/train.yaml",
                "lineagePublicationMode": "public",
            },
        ),
        (
            "update",
            "/api/v1/user/projects/mnist/training-requests/request-1",
            {"lineagePublicationMode": "public_anonymous"},
        ),
    ]


def test_tr_show_prints_lineage_publication_when_present(
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

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get_training_request(
            self,
            auth_state: AuthState,
            path: str,
        ) -> TrainingRequest:
            return TrainingRequest(
                id="request-1",
                title="Train model",
                status="open",
                projectSlug="mnist",
                lineagePublishedUrl="https://glaas.ai/dag/abc123",
                lineagePublishedSessionHash="abc123",
            )

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    shown = runner.invoke(cli, ["tr", "show", "request-1"], env=env, catch_exceptions=False)

    assert shown.exit_code == 0, shown.output
    assert "Session: abc123" in shown.output
    assert "Lineage URL: https://glaas.ai/dag/abc123" in shown.output


def test_tr_show_prints_reviewers_with_pending_and_decided_status(
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

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get_training_request(
            self,
            auth_state: AuthState,
            path: str,
        ) -> TrainingRequest:
            return TrainingRequest.model_validate(
                {
                    "id": "request-1",
                    "title": "Train model",
                    "status": "open",
                    "projectSlug": "mnist",
                    "assignees": [
                        {"userId": "user-jon", "user": {"id": "user-jon", "username": "jon"}},
                        {
                            "userId": "user-trevor",
                            "user": {"id": "user-trevor", "username": "trevor"},
                        },
                    ],
                    "reviews": [{"userId": "user-jon", "status": "approved"}],
                }
            )

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    shown = runner.invoke(cli, ["tr", "show", "request-1"], env=env, catch_exceptions=False)

    assert shown.exit_code == 0, shown.output
    assert "Reviewers:" in shown.output
    assert "jon  approved" in shown.output
    assert "trevor  pending" in shown.output


def test_tr_show_comments_flag_filters_events_in_human_and_json_mode(
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

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get_training_request(
            self,
            auth_state: AuthState,
            path: str,
        ) -> TrainingRequest:
            return TrainingRequest.model_validate(
                {
                    "id": "request-1",
                    "title": "Train model",
                    "status": "open",
                    "projectSlug": "mnist",
                    "events": [
                        {"id": "event-1", "type": "user_event", "subType": "created"},
                        {
                            "id": "event-2",
                            "type": "comment",
                            "content": "Looks good, approving.",
                            "user": {"id": "user-jon", "username": "jon"},
                            "createdAt": "2026-07-31T20:05:00.000Z",
                        },
                    ],
                }
            )

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    human = runner.invoke(
        cli, ["tr", "show", "request-1", "--comments"], env=env, catch_exceptions=False
    )
    as_json = runner.invoke(
        cli, ["tr", "show", "request-1", "--comments", "--json"], env=env, catch_exceptions=False
    )

    assert human.exit_code == 0, human.output
    assert "Comments on request-1 (1):" in human.output
    assert "jon ·" in human.output
    assert "Looks good, approving." in human.output
    assert "created" not in human.output

    assert as_json.exit_code == 0, as_json.output
    comments = json.loads(as_json.output)
    assert len(comments) == 1
    assert comments[0]["content"] == "Looks good, approving."


def test_tr_comment_posts_and_prints_confirmation(
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

    calls: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def add_training_request_comment(
            self,
            auth_state: AuthState,
            path: str,
            json_payload: dict[str, object],
        ) -> TrainingRequestEvent:
            calls.append((path, json_payload))
            return TrainingRequestEvent(
                id="comment-1",
                type="comment",
                content=str(json_payload["content"]),
                userId="user-1",
            )

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    result = runner.invoke(
        cli,
        ["tr", "comment", "request-1", "Looks good, approving."],
        env=env,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert "Commented on request-1." in result.output
    assert calls == [
        (
            "/api/v1/user/projects/mnist/training-requests/request-1/comments",
            {"content": "Looks good, approving."},
        )
    ]


def test_compute_and_jobs_commands_use_repo_project_context(
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

        def list_compute_targets(
            self,
            auth_state: AuthState,
            path: str,
            *,
            include_agent: bool = False,
        ) -> list[ComputeTarget]:
            calls.append(("targets", path, (auth_state.api_url, include_agent)))
            return [ComputeTarget(id="ct-1", name="GPU", type="dedicated", kind="dedicated")]

        def get_access_context(self, _auth_state: AuthState) -> AccessContext:
            return AccessContext.model_validate(_access_context_payload())

        def list_project_jobs(
            self,
            auth_state: AuthState,
            path: str,
            *,
            limit: int,
            status: str | None = None,
        ) -> ProjectJobs:
            calls.append(("jobs", path, (auth_state.api_url, limit, status)))
            return ProjectJobs(
                queuedJobs=[
                    TrainingJob(
                        id="job-1",
                        trainingRequestId="request-1",
                        projectSlug="mnist",
                        computeTargetId="ct-1",
                        status="QUEUED",
                    )
                ]
            )

        def get_project_job(
            self,
            auth_state: AuthState,
            path: str,
        ) -> TrainingJob:
            calls.append(("job", path, auth_state.api_url))
            return TrainingJob(
                id="job-1",
                trainingRequestId="request-1",
                projectSlug="mnist",
                computeTargetId="ct-1",
                status="QUEUED",
            )

    monkeypatch.setattr("treqs_cli.commands.compute.TreqsApiClient", FakeClient)
    monkeypatch.setattr("treqs_cli.commands.jobs.TreqsApiClient", FakeClient)
    monkeypatch.setattr("treqs_cli.commands.shared.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    targets = runner.invoke(
        cli,
        ["--json", "compute", "targets", "list", "--include-agent"],
        env=env,
        catch_exceptions=False,
    )
    jobs = runner.invoke(
        cli,
        ["--json", "jobs", "list", "--status", "QUEUED"],
        env=env,
        catch_exceptions=False,
    )
    job = runner.invoke(
        cli,
        ["--json", "jobs", "show", "job-1"],
        env=env,
        catch_exceptions=False,
    )

    assert targets.exit_code == 0, targets.output
    assert json.loads(targets.output)[0]["id"] == "ct-1"
    assert jobs.exit_code == 0, jobs.output
    assert json.loads(jobs.output)[0]["id"] == "job-1"
    assert job.exit_code == 0, job.output
    assert json.loads(job.output)["id"] == "job-1"
    assert calls == [
        ("targets", "/api/v1/user/compute-targets", ("https://api.treqs.ai", True)),
        ("jobs", "/api/v1/user/projects/mnist/jobs", ("https://api.treqs.ai", 20, "QUEUED")),
        ("job", "/api/v1/user/projects/mnist/jobs/job-1", "https://api.treqs.ai"),
    ]


def test_jobs_show_prints_lineage_publication_when_present(
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

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get_project_job(
            self,
            auth_state: AuthState,
            path: str,
        ) -> TrainingJob:
            return TrainingJob(
                id="job-1",
                trainingRequestId="request-1",
                projectSlug="mnist",
                status="COMPLETED",
                lineagePublishedUrl="https://glaas.ai/dag/abc123",
                lineagePublishedSessionHash="abc123",
            )

    monkeypatch.setattr("treqs_cli.commands.jobs.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    shown = runner.invoke(cli, ["jobs", "show", "job-1"], env=env, catch_exceptions=False)

    assert shown.exit_code == 0, shown.output
    assert "Session: abc123" in shown.output
    assert "Lineage URL: https://glaas.ai/dag/abc123" in shown.output


def test_jobs_cancel_resolves_target_from_job_and_cancels(
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

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get_project_job(self, _auth_state: AuthState, path: str) -> TrainingJob:
            calls.append(("get", path))
            return TrainingJob(
                id="job-1",
                projectSlug="mnist",
                computeTargetId="ct-1",
                status="QUEUED",
            )

        def cancel_job(self, _auth_state: AuthState, path: str) -> TrainingJob:
            calls.append(("cancel", path))
            return TrainingJob(id="job-1", computeTargetId="ct-1", status="CANCELLED")

    monkeypatch.setattr("treqs_cli.commands.jobs.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    result = runner.invoke(cli, ["jobs", "cancel", "job-1"], env=env, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "Cancelled job job-1." in result.output
    assert "Status: CANCELLED" in result.output
    assert calls == [
        ("get", "/api/v1/user/projects/mnist/jobs/job-1"),
        ("cancel", "/api/v1/user/compute-targets/ct-1/jobs/job-1/cancel"),
    ]


def test_jobs_cancel_with_explicit_target_skips_job_lookup(
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

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def list_compute_targets(
            self,
            _auth_state: AuthState,
            path: str,
            *,
            include_agent: bool = False,
        ) -> list[ComputeTarget]:
            calls.append(("targets", path))
            return [ComputeTarget(id="ct-2", name="gpu-box", type="dedicated", kind="dedicated")]

        def get_project_job(self, _auth_state: AuthState, path: str) -> TrainingJob:
            raise AssertionError("job lookup should be skipped when --target is given")

        def cancel_job(self, _auth_state: AuthState, path: str) -> TrainingJob:
            calls.append(("cancel", path))
            return TrainingJob(id="job-1", computeTargetId="ct-2", status="CANCELLED")

    monkeypatch.setattr("treqs_cli.commands.jobs.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    result = runner.invoke(
        cli,
        ["jobs", "cancel", "job-1", "--target", "gpu-box"],
        env=env,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        ("targets", "/api/v1/user/compute-targets"),
        ("cancel", "/api/v1/user/compute-targets/ct-2/jobs/job-1/cancel"),
    ]


def test_compute_targets_list_can_run_without_repo_context(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    config_home = tmp_path / "config"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    AuthStore(config_home / "auth.json").save(
        AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    )
    calls: list[tuple[str, str, object]] = []

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get_access_context(self, _auth_state: AuthState) -> AccessContext:
            return AccessContext.model_validate(_access_context_payload())

        def list_compute_targets(
            self,
            auth_state: AuthState,
            path: str,
            *,
            include_agent: bool = False,
        ) -> list[ComputeTarget]:
            calls.append(("targets", path, (auth_state.api_url, include_agent)))
            return [ComputeTarget(id="ct-1", name="GPU", type="dedicated", kind="dedicated")]

    monkeypatch.setattr("treqs_cli.commands.compute.TreqsApiClient", FakeClient)
    monkeypatch.setattr("treqs_cli.commands.shared.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_dir)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--json", "compute", "targets", "list", "--owner", "trevor"],
        env={"TREQS_CONFIG_HOME": str(config_home)},
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["id"] == "ct-1"
    assert calls == [
        ("targets", "/api/v1/user/compute-targets", ("https://api.treqs.ai", False)),
    ]


def test_json_flag_is_recognized_at_any_position(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    config_home = tmp_path / "config"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    AuthStore(config_home / "auth.json").save(
        AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    )

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get_access_context(self, _auth_state: AuthState) -> AccessContext:
            return AccessContext.model_validate(_access_context_payload())

        def list_compute_targets(
            self,
            auth_state: AuthState,
            path: str,
            *,
            include_agent: bool = False,
        ) -> list[ComputeTarget]:
            return [ComputeTarget(id="ct-1", name="GPU", type="dedicated", kind="dedicated")]

    monkeypatch.setattr("treqs_cli.commands.compute.TreqsApiClient", FakeClient)
    monkeypatch.setattr("treqs_cli.commands.shared.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_dir)
    env = {"TREQS_CONFIG_HOME": str(config_home)}
    runner = CliRunner()

    before = runner.invoke(
        cli,
        ["--json", "compute", "targets", "list", "--owner", "trevor"],
        env=env,
        catch_exceptions=False,
    )
    mid = runner.invoke(
        cli,
        ["compute", "--json", "targets", "list", "--owner", "trevor"],
        env=env,
        catch_exceptions=False,
    )
    after = runner.invoke(
        cli,
        ["compute", "targets", "list", "--owner", "trevor", "--json"],
        env=env,
        catch_exceptions=False,
    )
    no_flag = runner.invoke(
        cli,
        ["compute", "targets", "list", "--owner", "trevor"],
        env=env,
        catch_exceptions=False,
    )

    for label, result in [("before", before), ("mid", mid), ("after", after)]:
        assert result.exit_code == 0, f"{label}: {result.output}"
        assert json.loads(result.output)[0]["id"] == "ct-1", label

    assert no_flag.exit_code == 0, no_flag.output
    assert "Compute targets for" in no_flag.output


def test_json_flag_after_double_dash_is_a_literal_positional_value(
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

    calls: list[str] = []

    class FakeClient:
        def __init__(self, api_url: str) -> None:
            self.api_url = api_url

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get_training_request(self, auth_state: AuthState, path: str) -> TrainingRequest:
            calls.append(path)
            return _training_request_payload()

    monkeypatch.setattr("treqs_cli.commands.requests.TreqsApiClient", FakeClient)
    monkeypatch.chdir(work_repo)
    runner = CliRunner()
    env = {"TREQS_CONFIG_HOME": str(config_home)}

    # A literal "--json" after a `--` separator is the positional request-id argument,
    # not our global flag — the `--` must survive our own arg-scan and Click's own
    # nested group re-parsing so it isn't misread as the flag or rejected as an option.
    result = runner.invoke(
        cli,
        ["tr", "show", "--", "--json"],
        env=env,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    # Plain-text (not JSON) output confirms --json was NOT parsed as our flag.
    assert "ID: request-1" in result.output
    assert calls == [
        "/api/v1/user/projects/mnist/training-requests/--json",
    ]


def test_repo_local_commands_fail_clearly_outside_git_repo(tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    commands = [
        ("project", "use", "trevor/mnist"),
        ("project", "init"),
        ("project", "status"),
        ("project", "clear"),
        ("tr", "list"),
        ("tr", "create", "--title", "Train model"),
        ("tr", "show", "request-1"),
        ("tr", "update", "request-1", "--title", "Train model"),
        ("tr", "open", "request-1", "--compute-target", "ct-1"),
        ("tr", "queue", "request-1"),
        ("doctor", "--target", "ct-1"),
        (
            "run",
            "--title",
            "Train model",
            "--workflow",
            ".treqs/workflows/train.yml",
            "--target",
            "ct-1",
            "--yes",
        ),
        ("jobs", "list"),
        ("jobs", "show", "job-1"),
        ("jobs", "wait", "job-1"),
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


def _access_context_payload() -> dict[str, object]:
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
