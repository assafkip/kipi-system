#!/usr/bin/env python3
"""Paired test for token-guard.py's observation exemption (sp-ff7611cd) and
stall-warn rate limit (F4, prd-silent-absence-capability-gate-2026-07-23).

Pure-function tests on synthetic cache dicts — no /tmp cache files touched.
Includes the negative self-test fable-discipline requires: the blocking path
must still BLOCK, so the exemption cannot silently disable the guard.
"""
import importlib.util
import pathlib
import sys
import time

GUARD = pathlib.Path(__file__).resolve().parents[1] / "token-guard.py"
spec = importlib.util.spec_from_file_location("token_guard", GUARD)
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)

failures = []


def check(name, cond):
    if cond:
        print(f"PASS: {name}")
    else:
        failures.append(name)
        print(f"FAIL: {name}")


def cache_with_repeats(tool_name, tool_input, count):
    import hashlib, json
    h = hashlib.md5((tool_name + json.dumps(tool_input, sort_keys=True)).encode()).hexdigest()[:12]
    return {"repeat_map": {f"{tool_name}:{h}": count}}


# 1. Negative self-test: a non-observation tool at the limit still BLOCKS.
edit_input = {"file_path": "/x.py", "old_string": "a", "new_string": "b"}
cache = cache_with_repeats("Edit", edit_input, tg.RETRY_LIMIT)
check("exact_retry still blocks Edit at limit",
      tg.check_exact_retry("Edit", edit_input, cache) is not None)

# 2. A dedicated screenshot tool at (and beyond) the limit is exempt.
shot = {}
cache = cache_with_repeats("mcp__computer-use__screenshot", shot, tg.RETRY_LIMIT + 5)
check("screenshot tool exempt at limit+5",
      tg.check_exact_retry("mcp__computer-use__screenshot", shot, cache) is None)

# 3. Multi-action tool: screenshot action exempt, click action not.
obs = {"action": "screenshot"}
cache = cache_with_repeats("mcp__claude-in-chrome__computer", obs, tg.RETRY_LIMIT)
check("computer action=screenshot exempt",
      tg.check_exact_retry("mcp__claude-in-chrome__computer", obs, cache) is None)
clk = {"action": "left_click"}
cache = cache_with_repeats("mcp__claude-in-chrome__computer", clk, tg.RETRY_LIMIT)
check("computer action=left_click still blocks",
      tg.check_exact_retry("mcp__claude-in-chrome__computer", clk, cache) is not None)

# 4. Stall warn fires once, then is suppressed inside the window.
stalled = {"last_write_time": time.time() - tg.STALL_TIME_SECONDS - 5,
           "calls_since_write": tg.STALL_MIN_CALLS}
first = tg.check_time_stall(stalled)
check("stall warns on first trip", first is not None)
second = tg.check_time_stall(stalled)
check("stall suppressed inside window", second is None)

# 5. Stall re-warns after the window elapses.
stalled["last_stall_warn_time"] = time.time() - tg.STALL_TIME_SECONDS - 1
third = tg.check_time_stall(stalled)
check("stall re-warns after window", third is not None)

# 6. is_readonly_observation never claims a mutating tool.
for tool in ("Edit", "Write", "Bash", "mcp__claude-in-chrome__navigate"):
    check(f"{tool} is not an observation", not tg.is_readonly_observation(tool, {}))

if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nALL PASS")
