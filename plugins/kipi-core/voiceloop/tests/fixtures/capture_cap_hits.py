#!/usr/bin/env python3
"""Producer for the capped-run fixtures (ASK-2011). Regenerate, never hand-edit.

ASK-2008's fixture named a generator that was not in this repo, so the capture
could not be regenerated when the CLI's JSON shape drifted (PR #410 round review,
nit on claude-p-capture-2026-09-22.json:120). This script IS the generator for
the two documents Step 5 parses, and it lives beside them.

It SPENDS two real model calls on Haiku. Run it only when the CLI's capped-run
shape needs re-measuring:

    python3 plugins/kipi-core/voiceloop/tests/fixtures/capture_cap_hits.py

The two runs are built to hit their cap rather than to finish:

- turn cap: one tool call is required to answer, and `--max-turns 1` spends the
  only turn on the tool call, so the CLI stops before the answer.
- budget cap: `--max-budget-usd` is set below the price of one request.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "claude-haiku-4-5-20251001"
NO_MCP = ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']


#: What the recorded argv calls the binary. The RESOLVED path is whatever
#: `shutil.which` found on the capturing machine, which on this fleet is under
#: the founder's home -- and `test_no_founder_data` blocks a founder path inside
#: the plugin tree, correctly: this tree fans out to every instance. The capture
#: is evidence about the CLI's OUTPUT, and which directory the binary sat in is
#: no part of that, so the recorded argv keeps the name and drops the path.
BINARY_IN_FIXTURE = "claude"


def _scrub(arg: str, binary: str) -> str:
    """One argv element as it is RECORDED: no founder path, no long prompt."""
    if arg == binary:
        return BINARY_IN_FIXTURE
    return arg if len(arg) < 120 else "<prompt>"


def run(argv: list[str]) -> dict:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    return {"argv": [_scrub(a, argv[0]) for a in argv],
            "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def main() -> int:
    binary = shutil.which("claude")
    if not binary:
        sys.stderr.write("no claude binary on PATH\n")
        return 1
    cases = {
        "turn_cap": [binary, "-p",
                     "Use the Bash tool to run: echo hi. Then report what it printed.",
                     "--model", MODEL, *NO_MCP, "--allowedTools", "Bash",
                     "--output-format", "json", "--max-turns", "1"],
        "budget_cap": [binary, "-p", "Say pong and nothing else.",
                       "--model", MODEL, *NO_MCP,
                       "--output-format", "json", "--max-budget-usd", "0.000001"],
    }
    out = {}
    for name, argv in cases.items():
        out[name] = run(argv)
        doc = out[name]["stdout"][:200].replace("\n", " ")
        sys.stderr.write(f"{name}: exit={out[name]['returncode']} stdout[:200]={doc}\n")
    target = os.path.join(HERE, "claude-p-cap-hits-capture.json")
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    sys.stderr.write(f"wrote {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
