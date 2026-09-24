"""ASK-2072: a headless model call must not leave an MCP server running.

Provenance (captured, not typed): a read-only `ps` watch across one live hourly
job fire on 2026-09-23. Each `claude -p` the job made started an apify MCP
server; 7 of 27 calls left it reparented to launchd (ppid 1). One row, scrubbed:

    <pid>  ppid <claude -p pid>  pgid <job pgid>
    <pid>  ppid 1                pgid <job pgid>   +2:08 later

The stub stands in for `claude`: like the real CLI it starts a detached
"MCP server" unless told to load none, then exits without reaping it.
"""
import json
import os
import signal
import stat
import sys
import textwrap
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import prompt_render, usage_ledger  # noqa: E402

STUB = textwrap.dedent('''\
    #!{py}
    import json, os, subprocess, sys
    argv = sys.argv[1:]
    with open(os.environ["STUB_ARGV"], "w") as fh:
        json.dump(argv, fh)
    servers = None
    if "--strict-mcp-config" in argv and "--mcp-config" in argv:
        servers = json.loads(argv[argv.index("--mcp-config") + 1]).get("mcpServers")
    if servers != {{}}:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)", "stub-mcp-server"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(os.environ["STUB_PIDFILE"], "w") as fh:
            fh.write(str(child.pid))
    print("ok")
    ''')


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_one_model_call_leaves_no_mcp_server_running(tmp_path, monkeypatch):
    stub = tmp_path / "claude"
    stub.write_text(STUB.format(py=sys.executable))
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    argv_log, pidfile = tmp_path / "argv.json", tmp_path / "server.pid"
    monkeypatch.setenv("STUB_ARGV", str(argv_log))
    monkeypatch.setenv("STUB_PIDFILE", str(pidfile))
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)  # the stub is the binary: no live call

    prompt_render.run_model("say ok", claude_bin=str(stub), caller="c", model="m")

    leaked = None
    if pidfile.exists():
        leaked = int(pidfile.read_text())
        time.sleep(0.2)
        still = _alive(leaked)
        os.kill(leaked, signal.SIGTERM) if still else None
        assert not still, (
            "one headless model call left its MCP server running after exit "
            "(pid %d): the ASK-2072 leak" % leaked)
    # Guard against a test that cannot fail: the call really ran the stub.
    argv = json.loads(argv_log.read_text())
    assert "--strict-mcp-config" in argv
    assert json.loads(argv[argv.index("--mcp-config") + 1]) == {"mcpServers": {}}
    assert leaked is None
