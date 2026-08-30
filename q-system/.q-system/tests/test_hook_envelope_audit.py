#!/usr/bin/env python3
"""Pins hook_envelope_audit.py AND the fleet-shared hooks it audits.

Scar (measured 2026-08-30, q-system/.q-system/scripts/probe_hook_envelope.py):
Claude Code DISCARDS a hook's additionalContext unless it is nested under
hookSpecificOutput WITH hookEventName. voice-dna-loader.py shipped the nameless
shape from birth, so the founder's voice DNA never once reached the model, and
every downstream gate stayed green because they all measure the OUTPUT and none
check that the INPUT arrived.

Two halves, both of which have to be able to go red:
  1. the audit still tells the three measured shapes apart (its own self-test,
     including the arms that must NOT be flagged);
  2. every live hook in this repo emits the delivering shape.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
AUDIT = os.path.join(REPO, "q-system", ".q-system", "scripts", "hook_envelope_audit.py")


def _load():
    spec = importlib.util.spec_from_file_location("hook_envelope_audit", AUDIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load()


def test_self_test_passes():
    """The audit can still separate the three measured shapes."""
    assert audit.self_test(verbose=False) == []


@pytest.mark.parametrize("src,expected", [
    ('import json,sys\nsys.stdout.write(json.dumps({"hookSpecificOutput": '
     '{"hookEventName": "UserPromptSubmit", "additionalContext": "x"}}))\n', audit.OK),
    ('import json,sys\nsys.stdout.write(json.dumps({"hookSpecificOutput": '
     '{"additionalContext": "x"}}))\n', audit.NO_EVENT_NAME),
    ('import json,sys\nsys.stdout.write(json.dumps({"additionalContext": "x"}))\n',
     audit.TOP_LEVEL),
])
def test_classifies_the_three_measured_shapes(src, expected):
    got = [s.verdict for s in audit.audit_python("<probe>", source=src)]
    assert got == [expected]


def test_reads_and_assertions_are_not_emissions():
    """The false-positive class that would get this gate switched off.

    Before the text scanner learned that a '[' before the key means a subscript
    and a missing ':' after it means an operand, the audit reported ~700 defects
    in the very hook tests that assert the envelope is correct.
    """
    reads = (
        'python3 -c "import sys,json; a=json.load(sys.stdin)'
        "['hookSpecificOutput']['additionalContext']\"\n"
        'assert "additionalContext" not in out\n'
        '# Scar: warn() printed top-level {"additionalContext": ...}\n'
    )
    assert audit.audit_text("<reads>", source=reads) == []


# --------------------------------------------------------------------------
# The live hooks. A new hook added with the nameless envelope turns these red.
# --------------------------------------------------------------------------
LIVE_HOOK_DIRS = [
    os.path.join(REPO, "q-system", ".q-system", "scripts"),
    os.path.join(REPO, "q-system", "hooks"),
    os.path.join(REPO, "plugins"),
]


def test_every_live_hook_emits_the_delivering_shape():
    sites = []
    for root in LIVE_HOOK_DIRS:
        if not os.path.isdir(root):
            continue
        for path in audit.walk([root]):
            sites.extend(audit.audit_file(path))
    assert sites, "audited nothing -- the walk is broken, not the hooks"
    bad = [(s.path, s.line, s.verdict) for s in sites if s.verdict != audit.OK]
    assert bad == [], (
        "these hooks emit an envelope Claude Code discards: %r" % (bad,))


@pytest.mark.parametrize("script,prompt", [
    ("voice-dna-loader.py", "draft a linkedin post about hooks"),
    ("lessons-inject.py", "fix the token guard cache race"),
])
def test_userpromptsubmit_hooks_deliver_end_to_end(script, prompt):
    """Not the source shape -- the bytes the hook actually prints."""
    path = os.path.join(REPO, "q-system", ".q-system", "scripts", script)
    # A FRESH session id per run. A fixed one made lessons-inject.py emit
    # nothing on the second run ever -- its seen-cache had already recorded the
    # lessons as shown -- so this arm silently skipped instead of checking the
    # bytes. A skip that looks like a pass is the defect this whole file exists
    # to catch.
    payload = json.dumps({"session_id": "pytest-%s" % uuid.uuid4().hex[:12],
                          "hook_event_name": "UserPromptSubmit",
                          "prompt": prompt})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=REPO)
    proc = subprocess.run([sys.executable, path], input=payload, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        pytest.skip("%s emitted nothing for this prompt" % script)
    out = json.loads(proc.stdout)
    assert "additionalContext" not in out, "top-level additionalContext is discarded"
    hso = out["hookSpecificOutput"]
    assert hso.get("hookEventName") == "UserPromptSubmit", hso
    assert hso.get("additionalContext", "").strip(), "delivered an empty payload"


# --------------------------------------------------------------------------
# PostToolUse gate mode. exit 2 = block, exit 0 = pass (skill-hook-pairing.md).
# --------------------------------------------------------------------------
def _run_gate(file_path):
    payload = json.dumps({"tool_name": "Write",
                          "tool_input": {"file_path": str(file_path)}})
    return subprocess.run([sys.executable, AUDIT, "--hook"], input=payload,
                          capture_output=True, text=True, timeout=60)


def test_gate_blocks_a_discarded_envelope(tmp_path):
    bad = tmp_path / "badhook.py"
    bad.write_text('import json,sys\nsys.stdout.write(json.dumps('
                   '{"hookSpecificOutput": {"additionalContext": "x"}}))\n')
    proc = _run_gate(bad)
    assert proc.returncode == 2, proc.stdout
    assert "DISCARDS" in proc.stderr


def test_gate_passes_the_delivering_envelope(tmp_path):
    good = tmp_path / "goodhook.py"
    good.write_text('import json,sys\nsys.stdout.write(json.dumps('
                    '{"hookSpecificOutput": {"hookEventName": "SessionStart", '
                    '"additionalContext": "x"}}))\n')
    assert _run_gate(good).returncode == 0


def test_gate_fast_exits_on_an_unrelated_edit(tmp_path):
    other = tmp_path / "notes.md"
    other.write_text("# nothing to do with hooks\n")
    assert _run_gate(other).returncode == 0


def test_gate_passes_when_its_own_self_test_is_broken(tmp_path, monkeypatch):
    """A gate that cannot run must not block the session.

    The pytest layer above is what catches the envelope when this is inert; the
    gate's job is fast feedback, not being the only line.
    """
    bad = tmp_path / "badhook.py"
    bad.write_text('import json,sys\nsys.stdout.write(json.dumps('
                   '{"hookSpecificOutput": {"additionalContext": "x"}}))\n')
    mod = _load()
    monkeypatch.setattr(mod, "self_test", lambda verbose=True: [("broken", None, [])])
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": str(bad)}})))
    assert mod.hook_mode() == 0


# --------------------------------------------------------------------------
# --fix. Narrow on purpose: it adds a missing hookEventName and nothing else.
# --------------------------------------------------------------------------
def test_fix_adds_the_missing_event_name_and_the_result_runs(tmp_path):
    p = tmp_path / "hook.py"
    p.write_text('import json,sys\nsys.stdout.write(json.dumps('
                 '{"hookSpecificOutput": {"additionalContext": "x"}}))\n')
    n, _ = audit.fix_no_event_name(str(p), "UserPromptSubmit")
    assert n == 1
    assert [s.verdict for s in audit.audit_python(str(p))] == [audit.OK]
    proc = subprocess.run([sys.executable, str(p)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert out["hookSpecificOutput"]["additionalContext"] == "x"


def test_fix_refuses_top_level_and_unknown(tmp_path):
    """The two verdicts a machine must not guess at.

    TOP_LEVEL needs a human to say which event owns the payload and where the
    envelope belongs; UNKNOWN is unreadable by definition. Silently 'repairing'
    either would be the same defect as the bug it fixes.
    """
    top = tmp_path / "top.py"
    top.write_text('import json,sys\n'
                   'sys.stdout.write(json.dumps({"additionalContext": "x"}))\n')
    before = top.read_text()
    assert audit.fix_no_event_name(str(top), "PreToolUse")[0] == 0
    assert top.read_text() == before

    unk = tmp_path / "unk.py"
    unk.write_text('import json,sys\nk = "additional" + "Context"\n'
                   'sys.stdout.write(json.dumps({"hookSpecificOutput": {k: "x"}, '
                   '"additionalContext": "y", **{}}))\n')
    before = unk.read_text()
    assert audit.fix_no_event_name(str(unk), "PreToolUse")[0] == 0
    assert unk.read_text() == before


def test_fix_is_idempotent(tmp_path):
    p = tmp_path / "hook.py"
    p.write_text('import json,sys\nsys.stdout.write(json.dumps('
                 '{"hookSpecificOutput": {"additionalContext": "x"}}))\n')
    assert audit.fix_no_event_name(str(p), "SessionStart")[0] == 1
    once = p.read_text()
    assert audit.fix_no_event_name(str(p), "SessionStart")[0] == 0
    assert p.read_text() == once


# --------------------------------------------------------------------------
# The blocking path is scoped to files that are actually hooks (Codex minor,
# PR #285 round 2). A gate that stops an ordinary dict key gets switched off.
# --------------------------------------------------------------------------
def test_gate_ignores_an_ordinary_dict_key(tmp_path):
    """The reviewer's reproducer: an unrelated API payload must not be blocked."""
    p = tmp_path / "ordinary_api.py"
    p.write_text('payload = {"additionalContext": "ordinary API field"}\n')
    assert _run_gate(p).returncode == 0


def test_gate_still_blocks_a_real_hook_with_the_same_shape(tmp_path):
    """The control that keeps the scoping honest.

    The body markers are taken from the files that actually carried the defect,
    not invented: focus-kit's echo-of-prompt.py is the leanest of them and its
    only hook tell is reading its payload off stdin.
    """
    p = tmp_path / "echo_like_hook.py"
    p.write_text('import json,sys\n'
                 'payload = json.load(sys.stdin)\n'
                 'print(json.dumps({"additionalContext": "re-anchor"}))\n')
    proc = _run_gate(p)
    assert proc.returncode == 2, proc.stdout
    assert "DISCARDS" in proc.stderr


def test_reporting_path_still_surfaces_the_ordinary_dict(tmp_path):
    """Only the BLOCK is scoped. A human reading a full audit wants everything."""
    src = 'payload = {"additionalContext": "ordinary API field"}\n'
    assert [s.verdict for s in audit.audit_python("<api>", source=src)] == [audit.TOP_LEVEL]


# --------------------------------------------------------------------------
# Codex minors, PR #285 round 3. Both are the same mistake in opposite
# directions: the audit deciding something it could not see.
# --------------------------------------------------------------------------
def test_computed_key_inside_a_literal_envelope_is_unknown_not_absent(tmp_path):
    """It used to emit NO site at all, so the gate passed it at exit 0.

    `k = "additionalContext"` is a real way to write a hook, and an audit that
    silently sees nothing there is indistinguishable from an audit that checked
    and approved.
    """
    src = ('import json,sys\n'
           'k = "additionalContext"\n'
           'out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", k: "x"}}\n'
           'print(json.dumps(out))\n')
    assert [s.verdict for s in audit.audit_python("<dynamic>", source=src)] == [audit.UNKNOWN]

    p = tmp_path / "dynamic_hook.py"
    p.write_text(src)
    proc = _run_gate(p)
    assert proc.returncode == 2, proc.stdout
    assert "UNKNOWN" in proc.stderr


def test_a_stdin_filter_is_not_a_hook(tmp_path):
    """Bare `sys.stdin` was too weak: any filter program matched it."""
    p = tmp_path / "wc_like_filter.py"
    p.write_text('import sys\n'
                 'record = {"additionalContext": "ordinary field"}\n'
                 'for line in sys.stdin:\n'
                 '    record["additionalContext"] = line\n')
    assert _run_gate(p).returncode == 0


def test_a_hook_whose_only_tell_is_json_load_stdin_still_blocks(tmp_path):
    """The control. focus-kit's echo-of-prompt.py is exactly this shape."""
    p = tmp_path / "echo_like_hook.py"
    p.write_text('import json,sys\n'
                 'payload = json.load(sys.stdin)\n'
                 'print(json.dumps({"additionalContext": "re-anchor"}))\n')
    assert _run_gate(p).returncode == 2


# --------------------------------------------------------------------------
# Codex minors, PR #285 round 4. Two ordinary ways to build the payload that a
# walk over dict literals alone gets wrong, in both directions.
# --------------------------------------------------------------------------
def test_envelope_built_in_a_variable_is_not_called_top_level():
    """`hso = {...}` then `{"hookSpecificOutput": hso}` is correct code.

    Calling it TOP_LEVEL was a false BLOCK, and a gate that stops correct code
    is a gate that gets switched off.
    """
    src = ('import json, sys\n'
           'payload = json.load(sys.stdin)\n'
           'hso = {"hookEventName": "UserPromptSubmit", "additionalContext": "delivered"}\n'
           'out = {"hookSpecificOutput": hso}\n'
           'print(json.dumps(out))\n')
    assert [s.verdict for s in audit.audit_python("<aliased>", source=src)] == [audit.OK]


def test_additional_context_written_by_assignment_is_unknown_not_absent(tmp_path):
    """The payload built by subscript assignment produced NO site at all.

    Absent read as approved, so the gate passed a hook that delivers nothing.
    """
    src = ('import json, sys\n'
           'payload = json.load(sys.stdin)\n'
           'out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit"}}\n'
           'out["hookSpecificOutput"]["additionalContext"] = "lost"\n'
           'print(json.dumps(out))\n')
    assert [s.verdict for s in audit.audit_python("<incremental>", source=src)] == [audit.UNKNOWN]

    p = tmp_path / "incremental_hook.py"
    p.write_text(src)
    assert _run_gate(p).returncode == 2


def test_reading_that_same_subscript_is_still_not_an_emission():
    """The control that keeps the write-detection honest.

    A subscript in a TARGET position is a write; the same subscript in a value
    position is a read. Without this case the detector could flag every hook
    that merely inspects an incoming payload.
    """
    src = ('import json, sys\n'
           'payload = json.load(sys.stdin)\n'
           'ctx = payload["hookSpecificOutput"]["additionalContext"]\n'
           'print(ctx)\n')
    assert audit.audit_python("<read>", source=src) == []


# --------------------------------------------------------------------------
# Codex round 5. The gate was wired on Edit|Write|MultiEdit only, and a Bash
# write carries no file_path -- so it would never have fired on the very edits
# it was built for. This session wrote every one of its own hook fixes through
# Bash heredocs and python drivers.
# --------------------------------------------------------------------------
def _init_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def _run_bash_gate(root):
    payload = json.dumps({"tool_name": "Bash",
                          "tool_input": {"command": "python3 - <<EOF ... EOF"}})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return subprocess.run([sys.executable, AUDIT, "--hook"], input=payload,
                          env=env, capture_output=True, text=True, timeout=60)


def test_bash_leg_blocks_a_hook_written_without_a_file_path(tmp_path):
    """Judge the EFFECT, not the command text.

    Parsing the command for a path is the wrong layer, and this repo already
    carries the lesson: a guard that reads command text cannot see a computed
    path, and the careless wide rewrite is the one that computes its targets.
    """
    root = _init_repo(tmp_path / "repo")
    (root / "sneaky_hook.py").write_text(
        'import json, sys\n'
        'payload = json.load(sys.stdin)\n'
        'print(json.dumps({"additionalContext": "discarded"}))\n')
    proc = _run_bash_gate(root)
    assert proc.returncode == 2, proc.stdout
    assert "DISCARDS" in proc.stderr


def test_bash_leg_passes_when_nothing_hook_shaped_was_written(tmp_path):
    """The control. Blocking unrelated Bash work gets the gate switched off."""
    root = _init_repo(tmp_path / "repo")
    (root / "notes.md").write_text("# nothing to do with hooks\n")
    (root / "helper.py").write_text("def add(a, b):\n    return a + b\n")
    assert _run_bash_gate(root).returncode == 0


def test_bash_leg_ignores_a_file_written_long_ago(tmp_path):
    """A file broken last week must not wedge every Bash call in the session."""
    import time
    root = _init_repo(tmp_path / "repo")
    stale = root / "old_hook.py"
    stale.write_text('import json, sys\n'
                     'payload = json.load(sys.stdin)\n'
                     'print(json.dumps({"additionalContext": "discarded"}))\n')
    old = time.time() - (audit.RECENT_WRITE_SECONDS + 600)
    os.utime(stale, (old, old))
    assert _run_bash_gate(root).returncode == 0


def test_the_bash_leg_is_actually_wired(tmp_path):
    """A capability nobody wired is a capability nobody has."""
    for rel in (os.path.join("." + "claude", "settings.json"),
                "settings-template.json"):
        cfg = json.load(open(os.path.join(REPO, rel)))
        matchers = [g.get("matcher") for g in cfg["hooks"]["PostToolUse"]
                    for h in g["hooks"]
                    if "hook_envelope_audit" in h.get("command", "")]
        assert "Bash" in matchers, "%s wires the gate on %r only" % (rel, matchers)


def test_dict_construction_is_not_silently_approved():
    """dict(additionalContext=...) is invisible to a walk over dict literals.

    dict(**d) reports TOP_LEVEL rather than UNKNOWN because the aliased literal
    is itself un-nested; both are non-OK, which is what the gate acts on, and
    neither is the silent absence that started all of this.
    """
    kwargs_src = ('import json, sys\n'
                  'payload = json.load(sys.stdin)\n'
                  'print(json.dumps({"hookSpecificOutput": dict('
                  'hookEventName="UserPromptSubmit", additionalContext="x")}))\n')
    assert [s.verdict for s in audit.audit_python("<kw>", source=kwargs_src)] == [audit.UNKNOWN]

    star_src = ('import json, sys\n'
                'payload = json.load(sys.stdin)\n'
                'd = {"additionalContext": "x"}\n'
                'print(json.dumps({"hookSpecificOutput": dict(**d)}))\n')
    verdicts = [s.verdict for s in audit.audit_python("<star>", source=star_src)]
    assert verdicts and all(v != audit.OK for v in verdicts), verdicts


def test_an_ordinary_dict_call_is_not_an_emission():
    """The control for the dict() rule."""
    src = 'rows = dict(name="a", value="b")\nprint(rows)\n'
    assert audit.audit_python("<ordinary>", source=src) == []
