from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, cast

import httpx

from .application.compute.models import (
    AwsLaunchOptions,
    ComputeTarget,
    RegistrationCode,
    SecretMetadata,
)
from .application.jobs.models import (
    JobUpdates,
    LineageRepublishResult,
    LogPollResult,
    ProjectJobs,
    TrainingJob,
)
from .application.projects.models import Project
from .application.requests.models import (
    TrainingRequest,
    TrainingRequestEvent,
    TrainingRequestQueueResult,
    TrainingRequestReviewResult,
)
from .errors import ApiError, AuthError
from .models import AccessContext, AuthState, DeviceAuthorizationSession


class TreqsApiClient:
    def __init__(self, api_url: str, http_client: httpx.Client | None = None) -> None:
        self.api_url = api_url.rstrip("/")
        self._client = http_client or httpx.Client(timeout=30.0)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> TreqsApiClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def start_device_authorization(self) -> DeviceAuthorizationSession:
        payload = self.request_json(
            "POST",
            "/api/v1/auth/device/start",
            json_payload={"client_id": "treqs-cli", "client_name": "treqs-cli"},
        )
        return DeviceAuthorizationSession.model_validate(_unwrap_data(payload))

    def poll_device_token(
        self,
        session: DeviceAuthorizationSession,
        *,
        sleep: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> AuthState:
        deadline = time_fn() + max(session.expires_in, 1.0)
        interval = max(session.interval, 0.0)

        while time_fn() < deadline:
            try:
                payload = self.request_json(
                    "POST",
                    "/api/v1/auth/device/token",
                    json_payload={
                        "device_code": session.device_code,
                        "client_id": "treqs-cli",
                    },
                )
            except ApiError as exc:
                interval = _handle_device_poll_error(exc, interval=interval, sleep=sleep)
                continue
            data = _unwrap_data(payload)
            status = data.get("status")
            if status == "authorization_pending":
                interval = _float_value(data.get("interval"), default=interval)
                sleep(interval)
                continue
            if status == "slow_down":
                interval = _float_value(data.get("interval"), default=interval + 5.0)
                sleep(interval)
                continue
            if status == "expired_token":
                raise AuthError("Device authorization expired. Run `treqs login` again.")
            if status == "access_denied":
                raise AuthError("Device authorization was denied.")
            if status not in {None, "approved"}:
                raise AuthError(f"Unexpected device authorization status: {status}")
            try:
                return AuthState.from_token_payload(self.api_url, data)
            except ValueError as exc:
                raise AuthError(str(exc)) from exc

        raise AuthError("Device authorization timed out before approval completed.")

    def refresh_auth(self, auth_state: AuthState) -> AuthState:
        if not auth_state.refresh_token:
            raise AuthError("Session expired and no refresh token is available. Run `treqs login`.")
        payload = self.request_json(
            "POST",
            "/api/v1/auth/refresh",
            json_payload={"refresh_token": auth_state.refresh_token, "client_id": "treqs-cli"},
        )
        try:
            refreshed = AuthState.from_token_payload(self.api_url, _unwrap_data(payload))
        except ValueError as exc:
            raise AuthError(str(exc)) from exc
        return refreshed.model_copy(
            update={
                "refresh_token": refreshed.refresh_token or auth_state.refresh_token,
                "refresh_expires_at": refreshed.refresh_expires_at or auth_state.refresh_expires_at,
                "provider": refreshed.provider or auth_state.provider,
                "user": refreshed.user or auth_state.user,
            }
        )

    def logout(self, auth_state: AuthState) -> None:
        self.request_json(
            "POST",
            "/api/v1/auth/logout",
            auth_state=auth_state,
        )

    def get_access_context(self, auth_state: AuthState) -> AccessContext:
        try:
            payload = self.request_json("GET", "/api/v1/auth/access-context", auth_state=auth_state)
        except ApiError as exc:
            if exc.status_code != 404:
                raise
            payload = self.request_json("GET", "/api/v1/user/access-context", auth_state=auth_state)
        return AccessContext.model_validate(_unwrap_data(payload))

    def list_training_requests(
        self,
        auth_state: AuthState,
        path: str,
        *,
        statuses: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TrainingRequest]:
        params: dict[str, Any] = {}
        if statuses:
            params["status"] = ",".join(statuses)
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        payload = self.request_json(
            "GET",
            path,
            auth_state=auth_state,
            params=params or None,
        )
        return [TrainingRequest.model_validate(item) for item in _unwrap_list_data(payload)]

    def create_training_request(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequest:
        payload = self.request_json(
            "POST",
            path,
            auth_state=auth_state,
            json_payload=json_payload,
        )
        return TrainingRequest.model_validate(_unwrap_data(payload))

    def update_training_request(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequest:
        payload = self.request_json(
            "PATCH",
            path,
            auth_state=auth_state,
            json_payload=json_payload,
        )
        return TrainingRequest.model_validate(_unwrap_data(payload))

    def get_training_request(
        self,
        auth_state: AuthState,
        path: str,
    ) -> TrainingRequest:
        payload = self.request_json(
            "GET",
            path,
            auth_state=auth_state,
            params={"include": "assignees,reviews"},
        )
        return TrainingRequest.model_validate(_unwrap_data(payload))

    def add_training_request_comment(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequestEvent:
        payload = self.request_json(
            "POST",
            path,
            auth_state=auth_state,
            json_payload=json_payload,
        )
        return TrainingRequestEvent.model_validate(_unwrap_data(payload))

    def open_training_request(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequest:
        payload = self.request_json(
            "POST",
            path,
            auth_state=auth_state,
            json_payload=json_payload,
        )
        return TrainingRequest.model_validate(_unwrap_data(payload))

    def queue_training_request(
        self,
        auth_state: AuthState,
        path: str,
    ) -> TrainingRequestQueueResult:
        payload = self.request_json("POST", path, auth_state=auth_state)
        return TrainingRequestQueueResult.model_validate(_unwrap_data(payload))

    def submit_training_request_review(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> TrainingRequestReviewResult:
        payload = self.request_json(
            "POST",
            path,
            auth_state=auth_state,
            json_payload=json_payload,
        )
        return TrainingRequestReviewResult.model_validate(_unwrap_data(payload))

    def create_project(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> Project:
        payload = self.request_json(
            "POST",
            path,
            auth_state=auth_state,
            json_payload=json_payload,
        )
        return Project.model_validate(_unwrap_data(payload))

    def get_project(
        self,
        auth_state: AuthState,
        path: str,
    ) -> Project:
        payload = self.request_json("GET", path, auth_state=auth_state)
        return Project.model_validate(_unwrap_data(payload))

    def list_compute_targets(
        self,
        auth_state: AuthState,
        path: str,
        *,
        include_agent: bool = False,
    ) -> list[ComputeTarget]:
        params = {"include": "agent"} if include_agent else None
        payload = self.request_json("GET", path, auth_state=auth_state, params=params)
        return [ComputeTarget.model_validate(item) for item in _unwrap_list_data(payload)]

    def create_compute_target(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> ComputeTarget:
        payload = self.request_json(
            "POST",
            path,
            auth_state=auth_state,
            json_payload=json_payload,
        )
        return ComputeTarget.model_validate(_unwrap_data(payload))

    def get_provider_launch_options(
        self,
        auth_state: AuthState,
        path: str,
        *,
        region: str,
    ) -> AwsLaunchOptions:
        payload = self.request_json(
            "GET",
            path,
            auth_state=auth_state,
            params={"region": region},
        )
        return AwsLaunchOptions.model_validate(_unwrap_data(payload))

    def set_compute_target_secret(
        self,
        auth_state: AuthState,
        path: str,
        json_payload: dict[str, object],
    ) -> None:
        payload = self.request_json(
            "PUT",
            path,
            auth_state=auth_state,
            json_payload=json_payload,
        )
        if payload.get("success") is not True:
            raise ApiError(_error_message(payload, None))

    def list_compute_target_secrets(
        self,
        auth_state: AuthState,
        path: str,
    ) -> list[SecretMetadata]:
        payload = self.request_json("GET", path, auth_state=auth_state)
        return [SecretMetadata.model_validate(item) for item in _unwrap_list_data(payload)]

    def delete_compute_target_secret(
        self,
        auth_state: AuthState,
        path: str,
    ) -> None:
        # The API returns 204 No Content on success (no "success"/"data" envelope),
        # which request_json's 204 short-circuit turns into {"success": True}.
        payload = self.request_json("DELETE", path, auth_state=auth_state)
        if payload.get("success") is not True:
            raise ApiError(_error_message(payload, None))

    def create_registration_code(
        self,
        auth_state: AuthState,
        path: str,
    ) -> RegistrationCode:
        payload = self.request_json("POST", path, auth_state=auth_state)
        return RegistrationCode.model_validate(_unwrap_data(payload))

    def list_project_jobs(
        self,
        auth_state: AuthState,
        path: str,
        *,
        limit: int,
        status: str | None = None,
    ) -> ProjectJobs:
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        payload = self.request_json(
            "GET",
            path,
            auth_state=auth_state,
            params=params,
        )
        return ProjectJobs.model_validate(_unwrap_data(payload))

    def get_project_job(
        self,
        auth_state: AuthState,
        path: str,
    ) -> TrainingJob:
        payload = self.request_json("GET", path, auth_state=auth_state)
        return TrainingJob.model_validate(_unwrap_data(payload))

    def poll_job_updates(
        self,
        auth_state: AuthState,
        path: str,
        *,
        cursor: str | None,
        timeout_ms: int,
    ) -> JobUpdates:
        params: dict[str, Any] = {"timeout": timeout_ms}
        if cursor is not None:
            params["cursor"] = cursor
        payload = self.request_json(
            "GET",
            path,
            auth_state=auth_state,
            params=params,
            timeout=timeout_ms / 1000.0 + 15.0,
        )
        return JobUpdates.model_validate(_unwrap_data(payload))

    def republish_job_lineage(
        self,
        auth_state: AuthState,
        path: str,
    ) -> LineageRepublishResult:
        payload = self.request_json("POST", path, auth_state=auth_state)
        return LineageRepublishResult.model_validate(_unwrap_data(payload))

    def cancel_job(
        self,
        auth_state: AuthState,
        path: str,
    ) -> TrainingJob:
        payload = self.request_json("POST", path, auth_state=auth_state)
        return TrainingJob.model_validate(_unwrap_data(payload))

    def poll_job_logs(
        self,
        auth_state: AuthState,
        path: str,
        *,
        from_sequence: int,
        timeout_ms: int,
    ) -> LogPollResult:
        # Keep the HTTP read timeout safely above the server-side long-poll timeout so
        # the request does not abort before the API returns.
        http_timeout = timeout_ms / 1000.0 + 15.0
        payload = self.request_json(
            "GET",
            path,
            auth_state=auth_state,
            params={"from": from_sequence, "timeout": timeout_ms},
            timeout=http_timeout,
        )
        return LogPollResult.model_validate(_unwrap_data(payload))

    def request_json(
        self,
        method: str,
        path: str,
        *,
        auth_state: AuthState | None = None,
        json_payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if auth_state is not None:
            token_type = auth_state.token_type or "Bearer"
            headers["Authorization"] = f"{token_type} {auth_state.access_token}"

        request_kwargs: dict[str, Any] = {}
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        try:
            response = self._client.request(
                method,
                f"{self.api_url}{path}",
                json=json_payload,
                params=params,
                headers=headers,
                **request_kwargs,
            )
        except httpx.HTTPError as exc:
            raise ApiError(f"Failed to connect to TReqs API: {exc}") from exc

        if response.status_code == 204:
            # No Content has no body to parse; treat it as an implicit success envelope
            # so callers can use the same payload.get("success") check as everywhere else.
            return {"success": True}

        payload = _response_payload(response)
        if response.status_code >= 400:
            error_code, message = _error_details(payload)
            raise ApiError(
                message or f"TReqs API request failed with HTTP {response.status_code}",
                status_code=response.status_code,
                error_code=error_code,
                payload=payload,
            )
        if not isinstance(payload, dict):
            raise ApiError("TReqs API returned a non-object JSON response.")
        return payload


def ensure_fresh_auth(auth_store: Any, auth_state: AuthState) -> AuthState:
    if not auth_state.is_expired():
        return auth_state
    with TreqsApiClient(auth_state.api_url) as client:
        refreshed = client.refresh_auth(auth_state)
    auth_store.save(refreshed)
    return refreshed


def _handle_device_poll_error(
    exc: ApiError,
    *,
    interval: float,
    sleep: Callable[[float], None],
) -> float:
    if exc.error_code == "authorization_pending":
        sleep(interval)
        return interval
    if exc.error_code == "slow_down":
        slowed_interval = interval + 5.0
        sleep(slowed_interval)
        return slowed_interval
    if exc.error_code == "expired_token":
        raise AuthError("Device authorization expired. Run `treqs login` again.") from exc
    if exc.error_code == "access_denied":
        raise AuthError(str(exc) or "Device authorization was denied.") from exc
    raise exc


def _response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ApiError(
            f"TReqs API returned non-JSON response with status {response.status_code}",
            status_code=response.status_code,
        ) from exc


def _unwrap_data(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("success") is not True:
        raise ApiError(_error_message(payload, None))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ApiError("TReqs API response is missing object data.")
    return data


def _unwrap_list_data(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("success") is not True:
        raise ApiError(_error_message(payload, None))
    data = payload.get("data")
    if not isinstance(data, list):
        raise ApiError("TReqs API response is missing list data.")
    items: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ApiError("TReqs API list response contains a non-object item.")
        items.append(cast(dict[str, Any], item))
    return items


def _error_message(payload: Any, status_code: int | None) -> str:
    _error_code, message = _error_details(payload)
    if message:
        return message
    if status_code is not None:
        return f"TReqs API request failed with HTTP {status_code}"
    return "TReqs API request failed"


def _error_details(payload: Any) -> tuple[str | None, str | None]:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            return (
                code.strip() if isinstance(code, str) and code.strip() else None,
                message.strip() if isinstance(message, str) and message.strip() else None,
            )
    return None, None


def _float_value(value: Any, *, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    return default
