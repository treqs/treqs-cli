from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError


@dataclass(frozen=True)
class GitRepository:
    """Read-only Git launch checks plus local context exclusion."""

    root: Path

    def head_commit(self) -> str:
        return self.resolve_commit("HEAD")

    def resolve_commit(self, revision: str) -> str:
        commit = self._run("rev-parse", "--verify", f"{revision}^{{commit}}")
        if len(commit) != 40:
            raise ConfigError(f"Git revision did not resolve to a full commit: {revision}")
        return commit.lower()

    def current_branch(self) -> str:
        branch = self._run("branch", "--show-current")
        if not branch:
            raise ConfigError("Git HEAD is detached; pass an explicit source branch.")
        return branch

    def default_branch(self) -> str:
        try:
            remote_head = self._run("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        except ConfigError:
            return self.current_branch()
        _origin, separator, branch = remote_head.partition("/")
        return branch if separator and branch else self.current_branch()

    def origin_url(self) -> str:
        url = self._run("config", "--get", "remote.origin.url")
        if not url:
            raise ConfigError("Git remote 'origin' is not configured.")
        return url

    def is_clean(self) -> bool:
        output = self._run("status", "--porcelain", "--untracked-files=all")
        for line in output.splitlines():
            path = line[3:].strip() if len(line) > 3 else ""
            if path == ".treqs/config.toml" or path.startswith(".treqs/"):
                continue
            return False
        return True

    def head_is_pushed(self) -> bool:
        try:
            upstream = self._run(
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            )
        except ConfigError:
            return False
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", upstream],
            cwd=self.root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    def commit_is_pushed(self, commit: str) -> bool:
        result = self._run("branch", "--remotes", "--contains", commit)
        return any(line.strip().startswith("origin/") for line in result.splitlines())

    def path_exists_at_commit(self, commit: str, path: str) -> bool:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}:{path}"],
            cwd=self.root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    def exclude_treqs_context(self) -> None:
        exclude_token = self._run("rev-parse", "--git-path", "info/exclude")
        exclude_path = Path(exclude_token)
        if not exclude_path.is_absolute():
            exclude_path = self.root / exclude_path
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        patterns = {
            line.strip()
            for line in existing.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        if ".treqs/" in patterns or ".treqs" in patterns:
            return
        separator = "" if not existing or existing.endswith("\n") else "\n"
        with exclude_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{separator}.treqs/\n")

    def _run(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise ConfigError(f"Unable to run Git: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            message = f"git {' '.join(args)} failed"
            raise ConfigError(f"{message}: {detail}" if detail else message)
        return result.stdout.strip()
