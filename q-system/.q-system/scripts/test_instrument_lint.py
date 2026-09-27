#!/usr/bin/env python3
"""Reproducer for instrument-lint.py (case-004 instrument discipline).

Pairs with `q-system/.q-system/scripts/instrument-lint.py`, the deterministic
slice of `.claude/rules/instrument-discipline.md`.

Red-making input, named before the green was taken: a findings file dated on or
after the cutoff whose body says "0 of 40 domains resolved" and carries no
control label. If that input does not come back as a block, this suite is
decoration. Second red-making input: the same file with the word "control" in a
prose sentence and no label. That one MUST still block, or the label rule is
theater.

Third red-making input, added with the 2026-09-21 widening: the same
uncontrolled body written into `output/rca/`, `output/plans/` and a bare
`output/`, each dated after that scope's cutoff. Each must BLOCK, the labelled
twin must pass, and reverting SCOPES to the pre-widening pair must take all
three out of scope -- the mutation is what proves the new cases are bound to the
tuple rather than passing for some unrelated reason.

Run: python3 q-system/.q-system/scripts/test_instrument_lint.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINT = HERE / "instrument-lint.py"

spec = importlib.util.spec_from_file_location("instrument_lint", LINT)
if spec is None or spec.loader is None:  # pragma: no cover
    raise SystemExit(f"cannot load {LINT}")
IL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(IL)

FAILURES: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}: got {got!r}, want {want!r}")
        FAILURES.append(name)


NULL_NO_CONTROL = """# Finding: operator-controlled hosts

## Summary
0 of 40 domains resolved to an operator-controlled host.

## Implications
The control group is clean.
"""

NULL_PROSE_CONTROL = NULL_NO_CONTROL + """
We used a control group of 12 known-good domains as a sanity check.
"""

NULL_WITH_LABEL = NULL_NO_CONTROL + """
## Negative control
cash.app and cal.com, which MUST classify as third-party, did.
"""

NULL_WITH_BOLD_LABEL = NULL_NO_CONTROL + """
- **Known-answer case:** EV-0095 (zero-text PDF) returned zero, as it must.
"""

NO_NULL_CLAIM = """# Finding: redirect hops

## Summary
14 of 40 domains carry a redirect hop through a tracker.
"""

FENCED_ONLY = """# Finding

```
$ grep -c foo content.md
0 of 12
```
Counts above are from the raw capture.
"""

TILDE_FENCED_ONLY = FENCED_ONLY.replace("```", "~~~")

PHRASES = [
    "0 of 40 domains resolved",
    "none found in the corpus",
    "no evidence of a seller relay",
    "the query returned nothing",
    "zero matches across the tree",
    "no instances found in the second pass",
    # The next two are verbatim shapes from the case-004 file that held the
    # misclassification. The first cut of the regex passed that file clean.
    "Zero of 134 ordinary commerce operators run their own redirect",
    "brand queries returned zero QR carriers",
]

# Values, not claims. Every one of these fired in the first cut and asked a
# profile-stats table for a negative control (Codex, PR #298).
NOT_CLAIMS = [
    "| Following | 0 |",
    "| Posts | 199 | **0** |",
    "| errors | 0 |",
    "Step 0 of 5: seed collection",
    "attempt 0 of 3",
    "This should have been Step Zero of the investigation.",
    "18 of 40 matched.",
    "A nonexistent path was used.",
]

# Labels that contain the word but are not a control (Codex, PR #298).
NOT_CONTROL_LABELS = [
    "## Access control",
    "## Control plane",
    "## Command and control (C2)",
    "- **Quality control:** fine",
    "# Reachability, controls, and what the seven returned",
]
CONTROL_LABELS = [
    "## Control",
    "1. **Negative control:** cash.app",
    "> **Control:** the untouched tab",
    "## Negative control",
    "### Positive control: the row that MUST hit",
    "**Known-answer case:** EV-0095 returned zero, as it must.",
    "- **Calibration:** 12 hand-checked rows.",
]


def run_hook(path: Path) -> tuple[int, str]:
    payload = json.dumps({"tool_input": {"file_path": str(path)}})
    proc = subprocess.run([sys.executable, str(LINT)], input=payload,
                          capture_output=True, text=True)
    return proc.returncode, proc.stderr


def main() -> int:
    print("instrument-lint reproducer")

    # --- the red-making inputs this suite exists for --------------------------
    check("null claim, no control: violation",
          bool(IL.violations("f-2026-09-04.md", NULL_NO_CONTROL)), True)
    check("null claim, 'control' only in prose: STILL a violation",
          bool(IL.violations("f-2026-09-04.md", NULL_PROSE_CONTROL)), True)

    # --- the passes -----------------------------------------------------------
    check("null claim + heading label: pass",
          IL.violations("f-2026-09-04.md", NULL_WITH_LABEL), [])
    check("null claim + bold bullet label: pass",
          IL.violations("f-2026-09-04.md", NULL_WITH_BOLD_LABEL), [])
    check("no null claim at all: pass",
          IL.violations("f-2026-09-04.md", NO_NULL_CLAIM), [])
    check("null claim only inside a code fence: pass",
          IL.violations("f-2026-09-04.md", FENCED_ONLY), [])
    check("null claim only inside a ~~~ fence: pass",
          IL.violations("f-2026-09-04.md", TILDE_FENCED_ONLY), [])
    check("skip marker: pass",
          IL.violations("f-2026-09-04.md",
                        NULL_NO_CONTROL + "\ninstrument-lint-skip\n"), [])

    # --- every trigger phrase is individually load-bearing --------------------
    for phrase in PHRASES:
        check(f"phrase fires: {phrase!r}",
              len(IL.null_claims(f"# F\n\nResult: {phrase}.\n")), 1)
    for line in NOT_CLAIMS:
        check(f"value, not claim: {line!r}", IL.null_claims(f"# F\n\n{line}\n"), [])
    for line in NOT_CONTROL_LABELS:
        check(f"not a control label: {line!r}",
              IL.has_control_label(f"# F\n\n{line}\n"), False)
    for line in CONTROL_LABELS:
        check(f"control label: {line!r}",
              IL.has_control_label(f"# F\n\n{line}\n"), True)
    check("null claim + C2 heading is STILL a violation",
          bool(IL.violations("f-2026-09-04.md",
                             NULL_NO_CONTROL + "\n## Command and control (C2)\n")), True)

    # --- grandfathering: the corpus that predates the gate --------------------
    # 36 of 246 in-scope files fleet-wide (instance-registry.json) carry an
    # uncontrolled null-shaped line; 0 remain red after the exemption (2026-09-03).
    check("pre-cutoff filename is grandfathered",
          IL.is_grandfathered("FINDING-commerce-corpus-2026-09-03.md"), True)
    check("a DIRECTORY date never exempts (new file in an old premortem dir)",
          IL.is_grandfathered("/x/output/analyses/premortem-2026-08-13/followup.md"), False)
    check("pre-cutoff basename under a dated directory is exempt",
          IL.is_grandfathered("/x/output/analyses/PREMORTEM-2026-08-14.md"), True)
    check("on-cutoff file is in scope",
          IL.is_grandfathered(f"x-{IL.CUTOFF}.md"), False)
    check("undated, untracked file is NOT grandfathered (templates are in scope)",
          IL.is_grandfathered("_TEMPLATE.md"), False)
    with tempfile.TemporaryDirectory() as td:
        # undated F-NNN name, exempt only through git history
        repo = Path(td); f = repo / "F-006-phone-lookups.md"; f.write_text("x")
        env = {"GIT_AUTHOR_DATE": "2026-06-01T00:00:00", "GIT_COMMITTER_DATE": "2026-06-01T00:00:00",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"], "HOME": td}
        for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "commit", "-q", "-m", "old"]):
            subprocess.run(cmd, cwd=td, env=env, check=True, capture_output=True)
        check("undated file first seen by git before cutoff is grandfathered",
              IL.is_grandfathered(str(f), f), True)
        g = repo / "F-009-new.md"; g.write_text("y")
        check("undated file git has never seen is NOT grandfathered",
              IL.is_grandfathered(str(g), g), False)
        # deleted then re-created after cutoff: a NEW file, not an old one
        subprocess.run(["git", "rm", "-q", f.name], cwd=td, env=env, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "gone"], cwd=td, env=env, check=True, capture_output=True)
        f.write_text("again")
        env2 = dict(env, GIT_AUTHOR_DATE="2026-09-10T00:00:00", GIT_COMMITTER_DATE="2026-09-10T00:00:00")
        subprocess.run(["git", "add", f.name], cwd=td, env=env2, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "back"], cwd=td, env=env2, check=True, capture_output=True)
        check("file re-created after cutoff is NOT grandfathered (most recent add wins)",
              IL.is_grandfathered(str(f), f), False)

    # --- scope: the first and widest refusal ----------------------------------
    check("findings path in scope",
          IL.in_scope("/a/q-investigate/investigations/c/investigation/findings/F-2026-09-05.md"),
          True)
    check("analyses path in scope",
          IL.in_scope("/a/output/analyses/premortem-2026-09-05/X.md"), True)
    check("non-md in findings is refused by the scope test",
          IL.in_scope("/a/investigation/findings/data.json"), False)

    # --- the 2026-09-21 widening -------------------------------------------
    # Every directory added, and every candidate the measurement refused. The
    # numbers behind each refusal are in SCOPES; these are the contract.
    check("plans path is IN scope (widened 2026-09-21)",
          IL.in_scope("/a/q-system/output/plans/x-2026-09-25.md"), True)
    check("rca path is IN scope",
          IL.in_scope("/a/q-system/output/rca/rca-x-2026-09-25.md"), True)
    check("a bare output/ file is IN scope",
          IL.in_scope("/a/q-consult/output/HANDOFF-x-2026-09-25.md"), True)
    check("memory/ is OUT of scope (12 red in auto-memory, unexemptable)",
          IL.in_scope("/a/q-system/memory/last-handoff.md"), False)
    check("investigation evidence is OUT of scope (37 red, unexemptable)",
          IL.in_scope("/a/investigation/evidence/items/EV-0001-x/content.md"), False)

    # The widening must ADD, never RELAX. An analyses file sits under /output/
    # too; if the widest scope's later cutoff won, every analyses file written
    # between 2026-09-04 and 2026-09-21 would have gone quietly exempt.
    check("strictest cutoff wins where scopes overlap",
          IL.scope_cutoff("/a/output/analyses/x-2026-09-10.md"), "2026-09-04")
    check("an analyses file after the OLD cutoff still blocks",
          bool(IL.violations("/a/output/analyses/x-2026-09-10.md", NULL_NO_CONTROL,
                             None, IL.scope_cutoff("/a/output/analyses/x-2026-09-10.md"))),
          True)
    check("a new scope grandfathers its own inherited population",
          bool(IL.violations("/a/output/rca/rca-x-2026-09-15.md", NULL_NO_CONTROL,
                             None, IL.scope_cutoff("/a/output/rca/rca-x-2026-09-15.md"))),
          False)

    # BOUND to SCOPES, not passing for some other reason. Mutate the tuple back
    # to the pre-widening pair and every new case above must fall out of scope
    # (lesson derive-a-value-from-its-owner: verify the derivation is bound by
    # mutating the source of truth, never by reading agreement).
    WIDE = IL.SCOPES
    try:
        IL.SCOPES = (("/investigation/findings/", "2026-09-04"),
                     ("/output/analyses/", "2026-09-04"))
        for pathspec in ("/a/q-system/output/plans/x-2026-09-25.md",
                         "/a/q-system/output/rca/rca-x-2026-09-25.md",
                         "/a/q-consult/output/HANDOFF-x-2026-09-25.md"):
            check(f"mutation: out of scope with the old tuple: {pathspec}",
                  IL.in_scope(pathspec), False)
        check("mutation: the two original scopes survive the revert",
              IL.in_scope("/a/investigation/findings/F-2026-09-05.md"), True)
    finally:
        IL.SCOPES = WIDE
    check("SCOPES restored after the mutation", IL.SCOPES, WIDE)

    # --- end-to-end through the hook contract ---------------------------------
    with tempfile.TemporaryDirectory() as td:
        findings = Path(td) / "investigation" / "findings"
        findings.mkdir(parents=True)

        bad = findings / "FINDING-hosts-2026-09-05.md"
        bad.write_text(NULL_NO_CONTROL, encoding="utf-8")
        rc, err = run_hook(bad)
        check("hook blocks the uncontrolled null finding", rc, 2)
        check("stderr quotes the offending line", "0 of 40" in err, True)

        old = findings / "FINDING-hosts-2026-09-03.md"
        old.write_text(NULL_NO_CONTROL, encoding="utf-8")
        check("hook passes the same body under a pre-cutoff name",
              run_hook(old)[0], 0)

        good = findings / "FINDING-hosts-2026-09-06.md"
        good.write_text(NULL_WITH_LABEL, encoding="utf-8")
        check("hook passes the controlled finding", run_hook(good)[0], 0)

        # a cwd-relative payload path must still land in scope
        import os
        cwd0 = os.getcwd(); os.chdir(td)
        try:
            payload = json.dumps({"tool_input": {"file_path": "investigation/findings/FINDING-hosts-2026-09-05.md"}})
            rc_rel = subprocess.run([sys.executable, str(LINT)], input=payload,
                                    capture_output=True, text=True).returncode
        finally:
            os.chdir(cwd0)
        check("relative path in the payload is resolved and blocks", rc_rel, 2)

        outside = Path(td) / "notes-2026-09-06.md"
        outside.write_text(NULL_NO_CONTROL, encoding="utf-8")
        check("hook ignores a path the scope test refuses", run_hook(outside)[0], 0)

    # --- end to end through the hook, per newly covered directory -------------
    # red first: the uncontrolled body must BLOCK in each new directory before
    # the same body with a label is allowed to prove anything.
    with tempfile.TemporaryDirectory() as td:
        findings = Path(td) / "investigation" / "findings"
        findings.mkdir(parents=True, exist_ok=True)
        for sub in ("output/rca", "output/plans", "output", "output/analyses"):
            d = Path(td) / sub
            d.mkdir(parents=True, exist_ok=True)

            bad = d / "x-2026-09-25.md"
            bad.write_text(NULL_NO_CONTROL, encoding="utf-8")
            rc, err = run_hook(bad)
            check(f"hook blocks an uncontrolled null claim in {sub}/", rc, 2)
            check(f"stderr quotes the line in {sub}/", "0 of 40" in err, True)

            good = d / "y-2026-09-25.md"
            good.write_text(NULL_WITH_LABEL, encoding="utf-8")
            check(f"hook passes the controlled claim in {sub}/", run_hook(good)[0], 0)

        # The refusal must name THIS scope's cutoff. Red-first input, named before
        # the fix: an output/ file caught under the 2026-09-21 scope whose stderr
        # quotes 2026-09-04 tells its author to beat a date that is not the one
        # that would have exempted it (Codex reviewer, skeleton PR #398,
        # sp-6c0496a4). Cosmetic in effect, misleading in practice, and the rule
        # claims this stderr carries the whole fix.
        scoped = Path(td) / "output" / "rca" / "rca-cutoff-2026-09-25.md"
        scoped.write_text(NULL_NO_CONTROL, encoding="utf-8")
        rc_s, err_s = run_hook(scoped)
        check("output/ refusal blocks", rc_s, 2)
        check("output/ refusal names the WIDENED cutoff", "2026-09-21" in err_s, True)
        check("output/ refusal does NOT name the original cutoff",
              "2026-09-04" in err_s, False)
        findings_old = findings / "FINDING-cutoff-2026-09-25.md"
        findings_old.write_text(NULL_NO_CONTROL, encoding="utf-8")
        err_f = run_hook(findings_old)[1]
        check("findings/ refusal still names the ORIGINAL cutoff",
              "2026-09-04" in err_f, True)

        # the exemptions, per scope, at the boundary
        pre = Path(td) / "output" / "rca" / "rca-old-2026-09-20.md"
        pre.write_text(NULL_NO_CONTROL, encoding="utf-8")
        check("hook passes an output/ file dated before the widened cutoff",
              run_hook(pre)[0], 0)
        onday = Path(td) / "output" / "rca" / "rca-onday-2026-09-21.md"
        onday.write_text(NULL_NO_CONTROL, encoding="utf-8")
        check("hook blocks an output/ file dated ON the widened cutoff",
              run_hook(onday)[0], 2)
        # an analyses file between the two cutoffs must NOT be relaxed by the
        # widening it is now nested inside
        mid = Path(td) / "output" / "analyses" / "z-2026-09-10.md"
        mid.write_text(NULL_NO_CONTROL, encoding="utf-8")
        check("hook still blocks an analyses file dated between the cutoffs",
              run_hook(mid)[0], 2)

        # the refused candidates, end to end
        for sub, name in (("memory", "last-handoff.md"),
                          ("investigation/evidence/items/EV-0001-x", "content.md")):
            d = Path(td) / sub
            d.mkdir(parents=True, exist_ok=True)
            f = d / name
            f.write_text(NULL_NO_CONTROL, encoding="utf-8")
            check(f"hook fast-exits on {sub}/{name} (refused candidate)",
                  run_hook(f)[0], 0)

    # A missing / unreadable file and a malformed payload must never block.
    proc = subprocess.run([sys.executable, str(LINT)], input="not json",
                          capture_output=True, text=True)
    check("malformed payload exits 0", proc.returncode, 0)

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) red: {FAILURES}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
