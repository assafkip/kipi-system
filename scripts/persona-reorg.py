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
    },
    "consulting": {
        # ASK_AI_consultant is RENAMED to consulting (the consulting persona brain).
        "parent": {
            "name": "ASK_AI_consultant",
            "src": os.path.join(PROJECTS, "ASK_AI_consultant"),
            "dst": os.path.join(PROJECTS, "consulting"),
            "registry_name": "ASK_AI_consultant",
            # The 5 com.claudedaddy.* jobs moved to Cole in Part 1 (GTM extraction).
            # ASK core has no remaining installed launchd jobs (com.ask.ai-podcast
            # is in-repo only, not installed). So: no parent plists here.
            "plists": [],
        },
        "projects": [
            {"name": "Pure_spectrum_Q", "registry": "Pure_spectrum_Q",
             "plists": ["com.ktlyst.ps-slack-sync.plist",
                        "com.purespectrum.ti-weekly.plist"]},
            {"name": "4_points_consulting", "registry": "4_points_consulting"},
            {"name": "Alice", "registry": "Alice"},
        ],
    },
    "micro-saas": {
        # ANCHOR-LESS persona. Unlike cole-gtm/consulting there is no repo to
        # rename into the persona: the 6 micro-SaaS products are peers, none is
        # the brain. So the parent is a NEW empty bucket dir that the tool
        # CREATES (create=True), with a roster CLAUDE.md; the 6 cascade under it.
        # Named micro-saas (not products) to avoid overloading cole-gtm/products/
        # (the content machine) — founder call 2026-07-06.
        "parent": {
            "name": "micro-saas",
            "src": None,               # nothing to move — bucket is created
            "dst": os.path.join(PROJECTS, "micro-saas"),
            "registry_name": None,     # not a kipi instance; no registry entry
            "plists": [],
            "create": True,
        },
        # 6 Next.js $29 micro-SaaS repos. Zero registry, zero launchd (verified
        # 2026-07-06): pure Tier-0 repo moves.
        "projects": [
            {"name": "cheapcheck"},
            {"name": "briefonce"},
            {"name": "authorvoice"},
            {"name": "feedbackpin"},
            {"name": "runreceipts"},
            {"name": "shipgate"},
            # Re-homed here 2026-07-06 [USER-DIRECTED]: it's a friend's shipped
            # product, not an OSS dev tool. Moved out of dev-tools after that
            # batch landed; manifests fixed so each bucket's rollback stays true.
            {"name": "interview-coach-public"},
        ],
    },
    "intel": {
        # ANCHOR-LESS persona (create=True bucket, same pattern as micro-saas).
        # Investigations / OSINT deployments + tooling. The KTLYST product you
        # SELL (ktlyst-hub/product) also fits here but stays in ktlyst-hub until
        # that cluster split — added then, not now.
        "parent": {
            "name": "intel",
            "src": None,
            "dst": os.path.join(PROJECTS, "intel"),
            "registry_name": None,
            "plists": [],
            "create": True,
        },
        # kipi-investigations is a registry instance (name "investigations");
        # ktlyst-extract + facebook-ads have no registry/launchd (verified
        # 2026-07-06). Tier 1: one registry rewrite, no launchd/cron/bridge.
        "projects": [
            {"name": "kipi-investigations", "registry": "investigations"},
            {"name": "ktlyst-extract"},
            {"name": "facebook-ads-library-search"},
        ],
    },
    "dev-tools": {
        # ANCHOR-LESS persona (create=True bucket, same pattern as micro-saas/
        # intel). The shippable/OSS Claude Code plugins + dev tooling — peers,
        # no brain repo. NOTE: kipi-system (the factory/skeleton) is deliberately
        # NOT here — it stays top-level/meta (plan open-decision #3); every
        # persona depends on it, so nesting it under one is wrong.
        "parent": {
            "name": "dev-tools",
            "src": None,
            "dst": os.path.join(PROJECTS, "dev-tools"),
            "registry_name": None,
            "plists": [],
            "create": True,
        },
        # 7 plugin/tool repos. Verified 2026-07-06: zero registry, zero launchd
        # (name + body scan), zero linked worktrees, zero bridge — pure Tier-0
        # repo moves, the cleanest batch of the reorg.
        "projects": [
            {"name": "claude-focus"},
            {"name": "fable-discipline"},
            {"name": "kipi-rca"},
            {"name": "huntkit"},
            {"name": "tokentrim"},
            {"name": "founder-voice-kit"},
            # interview-coach-public was moved here on 2026-07-06 then re-homed to
            # micro-saas [USER-DIRECTED] — it's a friend's product, not a dev tool.
            # See the micro-saas projects list.
        ],
    },
}

# Part 1 of the ASK split: extract the GTM/content operation (products/) OUT of
# ASK and INTO cole-gtm. This deliberately GROWS Cole (founder call: Cole owns all
# GTM). One substitution everywhere: the old ASK root -> the cole-gtm root.
GTM_EXTRACT = {
    "label": "ASK products/ -> cole-gtm/products/",
    "src": os.path.join(PROJECTS, "ASK_AI_consultant", "products"),
    "dst": os.path.join(PROJECTS, "cole-gtm", "products"),
    "old_root": os.path.join(PROJECTS, "ASK_AI_consultant"),
    "new_root": os.path.join(PROJECTS, "cole-gtm"),
    "plists": [
        "com.claudedaddy.x-post.plist",
        "com.claudedaddy.youtube-post.plist",
        "com.claudedaddy.repo-distribution.plist",
        "com.claudedaddy.pinterest-post.plist",
        "com.claudedaddy.refill.plist",
    ],
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
    """Return (parent_move, [project_moves]) as (name, src, dst, exists) records.
    For a create=True (anchor-less) parent there is no src to move; `exists`
    reports whether the target bucket is already present (it should NOT be)."""
    p = PERSONAS[persona]["parent"]
    if p.get("create"):
        parent = (p["name"], None, p["dst"], not os.path.isdir(p["dst"]))
    else:
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
    if PERSONAS[persona]["parent"].get("create"):
        flag = c("will CREATE", "32") if exists else c("ALREADY EXISTS!", "1;31")
        print(f"\n  [create bucket]  {name}  (anchor-less — no repo to rename)")
        print(f"   -> {dst}         [{flag}]")
    else:
        flag = c("OK", "32") if exists else c("MISSING!", "1;31")
        print(f"\n  [parent rename]  {name}")
        print(f"      {src}")
        print(f"   -> {dst}         [{flag}]")
    print(f"\n  [cascade] {len(moves)} projects -> {dst}/projects/")
    for n, s, d, e in moves:
        flag = c("OK", "32") if e else c("MISSING!", "1;31")
        print(f"    - {n:<26} {s}")
        print(f"      {'':<26} -> {d}   [{flag}]")
        wt = _git_worktree_count(s) if e else 0
        if wt:
            print(f"      {'':<26} {c(f'{wt} git worktree(s) — git worktree repair runs post-move', '33')}")


def phase_registry(persona):
    hdr("PHASE B — instance-registry.json rewrites")
    parent, moves = build_moves(persona)
    with open(REGISTRY) as f:
        reg = json.load(f)
    # map src abspath -> dst abspath for every dir that moves (skip a None src:
    # an anchor-less parent creates its dir, it doesn't move one)
    move_map = {}
    if parent[1] is not None:
        move_map[parent[1]] = parent[2]
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
    # Expected count derived from the map, not hardcoded per-persona.
    P = PERSONAS[persona]
    expect = (1 if P["parent"].get("registry_name") else 0) + \
             sum(1 for p in P["projects"] if p.get("registry"))
    print(f"\n  {c(str(hits) + ' registry entries rewritten', '36')} "
          f"(expected {expect})")


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
    if movers:
        dst = PERSONAS[persona]["parent"]["dst"]
        names = ", ".join(m["name"] for m in movers)
        print(f"\n  {c('ACTION (held):', '1;31')} rewrite the ktlyst-cluster.md rows "
              f"-> {dst}/projects/<x> for {names}.")
    else:
        print(f"\n  {c('No global-rule (ktlyst-cluster.md) dependencies for this persona.', '32')}")


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
    buckets = {"skip": [], "vendored": [], "self_live": [], "self_data": [],
               "canonical": []}
    moved_prefixes = tuple(os.path.join(PROJECTS, s) for s in pattern_names)
    for line in out.splitlines():
        rel = line.replace(PROJECTS + "/", "")
        if any(k in line for k in GREP_SKIP):
            buckets["skip"].append(rel)
        elif any(k in line for k in GREP_VENDORED):
            buckets["vendored"].append(rel)
        elif line.startswith(moved_prefixes):
            key = "self_live" if is_live_selfref(line) else "self_data"
            buckets[key].append(rel)
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
    print(f"\n  {c('SELF-REF: live code/config', '1;33')} — WILL be rewritten "
          f"(old->new self-path):")
    for f in b["self_live"]:
        print(f"    * {f}")
    if not b["self_live"]:
        print("    (none)")
    print(f"\n  {c('SELF-REF: data/evidence/history', '35')} — LEFT AS-IS "
          f"(forensic integrity; never rewritten): {len(b['self_data'])} files")
    print(f"\n  {c('VENDORED (kipi-mcp, fleet-synced)', '35')} — rewrite SKELETON copy "
          f"only; instances re-sync via kipi update:")
    for f in sorted(set(f.split('/', 1)[1] if '/' in f else f for f in b["vendored"]))[:6]:
        print(f"    * .../{f}")
    print(f"    ({len(b['vendored'])} copies total across the fleet — 1 skeleton source of truth)")
    print(f"\n  {c('SKIP (worktrees/git/archive noise)', '90')} — {len(b['skip'])} files, not rewritten")


def phase_gitignore(persona):
    hdr("PHASE G — parent .gitignore")
    parent = PERSONAS[persona]["parent"]
    # src until renamed; for an anchor-less (create) parent the bucket is new,
    # so the .gitignore is written fresh at apply.
    gi = os.path.join(parent["src"] if parent.get("src") else parent["dst"],
                      ".gitignore")
    print(f"\n  Add to {parent['dst']}/.gitignore (currently {gi}):")
    print(f"      {c('projects/', '32')}      # nested independent repos, not tracked by parent")


def phase_summary(persona):
    P = PERSONAS[persona]
    dstname = os.path.basename(P["parent"]["dst"])
    hdr(f"SUMMARY — {persona} dry run")
    parent, moves = build_moves(persona)
    create = P["parent"].get("create", False)
    missing = [m[0] for m in moves if not m[3]] + ([] if parent[3] else [parent[0]])
    n_reg = (0 if create else 1) + sum(1 for p in P["projects"] if p.get("registry"))
    n_plists = len(P["parent"].get("plists", [])) + sum(
        len(p.get("plists", [])) for p in P["projects"])
    n_rule = sum(1 for p in P["projects"] if p.get("rule"))
    n_bridge = sum(1 for p in P["projects"] if p.get("bridge"))
    parent_line = (f"1 bucket created       -> {dstname}/  (anchor-less, new)"
                   if create else
                   f"1 parent rename        {P['parent']['name']} -> {dstname}")
    print(f"""
  {parent_line}
  {len(moves)} project moves        -> {dstname}/projects/*
  {n_reg} registry rewrites
  {n_plists} launchd plists       rewrite + reload (verify each fires)
  {n_rule} global rule            {'ktlyst-cluster.md [HELD]' if n_rule else '(none)'}
  {n_bridge} bridge writer(s)
  + self-ref (live code/config only) + vendored rewrites (see Phase F)
  + .gitignore projects/ in parent
""")
    if missing:
        print(c(f"  ⚠ MISSING source dirs: {missing}", "1;31"))
    elif create:
        print(c(f"  ✓ all {len(moves)} source dirs present on disk "
                f"(parent bucket will be created)", "32"))
    else:
        print(c(f"  ✓ all {1 + len(moves)} source dirs present on disk", "32"))
    print(c("\n  NOTHING WAS CHANGED. Founder approval gates the real run.", "1;36"))


# =============================================================================
# APPLY — real moves, phased, reversible. Every rewrite is .bak'd; every move is
# recorded to a manifest so --rollback reverses the batch.
# =============================================================================
import shutil

# Per-persona manifest — each instance keeps its OWN rollback record so one
# persona's migration never clobbers another's (cole and consulting are separate).
def manifest_path(persona):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        f"persona-reorg-manifest-{persona}.json")

# Personas already migrated. run_apply() checks membership here and sys.exit(3)s
# on a match (see the `if persona in MIGRATED` line), so a later persona's run
# cannot touch a finished one's dirs/plists/registry.
# consulting was migrated 2026-07-06 too (ASK -> consulting done); listing it
# makes run_apply exit early on a re-run, same as cole-gtm.
MIGRATED = {"cole-gtm", "consulting", "micro-saas", "intel", "dev-tools"}

_MANIFEST_FILE = None  # set at run_apply / run_rollback entry

# Curated LIVE self-ref files inside random-stuff-ideas to rewrite on rename.
# Dated historical records (podcast distribution logs, rca/, prd-os/, output/
# plans, codex-handoff, skill-proposals) are point-in-time truth — left as-is.
LIVE_SELFREF = [
    "README.md",
    ".codex/hooks.json",
    "gtm/stores/_starter/build-stores.workflow.js",
    "gtm/stores/_starter/rebuild-stores.workflow.js",
    "gtm/stores/_starter/rebuild-scratch.workflow.js",
    "gtm/stores/_starter/rebuild-on-kit.workflow.js",
]
# Skeleton vendored copies that ref the competitive-analysis path (instances
# re-sync via kipi update, so only the skeleton source of truth is rewritten).
VENDORED_SKELETON = [
    "plugins/kipi-core/kipi-mcp/docs/competitive-intel-analyst.md",
    "plugins/kipi-core/kipi-mcp/examples/competitive-intel/ai-live-sources.json",
]
BASELINE_FAIL = 2  # kipi check FAILs pre-existing before this reorg (verified)

_manifest = {"moves": [], "baks": []}


def _save_manifest():
    with open(_MANIFEST_FILE, "w") as f:
        json.dump(_manifest, f, indent=2)


def _bak(path, suffix=".persona-reorg.bak"):
    """Snapshot a file before rewriting it (for rollback). Idempotent.

    `suffix` namespaces the backup so a later pass cannot restore an earlier
    pass's snapshot (finding-7): the reorg uses `.persona-reorg.bak`; the
    remediation uses `.remediation.bak`. If they shared a suffix, a remediation
    rollback would restore PRE-REORG content (the reorg's snapshot) instead of
    the pre-remediation state, because `_bak` no-ops when a backup already
    exists."""
    b = path + suffix
    if os.path.exists(path) and not os.path.exists(b):
        shutil.copy2(path, b)
        _manifest["baks"].append({"orig": path, "bak": b})


def _move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    _manifest["moves"].append({"src": src, "dst": dst})
    print(f"    moved {src}\n       -> {dst}")


def _mkdir(path):
    """Create a NEW dir for an anchor-less bucket. Recorded so rollback can
    os.rmdir it (empty-only — never rmtree; rollback stays non-destructive)."""
    os.makedirs(path, exist_ok=True)
    _manifest.setdefault("created", []).append({"type": "dir", "path": path})
    print(f"    created dir {path}")


def _create_file(path, content):
    """Write a NEW file (bucket .gitignore / roster CLAUDE.md). Recorded so
    rollback removes it. Not _bak'd — there is no prior version to restore."""
    with open(path, "w") as f:
        f.write(content)
    _manifest.setdefault("created", []).append({"type": "file", "path": path})
    print(f"    created {path}")


def _replace_in_file(path, old, new):
    if not os.path.isfile(path):
        return 0
    with open(path) as f:
        body = f.read()
    if old not in body:
        return 0
    _bak(path)
    with open(path, "w") as f:
        f.write(body.replace(old, new))
    return body.count(old)


def rewrite_registry_entries(pairs):
    """pairs: list of (registry_entry_name, new_abs_path). Rewrites only those
    entries — called right after each dir actually moves, so kipi check never
    sees a registry path pointing at a not-yet-moved dir."""
    _bak(REGISTRY)
    with open(REGISTRY) as f:
        reg = json.load(f)
    want = dict(pairs)
    n = 0
    for inst in reg.get("instances", []):
        if inst["name"] in want:
            inst["path"] = want[inst["name"]]; n += 1
    with open(REGISTRY, "w") as f:
        json.dump(reg, f, indent=2)
    print(f"    registry: {n} entries rewritten ({', '.join(k for k, _ in pairs)})")


SELFREF_EXTS = (".sh", ".py", ".js", ".ts", ".mjs", ".cjs", ".json", ".md",
                ".html", ".htm", ".yaml", ".yml", ".txt", ".plist", ".cfg",
                ".toml", ".env")
# .mjs/.cjs added 2026-07-06 (PRD reorg-stale-ref-remediation, finding-7): the
# reorg missed runreceipts' dogfood.mjs/cdp-shot.mjs + cole-gtm's render.mjs —
# absolute self-refs in ES-module scripts that were never rewritten.


def path_forms(abs_path):
    """Every textual form a `~/projects`-anchored path can appear as, in a fixed
    order so a matching old/new pair zips 1:1. Absolute first, then the HOME-rel
    forms, then the PROJECTS-rel form. Added for finding-7: the reorg rewrote
    only the absolute /Users/... form and missed ~, $HOME, ${HOME}, $PROJECTS."""
    forms = [abs_path]
    if abs_path == HOME or abs_path.startswith(HOME + os.sep):
        rel = abs_path[len(HOME):]                    # "/projects/..."
        forms += ["~" + rel, "$HOME" + rel, "${HOME}" + rel]
    if abs_path == PROJECTS or abs_path.startswith(PROJECTS + os.sep):
        forms.append("$PROJECTS" + abs_path[len(PROJECTS):])
    return forms


def rewrite_all_forms(body, old_abs, new_abs):
    """Replace every path form of old_abs with the matching form of new_abs.
    The forms have disjoint prefixes (old is top-level, new is nested), so
    order-independent; returns (new_body, total_refs_replaced)."""
    count = 0
    for old_f, new_f in zip(path_forms(old_abs), path_forms(new_abs)):
        count += body.count(old_f)
        body = body.replace(old_f, new_f)
    return body, count


def build_oldnew_map():
    """THE single source of the reorg's old-abspath -> new-abspath mapping,
    derived from PERSONAS (not hand-copied). The audit + the cross-project
    remediation both import this so they cannot drift from the reorg definition
    (finding-6). Covers renamed parents and every cascaded project, including
    src_sub moves (ktlyst-hub/<x>), which a flat name->newloc dict cannot express."""
    m = {}
    for persona, P in PERSONAS.items():
        p = P["parent"]
        if not p.get("create") and p.get("src"):
            m[p["src"]] = p["dst"]                     # renamed anchor parent
        projects_root = os.path.join(p["dst"], "projects")
        for proj in P["projects"]:
            src = os.path.join(PROJECTS, proj.get("src_sub", proj["name"]))
            m[src] = os.path.join(projects_root, proj["name"])
    return m
SELFREF_SKIP_DIRS = {".venv", "venv", ".git", "node_modules", "__pycache__",
                     ".next", "dist", "build", ".pytest_cache", ".mypy_cache",
                     "_codex-worktrees", "worktrees", ".playwright-mcp"}
# Path segments that hold DATA/EVIDENCE/HISTORY, never live execution paths.
# Rewriting these is at best pointless churn and at worst corrupts forensic
# investigation evidence (4_points holds chain-of-custody case captures). The
# rewriter only touches live code/config, never these.
SELFREF_SKIP_PATHSEG = ("/investigations/", "/evidence/", "/output/", "/data/",
                        "/memory/", "/drafts/", "/sessions/", "/archived",
                        "/.prd-os/", "/audits/", "/logs/", "/runs/")
# "/runs/": scraper OUTPUT captures + run-manifests (facebook-ads-library-search).
# Point-in-time evidence — a run-manifest records where a past run wrote; rewriting
# its paths falsifies that record. Same forensic class as evidence/. Added when the
# intel persona surfaced ~70 runs/ data files mis-flagged as live code (2026-07-06).


def is_live_selfref(path):
    """True if the rewriter will touch this file: live code/config, not data,
    evidence, history, or a vendored/venv dir."""
    if any(seg in path + "/" for seg in SELFREF_SKIP_PATHSEG):
        return False
    if "/.venv/" in path or "/venv/" in path or "/node_modules/" in path:
        return False
    return path.endswith(SELFREF_EXTS) and not path.endswith(".log")


def rewrite_selfrefs_in(root, old_abs, new_abs):
    """Walk `root` and rewrite the old absolute path to the new one in LIVE
    code/config only. Consulting's launchd scripts hardcode PROJECT=/REPO=
    absolute self-paths, so the move breaks them unless rewritten. Skips vendored
    dirs, logs, and any data/evidence/output/history path (forensic integrity)."""
    files = refs = 0
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SELFREF_SKIP_DIRS]
        if any(seg in dirpath + "/" for seg in SELFREF_SKIP_PATHSEG):
            continue
        for fn in names:
            if not fn.endswith(SELFREF_EXTS) or fn.endswith(".log"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp) as f:
                    body = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            new_body, n = rewrite_all_forms(body, old_abs, new_abs)
            if n == 0:
                continue
            _bak(fp)
            with open(fp, "w") as f:
                f.write(new_body)
            files += 1
            refs += n
    print(f"    self-refs in {os.path.basename(root)}: {refs} refs across {files} files")
    return files


# --- Cross-project remediation (finding-8) -----------------------------------
# Code/config only — NOT .md/.txt/.html. Blanket prose rewriting would corrupt
# narrative records (canonical/decisions.md literally says "random-stuff-ideas
# renamed to cole-gtm"; rewriting that yields "cole-gtm renamed to cole-gtm").
# Operator-doc prose is fixed by a separate, targeted edit.
REMEDIATE_EXTS = (".sh", ".py", ".js", ".ts", ".mjs", ".cjs", ".json", ".yaml",
                  ".yml", ".toml", ".cfg", ".plist", ".env")
REMEDIATE_BASENAMES = {"Makefile", "Dockerfile", ".env.local"}
# History / forensic / re-synced / point-in-time — never rewritten.
REMEDIATE_SKIP_SEG = SELFREF_SKIP_PATHSEG + (
    "persona-reorg-manifest", ".persona-reorg.bak", ".remediation.bak",
    "/kipi-mcp/", "/.claude/projects/", "/.claude/paste-cache/", "/.claude/todos/",
    "/.claude/plugins/marketplaces/", "/.claude/plugins/cache/", "/distribution/",
    "/platform/", "/_archive", "/.git/", "node_modules/", "/worktrees/",
    "/.playwright-mcp/")
# Vendored plugin dirs: an INSTANCE copy re-syncs from the skeleton on `kipi
# update`, so rewriting it is churn (overwritten next update) — rewrite only the
# skeleton copy under kipi-system/. The reorg's own tooling holds old paths as
# data/fixtures (PERSONAS map, test fixtures) and must never be rewritten.
_VENDORED_PLUGIN_SEG = ("/plugins/prd-os/", "/plugins/kipi-core/",
                        "/plugins/kipi-ops/", "/plugins/kipi-design/")
_TOOLING_BASENAMES = {"persona-reorg.py", "reorg-stale-ref-audit.py",
                      "test_persona_reorg.py"}
_SKELETON = os.path.join(PROJECTS, "kipi-system")


def _remediate_skip_file(fp):
    if os.path.basename(fp) in _TOOLING_BASENAMES:
        return True
    if any(v in fp for v in _VENDORED_PLUGIN_SEG) and \
            not fp.startswith(_SKELETON + os.sep):
        return True
    return False


def remediate_cross_project(apply=False):
    """Rewrite references FROM any project TO a moved sibling, fleet-wide, in live
    code/config (finding-8). The reorg's self-ref rewriter only fixed a moved dir's
    refs to its OWN old path; a reference from project A to moved-project B was
    never touched (reddit-build-radar -> product repos, cole-gtm/.mcp.json ->
    4_points). Because it also sees a moved project's own missed self-refs (in the
    ~/$HOME/$PROJECTS forms finding-7 hardened), one pass clears both. Uses
    build_oldnew_map() (single source) + rewrite_all_forms (all four forms).
    .remediation.bak-backed (distinct from the reorg's .persona-reorg.bak so
    rollback restores pre-remediation, not pre-reorg — finding-7). Dry by default."""
    global _MANIFEST_FILE, _manifest
    _MANIFEST_FILE = manifest_path("remediation")
    _manifest = {"moves": [], "baks": []}
    # longest old path first: a nested old (Pure_spectrum_Q/projects/x) rewrites
    # before its parent so the more-specific match wins.
    pairs = sorted(build_oldnew_map().items(), key=lambda kv: len(kv[0]), reverse=True)
    extra = [os.path.join(HOME, ".claude", "plugins", "installed_plugins.json")]
    touched = total = 0
    def do_file(fp):
        nonlocal touched, total
        if any(seg in fp for seg in REMEDIATE_SKIP_SEG):
            return
        if _remediate_skip_file(fp):
            return
        try:
            with open(fp) as f:
                body = f.read()
        except (UnicodeDecodeError, OSError, IsADirectoryError):
            return
        new_body, n = body, 0
        for old_abs, new_abs in pairs:
            new_body, k = rewrite_all_forms(new_body, old_abs, new_abs)
            n += k
        if n == 0:
            return
        if apply:
            _bak(fp, ".remediation.bak")
            with open(fp, "w") as f:
                f.write(new_body)
        touched += 1
        total += n
        print(f"    {'rewrote' if apply else 'would rewrite'} {n:>3} in {fp.replace(HOME, '~')}")
    for dirpath, dirs, names in os.walk(PROJECTS):
        dirs[:] = [d for d in dirs if d not in SELFREF_SKIP_DIRS]
        if any(seg in dirpath + "/" for seg in REMEDIATE_SKIP_SEG):
            continue
        for fn in names:
            if fn.endswith(".log"):
                continue
            if fn.endswith(REMEDIATE_EXTS) or fn in REMEDIATE_BASENAMES:
                do_file(os.path.join(dirpath, fn))
    for fp in extra:
        if os.path.isfile(fp):
            do_file(fp)
    print(f"\n  {total} cross-project refs across {touched} files "
          f"({'APPLIED (.remediation.bak backed)' if apply else 'DRY — nothing changed'})")
    if apply:
        _save_manifest()
    return touched


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def _git_worktree_count(path):
    """Number of LINKED worktrees on a git repo (excludes the main worktree).
    Used to warn in the dry run; 0 for non-git dirs."""
    if not os.path.exists(os.path.join(path, ".git")):
        return 0
    code, out = sh(["git", "-C", path, "worktree", "list"])
    if code != 0:
        return 0
    return max(0, len([l for l in out.splitlines() if l.strip()]) - 1)


def _repair_git_worktrees(repo_src, repo_dst):
    """Git worktrees hardcode absolute paths in .git/worktrees/<id>/gitdir and in
    each worktree's .git file; a dir move breaks both. NESTED worktrees (common
    for codex agent worktrees under .claude/worktrees/) move WITH the repo, so a
    bare `git worktree repair` only fixes the main tree's self-link — the linked
    worktrees stay pinned to the old path and go `prunable`. Fix in two steps:
    repair the main tree, then repair each moved worktree at its NEW path
    (verified 2026-07-06 on kipi-investigations — bare repair left 3 prunable)."""
    if not os.path.exists(os.path.join(repo_dst, ".git")):
        return
    if _git_worktree_count(repo_dst) == 0:
        return
    sh(["git", "-C", repo_dst, "worktree", "repair"])          # step 1: main tree
    # step 2: git still lists moved nested worktrees at their OLD path; map each
    # back under the new repo root and repair explicitly.
    _, out = sh(["git", "-C", repo_dst, "worktree", "list", "--porcelain"])
    new_paths = []
    for line in out.splitlines():
        if line.startswith("worktree "):
            wt = line[len("worktree "):].strip()
            if wt != repo_dst and wt.startswith(repo_src + os.sep):
                new_paths.append(repo_dst + wt[len(repo_src):])
    if new_paths:
        code, _ = sh(["git", "-C", repo_dst, "worktree", "repair"] + new_paths)
        print(c(f"    git worktree repair: {len(new_paths)} nested worktree(s) "
                f"re-linked to new path", "32" if code == 0 else "1;31"))
    else:
        print(c("    git worktree repair: main linkage repaired", "32"))


def verify_kipi_check():
    code, out = sh(["kipi", "check"])
    import re as _re
    m = _re.search(r"FAIL:\s*(\d+)", out)
    fails = int(m.group(1)) if m else -1
    ok = 0 <= fails <= BASELINE_FAIL
    print(c(f"    verify kipi check: FAIL={fails} (baseline {BASELINE_FAIL}) "
            f"{'OK' if ok else 'REGRESSION'}", "32" if ok else "1;31"))
    return ok


def verify_launchd(label):
    code, out = sh(["launchctl", "list"])
    ok = label in out
    print(c(f"    verify launchd '{label}' loaded: {'OK' if ok else 'MISSING'}",
            "32" if ok else "1;31"))
    return ok


def rewrite_reload_plist(pl, src, dst, do_reload):
    path = os.path.join(LAUNCHAGENTS, pl)
    label = pl.replace(".plist", "").replace(".disabled", "")
    if do_reload:
        sh(["launchctl", "unload", path])          # ignore if not loaded
    n = _replace_in_file(path, src, dst)
    print(f"    plist {pl}: {n} refs rewritten")
    if do_reload:
        code, out = sh(["launchctl", "load", path])
        if code != 0 and out:
            print(c(f"      load warning: {out}", "33"))
        verify_launchd(label)


def run_apply(persona):
    """Data-driven, persona-generic. Phase 1 = rename parent (+ its plists,
    registry entry, self-refs). Phase 2 = move each project (+ its plists,
    self-refs, registry entry). Phase 3 = roster + persona follow-ups. Verifies
    kipi check after phases 1 and 2; aborts (rollback-able) on regression."""
    if persona in MIGRATED:
        print(c(f"REFUSED: '{persona}' is already migrated. The tool will not touch "
                f"a finished persona. Use --rollback --persona {persona} if you must "
                f"reverse it.", "1;31"))
        sys.exit(3)
    global _MANIFEST_FILE, _manifest
    _MANIFEST_FILE = manifest_path(persona)
    _manifest = {"moves": [], "baks": []}
    P = PERSONAS[persona]
    p = P["parent"]
    projects_root = os.path.join(p["dst"], "projects")
    print(c(f"\n### persona-reorg APPLY — {persona} (reversible, manifested) ###", "1;35"))

    # ---- PHASE 1: parent — rename an anchor repo, or CREATE an empty bucket ----
    if p.get("create"):
        hdr("APPLY PHASE 1 — create anchor-less bucket + projects/ + .gitignore")
        _mkdir(p["dst"])
        _mkdir(os.path.join(p["dst"], "projects"))
        _create_file(os.path.join(p["dst"], ".gitignore"), "projects/\n")
        print("    .gitignore: projects/ (new bucket — nested repos untracked)")
    else:
        hdr("APPLY PHASE 1 — rename parent, its plists, registry entry, self-refs")
        _move(p["src"], p["dst"])
        for pl in p.get("plists", []):
            rewrite_reload_plist(pl, p["src"], p["dst"], do_reload=not pl.endswith(".disabled"))
        if p.get("registry_name"):
            rewrite_registry_entries([(p["registry_name"], p["dst"])])
        rewrite_selfrefs_in(p["dst"], p["src"], p["dst"])
        gi = os.path.join(p["dst"], ".gitignore")
        _bak(gi)
        with open(gi, "a") as f:
            f.write("\nprojects/\n")
        print("    .gitignore: added projects/")
    _save_manifest()
    if not verify_kipi_check():
        return _abort("Phase 1 kipi check regression")

    # ---- PHASE 2: move each project + its plists + self-refs + registry ----
    hdr("APPLY PHASE 2 — move projects into projects/, rewrite plists + self-refs")
    reg_pairs = []
    for proj in P["projects"]:
        src = resolve_src(proj)
        dst = os.path.join(projects_root, proj["name"])
        _move(src, dst)
        _repair_git_worktrees(src, dst)
        rewrite_selfrefs_in(dst, src, dst)
        for pl in proj.get("plists", []):
            rewrite_reload_plist(pl, src, dst, do_reload=not pl.endswith(".disabled"))
        if proj.get("registry"):
            reg_pairs.append((proj["registry"], dst))
        _save_manifest()
    if reg_pairs:
        rewrite_registry_entries(reg_pairs)
    _save_manifest()
    if not verify_kipi_check():
        return _abort("Phase 2 kipi check regression")

    # ---- PHASE 3: roster + optional persona-specific follow-ups ----
    hdr("APPLY PHASE 3 — roster + persona follow-ups")
    _write_roster(persona)
    for v in P.get("vendored", []):  # optional: skeleton vendored rewrites
        skroot = os.path.join(PROJECTS, "kipi-system")
        vn = sum(_replace_in_file(os.path.join(skroot, rel), v["old"], v["new"])
                 for rel in v["files"])
        print(f"    vendored skeleton: {vn} refs rewritten (fleet re-syncs via kipi update)")
    _save_manifest()

    held = [proj for proj in P["projects"] if proj.get("rule")]
    if held:
        hdr("HELD — global rule edits (cross-instance preflight — founder confirm)")
        for proj in held:
            print(c(f"    {proj['rule']}: '{proj['name']}' row needs an old->new "
                    f"path rewrite (NOT applied).", "1;33"))

    hdr("APPLY COMPLETE")
    print(c(f"  Manifest: {_MANIFEST_FILE}  "
            f"(--rollback --persona {persona} reverses this batch)", "36"))
    venvs = [proj["name"] for proj in P["projects"]
             if os.path.isdir(os.path.join(projects_root, proj["name"], ".venv"))]
    if os.path.isdir(os.path.join(p["dst"], ".venv")):
        venvs.append(p["name"])
    if venvs:
        print(c(f"  venv note: recreate .venv in {', '.join(venvs)} "
                f"(absolute paths went stale on move).", "33"))


def _write_roster(persona):
    p = PERSONAS[persona]["parent"]
    claude = os.path.join(p["dst"], "CLAUDE.md")
    projs = PERSONAS[persona]["projects"]
    roster_lines = [f"- `projects/{proj['name']}/`\n" for proj in projs]
    if not os.path.isfile(claude):
        # Anchor-less bucket has no CLAUDE.md yet — create one as the roster.
        if p.get("create"):
            body = (f"# {persona} portfolio\n\n"
                    f"Bucket persona (no brain repo). Projects under it:\n\n"
                    + "".join(roster_lines))
            _create_file(claude, body)
            print(f"    roster: CLAUDE.md created with {len(projs)} projects")
        else:
            print(c("    CLAUDE.md missing — roster skipped", "31"))
        return
    _bak(claude)
    roster = [f"\n\n## {persona} portfolio (projects/*) — route here\n"] + roster_lines
    with open(claude, "a") as f:
        f.write("".join(roster))
    print(f"    roster: {len(projs)} projects added to CLAUDE.md")


def _abort(why):
    print(c(f"\n  ABORT: {why}. Manifest saved; run --rollback to reverse.", "1;31"))
    _save_manifest()
    sys.exit(2)


def run_rollback(persona):
    global _MANIFEST_FILE
    _MANIFEST_FILE = manifest_path(persona)
    if not os.path.isfile(_MANIFEST_FILE):
        print(c(f"No manifest for '{persona}' — nothing to roll back.", "31"))
        sys.exit(1)
    with open(_MANIFEST_FILE) as f:
        man = json.load(f)
    print(c(f"### persona-reorg ROLLBACK — {persona} ###", "1;35"))
    for b in reversed(man.get("baks", [])):
        if os.path.exists(b["bak"]):
            shutil.copy2(b["bak"], b["orig"])
            print(f"    restored {b['orig']}")
    for mv in reversed(man.get("moves", [])):
        if os.path.isdir(mv["dst"]):
            shutil.move(mv["dst"], mv["src"])
            print(f"    moved back {mv['dst']} -> {mv['src']}")
            # Symmetric with apply: a moved-back git repo's nested worktrees are
            # now pinned to the (new) location it just left — re-link them to the
            # restored path. Worktrees are currently linked to mv["dst"]; the repo
            # now lives at mv["src"]. No-op when the repo has no worktrees.
            _repair_git_worktrees(mv["dst"], mv["src"])
    # Anchor-less buckets: remove what the tool created. Files first, then dirs
    # via os.rmdir (empty-only — a non-empty bucket is KEPT and flagged, never
    # rmtree'd; rollback must not destroy anything it did not create).
    for cr in reversed(man.get("created", [])):
        pth = cr["path"]
        try:
            if cr["type"] == "file" and os.path.isfile(pth):
                os.remove(pth); print(f"    removed created file {pth}")
            elif cr["type"] == "dir" and os.path.isdir(pth):
                os.rmdir(pth); print(f"    removed created dir {pth}")
        except OSError as e:
            print(c(f"    KEPT {pth} (not empty / {e})", "33"))
    print(c("  Rollback done. Reload launchd plists manually if they were live.", "36"))


def _gtm_selfref_scan():
    """(live, data) file lists inside products/ that reference the old ASK root."""
    ge = GTM_EXTRACT
    out = subprocess.run(
        ["grep", "-rIl", "-F", ge["old_root"], ge["src"],
         "--exclude-dir=node_modules", "--exclude-dir=.git", "--exclude-dir=.venv"],
        capture_output=True, text=True).stdout
    live, data = [], []
    for line in out.splitlines():
        (live if is_live_selfref(line) else data).append(line.replace(PROJECTS + "/", ""))
    return live, data


def gtm_extract_preview():
    ge = GTM_EXTRACT
    print(c(f"\n### GTM EXTRACT DRY RUN — {ge['label']} ###", "1;35"))
    print("Reads live paths/plists/grep. Changes nothing.")

    hdr("PHASE 1 — move the products/ subtree out of ASK, into cole-gtm")
    exists = os.path.isdir(ge["src"])
    print(f"\n  {ge['src']}")
    print(f"   -> {ge['dst']}   [{c('OK' if exists else 'MISSING', '32' if exists else '1;31')}]")
    print(c("  GROWS cole-gtm on purpose (founder: Cole owns all GTM).", "33"))

    hdr("PHASE 2 — repoint + reload the 5 claudedaddy jobs")
    for pl in ge["plists"]:
        path = os.path.join(LAUNCHAGENTS, pl)
        n = 0
        if os.path.isfile(path):
            with open(path) as f:
                n = f.read().count(ge["old_root"])
        loaded = pl.replace(".plist", "") in sh(["launchctl", "list"])[1]
        flag = "loaded" if loaded else c("NOT loaded", "1;31")
        print(f"\n  {c(pl, '1;33')}  ({n} refs, {flag})  [rewrite + reload + verify fires]")
        print(f"      s|{ge['old_root']}|{ge['new_root']}|")

    hdr("PHASE 3 — self-ref rewrite inside products/ (live code only)")
    live, data = _gtm_selfref_scan()
    print(f"\n  {c('WILL rewrite', '1;33')} (live code/config, {len(live)} files):")
    for f in live[:40]:
        print(f"    * {f}")
    if len(live) > 40:
        print(f"    ... +{len(live) - 40} more")
    print(f"\n  {c('LEFT AS-IS', '35')} (data/generated/history, never rewritten): {len(data)} files")

    hdr("VERIFY PLAN + SUMMARY")
    print(f"  move: 1 subtree (products/)   plists: {len(ge['plists'])} rewrite+reload+verify")
    print(f"  self-ref: {len(live)} live rewritten, {len(data)} data left")
    print("  - kipi check stays at baseline (products/ is not a registry instance)")
    print("  - all 5 claudedaddy jobs loaded after reload (launchctl list)")
    print(c("\n  NOTHING CHANGED. Approve to run: --gtm-extract --apply.", "1;36"))


def gtm_extract_apply():
    global _MANIFEST_FILE, _manifest
    _MANIFEST_FILE = manifest_path("gtm-extract")
    _manifest = {"moves": [], "baks": []}
    ge = GTM_EXTRACT
    print(c(f"\n### GTM EXTRACT APPLY — {ge['label']} (reversible) ###", "1;35"))

    hdr("PHASE 1 — move products/ into cole-gtm")
    if not os.path.isdir(ge["src"]):
        print(c(f"  source missing: {ge['src']}", "1;31"))
        sys.exit(3)
    _move(ge["src"], ge["dst"])
    _save_manifest()

    hdr("PHASE 2 — repoint + reload the 5 claudedaddy jobs")
    for pl in ge["plists"]:
        rewrite_reload_plist(pl, ge["old_root"], ge["new_root"], do_reload=True)

    hdr("PHASE 3 — self-ref rewrite inside products/ (live code only)")
    rewrite_selfrefs_in(ge["dst"], ge["old_root"], ge["new_root"])
    _save_manifest()

    if not verify_kipi_check():
        return _abort("GTM-extract kipi check regression")

    hdr("GTM EXTRACT COMPLETE")
    print(c(f"  Manifest: {_MANIFEST_FILE}  "
            f"(--rollback --persona gtm-extract reverses this)", "36"))
    print(c("  NEXT: confirm a claudedaddy job fires from cole-gtm, then Part 2 "
            "(ASK->consulting) + retire the bridge.", "33"))


def main():
    ap = argparse.ArgumentParser(description="Fleet persona reorg (dry by default).")
    ap.add_argument("--persona", default="cole-gtm",
                    choices=list(PERSONAS) + ["gtm-extract", "remediation"])
    ap.add_argument("--dry", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true", help="Execute the phased, reversible moves.")
    ap.add_argument("--rollback", action="store_true", help="Reverse the last apply via manifest.")
    ap.add_argument("--gtm-extract", dest="gtm_extract", action="store_true",
                    help="Part 1: extract ASK products/ into cole-gtm (dry unless --apply).")
    ap.add_argument("--remediate", action="store_true",
                    help="Cross-project stale-ref remediation over already-moved "
                         "dirs (finding-8; dry unless --apply).")
    args = ap.parse_args()

    if args.rollback:
        run_rollback(args.persona)
        return
    if args.remediate:
        print(c("\n### persona-reorg CROSS-PROJECT REMEDIATION"
                f" ({'APPLY' if args.apply else 'DRY'}) ###", "1;35"))
        remediate_cross_project(apply=args.apply)
        return
    if args.gtm_extract:
        gtm_extract_apply() if args.apply else gtm_extract_preview()
        return
    if args.apply:
        run_apply(args.persona)
        return

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
