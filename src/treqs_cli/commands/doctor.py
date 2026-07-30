from __future__ import annotations

import click

from ..api import TreqsApiClient
from ..application.compute.service import ComputeTargetService, resolve_compute_target_id
from ..application.projects.models import parse_code_config
from ..application.projects.service import ProjectService
from ..context import TreqsContext
from ..errors import ConfigError
from ..git_repository import GitRepository
from ..help_text import examples
from ..output import emit_json, render_table
from .shared import load_project_api_context, require_git_repo


@click.command(
    "doctor",
    epilog=examples(
        "treqs doctor --target gpu-box",
        "treqs doctor --target gpu-box --workflow .treqs/workflows/train.yaml \\",
        "    --source-commit <sha>",
    ),
)
@click.option("--target", required=True, help="Compute target ID or name to validate.")
@click.option("--workflow", help="Workflow path to validate at the selected commit.")
@click.option(
    "--source-commit",
    default="HEAD",
    show_default=True,
    help="Git revision that will be submitted.",
)
@click.pass_obj
def doctor_command(
    state: TreqsContext,
    target: str,
    workflow: str | None,
    source_commit: str,
) -> None:
    """Validate laptop, project, source, and compute readiness."""
    require_git_repo(state)
    auth_state, repo_context = load_project_api_context(state)
    repository = GitRepository(state.repo_root)
    checks: list[dict[str, str]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "check": name,
                "status": "pass" if passed else "fail",
                "detail": detail,
            }
        )

    check("authentication", True, f"authenticated against {auth_state.api_url}")
    check(
        "project-context",
        True,
        f"{repo_context.owner_username}/{repo_context.project_slug}",
    )

    commit = repository.resolve_commit(source_commit)
    clean = repository.is_clean()
    check("clean-worktree", clean, "clean" if clean else "commit or stash source changes")
    pushed = repository.commit_is_pushed(commit)
    check("pushed-commit", pushed, commit if pushed else f"{commit} is not on origin")

    if workflow:
        workflow_exists = repository.path_exists_at_commit(commit, workflow)
        check(
            "workflow",
            workflow_exists,
            f"{workflow} at {commit}" if workflow_exists else f"{workflow} is absent at {commit}",
        )

    with TreqsApiClient(auth_state.api_url) as client:
        project = ProjectService(client, auth_state, repo_context).get(repo_context.project_slug)
        try:
            local_code = parse_code_config(f"github:{repository.origin_url()}")
            configured_full_name = (
                project.codeConfig.get("fullName") if project.codeConfig is not None else None
            )
            repository_matches = configured_full_name == local_code.fullName
            repository_detail = (
                local_code.fullName
                if repository_matches
                else f"project={configured_full_name or 'unconfigured'} local={local_code.fullName}"
            )
        except ValueError as exc:
            repository_matches = False
            repository_detail = str(exc)
        check("repository-binding", repository_matches, repository_detail)

        targets = ComputeTargetService(client, auth_state, repo_context).list(include_agent=True)
        try:
            target_id = resolve_compute_target_id(targets, target)
            selected_target = next(item for item in targets if item.id == target_id)
        except (ValueError, StopIteration) as exc:
            check("compute-target", False, str(exc) or f"target not found: {target}")
        else:
            check(
                "compute-target",
                True,
                f"{selected_target.name} ({selected_target.id})",
            )
            agent_ready = selected_target.agent is not None
            check(
                "compute-agent",
                agent_ready,
                "registered" if agent_ready else "no registered agent",
            )

    failed = [item for item in checks if item["status"] == "fail"]
    result = {"ready": not failed, "commit": commit, "checks": checks}
    if state.json_output:
        emit_json(result)
    else:
        render_table(checks, [("status", "STATUS"), ("check", "CHECK"), ("detail", "DETAIL")])

    if failed:
        names = ", ".join(item["check"] for item in failed)
        raise ConfigError(f"Preflight failed: {names}.")
