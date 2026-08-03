"""Tests for the Fable escalation branch on token-guard's stuck blocks (ASK-311).

The suite drives the guard exactly as the hook runner does — a subprocess with
hook JSON on stdin — because the escalation lives inside `block()`, and a
function-level test of `block()` would never prove the hook path reaches it.

NEVER THE LIVE PATH. Every case points KIPI_FABLE_CLAUDE_CMD at a stub script in
a tmp_path. No test may spend a real Fable call: the fable-discipline lint blocks
a test that touches a live data path, and a suite that pages a real model is the
same defect one tier up (the slack-notify fixture-run scar, 2026-08-01).

What each group holds:
  reproducer  — a Tier-A stuck block (edit spiral) carries a Fable triage and
                writes one ledger row. This is the case that was RED before the
                escalation branch existed.
  degrade     — a stub that hangs, exits non-zero, or prints nothing leaves the
                block byte-identical to today's plain block, and never hangs.
  fresh       — the child sees ONLY the packet: no --resume/--continue/session
                id in argv, stdin+argv content hashes to the logged packet, and
                a canary planted OUTSIDE the packet window never reaches it.
  scope       — policy and environmental blocks (sensitive file, MCP rate) do
                NOT escalate; warn-tier detectors do not escalate.
  cap         — escalations stop at the cap and the cap fires slack-notify once.
  recursion   — the child is marked so a nested guard cannot escalate again.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "..", "token-guard.py")
ESCALATE = os.path.join(HERE, "..", "scripts", "fable-escalate.py")

EDIT_FAIL_LIMIT = 3
RETRY_LIMIT = 3
VOLUME_CEILING = 50

TRIAGE_TEXT = "DIAGNOSIS: the edit target moved. NEXT: re-read the file."


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _stub(tmp_path, name, body):
    """Write an executable stub and return its path."""
    p = tmp_path / name
    p.write_text(body)
    p.chmod(0o755)
    return str(p)


def ok_stub(tmp_path):
    """A stub Fable that records how it was called and prints a triage.

    Records argv, stdin and the environment to <stub>.calls.jsonl so the
    fresh-session assertions can read exactly what the child received.
    """
    dump = str(tmp_path / "fable-calls.jsonl")
    body = f"""#!/usr/bin/env python3
import json, os, sys
rec = {{"argv": sys.argv[1:], "stdin": sys.stdin.read(),
        "env": {{k: v for k, v in os.environ.items() if k.startswith("KIPI_")
                 or k in ("CLAUDECODE", "CLAUDE_PROJECT_DIR")}},
        "cwd": os.getcwd()}}
with open({dump!r}, "a") as fh:
    fh.write(json.dumps(rec) + "\\n")
print({TRIAGE_TEXT!r})
"""
    return _stub(tmp_path, "fable-ok", body), dump


def calls(dump):
    if not os.path.exists(dump):
        return []
    return [json.loads(line) for line in open(dump) if line.strip()]


def run_guard(payload, env_overrides=None, timeout=90):
    env = dict(os.environ)
    env.setdefault("CLAUDECODE", "1")
    # A test must never reach the real model or the real ledger.
    env.pop("KIPI_FABLE_ESCALATION", None)
    env.update(env_overrides or {})
    return subprocess.run(
        [sys.executable, GUARD], input=json.dumps(payload),
        capture_output=True, text=True, timeout=timeout, env=env,
    )


def cache_path(actor):
    return f"/tmp/claude-guard-{actor}.json"


def edit_payload(actor, file_path="/tmp/spiral-target.py"):
    return {
        "session_id": actor,
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path, "old_string": "a", "new_string": "b"},
        "transcript_path": "",
    }


def seed(actor, **overrides):
    state = {
        "actor_key": actor,
        "tool_calls_since_user": 0,
        "agent_calls_since_user": 0,
        "mcp_timestamps": [],
        "repeat_map": {},
        "consecutive_reads": 0,
        "warnings_issued": 0,
        "file_read_counts": {},
        "greps_since_write": 0,
        "edit_targets": {},
        "agents_without_write": 0,
        "last_write_time": time.time(),
        "calls_since_write": 0,
        "last_volume_reset": time.time(),
        "gate_grace_remaining": 0,
        "gate_grace_gate": None,
        "gate_grace_grants": 0,
    }
    state.update(overrides)
    with open(cache_path(actor), "w") as fh:
        json.dump(state, fh)
    return state


@pytest.fixture
def actor():
    key = "fable-test-" + uuid.uuid4().hex[:10]
    yield key
    try:
        os.remove(cache_path(key))
    except OSError:
        pass


@pytest.fixture
def env(tmp_path, actor):
    """Base env: stubbed model, ledger + notifier redirected into tmp_path."""
    cmd, dump = ok_stub(tmp_path)
    notify_log = str(tmp_path / "notify.log")
    notify = _stub(
        tmp_path, "notify-stub",
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> {notify_log!r}\n')
    return {
        "KIPI_FABLE_CLAUDE_CMD": cmd,
        "KIPI_FABLE_LEDGER_DIR": str(tmp_path / "ledger"),
        "KIPI_FABLE_NOTIFY_CMD": notify,
        "_dump": dump,
        "_notify_log": notify_log,
    }


def guard_env(env):
    return {k: v for k, v in env.items() if not k.startswith("_")}


def ledger_rows(env):
    d = env["KIPI_FABLE_LEDGER_DIR"]
    if not os.path.isdir(d):
        return []
    rows = []
    for name in sorted(os.listdir(d)):
        with open(os.path.join(d, name)) as fh:
            rows += [json.loads(line) for line in fh if line.strip()]
    return rows


# --------------------------------------------------------------------------
# reproducer: the Tier-A stuck block escalates
# --------------------------------------------------------------------------

def test_edit_spiral_block_carries_fable_triage(actor, env):
    """THE REPRODUCER. An edit spiral is a Tier-A stuck state. Before the
    escalation branch the block message was the guard's own sentence and
    nothing else; now it also carries Fable's triage and leaves a ledger row."""
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    r = run_guard(edit_payload(actor), guard_env(env))

    assert r.returncode == 2, f"expected a block, got {r.returncode}: {r.stderr}"
    assert "edit attempts on" in r.stderr, "the original block reason must survive"
    assert TRIAGE_TEXT in r.stderr, (
        "the block did not carry a Fable triage — escalation did not fire.\n"
        + r.stderr)

    rows = ledger_rows(env)
    assert len(rows) == 1, f"expected exactly one ledger row, got {rows}"
    assert rows[0]["trigger"] == "edit-spiral"
    assert rows[0]["fable_ok"] is True
    assert rows[0]["packet_sha256"]
    assert rows[0]["duration_s"] >= 0


def configured_hook_timeout():
    """The REAL budget this hook runs under, read from the wiring.

    Deliberately NOT a literal 5. The number that matters is whatever
    .claude/settings.json actually gives token-guard on PreToolUse, so the
    assertion tracks the config; if someone retunes the hook, this test retunes
    with it instead of silently testing a number nobody uses any more.
    """
    path = os.path.join(HERE, "..", "..", "..", ".claude", "settings.json")
    settings = json.load(open(path))
    for group in settings["hooks"]["PreToolUse"]:
        for hook in group.get("hooks", []):
            if "token-guard.py" in hook.get("command", ""):
                return hook["timeout"]
    raise AssertionError("token-guard is not wired into PreToolUse at all")


def test_stuck_block_refuses_within_the_hook_timeout(actor, env, tmp_path):
    """THE FINDING-1 REPRODUCER (PR #75 round 1, Codex major).

    A refusal that arrives after this hook's configured timeout is not a late
    refusal -- it is NO refusal. Measured live 2026-08-03 against `claude -p`
    with a PreToolUse hook at `timeout: 5`:

        hook sleeps 0s, exits 2  -> tool BLOCKED (marker file absent)
        hook sleeps 8s, exits 2  -> tool RAN     (marker file created)

    So a guard that waits on a model call spends its own refusal. The stuck
    session then gets NEITHER the block NOR the triage, which is strictly worse
    than before the escalation existed. This pytest case is the executable that
    holds it: the guard must return its exit 2 inside the configured budget.
    """
    slow = _stub(tmp_path, "fable-slow",
                 "#!/bin/sh\nsleep 8\necho 'too late to matter'\n")
    overrides = guard_env(env)
    overrides["KIPI_FABLE_CLAUDE_CMD"] = slow

    budget = configured_hook_timeout()
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})

    started = time.time()
    r = run_guard(edit_payload(actor), overrides)
    elapsed = time.time() - started

    assert r.returncode == 2, f"expected a block, got {r.returncode}: {r.stderr}"
    assert "edit attempts on" in r.stderr, "the original block reason must survive"
    assert elapsed < budget, (
        "the guard took %.1fs but the hook runner kills it at %ss and DISCARDS "
        "its exit 2 -- the refusal never reaches the model." % (elapsed, budget))


def test_exact_retry_block_escalates(actor, env):
    """A2 is not the only stuck trigger: A1 (exact retry) escalates too."""
    payload = edit_payload(actor)
    key_input = json.dumps(payload["tool_input"], sort_keys=True)
    digest = hashlib.md5(("Edit" + key_input).encode()).hexdigest()[:12]
    seed(actor, repeat_map={f"Edit:{digest}": RETRY_LIMIT})
    r = run_guard(payload, guard_env(env))
    assert r.returncode == 2
    assert "exact call" in r.stderr
    assert TRIAGE_TEXT in r.stderr
    assert ledger_rows(env)[0]["trigger"] == "exact-retry"


def test_volume_ceiling_block_escalates(actor, env):
    """A6. The ceiling block is the deadlock shape the founder sees most."""
    seed(actor, tool_calls_since_user=VOLUME_CEILING)
    r = run_guard(
        {"session_id": actor, "hook_event_name": "PreToolUse",
         "tool_name": "Read", "tool_input": {"file_path": "/tmp/x"},
         "transcript_path": ""},
        guard_env(env))
    assert r.returncode == 2
    assert TRIAGE_TEXT in r.stderr
    assert ledger_rows(env)[0]["trigger"] == "volume-ceiling"


# --------------------------------------------------------------------------
# degrade: a broken Fable never costs the block and never hangs
# --------------------------------------------------------------------------

def _plain_block(actor, extra_env=None):
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    base = {"KIPI_FABLE_ESCALATION": "0"}
    base.update(extra_env or {})
    return run_guard(edit_payload(actor), base)


# The pre-ASK-311 edit-spiral block, verbatim and single-line. Asserted as a
# LITERAL, not as "same as the baseline run": a baseline computed through the
# same code cannot see a change that moves both sides. Mutation M6 (append the
# cap notice unconditionally) survived the same-as-baseline assertion alone and
# died against this one.
PLAIN_EDIT_SPIRAL = (
    "3 edit attempts on spiral-target.py. The approach isn't working. "
    "Read the file again, find the exact string, or tell the founder what's wrong.")


def test_disabled_escalation_is_todays_behavior(actor):
    r = _plain_block(actor)
    assert r.returncode == 2
    assert r.stderr.strip() == PLAIN_EDIT_SPIRAL
    assert "FABLE" not in r.stderr.upper()


@pytest.mark.parametrize("name,body", [
    ("hang", "#!/bin/sh\nsleep 600\n"),
    ("fail", "#!/bin/sh\necho boom >&2\nexit 1\n"),
    ("empty", "#!/bin/sh\nexit 0\n"),
    ("missing", None),
])
def test_broken_fable_degrades_to_plain_block(actor, env, tmp_path, name, body):
    """A timeout, a crash, empty output, or a missing binary all land on the
    SAME plain block today's guard emits — never a hang, never a lost block."""
    baseline = _plain_block(actor + "-base").stderr
    cmd = (_stub(tmp_path, "fable-" + name, body) if body
           else str(tmp_path / "does-not-exist"))
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    e = guard_env(env)
    e["KIPI_FABLE_CLAUDE_CMD"] = cmd
    e["KIPI_FABLE_TIMEOUT"] = "2"      # the hang case must be cut, not waited on

    start = time.time()
    r = run_guard(edit_payload(actor), e, timeout=30)
    elapsed = time.time() - start

    assert r.returncode == 2, "the block must survive a broken escalation"
    assert elapsed < 20, f"escalation hung for {elapsed:.1f}s"
    assert r.stderr.strip() == baseline.strip(), (
        "a failed escalation must leave the block byte-identical to today's")
    assert r.stderr.strip() == PLAIN_EDIT_SPIRAL, (
        "the literal check: 'same as the baseline' cannot see a change that "
        "moves the baseline too")
    rows = ledger_rows(env)
    assert len(rows) == 1 and rows[0]["fable_ok"] is False, (
        "a failed call must still be logged — a silent failure is invisible")
    assert rows[0]["failure"], "the ledger row must name why it failed"


# --------------------------------------------------------------------------
# fresh session: the child sees only the packet
# --------------------------------------------------------------------------

def _transcript(tmp_path, canary, tail_marker, filler=60):
    """A transcript whose FIRST record carries `canary` and whose last carries
    `tail_marker`. The packet window is bounded, so the canary must not reach
    the child while the tail marker must."""
    p = tmp_path / "transcript.jsonl"
    recs = [{"type": "user", "message": {"role": "user",
                                         "content": [{"type": "text", "text": canary}]}}]
    for i in range(filler):
        recs.append({"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": f"filler line {i}"}]}})
    recs.append({"type": "user", "message": {"role": "user",
                                             "content": [{"type": "text", "text": tail_marker}]}})
    p.write_text("\n".join(json.dumps(r) for r in recs))
    return str(p)


def test_child_gets_no_session_continuation(actor, env, tmp_path):
    """No --resume, --continue, or session id reaches the child: the triage
    runs in a session that shares no history with this one."""
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    payload = edit_payload(actor)
    payload["transcript_path"] = _transcript(tmp_path, "CANARY-HEAD", "TAIL-MARK")
    run_guard(payload, guard_env(env))

    c = calls(env["_dump"])
    assert len(c) == 1, "exactly one Fable call per escalation"
    argv = c[0]["argv"]
    joined = " ".join(argv)
    for forbidden in ("--resume", "--continue", "-c", "--session-id", actor):
        assert forbidden not in argv, f"{forbidden} leaked into the child argv"
    assert "--model" in argv and "claude-fable-5" in argv
    assert payload["transcript_path"] not in joined, (
        "the transcript PATH must never be handed to the child: a path is a "
        "capability, and a child that can open it is not a fresh session")


def test_child_sees_exactly_the_logged_packet(actor, env, tmp_path):
    """Whatever Fable saw hashes to the packet the ledger recorded. This is what
    makes the ledger row auditable rather than decorative."""
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    payload = edit_payload(actor)
    payload["transcript_path"] = _transcript(tmp_path, "CANARY-HEAD", "TAIL-MARK")
    run_guard(payload, guard_env(env))

    c = calls(env["_dump"])[0]
    seen = "".join(a for a in c["argv"] if a not in ("-p", "--model", "claude-fable-5")) + c["stdin"]
    row = ledger_rows(env)[0]
    assert hashlib.sha256(seen.encode()).hexdigest() == row["packet_sha256"], (
        "the child received something other than the logged packet")


def test_canary_outside_the_window_never_reaches_the_child(actor, env, tmp_path):
    """NEGATIVE SELF-TEST for the window. The tail marker proves the packet is
    really built from the transcript; the head canary proves the window is
    bounded. Without the tail assertion an empty packet would pass this test."""
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    payload = edit_payload(actor)
    payload["transcript_path"] = _transcript(tmp_path, "CANARY-HEAD", "TAIL-MARK")
    run_guard(payload, guard_env(env))

    c = calls(env["_dump"])[0]
    blob = " ".join(c["argv"]) + c["stdin"]
    assert "TAIL-MARK" in blob, "the packet carried no transcript content at all"
    assert "CANARY-HEAD" not in blob, "an unbounded window leaked the whole session"


def test_child_runs_outside_the_project(actor, env, tmp_path):
    """The child must not inherit the project cwd: a `claude -p` started inside
    the repo loads the repo's own hooks and CLAUDE.md, which is neither fresh
    nor free."""
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    run_guard(edit_payload(actor), guard_env(env))
    cwd = calls(env["_dump"])[0]["cwd"]
    repo = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    assert not cwd.startswith(repo), f"child ran inside the project: {cwd}"


def test_child_cannot_escalate_again(actor, env):
    """RECURSION GUARD. The child is a `claude` process; without a marker its
    own token-guard could escalate, and each escalation would spawn another."""
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    run_guard(edit_payload(actor), guard_env(env))
    child_env = calls(env["_dump"])[0]["env"]
    assert child_env.get("KIPI_FABLE_ESCALATION") == "0", (
        "the child was not marked, so a nested guard would escalate again")


# --------------------------------------------------------------------------
# scope: only stuck blocks escalate
# --------------------------------------------------------------------------

def test_sensitive_file_block_does_not_escalate(actor, env):
    """A policy refusal is not a stuck state. Nothing to triage."""
    seed(actor)
    r = run_guard(
        {"session_id": actor, "hook_event_name": "PreToolUse", "tool_name": "Write",
         "tool_input": {"file_path": "/tmp/app/.env"}, "transcript_path": ""},
        guard_env(env))
    assert r.returncode == 2
    assert TRIAGE_TEXT not in r.stderr
    assert calls(env["_dump"]) == []


def test_mcp_rate_block_does_not_escalate(actor, env):
    """environmental-trigger class (self-healing-retry.md rule 5): a rate limit
    stops on attempt 1 and no amount of cross-model triage fixes an API."""
    seed(actor, mcp_timestamps=[time.time()] * 31)
    r = run_guard(
        {"session_id": actor, "hook_event_name": "PreToolUse",
         "tool_name": "mcp__linear__list_issues", "tool_input": {},
         "transcript_path": ""},
        guard_env(env))
    assert r.returncode == 2
    assert TRIAGE_TEXT not in r.stderr
    assert calls(env["_dump"]) == []


def test_warn_tier_does_not_escalate(actor, env):
    """A warn means 'you may be drifting', not 'you are stuck'. Escalating here
    would spend the cap on states the run recovers from unaided."""
    seed(actor, consecutive_reads=20, calls_since_write=20,
         last_write_time=time.time() - 600)
    r = run_guard(
        {"session_id": actor, "hook_event_name": "PreToolUse", "tool_name": "Read",
         "tool_input": {"file_path": "/tmp/x"}, "transcript_path": ""},
        guard_env(env))
    assert r.returncode == 0
    assert calls(env["_dump"]) == []


# --------------------------------------------------------------------------
# cap: cross-model is a step before the human, not instead of one
# --------------------------------------------------------------------------

def test_escalations_stop_at_the_cap_and_page_once(actor, env):
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    e = guard_env(env)
    e["KIPI_FABLE_CAP"] = "2"

    for _ in range(2):
        seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1},
             fable_escalations=_count(env))
        r = run_guard(edit_payload(actor), e)
        assert TRIAGE_TEXT in r.stderr

    # third stuck block: cap reached
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1},
         fable_escalations=2)
    r = run_guard(edit_payload(actor), e)
    assert r.returncode == 2
    assert TRIAGE_TEXT not in r.stderr, "escalated past the cap"
    assert "cap" in r.stderr.lower()
    assert len(calls(env["_dump"])) == 2, "the model was called past the cap"

    log = open(env["_notify_log"]).read() if os.path.exists(env["_notify_log"]) else ""
    assert "stuck" in log.lower(), f"the founder was not paged at the cap: {log!r}"

    # a fourth block must not page again — one page per episode, not per call
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1},
         fable_escalations=2, fable_capped_notified=True)
    run_guard(edit_payload(actor), e)
    assert open(env["_notify_log"]).read().count("\n") == 1, "paged twice"


def _count(env):
    return len([r for r in ledger_rows(env) if r.get("fable_ok")])


# The capability gate invokes a `runner: python3` entry as `python3 <file>`
# (capability-gate.py:422). A pytest module has no __main__, so that invocation
# exits 0 having collected NOTHING and the gate reports a green it never earned.
# Measured 2026-08-02: `python3 tests/test_token_guard.py` exits 0 with no
# output. This block makes the manifest entry mean what it claims.
if __name__ == "__main__":
    sys.exit(subprocess.call(
        [sys.executable, "-m", "pytest", os.path.abspath(__file__), "-q"]))


# --------------------------------------------------------------------------
# fixture-run chokepoint: no suite may spend a real Fable call
# --------------------------------------------------------------------------

def test_a_fixture_run_without_a_stub_refuses_the_real_model(actor, env):
    """NEGATIVE SELF-TEST. Drop the stub and the escalation must refuse rather
    than reach the live model. Measured need: adding the escalation branch took
    the pre-existing test_token_guard.py from 0.7s to 60.9s and 6 failures,
    because six of its cases drive the volume ceiling and every one of them
    started billing Fable. The refusal is at the chokepoint, so a ceiling test
    written next month inherits it without knowing it exists."""
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    e = guard_env(env)
    del e["KIPI_FABLE_CLAUDE_CMD"]      # a suite that forgot to stub

    start = time.time()
    r = run_guard(edit_payload(actor), e, timeout=30)
    elapsed = time.time() - start

    assert r.returncode == 2
    assert TRIAGE_TEXT not in r.stderr
    assert elapsed < 15, f"a real model call was made ({elapsed:.1f}s)"
    row = ledger_rows(env)[0]
    assert row["fable_ok"] is False
    assert "fixture run" in row["failure"], (
        f"refused for the wrong reason: {row['failure']!r}")


def test_the_chokepoint_still_lets_a_stub_through(actor, env):
    """The paired positive. Without this the refusal above would pass even if
    the chokepoint refused everything, which would silently disable the whole
    feature in production."""
    seed(actor, edit_targets={"/tmp/spiral-target.py": EDIT_FAIL_LIMIT - 1})
    r = run_guard(edit_payload(actor), guard_env(env))
    assert TRIAGE_TEXT in r.stderr
    assert ledger_rows(env)[0]["fable_ok"] is True
