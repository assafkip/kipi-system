"""Tests for tool-output-trim.py (ASK-4649).

Fixtures are REAL captured output: a pytest run with 12 failing tests, a
`git log`, and a real Python traceback, each produced by running the command in
a temp dir. The jest block is the one synthetic fixture (jest is not installed
here) and is labelled as such.

Every test sets KIPI_TOOL_OUTPUT_DIR to a temp dir. The hook's default is the
live ~/.local/state/kipi/tool-output; a test that forgot the override would
write there, so the autouse fixture below points the override at tmp and
test_default_state_dir_is_the_live_path_but_is_never_written checks the
default without writing.

Mutants: TestMutants patches the hook source (one decision point each), runs
ONE named test against the patched copy, and requires it to FAIL. A test that
cannot go red is decoration (check-must-be-able-to-fail).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REAL_HOOK = HERE / "tool-output-trim.py"
HOOK = Path(os.environ.get("TOOL_OUTPUT_TRIM_PATH", str(REAL_HOOK)))
IN_MUTANT_RUN = os.environ.get("TRIM_MUTANT_RUN") == "1"


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    d = tmp_path / "state"
    monkeypatch.setenv("KIPI_TOOL_OUTPUT_DIR", str(d))
    monkeypatch.delenv("KIPI_OUTPUT_TRIM", raising=False)
    return d


def run_hook(payload, *, raw: str | None = None, env_extra: dict | None = None):
    env = dict(os.environ)
    env.update(env_extra or {})
    data = raw if raw is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, "-I", str(HOOK)],
        input=data, capture_output=True, text=True, env=env, timeout=30,
    )


def bash_payload(command, stdout, stderr="", session="sess1"):
    return {
        "session_id": session,
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False},
    }


def trimmed(proc):
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip(), "hook printed nothing, expected a trim"
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse"
    return out["updatedToolOutput"]


# ---- real captured fixtures -------------------------------------------------

PYTEST_FILE = textwrap.dedent(
    """
    import pytest

    @pytest.mark.parametrize("i", range(160))
    def test_pass_{tag}(i):
        assert True

    """
)


@pytest.fixture(scope="module")
def pytest_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("fixrun")
    body = PYTEST_FILE.replace("{tag}", "ok")
    for k in range(12):
        body += (
            f"def test_fail_{k:02d}():\n"
            f"    note = 'SRCMARK-{k:02d}'\n"
            f"    a1 = 1\n    a2 = 2\n    a3 = 3\n    a4 = 4\n"
            f"    x = {k}\n"
            f"    assert x == 'BOOMMARK-{k:02d}-expected', 'DETAIL-{k:02d}'\n\n"
        )
    (d / "test_fix.py").write_text(body)
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider", "test_fix.py"],
        cwd=d, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_ADDOPTS": ""},
    )
    assert r.returncode == 1 and "12 failed" in r.stdout, r.stdout[-400:]
    return r.stdout


@pytest.fixture(scope="module")
def git_log_out(tmp_path_factory):
    d = tmp_path_factory.mktemp("fixgit")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=d, env=env, check=True)
    for n in range(120):
        subprocess.run(["git", "commit", "-q", "--allow-empty", "--no-verify", "-m",
                        f"change number {n} touches subsystem {n % 7}"], cwd=d, env=env, check=True)
    r = subprocess.run(["git", "log"], cwd=d, env=env, capture_output=True, text=True, check=True)
    assert len(r.stdout) > 2000
    return r.stdout


# ---- behaviour --------------------------------------------------------------

def test_pytest_all_12_failures_survive(pytest_run, _state):
    r = run_hook(bash_payload("python3 -m pytest -v test_fix.py", pytest_run))
    out = trimmed(r)
    for k in range(12):
        assert f"BOOMMARK-{k:02d}-expected" in out["stdout"], f"failure {k} dropped"
        assert f"DETAIL-{k:02d}" in out["stdout"], f"failure {k} detail dropped"
        assert f"SRCMARK-{k:02d}" in out["stdout"], f"failure {k} source block dropped"
    assert len(out["stdout"]) < len(pytest_run) * 0.8
    assert "12 failed" in out["stdout"]
    assert out["interrupted"] is False and out["isImage"] is False


def test_saved_file_holds_the_full_text(pytest_run, _state):
    out = trimmed(run_hook(bash_payload("pytest -v", pytest_run, session="abc")))
    line = [l for l in out["stdout"].splitlines() if l.startswith("[trim: showing")][-1]
    path = Path(line.split(" is in ", 1)[1].rstrip("]"))
    assert path.parent == _state and path.name == "abc-1.txt"
    assert path.read_text() == pytest_run
    out2 = trimmed(run_hook(bash_payload("pytest -v", pytest_run, session="abc")))
    assert "abc-2.txt" in out2["stdout"]


def test_short_output_is_untouched():
    # 1840 chars of one repeated line: a trim WOULD pay here, so only the size floor refuses it.
    r = run_hook(bash_payload("echo hi", ("a" * 45 + "\n") * 40))
    assert r.returncode == 0 and r.stdout == ""


def test_long_git_log_is_trimmed_head_and_tail_kept(git_log_out):
    out = trimmed(run_hook(bash_payload("git log", git_log_out)))
    lines = git_log_out.splitlines()
    assert lines[0] in out["stdout"] and lines[-1] in out["stdout"]
    assert "lines omitted" in out["stdout"]
    assert len(out["stdout"]) < len(git_log_out) * 0.8


def test_head_30_lines_are_kept():
    text = "\n".join(f"headline number {i} unique {i * 7919}" for i in range(400))
    out = trimmed(run_hook(bash_payload("make", text)))
    assert "headline number 29 " in out["stdout"]
    assert "headline number 200 " not in out["stdout"]


def test_error_line_mid_output_kept_with_context():
    rows = [f"step {i} ok {'x' * (i % 11)} {i * 104729}" for i in range(400)]
    rows[200] = "ERROR: disk quota exceeded on /data"
    out = trimmed(run_hook(bash_payload("make all", "\n".join(rows))))
    assert "ERROR: disk quota exceeded" in out["stdout"]
    assert rows[199] in out["stdout"] and rows[201] in out["stdout"]


def test_real_traceback_block_kept_whole():
    tb = subprocess.run(
        [sys.executable, "-I", "-c",
         "def a(): return b()\ndef b(): return c()\ndef c(): return d()\ndef d(): raise ValueError('TBMARK-deep')\na()"],
        capture_output=True, text=True).stderr
    assert "TBMARK-deep" in tb and tb.count("File") >= 4
    pad = "\n".join(f"log line {i} {i * 7919}" for i in range(300))
    stdout = pad + "\n" + tb.rstrip("\n") + "\n" + pad
    out = trimmed(run_hook(bash_payload("run.sh", stdout)))
    for frame in tb.splitlines():
        assert frame in out["stdout"], f"traceback line dropped: {frame}"


def test_jest_failure_blocks_kept_whole_synthetic():
    # SYNTHETIC: jest output shape, not captured from a run (jest not installed).
    blocks = []
    for k in range(5):
        blocks.append(
            f"  ● Suite {k} › does thing {k}\n\n    expect(received).toBe(expected)\n\n"
            f"    Expected: \"JESTMARK-{k}\"\n    Received: \"other\"\n\n      at Object.<anonymous> (a.test.js:{k})\n"
        )
    pad = "\n".join(f"PASS src/file{i}.test.js ({i * 31} ms)" for i in range(300))
    text = pad + "\n" + "\n".join(blocks) + "\nTests:       5 failed, 300 passed, 305 total\n" + pad
    out = trimmed(run_hook(bash_payload("npx jest", text)))
    for k in range(5):
        assert f"JESTMARK-{k}" in out["stdout"]


def test_git_diff_command_untouched():
    text = "\n".join(f"+added line {i} {i * 7919}" for i in range(600))
    r = run_hook(bash_payload("git diff origin/main", text))
    assert r.returncode == 0 and r.stdout == ""
    r = run_hook(bash_payload("git -C /x show HEAD", text))
    assert r.stdout == ""


def test_hunk_header_content_untouched_even_via_wrapper():
    text = "diff --git a/f b/f\n@@ -1,3 +1,4 @@\n" + "\n".join(f"+line {i} {i * 7919}" for i in range(600))
    r = run_hook(bash_payload("./show-patch.sh", text))
    assert r.returncode == 0 and r.stdout == ""


def test_trim_under_20_percent_saving_is_skipped():
    # 60 distinct long lines: under head+tail, nothing omitted, footer only adds bytes.
    text = "\n".join(f"{i:03d} " + "q" * 40 + str(i * 7919) for i in range(60))
    assert len(text) > 2000
    r = run_hook(bash_payload("cmd", text))
    assert r.returncode == 0 and r.stdout == ""


def test_kill_switch():
    text = "\n".join(f"headline number {i} unique {i * 7919}" for i in range(400))
    assert trimmed(run_hook(bash_payload("make", text)))  # on
    r = run_hook(bash_payload("make", text), env_extra={"KIPI_OUTPUT_TRIM": "0"})
    assert r.returncode == 0 and r.stdout == ""


def test_broken_input_exits_0_prints_nothing(tmp_path):
    for raw in ["not json", "", "[]", "{}", '{"tool_name":"Bash","tool_response":"str"}',
                '{"tool_name":"Bash","tool_response":{"stdout":5}}']:
        r = run_hook(None, raw=raw)
        assert r.returncode == 0 and r.stdout == "", raw
    # State dir that cannot be created: the write raises, original output must stand.
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    text = "\n".join(f"headline number {i} unique {i * 7919}" for i in range(400))
    r = run_hook(bash_payload("make", text), env_extra={"KIPI_TOOL_OUTPUT_DIR": str(blocker / "sub")})
    assert r.returncode == 0 and r.stdout == ""


def test_non_bash_tool_untouched():
    p = bash_payload("x", "a\n" * 3000)
    p["tool_name"] = "Read"
    r = run_hook(p)
    assert r.returncode == 0 and r.stdout == ""


def test_default_state_dir_is_the_live_path_but_is_never_written(monkeypatch):
    monkeypatch.delenv("KIPI_TOOL_OUTPUT_DIR", raising=False)
    spec = importlib.util.spec_from_file_location("tot", REAL_HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.state_dir() == Path.home() / ".local" / "state" / "kipi" / "tool-output"


# ---- mutants: one per decision point, each must be killed -------------------

MUTANTS = [
    ("min_chars", "MIN_CHARS = 2000", "MIN_CHARS = 0", "test_short_output_is_untouched"),
    ("saving_gate", "if after > before * (1 - MIN_SAVING):\n        return None",
     "if False:\n        return None", "test_trim_under_20_percent_saving_is_skipped"),
    ("diff_command", "if GIT_DIFF_CMD_RE.search(command or \"\"):\n        return True",
     "if False:\n        return True", "test_git_diff_command_untouched"),
    ("diff_hunk", "return bool(HUNK_RE.search(out) or HUNK_RE.search(err))", "return False",
     "test_hunk_header_content_untouched_even_via_wrapper"),
    ("failure_blocks", "    keep: set[int] = set()\n    n = len(lines)\n    i = 0\n    while i < n:",
     "    keep: set[int] = set()\n    n = len(lines)\n    i = n\n    while i < n:",
     "test_pytest_all_12_failures_survive"),
    ("traceback_block", "if TRACEBACK_RE.match(line):", "if False:",
     "test_real_traceback_block_kept_whole"),
    ("error_context", "if SIGNAL_RE.search(lines[i]):\n            keep.update",
     "if False:\n            keep.update", "test_error_line_mid_output_kept_with_context"),
    ("head", "HEAD_LINES = 30", "HEAD_LINES = 0", "test_head_30_lines_are_kept"),
    ("kill_switch", "if os.environ.get(\"KIPI_OUTPUT_TRIM\") == \"0\":\n        return None",
     "if False:\n        return None", "test_kill_switch"),
    ("fail_open", "    except Exception:  # fail open", "    except ZeroDivisionError:  # fail open",
     "test_broken_input_exits_0_prints_nothing"),
    ("full_text_saved", "fh.write(body)", "fh.write(body[:40])", "test_saved_file_holds_the_full_text"),
]


@pytest.mark.skipif(IN_MUTANT_RUN, reason="mutant child run")
@pytest.mark.parametrize("name,old,new,killer", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(name, old, new, killer, tmp_path):
    src = REAL_HOOK.read_text()
    assert src.count(old) == 1, f"mutant {name}: anchor must match exactly once"
    patched = tmp_path / "tool-output-trim.py"
    patched.write_text(src.replace(old, new))
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider",
         f"{Path(__file__).resolve()}::{killer}"],
        capture_output=True, text=True,
        env={**os.environ, "TOOL_OUTPUT_TRIM_PATH": str(patched), "TRIM_MUTANT_RUN": "1"},
    )
    assert r.returncode != 0, f"mutant {name} SURVIVED: {killer} stayed green\n{r.stdout[-600:]}"
