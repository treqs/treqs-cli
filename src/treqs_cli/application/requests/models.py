from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

TrainingRequestStatus = Literal["draft", "open", "closed", "queued", "completed"]
TRAINING_REQUEST_STATUSES: tuple[TrainingRequestStatus, ...] = (
    "draft",
    "open",
    "closed",
    "queued",
    "completed",
)


class TrainingRequestCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = None
    status: TrainingRequestStatus = "draft"
    workflow_path: str | None = None

    def to_api_payload(self) -> dict[str, str]:
        payload = {"title": self.title, "status": self.status}
        if self.description is not None:
            payload["description"] = self.description
        if self.workflow_path is not None:
            payload["workflowPath"] = self.workflow_path
        return payload


class TrainingRequestListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statuses: tuple[TrainingRequestStatus, ...] = ()
    limit: int = 20
    offset: int = 0


class TrainingRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    description: str | None = None
    status: str
    projectSlug: str | None = None
    workflowPath: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


def training_request_rows(requests: Sequence[TrainingRequest]) -> list[dict[str, str]]:
    return [
        {
            "id": request.id,
            "status": request.status,
            "title": request.title,
            "created": request.createdAt or "",
        }
        for request in requests
    ]
