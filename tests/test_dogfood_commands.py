from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from click.testing import CliRunner

from treqs_cli.application.compute.models import ComputeTarget
from treqs_cli.application.jobs.models import JobUpdates, JobUpdateSnapshot, TrainingJob
from treqs_cli.application.requests.models import (
    TrainingRequest,
    TrainingRequestCreateInput,
    TrainingRequestQueueResult,
)
from treqs_cli.commands.run import run_command, validate_run_compute_target
from treqs_cli.config import AuthStore, RepoContextStore
from treqs_cli.context import TreqsContext
from treqs_cli.errors import ConfigError
from treqs_cli.models import AuthState, RepoContext


def test_run_chains_immutable_request_open_queue_and_job_lookup(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    commit = "a" * 40
    repo_context = RepoContext(
        api_url="https://api.treqs.ai",
        owner_id="owner-1",
        owner_type="user",
        owner_username="trevor",
        owner_display_name="Trevor",
        project_id="project-1",
        project_slug="xgboost-higgs",
        project_name="XGBoost HIGGS",
        current_username="trevor",
    )
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="token")
    state = TreqsContext(
        api_url_override=None,
        json_output=True,
        auth_store=AuthStore(tmp_path / "auth.json"),
        repo_context_store=RepoContextStore(tmp_path / ".treqs" / "config.toml"),
        cwd=tmp_path,
        repo_root=tmp_path,
        is_interactive=False,
        is_git_repo=True,
    )
    calls: list[tuple[str, object]] = []

    class FakeRepository:
        def __init__(self, _root: Path) -> None:
            pass

        def resolve_commit(self, revision: str) -> str:
            calls.append(("resolve", revision))
            return commit

        def is_clean(self) -> bool:
            return True

        def commit_is_pushed(self, value: str) -> bool:
            calls.append(("pushed", value))
            return True

        def path_exists_at_commit(self, value: str, path: str) -> bool:
            calls.append(("workflow", (value, path)))
            return True

        def current_branch(self) -> str:
            return "tb/dogfood-xgboost"

    class FakeClient:
        def __init__(self, _api_url: str) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class FakeComputeService:
        def __init__(self, *_args: object) -> None:
            pass

        def list(self, *, include_agent: bool = False) -> list[ComputeTarget]:
            calls.append(("targets", include_agent))
            return [
                ComputeTarget(
                    id="target-1",
                    name="eks-training-dev",
                    type="runpod",
                    kind="on-demand",
                    agent=None,
                )
            ]

    class FakeRequestService:
        def __init__(self, *_args: object) -> None:
            pass

        def create(self, create_input: Any) -> TrainingRequest:
            calls.append(("create", create_input))
            return TrainingRequest(
                id="request-1",
                title=create_input.title,
                status="draft",
                codeConfig=create_input.to_api_payload()["codeConfig"],
            )

        def open(self, request_id: str, open_input: Any) -> TrainingRequest:
            calls.append(("open", (request_id, open_input)))
            return TrainingRequest(
                id=request_id,
                title="Train XGBoost HIGGS",
                status="open",
                workflowSnapshotId="snapshot-1",
            )

        def queue(self, request_id: str) -> TrainingRequestQueueResult:
            calls.append(("queue", request_id))
            return TrainingRequestQueueResult(
                trainingRequest=TrainingRequest(
                    id=request_id,
                    title="Train XGBoost HIGGS",
                    status="queued",
                ),
                jobId="job-1",
            )

    class FakeJobService:
        def __init__(self, *_args: object) -> None:
            pass

        def get(self, job_id: str) -> TrainingJob:
            calls.append(("job", job_id))
            return TrainingJob(
                id=job_id,
                status="COMPLETED",
                lineagePublicationMode="private",
            )

    def fake_watch_job(*_args: object, **_kwargs: object) -> JobUpdates:
        calls.append(("watch", "job-1"))
        return JobUpdates(
            snapshot=JobUpdateSnapshot(
                jobStatus="COMPLETED",
                phase="terminal",
                message="Job completed",
            ),
            terminal=True,
        )

    monkeypatch.setattr("treqs_cli.commands.run.GitRepository", FakeRepository)
    monkeypatch.setattr("treqs_cli.commands.run.TreqsApiClient", FakeClient)
    monkeypatch.setattr("treqs_cli.commands.run.ComputeTargetService", FakeComputeService)
    monkeypatch.setattr("treqs_cli.commands.run.TrainingRequestService", FakeRequestService)
    monkeypatch.setattr("treqs_cli.commands.run.JobService", FakeJobService)
    monkeypatch.setattr("treqs_cli.commands.run.watch_job", fake_watch_job)
    monkeypatch.setattr(
        "treqs_cli.commands.run.load_project_api_context",
        lambda _state: (auth_state, repo_context),
    )

    result = CliRunner().invoke(
        run_command,
        [
            "--title",
            "Train XGBoost HIGGS",
            "--workflow",
            ".treqs/workflows/xgboost-higgs.yml",
            "--target",
            "eks-training-dev",
            "--lineage",
            "private",
            "--yes",
            "--follow",
        ],
        obj=state,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "completed"
    assert payload["sourceCommit"] == commit
    assert payload["workflowSnapshotId"] == "snapshot-1"
    assert payload["job"]["id"] == "job-1"

    create_input = cast(
        TrainingRequestCreateInput,
        next(value for action, value in calls if action == "create"),
    )
    assert create_input.source_commit == commit
    assert create_input.source_branch == "tb/dogfood-xgboost"
    assert create_input.workflow_path == ".treqs/workflows/xgboost-higgs.yml"
    assert create_input.compute_target_id == "target-1"
    assert create_input.lineage_mode == "private"
    assert ("targets", True) in calls
    assert ("queue", "request-1") in calls
    assert ("watch", "job-1") in calls


def test_run_compute_readiness_allows_dormant_auto_provisioned_target() -> None:
    validate_run_compute_target(
        ComputeTarget(
            id="target-1",
            name="RunPod",
            type="runpod",
            kind="on-demand",
            startupBehavior="auto-provision",
            agent=None,
        )
    )


def test_run_compute_readiness_rejects_unregistered_dedicated_target() -> None:
    with pytest.raises(ConfigError, match="no registered agent"):
        validate_run_compute_target(
            ComputeTarget(
                id="target-1",
                name="GPU box",
                type="dedicated",
                kind="dedicated",
                agent=None,
            )
        )


def test_run_compute_readiness_rejects_manual_start_target() -> None:
    with pytest.raises(ConfigError, match="only-if-running"):
        validate_run_compute_target(
            ComputeTarget(
                id="target-1",
                name="Manual GPU",
                type="runpod",
                kind="on-demand",
                startupBehavior="only-if-running",
                agent=None,
            )
        )
