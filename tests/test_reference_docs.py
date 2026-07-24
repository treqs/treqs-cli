from __future__ import annotations

from treqs_cli.reference_docs import reference_path, render_reference

REGENERATE_HINT = "regenerate with `uv run python -m treqs_cli.reference_docs`"


def test_cli_reference_is_current() -> None:
    path = reference_path()
    assert path.exists(), f"docs/CLI.md is missing; {REGENERATE_HINT}."

    actual = path.read_text(encoding="utf-8")
    assert actual == render_reference(), f"docs/CLI.md is stale; {REGENERATE_HINT}."
