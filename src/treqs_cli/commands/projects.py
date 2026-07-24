from __future__ import annotations

from typing import cast

import click

from ..api import TreqsApiClient
from ..application.projects.models import (
    PROJECT_VISIBILITIES,
    GitHubAccessMode,
    ProjectCreateInput,
    ProjectVisibility,
    parse_code_config,
    slugify_name,
    validate_slug,
)
from ..application.projects.service import ProjectService
from ..context import (
    TreqsContext,
    build_repo_context,
    project_scope,
    resolve_project_selection,
)
from ..errors import ConfigError
from ..models import AccessContext, AccessOwner, AccessProject
from ..output import emit_json, render_table
from .shared import (
    load_access_context,
    owner_option,
    require_git_repo,
    resolve_owner_scope,
)


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


@projects_group.command("create")
@click.argument("name")
@click.option("--slug", help="Project slug. Defaults to a slugified name.")
@click.option(
    "--visibility",
    type=click.Choice(PROJECT_VISIBILITIES),
    default="private",
    show_default=True,
    help="Project visibility.",
)
@click.option("--description", help="Project description.")
@click.option(
    "--code-config",
    help="Repository code config, for example github:https://github.com/owner/repo.",
)
@click.option(
    "--code-access-mode",
    type=click.Choice(["public", "github_app"]),
    default="public",
    show_default=True,
    help="GitHub access mode for --code-config.",
)
@click.option(
    "--default-branch",
    default="main",
    show_default=True,
    help="Default git branch for --code-config (workflow discovery + clone).",
)
@owner_option
@click.pass_obj
def projects_create_command(
    state: TreqsContext,
    name: str,
    slug: str | None,
    visibility: str,
    description: str | None,
    code_config: str | None,
    code_access_mode: str,
    default_branch: str,
    owner: str | None,
) -> None:
    """Create a project for a TReqs owner."""
    auth_state, access_context = load_access_context(state)
    scope = resolve_owner_scope(state, access_context, owner)

    try:
        resolved_slug = validate_slug(slug) if slug is not None else slugify_name(name)
        parsed_code_config = (
            parse_code_config(
                code_config,
                access_mode=cast(GitHubAccessMode, code_access_mode),
                default_branch=default_branch,
            )
            if code_config is not None
            else None
        )
        create_input = ProjectCreateInput(
            name=name,
            slug=resolved_slug,
            visibility=cast(ProjectVisibility, visibility),
            description=description,
            code_config=parsed_code_config,
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    with TreqsApiClient(auth_state.api_url) as client:
        project = ProjectService(client, auth_state, scope).create(create_input)

    if state.json_output:
        emit_json(project)
        return

    click.echo(f"Created project {project.slug}.")
    click.echo(f"ID: {project.id}")
    click.echo(f"Name: {project.name}")
    if project.visibility:
        click.echo(f"Visibility: {project.visibility}")
    click.echo(f"Owner: {scope.owner_username}")


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
