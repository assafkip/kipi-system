#!/usr/bin/env python3
"""Self-test for new-view-gate.py. Runs the hook the way Claude Code does: as a
subprocess, hook JSON on stdin, a real JSONL transcript on disk.

Run: python3 test_new_view_gate.py   (exit 0 = all pass)
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).with_name("new-view-gate.py")
_n = 0


def use(name, inp, error=False):
    global _n
    _n += 1
    tid = f"t{_n}"
    rows = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}]
    rows.append({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "is_error": error}]}})
    return rows


def run(tmp, calls, tool, inp, env_extra=None):
    tr = Path(tmp) / f"tr{_n}.jsonl"
    tr.write_text("\n".join(json.dumps(r) for c in calls for r in c))
    env = {k: v for k, v in os.environ.items() if k != "NEW_VIEW_GATE_OFF"}
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(
        {"tool_name": tool, "tool_input": inp, "transcript_path": str(tr)}),
        capture_output=True, text=True, env=env)
    return p.returncode


def main():
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: exit {got}, want {want}")

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        src = str(t / "app.py")
        tst = str(t / "tests" / "test_app.py")
        add1 = {"file_path": tst, "old_string": "x = 1",
                "new_string": "x = 1\ndef test_a():\n    pass"}
        add2 = {"file_path": tst, "old_string": "def test_a():",
                "new_string": "def test_a():\n    pass\ndef test_b():"}

        # 1. first test of a session with no view at all: blocked
        check("no view, first test", run(tmp, [], "Edit", add1), 2)
        # 2. read the code first: allowed
        check("code read first", run(tmp, [use("Read", {"file_path": src})], "Edit", add1), 0)
        # 3. reading only a TEST file is not a view
        check("test-file read only", run(tmp, [use("Read", {"file_path": tst})], "Edit", add1), 2)
        # 4. second test right after the first, no new view: blocked (the loop)
        hist = [use("Read", {"file_path": src}), use("Edit", add1)]
        check("second test same view", run(tmp, hist, "Edit", add2), 2)
        # 5. re-reading the SAME file is the same view: blocked
        check("same file re-read", run(tmp, hist + [use("Read", {"file_path": src})], "Edit", add2), 2)
        # 6. a fresh agent between: allowed
        check("new agent", run(tmp, hist + [use("Agent", {"prompt": "why does app fail"})], "Edit", add2), 0)
        # 7. a KB lookup between: allowed
        check("kb lookup", run(tmp, hist + [use("mcp__miyo__search", {"query": "app"})], "Edit", add2), 0)
        # 8. a canonical file between: allowed
        check("canonical", run(tmp, hist + [use("Read", {"file_path": "/r/canonical/decisions.md"})], "Edit", add2), 0)
        # 9. an add that was REFUSED does not reset the clock
        hist_ref = [use("Read", {"file_path": src}), use("Edit", add1, error=True)]
        check("refused add not counted", run(tmp, hist_ref, "Edit", add2), 0)
        # 10. editing a test without adding one: allowed
        check("edit no add", run(tmp, [], "Edit", {"file_path": tst, "old_string": "def test_a():\n  x=1",
                                                   "new_string": "def test_a():\n  x=2"}), 0)
        # 11. non-test source edit: never gated
        check("source edit", run(tmp, [], "Edit", {"file_path": src, "old_string": "a", "new_string": "def test_x():"}), 0)
        # 12. a NEW test file via Write: gated
        check("new test file", run(tmp, [], "Write", {"file_path": str(t / "b.test.ts"),
                                                      "content": "it('works', () => {})"}), 2)
        # 13. a new phase in a plan: gated without a view, allowed with one
        plan = {"file_path": "/r/plans/p.md", "old_string": "## Phase 1: a",
                "new_string": "## Phase 1: a\n## Phase 2: b"}
        check("phase no view", run(tmp, [], "Edit", plan), 2)
        check("phase with view", run(tmp, [use("Grep", {"pattern": "foo", "path": "/r/src"})], "Edit", plan), 0)
        # 14. js, go, bash test shapes count
        for name, body in [("x.spec.js", "test('a', () => {})"),
                           ("x_test.go", "func TestA(t *testing.T) {"),
                           ("test-x.sh", "test_a() {")]:
            check(f"shape {name}", run(tmp, [], "Edit", {"file_path": f"/r/{name}", "old_string": "",
                                                          "new_string": body}), 2)
        # 14b. a past Write of a check()-style test file (no defs) still counts as an add
        wrote = [use("Read", {"file_path": src}),
                 use("Write", {"file_path": str(t / "test_gate.py"), "content": "check('a', 1, 1)"})]
        check("past check-style write", run(tmp, wrote, "Edit", add1), 2)
        # 14c. review of #512: conftest/fixtures in tests/ are not test adds; prose "Phase 2" is not a phase
        check("new conftest", run(tmp, [], "Write", {"file_path": str(t / "tests" / "conftest.py"), "content": "import os"}), 0)
        check("new fixture", run(tmp, [], "Write", {"file_path": str(t / "tests" / "data.json"), "content": "{}"}), 0)
        check("prose phase", run(tmp, [], "Edit", {"file_path": "/r/h.md", "old_string": "",
                                                    "new_string": "Phase 2 shipped today."}), 0)
        check("bold list phase", run(tmp, [], "Edit", {"file_path": "/r/h.md", "old_string": "",
                                                        "new_string": "- **Phase 2**: build"}), 2)
        # 15. no transcript: fail open
        p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(
            {"tool_name": "Edit", "tool_input": add1, "transcript_path": str(t / "none")}),
            capture_output=True, text=True)
        check("no transcript", p.returncode, 0)
        # 16. kill switch
        check("kill switch", run(tmp, [], "Edit", add1, {"NEW_VIEW_GATE_OFF": "1"}), 0)

    for f in fails:
        print("FAIL", f)
    print(f"{'FAILED' if fails else 'PASSED'}: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
