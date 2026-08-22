#!/usr/bin/env python3
"""Self-test for evidence_ledger.py.

Pairs with RCA rca-conclusions-before-evidence-2026-07-28: six conclusions were
delivered before their evidence existed. The ledger is the durable store that makes
"how do you know this" a required field instead of a habit.

Hermetic: every case builds its own temp instance root. No repo-specific path.
Run: python3 test_evidence_ledger.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence_ledger as EL  # noqa: E402


def _root() -> Path:
    """A temp instance root shaped like a real one: <root>/q-thing/canonical/."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-thing" / "canonical").mkdir(parents=True)
    return tmp


def case_refuses_missing_command() -> bool:
    """A claim with no command is an inference, not a measurement. Refuse it."""
    repo = _root()
    try:
        EL.add(repo, claim="332 rows hold hand-typed dates", source="xlsx",
               command="", result="hand-typed strings: 332")
    except EL.LedgerError:
        return True
    return False


def case_refuses_missing_result() -> bool:
    """A command with no recorded output proves nothing was actually read."""
    repo = _root()
    try:
        EL.add(repo, claim="max date is 2026-07-21", source="xlsx",
               command="python3 -c 'openpyxl...'", result="")
    except EL.LedgerError:
        return True
    return False


def case_refuses_duplicate_claim_id() -> bool:
    """Append-only means a claim_id is written once. A second write is a bug."""
    repo = _root()
    row = EL.add(repo, claim="845 real dates", source="xlsx",
                 command="openpyxl count", result="real dates: 845")
    try:
        EL.append_row(repo, dict(row))
    except EL.LedgerError:
        return True
    return False


def case_append_is_order_preserving() -> bool:
    """Single writer, append only. Reading back returns insertion order."""
    repo = _root()
    EL.add(repo, claim="first", source="s", command="c1", result="r1")
    EL.add(repo, claim="second", source="s", command="c2", result="r2")
    EL.add(repo, claim="third", source="s", command="c3", result="r3")
    return [r["claim"] for r in EL.read(repo)] == ["first", "second", "third"]


def case_check_flags_a_corrupt_row() -> bool:
    """`check` is the standing validator, not just a write-time guard."""
    repo = _root()
    EL.add(repo, claim="ok", source="s", command="c", result="r")
    path = EL.ledger_path(repo)
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"claim_id": "ev-bad", "claim": "no command"}\n')
    return len(EL.check(repo)) > 0


def case_resolve_matches_thousands_separator() -> bool:
    """A draft says "1,177 rows"; the ledger recorded 1177. Same number."""
    repo = _root()
    EL.add(repo, claim="Brightspeed export has 1177 rows", source="xlsx",
           command="openpyxl len(rows)", result="1177")
    return EL.resolve_numbers(repo, "We found 1,177 rows in the export.") == []


def case_resolve_reports_an_invented_number() -> bool:
    """The whole point: a number nobody measured comes back unresolved."""
    repo = _root()
    EL.add(repo, claim="Brightspeed export has 1177 rows", source="xlsx",
           command="openpyxl len(rows)", result="1177")
    return EL.resolve_numbers(repo, "About 4,200 records were affected.") == ["4200"]


def case_resolve_ignores_single_digits() -> bool:
    """List markers and ordinals are not claims. Stated hole, tested so it stays."""
    repo = _root()
    return EL.resolve_numbers(repo, "1. First point\n2. Second point") == []


def case_resolve_spans_flags_an_unsourced_quote() -> bool:
    """A quoted span attributed to the client must trace to a recorded read."""
    repo = _root()
    EL.add(repo, claim="Marilyn wrote about the shared sheet", source="email",
           command="read email 2026-07-22",
           result='she wrote "we all work out of the same sheet"')
    grounded = EL.resolve_spans(repo, 'She said "we all work out of the same sheet".')
    invented = EL.resolve_spans(repo, 'She said "nobody ever opens that sheet".')
    return grounded == [] and invented == ["nobody ever opens that sheet"]


def case_ledger_path_prefers_instance_over_skeleton() -> bool:
    """An instance has both q-system/ and q-<name>/. Content lives in q-<name>/."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-system" / "canonical").mkdir(parents=True)
    (tmp / "q-prodigy" / "canonical").mkdir(parents=True)
    return EL.ledger_path(tmp).parent.parent.name == "q-prodigy"


def case_ledger_path_falls_back_to_skeleton() -> bool:
    """The skeleton itself has only q-system/. Resolve there, do not crash."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-system" / "canonical").mkdir(parents=True)
    return EL.ledger_path(tmp).parent.parent.name == "q-system"


# --------------------------------------------------------- fail-closed resolver
# Pairs with prd-canonical-read-path-repair-2026-08-22 / crpr-one-canonical-resolver.
# The old instance_root() was `named[0] if named else repo/"q-system"` -- a glob with
# no registry and no cross-check, structurally unable to be wrong out loud. Each case
# below is one measured way it answered confidently and wrongly.
#
# Every case pins KIPI_EVIDENCE_REGISTRY at its own temp registry. Without that the
# resolver falls back to the REAL fleet registry and the case stops being hermetic.

def _reg(tmp: Path, entries: list[dict]) -> Path:
    import json
    p = tmp / "registry.json"
    p.write_text(json.dumps({"instances": entries}), encoding="utf-8")
    os.environ["KIPI_EVIDENCE_REGISTRY"] = str(p)
    return p


def _raises(fn) -> bool:
    try:
        fn()
    except EL.ResolutionError:
        return True
    except Exception:
        return False
    return False


def case_resolver_refuses_two_named_canonical_dirs() -> bool:
    """sorted()[0] silently won. ZERO fleet instances hit this, so it must be
    synthetic -- a hazard with no current victim is still a hazard."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-alpha" / "canonical").mkdir(parents=True)
    (tmp / "q-beta" / "canonical").mkdir(parents=True)
    _reg(tmp, [])
    return _raises(lambda: EL.instance_root(tmp))


def case_resolver_refuses_root_with_no_canonical() -> bool:
    """Measured on 3 of 25 instances: resolves to a dir holding no canonical/."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-system").mkdir(parents=True)
    _reg(tmp, [])
    return _raises(lambda: EL.instance_root(tmp))


def case_resolver_refuses_registry_filesystem_mismatch() -> bool:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-real" / "canonical").mkdir(parents=True)
    _reg(tmp, [{"name": "x", "path": str(tmp), "instance_q_dir": "q-other"}])
    return _raises(lambda: EL.instance_root(tmp))


def case_resolver_refuses_registered_null_against_real_dir() -> bool:
    """The 6-of-25 case: registry says null, a real domain dir holds canonical/."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-real" / "canonical").mkdir(parents=True)
    _reg(tmp, [{"name": "x", "path": str(tmp), "instance_q_dir": None}])
    return _raises(lambda: EL.instance_root(tmp))


def case_resolver_uses_registry_as_authority() -> bool:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-real" / "canonical").mkdir(parents=True)
    _reg(tmp, [{"name": "x", "path": str(tmp), "instance_q_dir": "q-real"}])
    return EL.instance_root(tmp) == tmp / "q-real"


def case_resolver_nonstrict_restores_legacy_guess() -> bool:
    """The escape hatch must still guess, or callers cannot degrade deliberately."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "q-alpha" / "canonical").mkdir(parents=True)
    (tmp / "q-beta" / "canonical").mkdir(parents=True)
    _reg(tmp, [])
    return EL.instance_root(tmp, strict=False) == tmp / "q-alpha"


# ------------------------------------------------ the audit's exit code can fail
# SCAR (Codex review of PR #240, major). `_run_audit` ended in a hardcoded
# `return 0`, so the one command that enumerates unresolvable instances could not
# fail for the reason it exists. Both branches are asserted here; an exit code
# that is only ever observed as 0 is a constant, not a verdict.

def _audit_rc(tmp: Path, entries: list[dict], extra: list[str] | None = None) -> int:
    reg = _reg(tmp, entries)
    return EL.main(["--audit-instance-roots", "--registry", str(reg)] + (extra or []))


def case_audit_exits_nonzero_when_an_instance_is_refused() -> bool:
    """A registered instance whose registry says null while a real domain dir holds
    canonical/ -- the 6-of-25 shape. The resolver REFUSES it, so the audit must too."""
    tmp = Path(tempfile.mkdtemp())
    inst = tmp / "inst"
    (inst / "q-real" / "canonical").mkdir(parents=True)
    return _audit_rc(tmp, [{"name": "x", "path": str(inst), "instance_q_dir": None}]) == 1


def case_audit_exits_zero_when_every_instance_resolves() -> bool:
    """The green branch, or the case above proves only that the command is broken."""
    tmp = Path(tempfile.mkdtemp())
    inst = tmp / "inst"
    (inst / "q-real" / "canonical").mkdir(parents=True)
    return _audit_rc(tmp, [{"name": "x", "path": str(inst), "instance_q_dir": "q-real"}]) == 0


def case_audit_allow_refused_enumerates_without_failing() -> bool:
    """The opt-in hatch for callers that want the rows, not the verdict."""
    tmp = Path(tempfile.mkdtemp())
    inst = tmp / "inst"
    (inst / "q-real" / "canonical").mkdir(parents=True)
    entries = [{"name": "x", "path": str(inst), "instance_q_dir": None}]
    return _audit_rc(tmp, entries, ["--allow-refused"]) == 0


CASES = [
    ("audit exits non-zero on a REFUSED instance", case_audit_exits_nonzero_when_an_instance_is_refused),
    ("audit exits zero when every instance resolves", case_audit_exits_zero_when_every_instance_resolves),
    ("audit --allow-refused enumerates without failing", case_audit_allow_refused_enumerates_without_failing),
    ("resolver refuses two named canonical dirs", case_resolver_refuses_two_named_canonical_dirs),
    ("resolver refuses a root with no canonical/", case_resolver_refuses_root_with_no_canonical),
    ("resolver refuses registry/filesystem mismatch", case_resolver_refuses_registry_filesystem_mismatch),
    ("resolver refuses registered-null against a real dir", case_resolver_refuses_registered_null_against_real_dir),
    ("resolver uses the registry as authority", case_resolver_uses_registry_as_authority),
    ("resolver strict=False restores the legacy guess", case_resolver_nonstrict_restores_legacy_guess),
    ("refuses a claim with no command", case_refuses_missing_command),
    ("refuses a claim with no result", case_refuses_missing_result),
    ("refuses a duplicate claim_id", case_refuses_duplicate_claim_id),
    ("append is order preserving", case_append_is_order_preserving),
    ("check flags a corrupt row", case_check_flags_a_corrupt_row),
    ("resolve matches a thousands separator", case_resolve_matches_thousands_separator),
    ("resolve reports an invented number", case_resolve_reports_an_invented_number),
    ("resolve ignores single digits", case_resolve_ignores_single_digits),
    ("resolve_spans flags an unsourced quote", case_resolve_spans_flags_an_unsourced_quote),
    ("ledger_path prefers the instance dir", case_ledger_path_prefers_instance_over_skeleton),
    ("ledger_path falls back to q-system", case_ledger_path_falls_back_to_skeleton),
]


def main() -> int:
    failures = 0
    for name, fn in CASES:
        try:
            ok = bool(fn())
        except Exception as exc:  # a crash is a failure, not an error
            ok = False
            name = f"{name} [raised {type(exc).__name__}: {exc}]"
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
        failures += 0 if ok else 1
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
