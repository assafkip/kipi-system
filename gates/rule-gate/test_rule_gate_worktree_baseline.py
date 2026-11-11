#!/usr/bin/env python3
"""ASK-4283: rule_gate.py must not read a tracked rule file in a git worktree as NEW.

THE SCAR. 2026-11-09, worktree 4p-case-051-session: on the session's first tool call
the PostToolUse gate deleted 5 tracked .claude/rules files (q-investigation,
evidence-capture-protocol, investigation-claims-ledger, instance-conventions,
stop-precedence) and auto-commit committed the deletion as f31929ab (533 lines). The
same shape hit ask-141 and ask-4309 (7 deleted, 6 stripped). Measured cause: the
2026-11-08 baseline never walked those repos' rules (projects_files() stops at depth
4), so 0 of their 47 sections were grandfathered, and repair_file() has no per-path
baseline for a worktree path, so it removed instead of reverting.

WHAT THIS PINS. In a LINKED worktree, a section is grandfathered when it is in that
same path's blob at merge-base(HEAD, origin's default branch) and the file is in the
index. Everything else keeps today's behaviour, and the negatives below prove it:
an untracked new rule is still removed, a rule committed only on the branch is still
removed (the anchor is not HEAD, or auto-commit would grandfather any agent edit), and
the main checkout is judged exactly as before.

HOW IT RUNS THE GATE. As the hook does: JSON on stdin, `python3 rule_gate.py`. HOME is
a temp folder, so the gate's logs, quarantine and settings land there. By default the
gate is a COPY of the sibling rule_gate.py inside a temp LOCK folder with an empty
baseline. RULE_GATE_UNDER_TEST=<path> runs an installed gate in place instead; it then
reads that install's own baseline read-only and still writes only under the temp HOME.
"""
import json
import os
import shutil
import subprocess
import sys
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_GATE = os.path.join(HERE, "rule_gate.py")
RULE_REL = os.path.join(".claude", "rules", "tracked-prose.md")


def _token():
    return uuid.uuid4().hex


def _git(cwd, *args, env):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout


@pytest.fixture
def sandbox(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=str(home), GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    under_test = os.environ.get("RULE_GATE_UNDER_TEST")
    if under_test:
        gate = under_test
    else:
        lock = tmp_path / "lock"
        (lock / "hooks").mkdir(parents=True)
        gate = str(lock / "hooks" / "rule_gate.py")
        shutil.copyfile(REPO_GATE, gate)
        # An EMPTY baseline is the case-051 shape: a repo the baseline never walked.
        (lock / "baseline-v2.json").write_text(json.dumps({"sections": {}, "files": {}}))
        (lock / "managed-settings-path").write_text(str(tmp_path / "no-managed.json"))
    tok = _token()
    rule = (f"# Tracked rule {tok}\n\nAlways do the tracked thing. {tok}\n\n"
            f"## Second section {tok}\n\nMore tracked prose. {tok}\n")
    seed = tmp_path / "seed"
    _git(str(tmp_path), "init", "-q", "-b", "main", str(seed), env=env)
    (seed / ".claude" / "rules").mkdir(parents=True)
    (seed / RULE_REL).write_text(rule)
    (seed / "README.md").write_text("seed\n")
    _git(str(seed), "add", "-A", env=env)
    _git(str(seed), "commit", "-q", "-m", "seed", env=env)
    origin = tmp_path / "origin.git"
    _git(str(tmp_path), "clone", "-q", "--bare", str(seed), str(origin), env=env)
    main = home / "projects" / "repo"
    _git(str(tmp_path), "clone", "-q", str(origin), str(main), env=env)
    wt = home / ".config" / "kipi" / "worktrees" / "ask-x"
    _git(str(main), "worktree", "add", "-q", "-b", "sana/ask-x", str(wt), "origin/main", env=env)
    return {"home": home, "env": env, "gate": gate, "main": main, "wt": wt, "rule": rule}


def run_gate(sb, event, cwd, tool="Bash", tool_input=None, extra_env=None):
    payload = {"hook_event_name": event, "tool_name": tool,
               "tool_input": tool_input or {"command": "true"}, "cwd": str(cwd),
               "session_id": "ask-4283-test"}
    env = dict(sb["env"])
    env.update(extra_env or {})
    r = subprocess.run([sys.executable, sb["gate"]], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, cwd=str(cwd), timeout=60)
    assert r.returncode == 0, f"gate exited {r.returncode}: {r.stderr}"
    return r.stdout


def deleted_lines(sb, tree):
    out = _git(str(tree), "status", "--porcelain", env=sb["env"])
    return [l for l in out.splitlines() if l.startswith((" D", "D "))]


# ------------------------------------------------------------- the reproducer
def test_tracked_rule_in_linked_worktree_survives(sandbox):
    path = sandbox["wt"] / RULE_REL
    before = path.read_bytes()
    out = run_gate(sandbox, "PostToolUse", sandbox["wt"])
    assert path.exists(), "the gate deleted a tracked rule file in a linked worktree"
    assert path.read_bytes() == before, "the gate rewrote a tracked rule file in a linked worktree"
    assert deleted_lines(sandbox, sandbox["wt"]) == []
    # Byte-identical is not enough: a repair pass that rewrites the same bytes still
    # writes the file and blocks every tool call with a report (mutation run 1 SURVIVED
    # on exactly that). The gate must judge the file clean, not repair it back.
    assert "tracked-prose.md" not in out, f"the gate repaired a clean tracked file: {out[:300]}"


def test_reproducer_holds_with_a_foreign_git_dir_in_the_env(sandbox):
    # A hook launched from inside another git process can inherit GIT_DIR; the gate's
    # git reads must look at the rule file's own repo, not at the inherited one.
    path = sandbox["wt"] / RULE_REL
    before = path.read_bytes()
    run_gate(sandbox, "PostToolUse", sandbox["wt"],
             extra_env={"GIT_DIR": str(sandbox["home"] / "nowhere.git")})
    assert path.exists() and path.read_bytes() == before


# ------------------------------------------------------------- negatives: still strict
def test_untracked_new_rule_in_linked_worktree_is_still_removed(sandbox):
    new = sandbox["wt"] / ".claude" / "rules" / "agent-new.md"
    new.write_text(f"# Agent rule {_token()}\n\nAlways do a new thing.\n")
    run_gate(sandbox, "PostToolUse", sandbox["wt"])
    assert not new.exists(), "a genuinely new prose rule survived: the gate was disarmed"
    assert (sandbox["wt"] / RULE_REL).exists()


def test_rule_committed_only_on_the_branch_is_still_removed(sandbox):
    # The anchor is origin's default branch, not HEAD: auto-commit (f31929ab) or a
    # same-call `git commit` would otherwise grandfather any agent-written rule.
    new = sandbox["wt"] / ".claude" / "rules" / "committed-new.md"
    new.write_text(f"# Committed rule {_token()}\n\nAlways do a committed thing.\n")
    _git(str(sandbox["wt"]), "add", "-A", env=sandbox["env"])
    _git(str(sandbox["wt"]), "commit", "-q", "-m", "agent rule", env=sandbox["env"])
    run_gate(sandbox, "PostToolUse", sandbox["wt"])
    assert not new.exists(), "a rule that never reached origin was grandfathered by HEAD"


def test_new_section_in_a_tracked_rule_is_removed_and_upstream_kept(sandbox):
    path = sandbox["wt"] / RULE_REL
    path.write_text(sandbox["rule"] + f"\n## Agent addition {_token()}\n\nAlways do more.\n")
    run_gate(sandbox, "PostToolUse", sandbox["wt"])
    assert path.exists(), "a tracked rule file was deleted for one new section"
    text = path.read_text()
    assert "Agent addition" not in text, "a new prose section survived in a tracked file"
    assert text == sandbox["rule"], "the upstream sections were not kept byte-identical"


def test_edited_upstream_section_reverts_to_its_upstream_text(sandbox):
    path = sandbox["wt"] / RULE_REL
    path.write_text(sandbox["rule"].replace("Always do the tracked thing.",
                                            "Never do the tracked thing."))
    run_gate(sandbox, "PostToolUse", sandbox["wt"])
    assert path.exists()
    assert path.read_text() == sandbox["rule"], "an edited section did not revert to upstream"


def test_main_checkout_behaviour_is_unchanged(sandbox):
    # CONTROL. The fix is scoped to LINKED worktrees. The main checkout of a repo the
    # baseline never walked is judged exactly as before: the tracked prose is removed.
    # (That main-checkout half of the defect is its own ticket, not this one's scope.)
    path = sandbox["main"] / RULE_REL
    run_gate(sandbox, "PostToolUse", sandbox["main"])
    assert not path.exists(), "main-checkout behaviour changed"


def test_deletion_commit_on_head_then_revert(sandbox):
    # The f31929ab shape: HEAD carries a commit that deleted a tracked rule.
    wt, env = sandbox["wt"], sandbox["env"]
    path = wt / RULE_REL
    _git(str(wt), "rm", "-q", RULE_REL, env=env)
    _git(str(wt), "commit", "-q", "-m", "chore: update rules", env=env)
    run_gate(sandbox, "PostToolUse", wt)
    assert not path.exists(), "the gate must not invent files; a deletion stays a deletion"
    # A plain copy back is UNTRACKED (not in the index): judged as new, still removed.
    # (git rm of the folder's only file removed the folder too.)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sandbox["rule"])
    run_gate(sandbox, "PostToolUse", wt)
    assert not path.exists(), "an untracked file was grandfathered: the gate was widened"
    # The repair that works: revert the deletion commit. The file is tracked again,
    # its content is origin's, and it survives.
    _git(str(wt), "revert", "--no-edit", "HEAD", env=env)
    run_gate(sandbox, "PostToolUse", wt)
    assert path.exists() and path.read_text() == sandbox["rule"]


# ------------------------------------------------------------- PreToolUse
def _decision(out):
    out = out.strip()
    if not out:
        return "ALLOW"
    return "DENY" if json.loads(out).get("hookSpecificOutput", {}).get("permissionDecision") == "deny" else "ALLOW"


def test_pretool_allows_an_unchanged_write_and_denies_new_prose(sandbox):
    path = str(sandbox["wt"] / RULE_REL)
    same = run_gate(sandbox, "PreToolUse", sandbox["wt"], tool="Write",
                    tool_input={"file_path": path, "content": sandbox["rule"]})
    assert _decision(same) == "ALLOW", "an unchanged write to a tracked worktree rule was refused"
    more = run_gate(sandbox, "PreToolUse", sandbox["wt"], tool="Write",
                    tool_input={"file_path": path,
                                "content": sandbox["rule"] + "\n## New prose\n\nAlways X.\n"})
    assert _decision(more) == "DENY", "a new prose section in a tracked worktree rule was allowed"


if __name__ == "__main__":
    # The capability gate runs declared tests as `python3 <file>`.
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
