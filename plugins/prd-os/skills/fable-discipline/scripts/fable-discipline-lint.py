#!/usr/bin/env python3
"""
fable-discipline-lint.py — Deterministic test-isolation enforcer.

Pairs with the fable-discipline skill (SKILL.md). Enforces the one mechanically
checkable slice of that skill's "verify against a copy, never the live resource"
rule: a TEST file must not name a real data path. Tests use a temp copy, a
tempfile, or :memory:.

This is the graded-good Fable habit (it migrated a COPY of the live prod DB to
prove idempotency) turned into a consistent guardrail, because an independent
Codex review caught a sibling test risking mutation of the live founder DB.

Usage:
    python3 fable-discipline-lint.py <file_path>   # CLI mode
    (no args)                                 # hook mode: PostToolUse JSON on stdin

Exit codes:
    0 = clean (or out of scope)
    2 = violation (a test names a non-isolated data path)

Override:
    Add  # fable-discipline-lint-skip  anywhere in the file to bypass.

Detector coverage (enumerated on purpose, per the hook-blind-spots rule):
    CATCHES  a quoted literal that is a real DB path — has a path separator AND a
             DB extension (.db/.sqlite/.sqlite3/.duckdb) — and is not isolated,
             in ANY use except a comparison/assertion. That covers a direct
             connect("...")/open("..."), every assignment form (plain, augmented
             +=, walrus :=, dict/subscript/attr target), and a literal nested
             inside an f-string. The path-separator requirement is what lets
             `tmp_path / "t.db"` through: the bare filename "t.db" has no
             separator, and isolation lives in the temp variable.
    SKIPS    comparison/assertion lines (assert ..., ==, !=), where the literal
             is being checked, not used — e.g. an OSS-secrets audit test
             asserting the live path is NAMED in a report.
    MISSES   (documented deferrals, each a low-likelihood shape that would add
             false-positive risk to catch):
             - a no-argument default db.connect() (no literal to see; left to the
               skill's monkeypatch-the-default convention)
             - adjacent string concatenation: connect('/dir/' 'x.db')
             - a triple-quoted one-line DB path
             - pathlib bare-segment joins: Path('/abs/data') / 'x.db'
             - em-dash narration (not a tool call; lives in the skill + style)

Scope (fast-exit otherwise, token discipline):
    Fires only on a Python TEST file, detected by basename test_*.py / *_test.py
    or a path under a /tests/ directory. Non-test code and non-Python edits exit 0.
"""

import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "fable-discipline-lint-skip"

# Spillover capture: a deferral written into CODE (a "# TODO: out of scope" that
# nobody tracks) is the silent-drop scar. Block it unless the finding was
# captured and the line is acked with `# spillover-skip`. Scoped to code files so
# docs/PRDs that legitimately discuss scope are never tripped. The GATE
# (prd_runner gates run) is the enforcement; this lint is the write-time nudge.
SPILL_SKIP_MARKER = "spillover-skip"
_CODE_SUFFIXES = {".py", ".js", ".ts", ".jsx", ".tsx", ".sh", ".rb", ".go",
                  ".rs", ".java", ".c", ".cpp", ".h", ".mjs", ".cjs"}
_DEFERRAL = re.compile(
    r"out[- ]of[- ]scope|fix (?:it )?later|defer(?:red)? this|"
    r"leave (?:this )?for later|won'?t fix(?: now)?|punt(?:ed|ing)? on",
    re.IGNORECASE,
)


def is_code_file(file_path):
    return Path(str(file_path)).suffix in _CODE_SUFFIXES


def find_deferral_lines(text):
    if SPILL_SKIP_MARKER in text:
        return []
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if _DEFERRAL.search(line):
            hits.append((i, line.strip()[:80]))
    return hits


def format_deferral_report(file_path, hits):
    lines = [f"fable-discipline-lint: {len(hits)} uncaptured deferral(s) in {file_path}:"]
    for ln, snippet in hits:
        lines.append(f"  line {ln}: {snippet}")
    lines.append(
        "An out-of-scope deferral in code must be CAPTURED, never just written and "
        "forgotten. Run `prd_runner.py spillover add --source <id> --desc \"...\"` so "
        "the standing gate tracks it, then add  # spillover-skip  to this file to ack."
    )
    return "\n".join(lines)

# A path literal is isolated (safe in a test) if it names any of these.
ISOLATION_TOKENS = (
    ":memory:", "tmp", "temp", "fixture", "fixtures", "mock", "sample",
    "testdata", "test_data", "golden", "mktemp", "temporarydirectory",
    "tmp_path", "tmpdir", "/var/folders", "getfixturevalue", "monkeypatch",
)

# A quoted literal that is a real DB path: contains a path separator AND ends in
# a DB extension. Matches inside f-strings too (the inner quote is a real match).
_DBPATH = re.compile(r"""(['"])([^'"]*[/\\][^'"]*\.(?:db|sqlite|sqlite3|duckdb))\1""")


def _is_isolated(p):
    low = p.lower()
    return any(tok in low for tok in ISOLATION_TOKENS)


def is_test_file(file_path):
    p = Path(str(file_path))
    if p.suffix != ".py":
        return False
    name = p.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return "/tests/" in str(file_path).replace("\\", "/")


def find_violations(text):
    violations = []
    in_doc = False
    delim = None
    seen = set()
    for i, line in enumerate(text.splitlines(), 1):
        if in_doc:
            if delim in line:
                in_doc = False
                delim = None
            continue
        s = line.lstrip()
        if s.startswith("#"):
            continue
        # enter a triple-quoted block if one opens and does not close this line
        for q in ('"""', "'''"):
            if line.count(q) % 2 == 1:
                in_doc = True
                delim = q
                break
        # skip comparisons/assertions: the literal is being checked, not used
        if s.startswith("assert") or "==" in line or "!=" in line:
            continue
        for m in _DBPATH.finditer(line):
            path = m.group(2)
            if _is_isolated(path):
                continue
            key = (i, path)
            if key not in seen:
                seen.add(key)
                violations.append((i, path))
    return violations


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        # Never block a write on a read/infra failure; this is a content gate.
        return []
    if SKIP_MARKER in text:
        return []
    return find_violations(text)


def format_report(file_path, violations):
    lines = [f"fable-discipline-lint: {len(violations)} test-isolation violation(s) in {file_path}:"]
    for ln, path in violations:
        lines.append(f"  line {ln}: test names a live data path \"{path}\"")
    lines.append(
        "Tests must use a temp copy, a tempfile, or :memory: — never a real data "
        "resource (fable-discipline skill: verify against a copy). "
        f"Fix it, or add  # {SKIP_MARKER}  to bypass."
    )
    return "\n".join(lines)


def hook_mode():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name", "") not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)
    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)
    # Deferral capture: any CODE file that defers without capture is blocked.
    if is_code_file(file_path):
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception:
            text = ""
        deferrals = find_deferral_lines(text) if text else []
        if deferrals:
            print(format_deferral_report(file_path, deferrals), file=sys.stderr)
            sys.exit(2)
    # Test isolation: only on test files.
    if not is_test_file(file_path):
        sys.exit(0)
    violations = lint_file(file_path)
    if not violations:
        sys.exit(0)
    print(format_report(file_path, violations), file=sys.stderr)
    sys.exit(2)


def cli_mode(file_path):
    if is_code_file(file_path):
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception:
            text = ""
        deferrals = find_deferral_lines(text) if text else []
        if deferrals:
            print(format_deferral_report(file_path, deferrals))
            sys.exit(2)
    if not is_test_file(file_path):
        print(f"fable-discipline-lint: not a test file (deferral-checked only): {file_path}")
        sys.exit(0)
    violations = lint_file(file_path)
    if not violations:
        print(f"fable-discipline-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: fable-discipline-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
