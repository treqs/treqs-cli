from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Reserved stream id for the agent's own log. A task's stream is its id, so a
# non-UUID sentinel cannot collide with one.
AGENT_LOG_STREAM = "@agent"

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

JobUpdatePhase = Literal[
    "queued",
    "awaiting_compute_approval",
    "provisioning",
    "waiting_for_agent",
    "assigned",
    "acquired",
    "preparing",
    "running_task",
    "finalizing",
    "publishing_lineage",
    "blocked",
    "terminal",
]
JobLifecycleSeverity = Literal["info", "warning", "error"]


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
    lineagePublicationMode: str | None = None
    lineagePublicationStatus: str | None = None
    lineagePublishedUrl: str | None = None
    lineagePublishedSessionHash: str | None = None
    lineagePublicationError: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None


class TrainingTask(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    status: str
    exitCode: int | None = None
    failureReason: str | None = None
    errorClass: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None


def task_rows(tasks: Sequence[TrainingTask]) -> list[dict[str, str]]:
    return [
        {
            "name": task.name,
            "status": task.status,
            # An unrecorded exit code is not exit 0; show it as absent.
            "exit": "" if task.exitCode is None else str(task.exitCode),
            "reason": task.failureReason or "",
            "error": task.errorClass or "",
            "started": task.startedAt or "",
        }
        for task in tasks
    ]


class ProjectJobs(BaseModel):
    model_config = ConfigDict(extra="allow")

    activeJobs: list[TrainingJob] = Field(default_factory=list)
    queuedJobs: list[TrainingJob] = Field(default_factory=list)
    finishedJobs: list[TrainingJob] = Field(default_factory=list)

    def all_jobs(self) -> list[TrainingJob]:
        return [*self.activeJobs, *self.queuedJobs, *self.finishedJobs]


class JobUpdateCompute(BaseModel):
    model_config = ConfigDict(extra="allow")

    targetId: str
    targetName: str | None = None
    instanceId: str | None = None
    status: str | None = None
    attempt: int | None = None


class JobUpdateTask(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    status: str
    # A terminal snapshot names the task that ended the job. exitCode is absent
    # on older servers and null when the task never launched; neither is the
    # same as exit 0, so both stay None rather than defaulting to a number.
    exitCode: int | None = None
    failureReason: str | None = None
    errorClass: str | None = None

    def describe_failure(self) -> str:
        """One line naming the step that failed, and what is known about why."""
        detail = []
        if self.exitCode is not None:
            detail.append(f"exit code {self.exitCode}")
        if self.failureReason:
            detail.append(self.failureReason)
        if self.errorClass:
            detail.append(self.errorClass)
        if not detail:
            return f"task {self.name}"
        return f"task {self.name} ({', '.join(detail)})"


class JobUpdateSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    jobStatus: JobStatus
    phase: JobUpdatePhase
    message: str
    actionRequired: str | None = None
    compute: JobUpdateCompute | None = None
    task: JobUpdateTask | None = None
    lineagePublicationStatus: str | None = None


class JobLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    kind: str
    occurredAt: str
    severity: JobLifecycleSeverity
    message: str
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


class JobUpdates(BaseModel):
    model_config = ConfigDict(extra="allow")

    snapshot: JobUpdateSnapshot
    events: list[JobLifecycleEvent] = Field(default_factory=list)
    nextCursor: str | None = None
    terminal: bool = False


class LineageRepublishResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    publication_status: str
    published_session_hash: str | None = None
    published_url: str | None = None


class LogChunk(BaseModel):
    model_config = ConfigDict(extra="allow")

    sequence: int
    content: str


class LogPollResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    chunks: list[LogChunk] = Field(default_factory=list)
    hasMore: bool = False
    nextSequence: int = 0


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
