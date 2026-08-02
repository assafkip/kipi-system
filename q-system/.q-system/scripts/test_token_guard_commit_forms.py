#!/usr/bin/env python3
"""Paired test for token-guard.py's volume-ceiling commit exemption
(_is_commit_command), sp-91a19d16.

WHY THIS EXISTS (scar, 2026-08-01): the exemption matched the raw substring
"git commit". That is wrong in BOTH directions at once, and both directions
were observed live:

  - too tight: `git -C <worktree> commit -m ...` carries no "git commit"
    substring, so a worktree commit was BLOCKED at the ceiling. `git add` was
    never exempt at all, so the staging step that makes a commit possible was
    blocked too. An agent finished cross-repo GH_REPO scoping with a passing
    26-case suite, could not commit any of it, correctly refused to route
    around the gate, and stopped. Worktrees are the standard dispatch pattern
    here, so the ceiling effectively never cleared.
  - too loose: `echo "git commit"` and `grep -r "git commit" .` carry the
    substring and cleared the ceiling while shipping nothing.

The fix matches the INVOCATION (tokenised), not the substring. This test pins
both directions so a future "simplification" back to `in cmd` fails loudly.

DRIVES THE REAL SCRIPT. Every case pipes real PreToolUse hook JSON into
token-guard.py as a subprocess and reads the exit code (2 = block, 0 = allow),
because the defect lives in the wiring between the matcher and the ceiling
check, which a pure-function test cannot see.

REF HATCH: TOKEN_GUARD_REF=<git-ref> runs the cases against the copy of
token-guard.py at that ref instead of the working tree, so the pre-fix failure
can be re-observed on demand and this test is never a case that has only ever
been watched pass. Expect the pre-fix ref to FAIL cases 3/7/8/9/10/11/12.

ISOLATION: each case gets its own synthetic session id, so the guard cache is a
disposable per-case file that no real session can collide with, and it is
deleted afterwards. CLAUDE_PROJECT_DIR points at a non-repo temp dir so the
PreToolUse commit valve (reset_volume_if_committed, which shells out to git
HEAD) cannot mask the result. Case 1 is the built-in control for that: if the
git valve were doing the work, EVERY form would clear, not just the ones the
matcher recognises.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import uuid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKTREE_GUARD = REPO_ROOT / "q-system/.q-system/token-guard.py"

failures = []
_tmpdir = tempfile.TemporaryDirectory(prefix="tg-commit-forms-")
SANDBOX = pathlib.Path(_tmpdir.name)

# A directory that is deliberately NOT a git repo: _head_commit_epoch() returns
# None here, so the PreToolUse git valve is provably not the thing under test.
NON_REPO = SANDBOX / "not-a-repo"
NON_REPO.mkdir()


def guard_path():
    """The token-guard.py under test: the working tree, or a ref-extracted copy
    when TOKEN_GUARD_REF is set (the mutation/pre-fix hatch)."""
    ref = os.environ.get("TOKEN_GUARD_REF")
    if not ref:
        return WORKTREE_GUARD
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show",
         f"{ref}:q-system/.q-system/token-guard.py"],
        capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"TOKEN_GUARD_REF={ref} could not be read: {out.stderr.strip()}")
    dest = SANDBOX / f"token-guard-{ref.replace('/', '_')}.py"
    dest.write_text(out.stdout)
    return dest


GUARD = guard_path()

# Read the ceiling from the guard under test rather than hardcoding 50, so this
# test pins the BEHAVIOUR and not a constant someone may legitimately retune.
VOLUME_CEILING = int(subprocess.run(
    [sys.executable, "-c",
     "import importlib.util,sys;"
     "s=importlib.util.spec_from_file_location('g',sys.argv[1]);"
     "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
     "print(m.VOLUME_CEILING)", str(GUARD)],
    capture_output=True, text=True, check=True).stdout.strip())


def fire(command, calls_before, tool_name="Bash", tool_input=None, session=None,
         extra_cache=None):
    """One PreToolUse hook fire against the real script. Returns (exit_code,
    stderr). Seeds the actor cache to `calls_before` first."""
    session = session or f"tg-commit-forms-{uuid.uuid4()}"
    cache = pathlib.Path(f"/tmp/claude-guard-{session}.json")
    # last_volume_reset=now keeps the git valve inert even if CLAUDE_PROJECT_DIR
    # ever resolves to a real repo; last_write_time=now keeps the stall warning
    # quiet so the only signal in the exit code is the volume ceiling.
    import time
    seed = {
        "tool_calls_since_user": calls_before,
        "last_volume_reset": time.time(),
        "last_write_time": time.time(),
    }
    seed.update(extra_cache or {})
    cache.write_text(json.dumps(seed))
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": session,
        "tool_name": tool_name,
        "tool_input": tool_input if tool_input is not None else {"command": command},
    }
    env = dict(os.environ)
    env["CLAUDECODE"] = "1"
    env["CLAUDE_PROJECT_DIR"] = str(NON_REPO)
    env["KIPI_NOTIFY"] = "/usr/bin/true"
    proc = subprocess.run(
        [sys.executable, str(GUARD)], input=json.dumps(payload),
        capture_output=True, text=True, env=env)
    cache.unlink(missing_ok=True)
    return proc.returncode, proc.stderr


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        failures.append(name)
        print(f"FAIL: {name}{'  ' + detail if detail else ''}")


def at_ceiling(command):
    """Fire `command` as the call that lands exactly ON the ceiling."""
    return fire(command, VOLUME_CEILING - 1)


def check_clears(num, name, command):
    code, err = at_ceiling(command)
    check(f"{num}. clears ceiling: {name}", code == 0,
          f"exit={code} stderr={err.strip()[:120]!r}")


def check_blocks(num, name, command):
    code, err = at_ceiling(command)
    check(f"{num}. still BLOCKED: {name}", code == 2, f"exit={code}")


WT = "/private/tmp/claude-501/wt-example"

print(f"guard under test: {GUARD}")
print(f"VOLUME_CEILING={VOLUME_CEILING}\n")

# --- 0. The ceiling is real and reachable through the live path -------------
# Drive actual calls until the guard blocks. Inputs vary so check_exact_retry
# (3 identical calls) is not what stops us. Proves the rest of the matrix is
# testing a ceiling that genuinely fires, not a dead code path.
# fire() reseeds the cache per call, so driving needs its own loop over a cache
# that PERSISTS across calls.
def drive_to_ceiling():
    session = f"tg-commit-forms-drive-{uuid.uuid4()}"
    cache = pathlib.Path(f"/tmp/claude-guard-{session}.json")
    cache.unlink(missing_ok=True)
    env = dict(os.environ)
    env["CLAUDECODE"] = "1"
    env["CLAUDE_PROJECT_DIR"] = str(NON_REPO)
    env["KIPI_NOTIFY"] = "/usr/bin/true"
    try:
        for n in range(1, VOLUME_CEILING + 5):
            payload = {
                "hook_event_name": "PreToolUse",
                "session_id": session,
                "tool_name": "Read",
                "tool_input": {"file_path": f"{SANDBOX}/f{n}.txt"},
            }
            proc = subprocess.run(
                [sys.executable, str(GUARD)], input=json.dumps(payload),
                capture_output=True, text=True, env=env)
            if proc.returncode == 2:
                return n, proc.stderr
        return None, ""
    finally:
        cache.unlink(missing_ok=True)


blocked_at, block_err = drive_to_ceiling()
check("0. live path blocks exactly at VOLUME_CEILING",
      blocked_at == VOLUME_CEILING, f"blocked at {blocked_at}")
check("0b. and it is the VOLUME ceiling that fired",
      "tool calls without user input" in block_err, block_err.strip()[:120])

# --- POSITIVE: real-world commit forms must clear the ceiling ---------------
check_clears(1, "bare git commit (regression guard)", 'git commit -m "msg"')
check_clears(2, "cd + git add + git commit (&&)",
             f'cd {WT} && git add -A && git commit -m "msg"')
check_clears(3, "git -C <worktree> commit", f'git -C {WT} commit -m "msg"')
check_clears(4, "leading cd then commit", f'cd {WT} && git commit -m "msg"')
check_clears(5, "newline-separated commit", f'cd {WT}\ngit commit -m "msg"')
check_clears(6, "semicolon-separated commit", f'cd {WT}; git commit -m "msg"')
check_clears(7, "bare git add", "git add -A")
check_clears(8, "git -C <worktree> add", f"git -C {WT} add -A")
check_clears(9, "cd then git add", f"cd {WT} && git add -A")

# --- NEGATIVE: a mere MENTION must not clear the ceiling --------------------
# These are the cases that make this a matcher fix and not a policy relaxation.
check_blocks(10, "echo of the words", 'echo "git commit"')
check_blocks(11, "grep for the words", 'grep -r "git commit" .')
check_blocks(12, "-m message body mentioning both verbs",
             'python3 notify.py -m "remember to git add and git commit"')
check_blocks(13, "path segment containing commit",
             "cat /repo/docs/git-commit-guide.md")
check_blocks(14, "directory named commit", "ls /Users/x/projects/commit/")
check_blocks(15, "git subcommand that is not a checkpoint", "git log --oneline -20")
check_blocks(16, "commit --dry-run ships nothing", 'git commit --dry-run -m "msg"')

# --- The other detectors are untouched --------------------------------------
# A commit is exempt from the VOLUME ceiling ONLY. check_exact_retry runs at
# priority 2, ahead of the exemption, so an agent re-firing one identical failing
# commit must still be stopped: the exemption must not become a way to loop
# forever on a commit that never lands.
import hashlib as _h
_cmd = 'git commit -m "looping"'
_ti = {"command": _cmd}
_key = "Bash:" + _h.md5(
    ("Bash" + json.dumps(_ti, sort_keys=True)).encode()).hexdigest()[:12]
code, err = fire(_cmd, VOLUME_CEILING - 1,
                 extra_cache={"repeat_map": {_key: 3}})
check("17. exempt commit still hits the exact-retry detector", code == 2,
      f"exit={code} stderr={err.strip()[:80]!r}")

# --- The exemption widened; the RESET must not have -------------------------
# `git add` is exempt from the ceiling but ships nothing, so it must never look
# like progress. These pin the two readers apart: if a later edit points
# _invokes_git_commit at GIT_CHECKPOINT_SUBCOMMANDS, `git add` starts resetting
# the ceiling and an agent can hold the ceiling open forever without committing.
_mod = subprocess.run(
    [sys.executable, "-c",
     "import importlib.util,sys,json;"
     "s=importlib.util.spec_from_file_location('g',sys.argv[1]);"
     "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
     "resp={'exit_code':0,'stdout':'1 file changed'};"
     "print(json.dumps({"
     "'add_resets': m._is_successful_commit('cd /w && git add -A', resp),"
     "'wt_commit_resets': m._is_successful_commit("
     "'git -C /w commit -m x', resp),"
     "'compound_commit_resets': m._is_successful_commit("
     "'cd /w && git add -A && git commit -m x', resp)}))",
     str(GUARD)],
    capture_output=True, text=True, check=True)
_reset = json.loads(_mod.stdout)
check("18. `git add` does NOT reset the volume ceiling",
      _reset["add_resets"] is False, str(_reset))
check("19. `git -C <wt> commit` DOES reset the volume ceiling",
      _reset["wt_commit_resets"] is True, str(_reset))
check("20. compound cd+add+commit DOES reset the volume ceiling",
      _reset["compound_commit_resets"] is True, str(_reset))

_tmpdir.cleanup()
print()
if failures:
    print(f"FAILED ({len(failures)}): " + "; ".join(failures))
    sys.exit(1)
print("All checks passed.")
