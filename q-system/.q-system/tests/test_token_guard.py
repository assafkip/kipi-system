"""Black-box tests for the token-guard circuit breaker (sp0-guard-actor-scope).

The script is hyphen-named, so every test drives it as a subprocess with a
piped hook-JSON payload — exactly how the Claude Code hook runner invokes it.

Covers the issue's paired contract:
  feature  — a single spinning actor still hits its own VOLUME_CEILING (exit 2)
  bypass   — actors are isolated: a subagent (distinct agent_id) neither
             inherits nor increments the parent's counter; a parent at the
             ceiling does not block a subagent
  valve    — a repo HEAD commit newer than the last volume reset lifts the
             ceiling at PreToolUse time (wiring B, the dead-valve fix)
  PostToolUse — a successful `git commit` Bash event zeroes the volume
             counters (wiring A; settings.json routes Bash here)
  reset    — UserPromptSubmit zeroes per-message counters
  TTL      — caches older than CACHE_TTL_DAYS are swept on UserPromptSubmit

Evidence for the actor discriminator (agent_id, absent on main-session events)
is in q-system/output/guard-payload-dump.json, captured live 2026-06-11.
"""

import json
import os
import subprocess
import time
import uuid

import pytest

GUARD = os.path.join(os.path.dirname(__file__), "..", "token-guard.py")
VOLUME_CEILING = 50


def run_guard(payload, env_overrides=None):
    """Invoke the guard exactly as the hook runner does: JSON on stdin."""
    env = dict(os.environ)
    env.update(env_overrides or {})
    return subprocess.run(
        ["python3", GUARD], input=json.dumps(payload),
        capture_output=True, text=True, timeout=10, env=env,
    )


def cache_file(actor_key):
    return f"/tmp/claude-guard-{actor_key}.json"


def seed_cache(actor_key, **overrides):
    """Write a cache file as the guard would, with overrides applied."""
    state = {
        "actor_key": actor_key,
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
    }
    state.update(overrides)
    with open(cache_file(actor_key), "w") as f:
        json.dump(state, f)
    return state


def read_cache(actor_key):
    with open(cache_file(actor_key)) as f:
        return json.load(f)


def pre_tool_use(session_id, tool="Read", agent_id=None, tool_input=None):
    payload = {
        "session_id": session_id,
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input if tool_input is not None else {"file_path": "/tmp/x"},
    }
    if agent_id:
        payload["agent_id"] = agent_id
    return payload


@pytest.fixture
def session_id():
    """Unique per-test session id; removes every cache it spawned."""
    sid = f"tgtest-{uuid.uuid4().hex[:10]}"
    yield sid
    import glob
    for path in glob.glob(f"/tmp/claude-guard-{sid}*.json"):
        try:
            os.remove(path)
        except OSError:
            pass


# --- feature: the breaker still fires for a single spinning actor -----------


def test_single_actor_at_ceiling_blocks(session_id):
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING - 1)
    result = run_guard(pre_tool_use(session_id))
    assert result.returncode == 2, result.stderr
    assert "50 tool calls" in result.stderr


def test_below_ceiling_allows(session_id):
    seed_cache(session_id, tool_calls_since_user=5)
    result = run_guard(pre_tool_use(session_id))
    assert result.returncode == 0, result.stderr


# --- bypass: per-actor isolation --------------------------------------------


def test_subagent_does_not_inherit_parent_ceiling(session_id):
    """Parent at the ceiling; a subagent call (same session, own agent_id)
    must pass — this is the fan-out freeze observed live, inverted."""
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 10)
    result = run_guard(pre_tool_use(session_id, agent_id="agentA"))
    assert result.returncode == 0, result.stderr


def test_subagent_does_not_increment_parent_counter(session_id):
    seed_cache(session_id, tool_calls_since_user=7)
    run_guard(pre_tool_use(session_id, agent_id="agentA"))
    assert read_cache(session_id)["tool_calls_since_user"] == 7
    assert read_cache(f"{session_id}-agent-agentA")["tool_calls_since_user"] == 1


def test_two_subagents_have_independent_counters(session_id):
    seed_cache(f"{session_id}-agent-agentA",
               tool_calls_since_user=VOLUME_CEILING - 1)
    blocked = run_guard(pre_tool_use(session_id, agent_id="agentA"))
    free = run_guard(pre_tool_use(session_id, agent_id="agentB"))
    assert blocked.returncode == 2
    assert free.returncode == 0


def test_spinning_subagent_hits_its_own_ceiling(session_id):
    """Per-actor scoping must not silence the breaker for the subagent itself."""
    seed_cache(f"{session_id}-agent-agentA",
               tool_calls_since_user=VOLUME_CEILING - 1)
    result = run_guard(pre_tool_use(session_id, agent_id="agentA"))
    assert result.returncode == 2


# --- valve (wiring B): HEAD commit newer than last reset lifts the ceiling --


@pytest.fixture
def fake_repo(tmp_path):
    """A real git repo with one commit, used as CLAUDE_PROJECT_DIR."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "seed"],
                   cwd=repo, check=True)
    return str(repo)


def test_commit_newer_than_reset_lifts_ceiling(session_id, fake_repo):
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 3,
               last_volume_reset=time.time() - 3600)
    result = run_guard(pre_tool_use(session_id),
                       env_overrides={"CLAUDE_PROJECT_DIR": fake_repo})
    assert result.returncode == 0, result.stderr
    assert read_cache(session_id)["tool_calls_since_user"] == 0


def test_no_new_commit_keeps_block(session_id, fake_repo):
    """Reset stamped AFTER the HEAD commit -> no progress since -> still blocks."""
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 3,
               last_volume_reset=time.time() + 60)
    result = run_guard(pre_tool_use(session_id),
                       env_overrides={"CLAUDE_PROJECT_DIR": fake_repo})
    assert result.returncode == 2


def test_valve_outside_repo_fails_closed(session_id, tmp_path):
    """No repo at CLAUDE_PROJECT_DIR -> valve is a no-op, block stands."""
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 3,
               last_volume_reset=time.time() - 3600)
    result = run_guard(pre_tool_use(session_id),
                       env_overrides={"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert result.returncode == 2


# --- valve (wiring A): PostToolUse Bash commit reset -------------------------


def test_post_tool_use_successful_commit_resets(session_id):
    seed_cache(session_id, tool_calls_since_user=40)
    payload = {
        "session_id": session_id,
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m 'ship'"},
        "tool_response": {"stdout": "1 file changed", "stderr": ""},
    }
    result = run_guard(payload)
    assert result.returncode == 0
    cache = read_cache(session_id)
    assert cache["tool_calls_since_user"] == 0
    assert cache["last_volume_reset"] > 0


def test_post_tool_use_noop_commit_does_not_reset(session_id):
    seed_cache(session_id, tool_calls_since_user=40)
    payload = {
        "session_id": session_id,
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m 'ship'"},
        "tool_response": {"stdout": "nothing to commit", "stderr": ""},
    }
    run_guard(payload)
    assert read_cache(session_id)["tool_calls_since_user"] == 40


# --- UserPromptSubmit reset + TTL sweep --------------------------------------


def test_user_prompt_submit_resets_main_actor(session_id):
    seed_cache(session_id, tool_calls_since_user=49)
    payload = {"session_id": session_id, "hook_event_name": "UserPromptSubmit"}
    result = run_guard(payload)
    assert result.returncode == 0
    assert read_cache(session_id)["tool_calls_since_user"] == 0


def test_stale_caches_swept_on_user_prompt_submit(session_id):
    stale_key = f"{session_id}-agent-stale"
    fresh_key = f"{session_id}-agent-fresh"
    seed_cache(stale_key)
    seed_cache(fresh_key)
    eight_days_ago = time.time() - 8 * 86400
    os.utime(cache_file(stale_key), (eight_days_ago, eight_days_ago))
    run_guard({"session_id": session_id, "hook_event_name": "UserPromptSubmit"})
    assert not os.path.exists(cache_file(stale_key))
    assert os.path.exists(cache_file(fresh_key))

def test_auto_commit_subject_is_not_progress(session_id, fake_repo):
    """The 15-minute auto-committer must not lift the ceiling."""
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m",
                    "chore: update project files"], cwd=fake_repo, check=True)
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 3,
               last_volume_reset=time.time() + 60)
    result = run_guard(pre_tool_use(session_id),
                       env_overrides={"CLAUDE_PROJECT_DIR": fake_repo})
    assert result.returncode == 2
