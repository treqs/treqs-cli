from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        return datetime.fromisoformat(normalized)
    raise TypeError(f"Expected datetime string, got {type(value).__name__}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AccessUser(BaseModel):
    id: str
    sub: str | None = None
    username: str
    email: str


class AccessOwner(BaseModel):
    id: str
    type: str
    username: str
    display_name: str | None = None
    role: Literal["owner", "admin", "member"]


class AccessProject(BaseModel):
    id: str
    slug: str
    name: str
    visibility: str
    can_write: bool


class AccessContext(BaseModel):
    user: AccessUser
    owners: list[AccessOwner]
    projects_by_owner: dict[str, list[AccessProject]]

    def owner_by_id(self) -> dict[str, AccessOwner]:
        return {owner.id: owner for owner in self.owners}


class DeviceAuthorizationSession(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None = None
    expires_in: float = 600.0
    interval: float = 5.0


class AuthState(BaseModel):
    version: int = 1
    api_url: str
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    token_type: str = "Bearer"
    provider: str | None = None
    user: AccessUser | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("expires_at", "refresh_expires_at", mode="before")
    @classmethod
    def _parse_datetimes(cls, value: Any) -> datetime | None:
        return parse_datetime(value)

    def is_expired(self, *, skew_seconds: int = 300) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= utc_now().astimezone(timezone.utc) + timedelta(
            seconds=skew_seconds
        )

    @classmethod
    def from_token_payload(cls, api_url: str, payload: dict[str, Any]) -> AuthState:
        access_token = _string_value(payload.get("access_token")) or _string_value(
            payload.get("token")
        )
        if not access_token:
            raise ValueError("Token response is missing access_token")

        access_context_payload = payload.get("access_context")
        access_context = (
            AccessContext.model_validate(access_context_payload)
            if isinstance(access_context_payload, dict)
            else None
        )
        user_payload = payload.get("user")
        user = (
            access_context.user
            if access_context is not None
            else AccessUser.model_validate(user_payload)
            if isinstance(user_payload, dict)
            else None
        )
        expires_at = parse_datetime(payload.get("expires_at"))
        if expires_at is None:
            expires_in = _float_value(payload.get("expires_in"))
            if expires_in is not None:
                expires_at = utc_now() + timedelta(seconds=max(expires_in, 0.0))

        return cls(
            version=1,
            api_url=api_url.rstrip("/"),
            access_token=access_token,
            refresh_token=_string_value(payload.get("refresh_token")),
            expires_at=expires_at,
            refresh_expires_at=parse_datetime(payload.get("refresh_expires_at")),
            token_type=_string_value(payload.get("token_type")) or "Bearer",
            provider=_string_value(payload.get("provider")),
            user=user,
        )


class RepoContext(BaseModel):
    api_url: str
    owner_id: str
    owner_type: str
    owner_username: str
    owner_display_name: str | None = None
    project_id: str
    project_slug: str
    project_name: str
    current_username: str
    saved_at: datetime = Field(default_factory=utc_now)

    @field_validator("saved_at", mode="before")
    @classmethod
    def _parse_saved_at(cls, value: Any) -> datetime | None:
        return parse_datetime(value)


def _string_value(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _float_value(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None
