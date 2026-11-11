"""ASK-777: a coordinator message is a subagent's new turn.

UserPromptSubmit never fires for a subagent, so before this its volume counter
reset only on a commit. A lane that was committing, pushing and waiting on
review stopped at 50 calls (kipi-system #731, #729, 2026-11-11), and a resumed
lane started already at the ceiling because the cache outlives the resume.

The guard now reads the subagent's OWN transcript tail: a `type: user` row with
`origin.kind == "coordinator"` (the SendMessage shape, measured over 139 real
deliveries on 2026-11-10) newer than the last reset is that actor's
UserPromptSubmit. Rows the subagent can mint itself (task notifications from
its own background jobs, Stop-hook feedback, tool results) never reset it.

Every guard run here is isolated: its own session id, CLAUDE_PROJECT_DIR set to
a non-repo temp dir (so the commit valve cannot reset for the wrong reason),
Fable escalation off and its pending root in tmp_path.
"""

import glob
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone

import pytest

GUARD = os.path.join(os.path.dirname(__file__), "..", "token-guard.py")
VOLUME_CEILING = 50
AGENT = "agentA"


def iso(epoch):
    stamp = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return stamp[:-3] + "Z"


def row(kind=None, content="x", ts=None, tool_result=False, is_meta=True):
    message = {"role": "user", "content": content}
    if tool_result:
        message["content"] = [{"type": "tool_result", "tool_use_id": "t1",
                               "content": content}]
    entry = {"type": "user", "isSidechain": True, "message": message,
             "timestamp": iso(ts if ts is not None else time.time())}
    if is_meta:
        entry["isMeta"] = True
    if kind:
        entry["origin"] = {"kind": kind}
    return entry


def coordinator_row(ts=None):
    return row("coordinator", "The coordinator sent a message while you were "
               "working:\nreview verdict landed, continue", ts=ts)


@pytest.fixture
def lane(tmp_path):
    sid = f"tgturn-{uuid.uuid4().hex[:10]}"
    parent = tmp_path / f"{sid}.jsonl"
    parent.write_text("")
    own = tmp_path / sid / "subagents" / f"agent-{AGENT}.jsonl"
    own.parent.mkdir(parents=True)
    brief = row(content="You are Sana. Ship ASK-777.", is_meta=False,
                ts=time.time() - 3600)
    own.write_text(json.dumps(brief) + "\n")
    env = {"CLAUDECODE": "1", "CLAUDE_PROJECT_DIR": str(tmp_path),
           "KIPI_FABLE_ESCALATION": "0",
           "KIPI_FABLE_PENDING_ROOT": str(tmp_path / "pending")}
    yield {"sid": sid, "parent": str(parent), "own": own, "env": env}
    for path in glob.glob(f"/tmp/claude-guard-{sid}*"):
        try:
            os.remove(path)
        except OSError:
            pass


def append(lane, *entries):
    with open(lane["own"], "a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def call(lane, i, agent_id=AGENT):
    payload = {"session_id": lane["sid"], "hook_event_name": "PreToolUse",
               "tool_name": "Read", "tool_input": {"file_path": f"/tmp/tgturn-{i}"},
               "transcript_path": lane["parent"]}
    if agent_id:
        payload["agent_id"] = agent_id
    env = dict(os.environ)
    env.update(lane["env"])
    return subprocess.run(["python3", GUARD], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=10, env=env)


def seed(lane, calls, last_reset, agent_id=AGENT):
    key = f"{lane['sid']}-agent-{agent_id}" if agent_id else lane["sid"]
    state = {"actor_key": key, "tool_calls_since_user": calls,
             "agent_calls_since_user": 0, "mcp_timestamps": [], "repeat_map": {},
             "consecutive_reads": 0, "warnings_issued": 0, "file_read_counts": {},
             "greps_since_write": 0, "edit_targets": {}, "agents_without_write": 0,
             "last_write_time": time.time(), "calls_since_write": 0,
             "last_volume_reset": last_reset}
    with open(f"/tmp/claude-guard-{key}.json", "w") as f:
        json.dump(state, f)


def drive(lane, start, stop):
    """Return the 1-based index of the first blocked call, or None."""
    for i in range(start, stop + 1):
        result = call(lane, i)
        if result.returncode == 2:
            return i, result.stderr
        assert result.returncode == 0, result.stderr
    return None, ""


# --- reproducer: a working lane is not stopped by a count alone -------------


def test_productive_subagent_survives_55_calls(lane):
    """Red before ASK-777: call 50 blocked although the coordinator spoke at 45."""
    assert drive(lane, 1, 45) == (None, "")
    append(lane, coordinator_row())
    blocked_at, stderr = drive(lane, 46, 55)
    assert blocked_at is None, stderr


def test_resumed_subagent_at_the_ceiling_gets_a_new_turn(lane):
    """The 2026-08-14 fixture: a lane resumed at 50 was blocked on call one."""
    seed(lane, VOLUME_CEILING, last_reset=time.time() - 600)
    append(lane, coordinator_row())
    result = call(lane, 1)
    assert result.returncode == 0, result.stderr


# --- negative: a runaway still stops ----------------------------------------


def test_55_calls_with_no_coordinator_message_still_block(lane):
    blocked_at, stderr = drive(lane, 1, 55)
    assert blocked_at == VOLUME_CEILING
    assert "50 tool calls" in stderr


def test_rows_the_subagent_mints_itself_do_not_reset(lane):
    """Task notifications come from the lane's own background jobs: counting
    them would let `sleep 1` in a loop re-arm the budget (ASK-4144 class)."""
    assert drive(lane, 1, 45) == (None, "")
    append(lane,
           row("task-notification", "[SYSTEM NOTIFICATION] coordinator job done"),
           row(None, "Stop hook feedback: coordinator is waiting"),
           row(None, "coordinator", tool_result=True, is_meta=False),
           row("coordinator-ish", "coordinator"))
    blocked_at, _ = drive(lane, 46, 55)
    assert blocked_at == VOLUME_CEILING


def test_a_consumed_message_does_not_rearm(lane):
    """One coordinator message buys one window: a message older than the last
    reset (the one that already started this turn) resets nothing."""
    seed(lane, VOLUME_CEILING - 1, last_reset=time.time())
    append(lane, coordinator_row(ts=time.time() - 60))
    assert call(lane, 1).returncode == 2


def test_resumed_subagent_without_a_message_stays_blocked(lane):
    seed(lane, VOLUME_CEILING, last_reset=time.time() - 600)
    assert call(lane, 1).returncode == 2


def test_main_actor_ignores_coordinator_rows(lane):
    """The main actor resets on UserPromptSubmit only; its ceiling is unchanged."""
    with open(lane["parent"], "a") as f:
        f.write(json.dumps(coordinator_row()) + "\n")
    seed(lane, VOLUME_CEILING - 1, last_reset=time.time() - 600, agent_id=None)
    result = call(lane, 1, agent_id=None)
    assert result.returncode == 2
    assert "coordinator" not in result.stderr


def test_subagent_block_points_at_the_coordinator(lane):
    seed(lane, VOLUME_CEILING - 1, last_reset=time.time())
    result = call(lane, 1)
    assert result.returncode == 2
    assert "coordinator's next message" in result.stderr
    assert "50 tool calls" in result.stderr
