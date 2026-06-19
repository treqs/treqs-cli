from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ...context import owner_path
from ...models import AuthState, RepoContext
from .models import (
    ComputeTarget,
    ComputeTargetCreateInput,
    RegistrationCode,
    SecretInput,
)


class ComputeTargetApi(Protocol):
    def list_compute_targets(
        self,
        auth_state: AuthState,
        path: str,
        *,
        include_agent: bool = False,
    ) -> list[ComputeTarget]: ...

    def create_compute_target(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> ComputeTarget: ...

    def set_compute_target_secret(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> None: ...

    def create_registration_code(
        self,
        auth_state: AuthState,
        path: str,
    ) -> RegistrationCode: ...


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

    def create(self, create_input: ComputeTargetCreateInput) -> ComputeTarget:
        return self.client.create_compute_target(
            self.auth_state,
            compute_targets_path(self.scope),
            create_input.to_api_payload(),
        )

    def set_secret(self, target_id: str, secret: SecretInput) -> None:
        self.client.set_compute_target_secret(
            self.auth_state,
            compute_target_secrets_path(self.scope, target_id),
            secret.to_api_payload(),
        )

    def create_registration_code(self, target_id: str) -> RegistrationCode:
        return self.client.create_registration_code(
            self.auth_state,
            registration_codes_path(self.scope, target_id),
        )


def compute_targets_path(scope: ComputeTargetScope | RepoContext) -> str:
    return owner_path(
        scope.owner_username,
        scope.current_username,
        "/compute-targets",
    )


def compute_target_path(scope: ComputeTargetScope | RepoContext, target_id: str) -> str:
    return f"{compute_targets_path(scope)}/{target_id}"


def compute_target_secrets_path(
    scope: ComputeTargetScope | RepoContext,
    target_id: str,
) -> str:
    return f"{compute_target_path(scope, target_id)}/secrets"


def registration_codes_path(
    scope: ComputeTargetScope | RepoContext,
    target_id: str,
) -> str:
    return f"{compute_target_path(scope, target_id)}/agent/registration-codes"


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
