#!/usr/bin/env python3
"""Self-test for read-first-gate.py.

Pairs with RCA rca-conclusions-before-evidence-2026-07-28:
  - root cause #1: the read-first contract in `.claude/rules/quick-plan.md` is prose.
    "Nothing executes that. No plan was written; the methodology doc was not opened
    until the founder asked why."
  - root cause #2: the SessionStart hook printed the lesson index. "Titles entered
    context. Nothing required an open... Emission into context was treated as
    delivery."

Hermetic: each case builds a temp repo and a temp transcript.
Run: python3 test_read_first_gate.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

GATE = Path(__file__).resolve().parent / "read-first-gate.py"


def _repo(with_lessons: bool = True) -> Path:
    tmp = Path(tempfile.mkdtemp())
    meth = tmp / "q-system" / "methodology"
    meth.mkdir(parents=True)
    (meth / "anti-hallucination.md").write_text("# how to not make things up\n",
                                                encoding="utf-8")
    if with_lessons:
        lessons = tmp / "q-system" / "lessons"
        lessons.mkdir(parents=True)
        (lessons / "store-the-evidence.md").write_text("---\ntitle: x\n---\nbody\n",
                                                       encoding="utf-8")
    return tmp


def _transcript(tmp: Path, tool_uses: list[tuple[str, str]]) -> Path:
    """A transcript of (tool_name, file_path) pairs, in the shape Claude Code writes."""
    path = tmp / "transcript.jsonl"
    # A real transcript always opens with the user's turn; a session with prompts but
    # zero tool calls is the state the RCA describes, and must be distinguishable from
    # "no transcript at all" (which fails open).
    lines = [json.dumps({"message": {"role": "user", "content": [
        {"type": "text", "text": "trace the client's automation"}]}})]
    for name, fp in tool_uses:
        lines.append(json.dumps({"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": name, "input": {"file_path": fp}}]}}))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def run(repo: Path, transcript: Path, target: str = "notes.md") -> int:
    payload = json.dumps({
        "transcript_path": str(transcript),
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / target)},
    })
    proc = subprocess.run(
        [sys.executable, str(GATE)], input=payload, capture_output=True, text=True,
        env={"CLAUDE_PROJECT_DIR": str(repo), "PATH": "/usr/bin:/bin"}, check=False)
    return proc.returncode


ANTI = "q-system/methodology/anti-hallucination.md"
LESSON = "q-system/lessons/store-the-evidence.md"


def case_first_write_with_no_reads_blocks() -> bool:
    """THE reproducer: the session that produced the RCA. No plan, no methodology."""
    repo = _repo()
    return run(repo, _transcript(repo, [])) == 2


def case_methodology_read_but_no_lesson_blocks() -> bool:
    """Root cause #2: surfacing a lesson title is not delivering the lesson."""
    repo = _repo()
    return run(repo, _transcript(repo, [("Read", str(repo / ANTI))])) == 2


def case_both_read_passes() -> bool:
    repo = _repo()
    t = _transcript(repo, [("Read", str(repo / ANTI)), ("Read", str(repo / LESSON))])
    return run(repo, t) == 0


def case_second_write_passes() -> bool:
    """Only the FIRST write of a session is gated; after that it would be noise."""
    repo = _repo()
    t = _transcript(repo, [("Write", str(repo / "earlier.md"))])
    return run(repo, t) == 0


def case_bash_read_counts() -> bool:
    """Opening the file with cat/grep is opening it. Do not privilege one tool."""
    repo = _repo()
    path = repo / "transcript.jsonl"
    path.write_text("\n".join([
        json.dumps({"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": f"cat {repo / ANTI}"}}]}}),
        json.dumps({"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": f"sed -n 1,20p {repo / LESSON}"}}]}}),
    ]) + "\n", encoding="utf-8")
    return run(repo, path) == 0


def case_no_lessons_dir_only_needs_methodology() -> bool:
    """An instance with no lessons corpus is not asked to read one."""
    repo = _repo(with_lessons=False)
    return run(repo, _transcript(repo, [("Read", str(repo / ANTI))])) == 0


def case_missing_methodology_file_no_ops() -> bool:
    """Never gate on a file that does not exist -- that would be an unopenable block."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-system").mkdir(parents=True)
    return run(tmp, _transcript(tmp, [])) == 0


def case_writing_the_required_file_is_allowed() -> bool:
    """Editing anti-hallucination.md itself must not require having read it first."""
    repo = _repo()
    return run(repo, _transcript(repo, []), target=ANTI) == 0


def case_missing_transcript_no_ops() -> bool:
    """A hook that fails closed on missing input blocks the fix too. Fail open."""
    repo = _repo()
    return run(repo, repo / "does-not-exist.jsonl") == 0


BUS = "q-consult/.q-system/agent-pipeline/bus/2026-07-28/data-ingest.json"

# A morning-pipeline subagent reads instance state, then writes its bus artifact.
# It never opens the methodology doc or a lesson, because that reading belongs to
# the orchestrator that spawned it.
SUBAGENT_READS = [("Read", "q-consult/my-project/current-state.md")]


def case_subagent_bus_write_is_exempt() -> bool:
    """ASK-235: the wedge. Without the GENERATED_TARGETS exemption this returns 2
    and the morning pipeline stops fleet-wide on a gate nobody can see firing."""
    repo = _repo()
    return run(repo, _transcript(repo, SUBAGENT_READS), target=BUS) == 0


def case_non_generated_write_still_blocks() -> bool:
    """The negative half, and the one that gives the case above its meaning: the
    SAME ungrounded transcript writing a NON-generated path must still block. If
    this ever passes, the exemption has become a blanket off-switch."""
    repo = _repo()
    return run(repo, _transcript(repo, SUBAGENT_READS),
               target="q-consult/output/outreach/client-note.md") == 2


CASES = [
    ("first write with no reads blocks", case_first_write_with_no_reads_blocks),
    ("subagent bus write is exempt (ASK-235)", case_subagent_bus_write_is_exempt),
    ("non-generated write still blocks", case_non_generated_write_still_blocks),
    ("methodology read but no lesson blocks", case_methodology_read_but_no_lesson_blocks),
    ("both read passes", case_both_read_passes),
    ("second write of the session passes", case_second_write_passes),
    ("a Bash read counts as a read", case_bash_read_counts),
    ("no lessons dir -> only methodology required", case_no_lessons_dir_only_needs_methodology),
    ("missing methodology file no-ops", case_missing_methodology_file_no_ops),
    ("writing the required file itself is allowed", case_writing_the_required_file_is_allowed),
    ("missing transcript no-ops", case_missing_transcript_no_ops),
]


def main() -> int:
    failures = 0
    for name, fn in CASES:
        try:
            ok = bool(fn())
        except Exception as exc:
            ok = False
            name = f"{name} [raised {type(exc).__name__}: {exc}]"
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
        failures += 0 if ok else 1
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
