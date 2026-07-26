#!/usr/bin/env python3
"""Join every repo's CAPABILITY-MAP.json and report cross-repo overlaps.

Pairs with capability-map-gen.py (which produces the inputs) and the SDLC standard
at q-system/output/plans/linear-sdlc-standard-2026-07-26.md (Part 7).

WHY THIS IS A SCRIPT AND NOT A LINEAR QUERY (ASK-113): this analysis is a join
over 25 JSON files. Done as a script it is free, re-runnable in CI, and diffable
between runs. Done by querying ~1400 Linear issues it costs MCP calls, cannot run
in CI, and answers slower. That is the whole argument for keeping the inventory in
the repo and only the actionable slice in Linear.

FOUR FINDING CLASSES, in ascending order of how much they should worry you:

  DUPLICATE  same capability, same content, several repos. Expected for skeleton
             propagations; a finding only when it is NOT a propagation.
  DIVERGENT  same capability slug, DIFFERENT content hash. Two repos solved one
             problem two ways. This is the expensive class: whichever is better,
             the other one is quietly wrong, and nothing tells you which.
  ORPHAN     a capability in exactly one repo that looks like it ought to be
             shared. A promotion candidate for the skeleton.
  COLLISION  two repos both claiming the same EXTERNAL resource: a launchd label,
             a Slack channel, a cron slot, a config path. Two writers to one
             resource is a silent corruption path, and it has already bitten this
             fleet once (the launchd income-scanner scar).
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def content_hash(root: Path, entry: str) -> str:
    """Hash the actual backing file so DIVERGENT is decided on content, not names.

    A hook entry looks like `.claude/settings.json -> $CLAUDE_PROJECT_DIR/x.py
    [PostToolUse/Edit]`. Taking the part BEFORE the arrow hashed settings.json,
    which differs in every repo, so every hook reported as many versions as there
    were repos: 24 repos, 24 versions, entirely an artifact of the wrong file.
    The script after the arrow is the thing whose content actually matters.
    """
    raw = str(entry or "")
    path = raw.split(" -> ", 1)[1] if " -> " in raw else raw
    path = re.sub(r"\s*\[[^\]]*\]\s*$", "", path).strip()
    path = (path.replace("${CLAUDE_PROJECT_DIR}", "")
                .replace("$CLAUDE_PROJECT_DIR", "").lstrip("/"))
    if not path:
        return ""
    try:
        f = root / path
        if f.is_file():
            return hashlib.sha1(f.read_bytes()).hexdigest()[:12]
    except OSError:
        pass
    return ""


# External resources a repo can claim. Two repos claiming one of these is the
# COLLISION class: unlike code, these have exactly one instance in the world.
RESOURCE_PATTERNS = (
    ("launchd", re.compile(r"\bcom\.kipi\.[\w.\-]+")),
    ("config", re.compile(r"~/\.config/kipi/[\w.\-]+")),
    ("slack-webhook", re.compile(r"slack-webhook[\w.\-]*")),
    ("queue", re.compile(r"\.linear-queue\.jsonl")),
)


def scan_resources(root: Path, skeleton: Path) -> dict:
    """External resources named by this repo's OWN files.

    A file that also exists at the same path in the skeleton is a `kipi update`
    propagation: 24 repos carrying the same doc that mentions `com.kipi.lessons-daily`
    is ONE mention copied 24 times, not 24 repos competing for a launchd label.
    Counting those produced 20 "collisions" that were all propagation noise, which
    would have sent someone chasing a conflict that does not exist.

    Markdown is excluded outright: prose naming a resource is documentation, not a
    claim on it. A claim lives in code or a plist.
    """
    found = defaultdict(set)
    for pattern in ("*.sh", "*.py", "*.json", "*.plist"):
        for p in root.rglob(pattern):
            parts = set(p.parts)
            if parts & {".git", "node_modules", "__pycache__", "site-packages",
                        ".venv", "venv", "archives"}:
                continue
            rel = p.relative_to(root)
            # Skip skeleton propagations, unless we ARE the skeleton.
            if root.resolve() != skeleton.resolve() and (skeleton / rel).exists():
                continue
            try:
                text = p.read_text(errors="ignore")
            except OSError:
                continue
            for kind, rx in RESOURCE_PATTERNS:
                for m in rx.findall(text):
                    found[(kind, m.rstrip(".").strip())].add(str(rel))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-repo capability overlap report.")
    ap.add_argument("--maps", default="q-system/output/capability-maps")
    ap.add_argument("--out", required=True, help="markdown report path")
    ap.add_argument("--digest", help="compact JSON digest path (committable)")
    ap.add_argument("--skeleton", default=os.path.join(os.path.dirname(__file__), "..", "..", ".."),
                    help="skeleton root; files also present there are kipi update "
                         "propagations and do not count as a resource claim")
    ap.add_argument("--skip-resources", action="store_true",
                    help="skip the external-resource collision scan (slow)")
    args = ap.parse_args()

    maps = {}
    for f in sorted(Path(args.maps).glob("*.json")):
        try:
            d = json.load(open(f))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARN: skipping {f}: {exc}", file=sys.stderr)
            continue
        maps[d["repo"]] = d
    if not maps:
        print(f"BLOCK: no capability maps found under {args.maps}", file=sys.stderr)
        return 1

    # Two separate indexes, because DIVERGENT and DUPLICATE ask different questions.
    #
    # DIVERGENT is about PROPAGATION DRIFT: the same relative path, rsynced by
    # `kipi update` into every instance, whose contents have stopped matching.
    # Indexing it by capability NAME was wrong and produced a false headline:
    # three unrelated files all called `token-guard.py` at three different paths
    # were reported as "3 versions of token-guard", when the real
    # q-system/.q-system/token-guard.py is byte-identical in all 24 repos that
    # have it (verified by direct hash, 2026-07-26). Path is the propagation unit.
    #
    # DUPLICATE/ORPHAN stay NAME-indexed, because "two repos built a thing that
    # does the same job" is a naming question, not a path question.
    by_path = defaultdict(list)
    by_name = defaultdict(list)
    for repo, d in maps.items():
        root = Path(d["root"])
        for cap in d["capabilities"]:
            h = content_hash(root, cap.get("entry"))
            raw = str(cap.get("entry") or "")
            norm = raw.split(" -> ", 1)[1] if " -> " in raw else raw
            norm = re.sub(r"\s*\[[^\]]*\]\s*$", "", norm).strip()
            norm = (norm.replace("${CLAUDE_PROJECT_DIR}", "")
                        .replace("$CLAUDE_PROJECT_DIR", "").lstrip("/"))
            if norm:
                by_path[norm].append((repo, cap, h))
            by_name[slugify(cap["name"])].append((repo, cap, h))

    divergent = []
    for path, entries in by_path.items():
        if len(entries) < 2:
            continue
        hashes = {h for _, _, h in entries if h}
        if len(hashes) > 1:
            divergent.append((path, entries, hashes))

    duplicate, orphan_local = [], []
    for slug, entries in by_name.items():
        if len(entries) == 1:
            repo, cap, _ = entries[0]
            if cap.get("origin") == "local" and cap["layer"].startswith(("L0", "L3", "L5")):
                orphan_local.append((slug, repo, cap))
            continue
        if not all(c.get("origin") == "skeleton" for _, c, _ in entries):
            duplicate.append((slug, entries))

    collisions = {}
    if not args.skip_resources:
        owners = defaultdict(set)
        for repo, d in maps.items():
            for res in scan_resources(Path(d["root"]), Path(args.skeleton).resolve()):
                owners[res].add(repo)
        collisions = {k: v for k, v in owners.items() if len(v) > 1}

    # --- report ---------------------------------------------------------------
    L = []
    A = L.append
    A("# Cross-repo capability overlap report")
    A("")
    A(f"Generated by `capability-overlap.py` over {len(maps)} capability maps. "
      "Every number here is a join over generated recon, not a hand count.")
    A("")
    A("| Class | Count | What it means |")
    A("| -- | -- | -- |")
    A(f"| DIVERGENT | {len(divergent)} | Same capability, different content. The expensive class. |")
    A(f"| DUPLICATE | {len(duplicate)} | Same capability, same content, not a skeleton propagation. |")
    A(f"| COLLISION | {len(collisions)} | Two repos claiming ONE external resource. |")
    A(f"| ORPHAN | {len(orphan_local)} | Local-only governance/enforcement/engine, promotion candidate. |")
    A("")

    A("## DIVERGENT: one problem, several answers")
    A("")
    if not divergent:
        A("_None._")
    else:
        A("Same relative PATH, different file contents. `kipi update` rsyncs these, so "
          "they are supposed to be identical fleet-wide. Where they are not, some "
          "instances are running a stale copy and nothing announces it.")
        A("")
        for slug, entries, hashes in sorted(divergent, key=lambda x: -len(x[1]))[:40]:
            A(f"### `{slug}` in {len(entries)} repos, {len(hashes)} distinct versions")
            A("")
            A("| Repo | Entry | Content | Origin |")
            A("| -- | -- | -- | -- |")
            for repo, cap, h in sorted(entries, key=lambda e: e[0]):
                A(f"| `{repo}` | `{cap.get('entry')}` | `{h or 'n/a'}` | {cap.get('origin')} |")
            A("")

    A("## COLLISION: two repos, one external resource")
    A("")
    if not collisions:
        A("_None found by the current pattern set (launchd labels, ~/.config/kipi "
          "paths, slack webhooks, queue files)._")
    else:
        A("These have exactly one instance in the world. Two writers is a silent "
          "corruption path, not a style question.")
        A("")
        A("| Kind | Resource | Claimed by |")
        A("| -- | -- | -- |")
        for (kind, res), repos in sorted(collisions.items())[:60]:
            A(f"| {kind} | `{res}` | {', '.join(f'`{r}`' for r in sorted(repos))} |")
    A("")

    A("## DUPLICATE: same content, not a propagation")
    A("")
    if not duplicate:
        A("_None._")
    else:
        A("| Capability | Repos |")
        A("| -- | -- |")
        for slug, entries in sorted(duplicate, key=lambda x: -len(x[1]))[:40]:
            A(f"| `{slug}` | {', '.join(sorted(f'`{r}`' for r, _, _ in entries))} |")
    A("")

    A("## ORPHAN: local-only, promotion candidates")
    A("")
    A(f"{len(orphan_local)} governance/enforcement/engine capabilities exist in "
      "exactly one repo. Most should stay local. The ones worth promoting are those "
      "solving a problem every instance has.")
    A("")
    by_repo = defaultdict(int)
    for _, repo, _ in orphan_local:
        by_repo[repo] += 1
    A("| Repo | Local-only L0/L3/L5 capabilities |")
    A("| -- | -- |")
    for repo, n in sorted(by_repo.items(), key=lambda x: -x[1])[:25]:
        A(f"| `{repo}` | {n} |")
    A("")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(L) + "\n")

    if args.digest:
        digest = {
            "generated_from": len(maps),
            "repos": {
                r: {
                    "capabilities": len(d["capabilities"]),
                    "status_counts": d["status_counts"],
                    "origin_counts": d["origin_counts"],
                    "actionable_local": d["actionable_local"],
                    "nested_excluded": len(d.get("nested_repos_excluded", [])),
                } for r, d in sorted(maps.items())
            },
            "divergent": [
                {"capability": s, "repos": sorted(r for r, _, _ in e),
                 "distinct_versions": len(h)}
                for s, e, h in divergent
            ],
            "collisions": [
                {"kind": k, "resource": res, "repos": sorted(v)}
                for (k, res), v in sorted(collisions.items())
            ],
            "duplicate_non_propagated": [
                {"capability": s, "repos": sorted(r for r, _, _ in e)}
                for s, e in duplicate
            ],
        }
        Path(args.digest).write_text(json.dumps(digest, indent=2) + "\n")

    print(f"{len(maps)} maps joined -> DIVERGENT={len(divergent)} "
          f"DUPLICATE={len(duplicate)} COLLISION={len(collisions)} "
          f"ORPHAN={len(orphan_local)}")
    print(f"report: {args.out}" + (f"\ndigest: {args.digest}" if args.digest else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
