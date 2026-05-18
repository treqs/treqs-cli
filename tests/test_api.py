from __future__ import annotations

import httpx

from treqs_cli.api import TreqsApiClient
from treqs_cli.models import AccessUser, AuthState


def test_device_login_retries_pending_then_returns_auth_state() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/auth/device/start":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "device_code": "device-1",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://treqs.ai/device",
                        "verification_uri_complete": "https://treqs.ai/device?user_code=ABCD-EFGH",
                        "expires_in": 600,
                        "interval": 1,
                    },
                },
            )
        if (
            request.url.path == "/api/v1/auth/device/token"
            and calls.count("/api/v1/auth/device/token") == 1
        ):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"status": "authorization_pending", "interval": 1},
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "status": "approved",
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_at": "2030-01-01T00:00:00.000Z",
                    "token_type": "Bearer",
                    "provider": "github",
                    "access_context": _access_context_payload(),
                },
            },
        )

    client = TreqsApiClient(
        "https://api.treqs.ai",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    session = client.start_device_authorization()
    auth_state = client.poll_device_token(session, sleep=lambda _seconds: None)

    assert auth_state.access_token == "access-token"
    assert auth_state.refresh_token == "refresh-token"
    assert auth_state.user is not None
    assert auth_state.user.username == "trevor"


def test_device_login_handles_oauth_poll_errors() -> None:
    token_calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/api/v1/auth/device/start":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "device_code": "device-1",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://treqs.ai/device",
                        "expires_in": 600,
                        "interval": 1,
                    },
                },
            )
        token_calls += 1
        if token_calls == 1:
            return httpx.Response(
                400,
                json={
                    "success": False,
                    "error": {
                        "code": "authorization_pending",
                        "message": "authorization pending",
                    },
                },
            )
        if token_calls == 2:
            return httpx.Response(
                400,
                json={
                    "success": False,
                    "error": {"code": "slow_down", "message": "slow down"},
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "status": "approved",
                    "access_token": "access-token",
                    "expires_in": 3600,
                    "access_context": _access_context_payload(),
                },
            },
        )

    client = TreqsApiClient(
        "https://api.treqs.ai",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    session = client.start_device_authorization()
    auth_state = client.poll_device_token(session, sleep=lambda seconds: sleeps.append(seconds))

    assert auth_state.access_token == "access-token"
    assert sleeps == [1.0, 6.0]


def test_get_access_context_uses_bearer_auth() -> None:
    seen_authorization: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"success": True, "data": _access_context_payload()})

    client = TreqsApiClient(
        "https://api.treqs.ai",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    context = client.get_access_context(
        AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    )

    assert context.user.username == "trevor"
    assert seen_authorization == ["Bearer access-token"]


def test_get_access_context_falls_back_to_legacy_user_endpoint() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/api/v1/auth/access-context":
            return httpx.Response(
                404,
                json={"success": False, "error": {"message": "not found"}},
            )
        return httpx.Response(200, json={"success": True, "data": _access_context_payload()})

    client = TreqsApiClient(
        "https://api.treqs.ai",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    context = client.get_access_context(
        AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    )

    assert context.user.username == "trevor"
    assert seen_paths == ["/api/v1/auth/access-context", "/api/v1/user/access-context"]


def test_refresh_auth_preserves_existing_session_fields_when_response_is_sparse() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "access_token": "fresh-token",
                    "expires_in": 3600,
                },
            },
        )

    client = TreqsApiClient(
        "https://api.treqs.ai",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    refreshed = client.refresh_auth(
        AuthState(
            api_url="https://api.treqs.ai",
            access_token="stale-token",
            refresh_token="refresh-token",
            provider="github",
            user=AccessUser(
                id="user-1",
                sub="sub-1",
                username="trevor",
                email="trevor@example.com",
            ),
        )
    )

    assert refreshed.access_token == "fresh-token"
    assert refreshed.refresh_token == "refresh-token"
    assert refreshed.provider == "github"
    assert refreshed.user is not None
    assert refreshed.user.username == "trevor"


def _access_context_payload() -> dict[str, object]:
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
            }
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
            ]
        },
    }
