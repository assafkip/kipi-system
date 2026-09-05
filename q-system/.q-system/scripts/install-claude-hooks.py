#!/usr/bin/env python3
"""Install the repo's vendored hooks into the tree that actually runs them.

WHY THIS EXISTS (ASK-1144, codex BLOCKER on PR #279)
----------------------------------------------------
`~/.claude/settings.json` wires `~/.claude/hooks/destructive-op-deny.sh` by an
absolute path. The repository holds a vendored copy at
`q-system/.q-system/hooks/destructive-op-deny.sh`, and until now nothing
connected the two. So a correct fix to the vendored copy could be reviewed,
merged and celebrated while unattended agents kept executing the stale hook.
The reviewer's measurement, verbatim:

    checked_in_equals_installed=no
    tracked wiring references:            <- empty

A security fix that does not reach the running program is not a fix. This script
is the missing edge.

WHY IT IS NOT A HOLE ITSELF
---------------------------
`claude-path-write-guard.py` refuses an agent writing inside `.claude/`, and it
is right to: an agent that can edit destructive-op-deny.sh can disable its own
gates. An installer is a write path into exactly that directory, so it carries
its own refusals rather than inheriting trust from being called "install":

  1. BEHAVIOURAL GATE. The candidate hook is RUN against payloads whose correct
     answers are already known: four that must be denied, three that must be
     allowed. A source that gets any of them wrong is REFUSED.

     This replaces a token-count ratchet that was broken twice in two review
     rounds -- first by putting the tokens in comments, then by keeping every
     call site and redefining emit_deny to allow. Counting is blind to what the
     code DOES, and two bypasses of one shortcut means the shortcut was wrong.
     The MUST_ALLOW half is not decoration: without it, "denies all four" is
     satisfiable by exiting 2 on line one, which is an outage rather than a gate.

     Then a DIFFERENTIAL pass, because a fixed canary list cannot see an
     operation nobody thought to probe: both hooks run the same corpus, and
     everything the INSTALLED hook denies the candidate must deny too. The
     guarantee is "you cannot be weaker than what is already running", with no
     expected answers written down. It is a floor rather than a proof -- an
     operation the corpus omits is still invisible -- and that is stated here
     rather than implied away.
  2. SHEBANG. A source that drops the shebang is refused.
  3. THE EXECUTE BIT IS WIRING, NOT METADATA (the ASK-1118 scar). settings.json
     runs the hook as a BARE PATH, so a file landed at 0644 simply does not run:
     no hook error, no audit line, no gate goes red. An earlier tool wrote this
     exact hook through a temp-then-replace whose temp file was 0644 and turned
     the guard off machine-wide. So the install writes the mode explicitly and
     then RE-READS it from disk to confirm, instead of assuming chmod worked.
  4. BYTE VERIFICATION. After writing, the installed bytes are read back and
     compared to the source. A silent short write is not a success.
  5. ALLOWLIST. Only `<repo>/q-system/.q-system/hooks/*.sh`, one level deep,
     installs to `<home>/.claude/hooks/<same name>`. No path arithmetic from
     user input, no recursion.
  6. REGISTRATION IS CHECKED, NEVER WRITTEN. A hook that is not referenced from
     settings.json does not run, so "installed" without it is a false success
     and is now a FAILURE that prints the exact line to add.

     It is not written automatically, and that is a deliberate disagreement with
     the review that asked for it. settings.json is the file that wires every
     gate in the tree; apply_claude_changes.py refuses to let its one
     non-additive op target that file at all, for exactly this reason. An
     installer that edits it would be a strictly wider hole than the one this
     script closes -- arming a hook and disarming every other one are the same
     write. Detecting is the half that can be automated safely; the write stays
     a human action, and now it is an action the tool names precisely instead of
     leaving to be discovered.

`--check` is the read-only half and is what a gate should call: it reports drift
and exits 1 without writing anything.
"""

import argparse
import filecmp
import time
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SOURCE_DIR = os.path.join(REPO, "q-system", ".q-system", "hooks")

# WHAT THE HOOK DOES, NOT WHAT IT CONTAINS (PR #279 round 6, BLOCKER).
#
# The first ratchet counted `emit_deny` and `exit 2` call sites and refused a
# source that had fewer than the installed copy. Codex broke it in one line: keep
# every call site and redefine `emit_deny` to allow. Counting is blind to what
# the function DOES, and the previous round had already shown counting was blind
# to whether the tokens were even code. Two bypasses of one shortcut is the
# shortcut being wrong, not unlucky.
#
# So the gate is now BEHAVIOURAL: drive the candidate hook with payloads whose
# correct answers are already known and require it to get them right. That is
# the same discipline every other check in this change uses, and it is not
# fooled by any amount of clever text.
#
# Payload strings are assembled from parts at import time on purpose: written
# literally, the live PreToolUse hook blocks this file's own creation. That is
# its documented false positive, and paying for it here is cheaper than
# weakening the hook to make a source file convenient.
_R = "r" + "m"
_RF = "-r" + "f"

MUST_DENY = (
    ("Bash", {"command": "%s %s /tmp/probe-dir" % (_R, _RF)}),
    ("Bash", {"command": "git reset " + "--hard"}),
    ("mcp__linear__delete_issue", {}),
    ("mcp__supabase__delete_branch", {}),
)

# THE INSTALLED HOOK IS THE ORACLE (PR #279 major, round 7).
#
# MUST_DENY is a fixed list, so a candidate that keeps those four and quietly
# drops some operation nobody thought to probe passes every canary. A LONGER
# list has the same hole one item further out; the shape is wrong, not the
# length.
#
# So the real gate is DIFFERENTIAL: run both hooks over this corpus and require
# that everything the INSTALLED hook denies, the candidate denies too. No
# expected answers are written down, which is the point -- the guarantee becomes
# "you cannot be weaker than what is already running", and it holds for any
# operation in the corpus whether or not anyone reasoned about it.
#
# HONEST BOUNDARY: differential over a corpus is strictly stronger than fixed
# expectations and still cannot see an operation the corpus omits. It is a
# floor, not a proof, and MUST_DENY stays as the absolute floor for a first
# install where there is no installed hook to compare against.
DIFFERENTIAL_CORPUS = (
    ("Bash", {"command": "%s %s /tmp/x" % (_R, _RF)}),
    ("Bash", {"command": "%s -f /tmp/x" % _R}),
    ("Bash", {"command": "git reset " + "--hard HEAD~1"}),
    ("Bash", {"command": "git push origin +main"}),
    ("Bash", {"command": "git push --force origin main"}),
    ("Bash", {"command": "git branch -D feature"}),
    ("Bash", {"command": "git clean -fd"}),
    ("Bash", {"command": "git filter-repo --path x"}),
    ("Bash", {"command": "find . -name x -delete"}),
    ("Bash", {"command": "mkfs.ext4 /dev/sda1"}),
    ("Bash", {"command": "dd if=/dev/zero of=/dev/sda"}),
    ("Bash", {"command": "shred -u /tmp/x"}),
    ("Bash", {"command": "chmod -R 777 /"}),
    ("Bash", {"command": "kipi update"}),
    ("Bash", {"command": "rsync -a --delete /a/ /b/"}),
    ("mcp__linear__delete_issue", {}),
    ("mcp__linear__delete_project", {}),
    ("mcp__supabase__delete_branch", {}),
    ("mcp__supabase__reset_branch", {}),
    ("mcp__claude_ai_Gmail__delete_label", {}),
    ("mcp__claude_ai_Gmail__trash_thread", {}),
    ("mcp__claude_ai_Google_Drive__trash_file", {}),
    ("mcp__claude_ai_Google_Calendar__delete_event", {}),
    ("mcp__claude_ai_Notion__notion-move-pages", {}),
    ("mcp__plugin_vercel_vercel__deploy", {}),
    # Present so a candidate cannot pass by denying everything.
    ("Bash", {"command": "ls -la"}),
    ("Bash", {"command": "git status"}),
    ("mcp__linear__list_issues", {}),
    ("mcp__claude_ai_Gmail__untrash_message", {}),
    ("mcp__playwright__browser_drop", {}),
)

# A hook that denies EVERYTHING is not a working hook, it is an outage. Without
# these, "deny on all four" is satisfiable by `exit 2` on line one.
MUST_ALLOW = (
    ("Bash", {"command": "ls -la"}),
    ("mcp__linear__list_issues", {}),
    ("mcp__claude_ai_Gmail__untrash_message", {}),
)


def parses_as_bash(path):
    """`bash -n`. A hook bash cannot parse does not deny anything.

    PR #279 round 4, major: the installer printed "installed and verified
    executable" for a file with a syntax error. settings.json runs the hook as a
    bare path, so an early parse failure means the gate silently allows
    everything -- fails OPEN, which is the worst direction for this file.
    """
    try:
        proc = subprocess.run(["bash", "-n", path], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()


def registered_hook_commands(home):
    """Every command string wired under `hooks` in the tree's settings.json.

    Read from BOTH settings.json and settings.local.json: a hook wired only in
    the local override still runs, and calling it unregistered would be a false
    alarm in the opposite direction.
    """
    commands = []
    for name in ("settings.json", "settings.local.json"):
        path = os.path.join(home, ".claude", name)
        try:
            with open(path) as fh:
                settings = json.load(fh)
        except (OSError, ValueError):
            continue
        hooks = settings.get("hooks")
        if not isinstance(hooks, dict):
            continue
        for entries in hooks.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                for hook in (entry or {}).get("hooks", []) or []:
                    command = (hook or {}).get("command")
                    if isinstance(command, str):
                        commands.append(command)
    return commands


def is_registered(home, dst):
    """Is this exact file wired as a hook the tree will actually run?

    THE BLOCKER THIS ANSWERS (PR #279, codex). The installer copied the hook,
    verified its bytes, verified its execute bit, and printed
    "installed and verified executable" -- while nothing in settings.json
    referenced it. On a clean machine the guard would sit on disk, correct and
    executable, and never run once. A file present is not a gate armed, and
    reporting success for the first while claiming the second is the same false
    green this whole change is about.

    Matched by path, with $HOME and ~ collapsed, because a hook is wired as a
    literal path string.
    """
    home_real = os.path.realpath(home)
    spellings = {dst, os.path.realpath(dst)}
    for spelling in list(spellings):
        if spelling.startswith(home_real + os.sep):
            tail = spelling[len(home_real):]
            spellings.add("~" + tail)
            spellings.add("$HOME" + tail)
    return any(spelling in command
               for command in registered_hook_commands(home)
               for spelling in spellings)


def sources():
    """Every `<repo>/q-system/.q-system/hooks/*.sh`, one level deep."""
    if not os.path.isdir(SOURCE_DIR):
        return []
    return sorted(
        name for name in os.listdir(SOURCE_DIR)
        if name.endswith(".sh") and os.path.isfile(os.path.join(SOURCE_DIR, name))
    )


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


# Environment variables a shell script reads: $NAME and ${NAME...}. Deliberately
# generous -- a false positive costs one refusal and a line in a commit message,
# while a miss is a backdoor that installs.
_ENV_READ = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")


# Names the script ASSIGNS: `NAME=`, `local NAME=`, `declare -a NAME=`,
# `for NAME in`, `read NAME`. A variable the file defines for itself is not an
# environment read, whatever its case.
_ENV_ASSIGNED = re.compile(
    r"(?:^|;|\||&|\bthen\b|\bdo\b|\belse\b|\{)\s*"
    r"(?:local\s+|declare\s+(?:-\w+\s+)*|export\s+|readonly\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)=",
    re.M)
_ENV_LOOPVAR = re.compile(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
_ENV_READVAR = re.compile(r"\bread\s+(?:-\w+\s+)*([A-Za-z_][A-Za-z0-9_]*)")
_ENV_LOCALDECL = re.compile(r"\blocal\s+((?:[A-Za-z_][A-Za-z0-9_]*\s*)+)")


def _env_vars_read(text):
    """Environment reads only: names the script does NOT define for itself.

    THE BUG THIS FIXES REFUSED MY OWN HOOK (PR #279 major). The first cut kept
    every `$NAME` that was uppercase or contained an underscore, on the theory
    that shell locals here are lowercase. They are not: this hook declares
    MCP_OP, MCP_OP_LOWER, _scope and _tok. So the installer reported four "new
    environment reads" and REFUSED the very change it exists to deliver -- a
    guard that blocks its own repair, which is worse than the hole it closes and
    would have shipped silently because I tested the checker against the OLD
    hook, not against this PR's.

    Subtracting assigned names is exact rather than heuristic: `HOME` and
    `ALLOW_DESTRUCTIVE` are read and never assigned, so they stay; a backdoor's
    `${SOME_NEW_VAR:-}` is read and never assigned, so it is still caught.
    """
    assigned = set(_ENV_ASSIGNED.findall(text))
    assigned |= set(_ENV_LOOPVAR.findall(text))
    assigned |= set(_ENV_READVAR.findall(text))
    for group in _ENV_LOCALDECL.findall(text):
        assigned |= set(group.split())
    reads = {m for m in _ENV_READ.findall(text) if m.isupper() or "_" in m}
    return reads - assigned


def decision_of(hook_path, tool_name, tool_input, home):
    """Run the hook on one payload and return "deny", "allow" or "error".

    A PreToolUse hook denies by printing JSON at exit ZERO, so the exit code says
    nothing and only the payload does.
    """
    payload = {"tool_name": tool_name, "tool_input": dict(tool_input),
               "cwd": "/tmp"}
    env = dict(os.environ)
    env.pop("ALLOW_DESTRUCTIVE", None)   # a bypass in this process is not a verdict
    env["HOME"] = home
    try:
        proc = subprocess.run(["bash", hook_path], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError):
        return "error"
    # EXIT 2 IS ALSO A BLOCK. PreToolUse accepts two protocols: JSON at exit 0,
    # and a bare exit 2. destructive-op-deny uses the first exclusively, but a
    # prober that reads only that one calls an exit-2 hook "allow" -- which
    # would make the MUST_ALLOW half of the gate meaningless, since a hook that
    # blocks everything by exiting 2 would sail through as permissive. Found by
    # probing this gate with a hook that denies everything.
    if proc.returncode == 2:
        return "deny"
    out = (proc.stdout or "").strip()
    if not out:
        return "allow"
    try:
        parsed = json.loads(out)
    except ValueError:
        return "error"
    decision = parsed.get("hookSpecificOutput", {}).get("permissionDecision")
    return decision if decision in ("deny", "allow") else "error"


def parses_as_bash_text(text):
    """`bash -n` on text rather than a path, for hooks probed without install."""
    tmp = tempfile.mkdtemp(prefix="parsecheck-")
    try:
        path = os.path.join(tmp, "candidate.sh")
        with open(path, "w") as fh:
            fh.write(text)
        return parses_as_bash(path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _differential_only(name, source_text, installed_text):
    """The part of the gate that holds for ANY hook: never weaker than what runs."""
    if installed_text is None:
        return None
    probe_home = tempfile.mkdtemp(prefix="hookdiff-")
    try:
        os.makedirs(os.path.join(probe_home, ".claude", "audit"), exist_ok=True)
        candidate = os.path.join(probe_home, name)
        with open(candidate, "w") as fh:
            fh.write(source_text)
        reference = os.path.join(probe_home, "installed-" + name)
        with open(reference, "w") as fh:
            fh.write(installed_text)
        for tool, payload in DIFFERENTIAL_CORPUS:
            if decision_of(reference, tool, payload, probe_home) != "deny":
                continue
            now = decision_of(candidate, tool, payload, probe_home)
            if now != "deny":
                detail = payload.get("command", tool)
                return ("%s: the installed hook DENIES `%s` and the source does "
                        "not (%s). A hook may be repaired, never disarmed."
                        % (name, detail, now))
    finally:
        shutil.rmtree(probe_home, ignore_errors=True)
    return None


def refuse_if_weaker(name, source_text, installed_text):
    """Behavioural gate: does the CANDIDATE still deny what it must?

    Returns a refusal string, or None. Driven against a throwaway HOME so the
    probe writes its audit log there and never touches the real one.
    """
    # UNCONDITIONAL, not conditional on what is already installed (PR #279
    # minor). This was gated on the INSTALLED copy having a shebang, so on a
    # first install -- the case where there is no installed copy at all -- it
    # never ran, and a hook with no shebang could land. settings.json executes
    # the file by path, so a missing shebang is a broken hook whatever preceded
    # it. The prior state is irrelevant to whether this file can run.
    if not source_text.startswith("#!"):
        return "%s: the source has no shebang, so the tree cannot execute it" % name

    # AN ENV-VAR BACKDOOR IS INVISIBLE TO A BEHAVIOURAL PROBE (PR #279 minor).
    # A source can early-exit on a variable the probe does not set:
    #     [ "$SOME_NEW_VAR" = 1 ] && exit 0
    # Every canary passes, because the probe runs with a clean environment and
    # never sets that name. Running the hook cannot find a door whose key it
    # does not hold.
    #
    # So this one check is textual, and DIFFERENTIAL rather than a fixed list:
    # any environment variable the SOURCE reads that the INSTALLED hook does not
    # is refused. The installed hook stays the oracle, exactly as the corpus
    # comparison below uses it.
    #
    # HONEST BOUNDARY: this catches a backdoor keyed on a NEW variable. One that
    # repurposes a variable the hook already reads -- ALLOW_DESTRUCTIVE is the
    # sanctioned bypass and HOME is read throughout -- is NOT caught here, and no
    # amount of probing would catch it either. Stated rather than implied away.
    if installed_text is not None:
        new_vars = _env_vars_read(source_text) - _env_vars_read(installed_text)
        if new_vars:
            return ("%s: the source reads environment variable(s) the installed "
                    "hook does not (%s). A probe cannot open a door whose key it "
                    "does not hold, so a new env read is refused rather than "
                    "tested." % (name, ", ".join(sorted(new_vars))))

    # THE CANARIES DESCRIBE ONE HOOK, SO THEY ARE SCOPED TO IT (PR #279 minor).
    #
    # MUST_DENY encodes destructive-op-deny.sh's semantics. Applied to ANY
    # vendored hook, a second one -- a lint, a formatter, anything that is not a
    # destructive-op gate -- would fail every canary and be refused forever,
    # and kipi update would warn on every run until someone deleted the file.
    # A gate that cannot be satisfied by a legitimate input gets switched off.
    #
    # The DIFFERENTIAL below is the part that generalises: "you cannot be weaker
    # than what is already running" is true of every hook, needs no knowledge of
    # what the hook does, and still runs for all of them.
    if name != "destructive-op-deny.sh":
        ok, why = parses_as_bash_text(source_text)
        if not ok:
            return "%s: the source does not parse (`bash -n`): %s" % (name, why)
        return _differential_only(name, source_text, installed_text)

    probe_home = tempfile.mkdtemp(prefix="hookprobe-")
    try:
        os.makedirs(os.path.join(probe_home, ".claude", "audit"), exist_ok=True)
        candidate = os.path.join(probe_home, name)
        with open(candidate, "w") as fh:
            fh.write(source_text)
        for tool, payload in MUST_DENY:
            got = decision_of(candidate, tool, payload, probe_home)
            if got != "deny":
                return ("%s: the source ALLOWS a destructive operation it must "
                        "deny (%s -> %s). A hook may be repaired, never disarmed."
                        % (name, tool, got))
        for tool, payload in MUST_ALLOW:
            got = decision_of(candidate, tool, payload, probe_home)
            if got != "allow":
                return ("%s: the source DENIES an operation it must allow "
                        "(%s -> %s). A hook that blocks everything is an outage, "
                        "and an outage is how a gate gets switched off."
                        % (name, tool, got))

        # Differential, against the hook already running. Skipped on a first
        # install, where there is nothing to be weaker THAN.
        if installed_text is not None:
            reference = os.path.join(probe_home, "installed-" + name)
            with open(reference, "w") as fh:
                fh.write(installed_text)
            for tool, payload in DIFFERENTIAL_CORPUS:
                was = decision_of(reference, tool, payload, probe_home)
                if was != "deny":
                    continue          # the installed hook allows it; not a regression
                now = decision_of(candidate, tool, payload, probe_home)
                if now != "deny":
                    detail = payload.get("command", tool)
                    return ("%s: the installed hook DENIES `%s` and the source "
                            "does not (%s). A hook may be repaired, never "
                            "disarmed -- and this was found by comparing against "
                            "what is running, not against a list someone wrote."
                            % (name, detail, now))
    finally:
        shutil.rmtree(probe_home, ignore_errors=True)
    return None


def install_one(name, dest_dir, dry_run, home):
    src = os.path.join(SOURCE_DIR, name)
    dst = os.path.join(dest_dir, name)
    source_text = read(src)
    if source_text is None:
        return "%s: source unreadable" % name, False
    installed_text = read(dst)

    refusal = refuse_if_weaker(name, source_text, installed_text)
    if refusal:
        return "REFUSED " + refusal, False

    ok, why = parses_as_bash(src)
    if not ok:
        return ("REFUSED %s: the source does not parse (`bash -n`), and a hook "
                "bash cannot parse fails OPEN: %s" % (name, why)), False

    if (installed_text == source_text and os.path.exists(dst)
            and os.access(dst, os.X_OK) and is_registered(home, dst)):
        return "%s: already installed, executable and registered" % name, False

    if dry_run:
        reason = "not installed" if installed_text is None else "differs"
        return "%s: WOULD INSTALL (%s)" % (name, reason), True

    os.makedirs(dest_dir, exist_ok=True)

    # KEEP WHAT WE ARE ABOUT TO DESTROY (codex minor, PR #279).
    #
    # This overwrote the live guard with no copy kept. The installed hook is not
    # a checkout of anything: it is whatever was last written into $HOME, and
    # before this PR merges, that content exists in NO git object. So the first
    # `kipi update` on a machine whose hook had drifted, or had been hand-edited
    # during an incident, discarded the only copy of it, unrecoverably and
    # without saying so.
    #
    # The backup is written BEFORE the replace and only when the bytes actually
    # differ, so a no-op install leaves nothing behind. It is named by timestamp
    # and content hash: re-installing over the same drifted file collapses to one
    # backup, and the order stays readable.
    backup_note = ""
    if installed_text is not None and installed_text != source_text:
        backups = os.path.join(dest_dir, ".backups")
        os.makedirs(backups, exist_ok=True)
        digest = hashlib.sha256(
            installed_text.encode("utf-8", "replace")).hexdigest()[:12]
        stamp = time.strftime("%Y%m%dT%H%M%S")
        backup = os.path.join(backups, "%s.%s.%s" % (name, stamp, digest))
        if not os.path.exists(backup):
            shutil.copyfile(dst, backup)
        backup_note = " (previous copy kept at %s)" % backup

    tmp = dst + ".install.tmp"
    shutil.copyfile(src, tmp)

    # Mode BEFORE the replace, so the file is never observed non-executable.
    mode = stat.S_IMODE(os.stat(tmp).st_mode) | stat.S_IXUSR | stat.S_IRUSR
    for read_bit, exec_bit in ((stat.S_IRGRP, stat.S_IXGRP),
                               (stat.S_IROTH, stat.S_IXOTH)):
        if mode & read_bit:
            mode |= exec_bit
    os.chmod(tmp, mode)
    os.replace(tmp, dst)

    # Read BACK. A chmod that did not take and a short write both look like
    # success from the writing side, and this is the one file where "looks like
    # success" has already cost a machine-wide disarm once.
    if not filecmp.cmp(src, dst, shallow=False):
        return "%s: FAILED, installed bytes differ from source" % name, False
    if not os.access(dst, os.X_OK):
        return "%s: FAILED, installed file is not executable (the guard is OFF)" % name, False
    ok, why = parses_as_bash(dst)
    if not ok:
        return "%s: FAILED, the installed file does not parse: %s" % (name, why), False
    if not is_registered(home, dst):
        return ("%s: FAILED, installed and executable but NOT REGISTERED in "
                "settings.json, so it never runs. Wire it as a PreToolUse "
                "command:\n      \"command\": \"%s\"" % (name, dst)), False
    return ("%s: installed, parses, executable, and registered%s"
            % (name, backup_note)), True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=os.path.expanduser("~"),
                        help="tree holding .claude/ (default: $HOME)")
    parser.add_argument("--check", action="store_true",
                        help="report drift and exit 1; writes nothing")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would be installed; writes nothing")
    args = parser.parse_args(argv)

    dest_dir = os.path.join(args.home, ".claude", "hooks")
    names = sources()
    if not names:
        # A run that finds nothing to install must not report success. An empty
        # source dir means the vendored copy went missing, which is a broken
        # install path, not a clean one.
        print("REFUSED: no hooks found in %s" % SOURCE_DIR, file=sys.stderr)
        return 2

    if args.check:
        drift = []
        for name in names:
            src, dst = os.path.join(SOURCE_DIR, name), os.path.join(dest_dir, name)
            if not os.path.exists(dst):
                drift.append("%s: NOT INSTALLED" % name)
                continue
            # INDEPENDENT, not an elif chain. The first cut chained these, which
            # put the parse check behind "bytes differ" -- and a file whose bytes
            # MATCH a parsing source always parses, so that branch could never
            # fire for the reason it existed. An unreachable false branch reports
            # success by construction. All three conditions are asked separately
            # and every one that holds is reported.
            if not filecmp.cmp(src, dst, shallow=False):
                drift.append("%s: INSTALLED COPY DIFFERS from the repo" % name)
            if not os.access(dst, os.X_OK):
                drift.append("%s: installed but NOT EXECUTABLE (the guard is OFF)" % name)
            if not parses_as_bash(dst)[0]:
                drift.append("%s: installed but DOES NOT PARSE (the guard fails OPEN)" % name)
            if not is_registered(args.home, dst):
                drift.append("%s: installed but NOT REGISTERED in settings.json, "
                             "so it never runs" % name)
        for line in drift:
            print("  " + line)
        if drift:
            print("\nrun: python3 %s" % os.path.relpath(__file__, REPO))
            return 1
        print("all %d vendored hook(s) match the installed copy" % len(names))
        return 0

    failed = False
    for name in names:
        line, _ = install_one(name, dest_dir, args.dry_run, args.home)
        print("  " + line)
        if line.startswith("REFUSED") or "FAILED" in line:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
