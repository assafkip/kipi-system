#!/usr/bin/env python3
"""dev-skills-lint: the deterministic slice of `.claude/rules/dev-skills-auto-invoke.md`.

WHY (ASK-135, CAP-08 sweep): dev-skills-auto-invoke.md carried the word ENFORCED
and named no executable, so it was prompt-only. Per `skill-hook-pairing.md`'s
decision rule the rule splits in two:

  - DETERMINISTIC (this script): every skill the trigger table names resolves to
    a readable SKILL.md. A rule that tells you to invoke `mcp-builder` when
    `mcp-builder` is not installed is an instruction pointing at nothing, and
    that is a file-inspectable fact.
  - JUDGMENT (stays in the rule, NOT enforced): whether the reflex fires at all.
    No script can observe the skill you did not invoke. That half is measured
    advisory-only by `skill-trigger-eval.py` against
    `q-system/.q-system/skill-evals/dev-skills-auto-invoke.json`.

Run standalone; registered as a `kipi check` gate in `validate-separation.py`.
This is NOT a PostToolUse hook: the thing it validates is one always-loaded rule
file, not the file you happen to be editing, so paying a hook on every Edit
fleet-wide would buy nothing (`token-discipline.md`, scope-match).

  python3 q-system/.q-system/scripts/dev-skills-lint.py [--rule PATH] [--quiet]

Contract: exit 0 = pass (warnings may still print), exit 2 = fail. stdlib only.
Reproducer: `python3 q-system/.q-system/scripts/test/test-dev-skills-lint.py`.

TWO SEVERITIES, on purpose:

  ERROR (exit 2) -- a named skill resolves NOWHERE, or the table is missing or
    malformed. This is a defect in a file this repo owns and can fix.
  WARN (exit 0)  -- the skill resolves through some provider, but its
    `~/.claude/skills/<name>` entry is a DANGLING SYMLINK. Real breakage, and
    outside this repo: nothing in `kipi update` can repair a link into a
    directory that no longer exists on the founder's machine. Blocking on it
    would make `kipi check` red on every instance for a cause no instance owns,
    and a gate that is red on its own population gets switched off
    (`automated-filer-marking.md`, `plan-lint.py` made the same call).

HONEST BOUNDARY, three of them:
  1. A readable SKILL.md on disk is NOT proof the running session offers that
     skill. Plugin availability also depends on marketplace enablement state
     this repo does not own. Measured 2026-08-22: all six skills in the table
     resolved on disk, and three of them (`skill-creator`, `mcp-builder`,
     `hook-development`) were absent from that session's skill listing. Read a
     green here as "the name is not a typo and something provides it", never as
     "the model can invoke it".
  2. It checks the skill EXISTS, never that its content matches the "What it
     does" column, and never that the trigger column describes real work.
  3. It cannot see a row that should exist and does not. A skill class nobody
     added to the table is invisible to this check.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[2]
DEFAULT_RULE = REPO_ROOT / ".claude" / "rules" / "dev-skills-auto-invoke.md"

# A trigger row is `| trigger | `skill` | what it does |`. The header and the
# `|---|---|---|` separator are skipped by shape, not by line number.
ROW_RE = re.compile(r"^\|(?P<cells>.+)\|\s*$")
SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
BACKTICKED_RE = re.compile(r"`([A-Za-z0-9][A-Za-z0-9._:-]*)`")

HEADER_FIRST_CELL = "trigger"


def table_rows(body: str) -> list[tuple[int, list[str]]]:
    """Every pipe-table row that is not a header or a separator.

    Returns (1-indexed line number, cells). Rows outside a table are impossible
    to hit because a line has to start and end with `|` to match at all.
    """
    out: list[tuple[int, list[str]]] = []
    for lineno, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|") or SEPARATOR_RE.match(stripped):
            continue
        m = ROW_RE.match(stripped)
        if not m:
            continue
        cells = [c.strip() for c in m.group("cells").split("|")]
        if cells and cells[0].lower() == HEADER_FIRST_CELL:
            continue
        out.append((lineno, cells))
    return out


def search_roots(home: Path) -> list[Path]:
    """Every glob root a skill directory can live under, most specific first.

    Deliberately NOT a full `os.walk` of `~/.claude/plugins`: that tree carries
    one directory per installed version, so walking it turns a name check into a
    seconds-long crawl and finds skills from versions nothing loads.
    """
    claude = home / ".claude"
    return [
        REPO_ROOT / "plugins",          # this repo's own plugin groups
        claude / "skills",              # personal skills
        claude / "plugins" / "marketplaces",
        claude / "plugins" / "cache",
    ]


def _skill_md_under(root: Path, name: str) -> Path | None:
    """First readable `<...>/<name>/SKILL.md` under root, or None."""
    patterns = [
        f"{name}/SKILL.md",
        f"*/skills/{name}/SKILL.md",
        f"*/*/skills/{name}/SKILL.md",
        f"*/*/*/skills/{name}/SKILL.md",
        f"skills/{name}/SKILL.md",
    ]
    for pattern in patterns:
        for hit in root.glob(pattern):
            if hit.is_file():
                return hit
    return None


def resolve(name: str, home: Path) -> Path | None:
    for root in search_roots(home):
        if not root.is_dir():
            continue
        hit = _skill_md_under(root, name)
        if hit is not None:
            return hit
    return None


def dangling_personal_link(name: str, home: Path) -> str | None:
    """readlink target when `~/.claude/skills/<name>` is a link to nothing."""
    entry = home / ".claude" / "skills" / name
    if not entry.is_symlink():
        return None
    if (entry / "SKILL.md").is_file():
        return None
    try:
        return str(Path(entry).readlink())
    except OSError:
        return "<unreadable>"


def audit(rule_path: Path, home: Path) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one rule file."""
    errors: list[str] = []
    warnings: list[str] = []

    try:
        body = rule_path.read_text(encoding="utf-8")
    except OSError as exc:
        return ([f"cannot read {rule_path}: {exc}"], [])

    rows = table_rows(body)
    if not rows:
        # An empty result set is a broken reader, not a pass
        # (lesson: an-empty-ledger-is-a-broken-writer-until-a-live-path-test).
        errors.append(
            f"{rule_path.name}: no trigger table rows found. The rule's whole "
            "mechanism is that table; with no rows this check would pass by "
            "reading nothing.")
        return (errors, warnings)

    for lineno, cells in rows:
        if len(cells) < 2:
            errors.append(f"{rule_path.name}:{lineno}: row has fewer than 2 columns")
            continue
        names = BACKTICKED_RE.findall(cells[1])
        if not names:
            errors.append(
                f"{rule_path.name}:{lineno}: skill column carries no backticked "
                f"skill name (got {cells[1]!r}). Without backticks the row is "
                "unparseable and would be skipped silently.")
            continue
        for name in names:
            if resolve(name, home) is None:
                link = dangling_personal_link(name, home)
                extra = f" (~/.claude/skills/{name} -> {link}, dangling)" if link else ""
                errors.append(
                    f"{rule_path.name}:{lineno}: unresolved skill `{name}`"
                    f"{extra} -- no readable SKILL.md under any known root")
                continue
            link = dangling_personal_link(name, home)
            if link:
                warnings.append(
                    f"{rule_path.name}:{lineno}: `{name}` resolves through a "
                    f"plugin, but ~/.claude/skills/{name} is a dangling symlink "
                    f"-> {link}")
    return (errors, warnings)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rule", default=str(DEFAULT_RULE),
                    help="rule file to audit (default: dev-skills-auto-invoke.md)")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing on a clean pass")
    args = ap.parse_args(argv)

    rule_path = Path(args.rule)
    errors, warnings = audit(rule_path, Path.home())

    for w in warnings:
        print(f"  WARN  {w}")

    if errors:
        sys.stderr.write(
            "DEV-SKILLS LINT (fail): `.claude/rules/dev-skills-auto-invoke.md` "
            "tells you to invoke a skill before writing code. A row naming a "
            "skill that is not installed is an instruction pointing at "
            "nothing.\n")
        for e in errors:
            sys.stderr.write(f"    - {e}\n")
        sys.stderr.write(
            "\n  Fix by installing the skill, or by removing/renaming the row so "
            "the table only promises what exists.\n"
            "  Resolving on disk is not proof the running session offers the "
            "skill; see this script's HONEST BOUNDARY.\n")
        return 2

    if not args.quiet:
        rows = len(table_rows(rule_path.read_text(encoding="utf-8")))
        print(f"  dev-skills-lint: {rows} trigger row(s), all skills resolve"
              + (f", {len(warnings)} warning(s)" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
