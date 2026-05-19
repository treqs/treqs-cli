from __future__ import annotations

from collections.abc import Mapping

from ..api import TreqsApiClient, ensure_fresh_auth
from ..auth import resolve_api_url
from ..context import TreqsContext
from ..errors import ConfigError
from ..models import AccessContext, AuthState, RepoContext


def load_access_context(state: TreqsContext) -> tuple[AuthState, AccessContext]:
    auth_state = ensure_fresh_auth(
        state.auth_store,
        auth_state_for_request(state, state.auth_store.require()),
    )
    with TreqsApiClient(auth_state.api_url) as client:
        access_context = client.get_access_context(auth_state)
    return auth_state, access_context


def auth_state_for_request(state: TreqsContext, auth_state: AuthState) -> AuthState:
    if state.api_url_override is None:
        return auth_state
    return auth_state.model_copy(update={"api_url": resolve_api_url(state.api_url_override)})


def load_project_api_context(state: TreqsContext) -> tuple[AuthState, RepoContext]:
    require_git_repo(state)
    repo_context = state.repo_context_store.require()
    auth_state = state.auth_store.require()
    api_url = resolve_api_url(state.api_url_override or repo_context.api_url)
    auth_state = ensure_fresh_auth(
        state.auth_store,
        auth_state.model_copy(update={"api_url": api_url}),
    )
    return auth_state, repo_context


def require_git_repo(state: TreqsContext) -> None:
    if state.is_git_repo:
        return
    raise ConfigError(
        "This command requires a git repository for repo-local TReqs project context. "
        "Run it from inside a git repo, or run `git init` first."
    )


def string_field(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)
