# treqs-cli

`treqs-cli` is the command-line control plane for TReqs. The current slice covers
authentication, identity, project discovery, repo-local project context, training
request lifecycle commands, compute target discovery, and project job inspection.

## Installation

Install `treqs-cli` in an isolated tool environment (Python 3.10+):

```bash
uv tool install treqs-cli
# or
pipx install treqs-cli
```

To install it in an existing environment instead:

```bash
uv pip install treqs-cli
# or
pip install treqs-cli
```

Verify the console script after installation:

```bash
treqs --version
treqs --help
```

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
mypy src/treqs_cli
```

### Local E2E

`tests/e2e/` is a local-only harness and is intentionally ignored by git. It
targets the PM2-managed local `treqs-api` e2e service and database.

Run it explicitly:

```bash
TREQS_CLI_E2E=1 pytest tests/e2e -q
```

Useful overrides:

```bash
TREQS_E2E_API_URL=http://127.0.0.1:3202
TREQS_E2E_DEV_EMAIL=jon+test1@treqs.ai
TREQS_E2E_PROJECT_PREFIX=treqs-cli-e2e
```

Default `pytest` remains fast and deterministic; local e2e tests are skipped
unless `TREQS_CLI_E2E=1` is set.

## Commands

```bash
treqs login
treqs whoami
treqs orgs list
treqs projects list
treqs project use <owner>/<project>
treqs project status
treqs tr list
treqs tr create --title "Train MNIST" --workflow-snapshot-id <snapshot-id>
treqs tr show <request-id>
treqs tr update <request-id> --title "Train Fashion MNIST"
treqs tr update <request-id> --clear-workflow-path --clear-compute-target
treqs tr open <request-id> --workflow-path ".treqs/workflows/train.yaml" --compute-target <target>
treqs tr queue <request-id>
treqs compute targets list --owner <owner>
treqs jobs list --status QUEUED
treqs jobs show <job-id>
```

Every command documents its options, arguments, and examples in `--help`; the
full generated reference lives in [docs/CLI.md](docs/CLI.md) (regenerate with
`uv run python -m treqs_cli.reference_docs`).

### Owner scope

Owner-scoped commands (`projects create`, `compute ...`) accept
`--owner <org>` and default to the repo's bound project owner, then your
personal owner. Repo-bound commands (`project`, `tr`, `jobs`) always use the
binding in `.treqs/config.toml`. Discover organizations with `treqs orgs list`.

The CLI stores global auth state under the platform config directory, or
`TREQS_CONFIG_HOME` when set. Repo context is written to `.treqs/config.toml`.

## Shell completion

Click provides tab completion for commands and options:

```bash
# bash (~/.bashrc)
eval "$(_TREQS_COMPLETE=bash_source treqs)"

# zsh (~/.zshrc)
eval "$(_TREQS_COMPLETE=zsh_source treqs)"

# fish (~/.config/fish/completions/treqs.fish)
_TREQS_COMPLETE=fish_source treqs | source
```
