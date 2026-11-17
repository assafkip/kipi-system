"""Which rules load on demand, and the one frontmatter key that makes that true (ASK-5377).

Scar, measured 2026-11-17: `design-auto-invoke.md` declared its scope under `globs:`.
Claude Code honors `paths:` only, so the rule loaded at the start of every session and
every subagent while `instruction-budget-audit.py` counted it as conditional. A scope
written under the wrong key is an always-on rule that reads as a scoped one.

Why scope at all: a full subagent started at 91,995 tokens and about 27k of that was
always-loaded rule files, written cold on 789 subagent launches in one week.

This file is the enforcer the rule_gate reads for:
  RULE-2026-11-17-SCOPE-DESIGN    design-auto-invoke.md
  RULE-2026-11-17-SCOPE-DOGFOOD   dogfood-gate.md
  RULE-2026-11-17-SCOPE-SKILLHOOK skill-hook-pairing.md
  RULE-2026-11-17-SCOPE-MODEL     model-allocation.md
  RULE-2026-11-17-SCOPE-WIRING    wiring-check.md

What it does NOT prove: that Claude Code loads a rule when a matching file is touched.
That is the harness's behaviour; the receipt for it is a fresh-session `/context`.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RULES = REPO / ".claude" / "rules"

# Patterns that match every file: a rule carrying one is always-on whatever it claims.
CATCH_ALL = {"**/*", "**", "*"}

# Page sources, shared by the two design rules. Repo-wide on purpose: these rules ship to
# instances by `kipi update`, and an instance's public pages are not under sites/. The old
# `sites/**` scope would have kept the rule off every instance page even once honored.
PAGE_GLOBS = {"**/*.html", "**/*.css", "**/*.tsx", "**/*.jsx"}

# rule file -> (Rule-ID, patterns the scope must keep). Each required pattern is the
# surface where the rule's own subject lives, so narrowing past it switches the rule off
# for the work it governs.
SCOPED = {
    "design-auto-invoke.md": ("RULE-2026-11-17-SCOPE-DESIGN", PAGE_GLOBS),
    "dogfood-gate.md": ("RULE-2026-11-17-SCOPE-DOGFOOD", PAGE_GLOBS | {"plugins/kipi-design/**"}),
    # The pairing's subject is a skill and the hook script wired for it in settings.
    "skill-hook-pairing.md": (
        "RULE-2026-11-17-SCOPE-SKILLHOOK",
        {"plugins/**", "**/SKILL.md", "**/hooks.json", ".claude/settings*.json",
         ".claude/skills/**", "q-system/.q-system/scripts/**"},
    ),
    # Agent frontmatter plus the tier tables, which the rule says change together.
    "model-allocation.md": (
        "RULE-2026-11-17-SCOPE-MODEL",
        # validate-separation.py is the validator script holding those tables (Gate 1.1b).
        {".claude/agents/**", "**/agents/*.md", "validate-separation.py"},
    ),
    # Done-means-wired governs any code, hook, agent, bus or canonical change.
    "wiring-check.md": (
        "RULE-2026-11-17-SCOPE-WIRING",
        {"plugins/**", ".claude/**", "**/*.py", "**/*.sh", "**/*.js", "**/*.ts",
         "**/*.plist", "**/hooks.json", ".mcp.json", "**/canonical/**", "agent-pipeline/**"},
    ),
}

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.S)


def frontmatter_lists(text):
    """Return {key: [items]} for the top-level list keys of a rule's frontmatter."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    lists, key = {}, None
    for line in match.group(1).splitlines():
        top = re.match(r"^([A-Za-z_-]+):\s*$", line)
        item = re.match(r"""^\s+-\s+["']?([^"']+)["']?\s*$""", line)
        if top:
            key = top.group(1)
            lists[key] = []
        elif item and key:
            lists[key].append(item.group(1).strip())
        else:
            key = None
    return lists


def scope_violations(text, required):
    """Every reason this rule text does not hold the scope `required` asks for."""
    lists = frontmatter_lists(text)
    found = []
    if "globs" in lists:
        found.append("uses `globs:`, which Claude Code ignores; the rule loads every session")
    paths = set(lists.get("paths", []))
    if not paths:
        found.append("has no `paths:` list, so it is always-on")
    if paths & CATCH_ALL:
        found.append("carries a catch-all pattern, so it is always-on")
    missing = required - paths
    if missing:
        found.append("scope dropped " + ", ".join(sorted(missing)))
    return found


def test_no_rule_declares_its_scope_under_globs():
    wrong = [p.name for p in sorted(RULES.glob("*.md")) if "globs" in frontmatter_lists(p.read_text())]
    assert not wrong, f"`globs:` is not honored, use `paths:`: {wrong}"


def test_scoped_rules_hold_their_scope():
    for name, entry in SCOPED.items():
        problems = scope_violations((RULES / name).read_text(), entry[1])
        assert not problems, f"{name}: {problems}"


def test_scoped_rules_name_this_enforcer():
    for name, entry in SCOPED.items():
        rule_id = entry[0]
        text = (RULES / name).read_text()
        assert f"Rule-ID: {rule_id}" in text, f"{name} lost its Rule-ID line"
        assert "test_rule_path_scope.py" in text, f"{name} no longer names its enforcer"


def test_the_check_goes_red_on_each_planted_defect():
    required = {"**/*.html"}
    good = '---\ndescription: d\npaths:\n  - "**/*.html"\n---\n\n# R\n'
    assert scope_violations(good, required) == []
    planted = {
        "globs key": good.replace("paths:", "globs:"),
        "no frontmatter": "# R\n\nbody\n",
        "catch-all": good.replace('"**/*.html"', '"**/*.html"\n  - "**/*"'),
        "narrowed": good.replace("**/*.html", "sites/never/*.html"),
    }
    for label, text in planted.items():
        assert scope_violations(text, required), f"planted defect not caught: {label}"
