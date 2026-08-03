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
# comments gets switched off, so it must match the shape of a call: an interpreter
# followed by the notifier. Every real site in this repo is one of three forms.
INVOKE = re.compile(
    r"""(?:
          bash\s+["']?\$\{?(?:KIPI_)?NOTIFY          # bash "$NOTIFY"
        | bash\s+["'][^"']*slack-notify\.sh["']      # bash "$SKEL/.../slack-notify.sh"
        | subprocess\.run\(\s*\[[^\]]*(?i:notif)     # subprocess.run([notifier, msg]
        )""",
    re.VERBOSE,
)
KIND = re.compile(r"--kind")
WINDOW = 4

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
NOT_A_CALL = re.compile(
    r"""(?:
          ^\s*(?:\#|\*|//)                    # comment
        | env\[|setdefault|export\s           # test/env stubbing
        )""",
    re.VERBOSE,
)

# Review scratch trees hold frozen copies of old worker/converge revisions. They
# are not shipped, not loaded, and rewriting them would be noise in every diff.
SKIP_DIRS = (".pr", ".review-", "node_modules", ".prd-os/")
SKIP_FILES = ("slack-notify.sh", "notify-callsite-audit.py")


# A wrapper that forwards "$@" to the notifier cannot declare a --kind of its
# own -- its callers do. The audit reads a 4-line window and cannot follow that
# transitively (its HONEST BOUNDARY says so). Rather than widen the analysis or
# leave a permanent false positive, the wrapper DECLARES itself with this marker
# on the same line, which is greppable and reviewable. Same convention as
# `# spillover-skip` and `<!-- voice-lint-skip -->`.
#
# The marker is NOT a blanket mute: it asserts "the kind arrives from my caller",
# and every caller is then subject to the audit normally. kipi-dispatch.sh's
# page_ok carries it, and all five of its transitive call sites were verified to
# pass --kind on 2026-08-02 (ASK-310) -- one of them, stale-checkout, was bare
# until that same change.
FORWARD_MARKER = "notify-kind-forwarded"


def is_test_file(rel: str) -> bool:
    """A test that drives a BARE call is exercising the fail-open path on purpose,
    which is the behaviour the runtime gate is specified to have. Counting those
    as violations makes this audit permanently red.

    WHY THAT MATTERS MORE THAN IT SOUNDS (ASK-310). This gate was wired into
    `kipi check` on 2026-08-02 and, unfiltered, reported 6 call sites of which 5
    were its own and neighbouring test fixtures -- e.g.
    test-notify-decision-gate.sh:177 `bash "$NOTIFY" "a bare page with no kind at
    all"`, which exists precisely to prove the bare path still warns. A gate that
    can never go green teaches the operator to skim RED, and "a fleet-wide RED
    with no severity ranking is a silence" is root cause #3 of the RCA this gate
    was built to close. Shipping a permanently-red gate would have reproduced the
    exact defect being fixed.
    """
    base = os.path.basename(rel)
    return (base.startswith(("test-", "test_"))
            or base.endswith(("_test.py", "_test.sh"))
            or "/test/" in rel or rel.startswith("test/")
            or "/tests/" in rel or rel.startswith("tests/"))


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
        if is_test_file(rel):
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
        for i, line in enumerate(lines):
            if not INVOKE.search(line) or NOT_A_CALL.search(line):
                continue
            window = "\n".join(lines[i:i + WINDOW])
            if FORWARD_MARKER in window:
                continue
            if not KIND.search(window):
                found.append((rel, i + 1, line.strip()[:110]))
    return found


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
    print(
        "\nFix: pass --kind receipt (the machine handled it; it is recorded, not delivered)\n"
        "  or --kind decision --class <irreversible-git|out-of-tree-write|spend|publish>.\n"
        "A page that names the founder as the actor is a defect in the producer."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
