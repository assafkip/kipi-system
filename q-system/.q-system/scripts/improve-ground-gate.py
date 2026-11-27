#!/usr/bin/env python3
"""improve-ground-gate: before a NEW script, hook or gate file is created, ask
improve_ground.py whether the thing already exists. Pairs with the `improve`
skill (plugins/kipi-core/skills/improve), whose deterministic half it runs.

WHY (founder, 2026-11-26, verbatim): "I dont want just a memory note - it needs
a hook." and "improve_ground.py must be wired to run on its own before new
scripts or gates get built". Scar: PRs #885 to #888 built a parallel 45% plan
gate in ~6 hours and 7 review rounds while `~/.config/kipi/fleet-plan-billing-
until` and usage-pacer `cap_pct` already did it (reverted in #889, ASK-5797).
The guard before this hook was a memory note, which nothing reads at the
moment a file is created. ASK-5804.

Contract (PreToolUse, matcher Write):
  - fires only on a Write whose target does NOT exist yet, under
    q-system/.q-system/scripts/, plugins/<group>/hooks/, plugins/<group>/scripts/
    or ~/.config/kipi/. Edits and overwrites fast-exit 0.
  - test files are out of scope: a test's docstring describes the thing it
    tests, which by definition already exists, so every new test would block.
  - the idea it grounds is the session's active ticket (.claude/state/
    active-issue.json, the store prd-os and kipi-dsse both write; its spec's
    title) or else the new file's docstring / leading comment block.
  - verdict `already-built` -> exit 2, stderr names the cited file or lesson.
  - any other verdict, no text to ground, improve_ground missing, failing,
    unparseable or slower than SUBPROCESS_TIMEOUT -> exit 0 with one stderr line
    saying it did not check. A gate that cannot run must not block every new
    file; the fail-open is deliberate and named.
  - `improve-ground-skip` anywhere in the content bypasses it for that file.

Timing: improve_ground measured 0.55 to 1.08s per run on 2026-11-26. The
subprocess is capped at 5s and the hook is wired at timeout 10: a hook that
overruns its timeout is killed and its exit 2 is DISCARDED (fable-escalation.md,
measured 2026-08-03), so the cap must stay well inside the wired timeout.

HONEST BOUNDARY: it sees the Write tool only. A file created by Bash (cat >,
cp, a generator) is invisible to it. It grounds one sentence of intent, so a
docstring that does not say what the file does grounds nothing.

exit 0 = pass, exit 2 = block. stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKIP_MARKER = "improve-ground-skip"
SUBPROCESS_TIMEOUT = 5
MAX_IDEA_CHARS = 1200
IMPROVE_REL = "plugins/kipi-core/skills/improve/scripts/improve_ground.py"
# A path segment match, so worktrees (~/projects/kipi-wt-N/...) and instances
# are covered the same as the main checkout.
SCOPE_PATTERNS = (
    re.compile(r"/q-system/\.q-system/scripts/"),
    re.compile(r"/plugins/[^/]+/(hooks|scripts)/"),
)
TEST_NAME = re.compile(r"^(test[_-]|.*_test\.py$|conftest\.py$)")


def note(msg: str) -> None:
    print(f"improve-ground-gate: {msg}", file=sys.stderr)


def config_kipi_dir() -> str:
    return str(Path(os.path.expanduser("~/.config/kipi")).resolve()) + "/"


def is_in_scope(file_path: str) -> bool:
    p = str(Path(file_path).expanduser().resolve())
    if TEST_NAME.match(Path(p).name):
        return False
    if p.startswith(config_kipi_dir()):
        return True
    return any(rx.search(p) for rx in SCOPE_PATTERNS)


def header_text(content: str) -> str:
    """The module docstring, else the leading comment block (shebang skipped)."""
    m = re.match(r'\s*(?:#![^\n]*\n)?(?:\s*#[^\n]*\n)*\s*[rRuU]?("""|\'\'\')(.*?)\1',
                 content, re.S)
    if m and m.group(2).strip():
        return m.group(2).strip()
    lines = []
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("#!") and not lines:
            continue
        if s.startswith("#") or s.startswith("//"):
            lines.append(s.lstrip("#/ ").strip())
            continue
        if s == "" and not lines:
            continue
        break
    return " ".join(x for x in lines if x).strip()


def active_ticket_text(repo: Path) -> str:
    """Title of the active prd-os/kipi-dsse issue, or '' when none is active."""
    try:
        state = json.loads((repo / ".claude/state/active-issue.json").read_text())
    except (OSError, ValueError):
        return ""
    if not isinstance(state, dict) or not state.get("issue_id") or not state.get("spec_path"):
        return ""
    try:
        spec = (repo / state["spec_path"]).read_text()
    except OSError:
        return ""
    m = re.search(r"^title:\s*(.+)$", spec, re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def run_ground(script: Path, idea: str):
    """(verdict, cites) or (None, why-it-did-not-check)."""
    if not script.is_file():
        return None, f"improve_ground.py not found at {script}"
    try:
        proc = subprocess.run([sys.executable, str(script), "--target", "script", idea[:MAX_IDEA_CHARS]],
                              capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f"improve_ground.py took over {SUBPROCESS_TIMEOUT}s"
    except OSError as exc:
        return None, f"improve_ground.py did not start: {exc}"
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
        return None, f"improve_ground.py exit {proc.returncode}: {tail[0][:200]}"
    return out.get("verdict"), out.get("cites") or []


def decide(payload: dict, repo: Path, script: Path) -> int:
    if payload.get("tool_name") != "Write":
        return 0
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    content = tool_input.get("content") or ""
    if not file_path or Path(file_path).expanduser().exists() or not is_in_scope(file_path):
        return 0
    if SKIP_MARKER in content:
        return 0
    idea = active_ticket_text(repo) or header_text(content)
    if not idea:
        note(f"did not check {file_path}: no active ticket and no docstring or header comment")
        return 0
    verdict, detail = run_ground(script, idea)
    if verdict is None:
        note(f"did not check {file_path}: {detail}")
        return 0
    if verdict != "already-built":
        return 0
    cites = ", ".join(str(c) for c in detail) or "(no cite returned)"
    print(f"improve-ground-gate: BLOCKED new file {file_path}\n"
          f"improve_ground.py says this is already built: {cites}\n"
          f"Grounded on: {idea[:200]}\n"
          f"Open the cited file or lesson and extend it. If this file is truly new, "
          f"add the marker `{SKIP_MARKER}` with a one-line reason.", file=sys.stderr)
    return 2


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    repo = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    script = Path(os.environ.get("KIPI_IMPROVE_GROUND") or repo / IMPROVE_REL)
    try:
        return decide(payload if isinstance(payload, dict) else {}, repo, script)
    except Exception as exc:  # noqa: BLE001 - a crashing gate must not block every new file
        note(f"did not check: internal error {type(exc).__name__}: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
