#!/usr/bin/env python3
"""Pins Gate 1.3b's gating scope (ASK-191).

Three contracts, each with a negative case so a no-op implementation fails:

1. `unclassified_populated_record` is ADVISORY. A finding set that is entirely
   unclassified must produce zero gating findings, and a single classified
   finding in the same set must still gate. Without the second half, a
   partition that dropped everything would pass.
2. Paths `kipi update` never copies are advisory; paths it does copy gate.
   q-system/research/ is asserted GATING on purpose: the q-system rsync copies
   the whole tree minus INSTANCE_OWNED_SUBTREES, so research/ propagates. The
   ASK-191 issue text claimed otherwise; the code follows the rsync.
3. NON_PROPAGATED_PREFIXES does not drift from kipi-update.sh's
   INSTANCE_OWNED_SUBTREES. A comment cannot hold that line; this does.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "kipi_validate_separation", REPO_ROOT / "validate-separation.py"
    )
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load validate-separation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FAILURES: list[str] = []


def expect(label: str, condition: bool) -> None:
    if condition:
        print(f"  PASS {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


def finding(path: str, fact_class: str, line: int = 1) -> dict:
    return {"path": path, "line": line, "fact_class": fact_class}


def test_unclassified_is_advisory(vs) -> None:
    # A propagated path, so the ONLY reason these are non-gating is the class.
    unclassified_only = [
        finding("plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py",
                "unclassified_populated_record", n)
        for n in range(1, 51)
    ]
    gating, advisory = vs.partition_semantic_violations(unclassified_only)
    expect(
        "50 unclassified findings on a propagated path produce 0 gating",
        gating == [],
    )
    expect("...and all 50 stay visible as advisory", len(advisory) == 50)

    # NEGATIVE: one classified finding in the same propagated file must gate.
    # If this passes as empty, the partition is discarding everything and the
    # assertion above proves nothing.
    mixed = unclassified_only + [
        finding("plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py",
                "client_identity", 218)
    ]
    gating, advisory = vs.partition_semantic_violations(mixed)
    expect(
        "one client_identity among 50 unclassified still gates",
        len(gating) == 1 and gating[0]["fact_class"] == "client_identity",
    )
    expect("...and the 50 unclassified remain advisory", len(advisory) == 50)


def test_scope_matches_propagation(vs) -> None:
    non_propagated = [
        finding("q-system/canonical/talk-tracks.md", "source_identity", 13),
        finding("q-system/my-project/client-deliverables.md",
                "client_identity", 7),
        finding("q-system/memory/last-handoff.md", "pricing", 3),
        finding("q-system/output/report.md", "pricing", 3),
        finding("q-system/.q-system/data/db.md", "source_identity", 3),
        finding("q-system/.q-system/agent-pipeline/bus/x.md", "pricing", 3),
    ]
    gating, advisory = vs.partition_semantic_violations(non_propagated)
    expect(
        "classified findings on non-propagated paths do not gate",
        gating == [],
    )
    expect(
        "...and all 6 stay visible as advisory",
        len(advisory) == len(non_propagated),
    )

    # NEGATIVE: propagated paths with the SAME classes must gate. Without this,
    # a prefix check that matched everything would pass the block above.
    propagated = [
        finding("plugins/kipi-core/kipi-mcp/sources/linkedin-prospects.yaml",
                "client_identity", 14),
        finding("q-system/.q-system/commands.md", "pricing", 417),
        # research/ propagates: the rsync excludes only INSTANCE_OWNED_SUBTREES.
        finding("q-system/research/cc-workflow-learnings-2026-06-02.md",
                "source_identity", 4),
    ]
    gating, advisory = vs.partition_semantic_violations(propagated)
    expect(
        "classified findings on propagated paths DO gate (incl. research/)",
        len(gating) == 3 and advisory == [],
    )

    # A prefix must match on a path boundary, not a substring. `q-system/canonicalized/`
    # is a different directory and must still gate.
    boundary = [finding("q-system/canonicalized/x.md", "pricing", 1)]
    gating, _ = vs.partition_semantic_violations(boundary)
    expect(
        "prefix match is boundary-anchored (canonicalized/ still gates)",
        len(gating) == 1,
    )


def kipi_update_owned_subtrees() -> list[str]:
    """Parse INSTANCE_OWNED_SUBTREES out of kipi-update.sh."""
    text = (REPO_ROOT / "kipi-update.sh").read_text(encoding="utf-8")
    match = re.search(
        r"^INSTANCE_OWNED_SUBTREES=\(\s*\n(.*?)^\)", text, re.M | re.S
    )
    if match is None:
        raise SystemExit(
            "cannot find INSTANCE_OWNED_SUBTREES in kipi-update.sh -- the "
            "drift check cannot run, which is itself a failure"
        )
    return [
        line.strip()
        for line in match.group(1).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_no_drift_from_kipi_update(vs) -> None:
    owned = kipi_update_owned_subtrees()
    expected = {f"q-system/{sub}" for sub in owned}
    actual = set(vs.NON_PROPAGATED_PREFIXES)
    expect(
        f"NON_PROPAGATED_PREFIXES matches kipi-update.sh ({len(owned)} subtrees)",
        actual == expected,
    )
    if actual != expected:
        print(f"        only in validate-separation.py: {sorted(actual - expected)}")
        print(f"        only in kipi-update.sh:         {sorted(expected - actual)}")


def main() -> int:
    vs = load_validator()
    print("test-gate-13b-scope.py")
    test_unclassified_is_advisory(vs)
    test_scope_matches_propagation(vs)
    test_no_drift_from_kipi_update(vs)
    print()
    if FAILURES:
        print(f"test-gate-13b-scope.py: FAIL ({len(FAILURES)})")
        return 1
    print("test-gate-13b-scope.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
