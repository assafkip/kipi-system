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
  and that view's target was not already used before the previous addition.
  Re-reading the same file you read last round is the same view, not a new one.

  The first test/phase of a session needs a view too: "never add a test without
  a different view".

HONEST BOUNDARY: this proves a different thing was LOOKED AT between additions. It
cannot prove the look changed the thinking. Bash `cat`/`sed` reads do not count
(path extraction from shell text is guesswork); use Read/Grep or an agent.

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

RE_PHASE = re.compile(
    r"^(?:#{1,6}\s+|\s*[-*]\s+\**\s*|\s*\**)Phase\s+[0-9A-Za-z.]+\b",
    re.MULTILINE | re.IGNORECASE,
)


def is_test_path(path: str) -> bool:
    return bool(path) and bool(RE_TEST_PATH.search(path.replace("\\", "/")))


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
        if is_new and new.strip():
            return "test"
        # A PAST Write cannot be diffed (disk has moved on), and a test file in
        # check(...) style has no def to count. Found live 2026-10-03: the gate's
        # own self-test was written that way and did not reset the clock.
        if tool == "Write" and not read_disk and new.strip():
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
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def tool_calls(records) -> list[tuple[str, dict]]:
    """(name, input) for every tool call that was not refused or errored."""
    failed = set()
    for rec in records:
        msg = rec.get("message", {})
        if isinstance(msg, dict):
            for item in msg.get("content", []) or []:
                if (isinstance(item, dict) and item.get("type") == "tool_result"
                        and item.get("is_error")):
                    failed.add(item.get("tool_use_id"))
    calls = []
    for rec in records:
        msg = rec.get("message", {})
        if not isinstance(msg, dict):
            continue
        for item in msg.get("content", []) or []:
            if (isinstance(item, dict) and item.get("type") == "tool_use"
                    and item.get("id") not in failed):
                calls.append((item.get("name", ""), item.get("input") or {}))
    return calls


def has_new_view(calls) -> bool:
    """Since the last addition, was a view taken that was not used before it?"""
    last_add = -1
    for i, (name, inp) in enumerate(calls):
        # Past writes: the file on disk has moved on, so judge them by their own
        # input only (a Write to a test file with test defs counts as an add).
        if addition_kind(name, inp, read_disk=False):
            last_add = i
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
    if has_new_view(tool_calls(records)):
        return 0
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    print(
        f"BLOCKED by new-view-gate: this write adds a {kind} ({path}) and no NEW "
        "view was taken since the last test/phase was added.\n"
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
