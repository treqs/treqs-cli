from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from click.testing import CliRunner

from treqs_cli.cli import cli
from treqs_cli.config import AuthStore
from treqs_cli.models import AccessContext, AuthState


class _FakeClient:
    payload: ClassVar[dict[str, object]] = {}

    def __init__(self, api_url: str) -> None:
        self.api_url = api_url

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get_access_context(self, _auth_state: AuthState) -> AccessContext:
        return AccessContext.model_validate(self.payload)


def _setup(monkeypatch: Any, tmp_path: Path, payload: dict[str, object]) -> dict[str, str]:
    config_home = tmp_path / "config"
    AuthStore(config_home / "auth.json").save(
        AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    )
    _FakeClient.payload = payload
    monkeypatch.setattr("treqs_cli.commands.shared.TreqsApiClient", _FakeClient)
    monkeypatch.chdir(tmp_path)
    return {"TREQS_CONFIG_HOME": str(config_home)}


def test_orgs_list_renders_org_owners_only(monkeypatch: Any, tmp_path: Path) -> None:
    env = _setup(monkeypatch, tmp_path, _access_context_payload())
    runner = CliRunner()

    result = runner.invoke(cli, ["orgs", "list"], env=env, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "acme" in result.output
    assert "Acme Inc" in result.output
    assert "admin" in result.output
    # Personal owner is not an organization.
    assert "trevor" not in result.output


def test_orgs_list_emits_json_rows(monkeypatch: Any, tmp_path: Path) -> None:
    env = _setup(monkeypatch, tmp_path, _access_context_payload())
    runner = CliRunner()

    result = runner.invoke(cli, ["--json", "orgs", "list"], env=env, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert rows == [
        {
            "id": "org-1",
            "username": "acme",
            "name": "Acme Inc",
            "role": "admin",
            "projects": "2",
        },
        {
            "id": "org-2",
            "username": "beta",
            "name": "beta",
            "role": "member",
            "projects": "0",
        },
    ]


def test_orgs_list_reports_when_user_has_no_orgs(monkeypatch: Any, tmp_path: Path) -> None:
    payload = _access_context_payload()
    payload["owners"] = [payload["owners"][0]]  # type: ignore[index]
    payload["projects_by_owner"] = {"user-1": []}
    env = _setup(monkeypatch, tmp_path, payload)
    runner = CliRunner()

    result = runner.invoke(cli, ["orgs", "list"], env=env, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "do not belong to any organizations" in result.output


def test_whoami_names_each_owner_with_type_role_and_projects(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    env = _setup(monkeypatch, tmp_path, _access_context_payload())
    runner = CliRunner()

    result = runner.invoke(cli, ["whoami"], env=env, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "Owners: 3" in result.output
    assert "  - trevor (user, owner, projects=1)" in result.output
    assert "  - acme (organization, admin, projects=2)" in result.output
    assert "  - beta (organization, member, projects=0)" in result.output


def _access_context_payload() -> dict[str, Any]:
    return {
        "user": {
            "id": "user-1",
            "sub": "sub-1",
            "username": "trevor",
            "email": "trevor@example.com",
        },
        "owners": [
            {
                "id": "user-1",
                "type": "user",
                "username": "trevor",
                "display_name": "Trevor",
                "role": "owner",
            },
            {
                "id": "org-2",
                "type": "organization",
                "username": "beta",
                "display_name": None,
                "role": "member",
            },
            {
                "id": "org-1",
                "type": "organization",
                "username": "acme",
                "display_name": "Acme Inc",
                "role": "admin",
            },
        ],
        "projects_by_owner": {
            "user-1": [
                {
                    "id": "project-1",
                    "slug": "mnist",
                    "name": "MNIST",
                    "visibility": "private",
                    "can_write": True,
                }
            ],
            "org-1": [
                {
                    "id": "project-2",
                    "slug": "mnist",
                    "name": "MNIST Org",
                    "visibility": "private",
                    "can_write": True,
                },
                {
                    "id": "project-3",
                    "slug": "vision",
                    "name": "Vision",
                    "visibility": "private",
                    "can_write": False,
                },
            ],
        },
    }
