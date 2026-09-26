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

import os

# Overridable so the new-branch cases can be run against a COPY of the pre-change
# lint and observed going RED before they are trusted green (ASK-1953). Defaults to
# the real script, so an ordinary run is unaffected.
LINT = Path(os.environ.get(
    "HANDOFF_LINT_PATH",
    str(Path(__file__).resolve().parent / "handoff-provenance-lint.py")))


def run_full(rel_path: str, body: str) -> tuple[int, str]:
    """(exit code, stderr). The advisory posture is only observable in stderr: an
    exit 0 alone cannot be told apart from out-of-scope."""
    tmp = Path(tempfile.mkdtemp())
    target = tmp / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    proc = subprocess.run(
        [sys.executable, str(LINT)], input=payload, capture_output=True, text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp), "PATH": "/usr/bin:/bin"}, check=False)
    return proc.returncode, proc.stderr


def run(rel_path: str, body: str) -> int:
    return run_full(rel_path, body)[0]


def load(script_name: str):
    """Import a hyphenated sibling script as a module, for predicate-level cases."""
    import importlib.util
    path = Path(__file__).resolve().parent / script_name
    spec = importlib.util.spec_from_file_location(script_name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


# --- ASK-1953: the widened scan root ------------------------------------------------
# RCA rca-fleet-sync-two-day-spin-2026-09-20 row T1. Every case below goes RED against
# a copy of the pre-change lint (HANDOFF_LINT_PATH), which is what makes their green
# mean something; the run is recorded on the issue.

SESSION_HANDOFF = "q-consult/output/HANDOFF-fleet-sync-2026-09-20.md"
AUTO_MEMORY = (".claude/projects/-Users-x-projects-kipi-system/memory/"
               "project_thing.md")
AUTO_MEMORY_INDEX = ".claude/projects/-Users-x-projects-kipi-system/memory/MEMORY.md"


def case_session_handoff_blocks() -> bool:
    """THE reproducer for T1. The identical claim shape the lint already blocks in
    last-handoff.md, in the file `/q-handoff` writes under output/ instead."""
    return run(SESSION_HANDOFF,
               "- 22 of 26 instances synced by 11:40.\n") == 2


def case_session_handoff_labelled_passes() -> bool:
    """Widening must not make the artifact unwritable: the escape hatch still works."""
    return run(SESSION_HANDOFF,
               "- 22 of 26 instances synced [verified: kipi-update.sh --dry tail]\n") == 0


def case_session_handoff_prose_passes() -> bool:
    return run(SESSION_HANDOFF, "- Picked the sync back up; nothing decided yet.\n") == 0


def case_auto_memory_reports_and_does_not_block() -> bool:
    """Auto-memory is IN SCOPE and ADVISORY. exit 0, and a finding on stderr.

    Both halves in one case on purpose: an exit 0 alone is indistinguishable from
    out-of-scope, which is the failure this case exists to rule out."""
    code, err = run_full(AUTO_MEMORY,
                         "---\nname: thing\n---\n\n- The board held 229 issues.\n")
    return code == 0 and "229" in err and "NOT blocked" in err


def case_auto_memory_index_out_of_scope() -> bool:
    """MEMORY.md is the index, not a memory. Same exclusion memory-confidence-
    validator.py makes, and it must print nothing at all."""
    code, err = run_full(AUTO_MEMORY_INDEX, "- [A thing](project_thing.md) - 40 repos\n")
    return code == 0 and err.strip() == ""


FRONTMATTER_BODY = (
    "---\nname: thing\ndescription: \"shipped 2026-09-17, 3 spokes\"\n"
    "metadata:\n  modified: 2026-09-26T17:40:17.812Z\n---\n\nprose, no claims.\n")


def case_frontmatter_is_not_a_claim() -> bool:
    """A `description:` carrying a date labels the file; it does not assert inside it.
    Without the frontmatter skip, every auto-memory file reports on its own header.

    Asserted on BOTH postures, and the handoff half is what makes this case able to
    fail: the first draft checked only the auto-memory path, where the pre-change lint
    returns exit 0 because the path is out of scope entirely -- indistinguishable from
    the skip working. `--negative` flagged it DECORATION rather than the suite going
    green on a case that proved nothing (`feedback_check_must_be_able_to_fail`)."""
    handoff_code, handoff_err = run_full(HANDOFF, FRONTMATTER_BODY)
    mem_code, mem_err = run_full(AUTO_MEMORY, FRONTMATTER_BODY)
    return (handoff_code == 0 and handoff_err.strip() == ""
            and mem_code == 0 and mem_err.strip() == "")


def case_horizontal_rule_does_not_exempt_the_body() -> bool:
    """The frontmatter skip is LEADING-only. A `---` mid-file is a horizontal rule, and
    treating it as a fence opener would launder everything after it."""
    return run(HANDOFF, "# Session Handoff\n\nprose.\n\n---\n\n- 1,366 rows flagged.\n") == 2


def case_auto_memory_scope_matches_the_owner() -> bool:
    """memory-confidence-validator.py OWNS the auto-memory scope. Its filename is
    hyphenated so it cannot be imported by name; this is the divergence check that
    stands in for deriving the predicate from it. If the two ever disagree, this
    fails rather than the drift staying invisible (the 2026-07-28 two-vocabularies
    scar, in scope form)."""
    lint = load("handoff-provenance-lint.py")
    owner = load("memory-confidence-validator.py")
    paths = [
        "/a/.claude/projects/p/memory/project_thing.md",
        "/a/.claude/projects/p/memory/MEMORY.md",
        "/a/.claude/projects/p/memory/notes.txt",
        "/a/q-system/memory/last-handoff.md",
        "/a/.claude/projects/p/canonical/thing.md",
        "/a/memory/project_thing.md",
    ]
    return all(lint.is_auto_memory(p) == owner.in_scope(p) for p in paths)


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


HANDOFF = "memory/last-handoff.md"


def case_dated_markdown_header_passes() -> bool:
    """ASK-231 / sp-be424cdd: the shape the skeleton's OWN handoff template uses.
    META_RE only matched `key: value`, so this header tripped DATE_RE and the lint
    blocked the canonical artifact it exists to protect."""
    return run(HANDOFF, "# Session Handoff - 2026-06-11 EOD\n\nprose, no claims.\n") == 0


def case_dated_claim_still_blocks() -> bool:
    """The half that keeps the case above honest. Reversal #5 WAS a date claim, so
    if a dated ASSERTION ever stops blocking, this lint has lost its own scar."""
    return run(HANDOFF, "# Session Handoff - 2026-06-11 EOD\n\n"
                        "- a client row is dated 2026-12-21, five months out\n") == 2


def case_number_in_a_header_still_blocks() -> bool:
    """The exemption covers dates in headers, NOT numbers in headers -- otherwise a
    claim could be laundered by prefixing it with a `#`."""
    return run(HANDOFF, "## the sheet had 1,177 rows\n") == 2


def case_dated_claim_in_a_header_still_blocks() -> bool:
    """Codex adversarial review 2026-07-28. A `#` must not launder a dated claim.
    This is reversal #5 verbatim, wearing a heading -- the case that fell between
    "numbers in a header block" and "a dated claim in a bullet blocks"."""
    return run(HANDOFF, "## Client row dated 2026-12-21, five months out\n") == 2


def case_long_dated_header_still_blocks() -> bool:
    """The comma is not the only tell; a header that narrates is not a title."""
    return run(HANDOFF,
               "## the export we pulled on 2026-12-21 had rows dated in the future\n") == 2


CASES = [
    ("a bare number blocks", case_bare_number_blocks),
    ("dated markdown header passes (ASK-231)", case_dated_markdown_header_passes),
    ("a dated claim still blocks", case_dated_claim_still_blocks),
    ("a dated claim in a header still blocks", case_dated_claim_in_a_header_still_blocks),
    ("a long dated header still blocks", case_long_dated_header_still_blocks),
    ("a number in a header still blocks", case_number_in_a_header_still_blocks),
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
    # ASK-1953, the widened scan root. These are the cases that go RED against a copy
    # of the pre-change lint.
    ("a session handoff blocks on an unlabelled claim", case_session_handoff_blocks),
    ("a labelled session-handoff claim passes", case_session_handoff_labelled_passes),
    ("session-handoff prose without numbers passes", case_session_handoff_prose_passes),
    ("auto-memory reports and does NOT block", case_auto_memory_reports_and_does_not_block),
    ("the MEMORY.md index is out of scope", case_auto_memory_index_out_of_scope),
    ("frontmatter is not a claim, both postures", case_frontmatter_is_not_a_claim),
    ("a mid-file --- does not exempt the body", case_horizontal_rule_does_not_exempt_the_body),
    ("auto-memory scope matches its owner", case_auto_memory_scope_matches_the_owner),
]


# Names of the cases ASK-1953 added. `--negative` runs exactly these against a copy of
# the pre-change lint and requires every one to FAIL there. A new case that passes
# against the baseline cannot detect the change it claims to cover; it is decoration,
# and this is the run that says so.
WIDENED_CASE_NAMES = (
    "a session handoff blocks on an unlabelled claim",
    "auto-memory reports and does NOT block",
    "frontmatter is not a claim, both postures",
)


def negative(baseline: str) -> int:
    """Every widened case must go RED against `baseline`, or it proves nothing."""
    global LINT
    LINT = Path(baseline)
    if not LINT.is_file():
        print(f"no baseline at {baseline}")
        return 1
    wrong = 0
    for name, fn in CASES:
        if name not in WIDENED_CASE_NAMES:
            continue
        try:
            passed_on_baseline = bool(fn())
        except Exception:
            passed_on_baseline = False
        verdict = "DECORATION" if passed_on_baseline else "RED as required"
        print(f"{'FAIL' if passed_on_baseline else 'OK'}: {name} -- {verdict}")
        wrong += 1 if passed_on_baseline else 0
    print(f"\nnegative self-test against {baseline}: "
          f"{len(WIDENED_CASE_NAMES) - wrong}/{len(WIDENED_CASE_NAMES)} went red")
    return 1 if wrong else 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--negative":
        return negative(sys.argv[2])
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
