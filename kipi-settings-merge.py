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
import re
import sys

# A "script" is any .py/.sh path in the command; basenames identify the hook
# across path layouts (flattened vs pre-flattening) and wrapper forms.
SCRIPT_NAME_RE = re.compile(r"([A-Za-z0-9_\-]+\.(?:py|sh))")


def hook_key(command):
    """Identity of a hook command for dedup: the set of script basenames it
    invokes, or the raw string when no script is recognizable."""
    names = frozenset(SCRIPT_NAME_RE.findall(command))
    return names if names else command


def merge_settings(template, existing):
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
