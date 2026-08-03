from __future__ import annotations

import pytest

from treqs_cli.application.jobs.models import (
    JobLifecycleEvent,
    JobStatus,
    JobUpdatePhase,
    JobUpdates,
    JobUpdateSnapshot,
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
    project_job_updates_path,
    project_jobs_path,
    watch_job,
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


def test_job_updates_parse_snapshot_events_and_action() -> None:
    updates = JobUpdates.model_validate(
        {
            "snapshot": {
                "jobStatus": "QUEUED",
                "phase": "blocked",
                "message": "Compute provisioning failed: capacity exhausted",
                "actionRequired": "Retry provisioning or select another target.",
                "compute": {
                    "targetId": "ct-1",
                    "targetName": "gpu",
                    "instanceId": "instance-1",
                    "status": "failed",
                    "attempt": 1,
                },
                "task": None,
                "lineagePublicationStatus": None,
            },
            "events": [
                {
                    "id": "event-1",
                    "kind": "compute.provisioning_failed",
                    "occurredAt": "2026-07-30T12:03:05.000Z",
                    "severity": "error",
                    "message": "Launch failed: capacity exhausted",
                    "attributes": {"instanceId": "instance-1", "launchAttemptCount": 1},
                }
            ],
            "nextCursor": "event-1",
            "terminal": False,
        }
    )

    assert updates.snapshot.phase == "blocked"
    assert updates.snapshot.actionRequired == "Retry provisioning or select another target."
    assert updates.events[0].kind == "compute.provisioning_failed"
    assert updates.events[0].attributes["launchAttemptCount"] == 1


def test_job_service_polls_project_scoped_updates_with_cursor() -> None:
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

    updates = JobService(client, auth_state, repo_context).poll_updates(
        "job-1",
        cursor="event-1",
        timeout_ms=15000,
    )

    assert updates.snapshot.phase == "waiting_for_agent"
    assert project_job_updates_path(repo_context, "job 1") == (
        "/api/v1/user/orgs/acme/projects/mnist/jobs/job%201/updates"
    )
    assert client.calls == [
        (
            "updates",
            "/api/v1/user/orgs/acme/projects/mnist/jobs/job-1/updates",
            "event-1",
            15000,
        )
    ]


def test_watch_job_accumulates_deduplicated_events_until_terminal() -> None:
    queued_event = JobLifecycleEvent(
        id="event-1",
        kind="job.queued",
        occurredAt="2026-07-30T12:03:01.000Z",
        severity="info",
        message="Job queued",
    )
    completed_event = JobLifecycleEvent(
        id="event-2",
        kind="job.completed",
        occurredAt="2026-07-30T12:08:47.000Z",
        severity="info",
        message="Job completed",
    )
    source = _FakeWatchSource(
        [
            _updates("QUEUED", "queued", False, [queued_event], "event-1"),
            _updates(
                "COMPLETED",
                "terminal",
                True,
                [queued_event, completed_event],
                "event-2",
            ),
        ]
    )
    observed: list[JobUpdates] = []

    result = watch_job(
        source,
        "job-1",
        timeout_seconds=60,
        on_update=observed.append,
    )

    assert [call[0] for call in source.calls] == [None, "event-1"]
    assert [[event.id for event in update.events] for update in observed] == [
        ["event-1"],
        ["event-2"],
    ]
    assert [event.id for event in result.events] == ["event-1", "event-2"]
    assert result.terminal is True


def test_watch_job_falls_back_to_legacy_status_polling_for_older_api() -> None:
    source = _LegacyWatchSource()

    result = watch_job(
        source,
        "job-1",
        timeout_seconds=60,
        sleep=lambda _seconds: None,
    )

    assert result.snapshot.jobStatus == "COMPLETED"
    assert result.snapshot.phase == "terminal"
    assert result.terminal is True
    assert source.get_calls == 1


def test_watch_job_returns_immediately_when_user_action_is_required() -> None:
    source = _FakeWatchSource(
        [
            JobUpdates(
                snapshot=JobUpdateSnapshot(
                    jobStatus="QUEUED",
                    phase="blocked",
                    message="Compute provisioning failed",
                    actionRequired="Retry provisioning or select another target.",
                ),
                terminal=False,
            )
        ]
    )

    result = watch_job(source, "job-1", timeout_seconds=60)

    assert result.terminal is False
    assert result.snapshot.phase == "blocked"
    assert result.snapshot.actionRequired == "Retry provisioning or select another target."
    assert len(source.calls) == 1


def test_watch_job_emits_a_heartbeat_during_unchanged_long_waits() -> None:
    now = 0.0
    responses = [
        _updates("QUEUED", "waiting_for_agent", False, [], None),
        _updates("QUEUED", "waiting_for_agent", False, [], None),
        _updates("COMPLETED", "terminal", True, [], None),
    ]

    class Source:
        def poll_updates(
            self,
            _job_id: str,
            *,
            cursor: str | None,
            timeout_ms: int,
        ) -> JobUpdates:
            nonlocal now
            del cursor, timeout_ms
            response = responses.pop(0)
            if len(responses) == 1:
                now = 26.0
            return response

        def get(self, job_id: str) -> TrainingJob:
            return TrainingJob(id=job_id, status="QUEUED")

    heartbeats: list[JobUpdateSnapshot] = []
    result = watch_job(
        Source(),
        "job-1",
        timeout_seconds=60,
        heartbeat_seconds=25,
        on_heartbeat=heartbeats.append,
        monotonic=lambda: now,
    )

    assert result.terminal is True
    assert [snapshot.phase for snapshot in heartbeats] == ["waiting_for_agent"]


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

    def poll_job_updates(
        self,
        _auth_state: AuthState,
        path: str,
        *,
        cursor: str | None,
        timeout_ms: int,
    ) -> JobUpdates:
        self.calls.append(("updates", path, cursor, timeout_ms))
        return _updates("QUEUED", "waiting_for_agent", False, [], cursor)


def _updates(
    status: JobStatus,
    phase: JobUpdatePhase,
    terminal: bool,
    events: list[JobLifecycleEvent],
    cursor: str | None,
) -> JobUpdates:
    return JobUpdates(
        snapshot=JobUpdateSnapshot(
            jobStatus=status,
            phase=phase,
            message=f"Job is {phase}",
        ),
        events=events,
        nextCursor=cursor,
        terminal=terminal,
    )


class _FakeWatchSource:
    def __init__(self, updates: list[JobUpdates]) -> None:
        self.updates = updates
        self.calls: list[tuple[str | None, int]] = []

    def poll_updates(
        self,
        _job_id: str,
        *,
        cursor: str | None,
        timeout_ms: int,
    ) -> JobUpdates:
        self.calls.append((cursor, timeout_ms))
        return self.updates.pop(0)

    def get(self, job_id: str) -> TrainingJob:
        return TrainingJob(id=job_id, status="QUEUED")


class _LegacyWatchSource:
    def __init__(self) -> None:
        self.get_calls = 0

    def poll_updates(
        self,
        _job_id: str,
        *,
        cursor: str | None,
        timeout_ms: int,
    ) -> JobUpdates:
        del cursor, timeout_ms
        raise ApiError("Not found", status_code=404)

    def get(self, job_id: str) -> TrainingJob:
        self.get_calls += 1
        return TrainingJob(id=job_id, status="COMPLETED")
