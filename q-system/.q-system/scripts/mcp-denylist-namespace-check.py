#!/usr/bin/env python3
"""ASK-1923: measure destructive-op-deny.sh's MCP denylist in BOTH directions.

The denylist is a `case "$TOOL_NAME"` block of SERVER-NAME wildcards. That shape
is wrong twice over, and the two errors hide each other:

  OVER-BROAD  a wildcard on a server namespace denies that server's read-only
              queries too. `list_issues` and `get_issue` are refused.
  UNDER-BROAD a wildcard on a namespace NOBODY LOADS protects nothing, and reads
              exactly like protection. `mcp__plugin_linear_linear__*` is denied
              while the namespace actually registered is `mcp__linear__*`, so
              `mcp__linear__delete_issue` walks through -- against the founder's
              global CLAUDE.md, which names Linear *delete* as hook-blocked
              regardless of mode.

Run it:

    python3 q-system/.q-system/scripts/mcp-denylist-namespace-check.py --report
    python3 q-system/.q-system/scripts/mcp-denylist-namespace-check.py [--hook PATH]

`--report` prints the enumeration and always exits 0. The default mode exits 1
when a known-destructive tool measures ALLOW or a known-safe one measures DENY,
and 0 when every case agrees. Nothing is executed at the vendor side: the hook
only DECIDES, and HOME is redirected so its audit log never lands in the real one.

WHY THE EXPECTATIONS LIVE HERE AND ARE NOT DERIVED FROM THE HOOK.
`derive-a-value-from-its-owner` says never restate a value the shipping code
owns. That rule is about a value with ONE owner. This file is an ORACLE: it has
to hold a ground truth the hook does not own, or it cannot judge the hook at all.
A checker that derived its expectations from the matcher it checks would agree
with every matcher, including a broken one. So the two sources are deliberate,
and what IS derived from the hook -- never retyped -- is the set of namespaces
the denylist matches (`denylist_namespaces`).

WHERE THE TOOL NAMES CAME FROM. Every row carries `source`. `session` means the
name was read off a live Claude Code session's tool list on 2026-09-20, so it is
a namespace that really loads. `issue` means the name is quoted in ASK-1923,
measured there. `founder-claude-md` means the founder's global CLAUDE.md names
the operation class as hook-blocked. No name here was invented to make a case.
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIXTURE = REPO / "q-system/.q-system/tests/fixtures/destructive-op-deny.reference.sh"
LIVE = pathlib.Path(os.environ.get("HOME", "")) / ".claude/hooks/destructive-op-deny.sh"

# Same resolution order as probe_hook.py and test_destructive_op_deny_anchor.py,
# so all three suites agree about what "the guard" is on any given machine.
def resolve_hook():
    override = os.environ.get("KIPI_DESTRUCTIVE_HOOK")
    if override:
        return pathlib.Path(override)
    if LIVE.is_file():
        return LIVE
    return FIXTURE


# --- the oracle -------------------------------------------------------------
# expect: what the hook MUST decide. "deny" for anything that deletes or unlinks
# vendor-side state, "allow" for anything that only reads.
CASES = [
    # ---- destructive, and the namespace really is loaded --------------------
    {"tool": "mcp__linear__delete_issue", "expect": "deny", "source": "issue",
     "why": "founder CLAUDE.md names Linear *delete* as hook-blocked; the loaded "
            "namespace is mcp__linear__, not mcp__plugin_linear_linear__"},
    {"tool": "mcp__linear__delete_comment", "expect": "deny", "source": "session"},
    {"tool": "mcp__linear__delete_attachment", "expect": "deny", "source": "session"},
    {"tool": "mcp__linear__delete_status_update", "expect": "deny", "source": "session"},
    {"tool": "mcp__supabase__delete_branch", "expect": "deny", "source": "issue",
     "why": "on no list at all; measured ALLOW in ASK-1923"},
    {"tool": "mcp__supabase__reset_branch", "expect": "deny", "source": "session"},
    {"tool": "mcp__claude_ai_Gmail__delete_label", "expect": "deny",
     "source": "founder-claude-md"},
    {"tool": "mcp__claude_ai_Gmail__delete_draft", "expect": "deny", "source": "session"},
    {"tool": "mcp__claude_ai_Gmail__unlabel_thread", "expect": "deny",
     "source": "founder-claude-md"},
    {"tool": "mcp__claude_ai_Gmail__trash_thread", "expect": "deny", "source": "session"},
    {"tool": "mcp__claude_ai_Notion__notion-move-pages", "expect": "deny",
     "source": "founder-claude-md"},
    {"tool": "mcp__claude_ai_Google_Calendar__delete_event", "expect": "deny",
     "source": "founder-claude-md"},
    {"tool": "mcp__claude_ai_Google_Drive__trash_file", "expect": "deny", "source": "session"},
    {"tool": "mcp__claude_ai_Resend__remove-domain", "expect": "deny", "source": "session"},

    # ---- read-only, and the namespace really is loaded ----------------------
    {"tool": "mcp__linear__list_issues", "expect": "allow", "source": "session"},
    {"tool": "mcp__linear__get_issue", "expect": "allow", "source": "session"},
    {"tool": "mcp__linear__list_comments", "expect": "allow", "source": "session"},
    {"tool": "mcp__claude_ai_Notion__notion-search", "expect": "allow", "source": "session"},
    {"tool": "mcp__claude_ai_Notion__notion-fetch", "expect": "allow", "source": "session"},
    {"tool": "mcp__supabase__list_tables", "expect": "allow", "source": "session"},
    {"tool": "mcp__claude_ai_Gmail__list_labels", "expect": "allow", "source": "session"},
    {"tool": "mcp__claude_ai_Google_Calendar__list_events", "expect": "allow",
     "source": "session"},
    {"tool": "mcp__claude_ai_Resend__list-domains", "expect": "allow", "source": "session"},
    {"tool": "mcp__plugin_kipi-core_kipi__kipi_query", "expect": "allow", "source": "session"},

    # ---- read-only on the namespaces the denylist DOES wildcard -------------
    # These are the over-broad half, verbatim from ASK-1923. They are reads, so
    # they must ALLOW whether or not the namespace is one anybody loads.
    {"tool": "mcp__plugin_linear_linear__list_issues", "expect": "allow", "source": "issue"},
    {"tool": "mcp__plugin_linear_linear__get_issue", "expect": "allow", "source": "issue"},
    {"tool": "mcp__plugin_vercel_vercel__list_deployments", "expect": "allow",
     "source": "issue"},
    {"tool": "mcp__plugin_Notion_notion__notion-search", "expect": "allow", "source": "issue"},
]

# The carve-out the current block already has, kept as a case so a fix cannot
# quietly drop it.
CASES.append({"tool": "mcp__plugin_vercel_vercel__authenticate", "expect": "allow",
              "source": "issue", "why": "the one carve-out the current block has"})


# --- derived from the hook, never retyped -----------------------------------
MCP_BLOCK = re.compile(
    r"#\s*----\s*MCP destructive tool denials\s*----.*?^esac", re.S | re.M)


def denylist_namespaces(hook_text):
    """The `mcp__...` patterns the hook's MCP case block matches.

    Read out of the hook at run time. Retyping them here would make this file
    agree with itself instead of with the guard.
    """
    block = MCP_BLOCK.search(hook_text)
    if not block:
        return []
    return sorted(set(re.findall(r"mcp__[A-Za-z0-9_*-]+", block.group(0))))


def registered_namespaces(mcp_configs, cases):
    """`mcp__<server>__` prefixes that are reachable on this machine.

    Two sources, unioned: the MCP config files (declared servers) and the tool
    names in CASES marked `source: session` (observed loading). A denylist
    wildcard outside this union is protecting a name nobody can call.
    """
    found = set()
    for path in mcp_configs:
        try:
            data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for server in (data.get("mcpServers") or {}):
            found.add("mcp__%s__" % server)
    for case in cases:
        if case.get("source") == "session":
            found.add(case["tool"].rsplit("__", 1)[0] + "__")
    return found


def namespace_of(pattern):
    """`mcp__plugin_linear_linear__*` -> `mcp__plugin_linear_linear__`."""
    stripped = pattern.rstrip("*")
    if stripped.endswith("__"):
        return stripped
    return stripped.rsplit("__", 1)[0] + "__"


def dead_wildcards(hook_text, registered):
    """Denylist namespaces no registered server answers to."""
    dead = []
    for pattern in denylist_namespaces(hook_text):
        if not pattern.endswith("*"):
            continue
        ns = namespace_of(pattern)
        if ns not in registered:
            dead.append(pattern)
    return dead


# --- running the matcher ----------------------------------------------------
def decide(hook, tool_name, home):
    """Run a COPY of the hook on an MCP payload; return 'deny' or 'allow'."""
    copy = pathlib.Path(home) / "under-test.sh"
    shutil.copy(hook, copy)
    payload = json.dumps({"tool_name": tool_name, "tool_input": {}, "cwd": str(home)})
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("ALLOW_DESTRUCTIVE", None)
    proc = subprocess.run(["bash", str(copy)], input=payload,
                          capture_output=True, text=True, env=env)
    out = proc.stdout.strip()
    if not out:
        return "allow"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def measure(hook, cases=None):
    """[(case, decision)] for every case, each in its own throwaway HOME."""
    results = []
    for case in (cases if cases is not None else CASES):
        with tempfile.TemporaryDirectory() as home:
            results.append((case, decide(hook, case["tool"], home)))
    return results


def failures(hook, cases=None):
    """Cases whose measured decision is not the one the oracle requires."""
    return [(c, d) for c, d in measure(hook, cases) if d != c["expect"]]


# --- cli --------------------------------------------------------------------
def default_configs():
    return [REPO / ".mcp.json",
            pathlib.Path(os.environ.get("HOME", "")) / ".claude.json"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hook", help="guard to drive (default: see module doc)")
    parser.add_argument("--report", action="store_true",
                        help="print the enumeration and exit 0")
    parser.add_argument("--mcp-config", action="append", default=None,
                        help="MCP config JSON to read registered servers from "
                             "(repeatable; default: repo .mcp.json + ~/.claude.json)")
    args = parser.parse_args(argv)

    hook = pathlib.Path(args.hook) if args.hook else resolve_hook()
    if not hook.is_file():
        print("no guard to measure: %s" % hook, file=sys.stderr)
        return 2
    text = hook.read_text(encoding="utf-8")
    configs = args.mcp_config or default_configs()
    registered = registered_namespaces(configs, CASES)

    print("guard: %s" % hook)
    print("denylist patterns (read from the guard): %s"
          % ", ".join(denylist_namespaces(text)))

    dead = dead_wildcards(text, registered)
    print("\nDIRECTION 2 -- wildcards on namespaces nothing registers:")
    if dead:
        for pattern in dead:
            print("  DEAD   %s   (no registered server answers to it)" % pattern)
    else:
        print("  none")

    print("\nDIRECTION 1 -- what the matcher decides, case by case:")
    bad = []
    for case, decision in measure(hook):
        mark = "" if decision == case["expect"] else "   <- must %s" % case["expect"]
        if mark:
            bad.append((case, decision))
        print("  %-6s %-52s [%s]%s"
              % (decision.upper(), case["tool"], case["source"], mark))

    if args.report:
        print("\n%d case(s) disagree with the oracle. --report never fails."
              % len(bad))
        return 0

    if bad:
        print("\nFAIL: %d case(s) wrong." % len(bad))
        for case, decision in bad:
            print("  %s measured %s, must be %s%s"
                  % (case["tool"], decision, case["expect"],
                     " -- " + case["why"] if case.get("why") else ""))
        return 1
    print("\nOK: every case agrees with the oracle.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
