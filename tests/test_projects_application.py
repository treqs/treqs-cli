from __future__ import annotations

import pytest
from pydantic import ValidationError

from treqs_cli.application.projects.models import (
    Project,
    ProjectCreateInput,
    parse_code_config,
    slugify_name,
    validate_slug,
)
from treqs_cli.application.projects.service import (
    ProjectScope,
    ProjectService,
    projects_path,
)
from treqs_cli.models import AuthState, RepoContext


def test_create_input_builds_api_payload_and_forbids_unknown_fields() -> None:
    create_input = ProjectCreateInput(
        name="MNIST",
        slug="mnist",
        visibility="public",
        description="MNIST classifier",
        code_config=parse_code_config("github:https://github.com/treqs-ai/mnist"),
    )

    assert create_input.to_api_payload() == {
        "name": "MNIST",
        "slug": "mnist",
        "visibility": "public",
        "description": "MNIST classifier",
        "codeConfig": {
            "type": "github",
            "repositoryUrl": "https://github.com/treqs-ai/mnist",
            "fullName": "treqs-ai/mnist",
            "defaultBranch": "main",
            "accessMode": "public",
        },
    }
    with pytest.raises(ValidationError):
        ProjectCreateInput.model_validate({"name": "x", "slug": "x", "unexpected": "field"})


def test_minimal_create_input_defaults_to_private_and_omits_optional_fields() -> None:
    assert ProjectCreateInput(name="MNIST", slug="mnist").to_api_payload() == {
        "name": "MNIST",
        "slug": "mnist",
        "visibility": "private",
    }


def test_parse_code_config_handles_url_variants() -> None:
    expected = {
        "type": "github",
        "repositoryUrl": "https://github.com/owner/repo",
        "fullName": "owner/repo",
        "defaultBranch": "main",
        "accessMode": "public",
    }
    assert parse_code_config("github:https://github.com/owner/repo").to_api_payload() == expected
    assert (
        parse_code_config("github:https://github.com/owner/repo.git").to_api_payload() == expected
    )
    assert parse_code_config("github:owner/repo").to_api_payload() == expected
    assert (
        parse_code_config("github:https://github.com/owner/repo", access_mode="github_app")
        .to_api_payload()["accessMode"]
        == "github_app"
    )


def test_parse_code_config_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="Unsupported code config provider"):
        parse_code_config("gitlab:https://gitlab.com/owner/repo")
    with pytest.raises(ValueError, match="repository URL"):
        parse_code_config("github:")
    with pytest.raises(ValueError, match="owner and repo"):
        parse_code_config("github:https://github.com/owner")


def test_slug_helpers() -> None:
    assert slugify_name("My Cool Project!") == "my-cool-project"
    assert validate_slug("mnist-v2") == "mnist-v2"
    with pytest.raises(ValueError, match="lowercase"):
        validate_slug("Bad_Slug")


def test_project_service_builds_owner_scoped_path() -> None:
    client = _FakeProjectClient()
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    scope = ProjectScope(owner_username="acme", current_username="trevor")

    project = ProjectService(client, auth_state, scope).create(
        ProjectCreateInput(name="MNIST", slug="mnist")
    )

    assert project.id == "project-1"
    assert projects_path(scope) == "/api/v1/user/orgs/acme/projects"
    assert client.calls == [
        (
            "create",
            "/api/v1/user/orgs/acme/projects",
            {"name": "MNIST", "slug": "mnist", "visibility": "private"},
        ),
    ]


def test_project_service_uses_user_scope_for_self_owner() -> None:
    client = _FakeProjectClient()
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    scope = ProjectScope(owner_username="trevor", current_username="trevor")

    ProjectService(client, auth_state, scope).create(ProjectCreateInput(name="MNIST", slug="mnist"))

    assert projects_path(scope) == "/api/v1/user/projects"
    assert client.calls[0][1] == "/api/v1/user/projects"


def test_project_service_accepts_repo_context_scope() -> None:
    client = _FakeProjectClient()
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

    ProjectService(client, auth_state, repo_context).create(
        ProjectCreateInput(name="MNIST", slug="mnist")
    )

    assert client.calls[0][1] == "/api/v1/user/orgs/acme/projects"


class _FakeProjectClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def create_project(
        self,
        _auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> Project:
        self.calls.append(("create", path, json_payload))
        return Project(
            id="project-1",
            slug=str(json_payload["slug"]),
            name=str(json_payload["name"]),
            visibility=str(json_payload["visibility"]),
        )
