#!/usr/bin/env python3
"""issue-check-budget: an issue's required_checks are sized to what the issue touches.

WHY (founder, 2026-09-18, ASK-1796): "only issues that need the 6000 plus tests should
have them. Small issues like changing a line do not need 6000 plus checks. You need to
continuously verify that." required_checks is a free per-issue list (prd_split.py refuses
an empty one and injects nothing), so right-sizing was an authoring habit with no
executable. This is the executable. Run it after /prd-split, at /issue-start and at
/issue-verify.

Two rules, each exit 2 naming the issue:
  1. No spec carries a full-suite check. CI runs `verify.sh --full` on every PR
     (.github/workflows/verify.yml), so the whole suite already runs once at merge for
     every issue. A spec that names it runs it twice.
  2. At least one check targets the issue's own allowed_files tree (no unrelated green).

RETIRED before it shipped (founder, 2026-09-18, "1"): a rule forcing the full suite onto
issues touching fleet-wide files (kipi-update.sh, settings-template.json). Measured on
the 230 specs on main: 0 carried the full suite, and that rule was red on 23 closed
issues that shipped fine, because CI already covered them.

HONEST BOUNDARY: rule 2 compares path prefixes, so inside one large directory any test
"targets" any file. It catches a check from another subsystem, never a wrong test next
door. It reads the spec, never what /issue-verify actually ran.

stdlib only. Test: test/test_issue_check_budget.py.
"""
from __future__ import annotations

import importlib.util
import shlex
import sys
from pathlib import Path

PYTEST_VALUE_OPTS = {"-k", "-m", "-p", "-c", "-o", "-n", "--rootdir", "--maxfail"}


def _spec_parser():
    """issue_runner's own frontmatter parser, so this reads a spec the way /issue-start does."""
    here = Path(__file__).resolve()
    runner = here.parents[3] / "plugins" / "kipi-dsse" / "scripts" / "issue_runner.py"
    mod_spec = importlib.util.spec_from_file_location("issue_runner", runner)
    mod = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(mod)
    return mod._parse_frontmatter


def is_full_suite(cmd: str) -> bool:
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    if any(t.endswith("verify.sh") for t in toks) and "--full" in toks:
        return True
    if "kipi" in [Path(t).name for t in toks] and "check" in toks:
        return True
    names = [Path(t).name for t in toks]
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


def judge(front: dict) -> tuple[str, list[str]]:
    issue = str(front.get("id", "?"))
    allowed = [str(a) for a in (front.get("allowed_files") or [])]
    checks = [str(c) for c in (front.get("required_checks") or [])]
    full = [c for c in checks if is_full_suite(c)]
    narrow = [c for c in checks if not is_full_suite(c)]
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
        print("issue-check-budget: no issue specs given; nothing checked is not a pass", file=sys.stderr)
        return 2
    parse = _spec_parser()
    bad: list[str] = []
    for arg in argv:
        try:
            front = parse(Path(arg).read_text())
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
