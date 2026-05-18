from __future__ import annotations


class TreqsCliError(RuntimeError):
    """Base class for user-facing CLI errors."""


class ApiError(TreqsCliError):
    """Raised when treqs-api returns an error response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class AuthError(TreqsCliError):
    """Raised when auth state is missing, expired, or invalid."""


class ConfigError(TreqsCliError):
    """Raised when local or global CLI config cannot be read."""
