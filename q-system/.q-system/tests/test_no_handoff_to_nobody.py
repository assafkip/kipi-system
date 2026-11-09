#!/usr/bin/env python3
"""No machine message hands work to nobody (ASK-4012).

Founder, 2026-11-08, verbatim: "You keep saying someone needs to do a thing. Who is
this someone? This feels like hedging and getting things stuck." And: "Everything
must be enforced with code."

WHAT IS SCANNED. The strings fleet scripts under SCAN_PREFIXES (q-system/.q-system/,
q-system/hooks/, scripts/) and the root `kipi` CLI can send: Linear comments, ticket
titles and bodies, Slack and page text, cap and refusal lines, worker prompts.
plugins/ is NOT scanned. Measured 2026-11-08 (PR #658 review): 142 plugin scripts,
9 hits, one a live blocking hook ("run the deep read manually"). Widening the
scope is its own change, captured on the spillover ledger for Sana.
  * Python: every string literal, by ast. Docstrings are skipped (they are the
    code's own notes) and so are pattern arguments to re.compile and its siblings
    (a detector that matches the words is not a message that says them).
  * Shell: every line that is not a comment, so heredoc bodies count too.
Test files are never scanned; their fixtures quote the words on purpose.

WHAT FAILS. needs a human (or "a human" plus an action verb), someone, somebody, a person, manual or manually as an
action, parked for later, operator. Each says the next step belongs to nobody in
particular. The fix is a message that names the script or job that takes it.

A NEW EXCEPTION IS A REVIEWED DECISION, NEVER A MARKER. handoff-wording-exceptions.json
lists the five ASK-3824 cap sites, which that ticket rewrites with the code behind
them. Every exception must still match a hit (a stale one fails), and the count is
capped by EXCEPTION_CEILING here. There is no bypass marker, by design (coordinator
ruling, 2026-11-08): a legitimate use of a banned word, such as help text that means
a comparison operator, gets a row in the PR that needs it, with a `why`, and raises
the ceiling in the same diff, so the reviewer reads both. A row that is not on
origin/main and carries no `why` fails. PR #658 review, major: the earlier rule
refused every new row, so no author could turn the required check green.

AN EXCEPTION COVERS ITS PHRASE, NOT ITS LINE. A hit is excused only when the banned
word sits inside the row's `contains` text. Wording appended to an excused line
still fails (PR #658 review, minor: four phrases appended to a cap page passed).
"""
from __future__ import annotations

import ast

import pytest
import json
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
QDIR = HERE.parent
REPO = QDIR.parents[1]
EXCEPTIONS = QDIR / "handoff-wording-exceptions.json"
EXCEPTIONS_REL = "q-system/.q-system/handoff-wording-exceptions.json"

# The count of exceptions left. ASK-3824 (PR #662) removed its 4 cap-site rows; the 3
# left are the worker's not-armed branch. Lower it as ASK-3962 (pr-owner.py) lands.
EXCEPTION_CEILING = 3

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
        return [(rel, 0, "unparseable", "the scanner cannot read this file", 0)]
    skip = _docstring_ids(tree) | _pattern_ids(tree)
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip:
            # Matched on the normalized text so the offset indexes the text reported.
            norm = " ".join(n.value.split())
            for m in BANNED.finditer(norm):
                hits.append((rel, n.lineno, m.group(0), norm, m.start()))
    return hits


HEREDOC = re.compile(r"""<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")


def _strip(line: str, quote):
    """(the line up to an unquoted word-start `#`, the quote still open at its end).

    PR #658 review round 1: only full-line comments were skipped, so a trailing
    comment failed the gate. Round 2: the quote state was per line, so a ` # `
    inside a multi-line quoted string cut off the message text after it. `${#v}`
    and `$#` are never comments.
    """
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "\\":
            i += 2
            continue
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i], quote
        i += 1
    return line, quote


def strip_shell_comment(line: str) -> str:
    return _strip(line, None)[0]


def shell_hits(rel: str, text: str) -> list:
    """Quote state runs across lines. A heredoc body is tracked apart from it, so an
    apostrophe in body text never opens a quote over the code after the body.

    HEREDOC BODIES KEEP SHELL COMMENT RULES, ON PURPOSE (PR #658 round 2, the half
    rejected). Measured 2026-11-08: scanning bodies raw adds 10 hits on this tree and
    every one is a `#` comment inside embedded code (the python in linear-worker.sh),
    none a message.
    """
    hits, quote, delim = [], None, None
    for no, line in enumerate(text.splitlines(), 1):
        if delim is not None:
            if line.strip() == delim:
                delim = None
                continue
            s = strip_shell_comment(line).strip()
        else:
            code, after = _strip(line, quote)
            s = code.strip()
            # Any quote state: `X="$(python3 - <<'PY'` opens a quote AND a heredoc, and
            # the quote closes on the `)"` line after the body, so it is kept across.
            m = HEREDOC.search(code)
            if m:
                delim = m.group(2)
            quote = after
        if not s:
            continue
        for m in BANNED.finditer(s):
            hits.append((rel, no, m.group(0), s, m.start()))
    return hits


def scan(repo: pathlib.Path, files=None) -> list:
    hits = []
    for rel in (files if files is not None else fleet_files(repo)):
        text = (repo / rel).read_text(errors="replace")
        hits += python_hits(rel, text) if rel.endswith(".py") else shell_hits(rel, text)
    return hits


def matches(exc: dict, hit) -> bool:
    """The hit's word lies inside an occurrence of the row's phrase on that line."""
    if exc["path"] != hit[0]:
        return False
    text, at, want = hit[3], hit[4], exc["contains"]
    start = text.find(want)
    while start >= 0:
        if start <= at < start + len(want):
            return True
        start = text.find(want, start + 1)
    return False


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
            if (e["path"], e["contains"]) not in origin_keys and not (e.get("why") or "").strip():
                out.append(f"exception {e['path']} / {e['contains']!r} is new and gives no `why`; "
                           f"a new row carries the reason the reviewer reads")
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
    assert any("gives no `why`" in p for p in check(scan(root, ["s/b.sh"]), exc, 1, origin_keys=set()))
    assert check(scan(root, ["s/b.sh"]), exc, 1, origin_keys={("s/b.sh", "needs a human")}) == []


def test_a_new_row_with_a_why_and_a_raised_ceiling_is_green(tmp_path):
    """The reviewer's repro B: the author adds the row and raises the ceiling."""
    root = _tree(tmp_path, {"s/n.sh": 'echo "usage: pick a comparison operator (eq, gt, lt)"\n'})
    exc = [{"path": "s/n.sh", "contains": "pick a comparison operator", "ticket": "ASK-1",
            "why": "help text: a comparison operator, not a person"}]
    assert check(scan(root, ["s/n.sh"]), exc, 1, origin_keys=set()) == []
    assert any("ceiling" in p for p in check(scan(root, ["s/n.sh"]), exc, 0, origin_keys=set()))


def test_an_exception_does_not_license_words_appended_to_its_line(tmp_path):
    root = _tree(tmp_path, {"s/b.sh": 'echo "stuck - needs a human; ask someone, parked for later"\n'})
    exc = [{"path": "s/b.sh", "contains": "stuck - needs a human", "ticket": "ASK-1"}]
    problems = check(scan(root, ["s/b.sh"]), exc, 1)
    assert len(problems) == 2
    assert any("'someone'" in p for p in problems) and any("'parked for later'" in p for p in problems)


@pytest.mark.parametrize("line,want", [
    ("git pull --ff-only  # someone else may have pushed here", []),
    ('echo "ask someone"  # trailing note', ["someone"]),
    ("echo 'a # inside quotes, someone'", ["someone"]),
    ('n=${#arr[@]}; echo "$# args for someone"', ["someone"]),
])
def test_a_trailing_shell_comment_is_a_comment(tmp_path, line, want):
    assert [h[2] for h in shell_hits("s/c.sh", line + "\n")] == want


def test_a_hash_inside_a_multi_line_string_is_text():
    """PR #658 round 2: the quote opened on line 1 is still open on line 2."""
    text = 'echo "the job stops here,\n  # then someone has to restart it"\n'
    assert [h[2] for h in shell_hits("s/m.sh", text)] == ["someone"]


def test_a_heredoc_body_keeps_comment_rules_and_leaks_no_quote():
    text = ("python3 - <<'PY'\n"
            "# a comment inside embedded code may say someone\n"
            "print(\"don't stop\")\n"
            "PY\n"
            "git pull --ff-only  # someone else may have pushed\n"
            'echo "ask someone"\n')
    assert [(h[1], h[2]) for h in shell_hits("s/h.sh", text)] == [(6, "someone")]


def test_a_heredoc_inside_a_command_substitution_is_still_a_heredoc():
    """The ready() shape in linear-worker.sh: the quote and the heredoc open on one line."""
    text = ('PICKED="$(python3 - <<\'PY\'\n'
            "# embedded code may say the operator reads this\n"
            "PY\n"
            ')"\n'
            'echo "ask someone"\n')
    assert [(h[1], h[2]) for h in shell_hits("s/r.sh", text)] == [(5, "someone")]


def test_test_files_are_never_scanned():
    assert not in_scope("q-system/.q-system/tests/test_x.py")
    assert not in_scope("q-system/.q-system/scripts/test/test-x.sh")
    assert in_scope("q-system/.q-system/scripts/linear-worker.sh")
    assert in_scope("kipi")
