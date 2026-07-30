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
    startupBehavior: str | None = None
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
    # AWS-specific (see aws-provider.ts's AwsResources): amiId is required for AWS
    # launches; subnet/security-group/ssh-key are optional (AWS falls back to
    # account/VPC defaults when unset).
    ami_id: str | None = None
    # Ordered AZ candidates; first is primary, the rest are fallback subnets tried
    # in turn on a per-AZ capacity error (mirrors resources.subnetIds).
    subnet_ids: tuple[str, ...] = ()
    security_group_ids: tuple[str, ...] = ()
    ssh_key_name: str | None = None

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
        if self.ami_id is not None:
            resources["amiId"] = self.ami_id
        if self.subnet_ids:
            resources["subnetIds"] = list(self.subnet_ids)
        if self.security_group_ids:
            resources["securityGroupIds"] = list(self.security_group_ids)
        if self.ssh_key_name is not None:
            resources["sshKeyName"] = self.ssh_key_name

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


class AwsAmiOption(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str | None = None
    architecture: str | None = None
    creationDate: str | None = None


class AwsSubnetOption(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None
    vpcId: str
    availabilityZone: str
    cidrBlock: str | None = None
    isDefault: bool | None = None
    availableIpAddressCount: int | None = None


class AwsSecurityGroupOption(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str | None = None
    vpcId: str | None = None


class AwsLaunchOptions(BaseModel):
    model_config = ConfigDict(extra="allow")

    amis: list[AwsAmiOption] = []
    subnets: list[AwsSubnetOption] = []
    securityGroups: list[AwsSecurityGroupOption] = []
    # Per-resource discovery failures (e.g. missing ec2:DescribeSubnets permission).
    # An empty list with no entry here means the account genuinely has none of
    # that resource in the region, not that discovery failed.
    errors: dict[str, str] | None = None


class SecretInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str

    def to_api_payload(self) -> dict[str, object]:
        return {"name": self.name, "value": self.value}


class SecretMetadata(BaseModel):
    """Compute target secret metadata. The API never returns the secret value itself."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    createdAt: str | None = None
    updatedAt: str | None = None
    createdBy: str | None = None
    updatedBy: str | None = None
    createdByUsername: str | None = None
    updatedByUsername: str | None = None


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


def secret_rows(secrets: Sequence[SecretMetadata]) -> list[dict[str, str]]:
    return [
        {
            "name": secret.name,
            "createdAt": secret.createdAt or "",
            "updatedAt": secret.updatedAt or "",
            "createdBy": secret.createdByUsername or secret.createdBy or "",
            "updatedBy": secret.updatedByUsername or secret.updatedBy or "",
        }
        for secret in secrets
    ]


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
