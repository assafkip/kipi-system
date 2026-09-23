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
    "token-guard.py", "read-first-gate.py", "miyo-research-gate.py", "design-chain-gate.py",
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
    "voice-dna-loader.py",
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
