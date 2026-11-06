"""model-wrapper-runtime-proof-check counts a wrapper proven only from a green receipt (ASK-2540).

Every tree here is a throwaway git repo under tmp_path. The check RUNS the proof
tests it finds; they drive the fixture wrapper against gate_proof's stub claude,
so nothing here calls a model.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIPI_CORE = HERE.parents[2] / "plugins" / "kipi-core"
_spec = importlib.util.spec_from_file_location("mwrpc", HERE / "model-wrapper-runtime-proof-check.py")
mwrpc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mwrpc)

# why scrubbed: a hook exports GIT_DIR, and git's env outranks `-C`, so a fixture
# repo built under a commit hook would write into the real repo instead.
_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

GATED = f'''import subprocess, sys
sys.path.insert(0, {str(KIPI_CORE)!r})
from voiceloop import model_gate, usage_ledger
def call_model(prompt, claude_bin):
    """Shells claude behind the gate and the meter."""
    model_gate.check("fixture()")
    out = subprocess.run([claude_bin, "-p", prompt, "--output-format", "json"],
                         capture_output=True, text=True).stdout
    text, row = usage_ledger.finish(out, bot="t", job="fixture()")
    usage_ledger.append(row)
    return text
'''
UNGATED = '''import subprocess
def call_model(prompt, claude_bin):
    """Shells claude."""
    return subprocess.run([claude_bin, "-p", prompt], capture_output=True, text=True).stdout
'''
CODEX = '''import subprocess
def ask_codex(prompt):
    return subprocess.run(["codex", "exec", prompt], capture_output=True, text=True).stdout
'''


def _proof(body: str, target: str = "lib.wrap:call_model") -> str:
    return (f"import sys\nfrom pathlib import Path\nsys.path.insert(0, {str(KIPI_CORE)!r})\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
            "import pytest\nfrom voiceloop import gate_proof\nfrom lib.wrap import call_model\n"
            "def test_it():\n" + body.replace("TARGET", repr(target)))


GREEN = "    gate_proof.assert_gated(lambda b: call_model('hi', b), target=TARGET)\n"


def _repo(tmp_path: Path, files: dict) -> Path:
    top = tmp_path / "repo"
    for rel, text in files.items():
        p = top / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "init", "-q", str(top)], check=True, env=_ENV)
    subprocess.run(["git", "-C", str(top), "add", "-A"], check=True, env=_ENV)
    return top


def _run(top: Path) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mwrpc.main(["--root", str(top), "--json", "--no-alert"])
    return rc, json.loads(buf.getvalue())


def _names(rows):
    return [(r["path"], r["qualname"]) for r in rows]


def test_an_imported_model_caller_with_no_proof_is_uncovered(tmp_path):
    top = _repo(tmp_path, {"lib/wrap.py": UNGATED, "app.py": "from lib.wrap import call_model\n",
                           "lonely.py": UNGATED})
    rc, rep = _run(top)
    assert rc == 1
    # lonely.py calls the model but nothing imports it: a call site, not a wrapper.
    assert _names(rep["uncovered"]) == [("lib/wrap.py", "call_model")]


def test_a_passing_proof_that_ran_green_covers_it(tmp_path):
    top = _repo(tmp_path, {"lib/wrap.py": GATED, "app.py": "import lib.wrap as w\nw.call_model('x', 'y')\n",
                           "tests/test_wrap.py": _proof(GREEN)})
    rc, rep = _run(top)
    assert rc == 0, rep
    assert _names(rep["proven"]) == [("lib/wrap.py", "call_model")]
    assert rep["receipts"][0]["file"] == os.path.realpath(top / "lib" / "wrap.py")


def test_a_skipped_unreachable_or_inverted_proof_covers_nothing(tmp_path):
    # PR #525 review finding 1: each of these exited 0 when a parsed call counted.
    bodies = {
        "skipped": "    pytest.skip('later')\n" + GREEN,
        "unreachable": "    if False:\n    " + GREEN,
        "inverted": "    assert not gate_proof.prove(lambda b: call_model('hi', b), target=TARGET).ok\n",
    }
    for name, body in bodies.items():
        top = _repo(tmp_path / name, {"lib/wrap.py": UNGATED, "app.py": "from lib.wrap import call_model\n",
                                      "tests/test_wrap.py": _proof(body)})
        rc, rep = _run(top)
        assert rep["targets"] == ["lib.wrap:call_model"], name
        assert rc == 1 and _names(rep["uncovered"]) == [("lib/wrap.py", "call_model")], name


def test_a_proof_does_not_cover_a_same_named_copy_elsewhere(tmp_path):
    top = _repo(tmp_path, {"lib/wrap.py": GATED, "vendor/lib/wrap.py": UNGATED,
                           "app.py": "from lib.wrap import call_model\n",
                           "tests/test_wrap.py": _proof(GREEN)})
    rc, rep = _run(top)
    assert rc == 1
    assert _names(rep["proven"]) == [("lib/wrap.py", "call_model")]
    assert _names(rep["uncovered"]) == [("vendor/lib/wrap.py", "call_model")]


def test_a_non_constant_target_does_not_register(tmp_path):
    body = "    gate_proof.assert_gated(lambda b: call_model('hi', b), target=f\"lib.wrap:{'call_model'}\")\n"
    top = _repo(tmp_path, {"lib/wrap.py": GATED, "app.py": "from lib.wrap import call_model\n",
                           "tests/test_wrap.py": _proof(body)})
    rc, rep = _run(top)
    assert rc == 1 and rep["targets"] == []


def test_a_hyphenated_script_loaded_by_spec_is_a_wrapper(tmp_path):
    loader = ('import importlib.util\n'
              '_s = importlib.util.spec_from_file_location("mb", HERE / "morning-thing.py")\n'
              'mb = importlib.util.module_from_spec(_s)\n'
              'mb.call_model("x", "y")\n')
    top = _repo(tmp_path, {"scripts/morning-thing.py": UNGATED, "scripts/user.py": loader})
    rc, rep = _run(top)
    assert _names(rep["uncovered"]) == [("scripts/morning-thing.py", "call_model")]


def test_a_codex_wrapper_is_unprovable_not_uncovered(tmp_path):
    top = _repo(tmp_path, {"lib/cx.py": CODEX, "app.py": "from lib.cx import ask_codex\n"})
    rc, rep = _run(top)
    assert rc == 0 and rep["uncovered"] == []
    assert [(r["path"], r["kind"]) for r in rep["unprovable"]] == [("lib/cx.py", "codex")]


def test_alert_fires_once_per_state_change(tmp_path, monkeypatch):
    sent = tmp_path / "sent.txt"
    monkeypatch.setenv("KIPI_ALERT_CMD", f"{sys.executable} -c \"import sys;open('{sent}','a').write(sys.argv[1]+chr(10))\"")
    top = _repo(tmp_path, {"lib/wrap.py": UNGATED, "app.py": "from lib.wrap import call_model\n"})
    args = ["--root", str(top), "--state-dir", str(tmp_path / "state")]
    assert mwrpc.main(args) == 1
    assert mwrpc.main(args) == 1
    lines = sent.read_text().splitlines()
    assert len(lines) == 1 and "1 model-calling wrappers have no runtime gate proof" in lines[0]


def test_no_readable_root_refuses_to_report_zero(tmp_path):
    assert mwrpc.main(["--root", str(tmp_path / "missing"), "--no-alert"]) == 2
