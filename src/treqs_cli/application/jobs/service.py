from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from ...context import owner_path
from ...models import AuthState, RepoContext
from .models import JobStatus, ProjectJobs, TrainingJob


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


def project_jobs_path(repo_context: RepoContext) -> str:
    return owner_path(
        repo_context.owner_username,
        repo_context.current_username,
        f"/projects/{repo_context.project_slug}/jobs",
    )


def project_job_path(repo_context: RepoContext, job_id: str) -> str:
    return f"{project_jobs_path(repo_context)}/{quote(job_id, safe='')}"
