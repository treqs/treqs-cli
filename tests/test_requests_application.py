from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from treqs_cli.application.requests.models import (
    TrainingRequest,
    TrainingRequestCreateInput,
    TrainingRequestListFilters,
    TrainingRequestOpenInput,
    TrainingRequestQueueResult,
    TrainingRequestUpdateInput,
    training_request_rows,
)
from treqs_cli.application.requests.service import TrainingRequestService
from treqs_cli.models import AuthState, RepoContext


def test_create_input_builds_api_payload_and_forbids_unknown_fields() -> None:
    create_input = TrainingRequestCreateInput(
        title="Train model",
        description="Train a small model",
        status="draft",
        workflow_path=".github/workflows/train.yml",
        compute_target_id="ct-1",
        workflow_snapshot_id="snapshot-1",
        source_branch="tb/mnist-e2e-story",
    )

    assert create_input.to_api_payload() == {
        "title": "Train model",
        "description": "Train a small model",
        "status": "draft",
        "workflowPath": ".github/workflows/train.yml",
        "computeSelection": {"targetId": "ct-1"},
        "workflowSnapshotId": "snapshot-1",
        "codeConfig": {"sourceBranch": "tb/mnist-e2e-story"},
    }
    with pytest.raises(ValidationError):
        TrainingRequestCreateInput.model_validate({"title": "Train model", "unexpected": "field"})


def test_workflow_self_publishes_detection() -> None:
    from treqs_cli.commands.requests import workflow_self_publishes

    assert workflow_self_publishes("publish: |\n  roar register --public --yes\n")
    assert workflow_self_publishes("cmd: roar   register model.npz")
    assert not workflow_self_publishes("train: roar run -- python train.py\n")
    assert not workflow_self_publishes("echo registered lineage")


def test_create_input_includes_lineage_mode_when_set() -> None:
    create_input = TrainingRequestCreateInput(
        title="Private run",
        workflow_path=".treqs/workflows/mnist.yaml",
        source_branch="tb/x",
        lineage_mode="private",
    )

    assert create_input.to_api_payload()["lineagePublicationMode"] == "private"
    # Omitted by default so existing (non-lineage) creates are unchanged.
    assert "lineagePublicationMode" not in TrainingRequestCreateInput(title="x").to_api_payload()


def test_update_input_builds_clear_payload() -> None:
    update_input = TrainingRequestUpdateInput(
        clear_description=True,
        clear_workflow_path=True,
        clear_compute_target=True,
        clear_workflow_snapshot=True,
        clear_source_branch=True,
    )

    assert update_input.to_api_payload() == {
        "description": None,
        "workflowPath": None,
        "computeSelection": {"targetId": None},
        "workflowSnapshotId": None,
        "codeConfig": {"sourceBranch": None},
    }


def test_response_dto_allows_additive_api_fields_and_table_rows() -> None:
    request = TrainingRequest.model_validate(
        {
            "id": "request-1",
            "title": "Train model",
            "status": "queued",
            "projectSlug": "mnist",
            "createdAt": "2026-01-01T00:00:00.000Z",
            "newApiField": "kept",
        }
    )

    assert request.model_dump(mode="json")["newApiField"] == "kept"
    assert training_request_rows([request]) == [
        {
            "id": "request-1",
            "status": "queued",
            "title": "Train model",
            "created": "2026-01-01T00:00:00.000Z",
        }
    ]


def test_training_request_service_builds_owner_scoped_paths() -> None:
    client = _FakeTrainingRequestClient()
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    repo_context = RepoContext(
        api_url="https://api.treqs.ai",
        owner_id="org-1",
        owner_type="organization",
        owner_username="acme",
        owner_display_name="Acme",
        project_id="project-1",
        project_slug="mnist",
        project_name="MNIST",
        current_username="trevor",
    )
    service = TrainingRequestService(client, auth_state, repo_context)

    listed = service.list(
        TrainingRequestListFilters(statuses=("draft", "open"), limit=10, offset=5)
    )
    created = service.create(TrainingRequestCreateInput(title="Train model"))
    updated = service.update(
        "request-1",
        TrainingRequestUpdateInput(
            title="Updated model",
            workflow_path=".github/workflows/train.yml",
            compute_target_id="ct-1",
            workflow_snapshot_id="snapshot-1",
        ),
    )
    fetched = service.get("request-1")
    opened = service.open(
        "request-1",
        TrainingRequestOpenInput(
            workflow_path=".github/workflows/train.yml",
            compute_target_id="ct-1",
        ),
    )
    queued = service.queue("request-1")

    assert listed[0].id == "request-1"
    assert created.id == "request-2"
    assert updated.title == "Updated model"
    assert fetched.id == "request-1"
    assert opened.status == "open"
    assert queued.jobId == "job-1"
    assert client.calls == [
        (
            "list",
            "/api/v1/user/orgs/acme/projects/mnist/training-requests",
            ("draft", "open"),
            10,
            5,
        ),
        (
            "create",
            "/api/v1/user/orgs/acme/projects/mnist/training-requests",
            {"title": "Train model", "status": "draft"},
        ),
        (
            "update",
            "/api/v1/user/orgs/acme/projects/mnist/training-requests/request-1",
            {
                "title": "Updated model",
                "workflowPath": ".github/workflows/train.yml",
                "computeSelection": {"targetId": "ct-1"},
                "workflowSnapshotId": "snapshot-1",
            },
        ),
        (
            "get",
            "/api/v1/user/orgs/acme/projects/mnist/training-requests/request-1",
        ),
        (
            "open",
            "/api/v1/user/orgs/acme/projects/mnist/training-requests/request-1/open",
            {
                "workflowPath": ".github/workflows/train.yml",
                "computeSelection": {"targetId": "ct-1"},
            },
        ),
        (
            "queue",
            "/api/v1/user/orgs/acme/projects/mnist/training-requests/request-1/queue",
        ),
    ]


class _FakeTrainingRequestClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def list_training_requests(
        self,
        _auth_state: AuthState,
        path: str,
        *,
        statuses: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TrainingRequest]:
        self.calls.append(("list", path, tuple(statuses or ()), limit, offset))
        return [
            TrainingRequest(
                id="request-1",
                title="Train model",
                status="draft",
                projectSlug="mnist",
            )
        ]

    def create_training_request(
        self,
        _auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequest:
        self.calls.append(("create", path, json_payload))
        return TrainingRequest(
            id="request-2",
            title=str(json_payload["title"]),
            status=str(json_payload["status"]),
            projectSlug="mnist",
        )

    def update_training_request(
        self,
        _auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequest:
        self.calls.append(("update", path, json_payload))
        return TrainingRequest(
            id="request-1",
            title=str(json_payload["title"]),
            status="draft",
            workflowPath=str(json_payload["workflowPath"]),
            computeSelection={"targetId": "ct-1"},
            projectSlug="mnist",
        )

    def get_training_request(
        self,
        _auth_state: AuthState,
        path: str,
    ) -> TrainingRequest:
        self.calls.append(("get", path))
        return TrainingRequest(
            id="request-1",
            title="Train model",
            status="draft",
            projectSlug="mnist",
        )

    def open_training_request(
        self,
        _auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequest:
        self.calls.append(("open", path, json_payload))
        return TrainingRequest(
            id="request-1",
            title="Train model",
            status="open",
            workflowPath=str(json_payload["workflowPath"]),
            computeSelection={"targetId": "ct-1"},
            projectSlug="mnist",
        )

    def queue_training_request(
        self,
        _auth_state: AuthState,
        path: str,
    ) -> TrainingRequestQueueResult:
        self.calls.append(("queue", path))
        return TrainingRequestQueueResult(
            trainingRequest=TrainingRequest(
                id="request-1",
                title="Train model",
                status="queued",
                projectSlug="mnist",
            ),
            jobId="job-1",
        )
