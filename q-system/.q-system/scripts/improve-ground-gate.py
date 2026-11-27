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
    q-system/.q-system/scripts/, plugins/<group>/hooks/, plugins/<group>/scripts/,
    or ~/.config/kipi/ (its top level, or a <dir>/hooks/ or <dir>/scripts/ under
    it). Edits and overwrites fast-exit 0.
  - out of scope: test files (a test's docstring describes the thing it tests,
    which by definition exists), and scratch space: $TMPDIR, and
    ~/.config/kipi/review-trees|review-scratch. PR #892 round 1: the review
    harness points TMPDIR at ~/.config/kipi/review-scratch, and a whole-subtree
    scope blocked a reviewer's one-line repro file.
  - it grounds BOTH the session's active ticket (.claude/state/active-issue.json,
    the store prd-os and kipi-dsse both write; its spec's title) AND the new
    file's docstring or leading comment block, each separately. PR #892 round 1:
    `ticket or docstring` let a ticket title replace the file, so an exact
    duplicate passed for the whole life of a ticketed run, which is the scar.
  - it blocks (exit 2) only when an `already-built` verdict cites an existing
    CODE file (a script or hook), and names that file. A verdict that cites only
    a lesson or a memory/markdown file prints one advisory line and exits 0.
    Measured 2026-11-26: over 55 real scripts from the last 60 commits, 10 got
    `already-built`, and every lesson-only cite among them was a HOW lesson near
    the theme, not a duplicate implementation (ASK-5805 owns improve_ground's
    precision). A gate that blocks 18% of honest new files gets stamped with its
    skip marker everywhere, which turns it off without anyone deciding to.
  - any other verdict, no text to ground, improve_ground missing, failing,
    unparseable or over its time budget -> exit 0 with one stderr line saying it
    did not check. A gate that cannot run must not block every new file; the
    fail-open is deliberate and named.
  - `improve-ground-skip` anywhere in the content bypasses it for that file.

Timing: improve_ground measured 0.55 to 1.08s per run on 2026-11-26; the full
hook 0.64 to 0.69s. Up to two runs share TOTAL_BUDGET (7s) and the hook is wired
at timeout 10: a hook that overruns its timeout is killed and its exit 2 is
DISCARDED (fable-escalation.md, measured 2026-08-03), so the budget must stay
inside the wired timeout.

HONEST BOUNDARY: it sees the Write tool only. A file created by Bash (cat >,
cp, a generator) is invisible to it. With no ticket active it grounds only the
file's own header, so a file whose header does not say what it does grounds
nothing. A file format with no comment syntax (JSON) cannot carry the skip
marker.

exit 0 = pass, exit 2 = block. stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SKIP_MARKER = "improve-ground-skip"
TOTAL_BUDGET = 7.0
MAX_IDEA_CHARS = 1200
IMPROVE_REL = "plugins/kipi-core/skills/improve/scripts/improve_ground.py"
CODE_SUFFIXES = {".py", ".sh", ".js", ".mjs", ".ts", ".rb", ".pl", ".plist"}
# A path segment match, so worktrees (~/projects/kipi-wt-N/...) and instances
# are covered the same as the main checkout.
SCOPE_PATTERNS = (
    re.compile(r"/q-system/\.q-system/scripts/"),
    re.compile(r"/plugins/[^/]+/(hooks|scripts)/"),
)
CONFIG_SUBDIR = re.compile(r"^[^/]+/(hooks|scripts)/")
CONFIG_SCRATCH = ("review-trees/", "review-scratch/")
TEST_NAME = re.compile(r"^(test[_-]|.*_test\.py$|conftest\.py$)")


def note(msg: str) -> None:
    print(f"improve-ground-gate: {msg}", file=sys.stderr)


def _resolved(path: str) -> str:
    return str(Path(os.path.expanduser(path)).resolve())


def _under(path: str, root: str) -> bool:
    return path.startswith(root.rstrip("/") + "/")


def config_kipi_scope(p: str):
    """True/False when p is under ~/.config/kipi, None when it is not."""
    root = _resolved("~/.config/kipi")
    if not _under(p, root):
        return None
    rel = p[len(root) + 1:]
    if rel.startswith(CONFIG_SCRATCH):
        return False
    return "/" not in rel or bool(CONFIG_SUBDIR.match(rel))


def is_in_scope(file_path: str) -> bool:
    p = _resolved(file_path)
    if TEST_NAME.match(Path(p).name):
        return False
    tmp = os.environ.get("TMPDIR")
    if tmp and _under(p, _resolved(tmp)):
        return False
    in_config = config_kipi_scope(p)
    if in_config is not None:
        return in_config
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


def run_ground(script: Path, idea: str, budget: float):
    """(verdict, cites) or (None, why-it-did-not-check)."""
    if not script.is_file():
        return None, f"improve_ground.py not found at {script}"
    if budget <= 0.5:
        return None, f"no time left in the {TOTAL_BUDGET}s budget"
    try:
        proc = subprocess.run([sys.executable, str(script), "--target", "script", idea[:MAX_IDEA_CHARS]],
                              capture_output=True, text=True, timeout=budget)
    except subprocess.TimeoutExpired:
        return None, f"improve_ground.py took over {budget:.1f}s"
    except OSError as exc:
        return None, f"improve_ground.py did not start: {exc}"
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
        return None, f"improve_ground.py exit {proc.returncode}: {tail[0][:200]}"
    return out.get("verdict"), out.get("cites") or []


def _display(cite: str, roots: list) -> str:
    """A cite as a repo-relative path, so the message never carries one tree's
    absolute path into the next agent's instruction (PR #892 round 1)."""
    p = Path(cite)
    for root in roots:
        try:
            return str(p.resolve().relative_to(root.resolve()))
        except (ValueError, OSError):
            continue
    return cite


def code_cites(cites: list, roots: list) -> list:
    """The cites that name an existing script or hook, never a lesson or a .md."""
    found = []
    for cite in cites:
        p = Path(cite)
        candidates = [p] if p.is_absolute() else [r / p for r in roots]
        if p.suffix in CODE_SUFFIXES and any(c.is_file() for c in candidates):
            found.append(_display(str(cite), roots))
    return found


def _ideas(repo: Path, content: str) -> list:
    pairs = [("active ticket", active_ticket_text(repo)), ("file header", header_text(content))]
    return [(src, text) for src, text in pairs if text]


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
    ideas = _ideas(repo, content)
    if not ideas:
        note(f"did not check {file_path}: no active ticket and no docstring or header comment")
        return 0
    roots = [repo] + [script.resolve().parents[5]] * (len(script.resolve().parents) > 5)
    deadline = time.monotonic() + TOTAL_BUDGET
    for source, idea in ideas:
        verdict, detail = run_ground(script, idea, deadline - time.monotonic())
        if verdict is None:
            note(f"did not check {file_path} ({source}): {detail}")
            continue
        if verdict != "already-built":
            continue
        built = code_cites(detail, roots)
        if not built:
            shown = ", ".join(_display(str(c), roots) for c in detail) or "(no cite)"
            note(f"advisory, not blocking: the {source} is near {shown}; read it before building")
            continue
        print(f"improve-ground-gate: BLOCKED new file {file_path}\n"
              f"improve_ground.py says this is already built: {', '.join(built)}\n"
              f"Grounded on the {source}: {idea[:200]}\n"
              f"Open the cited file and extend it. If this file is truly new, "
              f"add the marker `{SKIP_MARKER}` with a one-line reason.", file=sys.stderr)
        return 2
    return 0


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
