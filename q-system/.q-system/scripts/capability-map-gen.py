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
import hashlib
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
        # Filters to the same parity as every other walker in this file (ASK-315).
        # SKIP_DIRS alone was a partial application: is_vendored also knows about
        # virtualenvs and vendor markers, and a repo checked out under a review tree
        # is already dark to every consumer, so registering it as nested was noise.
        if is_vendored(parent) or is_excluded_tree(parent, root):
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
        if is_vendored(p) or is_excluded_tree(p, root):
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
            if is_vendored(p) or is_excluded_tree(p, root):
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
        # A SKILL.md inside a review tree or a generated dir is a copy, not a skill
        # this repo ships. Same predicate as every other walker here (ASK-315).
        if is_vendored(p) or is_excluded_tree(p, root):
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
                # Matcher is part of the identity: one script can be wired to
                # several events/matchers, and those are different capabilities.
                # Without it, investigations' two PostToolUse run-lint.sh hooks
                # produced the same name AND the same entry, so even the path-hash
                # disambiguation collided (linear-sync exit 3, 2026-07-26).
                matcher = str(group.get("matcher") or "all")
                caps.append({
                    "name": f"hook {label} ({event}/{matcher})",
                    "layer": L_ENFORCEMENT,
                    "status": "BROKEN" if missing else "LIVE",
                    "summary": (f"{event} hook running {label}."
                                + (" Its script is MISSING from disk."
                                   if missing else "")),
                    "entry": f".claude/settings.json -> {scripts[0]} [{event}/{matcher}]",
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


# Files whose CONTENT can wire an engine. A mention anywhere in one of these is a
# reference; markdown is handled separately below because prose is not wiring.
SURFACE_CODE_EXT = {
    ".py", ".sh", ".bash", ".zsh", ".yml", ".yaml", ".toml", ".json",
    ".cfg", ".ini", ".mk",
}
# .txt IS PROSE, NOT CODE (codex round 5, major). It sat in SURFACE_CODE_EXT,
# where every mention counts with no invocation filter at all, so any note,
# report or log ANYWHERE outside q-system/output/ silently marked a named engine
# LIVE. Excluding the generated tree fixed one instance of this and left the
# class open: the same defect shape as the B1 prose leak, on a different
# extension. A .txt is a runbook far less often than it is somebody's notes, so
# it belongs with .md where a line must actually invoke something.
SURFACE_DOC_EXT = {".md", ".txt"}
# Extensionless wiring surfaces (the kipi CLI, Makefiles, lefthook's shell blocks).
SURFACE_NAMES = {"Makefile", "makefile", "kipi", "Dockerfile", "Justfile", "justfile"}

# GENERATED ARTIFACTS ARE NOT WIRING SURFACES (ASK-122, caught pre-merge).
#
# Widening the scan repo-wide swept in q-system/output/, which holds codex
# transcripts, run logs, plans and RCAs. Those name scripts constantly and run
# nothing. Measured on kipi-investigations: the `_sync_all` design-system script
# flipped to LIVE on the
# strength of `q-system/output/codex-sfactivity-prd-out.txt` line 738, a bare
# `find`-style listing of that script's path.
#
# NOTE the extension is omitted deliberately everywhere in these comments. A
# bare module name only counts inside import/loader syntax (MODULE_REF_RE), but
# the FILENAME regex matches anywhere in any code file, comments included. The
# first draft of this scar named the file outright and thereby marked it LIVE --
# a comment explaining that a script is dead resurrected it, which is the very
# shape documented just below. Do not add the suffix back.
#
# The invocation filter cannot save this: that line starts with "./" and so
# matches MD_INVOCATION_RE. A log of a command that ENUMERATED files is
# indistinguishable, line by line, from a runbook that INVOKES one. The only
# durable separator is provenance -- who wrote the file -- so the fix is to drop
# generated trees from the surface rather than to write a cleverer regex.
#
# q-system/output/ is the OS's generated-artifacts directory by convention; it is
# also in kipi-update.sh's INSTANCE_OWNED_SUBTREES, i.e. already understood
# fleet-wide as an instance's own output rather than source.
GENERATED_SURFACE_PREFIXES = ("q-system/output/",)

# Review scratch: a detached copy of the repo, or a dump ABOUT the repo. Neither
# is wiring. `.pr36rev/all-dors.json` is a Linear DoR dump whose own text says
# `_sync_all` has "no test, no wiring reference" -- a document asserting a
# script is DEAD was the thing marking it alive (Fable B2). Matched on the path
# component so a nested `.pr42rev-r2/tree/...` counts too.
#
# NOT a bare leading-dot rule. `.claude/` and `.q-system/` are this fleet's
# PRIMARY wiring locations; treating every dotted component as scratch is what
# made _witness_rank cite the wrong file (Fable A1).
# `.review-scratch/` AND `.review-tmp-*` ARE COMMITTED, AND WERE NOT MATCHED.
# Measured 2026-08-14: `git ls-files` returns 20 tracked files under those two
# prefixes, including full copies of linear-worker.sh, linear-claim.py and
# pr-review-agent.sh. Because the pattern only knew `.prNNrev`, every one of
# those copies was walked as a live surface -- emitted as a capability and
# eligible to sync into a duplicate permanent Linear issue for a script that
# already has one. Being COMMITTED is what made them invisible to this rule and
# to a `git status` check alike.
#
# `.wt-`, `.fable-wt` and `.sana-tmp` are here for the same reason, not as
# scope creep: repo-preflight.sh's `_shipping()` already excludes exactly that
# set, and two scratch definitions that disagree is the defect this file keeps
# rediscovering (sp-505140ae was the same shape in test-repo-preflight.sh).
# Keep the two lists in step.
#
# STILL NOT a bare leading-dot rule. `.claude/` and `.q-system/` are this
# fleet's PRIMARY wiring locations; treating every dotted component as scratch
# is what made _witness_rank cite the wrong file (Fable A1). Each prefix here is
# named on purpose.
SCRATCH_DIR_RE = re.compile(
    r"^\.pr\d+rev|^\.prd-os$|^worktrees$|^review-trees$"
    r"|^\.review-|^\.wt-|^\.fable-wt|^\.sana-tmp"
)


def _is_excluded_part(part: str) -> bool:
    return bool(SCRATCH_DIR_RE.match(part))


def is_excluded_tree(p: Path, root: Path) -> bool:
    """Generated artifact or review scratch: not an engine, not a wiring surface,
    not a witness.

    ONE predicate for EVERY consumer ON PURPOSE. Excluding a tree from only some of
    them is the defect shape that recurred six times in this file in one night:
    engines excluded but still voting as surfaces (Fable B3), trees off the surface
    but still collected as engines (review round 1 major), snapshots skipped one way
    only, has_test's own rglob left out of the very commit that claimed to
    consolidate everything. If a tree is not real, it is not real for any question.

    DO NOT WRITE A COUNT HERE (ASK-315). The previous version of this docstring said
    "all three consumers" and shipped with a fourth, because the count came from
    memory. `consumer-parity-check.py` now enumerates the consumers from this file's
    AST and blocks on any walker that skips this predicate, so the census is taken by
    a gate rather than recalled by a person.
    """
    try:
        rel = p.relative_to(root)
    except ValueError:
        return False
    if rel.as_posix().startswith(GENERATED_SURFACE_PREFIXES):
        return True
    return any(_is_excluded_part(part) for part in rel.parts)


def _witness_rank(p: Path):
    """Sort key preferring a REAL caller over a scratch copy of one.

    Ranks on KNOWN scratch markers, not on a leading dot. The dot rule demoted
    `.claude/` and `.q-system/` -- where most of this fleet's wiring actually
    lives -- so any non-hidden file out-cited the true caller (Fable A1).
    """
    scratch = any(_is_excluded_part(part) for part in p.parts)
    return (scratch, len(p.parts), str(p))

# A markdown line only counts as wiring if it INVOKES something. A findings doc
# saying "engine_x.py left the template unfilled" names a script without keeping it
# alive; a runbook line `python3 engine_x.py` does. Without this split, widening the
# scan repo-wide just trades false-dead for false-alive (ASK-122).
# ANCHORED TO INVOCATION POSITION (Fable B1). The unanchored version matched
# ordinary English, and this filter is the SOLE evidence for 9.2% of fleet LIVE
# verdicts:
#   "The source of the bug is engine_x.py"          -> hit on `source `
#   "run-sweep.sh used to call engine_x.py"         -> hit on `sh `
#   "this old python script engine_x.py is dead"    -> hit on `python `
#   "see ../notes for why engine_x.py was dropped"  -> hit on `./`
# All four assert the script is DEAD and all four marked it LIVE. The suite's
# prose-negative fixture passed only because its wording happened to dodge those
# tokens: green for a reason unrelated to correctness.
# A command starts a line or follows a pipe / && / ; / backtick / $( -- never
# mid-sentence. `-m` is dropped as a standalone arm: it cannot start a command,
# and `python -m x` is already covered by the python arm.
# The interpreter arms need trailing whitespace (`python3 x.py`); `./` does not,
# because the path follows it directly (`./x.py`). Requiring a separator for both
# silently dropped every `./script` caller -- caught by the kill-test, not by eye.
MD_INVOCATION_RE = re.compile(
    r"(?:^|[|&;(`]|\$\()\s*(?:(?:python3?|bash|sh|source)\s|\./)"
)

# Module tokens an engine can be reached by WITHOUT its .py suffix. `import x`,
# `from x import y`, `python -m x`, and importlib's spec_from_file_location("x", ...)
# are all real callers that a filename-only scan reads as silence. Scar: ASK-230,
# where provenance_vocabulary.py had two live importers and was reported inert
# because both wrote `import provenance_vocabulary` with no extension.
MODULE_REF_RE = re.compile(
    r"^\s*from\s+([\w.]+)\s+import\b"
    r"|^\s*import\s+([\w.]+)"
    r"|spec_from_file_location\(\s*[\"']([\w.\-]+)[\"']"
    r"|-m\s+([\w.]+)\b",
    re.M,
)


# `fill_sheet.2026-07-28.py` beside `fill_sheet.py` is a dated SNAPSHOT of an
# engine, not a second engine. Alice's run-sweep.sh writes one before every sweep
# (`cp "$GEN/fill_sheet.py" "$DIR/backups/fill_sheet.$TODAY.py"`) and copies it back
# on failure, so it is live DATA on a rollback path. No static scan can ever match
# it -- the caller interpolates $TODAY -- so it would report UNWIRED forever and
# the only way to "fix" it is to delete a rollback artifact (ASK-122).
DATED_SNAPSHOT_RE = re.compile(r"\.\d{4}-\d{2}-\d{2}$")


def _is_test_file(p: Path) -> bool:
    return p.name.startswith(("test_", "test-")) or "test" in p.parts or "tests" in p.parts


def _iter_surface_files(root: Path):
    """Every file in the repo whose content can constitute wiring.

    WHY REPO-WIDE (ASK-122): the previous list walked only .claude/, plugins/ and
    q-system/, so an instance whose code lives anywhere else reported its own
    runners as absent. Alice flagged 22 engines UNWIRED while `regenerate.sh` ran
    four of them by path and `pipeline.py` imported two more. The scan has to
    follow the repo, not a layout the skeleton happens to use.
    """
    for p in root.rglob("*"):
        if not p.is_file() or is_vendored(p):
            continue
        if is_excluded_tree(p, root):
            continue
        # A dated snapshot is DATA, and this file already says so by refusing to
        # collect it as an engine. It must not VOTE either: a rollback copy's
        # `import geo_clues` kept geo_clues.py LIVE after every real caller was
        # gone, and Alice writes one snapshot per sweep so the phantom votes
        # accumulate forever (Fable B3). Excluding it on one side only was the
        # same half-exclusion this file keeps repeating.
        if DATED_SNAPSHOT_RE.search(p.stem):
            continue
        if p.suffix.lower() in SURFACE_CODE_EXT or p.suffix.lower() in SURFACE_DOC_EXT:
            yield p
        elif p.name in SURFACE_NAMES:
            yield p


def _build_reference_index(root: Path, engines: list) -> dict:
    """Map each engine path -> the set of OTHER files that reference it.

    Two ways to match: the file name (`foo.py`, seen in shell/CLI invocations and
    config) and the bare module name, but the bare name ONLY inside an import or
    loader construct. A generic stem like `pipeline` appears in ordinary prose all
    over this fleet; counting bare-word hits would mark half the repo live.
    """
    by_filename = {}
    by_module = {}
    for p in engines:
        by_filename.setdefault(p.name, []).append(p)
        by_module.setdefault(p.stem, []).append(p)
    if not by_filename:
        return {}

    # One alternation, one pass per file: a per-engine regex would be
    # len(engines) x len(files) scans, which is minutes on a large instance.
    # The lookbehind must NOT exclude "/": the common form is path-qualified
    # (`python3 "$G/fill_sheet.py"`), and blocking it hid every shell caller.
    filename_re = re.compile(
        r"(?<![\w.\-])(" + "|".join(re.escape(n) for n in sorted(by_filename)) + r")(?![\w\-])"
    )

    refs: dict = {}
    for src in _iter_surface_files(root):
        text = read_text(src)
        if not text:
            continue
        if src.suffix.lower() in SURFACE_DOC_EXT:
            text = "\n".join(ln for ln in text.splitlines() if MD_INVOCATION_RE.search(ln))
            if not text:
                continue
        for match in filename_re.finditer(text):
            for engine in by_filename[match.group(1)]:
                if engine != src:
                    refs.setdefault(engine, set()).add(src)
        for match in MODULE_REF_RE.finditer(text):
            token = next((g for g in match.groups() if g), None)
            if not token:
                continue
            for part in (token, token.rsplit(".", 1)[-1]):
                for engine in by_module.get(part, ()):
                    if engine != src:
                        refs.setdefault(engine, set()).add(src)
    return refs


def collect_engines(root: Path) -> list:
    """Scripts that have a paired test, or that are referenced from a wiring
    surface. An engine with neither is reported UNWIRED rather than assumed fine."""
    caps = []
    # FOURTH consumer of the exclusion predicate, and the one I missed when
    # claiming "one predicate for all three" in the commit that introduced it
    # (codex round 3, major). Without this, a test filename inside a review tree
    # or a generated dir still grants has_test, so the same one-sided-exclusion
    # shape survived inside the very change written to eliminate it. The count
    # of consumers is not fixed at three; grep is_excluded_tree before adding a
    # new walk over the repo.
    # A DOCUMENT IS NOT A TEST, AND A MENTION IS NOT A PAIRING.
    #
    # This used to collect every file whose NAME starts with "test", regardless
    # of extension, and `has_test` then asked whether the engine's stem appeared
    # ANYWHERE inside one of those names as a substring. Two ways that goes wrong,
    # and both were live:
    #
    #   1. A Markdown fixture (`test-something.md`, a DoR dump, a review note)
    #      counted as a test. That is the Fable B2 shape one layer down -- a
    #      document that merely NAMES a script was the thing certifying it tested.
    #   2. The substring made `_sync_all` match `test_sync_all_helpers.md`, so
    #      unwired copies of _sync_all.py reported LIVE.
    #
    # So only EXECUTABLE test files count. The substring match itself is kept
    # deliberately -- see the scar below.
    #
    # TIGHTENING THE MATCH TO EXACT WAS TRIED AND REVERTED (codex, PR #164 r2).
    # Requiring the test filename to equal the engine stem looks obviously right
    # and is wrong: plugins/kipi-core/voiceloop/echo.py is genuinely tested by
    # voiceloop/tests/test_voiceloop.py, which imports echo and exercises
    # echo.prompt_echo and echo.opener_echo across ~20 lines. Its stem is
    # "voiceloop", not "echo", so exact matching flipped a real, covered engine to
    # UNWIRED -- a false alarm eligible for a permanent Linear issue, which is
    # worse than the false LIVE it was meant to fix. One test file legitimately
    # covers several engines, so filename equality cannot be the rule. The real
    # signal is the CONTENT reference (test_sources); making that reliable is
    # ASK-810, not a filename heuristic.
    TEST_SUFFIXES = {".py", ".sh"}
    tests = {p.name for p in root.rglob("test*")
             if p.is_file() and p.suffix in TEST_SUFFIXES
             and not is_vendored(p) and not is_excluded_tree(p, root)}

    engines = []
    for p in root.rglob("*.py"):
        if is_vendored(p):
            continue
        if p.name.startswith(("test_", "test-")) or "test" in p.parts:
            continue
        # A generated tree is not a wiring surface (see is_excluded_tree), so
        # it must not be an ENGINE source either. Excluding it from only one of
        # the two makes its contents permanently dark: still collected, but with
        # every file that could reference them now off-surface, so they report
        # UNWIRED with no way to ever clear it (review finding, PR #74 major;
        # would have compounded sp-3761d2d9). An artifact is not an engine, so
        # the coherent move is to stop reporting it at all rather than to report
        # it as dead. Measured: drops 12 phantom engines in kipi-investigations.
        if is_excluded_tree(p, root):
            continue
        if DATED_SNAPSHOT_RE.search(p.stem):
            continue
        if len(read_text(p).splitlines()) < 40:
            continue
        engines.append(p)

    refs = _build_reference_index(root, engines)

    for p in engines:
        text = read_text(p)
        sources = refs.get(p, set())
        # WITNESS ORDER IS NOT ALPHABETICAL (review finding, PR #74 minor).
        # Plain sorted()[0] puts dot-prefixed paths first, so the evidence named
        # a review scratch tree (.pr42rev/, .claude/worktrees/) instead of the
        # real caller in 163 of 785 witnesses measured across five repos. The
        # verdict was right and the citation was useless, which is worse than it
        # sounds: the citation is the only part a human re-checks.
        test_sources = sorted((s for s in sources if _is_test_file(s)), key=_witness_rank)
        wiring_sources = sorted((s for s in sources if not _is_test_file(s)), key=_witness_rank)
        has_test = any(p.stem in t for t in tests) or bool(test_sources)
        referenced = bool(wiring_sources)
        status = "LIVE" if (has_test or referenced) else "UNWIRED"
        bits = []
        if has_test:
            witness = rel(root, test_sources[0]) if test_sources else "name-matched test file"
            bits.append(f"has a paired test ({witness})")
        if referenced:
            bits.append(f"referenced on a wiring surface ({rel(root, wiring_sources[0])})")
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
        if is_vendored(p) or is_excluded_tree(p, root):
            continue
        files = [f for f in p.rglob("*")
                 if f.is_file() and not is_vendored(f) and not is_excluded_tree(f, root)]
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
    Linear issue, so disambiguate here rather than letting linear-sync refuse.

    The suffix is a hash of the ENTRY PATH, not a counter. A counter collided for
    real: one registered instance has a file that legitimately produces "engine core 2",
    and a second "engine core" was being renamed to "engine core (2)", which
    slugifies to the same key. linear-sync's collision guard caught it (exit 3),
    which is the guard working, but the generator should not emit the collision in
    the first place. A path hash is unique by construction and stable across runs,
    so re-running does not reshuffle keys and orphan already-created issues.
    """
    slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    seen, out = {}, []
    for cap in caps:
        base = cap["name"]
        k = slug(base)
        # Loop, do not single-shot. Hashing the entry alone is not enough when the
        # entries are themselves identical: kipi-investigations wires run-lint.sh
        # four times under the same event and matcher with different command
        # arguments, so all four hashed the same and stayed collided even after
        # renaming. Folding the ordinal into the hash terminates and is stable for
        # a given (entry, ordinal) pair.
        ordinal = 0
        while k in seen:
            ordinal += 1
            tag = hashlib.sha1(
                f"{cap.get('entry') or base}#{ordinal}".encode()
            ).hexdigest()[:6]
            cap["name"] = f"{base} [{tag}]"
            k = slug(cap["name"])
        seen[k] = True
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
    # Cleared FIRST: find_nested_repos now filters through is_vendored, which reads
    # this global, so a value left over from a previous build() in the same process
    # would decide which repos the next scan is allowed to see (ASK-315).
    _NESTED_REPOS = set()
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
