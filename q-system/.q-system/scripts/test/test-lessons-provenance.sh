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
import hashlib, importlib.util, json, re, subprocess, sys, tempfile
from pathlib import Path
DISTILL, REPO = sys.argv[1], Path(sys.argv[2])

fails = []
def check(n, c): print(f"  {'PASS' if c else 'FAIL'} {n}"); fails.append(n) if not c else None


def lesson_files(lessons_dir):
    return [f for f in sorted(lessons_dir.glob("*.md")) if f.name.lower() != "readme.md"]


def lesson_date(path):
    """The lesson's date, from a date line that may carry anything after the date.

    Was anchored with `\\s*$`, so `date: 2026-09-25 (backfilled)` parsed as None and
    that lesson was exempt from the invariant forever (codex, PR #370 round 3). The
    exemption is now also visible: undated() below is its own check, green on the
    175-lesson corpus today and able to go red.
    """
    m = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", path.read_text(errors="ignore"), re.M)
    return m.group(1) if m else None


def undated(lessons_dir):
    """Lessons carrying no parseable date line: they cannot be placed against the start."""
    return [f.stem for f in lesson_files(lessons_dir) if lesson_date(f) is None]


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
    for f in lesson_files(lessons_dir):
        d = lesson_date(f)
        # >= not >: a run that dies on the FIRST provenance night writes no row that
        # night, so the start comes from a later night and its orphans date earlier
        # than it. Strict > exempted exactly the orphans the crash produces (codex,
        # PR #370 rounds 1 and 3). A lesson dated on the start day is in scope.
        if d and d >= start and f.stem not in traced:
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

# 1b. the row is DURABLE with the lesson it names. The loop writes each lesson file to
#     disk immediately; if the ledger is only written after the loop, a run that dies
#     mid-loop leaves published lessons with no row at all -- and the next night
#     re-distills those un-ledgered sources and ships `-2` duplicates of them
#     (codex, PR #370 round 3, reproduced with SIGKILL). Death is injected here by
#     raising out of write_lesson on the second source, which is the same shape: the
#     first lesson is durable, the run never reaches the post-loop ledger write.
C = Path(tempfile.mkdtemp())
cinst = C / "projects" / "acme"; crca = cinst / "q-system" / "output" / "rca"; crca.mkdir(parents=True)
cdist = {}
for i in (1, 2):
    p = crca / f"rca-{i}.md"
    p.write_text(f"# night rca {i}\n\n## Structural root cause\ngeneric cause {i}.\n")
    cdist[hashlib.sha1(p.read_text().encode()).hexdigest()[:16]] = {
        "title": f"Night lesson {i}", "body": "Route every mutation through one writer.", "kind": "pattern"}
(C / "registry.json").write_text(json.dumps({"instances": [{"name": "acme", "path": str(cinst)}]}))
(C / "distilled.json").write_text(json.dumps(cdist))
clessons, cledger_path = C / "lessons", C / "ledger.json"

spec = importlib.util.spec_from_file_location("distill_under_test", DISTILL)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
_real_write = mod.write_lesson
_seen = []


def _die_after_first(*a, **k):
    if _seen:
        raise SystemExit(-9)  # the process is killed; nothing after the loop runs
    _seen.append(1)
    return _real_write(*a, **k)


mod.write_lesson = _die_after_first
_argv = sys.argv
sys.argv = ["lessons-distill.py", "--registry", str(C / "registry.json"), "--lessons-dir", str(clessons),
            "--held-dir", str(C / "held"), "--ledger", str(cledger_path),
            "--distilled-file", str(C / "distilled.json"), "--test-verify", "clean"]
try:
    mod.main()
except BaseException:
    pass
finally:
    sys.argv = _argv
durable = sorted(p.stem for p in clessons.glob("*.md")) if clessons.is_dir() else []
crashed_ledger = json.loads(cledger_path.read_text()) if cledger_path.is_file() else {}
ctraced = {r.get("lesson_id") for r in crashed_ledger.values()}
check("crash fixture left exactly one lesson durable", len(durable) == 1)
check(f"a killed run leaves no untraced lesson (untraced: {[d for d in durable if d not in ctraced]})",
      all(d in ctraced for d in durable))

# 2. the real repo: ledger + corpus as committed
real_ledger_path = REPO / "lesson-candidates" / ".processed.json"
real_lessons = REPO / "q-system" / "lessons"
check("ledger is present in the repo", real_ledger_path.is_file())
real_ledger = json.loads(real_ledger_path.read_text()) if real_ledger_path.is_file() else {}
check("ledger is non-empty (a parse returning nothing proves nothing)", len(real_ledger) > 0)
check("corpus is non-empty", any(real_lessons.glob("*.md")))
# A lesson with no parseable date line cannot be placed against the start, so it is
# exempt from the invariant. That exemption is a check of its own rather than silence:
# 0 of the 175 lessons lack one today (measured 2026-09-23), so this is green now and
# goes red the moment a lesson could buy itself an exemption.
real_undated = undated(real_lessons)
check(f"every lesson carries a parseable date line (undated: {real_undated})", real_undated == [])
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
# An orphan dated ON the start day is the one a crash on the first provenance night
# produces. Strict > exempted it; >= catches it. Own directory so the assertion above
# keeps its exact expected set.
S = Path(tempfile.mkdtemp()); sl = S / "lessons"; sl.mkdir()
(sl / "traced.md").write_text("---\nid: traced\nkind: pattern\ntitle: t\ndate: 2026-09-20\n---\n")
(sl / "same-day-orphan.md").write_text("---\nid: same-day-orphan\nkind: pattern\ntitle: s\ndate: 2026-09-19\n---\n")
check("negative: an orphan dated on the provenance start day is caught",
      untraced(sl, neg) == ["same-day-orphan"])
# A date line carrying anything after the date still parses, so it cannot buy an
# exemption from the invariant.
D = Path(tempfile.mkdtemp()); dl = D / "lessons"; dl.mkdir()
(dl / "trailing.md").write_text("---\nid: trailing\nkind: pattern\ntitle: x\ndate: 2026-09-25 (backfilled)\n---\n")
check("negative: a date line with trailing text parses and stays in scope",
      lesson_date(dl / "trailing.md") == "2026-09-25" and untraced(dl, neg) == ["trailing"])
(dl / "no-date.md").write_text("---\nid: no-date\nkind: pattern\ntitle: n\n---\n")
check("negative: a lesson with no date line is named by undated(), a dated one is not",
      undated(dl) == ["no-date"])

print("ALL PASS" if not fails else f"SOME FAILED: {fails}")
sys.exit(1 if fails else 0)
PY
