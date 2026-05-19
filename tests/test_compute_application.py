from __future__ import annotations

from treqs_cli.application.compute.models import ComputeTarget, compute_target_rows
from treqs_cli.application.compute.service import (
    ComputeTargetScope,
    ComputeTargetService,
    compute_targets_path,
    resolve_compute_target_id,
)
from treqs_cli.models import AuthState, RepoContext


def test_compute_target_rows_and_selection_resolution() -> None:
    targets = [
        ComputeTarget(id="ct-alpha", name="GPU Alpha", type="dedicated", kind="dedicated"),
        ComputeTarget(id="ct-beta", name="GPU Beta", type="runpod", kind="on-demand"),
    ]

    assert compute_target_rows(targets) == [
        {
            "id": "ct-alpha",
            "name": "GPU Alpha",
            "kind": "dedicated",
            "type": "dedicated",
            "status": "",
            "agent": "",
        },
        {
            "id": "ct-beta",
            "name": "GPU Beta",
            "kind": "on-demand",
            "type": "runpod",
            "status": "",
            "agent": "",
        },
    ]
    assert resolve_compute_target_id(targets, "ct-alpha") == "ct-alpha"
    assert resolve_compute_target_id(targets, "GPU Beta") == "ct-beta"
    assert resolve_compute_target_id(targets, "ct-b") == "ct-beta"


def test_compute_target_service_builds_owner_scoped_path() -> None:
    client = _FakeComputeTargetClient()
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

    targets = ComputeTargetService(client, auth_state, repo_context).list(include_agent=True)

    assert targets[0].id == "ct-1"
    assert compute_targets_path(repo_context) == "/api/v1/user/orgs/acme/compute-targets"
    assert client.calls == [
        ("list", "/api/v1/user/orgs/acme/compute-targets", True),
    ]


def test_compute_target_service_can_use_owner_scope_without_repo_context() -> None:
    client = _FakeComputeTargetClient()
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    scope = ComputeTargetScope(owner_username="trevor", current_username="trevor")

    targets = ComputeTargetService(client, auth_state, scope).list()

    assert targets[0].id == "ct-1"
    assert compute_targets_path(scope) == "/api/v1/user/compute-targets"
    assert client.calls == [
        ("list", "/api/v1/user/compute-targets", False),
    ]


class _FakeComputeTargetClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def list_compute_targets(
        self,
        _auth_state: AuthState,
        path: str,
        *,
        include_agent: bool = False,
    ) -> list[ComputeTarget]:
        self.calls.append(("list", path, include_agent))
        return [ComputeTarget(id="ct-1", name="GPU", type="dedicated", kind="dedicated")]
