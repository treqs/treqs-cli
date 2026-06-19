from __future__ import annotations

import click

from ..api import TreqsApiClient
from ..application.compute.models import (
    ComputeTargetCreateInput,
    compute_target_rows,
    parse_secret_assignment,
)
from ..application.compute.service import (
    ComputeTargetScope,
    ComputeTargetService,
    resolve_compute_target_id,
)
from ..context import TreqsContext, current_user_owner, resolve_owner_selection
from ..errors import ConfigError, TreqsCliError
from ..models import AccessContext
from ..output import emit_json, render_table
from .shared import load_access_context


@click.group("compute")
def compute_group() -> None:
    """Inspect compute resources for the current TReqs owner."""


@compute_group.group("targets")
def compute_targets_group() -> None:
    """Inspect compute targets for the current TReqs owner."""


@compute_targets_group.command("list")
@click.option("--include-agent", is_flag=True, help="Include registered agent details.")
@click.option("--owner", help="Owner username or organization to inspect.")
@click.pass_obj
def compute_targets_list_command(
    state: TreqsContext,
    include_agent: bool,
    owner: str | None,
) -> None:
    """List compute targets for a TReqs owner."""
    auth_state, access_context = load_access_context(state)
    scope = _resolve_compute_scope(state, access_context, owner)
    with TreqsApiClient(auth_state.api_url) as client:
        targets = ComputeTargetService(client, auth_state, scope).list(include_agent=include_agent)

    if state.json_output:
        emit_json(targets)
        return

    render_table(
        compute_target_rows(targets),
        [
            ("id", "ID"),
            ("name", "NAME"),
            ("kind", "KIND"),
            ("type", "TYPE"),
            ("status", "STATUS"),
            ("agent", "AGENT"),
        ],
    )


@compute_targets_group.command("create")
@click.option(
    "--kind",
    type=click.Choice(["dedicated"]),
    default="dedicated",
    show_default=True,
    help="Compute target kind.",
)
@click.option("--name", required=True, help="Compute target name.")
@click.option("--owner", help="Owner username or organization to create the target under.")
@click.pass_obj
def compute_targets_create_command(
    state: TreqsContext,
    kind: str,
    name: str,
    owner: str | None,
) -> None:
    """Create a dedicated compute target for a TReqs owner."""
    auth_state, access_context = load_access_context(state)
    scope = _resolve_compute_scope(state, access_context, owner)
    with TreqsApiClient(auth_state.api_url) as client:
        target = ComputeTargetService(client, auth_state, scope).create(
            ComputeTargetCreateInput(name=name)
        )

    if state.json_output:
        emit_json(target)
        return

    click.echo(f"Created compute target {target.name}.")
    click.echo(f"ID: {target.id}")
    click.echo(f"Kind: {target.kind or 'dedicated'}")
    click.echo(f"Type: {target.type}")


@compute_group.group("secrets")
def compute_secrets_group() -> None:
    """Manage compute target secrets for the current TReqs owner."""


@compute_secrets_group.command("set")
@click.option("--target", "target", required=True, help="Compute target ID or name.")
@click.option("--owner", help="Owner username or organization that owns the target.")
@click.argument("assignments", nargs=-1, required=True)
@click.pass_obj
def compute_secrets_set_command(
    state: TreqsContext,
    target: str,
    owner: str | None,
    assignments: tuple[str, ...],
) -> None:
    """Set one or more KEY=VALUE secrets on a compute target."""
    auth_state, access_context = load_access_context(state)
    scope = _resolve_compute_scope(state, access_context, owner)

    try:
        secrets = [parse_secret_assignment(assignment) for assignment in assignments]
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    succeeded: list[str] = []
    failures: list[tuple[str, str]] = []
    with TreqsApiClient(auth_state.api_url) as client:
        service = ComputeTargetService(client, auth_state, scope)
        target_id = _resolve_target_id(service, target)
        for secret in secrets:
            try:
                service.set_secret(target_id, secret)
            except TreqsCliError as exc:
                # Non-atomic: record the failure and keep setting the remaining secrets.
                failures.append((secret.name, str(exc)))
            else:
                succeeded.append(secret.name)

    if state.json_output:
        emit_json(
            {
                "targetId": target_id,
                "succeeded": succeeded,
                "failed": [{"name": name, "error": error} for name, error in failures],
            }
        )
    else:
        for name in succeeded:
            click.echo(f"Set secret {name}.")
        for name, error in failures:
            click.echo(f"Failed to set secret {name}: {error}")

    if failures:
        raise ConfigError(
            f"Failed to set {len(failures)} of {len(secrets)} secrets on compute target {target}."
        )


@compute_targets_group.group("registration-code")
def compute_targets_registration_code_group() -> None:
    """Manage agent registration codes for compute targets."""


@compute_targets_registration_code_group.command("create")
@click.option("--target", "target", required=True, help="Compute target ID or name.")
@click.option("--owner", help="Owner username or organization that owns the target.")
@click.pass_obj
def compute_targets_registration_code_create_command(
    state: TreqsContext,
    target: str,
    owner: str | None,
) -> None:
    """Create an agent registration code for a compute target."""
    auth_state, access_context = load_access_context(state)
    scope = _resolve_compute_scope(state, access_context, owner)
    with TreqsApiClient(auth_state.api_url) as client:
        service = ComputeTargetService(client, auth_state, scope)
        target_id = _resolve_target_id(service, target)
        registration_code = service.create_registration_code(target_id)

    if state.json_output:
        emit_json(registration_code)
        return

    click.echo(registration_code.code)


def _resolve_target_id(service: ComputeTargetService, selection: str) -> str:
    try:
        return resolve_compute_target_id(service.list(), selection)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _resolve_compute_scope(
    state: TreqsContext,
    access_context: AccessContext,
    owner: str | None,
) -> ComputeTargetScope:
    if owner is not None:
        selected_owner = resolve_owner_selection(access_context, owner)
        return ComputeTargetScope(
            owner_username=selected_owner.username,
            current_username=access_context.user.username,
        )

    if state.is_git_repo:
        repo_context = state.repo_context_store.load()
        if repo_context is not None:
            return ComputeTargetScope(
                owner_username=repo_context.owner_username,
                current_username=repo_context.current_username,
            )

    selected_owner = current_user_owner(access_context)
    return ComputeTargetScope(
        owner_username=selected_owner.username,
        current_username=access_context.user.username,
    )
