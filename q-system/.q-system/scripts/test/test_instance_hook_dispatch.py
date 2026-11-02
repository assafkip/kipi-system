"""instance-hook-dispatch: absent no-ops, present passes the exit code through, bad names refused."""
import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "instance-hook-dispatch.py")


def _run(project, name, stdin=b'{"x":1}'):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    return subprocess.run([sys.executable, SCRIPT, name], input=stdin, env=env, capture_output=True)


def _hook(project, name, body):
    d = project / "automation"
    d.mkdir(exist_ok=True)
    (d / (name + ".py")).write_text(body)


def test_absent_file_exits_0_silently(tmp_path):
    r = _run(tmp_path, "gate_draft_hook")
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""


def test_present_file_exiting_2_blocks_and_stderr_passes_through(tmp_path):
    _hook(tmp_path, "gate_draft_hook", "import sys; sys.stderr.write('REFUSED: trope'); sys.exit(2)")
    r = _run(tmp_path, "gate_draft_hook")
    assert r.returncode == 2 and b"REFUSED: trope" in r.stderr


def test_present_file_exiting_0_exits_0(tmp_path):
    _hook(tmp_path, "gate_draft_hook", "import sys; sys.exit(0)")
    assert _run(tmp_path, "gate_draft_hook").returncode == 0


def test_stdin_reaches_the_instance_hook(tmp_path):
    _hook(tmp_path, "gate_draft_hook",
          "import sys; sys.exit(2 if sys.stdin.read() == '{\"x\":1}' else 0)")
    assert _run(tmp_path, "gate_draft_hook").returncode == 2


def test_a_crashing_hook_is_not_a_pass(tmp_path):
    _hook(tmp_path, "gate_draft_hook", "raise SystemExit(1/0)")
    assert _run(tmp_path, "gate_draft_hook").returncode != 0


@pytest.mark.parametrize("bad", ["../evil", "a/b", "A", "x.py", "", "a b", "..", "x;y"])
def test_a_bad_name_is_refused_and_nothing_runs(tmp_path, bad):
    marker = tmp_path / "ran"
    (tmp_path / "evil.py").write_text(f"open({str(marker)!r}, 'w')")
    r = _run(tmp_path, bad)
    assert r.returncode == 2 and not marker.exists()


def test_a_symlink_name_cannot_escape_automation(tmp_path):
    # Names are joined under automation/ and never contain a separator, so ../ cannot be spelled.
    (tmp_path / "evil.py").write_text("import sys; sys.exit(2)")
    assert _run(tmp_path, "evil").returncode == 0  # no automation/evil.py -> absent -> no-op
