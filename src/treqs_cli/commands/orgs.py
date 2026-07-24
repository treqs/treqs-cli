from __future__ import annotations

import click

from ..context import TreqsContext
from ..models import AccessContext, AccessOwner
from ..output import emit_json, render_table
from .shared import load_access_context


@click.group("orgs")
def orgs_group() -> None:
    """List TReqs organizations you belong to."""


@orgs_group.command("list")
@click.pass_obj
def orgs_list_command(state: TreqsContext) -> None:
    """List organizations you belong to.

    Every USERNAME listed here is a valid value for --owner on owner-scoped
    commands and for <owner>/<project> selections in `treqs project use`.
    """
    _auth_state, access_context = load_access_context(state)
    rows = _org_rows(access_context)

    if state.json_output:
        emit_json(rows)
        return

    if not rows:
        click.echo("You do not belong to any organizations.")
        return

    render_table(
        rows,
        [
            ("username", "USERNAME"),
            ("name", "NAME"),
            ("role", "ROLE"),
            ("projects", "PROJECTS"),
        ],
    )


def _org_rows(access_context: AccessContext) -> list[dict[str, str]]:
    rows = [
        _org_row(owner, len(access_context.projects_by_owner.get(owner.id, [])))
        for owner in access_context.owners
        if owner.type == "organization"
    ]
    rows.sort(key=lambda row: row["username"])
    return rows


def _org_row(owner: AccessOwner, project_count: int) -> dict[str, str]:
    return {
        "id": owner.id,
        "username": owner.username,
        "name": owner.display_name or owner.username,
        "role": owner.role,
        "projects": str(project_count),
    }
