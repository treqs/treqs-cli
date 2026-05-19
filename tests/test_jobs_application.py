from __future__ import annotations

import pytest

from treqs_cli.application.jobs.models import ProjectJobs, TrainingJob, filter_jobs, job_rows
from treqs_cli.application.jobs.service import JobService, project_job_path, project_jobs_path
from treqs_cli.errors import ApiError
from treqs_cli.models import AuthState, RepoContext


def test_job_rows_and_filtering() -> None:
    jobs = [
        TrainingJob(
            id="job-1",
            trainingRequestId="request-1",
            projectSlug="mnist",
            computeTargetId="ct-1",
            status="QUEUED",
            createdAt="2026-01-01T00:00:00.000Z",
        ),
        TrainingJob(id="job-2", status="COMPLETED"),
    ]

    assert [job.id for job in filter_jobs(jobs, ("QUEUED",))] == ["job-1"]
    assert job_rows(jobs)[0] == {
        "id": "job-1",
        "status": "QUEUED",
        "request": "request-1",
        "project": "mnist",
        "target": "ct-1",
        "created": "2026-01-01T00:00:00.000Z",
    }


def test_job_service_builds_project_path_and_finds_job() -> None:
    client = _FakeJobsClient()
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    repo_context = RepoContext(
        api_url="https://api.treqs.ai",
        owner_id="org-1",
        owner_type="organization",
        owner_username="acme",
        owner_display_name="Acme",
        project_id="project-1",
        project_slug="mnist",
        project_name="MNIST",
        current_username="trevor",
    )
    service = JobService(client, auth_state, repo_context)

    jobs = service.list(limit=20, statuses=("QUEUED",))
    job = service.get("job-1")

    assert jobs[0].id == "job-1"
    assert job.id == "job-1"
    assert project_jobs_path(repo_context) == "/api/v1/user/orgs/acme/projects/mnist/jobs"
    assert project_job_path(repo_context, "job 1") == (
        "/api/v1/user/orgs/acme/projects/mnist/jobs/job%201"
    )
    assert client.calls == [
        ("list", "/api/v1/user/orgs/acme/projects/mnist/jobs", 20, "QUEUED"),
        ("get", "/api/v1/user/orgs/acme/projects/mnist/jobs/job-1"),
    ]


def test_job_service_reports_missing_job() -> None:
    client = _FakeJobsClient()
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    repo_context = RepoContext(
        api_url="https://api.treqs.ai",
        owner_id="user-1",
        owner_type="user",
        owner_username="trevor",
        owner_display_name="Trevor",
        project_id="project-1",
        project_slug="mnist",
        project_name="MNIST",
        current_username="trevor",
    )

    with pytest.raises(ApiError, match="Job missing"):
        JobService(client, auth_state, repo_context).get("missing")


class _FakeJobsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def list_project_jobs(
        self,
        _auth_state: AuthState,
        path: str,
        *,
        limit: int,
        status: str | None = None,
    ) -> ProjectJobs:
        self.calls.append(("list", path, limit, status))
        return ProjectJobs(
            queuedJobs=[
                TrainingJob(
                    id="job-1",
                    trainingRequestId="request-1",
                    projectSlug="mnist",
                    status="QUEUED",
                )
            ]
        )

    def get_project_job(
        self,
        _auth_state: AuthState,
        path: str,
    ) -> TrainingJob:
        self.calls.append(("get", path))
        job_id = path.rsplit("/", 1)[-1]
        if job_id == "missing":
            raise ApiError("Job missing", status_code=404)
        return TrainingJob(
            id=job_id,
            trainingRequestId="request-1",
            projectSlug="mnist",
            status="QUEUED",
        )
