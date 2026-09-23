#!/bin/bash
# Provenance for published lessons (ASK-539): every lesson in q-system/lessons/ traces to a
# row in lesson-candidates/.processed.json that names it by lesson_id.
#
# The "promoted from 2 unrelated instances" rule this issue was filed against is gone
# (AUTONOMOUS-SYSTEMS.md 3.2, founder redesign 2026-06-30). What stayed real: the ledger
# keyed each row on the SOURCE hash and never recorded which lesson that source became,
# so 175 published lessons traced to nothing (measured 2026-09-18: 136 rows, 0 with a
# lesson_id).
#
# Three parts:
#   1. lessons-distill.py writes lesson_id on every published row (fixture run, no claude).
#   2. the real repo invariant: a lesson dated after provenance started has a row.
#      The start is DERIVED from the ledger (the earliest row carrying a lesson_id), so the
#      pre-provenance population cannot turn this red, and no cutoff date is restated here.
#   3. negative self-test: the invariant goes RED on a lesson with no row.
#
# SKELETON ONLY. Part 2 reads `lesson-candidates/.processed.json`, a REPO-ROOT path.
# `kipi update` syncs q-system/, .claude/rules/ and plugins/, so no instance ever
# receives that directory and the test goes RED in all 24 of them. Part 0 below asserts
# the skeleton_only declaration rather than trusting someone to remember it.
# Run: bash q-system/.q-system/scripts/test/test-lessons-provenance.sh
set -euo pipefail
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$SCRIPTS/../../.." && pwd)"

python3 - "$SCRIPTS/lessons-distill.py" "$REPO" <<'PY'
import hashlib, json, re, subprocess, sys, tempfile
from pathlib import Path
DISTILL, REPO = sys.argv[1], Path(sys.argv[2])

fails = []
def check(n, c): print(f"  {'PASS' if c else 'FAIL'} {n}"); fails.append(n) if not c else None


def lesson_date(path):
    m = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})\s*$", path.read_text(errors="ignore"), re.M)
    return m.group(1) if m else None


def untraced(lessons_dir, ledger):
    """Lessons dated AFTER the first provenance-carrying row that no row names.

    The start comes from the DISTILLER's rows only (status "published"), never from
    every row carrying a lesson_id. lessons-distill.py stamps `date` with today's UTC
    date, so an automated row cannot be backdated; a hand-authored row carries the
    lesson's own date and README line 34 tells the founder to write it. Taking
    min() over both let one backdated hand-<id> row drag the start into 2026 and
    report 124 pre-provenance lessons as untraced (codex, PR #370 rounds 1 and 2).
    A hand row still TRACES its lesson; it just cannot move the start.
    """
    rows = [r for r in ledger.values() if r.get("lesson_id")]
    auto = [r for r in rows if r.get("status") == "published"]
    if not auto:
        return None  # provenance never started: nothing to enforce yet
    start = min(r["date"] for r in auto)
    traced = {r["lesson_id"] for r in rows}
    out = []
    for f in sorted(lessons_dir.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        d = lesson_date(f)
        if d and d > start and f.stem not in traced:
            out.append(f.stem)
    return out


# 0. this test is declared skeleton_only, so the per-instance gate skips it instead of
#    running it against a lesson-candidates/ that no instance has. Derived from the
#    manifest loader that owns the declaration, never restated here.
SELF = "q-system/.q-system/scripts/test/test-lessons-provenance.sh"
sys.path.insert(0, str(REPO / "q-system" / ".q-system" / "scripts"))
import capability_manifest as cm  # noqa: E402
if (REPO / cm.FRAGMENT_DIR).is_dir():
    declared = set((cm.load(str(REPO)) or {}).get("skeleton_only", []))
    check("manifest parsed a non-empty skeleton_only set", len(declared) > 0)
    check(f"{SELF} is declared skeleton_only", SELF in declared)
else:
    print("  INFO no capability fragment dir here; the declaration lives in the skeleton")

# 1. distill records lesson_id
T = Path(tempfile.mkdtemp())
inst = T / "projects" / "acme"; rca = inst / "q-system" / "output" / "rca"; rca.mkdir(parents=True)
r1 = rca / "rca-1.md"; r1.write_text("# clean rca\n\n## Structural root cause\ngeneric cause.\n")
h1 = hashlib.sha1(r1.read_text().encode()).hexdigest()[:16]
(T / "registry.json").write_text(json.dumps({"instances": [{"name": "acme", "path": str(inst)}]}))
(T / "distilled.json").write_text(json.dumps(
    {h1: {"title": "Guard shared mutations", "body": "Route every mutation through one writer.", "kind": "pattern"}}))
lessons, ledger_path = T / "lessons", T / "ledger.json"
subprocess.run(["python3", DISTILL, "--registry", str(T / "registry.json"), "--lessons-dir", str(lessons),
                "--held-dir", str(T / "held"), "--ledger", str(ledger_path),
                "--distilled-file", str(T / "distilled.json"), "--test-verify", "clean"],
               capture_output=True, text=True, check=True)
ledger = json.loads(ledger_path.read_text())
written = [p.stem for p in lessons.glob("*.md")]
check("fixture published exactly one lesson", len(written) == 1)
check("published ledger row names its lesson_id", ledger.get(h1, {}).get("lesson_id") in written)

# 2. the real repo: ledger + corpus as committed
real_ledger_path = REPO / "lesson-candidates" / ".processed.json"
real_lessons = REPO / "q-system" / "lessons"
check("ledger is present in the repo", real_ledger_path.is_file())
real_ledger = json.loads(real_ledger_path.read_text()) if real_ledger_path.is_file() else {}
check("ledger is non-empty (a parse returning nothing proves nothing)", len(real_ledger) > 0)
check("corpus is non-empty", any(real_lessons.glob("*.md")))
missing = untraced(real_lessons, real_ledger)
if missing is None:
    print("  INFO provenance not started in the committed ledger yet; invariant enforced from the first lesson_id row")
else:
    check(f"every lesson after provenance start has a ledger row (untraced: {missing})", missing == [])

# 3. negative self-test: the invariant must be able to go RED
N = Path(tempfile.mkdtemp()); nl = N / "lessons"; nl.mkdir()
(nl / "traced.md").write_text("---\nid: traced\nkind: pattern\ntitle: t\ndate: 2026-09-20\n---\n")
(nl / "orphan.md").write_text("---\nid: orphan\nkind: pattern\ntitle: o\ndate: 2026-09-21\n---\n")
(nl / "old.md").write_text("---\nid: old\nkind: pattern\ntitle: x\ndate: 2026-06-30\n---\n")
(nl / "ancient.md").write_text("---\nid: ancient\nkind: pattern\ntitle: a\ndate: 2026-02-01\n---\n")
neg = {"a": {"instance": "i", "status": "published", "date": "2026-09-19", "lesson_id": "traced"}}
check("negative: an untraced lesson after the start is caught, the old one is not", untraced(nl, neg) == ["orphan"])
check("negative: a ledger with no lesson_id rows enforces nothing", untraced(nl, {"a": {"date": "2026-09-19"}}) is None)
# A founder hand row dated with its lesson's own date (README line 34) must not drag the
# start backwards and turn the whole pre-provenance corpus red.
hand = dict(neg, h={"instance": "skeleton", "status": "hand-authored", "date": "2026-01-01", "lesson_id": "old"})
check("negative: a backdated hand-authored row traces its lesson and does not move the start",
      untraced(nl, hand) == ["orphan"])
check("negative: hand rows alone enforce nothing (the distiller defines the start)",
      untraced(nl, {"h": hand["h"]}) is None)

print("ALL PASS" if not fails else f"SOME FAILED: {fails}")
sys.exit(1 if fails else 0)
PY
