#!/usr/bin/env python3
"""Tests for the Miyo KB hooks: miyo-session-pull.py and miyo-research-gate.py."""
import importlib.util
import json
import os
import stat
import subprocess
import sys

import pytest

SCRIPTS = os.path.dirname(os.path.abspath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(SCRIPTS, name + ".py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pull = load("miyo-session-pull")
gate = load("miyo-research-gate")


def write_stub_miyo(tmp_path, payload):
    stub = tmp_path / "fake-miyo"
    stub.write_text(
        "#!/bin/sh\n" + "printf '%s' " + json.dumps(json.dumps(payload)) + "\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return str(stub)


class TestScope:
    def test_default_scope_matches_consulting(self):
        assert pull.in_scope("/Users/x/projects/consulting/projects/foo")
        assert gate.in_scope("/Users/x/projects/consulting/projects/foo")

    def test_default_scope_rejects_outside(self):
        assert not pull.in_scope("/Users/x/other")
        assert not gate.in_scope("/Users/x/other")

    def test_empty_scope_allows_anywhere(self, monkeypatch):
        monkeypatch.setenv("MIYO_KB_SCOPE", "")
        assert pull.in_scope("/anywhere")
        assert gate.in_scope("/anywhere")


class TestSessionPull:
    def test_build_queries_uses_folder_name(self):
        q = pull.build_queries("/tmp/consulting/projects/example_client_project")
        assert q[0] == "example_client_project"
        assert "example_client_project" in q[1]

    def test_run_search_parses_json_list(self, tmp_path):
        payload = [
            {"file_path": "a/b.md", "title": "T", "snippet": "s" * 200},
            {"path": "c/d.md"},
        ]
        monkey_bin = write_stub_miyo(tmp_path, payload)
        orig = pull.MIYO_BIN
        pull.MIYO_BIN = monkey_bin
        try:
            hits = pull.run_search("q")
        finally:
            pull.MIYO_BIN = orig
        assert len(hits) == 2
        assert hits[0][0] == "a/b.md" and len(hits[0][2]) == 160

    def test_run_search_fail_open_on_bad_output(self, tmp_path):
        broken = tmp_path / "broken-miyo"
        broken.write_text("#!/bin/sh\necho 'not json'\n")
        broken.chmod(broken.stat().st_mode | stat.S_IEXEC)
        orig = pull.MIYO_BIN
        pull.MIYO_BIN = str(broken)
        try:
            assert pull.run_search("q") == []
        finally:
            pull.MIYO_BIN = orig

    def test_render_caps_and_dedupes(self):
        hits = [("same.md", "t", "s"), ("same.md", "t2", "s2"), ("other.md", "o", "")]
        text = pull.render("/x/consulting/p", ["q1"], [hits])
        assert text.count("same.md") == 1
        assert len(text) <= pull.MAX_CHARS

    def test_main_silent_when_missing_binary(self, tmp_path, capsys):
        rc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "miyo-session-pull.py")],
            input=json.dumps({"cwd": str(tmp_path)}),
            env={**os.environ, "MIYO_BIN": str(tmp_path / "nope")},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert rc.returncode == 0
        assert rc.stdout == ""


class TestGateScan:
    def test_counts_research_and_miyo(self, tmp_path):
        t = tmp_path / "transcript.jsonl"
        rows = [
            {"type": "assistant", "message": {"content": [{"name": "Grep"}]}},
            {"type": "assistant", "message": {"content": [{"name": "Glob"}]}},
        ]
        lines = [json.dumps(r) for r in rows]
        lines.append('{"tool_name":"mcp__miyo__search","input":{"query":"x"}}')
        t.write_text("\n".join(lines))
        research, used = gate.scan_transcript(str(t))
        assert research == 2
        assert used is True

    def test_bash_miyo_counts_as_used(self, tmp_path):
        t = tmp_path / "transcript.jsonl"
        t.write_text('{"name":"Bash","command":"~/.miyo/bin/miyo search \\"q\\""}\n')
        research, used = gate.scan_transcript(str(t))
        assert used is True

    def test_no_miyo_detected(self, tmp_path):
        t = tmp_path / "transcript.jsonl"
        t.write_text('{"name":"Grep"}\n{"name":"Read"}\n')
        research, used = gate.scan_transcript(str(t))
        assert research == 1
        assert used is False


class TestGateDecide:
    def test_blocks_over_threshold_without_miyo(self):
        block, msg = gate.decide(5, False, 4)
        assert block is True
        assert "miyo search" in msg

    def test_passes_under_threshold(self):
        assert gate.decide(3, False, 4) == (False, None)

    def test_passes_once_miyo_used_even_over_threshold(self):
        assert gate.decide(50, True, 4) == (False, None)

    def test_message_names_kill_switch(self):
        _, msg = gate.decide(9, False, 4)
        assert "MIYO_GATE_OFF" in msg


class TestGateMain:
    BASE = {
        "tool_name": "Grep",
        "cwd": "/Users/x/projects/consulting/projects/p",
    }

    def run_gate(self, tmp_path, payload):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "miyo-research-gate.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(tmp_path),
        )

    def make_transcript(self, tmp_path, n_grep=6, miyo=False):
        t = tmp_path / "t.jsonl"
        lines = ['{"name":"Grep"}'] * n_grep
        if miyo:
            lines.append('{"name":"mcp__miyo__search"}')
        t.write_text("\n".join(lines))
        return str(t)

    def test_blocks_at_threshold(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MIYO_GATE_THRESHOLD", "4")
        p = dict(self.BASE, transcript_path=self.make_transcript(tmp_path))
        rc = self.run_gate(tmp_path, p)
        assert rc.returncode == 2
        assert "miyo" in rc.stderr.lower()

    def test_passes_with_miyo_in_transcript(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MIYO_GATE_THRESHOLD", "4")
        p = dict(
            self.BASE,
            transcript_path=self.make_transcript(tmp_path, miyo=True),
        )
        rc = self.run_gate(tmp_path, p)
        assert rc.returncode == 0

    def test_fails_open_without_transcript(self, tmp_path):
        p = dict(self.BASE, transcript_path="/nonexistent/t.jsonl")
        rc = self.run_gate(tmp_path, p)
        assert rc.returncode == 0

    def test_ignores_non_research_tools(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MIYO_GATE_THRESHOLD", "1")
        p = dict(
            self.BASE,
            tool_name="Read",
            transcript_path=self.make_transcript(tmp_path),
        )
        rc = self.run_gate(tmp_path, p)
        assert rc.returncode == 0

    def test_out_of_scope_never_blocks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MIYO_GATE_THRESHOLD", "1")
        p = dict(
            self.BASE,
            cwd="/Users/somewhere/else",
            transcript_path=self.make_transcript(tmp_path),
        )
        rc = self.run_gate(tmp_path, p)
        assert rc.returncode == 0

    def test_malformed_stdin_fails_open(self, tmp_path):
        rc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "miyo-research-gate.py")],
            input="not json at all {{{",
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(tmp_path),
        )
        assert rc.returncode == 0
