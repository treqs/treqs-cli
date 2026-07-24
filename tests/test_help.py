"""Help discoverability contract.

The universal rules (every leaf command has an Examples epilog; every
positional argument is documented by its uppercase metavar in the command
docstring) are enforced for the whole command tree.
"""

from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module

import click
from click.testing import CliRunner

from treqs_cli.cli import cli
from treqs_cli.command_registry import COMMAND_SPECS
from treqs_cli.help_text import EXAMPLES_HEADER


def _iter_leaf_commands() -> Iterator[tuple[str, click.Command]]:
    for spec in COMMAND_SPECS:
        module = import_module(spec.module_path)
        command = getattr(module, spec.attr_name)
        yield from _walk(spec.name, command)


def _walk(path: str, command: click.Command) -> Iterator[tuple[str, click.Command]]:
    if isinstance(command, click.Group):
        for name, subcommand in command.commands.items():
            yield from _walk(f"{path} {name}", subcommand)
    else:
        yield path, command


def test_root_help_shows_quick_start_scope_contract_and_env_vars() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Quick start:" in result.output
    assert "Owner scope:" in result.output
    assert "TREQS_API_URL" in result.output


def test_project_use_help_documents_selection_forms() -> None:
    result = CliRunner().invoke(cli, ["project", "use", "--help"])

    assert result.exit_code == 0
    assert "<owner>/<project>" in result.output
    assert "acme/mnist" in result.output
    assert EXAMPLES_HEADER in result.output


def test_every_leaf_command_has_an_examples_epilog() -> None:
    missing = [
        path
        for path, command in _iter_leaf_commands()
        if EXAMPLES_HEADER not in (command.epilog or "")
    ]
    assert not missing, (
        "Every command must document example invocations via "
        f"treqs_cli.help_text.examples: {sorted(missing)}"
    )


def test_every_argument_is_documented_in_its_command_docstring() -> None:
    missing: list[str] = []
    for path, command in _iter_leaf_commands():
        help_text = command.help or ""
        for param in command.params:
            if not isinstance(param, click.Argument):
                continue
            metavar = (param.metavar or param.name or "").upper().rstrip(".")
            if metavar and metavar not in help_text:
                missing.append(f"{path} <{metavar}>")
    assert not missing, (
        "Click never renders argument descriptions, so each command docstring "
        f"must explain its arguments by metavar: {sorted(missing)}"
    )
