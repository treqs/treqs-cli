from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from treqs_cli.application.requests.models import (
    TrainingRequest,
    TrainingRequestCreateInput,
    TrainingRequestListFilters,
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
    )

    assert create_input.to_api_payload() == {
        "title": "Train model",
        "description": "Train a small model",
        "status": "draft",
        "workflowPath": ".github/workflows/train.yml",
    }
    with pytest.raises(ValidationError):
        TrainingRequestCreateInput.model_validate({"title": "Train model", "unexpected": "field"})


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
    fetched = service.get("request-1")

    assert listed[0].id == "request-1"
    assert created.id == "request-2"
    assert fetched.id == "request-1"
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
            "get",
            "/api/v1/user/orgs/acme/projects/mnist/training-requests/request-1",
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
        json_payload: dict[str, str],
    ) -> TrainingRequest:
        self.calls.append(("create", path, json_payload))
        return TrainingRequest(
            id="request-2",
            title=json_payload["title"],
            status=json_payload["status"],
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
