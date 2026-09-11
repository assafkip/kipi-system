"""The guard cache must survive parallel hook fires (sp-016776e6).

WHAT THIS PINS, AND WHY IT IS ABOUT MONEY.

`load_cache` / `save_cache` are a read-modify-write of one JSON file with no
lock. Claude Code fires PreToolUse once per tool call, and parallel tool calls
mean parallel guard processes on the SAME actor cache. Each reads the same
pre-state, mutates its own copy, and the last writer wins -- every other
process's mutation is silently lost.

The lost mutation that costs real money is `fable_escalations`, the counter
`request_escalation` reads to decide whether this actor has spent its
KIPI_FABLE_CAP budget of cross-model triages. A lost increment means the next
process reads a stale count, decides it is under the cap, and spends another
billed `claude -p --model claude-fable-5` call.

Measured over the shipped ledger (q-system/output/fable-escalations/*.jsonl,
188 rows, 2026-08-08): 172 rows attempted a real call against a cap of 2 per
actor. 90 of them landed in a second that already carried another real call,
7 in the worst single second, and 8 distinct seconds carry two DIFFERENT
triggers -- which only two concurrent guard processes can produce.

NO REAL FABLE CALL IS EVER SPENT HERE. pytest exports PYTEST_CURRENT_TEST for
the duration of every test and the detached child inherits it, so
`call_fable`'s chokepoint refuses the live path and the child still writes its
ledger row. The row is therefore a receipt for an ATTEMPT that would have been
billed in production, which is exactly the quantity under test.
"""

import json
import os
import subprocess
import sys
import time
import uuid

import pytest

GUARD = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "token-guard.py"))
VOLUME_CEILING = 50
FABLE_CAP = 2
PARALLEL_FIRES = 8

# WHY A BARRIER AND NOT JUST N Popen CALLS.
#
# The first cut of this test fired 8 plain `python3 token-guard.py`
# subprocesses and PASSED against the unfixed code -- 3/3 green on a defect
# that provably exists. Interpreter startup is ~40ms and the guard's
# read-modify-write window is under 1ms, so process 1 had finished before
# process 8 had finished importing. The fires never overlapped; the test
# measured scheduling luck, not locking.
#
# So each process imports the guard FIRST, then parks on a barrier file, and
# the parent releases all of them at once. Interpreter startup is moved out of
# the measured window instead of being allowed to serialize it. Nothing about
# the code under test is softened: these are still N separate OS processes
# running the real main() against the real cache path, which is exactly the
# shape the hook runner produces on parallel tool calls.
_BARRIER_RUNNER = '''
import importlib.util, io, json, os, sys, time
guard_path, payload_file, barrier = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("guard_under_test", guard_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
payload = open(payload_file).read()
while not os.path.exists(barrier):
    time.sleep(0.001)
sys.stdin = io.StringIO(payload)
try:
    module.main()
except SystemExit:
    pass
'''


def cache_file(actor_key):
    return f"/tmp/claude-guard-{actor_key}.json"


@pytest.fixture
def actor(tmp_path):
    """A unique actor key, its seeded cache, and cleanup.

    Unique per run on purpose: the guard hardcodes its cache under /tmp, so
    isolation comes from the key, not from the directory. A shared key would
    make two test runs race each other -- the very defect under test.
    """
    key = "race-%s" % uuid.uuid4()
    yield key
    for path in (cache_file(key), f"/tmp/claude-fable-pending-{key}.json"):
        try:
            os.remove(path)
        except OSError:
            pass


def seed_at_ceiling(actor_key):
    """A cache parked exactly at the volume ceiling with no escalations spent.

    `last_volume_reset` is NOW so the commit-progress valve cannot lift the
    ceiling out from under the test: `reset_volume_if_committed` only fires on
    a HEAD commit NEWER than that stamp, and no commit is in the future.
    """
    state = {
        "actor_key": actor_key,
        "tool_calls_since_user": VOLUME_CEILING,
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
        "fable_escalations": 0,
    }
    with open(cache_file(actor_key), "w") as fh:
        json.dump(state, fh)


def read_ledger(directory):
    rows = []
    if not os.path.isdir(directory):
        return rows
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
    return rows


def await_rows(directory, expected, deadline_s=30):
    """Poll until `expected` ledger rows land, or the deadline passes.

    Polled, never slept-for-a-guess: the children are detached, so a fixed
    sleep would either flake or pad every run. Returning short is allowed --
    the assertions, not this helper, decide whether short is a failure.
    """
    end = time.time() + deadline_s
    rows = read_ledger(directory)
    while len(rows) < expected and time.time() < end:
        time.sleep(0.2)
        rows = read_ledger(directory)
    return rows


def fire_parallel_blocks(actor_key, ledger_dir, tmp_path, count=PARALLEL_FIRES):
    """`count` guard processes entering main() at the same instant.

    Each is a real hook invocation of the real script against the real cache
    path. See _BARRIER_RUNNER for why the release is synchronised.
    """
    env = dict(os.environ)
    env.update({
        "CLAUDECODE": "1",
        "KIPI_FABLE_LEDGER_DIR": str(ledger_dir),
        "KIPI_FABLE_CAP": str(FABLE_CAP),
        "KIPI_FABLE_PENDING": str(tmp_path / "pending.json"),
        # Not a git repo, so `_head_commit_epoch` returns None deterministically
        # and the commit valve cannot reset the ceiling mid-test.
        "CLAUDE_PROJECT_DIR": str(tmp_path),
    })
    runner = tmp_path / "barrier_runner.py"
    runner.write_text(_BARRIER_RUNNER)
    # A REAL transcript, not "". These cases are about the escalation COUNTER
    # under concurrency, and an escalation now refuses to spend a call or a cap
    # slot when it cannot read the session. With an empty path every parallel
    # fire takes the starvation path, the counter legitimately stays 0, and the
    # race assertions pass against a guard with no locking at all -- green for
    # the wrong reason. The payload has to be one the counter actually moves on.
    transcript = tmp_path / "race-transcript.jsonl"
    transcript.write_text("".join(
        json.dumps({"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "session line %d" % i}]}}) + "\n"
        for i in range(30)))
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({
        "session_id": actor_key,
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "/etc/hostname"},
        "transcript_path": str(transcript),
    }))
    barrier = tmp_path / "barrier"

    procs = [
        subprocess.Popen(
            [sys.executable, str(runner), GUARD, str(payload), str(barrier)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        for _ in range(count)
    ]
    _await_parked(procs)
    barrier.write_text("go")
    for proc in procs:
        proc.wait(timeout=60)
    return procs


def _await_parked(procs, settle_s=1.5):
    """Give every child time to finish importing and reach the barrier.

    A generous fixed settle rather than a handshake: the cost of being early
    is a test that silently stops overlapping (the exact failure this file was
    rewritten to fix), so the check below turns "a child died before the
    barrier" into a loud failure instead of a quiet non-overlap.
    """
    time.sleep(settle_s)
    dead = [p.returncode for p in procs if p.poll() is not None]
    assert not dead, (
        "%d of %d children exited BEFORE the barrier was released (codes %r); "
        "they never overlapped, so any green result below is meaningless"
        % (len(dead), len(procs), dead))


def test_parallel_fires_cannot_overspend_the_escalation_cap(actor, tmp_path):
    """N concurrent ceiling blocks must spend at most FABLE_CAP real calls.

    The assertion is on the LEDGER, not on the cache: a ledger row with
    `capped: false` is a call that reached `call_fable`, i.e. one that
    production would have billed. Counting the cache counter instead would
    measure the symptom's cousin rather than the spend.
    """
    ledger = tmp_path / "ledger"
    seed_at_ceiling(actor)
    fire_parallel_blocks(actor, ledger, tmp_path)
    rows = await_rows(ledger, PARALLEL_FIRES)

    # Guard against the green-for-nothing hole: if the children never ran, the
    # billed-call count is trivially 0 and the real assertion below proves
    # nothing. Every fire must have left a receipt of SOME kind.
    assert len(rows) == PARALLEL_FIRES, (
        "expected one ledger row per fire, got %d of %d -- the spend assertion "
        "below is only meaningful if every child actually ran"
        % (len(rows), PARALLEL_FIRES))

    billed = [r for r in rows if not r.get("capped")]
    assert len(billed) <= FABLE_CAP, (
        "%d of %d parallel fires reached call_fable against a cap of %d; the "
        "escalation counter lost %d increment(s) to the unlocked cache "
        "read-modify-write (sp-016776e6)"
        % (len(billed), PARALLEL_FIRES, FABLE_CAP, len(billed) - FABLE_CAP))


def test_parallel_fires_do_not_lose_the_escalation_counter(actor, tmp_path):
    """The persisted counter must show the cap fully spent, not one increment.

    Separate from the ledger assertion on purpose. The ledger proves what was
    SPENT; this proves the guard's own memory of it survived, which is what
    stops the next fire in the same session from spending again.
    """
    ledger = tmp_path / "ledger"
    seed_at_ceiling(actor)
    fire_parallel_blocks(actor, ledger, tmp_path)
    await_rows(ledger, PARALLEL_FIRES)

    with open(cache_file(actor)) as fh:
        cache = json.load(fh)
    assert cache.get("fable_escalations", 0) >= FABLE_CAP, (
        "cache recorded %r escalations after %d parallel fires; concurrent "
        "writers clobbered each other's increments (sp-016776e6)"
        % (cache.get("fable_escalations"), PARALLEL_FIRES))


def test_parallel_fires_do_not_lose_the_volume_counter(actor, tmp_path):
    """The same lost update, on the counter every run touches.

    The escalation counter is where the race costs money; this is where it
    costs the ceiling its accuracy. Both are the one defect, so both are
    pinned -- fixing only the expensive symptom would leave the class alive.
    """
    ledger = tmp_path / "ledger"
    seed_at_ceiling(actor)
    # Below the warning line, so no block fires and no child is spawned: this
    # isolates the plain counter increment from the escalation path entirely.
    with open(cache_file(actor)) as fh:
        cache = json.load(fh)
    cache["tool_calls_since_user"] = 0
    with open(cache_file(actor), "w") as fh:
        json.dump(cache, fh)

    fire_parallel_blocks(actor, ledger, tmp_path)

    with open(cache_file(actor)) as fh:
        cache = json.load(fh)
    assert cache.get("tool_calls_since_user") == PARALLEL_FIRES, (
        "counted %r of %d parallel tool calls; the rest were lost to the "
        "unlocked read-modify-write, so the ceiling undercounts a fan-out "
        "exactly when it is most needed (sp-016776e6)"
        % (cache.get("tool_calls_since_user"), PARALLEL_FIRES))


if __name__ == "__main__":
    # REQUIRED, not decoration. capability-gate.py runs a `runner: python3`
    # entry as `python3 <file>`, so a pytest-only module would define its tests,
    # call none of them, and exit 0 — registered, green, and enforcing nothing.
    sys.exit(pytest.main([__file__, "-v"]))
