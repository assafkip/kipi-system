#!/usr/bin/env python3
"""client-output-evidence-gate: a number in a client-facing draft must trace to a
recorded verification.

WHY (RCA rca-conclusions-before-evidence-2026-07-28, root cause #6): a client email
was drafted carrying specific counts and a structural claim about the client's
workflow. voice-lint, format-lint, audhd-lint and headline-lint all fire on that file
and all would have passed it -- they judge style. Nothing checked whether the numbers
were ever measured. The highest-consequence output had the weakest grounding check.
One of the six reversed conclusions in that session had already reached such a draft.

Pairs with `evidence_ledger.py`: every numeric literal (2+ significant digits) and
every quoted span (4+ words) in a file under `output/outreach/` must appear in a row
of `<instance-root>/canonical/evidence.jsonl`.

Scope: PostToolUse(Write|Edit|MultiEdit) on paths containing `output/outreach/`.
Everything else exits 0 immediately (token discipline: no logic on out-of-scope edits).

Escape hatches, in order of preference:
  1. Verify it -- `evidence_ledger.py add --claim ... --command ... --result ...`.
  2. Label it -- put `{{UNVERIFIED}}` / `{{UNVALIDATED}}` / `{{NEEDS_PROOF}}` on the
     line. The line is then exempt, because a labelled estimate is honest.
  3. Bypass the file -- `evidence-gate-skip`. Last resort; it turns the gate off.

HONEST BOUNDARY: this checks that a number APPEARS in a verified row, not that the
row's claim actually supports the sentence the number sits in. Two unrelated facts
that happen to share a value will pass. It also cannot see a false claim carrying no
numbers and no quotes -- prose assertions stay ungated here; the Stop-hook grounding
guard is what covers those.

Three further holes, all declared rather than silent (ASK-232 / ASK-233):
  - ISO dates and bare years (1900-2100) are not treated as measurements. A real
    count that happens to be a 4-digit year ("2026 orders shipped") passes unbacked.
  - An instance with NO `canonical/evidence.jsonl` is "not adopted yet" and this
    gate stands down entirely. The file's existence is the opt-in switch; one row
    turns enforcement on at full strength.
  - Therefore this gate proves nothing in an instance that never started a ledger.
    That is deliberate: the previous behaviour blocked every number in the first
    draft an instance ever wrote, which taught people to reach for the bypass.

Contract: reads hook JSON on stdin. exit 0 = pass, exit 2 = block. stdlib only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import evidence_ledger as EL
except Exception:  # an instance without the ledger module must not be blocked
    sys.exit(0)

SCOPE = "output/outreach/"
SKIP_MARKER = "evidence-gate-skip"
UNVERIFIED_MARKERS = ("{{UNVERIFIED}}", "{{UNVALIDATED}}", "{{NEEDS_PROOF}}")


def gated_text(body: str) -> str:
    """The body minus lines that already declare themselves unverified."""
    return "\n".join(line for line in body.splitlines()
                     if not any(m in line for m in UNVERIFIED_MARKERS))


def evaluate(repo, body: str) -> tuple[list[str], list[str]]:
    """(unbacked numbers, unbacked quotes). Empty pair = the draft is traceable."""
    if SKIP_MARKER in body:
        return [], []
    text = gated_text(body)
    return EL.resolve_numbers(repo, text), EL.resolve_spans(repo, text)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("path") or ""
    if not fp:
        return 0
    if SCOPE not in fp.replace("\\", "/"):
        return 0  # out of scope, fast exit

    try:
        body = Path(fp).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0

    repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    numbers, quotes = evaluate(repo, body)
    if not numbers and not quotes:
        return 0

    out = [f"CLIENT OUTPUT GATE (blocked): {fp}",
           "  This draft goes to a client. These do not trace to "
           "canonical/evidence.jsonl:"]
    out += [f"    - number {n}" for n in numbers[:20]]
    out += [f'    - quote "{q}"' for q in quotes[:10]]
    out += [
        "",
        "  Fix, best first:",
        "    1. Verify it, then record it:",
        "       python3 q-system/.q-system/scripts/evidence_ledger.py add \\",
        "         --claim '<what is true>' --source '<where>' \\",
        "         --command '<what you ran>' --result '<what it printed>'",
        "    2. Or label the line {{UNVERIFIED}} and let the client see it is an "
        "estimate.",
        f"    3. Or bypass this file with the marker `{SKIP_MARKER}`.",
        "",
        "  Scar 2026-07-28: six conclusions reversed in one session; one reached a "
        "client email draft before anyone recomputed it. Style gates passed that "
        "draft. This is the check that did not exist.",
    ]
    sys.stderr.write("\n".join(out) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
