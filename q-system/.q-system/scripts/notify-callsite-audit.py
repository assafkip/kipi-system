#!/usr/bin/env python3
"""Every founder-notification call site must declare a --kind. (ASK-294)

Pairs with: slack-notify.sh (the runtime half) and
test/test-notify-decision-gate.sh (which drives both halves).

WHY A SECOND, STATIC GATE AT ALL. The runtime gate fails OPEN for a caller with
no --kind, on purpose -- kipi update ships slack-notify.sh to instances carrying
producers this repo has never seen, and refusing those would silence an
instance-local alert nobody has migrated. That deliberate hole is exactly wide
enough for a NEW producer in THIS repo to be written bare and go unnoticed,
which is how 11 producers came to violate founder-notifications.md while it was
sitting there being correct. So the hole is closed statically where the code
lives, and left open at runtime where the fleet lives.

WHAT COUNTS AS A CALL SITE -- and why the window is 4 lines, not 1. The four
Python producers build the argv across several lines:

    subprocess.run(["bash", str(NOTIFY_SCRIPT),
                    "--kind", "receipt",
                    message], timeout=20)

so a per-line grep reports every one of them as bare. The check therefore reads
a window after the invocation token. That is a real limit, not a subtlety to
hide: see HONEST BOUNDARY below.

HONEST BOUNDARY (what this does NOT catch):
  * A call site that computes its argv dynamically (kind held in a variable
    built elsewhere, argv assembled in a list far from the call).
  * A producer that passes --kind decision --class <allowlisted> for something
    that is not really a founder decision. The enum bounds the vocabulary, it
    cannot audit intent. Only review does.
  * Producers in other repos. Fleet instances are outside this walk by design.
  * A LITERAL path executed directly with no interpreter AND no argument on the
    same line -- `"$SKEL/.../slack-notify.sh"` alone. That is indistinguishable
    from a `chmod +x` continuation operand without parsing the shell, and there
    is a live instance of the operand form in this repo. The `$NOTIFY` variable
    form, which is how every real producer here writes it, IS caught bare.
"""
import argparse
import os
import re
import subprocess
import sys

# AN INVOCATION, NOT A MENTION. The first cut matched a bare `slack-notify.sh`
# anywhere and reported 53 sites against a measured population of 11 producers --
# it was counting docstrings, a test's own assertion string, and three paragraphs
# of fable-discipline-lint prose ABOUT this script. A detector that cries wolf on
# comments gets switched off, so it must match the shape of a call.
#
# COMMAND POSITION, NOT AN INTERPRETER TOKEN (PR #72 review, minor). The version
# before this one required `bash ` adjacent to the notifier, and a reviewer
# planted four realistic bare producers against it. It caught ONE. It missed
# `"$NOTIFY" "msg"` -- and slack-notify.sh is mode 755, so a direct exec is the
# NATURAL form, not an exotic one -- and it missed `sh "$NOTIFY" "msg"`. A gate
# whose entire stated purpose is catching FUTURE producers cannot be blind to
# the most obvious way to write one.
#
# The interpreter requirement was load-bearing for a reason, though, and dropping
# it naively re-opens what it was protecting: an `^[A-Z_]+=` exclusion had been
# removed on the grounds that "every INVOKE form already requires an interpreter
# next to the notifier", which is what stops `NOTIFY="$SKEL/.../slack-notify.sh"`
# from reading as a call. So the anchor moves from "an interpreter precedes it"
# to "it is in COMMAND POSITION": start of line, or after ; & | ( or a shell
# keyword, optionally preceded by env assignments (the live
# `KIPI_INSTANCE_NAME="$n" bash .../slack-notify.sh` shape). A bare assignment
# has the notifier on the RIGHT of an `=`, never in command position, so it
# still cannot match -- verified by the negative cases in the paired suite.
_CMD_POS = r"""(?:^|[;&|(]|\b(?:then|else|elif|do|if|while|until|eval|exec|command)\s)
               \s*
               (?:[A-Za-z_][A-Za-z_0-9]*=(?:"[^"]*"|'[^']*'|\S*)\s+)*"""
_INTERP = r"""(?:(?:ba|da|k|z)?sh\s+(?:-\S+\s+)*)"""
# THE TRAILING BOUNDARY IS NOT DECORATION. Without `(?![A-Za-z0-9_])`, `$NOTIFY`
# also matches `$NOTIFY_RC` -- pr-review-agent.sh:848 prints that inside a WARN
# string, and widening this pattern reported that echo as an unclassified pager.
# A detector that cries wolf gets switched off, which is how the over-broad first
# cut (53 sites against a real 30) nearly died.
_NOTIFY_VAR = r"""["']?\$\{?(?:KIPI_)?NOTIFY\}?["']?(?![A-Za-z0-9_])"""
_NOTIFY_PATH = r"""["'][^"']*slack-notify\.sh["']"""
SHELL_INVOKE = re.compile(
    _CMD_POS + r"(?:" + _INTERP + r"?" + _NOTIFY_VAR + r"|"
    # A LITERAL PATH WITH NO INTERPRETER MUST CARRY AN ARGUMENT. `chmod +x \` +
    # a continuation line holding only "$skel/.../slack-notify.sh" is
    # line-initial, so command position alone reads it as a call. A real bare
    # exec passes a message; a chmod/cp/install operand is the last token on its
    # line. Requiring a following argument separates them without a shell parser.
    + r"(?:" + _INTERP + _NOTIFY_PATH + r"|" + _NOTIFY_PATH + r"\s+\S)" + r")",
    re.VERBOSE,
)
# PYTHON PRODUCERS GET THE PYTHON FORM ONLY. Shell command-position logic applied
# to a .py file read `"q-system/.../slack-notify.sh",` -- a plain list element in
# test_review_tier.py's coverage table -- as an invocation. A path in a Python
# list is data; the only way a .py file reaches the sink is by spawning it.
PY_INVOKE = re.compile(r"subprocess\.run\(\s*\[[^\]]*(?i:notif)")
# TWO ACCEPTED FORMS. Shell producers classify with a command-prefix env var,
# because a flag in argv is visible to notify stubs: stubs recording "$1" break
# when flags come first, and stubs recording "$*" pull the flags into the page
# TEXT when they come last. Both happened on this branch. A prefix is invisible
# to both forms, so no stub here or in any fleet instance needs to know this
# feature exists. argv flags stay valid for dispatch's page()/page_ok()
# pass-through, for the Python producers (whose stubs read "$1"), and by hand.
KIND = re.compile(r"--kind|KIPI_NOTIFY_KIND=")
WINDOW = 4
# A COMMENT MUST NOT SATISFY THE WINDOW (PR #72 review, minor). The window exists
# because the Python producers build argv across several lines. It was a plain
# 4-line slice, so a bare call followed by
#     # TODO(ASK-999): decide whether this should be --kind receipt or a decision.
# exempted itself -- prose next to a call could turn the gate off. Comment lines
# are now skipped rather than counted, so the window still spans four lines of
# actual CODE and a real multi-line call with a comment in the middle is not
# truncated either. NOT_A_CALL already handles a comment on the invocation line.
COMMENT_ONLY = re.compile(r"^\s*(?:#|//|\*)")

# CROSS-CHECKED AGAINST A MEASURED POPULATION, not eyeballed. Diffing this
# detector's output against the 11 producers found by hand caught faults in BOTH
# directions, which is the whole reason to do it:
#   * false POSITIVES: an over-broad `slack-notify.sh` match counted docstrings
#     and a lint's own prose about this script -- 53 sites against a real 30.
#   * false NEGATIVES, two real leaks:
#     - an `^[A-Z_]+=` exclusion meant to skip `NOTIFY=...` assignments also ate
#       `KIPI_INSTANCE_NAME="$name" bash .../slack-notify.sh "..."`, a live page.
#       Dropped entirely: every INVOKE form already requires an interpreter next
#       to the notifier, so a plain assignment cannot match one anyway.
#     - claude-integrity-tripwire.py runs `subprocess.run([notifier, message])`
#       with NO "bash" argv[0] and a lowercase name, so a bash-anchored pattern
#       could never see its four pages. Hence the third form.
# `bash -n` and a read-through would have caught neither.
# ONE EXPLICIT ACK, never a widened detector. Three shapes legitimately reach the
# sink without a literal --kind on the line: the dispatcher's page_ok() pass-through
# (its CALLERS carry the classification), a lint fixture that only quotes a call,
# and this gate's own suite, which must be able to make a bare call to prove the
# fail-open path. Loosening the regex to accommodate them would blind it to the
# real thing; a marker keeps each exemption named, greppable and countable.
NOT_A_CALL = re.compile(
    r"""(?:
          ^\s*(?:\#|\*|//)                    # comment
        | env\[|setdefault|export\s           # test/env stubbing
        | notify-kind-skip                    # explicit, per-line ack
        )""",
    re.VERBOSE,
)

# Review scratch trees hold frozen copies of old worker/converge revisions. They
# are not shipped, not loaded, and rewriting them would be noise in every diff.
SKIP_DIRS = (".pr", ".review-", "node_modules", ".prd-os/")
SKIP_FILES = ("slack-notify.sh", "notify-callsite-audit.py")


def tracked_files(repo):
    """git ls-files, so the walk matches what actually ships."""
    out = subprocess.run(
        ["git", "-C", repo, "ls-files"],
        capture_output=True, text=True, check=False,
    )
    for rel in out.stdout.splitlines():
        if not rel.endswith((".sh", ".py")):
            continue
        if any(rel.startswith(d) or ("/" + d) in rel for d in SKIP_DIRS):
            continue
        if os.path.basename(rel) in SKIP_FILES:
            continue
        yield rel


def offending_sites(repo):
    """Return [(relpath, lineno, text)] for invocations with no --kind nearby."""
    found = []
    for rel in tracked_files(repo):
        path = os.path.join(repo, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        invoke = PY_INVOKE if rel.endswith(".py") else SHELL_INVOKE
        for i, line in enumerate(lines):
            if not invoke.search(line) or NOT_A_CALL.search(line):
                continue
            if not KIND.search(kind_window(lines, i)):
                found.append((rel, i + 1, line.strip()[:110]))
    return found


def kind_window(lines, i, size=WINDOW):
    """The call line plus the next `size - 1` lines that are not comments."""
    window = [lines[i]]
    j = i + 1
    while len(window) < size and j < len(lines):
        if not COMMENT_ONLY.match(lines[j]):
            window.append(lines[j])
        j += 1
    return "\n".join(window)


def allowed_classes(repo):
    """The class enum, read from its ONE source: slack-notify.sh.

    PR #72 review, minor: this gate's fix text hardcoded four classes while
    ALLOWED_CLASSES permitted five, and kipi-dispatch.sh already used the fifth
    (`credential`). An author following the gate's own instruction could not
    discover a class the codebase relies on. A second copy of a list is a second
    thing to drift, so there is no copy -- and no hardcoded fallback either,
    because a fallback that silently disagrees is the bug wearing a hat.
    """
    path = os.path.join(repo, "q-system", ".q-system", "scripts", "slack-notify.sh")
    try:
        with open(path, encoding="utf-8") as fh:
            match = re.search(r'^ALLOWED_CLASSES="([^"]*)"', fh.read(), re.M)
    except OSError:
        return None
    return match.group(1).split() if match else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)

    bad = offending_sites(repo)
    if not bad:
        print("notify-callsite-audit: OK -- every call site declares a --kind")
        return 0

    print("notify-callsite-audit: %d call site(s) reach the founder with no --kind.\n" % len(bad))
    for rel, lineno, text in bad:
        print("  %s:%d\n      %s" % (rel, lineno, text))
    classes = allowed_classes(repo)
    enum = "|".join(classes) if classes else "see ALLOWED_CLASSES in slack-notify.sh"
    print(
        "\nFix: pass --kind receipt (the machine handled it; it is recorded, not delivered)\n"
        "  or --kind decision --class <%s>.\n"
        "A page that names the founder as the actor is a defect in the producer." % enum
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
