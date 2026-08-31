"""The skeleton Stop-gate routes a channel through an OPTIONAL instance registry.

The un-shipped half of prd-voice-gate-platform-aware-2026-07-22. The instance half
(cole-gtm/gtm/scripts/voice_channel_registry.py) shipped 2026-07-22 with tests; this half
did not, and `grep -c "voice_channel_registry\\|channel_registry"` against the gate
returned 0 for thirteen months. So consulting never received it and built a second channel
source of truth of its own, which is the defect the registry exists to prevent, recreated
one repo over.

TWO CLAIMS, and the second one outranks the first:

1. An instance WITH a registry grades a reddit-framed draft with the persona lint.
2. An instance with NO registry behaves exactly as it did before the registry existed.
   26 instances have no registry. A skeleton change that breaks them to add a feature
   one instance wants is not a feature.

Claim 2 is pinned by argv equality against the literal pre-change shape, not against a
baseline captured from the same code -- a baseline cannot see a change that moves both
sides (scar: "same as baseline" is a weak assert).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GATE = os.path.join(REPO, "q-system", ".q-system", "scripts", "voice-stop-gate.py")


def _load():
    spec = importlib.util.spec_from_file_location("voice_stop_gate_reg", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load()


def _registry(tmp_path, entry, default=None):
    """An instance tree whose registry lives at the in-repo default location."""
    data_dir = tmp_path / "q-system" / ".q-system" / "data"
    data_dir.mkdir(parents=True)
    reg = data_dir / "voice-channels.json"
    reg.write_text(json.dumps({
        "channels": {"reddit": entry},
        "default": default if default is not None else {"voice_ref": "voice",
                                                        "lint": "assaf"},
    }), encoding="utf-8")
    return reg


def _lint_script(tmp_path, name="persona_lint.py"):
    script = tmp_path / name
    script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    return script


# ------------------------------------------------------- claim 2: no registry, no change ----

def test_an_instance_with_no_registry_resolves_to_nothing(tmp_path):
    assert gate.resolve_channel_registry(tmp_path) is None


def test_no_registry_means_no_surface_lint(tmp_path):
    assert gate.channel_surface_lint(None, "reddit", tmp_path) is None


def test_the_argv_with_no_registry_is_the_pre_change_literal(tmp_path):
    """The exact list this file built before the registry existed:
        ["python3", str(script), file_path]
    Asserted as a literal on purpose. A baseline captured by calling the same helper
    twice would move with any change to it and prove nothing."""
    script = _lint_script(tmp_path, "voice-lint.py")
    assert gate._lint_argv(script, "/tmp/draft.md", gate.DEFAULT_LINT_INPUT) == [
        "python3", str(script), "/tmp/draft.md"]


def test_a_registered_assaf_channel_still_runs_the_assaf_lints(tmp_path):
    """A registry that exists but declares no surface lint for the channel is the same
    answer as no registry: None. Otherwise adding a registry for ONE channel would
    silently change every other channel in that instance."""
    reg = _registry(tmp_path, {"voice_ref": "voice", "lint": "assaf"})
    assert gate.channel_surface_lint(reg, "linkedin", tmp_path) is None


# ------------------------------------------------------ claim 1: a registry routes reddit ----

def test_a_registry_routes_reddit_to_its_surface_lint(tmp_path):
    script = _lint_script(tmp_path)
    reg = _registry(tmp_path, {
        "voice_ref": "voice", "surface_ref": "persona.md", "lint": "reddit_persona_lint",
        "lint_script": "persona_lint.py", "lint_input": "json_body"})
    resolved = gate.channel_surface_lint(reg, "reddit", tmp_path)
    assert resolved is not None
    assert resolved[0] == script
    assert resolved[1] == "json_body"


def test_a_json_body_lint_gets_the_flag_form(tmp_path):
    script = _lint_script(tmp_path)
    assert gate._lint_argv(script, "/tmp/d.json", "json_body") == [
        "python3", str(script), "--file", "/tmp/d.json"]


def test_a_pointer_file_finds_a_registry_kept_with_the_instances_own_config(tmp_path):
    """consulting keeps its registry at q-consult/config/voice-channels.json, cole-gtm at
    gtm/config/. There is no fleet-wide answer to which subtree that is, which is why the
    pointer exists."""
    elsewhere = tmp_path / "q-consult" / "config"
    elsewhere.mkdir(parents=True)
    reg = elsewhere / "voice-channels.json"
    reg.write_text(json.dumps({"channels": {}, "default": {}}), encoding="utf-8")
    data_dir = tmp_path / "q-system" / ".q-system" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "voice-channels.path").write_text(
        "# where this instance keeps it\nq-consult/config/voice-channels.json\n",
        encoding="utf-8")
    assert gate.resolve_channel_registry(tmp_path) == reg.resolve()


def test_a_pointer_naming_a_missing_file_is_returned_not_swallowed(tmp_path):
    """The resolve_reporter scar: return the NAMED path even when absent, so a reader can
    say 'the pointer names X, which is missing' instead of 'no registry'."""
    data_dir = tmp_path / "q-system" / ".q-system" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "voice-channels.path").write_text("nowhere/voice-channels.json\n",
                                                  encoding="utf-8")
    named = gate.resolve_channel_registry(tmp_path)
    assert named is not None
    assert not named.exists()


# --------------------------------------------------------------------- fail-closed ----

def test_a_malformed_registry_holds(tmp_path):
    data_dir = tmp_path / "q-system" / ".q-system" / "data"
    data_dir.mkdir(parents=True)
    reg = data_dir / "voice-channels.json"
    reg.write_text("{ not json", encoding="utf-8")
    with pytest.raises(gate.ChannelRegistryError):
        gate.channel_surface_lint(reg, "reddit", tmp_path)


def test_a_named_lint_script_that_is_missing_holds(tmp_path):
    reg = _registry(tmp_path, {"voice_ref": "voice", "lint": "reddit_persona_lint",
                               "lint_script": "gone.py"})
    with pytest.raises(gate.ChannelRegistryError, match="does not exist"):
        gate.channel_surface_lint(reg, "reddit", tmp_path)


def test_an_unknown_lint_input_holds(tmp_path):
    _lint_script(tmp_path)
    reg = _registry(tmp_path, {"voice_ref": "voice", "lint": "reddit_persona_lint",
                               "lint_script": "persona_lint.py", "lint_input": "telepathy"})
    with pytest.raises(gate.ChannelRegistryError, match="lint_input"):
        gate.channel_surface_lint(reg, "reddit", tmp_path)


# ------------------------------------------------------------------ channel detection ----

@pytest.mark.parametrize("text,expected", [
    ("here's the reddit post, ready to paste", "reddit"),
    ("here's the LinkedIn post", "linkedin"),
    ("here's the draft for Twitter", "x"),
    ("here's the fix for the parser", ""),
])
def test_detect_channel(text, expected):
    assert gate.detect_channel(text) == expected


# ----------------------------------------------------------- end to end, real process ----

def _run_gate(instance_root, message):
    """Run the gate as the hook runs it: a transcript on stdin, from a tmp instance root.

    The gate resolves INSTANCE_ROOT at import from ITS OWN location, so a subprocess run
    against the real file always reads the real instance. This copies the script into the
    tmp tree so the registry under test is the one it finds -- a refuse-path test run from
    the checkout it asks about proves nothing (scar: guard tests need the caller's shape).
    """
    scripts = instance_root / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    copy = scripts / "voice-stop-gate.py"
    copy.write_bytes(open(GATE, "rb").read())
    transcript = instance_root / "t.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": message}]},
    }) + "\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(copy)],
        input=json.dumps({"transcript_path": str(transcript)}),
        capture_output=True, text=True, timeout=60)


DRAFT = ("here's the reddit post, ready to paste:\n\n"
         "> been running this thing for a while now and the onboarding is still rough. "
         "worked for me, no idea about your setup. took me way too long to figure out "
         "that the parser was the part nobody looks at.\n")

ASSAF_SPOKE = "ASSAF VOICE LINT SPOKE"
PERSONA_SPOKE = "REDDIT PERSONA LINT SPOKE"


def _stub_lints(tmp_path):
    """All three lints present in EVERY tree, so the assertion is about which one the
    gate CHOSE and not about which one happened to be installed. Stubs, not the real
    lints: this test is about routing, and coupling the control to voice-lint's rule set
    would make it go red for a reason it does not exist to catch."""
    scripts = tmp_path / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "voice-lint.py").write_text(
        "import sys\n"
        "assert sys.argv[1].endswith('.md'), sys.argv\n"
        f"sys.stderr.write({ASSAF_SPOKE!r} + chr(10))\n"
        "sys.exit(2)\n", encoding="utf-8")
    (scripts / "voice-substance-lint.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8")
    persona = tmp_path / "persona_lint.py"
    persona.write_text(
        "import json, sys\n"
        "a = sys.argv\n"
        "assert '--file' in a, a\n"
        "body = json.load(open(a[a.index('--file') + 1]))['body']\n"
        "assert body.strip(), 'lint got an empty body'\n"
        f"sys.stderr.write({PERSONA_SPOKE!r} + chr(10))\n"
        "sys.exit(2)\n", encoding="utf-8")
    return scripts


def test_a_reddit_draft_reaches_the_registered_surface_lint(tmp_path):
    """THE reproducer. The lint the registry names is the one that runs, and the assaf
    lints -- present in this same tree -- do not."""
    _stub_lints(tmp_path)
    _registry(tmp_path, {"voice_ref": "voice", "surface_ref": "persona.md",
                         "lint": "reddit_persona_lint",
                         "lint_script": "persona_lint.py", "lint_input": "json_body"})
    result = _run_gate(tmp_path, DRAFT)
    assert result.returncode == 2, result.stdout + result.stderr
    assert PERSONA_SPOKE in result.stderr
    assert ASSAF_SPOKE not in result.stderr, "reddit was still graded on assaf voice"


def test_the_same_draft_with_no_registry_reaches_the_assaf_lints(tmp_path):
    """The control, and the state the mutation must restore. Same tree, same draft, same
    stubs; only the registry is gone."""
    _stub_lints(tmp_path)
    result = _run_gate(tmp_path, DRAFT)
    assert result.returncode == 2, result.stdout + result.stderr
    assert ASSAF_SPOKE in result.stderr
    assert PERSONA_SPOKE not in result.stderr


def test_a_broken_registry_holds_the_turn_rather_than_grading_on_assaf(tmp_path):
    _stub_lints(tmp_path)
    data_dir = tmp_path / "q-system" / ".q-system" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "voice-channels.json").write_text("{ not json", encoding="utf-8")
    result = _run_gate(tmp_path, DRAFT)
    assert result.returncode == 2
    assert "channel registry error" in result.stderr
    assert ASSAF_SPOKE not in result.stderr
    assert PERSONA_SPOKE not in result.stderr
