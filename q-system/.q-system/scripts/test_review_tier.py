#!/usr/bin/env python3
"""Paired test for review-tier.py (deterministic review-tier classifier).

Every case runs the REAL script via subprocess against either a captured real PR
diff or a diff produced by `git diff` inside a THROWAWAY tempdir repo. No case
touches a live data path and no case hand-writes diff text -- a fixture I invent
tests my assumption, not the producer's output (fable-discipline test isolation).

Sections, selectable with --only:
  real       the two PRs the founder named, classified from their real diffs
  precedence an escalate trigger beats every self-safe category
  unknown    a file matching no rule escalates
  self       the four self-sufficient categories actually return SELF
  errors     unparseable input fails CLOSED, never to SELF
  mutation   invert one trigger at a time and prove its case goes red
  list-breadth which LOOP_CRITICAL entries actually change the tier (only the
             .py ones do; the shell entries cannot reach the comment-only class
             at all, so narrowing the list would not have spared PR #60)
  fixture-hygiene  stored .diff fixtures carry no founder/instance strings --
             this dir PROPAGATES to every instance, and two independent gates
             have now misread a captured removal here as a live reference

The mutation section is the negative self-test. A check that has never been seen
to fail is a rubber stamp, so each trigger is disabled at the source and the case
that depends on it must flip. Each mutant asserts its own replacement applied --
a mutation that silently no-ops gives a false green.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
TIER = HERE / "review-tier.py"
FIXTURES = HERE / "test" / "fixtures" / "review-tier"
EXIT_SELF, EXIT_ESCALATE, EXIT_ERROR = 0, 10, 2

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS: {name}")
    else:
        failures.append(name)
        print(f"FAIL: {name}{(' -- ' + detail) if detail else ''}")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True)


def make_sandbox(tmp, instances=None):
    """A throwaway git repo shaped like this one: settings + registry + git."""
    root = pathlib.Path(tmp)
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps({
        "hooks": {"PostToolUse": [{"hooks": [{
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/q-system/.q-system/"
                       "scripts/voice-lint.py"}]}]}}))
    (root / "instance-registry.json").write_text(json.dumps(
        {"instances": instances if instances is not None else []}))
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return root


def produce_diff(root, rel, before, after):
    """Real `git diff` output for one file edit. Never hand-written."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(before)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "before")
    p.write_text(after)
    out = git(root, "diff")
    return out.stdout


def run_tier(diff_text, root, subject=""):
    """-> (exit_code, stdout+stderr). Feeds the diff through a temp file."""
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
        fh.write(diff_text)
        path = fh.name
    cmd = [sys.executable, str(TIER), "--diff-file", path, "--root", str(root)]
    if subject:
        cmd += ["--subject", subject]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "KIPI_NOTIFY": "/usr/bin/true"})
    pathlib.Path(path).unlink(missing_ok=True)
    return r.returncode, r.stdout + r.stderr


def run_tier_script_subject(script, diff_text, root, subject=""):
    """Same, but against a MUTATED copy of the script."""
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
        fh.write(diff_text)
        path = fh.name
    cmd = [sys.executable, str(script), "--diff-file", path, "--root", str(root)]
    if subject:
        cmd += ["--subject", subject]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "KIPI_NOTIFY": "/usr/bin/true"})
    pathlib.Path(path).unlink(missing_ok=True)
    return r.returncode, r.stdout + r.stderr


# --- the diffs each trigger needs, all producer-generated ---------------------

def diff_loop_critical_comment_only(root):
    """A comment-ONLY change inside a loop-critical file. The precedence case."""
    return produce_diff(
        root, "q-system/.q-system/scripts/attempts-ledger.py",
        "# old note\nvalue = 1\n",
        "# new note, still only a comment\nvalue = 1\n")


def diff_plain_comment_only(root):
    """Same shape, ordinary file. The control that proves SELF is reachable."""
    return produce_diff(root, "tools/helper.py",
                        "# old note\nvalue = 1\n",
                        "# new note\nvalue = 1\n")


def diff_unknown_file(root):
    """No comment token, not a test, not a doc: matches no rule."""
    return produce_diff(root, "tools/thing.rb", "puts 1\n", "puts 2\n")


def diff_ledger(root):
    return produce_diff(root, "data/attempts.jsonl", '{"a":1}\n', '{"a":2}\n')


def diff_rule_md(root):
    """Prose the runtime loads. A .md suffix must not make it 'just docs'."""
    return produce_diff(root, ".claude/rules/some-rule.md",
                        "old rule text\n", "new rule text\n")


def diff_scar_comment(root):
    """Word-only scar form (a date, no id) -- the real docstring shape.

    Deliberately carries NO sp-/ASK- id, so SCAR_WORD is the only trigger that
    can fire. The first draft used an id here and the mutation test passed for
    the wrong reason: SCAR_ID still matched with SCAR_WORD disabled.
    """
    return produce_diff(root, "tools/helper.py",
                        "# plain note\nvalue = 1\n",
                        "# Scar (2026-07-02): keep the order, it broke once\n"
                        "value = 1\n")


def diff_scar_id_comment(root):
    """The id form, on a comment-leading line."""
    return produce_diff(root, "tools/helper.py",
                        "# plain note\nvalue = 1\n",
                        "# keep the order (sp-1a2b3c4d)\nvalue = 1\n")


def diff_docs(root):
    return produce_diff(root, "docs/readme.md", "old\n", "new\n")


def diff_test_only(root):
    return produce_diff(root, "q-system/.q-system/scripts/test/test-thing.sh",
                        "echo 1\n", "echo 2\n")


def diff_wired_hook(root):
    """A validator wired from settings.json, derived from the repo not a list."""
    return produce_diff(root, "q-system/.q-system/scripts/voice-lint.py",
                        "x = 1\n", "x = 2\n")


# --- sections -----------------------------------------------------------------

def section_real():
    """The two PRs the founder named, from their real captured diffs."""
    for pr, expect_tier, expect_reason in [
            (60, "ESCALATE", "script the autonomous loop executes"),
            (53, "ESCALATE", "script the autonomous loop executes")]:
        f = FIXTURES / f"pr-{pr}.diff"
        if not f.is_file():
            check(f"real: pr-{pr} fixture present", False, str(f))
            continue
        code, out = run_tier(f.read_text(), HERE.parent.parent.parent)
        check(f"real: PR #{pr} -> {expect_tier}",
              out.splitlines()[0].strip() == expect_tier, out[:200])
        check(f"real: PR #{pr} reason names the trigger",
              expect_reason in out, out[:300])

    # PR #60 is the founder's stated SELF case AND the stated precedence case.
    # It cannot be both: it is comment-only, and it lands in linear-worker.sh
    # and pr-review-agent.sh, two loop-critical scripts. The precedence rule
    # ("the file is the risk, not the hunk") is the one that governs, so #60
    # escalates. Pinned here so the contradiction can never be silently
    # re-resolved the other way.
    f = FIXTURES / "pr-60.diff"
    if f.is_file():
        code, out = run_tier(f.read_text(), HERE.parent.parent.parent)
        check("real: PR #60 escalates on the FILE, not the hunk",
              code == EXIT_ESCALATE and "linear-worker.sh" in out
              and "pr-review-agent.sh" in out, out[:300])


def section_precedence():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_sandbox(tmp)
        d = diff_loop_critical_comment_only(root)
        check("precedence: diff really is comment-only",
              all(l[1:].strip().startswith("#") or not l[1:].strip()
                  for l in d.split("\n")
                  if (l.startswith("+") or l.startswith("-"))
                  and not l.startswith(("+++", "---"))), d[:300])
        code, out = run_tier(d, root)
        check("precedence: comment-only hunk in a loop-critical file ESCALATES",
              code == EXIT_ESCALATE, out[:300])
        check("precedence: reason names the loop-critical trigger",
              "script the autonomous loop executes (attempts-ledger.py)" in out,
              out[:300])

    with tempfile.TemporaryDirectory() as tmp:
        root = make_sandbox(tmp)
        code, out = run_tier(diff_docs(root), root, subject="Revert \"fix thing\"")
        check("precedence: a revert of pure docs still ESCALATES",
              code == EXIT_ESCALATE and "revert" in out.lower(), out[:300])

    with tempfile.TemporaryDirectory() as tmp:
        root = make_sandbox(tmp)
        code, out = run_tier(diff_wired_hook(root), root)
        check("precedence: a hook wired from settings.json ESCALATES",
              code == EXIT_ESCALATE and "wired from settings" in out, out[:300])

    with tempfile.TemporaryDirectory() as tmp:
        root = make_sandbox(tmp)
        code, out = run_tier(diff_scar_comment(root), root)
        check("precedence: a scar comment beats comment-only",
              code == EXIT_ESCALATE and "scar comment" in out, out[:300])

    with tempfile.TemporaryDirectory() as tmp:
        root = make_sandbox(tmp)
        code, out = run_tier(diff_ledger(root), root)
        check("precedence: an append-only ledger ESCALATES",
              code == EXIT_ESCALATE and "ledger" in out, out[:300])

    with tempfile.TemporaryDirectory() as tmp:
        root = make_sandbox(tmp)
        code, out = run_tier(diff_rule_md(root), root)
        check("precedence: a .md the runtime loads is not 'just docs'",
              code == EXIT_ESCALATE, out[:300])


def section_unknown():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_sandbox(tmp)
        code, out = run_tier(diff_unknown_file(root), root)
        check("unknown: a file matching no rule ESCALATES",
              code == EXIT_ESCALATE, out[:300])
        check("unknown: reason says unknown is not safe",
              "matches no self-review category" in out, out[:300])

    # One unknown file poisons an otherwise self-safe change.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_sandbox(tmp)
        mixed = diff_docs(root) + diff_unknown_file(root)
        code, out = run_tier(mixed, root)
        check("unknown: one unknown file among safe ones still ESCALATES",
              code == EXIT_ESCALATE, out[:300])


def section_self():
    """SELF must be reachable, or the classifier is a constant."""
    for name, maker, category in [
            ("comment-only", diff_plain_comment_only, "comment-only hunks"),
            ("pure docs", diff_docs, "pure docs/markdown"),
            ("test-only", diff_test_only, "test-only file")]:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_sandbox(tmp)
            code, out = run_tier(maker(root), root)
            check(f"self: {name} -> SELF", code == EXIT_SELF, out[:300])
            check(f"self: {name} reason names the category",
                  category in out, out[:300])


def section_errors():
    """Fail CLOSED. Every non-zero code means do not self-review."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_sandbox(tmp)
        code, out = run_tier("this is not a diff at all\n", root)
        check("errors: unparseable input exits non-zero (never SELF)",
              code == EXIT_ERROR and code != EXIT_SELF, f"code={code} {out[:200]}")
        check("errors: says treat as ESCALATE", "ESCALATE" in out, out[:200])

        code, out = run_tier("", root)
        check("errors: empty input exits non-zero (never SELF)",
              code != EXIT_SELF, f"code={code}")


# --- mutation: invert one trigger, prove its case goes red --------------------

# (label, needle, replacement, diff-maker, reason substring, mutated exit or None)
#
# The observable is the REASON, not the tier. Several triggers are backed up by
# `unknown is not safe`, so disabling one leaves the tier at ESCALATE while the
# specific reason vanishes -- defense in depth, measured 2026-08-01 when the
# DATA_PATH mutant stayed at exit 10 via the unknown-file catch. Asserting the
# reason proves WHICH trigger produced the answer; asserting the tier alone
# would have passed for the wrong reason. Where the tier does flip, that is
# pinned too.
MUTANTS = [
    ("LOOP_CRITICAL emptied",
     "LOOP_CRITICAL = {",
     # `and`, not `or`: set() is falsy, so `set() or {...}` returns the FULL set
     # and the mutant is a no-op. Caught by the needle-applied assertion below
     # reporting a mutated run identical to the clean one (2026-08-01).
     "LOOP_CRITICAL = set() and {",
     diff_loop_critical_comment_only,
     "script the autonomous loop executes", EXIT_SELF),

    ("EXECUTABLE_PROSE never matches",
     "EXECUTABLE_PROSE = re.compile(",
     'EXECUTABLE_PROSE = re.compile(r"(?!x)x") or re.compile(',
     diff_rule_md,
     "matches no self-review category", EXIT_SELF),

    ("DATA_PATH never matches",
     "DATA_PATH = re.compile(",
     'DATA_PATH = re.compile(r"(?!x)x") or re.compile(',
     diff_ledger,
     "declared data path or append-only ledger", None),

    ("SCAR_WORD never matches",
     'SCAR_WORD = re.compile(r"\\bscars?\\b", re.IGNORECASE)',
     'SCAR_WORD = re.compile(r"(?!x)x")',
     diff_scar_comment,
     "hunk carries a scar comment", EXIT_SELF),

    ("wired-hook lookup disabled",
     "        for hit in re.findall(r\"[\\w./${}-]+\\.(?:py|sh)\", text):",
     "        for hit in []:",
     diff_wired_hook,
     "wired from settings.json", None),

    ("revert detection disabled",
     'REVERT_SUBJECT = re.compile(r"^\\s*revert[:\\s\\"\']", re.IGNORECASE)',
     'REVERT_SUBJECT = re.compile(r"(?!x)x")',
     diff_docs,
     "change is a revert", EXIT_SELF),
]


def section_mutation():
    src = TIER.read_text()
    for label, needle, replacement, maker, reason, mutated_exit in MUTANTS:
        # The mutation must actually apply. A silent no-op mutation is a false
        # green: the case would stay green for the wrong reason.
        check(f"mutation: '{label}' needle is unique in source",
              src.count(needle) == 1, f"count={src.count(needle)}")
        if src.count(needle) != 1:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            mutant = pathlib.Path(tmp) / "review-tier-mutant.py"
            mutant.write_text(src.replace(needle, replacement, 1))
            root = make_sandbox(pathlib.Path(tmp) / "repo")
            diff = maker(root)
            subject = "Revert \"fix thing\"" if "revert" in label else ""

            code_ok, out_ok = run_tier(diff, root, subject=subject)
            code_mut, out_mut = run_tier_script_subject(
                mutant, diff, root, subject)

            check(f"mutation: '{label}' -- unmutated ESCALATES with its reason",
                  code_ok == EXIT_ESCALATE and reason in out_ok,
                  f"code={code_ok} {out_ok[:200]}")
            check(f"mutation: '{label}' -- reason GONE when trigger inverted",
                  reason not in out_mut, out_mut[:250])
            if mutated_exit is not None:
                check(f"mutation: '{label}' -- tier flips too",
                      code_mut == mutated_exit,
                      f"mutated={code_mut} expected={mutated_exit} {out_mut[:200]}")


# --- list-breadth --------------------------------------------------------------
# Asked 2026-08-02: PR #60 (3 comment lines) escalated because those comments sat
# in linear-worker.sh + pr-review-agent.sh, so the proposed lever was "narrow
# LOOP_CRITICAL". This section pins the MEASURED answer: narrowing cannot reach
# PR #60. Shell files have no COMMENT_TOKEN (heredocs make comment-only
# unprovable from a diff), so they fall to "matches no self-review category"
# whether or not the list names them -- the list changes the reason string, not
# the tier. Pinned as a test and not just a comment because the day someone adds
# shell to COMMENT_TOKEN these flip, and that is exactly when they need to learn
# that the list stopped being decorative.
LOOP_NEEDLE = "LOOP_CRITICAL = {"
LOOP_EMPTIED = "LOOP_CRITICAL = set() and {"

SHELL_LOOP_CRITICAL = [
    "q-system/.q-system/scripts/linear-worker.sh",
    "q-system/.q-system/scripts/converge.sh",
    "kipi-dispatch.sh",
    "q-system/.q-system/scripts/pr-review-agent.sh",
    "q-system/.q-system/scripts/slack-notify.sh",
]


def section_list_breadth():
    src = TIER.read_text()
    check("list-breadth: LOOP_CRITICAL needle is unique in source",
          src.count(LOOP_NEEDLE) == 1, f"count={src.count(LOOP_NEEDLE)}")
    if src.count(LOOP_NEEDLE) != 1:
        return
    with tempfile.TemporaryDirectory() as tmp:
        mutant = pathlib.Path(tmp) / "review-tier-no-list.py"
        mutant.write_text(src.replace(LOOP_NEEDLE, LOOP_EMPTIED, 1))
        root = make_sandbox(pathlib.Path(tmp) / "repo")

        # CONTROL FIRST. A .py loop-critical entry MUST flip to SELF once the
        # list is gone. Without this the shell assertions below could every one
        # be green because the mutation silently failed to apply -- the same
        # false-green shape the `and`/`or` note on the LOOP_CRITICAL mutant
        # records. This control is what makes the rest of the section mean
        # anything.
        code, out = run_tier_script_subject(
            mutant, diff_loop_critical_comment_only(root), root, "")
        check("list-breadth CONTROL: a .py entry DOES flip to SELF when the list "
              "is emptied (proves the mutation applied)",
              code == EXIT_SELF, f"code={code} {out[:200]}")

        f = FIXTURES / "pr-60.diff"
        if f.is_file():
            code, out = run_tier_script_subject(mutant, f.read_text(), root, "")
            check("list-breadth: PR #60 STILL escalates with LOOP_CRITICAL "
                  "emptied -- narrowing the list is not the lever",
                  code == EXIT_ESCALATE, f"code={code} {out[:200]}")

        for rel in SHELL_LOOP_CRITICAL:
            diff = produce_diff(root, rel,
                                "# old note\necho 1\n",
                                "# new note, still only a comment\necho 1\n")
            code, out = run_tier_script_subject(mutant, diff, root, "")
            check(f"list-breadth: {pathlib.Path(rel).name} escalates even without "
                  f"the list (shell has no comment token)",
                  code == EXIT_ESCALATE, f"code={code} {out[:200]}")


# --- fixture hygiene ----------------------------------------------------------
# These fixtures live under q-system/, which `kipi update` PROPAGATES to every
# instance. A captured diff is data, but rsync does not care: a founder-specific
# string sitting in a stored .diff ships fleet-wide exactly like one in source.
#
# Scar (2026-08-02): pr-60.diff captured the commit that DELETED the fleet's
# instance-name comments, so the fixture carried `KTLYST_strategy`, `ktlyst` and
# a literal /Users/... path on `-` (removal) lines. Two INDEPENDENT detectors
# then flagged it -- validate-separation's Full skeleton sweep (this one) and
# earlier the scar detector (sp-f3bd6be4). Two gates reading the same directory
# the same way is a signal about the directory, not a quirk of either gate.
#
# The comment TEXT was redacted, never the diff structure: line count, hunk
# headers and every non-comment line are byte-identical, and the classifier's
# JSON output (tier + reasons + files) is unchanged before vs after. That is
# safe here for a specific reason -- PR #60 escalates on BASENAME
# (linear-worker.sh) and, with the list emptied, on shell having no
# COMMENT_TOKEN. Neither path ever reads a comment's words, so redacting them
# cannot move the classification. Excluding this dir from the sweep was the
# wrong fix: it would have shipped the strings to the whole fleet silently.
FOUNDER_STRINGS = re.compile(r"KTLYST|ktlyst|q-ktlyst|/Users/assafkip")


def section_fixture_hygiene():
    fixtures = sorted(FIXTURES.glob("*.diff"))
    check("fixture-hygiene: fixtures are present", bool(fixtures),
          f"none found in {FIXTURES}")
    for f in fixtures:
        hits = FOUNDER_STRINGS.findall(f.read_text(errors="ignore"))
        check(f"fixture-hygiene: {f.name} carries no founder/instance strings "
              f"(it propagates to every instance)",
              not hits, f"{len(hits)} hit(s): {sorted(set(hits))[:4]}")
    # NEGATIVE SELF-TEST: the detector must actually fire on a planted string,
    # or every green above means only "the regex never matches anything".
    check("fixture-hygiene CONTROL: detector fires on a planted string",
          bool(FOUNDER_STRINGS.search("-#   KTLYST_strategy -> ...")))


SECTIONS = {
    "real": section_real, "precedence": section_precedence,
    "fixture-hygiene": section_fixture_hygiene,
    "unknown": section_unknown, "self": section_self,
    "errors": section_errors, "mutation": section_mutation,
    "list-breadth": section_list_breadth,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(SECTIONS))
    args = ap.parse_args()
    if not TIER.is_file():
        print(f"FAIL: review-tier.py not found at {TIER}")
        return 1
    for name in ([args.only] if args.only else list(SECTIONS)):
        print(f"\n--- {name} ---")
        SECTIONS[name]()
    print()
    if failures:
        print(f"FAILED ({len(failures)}): " + "; ".join(failures))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
