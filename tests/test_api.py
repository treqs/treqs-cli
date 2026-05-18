from __future__ import annotations

import httpx

from treqs_cli.api import TreqsApiClient
from treqs_cli.models import AuthState


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
