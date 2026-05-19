from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from treqs_cli.config import RepoContextStore, discover_repo_root, find_repo_root
from treqs_cli.context import (
    TreqsContext,
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


def test_resolve_project_selection_rejects_read_only_project() -> None:
    access_context = _access_context()

    with pytest.raises(Exception, match="not writable"):
        resolve_project_selection(access_context, "acme/readonly")


def test_find_repo_root_uses_git_metadata_from_nested_directory(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    nested = repo / "src" / "package"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    assert find_repo_root(nested) == repo.resolve()
    discovery = discover_repo_root(nested)
    assert discovery.root == repo.resolve()
    assert discovery.is_git_repo is True


def test_repo_discovery_marks_non_git_directory(tmp_path: Path) -> None:
    nested = tmp_path / "plain" / "nested"
    nested.mkdir(parents=True)

    discovery = discover_repo_root(nested)

    assert discovery.root == nested.resolve()
    assert discovery.is_git_repo is False


def test_treqs_context_records_repo_detection(tmp_path: Path) -> None:
    context = TreqsContext.create(
        api_url_override=None,
        json_output=False,
        cwd=tmp_path,
    )

    assert context.repo_root == tmp_path.resolve()
    assert context.is_git_repo is False


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
                    },
                    {
                        "id": "project-readonly",
                        "slug": "readonly",
                        "name": "Read Only",
                        "visibility": "private",
                        "can_write": False,
                    },
                ],
            },
        }
    )
