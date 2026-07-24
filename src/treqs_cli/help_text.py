"""Helpers for consistent, discoverable command help across the CLI.

Conventions enforced by tests/test_help.py:

- Every leaf command carries an ``Examples:`` epilog built with
  :func:`examples` so invocations render verbatim (no rewrapping).
- Every positional argument is explained in the command docstring by its
  uppercase metavar (Click renders option help but never argument help).
"""

from __future__ import annotations

EXAMPLES_HEADER = "Examples:"


def examples(*lines: str) -> str:
    """Build an ``Examples:`` epilog block from literal command lines.

    The leading ``\\b`` marks the paragraph as pre-formatted so Click keeps
    each example on its own line at any terminal width.
    """
    body = "\n".join(f"  {line}" for line in lines)
    return f"\b\n{EXAMPLES_HEADER}\n{body}"
