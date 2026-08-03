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

Every command documents its options, arguments, and examples in `--help`; the
full generated reference lives in [docs/CLI.md](docs/CLI.md) (regenerate with
`uv run python -m treqs_cli.reference_docs`).

### `treqs login` / `treqs logout`

Authenticate via browser/device login or a dashboard-generated API token;
`logout` clears local auth state and revokes the session when possible.

```bash
treqs login
treqs login --token treqs_pat_...
treqs logout
```

### `treqs whoami`

Show the authenticated user and every owner (yourself plus organizations) you
can act as, with your role and project count per owner.

```bash
treqs whoami
```

### `treqs orgs list`

List organizations you belong to. Every name shown is a valid `--owner` value
for owner-scoped commands and for `<owner>/<project>` selections.

```bash
treqs orgs list
```

### `treqs projects`

List projects available to you, or create a new one for an owner.

```bash
treqs projects list
treqs projects create "MNIST Digits" --visibility public
treqs projects create "Team Model" --owner acme
```

### `treqs project`

Manage the repo-local project binding, written to `.treqs/config.toml`. This
binding drives `tr` and `jobs` commands and sets the default owner scope for
owner-scoped commands.

```bash
treqs project use <owner>/<project>
treqs project status
treqs project clear
```

### `treqs tr`

Manage training requests for the repo-bound project: create a draft, open it
against a compute target, then queue it as a job.

```bash
treqs tr create --title "Train MNIST" --workflow-path .treqs/workflows/train.yaml
treqs tr list --status open
treqs tr open <request-id> --compute-target <target>
treqs tr queue <request-id>
```

### `treqs compute`

Inspect and create compute targets, set their secrets, and issue agent
registration codes.

```bash
treqs compute targets list --owner <owner>
treqs compute targets create --name gpu-box
treqs compute secrets set --target gpu-box WANDB_API_KEY=abc123
treqs compute targets registration-code create --target gpu-box
```

### `treqs jobs`

Inspect jobs, which are created by `treqs tr queue`.

```bash
treqs jobs list --status QUEUED
treqs jobs show <job-id>
treqs jobs watch <job-id>
treqs jobs logs <job-id> --follow
treqs jobs republish-lineage <job-id>
```

`jobs watch` follows compute provisioning, agent acquisition, execution, and
terminal status while also streaming workload logs. Lifecycle status is sent
to stderr and workload output remains on stdout. Ctrl-C detaches without
cancelling the job; use `treqs jobs cancel <job-id>` to cancel explicitly.

### API tokens

Besides the browser/device flow, the CLI accepts personal API tokens generated
in the TReqs dashboard (`treqs_pat_...`):

- `treqs login --token treqs_pat_...` validates the token against the API and
  stores it like a normal login. Use `--token -` to read the token from stdin
  (e.g. `echo $TOKEN | treqs login --token -`) so it never hits shell history.
- `TREQS_API_TOKEN=treqs_pat_...` authenticates API requests directly from the
  environment without touching stored auth state. When set, it takes
  precedence over any stored login; `treqs logout` still clears stored state
  but the environment token stays active until unset.

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
