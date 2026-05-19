# treqs-cli

`treqs-cli` is the command-line control plane for TReqs. This first slice focuses on
authentication, identity, project discovery, repo-local project context, and training
request basics.

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
treqs projects list
treqs project use <owner>/<project>
treqs project status
treqs requests list
treqs requests create --title "Train MNIST"
treqs requests show <request-id>
```

The CLI stores global auth state under the platform config directory, or
`TREQS_CONFIG_HOME` when set. Repo context is written to `.treqs/config.toml`.
