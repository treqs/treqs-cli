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
    compute_target_id: str | None = None
    workflow_snapshot_id: str | None = None
    source_branch: str | None = None
    lineage_mode: str | None = None

    def to_api_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"title": self.title, "status": self.status}
        if self.description is not None:
            payload["description"] = self.description
        if self.workflow_path is not None:
            payload["workflowPath"] = self.workflow_path
        if self.compute_target_id is not None:
            payload["computeSelection"] = {"targetId": self.compute_target_id}
        if self.workflow_snapshot_id is not None:
            payload["workflowSnapshotId"] = self.workflow_snapshot_id
        if self.source_branch is not None:
            payload["codeConfig"] = {"sourceBranch": self.source_branch}
        if self.lineage_mode is not None:
            payload["lineagePublicationMode"] = self.lineage_mode
        return payload


class TrainingRequestUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    status: TrainingRequestStatus | None = None
    workflow_path: str | None = None
    compute_target_id: str | None = None
    workflow_snapshot_id: str | None = None
    source_branch: str | None = None
    lineage_mode: str | None = None
    clear_description: bool = False
    clear_workflow_path: bool = False
    clear_compute_target: bool = False
    clear_workflow_snapshot: bool = False
    clear_source_branch: bool = False
    clear_lineage_mode: bool = False

    def to_api_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.title is not None:
            payload["title"] = self.title
        if self.clear_description:
            payload["description"] = None
        elif self.description is not None:
            payload["description"] = self.description
        if self.status is not None:
            payload["status"] = self.status
        if self.clear_workflow_path:
            payload["workflowPath"] = None
        elif self.workflow_path is not None:
            payload["workflowPath"] = self.workflow_path
        if self.clear_compute_target:
            payload["computeSelection"] = {"targetId": None}
        elif self.compute_target_id is not None:
            payload["computeSelection"] = {"targetId": self.compute_target_id}
        if self.clear_workflow_snapshot:
            payload["workflowSnapshotId"] = None
        elif self.workflow_snapshot_id is not None:
            payload["workflowSnapshotId"] = self.workflow_snapshot_id
        if self.clear_source_branch:
            payload["codeConfig"] = {"sourceBranch": None}
        elif self.source_branch is not None:
            payload["codeConfig"] = {"sourceBranch": self.source_branch}
        if self.clear_lineage_mode:
            payload["lineagePublicationMode"] = None
        elif self.lineage_mode is not None:
            payload["lineagePublicationMode"] = self.lineage_mode
        return payload


class TrainingRequestOpenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_path: str | None = None
    compute_target_id: str

    def to_api_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"computeSelection": {"targetId": self.compute_target_id}}
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
    workflowSnapshotId: str | None = None
    computeSelection: dict[str, object] | None = None
    lineagePublishedUrl: str | None = None
    lineagePublishedSessionHash: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class TrainingRequestQueueResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    trainingRequest: TrainingRequest
    jobId: str | None = None
    warningMessage: str | None = None


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
