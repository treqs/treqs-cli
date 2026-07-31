from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

import click

from ..api import TreqsApiClient
from ..application.compute.models import (
    AwsLaunchOptions,
    ComputeTarget,
    ComputeTargetCreateInput,
    compute_target_rows,
    parse_secret_assignment,
    secret_rows,
)
from ..application.compute.service import (
    ComputeTargetService,
    resolve_compute_target_id,
)
from ..context import OwnerScope, TreqsContext
from ..errors import ConfigError, TreqsCliError
from ..help_text import examples
from ..output import emit_json, render_table
from .shared import load_access_context, owner_option, resolve_owner_scope

T = TypeVar("T")


@click.group("compute")
def compute_group() -> None:
    """Inspect compute resources for the current TReqs owner."""


@compute_group.group("targets")
def compute_targets_group() -> None:
    """Inspect compute targets for the current TReqs owner."""


@compute_targets_group.command(
    "list",
    epilog=examples(
        "treqs compute targets list",
        "treqs compute targets list --owner acme",
        "treqs compute targets list --all",
        "treqs --json compute targets list --include-agent",
    ),
)
@click.option("--include-agent", is_flag=True, help="Include registered agent details.")
@owner_option
@click.option(
    "--all",
    "list_all",
    is_flag=True,
    help="List compute targets across every owner available to you.",
)
@click.pass_obj
def compute_targets_list_command(
    state: TreqsContext,
    include_agent: bool,
    owner: str | None,
    list_all: bool,
) -> None:
    """List compute targets for a TReqs owner (or all your owners with --all)."""
    auth_state, access_context = load_access_context(state)
    if list_all and owner:
        raise ConfigError("--all and --owner cannot be used together.")

    owner_by_id = {o.id: o.username for o in access_context.owners}

    with TreqsApiClient(auth_state.api_url) as client:
        targets: list[ComputeTarget]
        if list_all:
            targets = []
            for access_owner in access_context.owners:
                scope = OwnerScope(
                    owner_username=access_owner.username,
                    current_username=access_context.user.username,
                )
                targets.extend(
                    ComputeTargetService(client, auth_state, scope).list(
                        include_agent=include_agent
                    )
                )
            scope_label = "all your owners"
        else:
            scope = resolve_owner_scope(state, access_context, owner)
            targets = ComputeTargetService(client, auth_state, scope).list(
                include_agent=include_agent
            )
            scope_label = scope.owner_username

    if state.json_output:
        emit_json(targets)
        return

    click.echo(f"Compute targets for {scope_label} ({len(targets)}):")
    headers = [
        ("id", "ID"),
        ("name", "NAME"),
        ("kind", "KIND"),
        ("type", "TYPE"),
        ("status", "STATUS"),
        ("agent", "AGENT"),
    ]
    if list_all:
        render_table(compute_target_rows(targets, owner_by_id), [("owner", "OWNER"), *headers])
    else:
        render_table(compute_target_rows(targets), headers)


@compute_targets_group.command(
    "create",
    epilog=examples(
        "treqs compute targets create --name gpu-box",
        "treqs compute targets create --name team-gpu --owner acme",
        "treqs compute targets create --kind on-demand --name burst --type runpod \\",
        "    --instance-type cpu3c",
    ),
)
@click.option(
    "--kind",
    type=click.Choice(["dedicated", "on-demand"]),
    default="dedicated",
    show_default=True,
    help="Compute target kind.",
)
@click.option("--name", required=True, help="Compute target name.")
@click.option(
    "--type",
    "target_type",
    help="Provider for on-demand targets (runpod, lambda, aws, gcp, azure).",
)
@click.option("--instance-type", help="Instance type / flavor for on-demand targets (e.g. cpu3c).")
@click.option(
    "--region", default="any", show_default=True, help="Region (or 'any') for on-demand targets."
)
@click.option(
    "--ami-id",
    help=(
        "AWS AMI ID (--type aws only; required for AWS launches). Omit in an "
        "interactive session with a concrete --region to pick one from a live list."
    ),
)
@click.option(
    "--subnet-id",
    "subnet_ids",
    multiple=True,
    help=(
        "AWS subnet ID (--type aws only; repeatable). The first is the primary "
        "subnet; additional ones are fallback candidates tried on a per-AZ "
        "capacity error. Optional - AWS uses the account/VPC default if unset."
    ),
)
@click.option(
    "--security-group-id",
    "security_group_ids",
    multiple=True,
    help="AWS security group ID (--type aws only; repeatable, optional).",
)
@click.option(
    "--ssh-key-name",
    help="AWS EC2 key pair name to attach to the instance (--type aws only, optional).",
)
@click.option(
    "--install-roar",
    is_flag=True,
    help="Install roar on the instance at startup via the managed bootstrap (on-demand).",
)
@click.option(
    "--roar-ref",
    "roar_ref",
    help=(
        "Pin roar to a git ref (branch/tag) built from source instead of the "
        "PyPI release (on-demand; requires --install-roar)."
    ),
)
@click.option("--userdata-script", help="Extra shell run at instance startup (on-demand).")
@click.option(
    "--auto-shutdown", is_flag=True, help="Auto-shut down the instance when idle (on-demand)."
)
@click.option(
    "--idle-timeout",
    "idle_timeout_minutes",
    type=int,
    help="Idle minutes before auto-shutdown (on-demand).",
)
@click.option("--description", help="Compute target description.")
@owner_option
@click.pass_obj
def compute_targets_create_command(
    state: TreqsContext,
    kind: str,
    name: str,
    target_type: str | None,
    instance_type: str | None,
    region: str,
    ami_id: str | None,
    subnet_ids: tuple[str, ...],
    security_group_ids: tuple[str, ...],
    ssh_key_name: str | None,
    install_roar: bool,
    roar_ref: str | None,
    userdata_script: str | None,
    auto_shutdown: bool,
    idle_timeout_minutes: int | None,
    description: str | None,
    owner: str | None,
) -> None:
    """Create a compute target (dedicated, or on-demand for a provider)."""
    if kind == "on-demand":
        if not target_type:
            raise ConfigError("--type (provider) is required for on-demand targets.")
        if not instance_type:
            raise ConfigError("--instance-type is required for on-demand targets.")
        effective_type = target_type
    else:
        effective_type = "dedicated"

    auth_state, access_context = load_access_context(state)
    scope = resolve_owner_scope(state, access_context, owner)
    with TreqsApiClient(auth_state.api_url) as client:
        service = ComputeTargetService(client, auth_state, scope)

        if effective_type == "aws" and ami_id is None:
            ami_id, wizard_subnet_ids, wizard_security_group_ids = _resolve_aws_resources(
                state, service, region, subnet_ids, security_group_ids
            )
            subnet_ids = wizard_subnet_ids
            security_group_ids = wizard_security_group_ids

        target = service.create(
            ComputeTargetCreateInput(
                name=name,
                kind=kind,
                type=effective_type,
                instance_type=instance_type,
                region=region,
                ami_id=ami_id,
                subnet_ids=subnet_ids,
                security_group_ids=security_group_ids,
                ssh_key_name=ssh_key_name,
                install_roar=install_roar,
                roar_ref=roar_ref,
                userdata_script=userdata_script,
                auto_shutdown=auto_shutdown,
                idle_timeout_minutes=idle_timeout_minutes,
                description=description,
            )
        )

    if state.json_output:
        emit_json(target)
        return

    click.echo(f"Created compute target {target.name}.")
    click.echo(f"ID: {target.id}")
    click.echo(f"Kind: {target.kind or kind}")
    click.echo(f"Type: {target.type}")


def _resolve_aws_resources(
    state: TreqsContext,
    service: ComputeTargetService,
    region: str,
    subnet_ids: tuple[str, ...],
    security_group_ids: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Resolve an AWS on-demand target's AMI (required) and, if not already
    passed via flags, its subnet(s)/security group(s).

    Interactively walks the same AMI -> primary subnet (+ optional fallback
    subnets) -> security groups sequence as the dashboard's create wizard,
    backed by the same GET /provider-credentials/aws/launch-options data an
    agent could also call directly. Non-interactively, --ami-id must be
    passed explicitly since there is nothing to prompt.
    """
    if not state.is_interactive:
        raise ConfigError(
            "--ami-id is required for AWS on-demand targets (AWS EC2 launches fail "
            "without one). Run interactively with a concrete --region to select one "
            "from a live list, or pass --ami-id explicitly."
        )
    if region == "any":
        raise ConfigError(
            "AWS resource selection needs a concrete --region (not 'any') to look up "
            "AMIs/subnets/security groups for."
        )

    click.echo(f"Fetching AWS launch options for {region}...")
    options: AwsLaunchOptions = service.get_aws_launch_options(region)
    errors = options.errors or {}

    selected_ami = _prompt_choice(
        "AMI",
        options.amis,
        format_item=lambda ami: f"{ami.name}  ({ami.id})",
        get_id=lambda ami: ami.id,
        required=True,
        error=errors.get("amis"),
    )
    assert selected_ami is not None  # required=True guarantees a non-None return

    resolved_subnet_ids = list(subnet_ids)
    if not resolved_subnet_ids:
        remaining_subnets = list(options.subnets)
        primary = _prompt_choice(
            "primary subnet",
            remaining_subnets,
            format_item=lambda s: f"{s.id}  (az={s.availabilityZone})"
            + (f"  {s.name}" if s.name else ""),
            get_id=lambda s: s.id,
            required=False,
            error=errors.get("subnets"),
        )
        if primary is not None:
            resolved_subnet_ids.append(primary)
            remaining_subnets = [s for s in remaining_subnets if s.id != primary]
            while remaining_subnets and click.confirm(
                "Add a fallback subnet (tried if the primary is out of capacity)?",
                default=False,
            ):
                fallback = _prompt_choice(
                    "fallback subnet",
                    remaining_subnets,
                    format_item=lambda s: f"{s.id}  (az={s.availabilityZone})"
                    + (f"  {s.name}" if s.name else ""),
                    get_id=lambda s: s.id,
                    required=False,
                )
                if fallback is None:
                    break
                resolved_subnet_ids.append(fallback)
                remaining_subnets = [s for s in remaining_subnets if s.id != fallback]

    resolved_security_group_ids = list(security_group_ids)
    if not resolved_security_group_ids and options.securityGroups:
        remaining_groups = list(options.securityGroups)
        while remaining_groups and click.confirm("Add a security group?", default=False):
            group = _prompt_choice(
                "security group",
                remaining_groups,
                format_item=lambda g: f"{g.name}  ({g.id})",
                get_id=lambda g: g.id,
                required=False,
            )
            if group is None:
                break
            resolved_security_group_ids.append(group)
            remaining_groups = [g for g in remaining_groups if g.id != group]

    return selected_ami, tuple(resolved_subnet_ids), tuple(resolved_security_group_ids)


def _prompt_choice(
    label: str,
    items: Sequence[T],
    *,
    format_item: Callable[[T], str],
    get_id: Callable[[T], str],
    required: bool,
    error: str | None = None,
) -> str | None:
    """Print a numbered list and prompt for a selection.

    Returns the selected item's id, or None if the caller allowed skipping
    (required=False) and either nothing was available or the user skipped.
    """
    if not items:
        detail = f" ({error})" if error else ""
        if required:
            raise ConfigError(f"No {label} options available for this region{detail}.")
        click.echo(f"No {label} options found{detail}; skipping.")
        return None

    click.echo(f"\nAvailable {label}s:")
    for index, item in enumerate(items, start=1):
        click.echo(f"  {index}) {format_item(item)}")

    while True:
        raw = click.prompt(
            f"Select {label}" + ("" if required else " (blank to skip)"),
            default="",
            show_default=False,
        )
        if not raw:
            if required:
                click.echo("A selection is required.")
                continue
            return None
        if not raw.isdigit() or not (1 <= int(raw) <= len(items)):
            click.echo(f"Enter a number between 1 and {len(items)}.")
            continue
        return get_id(items[int(raw) - 1])


@compute_group.group("secrets")
def compute_secrets_group() -> None:
    """Manage compute target secrets for the current TReqs owner."""


@compute_secrets_group.command(
    "set",
    epilog=examples(
        "treqs compute secrets set --target gpu-box WANDB_API_KEY=abc123",
        "treqs compute secrets set --target gpu-box --owner acme HF_TOKEN=hf_x REGION=us",
    ),
)
@click.option("--target", "target", required=True, help="Compute target ID or name.")
@owner_option
@click.argument("assignments", nargs=-1, required=True)
@click.pass_obj
def compute_secrets_set_command(
    state: TreqsContext,
    target: str,
    owner: str | None,
    assignments: tuple[str, ...],
) -> None:
    """Set one or more KEY=VALUE secrets on a compute target.

    ASSIGNMENTS are KEY=VALUE pairs, separated by spaces. --target accepts a
    compute target ID, a unique name, or a unique ID prefix from
    `treqs compute targets list`.
    """
    auth_state, access_context = load_access_context(state)
    scope = resolve_owner_scope(state, access_context, owner)

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


@compute_secrets_group.command(
    "list",
    epilog=examples(
        "treqs compute secrets list --target gpu-box",
        "treqs --json compute secrets list --target gpu-box --owner acme",
    ),
)
@click.option("--target", "target", required=True, help="Compute target ID or name.")
@owner_option
@click.pass_obj
def compute_secrets_list_command(
    state: TreqsContext,
    target: str,
    owner: str | None,
) -> None:
    """List secret names (and metadata) set on a compute target.

    Secret values are never returned by the API and are not shown here.
    """
    auth_state, access_context = load_access_context(state)
    scope = resolve_owner_scope(state, access_context, owner)

    with TreqsApiClient(auth_state.api_url) as client:
        service = ComputeTargetService(client, auth_state, scope)
        target_id = _resolve_target_id(service, target)
        secrets = service.list_secrets(target_id)

    if state.json_output:
        emit_json(secrets)
        return

    click.echo(f"Secrets on compute target {target} ({len(secrets)}):")
    render_table(
        secret_rows(secrets),
        [
            ("name", "NAME"),
            ("createdAt", "CREATED"),
            ("updatedAt", "UPDATED"),
            ("createdBy", "CREATED BY"),
            ("updatedBy", "UPDATED BY"),
        ],
    )


@compute_secrets_group.command(
    "delete",
    epilog=examples(
        "treqs compute secrets delete --target gpu-box HF_TOKEN",
        "treqs compute secrets delete --target gpu-box --yes HF_TOKEN",
    ),
)
@click.option("--target", "target", required=True, help="Compute target ID or name.")
@owner_option
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip the delete confirmation prompt (for non-interactive use).",
)
@click.argument("name")
@click.pass_obj
def compute_secrets_delete_command(
    state: TreqsContext,
    target: str,
    owner: str | None,
    yes: bool,
    name: str,
) -> None:
    """Delete a secret from a compute target.

    NAME is the secret's name, as shown by `treqs compute secrets list`. Any
    job dispatched to this target after deletion will no longer receive this
    secret as an environment variable.
    """
    _confirm_secret_delete(state, target, name, yes)

    auth_state, access_context = load_access_context(state)
    scope = resolve_owner_scope(state, access_context, owner)

    with TreqsApiClient(auth_state.api_url) as client:
        service = ComputeTargetService(client, auth_state, scope)
        target_id = _resolve_target_id(service, target)
        service.delete_secret(target_id, name)

    if state.json_output:
        emit_json({"targetId": target_id, "deleted": name})
        return

    click.echo(f"Deleted secret {name} from compute target {target}.")


def _confirm_secret_delete(state: TreqsContext, target: str, name: str, yes: bool) -> None:
    """Guard against accidentally deleting a secret a job still depends on.

    Needs explicit confirmation: interactively via a prompt, or --yes for
    scripted/unattended use. In a non-interactive session without --yes,
    fails loudly instead of hanging on a prompt nobody can answer.
    """
    if yes:
        return
    if not state.is_interactive:
        raise ConfigError(
            f"Deleting secret {name} from compute target {target}. "
            "Re-run with --yes to confirm in a non-interactive session."
        )
    if not click.confirm(
        f"This will delete secret {name} from compute target {target}. Continue?",
        default=False,
    ):
        raise click.Abort()


@compute_targets_group.group("registration-code")
def compute_targets_registration_code_group() -> None:
    """Manage agent registration codes for compute targets."""


@compute_targets_registration_code_group.command(
    "create",
    epilog=examples(
        "treqs compute targets registration-code create --target gpu-box",
        "treqs compute targets registration-code create --target gpu-box --owner acme",
    ),
)
@click.option("--target", "target", required=True, help="Compute target ID or name.")
@owner_option
@click.pass_obj
def compute_targets_registration_code_create_command(
    state: TreqsContext,
    target: str,
    owner: str | None,
) -> None:
    """Create an agent registration code for a compute target.

    Prints a one-time code used to register a treqs-agent on the target
    machine. --target accepts a compute target ID, a unique name, or a
    unique ID prefix from `treqs compute targets list`.
    """
    auth_state, access_context = load_access_context(state)
    scope = resolve_owner_scope(state, access_context, owner)
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
