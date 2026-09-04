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
    "## Command and control (C2)",
    "- **Quality control:** fine",
    "# Reachability, controls, and what the seven returned",
]
CONTROL_LABELS = [
    "## Control",
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
    check("pre-cutoff DIRECTORY date is grandfathered (premortem layout)",
          IL.is_grandfathered("/x/output/analyses/premortem-2026-08-13/premortem.md"), True)
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

    # --- scope: the first and widest refusal ----------------------------------
    check("findings path in scope",
          IL.in_scope("/a/q-investigate/investigations/c/investigation/findings/F-2026-09-05.md"),
          True)
    check("analyses path in scope",
          IL.in_scope("/a/output/analyses/premortem-2026-09-05/X.md"), True)
    check("plans path is refused by the scope test",
          IL.in_scope("/a/q-system/output/plans/x-2026-09-05.md"), False)
    check("non-md in findings is refused by the scope test",
          IL.in_scope("/a/investigation/findings/data.json"), False)

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

        outside = Path(td) / "notes-2026-09-06.md"
        outside.write_text(NULL_NO_CONTROL, encoding="utf-8")
        check("hook ignores a path the scope test refuses", run_hook(outside)[0], 0)

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
