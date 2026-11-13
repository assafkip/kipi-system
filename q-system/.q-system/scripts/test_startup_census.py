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


def test_context_first_is_run_tokens_number_on_the_same_bytes():
    # The fixture keeps the producer's envelope (message id, model, timestamp), so
    # run_tokens reads it as 104 requests. The census reports run_tokens' number,
    # never a second count of its own.
    import run_tokens
    r = run_tokens.report([str(FX)])
    assert r["requests"] == 104
    assert r["context_first"] == 132256
    assert startup_census.census_file(str(FX))["context_first"] == 132256


def test_relative_or_doubled_path_reads_the_same(monkeypatch):
    monkeypatch.chdir(FX.parent)
    assert startup_census.census_file("./" + FX.name)["context_first"] == 132256
    assert startup_census.census_file(str(FX.parent) + "//" + FX.name)["context_first"] == 132256


def test_api_error_or_synthetic_first_record_is_not_a_free_start_up(tmp_path):
    bad = [{"type": "assistant", "isApiErrorMessage": True, "timestamp": "2026-11-13T00:00:00Z",
            "message": {"id": "e1", "model": "claude-opus-5-5", "usage": {"input_tokens": 0}, "content": []}},
           {"type": "assistant", "timestamp": "2026-11-13T00:00:00Z",
            "message": {"id": "s1", "model": "<synthetic>", "usage": {"input_tokens": 0}, "content": []}}]
    f = tmp_path / "t.ndjson"
    f.write_text("".join(json.dumps(r) + "\n" for r in bad) + FX.read_text())
    assert startup_census.census_file(str(f))["context_first"] == 132256


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
    assert c["mcp_servers_called"] == {"linear": 11}
    assert c["skills_called"] == {"prd-os:fable-discipline": 1}
    assert "granola" not in c["mcp_servers_called"]


def test_missing_shape_exits_1(tmp_path):
    f = tmp_path / "t.ndjson"
    f.write_text(json.dumps({"type": "assistant", "message": {"usage": {}, "content": []}}) + "\n")
    p = subprocess.run([sys.executable, str(HERE / "startup_census.py"), str(f)],
                       capture_output=True, text=True)
    assert p.returncode == 1
    assert "no api-request-shape" in p.stderr


def test_deferred_header_without_tool_additions_still_splits():
    # Producer shape after the MCP cut: no tool_addition blocks, so the block
    # opens with the deferred-tools header instead. Header text copied from a
    # real transcript; filler stands in for the names, environment and listing.
    head = "The following deferred tools are now available via ToolSearch."
    text = head + "x" * 3880 + "# Environment" + "y" * 1524 + "The following skills are available" + "z" * 30000
    recs = [{"type": "api-request-shape", "shape": {"system": [], "tools": []}},
            {"type": "api-request-blob", "message": {"content": [{"type": "text", "text": text}]}},
            {"type": "api-request"}]
    p = startup_census.parts(recs)
    assert p["skill_listing"] == 30000 + len("The following skills are available")
    assert p["deferred_tools_and_mcp_instructions"] == len(head) + 3880
    assert "brief_and_other" not in p


def test_listing_before_environment_is_counted_once():
    head = "The following deferred tools are now available via ToolSearch."
    text = head + "x" * 100 + "The following skills are available" + "z" * 1000 + "# Environment" + "y" * 500
    recs = [{"type": "api-request-shape", "shape": {"system": [], "tools": []}},
            {"type": "api-request-blob", "message": {"content": [{"type": "text", "text": text}]}},
            {"type": "api-request"}]
    p = startup_census.parts(recs)
    assert sum(p.values()) == len(text)
    assert p["environment"] == len("# Environment") + 500


def test_malformed_shape_is_reported_and_the_batch_goes_on(tmp_path):
    bad = tmp_path / "bad.ndjson"
    bad.write_text(json.dumps({"type": "api-request-shape"}) + "\n")
    p = subprocess.run([sys.executable, str(HERE / "startup_census.py"), str(bad), str(FX)],
                       capture_output=True, text=True)
    assert p.returncode == 1
    assert "cannot read" in p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["context_first"] for r in rows] == [132256]


def test_string_content_blob_is_counted():
    # Producer shape: a system blob whose content is a plain string.
    text = "The following deferred tools are now available via ToolSearch." + "x" * 900
    recs = [{"type": "api-request-shape", "shape": {"system": [], "tools": []}},
            {"type": "api-request-blob", "message": {"role": "system", "content": text}},
            {"type": "api-request"}]
    assert sum(startup_census.parts(recs).values()) == len(text)


def test_empty_shape_is_named_as_present(tmp_path):
    f = tmp_path / "e.ndjson"
    f.write_text(json.dumps({"type": "api-request-shape", "shape": {"system": [], "tools": []}}) + "\n")
    p = subprocess.run([sys.executable, str(HERE / "startup_census.py"), str(f)], capture_output=True, text=True)
    assert p.returncode == 1
    assert "api-request-shape present, no parts" in p.stderr
