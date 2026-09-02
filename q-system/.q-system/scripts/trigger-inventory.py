#!/usr/bin/env python3
"""Which stages actually have a trigger, derived from the tree, not from a list.

Issue lr-trigger-inventory (prd-lessons-rail-and-up-rail, plan 4d, CAP-2).
Measured 2026-09-01: three stages were built, correct and never running
(route-overrides-to-learn.py, the propagation call, the upstream push), and a
repo-wide grep for one script name returned 184 hits in dead worktree copies.
Three is a class: `every-stage-needs-its-own-trigger`.

Candidates are every *.py and *.sh directly under q-system/.q-system/scripts/
plus every repo-root *.sh. There is NO registry of stages (Codex finding-6 on
the PRD): a script nobody registered is exactly the one this exists to find.
q-system/.q-system/stages-exempt.json names libraries that have no trigger by
design, each with a reason; an entry whose file is gone exits 2.

Trigger surfaces read: plist templates in scripts/, installed plists
(KIPI_INSTALLED_PLISTS, default ~/Library/LaunchAgents), .claude/settings.json
hook commands, plugins/*/hooks/hooks.json, .github/workflows/*.yml,
lefthook.yml. A script named by a triggered script's non-comment text is
triggered transitively (via that script). The `kipi` CLI is a MANUAL entry
point, not a trigger: a stage reachable only by someone typing a command is
"manual-only", which is what the upstream push was.

Scope: .claude/worktrees/ and .wt-* are never scanned as stages; the report
prints how many trees and scripts that excluded (an audit that only works on
a tidy repo is not an audit).

Known limit: a script named inside another script's docstring counts as named;
comment lines (leading #) are stripped, docstrings are not.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import plistlib
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.realpath(os.path.join(HERE, "..", "..", ".."))
SCRIPTS_REL = "q-system/.q-system/scripts"
EXEMPT_REL = "q-system/.q-system/stages-exempt.json"
EXCLUDED = ((".claude/worktrees/", ".claude/worktrees/*"), (".wt-*", ".wt-*"))


def candidates(root):
    """Every *.py and *.sh anywhere under scripts/ (recursive: a script parked
    in a subdirectory is still a stage, Codex standard review) plus root *.sh."""
    out = []
    for pat in ("**/*.py", "**/*.sh"):
        out += [os.path.relpath(p, root) for p in glob.glob(os.path.join(root, SCRIPTS_REL, pat), recursive=True)]
    out += [os.path.relpath(p, root) for p in glob.glob(os.path.join(root, "*.sh"))]
    return sorted(set(out))


def excluded_scope(root):
    report = {}
    for label, pat in EXCLUDED:
        trees = [t for t in glob.glob(os.path.join(root, pat)) if os.path.isdir(t)]
        scripts = 0
        for t in trees:
            for p in ("*.py", "*.sh"):
                scripts += len(glob.glob(os.path.join(t, SCRIPTS_REL, p)))
            scripts += len(glob.glob(os.path.join(t, "*.sh")))
        report[label] = {"trees": len(trees), "scripts": scripts}
    return report


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _plist_text(path):
    try:
        with open(path, "rb") as fh:
            data = plistlib.load(fh)
        args = data.get("ProgramArguments", [])
        return " ".join(str(a) for a in args)
    except Exception:
        return _read(path)


def _hook_commands(settings_path):
    try:
        data = json.loads(_read(settings_path) or "{}")
    except ValueError:
        return _read(settings_path)
    cmds = []
    for groups in (data.get("hooks") or {}).values():
        for group in groups or []:
            for hook in group.get("hooks", []) or []:
                cmds.append(str(hook.get("command", "")))
    return "\n".join(cmds)


def trigger_sources(root, installed_dir):
    """(kind, name, text) for every registered trigger surface."""
    src = []
    for p in sorted(glob.glob(os.path.join(root, SCRIPTS_REL, "com.kipi.*.plist"))):
        src.append(("plist template", os.path.relpath(p, root), _plist_text(p)))
    for p in sorted(glob.glob(os.path.join(installed_dir, "com.kipi.*.plist"))):
        src.append(("installed plist", os.path.basename(p), _plist_text(p)))
    settings = os.path.join(root, ".claude", "settings.json")
    if os.path.exists(settings):
        src.append(("settings hook", ".claude/settings.json", _hook_commands(settings)))
    for p in sorted(glob.glob(os.path.join(root, "plugins", "*", "hooks", "hooks.json"))):
        src.append(("plugin hook", os.path.relpath(p, root), _read(p)))
    for p in sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.yml")) +
                    glob.glob(os.path.join(root, ".github", "workflows", "*.yaml"))):
        src.append(("workflow", os.path.relpath(p, root), _read(p)))
    lefthook = os.path.join(root, "lefthook.yml")
    if os.path.exists(lefthook):
        src.append(("lefthook", "lefthook.yml", _read(lefthook)))
    # The capability manifest: every fragment names a test file that verify.sh
    # (pre-commit + CI) runs. Measured 2026-09-01 before this surface was read:
    # 98 "dead" stages, most of them test files the manifest runs nightly.
    frags = sorted(glob.glob(os.path.join(root, "q-system", ".q-system", "capability", "expected_tests", "*.json")))
    if frags:
        paths = []
        for f in frags:
            try:
                paths.append(str(json.loads(_read(f)).get("path", "")))
            except ValueError:
                continue
        src.append(("capability manifest", f"{len(frags)} fragments", "\n".join(paths)))
    return src


def manual_sources(root):
    """Entry points a PERSON or an agent invokes on demand: the kipi CLI, slash
    commands, skills, MCP tools. Reachable, never scheduled: manual-only."""
    out = []
    cli = os.path.join(root, "kipi")
    if os.path.exists(cli):
        out.append(("kipi CLI", "kipi", _read(cli)))
    for kind, pat in (("slash command", "plugins/*/commands/*.md"), ("skill", "plugins/*/skills/*/SKILL.md"),
                      ("mcp server", "plugins/*/mcp/*.py"), ("mcp server", "plugins/*/mcp/**/*.py"),
                      ("plugin script", "plugins/*/scripts/*"), ("skill script", "plugins/*/skills/*/scripts/*"),
                      ("agent", ".claude/agents/*.md")):
        for p in sorted(glob.glob(os.path.join(root, pat), recursive=True)):
            if os.path.isfile(p):
                out.append((kind, os.path.relpath(p, root), _read(p)))
    return out


def _name_pattern(rel, cands):
    """A file name shared by two candidates (root foo.sh and scripts/foo.sh) must
    not let one trigger mark both (Codex adversarial review): an ambiguous name
    is matched with its parent directory, or, for a root script, only when no
    directory precedes it."""
    base = os.path.basename(rel)
    ambiguous = sum(1 for c in cands if os.path.basename(c) == base) > 1
    if not ambiguous:
        return r"(?<![\w.-])" + re.escape(base) + r"(?![\w-])"
    if os.sep in rel:
        parent = os.path.basename(os.path.dirname(rel))
        return r"(?<![\w.-])" + re.escape(parent + "/" + base) + r"(?![\w-])"
    return r"(?<![\w./-])" + re.escape(base) + r"(?![\w-])"


def _named(text, cands):
    """Candidates a text names: by file name, or (for .py) by import statement,
    since `import foo` carries no .py suffix and is how a library is reached."""
    hits = []
    for rel in cands:
        base = os.path.basename(rel)
        if re.search(_name_pattern(rel, cands), text):
            hits.append(rel)
            continue
        if base.endswith(".py"):
            stem = re.escape(base[:-3])
            if re.search(r"(?m)^\s*(?:import\s+" + stem + r"\b|from\s+" + stem + r"\s+import\b)", text):
                hits.append(rel)
            elif re.search(r"""["']""" + stem + r"""["']""", text):
                hits.append(rel)  # dynamic load by stem string (morning-brief's _optional_module)
    return hits


def _code_text(path):
    return "\n".join(l for l in _read(path).splitlines() if not l.lstrip().startswith("#"))


def load_exemptions(root):
    path = os.path.join(root, EXEMPT_REL)
    if not os.path.exists(path):
        return {}, []
    try:
        data = json.loads(_read(path))
    except ValueError as exc:
        return {}, [f"{EXEMPT_REL} is not valid JSON: {exc}"]
    problems, exempt = [], {}
    for entry in data.get("exempt", []):
        rel, reason = entry.get("path"), entry.get("reason")
        if not rel or not reason:
            problems.append(f"exemption without a path or reason: {entry}")
            continue
        if not os.path.exists(os.path.join(root, rel)):
            problems.append(f"stale exemption: {rel} does not exist")
            continue
        exempt[rel] = reason
    return exempt, problems


def inventory(root, installed_dir):
    cands = candidates(root)
    exempt, problems = load_exemptions(root)
    stages = {rel: {"status": "dead", "via": [], "sources": []} for rel in cands}
    sources = trigger_sources(root, installed_dir)
    queue = []
    for kind, name, text in sources:
        for rel in _named(text, cands):
            st = stages[rel]
            st["status"] = "triggered"
            st["sources"].append(f"{kind}: {name}")
            queue.append(rel)
    seen = set()
    while queue:
        rel = queue.pop(0)
        if rel in seen:
            continue
        seen.add(rel)
        for other in _named(_code_text(os.path.join(root, rel)), cands):
            if other == rel:
                continue
            st = stages[other]
            if not st["sources"] and rel not in st["via"]:
                st["via"].append(rel)  # every triggered namer, so the report says who reaches it
            if st["status"] != "triggered":
                st["status"] = "triggered"
                queue.append(other)
    for kind, name, text in manual_sources(root):
        for rel in _named(text, cands):
            if stages[rel]["status"] == "dead":
                stages[rel]["status"] = "manual-only"
                stages[rel]["sources"].append(f"{kind}: {name}")
    for rel, reason in exempt.items():
        if rel in stages and stages[rel]["status"] == "dead":
            stages[rel]["status"] = "exempt"
            stages[rel]["reason"] = reason
    return {
        "root": root,
        "stages": stages,
        "dead": sorted(r for r, s in stages.items() if s["status"] == "dead"),
        "excluded": excluded_scope(root),
        "triggers_read": [f"{kind}: {name}" for kind, name, _ in sources],
        "problems": problems,
    }


def render(inv):
    counts = {}
    for s in inv["stages"].values():
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    lines = [f"trigger inventory for {inv['root']}",
             f"triggers read: {len(inv['triggers_read'])} ({sum(1 for t in inv['triggers_read'] if t.startswith('installed plist'))} installed plists)"]
    for status, title in (("triggered", "TRIGGERED"), ("manual-only", "MANUAL-ONLY"), ("exempt", "EXEMPT"), ("dead", "DEAD")):
        lines.append(f"{title} ({counts.get(status, 0)})")
        for rel, s in sorted(inv["stages"].items()):
            if s["status"] != status:
                continue
            how = ", ".join(s["sources"]) or (f"via {s['via'][0]}" if s["via"] else "") or s.get("reason", "")
            lines.append(f"  {rel}" + (f"  [{how}]" if how else ""))
    ex = inv["excluded"]
    lines.append("excluded: " + "; ".join(f"{k} {v['trees']} tree(s), {v['scripts']} script(s)" for k, v in ex.items()))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    installed = os.environ.get("KIPI_INSTALLED_PLISTS") or os.path.expanduser("~/Library/LaunchAgents")
    root = os.path.realpath(a.root)
    if not os.path.isdir(os.path.join(root, SCRIPTS_REL)):
        print(f"trigger-inventory: {root} has no {SCRIPTS_REL}; broken apparatus", file=sys.stderr)
        return 3
    inv = inventory(root, installed)
    if inv["problems"]:
        for p in inv["problems"]:
            print(f"trigger-inventory: {p}", file=sys.stderr)
        return 2
    print(json.dumps(inv, indent=1) if a.json else render(inv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
