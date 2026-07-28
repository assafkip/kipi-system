#!/usr/bin/env python3
"""read-first-gate: the first write of a session waits until the required reading
actually happened.

WHY (RCA rca-conclusions-before-evidence-2026-07-28):
  - root cause #1: `.claude/rules/quick-plan.md` names the reads required before work
    of any size -- memory, plans, `q-system/methodology/anti-hallucination.md`, then
    the relevant code. "Nothing executes that. No plan was written; the methodology
    doc was not opened until the founder asked why." A rule that exists only as text
    is the prompt-only-enforcement pattern this repo bans everywhere else.
  - root cause #2: the SessionStart lessons hook printed the lesson index, including
    "Store the evidence, derive the conclusions". "Titles entered context. Nothing
    required an open, an acknowledgment, or a check... Emission into context was
    treated as delivery."

So: before the FIRST Write/Edit of a session, this gate requires that
`anti-hallucination.md` was opened, and that at least one file from the surfaced
lessons corpus was opened. Both are a single Read each. After the first write it
never fires again -- gating every write would be noise, and noise gets bypassed.

An open counts from ANY tool: Read, Grep, or a Bash `cat`/`sed`. The check is whether
the path appears in a tool_use input, not which tool was fashionable.

HONEST BOUNDARY: this proves a file was OPENED. It cannot prove the right lesson was
chosen out of the corpus, that it was read rather than skimmed, or that it changed
anything about the work that follows. It converts a zero-cost surface into a forced
open, which is the specific thing that was missing, and no more than that.

Fails OPEN in every ambiguous case (no transcript, missing files, unreadable JSON):
a hook that fails closed on missing input blocks the fix too.

Contract: PreToolUse(Write|Edit|MultiEdit) hook, reads hook JSON on stdin.
exit 0 = pass, exit 2 = block. Self-test: `python3 test_read_first_gate.py`.
stdlib only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

METHODOLOGY = "q-system/methodology/anti-hallucination.md"
LESSONS_DIR = "q-system/lessons"
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# The ONLY destinations this gate fires on. An allowlist, not an exemption list.
#
# WHY (ASK-235, 2026-07-28): this gate fires on the FIRST write of a session and
# reads that session's own transcript. A morning-pipeline subagent is spawned to do
# one narrow job, and the required reading happened in the ORCHESTRATOR's context,
# so the subagent's transcript cannot show it. Measured: a realistic subagent
# transcript returns both reads missing and the write exits 2. A control transcript
# that DID open both is allowed, so the check discriminates rather than
# always-blocking.
#
# The first attempt exempted generated artifacts (bus files, morning logs). That
# was whack-a-mole and it lost: `synthesizer` writes daily-schedule-<date>.html and
# schedule-data-<date>.json into q-system/output/, which is neither, so both still
# blocked. Every new agent that writes a new path would re-open the same wound.
#
# Inverting it fixes the shape rather than the instance. Default is ALLOW; the gate
# fires only where an ungrounded claim actually does damage. That is not a
# weakening dressed up as a design: the RCA's six reversed conclusions did their
# harm by reaching a client email draft and a handoff that the next session
# inherited verbatim. Those destinations are listed here. A bus file or a schedule
# is an intermediate artifact a later step consumes and re-derives.
#
# It also removes the dependency on an undocumented platform detail. Which
# transcript a subagent hook receives could not be settled on this machine (no
# transcript on disk carries isSidechain=True, and none was available to inspect),
# and an allowlist keyed to the write target is correct under either answer.
#
# HONEST BOUNDARY: this is now narrower than "the first write of a session". A
# session that writes CODE without opening the methodology doc is no longer gated
# here. That was always the weaker half -- the gate only ever proved a file was
# opened, never that it was read or applied -- and trading it for a rule that can
# ship fleet-wide beats a stronger rule that has to stay switched off.
GATED_TARGETS = (
    "/output/outreach/",        # client-facing drafts: the RCA's worst outcome
    "memory/last-handoff.md",   # carried reversal #5 into the next session as fact
    "/canonical/",              # the source of truth other work derives from
    "/output/rca/",             # a postmortem built on an unread record is worthless
    "/output/plans/",           # the artifact the read-first contract exists to ground
)


def _records(transcript_path) -> list[dict]:
    p = Path(transcript_path) if transcript_path else None
    if not p or not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _tool_uses(records) -> list[tuple[str, str]]:
    """(tool_name, serialized input) for every tool call in the session."""
    uses = []
    for rec in records:
        msg = rec.get("message", {})
        if not isinstance(msg, dict):
            continue
        for item in msg.get("content", []) or []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                uses.append((item.get("name", ""),
                             json.dumps(item.get("input", {}))))
    return uses


def already_wrote(uses) -> bool:
    return any(name in WRITE_TOOLS for name, _ in uses)


def opened(uses, needle: str) -> bool:
    """Did any tool call this session reference this path? Tool-agnostic by design."""
    return any(needle in blob for _, blob in uses)


def evaluate(repo: Path, uses, target: str) -> list[str]:
    """Required reads still missing. Empty list = allow the write."""
    if already_wrote(uses):
        return []

    # Authoring the required reading is exempt from having read it. Otherwise the
    # gate deadlocks the one write that could satisfy it -- a hook that fails closed
    # on its own bootstrap blocks the fix too.
    norm_target = target.replace("\\", "/")
    if METHODOLOGY in norm_target or LESSONS_DIR in norm_target:
        return []

    # Allowlist: anything not a conclusion-bearing destination is none of this
    # gate's business. See GATED_TARGETS for why this is inverted.
    if not any(marker in norm_target for marker in GATED_TARGETS):
        return []

    missing = []
    if (repo / METHODOLOGY).exists() and not opened(uses, METHODOLOGY):
        missing.append(METHODOLOGY)

    lessons_dir = repo / LESSONS_DIR
    if lessons_dir.is_dir():
        lessons = sorted(p.name for p in lessons_dir.glob("*.md"))
        if lessons and not any(opened(uses, f"{LESSONS_DIR}/{n}") for n in lessons):
            missing.append(f"{LESSONS_DIR}/<any one of {len(lessons)} lessons>")

    return missing


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get("tool_input") or {}
    target = ti.get("file_path") or ti.get("path") or ""

    records = _records(payload.get("transcript_path", ""))
    if not records:
        return 0  # no transcript, no evidence either way: fail open

    repo = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    missing = evaluate(repo, _tool_uses(records), target)
    if not missing:
        return 0

    listed = "\n".join(f"    - {m}" for m in missing)
    sys.stderr.write(
        "READ-FIRST GATE (blocked): this is the first write of the session and the "
        "required reading has not happened.\n" + listed + "\n\n"
        "  Open each one, then write. One Read each.\n\n"
        "  Scar 2026-07-28: a session issued six confident conclusions, all six were "
        "reversed by evidence available from the first minute, and one reached a "
        "client email draft. The methodology doc was not opened until the founder "
        "asked why. The lessons index had already printed 'Store the evidence, "
        "derive the conclusions' at the top of that session -- as a title nobody "
        "opened.\n"
        "  This gate fires once per session, on the first write only.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
