from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

_SECRET_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ComputeTarget(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    type: str
    kind: str | None = None
    status: str | None = None
    ownerId: str | None = None
    hasQueue: bool | None = None
    agent: dict[str, Any] | None = None


class ComputeTargetCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["dedicated"] = "dedicated"

    def to_api_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "type": "dedicated",
            "name": self.name,
            "resources": {},
            "costCalculation": {},
        }


class SecretInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str

    def to_api_payload(self) -> dict[str, object]:
        return {"name": self.name, "value": self.value}


class RegistrationCode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    code: str
    computeTargetId: str | None = None
    expiresAt: str | None = None
    createdAt: str | None = None


def validate_secret_name(name: str) -> str:
    token = name.strip()
    if not token:
        raise ValueError("Secret name cannot be empty.")
    if not _SECRET_NAME_PATTERN.match(token):
        raise ValueError(
            f"Invalid secret name: {name}. Names must be uppercase letters, numbers, and "
            "underscores, and start with a letter (^[A-Z][A-Z0-9_]*$)."
        )
    return token


def parse_secret_assignment(assignment: str) -> SecretInput:
    name, separator, value = assignment.partition("=")
    if not separator:
        raise ValueError(f"Invalid secret assignment: {assignment}. Use KEY=VALUE.")
    validated_name = validate_secret_name(name)
    if not value:
        raise ValueError(f"Secret {validated_name} requires a non-empty value.")
    return SecretInput(name=validated_name, value=value)


def compute_target_rows(targets: Sequence[ComputeTarget]) -> list[dict[str, str]]:
    return [
        {
            "id": target.id,
            "name": target.name,
            "kind": target.kind or "",
            "type": target.type,
            "status": target.status or "",
            "agent": _agent_status(target.agent),
        }
        for target in targets
    ]


def _agent_status(agent: dict[str, Any] | None) -> str:
    if not agent:
        return ""
    status = agent.get("status")
    if status is not None:
        return str(status)
    name = agent.get("name")
    return str(name) if name is not None else "registered"
