from __future__ import annotations

from typing import cast

import click

from ..api import TreqsApiClient
from ..application.requests.models import (
    TRAINING_REQUEST_STATUSES,
    TrainingRequestCreateInput,
    TrainingRequestListFilters,
    TrainingRequestStatus,
    training_request_rows,
)
from ..application.requests.service import TrainingRequestService
from ..context import TreqsContext
from ..output import emit_json, render_table
from .shared import load_project_api_context


@click.group("requests")
def requests_group() -> None:
    """Manage training requests for the current TReqs project."""


@requests_group.command("list")
@click.option(
    "--status",
    "statuses",
    multiple=True,
    type=click.Choice(TRAINING_REQUEST_STATUSES),
    help="Filter by status. Repeat to include multiple statuses.",
)
@click.option("--limit", type=click.IntRange(1, 100), default=20, show_default=True)
@click.option("--offset", type=click.IntRange(0), default=0, show_default=True)
@click.pass_obj
def requests_list_command(
    state: TreqsContext,
    statuses: tuple[str, ...],
    limit: int,
    offset: int,
) -> None:
    """List training requests for the repo-local project context."""
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        requests = TrainingRequestService(client, auth_state, repo_context).list(
            TrainingRequestListFilters(
                statuses=cast(tuple[TrainingRequestStatus, ...], statuses),
                limit=limit,
                offset=offset,
            )
        )

    if state.json_output:
        emit_json(requests)
        return

    render_table(
        training_request_rows(requests),
        [
            ("id", "ID"),
            ("status", "STATUS"),
            ("title", "TITLE"),
            ("created", "CREATED"),
        ],
    )


@requests_group.command("create")
@click.option("--title", required=True, help="Training request title.")
@click.option("--description", help="Training request description.")
@click.option(
    "--status",
    type=click.Choice(TRAINING_REQUEST_STATUSES),
    default="draft",
    show_default=True,
    help="Initial training request status.",
)
@click.option("--workflow-path", help="Workflow path, for example .github/workflows/train.yml.")
@click.pass_obj
def requests_create_command(
    state: TreqsContext,
    title: str,
    description: str | None,
    status: str,
    workflow_path: str | None,
) -> None:
    """Create a training request in the repo-local project context."""
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        request = TrainingRequestService(client, auth_state, repo_context).create(
            TrainingRequestCreateInput(
                title=title,
                description=description,
                status=cast(TrainingRequestStatus, status),
                workflow_path=workflow_path,
            )
        )

    if state.json_output:
        emit_json(request)
        return

    click.echo(f"Created training request {request.id}.")
    click.echo(f"Title: {request.title}")
    click.echo(f"Status: {request.status}")
    click.echo(f"Project: {repo_context.owner_username}/{repo_context.project_slug}")


@requests_group.command("show")
@click.argument("request_id")
@click.pass_obj
def requests_show_command(state: TreqsContext, request_id: str) -> None:
    """Show one training request from the repo-local project context."""
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        request = TrainingRequestService(client, auth_state, repo_context).get(request_id)

    if state.json_output:
        emit_json(request)
        return

    click.echo(request.title or "(untitled)")
    click.echo(f"ID: {request.id}")
    click.echo(f"Status: {request.status}")
    click.echo(f"Project: {repo_context.owner_username}/{repo_context.project_slug}")
    if request.workflowPath:
        click.echo(f"Workflow: {request.workflowPath}")
    if request.createdAt:
        click.echo(f"Created: {request.createdAt}")
    if request.updatedAt:
        click.echo(f"Updated: {request.updatedAt}")
    if request.description:
        click.echo("")
        click.echo(request.description)
