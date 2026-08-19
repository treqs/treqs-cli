"""Contract test for the CLI-wide owner scoping convention.

Every leaf command must fall into exactly one class:

- OWNER_SCOPED: talks to owner-scoped API paths directly and must carry the
  shared --owner option from `treqs_cli.commands.shared.owner_option`.
- REPO_BOUND: resolves its owner exclusively from the repo-local project
  context in `.treqs/config.toml` and must NOT expose --owner.
- SCOPE_FREE: does not target a single owner (auth, discovery/list-all
  commands) and must NOT expose --owner.

Adding a command without classifying it here fails this test on purpose:
pick a class, and if it is OWNER_SCOPED use the shared owner_option
decorator instead of a hand-rolled flag.
"""

from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module

import click

from treqs_cli.command_registry import COMMAND_SPECS
from treqs_cli.commands.shared import OWNER_OPTION_HELP

OWNER_SCOPED = {
    "projects create",
    "project init",
    "compute targets list",
    "compute targets instances",
    "compute targets create",
    "compute targets archive",
    "compute targets registration-code create",
    "compute secrets set",
    "compute secrets list",
    "compute secrets delete",
}

REPO_BOUND = {
    "project use",
    "project status",
    "project clear",
    "doctor",
    "run",
    "tr list",
    "tr create",
    "tr show",
    "tr update",
    "tr open",
    "tr queue",
    "tr comment",
    "tr review approve",
    "tr review reject",
    "jobs list",
    "jobs show",
    "jobs cancel",
    "jobs logs",
    "jobs tasks",
    "jobs wait",
    "jobs watch",
    "jobs republish-lineage",
}

SCOPE_FREE = {
    "login",
    "logout",
    "whoami",
    "projects list",
    "orgs list",
}


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


def _owner_params(command: click.Command) -> list[click.Option]:
    return [
        param
        for param in command.params
        if isinstance(param, click.Option) and "--owner" in param.opts
    ]


def test_every_command_is_classified_exactly_once() -> None:
    discovered = {path for path, _command in _iter_leaf_commands()}
    classified = OWNER_SCOPED | REPO_BOUND | SCOPE_FREE

    unclassified = discovered - classified
    stale = classified - discovered
    overlaps = (OWNER_SCOPED & REPO_BOUND) | (OWNER_SCOPED & SCOPE_FREE) | (REPO_BOUND & SCOPE_FREE)

    assert not unclassified, (
        f"New commands must be classified in the owner-scope contract test: {sorted(unclassified)}"
    )
    assert not stale, f"Classified commands no longer exist: {sorted(stale)}"
    assert not overlaps, f"Commands classified more than once: {sorted(overlaps)}"


def test_owner_scoped_commands_use_the_shared_owner_option() -> None:
    commands = dict(_iter_leaf_commands())
    for path in sorted(OWNER_SCOPED):
        owner_params = _owner_params(commands[path])
        assert owner_params, f"`treqs {path}` must accept --owner via owner_option."
        assert owner_params[0].help == OWNER_OPTION_HELP, (
            f"`treqs {path}` must use the shared owner_option decorator, "
            "not a hand-rolled --owner flag."
        )


def test_non_owner_scoped_commands_do_not_expose_owner_flags() -> None:
    commands = dict(_iter_leaf_commands())
    for path in sorted(REPO_BOUND | SCOPE_FREE):
        assert not _owner_params(commands[path]), (
            f"`treqs {path}` must not expose --owner; it is classified as "
            f"{'repo-bound' if path in REPO_BOUND else 'scope-free'}."
        )
