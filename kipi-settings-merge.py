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
import fcntl
import json
import os
import re
import sys
import time

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
    """(identity, shows the skeleton) for one script a command invokes.

    Identity is "path:<rel>" for an instance-owned script and the basename for
    everything else. Instance-owned means the canonical spelling (see
    hook_script_names) with a leading component other than q-system. Everything
    else keeps basename identity, because the other failure, a skeleton script
    read as an instance one, runs that script twice: the token-guard scar.

    "Shows the skeleton" is the SAME canonical spelling with q-system as the
    leading component, and it is the only evidence that lets the retired-hook
    drop delete a hook. Scar ASK-3876 (fleet reviewer, PR #615 round 1): that
    drop keyed on the basename alone, so `eval true && python3
    "$CLAUDE_PROJECT_DIR/automation/memory_autocapture.py"`, an instance's own
    script, was deleted as the retired skeleton script, before the union and
    whatever its event, with nothing printed. A first fix read q-system/ off any
    spelling, and Codex round 1 on PR #624 deleted `cd automation && python3
    q-system/memory_autocapture.py` with it: a relative path names whatever the
    working directory says. One grammar decides both directions, as the PR #615
    RCA concluded. Every template spelling of a retired script ever shipped is
    canonical (git log -S over settings-template.json, 2026-11-06), so real
    fossils still drop; any other spelling is kept and reported.
    """
    hit = _ANCHORED_RE.fullmatch(prefix + name) if plain else None
    if hit is None:
        return name, False
    exact = os.path.normpath(hit.group(1))
    # Identity folds case so Q-SYSTEM/ dedupes as q-system/ on macOS, where they
    # are one directory. The evidence that lets a hook be DELETED keeps case:
    # on a case-sensitive file system Q-SYSTEM/ is an instance's own directory
    # (Codex round 2 on PR #624), and no template spelling was ever upper case.
    rel = exact.lower()
    if rel.startswith(("/", "..")):
        return name, False
    if rel.split("/", 1)[0] == "q-system":
        return name, exact.split("/", 1)[0] == "q-system"
    return "path:" + rel, False


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


def _script_refs(command):
    """(identity, shows the skeleton) for each script the command invokes."""
    unquoted = command.translate(_SHELL_QUOTING)
    plain = _plain_command(unquoted)
    return [_script_identity(prefix, name, plain)
            for prefix, name in SCRIPT_PATH_RE.findall(unquoted)]


def _shows_skeleton(command):
    """True when the command invokes scripts and every one shows the skeleton."""
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
    invokes (see hook_script_names), or the raw string when none is recognizable.
    Contract (ASK-4249): an instance PostToolUse gate may carry a SEPARATE entry
    `test -f "$CLAUDE_PROJECT_DIR/<p>" || { echo ...; exit 2; }` beside its own
    hook. What keeps it is the script basename repeated in the echo message,
    which adds a second key element; the braces do not. A guard whose message
    omits the basename keys like the hook and is dropped. Pinned by
    test-settings-merge.sh."""
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
    # canonical path shows the script is the skeleton's (ASK-3876, _script_identity).
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
                    report.append("    KEPT [%s] retired script name, not spelled $CLAUDE_PROJECT_DIR/q-system/...: %s"
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
                    by_matcher[m] = {"matcher": m, "hooks": [], "_seen": set(), "_text": set()}
                    order.append(m)
                for h in grp.get("hooks", []):
                    command = h.get("command", "")
                    key = hook_key(command)
                    if key not in by_matcher[m]["_seen"]:
                        by_matcher[m]["_seen"].add(key)
                        by_matcher[m]["_text"].add(command)
                        by_matcher[m]["hooks"].append(h)
                    elif (from_instance and not isinstance(key, str)
                          and command not in by_matcher[m]["_text"]
                          and not _shows_skeleton(command)):
                        # A fossil of a template hook drops quietly: that is the
                        # token-guard fix. So does an exact copy of a kept hook:
                        # every instance carries the template's for-loop guard
                        # verbatim (measured 2026-11-07, 14 of 14). A different
                        # spelling that does not show it is the skeleton's may be
                        # the instance's own script, so its drop is named
                        # (ASK-3876).
                        report.append("    DROPPED [%s %s] same script name as an earlier hook, "
                                      "not spelled $CLAUDE_PROJECT_DIR/q-system/...: %s" % (event, m or "*", command))
            merged_hooks[event] = [
                {"matcher": by_matcher[m]["matcher"], "hooks": by_matcher[m]["hooks"]}
                if by_matcher[m]["matcher"] else {"hooks": by_matcher[m]["hooks"]}
                for m in order
            ]
        merged["hooks"] = merged_hooks

    return merged


# Measured 2026-11-07: an instance-mode apply in the test fixture holds the lock
# for 0.04s. The bound is for a stuck holder, so an unattended update fails one
# instance instead of hanging the fleet run.
LOCK_WAIT_SECONDS = 30.0


class LockBusy(Exception):
    pass


def hold_apply_lock(settings_path, wait):
    """Flock the directory holding settings_path, as apply does; returns the fd.

    Scar ASK-3880: instance mode made apply_claude_changes.py a second writer of
    an instance's .claude/settings.json. Apply held a lock and the merge took
    none, so an apply landing between the merge's read and its write was erased
    by the merge, while apply had printed "OK applied". The lock spans the READ:
    one that covers only the write still merges from a stale base.

    The DIRECTORY, not apply's .apply.lock file: taking the file meant creating
    it, and that left an untracked q-system/output/ path in every instance that
    does not ignore it (8 of 14, measured 2026-11-07), against the updater's
    clean-tree contract (test-kipi-update-safety.sh). Apply's acquire_lock takes
    this directory lock too; test-apply-claude-changes.sh case 8d holds it
    through apply's own acquire_lock, so the two cannot drift apart.
    """
    path = os.path.dirname(os.path.abspath(settings_path))
    fd = os.open(path, os.O_RDONLY)
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            # Only "someone holds it" waits. Any other flock error is not an
            # apply and reaches main's "cannot lock" line at once.
            if time.monotonic() >= deadline:
                os.close(fd)
                raise LockBusy(path)
            time.sleep(0.1)
        except OSError:
            os.close(fd)
            raise


def main(argv):
    if len(argv) != 3:
        sys.stderr.write("usage: kipi-settings-merge.py <template.json> <instance-settings.json>\n")
        return 2
    wait = float(os.environ.get("KIPI_SETTINGS_MERGE_LOCK_WAIT", LOCK_WAIT_SECONDS))
    # Every line goes to stdout, not stderr: kipi-update.sh discards this
    # script's stderr, so a line there is a silent drop by another name.
    try:
        lock = hold_apply_lock(argv[2], wait)
    except LockBusy as busy:
        print("    settings.json NOT updated: %s locked for over %gs by an apply" % (busy, wait))
        return 1
    except OSError as err:
        print("    settings.json NOT updated: cannot lock its directory: %s" % err)
        return 1
    try:
        template = json.load(open(argv[1]))
        existing = json.load(open(argv[2]))
        report = []
        merged = merge_settings(template, existing, report=report)
        with open(argv[2], "w") as f:
            json.dump(merged, f, indent=2)
    finally:
        os.close(lock)
    for line in report:
        print(line)
    print("    settings.json updated (MCP, plugins, permissions, tools, hooks preserved)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
