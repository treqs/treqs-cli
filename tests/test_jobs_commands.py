from __future__ import annotations

from pathlib import Path
from typing import Any

from click.testing import CliRunner

from treqs_cli.application.jobs.models import (
    JobLifecycleEvent,
    JobUpdates,
    JobUpdateSnapshot,
    LogChunk,
    LogPollResult,
    TrainingJob,
)
from treqs_cli.commands.jobs import jobs_watch_command
from treqs_cli.config import AuthStore, RepoContextStore
from treqs_cli.context import TreqsContext
from treqs_cli.errors import ConfigError
from treqs_cli.models import AuthState, RepoContext


def test_jobs_watch_sends_lifecycle_to_stderr_and_workload_logs_to_stdout(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    auth_state, repo_context, state = _context(tmp_path, json_output=False)

    class FakeClient:
        def __init__(self, _api_url: str) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class FakeJobService:
        def __init__(self, *_args: object) -> None:
            pass

        def get(self, job_id: str) -> TrainingJob:
            return TrainingJob(id=job_id, status="COMPLETED", computeTargetId="target-1")

    class FakeJobLogService:
        def __init__(self, *_args: object) -> None:
            pass

        def poll(
            self,
            _target_id: str,
            _job_id: str,
            *,
            from_sequence: int,
            timeout_ms: int,
            stream: str | None = None,
        ) -> LogPollResult:
            del from_sequence, timeout_ms
            return LogPollResult(
                chunks=[LogChunk(sequence=0, content="workload output\n")],
                hasMore=False,
                nextSequence=1,
            )

    def fake_watch_job(*_args: object, **kwargs: object) -> JobUpdates:
        update = _completed_updates()
        on_update = kwargs["on_update"]
        on_poll = kwargs["on_poll"]
        assert callable(on_update)
        assert callable(on_poll)
        on_update(update)
        on_poll()
        return update

    monkeypatch.setattr("treqs_cli.commands.jobs.TreqsApiClient", FakeClient)
    monkeypatch.setattr("treqs_cli.commands.jobs.JobService", FakeJobService)
    monkeypatch.setattr("treqs_cli.commands.jobs.JobLogService", FakeJobLogService)
    monkeypatch.setattr("treqs_cli.commands.jobs.watch_job", fake_watch_job)
    monkeypatch.setattr(
        "treqs_cli.commands.jobs.load_project_api_context",
        lambda _state: (auth_state, repo_context),
    )

    result = CliRunner().invoke(
        jobs_watch_command,
        ["job-1"],
        obj=state,
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.stdout == "workload output\n"
    assert "queued" in result.stderr
    assert "Job queued" in result.stderr
    assert "repository" in result.stderr
    assert "Preparing repository" in result.stderr
    assert "completed" in result.stderr


def _completed_updates() -> JobUpdates:
    return JobUpdates(
        snapshot=JobUpdateSnapshot(
            jobStatus="COMPLETED",
            phase="terminal",
            message="Job completed",
        ),
        events=[
            JobLifecycleEvent(
                id="event-1",
                kind="job.queued",
                occurredAt="2026-07-30T12:03:01.000Z",
                severity="info",
                message="Job queued",
            ),
            JobLifecycleEvent(
                id="event-2",
                kind="execution.repository_preparing",
                occurredAt="2026-07-30T12:03:02.000Z",
                severity="info",
                message="Preparing repository",
            ),
            JobLifecycleEvent(
                id="event-3",
                kind="job.completed",
                occurredAt="2026-07-30T12:08:47.000Z",
                severity="info",
                message="Job completed",
            ),
        ],
        nextCursor="event-3",
        terminal=True,
    )


def _context(
    tmp_path: Path,
    *,
    json_output: bool,
) -> tuple[AuthState, RepoContext, TreqsContext]:
    auth_state = AuthState(api_url="https://api.treqs.ai", access_token="token")
    repo_context = RepoContext(
        api_url="https://api.treqs.ai",
        owner_id="owner-1",
        owner_type="user",
        owner_username="trevor",
        owner_display_name="Trevor",
        project_id="project-1",
        project_slug="mnist",
        project_name="MNIST",
        current_username="trevor",
    )
    state = TreqsContext(
        api_url_override=None,
        json_output=json_output,
        auth_store=AuthStore(tmp_path / "auth.json"),
        repo_context_store=RepoContextStore(tmp_path / ".treqs" / "config.toml"),
        cwd=tmp_path,
        repo_root=tmp_path,
        is_interactive=False,
        is_git_repo=True,
    )
    return auth_state, repo_context, state


def test_jobs_logs_rejects_agent_and_task_together(tmp_path: Path) -> None:
    """They select different streams; silently preferring one would hide the other."""
    from treqs_cli.commands.jobs import jobs_logs_command

    state = TreqsContext(
        api_url_override=None,
        json_output=False,
        auth_store=AuthStore(tmp_path / "auth.json"),
        repo_context_store=RepoContextStore(tmp_path / ".treqs" / "config.toml"),
        cwd=tmp_path,
        repo_root=tmp_path,
        is_interactive=False,
        is_git_repo=True,
    )
    runner = CliRunner()
    result = runner.invoke(jobs_logs_command, ["job-1", "--agent", "--task", "task-1"], obj=state)

    assert result.exit_code != 0
    assert isinstance(result.exception, ConfigError)
    assert "not both" in str(result.exception)
