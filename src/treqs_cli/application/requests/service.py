from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ...context import owner_path
from ...errors import ApiError
from ...models import AuthState, RepoContext
from .models import (
    TrainingRequest,
    TrainingRequestCommentInput,
    TrainingRequestCreateInput,
    TrainingRequestEvent,
    TrainingRequestListFilters,
    TrainingRequestMember,
    TrainingRequestOpenInput,
    TrainingRequestQueueResult,
    TrainingRequestReviewInput,
    TrainingRequestReviewResult,
    TrainingRequestUpdateInput,
)


class TrainingRequestApi(Protocol):
    def list_training_requests(
        self,
        auth_state: AuthState,
        path: str,
        *,
        statuses: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TrainingRequest]: ...

    def create_training_request(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequest: ...

    def update_training_request(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequest: ...

    def get_training_request(
        self,
        auth_state: AuthState,
        path: str,
    ) -> TrainingRequest: ...

    def open_training_request(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequest: ...

    def queue_training_request(
        self,
        auth_state: AuthState,
        path: str,
    ) -> TrainingRequestQueueResult: ...

    def submit_training_request_review(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequestReviewResult: ...

    def add_training_request_comment(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequestEvent: ...

    def list_owner_members(
        self,
        auth_state: AuthState,
        path: str,
    ) -> list[TrainingRequestMember]: ...


@dataclass(frozen=True)
class TrainingRequestService:
    client: TrainingRequestApi
    auth_state: AuthState
    repo_context: RepoContext

    def list(self, filters: TrainingRequestListFilters) -> list[TrainingRequest]:
        return self.client.list_training_requests(
            self.auth_state,
            training_requests_path(self.repo_context),
            statuses=filters.statuses,
            limit=filters.limit,
            offset=filters.offset,
        )

    def create(self, create_input: TrainingRequestCreateInput) -> TrainingRequest:
        return self.client.create_training_request(
            self.auth_state,
            training_requests_path(self.repo_context),
            create_input.to_api_payload(),
        )

    def update(
        self,
        request_id: str,
        update_input: TrainingRequestUpdateInput,
    ) -> TrainingRequest:
        return self.client.update_training_request(
            self.auth_state,
            training_request_path(self.repo_context, request_id),
            update_input.to_api_payload(),
        )

    def get(self, request_id: str) -> TrainingRequest:
        return self.client.get_training_request(
            self.auth_state,
            training_request_path(self.repo_context, request_id),
        )

    def open(self, request_id: str, open_input: TrainingRequestOpenInput) -> TrainingRequest:
        return self.client.open_training_request(
            self.auth_state,
            f"{training_request_path(self.repo_context, request_id)}/open",
            open_input.to_api_payload(),
        )

    def queue(self, request_id: str) -> TrainingRequestQueueResult:
        return self.client.queue_training_request(
            self.auth_state,
            f"{training_request_path(self.repo_context, request_id)}/queue",
        )

    def review(
        self,
        request_id: str,
        review_input: TrainingRequestReviewInput,
    ) -> TrainingRequestReviewResult:
        return self.client.submit_training_request_review(
            self.auth_state,
            f"{training_request_path(self.repo_context, request_id)}/reviews",
            review_input.to_api_payload(),
        )

    def add_comment(
        self,
        request_id: str,
        comment_input: TrainingRequestCommentInput,
    ) -> TrainingRequestEvent:
        return self.client.add_training_request_comment(
            self.auth_state,
            f"{training_request_path(self.repo_context, request_id)}/comments",
            comment_input.to_api_payload(),
        )

    def list_potential_reviewers(self) -> Sequence[TrainingRequestMember]:
        """Owner members eligible to be assigned as reviewers.

        Only organization owners expose a members list; a personal owner has
        no one to assign but themselves, so callers fall back to treating
        `--reviewer` selections as raw user IDs in that case.
        """
        try:
            return self.client.list_owner_members(
                self.auth_state,
                owner_path(
                    self.repo_context.owner_username,
                    self.repo_context.current_username,
                    "/members",
                ),
            )
        except ApiError as exc:
            if exc.status_code == 404:
                return []
            raise


def training_requests_path(repo_context: RepoContext) -> str:
    return owner_path(
        repo_context.owner_username,
        repo_context.current_username,
        f"/projects/{repo_context.project_slug}/training-requests",
    )


def training_request_path(repo_context: RepoContext, request_id: str) -> str:
    return f"{training_requests_path(repo_context)}/{request_id}"


def resolve_reviewer_ids(
    members: Sequence[TrainingRequestMember],
    selections: Sequence[str],
) -> list[str]:
    """Resolve --reviewer/--add-reviewer/--remove-reviewer tokens to user IDs.

    Each selection may be a member username (case-insensitive) or a raw user
    ID. When the owner has no members list available (personal owners don't
    expose one), tokens are passed through as-is and left for the API to
    validate.
    """
    id_set = {member.id for member in members}
    username_to_id = {member.username.lower(): member.id for member in members}

    resolved: list[str] = []
    for selection in selections:
        token = selection.strip()
        if not token:
            raise ValueError("Reviewer selection cannot be empty.")
        if token in id_set:
            resolved.append(token)
            continue
        matched_id = username_to_id.get(token.lower())
        if matched_id is not None:
            resolved.append(matched_id)
            continue
        if not members:
            # No members list to check against (e.g. a personal owner):
            # assume the token is already a user ID and let the API validate it.
            resolved.append(token)
            continue
        raise ValueError(
            f"Reviewer not found in owner context: {selection}. Use a member username or user ID."
        )
    return resolved
