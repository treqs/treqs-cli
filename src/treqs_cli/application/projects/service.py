from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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


def projects_path(scope: OwnerScope | RepoContext) -> str:
    return owner_path(
        scope.owner_username,
        scope.current_username,
        "/projects",
    )
