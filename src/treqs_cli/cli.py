from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from typing import Any

import click

from . import __version__
from .command_registry import COMMAND_SPECS, build_help_groups, build_lazy_commands
from .errors import TreqsCliError

LAZY_COMMANDS: dict[str, tuple[str, str, str, bool]] = build_lazy_commands()
HELP_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = build_help_groups()


class _LazyTreqsContext:
    def __init__(self, *, api_url_override: str | None, json_output: bool) -> None:
        self._api_url_override = api_url_override
        self._json_output = json_output
        self._context: Any | None = None

    def _load(self) -> Any:
        if self._context is None:
            from .context import TreqsContext

            self._context = TreqsContext.create(
                api_url_override=self._api_url_override,
                json_output=self._json_output,
            )
        return self._context

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)


class LazyCommand(click.Command):
    def __init__(
        self,
        name: str,
        module_path: str,
        attr_name: str,
        short_help: str,
        hidden: bool = False,
    ) -> None:
        super().__init__(name=name, callback=None, help=short_help, hidden=hidden)
        self._module_path = module_path
        self._attr_name = attr_name
        self._real_command: click.Command | None = None

    def _load(self) -> click.Command:
        if self._real_command is None:
            try:
                module = import_module(self._module_path)
            except ModuleNotFoundError as exc:
                missing = exc.name or "unknown"
                raise click.ClickException(
                    f"Failed to load '{self.name}' because import '{missing}' is unavailable. "
                    "Install treqs-cli with its dependencies or run from the project virtualenv."
                ) from exc
            except ImportError as exc:
                raise click.ClickException(f"Failed to load '{self.name}': {exc}") from exc
            command = getattr(module, self._attr_name)
            if not isinstance(command, click.Command):
                raise click.ClickException(
                    f"Failed to load '{self.name}': {self._module_path}.{self._attr_name} "
                    "is not a Click command."
                )
            self._real_command = command
        return self._real_command

    def invoke(self, ctx: click.Context) -> Any:
        return self._load().invoke(ctx)

    def get_help(self, ctx: click.Context) -> str:
        return self._load().get_help(ctx)

    def get_params(self, ctx: click.Context) -> list[click.Parameter]:
        return self._load().get_params(ctx)

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: Any,
    ) -> click.Context:
        return self._load().make_context(info_name, args, parent=parent, **extra)


class LazyGroup(click.Group):
    def __init__(
        self,
        *args: Any,
        lazy_commands: dict[str, tuple[str, str, str, bool]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._lazy_commands = lazy_commands or {}
        for name, (module_path, attr_name, short_help, hidden) in self._lazy_commands.items():
            self.add_command(
                LazyCommand(name, module_path, attr_name, short_help, hidden),
                name,
            )

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(super().list_commands(ctx))

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        rendered_commands: set[str] = set()

        for section_name, command_names in HELP_GROUPS:
            rows = self._command_rows(ctx, formatter, command_names)
            if not rows:
                continue
            rendered_commands.update(name for name, _help in rows)
            with formatter.section(section_name):
                formatter.write_dl(rows)

        remaining = [name for name in self.list_commands(ctx) if name not in rendered_commands]
        rows = self._command_rows(ctx, formatter, remaining)
        if rows:
            with formatter.section("Other Commands"):
                formatter.write_dl(rows)

    def _command_rows(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
        command_names: Iterable[str],
    ) -> list[tuple[str, str]]:
        commands: list[tuple[str, click.Command]] = []
        max_name_len = 0

        for command_name in command_names:
            command = self.get_command(ctx, command_name)
            if command is None or command.hidden:
                continue
            commands.append((command_name, command))
            max_name_len = max(max_name_len, len(command_name))

        if not commands:
            return []

        help_limit = formatter.width - 6 - max_name_len
        return [
            (command_name, command.get_short_help_str(help_limit))
            for command_name, command in commands
        ]


CLI_EPILOG = """\b
Quick start:
  treqs login
  treqs projects list
  treqs project use <owner>/<project>
  treqs tr create --title "My run" --workflow-path .treqs/workflows/train.yaml
  treqs tr open <request-id> --compute-target <target>
  treqs tr queue <request-id>
  treqs jobs logs <job-id> --follow

\b
Owner scope:
  Owner-scoped commands accept --owner <org> and default to the repo's bound
  project owner, then your personal owner. Repo-bound commands (project, tr,
  jobs) always use the binding in .treqs/config.toml. Discover organizations
  with `treqs orgs list`.

\b
Authentication:
  `treqs login` uses a browser/device flow; `treqs login --token` stores a
  dashboard-issued API token instead. When TREQS_API_TOKEN is set it takes
  precedence over any stored login for API requests and is never persisted.

Run `treqs COMMAND --help` for the options, arguments, and examples of each
command.
"""


@click.command(cls=LazyGroup, lazy_commands=LAZY_COMMANDS, epilog=CLI_EPILOG)
@click.version_option(version=__version__, prog_name="treqs")
@click.option(
    "--api-url",
    envvar="TREQS_API_URL",
    show_envvar=True,
    help="TReqs API base URL.",
)
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_context
def cli(ctx: click.Context, api_url: str | None, json_output: bool) -> None:
    """TReqs command-line control plane."""
    ctx.obj = _LazyTreqsContext(api_url_override=api_url, json_output=json_output)


def main() -> None:
    try:
        cli()
    except TreqsCliError as exc:
        click.ClickException(str(exc)).show()
        raise SystemExit(1) from exc


__all__ = [
    "COMMAND_SPECS",
    "HELP_GROUPS",
    "LAZY_COMMANDS",
    "LazyCommand",
    "LazyGroup",
    "cli",
    "main",
]
