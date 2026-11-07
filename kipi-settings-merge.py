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
# of it so ownership can be told (see hook_script_names). Dots are part of the
# file name: without them custom.memory_autocapture.py read as the retired
# memory_autocapture.py and an instance hook was dropped (codex round 4, #615).
SCRIPT_PATH_RE = re.compile(r"((?:[^\s;|&()]*/)*)([A-Za-z0-9_.\-]+\.(?:py|sh))")
# The one spelling that earns path identity: the anchor, then plain path
# characters only, so no variable, glob, brace, tilde or escape can sit in it.
_ANCHORED_RE = re.compile(
    r"(?:\$CLAUDE_PROJECT_DIR|\$\{CLAUDE_PROJECT_DIR\})/([A-Za-z0-9._/\-]+)")
# A plain READ of the anchor. Any other mention (an assignment, an export,
# ${CLAUDE_PROJECT_DIR:=x}) can repoint every anchored path after it.
_ANCHOR_READ_RE = re.compile(
    r"\$\{CLAUDE_PROJECT_DIR\}|\$CLAUDE_PROJECT_DIR(?![A-Za-z0-9_])")
# Builtins that run text as code in this shell, which can repoint the anchor out
# of the merge's sight. Not cd, pushd or popd: an anchored path is absolute, so
# the working directory cannot change what it names, and refusing them only
# deleted real instance hooks (fleet review 2 on PR #615).
_STATE_WORDS = frozenset(("source", ".", "eval"))
# What separates one simple command from the next, and what may stand in front
# of a command's NAME: the POSIX command prefix (assignments, redirections),
# the reserved words that open a compound command, and the two wrappers that
# run a builtin by name.
_SIMPLE_COMMAND_SPLIT_RE = re.compile(r"[;&|(){}`\n]+")
_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_REDIRECT_RE = re.compile(r"[0-9]*[<>]+")
_BEFORE_NAME = frozenset(("if", "then", "else", "elif", "do", "while", "until",
                          "!", "time", "builtin", "command"))
# The shell removes these before a path reaches the file system, so they are
# removed before the path is read.
_SHELL_QUOTING = str.maketrans("", "", "\"'\\")


def _command_names(unquoted):
    """The NAME of each simple command: its first word after the prefix.

    Codex round 4 on PR #615: a position-blind word check read the `.` in
    `python3 "$CLAUDE_PROJECT_DIR/q-inst/x.py" .` as the source builtin, so a
    canonical instance hook lost its identity and was deduped away. A builtin
    only acts when it is the command name; as an argument it is data.
    """
    for part in _SIMPLE_COMMAND_SPLIT_RE.split(unquoted):
        words = iter(part.split())
        for word in words:
            if _REDIRECT_RE.fullmatch(word):
                next(words, None)  # a bare operator: its target is the next word
            elif not (word in _BEFORE_NAME or _ASSIGNMENT_RE.match(word)
                      or _REDIRECT_RE.match(word)):
                yield word
                break


def _plain_command(unquoted):
    """True when nothing in the command can change what an anchored path means.

    Only the anchor matters, because only an anchored path earns path identity.
    It can be repointed by a write to CLAUDE_PROJECT_DIR in the command, or by
    code the merge cannot read (a sourced file, an eval). A command that does
    either gets no path identity at all. Codex round 3's `cd` input needed no
    rule here: its path was relative, and relative paths no longer earn path
    identity.
    """
    if _STATE_WORDS & set(_command_names(unquoted)):
        return False
    return "CLAUDE_PROJECT_DIR" not in _ANCHOR_READ_RE.sub("", unquoted)


def _script_identity(prefix, name, plain):
    """Basename for a skeleton script, "path:<rel>" for an instance-owned one.

    Instance-owned means the canonical spelling (see hook_script_names) with a
    leading component other than q-system. Everything else keeps the old
    basename identity, because the other failure, a skeleton script read as an
    instance one, runs that script twice: the token-guard scar. The cost of the
    trade is that a non-canonical instance hook is deduped against a template
    script of the same name. That drop is reported, never silent, and the
    retired-hook drop no longer follows from basename identity alone
    (_skeleton_path, ASK-3876).
    """
    hit = _ANCHORED_RE.fullmatch(prefix + name) if plain else None
    if hit is None:
        return name
    rel = os.path.normpath(hit.group(1)).lower()
    if rel.startswith(("/", "..")) or rel.split("/", 1)[0] == "q-system":
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

    Path identity is granted to ONE spelling, the one all 17 live
    path-identity hooks across 14 instances use (measured 2026-11-06): a token
    that starts with $CLAUDE_PROJECT_DIR/ or ${CLAUDE_PROJECT_DIR}/ and goes on
    in plain path characters, in a command that cannot change what that anchor
    means (_plain_command). Ownership is then the LEADING path component, read
    after shell quoting is removed. Scar: three Codex rounds on PR #615 each
    found a spelling that broke the fix before it (a substring test, a quote
    between directory and name, a `cd` before a relative path), because the
    parser tried to READ every spelling. It now accepts one and refuses the
    rest (RCA rca-settings-merge-identity-three-rounds-2026-11-06). Limit: this
    reads text, not the disk, so an instance directory that is a symlink into
    q-system/ is not seen.
    """
    return frozenset(identity for identity, _ in _script_refs(command))


# Any spelling of the anchor, read loosely on purpose: this only decides whether
# a path is the skeleton's, and a loose read can only say "yes" for a path that
# then leads with q-system/.
_ANCHOR_SPLIT_RE = re.compile(r"(?:\$CLAUDE_PROJECT_DIR|\$\{CLAUDE_PROJECT_DIR\})/")


def _skeleton_path(prefix, name):
    """True when the path, read after its last anchor, leads with q-system/.

    The evidence a basename-keyed hook must show before the retired-hook drop
    may delete it. Scar ASK-3876 (fleet reviewer, PR #615 round 1): the drop
    keyed on the basename alone, so `eval true && python3
    "$CLAUDE_PROJECT_DIR/automation/memory_autocapture.py"`, an instance's own
    script outside the canonical grammar, was deleted as the retired skeleton
    script, before the union and whatever its event, with nothing printed.
    q-system/ is the skeleton's subtree by fleet rule (instance-automation-guard
    refuses an instance script there), and every template spelling of a retired
    script ever shipped leads with it (git log -S over settings-template.json,
    2026-11-06), so real fossils still drop.
    """
    rel = os.path.normpath(_ANCHOR_SPLIT_RE.split(prefix + name)[-1])
    return rel.split("/", 1)[0] == "q-system"


def _script_refs(command):
    """(identity, is-the-skeleton's) for each script the command invokes."""
    unquoted = command.translate(_SHELL_QUOTING)
    plain = _plain_command(unquoted)
    return [(_script_identity(prefix, name, plain), _skeleton_path(prefix, name))
            for prefix, name in SCRIPT_PATH_RE.findall(unquoted)]


def _shows_skeleton(command):
    """True when the command invokes scripts and every one is under q-system/."""
    refs = _script_refs(command)
    return bool(refs) and all(skeleton for _, skeleton in refs)


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


def load_retired(path=None, report=None):
    """Script basenames whose hooks were retired from the template. Missing
    file means none retired; a present-but-unreadable file raises, because a
    silent empty list would resurrect every dead hook (ASK-3512)."""
    path = path or RETIRED_PATH
    if not os.path.exists(path):
        # Into the report, not stderr: kipi-update.sh runs this script with
        # 2>/dev/null, so a stderr warning reached nobody.
        (report if report is not None else []).append(
            "    WARNING: kipi-retired-hooks.json missing; retired hooks will NOT be dropped")
        return frozenset()
    with open(path) as f:
        return frozenset(e["script"] for e in json.load(f).get("scripts", []))


def merge_settings(template, existing, retired=None, report=None):
    """The merged settings. Every instance hook it drops or keeps against the
    rules is appended to `report` as one line (main prints them on stdout)."""
    report = [] if report is None else report
    # Scar ASK-3512: the union below keeps every instance-only hook, so the two
    # hooks #571 removed from the template survived in every instance as inert
    # `test -f` wiring that no check could tell from live wiring. Drop retired
    # scripts from the INSTANCE side only, before the union, and only when the
    # path shows the script is the skeleton's (ASK-3876, _skeleton_path).
    retired = load_retired(report=report) if retired is None else frozenset(retired)
    existing = json.loads(json.dumps(existing))
    for event, groups in existing.get("hooks", {}).items():
        for grp in groups:
            live = []
            for h in grp.get("hooks", []):
                command = h.get("command", "")
                if not _only_retired(command, retired):
                    live.append(h)
                elif not _shows_skeleton(command):
                    live.append(h)
                    report.append("    KEPT [%s] retired script name, path not under q-system/: %s"
                                  % (event, command))
            grp["hooks"] = live
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
            groups = ([(False, g) for g in template.get("hooks", {}).get(event, [])]
                      + [(True, g) for g in existing.get("hooks", {}).get(event, [])])
            by_matcher = {}
            order = []
            for from_instance, grp in groups:
                m = grp.get("matcher", "")
                if m not in by_matcher:
                    by_matcher[m] = {"matcher": m, "hooks": [], "_seen": set()}
                    order.append(m)
                for h in grp.get("hooks", []):
                    command = h.get("command", "")
                    key = hook_key(command)
                    if key not in by_matcher[m]["_seen"]:
                        by_matcher[m]["_seen"].add(key)
                        by_matcher[m]["hooks"].append(h)
                    elif (from_instance and not isinstance(key, str)
                          and not _shows_skeleton(command)):
                        # A fossil of a template hook drops quietly: that is the
                        # token-guard fix. A spelling that does not show it is
                        # the skeleton's may be the instance's own script, so
                        # its drop is named (ASK-3876).
                        report.append("    DROPPED [%s %s] same script name as an earlier hook, "
                                      "path not under q-system/: %s" % (event, m or "*", command))
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
    report = []
    merged = merge_settings(template, existing, report=report)
    with open(argv[2], "w") as f:
        json.dump(merged, f, indent=2)
    # stdout, not stderr: kipi-update.sh discards this script's stderr, so a
    # line there is a silent drop by another name.
    for line in report:
        print(line)
    print("    settings.json updated (MCP, plugins, permissions, tools, hooks preserved)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
