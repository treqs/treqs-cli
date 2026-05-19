from __future__ import annotations

import click

from ..api import TreqsApiClient
from ..application.compute.models import compute_target_rows
from ..application.compute.service import ComputeTargetScope, ComputeTargetService
from ..context import TreqsContext, current_user_owner, resolve_owner_selection
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
