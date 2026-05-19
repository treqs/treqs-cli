from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict


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
