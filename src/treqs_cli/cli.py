from __future__ import annotations

from dataclasses import dataclass

import click

from . import __version__
from .api import TreqsApiClient, ensure_fresh_auth
from .auth import open_browser, resolve_api_url
from .config import AuthStore, RepoContextStore
from .context import build_repo_context, project_scope, resolve_project_selection
from .errors import ApiError, TreqsCliError
from .models import AccessContext, AccessOwner, AccessProject, AuthState
from .output import emit_json, render_table


@dataclass
class CliState:
    api_url: str | None
    json_output: bool
    auth_store: AuthStore


@click.group()
@click.version_option(version=__version__, prog_name="treqs")
@click.option("--api-url", envvar="TREQS_API_URL", help="TReqs API base URL.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_context
def cli(ctx: click.Context, api_url: str | None, json_output: bool) -> None:
    """TReqs command-line control plane."""
    ctx.obj = CliState(api_url=api_url, json_output=json_output, auth_store=AuthStore())


@cli.command("login")
@click.option("--force", is_flag=True, help="Replace an existing login without prompting.")
@click.option("--no-browser", is_flag=True, help="Do not try to open a browser automatically.")
@click.pass_obj
def login_command(state: CliState, force: bool, no_browser: bool) -> None:
    """Authenticate with TReqs using browser/device login."""
    api_url = resolve_api_url(state.api_url)
    existing = state.auth_store.load()
    if existing is not None and not force:
        identity = existing.user.username if existing.user else "existing session"
        click.echo(f"Already logged in as {identity}.")
        if not click.confirm("Replace existing session?", default=False):
            raise click.ClickException("Login cancelled; existing session preserved.")

    with TreqsApiClient(api_url) as client:
        session = client.start_device_authorization()
        verification_url = session.verification_uri_complete or session.verification_uri
        click.echo("Starting TReqs device login.")
        click.echo(f"Open this URL: {verification_url}")
        click.echo(f"Enter this code: {session.user_code}")
        if open_browser(verification_url, disabled=no_browser):
            click.echo("Opened browser for approval.")
        else:
            click.echo("Waiting for browser approval.")
        auth_state = client.poll_device_token(session)

    path = state.auth_store.save(auth_state)
    if state.json_output:
        emit_json({"auth": auth_state, "path": str(path)})
        return

    identity = auth_state.user.username if auth_state.user else "authenticated user"
    click.echo(f"Logged in as {identity}.")
    click.echo(f"Saved auth state to {path}.")


@cli.command("logout")
@click.pass_obj
def logout_command(state: CliState) -> None:
    """Clear local TReqs auth state and revoke the session when possible."""
    auth_state = state.auth_store.load()
    if auth_state is not None:
        try:
            with TreqsApiClient(auth_state.api_url) as client:
                client.logout(auth_state)
        except ApiError:
            pass
    removed = state.auth_store.delete()
    if state.json_output:
        emit_json({"removed": removed})
    else:
        click.echo("Logged out." if removed else "No stored login found.")


@cli.command("whoami")
@click.pass_obj
def whoami_command(state: CliState) -> None:
    """Show the authenticated TReqs user and owner access summary."""
    auth_state, access_context = _load_access_context(state)
    if state.json_output:
        emit_json({"auth": auth_state, "access_context": access_context})
        return

    user = access_context.user
    project_count = sum(len(projects) for projects in access_context.projects_by_owner.values())
    click.echo(f"{user.username} <{user.email}>")
    click.echo(f"User ID: {user.id}")
    click.echo(f"API: {auth_state.api_url}")
    click.echo(f"Owners: {len(access_context.owners)}")
    click.echo(f"Projects: {project_count}")


@cli.group("projects")
def projects_group() -> None:
    """List accessible TReqs projects."""


@projects_group.command("list")
@click.pass_obj
def projects_list_command(state: CliState) -> None:
    """List projects available to the authenticated user."""
    _auth_state, access_context = _load_access_context(state)
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


@cli.group("project")
def project_group() -> None:
    """Manage repo-local TReqs project context."""


@project_group.command("use")
@click.argument("selection")
@click.pass_obj
def project_use_command(state: CliState, selection: str) -> None:
    """Set this repo's TReqs project context."""
    auth_state, access_context = _load_access_context(state)
    owner, project = resolve_project_selection(access_context, selection)
    repo_context = build_repo_context(
        auth_state=auth_state,
        access_context=access_context,
        owner=owner,
        project=project,
    )
    path = RepoContextStore().save(repo_context)

    if state.json_output:
        emit_json({"context": repo_context, "path": str(path)})
        return

    click.echo(f"Using TReqs project {project_scope(owner, project)}.")
    click.echo(f"Saved to {path}.")


@project_group.command("status")
@click.pass_obj
def project_status_command(state: CliState) -> None:
    """Show the repo-local TReqs project context."""
    context = RepoContextStore().require()
    if state.json_output:
        emit_json(context)
        return
    click.echo(f"Project: {context.owner_username}/{context.project_slug}")
    click.echo(f"Name: {context.project_name}")
    click.echo(f"Owner: {context.owner_display_name or context.owner_username}")
    click.echo(f"API: {context.api_url}")


@project_group.command("clear")
@click.pass_obj
def project_clear_command(state: CliState) -> None:
    """Clear the repo-local TReqs project context."""
    removed = RepoContextStore().clear()
    if state.json_output:
        emit_json({"removed": removed})
    else:
        click.echo("Cleared TReqs project context." if removed else "No project context found.")


def main() -> None:
    try:
        cli()
    except TreqsCliError as exc:
        raise click.ClickException(str(exc)) from exc


def _load_access_context(state: CliState) -> tuple[AuthState, AccessContext]:
    auth_state = ensure_fresh_auth(state.auth_store, state.auth_store.require())
    with TreqsApiClient(auth_state.api_url) as client:
        access_context = client.get_access_context(auth_state)
    return auth_state, access_context


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
