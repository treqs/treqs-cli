from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ...context import owner_path
from ...models import AuthState, RepoContext
from .models import (
    TrainingRequest,
    TrainingRequestCommentInput,
    TrainingRequestCreateInput,
    TrainingRequestEvent,
    TrainingRequestListFilters,
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


def training_requests_path(repo_context: RepoContext) -> str:
    return owner_path(
        repo_context.owner_username,
        repo_context.current_username,
        f"/projects/{repo_context.project_slug}/training-requests",
    )


def training_request_path(repo_context: RepoContext, request_id: str) -> str:
    return f"{training_requests_path(repo_context)}/{request_id}"
