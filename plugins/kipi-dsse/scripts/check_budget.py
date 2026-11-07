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
  1. No spec carries a full-suite check. Since 2026-10-01 (RULE-2026-10-01-A) the full
     suite runs only in the nightly gates.yml; PRs and pushes run the owning tests. A
     spec that names the full suite brings back the run that rule removed. ENFORCED by verify.
  2. At least one check targets the issue's own allowed_files tree. CLI only: nobody has
     measured it against the spec population, and an unmeasured rule gets no blocking door.

RETIRED before it shipped (founder, 2026-09-18, "1"): a rule forcing the full suite onto
issues touching fleet-wide files. Measured on the 230 specs on main: 0 carried the full
suite, and that rule was red on 23 closed issues that shipped fine.

HONEST BOUNDARY: rule 2 compares path prefixes, so inside one large directory any test
"targets" any file. It reads the spec, never what verify actually ran.

SIZE CLASS (ASK-3827). `size_class()` and `DEPTH` decide how much review and how many
verify repeats an issue earns, from the ASK-1749 class of its diff. See the section below.

stdlib only. Tests: test_check_budget.py, test_size_class_depth.py.
"""
from __future__ import annotations

import importlib.util
import shlex
import subprocess
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


# ---------------------------------------------------------------------------
# Size class (ASK-3827): the review depth and verify repeats a diff earns
# ---------------------------------------------------------------------------
#
# The founder's lean-mode ruling, given four times (2026-09-18, 09-23, 10-30, 11-04): one
# review, one fix round, merge; an adversarial pass only for code that sends mail, touches
# client data, loses data or moves money. Until this, issue_runner gave every issue 2
# standard reviews, 1 adversarial and 5 to 10 verify repeats, so a one-line fix paid the
# receipt store's price (RCA 2026-11-06, root cause #4).
#
# ONE CLASSIFIER. The class is the tier the host repo's own change-size.py (ASK-1749) gives
# the committed diff against origin/main, loaded by path and called through
# `plan_for_repo`, the same file and the same entry point CI's capability gate calls.
# This plugin runs from the marketplace cache, which has no copy, and carries none: a
# vendored copy would be a second classifier that drifts from the one CI runs.
#
# UNKNOWN IS L. No classifier in the repo, a diff it cannot read, a tier it does not know,
# or uncommitted code: each gets the strict numbers. change-size.py reads committed HEAD,
# so uncommitted work reads as a 0-line S diff whatever its real size.
#
# NO RISK FLAG YET. The carve-out (adversarial for mail, client data, data loss, money,
# whatever the size) has no input: neither the classifier's verdict nor the issue spec
# carries a risk field, and a keyword guess would be a second, unmeasured classifier.
# Until one exists, adversarial follows the S/M/L numbers. Follow-up: ASK-3906.
#
# M's repeats are L's on purpose: the ruling sized M's review (1 plus 1), not its repeats.
DEPTH = {
    "S": {"review_cap": {"standard": 1, "adversarial": 0}, "repeat_min": 2, "repeat_max": 2},
    "M": {"review_cap": {"standard": 1, "adversarial": 1}, "repeat_min": 5, "repeat_max": 10},
    "L": {"review_cap": {"standard": 2, "adversarial": 1}, "repeat_min": 5, "repeat_max": 10},
}
STRICT_CLASS = "L"
CLASSIFIER_RELPATH = "q-system/.q-system/scripts/change-size.py"
DIFF_BASE = "origin/main"


def depth(size: str) -> dict:
    """The review caps and repeat bounds for a class. Anything not in DEPTH is L."""
    return DEPTH.get(size, DEPTH[STRICT_CLASS])


def _strict(reason: str) -> dict:
    return {"class": STRICT_CLASS, "reasons": [reason], "base": DIFF_BASE}


def _uncommitted(repo_root: Path) -> list[str]:
    """Paths git reports as changed or untracked (not ignored), new name for a rename."""
    r = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain=v1", "-z",
                        "--untracked-files=all"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git status: {r.stderr.strip()[:200]}")
    out, entries = [], r.stdout.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        out.append(entry[3:])
        if entry[0] in "RC":
            i += 1          # -z puts a rename's old name in the next field
    return out


def size_class(repo_root: Path) -> dict:
    """{"class": S|M|L, "reasons": [...], "base": ref} for the repo's diff. Never raises."""
    path = Path(repo_root) / CLASSIFIER_RELPATH
    if not path.is_file():
        return _strict(f"no ASK-1749 classifier at {CLASSIFIER_RELPATH}, so the strict numbers apply")
    try:
        spec = importlib.util.spec_from_file_location("kipi_change_size", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        dirty = [p for p in _uncommitted(Path(repo_root)) if mod.is_code(p) or mod.machinery_reason(p)]
        verdict = mod.plan_for_repo(Path(repo_root), DIFF_BASE)
        tier, reasons = verdict["tier"], [str(r) for r in verdict["reasons"]]
    except Exception as exc:  # noqa: BLE001 -- any failure here means the strict numbers
        return _strict(f"could not classify the diff against {DIFF_BASE} "
                       f"({type(exc).__name__}: {str(exc)[:160]})")
    if dirty:
        more = f" and {len(dirty) - 1} more" if len(dirty) > 1 else ""
        return _strict(f"uncommitted change to {dirty[0]}{more}; the classifier reads committed "
                       "HEAD only, so this change's size is unknown. Commit it")
    if tier not in DEPTH:
        return _strict(f"the classifier returned tier {tier!r}, which has no depth")
    return {"class": tier, "reasons": reasons, "base": DIFF_BASE}


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
