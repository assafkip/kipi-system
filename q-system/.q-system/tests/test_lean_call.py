"""The lean-call contract (scripts/lean_call.py) and the background callers routed through it.

Why this exists (RCA 2026-10-06, root cause #3): background `claude -p` calls
inherited the cwd's whole interactive setup. A two-word prompt cost about 350k
input-side tokens from a runner root and 3.6k from an empty dir with
`--setting-sources "" --tools ""`. Nothing stated the lean shape and nothing
measured it, so it drifted with every rule and hook added.

Every offline case runs a STUB `claude` on a sealed PATH (the stub's dir only),
so the real binary cannot be reached, and the stub records its argv and cwd.

The LIVE case makes one real Haiku call and is skipped unless
KIPI_LIVE_MODEL_TEST=1. It is the runtime proof: a source read is not one.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import lean_call  # noqa: E402

SETUP_TOKEN_CEILING = 5000


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def stub(tmp_path, monkeypatch):
    """A recording `claude` alone on PATH. Returns a reader for the last call."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    rec = tmp_path / "rec"
    exe = bindir / "claude"
    # /bin/sh by absolute path: the sealed PATH has nothing else on it.
    exe.write_text(
        "#!/bin/sh\n"
        'printf "%s\\0" "$@" > "$LEAN_REC.argv"\n'
        'pwd -P > "$LEAN_REC.cwd"\n'
        # builtins only: `ls` is NOT on the sealed PATH, and a missing ls
        # prints nothing, which reads exactly like an empty dir.
        'for f in * .[!.]*; do [ -e "$f" ] && echo "$f"; done > "$LEAN_REC.ls"\n'
        "printf '%s\\n' \"$LEAN_STUB_OUT\"\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("LEAN_REC", str(rec))
    monkeypatch.setenv("LEAN_STUB_OUT", "CLEAN")
    monkeypatch.setenv("KIPI_CLAUDE_BIN", str(exe))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def last():
        argv = Path(str(rec) + ".argv").read_bytes().split(b"\0")[:-1]
        return {"argv": [a.decode() for a in argv],
                "cwd": Path(str(rec) + ".cwd").read_text().strip(),
                "ls": Path(str(rec) + ".ls").read_text().strip()}
    last.exe = str(exe)
    return last


def _is_lean(call, test_cwd):
    argv = call["argv"]
    tail_ok = argv[-4:] == ["--setting-sources", "", "--tools", ""]
    cwd_ok = (call["ls"] == "" and Path(call["cwd"]).resolve() != Path(test_cwd).resolve()
              and Path(call["cwd"]).name.startswith("kipi-lean-"))
    return tail_ok, cwd_ok


# --- the module --------------------------------------------------------------

def test_default_is_lean_and_cwd_is_a_fresh_empty_dir(stub):
    lean_call.run([stub.exe, "-p", "hi"], capture_output=True, text=True)
    call = stub()
    assert call["argv"] == ["-p", "hi", "--setting-sources", "", "--tools", ""]
    tail_ok, cwd_ok = _is_lean(call, os.getcwd())
    assert tail_ok and cwd_ok, call
    assert not Path(call["cwd"]).exists(), "the empty dir must be removed afterwards"


def test_a_declared_need_is_honored_and_logged(stub, tmp_path, capsys):
    work = tmp_path / "work"
    work.mkdir()
    lean_call.run([stub.exe, "-p", "hi"], needs_tools=["Read", "Grep"],
                  needs_settings=True, cwd=str(work), capture_output=True, text=True)
    call = stub()
    assert call["argv"] == ["-p", "hi", "--tools", "Read,Grep"]
    assert Path(call["cwd"]).resolve() == work.resolve()
    err = capsys.readouterr().err
    assert "lean_call: declared tools=Read,Grep settings=on cwd=" in err


def test_an_undeclared_need_hiding_in_argv_is_refused():
    for bad in (["claude", "-p", "x", "--tools", "Read"],
                ["claude", "-p", "x", "--setting-sources=user"]):
        with pytest.raises(ValueError):
            lean_call.lean_argv(bad)


def test_negative_control_the_check_sees_a_fat_call(stub):
    """Drop the flags and the cwd: the same assertion must go red."""
    subprocess.run([stub.exe, "-p", "hi"], capture_output=True, text=True)
    call = stub()
    tail_ok, cwd_ok = _is_lean(call, os.getcwd())
    assert not tail_ok and not cwd_ok
    # The cwd listing must SEE files, or "empty" is unfalsifiable.
    assert call["ls"], "the stub's dir listing is blind"


# --- the background callers routed through it --------------------------------

def test_dor_drafter_call_is_lean(stub, monkeypatch):
    dor = _load("dor_lean", "linear-dor-drafter.py")
    good = "- **Outcome:** x\n- **Energy:** Quick Win | **Time:** 5m\n" + "pad " * 20
    monkeypatch.setenv("LEAN_STUB_OUT", good)
    issue = {"identifier": "T-1", "title": "t", "description": "d", "project": None}
    body, why = dor.draft_one(issue, timeout=20)
    assert body and not why, why
    assert _is_lean(stub(), os.getcwd()) == (True, True), stub()


def test_triage_call_is_lean(stub, monkeypatch):
    tri = _load("tri_lean", "linear-triage.py")
    monkeypatch.setenv("LEAN_STUB_OUT", "{}")
    issue = {"identifier": "T-1", "title": "t", "description": "d",
             "state": {"name": "Todo", "type": "unstarted"}, "comments": {"nodes": []},
             "labels": {"nodes": []}, "project": None, "createdAt": "2026-01-01T00:00:00Z"}
    tri.judge_batch([issue], timeout=20)
    assert _is_lean(stub(), os.getcwd()) == (True, True), stub()


def test_lessons_distill_calls_are_lean(stub, monkeypatch):
    ld = _load("ld_lean", "lessons-distill.py")
    ld.llm_verify_clean("some text", "real")
    assert _is_lean(stub(), os.getcwd()) == (True, True), stub()
    monkeypatch.setenv("LEAN_STUB_OUT", '{"title":"t","body":"b","kind":"pattern"}')
    assert ld.distill_with_claude("t", "c")
    assert _is_lean(stub(), os.getcwd()) == (True, True), stub()


# --- LIVE: one real call, measured ------------------------------------------

@pytest.mark.skipif(os.environ.get("KIPI_LIVE_MODEL_TEST") != "1",
                    reason="live model call; set KIPI_LIVE_MODEL_TEST=1")
def test_live_setup_tokens_under_ceiling():
    binary = shutil.which("claude")
    assert binary, "no claude on PATH"
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    r = lean_call.run([binary, "-p", "Reply OK.", "--model", "claude-haiku-4-5",
                       "--output-format", "json"],
                      capture_output=True, text=True, timeout=120,
                      stdin=subprocess.DEVNULL, env=env)
    assert r.returncode == 0, r.stderr[-500:]
    usage = json.loads(r.stdout)["usage"]
    setup = (usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
             + usage.get("cache_read_input_tokens", 0))
    print("LIVE lean setup tokens: %d (%s)" % (setup, json.dumps(usage)))
    assert setup < SETUP_TOKEN_CEILING, usage
