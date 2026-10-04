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


def use(name, inp, error=False, result=None):
    global _n
    _n += 1
    tid = f"t{_n}"
    rows = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}]
    user = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "is_error": error}]}}
    if result is not None:
        # Claude Code stores the Write outcome here: type create|update + originalFile.
        user["toolUseResult"] = result
    rows.append(user)
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


def run_err(tmp, calls, tool, inp):
    tr = Path(tmp) / f"tre{_n}.jsonl"
    tr.write_text("\n".join(json.dumps(r) for c in calls for r in c))
    env = {k: v for k, v in os.environ.items() if k != "NEW_VIEW_GATE_OFF"}
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(
        {"tool_name": tool, "tool_input": inp, "transcript_path": str(tr)}),
        capture_output=True, text=True, env=env)
    return p.returncode, p.stderr


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
        # 14d. review of #512: a shell read of the code is a view; a test run is not
        check("bash grep of code", run(tmp, hist + [use("Bash", {"command": "grep -n foo src/app.py"})], "Edit", add2), 0)
        check("bash cat of test only", run(tmp, hist + [use("Bash", {"command": "cat tests/test_app.py"})], "Edit", add2), 2)
        check("pytest is not a view", run(tmp, hist + [use("Bash", {"command": "pytest src/app.py -q"})], "Edit", add2), 2)
        # 14e. ASK-2473: running a test file directly is a test run, not a view,
        # even when the command also names a non-test path (cd, a tail pipe)
        check("direct python test run", run(tmp, hist + [use("Bash", {
            "command": "cd ~/projects/r && python3 plugins/k/hooks/test_app.py 2>&1 | tail -3"})], "Edit", add2), 2)
        check("direct bash test run", run(tmp, hist + [use("Bash", {
            "command": "cd ~/projects/r && bash scripts/test-app.sh | tail -5"})], "Edit", add2), 2)
        check("python -m pytest run", run(tmp, hist + [use("Bash", {
            "command": "cd ~/projects/r && python3 -m pytest -q src/app.py | tail -3"})], "Edit", add2), 2)
        # 14f. ASK-2473: no prior addition means the message must not claim one
        rc, err = run_err(tmp, [], "Edit", add1)
        check("first-add message", (rc, "no view was taken yet this session" in err,
                                    "since the last" in err), (2, True, False))
        rc, err = run_err(tmp, hist, "Edit", add2)
        check("later-add message", (rc, "since the last" in err), (2, True))
        # 14g. ASK-2472: a non-dict JSONL record is skipped, not a crash
        check("non-dict record skipped", run(tmp, [[[1, 2], "s", 3]], "Edit", add1), 2)
        check("non-dict record + view", run(tmp, [[[1, 2]], use("Read", {"file_path": src})], "Edit", add1), 0)
        # 14h. ASK-2472: a past Write that REWROTE a test file without new defs is
        # not an addition; its stored originalFile decides
        body = "def test_a():\n    pass\n"
        same = [use("Read", {"file_path": src}),
                use("Write", {"file_path": tst, "content": body},
                    result={"type": "update", "filePath": tst, "originalFile": body})]
        check("past rewrite no new defs", run(tmp, same, "Edit", add2), 0)
        grew = [use("Read", {"file_path": src}),
                use("Write", {"file_path": tst, "content": body + "def test_b():\n    pass\n"},
                    result={"type": "update", "filePath": tst, "originalFile": body})]
        check("past rewrite with new def", run(tmp, grew, "Edit", add2), 2)
        made = [use("Read", {"file_path": src}),
                use("Write", {"file_path": tst, "content": "check('a', 1, 1)"},
                    result={"type": "create", "filePath": tst, "originalFile": None})]
        check("past create counts", run(tmp, made, "Edit", add2), 2)
        # 14i. sp-df1f13a5 nit 1: a code read chained with a test run keeps the read credit
        check("read && test run", run(tmp, hist + [use("Bash", {
            "command": "git diff src/app.py && python3 tests/test_app.py"})], "Edit", add2), 0)
        check("test run ; read", run(tmp, hist + [use("Bash", {
            "command": "python3 tests/test_app.py; cat src/app.py"})], "Edit", add2), 0)
        check("test run piped to tail", run(tmp, hist + [use("Bash", {
            "command": "python3 tests/test_app.py | tail -3"})], "Edit", add2), 2)
        # 14j. sp-df1f13a5 nit 2: suite runners are test runs, not views
        for cmd in ["bash q-system/.q-system/verify.sh --changed --base origin/main | tail",
                    "bash scripts/ci-shaped-run.sh --all 2>&1 | tail -3",
                    "./run-tests.sh src/app.py | tail", "cd src/app.d && make test 2>&1 | tail -5",
                    "npm test -- src/app.js | tail"]:
            check(f"suite runner: {cmd[:30]}", run(tmp, hist + [use("Bash", {"command": cmd})], "Edit", add2), 2)
        # 14k. sp-df1f13a5 nit 3: a past check()-style rewrite that adds checks resets
        # the clock; one that adds none does not; an EMPTY stored original still counts
        cbody = "check('a', 1, 1)\n"
        cgrew = [use("Read", {"file_path": src}),
                 use("Write", {"file_path": tst, "content": cbody + "check('b', 2, 2)\n"},
                     result={"type": "update", "filePath": tst, "originalFile": cbody})]
        check("past check-style rewrite adds checks", run(tmp, cgrew, "Edit", add2), 2)
        csame = [use("Read", {"file_path": src}),
                 use("Write", {"file_path": tst, "content": cbody},
                     result={"type": "update", "filePath": tst, "originalFile": cbody})]
        check("past check-style rewrite no new checks", run(tmp, csame, "Edit", add2), 0)
        cempty = [use("Read", {"file_path": src}),
                  use("Write", {"file_path": tst, "content": cbody},
                      result={"type": "update", "filePath": tst, "originalFile": ""})]
        check("past write over empty original", run(tmp, cempty, "Edit", add2), 2)
        # 14l. sp-df1f13a5 nit 4: an internal bug fails open AND names itself on stderr
        rc, err = run_err(tmp, [[{"type": "user", "message": {"content": 5}}]], "Edit", add1)
        check("internal error is loud", (rc, len(err.strip().splitlines()), "TypeError" in err), (0, 1, True))
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
