from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    module_path: str
    attr_name: str
    short_help: str
    help_section: str | None = None
    hidden: bool = False


HELP_SECTION_ORDER: tuple[str, ...] = (
    "Start Here",
    "Project Context",
    "Training Requests",
    "Account",
)


COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec(
        name="login",
        module_path="treqs_cli.commands.auth",
        attr_name="login_command",
        short_help="Authenticate with TReqs using browser/device login.",
        help_section="Start Here",
    ),
    CommandSpec(
        name="whoami",
        module_path="treqs_cli.commands.auth",
        attr_name="whoami_command",
        short_help="Show the authenticated TReqs user and owner access summary.",
        help_section="Start Here",
    ),
    CommandSpec(
        name="projects",
        module_path="treqs_cli.commands.projects",
        attr_name="projects_group",
        short_help="List accessible TReqs projects.",
        help_section="Project Context",
    ),
    CommandSpec(
        name="project",
        module_path="treqs_cli.commands.projects",
        attr_name="project_group",
        short_help="Manage repo-local TReqs project context.",
        help_section="Project Context",
    ),
    CommandSpec(
        name="requests",
        module_path="treqs_cli.commands.requests",
        attr_name="requests_group",
        short_help="Manage training requests for the current TReqs project.",
        help_section="Training Requests",
    ),
    CommandSpec(
        name="logout",
        module_path="treqs_cli.commands.auth",
        attr_name="logout_command",
        short_help="Clear local TReqs auth state and revoke the session when possible.",
        help_section="Account",
    ),
)


def build_lazy_commands() -> dict[str, tuple[str, str, str, bool]]:
    return {
        spec.name: (spec.module_path, spec.attr_name, spec.short_help, spec.hidden)
        for spec in COMMAND_SPECS
    }


def build_help_groups() -> tuple[tuple[str, tuple[str, ...]], ...]:
    sections: dict[str, list[str]] = {section: [] for section in HELP_SECTION_ORDER}
    for spec in COMMAND_SPECS:
        if spec.hidden or spec.help_section is None:
            continue
        sections.setdefault(spec.help_section, []).append(spec.name)

    return tuple(
        (section, tuple(sections.get(section, ())))
        for section in HELP_SECTION_ORDER
        if sections.get(section)
    )
