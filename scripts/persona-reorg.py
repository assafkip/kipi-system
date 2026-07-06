#!/usr/bin/env python3
"""persona-reorg.py — deterministic, reversible fleet reorg under top-level personas.

Phase 1 of the fleet reorg (see q-system/output/plans/persona-reorg-2026-07-06.md
and cole-gtm-reorg-2026-07-06.md). Cole-GTM first, one persona at a time.

Design contract (founder rules):
  - `--dry` (default) prints EVERY dir move + EVERY path rewrite and changes NOTHING.
  - Reversible: the same map reversed rolls the batch back.
  - Two-pass grep on rename (token-discipline Cleanup Rule) — done in Phase F.
  - Nothing runs `--apply` until the founder approves a dry run. `--apply` is a
    guarded stub here on purpose; the move logic lands only after dry sign-off.

Locked decision (2026-07-06): Layout A — cole-gtm/ IS the renamed random-stuff-ideas
repo (Cole persona + gtm/ brain + launchd jobs already there). The 9 GTM projects
cascade under cole-gtm/projects/ as independent nested repos, gitignored in parent.
"""

import argparse
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, "projects")
REGISTRY = os.path.join(PROJECTS, "kipi-system", "instance-registry.json")
LAUNCHAGENTS = os.path.join(HOME, "Library", "LaunchAgents")
KTLYST_RULE = os.path.join(HOME, ".claude", "rules", "ktlyst-cluster.md")
BRIDGE = os.path.join(HOME, ".ktlyst", "bridge")

# --- Persona map (deterministic; the single source of the reorg plan) ----------
# Each project: name, current absolute src, optional registry entry name, optional
# launchd plist basenames, optional flags (rule/bridge) that need extra handling.
PERSONAS = {
    "cole-gtm": {
        # The parent: random-stuff-ideas is RENAMED to cole-gtm (repo stays intact).
        "parent": {
            "name": "random-stuff-ideas",
            "src": os.path.join(PROJECTS, "random-stuff-ideas"),
            "dst": os.path.join(PROJECTS, "cole-gtm"),
            "registry_name": "gtm-partner",
            "plists": [
                "com.cole.daily-podcast.plist",
                "com.cole.podcast-report.plist",
                "com.cole.podcast-weekly-report.plist",
                "com.cole.daily-video.plist.disabled",  # disabled: rewrite, do NOT reload
            ],
        },
        # The 9 projects that cascade under cole-gtm/projects/.
        "projects": [
            {"name": "notebooklm-daily-podcast"},
            {"name": "reddit-build-radar", "registry": "reddit-build-radar"},
            {"name": "vc-signals"},
            {"name": "event_coordinator", "src_sub": "ktlyst-hub/event_coordinator",
             "registry": "event_coordinator", "rule": "ktlyst-cluster"},
            {"name": "website", "src_sub": "ktlyst-hub/website",
             "registry": "ktlyst-website", "rule": "ktlyst-cluster",
             "bridge": "website-state.json"},
            {"name": "personal-brand", "src_sub": "ktlyst-hub/personal-brand",
             "registry": "personal-brand"},
            {"name": "founder-signal-engine"},
            {"name": "signal-desk"},
            {"name": "competitive-analysis",
             "plists": ["com.assaf.competitive-analysis.morning.plist"]},
        ],
    }
}

# Grep classification: paths matching these prefixes are noise (worktrees, git,
# archives, node_modules) and are SKIPPED — never rewritten.
GREP_SKIP = ("_codex-worktrees/", ".claude/worktrees/", "/.git/", "node_modules/",
             "_archive", "_archived")
# Vendored fleet copies that kipi update re-syncs from the skeleton. Rewrite the
# SKELETON copy only; instance copies are overwritten on next `kipi update`.
GREP_VENDORED = ("plugins/kipi-core/kipi-mcp/",)


def c(txt, code):
    return f"\033[{code}m{txt}\033[0m" if sys.stdout.isatty() else txt


def hdr(txt):
    print("\n" + c("=" * 78, "36"))
    print(c(txt, "1;36"))
    print(c("=" * 78, "36"))


def resolve_src(proj):
    sub = proj.get("src_sub", proj["name"])
    return os.path.join(PROJECTS, sub)


def build_moves(persona):
    """Return (parent_move, [project_moves]) as (name, src, dst, exists) records."""
    p = PERSONAS[persona]["parent"]
    parent = (p["name"], p["src"], p["dst"], os.path.isdir(p["src"]))
    projects_root = os.path.join(p["dst"], "projects")
    moves = []
    for proj in PERSONAS[persona]["projects"]:
        src = resolve_src(proj)
        dst = os.path.join(projects_root, proj["name"])
        moves.append((proj["name"], src, dst, os.path.isdir(src)))
    return parent, moves


def phase_moves(persona):
    hdr("PHASE A — directory moves")
    parent, moves = build_moves(persona)
    name, src, dst, exists = parent
    flag = c("OK", "32") if exists else c("MISSING!", "1;31")
    print(f"\n  [parent rename]  {name}")
    print(f"      {src}")
    print(f"   -> {dst}         [{flag}]")
    print(f"\n  [cascade] {len(moves)} projects -> {dst}/projects/")
    for n, s, d, e in moves:
        flag = c("OK", "32") if e else c("MISSING!", "1;31")
        print(f"    - {n:<26} {s}")
        print(f"      {'':<26} -> {d}   [{flag}]")


def phase_registry(persona):
    hdr("PHASE B — instance-registry.json rewrites")
    parent, moves = build_moves(persona)
    with open(REGISTRY) as f:
        reg = json.load(f)
    # map src abspath -> dst abspath for every dir that moves
    move_map = {parent[1]: parent[2]}
    for _, s, d, _ in moves:
        move_map[s] = d
    hits = 0
    for inst in reg.get("instances", []):
        old = inst["path"]
        # A registry path resolves if it equals a moved src, or lives under one.
        new = None
        for s, d in move_map.items():
            if old == s:
                new = d
            elif old.startswith(s + os.sep):
                new = d + old[len(s):]
        if new:
            hits += 1
            print(f"\n  {c(inst['name'], '1;33')}")
            print(f"      {old}")
            print(f"   -> {new}")
    print(f"\n  {c(str(hits) + ' registry entries rewritten', '36')} "
          f"(expected 5: gtm-partner, ktlyst-website, personal-brand, "
          f"event_coordinator, reddit-build-radar)")


def phase_plists(persona):
    hdr("PHASE C — launchd plist rewrites + reload plan")
    parent = PERSONAS[persona]["parent"]
    # every (src, dst, [plists], reload?) tuple
    units = [(parent["src"], parent["dst"], parent["plists"])]
    for proj in PERSONAS[persona]["projects"]:
        if proj.get("plists"):
            units.append((resolve_src(proj),
                          os.path.join(parent["dst"], "projects", proj["name"]),
                          proj["plists"]))
    for src, dst, plists in units:
        for pl in plists:
            path = os.path.join(LAUNCHAGENTS, pl)
            disabled = pl.endswith(".disabled")
            if not os.path.isfile(path):
                print(f"\n  {c(pl, '1;33')}  [{c('MISSING!', '1;31')}]")
                continue
            with open(path) as f:
                body = f.read()
            n = body.count(src)
            reload_note = (c("rewrite only (disabled — no reload)", "33")
                           if disabled else c("rewrite + launchctl reload + verify fires", "32"))
            print(f"\n  {c(pl, '1;33')}  ({n} path refs)  [{reload_note}]")
            print(f"      s|{src}|{dst}|")


def phase_rule(persona):
    hdr("PHASE D — global rule ktlyst-cluster.md  (HELD: needs founder confirm)")
    movers = [p for p in PERSONAS[persona]["projects"] if p.get("rule") == "ktlyst-cluster"]
    print(f"\n  File: {KTLYST_RULE}")
    print(f"  Cross-instance preflight rule → the founder confirms this edit before it runs.")
    if os.path.isfile(KTLYST_RULE):
        with open(KTLYST_RULE) as f:
            lines = f.readlines()
        for proj in movers:
            print(f"\n  {c(proj['name'], '1;33')} rows referencing ~/projects/ktlyst-hub/{proj['name']}:")
            for i, ln in enumerate(lines, 1):
                if f"ktlyst-hub/{proj['name']}" in ln:
                    print(f"      L{i}: {ln.rstrip()}")
    print(f"\n  {c('ACTION (held):', '1;31')} rewrite ~/projects/ktlyst-hub/<x> "
          f"-> ~/projects/cole-gtm/projects/<x> for website + event_coordinator.")


def phase_bridge(persona):
    hdr("PHASE E — KTLYST bridge (preserve, do not break)")
    proj = next((p for p in PERSONAS[persona]["projects"] if p.get("bridge")), None)
    if not proj:
        print("\n  No bridge writers in this persona.")
        return
    bf = os.path.join(BRIDGE, proj["bridge"])
    exists = os.path.isfile(bf)
    print(f"\n  {c(proj['name'], '1;33')} writes {bf} "
          f"[{c('present', '32') if exists else c('absent', '31')}]")
    print(f"  Dual citizenship: cole-gtm asset AND KTLYST bridge writer.")
    print(f"  {c('VERIFY after move:', '1;36')} website deploy/sync still updates "
          f"{proj['bridge']} (its write path must survive the move).")


def grep_hits(persona):
    parent = PERSONAS[persona]["parent"]
    names = [parent["name"]] + [p["name"] for p in PERSONAS[persona]["projects"]]
    subs = []
    for p in PERSONAS[persona]["projects"]:
        subs.append(p.get("src_sub", p["name"]))
    pattern_names = set(names) | set(subs)
    # Build a regex of every old path segment under ~/projects/
    alts = "|".join(sorted(pattern_names, key=len, reverse=True))
    pat = rf"/Users/[^/]+/projects/({alts})"
    try:
        out = subprocess.run(
            ["grep", "-rIl", "-E", pat, PROJECTS,
             "--exclude-dir=node_modules", "--exclude-dir=.git",
             "--exclude-dir=_codex-worktrees", "--exclude-dir=worktrees",
             "--exclude-dir=_archive", "--exclude-dir=_archived",
             "--exclude-dir=.next", "--exclude-dir=dist", "--exclude-dir=build",
             "--include=*.py", "--include=*.sh", "--include=*.json",
             "--include=*.md", "--include=*.plist", "--include=*.js", "--include=*.ts"],
            capture_output=True, text=True, timeout=240).stdout
    except Exception as e:
        return {"error": str(e)}
    buckets = {"skip": [], "vendored": [], "self_in_moved": [], "canonical": []}
    moved_prefixes = tuple(os.path.join(PROJECTS, s) for s in pattern_names)
    for line in out.splitlines():
        rel = line.replace(PROJECTS + "/", "")
        if any(k in line for k in GREP_SKIP):
            buckets["skip"].append(rel)
        elif any(k in line for k in GREP_VENDORED):
            buckets["vendored"].append(rel)
        elif line.startswith(moved_prefixes):
            buckets["self_in_moved"].append(rel)
        else:
            buckets["canonical"].append(rel)
    return buckets


def phase_grep(persona):
    hdr("PHASE F — two-pass grep, classified (Cleanup Rule)")
    b = grep_hits(persona)
    if "error" in b:
        print(f"  grep failed: {b['error']}")
        return
    print(f"\n  {c('CANONICAL / load-bearing', '1;32')} — script rewrites these directly:")
    for f in b["canonical"]:
        print(f"    * {f}")
    if not b["canonical"]:
        print("    (none beyond registry/plists handled in B/C)")
    print(f"\n  {c('SELF-REF inside moved dirs', '1;33')} — travel with the dir; "
          f"rewrite internal absolute self-paths old->new:")
    for f in b["self_in_moved"]:
        print(f"    * {f}")
    print(f"\n  {c('VENDORED (kipi-mcp, fleet-synced)', '35')} — rewrite SKELETON copy "
          f"only; instances re-sync via kipi update:")
    for f in sorted(set(f.split('/', 1)[1] if '/' in f else f for f in b["vendored"]))[:6]:
        print(f"    * .../{f}")
    print(f"    ({len(b['vendored'])} copies total across the fleet — 1 skeleton source of truth)")
    print(f"\n  {c('SKIP (worktrees/git/archive noise)', '90')} — {len(b['skip'])} files, not rewritten")


def phase_gitignore(persona):
    hdr("PHASE G — cole-gtm/.gitignore")
    parent = PERSONAS[persona]["parent"]
    gi = os.path.join(parent["src"], ".gitignore")  # src until renamed
    print(f"\n  Add to {parent['dst']}/.gitignore (currently {gi}):")
    print(f"      {c('projects/', '32')}      # nested independent repos, not tracked by parent")


def phase_summary(persona):
    hdr("SUMMARY — Cole-GTM dry run")
    parent, moves = build_moves(persona)
    missing = [m[0] for m in moves if not m[3]] + ([] if parent[3] else [parent[0]])
    print(f"""
  1 parent rename        random-stuff-ideas -> cole-gtm
  9 project moves        -> cole-gtm/projects/*
  5 registry rewrites    (gtm-partner, ktlyst-website, personal-brand,
                          event_coordinator, reddit-build-radar)
  5 launchd plists       4x com.cole.* (1 disabled) + competitive-analysis
                          -> reload the 4 enabled, verify each fires
  1 global rule          ktlyst-cluster.md  [HELD — founder confirm]
  1 bridge               website-state.json [preserve website dual role]
  + self-ref + vendored  rewrites (see Phase F)
  + .gitignore projects/ in parent
""")
    if missing:
        print(c(f"  ⚠ MISSING source dirs: {missing}", "1;31"))
    else:
        print(c("  ✓ all 10 source dirs present on disk", "32"))
    print(c("\n  NOTHING WAS CHANGED. Founder approval gates the real run.", "1;36"))


def main():
    ap = argparse.ArgumentParser(description="Fleet persona reorg (dry by default).")
    ap.add_argument("--persona", default="cole-gtm", choices=list(PERSONAS))
    ap.add_argument("--dry", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true",
                    help="Execute the moves. GUARDED: refuses until dry is approved.")
    args = ap.parse_args()

    if args.apply:
        print(c("REFUSED: --apply is not enabled yet.", "1;31"))
        print("The real move logic lands only after the founder approves this dry run.")
        print("Re-run without --apply to see the plan.")
        sys.exit(3)

    persona = args.persona
    print(c(f"\n### persona-reorg DRY RUN — persona: {persona} ###", "1;35"))
    print("Reads live registry/plists/grep. Changes nothing.")
    phase_moves(persona)
    phase_registry(persona)
    phase_plists(persona)
    phase_rule(persona)
    phase_bridge(persona)
    phase_grep(persona)
    phase_gitignore(persona)
    phase_summary(persona)


if __name__ == "__main__":
    main()
