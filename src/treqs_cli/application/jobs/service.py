from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import quote

from ...context import OwnerScope, owner_path
from ...errors import ApiError
from ...models import AuthState, RepoContext
from .models import (
    JobStatus,
    JobUpdatePhase,
    JobUpdates,
    JobUpdateSnapshot,
    LineageRepublishResult,
    LogPollResult,
    ProjectJobs,
    TrainingJob,
    TrainingTask,
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

    def poll_job_updates(
        self,
        auth_state: AuthState,
        path: str,
        *,
        cursor: str | None,
        timeout_ms: int,
    ) -> JobUpdates: ...

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

    def list_job_tasks(
        self,
        auth_state: AuthState,
        path: str,
    ) -> list[TrainingTask]: ...


class JobLogApi(Protocol):
    def poll_job_logs(
        self,
        auth_state: AuthState,
        path: str,
        *,
        from_sequence: int,
        timeout_ms: int,
        stream: str | None = None,
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

    def poll_updates(
        self,
        job_id: str,
        *,
        cursor: str | None,
        timeout_ms: int,
    ) -> JobUpdates:
        return self.client.poll_job_updates(
            self.auth_state,
            project_job_updates_path(self.repo_context, job_id),
            cursor=cursor,
            timeout_ms=timeout_ms,
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

    def tasks(self, target_id: str, job_id: str) -> list[TrainingTask]:
        return self.client.list_job_tasks(
            self.auth_state,
            job_tasks_path(self.repo_context, target_id, job_id),
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
        stream: str | None = None,
    ) -> LogPollResult:
        return self.client.poll_job_logs(
            self.auth_state,
            job_logs_poll_path(self.scope, target_id, job_id),
            from_sequence=from_sequence,
            timeout_ms=timeout_ms,
            stream=stream,
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


class JobWatchSource(Protocol):
    def poll_updates(
        self,
        job_id: str,
        *,
        cursor: str | None,
        timeout_ms: int,
    ) -> JobUpdates: ...

    def get(self, job_id: str) -> TrainingJob: ...


def watch_job(
    source: JobWatchSource,
    job_id: str,
    *,
    timeout_seconds: float,
    poll_timeout_ms: int = 25000,
    heartbeat_seconds: float = 25.0,
    legacy_poll_interval_seconds: float = 5.0,
    on_update: Callable[[JobUpdates], None] | None = None,
    on_heartbeat: Callable[[JobUpdateSnapshot], None] | None = None,
    on_poll: Callable[[], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> JobUpdates:
    """Watch lifecycle updates, falling back to coarse status polling on older APIs."""
    deadline = monotonic() + timeout_seconds
    cursor: str | None = None
    seen_event_ids: set[str] = set()
    all_events = []
    last_snapshot: str | None = None
    last_output_at = monotonic()
    legacy_polling = False

    while monotonic() < deadline:
        if legacy_polling:
            update = _legacy_job_update(source.get(job_id))
        else:
            remaining_ms = max(0, int((deadline - monotonic()) * 1000))
            try:
                update = source.poll_updates(
                    job_id,
                    cursor=cursor,
                    timeout_ms=min(poll_timeout_ms, remaining_ms),
                )
            except ApiError as exc:
                if exc.status_code != 404:
                    raise
                legacy_polling = True
                continue
            cursor = update.nextCursor or cursor

        new_events = [event for event in update.events if event.id not in seen_event_ids]
        for event in new_events:
            seen_event_ids.add(event.id)
            all_events.append(event)

        snapshot_key = update.snapshot.model_dump_json()
        snapshot_changed = snapshot_key != last_snapshot
        callback_update = update.model_copy(update={"events": new_events})
        if new_events or snapshot_changed:
            if on_update is not None:
                on_update(callback_update)
            last_snapshot = snapshot_key
            last_output_at = monotonic()
        elif monotonic() - last_output_at >= heartbeat_seconds:
            if on_heartbeat is not None:
                on_heartbeat(update.snapshot)
            last_output_at = monotonic()

        if on_poll is not None:
            on_poll()

        if update.terminal or update.snapshot.actionRequired is not None:
            return update.model_copy(update={"events": all_events, "nextCursor": cursor})

        if legacy_polling:
            remaining_seconds = max(0.0, deadline - monotonic())
            sleep(min(legacy_poll_interval_seconds, remaining_seconds))

    raise TimeoutError(f"Timed out after {timeout_seconds:g}s waiting for job {job_id}")


def _legacy_job_update(job: TrainingJob) -> JobUpdates:
    terminal = job.status in TERMINAL_JOB_STATUSES
    phases: dict[str, tuple[JobUpdatePhase, str]] = {
        "QUEUED": ("queued", "Job queued"),
        "ASSIGNED": ("assigned", "Job assigned to an agent"),
        "ACQUIRED": ("acquired", "Agent acquired the job"),
        "IN_PROGRESS": ("preparing", "Job is in progress"),
        "COMPLETED": ("terminal", "Job completed"),
        "FAILED": ("terminal", "Job failed"),
        "CANCELLED": ("terminal", "Job cancelled"),
    }
    phase, message = phases.get(job.status, ("queued", f"Job status: {job.status}"))
    return JobUpdates(
        snapshot=JobUpdateSnapshot(
            jobStatus=cast(JobStatus, job.status),
            phase=phase,
            message=message,
            lineagePublicationStatus=job.lineagePublicationStatus,
        ),
        terminal=terminal,
    )


def project_jobs_path(repo_context: RepoContext) -> str:
    return owner_path(
        repo_context.owner_username,
        repo_context.current_username,
        f"/projects/{repo_context.project_slug}/jobs",
    )


def project_job_path(repo_context: RepoContext, job_id: str) -> str:
    return f"{project_jobs_path(repo_context)}/{quote(job_id, safe='')}"


def project_job_updates_path(repo_context: RepoContext, job_id: str) -> str:
    return f"{project_job_path(repo_context, job_id)}/updates"


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


def job_tasks_path(
    scope: OwnerScope | RepoContext,
    target_id: str,
    job_id: str,
) -> str:
    return owner_path(
        scope.owner_username,
        scope.current_username,
        f"/compute-targets/{quote(target_id, safe='')}/jobs/{quote(job_id, safe='')}/tasks",
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
