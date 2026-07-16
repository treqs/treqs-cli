from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

ProjectVisibility = Literal["public", "private"]
PROJECT_VISIBILITIES: tuple[ProjectVisibility, ...] = ("public", "private")

GitHubAccessMode = Literal["public", "github_app"]

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


class CodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["github"] = "github"
    repositoryUrl: str
    fullName: str
    defaultBranch: str = "main"
    accessMode: GitHubAccessMode = "public"

    def to_api_payload(self) -> dict[str, object]:
        return {
            "type": self.type,
            "repositoryUrl": self.repositoryUrl,
            "fullName": self.fullName,
            "defaultBranch": self.defaultBranch,
            "accessMode": self.accessMode,
        }


class ProjectCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str
    visibility: ProjectVisibility = "private"
    description: str | None = None
    code_config: CodeConfig | None = None

    def to_api_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "slug": self.slug,
            "visibility": self.visibility,
        }
        if self.description is not None:
            payload["description"] = self.description
        if self.code_config is not None:
            payload["codeConfig"] = self.code_config.to_api_payload()
        return payload


class Project(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    slug: str
    name: str
    visibility: str | None = None
    description: str | None = None
    ownerId: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


def slugify_name(name: str) -> str:
    normalized = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug


def validate_slug(slug: str) -> str:
    token = slug.strip()
    if not token:
        raise ValueError("Project slug cannot be empty.")
    if len(token) > 100:
        raise ValueError("Project slug must be less than 100 characters.")
    if not _SLUG_PATTERN.match(token):
        raise ValueError("Project slug must contain only lowercase letters, numbers, and hyphens.")
    return token


def parse_code_config(
    spec: str,
    *,
    access_mode: GitHubAccessMode = "public",
    default_branch: str = "main",
) -> CodeConfig:
    token = spec.strip()
    provider, _, remainder = token.partition(":")
    provider = provider.strip().lower()
    remainder = remainder.strip()
    if provider != "github":
        raise ValueError(
            f"Unsupported code config provider: {provider or spec}. Use 'github:<url>'."
        )
    if not remainder:
        raise ValueError("Code config requires a repository URL, for example github:<url>.")

    repository_url, full_name = _normalize_github_url(remainder)
    return CodeConfig(
        type="github",
        repositoryUrl=repository_url,
        fullName=full_name,
        defaultBranch=default_branch,
        accessMode=access_mode,
    )


def _normalize_github_url(value: str) -> tuple[str, str]:
    candidate = value
    if not candidate.startswith(("http://", "https://")):
        candidate = candidate.removeprefix("github.com/")
        candidate = f"https://github.com/{candidate}"

    parsed = urlparse(candidate)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid GitHub repository URL: {value}")

    path = parsed.path.strip("/")
    path = path.removesuffix(".git")
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        raise ValueError(
            f"GitHub repository URL must include owner and repo, for example "
            f"https://github.com/owner/repo: {value}"
        )
    owner, repo = segments[0], segments[1]
    full_name = f"{owner}/{repo}"
    repository_url = f"https://{parsed.netloc}/{full_name}"
    return repository_url, full_name
