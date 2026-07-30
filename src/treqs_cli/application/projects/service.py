from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from ...context import OwnerScope, owner_path
from ...models import AuthState, RepoContext
from .models import Project, ProjectCreateInput


class ProjectApi(Protocol):
    def create_project(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> Project: ...

    def get_project(
        self,
        auth_state: AuthState,
        path: str,
    ) -> Project: ...


@dataclass(frozen=True)
class ProjectService:
    client: ProjectApi
    auth_state: AuthState
    scope: OwnerScope | RepoContext

    def create(self, create_input: ProjectCreateInput) -> Project:
        return self.client.create_project(
            self.auth_state,
            projects_path(self.scope),
            create_input.to_api_payload(),
        )

    def get(self, project_slug: str) -> Project:
        return self.client.get_project(
            self.auth_state,
            f"{projects_path(self.scope)}/{quote(project_slug, safe='')}",
        )


def projects_path(scope: OwnerScope | RepoContext) -> str:
    return owner_path(
        scope.owner_username,
        scope.current_username,
        "/projects",
    )
