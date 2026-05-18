# treqs-cli

`treqs-cli` is the command-line control plane for TReqs. This first slice focuses on
authentication, identity, project discovery, and repo-local project context.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
mypy src/treqs_cli
```

## Commands

```bash
treqs login
treqs whoami
treqs projects list
treqs project use <owner>/<project>
treqs project status
```

The CLI stores global auth state under the platform config directory, or
`TREQS_CONFIG_HOME` when set. Repo context is written to `.treqs/config.toml`.

