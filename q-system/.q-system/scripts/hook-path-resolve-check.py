#!/usr/bin/env python3
"""hook-path-resolve-check: which wired hooks are actually reachable, and which
are genuinely dead.

Scar (fleet-sync, 2026-09-20, RCA row T7): five live hooks were declared dead
and acted on. Two separate mistakes produced that verdict, and this tool exists
to make both of them impossible to repeat.

  1. RAW PATH COMPARISON. The home directory is reachable under two spellings:
     a root-owned symlink whose name is a prefix of the real account name,
     pointing at the real one. A process that inherited the short spelling
     hands a CLAUDE_PROJECT_DIR rooted under that symlink to every hook, so a
     checker that compares the project dir against the hook path as STRINGS
     sees two unrelated prefixes and concludes the hook lives outside the
     repo. The absolute paths are deliberately not written here: this file
     ships to every instance and to a public repo, and the push tripwire
     blocks a home path in the skeleton (PR #374 round 6). Both
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
  DEAD      a SCRIPT path (.py/.sh) that does not resolve to an existing file.
            The one fatal state.
  UNKNOWN   this tool cannot judge the reference. Three ways in: no path could
            be extracted from the command at all; the path resolves to a
            directory rather than a script; the path is not script-shaped and
            nothing is there. Reported, never fatal: a check that cannot see
            must not report dead. Same posture as hook_envelope_audit.py.

A third false-DEAD source, found after the two above and fixed the same way:
NOT EVERY REFERENCE IS A SCRIPT. `cd "$CLAUDE_PROJECT_DIR/q-consult"` is a live
SessionStart hook in the consulting instance, and os.path.isfile() on a
directory is False, so the reference read DEAD and this tool advised removing
working wiring -- the exact verdict it exists to stop. BARE_REL was already
anchored on .py/.sh; PROJECT_DIR_REF was not, so the two extractors disagreed
about what counts as a judgeable path. They agree now: anything that is not a
resolvable script is UNKNOWN, never DEAD. A missing extensionless path (the
`kipi` CLI, say) is therefore reported and not flagged, which is the deliberate
direction: a false UNKNOWN costs a reader one look, a false DEAD costs a live
gate.

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
import io
import json
import os
import re
import sys
import tokenize

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

# The suffixes BARE_REL already requires. check_site applies the same test to
# references pulled out by PROJECT_DIR_REF, which matches any path shape.
SCRIPT_EXT = (".py", ".sh")

# Terminating non-zero is one way to block. These are the others, all of which
# ride out on exit 0.
#
# `continue` is QUOTED here for the same reason `decision` already is: in a hook
# envelope it is always a JSON key, and bare it is a loop keyword. Unquoted, a
# Python `continue` statement with the token `False` anywhere in the next 400
# characters -- ordinary code, no envelope in sight -- read as a refusal and
# promoted a pure injector to LIVE (codex, PR #409 round 8).
BLOCK_SIGNALS = (
    "permissionDecision",
    '"decision"',
    "'decision'",
    '"continue"',
    "'continue'",
    "hookSpecificOutput",
)
# `continue` and `hookSpecificOutput` appear in additive emitters too, so they
# only count alongside an explicit refusal value. Word-bounded so `false` does
# not match inside `false_positives` and `block` does not match inside
# `blocklist`; the VALUE is what has to be there, not a substring of a name.
REFUSAL_VALUE_RE = re.compile(r"\b(?:deny|ask|block|false)\b")

# `SystemExit` is spelled out because the alternation is case-sensitive and the
# `Exit(` inside it would otherwise be missed. prompt-only-enforcement-guard.py
# ends on `raise SystemExit(main(sys.argv[1:]))` and returns 2 on a block, so it
# is a real gate whose only exit this pattern could not see. HEAD called it LIVE
# by accident -- a bare `continue` happened to sit near the word "block" -- and
# narrowing that accident away is what exposed the gap (codex, PR #409 round 8).
EXIT_CALL = re.compile(r"(?:(?:sys\.)?exit|SystemExit)\(\s*([^)]*?)\s*\)")
EXIT_SHELL = re.compile(r"\bexit\s+([^\s;&|)}]+)")

# An exit argument that provably means success. Everything else -- a literal 2,
# a variable, an expression -- is an exit status this tool cannot evaluate, and
# is counted as enforcement rather than against it.
BENIGN_EXIT = {"", "0", "none"}


def project_dir_for(settings_path: str) -> str:
    """The CLAUDE_PROJECT_DIR a hook wired in THIS settings file would be handed.

    Derived from the file's own location, never from $CLAUDE_PROJECT_DIR. An
    earlier draft preferred the env var "because that is what the runtime
    exports", and that preference is wrong in both directions:

      - When the named file IS this session's repo, the env var and the
        derivation realpath to the same directory, so the env var adds nothing.
      - When it is not -- the documented CLI form
        `hook-path-resolve-check.py <other-repo>/.claude/settings.json`, run
        from inside any Claude session -- the env var points at the SESSION's
        repo, every hook in the named file resolves under a root it does not
        live in, and the tool reports live hooks DEAD. That is the exact verdict
        this file exists to stop somebody acting on (codex, PR #409 rounds 4, 6
        and 8: the same finding three times, so the fix is structural rather
        than another special case).

    Realpath'd here, once, so nothing downstream ever compares a symlinked
    spelling against a resolved one. This is the call that turns the short
    home-directory spelling into the real one before any path is joined to it.
    """
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


def _looks_python(path: str, text: str) -> bool:
    if path.endswith(".py"):
        return True
    first = text.split("\n", 1)[0]
    return first.startswith("#!") and "python" in first


def _blank(lines: list[str], start: tuple[int, int], end: tuple[int, int]) -> None:
    """Overwrite one token's source span with spaces, in place.

    Blanking rather than deleting keeps every other row and column where it
    was, so nothing downstream has to care that the text was rewritten.
    """
    (row1, col1), (row2, col2) = start, end
    for row in range(row1, row2 + 1):
        idx = row - 1
        if idx >= len(lines):
            break
        line = lines[idx]
        a = min(col1 if row == row1 else 0, len(line))
        b = min(col2 if row == row2 else len(line), len(line))
        lines[idx] = line[:a] + " " * (b - a) + line[b:]


def _strip_python(text: str) -> str | None:
    """Python source minus comments and docstrings, or None if it will not
    tokenize.

    Only a STRING standing alone as a statement is dropped. A string INSIDE an
    expression is left alone on purpose: `"permissionDecision": "deny"` is the
    refusal itself, and removing it is the one error that costs a gate.
    """
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None
    lines = text.split("\n")
    # Start of file counts as start of a statement, so a module docstring is
    # recognised. NL and COMMENT are transparent: a shebang line must not stop
    # the docstring below it from being seen as one.
    starts_statement = True
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            _blank(lines, tok.start, tok.end)
            continue
        if tok.type == tokenize.NL:
            continue
        if tok.type == tokenize.STRING and starts_statement:
            _blank(lines, tok.start, tok.end)
            continue
        starts_statement = tok.type in (
            tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
        )
    return "\n".join(lines)


def strip_prose(text: str, path: str = "") -> str:
    """Source with the prose removed, so a sentence DESCRIBING a hook is never
    read as the hook's behaviour.

    Scar (codex P2, PR #409): `q-system/hooks/lessons-index.py` documents itself
    as "any error -> emit nothing, exit 0." and terminates through
    `sys.exit(0)` on every branch. Scanning raw source, EXIT_SHELL captured the
    sentence-final `0.`, which is not a benign exit argument, and a pure
    injector was reported LIVE.

    Conservative in ONE direction, deliberately. A false LIVE overstates how
    much of a settings file is a gate; a false ADDITIVE retires a working one.
    So every failure path returns the text with LESS removed rather than more,
    and the worst case is the old behaviour instead of a swallowed refusal.
    """
    if _looks_python(path, text):
        stripped = _strip_python(text)
        if stripped is not None:
            return stripped
    # Not Python, or it would not tokenize. A line whose first non-space
    # character is `#` is a whole-line comment in both shell and Python, so
    # blanking it cannot remove code. Trailing comments are left alone: finding
    # those in shell needs quote and heredoc tracking this tool does not do, and
    # leaving them in errs toward LIVE, which is the safe side.
    return "\n".join(
        "" if line.lstrip().startswith("#") else line
        for line in text.split("\n")
    )


def classify_body(text: str, path: str = "") -> str:
    """LIVE or ADDITIVE for a file that exists. Never DEAD -- existence is
    decided by the filesystem, not by reading the file."""
    # One chokepoint. Every signal below reads the stripped body, so a refusal
    # quoted in a docstring and an exit code named in a comment are treated the
    # same way: as documentation, not as behaviour.
    text = strip_prose(text, path)
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
            if REFUSAL_VALUE_RE.search(window):
                return LIVE
            idx += len(needle)
    return ADDITIVE


def check_site(project_dir: str, rel: str) -> dict:
    """Resolve one referenced path and classify it."""
    candidate = os.path.join(project_dir, rel)
    resolved = os.path.realpath(candidate)
    site = {"script": rel, "candidate": candidate, "resolved": resolved}
    # A reference to a directory. `cd "$CLAUDE_PROJECT_DIR/q-consult"` is the
    # live case; isfile() says False and the old code called that DEAD.
    if os.path.isdir(resolved):
        site["status"] = UNKNOWN
        site["note"] = "resolves to a directory, not a script"
        return site
    # isfile() on the realpath, so a symlink chain whose target was deleted is
    # DEAD and the fix for the symlink incident does not become "assume it is
    # there".
    if not os.path.isfile(resolved):
        if rel.endswith(SCRIPT_EXT):
            site["status"] = DEAD
            return site
        # Not script-shaped and not there. It may be a directory this hook
        # creates, an output file, or an extensionless binary; this tool cannot
        # tell which, so it reports and does not condemn.
        site["status"] = UNKNOWN
        site["note"] = "not a script path, and nothing at the resolved location"
        return site
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        # Present but unreadable is not dead, and this tool will not guess.
        site["status"] = UNKNOWN
        site["note"] = f"unreadable: {exc}"
        return site
    site["status"] = classify_body(text, resolved)
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


# The settings files this tool scans when given no path, repo-relative. A tree
# carries a SUBSET of these, never necessarily both: kipi-new-instance.sh copies
# settings-template.json INTO .claude/settings.json and never ships the template,
# so the skeleton has two and every instance has one. Named here rather than
# inline in default_targets() so the test derives the set from this constant
# instead of restating it (codex, PR #409 round 7).
SETTINGS_CANDIDATES = (os.path.join(".claude", "settings.json"), "settings-template.json")


def default_targets() -> list[str]:
    out = []
    for rel in SETTINGS_CANDIDATES:
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
        if site.get("note"):
            print(f"{'':9} {site['note']}")
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
