from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import AuthStore, RepoContextStore, find_repo_root
from .errors import ConfigError
from .models import AccessContext, AccessOwner, AccessProject, AuthState, RepoContext


@dataclass
class TreqsContext:
    """Shared Click context for a single treqs invocation."""

    api_url_override: str | None
    json_output: bool
    auth_store: AuthStore
    repo_context_store: RepoContextStore
    cwd: Path
    repo_root: Path
    is_interactive: bool

    @classmethod
    def create(
        cls,
        *,
        api_url_override: str | None,
        json_output: bool,
        cwd: Path | None = None,
    ) -> TreqsContext:
        resolved_cwd = (cwd or Path.cwd()).resolve()
        repo_root = find_repo_root(resolved_cwd)
        return cls(
            api_url_override=api_url_override,
            json_output=json_output,
            auth_store=AuthStore(),
            repo_context_store=RepoContextStore(start=resolved_cwd),
            cwd=resolved_cwd,
            repo_root=repo_root,
            is_interactive=sys.stdin.isatty(),
        )


def normalize_owner(value: str) -> str:
    return value.strip().removeprefix("@").lower()


def owner_base_path(owner: str, current_username: str | None) -> str:
    normalized = normalize_owner(owner)
    if current_username and normalized == normalize_owner(current_username):
        return "/api/v1/user"
    return f"/api/v1/user/orgs/{normalized}"


def owner_path(owner: str, current_username: str | None, subpath: str) -> str:
    normalized_subpath = subpath if subpath.startswith("/") else f"/{subpath}"
    return f"{owner_base_path(owner, current_username)}{normalized_subpath}"


def resolve_project_selection(
    access_context: AccessContext,
    selection: str,
) -> tuple[AccessOwner, AccessProject]:
    normalized = selection.strip()
    if not normalized:
        raise ConfigError("Project selection cannot be empty.")

    owner_token: str | None
    project_token: str
    if "/" in normalized:
        owner_token, project_token = normalized.split("/", 1)
        owner_token = normalize_owner(owner_token)
    else:
        owner_token = None
        project_token = normalized
    project_token = normalize_owner(project_token)

    matches: list[tuple[AccessOwner, AccessProject]] = []
    owners_by_id = access_context.owner_by_id()
    for owner_id, projects in access_context.projects_by_owner.items():
        owner = owners_by_id.get(owner_id)
        if owner is None:
            continue
        if owner_token is not None and not _owner_matches(owner, owner_token):
            continue
        for project in projects:
            if _project_matches(project, project_token):
                matches.append((owner, project))

    if not matches:
        raise ConfigError(f"Project not found in access context: {selection}")
    if len(matches) > 1:
        raise ConfigError(f"Project selection is ambiguous: {selection}. Use <owner>/<project>.")
    owner, project = matches[0]
    if not project.can_write:
        scope = project_scope(owner, project)
        raise ConfigError(f"Project is visible but not writable in TReqs access context: {scope}")
    return owner, project


def build_repo_context(
    *,
    auth_state: AuthState,
    access_context: AccessContext,
    owner: AccessOwner,
    project: AccessProject,
) -> RepoContext:
    return RepoContext(
        api_url=auth_state.api_url,
        owner_id=owner.id,
        owner_type=owner.type,
        owner_username=owner.username,
        owner_display_name=owner.display_name,
        project_id=project.id,
        project_slug=project.slug,
        project_name=project.name,
        current_username=access_context.user.username,
    )


def project_scope(owner: AccessOwner, project: AccessProject) -> str:
    return f"{owner.username}/{project.slug}"


def _owner_matches(owner: AccessOwner, token: str) -> bool:
    candidates = {
        normalize_owner(owner.username),
        normalize_owner(owner.id),
    }
    if owner.display_name:
        candidates.add(normalize_owner(owner.display_name))
        slug = _slugify(owner.display_name)
        if slug:
            candidates.add(slug)
    return token in candidates


def _project_matches(project: AccessProject, token: str) -> bool:
    candidates = {
        normalize_owner(project.slug),
        normalize_owner(project.id),
        normalize_owner(project.name),
    }
    slug = _slugify(project.name)
    if slug:
        candidates.add(slug)
    return token in candidates


def _slugify(value: str) -> str | None:
    normalized = normalize_owner(value)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or None
