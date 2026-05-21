from __future__ import annotations

from typing import cast

import click

from ..api import TreqsApiClient
from ..application.compute.service import ComputeTargetService, resolve_compute_target_id
from ..application.requests.models import (
    TRAINING_REQUEST_STATUSES,
    TrainingRequestCreateInput,
    TrainingRequestListFilters,
    TrainingRequestOpenInput,
    TrainingRequestStatus,
    TrainingRequestUpdateInput,
    training_request_rows,
)
from ..application.requests.service import TrainingRequestService
from ..context import TreqsContext
from ..errors import ConfigError
from ..models import AuthState, RepoContext
from ..output import emit_json, render_table
from .shared import load_project_api_context


@click.group("tr")
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
@click.option("--workflow-snapshot-id", help="Workflow snapshot ID for queue-time launch.")
@click.option("--compute-target", help="Compute target ID or name for this request.")
@click.pass_obj
def requests_create_command(
    state: TreqsContext,
    title: str,
    description: str | None,
    status: str,
    workflow_path: str | None,
    workflow_snapshot_id: str | None,
    compute_target: str | None,
) -> None:
    """Create a training request in the repo-local project context."""
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        compute_target_id = _resolve_compute_target(
            client, auth_state, repo_context, compute_target
        )
        request = TrainingRequestService(client, auth_state, repo_context).create(
            TrainingRequestCreateInput(
                title=title,
                description=description,
                status=cast(TrainingRequestStatus, status),
                workflow_path=workflow_path,
                compute_target_id=compute_target_id,
                workflow_snapshot_id=workflow_snapshot_id,
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
    compute_target_id = _compute_target_id(request.computeSelection)
    if compute_target_id:
        click.echo(f"Compute target: {compute_target_id}")
    if request.workflowSnapshotId:
        click.echo(f"Workflow snapshot: {request.workflowSnapshotId}")
    if request.createdAt:
        click.echo(f"Created: {request.createdAt}")
    if request.updatedAt:
        click.echo(f"Updated: {request.updatedAt}")
    if request.description:
        click.echo("")
        click.echo(request.description)


@requests_group.command("update")
@click.argument("request_id")
@click.option("--title", help="Training request title.")
@click.option("--description", help="Training request description.")
@click.option(
    "--status",
    type=click.Choice(TRAINING_REQUEST_STATUSES),
    help="Training request status.",
)
@click.option("--workflow-path", help="Workflow path, for example .github/workflows/train.yml.")
@click.option("--workflow-snapshot-id", help="Workflow snapshot ID for queue-time launch.")
@click.option("--compute-target", help="Compute target ID or name for this request.")
@click.option("--clear-description", is_flag=True, help="Clear the request description.")
@click.option("--clear-workflow-path", is_flag=True, help="Clear the workflow path.")
@click.option("--clear-compute-target", is_flag=True, help="Clear the compute target selection.")
@click.option(
    "--clear-workflow-snapshot", is_flag=True, help="Clear the workflow snapshot selection."
)
@click.pass_obj
def requests_update_command(
    state: TreqsContext,
    request_id: str,
    title: str | None,
    description: str | None,
    status: str | None,
    workflow_path: str | None,
    workflow_snapshot_id: str | None,
    compute_target: str | None,
    clear_description: bool,
    clear_workflow_path: bool,
    clear_compute_target: bool,
    clear_workflow_snapshot: bool,
) -> None:
    """Update a training request in the repo-local project context."""
    auth_state, repo_context = load_project_api_context(state)
    _validate_update_clear_options(
        description=description,
        workflow_path=workflow_path,
        compute_target=compute_target,
        workflow_snapshot_id=workflow_snapshot_id,
        clear_description=clear_description,
        clear_workflow_path=clear_workflow_path,
        clear_compute_target=clear_compute_target,
        clear_workflow_snapshot=clear_workflow_snapshot,
    )
    if all(
        value is None
        for value in (
            title,
            description,
            status,
            workflow_path,
            workflow_snapshot_id,
            compute_target,
        )
    ) and not any(
        (
            clear_description,
            clear_workflow_path,
            clear_compute_target,
            clear_workflow_snapshot,
        )
    ):
        raise ConfigError("Nothing to update. Provide at least one update option.")

    with TreqsApiClient(auth_state.api_url) as client:
        compute_target_id = _resolve_compute_target(
            client, auth_state, repo_context, compute_target
        )
        request = TrainingRequestService(client, auth_state, repo_context).update(
            request_id,
            TrainingRequestUpdateInput(
                title=title,
                description=description,
                status=cast(TrainingRequestStatus, status) if status is not None else None,
                workflow_path=workflow_path,
                compute_target_id=compute_target_id,
                workflow_snapshot_id=workflow_snapshot_id,
                clear_description=clear_description,
                clear_workflow_path=clear_workflow_path,
                clear_compute_target=clear_compute_target,
                clear_workflow_snapshot=clear_workflow_snapshot,
            ),
        )

    if state.json_output:
        emit_json(request)
        return

    click.echo(f"Updated training request {request.id}.")
    click.echo(f"Title: {request.title}")
    click.echo(f"Status: {request.status}")
    if request.workflowPath:
        click.echo(f"Workflow: {request.workflowPath}")
    compute_target_id = _compute_target_id(request.computeSelection)
    if compute_target_id:
        click.echo(f"Compute target: {compute_target_id}")
    if request.workflowSnapshotId:
        click.echo(f"Workflow snapshot: {request.workflowSnapshotId}")


@requests_group.command("open")
@click.argument("request_id")
@click.option("--workflow-path", help="Workflow path, for example .github/workflows/train.yml.")
@click.option("--compute-target", required=True, help="Compute target ID or name.")
@click.pass_obj
def requests_open_command(
    state: TreqsContext,
    request_id: str,
    workflow_path: str | None,
    compute_target: str,
) -> None:
    """Open a draft training request for review."""
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        compute_target_id = _resolve_compute_target(
            client, auth_state, repo_context, compute_target
        )
        if compute_target_id is None:
            raise ConfigError("Compute target is required to open a training request.")
        request = TrainingRequestService(client, auth_state, repo_context).open(
            request_id,
            TrainingRequestOpenInput(
                workflow_path=workflow_path,
                compute_target_id=compute_target_id,
            ),
        )

    if state.json_output:
        emit_json(request)
        return

    click.echo(f"Opened training request {request.id}.")
    click.echo(f"Status: {request.status}")
    if request.workflowPath:
        click.echo(f"Workflow: {request.workflowPath}")
    compute_target_id = _compute_target_id(request.computeSelection)
    if compute_target_id:
        click.echo(f"Compute target: {compute_target_id}")


@requests_group.command("queue")
@click.argument("request_id")
@click.pass_obj
def requests_queue_command(state: TreqsContext, request_id: str) -> None:
    """Queue an open training request as a job."""
    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        result = TrainingRequestService(client, auth_state, repo_context).queue(request_id)

    if state.json_output:
        emit_json(result)
        return

    click.echo(f"Queued training request {result.trainingRequest.id}.")
    if result.jobId:
        click.echo(f"Job: {result.jobId}")
    if result.warningMessage:
        click.echo(f"Warning: {result.warningMessage}")


def _resolve_compute_target(
    client: TreqsApiClient,
    auth_state: AuthState,
    repo_context: RepoContext,
    selection: str | None,
) -> str | None:
    if selection is None:
        return None

    try:
        return resolve_compute_target_id(
            ComputeTargetService(client, auth_state, repo_context).list(),
            selection,
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _validate_update_clear_options(
    *,
    description: str | None,
    workflow_path: str | None,
    compute_target: str | None,
    workflow_snapshot_id: str | None,
    clear_description: bool,
    clear_workflow_path: bool,
    clear_compute_target: bool,
    clear_workflow_snapshot: bool,
) -> None:
    conflicts = [
        (clear_description and description is not None, "--description", "--clear-description"),
        (
            clear_workflow_path and workflow_path is not None,
            "--workflow-path",
            "--clear-workflow-path",
        ),
        (
            clear_compute_target and compute_target is not None,
            "--compute-target",
            "--clear-compute-target",
        ),
        (
            clear_workflow_snapshot and workflow_snapshot_id is not None,
            "--workflow-snapshot-id",
            "--clear-workflow-snapshot",
        ),
    ]
    for has_conflict, set_option, clear_option in conflicts:
        if has_conflict:
            raise ConfigError(f"Cannot use {set_option} with {clear_option}.")


def _compute_target_id(compute_selection: dict[str, object] | None) -> str | None:
    if not compute_selection:
        return None
    target_id = compute_selection.get("targetId")
    return target_id if isinstance(target_id, str) else None
