from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import click

from ..api import TreqsApiClient
from ..application.compute.service import (
    ComputeTargetService,
    resolve_compute_target_id,
)
from ..application.jobs.models import (
    JOB_STATUSES,
    JobStatus,
    JobUpdates,
    JobUpdateSnapshot,
    job_rows,
    task_rows,
)
from ..application.jobs.service import (
    JobLogService,
    JobService,
    wait_for_terminal_job,
    watch_job,
)
from ..context import OwnerScope, TreqsContext
from ..errors import ConfigError
from ..help_text import examples
from ..models import AuthState, RepoContext
from ..output import emit_json, render_table
from .shared import load_project_api_context


@click.group("jobs")
def jobs_group() -> None:
    """Inspect jobs for the current TReqs project.

    All jobs commands are repo-bound: run them inside a git repo bound to a
    project with `treqs project use`. Jobs are created by queueing training
    requests (`treqs tr queue`).
    """


@jobs_group.command(
    "list",
    epilog=examples(
        "treqs jobs list",
        "treqs jobs list --status RUNNING --status QUEUED",
        "treqs --json jobs list --limit 50",
    ),
)
@click.option(
    "--status",
    "statuses",
    multiple=True,
    type=click.Choice(JOB_STATUSES),
    help="Filter by status. Repeat to include multiple statuses.",
)
@click.option("--limit", type=click.IntRange(1, 100), default=20, show_default=True)
@click.pass_obj
def jobs_list_command(
    state: TreqsContext,
    statuses: tuple[str, ...],
    limit: int,
) -> None:
    """List jobs for the repo-local project context."""
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        jobs = JobService(client, auth_state, repo_context).list(
            limit=limit,
            statuses=cast(tuple[JobStatus, ...], statuses),
        )

    if state.json_output:
        emit_json(jobs)
        return

    render_table(
        job_rows(jobs),
        [
            ("id", "ID"),
            ("status", "STATUS"),
            ("request", "REQUEST"),
            ("project", "PROJECT"),
            ("target", "TARGET"),
            ("created", "CREATED"),
        ],
    )


@jobs_group.command(
    "show",
    epilog=examples(
        "treqs jobs show <job-id>",
        "treqs --json jobs show <job-id>",
    ),
)
@click.argument("job_id")
@click.pass_obj
def jobs_show_command(state: TreqsContext, job_id: str) -> None:
    """Show one job from the repo-local project context.

    JOB_ID is the job ID shown by `treqs jobs list` or printed by
    `treqs tr queue`.
    """
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        job = JobService(client, auth_state, repo_context).get(job_id)

    if state.json_output:
        emit_json(job)
        return

    click.echo(f"Job: {job.id}")
    click.echo(f"Status: {job.status}")
    if job.trainingRequestId:
        click.echo(f"Request: {job.trainingRequestId}")
    if job.trainingRequest and job.trainingRequest.title:
        click.echo(f"Title: {job.trainingRequest.title}")
    if job.computeTargetId:
        click.echo(f"Compute target: {job.computeTargetId}")
    if job.projectSlug:
        click.echo(f"Project: {job.projectSlug}")
    if job.lineagePublicationMode:
        click.echo(f"Lineage mode: {job.lineagePublicationMode}")
    if job.lineagePublicationStatus:
        click.echo(f"Lineage publication: {job.lineagePublicationStatus}")
    if job.lineagePublishedSessionHash:
        click.echo(f"Session: {job.lineagePublishedSessionHash}")
    if job.lineagePublishedUrl:
        click.echo(f"Lineage URL: {job.lineagePublishedUrl}")
    if job.lineagePublicationError:
        click.echo(f"Lineage error: {job.lineagePublicationError}")
    if job.createdAt:
        click.echo(f"Created: {job.createdAt}")
    if job.updatedAt:
        click.echo(f"Updated: {job.updatedAt}")


@jobs_group.command(
    "wait",
    epilog=examples(
        "treqs jobs wait <job-id>",
        "treqs jobs wait <job-id> --timeout 3600",
    ),
)
@click.argument("job_id")
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.FloatRange(min=1.0),
    default=7200.0,
    show_default=True,
    help="Maximum seconds to wait for a terminal job state.",
)
@click.option(
    "--poll-interval",
    "poll_interval_seconds",
    type=click.FloatRange(min=0.1),
    default=5.0,
    show_default=True,
    help="Seconds between job status requests.",
)
@click.pass_obj
def jobs_wait_command(
    state: TreqsContext,
    job_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> None:
    """Wait for a job to complete, fail, or be cancelled.

    JOB_ID is the job ID shown by `treqs jobs list` or printed by
    `treqs tr queue`. Exits non-zero unless the job reaches COMPLETED.
    """
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        service = JobService(client, auth_state, repo_context)
        try:
            job = wait_for_terminal_job(
                lambda: service.get(job_id),
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        except TimeoutError as exc:
            raise ConfigError(str(exc)) from exc

    if state.json_output:
        emit_json(job)
    else:
        click.echo(f"Job: {job.id}")
        click.echo(f"Status: {job.status}")
        if job.lineagePublishedUrl:
            click.echo(f"Lineage URL: {job.lineagePublishedUrl}")

    if job.status != "COMPLETED":
        raise ConfigError(f"Job {job.id} finished with status {job.status}.")


@jobs_group.command(
    "watch",
    epilog=examples(
        "treqs jobs watch <job-id>",
        "treqs jobs watch <job-id> --timeout 3600",
        "treqs --json jobs watch <job-id>",
    ),
)
@click.argument("job_id")
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.FloatRange(min=1.0),
    default=7200.0,
    show_default=True,
    help="Maximum seconds to watch before detaching.",
)
@click.option(
    "--poll-timeout-ms",
    type=click.IntRange(1000, 30000),
    default=2000,
    show_default=True,
    help="Server-side lifecycle long-poll timeout per request.",
)
@click.pass_obj
def jobs_watch_command(
    state: TreqsContext,
    job_id: str,
    timeout_seconds: float,
    poll_timeout_ms: int,
) -> None:
    """Stream lifecycle status and workload logs until a job finishes.

    JOB_ID is the job ID shown by `treqs jobs list` or printed by
    `treqs tr queue`.

    Lifecycle updates are written to stderr. Workload logs remain on stdout.
    Ctrl-C detaches without cancelling the job.
    """
    auth_state, repo_context = load_project_api_context(state)
    renderer = JobLifecycleRenderer()

    with TreqsApiClient(auth_state.api_url) as client:
        job_service = JobService(client, auth_state, repo_context)
        initial_job = job_service.get(job_id)
        log_service = JobLogService(client, auth_state, repo_context)
        log_cursor = 0
        logs_pending = bool(initial_job.computeTargetId) and not state.json_output

        def poll_logs(timeout_ms: int = 1000) -> None:
            nonlocal log_cursor, logs_pending
            if not logs_pending or not initial_job.computeTargetId:
                return
            log_cursor, logs_pending = poll_job_logs_once(
                log_service,
                initial_job.computeTargetId,
                job_id,
                cursor=log_cursor,
                timeout_ms=timeout_ms,
            )

        try:
            updates = watch_job(
                job_service,
                job_id,
                timeout_seconds=timeout_seconds,
                poll_timeout_ms=poll_timeout_ms,
                on_update=None if state.json_output else renderer.render_update,
                on_heartbeat=None if state.json_output else renderer.render_heartbeat,
                on_poll=None if state.json_output else poll_logs,
            )
            while updates.terminal and logs_pending:
                poll_logs(30000)
        except KeyboardInterrupt:
            render_detached(job_id)
            return
        except TimeoutError as exc:
            raise ConfigError(str(exc)) from exc

    if state.json_output:
        emit_json(updates)

    if updates.snapshot.jobStatus != "COMPLETED":
        if updates.snapshot.actionRequired:
            raise ConfigError(f"Job {job_id} requires action: {updates.snapshot.actionRequired}")
        # Name the failing step when the server reports one. Without this the
        # only thing a caller learns from a failed job is its coarse status.
        task = updates.snapshot.task
        if task is not None:
            raise ConfigError(
                f"Job {job_id} finished with status {updates.snapshot.jobStatus} "
                f"at {task.describe_failure()}."
            )
        raise ConfigError(f"Job {job_id} finished with status {updates.snapshot.jobStatus}.")


@jobs_group.command(
    "republish-lineage",
    epilog=examples(
        "treqs jobs republish-lineage <job-id>",
    ),
)
@click.argument("job_id")
@click.pass_obj
def jobs_republish_lineage_command(state: TreqsContext, job_id: str) -> None:
    """Re-publish a job's stored lineage package to GLaaS.

    JOB_ID is the job ID shown by `treqs jobs list`. Recovers a lineage
    publication that failed transiently (for example a GLaaS outage) from the
    package stored at upload time — no need to re-run training.
    """
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        result = JobService(client, auth_state, repo_context).republish_lineage(job_id)

    if state.json_output:
        emit_json(result)
        return

    click.echo(f"Publication status: {result.publication_status}")
    if result.published_session_hash:
        click.echo(f"Session: {result.published_session_hash}")
    if result.published_url:
        click.echo(f"Lineage URL: {result.published_url}")


@jobs_group.command(
    "cancel",
    epilog=examples(
        "treqs jobs cancel <job-id>",
        "treqs jobs cancel <job-id> --target gpu-box",
    ),
)
@click.argument("job_id")
@click.option("--target", "target", help="Compute target ID or name. Defaults to the job's target.")
@click.pass_obj
def jobs_cancel_command(state: TreqsContext, job_id: str, target: str | None) -> None:
    """Cancel a queued or running job.

    JOB_ID is the job ID shown by `treqs jobs list` or printed by
    `treqs tr queue`. Only QUEUED/ASSIGNED/ACQUIRED/IN_PROGRESS jobs can be
    cancelled; cancelling an already-cancelled job is a no-op.
    """
    auth_state, repo_context = load_project_api_context(state)
    scope = OwnerScope(
        owner_username=repo_context.owner_username,
        current_username=repo_context.current_username,
    )
    with TreqsApiClient(auth_state.api_url) as client:
        target_id = _resolve_job_target_id(client, auth_state, repo_context, scope, job_id, target)
        job = JobService(client, auth_state, repo_context).cancel(target_id, job_id)

    if state.json_output:
        emit_json(job)
        return

    click.echo(f"Cancelled job {job.id}.")
    click.echo(f"Status: {job.status}")


@jobs_group.command(
    "tasks",
    epilog=examples(
        "treqs jobs tasks <job-id>",
        "treqs jobs tasks <job-id> --target gpu-box",
        "treqs --json jobs tasks <job-id>",
    ),
)
@click.argument("job_id")
@click.option("--target", "target", help="Compute target ID or name. Defaults to the job's target.")
@click.pass_obj
def jobs_tasks_command(
    state: TreqsContext,
    job_id: str,
    target: str | None,
) -> None:
    """Show each task of a job with its status and exit code.

    JOB_ID is the job ID shown by `treqs jobs list` or printed by
    `treqs tr queue`.

    An empty EXIT column means no exit code was recorded, which is different
    from exit 0 — most often a task that never launched.
    """
    auth_state, repo_context = load_project_api_context(state)
    scope = OwnerScope(
        owner_username=repo_context.owner_username,
        current_username=repo_context.current_username,
    )
    with TreqsApiClient(auth_state.api_url) as client:
        target_id = _resolve_job_target_id(client, auth_state, repo_context, scope, job_id, target)
        tasks = JobService(client, auth_state, repo_context).tasks(target_id, job_id)

    if state.json_output:
        emit_json(tasks)
        return

    render_table(
        task_rows(tasks),
        [
            ("name", "NAME"),
            ("status", "STATUS"),
            ("exit", "EXIT"),
            ("reason", "REASON"),
            ("error", "ERROR"),
            ("started", "STARTED"),
        ],
    )


@jobs_group.command(
    "logs",
    epilog=examples(
        "treqs jobs logs <job-id>",
        "treqs jobs logs <job-id> --follow",
        "treqs jobs logs <job-id> --target gpu-box --follow",
    ),
)
@click.argument("job_id")
@click.option("--target", "target", help="Compute target ID or name. Defaults to the job's target.")
@click.option("--follow", is_flag=True, help="Keep polling until the job's logs are complete.")
@click.option(
    "--poll-timeout-ms",
    type=click.IntRange(1000, 60000),
    default=30000,
    show_default=True,
    help="Server-side long-poll timeout per request, in milliseconds.",
)
@click.pass_obj
def jobs_logs_command(
    state: TreqsContext,
    job_id: str,
    target: str | None,
    follow: bool,
    poll_timeout_ms: int,
) -> None:
    """Print logs for a job, optionally following until complete.

    JOB_ID is the job ID shown by `treqs jobs list` or printed by
    `treqs tr queue`.
    """
    auth_state, repo_context = load_project_api_context(state)
    scope = OwnerScope(
        owner_username=repo_context.owner_username,
        current_username=repo_context.current_username,
    )
    with TreqsApiClient(auth_state.api_url) as client:
        target_id = _resolve_job_target_id(client, auth_state, repo_context, scope, job_id, target)
        follow_job_logs(
            JobLogService(client, auth_state, scope),
            target_id,
            job_id,
            follow=follow,
            poll_timeout_ms=poll_timeout_ms,
        )


def follow_job_logs(
    log_service: JobLogService,
    target_id: str,
    job_id: str,
    *,
    follow: bool,
    poll_timeout_ms: int,
) -> None:
    """Render paged job logs and optionally follow them to completion."""
    cursor = 0
    while True:
        cursor, has_more = poll_job_logs_once(
            log_service,
            target_id,
            job_id,
            cursor=cursor,
            timeout_ms=poll_timeout_ms,
        )
        if not has_more or not follow:
            break


def poll_job_logs_once(
    log_service: JobLogService,
    target_id: str,
    job_id: str,
    *,
    cursor: int,
    timeout_ms: int,
) -> tuple[int, bool]:
    """Render one workload-log poll and return its next cursor and continuation state."""
    result = log_service.poll(
        target_id,
        job_id,
        from_sequence=cursor,
        timeout_ms=timeout_ms,
    )
    for chunk in result.chunks:
        click.echo(chunk.content, nl=False)
    return result.nextSequence, result.hasMore


class JobLifecycleRenderer:
    def __init__(self) -> None:
        self._last_phase: str | None = None
        self._last_action: str | None = None

    def render_update(self, update: JobUpdates) -> None:
        rendered_messages: set[str] = set()
        for event in update.events:
            rendered_messages.add(event.message)
            _echo_lifecycle(
                _event_time(event.occurredAt),
                _event_label(event.kind),
                event.message,
            )

        snapshot = update.snapshot
        if snapshot.phase != self._last_phase and snapshot.message not in rendered_messages:
            _echo_lifecycle(_now_time(), snapshot.phase, snapshot.message)
        if snapshot.actionRequired and snapshot.actionRequired != self._last_action:
            _echo_lifecycle(_now_time(), "action required", snapshot.actionRequired)

        self._last_phase = snapshot.phase
        self._last_action = snapshot.actionRequired

    def render_heartbeat(self, snapshot: JobUpdateSnapshot) -> None:
        _echo_lifecycle(_now_time(), snapshot.phase, f"Still waiting — {snapshot.message}")


def _echo_lifecycle(timestamp: str, label: str, message: str) -> None:
    click.echo(f"{timestamp}  {label:<18} {message}", err=True)


def _event_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except ValueError:
        return _now_time()


def _now_time() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _event_label(kind: str) -> str:
    labels = {
        "job.queued": "queued",
        "compute.approval_required": "approval",
        "compute.provisioning_started": "provisioning",
        "compute.provider_accepted": "booting",
        "compute.provisioning_failed": "blocked",
        "compute.waiting_for_agent": "waiting for agent",
        "compute.agent_ready": "ready",
        "job.assigned": "assigned",
        "job.acquired": "acquired",
        "job.started": "running",
        "execution.repository_preparing": "repository",
        "execution.repository_ready": "repository",
        "execution.environment_preparing": "environment",
        "execution.environment_ready": "environment",
        "task.started": "task",
        "task.completed": "task",
        "task.failed": "task failed",
        "job.finalizing": "finalizing",
        "lineage.export_started": "lineage export",
        "lineage.export_completed": "lineage export",
        "lineage.upload_started": "lineage upload",
        "lineage.upload_completed": "lineage upload",
        "lineage.upload_failed": "lineage failed",
        "lineage.publication_started": "publishing",
        "lineage.publication_completed": "published",
        "lineage.publication_failed": "publish failed",
        "job.completed": "completed",
        "job.failed": "failed",
        "job.cancelled": "cancelled",
    }
    return labels.get(kind, kind)


def render_local_status(label: str, message: str) -> None:
    _echo_lifecycle(_now_time(), label, message)


def render_detached(job_id: str) -> None:
    click.echo(f"Detached from job {job_id}; the job is still running.", err=True)
    click.echo(f"Reattach: treqs jobs watch {job_id}", err=True)
    click.echo(f"Cancel:   treqs jobs cancel {job_id}", err=True)


def _resolve_job_target_id(
    client: TreqsApiClient,
    auth_state: AuthState,
    repo_context: RepoContext,
    scope: OwnerScope,
    job_id: str,
    target: str | None,
) -> str:
    if target is not None:
        try:
            return resolve_compute_target_id(
                ComputeTargetService(client, auth_state, scope).list(),
                target,
            )
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc

    job = JobService(client, auth_state, repo_context).get(job_id)
    if not job.computeTargetId:
        raise ConfigError(
            f"Job {job_id} has no compute target. Pass --target to poll logs explicitly."
        )
    return job.computeTargetId
