from __future__ import annotations

from typing import cast

import click

from ..api import TreqsApiClient
from ..application.compute.service import (
    ComputeTargetScope,
    ComputeTargetService,
    resolve_compute_target_id,
)
from ..application.jobs.models import JOB_STATUSES, JobStatus, job_rows
from ..application.jobs.service import JobLogService, JobService
from ..context import TreqsContext
from ..errors import ConfigError
from ..models import AuthState, RepoContext
from ..output import emit_json, render_table
from .shared import load_project_api_context


@click.group("jobs")
def jobs_group() -> None:
    """Inspect jobs for the current TReqs project."""


@jobs_group.command("list")
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


@jobs_group.command("show")
@click.argument("job_id")
@click.pass_obj
def jobs_show_command(state: TreqsContext, job_id: str) -> None:
    """Show one job from the repo-local project context."""
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
    if job.createdAt:
        click.echo(f"Created: {job.createdAt}")
    if job.updatedAt:
        click.echo(f"Updated: {job.updatedAt}")


@jobs_group.command("logs")
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
    """Print logs for a job, optionally following until complete."""
    auth_state, repo_context = load_project_api_context(state)
    scope = ComputeTargetScope(
        owner_username=repo_context.owner_username,
        current_username=repo_context.current_username,
    )
    with TreqsApiClient(auth_state.api_url) as client:
        target_id = _resolve_log_target_id(
            client, auth_state, repo_context, scope, job_id, target
        )
        log_service = JobLogService(client, auth_state, scope)
        cursor = 0
        while True:
            result = log_service.poll(
                target_id,
                job_id,
                from_sequence=cursor,
                timeout_ms=poll_timeout_ms,
            )
            for chunk in result.chunks:
                click.echo(chunk.content, nl=False)
            cursor = result.nextSequence
            if not result.hasMore:
                break
            if not follow:
                break


def _resolve_log_target_id(
    client: TreqsApiClient,
    auth_state: AuthState,
    repo_context: RepoContext,
    scope: ComputeTargetScope,
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
