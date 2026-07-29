from __future__ import annotations

import pytest

from treqs_cli.application.jobs.models import (
    LineageRepublishResult,
    LogChunk,
    LogPollResult,
    ProjectJobs,
    TrainingJob,
    filter_jobs,
    job_rows,
)
from treqs_cli.application.jobs.service import (
    JobLogService,
    JobService,
    job_cancel_path,
    job_logs_poll_path,
    project_job_path,
    project_jobs_path,
)
from treqs_cli.context import OwnerScope
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


def test_training_job_parses_lineage_publication_fields() -> None:
    job = TrainingJob.model_validate(
        {
            "id": "job-1",
            "status": "COMPLETED",
            "lineagePublishedUrl": "https://glaas.ai/dag/abc123",
            "lineagePublishedSessionHash": "abc123",
        }
    )

    assert job.lineagePublishedUrl == "https://glaas.ai/dag/abc123"
    assert job.lineagePublishedSessionHash == "abc123"

    unpublished = TrainingJob(id="job-2", status="QUEUED")

    assert unpublished.lineagePublishedUrl is None
    assert unpublished.lineagePublishedSessionHash is None


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


def test_job_service_republish_lineage_builds_path_and_parses_result() -> None:
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

    result = JobService(client, auth_state, repo_context).republish_lineage("job-1")

    assert result.publication_status == "published"
    assert result.published_session_hash == "a" * 64
    assert client.calls == [
        ("republish", "/api/v1/user/orgs/acme/projects/mnist/jobs/job-1/lineage/republish"),
    ]


def test_job_service_cancel_builds_path_and_parses_result() -> None:
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

    job = JobService(client, auth_state, repo_context).cancel("ct-1", "job-1")

    assert job.id == "job-1"
    assert job.status == "CANCELLED"
    assert job_cancel_path(repo_context, "ct-1", "job-1") == (
        "/api/v1/user/orgs/acme/compute-targets/ct-1/jobs/job-1/cancel"
    )
    assert client.calls == [
        ("cancel", "/api/v1/user/orgs/acme/compute-targets/ct-1/jobs/job-1/cancel"),
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


def test_job_log_service_builds_compute_target_scoped_poll_path() -> None:
    client = _FakeJobLogClient()
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="access-token")
    scope = OwnerScope(owner_username="acme", current_username="trevor")

    result = JobLogService(client, auth_state, scope).poll(
        "ct-1",
        "job-1",
        from_sequence=3,
        timeout_ms=15000,
    )

    assert result.nextSequence == 5
    assert result.chunks[0].content == "line\n"
    assert job_logs_poll_path(scope, "ct-1", "job-1") == (
        "/api/v1/user/orgs/acme/compute-targets/ct-1/jobs/job-1/logs/poll"
    )
    assert client.calls == [
        ("poll", "/api/v1/user/orgs/acme/compute-targets/ct-1/jobs/job-1/logs/poll", 3, 15000),
    ]


def test_log_poll_result_parses_api_shape() -> None:
    result = LogPollResult.model_validate(
        {
            "chunks": [{"sequence": 0, "content": "hello\n"}],
            "hasMore": True,
            "nextSequence": 1,
        }
    )

    assert result.chunks == [LogChunk(sequence=0, content="hello\n")]
    assert result.hasMore is True
    assert result.nextSequence == 1


class _FakeJobLogClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def poll_job_logs(
        self,
        _auth_state: AuthState,
        path: str,
        *,
        from_sequence: int,
        timeout_ms: int,
    ) -> LogPollResult:
        self.calls.append(("poll", path, from_sequence, timeout_ms))
        return LogPollResult(
            chunks=[LogChunk(sequence=4, content="line\n")],
            hasMore=False,
            nextSequence=5,
        )


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

    def republish_job_lineage(
        self,
        _auth_state: AuthState,
        path: str,
    ) -> LineageRepublishResult:
        self.calls.append(("republish", path))
        return LineageRepublishResult(
            publication_status="published",
            published_session_hash="a" * 64,
            published_url="https://dev.glaas.ai/dag/" + "a" * 64,
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

    def cancel_job(
        self,
        _auth_state: AuthState,
        path: str,
    ) -> TrainingJob:
        self.calls.append(("cancel", path))
        job_id = path.split("/jobs/", 1)[-1].removesuffix("/cancel")
        return TrainingJob(id=job_id, status="CANCELLED")
