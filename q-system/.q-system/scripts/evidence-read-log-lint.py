#!/usr/bin/env python3
"""evidence-read-log-lint: an `ev-` id written into a record must have been OPENED
from the evidence ledger earlier in this session. A citation is a re-read, never a
recall.

WHY (ASK-438): on two consecutive days an agent stated an inference in the grammar of
an observation five times, and the founder caught every one. Three of the five carried
an `ev-` id the session had never opened: the id was recalled from a summary, and the
row it named said something narrower (a shape profile read as a precision figure) or
the opposite (a row recording that a transfer had NOT landed, cited as proof that it
had). Nothing gated it. Detecting bad prose is a heuristic with a false-positive rate;
detecting "you cited a row you never opened" is set membership on data the session
already writes: its own transcript.

WHAT IT DOES. PostToolUse on Write|Edit|MultiEdit. For a file under `canonical/`,
`.prd-os/prds/` or `output/`, it computes the `ev-` ids the edit NEWLY introduced
(present after, absent before; the "before" comes from the tool's own
`tool_response.originalFile`, reconstructed from old/new strings when that is missing).
For each such id it requires an earlier tool RESULT in the session transcript
(`transcript_path`, plus the session's `subagents/*.jsonl`) that both
  - came from a LEDGER READ: the tool call's input names `evidence.jsonl`,
    `evidence_ledger` or `evidence-citation-lint` (a Read of the ledger, a grep of it,
    `evidence_ledger.py show|list|check`), and
  - contains that exact id.
Results of Write/Edit/MultiEdit/NotebookEdit never count: an Edit's result echoes the
text just written, which would let every citation launder itself.

MODE. `KIPI_EVIDENCE_READ_LOG_MODE`:
  advisory (default)  exit 0, stderr names each id and the command that opens it,
                      and a row is logged
  blocking            exit 2, the same message
ADVISORY BY DEFAULT, deliberately (PR #433 round 4). Four review rounds each found
one more real producer whose output the id extraction rejected, and the replay
below was taken before the row-shape rule existed, so it no longer measures the
code that ships. Flip to blocking only after the calibration log below shows the
false-block rate on real sessions. The ORIGINAL reasoning, kept for that decision: The last citation lint shipped blocking
and had to be demoted because ~30 findings were nearly all false. Before this one was
wired, it was replayed over every session transcript on the build machine
(2026-09-23, read-only; the replay script and its output are in the ASK-438 PR body):
10 in-scope writes introduced an ev- id, 3 would have fired, and all 3 were the exact
shape this gate exists for, an id copied out of a summary file (a decisions log, a
work-state note) that the session never opened in the ledger. Zero of 3 were false
positives. The same replay with "any tool result counts" fired on 0 of 10, which is
why the ledger-read requirement below is the rule and not a refinement.
Both modes append a row to `q-system/output/evidence-read-log-lint.jsonl` when they
fire. A turn with nothing to say writes nothing.

HONEST BOUNDARY (what this does NOT catch, stated so it is not read as coverage):
  - A number written with no citation at all. There is no id to check.
  - A conclusion drawn wider than the field it rests on ("not admin as user A" written
    as "not admin"). The id was opened; the reading was wrong.
  - Opening a row does not prove reading it carefully. This removes "I cited from
    memory", not "I misread it". Opening the row and ignoring its content passes.
  - A `list` small enough to stay in the transcript opens every row it printed; a
    large one is persisted (next bullet). `show <id>` is the precise verb and the
    one the refusal names.
  - A large ledger read is PERSISTED out of the transcript: the harness replaces a
    result over roughly 30 KB with a `<persisted-output>` pointer to a
    `tool-results/` file plus a 2 KB preview (a 255-row `list` is 210 KB). The
    pointer path is remembered as ledger output, and a later tool call that names
    THAT path counts as a ledger read (PR #433 review). A read of any other
    `tool-results/` file does not.
  - A Bash call that names the ledger and ALSO echoes an arbitrary id (`echo ev-x;
    cat evidence.jsonl`) counts as a read. This is a gate on honest recall, not on an
    adversary forging provenance.
  - Every subagent transcript of the session counts, so a sibling subagent's read
    satisfies the gate for another subagent. Hooks do not say which agent is writing.
  - No transcript, or an unreadable one, passes (exit 0 with a note): the gate cannot
    observe the session, and a gate red on what it cannot see gets switched off.
  - The id format is `ev-` plus 10 lowercase hex characters, the only shape
    `evidence_ledger.make_claim_id` produces.

Bypass per file: put `evidence-read-log-skip` in the file.
Contract: hook JSON on stdin. exit 0 = pass, exit 2 = block. stdlib only.
Self-test: `python3 test_evidence_read_log_lint.py`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SKIP_MARKER = "evidence-read-log-skip"
MODE_ENV = "KIPI_EVIDENCE_READ_LOG_MODE"
CALIBRATION_LOG = "q-system/output/evidence-read-log-lint.jsonl"

ID_RE = re.compile(r"\bev-[0-9a-f]{10}\b")

# What a ROW looks like in ledger output: a JSON `"claim_id": "ev-..."` (a Read or
# grep of evidence.jsonl, `show`, `list --json`), or a `list` line that STARTS with
# the id. A bare id anywhere else is not a row. PR #433 round 3: a failed
# `show ev-x` prints "no such row: ev-x", so the refusal's own remedy for a
# nonexistent id counted as opening it and laundered the citation.
# Every shape a real producer prints for a row that EXISTS (PR #433 round 4 found
# two this list missed; the test drives the real `add`):
#   "claim_id": "ev-x"   Read/grep of evidence.jsonl, `show`, `list --json`
#   ev-x  <claim>        `list`
#   ev-x                 `add`, which prints only the new id
#   === ev-x ===         an instance's evidence-citation-lint.py --show
# Its miss line, "ev-x: NOT IN LEDGER", matches none of them on purpose.
ROW_ID_RE = re.compile(
    r'"claim_id"\s*:\s*"(ev-[0-9a-f]{10})"'
    r'|^[ \t]*(?:\d+[\t\u2192 ]+)?(ev-[0-9a-f]{10})(?:  |[ \t]*$)'
    r'|^=== (ev-[0-9a-f]{10}) ===[ \t]*$',
    re.MULTILINE)


def row_ids_in(text) -> set[str]:
    if not isinstance(text, str):
        return set()
    return {next(g for g in m if g) for m in ROW_ID_RE.findall(text)}

# The three trees where a citation becomes a record someone else acts on. Matched as
# path SEGMENTS so `my-output-notes/` or `canonicalize.py` never fall in scope.
SCOPE_SEGMENTS = ("/canonical/", "/.prd-os/prds/", "/output/")

WRITER_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
# A delegated agent's RESULT is its summary, not the ledger, even when the prompt
# named the ledger: that is exactly the recall-from-a-summary this gate exists for.
SUMMARY_TOOLS = frozenset({"Task", "Agent"})

# What makes a tool call a read of the ledger. Matched against the json of the call's
# INPUT, so a Read's file_path, a Grep's path and a Bash command all qualify.
LEDGER_MARKERS = ("evidence.jsonl", "evidence_ledger", "evidence-citation-lint")

# The path a persisted-output pointer names. Only a pointer found in a LEDGER read's
# result is remembered, so this never widens to "any tool-results file".
PERSISTED_RE = re.compile(r"[^\s<>\"'`]*tool-results/[^\s<>\"'`]+")


def ids_in(text) -> set[str]:
    return set(ID_RE.findall(text or "")) if isinstance(text, str) else set()


def in_scope(fp: str) -> bool:
    p = "/" + fp.replace(os.sep, "/").lstrip("/")
    return any(seg in p for seg in SCOPE_SEGMENTS)


# ----------------------------------------------------------------- before and after

def _undo_edit(body: str, old: str, new: str, replace_all: bool) -> str:
    if not new:
        return body  # a pure deletion introduces nothing; before >= after
    if replace_all:
        return body.replace(new, old)
    return body.replace(new, old, 1)


def before_and_after(payload: dict, disk_body: str | None) -> tuple[str, str]:
    """(before, after) text of the file for this one tool call.

    The tool's own `originalFile` is authoritative for `before`. Reconstruction from
    old/new strings is the fallback, because a hook payload is a contract we observe,
    not one we own.
    """
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    tr = payload.get("tool_response")
    tr = tr if isinstance(tr, dict) else {}

    if tool == "Write":
        after = ti.get("content") if isinstance(ti.get("content"), str) else (disk_body or "")
    else:
        after = disk_body if disk_body is not None else ""

    orig = tr.get("originalFile")
    if isinstance(orig, str):
        return orig, after
    if tool == "Write":
        if tr.get("type") == "update":
            # An overwrite whose prior body the payload did not carry: the ids that
            # were already there are unknowable, so claim nothing new rather than
            # false-block every pre-existing citation (round 3 minor). Fails open,
            # which is the NOT_SECURITY class this lint is filed under.
            return after, after
        # create (originalFile null) or a payload without it: everything is new.
        return "", after
    if tool == "Edit":
        return _undo_edit(after, ti.get("old_string") or "", ti.get("new_string") or "",
                          bool(ti.get("replace_all"))), after
    if tool == "MultiEdit":
        before = after
        for e in reversed(ti.get("edits") or []):
            if isinstance(e, dict):
                before = _undo_edit(before, e.get("old_string") or "",
                                    e.get("new_string") or "", bool(e.get("replace_all")))
        return before, after
    return after, after  # unknown writer: claim nothing new rather than guess


def introduced(before: str, after: str) -> list[str]:
    return sorted(ids_in(after) - ids_in(before))


# ----------------------------------------------------------------- the transcript

def transcript_files(transcript_path: str) -> list[Path]:
    """The session transcript plus its subagent sidechains, which live beside it at
    `<dir>/<session-id>/subagents/*.jsonl` (ASK-256: a gate that reads only the parent
    transcript blocked a subagent that had done the read)."""
    if not transcript_path:
        return []
    given = Path(transcript_path)
    main = given
    if given.parent.name == "subagents":
        # Handed a sidechain: the parent session sits at <dir>/<session>.jsonl, and a
        # read the parent did before delegating counts for the subagent too.
        session_dir = given.parent.parent
        main = session_dir.parent / f"{session_dir.name}.jsonl"
    out = [main] if main.is_file() else []
    sub = main.parent / main.stem / "subagents"
    if sub.is_dir():
        out.extend(sorted(sub.glob("*.jsonl")))
    if given.is_file() and given not in out:
        out.append(given)
    return out


def _records(path: Path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except OSError:
        return


def _blocks(rec: dict) -> list:
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    return content if isinstance(content, list) else []


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c
                         if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def opened_ids(records, ledger_only: bool = True) -> set[str]:
    """Every ev- id that appeared in the RESULT of a ledger read, in record order.

    `ledger_only=False` exists for the calibration replay only: it counts any tool
    result, which is the looser reading the replay compares against.
    """
    calls: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    persisted: set[str] = set()  # ledger output moved out of the transcript
    for rec in records:
        for b in _blocks(rec):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                try:
                    inp = json.dumps(b.get("input"), ensure_ascii=False)
                except Exception:
                    inp = ""
                calls[b.get("id") or ""] = (b.get("name") or "", inp)
            elif b.get("type") == "tool_result":
                name, inp = calls.get(b.get("tool_use_id") or "", ("", ""))
                if name in WRITER_TOOLS or name in SUMMARY_TOOLS:
                    continue  # an Edit echoes what it wrote; a Task returns a summary
                text = _result_text(b)
                is_ledger = (any(m in inp for m in LEDGER_MARKERS)
                             or any(p in inp for p in persisted))
                if ledger_only and not is_ledger:
                    continue
                if is_ledger:
                    persisted |= set(PERSISTED_RE.findall(text))
                seen |= row_ids_in(text) if ledger_only else ids_in(text)
    return seen


def session_opened_ids(transcript_path: str) -> set[str] | None:
    """None when the session cannot be observed at all."""
    files = transcript_files(transcript_path)
    if not files:
        return None
    seen: set[str] = set()
    for f in files:
        seen |= opened_ids(_records(f))
    return seen


# ----------------------------------------------------------------- the decision

def unopened(payload: dict, disk_body: str | None) -> tuple[list[str], bool]:
    """(ids cited without being opened, observable)."""
    before, after = before_and_after(payload, disk_body)
    new = introduced(before, after)
    if not new:
        return [], True
    opened = session_opened_ids(payload.get("transcript_path") or "")
    if opened is None:
        return [], False
    return [i for i in new if i not in opened], True


def _log(root: str, fp: str, ids: list[str], mode: str, transcript: str) -> None:
    try:
        p = Path(root) / CALIBRATION_LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event": "advisory" if mode == "advisory" else "blocked",
                "file": fp, "ids": ids,
                "session": Path(transcript).stem if transcript else None,
            }) + "\n")
    except OSError:
        pass  # the log is calibration, never a reason to fail the write


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") not in WRITER_TOOLS:
        return 0
    ti = payload.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("notebook_path") or ""
    if not fp:
        return 0
    path = Path(fp).resolve()
    fp = str(path)
    if not in_scope(fp):
        return 0
    try:
        disk_body = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        disk_body = None
    if disk_body is not None and SKIP_MARKER in disk_body:
        return 0

    bad, observable = unopened(payload, disk_body)
    if not observable:
        sys.stderr.write("evidence-read-log-lint: no session transcript to read; "
                         "citation not checked.\n")
        return 0
    if not bad:
        return 0

    mode = os.environ.get(MODE_ENV, "advisory").strip().lower()
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    _log(root, fp, bad, mode, payload.get("transcript_path") or "")
    ids = " ".join(bad)
    sys.stderr.write(
        f"EVIDENCE READ-LOG LINT ({'advisory' if mode == 'advisory' else 'blocked'}): "
        f"{Path(fp).name} now cites {ids}, and nothing this session opened "
        f"{'that row' if len(bad) == 1 else 'those rows'} from the ledger.\n"
        "  A citation is a re-read at write time, never a recall (ASK-438: three of five\n"
        "  wrong claims cited a row that said something narrower, or the opposite).\n"
        f"  Open it first:  python3 q-system/.q-system/scripts/evidence_ledger.py show {ids}\n"
        "  Then re-check that the row says what your sentence says, and re-write.\n"
        f"  Deliberate exception: add `{SKIP_MARKER}` to the file.\n")
    # Only the explicit "blocking" blocks while the gate is being calibrated.
    return 2 if mode == "blocking" else 0


if __name__ == "__main__":
    sys.exit(main())
