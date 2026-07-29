from __future__ import annotations

import sys

import click

from ..api import TreqsApiClient
from ..auth import (
    TREQS_API_TOKEN_ENV,
    env_api_token,
    open_browser,
    resolve_api_url,
    token_auth_state,
)
from ..context import TreqsContext
from ..errors import ApiError, AuthError
from ..help_text import examples
from ..models import AuthState
from ..output import emit_json
from .shared import auth_state_for_request, load_access_context


@click.command(
    "login",
    epilog=examples(
        "treqs login",
        "treqs login --no-browser",
        "treqs login --token treqs_pat_XXXXXXXX",
        "echo $TOKEN | treqs login --token -",
        "treqs --api-url http://localhost:3001 login",
    ),
)
@click.option("--force", is_flag=True, help="Replace an existing login without prompting.")
@click.option("--no-browser", is_flag=True, help="Do not try to open a browser automatically.")
@click.option(
    "--token",
    help=(
        "Log in with a TReqs API token from the dashboard instead of the browser "
        "flow. Pass '-' to read the token from stdin."
    ),
)
@click.pass_obj
def login_command(state: TreqsContext, force: bool, no_browser: bool, token: str | None) -> None:
    """Authenticate with TReqs using browser/device login or an API token.

    Starts a device authorization flow: approve the printed URL and code in
    your browser and the CLI stores the session in the platform config
    directory (override with TREQS_CONFIG_HOME). With --token, the browser
    flow is skipped and a dashboard-issued API token is validated and stored
    instead. To use a token without storing it, set TREQS_API_TOKEN; it takes
    precedence over any stored login for API requests.
    """
    api_url = resolve_api_url(state.api_url_override)
    existing = state.auth_store.load()
    if existing is not None and not force:
        identity = existing.user.username if existing.user else "existing session"
        click.echo(f"Already logged in as {identity}.")
        if not click.confirm("Replace existing session?", default=False):
            raise click.ClickException("Login cancelled; existing session preserved.")

    if token is not None:
        auth_state = _validate_api_token(api_url, _read_token_value(token))
    else:
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


def _read_token_value(token: str) -> str:
    value = sys.stdin.readline() if token == "-" else token
    value = value.strip()
    if not value:
        raise click.UsageError("API token is empty. Pass --token <token> or pipe it to --token -.")
    return value


def _validate_api_token(api_url: str, token: str) -> AuthState:
    auth_state = token_auth_state(api_url, token)
    with TreqsApiClient(api_url) as client:
        try:
            access_context = client.get_access_context(auth_state)
        except ApiError as exc:
            if exc.status_code == 401:
                raise AuthError("Invalid or revoked API token.") from exc
            raise
    return auth_state.model_copy(update={"user": access_context.user})


@click.command(
    "logout",
    epilog=examples(
        "treqs logout",
    ),
)
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
    if env_api_token() is not None:
        click.echo(
            f"Note: {TREQS_API_TOKEN_ENV} is set in the environment and remains "
            "active until unset.",
            err=True,
        )
    if state.json_output:
        emit_json({"removed": removed})
    else:
        click.echo("Logged out." if removed else "No stored login found.")


@click.command(
    "whoami",
    epilog=examples(
        "treqs whoami",
        "treqs --json whoami",
    ),
)
@click.pass_obj
def whoami_command(state: TreqsContext) -> None:
    """Show the authenticated TReqs user and owner access summary.

    Lists every owner you can act as (yourself plus organizations) with your
    role and project count per owner.
    """
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
    for owner in access_context.owners:
        owner_projects = len(access_context.projects_by_owner.get(owner.id, []))
        click.echo(f"  - {owner.username} ({owner.type}, {owner.role}, projects={owner_projects})")
    click.echo(f"Projects: {project_count}")
