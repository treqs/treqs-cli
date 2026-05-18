from __future__ import annotations

from pathlib import Path

import pytest

from treqs_cli.config import RepoContextStore
from treqs_cli.context import (
    build_repo_context,
    owner_base_path,
    owner_path,
    project_scope,
    resolve_project_selection,
)
from treqs_cli.models import AccessContext, AuthState


def test_owner_route_helpers_match_dashboard_semantics() -> None:
    assert owner_base_path("Trevor", "trevor") == "/api/v1/user"
    assert owner_base_path("@Acme", "trevor") == "/api/v1/user/orgs/acme"
    assert (
        owner_path("@Acme", "trevor", "/projects/mnist/training-requests")
        == "/api/v1/user/orgs/acme/projects/mnist/training-requests"
    )


def test_resolve_project_selection_by_owner_project() -> None:
    access_context = _access_context()

    owner, project = resolve_project_selection(access_context, "acme/mnist")

    assert owner.username == "acme"
    assert project.slug == "mnist"
    assert project_scope(owner, project) == "acme/mnist"


def test_resolve_project_selection_requires_disambiguation() -> None:
    access_context = _access_context()

    with pytest.raises(Exception, match="ambiguous"):
        resolve_project_selection(access_context, "mnist")


def test_repo_context_round_trip(tmp_path: Path) -> None:
    access_context = _access_context()
    owner, project = resolve_project_selection(access_context, "trevor/mnist")
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="token")
    context = build_repo_context(
        auth_state=auth_state,
        access_context=access_context,
        owner=owner,
        project=project,
    )
    store = RepoContextStore(tmp_path / ".treqs" / "config.toml")

    path = store.save(context)
    loaded = store.load()

    assert path.exists()
    assert loaded is not None
    assert loaded.owner_username == "trevor"
    assert loaded.project_slug == "mnist"


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
                    "display_name": "Acme",
                    "role": "admin",
                },
            ],
            "projects_by_owner": {
                "user-1": [
                    {
                        "id": "project-personal",
                        "slug": "mnist",
                        "name": "MNIST Personal",
                        "visibility": "private",
                        "can_write": True,
                    }
                ],
                "org-1": [
                    {
                        "id": "project-org",
                        "slug": "mnist",
                        "name": "MNIST Org",
                        "visibility": "private",
                        "can_write": True,
                    }
                ],
            },
        }
    )
