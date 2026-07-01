from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

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
    kind: str = "dedicated"
    # For on-demand targets, `type` is the provider (runpod, lambda, aws, gcp, azure).
    type: str = "dedicated"
    instance_type: str | None = None
    region: str = "any"
    install_roar: bool = False
    roar_ref: str | None = None
    userdata_script: str | None = None
    auto_shutdown: bool = False
    idle_timeout_minutes: int | None = None
    description: str | None = None

    def to_api_payload(self) -> dict[str, object]:
        if self.kind != "on-demand":
            return {
                "kind": "dedicated",
                "type": "dedicated",
                "name": self.name,
                "resources": {},
                "costCalculation": {},
            }

        resources: dict[str, object] = {"region": self.region}
        if self.instance_type is not None:
            resources["instanceType"] = self.instance_type
        if self.install_roar:
            resources["installRoar"] = True
        if self.roar_ref is not None:
            resources["roarRef"] = self.roar_ref
        if self.userdata_script is not None:
            resources["userdataScript"] = self.userdata_script

        payload: dict[str, object] = {
            "kind": "on-demand",
            "type": self.type,
            "name": self.name,
            "resources": resources,
            "costCalculation": {},
            "providerConfig": {
                "provider": self.type,
                "instanceType": self.instance_type or "",
                "region": self.region,
            },
        }
        if self.description is not None:
            payload["description"] = self.description
        if self.auto_shutdown:
            payload["autoShutdownEnabled"] = True
        if self.idle_timeout_minutes is not None:
            payload["idleTimeoutMinutes"] = self.idle_timeout_minutes
        return payload


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


def compute_target_rows(
    targets: Sequence[ComputeTarget],
    owner_by_id: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for target in targets:
        row = {
            "id": target.id,
            "name": target.name,
            "kind": target.kind or "",
            "type": target.type,
            "status": target.status or "",
            "agent": _agent_status(target.agent),
        }
        if owner_by_id is not None:
            row["owner"] = owner_by_id.get(target.ownerId or "", target.ownerId or "")
        rows.append(row)
    return rows


def _agent_status(agent: dict[str, Any] | None) -> str:
    if not agent:
        return ""
    status = agent.get("status")
    if status is not None:
        return str(status)
    name = agent.get("name")
    return str(name) if name is not None else "registered"
