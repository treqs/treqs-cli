from __future__ import annotations

from typing import cast

import click

from ..api import TreqsApiClient
from ..application.jobs.models import JOB_STATUSES, JobStatus, job_rows
from ..application.jobs.service import JobService
from ..context import TreqsContext
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
