#!/usr/bin/env python3
# prompt-only-enforcement-skip: the strings handled here DESCRIBE defects found in rule and
# skill files. This script is itself the deterministic check (--check exits non-zero on drift);
# the unbacked-label problem is reported as finding R-25, not asserted here.
"""Prompt-audit ledger: render the founder-readable checklist, or verify it against the report.

  --render   rebuild prompt-audit-<date>-ledger.md from the JSON (JSON is source of truth)
  --check    derive finding ids from the REPORT and fail if the ledger does not match

Status lives in the JSON: open | in-progress | done | wontfix. Edit it there, then --render.
Paired with q-system/output/prompt-audit-<date>.md, which holds the evidence and the
replacement text for every id. Written 2026-09-02 by the /claude-api prompt-audit run.
"""
import json, re, sys, pathlib, datetime

ROOT = pathlib.Path(__file__).resolve().parents[3] / "q-system" / "output"
AUDIT_DATE = "2026-09-02"
JSON_PATH = ROOT / f"prompt-audit-{AUDIT_DATE}-ledger.json"
MD_PATH = ROOT / f"prompt-audit-{AUDIT_DATE}-ledger.md"
REPORT_PATH = ROOT / f"prompt-audit-{AUDIT_DATE}.md"
MERGED = {"R-3": "C-15", "R-13": "X-3", "R-24": "X-15"}


def load():
    if not JSON_PATH.exists():
        sys.exit(f"no ledger at {JSON_PATH}")
    return json.loads(JSON_PATH.read_text())


def render():
    doc = load()
    rows = doc["findings"]
    counts = {s: sum(1 for r in rows if r["severity"] == s) for s in ("high", "medium", "low", "flag")}
    done = sum(1 for r in rows if r["status"] == "done")
    L = ["<!-- voice-lint-skip -->",
         f"# Prompt audit ledger, {AUDIT_DATE}",
         "",
         f"Status index for the {len(rows)} findings in [{REPORT_PATH.name}]({REPORT_PATH.name}). "
         "That report has the evidence and the exact replacement text; this file is what you re-enter through.",
         "",
         f"**{done} of {len(rows)} done.** High {counts['high']}, medium {counts['medium']}, "
         f"low {counts['low']}, flag {counts['flag']}. "
         f"(The first pass said 83: that was the raw lane count, and {len(MERGED)} defects had been found by two lanes each.)",
         "",
         f"Regenerate after editing status in the JSON: `python3 {pathlib.Path(__file__).name} --render`",
         ""]
    for sev, title, blurb in [
        ("high", "High", "Verified by direct existence checks, not just by reading."),
        ("medium", "Medium", "Real, documented against the behavior of the model actually running, each with replacement text in the report."),
        ("low", "Low", "Worth doing, small blast radius."),
        ("flag", "Flag: a decision, not an edit", "No fix proposed. These need a call from the founder or Sana."),
    ]:
        sel = [r for r in rows if r["severity"] == sev]
        if not sel:
            continue
        L += [f"## {title} ({len(sel)})", "", blurb, ""]
        for r in sel:
            mark = "x" if r["status"] == "done" else " "
            tags = []
            if r.get("owner"):
                tags.append(r["owner"])
            if r["status"] not in ("open", "done"):
                tags.append(r["status"])
            if r.get("resolved_by"):
                tags.append(r["resolved_by"])
            tag = f" _[{', '.join(tags)}]_" if tags else ""
            L.append(f"- [{mark}] **{r['id']}**{tag} {r['what']}. `{r['files']}`")
        L.append("")
    L += ["## How to read a row", "",
          "The id (for example S-2) is the heading to search for in the report. Each finding there gives "
          "the text as it stands now, why it is stale for the model actually running, who wrote it and when, "
          "and replacement text ready to paste.", ""]
    MD_PATH.write_text("\n".join(L))
    print(f"rendered {MD_PATH}  ({done}/{len(rows)} done)")


def check():
    """Derive ids from the report; fail if the ledger does not cover exactly those."""
    doc = load()
    report = REPORT_PATH.read_text()
    head = set(re.findall(r"^### ([RSXC]-\d+)\b", report, re.M))
    bullet = set(re.findall(r"^- \*\*([RSXC]-\d+)\*\*", report, re.M))
    from_report = head | bullet
    if not from_report:
        sys.exit("FAIL parsed zero ids out of the report; the regex stopped matching")
    from_ledger = {f["id"] for f in doc["findings"]}
    ok = True
    # A ledger row with no heading of its own is legitimate in exactly two cases: an id
    # merged into another finding (the report writes it once, under the first id), and a
    # finding added after the report was written. Both must SAY so, or a typo would hide
    # here. Everything else in either direction is drift.
    exempt = set(MERGED.values()) | {f["id"] for f in doc["findings"] if f.get("added_after_report")}
    for f in doc["findings"]:
        if f["id"] in from_ledger - from_report and f["id"] not in exempt:
            pass  # falls through to the drift report below
    for label, diff in (("in report, absent from ledger", sorted(from_report - from_ledger)),
                        ("in ledger, absent from report", sorted(from_ledger - from_report - exempt))):
        if diff:
            ok = False
            print(f"FAIL {label}: {diff}")
    if len(from_ledger) != doc["distinct_findings"]:
        ok = False
        print(f"FAIL declared distinct_findings={doc['distinct_findings']} but {len(from_ledger)} rows")
    for f in doc["findings"]:
        if f["status"] == "done" and not f.get("resolved_by"):
            ok = False
            print(f"FAIL {f['id']} marked done with no resolved_by")
    print(f"report ids: {len(from_report)}   ledger ids: {len(from_ledger)}")
    print("PASS ledger and report agree" if ok else "FAIL ledger does not match report")
    return 0 if ok else 1


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if arg == "--render":
        render()
    elif arg == "--check":
        sys.exit(check())
    else:
        sys.exit(__doc__)
