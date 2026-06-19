from __future__ import annotations

import pytest

from treqs_cli.application.compute.models import (
    ComputeTarget,
    ComputeTargetCreateInput,
    RegistrationCode,
    SecretInput,
    compute_target_rows,
    parse_secret_assignment,
    validate_secret_name,
)
from treqs_cli.application.compute.service import (
    ComputeTargetScope,
    ComputeTargetService,
    compute_target_secrets_path,
    compute_targets_path,
    registration_codes_path,
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


def test_compute_target_create_input_sends_dedicated_payload_without_provider_config() -> None:
    create_input = ComputeTargetCreateInput(name="Dedicated GPU")

    assert create_input.to_api_payload() == {
        "kind": "dedicated",
        "type": "dedicated",
        "name": "Dedicated GPU",
        "resources": {},
        "costCalculation": {},
    }
    assert "providerConfig" not in create_input.to_api_payload()


def test_secret_name_validation_and_assignment_parsing() -> None:
    assert validate_secret_name("API_KEY") == "API_KEY"
    assert validate_secret_name("S3_2") == "S3_2"
    for bad in ("api_key", "1KEY", "WITH-DASH", ""):
        with pytest.raises(ValueError, match=r"secret name|cannot be empty"):
            validate_secret_name(bad)

    parsed = parse_secret_assignment("API_KEY=abc=123")
    assert parsed == SecretInput(name="API_KEY", value="abc=123")
    with pytest.raises(ValueError, match="KEY=VALUE"):
        parse_secret_assignment("API_KEY")
    with pytest.raises(ValueError, match="non-empty value"):
        parse_secret_assignment("API_KEY=")
    with pytest.raises(ValueError, match="secret name"):
        parse_secret_assignment("bad-name=value")


def test_compute_target_service_create_set_secret_and_registration_code_paths() -> None:
    client = _FakeComputeTargetClient()
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    scope = ComputeTargetScope(owner_username="acme", current_username="trevor")
    service = ComputeTargetService(client, auth_state, scope)

    created = service.create(ComputeTargetCreateInput(name="Dedicated GPU"))
    service.set_secret("ct-1", SecretInput(name="API_KEY", value="secret-value"))
    code = service.create_registration_code("ct-1")

    assert created.id == "ct-1"
    assert code.code == "ABC123"
    assert compute_target_secrets_path(scope, "ct-1") == (
        "/api/v1/user/orgs/acme/compute-targets/ct-1/secrets"
    )
    assert registration_codes_path(scope, "ct-1") == (
        "/api/v1/user/orgs/acme/compute-targets/ct-1/agent/registration-codes"
    )
    assert client.calls == [
        (
            "create",
            "/api/v1/user/orgs/acme/compute-targets",
            {
                "kind": "dedicated",
                "type": "dedicated",
                "name": "Dedicated GPU",
                "resources": {},
                "costCalculation": {},
            },
        ),
        (
            "set_secret",
            "/api/v1/user/orgs/acme/compute-targets/ct-1/secrets",
            {"name": "API_KEY", "value": "secret-value"},
        ),
        (
            "registration_code",
            "/api/v1/user/orgs/acme/compute-targets/ct-1/agent/registration-codes",
        ),
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

    def create_compute_target(
        self,
        _auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> ComputeTarget:
        self.calls.append(("create", path, json_payload))
        return ComputeTarget(
            id="ct-1",
            name=str(json_payload["name"]),
            type=str(json_payload["type"]),
            kind=str(json_payload["kind"]),
        )

    def set_compute_target_secret(
        self,
        _auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> None:
        self.calls.append(("set_secret", path, json_payload))

    def create_registration_code(
        self,
        _auth_state: AuthState,
        path: str,
    ) -> RegistrationCode:
        self.calls.append(("registration_code", path))
        return RegistrationCode(id="rc-1", code="ABC123", computeTargetId="ct-1")
