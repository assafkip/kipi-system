#!/usr/bin/env python3
"""Reproducer for plan-lint.py (ASK-136).

Pairs with `q-system/.q-system/scripts/plan-lint.py`, the deterministic slice of
`.claude/rules/quick-plan.md`.

Red-making input, named before the green was taken (lesson
`a-check-must-be-able-to-fail-for-the-reason-you-care-abou`): a plan file dated
on/after the cutoff whose body carries What/why, Approach, Files to touch and
Patterns to follow but NOT "Acceptance criteria". If that input does not come
back as a block, this suite is decoration.

Run: python3 q-system/.q-system/scripts/test_plan_lint.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINT = HERE / "plan-lint.py"

spec = importlib.util.spec_from_file_location("plan_lint", LINT)
if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
    raise SystemExit(f"cannot load {LINT}")
PL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PL)

FAILURES: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}: got {got!r}, want {want!r}")
        FAILURES.append(name)


COMPLETE = """# Ship the thing

## What/why
One line of why.

## Approach
Three options existed; the pick is B.

## Files to touch
- `q-system/.q-system/scripts/plan-lint.py`

## Acceptance criteria
- [ ] the reproducer goes green

## Patterns to follow
Same shape as handoff-provenance-lint.py.
"""

MISSING_ACCEPTANCE = COMPLETE.replace(
    "## Acceptance criteria\n- [ ] the reproducer goes green\n\n", "")


def run_hook(path: Path) -> tuple[int, str]:
    payload = json.dumps({"tool_input": {"file_path": str(path)}})
    proc = subprocess.run(
        [sys.executable, str(LINT)], input=payload,
        capture_output=True, text=True)
    return proc.returncode, proc.stderr


def main() -> int:
    print("plan-lint reproducer")

    # --- the red-making input this suite exists for ---------------------------
    check("missing Acceptance criteria is reported",
          PL.missing_sections(MISSING_ACCEPTANCE), ["Acceptance criteria"])
    check("a complete plan reports nothing",
          PL.missing_sections(COMPLETE), [])

    # --- every section is individually load-bearing ---------------------------
    for label, needle in [
        ("What/why", "## What/why\nOne line of why.\n\n"),
        ("Approach", "## Approach\nThree options existed; the pick is B.\n\n"),
        ("Files to touch",
         "## Files to touch\n- `q-system/.q-system/scripts/plan-lint.py`\n\n"),
        ("Patterns to follow",
         "## Patterns to follow\nSame shape as handoff-provenance-lint.py.\n"),
    ]:
        body = COMPLETE.replace(needle, "")
        check(f"missing {label} is reported",
              PL.missing_sections(body), [label])

    # A bold label is the other shape the rule's own prose uses.
    bold = COMPLETE.replace("## Acceptance criteria",
                            "**Acceptance criteria:**")
    check("bold label counts as the section", PL.missing_sections(bold), [])

    # --- filename contract ----------------------------------------------------
    check("dated filename passes",
          PL.filename_violation("ship-the-thing-2026-08-25.md"), None)
    check("undated filename is a violation",
          bool(PL.filename_violation("ship-the-thing.md")), True)
    check("date not in trailing position is a violation",
          bool(PL.filename_violation("continuation-2026-08-25-automerge.md")),
          True)

    # --- grandfathering: the corpus that predates the gate --------------------
    # 39 of the 57 plans on disk at ship time are missing at least one section.
    # A gate red on its own population gets switched off, so pre-cutoff plans
    # are exempt (same reasoning as automated-filer-marking.md).
    check("pre-cutoff plan is grandfathered",
          PL.is_grandfathered("triage-design-2026-07-27.md"), True)
    check("undated legacy name with an inner date is grandfathered",
          PL.is_grandfathered("continuation-2026-07-28-automerge.md"), True)
    check("on-cutoff plan is in scope",
          PL.is_grandfathered(f"x-{PL.CUTOFF}.md"), False)
    check("post-cutoff plan is in scope",
          PL.is_grandfathered("x-2027-01-01.md"), False)
    check("a name with no date at all is NOT grandfathered",
          PL.is_grandfathered("notes.md"), False)

    # --- end-to-end through the hook contract ---------------------------------
    with tempfile.TemporaryDirectory() as td:
        plans = Path(td) / "q-system" / "output" / "plans"
        plans.mkdir(parents=True)

        bad = plans / "ship-the-thing-2026-08-25.md"
        bad.write_text(MISSING_ACCEPTANCE, encoding="utf-8")
        rc, err = run_hook(bad)
        check("hook blocks the incomplete plan", rc, 2)
        check("stderr names the missing section",
              "Acceptance criteria" in err, True)

        good = plans / "ship-the-thing-2026-08-26.md"
        good.write_text(COMPLETE, encoding="utf-8")
        check("hook passes the complete plan", run_hook(good)[0], 0)

        legacy = plans / "triage-design-2026-07-27.md"
        legacy.write_text(MISSING_ACCEPTANCE, encoding="utf-8")
        check("hook passes a grandfathered plan", run_hook(legacy)[0], 0)

        skipped = plans / "ship-the-thing-2026-08-27.md"
        skipped.write_text(MISSING_ACCEPTANCE + f"\n{PL.SKIP_MARKER}\n",
                           encoding="utf-8")
        check("skip marker bypasses the block", run_hook(skipped)[0], 0)

        # Fast-exit paths. A too-wide plan linter blocks every write in every
        # instance, which is the failure mode the DoR's blast-radius line calls
        # out, so both misses below must return 0.
        elsewhere = Path(td) / "q-system" / "output" / "notes-2026-08-25.md"
        elsewhere.write_text(MISSING_ACCEPTANCE, encoding="utf-8")
        check("a file outside output/plans/ is ignored",
              run_hook(elsewhere)[0], 0)

        code = Path(td) / "q-system" / "output" / "plans" / "helper.py"
        code.write_text("x = 1\n", encoding="utf-8")
        check("a non-markdown file in plans/ is ignored", run_hook(code)[0], 0)

    # Malformed stdin must not block: a hook that fails closed on its own
    # plumbing blocks the fix too (lesson a-hook-that-fails-closed-...).
    proc = subprocess.run([sys.executable, str(LINT)], input="not json",
                          capture_output=True, text=True)
    check("garbage stdin exits 0", proc.returncode, 0)

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
