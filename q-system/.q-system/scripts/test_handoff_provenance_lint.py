#!/usr/bin/env python3
"""Self-test for handoff-provenance-lint.py.

Pairs with RCA rca-conclusions-before-evidence-2026-07-28, root cause #4: "last-
handoff.md mixed verified measurements with unverified inferences in one prose voice.
Reversal #5 rode in on that. A reader cannot distinguish 'recomputed from the export'
from 'inferred last Tuesday' because the format has no field for it."

Reversal #5 was a Brightspeed row dated five months in the future. It was inherited
verbatim from the handoff and repeated as fact across several turns. Recomputation
showed no such row existed.

Run: python3 test_handoff_provenance_lint.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

LINT = Path(__file__).resolve().parent / "handoff-provenance-lint.py"


def run(rel_path: str, body: str) -> int:
    tmp = Path(tempfile.mkdtemp())
    target = tmp / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    proc = subprocess.run(
        [sys.executable, str(LINT)], input=payload, capture_output=True, text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp), "PATH": "/usr/bin:/bin"}, check=False)
    return proc.returncode


HANDOFF = "q-thing/memory/last-handoff.md"


def case_bare_number_blocks() -> bool:
    """THE reproducer: reversal #5's shape -- a measurement-looking claim, no source."""
    return run(HANDOFF, "- One Brightspeed row is dated 2026-12-21, five months out.\n") == 2


def case_verified_marker_passes() -> bool:
    return run(HANDOFF,
               "- Brightspeed has 332 hand-typed dates "
               "[verified: openpyxl over the xlsx, 2026-07-28]\n") == 0


def case_unverified_marker_passes() -> bool:
    """Labelling an inference is the whole point. It must stay cheap to be honest."""
    return run(HANDOFF, "- Roughly 400 rows look affected {{UNVERIFIED}}\n") == 0


def case_claim_id_reference_passes() -> bool:
    """A pointer into the evidence ledger is the strongest provenance available."""
    return run(HANDOFF, "- The export holds 1177 rows (ev-a1b2c3d4e5)\n") == 0


def case_non_handoff_file_out_of_scope() -> bool:
    return run("q-thing/output/notes.md", "- 1,366 rows are flagged review.\n") == 0


def case_iso_date_alone_does_not_trip() -> bool:
    """A handoff header carries dates. Dates are not measurements."""
    return run(HANDOFF, "# Handoff\n\n**Date:** 2026-07-28\n**Session:** morning\n") == 0


def case_skip_marker_bypasses() -> bool:
    return run(HANDOFF,
               "<!-- handoff-provenance-skip -->\n- 1,366 rows flagged.\n") == 0


def case_prose_without_numbers_passes() -> bool:
    """Only measurement-shaped claims are gated; the format stays writable."""
    return run(HANDOFF, "- Picked up the Blue Peak thread with Zach; nothing decided.\n") == 0


def case_multiple_bad_lines_still_blocks() -> bool:
    return run(HANDOFF,
               "- 1,366 Vyve rows flagged.\n"
               "- 21 Brightspeed rows flagged.\n") == 2


def case_mixed_file_blocks_on_the_bad_line() -> bool:
    """One labelled line does not launder an unlabelled one."""
    return run(HANDOFF,
               "- 332 hand-typed dates [verified: openpyxl count]\n"
               "- 1,366 rows are flagged review.\n") == 2


def case_shared_enum_validated_passes() -> bool:
    """The incumbent vocabulary now satisfies this lint. Before the shared table
    it did not, which was two words for one idea in one repo."""
    return run(HANDOFF, "- 1,366 rows flagged. provenance: validated\n") == 0


def case_shared_enum_inferred_passes() -> bool:
    """Labelling an inference is the correct move, not a lesser one."""
    return run(HANDOFF, "- roughly 400 rows affected. provenance: inferred\n") == 0


def case_typod_enum_value_still_blocks() -> bool:
    """A typo must not silently satisfy the requirement."""
    return run(HANDOFF, "- 1,366 rows flagged. provenance: verifed\n") == 2


def case_bare_provenance_word_blocks() -> bool:
    """The word alone, with no value, is not provenance."""
    return run(HANDOFF, "- 1,366 rows flagged. provenance matters here\n") == 2


CASES = [
    ("a bare number blocks", case_bare_number_blocks),
    ("shared enum `validated` passes", case_shared_enum_validated_passes),
    ("shared enum `inferred` passes", case_shared_enum_inferred_passes),
    ("a typo'd enum value still blocks", case_typod_enum_value_still_blocks),
    ("the bare word `provenance` still blocks", case_bare_provenance_word_blocks),
    ("[verified: ...] passes", case_verified_marker_passes),
    ("{{UNVERIFIED}} passes", case_unverified_marker_passes),
    ("an ev- claim id passes", case_claim_id_reference_passes),
    ("non-handoff file is out of scope", case_non_handoff_file_out_of_scope),
    ("an ISO date alone does not trip", case_iso_date_alone_does_not_trip),
    ("skip marker bypasses", case_skip_marker_bypasses),
    ("prose without numbers passes", case_prose_without_numbers_passes),
    ("multiple unlabelled lines block", case_multiple_bad_lines_still_blocks),
    ("one labelled line does not launder another", case_mixed_file_blocks_on_the_bad_line),
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
