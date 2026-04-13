# PRD: Ripple Graph — Karpathy LLM Wiki Pattern for Kipi

**Date:** 2026-04-12
**Author:** Assaf Kipnis
**Status:** Draft
**Priority:** P1 (high)
**Audit:** v2 — 6 findings addressed (section-level targeting removed, token math corrected, lint scope narrowed, source retention added, test harness added, engage deferred)

---

## 0. User Stories

### US-1: Consistent propagation after debrief
**As** a solo founder running debriefs after every call,
**I want** every insight I extract to automatically ripple to all canonical files it touches,
**so that** I never find stale talk tracks contradicting what I learned two conversations ago.
**Acceptance:** After debrief, `ripple-verify.py` exits 0. All targets in the ripple graph either updated or explicitly skipped with reason logged in changelog.

### US-2: Audit trail for canonical edits
**As** a founder working across multiple sessions,
**I want** a chronological log of every canonical file change with date, source, and workflow,
**so that** I can trace why a talk track changed and whether the change came from a real conversation or a model hallucination.
**Acceptance:** Every canonical edit during debrief/calibrate produces a changelog entry. `wc -l canonical/changelog.md` grows monotonically with canonical edits.

### US-3: Weekly structural lint
**As** a founder who can't manually cross-check 10+ canonical files,
**I want** a deterministic lint that catches structural issues: unvalidated markers in talk tracks, orphaned competitors, and stale changelog entries,
**so that** I catch the easy contradictions automatically and know where to look for harder ones.
**Acceptance:** `content-lint.py` exits 2 when talk-tracks contain `{{UNVALIDATED}}` markers. Exits 1 when competitors in landscape are missing from objections. Runs every Friday in `/q-wrap`. Does NOT claim to catch semantic contradictions (that's v1.1).

### US-4: Raw source preservation
**As** a founder who sometimes realizes the debrief missed something days later,
**I want** the original conversation transcript saved before extraction begins,
**so that** I can re-read the raw source and extract what was missed without relying on memory.
**Acceptance:** `sources/YYYY-MM-DD-person-name.md` exists before any changelog entry for that debrief. File is immutable after creation. Auto-deleted after 90 days.

### US-5: Calibrate ripple check
**As** a founder updating current-state.md with a new capability,
**I want** the system to tell me which other files might be inconsistent now,
**so that** I don't forget to update talk tracks, objections, and competitive landscape.
**Acceptance:** `changelog-write.py` returns `ripple_targets` list. Model checks each target. `ripple-verify.py` exits 0 before calibrate completes.

### US-6: Zero additional token cost for deterministic operations
**As** a token-conscious founder,
**I want** the ripple graph lookup, changelog write, and verification to be Python scripts, not LLM calls,
**so that** the only tokens spent are on reading/writing the actual canonical file content, not on figuring out which files to check.
**Acceptance:** `changelog-write.py`, `ripple-verify.py`, and `content-lint.py` use zero LLM tokens. All logic is regex/JSON parsing. The model's only job is reading targets and deciding if an update is needed.

## 1. Problem

Information enters the system through four workflows: debrief, calibrate, engage, and morning routine. Each workflow routes insights to one or two canonical files. It does not propagate to all files the insight touches.

- **Evidence:** Founder reports inconsistent propagation depth. A prospect saying "we already use CrowdStrike for this" updates `objections.md` but not `competitive-landscape.md`, `talk-tracks.md`, `market-intelligence.md`, or `discovery.md`. The debrief template defines 11 routing targets (lines 232-317 of `methodology/debrief-template.md`), but routing depends on the model noticing downstream implications in a single session. Sometimes it does. Sometimes it doesn't.
- **Impact:** Canonical files drift apart. Talk tracks claim things current-state doesn't support. Objection responses reference capabilities that changed. Market intelligence misses signals that entered through debrief. The founder encounters stale or contradictory information across sessions.
- **Root cause:** No deterministic mechanism enforces cross-file consistency. Propagation is LLM-attention-dependent, which means it varies by session length, context load, and model behavior. The system has no change ledger, no content lint, and no raw source archive. These are the three structural gaps identified by Karpathy's LLM Wiki pattern that Kipi does not yet implement.

## 2. Scope

### In Scope
- Deterministic ripple graph: a JSON map defining which canonical files must be checked when any canonical file changes (file-level edges only in v1)
- Change ledger: append-only log of every canonical file edit with date, source, and what changed
- Structural lint: a script that checks for markers, orphaned references, and staleness (NOT semantic contradictions)
- Raw source archive: conversation transcripts saved before debrief extraction, with 90-day retention
- Ripple enforcement: soft-gate verification that surfaces missing propagation targets
- Test harness: automated regression script wired into `kipi check`

### Out of Scope
- Obsidian graph view integration (free if Obsidian is the vault viewer, no build needed)
- Auto-generated `index.md` catalog (useful but independent, separate PRD)
- Changes to the morning pipeline agent architecture (ripple graph is a post-ingest layer, not a pipeline change)
- Rewriting the debrief template (the template is good, the enforcement is the gap)
- Semantic lint / cross-file claim comparison (v1.1, requires Haiku LLM pass)
- Section-level ripple targeting (v1.1, requires header validation to avoid silent failures)
- Engage workflow changelog integration (separate follow-up PRD after v1 data)

### Non-Goals
- Replacing the debrief's 11-target routing with an automated system. The debrief routing stays. The ripple graph is a verification layer that catches what the routing missed.
- Building a full knowledge graph database. The ripple graph is a static JSON map, not a graph DB.
- Making propagation fully automatic without model involvement. The model still writes the updates. The script tells it which files to check and verifies it actually did.
- Catching semantic contradictions in v1. "Structural lint" catches markers and orphans. "Semantic lint" (v1.1) catches claim-vs-claim drift using a cheap LLM pass.

## 3. Changes

### Change 1: Ripple Graph Definition

- **What:** A JSON file mapping every canonical file to ALL other files that could be affected when it changes. File-level edges only (no section targeting in v1).
- **Where:** `q-system/.q-system/ripple-graph.json`
- **Why:** No deterministic mechanism exists to tell the model "you changed X, now check Y and Z." The model must discover this through attention, which is unreliable. (Section 1, root cause)
- **v1 design decision:** File-level only, not section-level. Section-level targeting requires matching graph keys to markdown headers. If a founder renames a section, the graph silently breaks. A system that fails silently is worse than no system. Section-level precision is a v1.1 optimization after 30 days of changelog data showing which files produce noise.
- **Exact change:**

```json
{
  "_version": 1,
  "_description": "When SOURCE changes, check each TARGET for consistency. File-level edges only (v1). Section-level targeting deferred to v1.1 with header validation.",
  "graph": {
    "canonical/current-state.md": [
      "canonical/talk-tracks.md",
      "canonical/objections.md",
      "my-project/competitive-landscape.md",
      "canonical/market-intelligence.md",
      "canonical/discovery.md"
    ],
    "canonical/objections.md": [
      "canonical/talk-tracks.md",
      "canonical/discovery.md",
      "my-project/competitive-landscape.md"
    ],
    "canonical/talk-tracks.md": [
      "canonical/objections.md",
      "canonical/market-intelligence.md",
      "my-project/current-state.md"
    ],
    "canonical/market-intelligence.md": [
      "canonical/talk-tracks.md",
      "my-project/icp.md",
      "my-project/icp-signals.md",
      "my-project/competitive-landscape.md",
      "canonical/objections.md"
    ],
    "canonical/discovery.md": [
      "canonical/objections.md",
      "canonical/talk-tracks.md",
      "my-project/current-state.md"
    ],
    "my-project/competitive-landscape.md": [
      "canonical/objections.md",
      "canonical/talk-tracks.md",
      "canonical/market-intelligence.md"
    ],
    "my-project/relationships.md": [
      "my-project/progress.md"
    ],
    "canonical/pricing-framework.md": [
      "canonical/talk-tracks.md",
      "canonical/objections.md"
    ],
    "canonical/verticals.md": [
      "canonical/talk-tracks.md",
      "my-project/icp.md",
      "canonical/market-intelligence.md"
    ],
    "canonical/engagement-playbook.md": [],
    "canonical/lead-lifecycle-rules.md": [],
    "canonical/content-intelligence.md": [
      "canonical/market-intelligence.md",
      "marketing/content-themes.md"
    ]
  }
}
```

- **Scope:** Skeleton (all instances via `kipi update`). No instance-local overrides (YAGNI).

### Change 2: Change Ledger

- **What:** An append-only markdown file that logs every canonical file edit with timestamp, source workflow, file changed, and one-line summary
- **Where:** `q-system/canonical/changelog.md`
- **Why:** No audit trail exists for canonical edits. The founder cannot see what changed, when, or why across sessions. Morning logs track pipeline execution, not content changes. (Section 1, evidence)
- **Exact change:**

```markdown
# Canonical Changelog

> Append-only. Never edit or delete entries. Auto-pruned to last 60 days by md-prune.py. Line budget: 200.

## Format <!-- pin -->

```
### YYYY-MM-DD | workflow | file
One-line summary of what changed and why.
Source: [person/conversation/market signal/founder directive]
```

<!-- entries below this line -->
```

- **Scope:** Skeleton. The changelog is instance-specific content but the file and format ship with the skeleton.

### Change 3: Changelog Writer Script

- **What:** A Python script that appends a structured entry to the changelog and returns the ripple targets for the changed file
- **Where:** `q-system/.q-system/scripts/changelog-write.py`
- **Why:** The model should not manually format changelog entries or look up ripple targets. Both operations are deterministic and must be scripted. (Root CLAUDE.md: "prefer deterministic, script-based solutions over LLM-instruction fixes")
- **Exact change:**

```python
#!/usr/bin/env python3
"""
Append a changelog entry and return ripple targets.

Usage:
    python3 changelog-write.py <file> <workflow> <summary> [--source SOURCE]

Example:
    python3 changelog-write.py canonical/objections.md debrief \
        "Added CrowdStrike competitive objection with differentiation response" \
        --source "Josh Martinez - 2026-04-12 - conversation"

Output (stdout JSON):
    {"logged": true, "ripple_targets": ["canonical/talk-tracks.md", ...]}

Exit 0 = success
Exit 1 = invalid arguments
Exit 2 = ripple-graph.json missing or malformed
"""

import json
import os
import sys
from datetime import date

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CHANGELOG = os.path.join(QROOT, "canonical", "changelog.md")
RIPPLE_GRAPH = os.path.join(QROOT, ".q-system", "ripple-graph.json")


def load_ripple_graph():
    try:
        with open(RIPPLE_GRAPH) as f:
            return json.load(f)["graph"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print(f"ERROR: ripple-graph.json: {e}", file=sys.stderr)
        sys.exit(2)


def get_ripple_targets(graph, file_key):
    targets = graph.get(file_key, [])
    # Never include the source file as its own target
    return sorted(t for t in targets if t != file_key)


def append_changelog(file_key, workflow, summary, source):
    changelog_dir = os.path.dirname(CHANGELOG)
    if not os.path.isdir(changelog_dir):
        print(f"ERROR: directory {changelog_dir} does not exist", file=sys.stderr)
        sys.exit(2)
    today = date.today().isoformat()
    entry = f"\n### {today} | {workflow} | {file_key}\n{summary}\nSource: {source}\n"
    with open(CHANGELOG, "a") as f:
        f.write(entry)


def main():
    if len(sys.argv) < 4:
        print("Usage: changelog-write.py <file> <workflow> <summary> [--source SOURCE]",
              file=sys.stderr)
        sys.exit(1)

    file_key = sys.argv[1]
    workflow = sys.argv[2]
    summary = sys.argv[3]
    source = "founder directive"

    if "--source" in sys.argv:
        idx = sys.argv.index("--source")
        if idx + 1 < len(sys.argv):
            source = sys.argv[idx + 1]

    graph = load_ripple_graph()
    targets = get_ripple_targets(graph, file_key)
    append_changelog(file_key, workflow, summary, source)

    result = {"logged": True, "ripple_targets": targets}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
```

- **Scope:** Skeleton.

### Change 4: Structural Lint Script

- **What:** A Python script that checks for structural issues across canonical files: unvalidated markers, orphaned references, and changelog staleness. Does NOT check semantic contradictions (that's v1.1).
- **Where:** `q-system/.q-system/scripts/content-lint.py`
- **Why:** No mechanism checks structural consistency. Talk tracks can contain `{{UNVALIDATED}}` markers (errors). Competitors can appear in landscape but not objections (orphans). Changelog entries can go stale (staleness). These are deterministic checks. Semantic checks ("talk tracks claim X but current-state says Y") require an LLM pass and are deferred. (Section 1, impact)
- **Exact change:**

```python
#!/usr/bin/env python3
"""
Structural lint: check canonical files for markers, orphans, and staleness.

Checks (structural only, no semantic analysis):
1. Talk tracks containing {{UNVALIDATED}} or {{NEEDS_PROOF}} markers (ERROR)
2. Competitive landscape headers not matching any objections header (WARNING)
3. Changelog entries older than 60 days (WARNING, collapsed to single count)
4. Excessive unvalidated markers in non-discovery files (WARNING if >3)

NOT checked (v1.1 semantic lint):
- Talk tracks claiming capabilities not in current-state.md
- Objection responses referencing proof points that don't exist
- Cross-file claim contradictions

Usage:
    python3 content-lint.py [--json]

Exit 0 = clean
Exit 1 = warnings found
Exit 2 = errors found
"""

import json
import os
import re
import sys
from datetime import date, timedelta

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

FILES = {
    "current_state": os.path.join(QROOT, "my-project", "current-state.md"),
    "talk_tracks": os.path.join(QROOT, "canonical", "talk-tracks.md"),
    "objections": os.path.join(QROOT, "canonical", "objections.md"),
    "competitive": os.path.join(QROOT, "my-project", "competitive-landscape.md"),
    "market_intel": os.path.join(QROOT, "canonical", "market-intelligence.md"),
    "discovery": os.path.join(QROOT, "canonical", "discovery.md"),
    "changelog": os.path.join(QROOT, "canonical", "changelog.md"),
    "proof_points": os.path.join(QROOT, "marketing", "assets", "proof-points.md"),
}


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def extract_headers(content, level="## "):
    """Extract markdown headers at a given level."""
    return [
        line.lstrip("#").strip()
        for line in content.splitlines()
        if line.startswith(level)
    ]


def extract_unvalidated_markers(content):
    return re.findall(r"\{\{(UNVALIDATED|NEEDS_PROOF)\}\}", content)


def check_changelog_staleness(content):
    cutoff = date.today() - timedelta(days=60)
    stale_count = 0
    for match in re.finditer(r"### (\d{4}-\d{2}-\d{2})", content):
        try:
            entry_date = date.fromisoformat(match.group(1))
            if entry_date < cutoff:
                stale_count += 1
        except ValueError:
            pass
    if stale_count > 0:
        return [f"{stale_count} changelog entries older than 60 days. Run md-prune.py."]
    return []


def check_orphaned_competitors(competitive, objections):
    warnings = []
    comp_headers = extract_headers(competitive, "## ")
    obj_headers = {h.lower() for h in extract_headers(objections, "## ")}
    obj_headers.update({h.lower() for h in extract_headers(objections, "### ")})
    for header in comp_headers:
        name = header.strip().lower()
        if name and len(name) > 2 and name not in obj_headers:
            warnings.append(
                f"Competitor '{header}' in competitive-landscape.md "
                f"but no matching header in objections.md"
            )
    return warnings


def check_unvalidated_in_talk_tracks(talk_tracks):
    errors = []
    markers = extract_unvalidated_markers(talk_tracks)
    if markers:
        errors.append(
            f"talk-tracks.md contains {len(markers)} unvalidated marker(s). "
            f"Talk tracks must be proven language only."
        )
    return errors


def main():
    json_mode = "--json" in sys.argv
    files = {k: read(v) for k, v in FILES.items()}

    warnings = []
    errors = []

    errors.extend(check_unvalidated_in_talk_tracks(files["talk_tracks"]))

    warnings.extend(check_orphaned_competitors(
        files["competitive"], files["objections"]
    ))

    warnings.extend(check_changelog_staleness(files["changelog"]))

    for name, content in files.items():
        if name in ("changelog", "discovery"):
            continue
        count = len(extract_unvalidated_markers(content))
        if count > 3:
            warnings.append(
                f"{name} has {count} unvalidated markers. Review and resolve."
            )

    if json_mode:
        print(json.dumps({
            "errors": errors,
            "warnings": warnings,
            "clean": len(errors) == 0 and len(warnings) == 0,
        }, indent=2))
    else:
        if errors:
            print("ERRORS:")
            for e in errors:
                print(f"  x {e}")
        if warnings:
            print("WARNINGS:")
            for w in warnings:
                print(f"  ! {w}")
        if not errors and not warnings:
            print("Content lint: clean")

    if errors:
        sys.exit(2)
    elif warnings:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
```

- **Scope:** Skeleton.

### Change 5: Ripple Verification Script

- **What:** A Python script that reads today's changelog entries, looks up ripple targets for each, and checks if those targets also have changelog entries
- **Where:** `q-system/.q-system/scripts/ripple-verify.py`
- **Why:** The ripple graph is useless without enforcement. This script is the gate that checks whether the model actually propagated changes to all affected files. (Section 1, root cause)
- **Exact change:**

```python
#!/usr/bin/env python3
"""
Verify that all ripple targets were addressed after canonical edits.

Usage:
    python3 ripple-verify.py <changelog-path> <date> [--json]

Reads today's changelog entries, looks up ripple targets for each,
checks if those targets also have changelog entries for today.

Exit 0 = all targets addressed
Exit 1 = missing targets (printed to stdout)
Exit 2 = ripple-graph.json missing or malformed
"""

import json
import os
import re
import sys

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
RIPPLE_GRAPH = os.path.join(QROOT, ".q-system", "ripple-graph.json")


def load_ripple_graph():
    try:
        with open(RIPPLE_GRAPH) as f:
            return json.load(f)["graph"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print(f"ERROR: ripple-graph.json: {e}", file=sys.stderr)
        sys.exit(2)


def parse_changelog_entries(changelog_path, target_date):
    entries = []
    files_touched = set()
    with open(changelog_path) as f:
        content = f.read()

    pattern = rf"### {re.escape(target_date)} \| ([^\|]+) \| ([^\n]+)"
    for match in re.finditer(pattern, content):
        file_key = match.group(2).strip()
        entries.append({"file": file_key})
        files_touched.add(file_key)

    return entries, files_touched


def get_all_ripple_targets(graph, entries):
    required = {}
    for entry in entries:
        file_key = entry["file"]
        targets = graph.get(file_key, [])
        for t in targets:
            if t != file_key:
                if t not in required:
                    required[t] = []
                required[t].append(file_key)
    return required


def main():
    if len(sys.argv) < 3:
        print("Usage: ripple-verify.py <changelog-path> <date> [--json]",
              file=sys.stderr)
        sys.exit(1)

    changelog_path = sys.argv[1]
    target_date = sys.argv[2]
    json_mode = "--json" in sys.argv

    graph = load_ripple_graph()
    entries, files_touched = parse_changelog_entries(changelog_path, target_date)

    if not entries:
        if json_mode:
            print(json.dumps({"status": "no_entries", "date": target_date}))
        else:
            print(f"No changelog entries for {target_date}. Nothing to verify.")
        sys.exit(0)

    required = get_all_ripple_targets(graph, entries)

    missing = {}
    for target, sources in required.items():
        if target not in files_touched:
            missing[target] = sources

    if json_mode:
        print(json.dumps({
            "date": target_date,
            "entries": len(entries),
            "files_touched": sorted(files_touched),
            "ripple_targets_required": len(required),
            "missing": missing,
            "complete": len(missing) == 0,
        }, indent=2))
    else:
        if missing:
            print(f"INCOMPLETE RIPPLE ({len(missing)} targets not addressed):\n")
            for target, sources in missing.items():
                print(f"  x {target}")
                for s in sources:
                    print(f"      triggered by: {s}")
            print(f"\nRun content-lint.py after addressing these.")
        else:
            print(f"Ripple complete. {len(entries)} edits, "
                  f"{len(required)} targets, all addressed.")

    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
```

- **Scope:** Skeleton.

### Change 6: Raw Source Archive Directory

- **What:** A directory for saving conversation transcripts before extraction, with 90-day retention
- **Where:** `q-system/sources/` (gitignored, instance-specific content)
- **Why:** Conversation transcripts vanish after debrief extraction. If the debrief missed something or the model made an error, the raw source is gone. Karpathy's pattern treats raw sources as an immutable layer the system can re-read. (Section 1, evidence)
- **Retention policy:** Sources older than 90 days are deleted by `/q-wrap` monthly check (1st of month). After 90 days, the canonical files are the record. The raw source served its purpose.
- **Exact change:**

Create `q-system/sources/.gitkeep` and add `q-system/sources/*.md` to `.gitignore`.

Debrief template addition (append after line 5 of `methodology/debrief-template.md`):

```markdown
## Raw Source Archival (before extraction)

Before running the template, save the raw conversation transcript:
1. Write the full transcript to `sources/YYYY-MM-DD-person-name.md`
2. Frontmatter: `date`, `person`, `company`, `workflow: debrief`
3. This file is immutable after creation. Never edit it.
4. Proceed with extraction only after the source is saved.
5. Retention: 90 days. Sources older than 90 days auto-deleted on 1st of month via /q-wrap.
```

- **Scope:** Skeleton (directory structure + template addition). Content is instance-specific and gitignored.

### Change 7: Debrief Integration

- **What:** Add ripple verification as the final gate in the debrief quality checklist
- **Where:** `q-system/methodology/debrief-template.md` (append to Quality Checklist, after line 318)
- **Why:** The debrief is the highest-frequency ingest event. If ripple verification works here, it works everywhere. (Section 1, evidence)
- **Exact change:**

Append to the Quality Checklist:

```markdown
- [ ] **Ripple verification complete:**
  - [ ] Every canonical file edit logged via `changelog-write.py`
  - [ ] `ripple-verify.py` run with today's date
  - [ ] If exit 0: done
  - [ ] If exit 1 (soft gate): address missing targets or log skip reason in changelog. Do NOT block debrief completion.
```

- **Scope:** Skeleton.

### Change 8: Calibrate Integration

- **What:** Add changelog + ripple verification to `/q-calibrate` workflow
- **Where:** `.claude/rules/` (new rule or addition to existing rule that governs calibrate behavior)
- **Why:** Calibrate is the second-highest-frequency ingest event. A founder updating `current-state.md` with a new capability must see "also check talk-tracks, objections, competitive-landscape" as a deterministic prompt, not an LLM attention gamble.
- **Exact change:**

Add to the calibrate workflow instructions (wherever `/q-calibrate` is defined):

```markdown
## Post-Edit Ripple Check (ENFORCED)

After every canonical file edit during calibrate:
1. Run `python3 q-system/.q-system/scripts/changelog-write.py <file> calibrate "<summary>" --source "founder directive"`
2. Read the `ripple_targets` from stdout
3. For each target: read the file, check if the edit creates an inconsistency, update if needed
4. After all edits: run `python3 q-system/.q-system/scripts/ripple-verify.py q-system/canonical/changelog.md YYYY-MM-DD`
5. Exit 0 = done. Exit 1 = surface missing targets (soft gate). Do NOT block calibrate.
```

- **Scope:** Skeleton.

### Change 9: Weekly Structural Lint in /q-wrap

- **What:** Add content-lint.py to the `/q-wrap` evening health check. Add monthly source pruning.
- **Where:** Wherever `/q-wrap` is defined (skill or rule file)
- **Why:** Even with per-edit ripple checks, drift accumulates. A weekly lint catches structural issues. Monthly source pruning prevents unbounded disk growth.
- **Exact change:**

Add to `/q-wrap`:

```markdown
## Structural Lint (weekly, runs on Fridays)

If today is Friday:
1. Run `python3 q-system/.q-system/scripts/content-lint.py --json`
2. If exit 0: log "Content lint: clean" to wrap output
3. If exit 1: surface warnings to founder with one-line summaries
4. If exit 2: surface errors as blockers. These are structural issues that need resolution before next week.

## Source Archive Pruning (monthly, runs on 1st)

If today is the 1st of the month:
1. Delete files in `q-system/sources/` older than 90 days
2. Log count of deleted files to wrap output
```

- **Scope:** Skeleton.

### Change 10: Ripple Test Harness

- **What:** A single Python script that runs all Phase 1 regression tests (script isolation + graph validation) and exits 0/1
- **Where:** `q-system/.q-system/scripts/test-ripple.py`
- **Why:** 10 manual regression checks will not be run. A human remembering to run 5 bash commands after every change is not a system. Wire it into `kipi check` so it runs automatically.
- **Exact change:**

```python
#!/usr/bin/env python3
"""
Ripple system regression tests. Run automatically via `kipi check`.

Tests:
1. ripple-graph.json is valid JSON with "graph" key
2. All source files in graph exist on disk
3. All target files in graph exist on disk
4. No file lists itself as a ripple target
5. changelog-write.py runs without import errors
6. content-lint.py runs without import errors
7. ripple-verify.py runs without import errors

Exit 0 = all pass
Exit 1 = failures (printed to stdout)
"""

import json
import os
import subprocess
import sys

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.dirname(__file__)
RIPPLE_GRAPH = os.path.join(QROOT, ".q-system", "ripple-graph.json")

failures = []


def test(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        msg = f"  FAIL: {name}" + (f" ({detail})" if detail else "")
        print(msg)
        failures.append(msg)


def test_graph_valid():
    try:
        with open(RIPPLE_GRAPH) as f:
            data = json.load(f)
        test("graph is valid JSON", True)
        test("graph has 'graph' key", "graph" in data,
             "missing top-level 'graph' key")
        return data.get("graph", {})
    except (FileNotFoundError, json.JSONDecodeError) as e:
        test("graph is valid JSON", False, str(e))
        return {}


def test_files_exist(graph):
    missing = []
    for src, targets in graph.items():
        if not os.path.exists(os.path.join(QROOT, src)):
            missing.append(src)
        for tgt in targets:
            if not os.path.exists(os.path.join(QROOT, tgt)):
                missing.append(tgt)
    test("all referenced files exist", len(missing) == 0,
         f"missing: {missing}")


def test_no_self_reference(graph):
    self_refs = []
    for src, targets in graph.items():
        if src in targets:
            self_refs.append(src)
    test("no self-references", len(self_refs) == 0,
         f"self-referencing: {self_refs}")


def test_script_runs(name, script_path):
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=10
        )
        # Scripts with no args should exit 1 (usage) or 0, not crash
        test(f"{name} runs without crash", result.returncode in (0, 1),
             f"exit {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        test(f"{name} runs without crash", False, str(e))


def main():
    print("Ripple system regression tests:\n")

    graph = test_graph_valid()
    if graph:
        test_files_exist(graph)
        test_no_self_reference(graph)

    test_script_runs("changelog-write.py",
                     os.path.join(SCRIPTS, "changelog-write.py"))
    test_script_runs("content-lint.py",
                     os.path.join(SCRIPTS, "content-lint.py"))
    test_script_runs("ripple-verify.py",
                     os.path.join(SCRIPTS, "ripple-verify.py"))

    print(f"\n{7 - len(failures)}/7 passed, {len(failures)} failed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
```

- **Scope:** Skeleton. Wire into `kipi check` alongside `validate-separation.py`.

## 4. Change Interaction Matrix

| Change A | Change B | Interaction | Resolution |
|----------|----------|-------------|------------|
| Ripple Graph (1) | Changelog Writer (3) | Writer reads graph to return targets | Writer depends on graph. Graph ships first. |
| Changelog Writer (3) | Ripple Verify (5) | Verify reads entries written by Writer | Same changelog file. Writer appends, Verify reads. No conflict. |
| Structural Lint (4) | Ripple Verify (5) | Both check canonical health | Different scopes. Lint checks content structure. Verify checks process. Run lint after verify. |
| Raw Source Archive (6) | Debrief Integration (7) | Archive before extraction, verify after | Sequential by design. Archive is step 1, verify is last step. |
| Debrief Integration (7) | Calibrate Integration (8) | Both use changelog-write + ripple-verify | Same scripts, different workflow argument. No conflict. |
| Structural Lint (4) | Weekly Wrap (9) | Wrap calls lint | Wrap is caller, lint is callee. No conflict. |
| Test Harness (10) | All scripts (3-5) | Harness tests all scripts | Harness is read-only. Does not modify state. |

## 5. Files Modified

| File | Change Type | Lines Added | Lines Removed |
|------|------------|-------------|---------------|
| `q-system/.q-system/ripple-graph.json` | Add | ~55 | 0 |
| `q-system/canonical/changelog.md` | Add | ~15 | 0 |
| `q-system/.q-system/scripts/changelog-write.py` | Add | ~85 | 0 |
| `q-system/.q-system/scripts/content-lint.py` | Add | ~130 | 0 |
| `q-system/.q-system/scripts/ripple-verify.py` | Add | ~100 | 0 |
| `q-system/.q-system/scripts/test-ripple.py` | Add | ~95 | 0 |
| `q-system/sources/.gitkeep` | Add | 0 | 0 |
| `.gitignore` | Edit | +1 | 0 |
| `q-system/methodology/debrief-template.md` | Edit | +18 | 0 |
| `/q-calibrate` workflow | Edit | +10 | 0 |
| `/q-wrap` workflow | Edit | +14 | 0 |
| `.claude/rules/folder-structure.md` | Edit | +4 | 0 |
| `.claude/rules/md-hygiene.md` | Edit | +1 | 0 |

## 6. Test Cases

### [Change 1: Ripple Graph] Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 1.1 | DET | Graph is valid JSON | `python3 -c "import json; json.load(open(...))"` | Exit 0 | No parse errors |
| 1.2 | DET | Every file in graph exists | `test-ripple.py` check | All exist | Exit 0 |
| 1.3 | DET | No self-references | `test-ripple.py` check | Zero | Exit 0 |
| 1.4 | DET | Leaf files return empty targets | Look up engagement-playbook | `[]` | Empty list |

### [Change 3: Changelog Writer] Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 3.1 | DET | Basic write | `changelog-write.py canonical/objections.md debrief "Added objection" --source "Josh"` | `logged: true`, targets list | Exit 0, targets include talk-tracks, discovery, competitive-landscape |
| 3.2 | DET | Missing ripple graph | Delete graph, run writer | Error | Exit 2 |
| 3.3 | DET | File not in graph | `changelog-write.py canonical/foo.md debrief "test"` | Empty targets | Exit 0, `ripple_targets: []` |
| 3.4 | DET | Summary with spaces | `changelog-write.py canonical/objections.md debrief "Long summary with spaces" --source "Person Name"` | Full summary in entry | Exit 0, changelog has full text |

### [Change 4: Structural Lint] Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 4.1 | DET | Clean files | No markers, no orphans | "Content lint: clean" | Exit 0 |
| 4.2 | DET | Unvalidated in talk tracks | Add `{{UNVALIDATED}}` | Error | Exit 2 |
| 4.3 | DET | Stale changelog (collapsed) | 10 entries >60 days | Single warning "10 entries" | Exit 1, one warning line |
| 4.4 | DET | Discovery excluded | 5x `{{UNVALIDATED}}` in discovery | No warning | Exit 0 |
| 4.5 | DET | Orphaned competitor (header match) | Competitor header in landscape, body-only in objections | Warning | Exit 1, header-to-header match only |

### [Change 5: Ripple Verify] Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 5.1 | DET | All targets addressed | Entries for source + all targets | "Ripple complete" | Exit 0 |
| 5.2 | DET | Missing targets | Entry for objections, not talk-tracks | Lists missing | Exit 1 |
| 5.3 | DET | No entries for date | No entries | "No entries" | Exit 0 |
| 5.4 | DET | Missing graph file | Delete graph | Error | Exit 2 |

### [Change 7: Debrief Integration] Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 7.1 | BEH | Full debrief with ripple | Test conversation | Changelog + verify exit 0 | Verified over 3 debriefs |
| 7.2 | BEH | Soft gate: missing targets | Model skips a target | Verify exit 1, warning surfaced, debrief completes | Debrief NOT blocked |
| 7.3 | BEH | Source saved before extraction | Paste transcript | Source file timestamp < first changelog timestamp | File order correct |

### [Change 10: Test Harness] Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 10.1 | DET | All pass | Valid graph, all files exist | "7/7 passed" | Exit 0 |
| 10.2 | DET | Missing file in graph | Remove a target file | "FAIL: all referenced files exist" | Exit 1 |

## 7. Regression Tests

| # | What to Verify | How to Verify | Pass Criteria |
|---|----------------|---------------|---------------|
| R-1 | Debrief routing (all 11 targets) | Run debrief, check all routing targets | All 11 populated. No target skipped. |
| R-2 | Morning pipeline unaffected | Run `/q-morning` + audit | Audit passes. No phase reads changelog or ripple-graph. |
| R-3 | md-prune.py handles changelog | Add to md-hygiene (200 lines). Test with 250-line changelog. | Oldest entries archived. Pinned format preserved. |
| R-4 | canonical-digest.py works | Run digest with changelog in canonical/ | Exit 0. Changelog NOT in digest. |
| R-5 | token-guard counters | 3+ edits triggering changelog-write | Bash calls count as tool calls, NOT MCP calls. |
| R-6 | Calibrate with zero changes | Run calibrate, no edits | No entries. "No entries." Exit 0. |
| R-7 | /q-wrap on non-Friday | Wrap on Tuesday | No lint output. |
| R-8 | kipi update propagation | `kipi update --dry` | Shows graph, changelog, 4 scripts, sources/.gitkeep. |
| R-9 | PostCompact during debrief | Trigger compaction | Changelog on disk survives. Model can resume. |
| R-10 | validate-separation.py | `kipi check` | Zero violations. |

## 7a. Code Audit

### changelog-write.py

| Check | Status | Finding |
|-------|--------|---------|
| QROOT resolution | PASS | `os.path.join(dirname, "..", "..")` matches codebase convention |
| Exit codes (0/1/2) | PASS | Matches canonical-digest, verify-bus |
| Missing changelog dir | FIXED | Directory existence check before append |
| Spaces in CLI args | DOCUMENTED | Shell must quote. Test 3.4 covers. |
| Concurrent writes | PASS | Single-user system. Append atomic enough. |
| No secrets | PASS | No env vars, no network. |

### content-lint.py

| Check | Status | Finding |
|-------|--------|---------|
| Orphaned competitor check | FIXED | Header-to-header matching, not body text. "AI" no longer false-matches. |
| Staleness noise | FIXED | Collapsed to single count warning. |
| discovery.md exclusion | FIXED | Excluded from >3 threshold. Discovery holds unvalidated by design. |
| Scope naming | FIXED | Renamed to "structural lint." Docstring explicitly states what is NOT checked. |

### ripple-verify.py

| Check | Status | Finding |
|-------|--------|---------|
| Changelog regex | FIXED | Simplified to match file-level format (no section field in v1). |
| Missing graph file | FIXED | try/except with exit 2, matching convention. |
| Trust model | DOCUMENTED | Changelog entry = file was edited. Acceptable for soft gate. |

### ripple-graph.json

| Check | Status | Finding |
|-------|--------|---------|
| All files exist | NEEDS VERIFY | test-ripple.py checks this automatically. |
| No circular ripples | PASS | Verify checks one depth only. No infinite loop. |
| Section keys removed | FIXED | v1 is file-level only. No stale-section risk. |
| marketing/ path | DOCUMENTED | QROOT-relative. Acceptable. |

## 7b. Token Audit

### Per-operation cost

| Operation | Mechanism | Tokens in | Tokens out | Notes |
|-----------|-----------|-----------|------------|-------|
| Ripple lookup | changelog-write.py (Bash) | ~50 | 0 | Deterministic |
| Changelog append | changelog-write.py (Bash) | ~70 | 0 | Deterministic |
| Read ripple target | Read tool | ~200-500/file | 0 | Real cost. Model re-reads source too. |
| Decide on target | Model judgment | ~200-400 (source re-read) | ~50-100 | Only LLM cost. Model compares source edit to target. |
| Write update | Edit tool | ~100 | ~50-200 | Only if needed. Most targets: "no change." |
| Ripple verify | ripple-verify.py (Bash) | ~60 | 0 | Deterministic |
| Content lint | content-lint.py (Bash) | ~60 | 0 | Weekly. Negligible. |

### Worst case: debrief touches 4 files

Model re-reads source file when comparing each target. This doubles the "read target" cost because the source context is needed alongside the target.

| Step | Tokens in | Tokens out | Cumulative |
|------|-----------|------------|------------|
| 4x changelog-write | 480 | 0 | 480 |
| Read 6 unique targets + source re-reads | 3,600 | 0 | 4,080 |
| Model decides on each (6 targets) | 0 | 500 | 4,580 |
| 2 targets need updates | 200 | 250 | 5,030 |
| 2x changelog-write for updates | 240 | 0 | 5,270 |
| 1x ripple-verify | 60 | 0 | 5,330 |
| **Total** | **4,580** | **750** | **5,330** |

**~5,300 tokens for full ripple.** Typical debrief: 15,000-25,000. Overhead: ~21-35%. Honest number, not the flattering one.

### Best case: calibrate, 1 file, no updates

| Step | Tokens in | Tokens out | Cumulative |
|------|-----------|------------|------------|
| 1x changelog-write | 120 | 0 | 120 |
| Read 3 targets + source re-read | 1,800 | 0 | 1,920 |
| Model decides (all consistent) | 0 | 150 | 2,070 |
| 1x ripple-verify | 60 | 0 | 2,130 |
| **Total** | **1,980** | **150** | **2,130** |

**~2,100 tokens when nothing needs updating.** Consistency tax.

### Scripts vs pure LLM savings

| Without scripts | With scripts | Savings per edit |
|-----------------|-------------|-----------------|
| Model reads graph JSON (~400) + reasons about targets (~200 out) | Script returns in ~50 | ~550 |
| Model formats changelog (~150 out) | Script formats, 0 out | ~150 |
| Model parses changelog to verify (~300 in + ~100 out) | Script in ~60 | ~340 |
| **Per edit** | | **~1,040** |

4-file debrief: **~4,160 tokens saved.** Pays for most of the ripple overhead.

### Token discipline integration

- Bash calls count toward 50-call ceiling, NOT 30-call MCP ceiling.
- 4-file debrief adds ~8 Bash calls. Within threshold.
- "15 reads without write" rule prevents runaway ripple chains naturally.
- Content lint: 1 Bash call per Friday. Negligible.
- test-ripple.py: runs during `kipi check`, not during sessions. Zero session cost.

## 7c. Regression Testing Protocol

### Phase 1: Automated (runs via `kipi check`)

```bash
python3 q-system/.q-system/scripts/test-ripple.py
```

7 checks. Exit 0 = pass. Exit 1 = print failures. No human memory required.

### Phase 2: Existing harness compatibility (run once after implementation)

```bash
python3 q-system/.q-system/scripts/canonical-digest.py 2026-04-12 --json && echo "PASS"
python3 validate-separation.py && echo "PASS"
```

### Phase 3: Workflow integration (BEH, verified over 1 week)

| Test | Workflow | Observe | Pass if |
|------|----------|---------|---------|
| W-1 | `/q-debrief` | Source saved, changelog entries, verify runs | All three in order. Source timestamp < changelog. |
| W-2 | `/q-calibrate` | Changelog per edit, targets surfaced | Model states "consistent" or "updated." |
| W-3 | `/q-wrap` Friday | Lint runs | Output in wrap. |
| W-4 | `/q-wrap` Tuesday | No lint | No lint in wrap. |
| W-5 | `/q-morning` | Normal | Audit passes. No changelog from pipeline. |
| W-6 | Debrief, zero changes | No changelog | "No entries." Exit 0. |
| W-7 | Compaction mid-debrief | PostCompact fires | Changelog on disk survives. |

## 8. Rollback Plan

| Change | Rollback Steps | Risk |
|--------|---------------|------|
| Ripple graph (1) | Delete `ripple-graph.json`. Scripts exit 2 (safe). | Zero. |
| Changelog (2-3) | Delete `changelog.md` + `changelog-write.py`. Remove workflow references. | Zero. Reverts to pre-ripple. |
| Structural lint (4) | Delete `content-lint.py`. Remove wrap call. | Zero. |
| Ripple verify (5) | Delete `ripple-verify.py`. Remove gates. | Zero. |
| Source archive (6) | Delete `sources/`. Remove template addition. | Low. Existing sources untouched. |
| Test harness (10) | Delete `test-ripple.py`. Remove from `kipi check`. | Zero. |

## 9. Change Review Checklist

| Check | Status | Notes |
|-------|--------|-------|
| Changes are additive | Pending | All new files. Nothing deleted. |
| No conflicts with enforced rules | Pending | Extends workflows, does not replace. |
| No hardcoded secrets | Pending | File paths only. |
| Propagation path verified | Pending | Standard skeleton paths. |
| Exit codes preserved | Pending | 0/1/2 matching convention. |
| AUDHD-friendly | Pending | Factual output, no judgment. |
| Test coverage | Pending | 19 DET + 3 BEH + 7 automated regression. |

## 10. Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Cross-file consistency | Inconsistent | ripple-verify exit 0 on 90%+ debriefs in 2 weeks | Session effort logs |
| Structural issues detected | Unknown | Lint surfaces issues weekly | `content-lint.py --json` Fridays |
| Audit trail coverage | Zero | 100% of canonical edits logged | Changelog lines vs git log count |
| Source preservation | 0% | 100% of debrief conversations archived | `ls sources/*.md` vs changelog debrief count |
| Token overhead | 0 | <5,500 per debrief | Bash call count in session logs |
| test-ripple.py in kipi check | N/A | Exit 0 on every `kipi check` | Automated |

## 11. Implementation Order

1. **Ripple graph JSON** - foundation
2. **Changelog file** - needed by writer
3. **Changelog writer** - depends on 1 + 2
4. **Structural lint** - depends on 2
5. **Ripple verify** - depends on 1 + 2
6. **Test harness** - depends on 1, 3, 4, 5
7. **Raw source archive** - no dependencies
8. **Debrief template updates** - depends on 3, 5, 7
9. **Calibrate workflow updates** - depends on 3, 5
10. **Wrap workflow updates** - depends on 4
11. **Folder structure + md-hygiene + kipi check wiring** - depends on all above

Parallel: 1+2+7. Then 3+4+5. Then 6. Then 8+9+10. Then 11.

## 12. Open Questions

| Question | Owner | Deadline | Resolution |
|----------|-------|----------|------------|
| Should `/q-engage` write to changelog? | Assaf | 2026-04-19 | **YES, but separate follow-up PRD.** Engage captures market signals that vanish. Same bug class. But no US, no test case, no implementation detail here. Needs its own change entry after v1 data shows which signals matter. |
| Should morning pipeline use ripple graph? | Assaf | 2026-04-19 | **NO.** Read-heavy synthesis. Doesn't create canonical knowledge. Revisit after 30 days. |
| Hard gate or soft gate? | Assaf | 2026-04-15 | **SOFT GATE.** Warn, don't block. Upgrade after 2-3 weeks if warnings ignored. |
| Instance-local overrides? | Assaf | 2026-04-19 | **NO.** YAGNI. One active instance. |
| Changelog line budget? | Assaf | 2026-04-15 | **200 lines.** 60 days at ~3 edits/day. |
| Section-level graph targeting? | Assaf | 2026-04-19 | **DEFERRED to v1.1.** Requires header validation to avoid silent failure. Ship file-level only in v1. Add sections after 30 days of data. |
| Semantic lint (cross-file claim comparison)? | Assaf | 2026-04-26 | **DEFERRED to v1.1.** Requires Haiku LLM pass. Structural lint ships now. Semantic lint after changelog shows which files actually drift. |

## 13. Wiring Checklist (MANDATORY)

| Check | Status | Notes |
|-------|--------|-------|
| PRD saved to `q-system/output/prd-ripple-graph-2026-04-12.md` | Done | This file |
| All code/config changes implemented and tested | Pending | |
| New files listed in folder-structure rule | Pending | graph, changelog, 4 scripts, sources/ |
| New conventions referenced in root CLAUDE.md | Pending | Ripple verification |
| `md-hygiene.md` updated (changelog: 200 lines) | Pending | |
| `kipi check` wired to run test-ripple.py | Pending | |
| Memory entry saved | Pending | |
| `kipi update --dry` confirms diff | Pending | |
| `kipi update` pushed to instances | Pending | |
| PRD Status updated to "Done" | Pending | |
