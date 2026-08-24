#!/usr/bin/env python3
"""KB freshness guard: deterministic Stop-hook for memory/graph.jsonl.

Why this shape (prd-kb-graph-guard-2026-08-24): entity relationships enter
investigations through whatever path a session takes, and /q-* commands are
invoked autonomously, not by the founder. So enforcement cannot key on any
command -- it keys on the only layer that always runs, session Stop.

Contract (matches memory-confidence-validator):
  exit 0          fresh, nothing to do, or ANY doubt -> silent pass
  exit 2 + stderr stale -> message fed back; the live agent extracts triples now

Scar-guarded decisions:
- mtime comparison, not line counts: stateless, no SessionStart pairing, no
  state that can go missing and false-green.
- escalate-then-release: the SECOND same-day stale writes one Sana queue line
  and exits 0. Holding sessions hostage on Stop produced gate-off pressure in
  every previous guard (memory-lint docstring); one bounded complaint per day
  is the loudest safe signal.
- silent-safe: missing KB/dirs or any exception exits 0. A capture bug must
  never block a session close.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

STATE_DIRNAME = Path(".claude/state")
STATE_FILENAME = "kb-graph-guard.json"
WATCH_SUBDIRS = ("targets", "findings")


def fail_open(msg: str) -> int:
    sys.stderr.write(f"kb-graph-guard: {msg}\n")
    return 0


def find_repo_root() -> Path | None:
    env_root = None
    import os

    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    probe = Path.cwd()
    for candidate in [probe, *probe.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def find_kb(root: Path) -> Path | None:
    """Same discovery rule as ensure_instance_kb.py: q-dir first, root fallback."""
    q_dirs = sorted(p for p in root.glob("q-*/memory/graph.jsonl") if p.is_file())
    if q_dirs:
        return q_dirs[0]
    root_kb = root / "memory" / "graph.jsonl"
    return root_kb if root_kb.is_file() else None


def newest_entity_mtime(root: Path) -> float | None:
    """Scan <root>/investigations AND <root>/q-*/investigations: instances with
    an instance_q_dir keep cases under the q-dir, plain ones at repo root."""
    newest = None
    candidates = [root / "investigations"]
    candidates += sorted(root.glob("q-*/investigations"))
    for investigations in candidates:
        if not investigations.is_dir():
            continue
        for sub in WATCH_SUBDIRS:
            for dirpath in investigations.rglob(f"investigation/{sub}"):
                if not dirpath.is_dir():
                    continue
                for f in dirpath.rglob("*"):
                    if f.is_file() and not f.name.startswith("."):
                        m = f.stat().st_mtime
                        newest = m if newest is None or m > newest else newest
    return newest


def load_state(state_file: Path) -> dict:
    try:
        return json.loads(state_file.read_text())
    except Exception:
        return {}


def queue_escalation(root: Path, kb_path: Path) -> bool:
    script = root / "q-system" / ".q-system" / "scripts" / "linear-queue.py"
    if not script.is_file():
        return False
    try:
        subprocess.run(
            ["python3", str(script), "add",
             "--repo", root.name,
             "--kind", "issue",
             "--title", f"KB stale: entity data outgrew graph.jsonl ({dt.date.today()})",
             "--note", f"kb-graph-guard second same-day miss. KB: {kb_path}",
             "--source", "kb-guard"],
            capture_output=True, timeout=10,
        )
        return True
    except Exception:
        return False


def main() -> int:
    try:
        root = find_repo_root()
        if root is None:
            return 0
        kb = find_kb(root)
        if kb is None:
            return 0
        newest = newest_entity_mtime(root)
        if newest is None:
            return 0
        if newest <= kb.stat().st_mtime:
            return 0

        today = dt.date.today().isoformat()
        state_file = root / STATE_DIRNAME / STATE_FILENAME
        state = load_state(state_file)
        if state.get("last_warned") == today:
            already_escalated = state.get("escalated") == today
            if not already_escalated and queue_escalation(root, kb):
                state["escalated"] = today
                state_file.parent.mkdir(parents=True, exist_ok=True)
                state_file.write_text(json.dumps(state))
            return 0

        state["last_warned"] = today
        state.pop("escalated", None)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state))
        sys.stderr.write(
            "kb-graph-guard: entity files changed this session but "
            f"{kb.relative_to(root)} is older. Extract relationship triples "
            "(s/p/o/t lines) from the targets/findings you touched and append "
            "them to the KB before closing.\n"
        )
        return 2
    except Exception as exc:
        return fail_open(f"unexpected error, passing: {exc}")


if __name__ == "__main__":
    sys.exit(main())
