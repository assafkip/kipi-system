#!/usr/bin/env python3
"""Reproducer for dev-skills-lint (ASK-135).

Written BEFORE the engine, run RED first (`ModuleNotFoundError` / missing
script), then green. The cases that matter are the ones that make the linter go
RED for the reason we care about -- a trigger table naming a skill that is not
installed. A validator that can only ever print "ok" is decoration
(lesson: a-check-must-be-able-to-fail-for-the-reason-you-care-about).

Run: python3 q-system/.q-system/scripts/test/test-dev-skills-lint.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
SCRIPTS = HERE.parents[1]
LINT = SCRIPTS / "dev-skills-lint.py"
REPO = HERE.parents[4]
REAL_RULE = REPO / ".claude" / "rules" / "dev-skills-auto-invoke.md"

FAILURES: list[str] = []


def run(rule: Path, home: Path | None = None, verbose: bool = False) -> tuple[int, str]:
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = str(home)
    argv = [sys.executable, str(LINT), "--rule", str(rule)]
    if verbose:
        argv.append("--verbose")
    proc = subprocess.run(argv, capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout + proc.stderr


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}{(' -- ' + detail) if detail else ''}")
        FAILURES.append(name)


def write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(body, encoding="utf-8")
    return path


TABLE_HEAD = (
    "| Trigger | Skill | What it does |\n"
    "|---------|-------|-------------|\n"
)


def rule_with_rows(rows: str) -> str:
    return (
        "---\ndescription: t\npaths:\n  - \"plugins/**\"\n---\n\n"
        "# Development Skills Auto-Invocation\n\n" + TABLE_HEAD + rows + "\n"
    )


def main() -> int:
    if not LINT.exists():
        print(f"RED: {LINT} does not exist yet")
        return 1

    print("test-dev-skills-lint")

    # 1. The live rule file must be GREEN. This validator ships fleet-wide via
    #    `kipi update`; red on its own population is how a gate gets switched off.
    rc, out = run(REAL_RULE)
    check("live rule file exits 0", rc == 0, f"rc={rc}\n{out}")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 2. THE reproducer: a row naming a skill that exists nowhere.
        bad = write(tmp, "bad-skill.md", rule_with_rows(
            "| Editing a skill | `skill-creator` | structure |\n"
            "| Nonsense | `no-such-skill-xyz` | nothing |\n"))
        rc, out = run(bad)
        check("unresolvable skill exits 2", rc == 2, f"rc={rc}\n{out}")
        check("unresolvable skill is named in the output",
              "no-such-skill-xyz" in out, out)
        # Negative self-test: it must not flag the row that DOES resolve.
        check("resolvable sibling row is not flagged",
              out.count("skill-creator") == 0
              or "skill-creator" not in out.split("unresolved", 1)[-1],
              out)

        # 3. No table at all. An empty result set is a broken reader, not a pass
        #    (lesson: an-empty-ledger-is-a-broken-writer).
        empty = write(tmp, "no-table.md", "# Rule\n\nProse only, no table.\n")
        rc, out = run(empty)
        check("rule with no trigger table exits 2", rc == 2, f"rc={rc}\n{out}")

        # 4. A row whose skill cell carries no backticked name is malformed, not
        #    silently skipped -- otherwise deleting the backticks empties the
        #    table and the gate goes quiet.
        malformed = write(tmp, "malformed.md", rule_with_rows(
            "| Editing a skill | skill-creator | structure |\n"))
        rc, out = run(malformed)
        check("row with no backticked skill exits 2", rc == 2, f"rc={rc}\n{out}")

        # 5. A dangling symlink in the personal skills dir is reported (WARN)
        #    and does NOT block, because the repo cannot repair ~/.claude.
        fake_home = tmp / "home"
        skills = fake_home / ".claude" / "skills"
        skills.mkdir(parents=True)
        provider = tmp / "provider" / "skills" / "ghost-skill"
        provider.mkdir(parents=True)
        (provider / "SKILL.md").write_text("---\nname: ghost-skill\n---\n")
        (fake_home / ".claude" / "plugins" / "marketplaces" / "mk").mkdir(parents=True)
        os.symlink(provider.parent,
                   fake_home / ".claude" / "plugins" / "marketplaces" / "mk" / "skills")
        os.symlink(tmp / "gone" / "ghost-skill", skills / "ghost-skill")
        ghost = write(tmp, "ghost.md", rule_with_rows(
            "| Ghost | `ghost-skill` | nothing |\n"))
        rc, out = run(ghost, home=fake_home)
        check("dangling symlink exits 0 when another provider resolves",
              rc == 0, f"rc={rc}\n{out}")
        check("dangling symlink is reported", "dangling" in out.lower(), out)

        # 6. A skill that resolves ONLY via the dangling link, with no other
        #    provider, is unresolved -- exit 2.
        os.symlink(tmp / "gone" / "orphan-skill", skills / "orphan-skill")
        orphan = write(tmp, "orphan.md", rule_with_rows(
            "| Orphan | `orphan-skill` | nothing |\n"))
        rc, out = run(orphan, home=fake_home)
        check("skill with only a dangling link exits 2", rc == 2, f"rc={rc}\n{out}")

        # 7. THE second reproducer (Codex PR #238, major): a pipe row that is not
        #    part of the trigger table must not be able to satisfy the gate. Gut
        #    the table's rows, leave one stray row in a later section, and the
        #    gate has to still say the table is empty -- otherwise deleting the
        #    table is a silent pass and the "no rows" guard only ever fires on a
        #    file with no pipes at all.
        gutted = write(tmp, "gutted.md",
                       rule_with_rows("") + "\n## Examples\n\n"
                       "| note | `skill-creator` | a leftover row |\n")
        rc, out = run(gutted)
        check("gutted table is not rescued by a stray row elsewhere",
              rc == 2, f"rc={rc}\n{out}")

        # 8. The negative self-test for #7: rows of an UNRELATED table must not
        #    be validated as trigger rows either. A fix that just rejects
        #    everything with a pipe in it would pass #7 and break every rule doc
        #    that carries a second table (most of them do).
        sibling = write(tmp, "sibling-table.md", rule_with_rows(
            "| Editing a skill | `skill-creator` | structure |\n")
            + "\n## Enforcement pairing\n\n"
            "| Piece | Status |\n|---|---|\n"
            "| the detector | wired PostToolUse |\n")
        rc, out = run(sibling)
        check("an unrelated table below the trigger table is ignored",
              rc == 0, f"rc={rc}\n{out}")

        # 9. THE third reproducer (Codex PR #238 round 3, major): a PASSING run
        #    must not spend more than one line on a condition it cannot fix.
        #    The live gate printed one WARN per stale link -- six identical
        #    lines on every `kipi check`, fleet-wide, for skills that resolve
        #    fine. Repeat non-actionable warnings are how an operator learns to
        #    skim past the real one. The fact is still stated, once, in the
        #    pass line; the per-skill list moves behind --verbose.
        rc, out = run(ghost, home=fake_home)
        printed = [ln for ln in out.splitlines() if ln.strip()]
        check("a passing run prints exactly one line",
              rc == 0 and len(printed) == 1, f"rc={rc}\n{out}")
        check("that one line still names the dangling link",
              "dangling" in out.lower(), out)

        # 10. Negative self-test for #9: collapsing the output must not DELETE
        #     the evidence. --verbose still names the affected skill, so the
        #     quiet default is a summary and not a silent swallow.
        rc, out = run(ghost, home=fake_home, verbose=True)
        check("--verbose exits 0 and names the affected skill",
              rc == 0 and "ghost-skill" in out, f"rc={rc}\n{out}")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
