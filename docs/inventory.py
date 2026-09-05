#!/usr/bin/env python3
"""The one enumeration of every functionality surface in kipi-system, read from the
code at run time. Both docs/check_coverage.py (the gate) and docs/generate_reference.py
(the catalog) import this, so the gate and the catalog can never disagree about what
exists (lesson: derive a value from the code that owns it, never restate it).

Surface classes and where each is read from:

  script     every .py and .sh under q-system/.q-system, q-system/hooks, scripts/, automation/
             (repo-root instance automation, RULE-2026-06-30-A) and the repo root
             that is not a test (tests are a surface too, listed under `test`)
  test       the test files for those scripts
  mcp_tool   every @mcp.tool() in the MCP server
  resource   every @mcp.resource() in the MCP server
  command    every plugins/*/commands/*.md
  skill      every plugins/*/skills/*/SKILL.md
  hook       every command string under hooks in .claude/settings.json, settings-template.json
             and every plugins/*/hooks/hooks.json, reduced to the script it runs
  job        every com.kipi.*.plist label in the live tree
  rule       every .claude/rules/*.md
  agent      every .claude/agents/*.md
  style      every .claude/output-styles/*.md
  cli_verb   every verb the kipi dispatcher accepts

Each surface is a Surface(cls, name, path, doc). `name` is the token the docs must contain
verbatim (a filename, a tool name, a command name, a label). Scratch trees and copies are
excluded by SKIP_DIRS; that list is the scope decision and it is written here once.

Floor: enumerate() raises if any class comes back empty. An empty class is a broken
enumerator, never "nothing to document" (lesson: a check must be able to fail for the
reason you care about).
"""
from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "worktrees", "docs",
    "fable-wt", "template-repo", "security-remediation", "runs", "review-scratch",
    "review-tmp-pr11", "rescued", "dist", "sites",
}
SKIP_PREFIXES = (".wt-", ".pr")

SCRIPT_ROOTS = ("q-system/.q-system", "q-system/hooks", "scripts", "automation")
ROOT_TOOL_GLOBS = ("*.py", "*.sh", "kipi")
MCP_SERVER = "plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py"
SETTINGS_FILES = (".claude/settings.json", "settings-template.json")


@dataclass(frozen=True)
class Surface:
    cls: str
    name: str
    path: str
    doc: str = ""

    def key(self) -> tuple[str, str]:
        return (self.cls, self.name)


def _skip(dirname: str) -> bool:
    return dirname in SKIP_DIRS or dirname.startswith(SKIP_PREFIXES)


def _first_doc(path: Path) -> str:
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if path.suffix == ".py":
        try:
            doc = ast.get_docstring(ast.parse(src)) or ""
        except Exception:
            doc = ""
        return doc.strip().splitlines()[0].strip() if doc.strip() else ""
    for line in src.splitlines()[1:40]:
        s = line.strip()
        if s.startswith("#") and not s.startswith("#!"):
            s = s.lstrip("#").strip()
            if s:
                return s[:160]
    return ""


def _is_test(path: Path) -> bool:
    n = path.name
    return n.startswith("test") or "/test/" in path.as_posix() or "/tests/" in path.as_posix()


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def scripts_and_tests() -> list[Surface]:
    out: list[Surface] = []
    seen: set[str] = set()
    for base in SCRIPT_ROOTS:
        b = ROOT / base
        if not b.is_dir():
            continue
        for dp, dns, fns in os.walk(b):
            dns[:] = [d for d in dns if not _skip(d)]
            for fn in sorted(fns):
                if not fn.endswith((".py", ".sh")):
                    continue
                p = Path(dp) / fn
                rel = _rel(p)
                if rel in seen:
                    continue
                seen.add(rel)
                out.append(Surface("test" if _is_test(p) else "script", fn, rel, _first_doc(p)))
    for pat in ROOT_TOOL_GLOBS:
        for p in sorted(ROOT.glob(pat)):
            if not p.is_file():
                continue
            rel = _rel(p)
            if rel in seen:
                continue
            seen.add(rel)
            out.append(Surface("test" if _is_test(p) else "script", p.name, rel, _first_doc(p)))
    return out


def mcp_tools_and_resources() -> list[Surface]:
    src = (ROOT / MCP_SERVER).read_text(encoding="utf-8", errors="ignore")
    out: list[Surface] = []
    for m in re.finditer(r'@mcp\.tool\(\)\s*\n(?:async )?def (\w+)\([^)]*\)[^:]*:\s*\n\s*"""(.*?)(?:\n|""")', src, re.S):
        out.append(Surface("mcp_tool", m.group(1), MCP_SERVER, m.group(2).strip()[:160]))
    for m in re.finditer(r'@mcp\.resource\("([^"]+)"\)', src):
        out.append(Surface("resource", m.group(1), MCP_SERVER, ""))
    return out


def _frontmatter_desc(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    m = re.search(r"^description:\s*(.+)$", text, re.M)
    return m.group(1).strip().strip('"')[:200] if m else ""


def commands_and_skills() -> list[Surface]:
    out: list[Surface] = []
    for p in sorted(ROOT.glob("plugins/*/commands/*.md")):
        out.append(Surface("command", "/" + p.stem, _rel(p), _frontmatter_desc(p)))
    for p in sorted(ROOT.glob("plugins/*/skills/*/SKILL.md")):
        out.append(Surface("skill", p.parent.name, _rel(p), _frontmatter_desc(p)))
    return out


def hooks() -> list[Surface]:
    """Every hook reduced to the script it runs. Wired twice (both settings files) counts once;
    the docs must name the SCRIPT, which is what a reader can open. A script wired on more
    than one event keeps EVERY event and matcher in its doc, in first-seen order. Codex on
    PR #306 measured the first-wins version: token-guard.py is wired PreToolUse, PostToolUse
    and UserPromptSubmit and the catalog named only one, so a reader debugging a blocked
    Bash call was sent to the wrong event."""
    paths: dict[str, str] = {}
    fired: dict[str, list[str]] = {}
    files = [ROOT / f for f in SETTINGS_FILES] + sorted(ROOT.glob("plugins/*/hooks/hooks.json"))
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for event, groups in (data.get("hooks") or {}).items():
            for g in groups:
                for hk in g.get("hooks", []):
                    cmd = hk.get("command", "")
                    names = re.findall(r"([\w.-]+\.(?:py|sh))\b", cmd)
                    name = names[-1] if names else cmd.strip()[:60]
                    paths.setdefault(name, _rel(f))
                    on = f"{event} ({g.get('matcher', '*')})"
                    if on not in fired.setdefault(name, []):
                        fired[name].append(on)
    return [Surface("hook", n, paths[n], "; ".join(fired[n])) for n in paths]


def jobs() -> list[Surface]:
    out: dict[str, Surface] = {}
    for base in ("q-system", "plugins", "scripts", "automation"):
        b = ROOT / base
        if not b.is_dir():
            continue
        for dp, dns, fns in os.walk(b):
            dns[:] = [d for d in dns if not _skip(d)]
            for fn in fns:
                if fn.startswith("com.kipi.") and fn.endswith(".plist"):
                    label = fn[:-len(".plist")]
                    out.setdefault(label, Surface("job", label, _rel(Path(dp) / fn), ""))
    return list(out.values())


def claude_surfaces() -> list[Surface]:
    out: list[Surface] = []
    for p in sorted((ROOT / ".claude" / "rules").glob("*.md")):
        out.append(Surface("rule", p.name, _rel(p), ""))
    for p in sorted((ROOT / ".claude" / "agents").glob("*.md")):
        out.append(Surface("agent", p.stem, _rel(p), _frontmatter_desc(p)))
    for p in sorted((ROOT / ".claude" / "output-styles").glob("*.md")):
        out.append(Surface("style", p.stem, _rel(p), ""))
    return out


def cli_verbs() -> list[Surface]:
    src = (ROOT / "kipi").read_text(encoding="utf-8", errors="ignore")
    out: list[Surface] = []
    seen: set[str] = set()
    for m in re.finditer(r"^\s{2,8}([a-z][a-z0-9-]+)\)\s", src, re.M):
        v = m.group(1)
        if v in seen or v in ("esac", "*"):
            continue
        seen.add(v)
        out.append(Surface("cli_verb", v, "kipi", ""))
    return out


ORDER = ("script", "test", "mcp_tool", "resource", "command", "skill", "hook", "job",
         "rule", "agent", "style", "cli_verb")


def enumerate_surfaces() -> list[Surface]:
    all_: list[Surface] = []
    all_ += scripts_and_tests()
    all_ += mcp_tools_and_resources()
    all_ += commands_and_skills()
    all_ += hooks()
    all_ += jobs()
    all_ += claude_surfaces()
    all_ += cli_verbs()
    counts = {c: 0 for c in ORDER}
    for s in all_:
        counts[s.cls] = counts.get(s.cls, 0) + 1
    empty = [c for c, n in counts.items() if n == 0]
    if empty:
        raise RuntimeError(f"enumerator floor: zero surfaces for {empty}; the enumerator is broken, not the repo")
    return all_


if __name__ == "__main__":
    surfaces = enumerate_surfaces()
    by = {}
    for s in surfaces:
        by.setdefault(s.cls, []).append(s)
    for c in ORDER:
        print(f"{c:10s} {len(by.get(c, [])):4d}")
    print(f"{'total':10s} {len(surfaces):4d}")
