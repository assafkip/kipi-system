#!/usr/bin/env python3
"""check_budget: an issue's required_checks are sized to what the issue touches.

WHY (founder, 2026-09-18, ASK-1796): "only issues that need the 6000 plus tests should
have them. Small issues like changing a line do not need 6000 plus checks. You need to
continuously verify that." And the same day: "Ensure that you're not running the 6000
tests that take over ten minutes for every single thing."

Lives beside its only caller since ASK-1810. It was q-system/.q-system/scripts/
issue-check-budget.py, which imported issue_runner from this directory while issue_runner
was about to call it back, and the plugin runs in repos that have no q-system tree.
`issue_runner.py verify` calls `judge()` on the spec snapshot before any check runs and
refuses on rule 1. The CLI below runs both rules over spec files, for /prd-split.

Two rules:
  1. No spec carries a full-suite check. CI runs `verify.sh --full` on every PR
     (.github/workflows/verify.yml), so the whole suite already runs once at merge for
     every issue. A spec that names it runs it twice. ENFORCED by verify.
  2. At least one check targets the issue's own allowed_files tree. CLI only: nobody has
     measured it against the spec population, and an unmeasured rule gets no blocking door.

RETIRED before it shipped (founder, 2026-09-18, "1"): a rule forcing the full suite onto
issues touching fleet-wide files. Measured on the 230 specs on main: 0 carried the full
suite, and that rule was red on 23 closed issues that shipped fine.

HONEST BOUNDARY: rule 2 compares path prefixes, so inside one large directory any test
"targets" any file. It reads the spec, never what verify actually ran.

stdlib only. Test: test_check_budget.py.
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

PYTEST_VALUE_OPTS = {"-k", "-m", "-p", "-c", "-o", "-n", "--rootdir", "--maxfail"}


def is_full_suite(cmd: str) -> bool:
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    if any(t.endswith("verify.sh") for t in toks) and any(t == "--full" or t.startswith("--full=") for t in toks):
        return True
    if "kipi" in [Path(t).name for t in toks] and "check" in toks:
        return True
    names = ["pytest" if Path(t).name == "py.test" else Path(t).name for t in toks]
    if "pytest" not in names:
        return False
    after = toks[names.index("pytest") + 1:]
    skip = False
    for t in after:
        if skip:
            skip = False
        elif t in PYTEST_VALUE_OPTS:
            skip = True
        elif not t.startswith("-"):
            return False          # a path or node id scopes the run
    return True


def _targets(cmd: str, allowed: list[str]) -> bool:
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    paths = [Path(t).parts for t in toks if "/" in t and not t.startswith("-")]
    for a in allowed:
        a_dir = Path(a).parts[:-1]
        need = max(1, min(2, len(a_dir)))
        for p in paths:
            common = 0
            for x, y in zip(a_dir, p):
                if x != y:
                    break
                common += 1
            if common >= need:
                return True
    return False


def full_suite_checks(checks: list[str]) -> list[str]:
    """Rule 1 alone: the checks that run the whole suite. What verify refuses on."""
    return [str(c) for c in checks if is_full_suite(str(c))]


def judge(front: dict) -> tuple[str, list[str]]:
    issue = str(front.get("id", "?"))
    allowed = [str(a) for a in (front.get("allowed_files") or [])]
    checks = [str(c) for c in (front.get("required_checks") or [])]
    full = full_suite_checks(checks)
    narrow = [c for c in checks if c not in full]
    probs = []
    if full:
        probs.append(f"{issue}: carries the full suite ({full[0]!r}). CI runs it once per PR for "
                     f"every issue. Name the tests for the files this issue changes instead.")
    if not any(_targets(c, allowed) for c in narrow):
        probs.append(f"{issue}: no check targets its own allowed_files tree. A green from "
                     f"another subsystem proves nothing about this change.")
    return ("full" if full else "narrow"), probs


def main(argv: list[str]) -> int:
    if not argv:
        print("check_budget: no issue specs given; nothing checked is not a pass", file=sys.stderr)
        return 2
    # Lazy: the only import of issue_runner, and only on the CLI path, so issue_runner can
    # import this module without a cycle.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from issue_runner import _parse_frontmatter
    bad: list[str] = []
    for arg in argv:
        try:
            front = _parse_frontmatter(Path(arg).read_text())
        except (OSError, ValueError) as e:
            bad.append(f"{arg}: unreadable spec: {e}")
            continue
        tier, probs = judge(front)
        print(f"{front.get('id', arg)}: {tier} ({len(front.get('required_checks') or [])} check(s))")
        bad += probs
    if bad:
        print("CHECK BUDGET (refused):", file=sys.stderr)
        for b in bad:
            print("  " + b, file=sys.stderr)
        return 2
    print(f"check budget ok: {len(argv)} spec(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
