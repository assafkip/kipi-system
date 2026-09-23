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

    # ---- destruction carried in the PAYLOAD, invisible in the name ----------
    # The operation name reads as ordinary and the statement is not. Both
    # measured ALLOW while this checker printed OK, because the oracle had no
    # case for them: a clean run was reporting coverage it did not have (PR #390
    # review round 3, major).
    {"tool": "mcp__supabase__execute_sql", "expect": "deny", "source": "session",
     "input": {"query": "DROP TABLE users;"},
     "why": "`execute_sql` matches no destructive verb; the DROP is in the payload"},
    {"tool": "mcp__supabase__apply_migration", "expect": "deny", "source": "session",
     "input": {"name": "drop_email",
               "query": "ALTER TABLE users DROP COLUMN email;"},
     "why": "a migration that drops a column is a schema deletion"},

    # ---- a destructive verb the gate cannot place ---------------------------
    # Local plugin state, not vendor state. Denied ON PURPOSE and fail-closed:
    # the gate cannot tell local from remote, the miss costs production data and
    # the false positive costs one approval. What the review found was the
    # MESSAGE claiming vendor-side deletion, which it no longer does (PR #390
    # review round 3, minor).
    {"tool": "mcp__plugin_kipi-core_kipi__loop_force_close", "expect": "deny",
     "source": "session",
     "why": "force-closing a tracked loop destroys tracking state; the deny "
            "message now says only that a destructive verb matched"},
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

    # ---- mutating, on a server where EVERY non-read op is denied -------------
    # The founder's global CLAUDE.md names "Vercel mutating ops". The registered
    # Vercel connector is `mcp__claude_ai_Vercel__`, with a CAPITAL V, so a
    # server matcher that is case-sensitive misses it -- the same server-name
    # miss this issue exists to fix (PR #390 review, minor).
    {"tool": "mcp__claude_ai_Vercel__update_project", "expect": "deny",
     "source": "synthetic-op-real-server",
     "why": "the SERVER segment is real (the claude.ai Vercel connector, seen "
            "unauthenticated in this session's server list); the op name is "
            "synthetic because an unauthenticated connector exposes no tool "
            "list to read one from. The assertion here is about the server "
            "segment, which the op name does not affect"},

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
    # The other side of the payload rule. Keyed on the STATEMENT, so the same
    # two operations that deny a DROP still run a SELECT and an additive
    # migration -- a gate that refuses every query is a gate someone switches off.
    {"tool": "mcp__supabase__execute_sql", "expect": "allow", "source": "session",
     "input": {"query": "SELECT id FROM users LIMIT 5"}},
    {"tool": "mcp__supabase__apply_migration", "expect": "allow", "source": "session",
     "input": {"name": "add_nickname",
               "query": "ALTER TABLE users ADD COLUMN nickname text"}},
    # A drag-and-drop GESTURE. `drop` reads as a destructive SQL verb and is not
    # one here; it was on the destructive list and denied a mouse move with a
    # message about vendor-side deletion (PR #390 review, minor).
    {"tool": "mcp__playwright__browser_drop", "expect": "allow", "source": "session"},
    {"tool": "mcp__playwright__browser_drag", "expect": "allow", "source": "session"},
    # On the read list, and it WRITES: it resolves a review thread at the vendor
    # side. Not destructive, so `allow` is the right decision either way -- the
    # defect the reviewer named was the claim that the read list opens nothing
    # that writes. Kept as a case so the claim stays checkable.
    {"tool": "mcp__linear__resolve_diff_thread", "expect": "allow", "source": "session"},

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
def run_hook(hook, tool_name, home, tool_input=None):
    """Drive a COPY of the guard with one MCP payload; return its parsed reply.

    None when the guard said nothing, which is how it signals allow. `tool_input`
    is the verbatim payload: some operations carry their destruction there and
    nowhere in the name, so a checker that always sent `{}` could not see them.
    """
    copy = pathlib.Path(home) / "under-test.sh"
    shutil.copy(hook, copy)
    payload = json.dumps({"tool_name": tool_name,
                          "tool_input": tool_input if tool_input is not None else {},
                          "cwd": str(home)})
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("ALLOW_DESTRUCTIVE", None)
    proc = subprocess.run(["bash", str(copy)], input=payload,
                          capture_output=True, text=True, env=env)
    out = proc.stdout.strip()
    return json.loads(out) if out else None


def decide(hook, tool_name, home, tool_input=None):
    """'deny' or 'allow' for one MCP call."""
    reply = run_hook(hook, tool_name, home, tool_input)
    if reply is None:
        return "allow"
    return reply["hookSpecificOutput"]["permissionDecision"]


def deny_reason(hook, tool_name, home, tool_input=None):
    """The guard's stated reason, or None when it allowed the call."""
    reply = run_hook(hook, tool_name, home, tool_input)
    if reply is None:
        return None
    return reply["hookSpecificOutput"]["permissionDecisionReason"]


def deny_hash(hook, tool_name, home, tool_input=None):
    """The `kipi-approve <hash>` grant scope the guard offers for `tool_name`.

    None when the guard allowed the call (no grant is offered for an allow).
    """
    reason = deny_reason(hook, tool_name, home, tool_input)
    if reason is None:
        return None
    # One literal space, then a possibly-EMPTY token. `\s+(\S+)` walked past the
    # blank the guard emits when no capability-token.sh is reachable and
    # captured the next word ("(or"), so two different calls both "hashed" to
    # the same fixed string and a binding test passed on a guard that binds
    # nothing (PR #390 review round 3, found while writing its reproducer).
    found = re.search(r"kipi-approve (\S*)", reason)
    return (found.group(1) or None) if found else None


# A payload whose values are unmistakable in a log line. The guard's
# log_decision writes "$COMMAND" verbatim into
# $HOME/.claude/audit/destructive-op-deny.log, so binding the approval grant to
# the raw tool_input put every MCP argument on disk in plaintext.
PAYLOAD_PROBE = {"labelId": "SECRET-LABEL-42", "token": "hunter2"}


def logged_command(hook, tool_name, home, tool_input=None):
    """The `cmd` field the guard wrote into its audit log for this call."""
    run_hook(hook, tool_name, home, tool_input)
    log = pathlib.Path(home) / ".claude/audit/destructive-op-deny.log"
    if not log.is_file():
        return None
    rows = [r for r in log.read_text(encoding="utf-8").splitlines() if r.strip()]
    if not rows:
        return None
    return json.loads(rows[-1])["cmd"]


def payload_in_audit_log(hook, home, tool="mcp__claude_ai_Gmail__delete_label"):
    """Does the plaintext audit log carry the MCP payload verbatim?

    'LEAK', 'digest' (bound but unreadable), 'unbound' (nothing about the call
    reached the log, which is what an UNPATCHED guard does -- reporting that as
    'digest' would read as protection), or 'no-log'.
    """
    cmd = logged_command(hook, tool, home, PAYLOAD_PROBE)
    if cmd is None:
        return "no-log"
    if any(v in cmd for v in PAYLOAD_PROBE.values()):
        return "LEAK"
    return "digest" if tool in cmd else "unbound"


def token_home(home):
    """A throwaway HOME carrying the REAL capability-token.sh, or None.

    The token script is copied, never stubbed: a stub would encode this file's
    idea of how grants are scoped, and the thing being measured IS how they are
    scoped. Returns None when the machine has no token script to copy.
    """
    source = pathlib.Path(os.environ.get(
        "KIPI_CAPABILITY_TOKEN",
        str(pathlib.Path(os.environ.get("HOME", "")) / ".claude/bin/capability-token.sh")))
    if not source.is_file():
        return None
    home = pathlib.Path(home)
    (home / ".claude/bin").mkdir(parents=True, exist_ok=True)
    installed = home / ".claude/bin/capability-token.sh"
    shutil.copy(source, installed)
    installed.chmod(0o755)
    return installed


def grant_leak(hook, home, tool_a="mcp__claude_ai_Gmail__delete_label",
               tool_b="mcp__claude_ai_Google_Calendar__delete_event"):
    """Does one approved MCP denial unlock a DIFFERENT MCP destructive op?

    emit_deny scopes its grant to `$COMMAND` + `$CWD`, and an MCP payload has no
    `.tool_input.command`, so every MCP denial in one cwd hashed the EMPTY
    STRING. Returns one of: 'no-token-script', 'not-both-denied',
    'LEAK' (a grant minted for A was consumed by B), 'scoped'.
    """
    token = token_home(home)
    if token is None:
        return "no-token-script"
    hash_a = deny_hash(hook, tool_a, home)
    hash_b = deny_hash(hook, tool_b, home)
    if hash_a is None or hash_b is None:
        return "not-both-denied"
    env = dict(os.environ)
    env["HOME"] = str(home)
    subprocess.run(["bash", str(token), "mint", hash_a],
                   capture_output=True, text=True, env=env)
    return "LEAK" if decide(hook, tool_b, home) == "allow" else "scoped"


def measure(hook, cases=None):
    """[(case, decision)] for every case, each in its own throwaway HOME."""
    results = []
    for case in (cases if cases is not None else CASES):
        with tempfile.TemporaryDirectory() as home:
            results.append(
                (case, decide(hook, case["tool"], home, case.get("input"))))
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
        # Two cases can share a tool name and differ only in the payload, which
        # is the whole point of the SQL rows: print enough to tell them apart.
        label = case["tool"]
        if case.get("input"):
            label += "  " + json.dumps(case["input"])[:44]
        print("  %-6s %-72s [%s]%s"
              % (decision.upper(), label, case["source"], mark))

    with tempfile.TemporaryDirectory() as home:
        leak = grant_leak(hook, home)
    with tempfile.TemporaryDirectory() as home:
        logged = payload_in_audit_log(hook, home)
    print("\nDIRECTION 3 -- how wide is one approval token:")
    print({
        "LEAK": "  LEAK   a grant minted for one MCP denial was consumed by a "
                "DIFFERENT one\n         (emit_deny hashes $COMMAND, and an MCP "
                "payload carries none)",
        "scoped": "  scoped  a grant for one MCP denial does not unlock another",
        "not-both-denied": "  n/a    the two probe tools are not both denied on "
                           "this guard",
        "no-token-script": "  n/a    no capability-token.sh on this machine to "
                           "measure with",
    }[leak])

    print("\nDIRECTION 4 -- what the plaintext audit log keeps:")
    print({
        "LEAK": "  LEAK   the MCP payload is written verbatim into\n"
                "         $HOME/.claude/audit/destructive-op-deny.log",
        "digest": "  digest  the log records a hash of the payload, not the "
                  "payload",
        "unbound": "  n/a    the log row carries nothing about the call at all "
                   "(an MCP payload\n         has no .tool_input.command), so "
                   "there is no payload to keep yet",
        "no-log": "  n/a    the guard wrote no audit row for the probe call",
    }[logged])

    if args.report:
        print("\n%d case(s) disagree with the oracle. --report never fails."
              % len(bad))
        return 0

    if leak == "LEAK":
        print("\nFAIL: one MCP approval token unlocks any other MCP destructive "
              "operation in the same cwd.")
        return 1

    if logged == "LEAK":
        print("\nFAIL: the guard writes MCP tool_input payloads into its "
              "plaintext audit log.")
        return 1

    if bad:
        print("\nFAIL: %d case(s) wrong." % len(bad))
        for case, decision in bad:
            print("  %s measured %s, must be %s%s"
                  % (case["tool"], decision, case["expect"],
                     " -- " + case["why"] if case.get("why") else ""))
        return 1
    # Say what a pass covers. This script exited 0 and printed OK on a guard
    # that allowed `execute_sql` running DROP TABLE, because the oracle held no
    # case for it (PR #390 review round 3). A clean run means the cases below
    # agree, never that the guard is complete.
    print("\nOK: all %d oracle case(s) agree, the approval token is scoped, and "
          "the audit log keeps no payload.\n"
          "    This is the coverage of the case list above, not a proof that "
          "every destructive MCP operation is denied." % len(CASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
