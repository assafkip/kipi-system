"""Tests for ruling-gate.py (ASK-4382, RULE-2026-11-10-RULING).

Every case runs a COPY of the gate inside tmp_path, with HOME pointed at a fake
home, so no test reads or writes a live settings file, LaunchAgent, state dir
or scope file. The case and its enforcers live in a throwaway git repo.

Negative self-tests first: each refusal is shown to fire on the bad input
before the matching good input is shown to pass, so a green run is not a gate
that cannot fail.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GATE_SRC = Path(__file__).resolve().parents[1] / "scripts" / "ruling-gate.py"
REPO_BASELINE = Path(__file__).resolve().parents[1] / "ruling-gate-baseline.json"
CASE = "case-007-demo"
KEY = f"{CASE}:R-01"
R1 = 'RULING: R-01 | 2026-11-10 | other | "only tools that fit the case run"'
R2 = 'RULING: R-02 | 2026-11-10 | other | "the export is in scope"'
OLD_DATE = "2026-01-01T00:00:00"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


class Box:
    def __init__(self, tmp):
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        q = tmp / "skel" / "q-system" / ".q-system"
        (q / "scripts").mkdir(parents=True)
        self.gate = q / "scripts" / "ruling-gate.py"
        shutil.copy(GATE_SRC, self.gate)
        self.baseline = q / "ruling-gate-baseline.json"
        self.baseline.write_text(json.dumps({"hashes": []}))
        self.repo = tmp / "inst"
        (self.repo / "inv" / CASE / "canonical").mkdir(parents=True)
        _git(self.repo, "init", "-q")
        self.scope = self.repo / "inv" / CASE / "canonical" / "scope.md"
        self.scope.write_text("# Scope\n\nSome case text.\n")
        self.env = dict(os.environ, HOME=str(self.home))
        self.env.pop("CLAUDE_PROJECT_DIR", None)

    def code(self, rel, body, track=False):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        if track:
            _git(self.repo, "add", rel)
        return p

    def hook(self, event, tool, tin, tool_use_id="t1"):
        payload = {"hook_event_name": event, "tool_name": tool, "tool_input": tin,
                   "cwd": str(self.repo), "session_id": "s1", "tool_use_id": tool_use_id}
        r = subprocess.run([sys.executable, str(self.gate)], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env, timeout=60)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    def write(self, content):
        out = self.hook("PreToolUse", "Write", {"file_path": str(self.scope), "content": content})
        if not out:
            return "ALLOW", ""
        d = json.loads(out)["hookSpecificOutput"]
        assert d["permissionDecision"] == "deny"
        return "DENY", d["permissionDecisionReason"]

    def cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(self.gate), *args], capture_output=True, text=True,
                              env=self.env, timeout=60, cwd=cwd or str(self.tmp))

    def commit(self, msg, old=True):
        # A pulled or checked-out commit predates the call that brings it in; one
        # made inside the call does not. OLD dates stand for the former.
        env = dict(self.env, GIT_AUTHOR_DATE=OLD_DATE, GIT_COMMITTER_DATE=OLD_DATE) if old else self.env
        for a in (["add", "-A", "inv"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg]):
            subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True, env=env)

    def status(self):
        return subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True,
                              text=True, check=True).stdout.strip()

    def grandfather(self, *lines):
        hashes = [hashlib.sha256((CASE + "\n" + " ".join(l.split())).encode()).hexdigest()[:16] for l in lines]
        self.baseline.write_text(json.dumps({"hashes": hashes}))


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def scope_with(*lines):
    return "# Scope\n\nSome case text.\n\n" + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the four required cases
def test_ruling_with_no_enforcer_is_refused(box):
    verdict, why = box.write(scope_with(R1))
    assert verdict == "DENY" and "no ENFORCED-BY line" in why and KEY in why


def test_enforcer_that_lacks_the_id_is_refused_then_passes_with_it(box):
    box.code("tests/test_r01.py", "# enforces something else entirely\n", track=True)
    verdict, why = box.write(scope_with(R1, "ENFORCED-BY: R-01 | tests/test_r01.py"))
    assert verdict == "DENY" and f"does not contain {KEY}" in why
    box.code("tests/test_r01.py", f"# {KEY}: only tools that fit the case run\n", track=True)
    assert box.write(scope_with(R1, "ENFORCED-BY: R-01 | tests/test_r01.py"))[0] == "ALLOW"


def test_bare_ruling_id_is_not_the_case_qualified_id(box):
    box.code("tests/test_r01.py", "# R-01 of some case\n", track=True)
    verdict, why = box.write(scope_with(R1, "ENFORCED-BY: R-01 | tests/test_r01.py"))
    assert verdict == "DENY" and "does not contain" in why


def test_unenforced_passes_the_write_and_shows_in_the_debt_listing(box):
    line = "UNENFORCED: R-01 | no tool call to hook; the founder decides it in conversation"
    assert box.write(scope_with(R1, line))[0] == "ALLOW"
    box.scope.write_text(scope_with(R1, line))
    stub = box.code("notify_stub.sh", f'echo "$1" >> "{box.tmp}/alerts.txt"\n')
    out = box.tmp / "debt.md"
    r = box.cli("--report", "--baseline", str(box.baseline), "--notify", str(stub), "--out", str(out), str(box.repo))
    assert r.returncode == 0, r.stderr
    assert f"UNENFORCED {KEY}" in out.read_text()
    alerts = (box.tmp / "alerts.txt").read_text()
    assert "1 UNENFORCED" in alerts and KEY in alerts


# ---------------------------------------------------------------- resolution rules
def test_unwired_enforcer_is_refused_until_it_is_a_tracked_test(box):
    box.code("lib/enforce_r01.py", f"# {KEY}\n")
    verdict, why = box.write(scope_with(R1, "ENFORCED-BY: R-01 | lib/enforce_r01.py"))
    assert verdict == "DENY" and "no named enforcer is wired" in why
    box.code("tests/test_r01.py", f"# {KEY}\n")  # a test, but untracked: still not wired
    assert box.write(scope_with(R1, "ENFORCED-BY: R-01 | lib/enforce_r01.py, tests/test_r01.py"))[0] == "DENY"
    _git(box.repo, "add", "tests/test_r01.py")
    assert box.write(scope_with(R1, "ENFORCED-BY: R-01 | lib/enforce_r01.py, tests/test_r01.py"))[0] == "ALLOW"


def test_settings_hook_counts_as_wired(box):
    box.code("hooks/r01_hook.py", f"# {KEY}\n")
    settings = box.repo / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
        {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/hooks/r01_hook.py"'}]}]}}))
    assert box.write(scope_with(R1, "ENFORCED-BY: R-01 | hooks/r01_hook.py"))[0] == "ALLOW"


def test_missing_noncode_and_temp_enforcers_are_refused(box, tmp_path_factory):
    assert "does not exist" in box.write(scope_with(R1, "ENFORCED-BY: R-01 | tests/nope.py"))[1]
    box.code("tests/notes.md", f"{KEY}\n", track=True)
    assert "is not code" in box.write(scope_with(R1, "ENFORCED-BY: R-01 | tests/notes.md"))[1]
    stub = tmp_path_factory.mktemp("elsewhere") / "test_stub.py"
    stub.write_text(f"# {KEY}\n")
    assert "temp-space" in box.write(scope_with(R1, f"ENFORCED-BY: R-01 | {stub}"))[1]


def test_ambiguous_or_thin_declarations_are_refused(box):
    box.code("tests/test_r01.py", f"# {KEY}\n", track=True)
    both = scope_with(R1, "ENFORCED-BY: R-01 | tests/test_r01.py", "UNENFORCED: R-01 | a long enough reason here")
    assert "both ENFORCED-BY and UNENFORCED" in box.write(both)[1]
    assert "at least 20 characters" in box.write(scope_with(R1, "UNENFORCED: R-01 | later"))[1]
    assert "malformed" in box.write(scope_with(R1, "Enforced-By: R-01 tests/test_r01.py"))[1]


def test_prose_that_starts_with_ruling_is_not_a_ruling(box):
    assert box.write(scope_with("Ruling: the founder decided this in the call notes."))[0] == "ALLOW"
    assert "malformed" in box.write(scope_with("RULING: R-1 | 2026-11-10 | other | \"x\""))[1]


def test_nested_repo_is_not_walked(box):
    nested = box.repo / "projects" / "other"
    (nested / CASE / "canonical").mkdir(parents=True)
    _git(nested, "init", "-q")
    (nested / CASE / "canonical" / "scope.md").write_text(scope_with(R1))
    box.hook("PreToolUse", "Bash", {"command": "x"}, tool_use_id="t9")
    snap = next((box.home / ".local" / "state" / "kipi" / "ruling-gate" / "snap").glob("*t9.json"))
    assert list(json.loads(snap.read_text())) == [str(box.scope)]


def test_edit_tool_is_judged_on_the_result(box):
    tin = {"file_path": str(box.scope), "old_string": "Some case text.", "new_string": "Some case text.\n" + R1}
    out = box.hook("PreToolUse", "Edit", tin)
    assert '"deny"' in out


# ---------------------------------------------------------------- grandfathering and debt
def test_grandfathered_ruling_passes_untouched_and_fails_once_changed(box):
    box.grandfather(R1)
    box.scope.write_text(scope_with(R1))
    assert box.write(scope_with(R1) + "\nmore notes\n")[0] == "ALLOW"
    changed = R1.replace("only tools", "all tools")
    assert box.write(scope_with(changed))[0] == "DENY"


def test_dropping_a_declaration_is_refused(box):
    box.grandfather(R1)
    line = "UNENFORCED: R-01 | no tool call to hook; decided in conversation"
    box.scope.write_text(scope_with(R1, line))
    verdict, why = box.write(scope_with(R1))
    assert verdict == "DENY" and "drops the ruling's" in why


def test_baseline_file_cannot_be_edited_through_the_gate(box):
    out = box.hook("PreToolUse", "Write", {"file_path": str(box.baseline), "content": '{"hashes": ["x"]}'})
    assert '"deny"' in out


# ---------------------------------------------------------------- shell writes
def test_shell_write_of_an_unenforced_ruling_is_reverted(box):
    box.grandfather(R1)
    box.scope.write_text(scope_with(R1))
    assert box.hook("PreToolUse", "Bash", {"command": "x"}) == ""
    changed = R1.replace("only tools", "all tools")
    r2 = 'RULING: R-02 | 2026-11-10 | other | "a brand new decision"'
    box.scope.write_text(scope_with(changed, r2))  # what a shell redirect would do
    out = json.loads(box.hook("PostToolUse", "Bash", {"command": "x"}))
    assert out["decision"] == "block" and "reverted 2 ruling(s)" in out["reason"]
    text = box.scope.read_text()
    assert R1 in text and "all tools" not in text and "R-02" not in text
    saved = list((box.home / ".local" / "state" / "kipi" / "ruling-gate" / "quarantine").iterdir())
    assert len(saved) == 1 and "a brand new decision" in saved[0].read_text()


def test_shell_write_of_an_enforced_ruling_stays(box):
    box.code("tests/test_r01.py", f"# {KEY}\n", track=True)
    box.hook("PreToolUse", "Bash", {"command": "x"}, tool_use_id="t2")
    box.scope.write_text(scope_with(R1, "ENFORCED-BY: R-01 | tests/test_r01.py"))
    assert box.hook("PostToolUse", "Bash", {"command": "x"}, tool_use_id="t2") == ""
    assert R1 in box.scope.read_text()


# PR #729 review, finding 2: judged by effect, a git checkout or ff merge looked like
# a shell write, and the repair rewrote a tracked client scope.md.
def test_git_checkout_of_a_committed_version_is_not_repaired(box):
    box.code("tests/test_r01.py", f"# {KEY}\n", track=True)
    box.scope.write_text(scope_with(R1))
    box.commit("older")
    _git(box.repo, "branch", "older")
    box.scope.write_text(scope_with(R1, "ENFORCED-BY: R-01 | tests/test_r01.py"))
    box.commit("declared")
    box.hook("PreToolUse", "Bash", {"command": "git checkout older"}, tool_use_id="t3")
    _git(box.repo, "checkout", "-q", "older")
    assert box.hook("PostToolUse", "Bash", {"command": "git checkout older"}, tool_use_id="t3") == ""
    assert "ENFORCED-BY" not in box.scope.read_text() and box.status() == ""


def test_git_ff_merge_of_a_colleagues_ruling_is_not_deleted(box):
    box.grandfather(R1)
    box.scope.write_text(scope_with(R1))
    box.commit("base")
    _git(box.repo, "checkout", "-qb", "colleague")
    box.scope.write_text(scope_with(R1, R2))
    box.commit("colleague adds R-02, no enforcer yet")
    _git(box.repo, "checkout", "-q", "-")
    box.hook("PreToolUse", "Bash", {"command": "git merge"}, tool_use_id="t4")
    _git(box.repo, "merge", "--ff-only", "-q", "colleague")
    assert box.hook("PostToolUse", "Bash", {"command": "git merge"}, tool_use_id="t4") == ""
    assert R2 in box.scope.read_text() and box.status() == ""


def test_write_and_commit_inside_the_call_is_still_reverted(box):
    # Negative self-test for the skip above: "matches HEAD" alone would let this through.
    box.grandfather(R1)
    box.scope.write_text(scope_with(R1))
    box.commit("base")
    box.hook("PreToolUse", "Bash", {"command": "x"}, tool_use_id="t5")
    box.scope.write_text(scope_with(R1, R2))
    box.commit("sneak", old=False)
    out = json.loads(box.hook("PostToolUse", "Bash", {"command": "x"}, tool_use_id="t5"))
    assert out["decision"] == "block" and "reverted 1 ruling(s)" in out["reason"]
    assert "R-02" not in box.scope.read_text()


# ---------------------------------------------------------------- the scheduled report
def test_report_lists_debt_alerts_once_and_fails_loudly(box):
    box.grandfather(R1)
    box.scope.write_text(scope_with(R1))
    stub = box.code("notify_stub.sh", f'echo "$1" >> "{box.tmp}/alerts.txt"\n')
    args = ("--report", "--baseline", str(box.baseline), "--notify", str(stub), "--out", str(box.tmp / "d.md"),
            str(box.repo))
    assert box.cli(*args).returncode == 0
    assert box.cli(*args).returncode == 0
    alerts = (box.tmp / "alerts.txt").read_text().splitlines()
    assert len(alerts) == 1 and "1 grandfathered DEBT" in alerts[0]  # same state: one alert
    box.scope.write_text(scope_with(R1, 'RULING: R-02 | 2026-11-10 | other | "new"'))
    broken = box.code("notify_broken.sh", "exit 1\n")
    r = box.cli("--report", "--baseline", str(box.baseline), "--notify", str(broken), "--out",
                str(box.tmp / "d.md"), str(box.repo))
    assert r.returncode == 1 and "not filed" in r.stderr
    assert "FAIL " + f"{CASE}:R-02" in (box.tmp / "d.md").read_text()


def test_report_refuses_without_a_baseline(box):
    r = box.cli("--report", "--baseline", str(box.tmp / "missing.json"), "--no-alert", str(box.repo))
    assert r.returncode == 1 and "baseline" in r.stderr


def test_cli_bad_paths_give_a_message_not_a_traceback(box):
    # PR #729 review, finding 5.
    r = box.cli("--check", str(box.tmp / "no-such" / "canonical" / "scope.md"))
    assert r.returncode == 2 and "no such file" in r.stderr and "Traceback" not in r.stderr
    r = box.cli("--report", "--baseline", str(box.baseline), "--no-alert", "--out", "debt-bare.md", str(box.repo))
    assert r.returncode == 0 and "Traceback" not in r.stderr and (box.tmp / "debt-bare.md").is_file()


def test_init_writes_hashes_only_and_never_twice(box):
    box.scope.write_text(scope_with(R1))
    out = box.tmp / "b.json"
    assert box.cli("--init", "--out", str(out), str(box.repo)).returncode == 0
    data = json.loads(out.read_text())
    assert data["count"] == 1 and "only tools" not in out.read_text() and CASE not in out.read_text()
    assert box.cli("--init", "--out", str(out), str(box.repo)).returncode == 3


# ---------------------------------------------------------------- the shipped baseline
# The grandfather set taken when the gate shipped. It never changes: a changed
# digest means someone grandfathered a ruling by hand. Debt shrinks by adding
# ENFORCED-BY lines in the case, never by editing this file.
PINNED_COUNT = 19
# Re-taken 2026-11-10 before merge (PR #729 review, finding 3): the first take went
# stale when a case session edited R-17..R-19 22 minutes later, ungated because the
# gate was not live yet. "When the gate shipped" means merge, so the set is taken then.
PINNED_DIGEST = "6768882920b84a2d2aaff519c7723e2c70d9a8c885af5a9531b1ec09c2d6aa93"


def test_shipped_baseline_is_pinned_and_holds_no_text():
    data = json.loads(REPO_BASELINE.read_text())
    hashes = data["hashes"]
    assert all(len(h) == 16 and all(c in "0123456789abcdef" for c in h) for h in hashes)
    assert len(hashes) == PINNED_COUNT
    assert hashlib.sha256("\n".join(sorted(hashes)).encode()).hexdigest() == PINNED_DIGEST
