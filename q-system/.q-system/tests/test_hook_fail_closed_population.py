#!/usr/bin/env python3
"""No security gate may crash OPEN (ASK-1180).

## The class

A blocking hook refuses only when one line runs: `sys.exit(2)` or a deny-JSON
print. An uncaught exception exits 1, which is neither, so the tool call goes
through. Two members were measured through the real stdin interface:
merge-bypass-gate (ASK-1179, a NameError on the plain squash merge, EXIT=1 and no
deny) and claude-path-write-guard (a crash as the first statement of analyse():
rc=1, blocks=False, while the live guard returned rc=2 on the same payload).

## What this file proves, and how

1. CENSUS BY CODE. Every blocking hook wired in settings-template.json (what
   ships to the fleet) and in the skeleton's own .claude/settings.json is
   enumerated from the files, and each must be CLASSIFIED below. A new blocking
   hook fails this file until someone decides whether it is a security gate.
   A hook wired with a trailing `|| true` cannot block and is not in the census.

2. For each security gate, on a temp copy and never the live tree:
   - control: the unmutated copy REFUSES the payload (so the payload is real);
   - crash: `raise RuntimeError(SENTINEL)` is injected as the first statement of
     each named decision function, the same payload is driven through stdin, and
     the copy must still refuse. The SENTINEL must appear on stderr, which proves
     the injected crash actually fired: a refusal from a copy whose mutant never
     ran would be the ordinary refusal, not evidence (the ASK-1180 comment
     records exactly that mismeasurement once, inside a swallowing `except`);
   - out of jurisdiction: a crashed copy must ALLOW input the gate never
     governed, because several of these run on every Bash call and a blanket
     deny would brick the session;
   - helper absent: with hook_fail_closed.py missing, the gate must still
     refuse. Deleting one shared file must not reopen six gates.

## The ref hatch

    git show <pre-fix-sha>:q-system/.q-system/scripts > ... (whole dir)
    KIPI_FAILCLOSED_SCRIPTS=/path/to/old/scripts python3 -m pytest <this file>

loads every gate from that directory instead, which is how this suite was
watched going red on the code it fixes.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
SCRIPTS = Path(os.environ.get("KIPI_FAILCLOSED_SCRIPTS") or (HERE.parent / "scripts"))
HELPER = "hook_fail_closed.py"
SENTINEL = "ASK1180-INJECTED-CRASH"

SETTINGS_FILES = (ROOT / "settings-template.json", ROOT / ".claude" / "settings.json")
BLOCKING_EVENTS = {"PreToolUse", "PostToolUse", "Stop", "SubagentStop", "UserPromptSubmit"}
# Any .py a hook command names, wherever it lives. The first version matched three
# q-system directories only, so a gate under plugins/ was invisible rather than
# unclassified (PR #427 round 2).
SCRIPT_RE = re.compile(r"([A-Za-z0-9_\-]+\.py)\b")
NEVER_BLOCKS_RE = re.compile(r"\|\|\s*true\s*$")

# The six ASK-1180 names as security gates: a crash in any of them costs exactly
# the thing it exists to prevent, and is not recoverable.
SECURITY = {
    "merge-bypass-gate.py", "claude-path-write-guard.py", "code_claim_grounding_guard.py",
    "prompt-only-enforcement-guard.py", "settings-template-sync-check.py",
    "claude-integrity-tripwire.py",
}

# Every other blocking hook, classified on purpose. ASK-1180 scopes these out
# ("lints stay as they are"): a lint failing open costs one bad file landing.
# Moving a name from here to SECURITY is how the tail gets picked up.
NOT_SECURITY = {
    "token-guard.py", "read-first-gate.py", "agent-brief-one-job-guard.py", "miyo-research-gate.py", "design-chain-gate.py",
    "design-engine-door.py", "enforced-claim-lint.py", "voice-lint.py",
    "voice-substance-lint.py", "voiceloop-band-lint.py", "memory-confidence-validator.py",
    "consumer-parity-check.py", "audhd-lint.py", "batch-uniformity-lint.py",
    "decision-origin-tag-lint.py", "format-lint.py", "linear-filer-label-lint.py",
    "headline-lint.py", "spillover-ratchet.py", "lessons-validator.py",
    "linkedin-format-lint.py", "wiring-check.py", "plan-lint.py", "instrument-lint.py",
    "instance-automation-guard.py", "client-output-evidence-gate.py",
    "handoff-provenance-lint.py", "hook_envelope_audit.py", "hook-path-resolve-check.py",
    "portability-lint-hook.py", "blocked-claim-evidence-lint.py", "voice-stop-gate.py",
    "kb-graph-guard.py", "auto-commit.py", "knowledge-inject.py", "lessons-inject.py",
    "voice-dna-loader.py", "capability-claim-lint.py", "evidence-read-log-lint.py",
    "worktree-disk-floor.py",
}


def wired_blocking_hooks() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for settings in SETTINGS_FILES:
        data = json.loads(settings.read_text())
        for event, groups in data.get("hooks", {}).items():
            if event not in BLOCKING_EVENTS:
                continue
            for group in groups:
                for hook in group.get("hooks", []):
                    command = hook.get("command", "").strip()
                    if NEVER_BLOCKS_RE.search(command):
                        continue
                    for name in SCRIPT_RE.findall(command):
                        found.setdefault(name, set()).add(event)
    return found


def test_census_is_not_empty():
    # A census that read nothing would pass every classification check below.
    hooks = wired_blocking_hooks()
    assert len(hooks) >= 20, f"only {len(hooks)} blocking hooks enumerated: {sorted(hooks)}"
    assert SECURITY <= set(hooks), f"security gates not wired: {sorted(SECURITY - set(hooks))}"


def test_every_blocking_hook_is_classified():
    unclassified = sorted(set(wired_blocking_hooks()) - SECURITY - NOT_SECURITY)
    assert not unclassified, (
        "blocking hook(s) wired with no ASK-1180 classification. Decide: is a crash "
        "here a security hole (add to SECURITY with a case below) or a lint (add to "
        f"NOT_SECURITY)? {unclassified}")


# ---------------------------------------------------------------------------
# harness


def _bash(command: str, cwd: Path) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd),
            "tool_input": {"command": command}}


def _write(path: Path, content: str) -> dict:
    return {"hook_event_name": "PostToolUse", "tool_name": "Write",
            "tool_input": {"file_path": str(path), "content": content}}


def _edit(path: Path) -> dict:
    return {"hook_event_name": "PostToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": str(path), "old_string": "a", "new_string": "b"}}


def _git(root: Path, *argv: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True, env=env)


def _stage(tmp: Path, name: str, with_helper: bool = True) -> Path:
    """Copy one gate (and the helper) into a skeleton-shaped temp tree."""
    dest = tmp / "q-system" / ".q-system" / "scripts"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPTS / name, dest / name)
    if with_helper and (SCRIPTS / HELPER).exists():
        shutil.copy2(SCRIPTS / HELPER, dest / HELPER)
    return dest / name


def _inject(gate: Path, func: str) -> None:
    """raise SENTINEL as the first statement of `func`. Refuses if it cannot."""
    source = gate.read_text()
    node = next((n for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.FunctionDef) and n.name == func), None)
    assert node is not None, f"{gate.name} has no function {func}(); the case list is stale"
    first = node.body[0]
    lines = source.splitlines(keepends=True)
    indent = " " * first.col_offset
    lines.insert(first.lineno - 1, f"{indent}raise RuntimeError({SENTINEL!r})\n")
    mutated = "".join(lines)
    assert mutated != source
    compile(mutated, str(gate), "exec")
    gate.write_text(mutated)


def _run(gate: Path, payload: dict | None, argv=(), env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["KIPI_NOTIFY"] = "/usr/bin/true"  # a test never pages anyone
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(env_extra or {})
    stdin = "" if payload is None else json.dumps(payload)
    return subprocess.run([sys.executable, str(gate), *argv], input=stdin, env=env,
                          capture_output=True, text=True, timeout=120, cwd=str(gate.parent))


def _refused(proc) -> bool:
    if proc.returncode == 2:
        return True
    try:
        out = json.loads(proc.stdout or "{}")
    except ValueError:
        return False
    hso = out.get("hookSpecificOutput") or {}
    return hso.get("permissionDecision") == "deny" or out.get("decision") == "block"


# ---------------------------------------------------------------------------
# per-gate cases: (setup(tmp) -> (in_payload, out_payload, argv, env), decision functions)


def _merge(tmp):
    return _bash("gh pr merge 155 --squash", tmp), _bash("ls -la", tmp), (), {}


def _path_guard(tmp):
    return _bash("touch .claude/_probe.txt", tmp), _bash("ls -la", tmp), (), {}


def _grounding(tmp):
    (tmp / "docs").mkdir(exist_ok=True)
    (tmp / "docs" / "notes.md").write_text("real file\n")
    transcript = tmp / "transcript.jsonl"
    rows = [
        {"message": {"role": "user", "content": [{"type": "text", "text": "is it fine?"}]}},
        {"message": {"role": "assistant", "content": [
            {"type": "text", "text": "I checked docs/notes.md and it is fine."}]}},
    ]
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    inside = {"hook_event_name": "Stop", "stop_hook_active": False,
              "transcript_path": str(transcript)}
    outside = dict(inside, stop_hook_active=True)
    return inside, outside, (), {"CLAUDE_PROJECT_DIR": str(tmp)}


# prompt-only-enforcement-skip
# ^ the claim below is the FIXTURE under test: the sentence the guard exists to
#   refuse, fed to a temp copy to prove it still refuses when it crashes.
def _prompt_only(tmp):
    claim = "# Rule\n\nThis behavior is enforced by the prompt.\n"
    return (_write(tmp / "rule.md", claim), _write(tmp / "image.png", claim), (),
            {"CLAUDE_PROJECT_DIR": str(tmp)})


def _sync(tmp):
    hook = lambda s: {"hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
        {"type": "command", "command": f"python3 q-system/.q-system/scripts/{s}"}]}]}}
    (tmp / ".claude").mkdir(exist_ok=True)
    (tmp / ".claude" / "settings.json").write_text(json.dumps(hook("stranded-lint.py")))
    (tmp / "settings-template.json").write_text(json.dumps({"hooks": {}}))
    return (_edit(tmp / "settings-template.json"), _edit(tmp / "README.md"), (),
            {"CLAUDE_PROJECT_DIR": str(tmp)})


def _tripwire(tmp):
    rules = tmp / ".claude" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / "a.md").write_text("sanctioned\n")
    _git(tmp, "init", "-q")
    _git(tmp, "add", "-A")
    _git(tmp, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    gate = tmp / "q-system" / ".q-system" / "scripts" / "claude-integrity-tripwire.py"
    base = _run(gate, None, ("--baseline", "--quiet"))
    assert base.returncode == 0, base.stderr
    (rules / "a.md").write_text("tampered\n")
    # Its jurisdiction is the whole tree on every call, so there is no
    # out-of-jurisdiction input to test.
    return _edit(rules / "a.md"), None, ("--enforce", "--quiet"), {}


CASES = {
    "merge-bypass-gate.py": (_merge, ["main", "classify"]),
    "claude-path-write-guard.py": (_path_guard, ["main", "analyse"]),
    "code_claim_grounding_guard.py": (_grounding, ["main", "evaluate_subsystems", "evaluate"]),
    "prompt-only-enforcement-guard.py": (_prompt_only, ["main", "scan_payload"]),
    "settings-template-sync-check.py": (_sync, ["main", "find_divergence", "scripts_in_hooks"]),
    "claude-integrity-tripwire.py": (_tripwire, ["main", "verify"]),
}


def test_every_security_gate_has_a_case():
    assert set(CASES) == SECURITY


def _prepared(tmp_path, name, with_helper=True):
    gate = _stage(tmp_path, name, with_helper)
    setup, _funcs = CASES[name]
    inside, outside, argv, env = setup(tmp_path)
    return gate, inside, outside, argv, env


@pytest.mark.parametrize("name", sorted(CASES))
def test_control_the_live_copy_refuses(tmp_path, name):
    gate, inside, _out, argv, env = _prepared(tmp_path, name)
    proc = _run(gate, inside, argv, env)
    assert _refused(proc), (f"{name}: the unmutated copy did not refuse, so this payload "
                            f"proves nothing. rc={proc.returncode} out={proc.stdout[-300:]!r} "
                            f"err={proc.stderr[-600:]!r}")


CRASH_CASES = [(n, f) for n in sorted(CASES) for f in CASES[n][1]]


@pytest.mark.parametrize("name,func", CRASH_CASES)
def test_a_crash_in_the_decision_path_still_refuses(tmp_path, name, func):
    gate, inside, _out, argv, env = _prepared(tmp_path, name)
    _inject(gate, func)
    proc = _run(gate, inside, argv, env)
    assert SENTINEL in proc.stderr, (
        f"{name}:{func}: the injected crash never reached stderr, so either it did "
        f"not fire on this path or something SWALLOWED it silently. "
        f"rc={proc.returncode} err={proc.stderr[-600:]!r}")
    assert _refused(proc), (f"{name}:{func} CRASHES OPEN: rc={proc.returncode} "
                            f"out={proc.stdout[-300:]!r} err={proc.stderr[-400:]!r}")


OUTSIDE_CASES = [(n, f) for n, f in CRASH_CASES if n != "claude-integrity-tripwire.py"]


@pytest.mark.parametrize("name,func", OUTSIDE_CASES)
def test_a_crash_outside_the_jurisdiction_allows(tmp_path, name, func):
    gate, _in, outside, argv, env = _prepared(tmp_path, name)
    _inject(gate, func)
    proc = _run(gate, outside, argv, env)
    assert not _refused(proc), (f"{name}:{func} refused input it never governed after a "
                                f"crash; on a Bash matcher that bricks the session. "
                                f"rc={proc.returncode} err={proc.stderr[-400:]!r}")


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_missing_helper_does_not_reopen_the_gate(tmp_path, name):
    gate, inside, _out, argv, env = _prepared(tmp_path, name, with_helper=False)
    _inject(gate, CASES[name][1][0])
    proc = _run(gate, inside, argv, env)
    assert _refused(proc), (f"{name}: with {HELPER} absent, a crash opened the gate. "
                            f"rc={proc.returncode} err={proc.stderr[-400:]!r}")


def test_layer2_watches_the_helper(tmp_path):
    """A tampered helper disables six gates with no signal, so Layer 2 must restore it."""
    gate = _stage(tmp_path, "claude-integrity-tripwire.py")
    helper = gate.parent / HELPER
    assert helper.exists(), "helper was not staged"
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    assert _run(gate, None, ("--baseline", "--quiet")).returncode == 0
    clean = helper.read_text()
    helper.write_text(clean + "\n\ndef run(call, *, gate, in_jurisdiction):\n    return 0\n")
    proc = _run(gate, None, ("--enforce", "--quiet"))
    assert proc.returncode == 2, f"tamper not acted on: rc={proc.returncode} err={proc.stderr[-400:]!r}"
    assert helper.read_text() == clean, "Layer 2 did not restore the tampered helper"


def test_census_sees_a_hook_outside_q_system():
    assert SCRIPT_RE.findall('python3 "$CLAUDE_PROJECT_DIR/plugins/kipi-core/hooks/new-gate.py"') \
        == ["new-gate.py"]


@pytest.mark.parametrize("helper", [True, False], ids=["helper", "inline-fallback"])
def test_unparseable_payload_verdict_is_the_same_with_or_without_the_helper(tmp_path, helper):
    """A crash on whitespace stdin must not refuse every Bash call when the helper is gone."""
    gate = _stage(tmp_path, "merge-bypass-gate.py", with_helper=helper)
    _inject(gate, "main")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    proc = subprocess.run([sys.executable, str(gate)], input="   \n", env=env,
                          capture_output=True, text=True, timeout=60)
    assert SENTINEL in proc.stderr, proc.stderr[-400:]
    assert proc.returncode == 0, f"helper={helper}: rc={proc.returncode} err={proc.stderr[-300:]!r}"


def test_sync_check_preflight_exits_even_if_main_returns(tmp_path):
    """--check must never fall through into the stdin-reading hook path."""
    gate = _stage(tmp_path, "settings-template-sync-check.py")
    src = gate.read_text()
    anchor = "def main():\n"
    assert src.count(anchor) == 1
    gate.write_text(src.replace(anchor, anchor + "    return 0\n", 1))
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    p = subprocess.Popen([sys.executable, str(gate), "--check"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        rc = p.wait(timeout=15)  # stdin stays open: the kipi update shape
    except subprocess.TimeoutExpired:
        p.kill()
        pytest.fail("--check fell through and blocked reading stdin")
    finally:
        p.stdin.close()
    assert rc == 0


# ---------------------------------------------------------------------------
# ASK-4207: the voice gates' WRAPPERS fail closed.
#
# The cases above inject a crash into a gate's Python. The voice gates also had
# a hole one layer out, in the wired shell command. The template wrapped them in
# `if [ -f X ]; then python3 X; fi`, so a missing script ran nothing and exited
# 0, and every instance's voice check passed unchecked text without a word. An
# uncaught exception exits 1, which the harness treats as non-blocking, so a
# crash passed it too. Measured on de746fa7: the template's five voice entries
# exited 0 with the script missing and 1 on a crash.
#
# The K1a guard (ASK-4249, test-settings-merge.sh) is a SEPARATE entry beside an
# instance gate. It cannot be one here: the merge keys a q-system/ script by its
# basename, so a separate guard and its hook read as one key and the second is
# dropped (pinned below). The guard therefore sits inside the same entry, with
# the K1a message, and every mention of the script keeps the anchored
# $CLAUDE_PROJECT_DIR/q-system/ spelling so the retired-hook drop still sees the
# whole entry as the skeleton's.

VOICE_GATES = ("voice-lint.py", "voice-substance-lint.py", "voiceloop-band-lint.py",
               "voice-stop-gate.py")
VOICE_RESTORE = "Restore it: kipi update"
VOICE_SCRIPT_DIR = "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/"
# The shape every voice entry carried before ASK-4207: the merge test below feeds
# it in as an instance's stale copy.
VOICE_OLD_FORM = 'if [ -f "{p}" ]; then python3 "{p}"{a}; fi'


def _voice_entries():
    """(settings file, event, gate, command) for every wired voice-gate command."""
    out = []
    for settings in SETTINGS_FILES:
        for event, groups in json.loads(settings.read_text()).get("hooks", {}).items():
            for group in groups:
                for hook in group.get("hooks", []):
                    command = hook.get("command", "")
                    gates = [g for g in VOICE_GATES if "scripts/" + g in command]
                    if gates:
                        out.append((settings.name, event, gates[0], command))
    return out


VOICE_ENTRIES = _voice_entries()
VOICE_IDS = ["%s:%s:%s%s" % (f, e, g, ":drain" if "--drain-only" in c else "")
             for f, e, g, c in VOICE_ENTRIES]


def test_voice_census_reads_every_entry():
    # A census that read nothing would pass every case below. Each settings file
    # wires the three PostToolUse lints, the Stop gate and its SessionStart drain.
    want = {("PostToolUse", "voice-lint.py"), ("PostToolUse", "voice-substance-lint.py"),
            ("PostToolUse", "voiceloop-band-lint.py"), ("Stop", "voice-stop-gate.py"),
            ("SessionStart", "voice-stop-gate.py")}
    for settings in SETTINGS_FILES:
        got = {(e, g) for f, e, g, _ in VOICE_ENTRIES if f == settings.name}
        assert want <= got, f"{settings.name} lost voice entries: {sorted(want - got)}"
    assert len(VOICE_ENTRIES) == 10, VOICE_IDS


def test_voice_template_and_skeleton_agree():
    by_file = {}
    for f, e, _g, c in VOICE_ENTRIES:
        by_file.setdefault(f, set()).add((e, c))
    template, skeleton = (by_file[s.name] for s in SETTINGS_FILES)
    assert template == skeleton, sorted(template ^ skeleton)


def _run_voice(command, tree, body, stdin="{}"):
    """Run a wired command as the harness does: through sh, the project dir set."""
    scripts = tree / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    gate = next(g for g in VOICE_GATES if "scripts/" + g in command)
    if body is not None:
        (scripts / gate).write_text(body)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["CLAUDE_PROJECT_DIR"] = str(tree)
    return gate, subprocess.run(["/bin/sh", "-c", command], input=stdin, env=env,
                                capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("entry", VOICE_ENTRIES, ids=VOICE_IDS)
def test_voice_gate_missing_refuses_and_names_the_restore(tmp_path, entry):
    gate, proc = _run_voice(entry[3], tmp_path, None)
    assert proc.returncode == 2, f"rc={proc.returncode} with {gate} missing, wanted 2"
    assert f"{gate} missing: the gate cannot run" in proc.stderr, proc.stderr[-300:]
    assert VOICE_RESTORE in proc.stderr, proc.stderr[-300:]


@pytest.mark.parametrize("entry", VOICE_ENTRIES, ids=VOICE_IDS)
def test_voice_gate_crash_refuses(tmp_path, entry):
    # Crash mapping: in hook mode none of these scripts exits 1 on purpose (their
    # only sys.exit(1) is an argv usage error the wired command never reaches), so
    # any exit other than 0 or 2 is an uncaught exception and must refuse.
    gate, proc = _run_voice(entry[3], tmp_path, f"raise RuntimeError({SENTINEL!r})\n")
    assert SENTINEL in proc.stderr, f"the stub never ran: {proc.stderr[-300:]}"
    assert proc.returncode == 2, f"rc={proc.returncode} on a crash of {gate}, wanted 2"
    assert f"{gate} crashed (exit 1): the gate cannot run" in proc.stderr, proc.stderr[-300:]


@pytest.mark.parametrize("entry", VOICE_ENTRIES, ids=VOICE_IDS)
def test_voice_gate_verdict_passes_through(tmp_path, entry):
    # Negative control for the two cases above: a wrapper that refused everything
    # would pass them. A clean gate stays 0 with its stdout intact; a refusal
    # stays 2 with its own reason and no crash message.
    _, ok = _run_voice(entry[3], tmp_path / "ok", "print('GATE-OK')\n")
    assert ok.returncode == 0 and "GATE-OK" in ok.stdout, (ok.returncode, ok.stderr[-300:])
    _, no = _run_voice(entry[3], tmp_path / "no",
                       "import sys\nsys.stderr.write('GATE-REFUSED')\nsys.exit(2)\n")
    assert no.returncode == 2 and "GATE-REFUSED" in no.stderr, (no.returncode, no.stderr[-300:])
    assert "crashed" not in no.stderr, no.stderr[-300:]


# A broken gate on Stop must not wedge the session (PR #743 review, major). Exit 2
# on Stop keeps Claude going, and a missing or crashed script is a condition no
# turn can fix, so an unconditional 2 refuses every stop forever. The hooks docs:
# "The `stop_hook_active` field is `true` when Claude Code is already continuing as
# a result of a stop hook. Check this value or process the transcript to avoid
# blocking on a condition that will never resolve." So the first stop refuses with
# the message, and the continuation stop is let through with the message again.
VOICE_STOP = [(e, i) for e, i in zip(VOICE_ENTRIES, VOICE_IDS) if e[1] == "Stop"]
VOICE_BROKEN = {"missing": (None, "missing: the gate cannot run"),
                "crash": (f"raise RuntimeError({SENTINEL!r})\n", "crashed (exit 1): the gate cannot run")}
# Claude Code may serialize with or without the space; both must be read.
STOP_AGAIN = {"spaced": json.dumps({"hook_event_name": "Stop", "stop_hook_active": True}),
              "compact": json.dumps({"hook_event_name": "Stop", "stop_hook_active": True},
                                    separators=(",", ":"))}


def test_voice_stop_census_reads_both_files():
    assert len(VOICE_STOP) == 2, [i for _, i in VOICE_STOP]


@pytest.mark.parametrize("form", sorted(STOP_AGAIN))
@pytest.mark.parametrize("broken", sorted(VOICE_BROKEN))
@pytest.mark.parametrize("entry", [e for e, _ in VOICE_STOP], ids=[i for _, i in VOICE_STOP])
def test_voice_stop_wrapper_lets_the_continuation_stop_through(tmp_path, entry, broken, form):
    body, message = VOICE_BROKEN[broken]
    gate, proc = _run_voice(entry[3], tmp_path, body, stdin=STOP_AGAIN[form])
    assert proc.returncode == 0, (
        f"rc={proc.returncode} on a continuation stop with {gate} {broken}: the session "
        f"is wedged in a refusal no turn can fix")
    assert f"{gate} {message}" in proc.stderr, proc.stderr[-300:]


@pytest.mark.parametrize("stdin", [
    json.dumps({"hook_event_name": "Stop", "stop_hook_active": False}),
    json.dumps({"hook_event_name": "Stop"}),
    # The field's text inside a message is escaped JSON, not the field itself.
    json.dumps({"hook_event_name": "Stop", "stop_hook_active": False,
                "last_assistant_message": 'it sends "stop_hook_active": true'}),
], ids=["false", "absent", "quoted-in-message"])
@pytest.mark.parametrize("broken", sorted(VOICE_BROKEN))
@pytest.mark.parametrize("entry", [e for e, _ in VOICE_STOP], ids=[i for _, i in VOICE_STOP])
def test_voice_stop_wrapper_first_stop_still_refuses(tmp_path, entry, broken, stdin):
    # Negative control: a wrapper that let every broken stop through would pass the
    # case above. The first stop must refuse, or the broken gate is never reported.
    body, message = VOICE_BROKEN[broken]
    gate, proc = _run_voice(entry[3], tmp_path, body, stdin=stdin)
    assert proc.returncode == 2, f"rc={proc.returncode} with {gate} {broken}, wanted 2"
    assert f"{gate} {message}" in proc.stderr, proc.stderr[-300:]


@pytest.mark.parametrize("entry", [e for e, _ in VOICE_STOP], ids=[i for _, i in VOICE_STOP])
def test_voice_stop_wrapper_runs_a_present_gate_unchanged(tmp_path, entry):
    # The hatch is for a broken gate only. A present gate gets the payload byte for
    # byte and keeps its own refusal, continuation stop or not.
    body = ("import sys\nsys.stdout.write(sys.stdin.read())\n"
            "sys.stderr.write('GATE-REFUSED')\nsys.exit(2)\n")
    _, proc = _run_voice(entry[3], tmp_path, body, stdin=STOP_AGAIN["spaced"])
    assert proc.returncode == 2 and "GATE-REFUSED" in proc.stderr, (proc.returncode, proc.stderr)
    assert json.loads(proc.stdout) == json.loads(STOP_AGAIN["spaced"]), proc.stdout[-300:]
    assert "cannot run" not in proc.stderr, proc.stderr[-300:]


# PR #743 review, major, disposed: "PostToolUse voice-lint wrappers deny every
# Edit/Write when the script is absent or crashes." They cannot deny it. The hooks
# docs, exit code 2 table: "| `PostToolUse` | No | Shows stderr to Claude; the
# tool already ran |". The write has landed before the hook starts, so a broken
# lint costs a gate-cannot-run notice on each write until `kipi update` restores
# it, which is the fail-closed signal ASK-4207 exists for. This case pins the half
# a test can see: the wrapper returns 2 and leaves the written file as it was.
VOICE_POST = [(e, i) for e, i in zip(VOICE_ENTRIES, VOICE_IDS) if e[1] == "PostToolUse"]


@pytest.mark.parametrize("broken", sorted(VOICE_BROKEN))
@pytest.mark.parametrize("entry", [e for e, _ in VOICE_POST], ids=[i for _, i in VOICE_POST])
def test_voice_post_wrapper_leaves_the_written_file_on_disk(tmp_path, entry, broken):
    assert len(VOICE_POST) == 6, [i for _, i in VOICE_POST]
    draft = tmp_path / "notes" / "draft.md"
    draft.parent.mkdir()
    draft.write_text("already written by the tool\n")
    before = draft.stat()
    body, message = VOICE_BROKEN[broken]
    gate, proc = _run_voice(entry[3], tmp_path, body,
                            stdin=json.dumps(_write(draft, "already written by the tool\n")))
    assert proc.returncode == 2 and f"{gate} {message}" in proc.stderr, (proc.returncode,
                                                                          proc.stderr[-300:])
    assert draft.read_text() == "already written by the tool\n"
    assert draft.stat().st_mtime_ns == before.st_mtime_ns, "the wrapper touched the file"


def _settings_merge():
    import importlib.util
    spec = importlib.util.spec_from_file_location("kipi_settings_merge",
                                                  ROOT / "kipi-settings-merge.py")
    mod = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(mod)
    return mod


def _voice_commands(settings):
    return [h["command"] for gs in settings.get("hooks", {}).values() for g in gs
            for h in g["hooks"] if any("scripts/" + v in h.get("command", "") for v in VOICE_GATES)]


def test_the_update_merge_replaces_an_instance_stale_voice_wrapper():
    """Load path for instances: the update rebuilds settings.json from the
    template, so the template's fail-closed entry must win over the old wrapper an
    instance still carries, and must stay droppable as the skeleton's if retired."""
    merge = _settings_merge()
    template = json.loads(SETTINGS_FILES[0].read_text())
    stale = {"hooks": {}}
    for event, groups in template["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                command = hook.get("command", "")
                gate = next((g for g in VOICE_GATES if "scripts/" + g in command), None)
                if gate is None:
                    continue
                assert merge.hook_script_names(command) == {gate}, command
                assert merge._shows_skeleton(command), command
                old = VOICE_OLD_FORM.format(p=VOICE_SCRIPT_DIR + gate,
                                            a=" --drain-only" if "--drain-only" in command else "")
                grp = {"hooks": [{"type": "command", "command": old}]}
                if "matcher" in group:
                    grp["matcher"] = group["matcher"]
                stale["hooks"].setdefault(event, []).append(grp)
    report = []
    wired = _voice_commands(merge.merge_settings(template, stale, retired=frozenset(),
                                                 report=report))
    assert len(wired) == 5, wired
    assert not [c for c in wired if c.startswith("if ")], f"a stale wrapper survived: {wired}"
    assert not report, report
    # Retirement still reaches the new entry, because every script mention in it
    # is anchored: a fail-closed entry that outlived its script would refuse forever.
    left = _voice_commands(merge.merge_settings({"hooks": {}}, {"hooks": template["hooks"]},
                                                retired=frozenset(VOICE_GATES), report=[]))
    assert not left, f"a retired voice gate's fail-closed entry would outlive it: {left}"


def test_a_separate_guard_for_a_q_system_gate_is_deduped():
    """Why the guard is not a separate K1a entry here: the merge keys both by the
    basename and keeps only the first, so the guard would silently vanish."""
    merge = _settings_merge()
    p = VOICE_SCRIPT_DIR + "voice-lint.py"
    hook = VOICE_OLD_FORM.format(p=p, a="")
    guard = f'test -f "{p}" || {{ echo "voice-lint.py missing: the gate cannot run" >&2; exit 2; }}'
    tpl = {"hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [
        {"type": "command", "command": hook}, {"type": "command", "command": guard}]}]}}
    merged = merge.merge_settings(tpl, {}, retired=frozenset(), report=[])
    assert [h["command"] for h in merged["hooks"]["PostToolUse"][0]["hooks"]] == [hook]
