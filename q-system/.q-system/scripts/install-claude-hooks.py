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

  1. RATCHET. A source that reduces the installed hook's `emit_deny` or `exit 2`
     call sites is REFUSED. A hook may be repaired, never disarmed. Counted, not
     parsed: a count cannot tell a real deny from a weakened one, and coarse is
     the right trade for a guard whose failure mode is a silently disabled gate.
     Narrowing a deny's CONDITION while keeping its call site is NOT caught here.
     Say that plainly rather than implying more coverage than exists.
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

`--check` is the read-only half and is what a gate should call: it reports drift
and exits 1 without writing anything.
"""

import argparse
import filecmp
import os
import shutil
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SOURCE_DIR = os.path.join(REPO, "q-system", ".q-system", "hooks")

# A hook may be repaired, never disarmed. These are the tokens that make a hook
# a gate rather than a comment.
TEETH = ("emit_deny", "exit 2")


def code_only(text):
    """Drop comment bodies before counting teeth.

    THE HOLE THIS CLOSES (PR #279 round 4, blocker). The ratchet counted these
    tokens as raw text over the whole file, so a source that deletes every real
    `emit_deny` call and pads the comments with the word `emit_deny` keeps the
    count identical and installs a gutted hook with every check green. A guard
    whose bypass is typing a word in a comment is not a guard.

    Line-oriented and deliberately crude: a `#` inside a shell string is treated
    as a comment start, so a real call after one on the same line is not
    counted. That direction is SAFE -- undercounting the source can only make
    the ratchet refuse an install, never wave one through. The opposite mistake
    is the one that costs a machine.
    """
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


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


def refuse_if_weaker(name, source_text, installed_text):
    """The ratchet. Returns a refusal string, or None."""
    if installed_text is None:
        return None  # nothing installed yet; there are no teeth to lose
    if installed_text.startswith("#!") and not source_text.startswith("#!"):
        return "%s: the source drops the shebang" % name
    installed_code, source_code = code_only(installed_text), code_only(source_text)
    for token in TEETH:
        was, now = installed_code.count(token), source_code.count(token)
        if now < was:
            return ("%s: the source reduces `%s` call sites (%d -> %d). A hook "
                    "may be repaired, never disarmed." % (name, token, was, now))
    return None


def install_one(name, dest_dir, dry_run):
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

    if installed_text == source_text and os.path.exists(dst) and os.access(dst, os.X_OK):
        return "%s: already installed and executable" % name, False

    if dry_run:
        reason = "not installed" if installed_text is None else "differs"
        return "%s: WOULD INSTALL (%s)" % (name, reason), True

    os.makedirs(dest_dir, exist_ok=True)
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
    return "%s: installed, parses, verified executable" % name, True


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
        for line in drift:
            print("  " + line)
        if drift:
            print("\nrun: python3 %s" % os.path.relpath(__file__, REPO))
            return 1
        print("all %d vendored hook(s) match the installed copy" % len(names))
        return 0

    failed = False
    for name in names:
        line, _ = install_one(name, dest_dir, args.dry_run)
        print("  " + line)
        if line.startswith("REFUSED") or "FAILED" in line:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
