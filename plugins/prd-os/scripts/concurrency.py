"""Shared concurrency guard for the prd-os plugin.

Invariant: at most one active workflow context at a time. You can have an
active PRD (being drafted, reviewed, approved) OR an active issue (being
implemented). Never both. Mixing them opens coordination bugs (a PRD
changing its manifest while an issue derived from it is in-flight) and
makes the scope/stop hooks ambiguous about which spec they are protecting.

Both runners import these helpers at their state-write entry points
(`prd_runner new|load`, `issue_runner load`). The checks live here rather
than in each runner so both sides share one definition of "active".

`ISSUE_GATE_OFF=1` does NOT bypass this guard. The scope/stop hooks honor
it because they protect in-progress work that the human has already chosen
to fast-path through. Concurrency, by contrast, protects the workflow
runtime itself — fast-pathing it corrupts state files that every later
command reads. If the founder genuinely needs to hold both contexts at
once (e.g., during migration), they must clear one explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class ConcurrencyError(Exception):
    """Raised when opening a context would conflict with an active context."""


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def active_issue_id(issue_state_path: Path) -> Optional[str]:
    """Return the active issue id, or None when no issue is active."""
    state = _read_json(issue_state_path)
    issue_id = state.get("issue_id")
    return issue_id if isinstance(issue_id, str) and issue_id else None


def active_prd(prd_state_path: Path) -> Optional[dict]:
    """Return {'prd_id': ..., 'status': ...} for any non-archived active PRD.

    An `archived` PRD counts as not-active: the spec is frozen and nothing
    downstream should still be blocked on it. Empty/missing state also
    returns None.
    """
    state = _read_json(prd_state_path)
    prd_id = state.get("prd_id")
    if not isinstance(prd_id, str) or not prd_id:
        return None
    status = state.get("status")
    if status == "archived":
        return None
    return {"prd_id": prd_id, "status": status}


def assert_no_active_issue(issue_state_path: Path, *, action: str) -> None:
    """Raise ConcurrencyError when an issue is active."""
    issue_id = active_issue_id(issue_state_path)
    if issue_id:
        raise ConcurrencyError(
            f"cannot {action}: issue {issue_id!r} is active. "
            "Close the issue (`/issue-closeout`) or clear its state "
            "(`issue_runner.py clear`) before starting PRD work."
        )


def assert_no_active_prd(prd_state_path: Path, *, action: str) -> None:
    """Raise ConcurrencyError when a non-archived PRD is active."""
    prd = active_prd(prd_state_path)
    if prd:
        raise ConcurrencyError(
            f"cannot {action}: PRD {prd['prd_id']!r} is active "
            f"(status={prd['status']!r}). "
            "Archive the PRD (`prd_runner.py archive`) or clear its state "
            "(`prd_runner.py clear`) before loading an issue."
        )
