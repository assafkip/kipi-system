#!/usr/bin/env python3
"""Self-test for provenance_vocabulary.py, the ONE source both provenance
validators read.

WHY: `memory-confidence-validator.py` hardcoded a six-value enum; three days later
`handoff-provenance-lint.py` shipped a different vocabulary for the same idea.
Two words for one thing in one repo is the drift class this repo writes rules
against. This module is the single table; both validators load it at runtime, so
a future addition cannot land in one and not the other.

Survived all three Codex rounds on PRD prd-deterministic-reading-2026-07-28 as the
only uncontested part, and answers its round-2 finding that precedence was defined
only for `ev-<id>` versus everything else.

Run: python3 test_provenance_vocabulary.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import provenance_vocabulary as PV  # noqa: E402


def case_enum_matches_the_incumbent() -> bool:
    """The table must be exactly memory-confidence.md's enum. It is the incumbent;
    this module adopts it rather than redefining it."""
    return PV.PROVENANCE == {
        "explicit_statement", "inferred", "corrected",
        "validated", "observed", "imported",
    }


def case_every_enum_value_has_a_rank() -> bool:
    """A value with no rank would make precedence undefined for that pair, which
    is exactly the round-2 finding."""
    return all(PV.rank(f"provenance: {v}") is not None for v in PV.PROVENANCE)


def case_claim_id_outranks_every_enum_value() -> bool:
    """An ev- id points at a row carrying the command AND its output. Nothing the
    enum can express is stronger than a recorded measurement."""
    ev = PV.rank("ev-a1b2c3d4e5")
    return all(ev > PV.rank(f"provenance: {v}") for v in PV.PROVENANCE)


def case_validated_outranks_inferred() -> bool:
    return PV.rank("provenance: validated") > PV.rank("provenance: inferred")


def case_unverified_equals_inferred() -> bool:
    """`{{UNVERIFIED}}` is the shorthand already used across canonical docs. If it
    ranked differently from `inferred`, the same claim would score two ways."""
    return PV.rank("{{UNVERIFIED}}") == PV.rank("provenance: inferred")


def case_unvalidated_and_needs_proof_are_aliases() -> bool:
    r = PV.rank("provenance: inferred")
    return PV.rank("{{UNVALIDATED}}") == r and PV.rank("{{NEEDS_PROOF}}") == r


def case_no_marker_has_no_rank() -> bool:
    return PV.rank("- we found 1,366 flagged rows") is None


def case_unknown_enum_value_has_no_rank() -> bool:
    """A typo must not silently satisfy a provenance requirement."""
    return PV.rank("provenance: verifed") is None


def case_strongest_picks_the_winner() -> bool:
    """Round-2 finding: a line carrying two forms had no defined winner."""
    line = "- 332 hand-typed dates ev-a1b2c3d4e5 provenance: inferred"
    winner, seen = PV.strongest(line)
    return winner == "ev-a1b2c3d4e5" and len(seen) == 2


def case_strongest_reports_a_downgrade_pair() -> bool:
    """The pair must be reported so a downgrade is never silent."""
    line = "- claim provenance: validated {{UNVERIFIED}}"
    winner, seen = PV.strongest(line)
    return winner == "provenance: validated" and len(seen) == 2


def case_strongest_on_a_bare_line() -> bool:
    return PV.strongest("- just prose") == (None, [])


def case_validator_fallback_matches_the_table() -> bool:
    """memory-confidence-validator.py keeps a literal fallback for an instance
    mid-`kipi update`. A fallback that drifts from the table reintroduces the exact
    two-vocabularies bug this module exists to kill, so it is pinned by test."""
    import re
    src = (Path(__file__).resolve().parent /
           "memory-confidence-validator.py").read_text(encoding="utf-8")
    m = re.search(r"_FALLBACK_PROVENANCE\s*=\s*\{(.*?)\}", src, re.S)
    if not m:
        return False
    fallback = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    return fallback == PV.PROVENANCE


def case_table_is_data_not_code() -> bool:
    """The repo's own pattern: allowlists load from a table at runtime, so adding
    a value is a data change. Rule 10 of the client's QA validator, same idea."""
    return PV.TABLE_PATH.exists() and PV.TABLE_PATH.suffix == ".json"


CASES = [
    ("enum matches the incumbent", case_enum_matches_the_incumbent),
    ("every enum value has a rank", case_every_enum_value_has_a_rank),
    ("ev- id outranks every enum value", case_claim_id_outranks_every_enum_value),
    ("validated outranks inferred", case_validated_outranks_inferred),
    ("{{UNVERIFIED}} equals inferred", case_unverified_equals_inferred),
    ("{{UNVALIDATED}} / {{NEEDS_PROOF}} are aliases", case_unvalidated_and_needs_proof_are_aliases),
    ("a line with no marker has no rank", case_no_marker_has_no_rank),
    ("an unknown enum value has no rank", case_unknown_enum_value_has_no_rank),
    ("strongest() picks the winner", case_strongest_picks_the_winner),
    ("strongest() reports the downgrade pair", case_strongest_reports_a_downgrade_pair),
    ("strongest() on a bare line", case_strongest_on_a_bare_line),
    ("validator fallback matches the table", case_validator_fallback_matches_the_table),
    ("the table is data, not code", case_table_is_data_not_code),
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
