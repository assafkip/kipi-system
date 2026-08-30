#!/usr/bin/env python3
"""Find callers that page a human and then ignore whether the page landed.

THE GAP THIS CLOSES (sp-ebe6a2b5, sp-1d78407e, ASK-627). ASK-534 gave
`slack-notify.sh` a real exit contract:

    0 = delivered   1 = send failed   3 = no webhook   4 = fixture-refused

Exactly THREE call sites fleet-wide read it. Thirteen others still record state,
set a flag, or write a marker on the assumption that a page went out. The worst
measured instance is `ci-redrive.py`: it claims its one escalation flag at :483,
notifies at :485, and `notify()` discards the return code entirely -- so the flag
burns whether or not a human was ever reached.

`sp-ebe6a2b5` says the gate that would enforce this "never landed on main", and
that was true: `git grep notify-callsite-audit.py` returned nothing. This is it.

WHY A GATE AND NOT THIRTEEN HAND-FIXES. The thirteen are not thirteen
independent bugs; they are one missing check. Converting them by hand without a
gate just resets the clock -- the fourteenth caller lands next week. That reading
is also what the evidence supports: the sites that DID get fixed are exactly the
ones with a caller that already wanted the answer (ASK-534 armed dead code
already sitting in kipi-dispatch.sh), while `converge.sh` and `ci-redrive.py`,
which had no such caller, were untouched.

WHAT A CLEAN RUN DOES NOT MEAN. Reading the exit code is necessary, not
sufficient: a caller can read it and do nothing useful. And "no findings" is the
shape that has fooled this repo three times today, so `--expect-findings` exists
to assert the detector can still see, and the self-test at the bottom proves the
DISCARDED patterns are actually matched rather than trusted.

Exit 0 = clean, 1 = findings, 2 = the detector itself looks broken.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

NOTIFY = "slack-notify.sh"

# Directories that are scratch, vendored, or self-referential.
# `\.pr\d+rev` alone did NOT match `.pr39rev3` or `.pr42rev-r2`, so 200+ review
# scratch copies were audited as if they were live code and swamped the real
# findings. Measured, not guessed: the first run reported 527 sites across 220
# files, and the live tree has a small fraction of that.
SKIP_DIR = re.compile(r'(^|/)(\.pr[\w.-]*rev[\w.-]*|\.fable-wt|\.sana-tmp|\.git|'
                      r'\.review[\w.-]*|\.runs|worktrees|security-remediation|'
                      r'node_modules|__pycache__|template-repo|dist|issues|'
                      r'sites)(/|$)|(^|/)q-system/output(/|$)')

# A test paging a human is its own (already-solved) problem: slack-notify.sh
# refuses on the fixture signal. Auditing them here would bury the real callers.
#
# A lint or audit carries the notifier's name as a PATTERN, not as a call -- this
# script's own self-test fixtures were being reported as 9 call sites that ignore
# their status. A detector that flags itself is noise that teaches people to skim
# its output.
SKIP_FILE = re.compile(r'(^|/)(test[-_].*|.*_test)\.(py|sh)$'
                       r'|[-_](lint|audit|guard)\.py$')

# The shapes that THROW the answer away. `|| true` is the loudest: it converts
# every non-zero -- failed send AND no-webhook AND fixture-refusal -- into
# success, and it is the exact form used at 11 sites in linear-worker.sh.
DISCARD_SH = (
    (re.compile(r'\|\|\s*true\s*$'), "`|| true` swallows every non-zero"),
    (re.compile(r'2>/dev/null\s*\|\|\s*:'), "`|| :` swallows every non-zero"),
    (re.compile(r'^\s*(bash|sh|zsh)\s+[^\n]*' + re.escape(NOTIFY) +
                r'[^\n]*&\s*$'), "backgrounded, so the status is unobservable"),
)

# The shapes that CONSUME it.
# These must NOT require the literal filename either: the call is usually made
# through a variable, and requiring the name here produced a false positive on
# `if bash "$NOTIFY" ...` -- a caller that does exactly the right thing. Caught
# by the self-test, which is the only reason this file is not shipping broken.
CONSUME_SH = (
    re.compile(r'^\s*if\s+'),                          # `if bash "$NOTIFY" ...`
    re.compile(r';\s*then\b'),
    re.compile(r'^\s*\w+=\$\?', re.M),                 # rc=$? on the next line
    re.compile(r'&&\s*\w'),                            # chained on success
    re.compile(r'\bpage_ok\b|\bnotify_send\b'),        # the wrappers that check
    re.compile(r'\breturncode\b|\bcheck=True\b'),      # python consumers
)


def _iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not SKIP_DIR.search(os.path.join(dirpath, d))]
        for name in filenames:
            if not name.endswith((".sh", ".py")):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            if SKIP_DIR.search(rel) or SKIP_FILE.search(rel):
                continue
            if os.path.basename(path) == NOTIFY:
                continue                                # the notifier itself
            yield path, rel


def _callsite_tokens(text):
    """What a call to the notifier looks like IN THIS FILE.

    Real callers rarely write the filename at the call. They resolve it once --
    `NOTIFY="$DIR/slack-notify.sh"`, or `script = os.path.join(..., "slack-notify.sh")`
    -- and then invoke the variable. A scan for the literal filename sees the
    ASSIGNMENT and misses every actual call, which is a false clean on exactly
    the files that page the most. The self-test caught this before it shipped.
    """
    tokens = {NOTIFY}
    for var in re.findall(r'(\w+)\s*=\s*[^\n]*' + re.escape(NOTIFY), text):
        tokens.add("$" + var)
        tokens.add("${" + var + "}")
        tokens.add(var)                 # python: subprocess.run(["bash", script])
    return tokens


def audit_text(text, rel):
    """Return (findings, callsite_count) for one file."""
    findings = []
    lines = text.splitlines()
    tokens = _callsite_tokens(text)
    count = 0
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        # An assignment is not a call. Counting it would report a file that
        # merely names the path as if it paged someone.
        if re.search(r'^\s*\w+\s*=\s*[^\n]*' + re.escape(NOTIFY), line):
            continue
        if not any(tok in line for tok in tokens):
            continue
        # Require an actual invocation on the line, ALWAYS -- not only when the
        # call is made through a variable. A docstring that merely names the
        # notifier ("Single notification channel: slack-notify.sh") was being
        # reported as a call site that ignores its status.
        if not re.search(r'\b(bash|sh|zsh|subprocess|Popen|check_call|'
                         r'check_output|system|exec)\b', line):
            continue
        count += 1
        window = "\n".join(lines[i:i + 2])          # the call plus the line after
        for pattern, why in DISCARD_SH:
            if pattern.search(line):
                findings.append((rel, i + 1, why, line.strip()[:90]))
                break
        else:
            if not any(p.search(window) for p in CONSUME_SH):
                findings.append((rel, i + 1,
                                 "status neither checked nor stored",
                                 line.strip()[:90]))
    return findings, count


def self_test():
    """Prove the detector matches what it claims BEFORE trusting a clean run.

    A lint that only ever reports clean is indistinguishable from one that
    works, and that exact failure shipped twice in this repo today.
    """
    # Each fixture is a whole FILE, because the variable-resolution step needs
    # the assignment to be present -- which is the thing the first version of
    # this self-test got wrong, and why it correctly reported the detector broken.
    assign = 'NOTIFY="$DIR/slack-notify.sh"\n'
    must_flag = [
        assign + 'bash "$NOTIFY" "msg" 2>/dev/null || true',
        assign + 'bash "$NOTIFY" "x" 2>/dev/null || :',
        assign + 'bash "$NOTIFY" "msg"',
        'bash "$D/slack-notify.sh" "msg" || true',
    ]
    must_pass = [
        assign + 'if bash "$NOTIFY" "msg"; then echo ok; fi',
        assign + 'bash "$NOTIFY" "msg" && record_sent',
        assign + 'page_ok bash "$NOTIFY" "msg"',
        assign + 'bash "$NOTIFY" "msg"\nrc=$?',
        # An assignment alone must NOT be reported as a call site.
        assign,
    ]
    bad = []
    for src in must_flag:
        f, _ = audit_text(src, "x.sh")
        if not f:
            bad.append(f"MISSED a discard: {src}")
    for src in must_pass:
        f, _ = audit_text(src, "x.sh")
        if f:
            bad.append(f"FALSE POSITIVE on a consumer: {src}")
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    ap.add_argument("--expect-findings", type=int, default=None,
                    help="fail if the count differs; pins a known backlog so it "
                         "can only shrink")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    broken = self_test()
    if broken:
        for line in broken:
            print(f"DETECTOR BROKEN: {line}", file=sys.stderr)
        return 2

    findings, sites, files = [], 0, 0
    for path, rel in _iter_files(args.root):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        if NOTIFY not in text:
            continue
        files += 1
        got, n = audit_text(text, rel)
        sites += n
        findings.extend(got)

    if not args.quiet:
        print(f"notify-callsite-audit: {sites} call site(s) across {files} file(s)")
    for rel, line, why, src in findings:
        print(f"  {rel}:{line}: {why}\n      {src}")
    if not findings and not args.quiet:
        print("  every call site consumes the notifier's exit status")

    if args.expect_findings is not None and len(findings) != args.expect_findings:
        print(f"\nexpected {args.expect_findings} finding(s), got {len(findings)}. "
              f"If this went DOWN, lower the number in the same commit that fixed "
              f"a call site. If it went UP, a new caller is ignoring whether a "
              f"human was reached.", file=sys.stderr)
        return 1
    return 1 if (findings and args.expect_findings is None) else 0


if __name__ == "__main__":
    sys.exit(main())
