from __future__ import annotations

from typing import cast
from unittest.mock import patch

import click
from click.testing import CliRunner

from treqs_cli.cli import COMMAND_SPECS, LAZY_COMMANDS, LazyCommand, cli
from treqs_cli.command_registry import build_help_groups


def test_lazy_registry_is_built_from_command_specs() -> None:
    assert {spec.name for spec in COMMAND_SPECS} == set(LAZY_COMMANDS)
    assert len(COMMAND_SPECS) == len({spec.name for spec in COMMAND_SPECS})


def test_help_groups_are_built_from_command_specs() -> None:
    help_groups = dict(build_help_groups())

    assert help_groups["Start Here"] == ("login", "whoami")
    assert help_groups["Project Context"] == ("projects", "project")
    assert help_groups["Training Requests"] == ("tr",)
    assert help_groups["Compute"] == ("compute",)
    assert help_groups["Jobs"] == ("jobs",)
    assert help_groups["Account"] == ("logout",)


def test_top_level_help_uses_registry_without_importing_command_modules() -> None:
    runner = CliRunner()

    with patch("treqs_cli.cli.import_module") as import_module:
        result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0, result.output
    import_module.assert_not_called()
    assert "Start Here:" in result.output
    assert "Project Context:" in result.output
    assert "Training Requests:" in result.output
    assert "Compute:" in result.output
    assert "Jobs:" in result.output
    assert "Account:" in result.output
    assert "Authenticate with TReqs using browser/device login." in result.output
    assert "Manage repo-local TReqs project context." in result.output
    assert "Manage training requests for the current TReqs project." in result.output
    assert "Inspect compute resources for the current TReqs owner." in result.output
    assert "Inspect jobs for the current TReqs project." in result.output


def test_subcommand_help_reports_import_errors_cleanly() -> None:
    runner = CliRunner()
    missing = ModuleNotFoundError("No module named 'httpx'")
    missing.name = "httpx"
    command = cast(click.Group, cli).commands["tr"]
    assert isinstance(command, LazyCommand)
    command._real_command = None

    with patch("treqs_cli.cli.import_module", side_effect=missing):
        result = runner.invoke(cli, ["tr", "--help"])

    assert result.exit_code != 0
    assert "Failed to load 'tr'" in result.output
    assert "httpx" in result.output
    assert "Traceback" not in result.output
