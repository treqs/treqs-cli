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
    OwnerScope,
    TreqsContext,
    build_repo_context,
    current_user_owner,
    project_scope,
    resolve_owner_selection,
    resolve_project_selection,
)
from ..errors import ConfigError
from ..git_repository import GitRepository
from ..help_text import examples
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


@projects_group.command(
    "list",
    epilog=examples(
        "treqs projects list",
        "treqs --json projects list",
    ),
)
@click.pass_obj
def projects_list_command(state: TreqsContext) -> None:
    """List projects available to the authenticated user.

    Shows projects across every owner you can access, personal and
    organization-owned. The SCOPE column is <owner>/<project> and is valid
    input for `treqs project use`.
    """
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


@projects_group.command(
    "create",
    epilog=examples(
        'treqs projects create "MNIST Digits"',
        'treqs projects create "MNIST Digits" --slug mnist --visibility public',
        'treqs projects create "Team Model" --owner acme',
        "treqs projects create Vision --code-config github:https://github.com/acme/vision",
    ),
)
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
    """Create a project for a TReqs owner.

    NAME is the human-readable project name; the project slug defaults to a
    slugified NAME unless --slug is given. Use --owner to create the project
    under an organization from `treqs orgs list`.
    """
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


@project_group.command(
    "init",
    epilog=examples(
        "treqs project init",
        "treqs project init --owner acme --visibility public",
        'treqs project init --name "MNIST" --slug mnist',
    ),
)
@click.option(
    "--from-git/--no-from-git",
    default=True,
    show_default=True,
    help="Discover the GitHub repository from the origin remote.",
)
@click.option("--name", help="Project name. Defaults to the repository name.")
@click.option("--slug", help="Project slug. Defaults to a slugified project name.")
@click.option(
    "--visibility",
    type=click.Choice(PROJECT_VISIBILITIES),
    default="private",
    show_default=True,
)
@click.option("--description", help="Project description.")
@click.option(
    "--code-access-mode",
    type=click.Choice(["public", "github_app"]),
    default="github_app",
    show_default=True,
)
@click.option("--default-branch", help="Repository default branch. Discovered when omitted.")
@owner_option
@click.option("--use/--no-use", default=True, show_default=True, help="Bind this checkout.")
@click.pass_obj
def project_init_command(
    state: TreqsContext,
    from_git: bool,
    name: str | None,
    slug: str | None,
    visibility: str,
    description: str | None,
    code_access_mode: str,
    default_branch: str | None,
    owner: str | None,
    use: bool,
) -> None:
    """Create or bind a project from the current Git repository.

    Discovers the GitHub repository from the `origin` remote and creates a
    TReqs project for it (or binds an existing one), then writes the repo-local
    project context unless --no-use is given. Use --owner to place the project
    under an organization from `treqs orgs list`.
    """
    require_git_repo(state)
    if not from_git:
        raise ConfigError("project init currently requires --from-git.")

    repository = GitRepository(state.repo_root)
    auth_state, access_context = load_access_context(state)
    selected_owner = (
        resolve_owner_selection(access_context, owner)
        if owner is not None
        else current_user_owner(access_context)
    )

    try:
        code_config = parse_code_config(
            f"github:{repository.origin_url()}",
            access_mode=cast(GitHubAccessMode, code_access_mode),
            default_branch=default_branch or repository.default_branch(),
        )
        resolved_name = name or code_config.fullName.rsplit("/", 1)[-1]
        resolved_slug = validate_slug(slug) if slug is not None else slugify_name(resolved_name)
        if not resolved_slug:
            raise ValueError("Project name does not produce a valid slug.")
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    scope = OwnerScope(
        owner_username=selected_owner.username,
        current_username=access_context.user.username,
    )
    existing = next(
        (
            project
            for project in access_context.projects_by_owner.get(selected_owner.id, [])
            if project.slug == resolved_slug
        ),
        None,
    )

    with TreqsApiClient(auth_state.api_url) as client:
        service = ProjectService(client, auth_state, scope)
        if existing is not None:
            project_detail = service.get(existing.slug)
            configured_full_name = (
                project_detail.codeConfig.get("fullName")
                if project_detail.codeConfig is not None
                else None
            )
            if configured_full_name != code_config.fullName:
                raise ConfigError(
                    f"Existing project {selected_owner.username}/{existing.slug} is not bound "
                    f"to GitHub repository {code_config.fullName}."
                )
            selected_project = existing
            created = False
        else:
            project_detail = service.create(
                ProjectCreateInput(
                    name=resolved_name,
                    slug=resolved_slug,
                    visibility=cast(ProjectVisibility, visibility),
                    description=description,
                    code_config=code_config,
                )
            )
            selected_project = AccessProject(
                id=project_detail.id,
                slug=project_detail.slug,
                name=project_detail.name,
                visibility=project_detail.visibility or visibility,
                can_write=True,
            )
            created = True

    repo_context = build_repo_context(
        auth_state=auth_state,
        access_context=access_context,
        owner=selected_owner,
        project=selected_project,
    )
    context_path = None
    if use:
        repository.exclude_treqs_context()
        context_path = state.repo_context_store.save(repo_context)

    result = {
        "created": created,
        "project": project_detail,
        "context": repo_context if use else None,
        "contextPath": str(context_path) if context_path else None,
    }
    if state.json_output:
        emit_json(result)
        return

    action = "Created" if created else "Found"
    click.echo(f"{action} TReqs project {selected_owner.username}/{selected_project.slug}.")
    if context_path:
        click.echo(f"Using this project in {state.repo_root}.")
        click.echo(f"Saved to {context_path}.")


@project_group.command(
    "use",
    epilog=examples(
        "treqs project use trevor/mnist",
        "treqs project use acme/mnist",
        "treqs project use mnist",
    ),
)
@click.argument("selection")
@click.pass_obj
def project_use_command(state: TreqsContext, selection: str) -> None:
    """Set this repo's TReqs project context.

    SELECTION is <owner>/<project> (see `treqs projects list` for valid
    scopes), or a bare project slug, name, or ID when it is unambiguous
    across your owners. The owner may be your username or an organization.
    Read-only projects are rejected. The context is saved to
    .treqs/config.toml and drives repo-bound commands (tr, jobs) plus the
    default owner scope of owner-scoped commands.
    """
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


@project_group.command(
    "status",
    epilog=examples(
        "treqs project status",
        "treqs --json project status",
    ),
)
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


@project_group.command(
    "clear",
    epilog=examples(
        "treqs project clear",
    ),
)
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
