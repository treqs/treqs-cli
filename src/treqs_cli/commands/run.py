from __future__ import annotations

import click

from ..api import TreqsApiClient
from ..application.compute.models import ComputeTarget
from ..application.compute.service import ComputeTargetService, resolve_compute_target_id
from ..application.jobs.service import JobLogService, JobService, watch_job
from ..application.requests.models import TrainingRequestCreateInput, TrainingRequestOpenInput
from ..application.requests.service import TrainingRequestService
from ..context import TreqsContext
from ..errors import ApiError, ConfigError
from ..git_repository import GitRepository
from ..help_text import examples
from ..output import emit_json
from .jobs import (
    JobLifecycleRenderer,
    poll_job_logs_once,
    render_detached,
    render_local_status,
)
from .shared import load_project_api_context, require_git_repo


@click.command(
    "run",
    epilog=examples(
        'treqs run --title "Train v2" --workflow .treqs/workflows/train.yaml \\',
        "    --compute-target gpu-box",
        'treqs run --title "Smoke" --workflow .treqs/workflows/train.yaml \\',
        "    --compute-target gpu-box --lineage private --follow --yes",
    ),
)
@click.option("--title", required=True, help="Training request title.")
@click.option("--description", help="Training request description.")
@click.option("--workflow", required=True, help="Committed .treqs workflow path.")
@click.option("--target", required=True, help="Compute target ID or name.")
@click.option(
    "--source-commit",
    default="HEAD",
    show_default=True,
    help="Immutable Git revision to submit.",
)
@click.option(
    "--lineage",
    "lineage_mode",
    type=click.Choice(["private", "public", "public_anonymous"]),
    default="private",
    show_default=True,
)
@click.option("--follow", is_flag=True, help="Follow logs and wait for completion.")
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.FloatRange(min=1.0),
    default=7200.0,
    show_default=True,
    help="Maximum seconds to wait when --follow is used.",
)
@click.option("--yes", is_flag=True, help="Confirm the compute launch non-interactively.")
@click.pass_obj
def run_command(
    state: TreqsContext,
    title: str,
    description: str | None,
    workflow: str,
    target: str,
    source_commit: str,
    lineage_mode: str,
    follow: bool,
    timeout_seconds: float,
    yes: bool,
) -> None:
    """Create, open, queue, and optionally follow a training request."""
    if not state.json_output:
        render_local_status("local", "Validating Git source and workflow")
    require_git_repo(state)
    repository = GitRepository(state.repo_root)
    commit = repository.resolve_commit(source_commit)
    if not repository.is_clean():
        raise ConfigError(
            "Git worktree has uncommitted source changes. Commit or stash them first."
        )
    if not repository.commit_is_pushed(commit):
        raise ConfigError(f"Git commit {commit} is not present on an origin tracking branch.")
    if not repository.path_exists_at_commit(commit, workflow):
        raise ConfigError(f"Workflow {workflow} does not exist at commit {commit}.")
    if not state.json_output:
        render_local_status("local", f"Source commit ready: {commit[:12]}")

    auth_state, repo_context = load_project_api_context(state)
    with TreqsApiClient(auth_state.api_url) as client:
        compute_service = ComputeTargetService(client, auth_state, repo_context)
        targets = compute_service.list(include_agent=True)
        try:
            target_id = resolve_compute_target_id(targets, target)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        selected_target = next(item for item in targets if item.id == target_id)
        validate_run_compute_target(selected_target)

        if not yes:
            if not state.is_interactive:
                raise ConfigError("Non-interactive launches require --yes.")
            click.echo(f"Project: {repo_context.owner_username}/{repo_context.project_slug}")
            click.echo(f"Source commit: {commit}")
            click.echo(f"Workflow: {workflow}")
            click.echo(f"Compute target: {selected_target.name} ({target_id})")
            click.echo(f"Lineage: {lineage_mode}")
            click.confirm("Create and queue this training request?", abort=True)

        request_service = TrainingRequestService(client, auth_state, repo_context)
        if not state.json_output:
            render_local_status("request", "Creating training request")
        request = request_service.create(
            TrainingRequestCreateInput(
                title=title,
                description=description,
                status="draft",
                workflow_path=workflow,
                compute_target_id=target_id,
                source_branch=repository.current_branch(),
                source_commit=commit,
                lineage_mode=lineage_mode,
            )
        )
        if not state.json_output:
            render_local_status("workflow", "Snapshotting committed workflow")
        opened = request_service.open(
            request.id,
            TrainingRequestOpenInput(
                workflow_path=workflow,
                compute_target_id=target_id,
            ),
        )

        try:
            if not state.json_output:
                render_local_status("queue", f"Queueing on {selected_target.name}")
            queued = request_service.queue(opened.id)
        except ApiError as exc:
            if "approval" not in str(exc).lower() and "reviewer" not in str(exc).lower():
                raise
            result = {
                "status": "waiting_review",
                "trainingRequest": opened,
                "jobId": None,
                "sourceCommit": commit,
                "nextCommands": [
                    f"treqs tr review approve {opened.id}",
                    f"treqs tr queue {opened.id}",
                ],
            }
            if state.json_output:
                emit_json(result)
            else:
                click.echo(f"Opened training request {opened.id}; approval is required.")
                click.echo(f"Reviewer: treqs tr review approve {opened.id}")
                click.echo(f"Then queue: treqs tr queue {opened.id}")
            return

        if not queued.jobId:
            raise ConfigError(f"Training request {opened.id} queued without a job ID.")
        job_id = queued.jobId
        detached = False
        watch_result = None

        try:
            job_service = JobService(client, auth_state, repo_context)
            if follow:
                renderer = JobLifecycleRenderer()
                log_service = JobLogService(client, auth_state, repo_context)
                log_cursor = 0
                logs_pending = not state.json_output

                def poll_logs(timeout_ms: int = 1000) -> None:
                    nonlocal log_cursor, logs_pending
                    if not logs_pending:
                        return
                    log_cursor, logs_pending = poll_job_logs_once(
                        log_service,
                        target_id,
                        job_id,
                        cursor=log_cursor,
                        timeout_ms=timeout_ms,
                    )

                watch_result = watch_job(
                    job_service,
                    job_id,
                    timeout_seconds=timeout_seconds,
                    poll_timeout_ms=2000,
                    on_update=None if state.json_output else renderer.render_update,
                    on_heartbeat=None if state.json_output else renderer.render_heartbeat,
                    on_poll=None if state.json_output else poll_logs,
                )
                while watch_result.terminal and logs_pending:
                    poll_logs(30000)
            job = job_service.get(job_id)
        except KeyboardInterrupt:
            detached = True
            render_detached(job_id)
            job = JobService(client, auth_state, repo_context).get(job_id)
        except TimeoutError as exc:
            raise ConfigError(str(exc)) from exc

    if job.status == "COMPLETED":
        run_status = "completed"
    elif job.status in {"FAILED", "CANCELLED"}:
        run_status = "failed"
    else:
        run_status = "queued"

    result = {
        "status": run_status,
        "trainingRequest": queued.trainingRequest,
        "job": job,
        "sourceCommit": commit,
        "workflowSnapshotId": opened.workflowSnapshotId,
        "lineageUrl": job.lineagePublishedUrl,
    }
    if state.json_output:
        emit_json(result)
    else:
        click.echo(f"Training request: {queued.trainingRequest.id}")
        click.echo(f"Job: {job.id}")
        click.echo(f"Status: {job.status}")
        click.echo(f"Source commit: {commit}")
        if opened.workflowSnapshotId:
            click.echo(f"Workflow snapshot: {opened.workflowSnapshotId}")
        if job.lineagePublishedUrl:
            click.echo(f"Lineage URL: {job.lineagePublishedUrl}")

    if follow and not detached and job.status != "COMPLETED":
        if watch_result is not None and watch_result.snapshot.actionRequired:
            raise ConfigError(
                f"Job {job.id} requires action: {watch_result.snapshot.actionRequired}"
            )
        raise ConfigError(f"Job {job.id} finished with status {job.status}.")


def validate_run_compute_target(target: ComputeTarget) -> None:
    """Allow dormant on-demand targets while retaining manual-start safeguards."""
    if target.agent is not None:
        return
    if target.kind != "on-demand":
        raise ConfigError(f"Compute target {target.name} has no registered agent.")
    if target.startupBehavior == "only-if-running":
        raise ConfigError(
            f"Compute target {target.name} must be started before queueing "
            "because its startup behavior is only-if-running."
        )
