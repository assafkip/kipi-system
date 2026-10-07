"""model-wrapper-runtime-proof-check finds wrappers and their runtime proofs (ASK-2540).

Every tree here is a throwaway git repo under tmp_path. Nothing runs a model.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("mwrpc", HERE / "model-wrapper-runtime-proof-check.py")
mwrpc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mwrpc)

# why scrubbed: a hook exports GIT_DIR, and git's env outranks `-C`, so a fixture
# repo built under a commit hook would write into the real repo instead.
_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

WRAPPER = '''import subprocess
def call_model(prompt, claude_bin):
    """Shells claude."""
    return subprocess.run([claude_bin, "-p", prompt], capture_output=True, text=True).stdout
def not_a_model(x):
    return x
'''


def _repo(tmp_path: Path, files: dict) -> Path:
    top = tmp_path / "repo"
    for rel, text in files.items():
        p = top / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "init", "-q", str(top)], check=True, env=_ENV)
    subprocess.run(["git", "-C", str(top), "add", "-A"], check=True, env=_ENV)
    return top


def _run(top: Path, tmp_path: Path, *extra) -> tuple[int, dict]:
    out = tmp_path / "out.json"
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mwrpc.main(["--root", str(top), "--json", "--no-alert", *extra])
    out.write_text(buf.getvalue())
    return rc, json.loads(buf.getvalue())


def test_an_imported_model_caller_with_no_proof_is_uncovered(tmp_path):
    top = _repo(tmp_path, {"lib/wrap.py": WRAPPER, "app.py": "from lib.wrap import call_model\n",
                           "lonely.py": WRAPPER})
    rc, rep = _run(top, tmp_path)
    assert rc == 1
    # lonely.py calls the model but nothing imports it: a call site, not a wrapper.
    assert [(u["path"], u["qualname"]) for u in rep["uncovered"]] == [("lib/wrap.py", "call_model")]


def test_a_constant_target_in_a_test_covers_it(tmp_path):
    proof = ('from voiceloop import gate_proof\n'
             'def test_it():\n'
             '    gate_proof.assert_gated(lambda b: None, target="lib.wrap:call_model")\n')
    top = _repo(tmp_path, {"lib/wrap.py": WRAPPER, "app.py": "import lib.wrap as w\nw.call_model('x', 'y')\n",
                           "tests/test_wrap.py": proof})
    rc, rep = _run(top, tmp_path)
    assert rc == 0, rep
    assert [(p["path"], p["qualname"]) for p in rep["proven"]] == [("lib/wrap.py", "call_model")]


def test_a_non_constant_target_or_a_proof_outside_tests_does_not_register(tmp_path):
    fstring = ('from voiceloop import gate_proof\n'
               'def test_it():\n'
               '    gate_proof.prove(lambda b: None, target=f"lib.wrap:{\'call_model\'}")\n')
    top = _repo(tmp_path, {"lib/wrap.py": WRAPPER, "app.py": "from lib.wrap import call_model\n",
                           "tests/test_wrap.py": fstring,
                           "notatest.py": 'prove(None, target="lib.wrap:call_model")\n'})
    rc, rep = _run(top, tmp_path)
    assert rc == 1 and rep["targets"] == []


def test_a_hyphenated_script_loaded_by_spec_is_a_wrapper(tmp_path):
    loader = ('import importlib.util\n'
              '_s = importlib.util.spec_from_file_location("mb", HERE / "morning-thing.py")\n'
              'mb = importlib.util.module_from_spec(_s)\n'
              'mb.call_model("x", "y")\n')
    top = _repo(tmp_path, {"scripts/morning-thing.py": WRAPPER, "scripts/user.py": loader})
    rc, rep = _run(top, tmp_path)
    assert [(u["path"], u["qualname"]) for u in rep["uncovered"]] == [("scripts/morning-thing.py", "call_model")]
    proof = 'def test_it():\n    assert_gated(lambda b: None, target="morning_thing:call_model")\n'
    (top / "scripts" / "test_mt.py").write_text(proof)
    subprocess.run(["git", "-C", str(top), "add", "-A"], check=True, env=_ENV)
    rc, rep = _run(top, tmp_path)
    assert rc == 0 and rep["uncovered"] == []


def test_alert_fires_once_per_state_change(tmp_path, monkeypatch):
    sent = tmp_path / "sent.txt"
    monkeypatch.setenv("KIPI_ALERT_CMD", f"{sys.executable} -c \"import sys;open('{sent}','a').write(sys.argv[1]+chr(10))\"")
    top = _repo(tmp_path, {"lib/wrap.py": WRAPPER, "app.py": "from lib.wrap import call_model\n"})
    args = ["--root", str(top), "--state-dir", str(tmp_path / "state")]
    assert mwrpc.main(args) == 1
    assert mwrpc.main(args) == 1
    lines = sent.read_text().splitlines()
    assert len(lines) == 1 and "1 model-calling wrappers have no runtime gate proof" in lines[0]


def test_no_readable_root_refuses_to_report_zero(tmp_path, capsys):
    assert mwrpc.main(["--root", str(tmp_path / "missing"), "--no-alert"]) == 2
