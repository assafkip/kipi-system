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

# The volume ceiling is off by default (founder 2026-11-21); this suite pins the mechanism, so it turns it on.
os.environ["KIPI_TOKEN_GUARD_VOLUME_CEILING"] = "1"

GUARD = os.path.join(os.path.dirname(__file__), "..", "token-guard.py")
VOLUME_CEILING = 50


def run_guard(payload, env_overrides=None):
    """Invoke the guard exactly as the hook runner does: JSON on stdin."""
    env = dict(os.environ)
    # THE RUNTIME MARKER IS AN INPUT, SO THIS HARNESS SETS IT.
    #
    # the scar (2026-08-27): token-guard.py's first statement is
    #     if not os.environ.get("CLAUDECODE"): sys.exit(0)
    # a deliberate circuit breaker so foreign runtimes (Codex loading the kipi
    # plugins through its own marketplace clone) never fire it. CLAUDECODE=1 is
    # set only by the Claude Code runtime.
    #
    # These tests INHERITED it. Every developer running them is inside Claude
    # Code, so it was always set and 14 passed. In GitHub Actions it does not
    # exist, the guard exited 0 before doing anything, and 12 tests failed
    # asserting a block that never came ("assert 0 == 2", where 0 is the
    # returncode) or a counter that never reset. Measured both ways on one
    # machine, same commit:
    #     env -u CLAUDECODE pytest test_token_guard.py -> 11 failed, 3 passed
    #                       pytest test_token_guard.py -> 14 passed
    #
    # Set BEFORE the overrides so a test can still blank it deliberately, which
    # is what test_a_foreign_runtime_is_a_no_op below does.
    env["CLAUDECODE"] = "1"
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


def test_three_identical_polls_are_not_a_retry(session_id):
    """Poll takes no input, so every Poll hashes the same. The harness adds
    Polls itself; the 3rd one blocked Sana agents twice on 2026-11-22 (ASK-5543)."""
    codes = [run_guard(pre_tool_use(session_id, tool="Poll", tool_input={})).returncode
             for _ in range(3)]
    assert codes == [0, 0, 0]


def test_three_identical_bash_calls_still_block(session_id):
    """The mutant for the Poll exemption: a real retry must still stop."""
    call = pre_tool_use(session_id, tool="Bash", tool_input={"command": "false"})
    codes = [run_guard(call).returncode for _ in range(3)]
    assert codes == [0, 0, 2]


def test_a_foreign_runtime_is_a_no_op(session_id):
    """The other half of the marker, which nothing covered.

    token-guard.py exits 0 immediately unless CLAUDECODE is set. That breaker
    exists because a UserPromptSubmit block once fired inside `codex exec` and
    killed an in-repo review (sp-28bf75a4). Every other test in this file now
    sets the marker, so without this one the no-op path would be asserted
    nowhere -- and it is the path that protects other runtimes.

    It also proves the harness fix is load-bearing rather than cosmetic: blank
    the marker and the guard stops blocking, which is exactly what CI was
    seeing."""
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 5)
    blocked = run_guard(pre_tool_use(session_id))
    assert blocked.returncode == 2, "sanity: this payload must block normally"

    inert = run_guard(pre_tool_use(session_id), env_overrides={"CLAUDECODE": ""})
    assert inert.returncode == 0, "a foreign runtime must never be blocked"
    assert inert.stdout == "", "a foreign runtime must not even emit context"


# --- the per-instance switch: 4 Points keeps the ceiling off (ASK-5487) -------
# Founder, 2026-11-19 (case-057), verbatim: "Remove the 50 tool guard for 4 points".
# The instance carries it as q-investigate/.guard-overrides.json. The fleet default
# went off on 2026-11-21, but KIPI_TOKEN_GUARD_VOLUME_CEILING=1 turns it back on,
# and the 4 Points ruling must hold through that too. The helper first lived only in
# the instance's q-system copy, which every skeleton sync overwrites.


def _instance(tmp_path, body):
    root = tmp_path / "instance"
    (root / "q-investigate").mkdir(parents=True)
    if body is not None:
        (root / "q-investigate" / ".guard-overrides.json").write_text(body)
    return {"CLAUDE_PROJECT_DIR": str(root)}


def test_instance_override_keeps_the_ceiling_off(session_id, tmp_path):
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 5)
    env = _instance(tmp_path, json.dumps({"volume_ceiling": "off"}))
    result = run_guard(pre_tool_use(session_id), env_overrides=env)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("body", [None, "{not json", json.dumps({"volume_ceiling": "on"}), json.dumps(["off"])])
def test_no_valid_override_keeps_the_ceiling(session_id, tmp_path, body):
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 5)
    result = run_guard(pre_tool_use(session_id), env_overrides=_instance(tmp_path, body))
    assert result.returncode == 2, result.stderr
    assert "50 tool calls" in result.stderr


def _git_spy(tmp_path):
    """A fake git first on PATH that records every call, so a test can see the probe."""
    bindir = tmp_path / "spybin"
    bindir.mkdir()
    log = tmp_path / "git-calls.log"
    spy = bindir / "git"
    spy.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit 1\n')
    spy.chmod(0o755)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"}, log


# Codex review of #883: with the ceiling off, every call past the warning count still
# ran `git log` (3s cap) for a check that could no longer refuse anything.
def test_override_off_skips_the_commit_probe(session_id, tmp_path):
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 5)
    env = _instance(tmp_path, json.dumps({"volume_ceiling": "off"}))
    path_env, log = _git_spy(tmp_path)
    env.update(path_env)
    result = run_guard(pre_tool_use(session_id), env_overrides=env)
    assert result.returncode == 0, result.stderr
    assert not log.exists(), f"probe ran with the ceiling off: {log.read_text()}"


def test_ceiling_on_still_pays_for_the_commit_probe(session_id, tmp_path):
    # The control: the spy must see the probe when the ceiling is live, or the
    # test above proves nothing.
    seed_cache(session_id, tool_calls_since_user=VOLUME_CEILING + 5)
    env = _instance(tmp_path, None)
    path_env, log = _git_spy(tmp_path)
    env.update(path_env)
    run_guard(pre_tool_use(session_id), env_overrides=env)
    assert log.exists() and "log" in log.read_text()
