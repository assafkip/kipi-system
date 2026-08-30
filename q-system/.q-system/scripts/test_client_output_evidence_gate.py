#!/usr/bin/env python3
"""Self-test for client-output-evidence-gate.py.

Pairs with RCA rca-conclusions-before-evidence-2026-07-28, root cause #6: "A client
email was drafted containing specific counts and a structural claim about the client's
workflow. Style gates would have fired on voice and format. Nothing checks that a
number in a client-facing draft traces to a recorded verification. The
highest-consequence output has the weakest grounding check."

Hermetic: each case builds its own temp repo with its own ledger.
Run: python3 test_client_output_evidence_gate.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence_ledger as EL  # noqa: E402

GATE = Path(__file__).resolve().parent / "client-output-evidence-gate.py"


def _repo_with_ledger() -> Path:
    """A temp instance carrying one verified fact: the export has 1177 rows."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-thing" / "canonical").mkdir(parents=True)
    # REGISTERED, because this fixture WRITES via EL.add and the write path refuses
    # an unregistered repo (an unattended run must not append evidence to the wrong
    # tree). The env var is picked up by the gate subprocess too. Reads do not need
    # this; only the write does.
    _registry = tmp / "registry.json"
    _registry.write_text(json.dumps({"instances": [
        {"name": "tmp-instance", "path": str(tmp), "instance_q_dir": "q-thing"}]}),
        encoding="utf-8")
    os.environ["KIPI_EVIDENCE_REGISTRY"] = str(_registry)
    EL.add(tmp, claim="Brightspeed export has 1177 rows", source="xlsx",
           command="openpyxl len(rows)", result="1177 rows, 332 hand-typed dates")
    return tmp


def run(repo: Path, rel_path: str, body: str) -> int:
    """Write the file, then feed the gate the hook payload Claude Code would."""
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    proc = subprocess.run(
        [sys.executable, str(GATE)], input=payload, capture_output=True,
        text=True, env={"CLAUDE_PROJECT_DIR": str(repo), "PATH": "/usr/bin:/bin"},
        check=False)
    return proc.returncode


OUTREACH = "q-thing/output/outreach/draft-email.md"


def case_unsourced_number_blocks() -> bool:
    """THE reproducer: a count nobody measured, in a client-facing draft."""
    return run(_repo_with_ledger(), OUTREACH,
               "Hi Zach,\n\nWe found 4,200 duplicate rows this week.\n") == 2


def case_ledger_backed_number_passes() -> bool:
    return run(_repo_with_ledger(), OUTREACH,
               "Hi Zach,\n\nThe export holds 1,177 rows.\n") == 0


def case_non_outreach_file_is_out_of_scope() -> bool:
    """Scope must match the gate. Internal notes are not client-facing."""
    return run(_repo_with_ledger(), "q-thing/memory/notes.md",
               "We found 4,200 duplicate rows.\n") == 0


def case_unverified_marker_exempts_its_line() -> bool:
    """The escape hatch keeps honesty. Labelling a guess is allowed; hiding it is not."""
    return run(_repo_with_ledger(), OUTREACH,
               "Roughly 4,200 rows look affected. {{UNVERIFIED}}\n") == 0


def case_skip_marker_bypasses() -> bool:
    return run(_repo_with_ledger(), OUTREACH,
               "<!-- evidence-gate-skip -->\nWe found 4,200 rows.\n") == 0


def case_unsourced_quote_blocks() -> bool:
    """A span attributed to the client must trace to a recorded read."""
    return run(_repo_with_ledger(), OUTREACH,
               'You told us "nobody ever opens that shared sheet" last week.\n') == 2


def case_single_digits_do_not_block() -> bool:
    """Stated hole, tested so it stays a decision and not a drift."""
    return run(_repo_with_ledger(), OUTREACH,
               "Three things:\n1. First\n2. Second\n3. Third\n") == 0


def case_no_ledger_is_a_no_op() -> bool:
    """DECISION CHANGED 2026-07-28 (ASK-233). This case previously asserted the
    opposite -- "no ledger still blocks a number" -- on the reasoning that an
    instance which verified nothing has backed nothing.

    That reasoning is right about the epistemics and wrong about the outcome. With
    no ledger every lookup misses, so the FIRST draft an instance ever writes blocks
    on every number in it at once, with no incremental path. The gate was harshest
    exactly where it had zero signal, and the only way through was the bypass marker
    -- which turns the gate off permanently for that file. 21 instances received
    these scripts with no ledger in any of them.

    So an absent ledger now means "not adopted yet" and the gate stands down. The
    file's existence is the opt-in switch. The pairing case below proves adoption
    flips enforcement back on at full strength, so this is a bootstrap allowance and
    not a way to disable the gate by deleting a file."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-thing" / "canonical").mkdir(parents=True)
    return run(tmp, OUTREACH, "We found 4,200 duplicate rows.\n") == 0


def case_one_ledger_row_turns_enforcement_back_on() -> bool:
    """The negative half of the case above: once the ledger EXISTS, an unbacked
    number blocks again. Without this, "no ledger no-ops" would be indistinguishable
    from "the gate never fires"."""
    tmp = Path(tempfile.mkdtemp())
    canon = tmp / "q-thing" / "canonical"
    canon.mkdir(parents=True)
    (canon / "evidence.jsonl").write_text(json.dumps({
        "claim_id": "ev-0000000000", "claim": "unrelated fact", "source": "s",
        "command": "true", "result": "ok", "verified_at": "2026-07-28T00:00:00Z",
    }) + "\n", encoding="utf-8")
    return run(tmp, OUTREACH, "We found 4,200 duplicate rows.\n") == 2


def case_a_date_is_not_a_measurement() -> bool:
    """ASK-232: `zach-info-request.md` blocked on ['13','2026'], both out of a date.
    A dated line passes; a genuine unbacked count on the same line still blocks."""
    tmp = Path(tempfile.mkdtemp())
    canon = tmp / "q-thing" / "canonical"
    canon.mkdir(parents=True)
    (canon / "evidence.jsonl").write_text(json.dumps({
        "claim_id": "ev-0000000001", "claim": "unrelated", "source": "s",
        "command": "true", "result": "ok", "verified_at": "2026-07-28T00:00:00Z",
    }) + "\n", encoding="utf-8")
    dated_only = run(tmp, OUTREACH, "Recorded on 2026-07-28, our 2026 plan.\n")
    with_count = run(tmp, OUTREACH, "On 2026-07-28 we found 47 duplicates.\n")
    return dated_only == 0 and with_count == 2


CASES = [
    ("unsourced number in outreach blocks", case_unsourced_number_blocks),
    ("ledger-backed number passes", case_ledger_backed_number_passes),
    ("non-outreach file is out of scope", case_non_outreach_file_is_out_of_scope),
    ("{{UNVERIFIED}} exempts its line", case_unverified_marker_exempts_its_line),
    ("skip marker bypasses", case_skip_marker_bypasses),
    ("unsourced quote blocks", case_unsourced_quote_blocks),
    ("single digits do not block", case_single_digits_do_not_block),
    ("no ledger is a no-op (ASK-233)", case_no_ledger_is_a_no_op),
    ("one ledger row turns enforcement back on", case_one_ledger_row_turns_enforcement_back_on),
    ("a date is not a measurement (ASK-232)", case_a_date_is_not_a_measurement),
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
