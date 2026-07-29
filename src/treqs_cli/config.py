from __future__ import annotations

import json
import os
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

import tomli_w

from .errors import AuthError, ConfigError
from .models import AuthState, RepoContext

DEFAULT_API_URL = "https://api.treqs.ai"


@dataclass(frozen=True)
class RepoDiscovery:
    root: Path
    is_git_repo: bool


def config_home() -> Path:
    override = os.environ.get("TREQS_CONFIG_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "treqs"
    return Path(user_config_dir("treqs", "TReqs"))


def auth_state_path() -> Path:
    return config_home() / "auth.json"


class AuthStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or auth_state_path()

    def load(self) -> AuthState | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AuthError(f"Stored auth state is not valid JSON: {self.path}") from exc
        if not isinstance(payload, dict):
            raise AuthError(f"Stored auth state must be a JSON object: {self.path}")
        return AuthState.model_validate(payload)

    def require(self) -> AuthState:
        state = self.load()
        if state is None:
            raise AuthError("Not logged in. Run `treqs login` first.")
        return state

    def save(self, state: AuthState) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = state.model_dump(mode="json", exclude_none=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(content)
            with suppress(OSError):
                tmp_path.chmod(0o600)
            tmp_path.replace(self.path)
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp_path.exists():
                with suppress(OSError):
                    tmp_path.unlink()
        return self.path

    def delete(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True


def discover_repo_root(start: Path | None = None) -> RepoDiscovery:
    current = (start or Path.cwd()).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=current,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            return RepoDiscovery(root=Path(out).resolve(), is_git_repo=True)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return RepoDiscovery(root=candidate, is_git_repo=True)
    return RepoDiscovery(root=current, is_git_repo=False)


def current_branch(repo_root: Path) -> str | None:
    """Current checked-out git branch, or None if detached/unresolvable.

    Mirrors roar's `git rev-parse --abbrev-ref HEAD` VCS detection, except a
    detached HEAD (which that command reports literally as `"HEAD"`) is
    treated as unknown rather than recorded as a fake branch name.
    """
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return out if out and out != "HEAD" else None


def find_repo_root(start: Path | None = None) -> Path:
    return discover_repo_root(start).root


def repo_config_path(start: Path | None = None) -> Path:
    return find_repo_root(start) / ".treqs" / "config.toml"


class RepoContextStore:
    def __init__(self, path: Path | None = None, *, start: Path | None = None) -> None:
        self.path = path or repo_config_path(start)

    def load(self) -> RepoContext | None:
        if not self.path.exists():
            return None
        try:
            with self.path.open("rb") as handle:
                payload = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Repo context is not valid TOML: {self.path}") from exc

        context_payload = payload.get("context")
        if not isinstance(context_payload, dict):
            return None
        return RepoContext.model_validate(context_payload)

    def require(self) -> RepoContext:
        context = self.load()
        if context is None:
            raise ConfigError(
                "No TReqs project context. Run `treqs project use <owner>/<project>`."
            )
        return context

    def save(self, context: RepoContext) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"context": context.model_dump(mode="json", exclude_none=True)}
        self.path.write_text(tomli_w.dumps(payload), encoding="utf-8")
        return self.path

    def clear(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True
