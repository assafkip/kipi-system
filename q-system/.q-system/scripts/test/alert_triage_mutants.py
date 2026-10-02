#!/usr/bin/env python3
"""Show every ASK-1133 defect pin going RED against a build without its fix.

ASK-1133's first acceptance line: "Each of the 10 defects has a test that is
shown RED against a build without its fix". A green suite proves only that the
fix and the test agree today. This reverts ONE fix at a time in a temporary copy
of linear-alert-triage.py, runs the test class that pins that defect against the
copy, and requires it to FAIL. A mutant whose tests stay green means that pin is
decoration, and this script exits 1.

Never touches the shipped script: the mutant is a copy in a temp directory,
handed to the suite through KIPI_ALERT_TRIAGE_UNDER_TEST.

Every replacement must match EXACTLY ONCE. A mutant that no longer applies,
because the code it reverts was reworded, is reported as an error rather than
counted as killed: a reversion that changed nothing would fail no test and read
as a pin that works.

    python3 q-system/.q-system/scripts/test/alert_triage_mutants.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPT = TEST_DIR.parent / "linear-alert-triage.py"
SUITE = TEST_DIR / "test_linear_alert_triage.py"

# (defect, what is reverted, [(shipped text, reverted text)], extra env, test class)
MUTANTS = [
    ("D1", "no scheduled caller: the lane template is absent", [],
     {"KIPI_ALERT_TRIAGE_PLIST_DIR": "<empty>"}, "TestD1LaneHasAScheduledCaller"),
    ("D1", "no run verb on the CLI",
     [('choices=["list", "promote", "close", "run"]', 'choices=["list", "promote", "close"]')],
     {}, "TestD1LaneHasAScheduledCaller"),
    ("D2", "hold does not re-check that the issue is still an alert",
     [("    if not is_alert_ticket(fresh.get(\"description\") or \"\"):\n"
       "        return Outcome(False, f\"{ident}: SKIPPED (no longer an alert; promoted while this ran)\")",
       "    if False:\n        pass")],
     {}, "TestD2HoldHasNoneOfClosesOldDefects"),
    ("D2", "hold ignores the rationale comment's result",
     [("        raise RuntimeError(f\"{ident}: refusing to hold", "        print(f\"{ident}: refusing to hold")],
     {}, "TestD2HoldHasNoneOfClosesOldDefects"),
    ("D3", "hold rewrites the description from its stale read",
     [('{"id": ident, "input": {"addedLabelIds": [label_id]}}',
       '{"id": ident, "input": {"addedLabelIds": [label_id], "description": fresh.get("description")}}')],
     {}, "TestD3HoldCannotClobberAPromotion"),
    ("D4", "the pass always exits 0",
     [("    if not batch:\n        return 0", "    if True:\n        return 0")],
     {}, "TestD4TotalModelFailureIsNotAQuietNight"),
    ("D5", "a skipped write is counted as written",
     [("    if out.wrote:\n        return \"written\"", "    if out is not None:\n        return \"written\"")],
     {}, "TestD5SkippedWritesAreNotSuccesses"),
    ("D6", "the pool is pinned to one project",
     [("    for i in fetch_open(ls, None):", "    for i in fetch_open(ls, \"kipi-system\"):")],
     {}, "TestD6TheLaneIsFleetWide"),
    ("D7", "the model call is granted edit permission",
     [('"--strict-mcp-config", "--tools", ""]', '"--permission-mode", "acceptEdits"]')],
     {}, "TestD7TheModelGetsNoTools"),
    ("D7", "MCP servers still load (built-in tools only removed)",
     [('"--strict-mcp-config", "--tools", ""]', '"--tools", ""]')],
     {}, "TestD7TheModelGetsNoTools"),
    ("D8", "a missing hold label raises instead of being created",
     [("    teams = ((ls.graphql(TEAM_ID_Q",
       "    raise RuntimeError('create the label by hand')\n    teams = ((ls.graphql(TEAM_ID_Q")],
     {}, "TestD8FreshWorkspaceNeedsNoHandMadeLabel"),
    ("D9", "a bodyless verdict parses and falls through into HOLD",
     [("    if verdict not in VERDICTS or not body:", "    if verdict not in VERDICTS:"),
      ("        if kind == \"PROMOTE\":", "        if kind == \"PROMOTE\" and body:"),
      ("        elif kind == \"HOLD\":", "        elif True:")],
     {}, "TestD9ABodylessPromoteIsNeverAHold"),
    ("D10", "promotion does not require owner:sana",
     [("    if OWNER_LABEL not in labels:", "    if False:")],
     {}, "TestD10TheLaneNeverPromotesAnUnroutableAlert"),
]


def run_class(module: Path, test_class: str, env_extra: dict, empty_dir: str) -> int:
    env = {**os.environ, "KIPI_ALERT_TRIAGE_UNDER_TEST": str(module)}
    env.update({k: (empty_dir if v == "<empty>" else v) for k, v in env_extra.items()})
    res = subprocess.run([sys.executable, "-m", "pytest", str(SUITE), "-q",
                          "-p", "no:cacheprovider", "-k", test_class],
                         capture_output=True, text=True, env=env)
    return res.returncode


def build_mutant(shipped: str, edits: list) -> str | None:
    """The shipped text with every edit applied, or None if any edit misses."""
    out = shipped
    for old, new in edits:
        if out.count(old) != 1:
            return None
        out = out.replace(old, new)
    return out


def main() -> int:
    shipped = SCRIPT.read_text(encoding="utf-8")
    bad = 0
    with tempfile.TemporaryDirectory(prefix="alert-triage-mutants-") as tmp:
        empty = Path(tmp) / "no-plists"
        empty.mkdir()
        for n, (defect, what, edits, env, test_class) in enumerate(MUTANTS):
            if run_class(SCRIPT, test_class, {}, str(empty)) != 0:
                print(f"BASELINE RED  {defect} {test_class}: fix the suite first")
                bad += 1
                continue
            text = build_mutant(shipped, edits)
            if text is None:
                print(f"NOT APPLIED   {defect} {what}: the reverted text moved")
                bad += 1
                continue
            module = Path(tmp) / f"mutant_{n}.py"
            module.write_text(text, encoding="utf-8")
            rc = run_class(module, test_class, env, str(empty))
            verdict = "KILLED  (RED)" if rc != 0 else "SURVIVED"
            bad += rc == 0
            print(f"{verdict:13} {defect:3} {what}  [{test_class}]")
    print(f"{len(MUTANTS) - bad}/{len(MUTANTS)} mutants killed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
