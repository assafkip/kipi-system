#!/usr/bin/env python3
"""Every script path, sibling file and skill/command name a SKILL.md tells the
model to use must actually resolve.

WHY THIS SHAPE (scar, prompt audit 2026-09-02, findings S-1/S-2/S-3).
Three skills instructed the model to run scripts that were never committed
(`deck-ai/scripts/setup.sh`, `generate.py`, `render.sh`), to route work to five
skills installed in no marketplace (`ui-styling`, `ai-artist`, `ai-multimodal`,
`project-management`, `assets-organizing`) under two foreign command namespaces
(`/ckm:`, `/ck:`), and to call `python3 skills/ui-ux-pro-max/scripts/search.py`,
a path relative to a repo-root `skills/` dir that does not exist here. Every run
that followed those files failed at step one, silently, for months. Reading the
SKILL cannot catch this: the text is plausible. Only executing the reference
against the filesystem can.

WHAT IT CANNOT SEE. A skill name is resolved against the skill dirs installed on
THIS machine (repo plugins + the marketplace clones and the plugin cache under
$CLAUDE_CONFIG_DIR). When those roots are absent the external half reports SKIP
rather than a false green, and the in-repo half still hard-fails. There is no
allowlist to append a dead name to on purpose: the resolution set is discovered,
never declared.

Usage:
    python3 q-system/.q-system/scripts/test/test-skill-refs-resolve.py [--verbose]
Exit 0 = every reference resolved. Exit 1 = at least one dead reference.
"""

import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

# The three skills the audit found broken. A skill joins this list when its
# references are meant to be executable, not when it merely has a scripts/ dir.
SKILL_DIRS = (
    "plugins/kipi-core/skills/deck-ai",
    "plugins/kipi-design/skills/design",
    "plugins/kipi-design/skills/ui-ux-pro-max",
)

# Directories a skill owns. A reference under one of these is a promise about
# THIS skill's tree and must exist. Anything else (./deck.pptx, ./decisions.json,
# design-system/MASTER.md) is an artifact the workflow CREATES, so existence is
# not a precondition and is deliberately not asserted.
OWNED_DIRS = ("scripts", "references", "data", "templates", "assets")

# ui-ux-pro-max/src/ is the upstream packaging source that emits this skill for
# Cursor / Windsurf / Gemini / etc. Its `skills/ui-ux-pro-max/...` paths are
# correct FOR THOSE TARGETS and wrong here, and no Claude load path reads it —
# SKILL.md's reference table never points inside it. Scoping it out is a
# decision, not an oversight: asserting repo-relative existence there would
# red-flag correct upstream text.
EXCLUDED_SUBDIRS = ("src",)

PATH_RE = re.compile(
    r"(?:\$\{CLAUDE_SKILL_DIR\}/|<skill>/|(?<![\w./$-]))"
    r"((?:" + "|".join(OWNED_DIRS) + r")/[A-Za-z0-9_./-]+)"
)
# A trailing sentence period is not part of a filename.
TRAILING_JUNK = re.compile(r"[.,;:)]+$")

# An interpreter followed by a path is an instruction to RUN that file. This is
# the half a bare OWNED_DIRS scan misses: `python3 skills/ui-ux-pro-max/scripts/
# search.py` names a repo-root `skills/` dir that does not exist here (S-3), and
# nothing in the token looks skill-relative.
RUN_RE = re.compile(r"\b(?:python3?|bash|sh|node)\s+"
                    r"((?:\$\{CLAUDE_SKILL_DIR\}/|<skill>/)?[A-Za-z0-9_${}./-]+"
                    r"\.(?:py|sh|js|mjs))")

# `--domain X` / `--stack Y` on a ui-ux-pro-max command line. A value its own
# core.py does not know fails at argparse, same as a missing file.
ARGVAL_RE = re.compile(r"--(domain|stack)\s+[\"']?([a-z][a-z0-9-]*)[\"']?")

SKILL_WORD_RE = re.compile(r"\bsub-skills?\b|\bskills?\b", re.IGNORECASE)
BACKTICK_RE = re.compile(r"`([^`]+)`")
# `**External sub-skills:** brand, design-system` — a bare comma list under a
# bolded label that ends in "skill(s):". Same claim, no backticks.
BARE_LIST_RE = re.compile(r"\*\*[^*]*\bsub-skills?:\*\*|\*\*[^*]*\bskills?:\*\*",
                          re.IGNORECASE)
SLASH_RE = re.compile(r"(?<![\w/])/([a-z][a-z0-9-]*)(?::([a-z][a-z0-9-]*))?\b")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,}$")

# Prose that reads like a skill name but is one. Derived, not declared: a token
# is only a candidate if it survives NAME_RE and is not a path or a flag.
def is_name_candidate(tok):
    tok = tok.strip()
    return bool(NAME_RE.match(tok))


def config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))


def discover_skills():
    """Set of installed skill names, and the set of plugin namespaces.

    Returns (skills, plugins, external_roots_seen).
    """
    skills, plugins = set(), set()
    seen_external = False

    for p in REPO.glob("plugins/*/skills/*/SKILL.md"):
        skills.add(p.parent.name)
    for p in REPO.glob("plugins/*/plugin.json"):
        plugins.add(p.parent.name)

    cfg = config_dir()
    for root in (cfg / "plugins" / "marketplaces", cfg / "plugins" / "cache",
                 cfg / "skills"):
        if not root.is_dir():
            continue
        seen_external = True
        for p in root.rglob("SKILL.md"):
            if p.parent.parent.name in ("skills",) or p.parent.parent == root:
                skills.add(p.parent.name)
        for p in root.rglob("plugin.json"):
            plugins.add(p.parent.name)
    return skills, plugins, seen_external


def extract_paths(text):
    """{(reference_as_written, path_relative_to_skill_root_or_None)}.

    None means "not skill-relative" — resolve it against the repo root instead,
    which is how a `skills/...` path gets caught.
    """
    out = set()
    for m in PATH_RE.finditer(text):
        out.add((m.group(0), TRAILING_JUNK.sub("", m.group(1))))
    for m in RUN_RE.finditer(text):
        raw = TRAILING_JUNK.sub("", m.group(1))
        rel = re.sub(r"^(?:\$\{CLAUDE_SKILL_DIR\}/|<skill>/)", "", raw)
        skill_relative = raw != rel or rel.split("/", 1)[0] in OWNED_DIRS
        out.add((raw, rel if skill_relative else None))
    return out


def load_uiux_vocab():
    """(domains, stacks) straight out of ui-ux-pro-max's own core.py, so the
    docs are graded against the parser rather than against a copy of it."""
    core_dir = REPO / "plugins/kipi-design/skills/ui-ux-pro-max/scripts"
    if not (core_dir / "core.py").is_file():
        return None, None
    sys.path.insert(0, str(core_dir))
    try:
        import core  # noqa: PLC0415
        return set(core.CSV_CONFIG), set(core.AVAILABLE_STACKS)
    except Exception as err:  # a broken import must not read as a pass
        print(f"WARN: could not load ui-ux-pro-max core.py: {err}",
              file=sys.stderr)
        return None, None
    finally:
        sys.path.remove(str(core_dir))


def extract_names(text):
    """(skill_names, namespaced_commands) claimed by this file."""
    names, commands = set(), set()
    for line in text.splitlines():
        if SKILL_WORD_RE.search(line):
            for tok in BACKTICK_RE.findall(line):
                tok = tok.lstrip("/")
                if is_name_candidate(tok):
                    names.add(tok)
            m = BARE_LIST_RE.search(line)
            if m:
                for tok in line[m.end():].split(","):
                    tok = tok.strip().strip("`*. ")
                    if is_name_candidate(tok):
                        names.add(tok)
        for ns, name in SLASH_RE.findall(line):
            if name:
                commands.add((ns, name))
            elif ns in ("ck", "ckm"):
                commands.add((ns, ""))
    return names, commands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    skills, plugins, has_external = discover_skills()
    domains, stacks = load_uiux_vocab()
    failures, checked = [], 0

    for rel in SKILL_DIRS:
        root = REPO / rel
        if not root.is_dir():
            failures.append(f"{rel}: skill directory missing")
            continue
        is_uiux = root.name == "ui-ux-pro-max"
        for md in sorted(root.rglob("*.md")):
            if md.relative_to(root).parts[0] in EXCLUDED_SUBDIRS:
                continue
            text = md.read_text(encoding="utf-8")
            where = md.relative_to(REPO)

            for raw, ref in sorted(extract_paths(text)):
                checked += 1
                base = root if ref is not None else REPO
                target = base / (ref if ref is not None else raw)
                if not target.exists():
                    failures.append(f"{where}: path does not exist: {raw}")
                elif args.verbose:
                    print(f"  ok  path  {where}: {raw}")

            if is_uiux and domains is not None:
                for flag, val in ARGVAL_RE.findall(text):
                    checked += 1
                    known = domains if flag == "domain" else stacks
                    if val not in known:
                        failures.append(
                            f"{where}: --{flag} {val} is not accepted by "
                            f"scripts/core.py")
                    elif args.verbose:
                        print(f"  ok  arg   {where}: --{flag} {val}")

            names, commands = extract_names(text)
            for name in sorted(names):
                checked += 1
                if name in skills:
                    if args.verbose:
                        print(f"  ok  skill {where}: {name}")
                elif not has_external:
                    print(f"  SKIP skill {where}: {name} "
                          "(no installed-plugin roots on this machine)")
                else:
                    failures.append(
                        f"{where}: names a skill that is installed nowhere: {name}")
            for ns, name in sorted(commands):
                checked += 1
                target = name or ns
                if name and ns not in plugins:
                    failures.append(
                        f"{where}: command /{ns}:{name} uses namespace "
                        f"'{ns}', which is not an installed plugin")
                elif target not in skills and has_external:
                    failures.append(
                        f"{where}: command /{ns}{':' + name if name else ''} "
                        f"resolves to no installed skill")
                elif args.verbose:
                    print(f"  ok  cmd   {where}: /{ns}{':' + name if name else ''}")

    if failures:
        print(f"FAIL: {len(failures)} dead reference(s) "
              f"across {len(SKILL_DIRS)} skills ({checked} checked)\n",
              file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print(f"OK: {checked} references resolve across {len(SKILL_DIRS)} skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
