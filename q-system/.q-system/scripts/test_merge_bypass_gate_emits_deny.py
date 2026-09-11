#!/usr/bin/env python3
"""A classified bypass must actually EMIT a deny. End-to-end, via stdin (ASK-1136).

WHY THIS EXISTS. merge-bypass-gate.py had five test suites and none of them could
tell whether the gate denies anything. Measured 2026-08-29 on a clean origin/main
at 896b0e5a: changing

    "permissionDecision": "deny"   ->   "allow"

so the gate denies NOTHING, ever, left all five suites GREEN.

The reason is structural, not sloppiness. Every existing suite calls
`classify(command, cwd)` directly and asserts the returned label. That is the
PARSER, and it is thoroughly tested. Nothing invoked the gate the way the hook
does -- JSON on stdin, decision on stdout -- so the EMITTER had no coverage at
all, and the gap was invisible because five files full of careful assertions
looked like thorough coverage of the whole gate.

This gate decides whether a merge can bypass review. It is live and it works: it
refused `gh pr merge --repo ... --squash --delete-branch=false` on 2026-08-29 and
named the sanctioned form. The gate being correct was never in question. What was
missing is anything that would notice if it stopped being correct.

So this file asserts the seam the others skip, and ONLY that seam. It does not
re-test classification; classify() has five suites already.

Isolation: builds throwaway git repos in a tmpdir, runs the gate as a subprocess
with a synthetic PreToolUse payload, and touches no network, no real repo, and
no commit status.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = Path(__import__("os").environ.get("MERGE_BYPASS_GATE", HERE / "merge-bypass-gate.py"))

FAILURES: list[str] = []
CHECKS = 0


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True, text=True)


def _make_repo(root: Path, name: str, origin: str, branch: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "remote", "add", "origin", origin)
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-q", "-b", branch)
    return repo


def run_gate(command: str, cwd: Path) -> tuple[int, str]:
    """Drive the gate exactly as the hook runner does."""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    p = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout


def decision_of(stdout: str) -> str:
    """`allow` is SILENCE by contract, so empty stdout means allow."""
    if not stdout.strip():
        return "allow"
    try:
        return (json.loads(stdout).get("hookSpecificOutput") or {}).get("permissionDecision", "?")
    except json.JSONDecodeError:
        return "unparseable"


def check(name: str, got: str, want: str, extra: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{name}\n    want: {want}\n    got : {got}\n    {extra}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo = _make_repo(root, "prot", "https://github.com/assafkip/kipi-system.git", "feature")

        # A shape the classifier calls a bypass MUST come back as an emitted deny.
        # This is the assertion whose absence let the mutant live.
        rc, out = run_gate("gh pr merge --admin 1", repo)
        check("an --admin merge emits permissionDecision=deny", decision_of(out), "deny",
              f"rc={rc} stdout={out[:120]!r}")

        # The deny must also be well-formed for the runner, not merely non-empty:
        # a malformed payload is not a refusal, it is an ignored hook.
        rc, out = run_gate("gh pr merge --admin 1", repo)
        check("the deny payload parses as JSON", decision_of(out) != "unparseable" and "ok" or "bad",
              "ok", f"stdout={out[:120]!r}")
        check("the deny names the gate so the operator can act",
              "merge-bypass-gate" in out and "ok" or "missing", "ok")

        # EXIT 0 EITHER WAY IS THE CONTRACT, and it is why exit-code mutation was
        # inconclusive on this gate. Pinned so nobody "fixes" it into exit 2 and
        # silently changes how the runner treats the hook.
        check("a deny still exits 0 (decision lives in stdout, not the code)",
              str(rc), "0")

        # The other direction, so the test can distinguish. Without this a gate
        # that denied EVERYTHING would also pass every assertion above.
        rc, out = run_gate("gh pr merge --auto --squash 1", repo)
        check("the sanctioned form is allowed (silence)", decision_of(out), "allow",
              f"rc={rc} stdout={out[:120]!r}")
        check("an allow exits 0", str(rc), "0")

        # A non-Bash tool must be ignored outright, or the gate would be
        # adjudicating events it knows nothing about.
        p = subprocess.run([sys.executable, str(GATE)],
                           input=json.dumps({"tool_name": "Read", "tool_input": {}}),
                           capture_output=True, text=True, timeout=60)
        check("a non-Bash tool is passed through", decision_of(p.stdout), "allow")

    print()
    if FAILURES:
        for f in FAILURES:
            print(f"  FAIL {f}")
        print(f"\nFAILED: {len(FAILURES)} of {CHECKS}")
        return 1
    print(f"PASS: {CHECKS} checks green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
