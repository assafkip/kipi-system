#!/usr/bin/env python3
"""kipi-settings-merge: rebuild an instance's .claude/settings.json from
settings-template.json, preserving instance customizations.

Extracted from kipi-update.sh's inline heredoc (2026-07-02) so the merge is
testable. Scar, same date: hook dedup keyed on the EXACT command string, so
when the template changed a hook's command form (token-guard `|| true` ->
if-then), the merge kept BOTH and instances ran token-guard twice per tool
call — every counter doubled, the 50-call ceiling behaved as 25. Observed
live in school-negotiator: THREE token-guard commands per event (current
form, prior `|| true` form, and a pre-flattening `q-system/q-system/` fossil).
Stale forms could never be retired because the raw string never matched.

Dedup now keys on the SCRIPT BASENAMES a command invokes (template groups are
merged first, so the template's current form wins and every stale variant of
the same script drops out). Commands that invoke no recognizable script fall
back to the raw command string. Instance-added hooks for scripts the template
does not know keep surviving updates (the original reason this merge exists).

Usage: kipi-settings-merge.py <template.json> <instance-settings.json>
Writes the merged result back to <instance-settings.json>.
"""
import json
import os
import re
import sys

# A "script" is any .py/.sh path in the command, read with the directory in front
# of it so ownership can be told (see hook_script_names).
SCRIPT_PATH_RE = re.compile(r"((?:[^\s;|&()]*/)*)([A-Za-z0-9_\-]+\.(?:py|sh))")
_PROJECT_VARS = ("${CLAUDE_PROJECT_DIR}/", "$CLAUDE_PROJECT_DIR/")


def _script_identity(prefix, name):
    """Basename for a skeleton script, "path:<rel>" for an instance-owned one.

    Instance-owned means PROVABLY project-relative (after $CLAUDE_PROJECT_DIR/,
    or a bare relative path) with a leading component other than q-system.
    Everything else keeps the old basename identity, so a spelling this cannot
    read fails toward dedup, the direction the token-guard scar was about.
    """
    full = prefix + name
    rel = None
    for var in _PROJECT_VARS:
        at = full.rfind(var)
        if at != -1:
            rel = full[at + len(var):]
            break
    if rel is None:
        rel = full[2:] if full.startswith("./") else full
        if "/" not in rel or rel.startswith(("/", "~", "$")):
            return name
    rel = os.path.normpath(rel).lower()
    if rel.startswith("..") or rel.split("/", 1)[0] == "q-system":
        return name
    return "path:" + rel


def hook_script_names(command):
    """Script identities a command invokes.

    A script under the q-system/ subtree is the skeleton's, and is identified by
    basename so every path layout of it dedupes (the token-guard fossil scar in
    the module docstring). Every template hook lives there (measured 2026-11-06).
    An instance's own script is identified by its path: keyed by basename alone,
    an instance's q-inst/token-guard.py was deduped against the template's
    token-guard, and an instance script that shared a retired name was retired
    with it (codex review of kipi-system PR #615, ASK-3685). apply-claude-changes
    lets an instance wire its own hooks on the premise that this merge keeps
    them; this is what makes that true.

    Ownership is the LEADING path component, read after shell quotes are
    removed. Codex round 2 broke both shortcuts: a substring test made
    q-inst/not-q-system/x.py skeleton-owned, and a quote between directory and
    name ("$D/q-system/.q-system"/token-guard.py) hid the prefix so a template
    script read as an instance one and ran twice.
    """
    unquoted = command.replace('"', "").replace("'", "")
    return frozenset(_script_identity(prefix, name)
                     for prefix, name in SCRIPT_PATH_RE.findall(unquoted))


def _only_retired(command, retired):
    """True only when EVERY script the command invokes is retired. A chained
    command (live guard && retired script) must survive: dropping it would
    silently unwire the live script too (review of #576)."""
    names = hook_script_names(command)
    return bool(names) and names <= retired


def hook_key(command):
    """Identity of a hook command for dedup: the set of script identities it
    invokes (see hook_script_names), or the raw string when none is recognizable."""
    names = hook_script_names(command)
    return names if names else command


RETIRED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "kipi-retired-hooks.json")


def load_retired(path=None):
    """Script basenames whose hooks were retired from the template. Missing
    file means none retired; a present-but-unreadable file raises, because a
    silent empty list would resurrect every dead hook (ASK-3512)."""
    path = path or RETIRED_PATH
    if not os.path.exists(path):
        sys.stderr.write("    WARNING: kipi-retired-hooks.json missing; retired hooks will NOT be dropped\n")
        return frozenset()
    with open(path) as f:
        return frozenset(e["script"] for e in json.load(f).get("scripts", []))


def merge_settings(template, existing, retired=None):
    # Scar ASK-3512: the union below keeps every instance-only hook, so the two
    # hooks #571 removed from the template survived in every instance as inert
    # `test -f` wiring that no check could tell from live wiring. Drop retired
    # scripts from the INSTANCE side only, before the union.
    retired = load_retired() if retired is None else frozenset(retired)
    existing = json.loads(json.dumps(existing))
    for event, groups in existing.get("hooks", {}).items():
        for grp in groups:
            grp["hooks"] = [h for h in grp.get("hooks", [])
                            if not _only_retired(h.get("command", ""), retired)]
        existing["hooks"][event] = [g for g in groups if g.get("hooks")]
    merged = dict(template)

    # Preserve instance MCP servers (all, including disabled _prefixed)
    if "mcpServers" in existing:
        merged["mcpServers"] = dict(template.get("mcpServers", {}))
        for k, v in existing["mcpServers"].items():
            merged["mcpServers"][k] = v

    # Preserve instance-specific enabled plugins (additive merge)
    if "enabledPlugins" in existing:
        merged["enabledPlugins"] = dict(template.get("enabledPlugins", {}))
        merged["enabledPlugins"].update(existing["enabledPlugins"])

    # Preserve instance-specific permission additions (merge allow lists)
    if "permissions" in existing and "allow" in existing["permissions"]:
        template_allow = set(template.get("permissions", {}).get("allow", []))
        instance_allow = set(existing["permissions"]["allow"])
        merged["permissions"]["allow"] = sorted(template_allow | instance_allow)

    # Preserve instance tool configurations (additive merge)
    if "toolConfigurations" in existing:
        merged["toolConfigurations"] = dict(template.get("toolConfigurations", {}))
        merged["toolConfigurations"].update(existing["toolConfigurations"])

    # Preserve instance model override if different from template
    if existing.get("model") and existing.get("model") != template.get("model"):
        merged["model"] = existing["model"]

    # Union template + instance hooks per event+matcher. Template first: for a
    # given script, the template's CURRENT command form wins and the instance's
    # stale variants drop (the double-token-guard scar above). Instance-added
    # hooks for scripts unknown to the template survive.
    if "hooks" in existing or "hooks" in template:
        merged_hooks = {}
        events = set(list(template.get("hooks", {})) + list(existing.get("hooks", {})))
        for event in events:
            groups = (template.get("hooks", {}).get(event, [])
                      + existing.get("hooks", {}).get(event, []))
            by_matcher = {}
            order = []
            for grp in groups:
                m = grp.get("matcher", "")
                if m not in by_matcher:
                    by_matcher[m] = {"matcher": m, "hooks": [], "_seen": set()}
                    order.append(m)
                for h in grp.get("hooks", []):
                    key = hook_key(h.get("command", ""))
                    if key not in by_matcher[m]["_seen"]:
                        by_matcher[m]["_seen"].add(key)
                        by_matcher[m]["hooks"].append(h)
            merged_hooks[event] = [
                {"matcher": by_matcher[m]["matcher"], "hooks": by_matcher[m]["hooks"]}
                if by_matcher[m]["matcher"] else {"hooks": by_matcher[m]["hooks"]}
                for m in order
            ]
        merged["hooks"] = merged_hooks

    return merged


def main(argv):
    if len(argv) != 3:
        sys.stderr.write("usage: kipi-settings-merge.py <template.json> <instance-settings.json>\n")
        return 2
    template = json.load(open(argv[1]))
    existing = json.load(open(argv[2]))
    merged = merge_settings(template, existing)
    with open(argv[2], "w") as f:
        json.dump(merged, f, indent=2)
    print("    settings.json updated (MCP, plugins, permissions, tools, hooks preserved)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
