#!/usr/bin/env python3
"""new-view-gate: no new test and no new phase without a DIFFERENT view first.

WHY (founder, 2026-10-03, verbatim): "you cant just keep adding tests. that should
be enforced in code. you cannot add more tests or phases - you must view the
problem from a diferent perspective, a new agent or a look into the code, the kb or
canonical files - never add a test without a different view - enforce this across
all build types, tests, repos - everyhting".

The failure shape: a fix goes red, the agent adds a test; still red, adds another
test or another plan phase; and every round repeats the same mental model. The
lesson `the-author-of-a-fix-picks-the-oracle-the-fix-already-passes` documents six
instances in one session. A new assertion written from the same view tests the
view, not the code.

THE RULE (deterministic, read from the session transcript):
  An Edit/Write/MultiEdit/NotebookEdit that ADDS a test (a new test file, or more
  test definitions than before) or ADDS a phase (more `Phase N` headings in a
  markdown file than before) is blocked unless, since the previous test/phase
  addition in this session, at least one NEW view was taken:
    - an Agent/Task call (a fresh agent),
    - a KB lookup (any mcp__miyo__* tool, or a Bash `miyo search`),
    - a Read/Grep/Glob of something that is NOT a test file (the code itself,
      canonical/, the lessons corpus, memory),
  and that view's target was not used anywhere before the previous addition.
  Re-reading any file already read earlier in the session is the same view.

  The first test/phase of a session needs a view too: "never add a test without
  a different view".

HONEST BOUNDARY: this proves a different thing was LOOKED AT between additions. It
cannot prove the look changed the thinking. ANY fresh non-test read satisfies the
gate, including one unrelated to the problem (sp-e96411d5 item 1, kept on purpose:
relevance is a judgment no transcript regex can make). A Bash read (cat, sed -n,
grep, rg, git show ...) counts when it names a non-test path; a test run never
counts, including a test file run directly (python3 x/test_a.py, bash test-a.sh).

A PAST Write is judged by what Claude Code stored for it: toolUseResult.type
create|update and originalFile. A rewrite of an existing test file with no new defs
is then not an addition. When that record is missing (an older transcript, a call
still pending), the Write to a test file counts as an addition, conservatively.

Fails OPEN on missing/unreadable transcript or malformed input: a hook that fails
closed on its own infrastructure blocks the fix too. Kill switch for the founder's
shell only: NEW_VIEW_GATE_OFF=1.

Contract: PreToolUse(Write|Edit|MultiEdit|NotebookEdit), hook JSON on stdin.
exit 0 = pass, exit 2 = block (stderr goes to the model). stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Keys tool_calls() adds to a COPY of a past Write's input. Never in a live payload.
PRIOR_TEXT = "__nvg_original_file__"
PRIOR_NEW = "__nvg_created__"

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
AGENT_TOOLS = {"Agent", "Task"}
LOOK_TOOLS = {"Read", "Grep", "Glob"}

# A test file, by name or location, in any language this fleet writes.
RE_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec)/"
    r"|(^|/)test[_\-][^/]*$"
    r"|[_\-.]test\.[A-Za-z0-9]+$"
    r"|\.spec\.[A-Za-z0-9]+$"
    r"|(^|/)conftest\.py$"
)

# One test definition, per language. Counted, not parsed: the question is "did the
# count go up", and a regex answers it the same way on both sides of the edit.
RE_TEST_DEF = re.compile(
    r"^\s*(?:async\s+)?def\s+test\w*\s*\("                 # python
    r"|^\s*func\s+Test\w*\s*\("                            # go
    r"|^\s*#\[(?:tokio::)?test\]"                          # rust
    r"|\b(?:it|test)(?:\.(?:only|each|concurrent))?\s*\(\s*['\"`]"  # js/ts
    r"|^\s*(?:function\s+)?test_\w+\s*\(\)\s*\{"           # bash
    r"|^\s*@Test\b",                                       # java/kotlin
    re.MULTILINE,
)

# A heading or a bold list item only. Prose that starts "Phase 2 ..." in a
# handoff or PR body is not a new phase (review of #512).
RE_BASH_READ = re.compile(
    r"(^|[;&|]\s*|\s)(cat|sed\s+-n|head|tail|grep|rg|awk|less|git\s+(show|grep|log|diff))\b")
RE_TEST_RUN = re.compile(r"\b(pytest|unittest|npm\s+test|go\s+test|cargo\s+test|jest|vitest)\b")
# Running a test FILE directly is a test run too. ASK-2473: `cd repo && python3
# hooks/test_x.py | tail` named a non-test path (the cd target) and a reader (tail),
# so run-the-suite-then-add-a-test passed as a view.
INTERPRETERS = {"python", "python3", "bash", "sh", "zsh", "node", "deno", "bun", "ruby", "perl"}

RE_PHASE = re.compile(
    r"^(?:#{1,6}\s+|\s*[-*]\s+\*\*)Phase\s+[0-9A-Za-z.]+\b",
    re.MULTILINE | re.IGNORECASE,
)


# The file itself is a test (not a conftest or fixture that lives in tests/).
RE_TEST_FILE = re.compile(
    r"(^|/)test[_\-][^/]*$|[_\-.]test\.[A-Za-z0-9]+$|\.spec\.[A-Za-z0-9]+$")


def is_test_file(path: str) -> bool:
    return bool(path) and bool(RE_TEST_FILE.search(path.replace("\\", "/")))


def is_test_path(path: str) -> bool:
    return bool(path) and bool(RE_TEST_PATH.search(path.replace("\\", "/")))


def is_test_run(cmd: str) -> bool:
    """A Bash command that runs tests: a runner, or an interpreter given a test file."""
    if RE_TEST_RUN.search(cmd or ""):
        return True
    words = re.split(r"[\s;&|()]+", cmd or "")
    for i, w in enumerate(words):
        name = w.rsplit("/", 1)[-1]
        if w.startswith("./") and is_test_file(w):
            return True
        if name in INTERPRETERS or re.fullmatch(r"python3\.\d+", name):
            rest = [x for x in words[i + 1:] if x and not x.startswith("-")]
            if rest and is_test_file(rest[0]):
                return True
    return False


def is_markdown(path: str) -> bool:
    return path.lower().endswith((".md", ".markdown", ".mdx"))


def _count(regex, text: str) -> int:
    return len(regex.findall(text or ""))


def _old_and_new(tool: str, inp: dict, read_disk: bool) -> tuple[str, str, bool]:
    """(old text, new text, file_is_new) for one write call."""
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    if tool == "Edit":
        return inp.get("old_string", ""), inp.get("new_string", ""), False
    if tool == "MultiEdit":
        edits = inp.get("edits") or []
        return ("\n".join(e.get("old_string", "") for e in edits),
                "\n".join(e.get("new_string", "") for e in edits), False)
    if tool == "NotebookEdit":
        return "", inp.get("new_source", ""), False
    # Write
    new = inp.get("content", "")
    if not read_disk:
        # tool_calls() copies the stored outcome of a past Write onto its input.
        if isinstance(inp.get(PRIOR_TEXT), str):
            return inp[PRIOR_TEXT], new, False
        if inp.get(PRIOR_NEW):
            return "", new, True
        return "", new, False
    p = Path(path)
    if not p.exists():
        return "", new, True
    try:
        return p.read_text(encoding="utf-8", errors="ignore"), new, False
    except Exception:
        return "", new, False


def addition_kind(tool: str, inp: dict, read_disk: bool = True) -> str | None:
    """'test', 'phase' or None: does this write ADD a test or a phase?"""
    if tool not in WRITE_TOOLS or not isinstance(inp, dict):
        return None
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    old, new, is_new = _old_and_new(tool, inp, read_disk)
    if is_test_path(path):
        if _count(RE_TEST_DEF, new) > _count(RE_TEST_DEF, old):
            return "test"
        if is_new and new.strip() and is_test_file(path):
            return "test"
        # A PAST Write cannot be diffed (disk has moved on), and a test file in
        # check(...) style has no def to count. Found live 2026-10-03: the gate's
        # own self-test was written that way and did not reset the clock.
        if (tool == "Write" and not read_disk and new.strip() and is_test_file(path)
                and PRIOR_TEXT not in inp):
            return "test"
    if is_markdown(path) and _count(RE_PHASE, new) > _count(RE_PHASE, old):
        return "phase"
    return None


def view_key(tool: str, inp: dict) -> str | None:
    """A stable key for a view, or None if this call is not a view."""
    if not isinstance(inp, dict):
        inp = {}
    if tool in AGENT_TOOLS:
        return "agent:" + (inp.get("prompt") or inp.get("description") or "")[:200]
    if "miyo" in tool.lower():
        return "kb:" + json.dumps(inp, sort_keys=True)[:200]
    if tool == "Bash" and re.search(r"\bmiyo\s+search\b", inp.get("command", "")):
        return "kb:" + inp.get("command", "")[:200]
    # A shell read of a non-test path is a look at the code too. Review of #512:
    # a real transcript had 34 Bash calls and 0 Read/Grep/Glob, so ignoring the
    # shell blocked sessions that had looked. Test runners are not a view.
    if tool == "Bash":
        cmd = inp.get("command", "")
        if RE_BASH_READ.search(cmd) and not is_test_run(cmd):
            paths = [w for w in re.findall(r"[\w./~\-]+", cmd) if "/" in w or "." in w]
            if any(not is_test_path(w) for w in paths):
                return "bash:" + " ".join(cmd.split())[:200]
    if tool in LOOK_TOOLS:
        target = inp.get("file_path") or inp.get("path") or ""
        pattern = inp.get("pattern") or ""
        if tool == "Read" and is_test_path(target):
            return None
        if tool == "Glob" and is_test_path(pattern):
            return None
        if tool == "Grep" and target and is_test_path(target):
            return None
        return f"{tool}:{target}:{pattern}"
    return None


def _records(transcript_path):
    p = Path(transcript_path) if transcript_path else None
    if not p or not p.exists():
        return None
    out = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        # ASK-2472: a list/str/number line raised AttributeError in tool_calls.
        if isinstance(rec, dict):
            out.append(rec)
    return out


def tool_calls(records) -> list[tuple[str, dict]]:
    """(name, input) for every tool call that was not refused or errored."""
    records = [r for r in records if isinstance(r, dict)]
    failed = set()
    stored = {}
    for rec in records:
        msg = rec.get("message", {})
        if isinstance(msg, dict):
            for item in msg.get("content", []) or []:
                if not (isinstance(item, dict) and item.get("type") == "tool_result"):
                    continue
                if item.get("is_error"):
                    failed.add(item.get("tool_use_id"))
                if isinstance(rec.get("toolUseResult"), dict):
                    stored[item.get("tool_use_id")] = rec["toolUseResult"]
    calls = []
    for rec in records:
        msg = rec.get("message", {})
        if not isinstance(msg, dict):
            continue
        for item in msg.get("content", []) or []:
            if (isinstance(item, dict) and item.get("type") == "tool_use"
                    and item.get("id") not in failed):
                name, inp = item.get("name", ""), item.get("input") or {}
                res = stored.get(item.get("id"))
                if name == "Write" and isinstance(inp, dict) and res:
                    inp = dict(inp)
                    if res.get("type") == "update" and isinstance(res.get("originalFile"), str):
                        inp[PRIOR_TEXT] = res["originalFile"]
                    elif res.get("type") == "create":
                        inp[PRIOR_NEW] = True
                calls.append((name, inp))
    return calls


def last_addition(calls) -> int:
    """Index of the last past test/phase addition, -1 if none this session."""
    last_add = -1
    for i, (name, inp) in enumerate(calls):
        # Past writes: the file on disk has moved on, so judge them by their own
        # input plus the stored originalFile tool_calls() attached.
        if addition_kind(name, inp, read_disk=False):
            last_add = i
    return last_add


def has_new_view(calls) -> bool:
    """Since the last addition, was a view taken that was not used before it?"""
    last_add = last_addition(calls)
    before = {view_key(n, x) for n, x in calls[:last_add + 1]} - {None}
    after = [view_key(n, x) for n, x in calls[last_add + 1:]]
    return any(k and k not in before for k in after)


def main() -> int:
    if os.environ.get("NEW_VIEW_GATE_OFF") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input") or {}
    kind = addition_kind(tool, inp)
    if not kind:
        return 0
    try:
        records = _records(payload.get("transcript_path"))
    except Exception:
        return 0
    if records is None:
        return 0
    try:
        calls = tool_calls(records)
        if has_new_view(calls):
            return 0
        prior = last_addition(calls) >= 0
    except Exception:
        return 0
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    # ASK-2473: with no earlier addition, "since the last test was added" was false.
    when = ("no NEW view was taken since the last test/phase was added" if prior
            else "no view was taken yet this session")
    print(
        f"BLOCKED by new-view-gate: this write adds a {kind} ({path}) and {when}.\n"
        "Adding another test or phase from the same view tests the view, not the "
        "code. First look at the problem differently, with ONE of:\n"
        "  - a fresh agent (Agent tool) on the problem, not on your fix\n"
        "  - the code under test itself (Read/Grep a non-test file you have not read yet this round)\n"
        "  - the KB (mcp__miyo__search) or canonical/ / lessons files\n"
        "Then write the test or phase from what that view showed you.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
