from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal[
    "QUEUED",
    "ASSIGNED",
    "ACQUIRED",
    "IN_PROGRESS",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]
JOB_STATUSES: tuple[JobStatus, ...] = (
    "QUEUED",
    "ASSIGNED",
    "ACQUIRED",
    "IN_PROGRESS",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)


class JobTrainingRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str | None = None
    status: str | None = None
    projectSlug: str | None = None


class TrainingJob(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    trainingRequestId: str | None = None
    projectId: str | None = None
    projectSlug: str | None = None
    computeTargetId: str | None = None
    agentId: str | None = None
    status: str
    trainingRequest: JobTrainingRequest | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None


class ProjectJobs(BaseModel):
    model_config = ConfigDict(extra="allow")

    activeJobs: list[TrainingJob] = Field(default_factory=list)
    queuedJobs: list[TrainingJob] = Field(default_factory=list)
    finishedJobs: list[TrainingJob] = Field(default_factory=list)

    def all_jobs(self) -> list[TrainingJob]:
        return [*self.activeJobs, *self.queuedJobs, *self.finishedJobs]


def filter_jobs(
    jobs: Iterable[TrainingJob],
    statuses: Sequence[str] = (),
) -> list[TrainingJob]:
    if not statuses:
        return list(jobs)
    allowed = set(statuses)
    return [job for job in jobs if job.status in allowed]


def job_rows(jobs: Sequence[TrainingJob]) -> list[dict[str, str]]:
    return [
        {
            "id": job.id,
            "status": job.status,
            "request": _request_title(job),
            "project": job.projectSlug or "",
            "target": job.computeTargetId or "",
            "created": job.createdAt or "",
        }
        for job in jobs
    ]


def _request_title(job: TrainingJob) -> str:
    if job.trainingRequest and job.trainingRequest.title:
        return job.trainingRequest.title
    return job.trainingRequestId or ""
