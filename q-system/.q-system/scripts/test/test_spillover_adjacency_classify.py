#!/usr/bin/env python3
"""Reproducer + acceptance for the spillover adjacency classifier (ASK-2014).

WHAT IT PINS: `spillover-adjacency-classify.py` decides, from data alone, whether
a spillover row would have qualified as a small adjacent fix instead of a filed
ticket. Three gates, each separately decidable and separately reportable:

  G1 severity   row severity at or below `medium` in prd-os's own severity order
  G2 adjacency  a path named in the row's description is in the changed-file set
                of the issue named in `source`
  G3 size       the resolution commit's changed-line count is under the cap

Verdicts are three-way ON PURPOSE. `FIX_IN_PLACE` and `FILE_TICKET` are the two
answers the founder decision needs; `UNDECIDABLE` is the third because the ledger
does not carry a patch for a row nobody has fixed yet, and collapsing that into
either answer would invent the number this issue exists to measure. 1,760 of the
1,780 real rows carry no `resolution_commit` (measured 2026-09-29), so a two-way
verdict would have to guess on 98.9% of the population.

WHY THE FIXTURES ARE REAL ROWS: an invented row tests the author's idea of the
schema. Every row in fixtures/spillover-adjacency/rows.jsonl was copied verbatim
from the founder's live `.prd-os/spillover.jsonl` (gitignored, so it is never in a
fresh checkout), and every `resolution_commit` in it resolves in this repo's
history. Case 13 is the binding check: it runs the changed-file derivation against
THIS repo, so the fixture expectations cannot pass by agreeing with themselves.

WHERE THIS SUITE IS BLIND, stated so nobody counts it as coverage: it does not
check that the real ledger's split is correct, only that the classifier's rules
are applied as described. The split is a measurement, printed by the replay, not
an assertion. And the `basename` adjacency strength is a loose match by
construction -- a row saying only "prd_runner.py" cannot be told apart from a row
meaning a different file of the same name. The classifier reports the strength per
row instead of hiding it, which is the most the data supports.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "q-system/.q-system/scripts/spillover-adjacency-classify.py"
# .ndjson, not .jsonl, and the extension is the whole reason. `.gitignore:43`
# excludes `*.jsonl` and un-ignores only `receipts.jsonl`, so a fixture named
# rows.jsonl cannot be committed and this suite would have gone green locally and
# red in CI on a missing file. The classifier reads lines, so the extension is
# free; editing .gitignore to carve out one fixture is not in this issue's scope.
FIXTURES = Path(__file__).resolve().parent / "fixtures/spillover-adjacency/rows.ndjson"

PASS = 0


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg):
    global PASS
    PASS += 1
    print(f"  ok: {msg}")


# --- case 1: the script exists and exposes the functions the rest drives ------
if not SCRIPT.is_file():
    fail(f"spillover-adjacency-classify.py does not exist at {SCRIPT}")
if not FIXTURES.is_file():
    fail(f"fixture ledger does not exist at {FIXTURES}")

spec = importlib.util.spec_from_file_location("sac", SCRIPT)
sac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sac)

REQUIRED = [
    "severity_order", "collapse_rows", "extract_paths",
    "changed_files_by_issue", "classify", "main",
]
missing = [n for n in REQUIRED if not hasattr(sac, n)]
if missing:
    fail("classifier is missing " + ", ".join(missing))
ok("classifier loads and exposes " + ", ".join(REQUIRED))


# --- case 2: severity order is DERIVED from prd-os, not restated here ---------
order = sac.severity_order()
if not order:
    fail("severity_order() returned nothing; the derivation from prd_runner.py "
         "silently produced an empty tuple, which would make the severity gate "
         "a no-op that reads as green")
if "medium" not in order:
    fail(f"severity_order() has no 'medium' to threshold against: {order}")
if order.index("major") <= order.index("medium"):
    fail(f"severity_order() does not rank major above medium: {order}")
if list(order) == ["low", "minor", "medium", "high", "major", "blocker"] and \
        "SPILLOVER_SEVERITY_ORDER" not in SCRIPT.read_text():
    fail("severity order matches prd-os by value but the classifier never names "
         "SPILLOVER_SEVERITY_ORDER, so it is a hand-typed copy, not a derivation")
ok(f"severity order derived from prd_runner.py: {order}")

# The derivation is BOUND, not merely equal: point it at a copy whose order was
# mutated and confirm the classifier reports the mutated order.
with tempfile.TemporaryDirectory() as td:
    fake = Path(td) / "prd_runner.py"
    fake.write_text(
        'SPILLOVER_SEVERITY_ORDER = ("nit", "medium", "catastrophe")\n')
    got = sac.severity_order(runner_path=fake)
if got != ("nit", "medium", "catastrophe"):
    fail(f"severity_order() ignored the file it was pointed at (got {got}); it "
         "is not reading prd_runner.py at all")
ok("severity order is bound to prd_runner.py, not a literal that happens to match")


# --- case 3-8: the three gates, each decided separately ----------------------
CHANGED = {"ASK-100": {"q-system/.q-system/scripts/foo.py",
                       "plugins/prd-os/scripts/prd_runner.py"}}
SIZES = {"aaa1111": 4, "bbb2222": 900}


def row(**kw):
    base = {
        "id": "sp-test", "source": "ASK-100", "severity": "medium",
        "description": "q-system/.q-system/scripts/foo.py needs a guard",
        "status": "open", "created_at": "2026-09-01T00:00:00Z",
    }
    base.update(kw)
    return base


def verdict(r, cap=20):
    return sac.classify(r, CHANGED, cap, SIZES, order)


v, why = verdict(row(resolution_commit="aaa1111"))
if v != "FIX_IN_PLACE":
    fail(f"medium + adjacent + 4-line patch under a cap of 20 should be "
         f"FIX_IN_PLACE, got {v} ({why})")
ok(f"medium + adjacent + small patch -> FIX_IN_PLACE ({why})")

v, why = verdict(row(severity="major", resolution_commit="aaa1111"))
if v != "FILE_TICKET":
    fail(f"a major severity row must be FILE_TICKET, got {v} ({why})")
if "severity" not in why:
    fail(f"FILE_TICKET on severity does not say so in its reason: {why}")
ok(f"major severity -> FILE_TICKET, reason names the severity gate ({why})")

v, why = verdict(row(description="some other file elsewhere/bar.py is wrong",
                     resolution_commit="aaa1111"))
if v != "FILE_TICKET":
    fail(f"a path outside the issue's changed-file set must be FILE_TICKET, "
         f"got {v} ({why})")
if "adjacen" not in why:
    fail(f"FILE_TICKET on adjacency does not say so in its reason: {why}")
ok(f"named path outside the changed-file set -> FILE_TICKET ({why})")

v, why = verdict(row(resolution_commit="bbb2222"))
if v != "FILE_TICKET":
    fail(f"a 900-line patch against a cap of 20 must be FILE_TICKET, got {v} ({why})")
if "size" not in why:
    fail(f"FILE_TICKET on size does not say so in its reason: {why}")
ok(f"patch over the line cap -> FILE_TICKET ({why})")

v, why = verdict(row())
if v != "UNDECIDABLE":
    fail(f"a row with no resolution_commit has no patch to measure and must be "
         f"UNDECIDABLE, got {v} ({why})")
if "size" not in why:
    fail(f"UNDECIDABLE on an unmeasurable patch does not name the gate: {why}")
ok(f"no resolution_commit -> UNDECIDABLE, size gate named ({why})")

v, why = verdict(row(description="the worker keeps doing the wrong thing",
                     resolution_commit="aaa1111"))
if v != "UNDECIDABLE":
    fail(f"a description naming no path cannot be judged for adjacency and must "
         f"be UNDECIDABLE, got {v} ({why})")
ok(f"description names no path -> UNDECIDABLE ({why})")

v, why = verdict(row(source="ASK-999", resolution_commit="aaa1111"))
if v != "UNDECIDABLE":
    fail(f"a source with no commits in history cannot be judged for adjacency "
         f"and must be UNDECIDABLE, got {v} ({why})")
ok(f"source with no commits -> UNDECIDABLE ({why})")

# The cap is a knob, not a baked-in number: the same row flips on it alone.
v20, _ = verdict(row(resolution_commit="bbb2222"), cap=20)
v999, _ = verdict(row(resolution_commit="bbb2222"), cap=1000)
if not (v20 == "FILE_TICKET" and v999 == "FIX_IN_PLACE"):
    fail(f"the line cap does not change the verdict (cap 20 -> {v20}, "
         f"cap 1000 -> {v999}); --max-lines is decoration")
ok("the verdict moves with --max-lines, so the cap is a real parameter")


# --- case 9: last-write-wins per id, the ledger's own read semantics ---------
lines = [
    json.dumps({"id": "sp-1", "severity": "minor", "status": "open"}),
    json.dumps({"id": "sp-1", "severity": "minor", "status": "resolved"}),
    json.dumps({"id": "sp-2", "severity": "medium", "status": "open"}),
]
collapsed = sac.collapse_rows(lines)
if len(collapsed) != 2:
    fail(f"collapse_rows kept {len(collapsed)} rows from 2 ids; the append-only "
         "ledger is being double-counted")
if {r["id"]: r["status"] for r in collapsed}["sp-1"] != "resolved":
    fail("collapse_rows did not apply last-write-wins; an earlier row won")
ok("collapse_rows applies last-write-wins per id")


# --- case 10: path extraction finds paths and not prose ----------------------
paths = sac.extract_paths(
    "plugins/prd-os/scripts/prd_runner.py:2802 and validate.yml are both wrong")
if "plugins/prd-os/scripts/prd_runner.py" not in paths:
    fail(f"extract_paths missed a full path with a line suffix: {paths}")
if "validate.yml" not in paths:
    fail(f"extract_paths missed a bare filename: {paths}")
if sac.extract_paths("the worker filed a ticket instead of fixing it"):
    fail("extract_paths found a path in prose with no filename in it")
ok(f"extract_paths reads paths, not prose: {sorted(paths)}")


# --- case 11: an absent ledger exits non-zero and says so -------------------
with tempfile.TemporaryDirectory() as td:
    absent = Path(td) / "nope.jsonl"
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--ledger", str(absent)],
        capture_output=True, text=True)
if p.returncode == 0:
    fail("an absent ledger exited 0; the replay printed an empty split instead "
         "of refusing, which is the silent-absence class this repo exists to kill")
if "nope.jsonl" not in (p.stdout + p.stderr):
    fail(f"the absent-ledger refusal does not name the path it looked for: "
         f"{p.stdout}{p.stderr}")
ok(f"absent ledger -> exit {p.returncode} and the path is named")


# --- case 12: the replay prints a verdict per row and a final count ---------
fixture_rows = sac.collapse_rows(FIXTURES.read_text().splitlines())
p = subprocess.run(
    [sys.executable, str(SCRIPT), "--ledger", str(FIXTURES), "--repo-root", str(ROOT)],
    capture_output=True, text=True)
if p.returncode != 0:
    fail(f"replay over the committed fixtures exited {p.returncode}: "
         f"{p.stdout}{p.stderr}")
body = p.stdout.splitlines()
per_row = [ln for ln in body if ln.startswith("ROW ")]
if len(per_row) != len(fixture_rows):
    fail(f"replay printed {len(per_row)} row lines for {len(fixture_rows)} "
         "fixture rows; rows are being dropped or duplicated")
if not any(ln.startswith("TOTAL") for ln in body):
    fail("replay printed no TOTAL line, so there is no final count")
ok(f"replay prints {len(per_row)} row lines and a TOTAL count")

# The two verdicts the real population produces, including at least one
# FILE_TICKET so this check can go red on a rule change.
seen = {ln.split()[2] for ln in per_row}
for need in ("FILE_TICKET", "UNDECIDABLE"):
    if need not in seen:
        fail(f"no fixture row classifies {need}; that rule is untested here "
             f"(fixtures produced {sorted(seen)})")
ok(f"fixtures exercise the verdicts the real ledger produces: {sorted(seen)}")

# NOT A GAP, A MEASUREMENT. No real row reaches FIX_IN_PLACE, and none can at any
# cap below 409: all 20 rows in the live ledger that carry a `resolution_commit`
# measure 409 to 2,728 lines, and every one of them is either above medium or has
# a non-issue `source` with no commits to derive adjacency from (measured
# 2026-09-29). So FIX_IN_PLACE is pinned by the unit cases above, which drive
# classify() directly, and this asserts the absence rather than leaving it silent.
# If a future row does reach it, this goes RED and the fixtures get refreshed.
if "FIX_IN_PLACE" in seen:
    fail("a fixture row now classifies FIX_IN_PLACE; the measured claim that no "
         "real row qualifies is stale, so refresh the fixtures and the funnel "
         "numbers in the classifier's docstring")
ok("no real fixture row reaches FIX_IN_PLACE, asserted rather than assumed")

# --limit is honoured, so a replay over 1,780 real rows can be sampled.
p2 = subprocess.run(
    [sys.executable, str(SCRIPT), "--ledger", str(FIXTURES),
     "--repo-root", str(ROOT), "--limit", "2"],
    capture_output=True, text=True)
limited = [ln for ln in p2.stdout.splitlines() if ln.startswith("ROW ")]
if len(limited) != 2:
    fail(f"--limit 2 printed {len(limited)} row lines; the flag is ignored")
ok("--limit caps the rows printed")


# --- case 13: the changed-file derivation is bound to THIS repo's history ----
cmap = sac.changed_files_by_issue(ROOT)
if not cmap:
    fail("changed_files_by_issue returned an empty map against this repo; the "
         "adjacency gate would then be undecidable for every row and the split "
         "would be vacuous while reading as green")
# ASK-2172 rather than this issue's own id ON PURPOSE. Keying the assertion to
# ASK-2014 made the suite order-dependent: it went red until this branch's own
# commit existed, so a green run would have depended on when it was run rather
# than on whether the parse works. ASK-2172 is merged on main (8bf23aa9, "the
# --json stdout is one JSON document" fix) and its commit touches a path that is
# still on disk, which is what binds this check to real history.
ANCHOR = "ASK-2172"
ANCHOR_FILE = "q-system/.q-system/scripts/linear-triage-health.py"
if ANCHOR not in cmap:
    fail(f"changed_files_by_issue did not find {ANCHOR}, which is merged on main; "
         f"the git parse is broken ({len(cmap)} ids found)")
if ANCHOR_FILE not in cmap[ANCHOR]:
    fail(f"changed_files_by_issue found {ANCHOR} but not {ANCHOR_FILE}, which its "
         f"commit edits: {sorted(cmap[ANCHOR])[:5]}")
if not (ROOT / ANCHOR_FILE).is_file():
    fail(f"{ANCHOR_FILE} is no longer on disk; this anchor has rotted and the "
         "check needs a live one")
ok(f"changed-file map derived from git: {len(cmap)} issue ids, {ANCHOR} carries "
   f"{len(cmap[ANCHOR])} files including the one on disk")

# Every resolution_commit in the fixtures resolves here, so the size gate in the
# fixture expectations is measured and not silently undecidable.
for r in fixture_rows:
    sha = r.get("resolution_commit")
    if not sha:
        continue
    if sac.commit_line_count(ROOT, sha) is None:
        fail(f"fixture row {r['id']} cites resolution_commit {sha}, which does "
             "not resolve in this repo; its size gate is untested")
ok("every fixture resolution_commit resolves in this repo's history")

print(f"PASS: {PASS}/{PASS} spillover adjacency classifier checks")
