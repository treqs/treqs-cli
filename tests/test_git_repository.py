from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from treqs_cli.git_repository import GitRepository


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def repository(tmp_path: Path) -> GitRepository:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "TReqs Test")
    git(repo, "config", "user.email", "test@treqs.invalid")
    git(repo, "remote", "add", "origin", str(remote))
    (repo / "train.py").write_text("print('train')\n", encoding="utf-8")
    git(repo, "add", "train.py")
    git(repo, "commit", "-m", "initial")
    git(repo, "push", "-u", "origin", "main")
    return GitRepository(repo)


def test_resolves_clean_pushed_head(repository: GitRepository) -> None:
    assert len(repository.head_commit()) == 40
    assert repository.current_branch() == "main"
    assert repository.default_branch() == "main"
    assert repository.is_clean()
    assert repository.head_is_pushed()


def test_ignores_repo_local_treqs_context(repository: GitRepository) -> None:
    config = repository.root / ".treqs" / "config.toml"
    config.parent.mkdir()
    config.write_text("[context]\n", encoding="utf-8")

    assert repository.is_clean()


def test_detects_uncommitted_and_unpushed_source(repository: GitRepository) -> None:
    (repository.root / "train.py").write_text("print('changed')\n", encoding="utf-8")
    assert not repository.is_clean()

    git(repository.root, "add", "train.py")
    git(repository.root, "commit", "-m", "changed")
    assert repository.is_clean()
    assert not repository.head_is_pushed()


def test_adds_treqs_context_to_local_git_exclude(repository: GitRepository) -> None:
    repository.exclude_treqs_context()
    repository.exclude_treqs_context()

    exclude = (repository.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.splitlines().count(".treqs/") == 1
