#!/usr/bin/env python3
"""No machine message hands work to nobody (ASK-4012).

Founder, 2026-11-08, verbatim: "You keep saying someone needs to do a thing. Who is
this someone? This feels like hedging and getting things stuck." And: "Everything
must be enforced with code."

WHAT IS SCANNED. Every string a fleet script can send: Linear comments, ticket
titles and bodies, Slack and page text, cap and refusal lines, worker prompts.
  * Python: every string literal, by ast. Docstrings are skipped (they are the
    code's own notes) and so are pattern arguments to re.compile and its siblings
    (a detector that matches the words is not a message that says them).
  * Shell: every line that is not a comment, so heredoc bodies count too.
Test files are never scanned; their fixtures quote the words on purpose.

WHAT FAILS. needs a human (or "a human" plus an action verb), someone, somebody, a person, manual or manually as an
action, parked for later, operator. Each says the next step belongs to nobody in
particular. The fix is a message that names the script or job that takes it.

THE EXCEPTIONS MAY ONLY SHRINK. handoff-wording-exceptions.json lists the five
ASK-3824 cap sites, which that ticket rewrites with the code behind them. Every
exception must still match a hit (a stale one fails), the list is capped by
EXCEPTION_CEILING here, and when git can read origin/main the list must be a
subset of main's.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
QDIR = HERE.parent
REPO = QDIR.parents[1]
EXCEPTIONS = QDIR / "handoff-wording-exceptions.json"
EXCEPTIONS_REL = "q-system/.q-system/handoff-wording-exceptions.json"

# The count of exceptions when this test was written. Lower it as ASK-3824 lands.
EXCEPTION_CEILING = 7

ACTION_NOUNS = (r"resolve|resolution|intervention|fix|review|step|action|edit|clean-?up|"
                r"decision|merge|triage|re-?run|override|recovery|repair|work|follow-?up")
BANNED = re.compile(
    r"\b(?:needs?|requires?|needing) a human\b"
    r"|\ba human (?:must|should|will|has to|needs? to|resolves?|decides?|checks?|runs?|fixes?|reviews?)\b"
    r"|\bsomeone\b|\bsomebody\b"
    r"|\ba person\b(?!'s)"
    r"|\bmanually\b"
    rf"|\bmanual (?:{ACTION_NOUNS})\b"
    r"|\b(?:needs?|requires?|needing) manual\b"
    r"|\bparked for later\b"
    r"|\boperators?\b",
    re.I)

# Fleet scripts: the code that runs unattended and writes to tickets, Slack and logs.
SCAN_PREFIXES = ("q-system/.q-system/", "q-system/hooks/", "scripts/")
SCAN_SUFFIXES = (".py", ".sh")
ROOT_EXTRA = ("kipi",)
RE_FUNCS = {"compile", "search", "match", "fullmatch", "sub", "subn", "findall",
            "finditer", "split"}


def is_test_path(rel: str) -> bool:
    name = pathlib.PurePosixPath(rel).name
    parts = set(pathlib.PurePosixPath(rel).parts)
    return bool(parts & {"test", "tests"}) or name.startswith(("test_", "test-")) \
        or name.endswith(("_test.py", "-test.sh"))


def in_scope(rel: str) -> bool:
    if is_test_path(rel) or not rel.endswith(SCAN_SUFFIXES + ROOT_EXTRA):
        return False
    return rel.startswith(SCAN_PREFIXES) or "/" not in rel


def fleet_files(repo: pathlib.Path) -> list:
    out = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True,
                         text=True, check=True).stdout.split("\n")
    return sorted(r for r in out if r and in_scope(r) and (repo / r).is_file())


def _docstring_ids(tree) -> set:
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
            ids.add(id(n.body[0].value))
    return ids


def _pattern_ids(tree) -> set:
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in RE_FUNCS and isinstance(n.func.value, ast.Name) \
                and n.func.value.id == "re" and n.args:
            ids.update(id(c) for c in ast.walk(n.args[0]) if isinstance(c, ast.Constant))
    return ids


def python_hits(rel: str, text: str) -> list:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [(rel, 0, "unparseable", "the scanner cannot read this file")]
    skip = _docstring_ids(tree) | _pattern_ids(tree)
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip:
            for m in BANNED.finditer(n.value):
                hits.append((rel, n.lineno, m.group(0), " ".join(n.value.split())))
    return hits


def shell_hits(rel: str, text: str) -> list:
    hits = []
    for no, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        for m in BANNED.finditer(s):
            hits.append((rel, no, m.group(0), s))
    return hits


def scan(repo: pathlib.Path, files=None) -> list:
    hits = []
    for rel in (files if files is not None else fleet_files(repo)):
        text = (repo / rel).read_text(errors="replace")
        hits += python_hits(rel, text) if rel.endswith(".py") else shell_hits(rel, text)
    return hits


def matches(exc: dict, hit) -> bool:
    return exc["path"] == hit[0] and exc["contains"] in hit[3]


def check(hits: list, exceptions: list, ceiling: int, origin_keys=None) -> list:
    """Every reason the tree fails. [] means it holds."""
    out = []
    for h in hits:
        if not any(matches(e, h) for e in exceptions):
            out.append(f"{h[0]}:{h[1]}: '{h[2]}' hands work to nobody: {h[3][:200]}")
    for e in exceptions:
        if not re.fullmatch(r"ASK-\d+", e.get("ticket") or ""):
            out.append(f"exception {e.get('path')} names no ticket")
        if not any(matches(e, h) for h in hits):
            out.append(f"exception {e['path']} / {e['contains']!r} matches nothing: remove it")
    if len(exceptions) > ceiling:
        out.append(f"{len(exceptions)} exceptions, ceiling {ceiling}: the list may only shrink")
    if origin_keys is not None:
        for e in exceptions:
            if (e["path"], e["contains"]) not in origin_keys:
                out.append(f"exception {e['path']} / {e['contains']!r} is new; the list may only shrink")
    return out


def load_exceptions() -> list:
    return json.loads(EXCEPTIONS.read_text())["exceptions"] if EXCEPTIONS.exists() else []


def origin_keys():
    try:
        text = subprocess.run(["git", "-C", str(REPO), "show", f"origin/main:{EXCEPTIONS_REL}"],
                              capture_output=True, text=True, check=True).stdout
        return {(e["path"], e["contains"]) for e in json.loads(text)["exceptions"]}
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError):
        return None


# --- the real tree -------------------------------------------------------------

def test_the_scan_reaches_the_fleet_scripts():
    files = fleet_files(REPO)
    for must in ("q-system/.q-system/scripts/linear-worker.sh",
                 "q-system/.q-system/scripts/converge.sh",
                 "q-system/.q-system/scripts/linear-alert-triage.py", "kipi-dispatch.sh"):
        assert must in files, must
    assert not [f for f in files if is_test_path(f)]


def test_no_fleet_message_hands_work_to_nobody():
    problems = check(scan(REPO), load_exceptions(), EXCEPTION_CEILING, origin_keys())
    assert problems == [], "\n".join(problems)


# --- the negative self-tests -------------------------------------------------

def _tree(tmp_path, files: dict) -> pathlib.Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


CLEAN_PY = '''"""Docstring may say someone: it is a note, not a message."""
import re
PAT = re.compile(r"the operator")
MSG = "linear-dor-drafter.py (com.kipi.linear-dor, 03:00) redrafts it"
KIND = "manual-only"
'''
CLEAN_SH = '# a comment may say someone\necho "the worker retries at 03:00"\n'


def test_clean_fixture_is_green(tmp_path):
    root = _tree(tmp_path, {"s/a.py": CLEAN_PY, "s/b.sh": CLEAN_SH})
    assert check(scan(root, ["s/a.py", "s/b.sh"]), [], 0) == []


def test_a_handoff_in_a_python_message_goes_red(tmp_path):
    root = _tree(tmp_path, {"s/a.py": CLEAN_PY + 'X = f"{n} tickets: someone should look"\n'})
    assert any("someone" in p for p in check(scan(root, ["s/a.py"]), [], 0))


def test_a_handoff_in_a_shell_heredoc_body_goes_red(tmp_path):
    body = 'cat <<EOF\nThis PR needs a human to merge it.\nEOF\n'
    root = _tree(tmp_path, {"s/b.sh": CLEAN_SH + body})
    assert any("needs a human" in p for p in check(scan(root, ["s/b.sh"]), [], 0))


def test_manual_as_an_action_goes_red_and_as_a_kind_does_not(tmp_path):
    root = _tree(tmp_path, {"s/a.py": 'A = "merge failed (needs manual resolve)"\nB = "manual-only"\n'})
    hits = scan(root, ["s/a.py"])
    assert {h[3] for h in hits} == {"merge failed (needs manual resolve)"}


def test_an_exception_covers_its_hit_only(tmp_path):
    root = _tree(tmp_path, {"s/b.sh": 'echo "stuck - needs a human"\necho "ask someone"\n'})
    exc = [{"path": "s/b.sh", "contains": "stuck - needs a human", "ticket": "ASK-1"}]
    problems = check(scan(root, ["s/b.sh"]), exc, 1)
    assert len(problems) == 1 and "ask someone" in problems[0]


def test_a_stale_exception_goes_red(tmp_path):
    root = _tree(tmp_path, {"s/b.sh": CLEAN_SH})
    exc = [{"path": "s/b.sh", "contains": "gone", "ticket": "ASK-1"}]
    assert any("matches nothing" in p for p in check(scan(root, ["s/b.sh"]), exc, 1))


def test_growing_the_exception_list_goes_red(tmp_path):
    root = _tree(tmp_path, {"s/b.sh": 'echo "needs a human"\n'})
    exc = [{"path": "s/b.sh", "contains": "needs a human", "ticket": "ASK-1"}]
    assert any("ceiling" in p for p in check(scan(root, ["s/b.sh"]), exc, 0))
    assert any("is new" in p for p in check(scan(root, ["s/b.sh"]), exc, 1, origin_keys=set()))
    assert check(scan(root, ["s/b.sh"]), exc, 1, origin_keys={("s/b.sh", "needs a human")}) == []


def test_test_files_are_never_scanned():
    assert not in_scope("q-system/.q-system/tests/test_x.py")
    assert not in_scope("q-system/.q-system/scripts/test/test-x.sh")
    assert in_scope("q-system/.q-system/scripts/linear-worker.sh")
    assert in_scope("kipi")
