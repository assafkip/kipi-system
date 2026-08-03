#!/usr/bin/env python3
"""blocked-claim-evidence-lint: a report saying "this is blocked" must carry the
command that settles it, or say out loud that it is an inference.

WHY (ASK-317, RCA rca-inherited-claim-treated-as-verified-2026-08-02): six false
"this is blocked" reports in one session. Each was fluent, specific, wrong, and wrong
in the direction that transferred work to the founder or stopped work entirely. Cost:
a correct, fully reviewed PR sat unmerged, and two non-existent decisions were put on
the founder's plate. Every one of them was settled later by a ten-second command.

THE HOLE THIS FILLS: `evidence-ledger.md` already requires a stored command and result
for a claim, and its four gates fire on client output, handoffs, and first writes.
NONE fire on an agent-to-agent or agent-to-founder status report -- the exact channel
all six travelled. The rule existed; its enforcement had a hole this shape.

THE THREE SUB-SHAPES, each with its own remediation (generic stderr teaches nothing):

  1. rollup-as-config          a computed roll-up read as a policy statement.
                               `mergeStateStatus: BLOCKED` is derived from several
                               # human-handoff-audit: definitional -- this quotes a MISREADING being
                               # corrected, not a handoff this code performs.
                               inputs; it was read as "a human must approve".
  2. my-denial-as-object-property   a refusal aimed at MY tool layer reported as a
                               property of the object. "I can't" became "it can't".
                               The command had never been run.
  3. lookup-as-runtime-fact    one lookup's result reported as a runtime fact. One
                               `ls` returned nothing, so "the file does not exist".
                               Mirror image: references existed, so "the scripts are
                               LIVE" -- neither had ever been executed.

MODE (this ships ADVISORY on purpose). `KIPI_BLOCKED_CLAIM_LINT_MODE`:
  advisory (default)  exit 0, findings appended to output/blocked-claim-lint.jsonl
  blocking            exit 2, per-sub-shape remediation on stderr
A Stop hook that fires noisily trains the operator to skim, which costs the real alert
later. So the false-positive rate gets measured on real session output from the
advisory log FIRST, and `blocking` is turned on against that evidence, not against a
hunch. The promotion is a one-word env change, not a rewrite.

HONEST BOUNDARY (stated so this is not theater):
  - It checks that a claim DECLARES its evidence, not that the evidence is true. A
    fenced block holding two commands and no real output passes.
  - Evidence must FOLLOW the claim within LOOKAHEAD lines, or be inline provenance.
    Showing the command first and concluding after is not recognised; use
    `[verified: <cmd>]` on the claim line for that shape.
  - A blocking claim phrased with none of the trigger words passes untouched. This is
    a keyword gate over a prose channel, and prose has infinite synonyms.
  - Only fenced blocks count as command evidence. A command in backticks inside prose
    does not, deliberately: claim #5 ("`gh pr merge` is denied") quoted the command it
    had never run.

Contract: reads {transcript_path, stop_hook_active} JSON on stdin (Claude Code Stop
hook). exit 0 = pass, exit 2 = block. Per-answer bypass: put `blocked-claim-skip` in
the answer. stdlib only.
Self-test: `python3 test_blocked_claim_evidence_lint.py`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

SKIP_MARKER = "blocked-claim-skip"
MODE = os.environ.get("KIPI_BLOCKED_CLAIM_LINT_MODE", "advisory").strip().lower()
CALIBRATION_LOG = "q-system/output/blocked-claim-lint.jsonl"

# How far AFTER a claim its settling fence may start. Two lines is the natural shape
# (claim, blank, fence); four leaves slack for a lead-in line without letting an
# unrelated block three claims down launder this one.
LOOKAHEAD = 4

# A fenced block is command evidence only if its first line is a command AND at least
# one more non-empty line follows it -- the output. A command with no output settles
# nothing; that is the "I ran it, trust me" shape.
COMMAND_VERBS = (
    "gh", "git", "ls", "cat", "find", "grep", "rg", "sed", "awk", "head", "tail",
    "wc", "stat", "test", "bash", "sh", "zsh", "python3", "python", "node", "npm",
    "make", "curl", "jq", "launchctl", "docker", "psql", "sqlite3", "open", "echo",
    "printf", "diff", "tree", "ps", "which", "env",
)
_CMD_RE = re.compile(
    r"^(?:[$%>]\s+)?(?:" + "|".join(re.escape(v) for v in COMMAND_VERBS) + r")(?:\s|$)")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")
_VERIFIED_RE = re.compile(r"\[verified:")

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # the ONE provenance table, shared with handoff-provenance-lint
    import provenance_vocabulary as PV
except Exception:  # pragma: no cover - an instance mid-kipi-update must not break
    PV = None
    _FALLBACK_PROV_RE = re.compile(
        r"\{\{UNVERIFIED\}\}|\{\{UNVALIDATED\}\}|\{\{NEEDS_PROOF\}\}"
        r"|\bev-[0-9a-f]{10}\b")


class Pattern(NamedTuple):
    pattern_id: str
    why: str
    triggers: tuple
    settles: str


class Claim(NamedTuple):
    """One state claim: a SENTENCE, located by its line and its place within it."""
    line: int
    ordinal: int  # sentence index within the line; two claims on a line are two claims
    pattern: Pattern
    text: str

    @property
    def key(self) -> tuple[int, int]:
        """Identity AND reading order: max() over keys is the nearest claim above."""
        return (self.line, self.ordinal)


class Finding(NamedTuple):
    pattern: str
    line: int
    text: str
    why: str
    settles: str


PATTERNS = (
    Pattern(
        pattern_id="rollup-as-config",
        why=("a computed roll-up read as a policy statement. `mergeStateStatus: "
             "BLOCKED` is derived from several inputs; it is not a record of who "
             "must approve."),
        triggers=(
            re.compile(r"\bblocked\b", re.I),
            re.compile(r"\bblocks\s+(?:the|this|our|merge|it)\b", re.I),
            re.compile(r"\bpending\s+\w*\s*approval\b", re.I),
            re.compile(r"\brequires?\s+(?:\w+\s+){0,2}approval\b", re.I),
            re.compile(r"\bwaiting\s+on\s+(?:review|approval|a\s+reviewer)\b", re.I),
            re.compile(r"\bmergeStateStatus\b", re.I),
            re.compile(r"\bout\s+of\s+credits\b", re.I),
        ),
        settles=(
            "    branch protection is CONFIG; mergeStateStatus is a ROLL-UP. Read the\n"
            "    config, not the roll-up:\n"
            "gh api repos/<owner>/<repo>/branches/<base>/protection "
            "--jq .required_pull_request_reviews\n"
            "gh pr view <n> --json mergeStateStatus,mergeable,statusCheckRollup,reviewDecision\n"
            "    Scar: `required_pull_request_reviews` was null. No human approval was\n"
            "    ever configured, and a reviewed PR sat unmerged on that claim."
        ),
    ),
    Pattern(
        pattern_id="my-denial-as-object-property",
        why=("a refusal aimed at MY tool layer reported as a property of the object. "
             "\"I can't\" is a fact about this session; \"it can't\" is a claim about "
             "the world."),
        triggers=(
            re.compile(r"\bdenied\b", re.I),
            re.compile(r"\bnot\s+permitted\b", re.I),
            re.compile(r"\bno\s+permission\b", re.I),
            re.compile(r"\bpermission\s+(?:was\s+)?refused\b", re.I),
            re.compile(r"\b(?:cannot|can'?t)\s+be\s+(?:run|invoked|called|used|"
                       r"executed)\b", re.I),
            re.compile(r"\bis\s+(?:un)?available\s+to\s+the\s+tool\s+layer\b", re.I),
            # The repo's OWN status wording, and it was invisible to the first cut
            # (PR #79 review, codex). The autonomous-board prompt tells agents to
            # report when "Linear is unreachable" -- a stop claim about an external
            # service, which is this sub-shape exactly: one failed call at my layer
            # reported as a property of the service.
            re.compile(r"\b(?:is|are|was|were)\s+(?:unreachable|unavailable|down|"
                       r"offline|inaccessible)\b", re.I),
            re.compile(r"\bthe\s+tool\s+layer\s+(?:refuses|forbids|blocks)\b", re.I),
        ),
        settles=(
            "    run it ONCE. The command's own error text names the fix, and a\n"
            "    refusal you never triggered is not a refusal:\n"
            "gh pr merge <n> --squash --admin      # or whatever you believe is denied\n"
            "    Then report what the tool said, verbatim.\n"
            "    Scar: `gh pr merge` was reported denied to the tool layer. It had\n"
            "    never been run, and its error text names `--admin`."
        ),
    ),
    Pattern(
        pattern_id="lookup-as-runtime-fact",
        why=("one lookup's result reported as a runtime fact. Absence at one path is "
             "not absence, and the existence of references is not a run."),
        triggers=(
            re.compile(r"\bdoes\s+not\s+exist\b", re.I),
            re.compile(r"\bdoesn'?t\s+exist\b", re.I),
            re.compile(r"\bno\s+such\s+file\b", re.I),
            re.compile(r"\bwas\s+never\s+written\b", re.I),
            # `[^;\n]` and not `[^.;\n]`: the subject of this claim is usually a
            # FILENAME, and a filename carries a dot. Excluding `.` here is what
            # made the first cut miss reproducer claims 3 and 4 verbatim
            # ("no `degraded.state` was written"). Sentence splitting already
            # bounds the span, so the dot costs nothing.
            re.compile(r"\bno\s+\S[^;\n]{0,40}?\s+was\s+written\b", re.I),
            re.compile(r"\bnever\s+(?:ran|executed|fired)\b", re.I),
            re.compile(r"\b(?:is|are)\s+missing\b", re.I),
            re.compile(r"\b(?:is|are)\s+(?:live|running|active)\b", re.I),
            re.compile(r"\bnothing\s+was\s+(?:written|produced|emitted)\b", re.I),
        ),
        settles=(
            "    one path is not every path, and a reference is not a run. Settle both\n"
            "    directions before reporting:\n"
            "find <root> -name '<file>' -print -exec cat {} +\n"
            "grep -rn '<name>' <root>          # references exist...\n"
            "    ...now show the run: the invocation itself, or the run-log line that\n"
            "    proves it executed.\n"
            "    Scar: `degraded.state` was reported unwritten. It existed at the\n"
            "    per-engine path, held `1`, and was timestamped. Separately, ten\n"
            "    scripts were reported LIVE on the strength of references alone;\n"
            "    none had ever been executed."
        ),
    ),
)


def _has_provenance(line: str) -> bool:
    """A line that labels itself is doing the right thing, not a lesser thing."""
    if _VERIFIED_RE.search(line):
        return True
    if PV is not None:
        return PV.has_provenance(line)
    return bool(_FALLBACK_PROV_RE.search(line))


def _fence_spans(lines: list[str]) -> list[tuple[int, int]]:
    """(start_index, end_index) for every fenced block, end inclusive."""
    spans, open_at = [], None
    for i, line in enumerate(lines):
        if not _FENCE_RE.match(line):
            continue
        if open_at is None:
            open_at = i
        else:
            spans.append((open_at, i))
            open_at = None
    if open_at is not None:  # unterminated fence: treat the rest as its interior
        spans.append((open_at, len(lines) - 1))
    return spans


def _settling_fences(lines: list[str], spans: list[tuple[int, int]]) -> set[int]:
    """Start indices of fences that hold a command AND at least one output line."""
    out = set()
    for start, end in spans:
        inner = [ln for ln in lines[start + 1:end] if ln.strip()]
        if len(inner) >= 2 and _CMD_RE.match(inner[0].strip()):
            out.add(start)
    return out


def _claims(lines: list[str], interior: set[int]) -> list[Claim]:
    """Every unlabelled state claim, in reading order.

    A claim is a SENTENCE, not a line. Scar (PR #79 review round 2, codex): round 1
    bound each fence to the nearest claim LINE, and this loop kept only the first
    claim per line, so a line carrying two claims collapsed to one entry and a single
    fence cleared both. The laundering just moved from between lines to within one.
    Sentences are the unit the trigger regexes already match on, so they are the unit
    a fence has to answer.
    """
    claims = []
    for i, line in enumerate(lines):
        if i in interior or not line.strip() or _has_provenance(line):
            continue
        for ordinal, sentence in enumerate(_SENTENCE_SPLIT_RE.split(line)):
            sentence = sentence.strip()
            if not sentence or sentence.endswith("?"):
                continue  # a question is an open loop, not a claim
            hit = _first_match(sentence)
            if hit is not None:
                claims.append(Claim(i, ordinal, hit, sentence))
    return claims


def _settled_claims(claims: list[Claim], settling: set[int]) -> set[tuple[int, int]]:
    """The (line, ordinal) keys a fence settles. ONE fence settles exactly ONE claim.

    Evidence must FOLLOW the claim: a fence above it belongs to an earlier claim.
    Scar (PR #79 review, codex): the first cut cleared EVERY claim within LOOKAHEAD
    lines of any settling fence, so output answering one claim silently laundered an
    unrelated false claim sitting next to it -- the exact laundering this gate exists
    to stop. A fence is evidence for the nearest claim it follows, and it is spent
    once, so two adjacent claims need two fences.

    "Nearest" is by (line, ordinal), so on a two-claim line the fence below answers
    the LAST sentence, and the earlier one still needs its own command.
    """
    settled: set[tuple[int, int]] = set()
    for fence in sorted(settling):
        owners = [c.key for c in claims
                  if c.line < fence <= c.line + LOOKAHEAD and c.key not in settled]
        if owners:
            settled.add(max(owners))  # the nearest claim above this fence
    return settled


def evaluate(final_text: str) -> list[Finding]:
    """Every unsettled blocked/denied/unavailable/non-existent claim in the answer."""
    if not final_text or SKIP_MARKER in final_text:
        return []
    lines = final_text.splitlines()
    spans = _fence_spans(lines)
    interior = {i for start, end in spans for i in range(start, end + 1)}
    claims = _claims(lines, interior)
    settled = _settled_claims(claims, _settling_fences(lines, spans))
    # Report the SENTENCE, not the whole line: on a two-claim line the operator has
    # to see which half is still unsettled, not re-read the line and guess.
    return [Finding(c.pattern.pattern_id, c.line + 1, c.text,
                    c.pattern.why, c.pattern.settles)
            for c in claims if c.key not in settled]


def _first_match(sentence: str):
    for pattern in PATTERNS:
        if any(trigger.search(sentence) for trigger in pattern.triggers):
            return pattern
    return None


# --- Stop-hook plumbing ------------------------------------------------------
def _final_assistant_text(records: list[dict]) -> str:
    text = ""
    for rec in records:
        msg = rec.get("message", {})
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        parts = [i.get("text", "") for i in msg.get("content", [])
                 if isinstance(i, dict) and i.get("type") == "text"]
        if parts:
            text = "\n".join(parts)  # keep the LAST assistant text block
    return text


def _load_records(transcript_path: str) -> list[dict]:
    path = Path(transcript_path) if transcript_path else None
    if not path or not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _log_calibration(findings: list[Finding]) -> None:
    """Advisory-mode output. This log IS the calibration evidence the promotion to
    blocking has to be argued from, so a failure to write it must be visible, not
    silently swallowed -- but it must never take down the turn either."""
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    target = root / CALIBRATION_LOG
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": MODE,
        "findings": [{"pattern": f.pattern, "line": f.line, "text": f.text[:300]}
                     for f in findings],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except Exception as exc:
        sys.stderr.write(f"blocked-claim-evidence-lint: calibration log unwritable "
                         f"({type(exc).__name__}: {exc})\n")


def _report(findings: list[Finding]) -> str:
    blocks = []
    for pattern_id in dict.fromkeys(f.pattern for f in findings):
        group = [f for f in findings if f.pattern == pattern_id]
        listed = "\n".join(f"    line {f.line}: {f.text[:120]}" for f in group[:8])
        blocks.append(f"  [{pattern_id}] {group[0].why}\n{listed}\n\n"
                      f"{group[0].settles}")
    return "\n\n".join(blocks)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("stop_hook_active"):  # loop guard: block at most once per cycle
        return 0
    records = _load_records(payload.get("transcript_path", ""))
    if not records:
        return 0
    findings = evaluate(_final_assistant_text(records))
    if not findings:
        return 0

    if MODE != "blocking":
        _log_calibration(findings)
        counts = ", ".join(
            f"{p} x{sum(1 for f in findings if f.pattern == p)}"
            for p in dict.fromkeys(f.pattern for f in findings))
        print(f"blocked-claim-evidence-lint (advisory): {len(findings)} unsettled "
              f"state claim(s) [{counts}] -> {CALIBRATION_LOG}")
        return 0

    sys.stderr.write(
        "BLOCKED-CLAIM EVIDENCE (blocked): your answer asserts a blocked, denied, "
        "unavailable, or non-existent state with no command output next to it.\n\n"
        + _report(findings) + "\n\n"
        "  Attach the command AND its output in a fenced block under the claim, or "
        "label the line as an inference ({{UNVERIFIED}} / provenance: inferred). "
        "Labelling is the correct move, not a lesser one -- the defect is prose that "
        "hides which kind of statement it is making.\n"
        "  Scar 2026-08-02: six claims of this exact shape in one session. Every one "
        "was settled later by a ten-second command. A reviewed PR sat unmerged and "
        "two non-existent decisions reached the founder.\n"
        f"  Deliberate exception: put `{SKIP_MARKER}` in the answer.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
