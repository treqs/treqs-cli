from __future__ import annotations

import click

from ..api import TreqsApiClient
from ..auth import open_browser, resolve_api_url
from ..context import TreqsContext
from ..errors import ApiError
from ..output import emit_json
from .shared import auth_state_for_request, load_access_context


@click.command("login")
@click.option("--force", is_flag=True, help="Replace an existing login without prompting.")
@click.option("--no-browser", is_flag=True, help="Do not try to open a browser automatically.")
@click.pass_obj
def login_command(state: TreqsContext, force: bool, no_browser: bool) -> None:
    """Authenticate with TReqs using browser/device login."""
    api_url = resolve_api_url(state.api_url_override)
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


@click.command("logout")
@click.pass_obj
def logout_command(state: TreqsContext) -> None:
    """Clear local TReqs auth state and revoke the session when possible."""
    auth_state = state.auth_store.load()
    if auth_state is not None:
        try:
            auth_state_for_logout = auth_state_for_request(state, auth_state)
            with TreqsApiClient(auth_state_for_logout.api_url) as client:
                client.logout(auth_state_for_logout)
        except ApiError:
            pass
    removed = state.auth_store.delete()
    if state.json_output:
        emit_json({"removed": removed})
    else:
        click.echo("Logged out." if removed else "No stored login found.")


@click.command("whoami")
@click.pass_obj
def whoami_command(state: TreqsContext) -> None:
    """Show the authenticated TReqs user and owner access summary."""
    auth_state, access_context = load_access_context(state)
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
