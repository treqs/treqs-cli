from __future__ import annotations

import json

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


def test_training_request_methods_use_project_paths_and_payloads() -> None:
    seen_requests: list[tuple[str, str, dict[str, str], object | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        seen_requests.append(
            (
                request.method,
                request.url.path,
                dict(request.url.params.multi_items()),
                body,
            )
        )
        if request.method == "GET" and request.url.path.endswith("/training-requests"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "id": "request-1",
                            "title": "Train model",
                            "status": "draft",
                            "projectSlug": "mnist",
                        }
                    ],
                },
            )
        if request.method == "POST" and request.url.path.endswith("/queue"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "trainingRequest": {
                            "id": "request-1",
                            "title": "Train model",
                            "status": "queued",
                            "projectSlug": "mnist",
                        },
                        "jobId": "job-1",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": "request-1",
                    "title": "Train model",
                    "status": "draft",
                    "projectSlug": "mnist",
                },
            },
        )

    client = TreqsApiClient(
        "https://api.treqs.ai",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")

    listed = client.list_training_requests(
        auth_state,
        "/api/v1/user/projects/mnist/training-requests",
        statuses=("draft", "open"),
        limit=10,
        offset=5,
    )
    created = client.create_training_request(
        auth_state,
        "/api/v1/user/projects/mnist/training-requests",
        {"title": "Train model", "status": "draft"},
    )
    updated = client.update_training_request(
        auth_state,
        "/api/v1/user/projects/mnist/training-requests/request-1",
        {"title": "Updated model"},
    )
    fetched = client.get_training_request(
        auth_state,
        "/api/v1/user/projects/mnist/training-requests/request-1",
    )
    opened = client.open_training_request(
        auth_state,
        "/api/v1/user/projects/mnist/training-requests/request-1/open",
        {"workflowPath": ".github/workflows/train.yml", "computeSelection": {"targetId": "ct-1"}},
    )
    queued = client.queue_training_request(
        auth_state,
        "/api/v1/user/projects/mnist/training-requests/request-1/queue",
    )

    assert listed[0].id == "request-1"
    assert created.id == "request-1"
    assert updated.id == "request-1"
    assert fetched.id == "request-1"
    assert opened.id == "request-1"
    assert queued.jobId == "job-1"
    assert seen_requests == [
        (
            "GET",
            "/api/v1/user/projects/mnist/training-requests",
            {"status": "draft,open", "limit": "10", "offset": "5"},
            None,
        ),
        (
            "POST",
            "/api/v1/user/projects/mnist/training-requests",
            {},
            {"title": "Train model", "status": "draft"},
        ),
        (
            "PATCH",
            "/api/v1/user/projects/mnist/training-requests/request-1",
            {},
            {"title": "Updated model"},
        ),
        (
            "GET",
            "/api/v1/user/projects/mnist/training-requests/request-1",
            {},
            None,
        ),
        (
            "POST",
            "/api/v1/user/projects/mnist/training-requests/request-1/open",
            {},
            {
                "workflowPath": ".github/workflows/train.yml",
                "computeSelection": {"targetId": "ct-1"},
            },
        ),
        (
            "POST",
            "/api/v1/user/projects/mnist/training-requests/request-1/queue",
            {},
            None,
        ),
    ]


def test_compute_and_job_methods_use_owner_project_paths() -> None:
    seen_requests: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(
            (
                request.method,
                request.url.path,
                dict(request.url.params.multi_items()),
            )
        )
        if request.url.path.endswith("/compute-targets"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "id": "ct-1",
                            "name": "GPU",
                            "kind": "dedicated",
                            "type": "dedicated",
                            "status": "active",
                        }
                    ],
                },
            )
        if request.url.path.endswith("/jobs/job-1"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "id": "job-1",
                        "trainingRequestId": "request-1",
                        "projectSlug": "mnist",
                        "computeTargetId": "ct-1",
                        "status": "QUEUED",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "activeJobs": [],
                    "queuedJobs": [
                        {
                            "id": "job-1",
                            "trainingRequestId": "request-1",
                            "projectSlug": "mnist",
                            "computeTargetId": "ct-1",
                            "status": "QUEUED",
                        }
                    ],
                    "finishedJobs": [],
                },
            },
        )

    client = TreqsApiClient(
        "https://api.treqs.ai",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")

    targets = client.list_compute_targets(
        auth_state,
        "/api/v1/user/compute-targets",
        include_agent=True,
    )
    jobs = client.list_project_jobs(
        auth_state,
        "/api/v1/user/projects/mnist/jobs",
        limit=20,
        status="QUEUED",
    )
    job = client.get_project_job(
        auth_state,
        "/api/v1/user/projects/mnist/jobs/job-1",
    )

    assert targets[0].id == "ct-1"
    assert jobs.queuedJobs[0].id == "job-1"
    assert job.id == "job-1"
    assert seen_requests == [
        ("GET", "/api/v1/user/compute-targets", {"include": "agent"}),
        ("GET", "/api/v1/user/projects/mnist/jobs", {"limit": "20", "status": "QUEUED"}),
        ("GET", "/api/v1/user/projects/mnist/jobs/job-1", {}),
    ]


def test_write_surface_methods_use_owner_paths_and_payloads() -> None:
    seen_requests: list[tuple[str, str, dict[str, str], object | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        seen_requests.append(
            (
                request.method,
                request.url.path,
                dict(request.url.params.multi_items()),
                body,
            )
        )
        if request.url.path.endswith("/projects"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "id": "project-1",
                        "slug": "mnist",
                        "name": "MNIST",
                        "visibility": "private",
                    },
                },
            )
        if request.url.path.endswith("/secrets"):
            return httpx.Response(
                200,
                json={"success": True, "data": {"name": "API_KEY"}},
            )
        if request.url.path.endswith("/registration-codes"):
            return httpx.Response(
                201,
                json={"success": True, "data": {"id": "rc-1", "code": "ABC123"}},
            )
        if request.url.path.endswith("/logs/poll"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "chunks": [{"sequence": 3, "content": "log line\n"}],
                        "hasMore": False,
                        "nextSequence": 4,
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": "ct-1",
                    "name": "Dedicated GPU",
                    "kind": "dedicated",
                    "type": "dedicated",
                },
            },
        )

    client = TreqsApiClient(
        "https://api.treqs.ai",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")

    project = client.create_project(
        auth_state,
        "/api/v1/user/orgs/acme/projects",
        {"name": "MNIST", "slug": "mnist", "visibility": "private"},
    )
    target = client.create_compute_target(
        auth_state,
        "/api/v1/user/orgs/acme/compute-targets",
        {
            "kind": "dedicated",
            "type": "dedicated",
            "name": "Dedicated GPU",
            "resources": {},
            "costCalculation": {},
        },
    )
    client.set_compute_target_secret(
        auth_state,
        "/api/v1/user/orgs/acme/compute-targets/ct-1/secrets",
        {"name": "API_KEY", "value": "secret-value"},
    )
    code = client.create_registration_code(
        auth_state,
        "/api/v1/user/orgs/acme/compute-targets/ct-1/agent/registration-codes",
    )
    logs = client.poll_job_logs(
        auth_state,
        "/api/v1/user/orgs/acme/compute-targets/ct-1/jobs/job-1/logs/poll",
        from_sequence=3,
        timeout_ms=15000,
    )

    assert project.id == "project-1"
    assert target.id == "ct-1"
    assert code.code == "ABC123"
    assert logs.chunks[0].content == "log line\n"
    assert logs.nextSequence == 4
    assert seen_requests == [
        (
            "POST",
            "/api/v1/user/orgs/acme/projects",
            {},
            {"name": "MNIST", "slug": "mnist", "visibility": "private"},
        ),
        (
            "POST",
            "/api/v1/user/orgs/acme/compute-targets",
            {},
            {
                "kind": "dedicated",
                "type": "dedicated",
                "name": "Dedicated GPU",
                "resources": {},
                "costCalculation": {},
            },
        ),
        (
            "PUT",
            "/api/v1/user/orgs/acme/compute-targets/ct-1/secrets",
            {},
            {"name": "API_KEY", "value": "secret-value"},
        ),
        (
            "POST",
            "/api/v1/user/orgs/acme/compute-targets/ct-1/agent/registration-codes",
            {},
            None,
        ),
        (
            "GET",
            "/api/v1/user/orgs/acme/compute-targets/ct-1/jobs/job-1/logs/poll",
            {"from": "3", "timeout": "15000"},
            None,
        ),
    ]


def test_poll_job_logs_raises_http_timeout_above_poll_timeout() -> None:
    seen_timeouts: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(request.extensions.get("timeout", {}).get("read"))
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {"chunks": [], "hasMore": False, "nextSequence": 0},
            },
        )

    client = TreqsApiClient(
        "https://api.treqs.ai",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")

    client.poll_job_logs(
        auth_state,
        "/api/v1/user/compute-targets/ct-1/jobs/job-1/logs/poll",
        from_sequence=0,
        timeout_ms=30000,
    )

    # HTTP read timeout must sit safely above the 30s server-side long-poll timeout.
    assert seen_timeouts[0] is not None
    assert seen_timeouts[0] > 30.0


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
