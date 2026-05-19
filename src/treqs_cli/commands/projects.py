from __future__ import annotations

import click

from ..context import TreqsContext, build_repo_context, project_scope, resolve_project_selection
from ..models import AccessContext, AccessOwner, AccessProject
from ..output import emit_json, render_table
from .shared import load_access_context, require_git_repo


@click.group("projects")
def projects_group() -> None:
    """List accessible TReqs projects."""


@projects_group.command("list")
@click.pass_obj
def projects_list_command(state: TreqsContext) -> None:
    """List projects available to the authenticated user."""
    _auth_state, access_context = load_access_context(state)
    rows = _project_rows(access_context)
    if state.json_output:
        emit_json(rows)
        return
    render_table(
        rows,
        [
            ("scope", "SCOPE"),
            ("name", "NAME"),
            ("visibility", "VISIBILITY"),
            ("write", "WRITE"),
        ],
    )


@click.group("project")
def project_group() -> None:
    """Manage repo-local TReqs project context."""


@project_group.command("use")
@click.argument("selection")
@click.pass_obj
def project_use_command(state: TreqsContext, selection: str) -> None:
    """Set this repo's TReqs project context."""
    require_git_repo(state)
    auth_state, access_context = load_access_context(state)
    owner, project = resolve_project_selection(access_context, selection)
    repo_context = build_repo_context(
        auth_state=auth_state,
        access_context=access_context,
        owner=owner,
        project=project,
    )
    path = state.repo_context_store.save(repo_context)

    if state.json_output:
        emit_json({"context": repo_context, "path": str(path)})
        return

    click.echo(f"Using TReqs project {project_scope(owner, project)}.")
    click.echo(f"Saved to {path}.")


@project_group.command("status")
@click.pass_obj
def project_status_command(state: TreqsContext) -> None:
    """Show the repo-local TReqs project context."""
    require_git_repo(state)
    context = state.repo_context_store.require()
    if state.json_output:
        emit_json(context)
        return
    click.echo(f"Project: {context.owner_username}/{context.project_slug}")
    click.echo(f"Name: {context.project_name}")
    click.echo(f"Owner: {context.owner_display_name or context.owner_username}")
    click.echo(f"API: {context.api_url}")


@project_group.command("clear")
@click.pass_obj
def project_clear_command(state: TreqsContext) -> None:
    """Clear the repo-local TReqs project context."""
    require_git_repo(state)
    removed = state.repo_context_store.clear()
    if state.json_output:
        emit_json({"removed": removed})
    else:
        click.echo("Cleared TReqs project context." if removed else "No project context found.")


def _project_rows(access_context: AccessContext) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    owners_by_id = access_context.owner_by_id()
    for owner_id, projects in access_context.projects_by_owner.items():
        owner = owners_by_id.get(owner_id)
        if owner is None:
            continue
        for project in projects:
            rows.append(_project_row(owner, project))
    rows.sort(key=lambda row: row["scope"])
    return rows


def _project_row(owner: AccessOwner, project: AccessProject) -> dict[str, str]:
    return {
        "scope": project_scope(owner, project),
        "name": project.name,
        "visibility": project.visibility,
        "write": "yes" if project.can_write else "no",
    }
