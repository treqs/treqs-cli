from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ...context import owner_path
from ...models import AuthState, RepoContext
from .models import ComputeTarget


class ComputeTargetApi(Protocol):
    def list_compute_targets(
        self,
        auth_state: AuthState,
        path: str,
        *,
        include_agent: bool = False,
    ) -> list[ComputeTarget]: ...


@dataclass(frozen=True)
class ComputeTargetScope:
    owner_username: str
    current_username: str | None


@dataclass(frozen=True)
class ComputeTargetService:
    client: ComputeTargetApi
    auth_state: AuthState
    scope: ComputeTargetScope | RepoContext

    def list(self, *, include_agent: bool = False) -> list[ComputeTarget]:
        return self.client.list_compute_targets(
            self.auth_state,
            compute_targets_path(self.scope),
            include_agent=include_agent,
        )


def compute_targets_path(scope: ComputeTargetScope | RepoContext) -> str:
    return owner_path(
        scope.owner_username,
        scope.current_username,
        "/compute-targets",
    )


def resolve_compute_target_id(
    targets: Sequence[ComputeTarget],
    selection: str,
) -> str:
    token = selection.strip()
    if not token:
        raise ValueError("Compute target selection cannot be empty.")

    exact_id_matches = [target for target in targets if target.id == token]
    if len(exact_id_matches) == 1:
        return exact_id_matches[0].id

    normalized = token.lower()
    name_matches = [target for target in targets if target.name.lower() == normalized]
    if len(name_matches) == 1:
        return name_matches[0].id
    if len(name_matches) > 1:
        raise ValueError(
            f"Compute target selection is ambiguous: {selection}. Use the compute target ID."
        )

    prefix_matches = [target for target in targets if target.id.startswith(token)]
    if len(prefix_matches) == 1:
        return prefix_matches[0].id
    if len(prefix_matches) > 1:
        raise ValueError(
            f"Compute target selection is ambiguous: {selection}. Use the full compute target ID."
        )

    raise ValueError(f"Compute target not found in owner context: {selection}")
