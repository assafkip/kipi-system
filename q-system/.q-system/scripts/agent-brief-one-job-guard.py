#!/usr/bin/env python3
"""PreToolUse(Agent|Task) gate: one agent brief = one job = one PR (ASK-2541).

Pairs with plugins/prd-os/scripts/one_job.py, the single detector that
prd_split.py also uses, so a spec and a brief are held to the same rule.

why: RCA token-burn-recurs-after-gate-2026-10-06, root cause #4. "Fresh agent
per task" was followed as "fresh agent per brief", and one brief bundled five
jobs (three PRs, a dry run, a review loop). That agent ran 57 turns and re-read
10.3M cached tokens for 6.4k tokens of output, because every turn spent
waiting on a commit re-read its whole context. An orchestrator brief that asks
one agent to "split this into several PRs" is the same defect: split it BEFORE
launch, one agent per PR.

Measured before it was allowed to block (2026-10-06): run over 414 distinct
real Agent briefs from the last 30 days of transcripts, it flagged 9. By hand,
8 of those asked for two or more PRs and 1 only quoted the old "three PRs"
scar, so it blocks about 1 in 406 single-job briefs (0.25%), well under the
10% line where a gate red on its own population gets switched off. 0 of 741
real PRD manifest entries trip the same detector. Known miss, kept on purpose:
"land the three PRs" with no making-verb right before the count passes; the
count rule needs "into/as/open/ship ... N PRs" because a bare count was a
description far more often than a request.

Honest boundary: a regex reads words, never intent. It cannot tell a request
from a quotation, and a brief that hides a second job in prose without the
words "PR", "pull request" or "branch" (for example "then do the dry run")
passes. It counts PRs, not every kind of job.

Bypass for a brief that only QUOTES a multi-PR shape: BYPASS_RE below stands
this script down when the brief carries `one-job-brief-skip: <why>`. The
reason text is required so a bypass stays countable in transcripts.

Exit codes: 2 = block (stderr goes back to Claude), 0 = allow.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BYPASS_RE = re.compile(r"one-job-brief-skip:\s*\S[^\n]{9,}")

# q-system/.q-system/scripts/<this> -> repo root is three levels above scripts/.
# plugins/ is synced into every instance by `kipi update`, beside q-system/.
_DETECTOR_DIR = Path(__file__).resolve().parents[3] / "plugins" / "prd-os" / "scripts"


def _load_detector():
    sys.path.insert(0, str(_DETECTOR_DIR))
    try:
        import one_job  # noqa: PLC0415
    except ImportError:
        return None
    finally:
        sys.path.pop(0)
    return one_job


def _payload() -> dict:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        # Malformed input is the harness's bug, not a second job. Failing
        # closed here would block every agent launch for a reason nobody can
        # act on, and a gate that does that gets switched off.
        return {}
    return data if isinstance(data, dict) else {}


def _guidance(reasons: list[str], howto: str) -> str:
    lines = "\n".join(f"  - {r}" for r in reasons)
    return (
        "BLOCKED: this agent brief asks for more than one PR. One brief is one "
        "job is one PR.\n\n"
        f"What the detector saw:\n{lines}\n\n"
        f"{howto}\n\n"
        "Scar: one brief bundled three PRs, a dry run and a review loop. Its "
        "agent ran 57 turns and re-read 10.3M cached tokens while it waited on "
        "commits (RCA token-burn-recurs-after-gate-2026-10-06, root cause #4).\n\n"
        "If this brief is one job and only QUOTES a multi-PR shape, add\n"
        "  one-job-brief-skip: <why this brief is one job>\n"
        "to the prompt.\n"
    )


def main() -> int:
    data = _payload()
    if data.get("tool_name") not in (None, "Agent", "Task"):
        return 0
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    text = "\n".join(
        str(tool_input.get(k) or "") for k in ("description", "prompt")
    )
    if not text.strip() or BYPASS_RE.search(text):
        return 0

    one_job = _load_detector()
    if one_job is None:
        # Say it out loud: a guard that silently loses its detector reads as
        # coverage. Still exit 0, an instance without plugins/ synced yet must
        # be able to launch agents.
        sys.stderr.write(
            f"agent-brief-one-job-guard: INERT, no one_job.py under {_DETECTOR_DIR}\n"
        )
        return 0

    reasons = one_job.multi_pr_reasons(text)
    if not reasons:
        return 0
    sys.stderr.write(_guidance(reasons, one_job.SPLIT_HOWTO))
    return 2


if __name__ == "__main__":
    sys.exit(main())
