#!/usr/bin/env python3
"""ASK-1144: refuse an MCP denylist namespace that names no server anywhere.

PAIRS WITH `q-system/.q-system/hooks/destructive-op-deny.sh` (the MCP case).

WHY THIS EXISTS AND WHY IT IS NOT THE FIX
-----------------------------------------
On 2026-08-29 the hook's MCP case named `mcp__plugin_linear_linear__*` while the
loaded Linear server is `mcp__linear__*`, and `mcp__supabase__delete_branch` sat
in the live tool roster matched by nothing. The founder's CLAUDE.md calls Linear
`*delete*` hook-blocked and NON-NEGOTIABLE. It was neither: the rule was stated,
the gate was wired, the pattern matched nothing.

The FIX for that is operation-keyed denial in the hook -- `delete` is spelled
`delete` on every vendor, so the deny stops depending on guessing the vendor
segment. This script is the SECOND half, and it answers a different question:
operation-keying makes a *missing* namespace harmless, but it does not make a
*dead* namespace visible. A dead entry reads, to anyone auditing the file, as
coverage. That is what let the hole survive review.

So: every `mcp__<something>__` namespace the hook names is compared against the
servers this machine can actually register. One that matches nothing is a dead
entry and this exits 1.

WHAT IT CAN AND CANNOT SEE (read the silence narrowly)
-------------------------------------------------------
CAN: a namespace matching NO server in any config on this box.
CANNOT: whether a matched server is loaded in the CURRENT session, whether the
operation names inside a real server exist, or whether a server that IS loaded is
missing from the denylist. The last one is deliberately not this script's job --
operation-keying is what covers it, and a script enumerating "every server that
should be denied" would be a second, drifting copy of the hook's policy.

The connector namespaces (`mcp__claude_ai_*`) live in the user's account, not in
any file on disk, so they cannot be discovered. They are declared in
KNOWN_CONNECTOR_NAMESPACES below, in the open, where a reviewer can see the list
is a declaration rather than a measurement.
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO = os.path.abspath(os.path.join(QROOT, ".."))
DEFAULT_HOOK = os.path.join(QROOT, ".q-system", "hooks", "destructive-op-deny.sh")

# Namespaces served by claude.ai account connectors. Not discoverable from any
# file: they are provisioned per account. Declared, not measured -- so a stale
# entry here is a blind spot this script cannot close, and saying that plainly is
# the point of putting them in one named tuple instead of a regex exemption.
KNOWN_CONNECTOR_NAMESPACES = (
    "mcp__claude_ai_Gmail__",
    "mcp__claude_ai_Google_Calendar__",
    "mcp__claude_ai_Google_Drive__",
    "mcp__claude_ai_Notion__",
)

# `mcp__` + a name + `__`, optionally followed by a shell-glob `*` or a literal
# operation. Only the namespace half is extracted.
NAMESPACE_RE = re.compile(r"\bmcp__([A-Za-z0-9_.\-]+?)__")


def _servers_from_mcp_json(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return []
    return [name for name in servers if isinstance(name, str)]


def plain_server_namespaces():
    """`mcp__<server>__` for every directly-configured server."""
    names = set()
    for path in (
        os.path.join(REPO, ".mcp.json"),
        os.path.expanduser("~/.claude.json"),
        os.path.expanduser("~/.mcp.json"),
    ):
        for name in _servers_from_mcp_json(path):
            names.add("mcp__%s__" % name)
    return names


def _plugin_dirs():
    """(plugin_name, directory) for every plugin whose files are on this box.

    Two layouts, and the second is why this is not a single glob. A marketplace
    clone puts the plugin under a directory named after it
    (`marketplaces/<mp>/<plugin>/`). An installed plugin can instead live in a
    cache clone whose directory name is a git temp id
    (`cache/temp_git_1788041798495_2plx12/`) -- the `vercel` plugin does exactly
    that here, so a name-from-directory rule reports its server as DEAD while the
    tool roster carries `mcp__plugin_vercel_vercel__authenticate`. The plugin's
    real name comes from its own manifest in that case.
    """
    pairs = []
    plugins_root = os.path.expanduser("~/.claude/plugins")

    for path in glob.glob(os.path.join(plugins_root, "marketplaces", "*", "*")):
        if os.path.isdir(path):
            pairs.append((os.path.basename(path), path))
    for path in glob.glob(os.path.join(plugins_root, "marketplaces", "*")):
        if os.path.isdir(path):
            pairs.append((os.path.basename(path), path))
    for path in glob.glob(os.path.join(plugins_root, "cache", "*")):
        if not os.path.isdir(path):
            continue
        manifest = os.path.join(path, ".claude-plugin", "plugin.json")
        name = None
        try:
            with open(manifest) as fh:
                name = json.load(fh).get("name")
        except (OSError, ValueError):
            name = None
        pairs.append((name or os.path.basename(path), path))
    # The repo's own plugins/: what a fleet instance receives. A denylist entry
    # naming one is legitimate on a box where it is not installed yet.
    for path in glob.glob(os.path.join(REPO, "plugins", "*")):
        if os.path.isdir(path):
            pairs.append((os.path.basename(path), path))
    return pairs


def plugin_server_namespaces():
    """`mcp__plugin_<plugin>_<server>__` for every plugin that ships a server."""
    names = set()
    for plugin, directory in _plugin_dirs():
        for path in (
            os.path.join(directory, ".mcp.json"),
            os.path.join(directory, ".claude-plugin", ".mcp.json"),
        ):
            for server in _servers_from_mcp_json(path):
                names.add("mcp__plugin_%s_%s__" % (plugin, server))
    return names


def known_namespaces():
    names = set(KNOWN_CONNECTOR_NAMESPACES)
    names |= plain_server_namespaces()
    names |= plugin_server_namespaces()
    return names


def namespaces_in_hook(hook_path):
    """Every distinct `mcp__<ns>__` in the hook's EXECUTABLE lines, in file order.

    Comment lines are excluded, and that boundary is deliberate rather than
    convenient: this file documents its own scar by naming the two dead
    namespaces it removed. A checker that read comments would make writing that
    history impossible, and the history is the thing that stops the entry coming
    back. What matters is whether a dead namespace can still be read as a live
    DENY -- and only a case pattern can be.

    A `#` inside a string would be mis-stripped. There are none in this file's
    MCP case, and the failure direction is safe: over-stripping can only hide a
    namespace from the check, which the empty-result refusal in main() catches.
    """
    found = []
    with open(hook_path) as fh:
        for line in fh:
            code = line.split("#", 1)[0]
            for match in NAMESPACE_RE.finditer(code):
                ns = "mcp__%s__" % match.group(1)
                if ns not in found:
                    found.append(ns)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", default=DEFAULT_HOOK, help="hook file to inspect")
    parser.add_argument(
        "--list", action="store_true", help="print every known namespace and exit 0"
    )
    args = parser.parse_args(argv)

    known = known_namespaces()

    if args.list:
        for ns in sorted(known):
            print(ns)
        return 0

    if not os.path.isfile(args.hook):
        print("REFUSED: hook not found: %s" % args.hook, file=sys.stderr)
        return 2

    # A checker that finds nothing to check must not report success. If the regex
    # or the file ever stops yielding namespaces, that is a broken checker, not a
    # clean hook -- the exact "runs, passes, blind" shape this whole change is about.
    declared = namespaces_in_hook(args.hook)
    if not declared:
        print(
            "REFUSED: no mcp__ namespace found in %s. Either the hook lost its MCP "
            "case or this checker's parser did; neither is a pass." % args.hook,
            file=sys.stderr,
        )
        return 2

    dead = [ns for ns in declared if ns not in known]

    print("namespaces named by the hook: %d" % len(declared))
    print("servers known to this machine: %d" % len(known))
    for ns in declared:
        print("  %-46s %s" % (ns, "OK" if ns in known else "DEAD"))

    if dead:
        print("")
        print("DEAD NAMESPACE(S) -- these deny nothing and read as coverage:")
        for ns in dead:
            print("  %s" % ns)
        print("")
        print(
            "Fix by deleting the entry, not by widening it: the operation-keyed "
            "deny in the same hook already covers the destructive ops on whatever "
            "server this was meant to name (ASK-1144)."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
