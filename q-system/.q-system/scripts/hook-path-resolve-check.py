#!/usr/bin/env python3
"""hook-path-resolve-check: which wired hooks are actually reachable, and which
are genuinely dead.

Scar (fleet-sync, 2026-09-20, RCA row T7): five live hooks were declared dead
and acted on. Two separate mistakes produced that verdict, and this tool exists
to make both of them impossible to repeat.

  1. RAW PATH COMPARISON. `/Users/assafkip` is a root-owned symlink to
     `/Users/assafkipnis`. A process that inherited the short spelling hands
     CLAUDE_PROJECT_DIR=/Users/assafkip/... to every hook, so a checker that
     compares the project dir against the hook path as STRINGS sees two
     unrelated prefixes and concludes the hook lives outside the repo. Both
     sides are realpath'd here before anything is compared or tested, and the
     resolved path is printed in the report so the next reader can see which
     file was actually inspected.

  2. EXIT CODE AS THE LIVENESS ORACLE. A guard that refuses by emitting
     `permissionDecision: deny` terminates 0 every single time.
     claude-path-write-guard.py is exactly this shape and it blocks real work
     daily. Reading "never exits non-zero" as "does nothing" retires working
     gates. Enforcement is read from the block SIGNALS in the file, and an
     exit code this tool cannot evaluate statically counts as enforcement,
     never against it.

Classification per (hook command, script path) site:

  LIVE      resolves through symlinks to an existing file, and the file carries
            a blocking signal (exit 2, permissionDecision deny/ask, decision
            block, continue false) OR an exit status this tool cannot evaluate.
  ADDITIVE  resolves, exists, and positively never blocks: no blocking signal
            and no indeterminate exit. Injectors are this by design -- four of
            this repo's UserPromptSubmit hooks are additive-only -- so it is
            REPORTED and never fatal. A gate that goes red on its own
            population gets switched off.
  DEAD      the path does not resolve to an existing file. The one fatal state.
  UNKNOWN   no script path could be extracted from the command. Reported, never
            fatal: a check that cannot see must not report dead. Same posture as
            hook_envelope_audit.py.

Exit 0 when nothing is DEAD, 2 when anything is.

Usage:
    hook-path-resolve-check.py                      # both repo settings files
    hook-path-resolve-check.py <settings.json> ...  # named files
    hook-path-resolve-check.py --json <file> ...    # machine-readable report
    hook-path-resolve-check.py --hook               # PostToolUse, hook JSON on stdin

stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# scripts/ -> .q-system/ -> q-system/ -> repo root
REPO_ROOT = os.path.realpath(os.path.join(SCRIPT_DIR, "..", "..", ".."))

LIVE = "LIVE"
ADDITIVE = "ADDITIVE"
DEAD = "DEAD"
UNKNOWN = "UNKNOWN"

# $CLAUDE_PROJECT_DIR/<rel> and ${CLAUDE_PROJECT_DIR}/<rel>. The trailing class
# stops at shell metacharacters and quotes so a path never swallows the rest of
# a `test -f X && python3 X` command.
#
# `}` is in that stop set because of the integrity-restore hook, which nests the
# reference inside a default-value expansion:
#   N="${KIPI_NOTIFY:-$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/slack-notify.sh}"
# Without it the closing brace rides along on the path, nothing resolves, and a
# live hook is reported DEAD -- the exact verdict this tool was built to stop
# somebody acting on. Caught by the live control in
# test_repo_settings_have_no_dead_hooks, not by a fixture.
PROJECT_DIR_REF = re.compile(
    r"\$(?:CLAUDE_PROJECT_DIR|\{CLAUDE_PROJECT_DIR\})/([^\s\"'`;&|)}]+)"
)

# A bare repo-relative path. The integrity-restore hook carries its two script
# paths as loop values (`for R in q-system/.../a.py q-system/.../b.py`) and
# joins them with $CLAUDE_PROJECT_DIR only later, so the reference regex above
# never sees them. Anchored on the directories this repo actually ships to keep
# arbitrary words out.
BARE_REL = re.compile(
    r"(?<![\w/$.-])((?:q-system|plugins|\.claude|automation)/[\w./-]+\.(?:py|sh))"
)

# Terminating non-zero is one way to block. These are the others, all of which
# ride out on exit 0.
BLOCK_SIGNALS = (
    "permissionDecision",
    '"decision"',
    "'decision'",
    "continue",
    "hookSpecificOutput",
)
# `continue` and `hookSpecificOutput` appear in additive emitters too, so they
# only count alongside an explicit refusal value.
REFUSAL_VALUES = ("deny", "ask", "block", "false")

EXIT_CALL = re.compile(r"(?:sys\.)?exit\(\s*([^)]*?)\s*\)")
EXIT_SHELL = re.compile(r"\bexit\s+([^\s;&|)}]+)")

# An exit argument that provably means success. Everything else -- a literal 2,
# a variable, an expression -- is an exit status this tool cannot evaluate, and
# is counted as enforcement rather than against it.
BENIGN_EXIT = {"", "0", "none"}


def project_dir_for(settings_path: str) -> str:
    """The CLAUDE_PROJECT_DIR a hook in this settings file would be handed.

    Realpath'd here, once, so nothing downstream ever compares a symlinked
    spelling against a resolved one. The env var wins when set because that is
    what the runtime actually exports; derivation from the file's location is
    the fallback for a CLI run against an arbitrary file.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return os.path.realpath(env)
    d = os.path.dirname(os.path.abspath(settings_path))
    if os.path.basename(d) == ".claude":
        d = os.path.dirname(d)
    return os.path.realpath(d)


def extract_paths(command: str) -> list[str]:
    """Repo-relative script paths named by one hook command, in order, deduped."""
    found: list[str] = []
    for rel in PROJECT_DIR_REF.findall(command):
        # `$CLAUDE_PROJECT_DIR/$R` -- the path is a variable this tool cannot
        # expand. Dropping it here is correct: the BARE_REL pass below picks the
        # loop's literal values up instead.
        if "$" in rel:
            continue
        if rel not in found:
            found.append(rel)
    for rel in BARE_REL.findall(command):
        if rel not in found:
            found.append(rel)
    return found


def classify_body(text: str) -> str:
    """LIVE or ADDITIVE for a file that exists. Never DEAD -- existence is
    decided by the filesystem, not by reading the file."""
    for match in EXIT_CALL.finditer(text):
        if match.group(1).strip().strip("\"'").lower() not in BENIGN_EXIT:
            return LIVE
    for match in EXIT_SHELL.finditer(text):
        if match.group(1).strip().strip("\"'").lower() not in BENIGN_EXIT:
            return LIVE
    lowered = text.lower()
    for signal in BLOCK_SIGNALS:
        idx = 0
        needle = signal.lower()
        while True:
            idx = lowered.find(needle, idx)
            if idx < 0:
                break
            # A refusal value within the same emitted object. The window is
            # generous on purpose: a pretty-printed envelope puts the key and
            # its value several lines apart, and a false LIVE is the safe error
            # here while a false ADDITIVE is the one that retires a gate.
            window = lowered[idx: idx + 400]
            if any(v in window for v in REFUSAL_VALUES):
                return LIVE
            idx += len(needle)
    return ADDITIVE


def check_site(project_dir: str, rel: str) -> dict:
    """Resolve one referenced path and classify it."""
    candidate = os.path.join(project_dir, rel)
    resolved = os.path.realpath(candidate)
    site = {"script": rel, "candidate": candidate, "resolved": resolved}
    # isfile() on the realpath, so a symlink chain whose target was deleted is
    # DEAD and the fix for the symlink incident does not become "assume it is
    # there".
    if not os.path.isfile(resolved):
        site["status"] = DEAD
        return site
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        # Present but unreadable is not dead, and this tool will not guess.
        site["status"] = UNKNOWN
        site["note"] = f"unreadable: {exc}"
        return site
    site["status"] = classify_body(text)
    return site


def scan(settings_path: str) -> list[dict]:
    """Every hook command in one settings file, classified."""
    with open(settings_path, "r", encoding="utf-8") as fh:
        settings = json.load(fh)
    project_dir = project_dir_for(settings_path)
    sites: list[dict] = []
    hooks = settings.get("hooks") or {}
    for event, groups in hooks.items():
        for group in groups or []:
            matcher = group.get("matcher", "")
            for entry in group.get("hooks") or []:
                command = entry.get("command", "")
                base = {
                    "settings": settings_path,
                    "event": event,
                    "matcher": matcher,
                    "command": command,
                }
                rels = extract_paths(command)
                if not rels:
                    sites.append({**base, "script": "", "candidate": "",
                                  "resolved": "", "status": UNKNOWN,
                                  "note": "no script path in command"})
                    continue
                for rel in rels:
                    sites.append({**base, **check_site(project_dir, rel)})
    return sites


def default_targets() -> list[str]:
    out = []
    for rel in (os.path.join(".claude", "settings.json"), "settings-template.json"):
        path = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(path):
            out.append(path)
    return out


def report_for(paths: list[str]) -> dict:
    sites: list[dict] = []
    for path in paths:
        sites.extend(scan(path))
    counts = {s: 0 for s in (LIVE, ADDITIVE, DEAD, UNKNOWN)}
    for site in sites:
        counts[site["status"]] += 1
    return {
        "files": paths,
        "sites": sites,
        "live": counts[LIVE],
        "additive": counts[ADDITIVE],
        "dead": counts[DEAD],
        "unknown": counts[UNKNOWN],
    }


def print_human(report: dict) -> None:
    for site in report["sites"]:
        if site["status"] == LIVE:
            continue
        label = site["script"] or site["command"][:60]
        print(f"{site['status']:9} {site['event']:16} {label}")
        if site["status"] == DEAD:
            print(f"{'':9} wired at : {site['candidate']}")
            print(f"{'':9} resolved : {site['resolved']}  (no such file)")
    print(
        f"\n{len(report['sites'])} hook sites: {report['live']} live, "
        f"{report['additive']} additive, {report['unknown']} unknown, "
        f"{report['dead']} dead"
    )
    if report["dead"]:
        print(
            "\nDEAD means the path does not resolve to a file. Before deleting "
            "the wiring, confirm the resolved path above is the one you expect: "
            "a symlinked project dir is what produced five false deads on "
            "2026-09-20.",
            file=sys.stderr,
        )


def hook_mode() -> int:
    """PostToolUse. Self-scope to edits of a settings file and stay silent
    otherwise -- running this on every Edit is token spend for nothing."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    edited = (payload.get("tool_input") or {}).get("file_path") or ""
    base = os.path.basename(edited)
    if base not in ("settings.json", "settings-template.json"):
        return 0
    targets = default_targets()
    if not targets:
        return 0
    try:
        report = report_for(targets)
    except (OSError, json.JSONDecodeError):
        # A half-written settings file mid-edit is not a dead hook.
        return 0
    if not report["dead"]:
        return 0
    lines = [
        f"BLOCKED by hook-path-resolve-check: {report['dead']} wired hook "
        f"path(s) resolve to nothing."
    ]
    for site in report["sites"]:
        if site["status"] == DEAD:
            lines.append(f"  {site['event']}: {site['script']}")
            lines.append(f"    resolved to {site['resolved']} (no such file)")
    lines.append(
        "Either restore the script or remove the wiring. If the path looks "
        "correct, check whether the project dir came in through a symlink "
        "before assuming the hook is dead (scar 2026-09-20)."
    )
    print("\n".join(lines), file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="settings JSON files to scan")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument("--hook", action="store_true", help="PostToolUse mode")
    args = parser.parse_args(argv)

    if args.hook:
        return hook_mode()

    targets = [os.path.abspath(p) for p in args.paths] or default_targets()
    if not targets:
        print("no settings file to scan", file=sys.stderr)
        return 2
    report = report_for(targets)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 2 if report["dead"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
