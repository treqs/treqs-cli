from __future__ import annotations

import json
from typing import Any

import click
from pydantic import BaseModel


def emit_json(value: Any) -> None:
    click.echo(json.dumps(_jsonable(value), indent=2, sort_keys=True))


def render_table(rows: list[dict[str, str]], headers: list[tuple[str, str]]) -> None:
    if not rows:
        click.echo("No results.")
        return
    widths = {
        key: max(len(label), *(len(row.get(key, "")) for row in rows)) for key, label in headers
    }
    click.echo("  ".join(label.ljust(widths[key]) for key, label in headers))
    for row in rows:
        click.echo("  ".join(row.get(key, "").ljust(widths[key]) for key, _label in headers))


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
