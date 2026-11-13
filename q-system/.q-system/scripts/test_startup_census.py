"""Tests for startup_census.py (ASK-4747).

The fixture is a real sana subagent transcript (2026-11-13, PR #786 build) with
every text and tool schema replaced by filler of the SAME length, so the
lengths the census reports are the real ones and no private text is committed.
The known answers below were read by hand from the original transcript before
the census existed: first request 132,256 tokens, granola tool schemas 23,744
characters, instructions block 100,236 characters.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FX = HERE / "fixtures" / "startup_census" / "sana_first.ndjson"
sys.path.insert(0, str(HERE))
import startup_census  # noqa: E402


def _recs():
    return [json.loads(line) for line in FX.read_text().splitlines() if line.strip()]


def test_first_request_context_is_the_earliest_not_the_last():
    # The fixture holds 100+ requests; the last one is far larger than the first.
    recs = _recs()
    assert startup_census.census(recs)["context_first"] == 132256


def test_parts_match_the_hand_read_numbers():
    p = startup_census.census(_recs())["parts_chars"]
    assert p["tools.granola"] == 23744
    assert p["instructions"] == 100236
    assert p["tool_addition.claude_ai_Firecrawl"] == 26791
    assert p["skill_listing"] == 30078


def test_only_the_first_requests_blobs_count():
    # Blobs written after the first api-request belong to request 2. Counting
    # them would grow brief_and_other past the brief the agent was given.
    p = startup_census.census(_recs())["parts_chars"]
    assert p["brief_and_other"] == 6110


def test_usage_counts_tool_calls():
    c = startup_census.census(_recs())
    assert c["mcp_servers_called"] == {"linear": 9}
    assert c["skills_called"] == {"prd-os:fable-discipline": 1}
    assert "granola" not in c["mcp_servers_called"]


def test_missing_shape_exits_1(tmp_path):
    f = tmp_path / "t.ndjson"
    f.write_text(json.dumps({"type": "assistant", "message": {"usage": {}, "content": []}}) + "\n")
    p = subprocess.run([sys.executable, str(HERE / "startup_census.py"), str(f)],
                       capture_output=True, text=True)
    assert p.returncode == 1
    assert "no api-request-shape" in p.stderr
