from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

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
            payload = self.request_json(
                "POST",
                "/api/v1/auth/device/token",
                json_payload={"device_code": session.device_code},
            )
            data = _unwrap_data(payload)
            status = data.get("status")
            if status == "authorization_pending":
                interval = _float_value(data.get("interval"), default=interval)
                sleep(interval)
                continue
            if status not in {None, "approved"}:
                raise AuthError(f"Unexpected device authorization status: {status}")
            return AuthState.from_token_payload(self.api_url, data)

        raise AuthError("Device authorization timed out before approval completed.")

    def refresh_auth(self, auth_state: AuthState) -> AuthState:
        if not auth_state.refresh_token:
            raise AuthError("Session expired and no refresh token is available. Run `treqs login`.")
        payload = self.request_json(
            "POST",
            "/api/v1/auth/refresh",
            json_payload={"refresh_token": auth_state.refresh_token},
        )
        return AuthState.from_token_payload(self.api_url, _unwrap_data(payload))

    def logout(self, auth_state: AuthState) -> None:
        self.request_json(
            "POST",
            "/api/v1/auth/logout",
            auth_state=auth_state,
        )

    def get_access_context(self, auth_state: AuthState) -> AccessContext:
        payload = self.request_json("GET", "/api/v1/user/access-context", auth_state=auth_state)
        return AccessContext.model_validate(_unwrap_data(payload))

    def request_json(
        self,
        method: str,
        path: str,
        *,
        auth_state: AuthState | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if auth_state is not None:
            token_type = auth_state.token_type or "Bearer"
            headers["Authorization"] = f"{token_type} {auth_state.access_token}"

        try:
            response = self._client.request(
                method,
                f"{self.api_url}{path}",
                json=json_payload,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ApiError(f"Failed to connect to TReqs API: {exc}") from exc

        payload = _response_payload(response)
        if response.status_code >= 400:
            raise ApiError(
                _error_message(payload, response.status_code),
                status_code=response.status_code,
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


def _error_message(payload: Any, status_code: int | None) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    if status_code is not None:
        return f"TReqs API request failed with HTTP {status_code}"
    return "TReqs API request failed"


def _float_value(value: Any, *, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    return default
