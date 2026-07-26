#!/usr/bin/env python3
"""Generate a CAPABILITY-MAP.json for a kipi instance repo by structural recon.

Pairs with linear-sync.py (which turns a map into a Linear plan) and the SDLC
standard at q-system/output/plans/linear-sdlc-standard-2026-07-26.md.

WHY A GENERATOR AND NOT 24 HAND-WRITTEN MAPS (ASK-113): a hand-written map is
accurate for one afternoon. It drifts the moment a command is added, and nothing
detects the drift. This walks the repo and reports what is ACTUALLY there, so
re-running it is how you notice a capability appeared or a hook went dead.

WHAT IT WILL NOT DO: it does not judge whether a capability is *good*, and it does
not invent evidence. Every `evidence` string it emits is a fact it read off disk
(a path, a line count, a wiring reference it found or failed to find). Status is
derived from wiring, not from claims in prose. The senior-engineer triage pass
adds judgment on top of this; it does not replace it.

THE VALUABLE DETECTION: a hook wired in settings.json whose script does not exist
on disk. That is a dead enforcement gate -- the switch is on and nothing is behind
it -- and it is invisible to every prose-level review.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Layers, in the order they appear in the emitted map.
L_GOVERNANCE = "L0 Governance and rules"
L_COMMANDS = "L1 Commands"
L_SKILLS = "L2 Skills"
L_ENFORCEMENT = "L3 Enforcement and automation"
L_AGENTS = "L4 Agents"
L_ENGINES = "L5 Engines and scripts"
L_DOMAIN = "L6 Domain data"

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
    "dist", "build", ".next", ".claude-plugin", "archives",
    "site-packages", "dist-packages", "vendor", ".mypy_cache", ".ruff_cache",
    ".tox", "eggs", ".eggs", "htmlcov", ".terraform",
}

# Substrings that mark a vendored tree wherever they appear in a path. Directory
# NAME matching alone was not enough: 4_points_consulting keeps a virtualenv under
# q-investigate/ whose inner dirs are named lib/ and python3.x/, so a name-only
# filter admitted 5450 site-packages files as "engines" (recon run 2026-07-26).
VENDOR_MARKERS = ("site-packages", "dist-packages", "/node_modules/", "/.git/")


# Roots of git repos nested INSIDE the repo being scanned. Populated per run.
#
# WHY (ASK-113): several instances contain other instances. ASK_AI_consultant is
# ~/projects/consulting, which holds 12 sibling instance repos under projects/;
# gtm-partner is ~/projects/cole-gtm, which holds 5. Without this, a parent's map
# swallows every child's capabilities and the fleet is counted several times over
# (first full run: 12430 capabilities, badly inflated). A nested git repo is a
# separate unit of propagation and gets its own map and its own Linear project.
_NESTED_REPOS: set = set()


def find_nested_repos(root: Path) -> set:
    """Directories under `root` that are their own git repo (or worktree)."""
    found = set()
    for git in root.rglob(".git"):
        parent = git.parent
        if parent.resolve() == root.resolve():
            continue
        if any(d in SKIP_DIRS for d in parent.parts):
            continue
        found.add(parent.resolve())
    return found


def is_vendored(p: Path) -> bool:
    if any(d in SKIP_DIRS for d in p.parts):
        return True
    if _NESTED_REPOS:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        for nested in _NESTED_REPOS:
            if nested in rp.parents:
                return True
    s = "/" + str(p).replace(os.sep, "/") + "/"
    if any(m in s for m in VENDOR_MARKERS):
        return True
    # A virtualenv identifies itself with pyvenv.cfg at its root; anything under
    # such a directory is a dependency, not a capability of this repo.
    for parent in p.parents:
        if (parent / "pyvenv.cfg").exists():
            return True
        if parent.name in ("bin", "lib") and (parent.parent / "pyvenv.cfg").exists():
            return True
    return False


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except OSError:
        return ""


def frontmatter_description(text: str) -> str:
    """Pull `description:` out of a markdown frontmatter block, if present."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    for line in text[3:end].splitlines():
        if line.strip().startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


def first_prose_line(text: str) -> str:
    """First real sentence, skipping frontmatter, headings, and code fences."""
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body = text[end + 4:]
    in_fence = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s or s.startswith(("#", "|", ">", "-", "*", "<!--")):
            continue
        return s[:200]
    return ""


def summarize(text: str, fallback: str) -> str:
    return frontmatter_description(text) or first_prose_line(text) or fallback


def walk(root: Path, *parts):
    """Glob helper that skips vendored and cache directories."""
    base = root.joinpath(*parts[:-1]) if len(parts) > 1 else root
    if not base.is_dir():
        return []
    out = []
    for p in base.rglob(parts[-1]):
        if is_vendored(p):
            continue
        if p.is_file():
            out.append(p)
    return sorted(out)


def rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


# --- collectors ---------------------------------------------------------------


def collect_commands(root: Path) -> list:
    caps = []
    seen = set()
    for base in (root / ".claude" / "commands", root / "plugins"):
        if not base.is_dir():
            continue
        for p in base.rglob("*.md"):
            if is_vendored(p):
                continue
            if base.name == "plugins" and "commands" not in p.parts:
                continue
            name = f"/{p.stem}"
            if name in seen:
                continue
            seen.add(name)
            text = read_text(p)
            caps.append({
                "name": f"command {name}",
                "layer": L_COMMANDS,
                "status": "LIVE" if len(text.strip()) > 120 else "NEEDS_WORK",
                "summary": summarize(text, f"Slash command {name}."),
                "entry": rel(root, p),
                "trigger": f"manual: {name}",
                "evidence": f"{rel(root, p)}: {len(text.splitlines())} lines on disk."
                            + ("" if len(text.strip()) > 120 else " Body is near-empty, so the command is a stub."),
            })
    return caps


def collect_skills(root: Path) -> list:
    caps = []
    for p in root.rglob("SKILL.md"):
        if is_vendored(p):
            continue
        text = read_text(p)
        name = p.parent.name
        caps.append({
            "name": f"skill {name}",
            "layer": L_SKILLS,
            "status": "LIVE",
            "summary": summarize(text, f"Skill {name}."),
            "entry": rel(root, p),
            "trigger": "model-invoked, or an auto-invoke rule",
            "evidence": f"{rel(root, p)}: {len(text.splitlines())} lines on disk.",
        })
    return caps


def collect_rules(root: Path) -> list:
    caps = []
    for p in walk(root, ".claude", "rules", "*.md"):
        text = read_text(p)
        enforced = "ENFORCED" in text
        named = re.findall(r"[\w\-/]+\.(?:py|sh)\b", text)
        caps.append({
            "name": f"rule {p.stem}",
            "layer": L_GOVERNANCE,
            "status": "LIVE" if (not enforced or named) else "NEEDS_WORK",
            "summary": summarize(text, f"Rule {p.stem}."),
            "entry": rel(root, p),
            "trigger": "always-on instruction context",
            "evidence": (
                f"{rel(root, p)}: {len(text.splitlines())} lines; "
                + (f"claims ENFORCED and names {len(set(named))} executable(s)."
                   if enforced and named else
                   "claims ENFORCED but names NO executable, so it is prompt-only."
                   if enforced else "advisory, no enforcement claim.")
            ),
        })
    return caps


def collect_hooks(root: Path) -> list:
    """The high-value pass: a hook wired in settings.json whose script is gone."""
    caps = []
    settings = root / ".claude" / "settings.json"
    if not settings.is_file():
        return caps
    try:
        data = json.loads(read_text(settings) or "{}")
    except json.JSONDecodeError:
        return [{
            "name": "hook wiring (settings.json)",
            "layer": L_ENFORCEMENT,
            "status": "BROKEN",
            "summary": "settings.json does not parse as JSON, so no hook in it can load.",
            "entry": rel(root, settings),
            "trigger": "session lifecycle",
            "evidence": f"{rel(root, settings)}: json.JSONDecodeError on parse.",
        }]

    for event, groups in (data.get("hooks") or {}).items():
        for group in groups if isinstance(groups, list) else []:
            for hook in (group.get("hooks") or []):
                cmd = hook.get("command") or ""
                scripts = re.findall(r"[\w\-./${}]+\.(?:py|sh)", cmd)
                resolved, missing = [], []
                for s in scripts:
                    clean = (s.replace("${CLAUDE_PROJECT_DIR}", "")
                              .replace("$CLAUDE_PROJECT_DIR", "").lstrip("/"))
                    if "${" in clean or "$" in clean:
                        continue
                    (resolved if (root / clean).is_file() else missing).append(clean)
                if not scripts:
                    continue
                label = os.path.basename(scripts[0])
                caps.append({
                    "name": f"hook {label} ({event})",
                    "layer": L_ENFORCEMENT,
                    "status": "BROKEN" if missing else "LIVE",
                    "summary": (f"{event} hook running {label}."
                                + (" Its script is MISSING from disk."
                                   if missing else "")),
                    "entry": f".claude/settings.json -> {label}",
                    "trigger": f"{event} ({group.get('matcher', 'all')})",
                    "evidence": (
                        f"Wired in .claude/settings.json under {event}. "
                        + (f"MISSING on disk: {', '.join(missing)}. The switch is on "
                           f"and nothing is behind it."
                           if missing else
                           f"Script present: {', '.join(resolved) if resolved else label}.")
                    ),
                })
    return caps


def collect_agents(root: Path) -> list:
    caps = []
    for p in walk(root, ".claude", "agents", "*.md"):
        text = read_text(p)
        m = re.search(r"^model:\s*(\S+)", text, re.M)
        caps.append({
            "name": f"agent {p.stem}",
            "layer": L_AGENTS,
            "status": "LIVE" if m else "NEEDS_WORK",
            "summary": summarize(text, f"Agent {p.stem}."),
            "entry": rel(root, p),
            "trigger": "invoked by an orchestrator or the Agent tool",
            "evidence": (f"{rel(root, p)}: model pinned to {m.group(1)}."
                         if m else
                         f"{rel(root, p)}: NO model: frontmatter, so tier is unpinned."),
        })
    return caps


def _docstring_line(text: str) -> str:
    """First line of a module docstring, or '' if there is not a well-formed one."""
    parts = text.split('"""')
    if len(parts) < 3:
        return ""
    lines = [ln.strip() for ln in parts[1].strip().splitlines() if ln.strip()]
    return lines[0][:180] if lines else ""


def collect_engines(root: Path) -> list:
    """Scripts that have a paired test, or that are referenced from a wiring
    surface. An engine with neither is reported UNWIRED rather than assumed fine."""
    caps = []
    tests = {p.name for p in root.rglob("test*") if p.is_file() and not is_vendored(p)}

    # Wiring surfaces mirror capability-gate.py's WIRING_SURFACE_GLOBS. A narrower
    # list reports UNWIRED for engines that are in fact called by another engine or
    # by the kipi CLI: the first run of this generator flagged 60 UNWIRED in
    # 4_points_consulting purely because python-calls-python was never read.
    surfaces = ""
    for pat in (".claude/settings.json", "settings-template.json", "lefthook.yml",
                "Makefile", "*.sh", "kipi*", "validate-separation.py",
                ".github/workflows/*.yml", "*/hooks/hooks.json", "*/*/hooks.json"):
        for p in root.glob(pat):
            if p.is_file() and not is_vendored(p):
                surfaces += read_text(p)
    for sub in (root / ".claude", root / "plugins", root / "q-system"):
        if not sub.is_dir():
            continue
        for pattern in ("*.md", "*.py", "*.sh", "*.json"):
            for p in sub.rglob(pattern):
                if is_vendored(p) or p.name.startswith(("test_", "test-")):
                    continue
                surfaces += read_text(p)

    for p in root.rglob("*.py"):
        if is_vendored(p):
            continue
        if p.name.startswith(("test_", "test-")) or "test" in p.parts:
            continue
        text = read_text(p)
        if len(text.splitlines()) < 40:
            continue
        has_test = any(p.stem in t for t in tests)
        referenced = p.name in surfaces
        status = "LIVE" if (has_test or referenced) else "UNWIRED"
        bits = []
        if has_test:
            bits.append("has a paired test")
        if referenced:
            bits.append("referenced on a wiring surface")
        if not bits:
            bits.append("NO test and NO wiring reference found")
        caps.append({
            "name": f"engine {p.stem}",
            "layer": L_ENGINES,
            "status": status,
            # A file can contain a single unpaired \"\"\" (inside a string, or a
            # truncated file), so index [1] is not safe and an empty docstring
            # has no [0] line. Fall back rather than lose the whole collector.
            "summary": _docstring_line(text) or f"Python engine {p.name}.",
            "entry": rel(root, p),
            "trigger": "called by a hook, a command, or another script",
            "evidence": f"{rel(root, p)}: {len(text.splitlines())} lines; " + ", ".join(bits) + ".",
        })
    return caps


def collect_domains(root: Path) -> list:
    caps = []
    for p in sorted(root.glob("q-*")):
        if not p.is_dir() or p.name in ("q-system",):
            continue
        files = [f for f in p.rglob("*") if f.is_file() and not is_vendored(f)]
        caps.append({
            "name": f"domain {p.name}",
            "layer": L_DOMAIN,
            "status": "LIVE" if files else "NEEDS_WORK",
            "summary": f"Instance-specific domain directory {p.name}/.",
            "entry": p.name + "/",
            "trigger": "read by this instance's commands and skills",
            "evidence": f"{p.name}/: {len(files)} file(s) on disk.",
        })
    return caps


def dedupe(caps: list) -> list:
    """Two capabilities that slugify to one key would collapse into one permanent
    Linear issue, so disambiguate here rather than letting linear-sync refuse."""
    slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    seen, out = {}, []
    for cap in caps:
        k = slug(cap["name"])
        if k in seen:
            seen[k] += 1
            cap["name"] = f"{cap['name']} ({seen[k]})"
        else:
            seen[k] = 1
        out.append(cap)
    return out


def tag_origin(caps: list, root: Path, skeleton: Path) -> list:
    """Mark each capability skeleton-propagated or instance-local.

    WHY THIS IS LOAD-BEARING (ASK-113): `kipi update` rsyncs .claude/rules/,
    .claude/agents/, q-system/ and plugins/ from the skeleton into all 24
    instances. Those capabilities are therefore THE SAME capability, present 24
    times. Filing an issue per instance for a skeleton rule would create ~24
    permanent duplicates of one problem and would itself be the fleet-homogeneity
    violation this whole exercise exists to find.

    A shared capability is tracked ONCE, in the kipi-system project. Instance maps
    still RECORD it (the overlap pass needs to see it) but set track=false so it
    never becomes an issue in the instance's project.

    The test is path existence in the skeleton, which is exactly what rsync
    copies, so it cannot drift from the propagation it models.
    """
    for cap in caps:
        entry = (cap.get("entry") or "").split(" -> ")[0].strip()
        is_shared = False
        if entry and not entry.startswith("/"):
            candidate = skeleton / entry
            is_shared = candidate.exists() and root.resolve() != skeleton.resolve()
        cap["origin"] = "skeleton" if is_shared else "local"
        # Track locally only what this repo actually owns.
        cap["track"] = not is_shared
    return caps


def build(root: Path, repo: str, skeleton: Path) -> dict:
    global _NESTED_REPOS
    _NESTED_REPOS = find_nested_repos(root)
    caps = []
    for fn in (collect_rules, collect_commands, collect_skills, collect_hooks,
               collect_agents, collect_engines, collect_domains):
        try:
            caps.extend(fn(root))
        except Exception as exc:  # one bad collector must not lose the rest
            print(f"WARN: {fn.__name__} failed on {repo}: {exc}", file=sys.stderr)
    caps = dedupe(caps)
    caps = tag_origin(caps, root, skeleton)

    counts, origins = {}, {}
    for cap in caps:
        counts[cap["status"]] = counts.get(cap["status"], 0) + 1
        origins[cap["origin"]] = origins.get(cap["origin"], 0) + 1
    trackable = [c for c in caps if c["track"] and c["status"] != "LIVE"]
    return {
        "_readme": (
            "Generated by q-system/.q-system/scripts/capability-map-gen.py from "
            "structural recon of this repo. Every 'evidence' string is a fact read "
            "off disk, not a claim. Status is derived from wiring: BROKEN means a "
            "hook is wired to a script that is not there; UNWIRED means an engine "
            "has neither a test nor a wiring reference. Re-run to detect drift."
        ),
        "repo": repo,
        "root": str(root),
        "summary": f"Capabilities of the {repo} repo: {len(caps)} detected.",
        "nested_repos_excluded": sorted(str(n) for n in _NESTED_REPOS),
        "status_counts": counts,
        "origin_counts": origins,
        "actionable_local": len(trackable),
        "capabilities": caps,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a CAPABILITY-MAP.json by recon.")
    ap.add_argument("--root", required=True, help="repo root to scan")
    ap.add_argument("--repo", required=True, help="repo/instance name")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skeleton", default=os.path.join(os.path.dirname(__file__), "..", "..", ".."),
                    help="skeleton repo root; capabilities that also exist there are "
                         "kipi update propagations and are tracked once, in kipi-system")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"BLOCK: {root} is not a directory", file=sys.stderr)
        return 1
    cmap = build(root, args.repo, Path(args.skeleton).resolve())
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(cmap, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    counts = ", ".join(f"{k}={v}" for k, v in sorted(cmap["status_counts"].items()))
    origins = ", ".join(f"{k}={v}" for k, v in sorted(cmap["origin_counts"].items()))
    print(f"{args.repo}: {len(cmap['capabilities'])} capabilities ({counts}) "
          f"[{origins}] -> {cmap['actionable_local']} actionable+local -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
