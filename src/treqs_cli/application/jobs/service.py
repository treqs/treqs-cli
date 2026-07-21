from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from ...context import OwnerScope, owner_path
from ...models import AuthState, RepoContext
from .models import (
    JobStatus,
    LineageRepublishResult,
    LogPollResult,
    ProjectJobs,
    TrainingJob,
)

TERMINAL_JOB_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


class JobsApi(Protocol):
    def list_project_jobs(
        self,
        auth_state: AuthState,
        path: str,
        *,
        limit: int,
        status: str | None = None,
    ) -> ProjectJobs: ...

    def get_project_job(
        self,
        auth_state: AuthState,
        path: str,
    ) -> TrainingJob: ...

    def republish_job_lineage(
        self,
        auth_state: AuthState,
        path: str,
    ) -> LineageRepublishResult: ...

    def cancel_job(
        self,
        auth_state: AuthState,
        path: str,
    ) -> TrainingJob: ...


class JobLogApi(Protocol):
    def poll_job_logs(
        self,
        auth_state: AuthState,
        path: str,
        *,
        from_sequence: int,
        timeout_ms: int,
    ) -> LogPollResult: ...


@dataclass(frozen=True)
class JobService:
    client: JobsApi
    auth_state: AuthState
    repo_context: RepoContext

    def list(self, *, limit: int, statuses: Sequence[JobStatus] = ()) -> list[TrainingJob]:
        if not statuses:
            return self.client.list_project_jobs(
                self.auth_state,
                project_jobs_path(self.repo_context),
                limit=limit,
            ).all_jobs()

        jobs: list[TrainingJob] = []
        seen: set[str] = set()
        for status in statuses:
            grouped_jobs = self.client.list_project_jobs(
                self.auth_state,
                project_jobs_path(self.repo_context),
                limit=limit,
                status=status,
            )
            for job in grouped_jobs.all_jobs():
                if job.id in seen:
                    continue
                seen.add(job.id)
                jobs.append(job)
        return jobs

    def get(self, job_id: str) -> TrainingJob:
        return self.client.get_project_job(
            self.auth_state,
            project_job_path(self.repo_context, job_id),
        )

    def republish_lineage(self, job_id: str) -> LineageRepublishResult:
        return self.client.republish_job_lineage(
            self.auth_state,
            f"{project_job_path(self.repo_context, job_id)}/lineage/republish",
        )

    def cancel(self, target_id: str, job_id: str) -> TrainingJob:
        return self.client.cancel_job(
            self.auth_state,
            job_cancel_path(self.repo_context, target_id, job_id),
        )


@dataclass(frozen=True)
class JobLogService:
    client: JobLogApi
    auth_state: AuthState
    scope: OwnerScope | RepoContext

    def poll(
        self,
        target_id: str,
        job_id: str,
        *,
        from_sequence: int,
        timeout_ms: int,
    ) -> LogPollResult:
        return self.client.poll_job_logs(
            self.auth_state,
            job_logs_poll_path(self.scope, target_id, job_id),
            from_sequence=from_sequence,
            timeout_ms=timeout_ms,
        )


def wait_for_terminal_job(
    fetch_job: Callable[[], TrainingJob],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = 5.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> TrainingJob:
    """Poll a job until it reaches a terminal state or the timeout expires."""
    deadline = monotonic() + timeout_seconds
    while True:
        job = fetch_job()
        if job.status in TERMINAL_JOB_STATUSES:
            return job
        if monotonic() >= deadline:
            raise TimeoutError(f"Timed out after {timeout_seconds:g}s waiting for job {job.id}")
        sleep(poll_interval_seconds)


def project_jobs_path(repo_context: RepoContext) -> str:
    return owner_path(
        repo_context.owner_username,
        repo_context.current_username,
        f"/projects/{repo_context.project_slug}/jobs",
    )


def project_job_path(repo_context: RepoContext, job_id: str) -> str:
    return f"{project_jobs_path(repo_context)}/{quote(job_id, safe='')}"


def job_logs_poll_path(
    scope: OwnerScope | RepoContext,
    target_id: str,
    job_id: str,
) -> str:
    return owner_path(
        scope.owner_username,
        scope.current_username,
        f"/compute-targets/{quote(target_id, safe='')}/jobs/{quote(job_id, safe='')}/logs/poll",
    )


def job_cancel_path(
    scope: OwnerScope | RepoContext,
    target_id: str,
    job_id: str,
) -> str:
    return owner_path(
        scope.owner_username,
        scope.current_username,
        f"/compute-targets/{quote(target_id, safe='')}/jobs/{quote(job_id, safe='')}/cancel",
    )
