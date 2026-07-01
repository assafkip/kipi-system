#!/usr/bin/env python3
"""lessons-harvest: the cross-instance learning ENGINE (the missing half of the corpus).

The lessons corpus (q-system/lessons/) has the sharing RAIL but no engine, so it holds one
lesson. claudesidian fills its single-vault brain via capture -> synthesize -> write-back. This
ports that loop to the fleet, but the write-back is HUMAN promotion, because kipi's confidentiality
model FORBIDS auto-publishing a client scar (skeleton-sole-writer + human-authored abstraction are
PRIMARY controls; the validator only checks shape, not semantics -- PRD prd-cross-instance-learning).

So this engine automates the tedious 90% and stops at a review queue:
  HARVEST every instance's RCAs -> CLASSIFY each structural cause into a fixed-taxonomy tag (LLM
  proposes, this script verifies the tag is in the allowlist -- the sycophancy-harness pattern) ->
  CLUSTER by tag -> emit a CANDIDATE only when 2+ UNRELATED instances share a tag -> write it to
  repo-root lesson-candidates/ (skeleton-only, git-tracked, NOT fanned to instances). The founder
  then hand-authors the real lesson (sole-writer + human-abstraction controls stay intact).

"Unrelated" is derived from name/path: the ktlyst cluster (and any shared hub parent dir) count as
ONE cluster; a candidate needs 2+ DISTINCT clusters. Unsure => treated as RELATED (the safe default,
so we never over-claim "unrelated" and surface a same-client pattern for promotion).

Usage:
  lessons-harvest.py                 # classify via `claude -p`, write candidates
  lessons-harvest.py --dry           # print candidates, write nothing
  lessons-harvest.py --registry P    # override registry (tests)
  lessons-harvest.py --tags-file P   # JSON {rca_abspath: cause_type}; skips the LLM (tests)
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]        # q-system/.q-system/scripts -> repo root
DEFAULT_REGISTRY = REPO_ROOT / "instance-registry.json"
CANDIDATES_DIR = REPO_ROOT / "lesson-candidates"        # outside q-system/ => never fanned

# Fixed cause-type taxonomy. The LLM must return one of these; anything else -> "other" (dropped
# from clustering, since a vague tag is not a shareable pattern). Grow deliberately, not per-run.
TAXONOMY = [
    "two-writers-shared-resource",
    "prompt-only-enforcement",
    "sync-delete-clobber",
    "derived-copy-drift",
    "wrong-date-or-year-default",
    "missing-idempotency",
    "silent-failure-no-surface",
    "path-doubling",
    "unvalidated-llm-output",
    "missing-reproducer",
]
UNSHAREABLE = {"other", "unclassified"}


def load_instances(registry_path):
    data = json.loads(Path(registry_path).read_text())
    out = []
    for entry in data.get("instances", []):
        if str(entry.get("status", "")).startswith("merged"):
            continue
        out.append((entry["name"], entry["path"]))
    return out


def cluster_of(name, path):
    """Relatedness group. Same cluster => NOT independent evidence. Conservative: only known
    groupings merge; everything else is its own cluster (treated as unrelated to the rest)."""
    low = name.lower()
    if "ktlyst" in low or "/ktlyst-hub/" in path:
        return "ktlyst"
    parent = Path(path).parent.name
    if parent and parent not in ("projects", "", "/"):
        return f"hub:{parent}"          # a shared non-generic parent dir = a hub cluster
    return f"solo:{low}"


def rca_files(instance_path):
    rca_dir = Path(instance_path) / "q-system" / "output" / "rca"
    if not rca_dir.is_dir():
        return []
    return sorted(p for p in rca_dir.glob("*.md") if p.name.lower() != "readme.md")


def structural_root_cause(md_text):
    """Extract the '## Structural root cause' section — the reusable-pattern part of an RCA."""
    match = re.search(r"##\s*Structural root cause\s*\n(.+?)(?:\n##\s|\Z)", md_text, re.S | re.I)
    return (match.group(1).strip() if match else "").strip()


def rca_title(md_text):
    match = re.search(r"^#\s+(.+)$", md_text, re.M)
    return match.group(1).strip() if match else "(untitled RCA)"


def classify_with_claude(title, cause_text):
    """LLM proposes a tag; caller verifies it is in TAXONOMY. Fallback 'unclassified' on any error."""
    taxonomy = ", ".join(TAXONOMY)
    prompt = (
        "Classify the STRUCTURAL ROOT CAUSE below into exactly ONE tag from this fixed list, or "
        f"'other' if none fit. Reply with ONLY the tag, nothing else.\nTags: {taxonomy}, other\n\n"
        f"RCA title: {title}\nStructural root cause:\n{cause_text[:1500]}"
    )
    try:
        result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=90)
    except Exception:
        return "unclassified"
    tag = result.stdout.strip().split()[0].strip().lower() if result.stdout.strip() else "unclassified"
    return tag if tag in TAXONOMY else "other"


def harvest(instances, tags_file):
    """Return list of dicts: {instance, cluster, path, title, cause_type}."""
    injected = json.loads(Path(tags_file).read_text()) if tags_file else None
    rows = []
    for name, path in instances:
        cluster = cluster_of(name, path)
        for rca in rca_files(path):
            text = rca.read_text(errors="ignore")
            title = rca_title(text)
            if injected is not None:
                cause = injected.get(str(rca), "unclassified")
            else:
                cause = classify_with_claude(title, structural_root_cause(text))
            rows.append({"instance": name, "cluster": cluster,
                         "path": str(rca), "title": title, "cause_type": cause})
    return rows


def find_candidates(rows):
    """A candidate = a cause_type present in 2+ DISTINCT clusters. Returns {cause_type: [rows]}."""
    by_type = {}
    for row in rows:
        if row["cause_type"] in UNSHAREABLE:
            continue
        by_type.setdefault(row["cause_type"], []).append(row)
    return {ct: rs for ct, rs in by_type.items()
            if len({r["cluster"] for r in rs}) >= 2}


def render_candidate(cause_type, rows, stamp):
    clusters = sorted({r["cluster"] for r in rows})
    sources = "\n".join(f"- `{r['instance']}` [{r['cluster']}]: {r['path']}\n  RCA: {r['title']}"
                        for r in rows)
    return f"""---
status: candidate
cause_type: {cause_type}
unrelated_clusters: {len(clusters)}
generated_at: {stamp}
---

# Candidate lesson: {cause_type}

The same structural cause-type recurred in {len(clusters)} UNRELATED clusters
({', '.join(clusters)}). That cross-cluster recurrence is the de-identification: a pattern common
to unrelated engagements is generic by construction. This is a DRAFT for the founder to promote.

## Source RCAs (skeleton-only — NEVER copy paths/names into the published lesson)
{sources}

## Promote (human, keeps sole-writer + abstraction controls)
1. Read the source RCAs. Write a NET-NEW, HOW-only restatement — never paste/auto-scrub a scar.
2. Create `q-system/lessons/<kebab-id>.md`, frontmatter EXACTLY {{id, kind: pattern|methodology, title, date}}.
3. The lessons-validator gates the write (allowlist + client-token denylist). Delete this candidate after promoting.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--tags-file", default=None)
    ap.add_argument("--candidates-dir", default=str(CANDIDATES_DIR))
    args = ap.parse_args()

    if not Path(args.registry).exists():
        # This tool is skeleton-only (it reads the fleet registry). The script propagates to
        # instances via kipi update; run there it has no registry -> no-op, not a traceback.
        print(f"no registry at {args.registry} — lessons-harvest runs from the skeleton "
              f"(via `kipi lessons-harvest`), not inside an instance.")
        return 0

    instances = load_instances(args.registry)
    rows = harvest(instances, args.tags_file)
    candidates = find_candidates(rows)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not candidates:
        print(f"harvested {len(rows)} RCA(s) across {len(instances)} instance(s); "
              f"no cause-type recurs across 2+ unrelated clusters yet.")
        return 0

    dest = Path(args.candidates_dir)
    for cause_type, crows in sorted(candidates.items()):
        body = render_candidate(cause_type, crows, stamp)
        clusters = sorted({r["cluster"] for r in crows})
        print(f"CANDIDATE: {cause_type} — {len(clusters)} clusters ({', '.join(clusters)})")
        if not args.dry:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f"{cause_type}.md").write_text(body)
    if args.dry:
        print(f"[dry] would write {len(candidates)} candidate(s) to {dest}")
    else:
        print(f"wrote {len(candidates)} candidate(s) to {dest} — review + promote by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
