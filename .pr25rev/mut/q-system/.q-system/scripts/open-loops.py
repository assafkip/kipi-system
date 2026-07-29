#!/usr/bin/env python3
"""Open-loops surfacer: nothing parked falls on the ground. (AUDHD anti-drop.)

Why this exists: deferred / half-baked / waiting-on-external items left as prose
in a ledger get forgotten. This reads the explicit registry
(q-system/memory/open-loops.json) plus any genuinely-deferred prd-os findings and
re-surfaces them EVERY SessionStart via additionalContext, so doing nothing keeps
them in view instead of letting them rot. The agent relays them to the founder.

Two modes:
  - hook mode (no args): emit {"hookSpecificOutput": {...additionalContext...}} for SessionStart.
  - `--report`:  print a plain checklist for a human to read on demand.

Discipline this enforces: a parked item is an entry in open-loops.json, never a
prose "deferred / your call later" line. Close a loop by setting status:"closed".

Fail-closed + never-blocks: any error -> emit nothing, exit 0. stdlib only.
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

CAP = 25

# A deferred prd-os finding is a GENUINE open loop (not closeout bookkeeping) when
# its rationale points at real future work and is NOT "folded into" an issue.
FUTURE_WORK_RE = re.compile(r"\b(v2|v3|phase\s*2|phase\s*3|revisit|backlog|deferred to|once .+ exists|when .+ )", re.IGNORECASE)
FOLDED_RE = re.compile(r"folded into|refinement, not a standalone|confirmation, no defect", re.IGNORECASE)


def get_qroot(project_dir):
    nested = Path(project_dir) / "q-system" / "q-system" / "canonical"
    if nested.exists():
        return Path(project_dir) / "q-system" / "q-system"
    return Path(project_dir) / "q-system"


def project_root():
    pd = os.environ.get("CLAUDE_PROJECT_DIR")
    if pd:
        return Path(pd)
    # CLI fallback: this file is q-system/.q-system/scripts/open-loops.py
    return Path(__file__).resolve().parents[3]


def registry_loops(qroot):
    path = qroot / "memory" / "open-loops.json"
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    out = []
    for loop in data.get("loops", []):
        if str(loop.get("status", "open")).lower() == "closed":
            continue
        title = (loop.get("title") or "").strip()
        action = (loop.get("next_action") or "").strip()
        if not title:
            continue
        out.append((title, action, bool(loop.get("needs_founder"))))
    return out


def deferred_findings(repo_root):
    """Returns (surfaced, unclassified). surfaced = genuine future-work deferrals.
    unclassified = deferred + not closeout-bookkeeping + not keyword-matched: COUNTED
    (never silently dropped) so a plainly-worded parked finding can't fall on the ground."""
    out = []
    seen = set()
    unclassified = 0
    for jf in sorted(glob.glob(str(repo_root / ".prd-os" / "findings" / "*.jsonl"))):
        try:
            lines = Path(jf).read_text().splitlines()
        except Exception:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if str(d.get("disposition", "")).lower() != "deferred":
                continue
            rationale = (d.get("rationale") or "").strip()
            if not rationale or FOLDED_RE.search(rationale):
                continue  # closeout bookkeeping -> genuinely closed
            if FUTURE_WORK_RE.search(rationale):
                body = (d.get("body") or d.get("id") or "deferred item").strip()
                key = body[:60]
                if key in seen:
                    continue
                seen.add(key)
                out.append((body[:80], rationale[:120], False))
            else:
                unclassified += 1  # not auto-classified -> surfaced as a catch-all
    return out, unclassified


def collect(project_dir):
    repo = project_root()
    qroot = get_qroot(str(repo))  # anchor registry + findings to the same root (CLI-safe)
    loops = registry_loops(qroot)
    fnd, unclassified = deferred_findings(repo)
    loops += fnd
    return loops[:CAP], unclassified


def render(loops, unclassified=0):
    n = len(loops) + (1 if unclassified else 0)
    head = (f"# Open loops ({n}) -- surface these to the founder now. Nothing parked "
            f"falls on the ground.\n"
            f"# Close one: set status:\"closed\" in q-system/memory/open-loops.json.\n")
    lines = [head]
    for title, action, needs_founder in loops:
        tag = " [needs you]" if needs_founder else ""
        lines.append(f"- [ ] {title}{tag} -> {action}")
    if unclassified:
        lines.append(f"- [ ] {unclassified} deferred prd-os finding(s) not auto-classified "
                     f"-> review rationale in .prd-os/findings/ and either close (won't-do) or "
                     f"add to open-loops.json (so nothing stays in limbo)")
    return "\n".join(lines)


def main():
    try:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        report_mode = "--report" in sys.argv[1:]
        loops, unclassified = collect(project_dir)
        if not loops and not unclassified:
            if report_mode:
                print("No open loops. Clean.")
            sys.exit(0)
        body = render(loops, unclassified)
        if report_mode:
            print(body)
        else:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart", "additionalContext": body}}))
        sys.exit(0)
    except Exception:
        sys.exit(0)  # never block session start


if __name__ == "__main__":
    main()
