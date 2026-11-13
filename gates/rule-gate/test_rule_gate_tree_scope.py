#!/usr/bin/env python3
"""ASK-4681 and ASK-4769 (option a): the rule gate judges a tree by its own content,
wherever the tree sits, and a Stop judges only the session's own tree.

THE SCARS.
- 2026-11-12, consulting PR #540: a new rule naming a git-tracked test as its enforcer
  was deleted after every tool call in the reviewer's tree under ~/.config/kipi/
  review-trees (28 cycles in round 2), because the tracked-test allowance only counted
  paths under ~/projects. The same rule survived under ~/projects.
- 2026-11-13: an uncommitted rule edit in ~/projects/_worktrees/ask-4641 (consulting)
  blocked the Stop of an unrelated kipi-system session twice, and made kipi-system
  review rounds (PR #788 round 2, PR #789 round 1) end UNSTATED. The Stop scan walked
  all of ~/projects.
- Same night: a new wired section inserted above an old section's JSON block made the
  old, unchanged section read as changed, because a section is identified by the hash
  of its whole body and the JSON tail had moved into the new section.

HOW IT RUNS THE GATE. As the hook does: JSON on stdin, `python3 rule_gate.py`, HOME
swapped to a sandbox. RULE_GATE_UNDER_TEST=<path> runs an installed gate in place (the
installer's steps 8 and 10); it then reads that install's baseline read-only.

THE SANDBOX IS OUTSIDE TEMP SPACE ON PURPOSE. check_section refuses an enforcer under
/tmp or /var/folders, which is where pytest's tmp_path lives on macOS, so a rule that
SHOULD be kept could never be kept there and every positive case below would be
vacuous. Each test gets its own folder under ~/.cache/kipi-rule-gate-tests and removes
it afterwards. With the default gate copy nothing here reads or writes ~/projects or
~/.config; under RULE_GATE_UNDER_TEST the installed gate reads its own baseline and
managed-settings-path, read-only, and writes only under the sandbox HOME.
"""
import json
import os
import pwd
import shutil
import subprocess
import sys
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_GATE = os.path.join(HERE, "rule_gate.py")
# The ACCOUNT's home, not $HOME: test_install_rule_gate.py runs this file with HOME set to
# a pytest temp folder, and a sandbox there put 11 positive cases back in temp space (the
# installer's step 3 went red on the fixed source).
SANDBOX_ROOT = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".cache", "kipi-rule-gate-tests")
TEMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
STOP_SCAN = "hold rule text with no wired enforcer"


def tok():
    return uuid.uuid4().hex[:12]


class Sandbox:
    def __init__(self, root):
        self.root = root
        self.home = os.path.join(root, "home")
        os.makedirs(self.home)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GIT_") and k != "CLAUDE_PROJECT_DIR"}
        env.update(HOME=self.home, GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        self.env = env
        under_test = os.environ.get("RULE_GATE_UNDER_TEST")
        if under_test:
            self.gate = under_test
        else:
            lock = os.path.join(root, "lock")
            os.makedirs(os.path.join(lock, "hooks"))
            self.gate = os.path.join(lock, "hooks", "rule_gate.py")
            shutil.copyfile(REPO_GATE, self.gate)
            # An EMPTY baseline: every section of these repos is judged on its own.
            self.put(os.path.join(lock, "baseline-v2.json"), json.dumps({"sections": {}, "files": {}}))
            self.put(os.path.join(lock, "managed-settings-path"), os.path.join(root, "no-managed.json"))
        self.n = 0

    def h(self, *parts):
        return os.path.join(self.home, *parts)

    @staticmethod
    def put(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def git(self, cwd, *args):
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=self.env)
        assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
        return r.stdout

    def repo(self, name, files, at):
        """A repo with an origin; its main checkout is cloned to `at`."""
        seed = os.path.join(self.root, "seeds", name)
        self.git(self.root, "init", "-q", "-b", "main", seed)
        files = dict(files)
        files.setdefault("README.md", f"{name}\n")
        for rel, text in files.items():
            self.put(os.path.join(seed, rel), text)
        self.git(seed, "add", "-A")
        self.git(seed, "commit", "-q", "-m", "seed")
        origin = os.path.join(self.root, "origins", name + ".git")
        self.git(self.root, "clone", "-q", "--bare", seed, origin)
        self.git(self.root, "clone", "-q", origin, at)
        return at

    def worktree(self, main, at, branch):
        self.git(main, "worktree", "add", "-q", "-b", branch, at, "origin/main")
        return at

    def run(self, event, cwd, tool="Bash", tool_input=None):
        self.n += 1
        payload = {"hook_event_name": event, "tool_name": tool,
                   "tool_input": tool_input or {"command": "true"}, "cwd": cwd,
                   # A fresh session per run, so the Stop block cap never hides a verdict.
                   "session_id": f"ask-4681-{self.n}-{tok()}"}
        r = subprocess.run([sys.executable, self.gate], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env, cwd=cwd, timeout=120)
        assert r.returncode == 0, f"gate exited {r.returncode}: {r.stderr}"
        return r.stdout

    def scan(self, cwd):
        r = subprocess.run([sys.executable, self.gate, "--scan"], capture_output=True,
                           text=True, env=self.env, cwd=cwd, timeout=120)
        return r.returncode, r.stdout

    def stop_scan_reasons(self, cwd):
        out = self.run("Stop", cwd)
        reasons = []
        for line in out.splitlines():
            try:
                reason = json.loads(line).get("reason") or ""
            except ValueError:
                continue
            if STOP_SCAN in reason:
                reasons.append(reason)
        return reasons


@pytest.fixture
def sb():
    root = os.path.join(SANDBOX_ROOT, uuid.uuid4().hex)
    assert not os.path.realpath(root).startswith(TEMP_PREFIXES), (
        f"sandbox {root} is in temp space: every enforcer would be refused and the "
        f"positive cases would test nothing")
    os.makedirs(root)
    try:
        yield Sandbox(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def unwired_prose(t):
    return f"# Builder notes {t}\n\nAlways do the unwired thing {t}.\n"


# ======================================================== (a) Stop scope (ASK-4769)
def test_stop_judges_only_the_sessions_own_tree(sb):
    a = sb.repo("a", {}, sb.h("projects", "a"))
    b = sb.repo("b", {}, sb.h("projects", "b"))
    b_wt = sb.worktree(b, sb.h("projects", "_worktrees", "b-wt"), "sana/b")
    t = tok()
    # docs/CLAUDE.md sits below the worktree root, so it is outside the PostToolUse hot set
    # and only the Stop scan can see it: the ask-4641 shape.
    sb.put(os.path.join(b_wt, "docs", "CLAUDE.md"), unwired_prose(t))
    assert sb.stop_scan_reasons(a) == [], "repo B's worktree debt blocked a Stop in repo A"
    assert sb.stop_scan_reasons(b) == [], "a sibling worktree's debt blocked B's main checkout"
    own = sb.stop_scan_reasons(b_wt)
    assert own and "docs/CLAUDE.md" in own[0], "the session's own tree is no longer judged at Stop"


def test_stop_does_not_descend_into_a_nested_worktree(sb):
    # kipi-system's main checkout holds other sessions' trees under worktrees/ and
    # .wt-floor-wiring/; a nested .git marks another tree.
    a = sb.repo("a", {}, sb.h("projects", "a"))
    nested = sb.worktree(a, os.path.join(a, "worktrees", "x"), "sana/x")
    sb.put(os.path.join(nested, "docs", "CLAUDE.md"), unwired_prose(tok()))
    assert sb.stop_scan_reasons(a) == [], "a nested worktree's debt blocked the main checkout"
    assert sb.stop_scan_reasons(nested), "the nested tree's own session is no longer judged"


def test_stop_judges_own_tree_wherever_it_sits(sb):
    # Negative, location half: the old scan never looked outside ~/projects.
    a = sb.repo("a", {}, sb.h("projects", "a"))
    wt = sb.worktree(a, sb.h(".config", "kipi", "worktrees", "ask-1"), "sana/ask-1")
    sb.put(os.path.join(wt, "docs", "CLAUDE.md"), unwired_prose(tok()))
    assert sb.stop_scan_reasons(wt), "an unwired rule in a ~/.config worktree passed its own Stop"


# ======================================================== (b) a split is not a change
def split_fixture(sb, t, kind="worktree"):
    old = (f"# Split rule {t}\n\nIntro prose {t}.\n\n"
           f"## Old section {t}\n\nOld prose that keeps its verdict {t}.\n\n"
           f"```json\n[{{\"clause\": \"Old section {t}\", \"status\": \"ENFORCED\"}}]\n```\n")
    r = sb.repo("r", {os.path.join(".claude", "rules", "split.md"): old}, sb.h("projects", "r"))
    if kind == "worktree":
        wt = sb.worktree(r, sb.h(".config", "kipi", "worktrees", "r-wt"), "sana/r")
    else:
        # A review tree is a CLONE (.git is a folder) whose path no baseline walked; its
        # unchanged sections are grandfathered only by hash, from the install baseline,
        # which --init takes here over the sandbox HOME (it walks ~/projects/r).
        r_init = subprocess.run([sys.executable, sb.gate, "--init"], capture_output=True,
                                text=True, env=sb.env, cwd=sb.home, timeout=120)
        assert r_init.returncode == 0 and "baseline" in r_init.stdout, r_init.stdout + r_init.stderr
        wt = sb.h(".config", "kipi", "review-trees", "owner_r__pr-1")
        sb.git(sb.root, "clone", "-q", os.path.join(sb.root, "origins", "r.git"), wt)
    # Wired through a LaunchAgent plist: location-proof on old and new code alike, so
    # these tests measure the split and nothing else.
    enf = os.path.join(wt, "automation", "split_check.py")
    sb.put(enf, f"# enforces RULE-SPLIT-{t}\n")
    sb.put(sb.h("Library", "LaunchAgents", "com.test.split.plist"), f"<string>{enf}</string>\n")
    return wt, os.path.join(wt, ".claude", "rules", "split.md"), old


def wired_section(t):
    return (f"## New wired section {t}\n\nRule-ID: RULE-SPLIT-{t}\n"
            f"Enforced by: automation/split_check.py\n\nThe new rule {t}.\n\n")


def fails_for(out, heading):
    return [l for l in out.splitlines() if l.startswith("FAIL") and heading in l]


def test_wired_section_inserted_above_the_json_block_keeps_the_old_verdict(sb):
    t = tok()
    wt, path, old = split_fixture(sb, t)
    json_at = old.index("```json")
    new = old[:json_at] + wired_section(t) + old[json_at:]
    sb.put(path, new)
    _, out = sb.scan(wt)
    assert fails_for(out, f"## Old section {t}") == [], f"an unchanged section read as changed:\n{out}"
    assert fails_for(out, "New wired section") == [], f"the wired new section failed:\n{out}"
    sb.run("PostToolUse", wt)
    with open(path) as fh:
        assert fh.read() == new, "the gate rewrote a file whose only change is a wired section"


def test_wired_section_inserted_above_the_json_block_in_a_review_tree_clone(sb):
    # PR #793 review, round 1: keyed by path, the split test found no old body in a
    # clone, and the gate deleted the old section's heading and prose.
    if os.environ.get("RULE_GATE_UNDER_TEST"):
        pytest.skip("needs --init on a sandbox lock; --init is never run against an installed gate")
    t = tok()
    tree, path, old = split_fixture(sb, t, kind="clone")
    json_at = old.index("```json")
    new = old[:json_at] + wired_section(t) + old[json_at:]
    sb.put(path, new)
    _, out = sb.scan(tree)
    assert fails_for(out, f"## Old section {t}") == [], f"a clone read an unchanged section as changed:\n{out}"
    sb.run("PostToolUse", tree)
    with open(path) as fh:
        assert fh.read() == new, "the gate rewrote a clone's file whose only change is a wired section"


def test_stop_outside_any_git_tree_records_that_it_scanned_nothing(sb):
    # PR #793 review, round 1: the skip was silent, so it read the same as a clean scan.
    # Decision recorded in stop(): no walk of a non-git cwd (it would judge folders no
    # session owns), and a no-tree row says the Stop added nothing to the hot set.
    d = sb.h("projects", "notarepo")
    sb.put(os.path.join(d, "docs", "CLAUDE.md"), unwired_prose(tok()))
    assert sb.stop_scan_reasons(d) == []
    with open(sb.h(".config", "kipi", "rule-gate", "rule-gate.jsonl")) as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    assert any(r.get("mode") == "stop" and r.get("verdict") == "no-tree" and r.get("cwd") == d
               for r in rows), "a Stop outside any git tree left no record of its skip"


def test_wired_section_inserted_at_a_boundary_keeps_the_old_verdict(sb):
    # Control: the clean-boundary shape already passed before ASK-4681.
    t = tok()
    wt, path, old = split_fixture(sb, t)
    at = old.index(f"## Old section {t}")
    sb.put(path, old[:at] + wired_section(t) + old[at:])
    rc, out = sb.scan(wt)
    assert rc == 0 and "FAIL" not in out, out


def test_unwired_section_above_the_json_block_restores_the_old_section_in_one_pass(sb):
    # Negative: the moved tail rode into a section that fails, so the old section is
    # changed too; one repair pass must give back origin's text, JSON tail included.
    t = tok()
    wt, path, old = split_fixture(sb, t)
    json_at = old.index("```json")
    sb.put(path, old[:json_at] + f"## Unwired {t}\n\nAlways do the unwired thing.\n\n" + old[json_at:])
    sb.run("PostToolUse", wt)
    with open(path) as fh:
        assert fh.read() == old, "one repair pass did not restore origin's text"


def test_deleted_tail_is_still_a_change(sb):
    # Negative: the old section kept only a prefix and its tail is gone, not moved.
    t = tok()
    wt, path, old = split_fixture(sb, t)
    json_at = old.index("```json")
    sb.put(path, old[:json_at] + wired_section(t))
    _, out = sb.scan(wt)
    assert fails_for(out, f"## Old section {t}"), f"a deleted tail passed as a split:\n{out}"


def test_edited_prefix_is_still_a_change(sb):
    t = tok()
    wt, path, old = split_fixture(sb, t)
    json_at = old.index("```json")
    edited = old[:json_at].replace("keeps its verdict", "loses its verdict")
    sb.put(path, edited + wired_section(t) + old[json_at:])
    _, out = sb.scan(wt)
    assert fails_for(out, f"## Old section {t}"), f"an edited section passed as a split:\n{out}"


# ======================================================== (c) location does not change the verdict
LOCATIONS = {
    "projects-main": ("projects", "repo-loc"),
    "projects-worktree": ("projects", "_worktrees", "ask-loc"),
    "config-worktree": (".config", "kipi", "worktrees", "ask-loc"),
    "review-tree-clone": (".config", "kipi", "review-trees", "owner_repo__pr-1"),
}


def tree_at(sb, where):
    parts = LOCATIONS[where]
    if where == "projects-main":
        return sb.repo("loc", {}, sb.h(*parts))
    if where == "review-tree-clone":
        main = sb.repo("loc", {}, sb.h("projects", "repo-loc"))
        sb.git(sb.root, "clone", "-q", os.path.join(sb.root, "origins", "loc.git"), sb.h(*parts))
        return sb.h(*parts)
    main = sb.repo("loc", {}, sb.h("projects", "repo-loc"))
    return sb.worktree(main, sb.h(*parts), "sana/loc")


def new_rule(tree, t, enforcers):
    return os.path.join(tree, ".claude", "rules", f"new-rule-{t}.md"), (
        f"# New rule {t}\n\nRule-ID: RULE-LOC-{t}\nEnforced by: {enforcers}\n\n"
        f"Always do the new thing {t}.\n")


@pytest.mark.parametrize("where", sorted(LOCATIONS))
def test_rule_with_a_tracked_test_enforcer_is_kept_in_every_location(sb, where):
    tree, t = tree_at(sb, where), tok()
    sb.put(os.path.join(tree, "tests", f"test_new_rule_{t}.py"), f"# RULE-LOC-{t}\n")
    path, text = new_rule(tree, t, f"tests/test_new_rule_{t}.py")
    sb.put(path, text)
    sb.git(tree, "add", "-A")
    sb.run("PostToolUse", tree)
    assert os.path.exists(path), f"{where}: a rule with a tracked test enforcer was removed"


@pytest.mark.parametrize("where", sorted(LOCATIONS))
def test_rule_with_a_project_dir_wired_hook_is_kept_in_every_location(sb, where):
    tree, t = tree_at(sb, where), tok()
    sb.put(os.path.join(tree, "automation", f"hook_{t}.py"), f"# RULE-LOC-{t}\n")
    sb.put(os.path.join(tree, ".claude", "settings.json"), json.dumps({"hooks": {"PostToolUse": [
        {"matcher": "Edit|Write", "hooks": [{"type": "command",
         "command": f'python3 "$CLAUDE_PROJECT_DIR/automation/hook_{t}.py"'}]}]}}))
    path, text = new_rule(tree, t, f"automation/hook_{t}.py")
    sb.put(path, text)
    sb.run("PostToolUse", tree)
    assert os.path.exists(path), f"{where}: a rule wired through $CLAUDE_PROJECT_DIR was removed"


def test_relative_enforcer_resolves_against_the_rule_files_tree_not_the_cwd(sb):
    tree, t = tree_at(sb, "config-worktree"), tok()
    sb.put(os.path.join(tree, "tests", f"test_new_rule_{t}.py"), f"# RULE-LOC-{t}\n")
    path, text = new_rule(tree, t, f"tests/test_new_rule_{t}.py")
    sb.put(path, text)
    sb.git(tree, "add", "-A")
    sub = os.path.join(tree, "sub")
    os.makedirs(sub)
    sb.run("PostToolUse", sub)
    assert os.path.exists(path), "a session in a subfolder judged the rule's enforcer against its cwd"


# ======================================================== (d) negatives: still strict
@pytest.mark.parametrize("where", sorted(LOCATIONS))
def test_rule_with_no_enforcer_is_removed_in_every_location(sb, where):
    tree, t = tree_at(sb, where), tok()
    path, text = new_rule(tree, t, f"tests/test_missing_{t}.py")
    sb.put(path, text)
    sb.run("PostToolUse", tree)
    assert not os.path.exists(path), f"{where}: a rule with no enforcer survived"


@pytest.mark.parametrize("where", ["config-worktree", "projects-main"])
def test_untracked_test_enforcer_is_not_wired(sb, where):
    tree, t = tree_at(sb, where), tok()
    sb.put(os.path.join(tree, "tests", f"test_new_rule_{t}.py"), f"# RULE-LOC-{t}\n")
    path, text = new_rule(tree, t, f"tests/test_new_rule_{t}.py")
    sb.put(path, text)  # nothing git-added
    sb.run("PostToolUse", tree)
    assert not os.path.exists(path), f"{where}: an untracked test counted as wiring"


def test_another_trees_project_dir_hook_does_not_wire_this_tree(sb):
    # X's settings name $CLAUDE_PROJECT_DIR/automation/hook.py; that hook runs only in
    # X's sessions, so Y's identically named file is not wired by it.
    t = tok()
    x = sb.repo("x", {}, sb.h("projects", "x"))
    sb.put(os.path.join(x, ".claude", "settings.json"), json.dumps({"hooks": {"PostToolUse": [
        {"hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/automation/hook.py"'}]}]}}))
    y = sb.repo("y", {}, sb.h("projects", "y"))
    sb.put(os.path.join(y, "automation", "hook.py"), f"# RULE-LOC-{t}\n")
    path, text = new_rule(y, t, "automation/hook.py")
    sb.put(path, text)
    sb.run("PostToolUse", y)
    assert not os.path.exists(path), "another tree's $CLAUDE_PROJECT_DIR hook wired this tree"


def test_pretool_refuses_an_unwired_rule_in_a_config_worktree(sb):
    tree, t = tree_at(sb, "config-worktree"), tok()
    path, text = new_rule(tree, t, f"tests/test_missing_{t}.py")
    out = sb.run("PreToolUse", tree, tool="Write", tool_input={"file_path": path, "content": text})
    assert '"permissionDecision": "deny"' in out, f"an unwired rule write was allowed: {out[:300]}"


if __name__ == "__main__":
    # The capability gate runs declared tests as `python3 <file>`.
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
